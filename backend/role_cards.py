"""Immutable, versioned employer-declared role terms."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .domain_errors import DomainError
from .models import HiringNeed, Invitation, RoleVersion, User, now
from .product_events import (product_event_data_mode, write_invitation_event,
                             write_product_event)
from .schemas import RoleCardIn


FRESHNESS = timedelta(days=14)
ROLE_TERM_FIELDS = (
    "title", "description", "specialization", "grade", "competencies", "stack",
    "salary_min_rub", "salary_max_rub", "work_format", "work_city", "industry", "first_30_days",
    "interview_steps", "take_home_minutes", "response_sla_hours",
)
class RoleVersionError(DomainError):
    pass


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def is_role_fresh(confirmed_at: datetime | None, at: datetime) -> bool:
    return bool(confirmed_at and _utc(at) < _utc(confirmed_at) + FRESHNESS)


def terms_hash(payload: dict[str, Any]) -> str:
    """Hash stable, decision-relevant terms; exclude contact and attestations."""
    terms = {key: payload[key] for key in ROLE_TERM_FIELDS if key in payload}
    canonical = json.dumps(terms, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_role_event(db: Session, need: HiringNeed, actor_id: str, event_type: str,
                       version: int, at: datetime, extra: dict | None = None) -> None:
    user = db.get(User, actor_id)
    payload = {"version": version, **(extra or {})}
    write_product_event(
        db, type=event_type, entity_type="role", entity_id=need.id,
        employer_id=need.employer_id, actor_id=actor_id,
        dedupe_key=(f"role:{need.id}:v{version}:{event_type}"
                    if event_type in ("role_version_created", "role_closed")
                    else f"role:{need.id}:v{version}:{event_type}:{_utc(at).isoformat()}"),
        data_mode=product_event_data_mode(settings.app_mode, user),
        payload=payload, at=at,
    )


def create_initial_draft(db: Session, need: HiringNeed, *, source: str = "employer_declared",
                         actor_id: str | None = None, at: datetime | None = None) -> RoleVersion:
    """Preserve only fields the legacy form actually collected; never invent missing terms."""
    at = at or now()
    payload = {
        "title": need.title, "description": need.description,
        "specialization": need.specialization, "grade": need.grade,
        "competencies": need.competencies or [], "stack": need.stack or [],
        "salary_min_rub": need.salary_min_rub, "salary_max_rub": need.salary_max_rub,
        "work_format": need.work_format,
    }
    need.current_role_version = 1
    need.publication_state = "draft"
    need.discoverable = False
    need.confirmed_at = None
    version = RoleVersion(
        need_id=need.id, version=1, schema_version=1, payload=payload,
        terms_hash=terms_hash(payload), source=source, created_at=at,
    )
    db.add(version)
    db.flush()
    if actor_id:
        _record_role_event(db, need, actor_id, "role_version_created", 1, at,
                           {"terms_hash": version.terms_hash, "source": source})
    return version


def _owned_need(db: Session, employer_id: str, need_id: str) -> HiringNeed:
    need = db.scalar(select(HiringNeed).where(HiringNeed.id == need_id).with_for_update())
    if not need or need.employer_id != employer_id:
        raise RoleVersionError("NOT_FOUND", 404)
    return need


def create_role_version(db: Session, employer_id: str, need_id: str, payload: RoleCardIn,
                        expected_version: int, at: datetime,
                        source: str = "employer_declared") -> RoleVersion:
    if source not in ("employer_declared", "synthetic_demo"):
        raise RoleVersionError("INVALID_ROLE_SOURCE", 422)
    need = _owned_need(db, employer_id, need_id)
    if need.publication_state == "closed":
        raise RoleVersionError("ROLE_CLOSED")
    if need.current_role_version != expected_version:
        raise RoleVersionError("ROLE_VERSION_CONFLICT")
    next_version = expected_version + 1
    card = payload.model_dump(mode="json")
    version_hash = terms_hash(card)
    changed = db.execute(
        update(HiringNeed)
        .where(HiringNeed.id == need_id, HiringNeed.employer_id == employer_id,
               HiringNeed.current_role_version == expected_version,
               HiringNeed.publication_state != "closed")
        .values(
            title=card["title"], description=card["description"],
            specialization=card["specialization"], grade=card["grade"],
            competencies=card["competencies"], stack=card["stack"],
            salary_min_rub=card["salary_min_rub"], salary_max_rub=card["salary_max_rub"],
            work_format=card["work_format"], current_role_version=next_version,
            publication_state="draft", discoverable=False, confirmed_at=None,
        ).execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise RoleVersionError("ROLE_VERSION_CONFLICT")
    version = RoleVersion(
        need_id=need_id, version=next_version, schema_version=1, payload=card,
        terms_hash=version_hash, source=source, created_at=at,
    )
    db.add(version)
    db.flush()
    db.expire(need)
    db.refresh(need)
    _record_role_event(db, need, employer_id, "role_version_created", next_version, at,
                       {"terms_hash": version_hash, "source": source})
    return version


def _current_version(db: Session, need: HiringNeed) -> RoleVersion:
    version = db.scalar(select(RoleVersion).where(
        RoleVersion.need_id == need.id, RoleVersion.version == need.current_role_version
    ))
    if not version:
        raise RoleVersionError("ROLE_VERSION_NOT_FOUND")
    return version


def _cancel_obsolete_pending(db: Session, need: HiringNeed, current_version_id: str, at: datetime) -> None:
    pending = db.scalars(select(Invitation).where(
        Invitation.need_id == need.id,
        Invitation.role_version_id.is_not(None),
        Invitation.role_version_id != current_version_id,
        Invitation.state.in_(("sent", "viewed")),
    )).all()
    for invitation in pending:
        invitation.state = "withdrawn"
        invitation.state_version += 1
        invitation.decided_at = at
        write_invitation_event(db, invitation, "invitation_withdrawn", need.employer_id, at)


def publish_role(db: Session, employer_id: str, need_id: str, *, expected_version: int,
                 active_headcount_attested: bool, discoverable: bool, at: datetime) -> HiringNeed:
    need = _owned_need(db, employer_id, need_id)
    if need.current_role_version != expected_version:
        raise RoleVersionError("ROLE_VERSION_CONFLICT")
    if need.publication_state == "closed":
        raise RoleVersionError("ROLE_CLOSED")
    version = _current_version(db, need)
    if not active_headcount_attested or not version.payload.get("active_headcount_attested"):
        raise RoleVersionError("ROLE_ATTESTATION_REQUIRED")
    try:
        RoleCardIn.model_validate(version.payload)
    except Exception as exc:
        raise RoleVersionError("ROLE_INCOMPLETE") from exc
    if version.terms_hash != terms_hash(version.payload):
        raise RoleVersionError("ROLE_TERMS_HASH_INVALID")
    if need.publication_state == "active" and is_role_fresh(need.confirmed_at, at) \
            and need.discoverable == discoverable:
        return need
    need.publication_state = "active"
    need.discoverable = discoverable
    need.confirmed_at = at
    _cancel_obsolete_pending(db, need, version.id, at)
    _record_role_event(db, need, employer_id, "role_published", expected_version, at,
                       {"discoverable": discoverable})
    db.flush()
    return need


def reconfirm_role(db: Session, employer_id: str, need_id: str, *, expected_version: int,
                   active_headcount_attested: bool, at: datetime) -> HiringNeed:
    need = _owned_need(db, employer_id, need_id)
    if need.current_role_version != expected_version:
        raise RoleVersionError("ROLE_VERSION_CONFLICT")
    if need.publication_state != "active":
        raise RoleVersionError("ROLE_NOT_ACTIVE")
    if not active_headcount_attested:
        raise RoleVersionError("ROLE_ATTESTATION_REQUIRED")
    version = _current_version(db, need)
    try:
        RoleCardIn.model_validate(version.payload)
    except Exception as exc:
        raise RoleVersionError("ROLE_INCOMPLETE") from exc
    need.confirmed_at = at
    _record_role_event(db, need, employer_id, "role_reconfirmed", expected_version, at)
    db.flush()
    return need


def pause_role(db: Session, employer_id: str, need_id: str, *, expected_version: int,
               at: datetime) -> HiringNeed:
    need = _owned_need(db, employer_id, need_id)
    if need.current_role_version != expected_version:
        raise RoleVersionError("ROLE_VERSION_CONFLICT")
    if need.publication_state == "closed":
        raise RoleVersionError("ROLE_CLOSED")
    if need.publication_state == "paused":
        return need
    if need.publication_state != "active":
        raise RoleVersionError("ROLE_NOT_ACTIVE")
    need.publication_state = "paused"
    need.discoverable = False
    _cancel_obsolete_pending(db, need, "", at)
    _record_role_event(db, need, employer_id, "role_paused", expected_version, at)
    db.flush()
    return need


def close_role(db: Session, employer_id: str, need_id: str, *, expected_version: int,
               at: datetime) -> HiringNeed:
    need = _owned_need(db, employer_id, need_id)
    if need.current_role_version != expected_version:
        raise RoleVersionError("ROLE_VERSION_CONFLICT")
    if need.publication_state == "closed":
        return need
    need.publication_state = "closed"
    need.discoverable = False
    _cancel_obsolete_pending(db, need, "", at)
    _record_role_event(db, need, employer_id, "role_closed", expected_version, at)
    db.flush()
    return need


def role_card_data(db: Session, need: HiringNeed, at: datetime) -> dict:
    version = db.scalar(select(RoleVersion).where(
        RoleVersion.need_id == need.id, RoleVersion.version == need.current_role_version
    )) if need.current_role_version else None
    payload = version.payload if version else {
        "title": need.title, "description": need.description,
        "specialization": need.specialization, "grade": need.grade,
        "competencies": need.competencies or [], "stack": need.stack or [],
        "salary_min_rub": need.salary_min_rub, "salary_max_rub": need.salary_max_rub,
        "work_format": need.work_format,
    }
    try:
        RoleCardIn.model_validate(payload)
        missing_fields: list[str] = []
    except ValidationError as exc:
        missing_fields = sorted({
            str(error["loc"][0]) for error in exc.errors()
            if error.get("loc") and isinstance(error["loc"][0], str)
        })
    return {
        "need_id": need.id, "version": version.version if version else None,
        "schema_version": version.schema_version if version else None,
        "payload": payload, "terms_hash": version.terms_hash if version else None,
        "source": version.source if version else None,
        "current_role_version": need.current_role_version,
        "publication_state": need.publication_state, "discoverable": need.discoverable,
        "confirmed_at": need.confirmed_at, "fresh": is_role_fresh(need.confirmed_at, at),
        "missing_fields": missing_fields,
        "salary_currency": "RUB", "salary_period": "month", "salary_basis": "gross",
    }
