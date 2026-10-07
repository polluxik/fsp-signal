"""Transactional, deduplicated product events with a strict payload allowlist."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .domain_errors import DomainError
from .models import Invitation, ProductEvent, User, uid


EVENT_PAYLOAD_FIELDS = {
    "role_version_created": {"version", "terms_hash", "source"},
    "role_published": {"version", "discoverable"},
    "role_reconfirmed": {"version"},
    "role_paused": {"version"},
    "role_closed": {"version"},
    "invitation_sent": {"state_version", "role_version_id"},
    "invitation_viewed": {"state_version", "role_version_id"},
    "invitation_accepted": {"state_version", "role_version_id"},
    "invitation_rejected": {"state_version", "role_version_id"},
    "invitation_withdrawn": {"state_version", "role_version_id"},
    "invitation_expired": {"state_version", "role_version_id"},
    "interview_held": {"state_version", "role_version_id"},
    "promotion_demo_activated": {"role_version_id"},
    "sponsored_role_impression": {"role_version_id", "placement"},
    "sponsored_role_decision": {"role_version_id", "action"},
}


def product_event_data_mode(app_mode: str, *users: User | None) -> str:
    if app_mode in ("test", "demo") or any(
        user and user.origin == "synthetic_fixture" for user in users
    ):
        return "synthetic"
    return "real"


class ProductEventError(DomainError):
    pass


def write_product_event(
    db: Session, *, type: str, entity_type: str, entity_id: str,
    employer_id: str | None, actor_id: str | None, dedupe_key: str,
    data_mode: str, payload: dict, at: datetime,
) -> ProductEvent:
    allowed = EVENT_PAYLOAD_FIELDS.get(type)
    if allowed is None or set(payload) - allowed:
        raise ValueError("event type or payload is not allowlisted")
    if entity_type == "role":
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
    elif entity_type == "invitation":
        if not isinstance(payload.get("state_version"), int) or payload["state_version"] < 1:
            raise ValueError("invitation event requires a positive state version")
        role_version_id = payload.get("role_version_id")
        if role_version_id is not None and not isinstance(role_version_id, str):
            raise ValueError("invalid invitation role version id")
    elif entity_type == "promotion_campaign":
        if not isinstance(payload.get("role_version_id"), str):
            raise ValueError("promotion event requires an allowlisted role version id")
        if type == "promotion_demo_activated":
            pass
        elif type == "sponsored_role_impression":
            if payload.get("placement") != "candidate_roles_shelf":
                raise ValueError("invalid sponsored impression placement")
        elif type == "sponsored_role_decision":
            if payload.get("action") not in ("saved", "hidden", "none"):
                raise ValueError("invalid sponsored role decision")
        else:
            raise ValueError("unsupported promotion event")
    else:
        raise ValueError("unsupported event entity")
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


def write_invitation_event(db: Session, invitation: Invitation, event_type: str,
                           actor_id: str | None, at: datetime,
                           *, state_version: int | None = None) -> ProductEvent:
    """Write a privacy-minimal event for one persisted invitation transition."""
    version = state_version or invitation.state_version
    employer = db.get(User, invitation.employer_id)
    candidate = db.get(User, invitation.candidate_id)
    return write_product_event(
        db, type=event_type, entity_type="invitation", entity_id=invitation.id,
        employer_id=invitation.employer_id, actor_id=actor_id,
        dedupe_key=f"invitation:{invitation.id}:v{version}:{event_type}",
        data_mode=product_event_data_mode(settings.app_mode, employer, candidate),
        payload={"state_version": version, "role_version_id": invitation.role_version_id},
        at=at,
    )
