"""Versioned candidate preferences and pair-scoped access revocation."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain_errors import DomainError
from .models import CandidateProfile, ContactGrant, Invitation, User, now
from .product_events import write_invitation_event
from .schemas import CandidateIn, CandidatePreferencesIn


ALL_FORMATS = ["remote", "hybrid", "office"]


class PreferencesError(DomainError):
    pass


@dataclass(frozen=True)
class AccessChangeResult:
    employer_id: str
    blocked: bool
    revoked_grants: int
    withdrawn_invitations: int


def formats_from_legacy(value: str) -> list[str]:
    return ALL_FORMATS.copy() if value == "any" else [value] if value in ALL_FORMATS else []


def is_blocked(profile: CandidateProfile, employer_id: str) -> bool:
    return employer_id in set(profile.blocked_employer_ids or [])


def preferences_data(profile: CandidateProfile | None) -> dict:
    preferences = (profile.preferences or {}) if profile else {}
    if profile is None:
        legacy_formats = ["remote"]
        salary_min = None
        available = True
        version = 1
    else:
        old_format = profile.work_format
        legacy_formats = formats_from_legacy(old_format)
        salary_min = profile.min_salary_rub or None
        available = profile.available
        version = profile.preferences_version or 1
    return {
        "version": version,
        "salary_min_rub": preferences.get("salary_min_rub", salary_min),
        "allowed_work_formats": preferences.get("allowed_work_formats", legacy_formats),
        "allowed_cities": preferences.get("allowed_cities", []),
        "excluded_industries": preferences.get("excluded_industries", []),
        "preferred_stack": preferences.get("preferred_stack", []),
        "preferred_tasks": preferences.get("preferred_tasks", []),
        "max_take_home_minutes": preferences.get("max_take_home_minutes"),
        "available": preferences.get("available", available),
        "adult_hiring_confirmed": bool(profile and profile.adult_attested_at),
    }


def save_profile_preferences(profile: CandidateProfile, payload: CandidateIn, at: datetime,
                             *, is_new: bool) -> None:
    """Synchronize legacy profile fields only through the current preference version."""
    current = preferences_data(profile)
    if not is_new:
        if payload.expected_preferences_version is None:
            raise PreferencesError("PREFERENCES_VERSION_REQUIRED")
        if payload.expected_preferences_version != current["version"]:
            raise PreferencesError("PREFERENCES_VERSION_CONFLICT")

    changes = {
        "salary_min_rub": payload.min_salary_rub != profile.min_salary_rub,
        "allowed_work_formats": payload.work_format != profile.work_format,
        "available": payload.available != profile.available,
    }
    if is_new or any(changes.values()):
        preference_fields = (
            "salary_min_rub", "allowed_work_formats", "allowed_cities", "excluded_industries",
            "preferred_stack", "preferred_tasks", "max_take_home_minutes", "available",
        )
        existing = profile.preferences or {}
        preferences = {field: existing.get(field, current[field]) for field in preference_fields}
        if is_new or changes["salary_min_rub"]:
            preferences["salary_min_rub"] = payload.min_salary_rub or None
        if is_new or changes["allowed_work_formats"]:
            preferences["allowed_work_formats"] = formats_from_legacy(payload.work_format)
        if is_new or changes["available"]:
            preferences["available"] = payload.available
        profile.preferences = preferences
        profile.preferences_version = max(1, profile.preferences_version or 1) + (0 if is_new else 1)
        profile.preferences_confirmed_at = at

    profile.min_salary_rub = payload.min_salary_rub
    profile.work_format = payload.work_format
    profile.available = payload.available


def save_preferences(db: Session, candidate_id: str, payload: CandidatePreferencesIn,
                     at: datetime) -> dict:
    profile = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == candidate_id
    ).with_for_update())
    if profile is None:
        profile = CandidateProfile(user_id=candidate_id, preferences_version=1)
        db.add(profile)
        db.flush()
    if profile.preferences_version != payload.expected_version:
        raise PreferencesError("PREFERENCES_VERSION_CONFLICT")

    next_preferences = payload.model_dump(exclude={"expected_version", "adult_hiring_confirmed"})
    next_preferences["allowed_work_formats"] = list(dict.fromkeys(next_preferences["allowed_work_formats"]))
    profile.preferences = next_preferences
    profile.preferences_version += 1
    profile.preferences_confirmed_at = at
    profile.min_salary_rub = payload.salary_min_rub or 0
    profile.work_format = (payload.allowed_work_formats[0]
                           if len(payload.allowed_work_formats) == 1 else "any")
    profile.available = payload.available
    profile.adult_attested_at = at if payload.adult_hiring_confirmed else None
    db.flush()
    return preferences_data(profile)


def _owned_employer(db: Session, employer_id: str) -> User:
    employer = db.get(User, employer_id)
    if not employer or employer.role != "employer":
        raise PreferencesError("NOT_FOUND", 404)
    return employer


def _profile(db: Session, candidate_id: str) -> CandidateProfile:
    profile = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == candidate_id
    ).with_for_update())
    if not profile:
        raise PreferencesError("PROFILE_REQUIRED", 409)
    return profile


def _revoke_grants(db: Session, candidate_id: str, employer_id: str, at: datetime) -> int:
    grants = db.scalars(select(ContactGrant).where(
        ContactGrant.candidate_id == candidate_id,
        ContactGrant.employer_id == employer_id,
        ContactGrant.revoked_at.is_(None),
    )).all()
    for grant in grants:
        grant.revoked_at = at
    return len(grants)


def revoke_employer_contacts(db: Session, candidate_id: str, employer_id: str,
                             at: datetime) -> AccessChangeResult:
    _owned_employer(db, employer_id)
    _profile(db, candidate_id)
    revoked = _revoke_grants(db, candidate_id, employer_id, at)
    db.flush()
    return AccessChangeResult(employer_id, False, revoked, 0)


def block_employer(db: Session, candidate_id: str, employer_id: str,
                   at: datetime) -> AccessChangeResult:
    _owned_employer(db, employer_id)
    profile = _profile(db, candidate_id)
    blocked = set(profile.blocked_employer_ids or [])
    blocked.add(employer_id)
    profile.blocked_employer_ids = sorted(blocked)

    pending = db.scalars(select(Invitation).where(
        Invitation.candidate_id == candidate_id,
        Invitation.employer_id == employer_id,
        Invitation.state.in_(("sent", "viewed")),
    )).all()
    for invitation in pending:
        invitation.state = "withdrawn"
        invitation.state_version += 1
        invitation.decided_at = at
        write_invitation_event(db, invitation, "invitation_withdrawn", candidate_id, at)
    revoked = _revoke_grants(db, candidate_id, employer_id, at)
    db.flush()
    return AccessChangeResult(employer_id, True, revoked, len(pending))
