"""Transactional, deduplicated product events with a strict payload allowlist."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain_errors import DomainError
from .models import ProductEvent, uid


EVENT_PAYLOAD_FIELDS = {
    "role_version_created": {"version", "terms_hash", "source"},
    "role_published": {"version", "discoverable"},
    "role_reconfirmed": {"version"},
    "role_paused": {"version"},
    "role_closed": {"version"},
}


class ProductEventError(DomainError):
    pass


def write_product_event(
    db: Session, *, type: str, entity_type: str, entity_id: str,
    employer_id: str | None, actor_id: str | None, dedupe_key: str,
    data_mode: str, payload: dict, at: datetime,
) -> ProductEvent:
    allowed = EVENT_PAYLOAD_FIELDS.get(type)
    if entity_type != "role" or allowed is None or set(payload) - allowed:
        raise ValueError("event type or payload is not allowlisted")
    if not isinstance(payload.get("version"), int) or payload["version"] < 1:
        raise ValueError("role event version must be a positive integer")
    if type == "role_version_created" and (
        payload.get("source") not in ("employer_declared", "legacy_import", "synthetic_demo")
        or not isinstance(payload.get("terms_hash"), str)
        or len(payload["terms_hash"]) != 64
    ):
        raise ValueError("role version event requires a source and hash")
    if type == "role_published" and not isinstance(payload.get("discoverable"), bool):
        raise ValueError("role publication event requires discoverable")
    if data_mode not in ("real", "synthetic"):
        raise ValueError("invalid data mode")
    if len(dedupe_key) > 180:
        raise ValueError("dedupe key is too long")

    existing = db.scalar(select(ProductEvent).where(ProductEvent.dedupe_key == dedupe_key))
    if existing:
        if (existing.type, existing.entity_type, existing.entity_id, existing.payload,
                existing.employer_id, existing.actor_id, existing.data_mode) != (
            type, entity_type, entity_id, payload, employer_id, actor_id, data_mode
        ):
            raise ProductEventError("EVENT_DEDUPE_CONFLICT")
        return existing
    event = ProductEvent(
        id=uid(), type=type, entity_type=entity_type, entity_id=entity_id,
        employer_id=employer_id, actor_id=actor_id, dedupe_key=dedupe_key,
        data_mode=data_mode, payload=payload, occurred_at=at,
    )
    db.add(event)
    db.flush()
    return event
