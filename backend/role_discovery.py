"""Candidate-side role discovery and private save/hide decisions."""

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .domain_errors import DomainError
from .matching import evaluate_compatibility
from .models import (CandidateProfile, EmployerProfile, HiringNeed, RoleDecision,
                     RoleVersion, User, now)
from .preferences import is_blocked, preferences_data
from .role_cards import FRESHNESS, is_role_fresh, terms_hash
from .schemas import (CandidateRoleCard, CandidateRoleFeedItem, CompatibilityReport,
                      RoleDecisionOut, RoleFeedOut, RoleCardIn)


class RoleDiscoveryError(DomainError):
    pass


RoleAction = Literal["saved", "hidden", "none"]
_MAX_PAGE_SIZE = 20
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_PATTERNS = (
    re.compile(
    r"(?<!\w)(?:\+7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{2}[\s().-]*\d{2}(?!\d)"
    ),
    re.compile(r"(?<!\w)(?:\+\d{1,3}[ .()-]*)?(?:\d{2,4}[ .()-]+){2,4}\d{2,4}(?!\w)"),
)


def _filters_fingerprint(specialization: str | None, grade: str | None,
                         work_format: str | None, saved_only: bool) -> str:
    canonical = json.dumps({
        "specialization": specialization, "grade": grade,
        "work_format": work_format, "saved_only": saved_only,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _encode_cursor(confirmed_at: datetime, need_id: str, fingerprint: str) -> str:
    payload = json.dumps({
        "confirmed_at": confirmed_at.isoformat(), "need_id": need_id,
        "filters": fingerprint,
    }, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str, fingerprint: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        confirmed_at = datetime.fromisoformat(payload["confirmed_at"])
        need_id = payload["need_id"]
        if payload.get("filters") != fingerprint or not isinstance(need_id, str) or not need_id:
            raise ValueError("cursor filters do not match")
        return confirmed_at, need_id
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError) as exc:
        raise RoleDiscoveryError("ROLE_CURSOR_INVALID", 422) from exc


def _data_mode(version: RoleVersion, employer: User) -> str:
    if settings.app_mode in {"demo", "test"}:
        return "synthetic"
    if version.source == "synthetic_demo" or employer.origin == "synthetic_fixture":
        return "synthetic"
    if version.source == "legacy_import" or employer.origin == "legacy_import":
        return "unknown"
    if employer.origin == "direct_signup":
        return "real"
    return "unknown"


def _public_role(payload: dict) -> CandidateRoleCard | None:
    try:
        # Validate the stored immutable version, then whitelist candidate-visible fields.
        role = RoleCardIn.model_validate(payload)
        safe = role.model_dump(mode="json", exclude={"employer_contact", "active_headcount_attested"})
        return CandidateRoleCard.model_validate(safe)
    except ValidationError:
        return None


def _text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _text_values(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _text_values(nested)


def _contains_contact_details(role: CandidateRoleCard, company_name: str) -> bool:
    candidate_visible_text = [*_text_values(role.model_dump(mode="json")), company_name]
    for value in candidate_visible_text:
        if _EMAIL_PATTERN.search(value):
            return True
        for pattern in _PHONE_PATTERNS:
            for match in pattern.finditer(value):
                digits = sum(character.isdigit() for character in match.group())
                if 10 <= digits <= 15:
                    return True
    return False


def _company_name(company: EmployerProfile | None) -> str:
    return (company.company_name.strip() if company and (company.company_name or "").strip()
            else "Работодатель")


def discover_roles(db: Session, candidate_id: str, cursor: str | None = None, limit: int = 5, *,
                   specialization: str | None = None, grade: str | None = None,
                   work_format: str | None = None, saved_only: bool = False) -> RoleFeedOut:
    if limit < 1 or limit > _MAX_PAGE_SIZE:
        raise RoleDiscoveryError("ROLE_PAGE_SIZE_INVALID", 422)
    candidate = db.get(User, candidate_id)
    if not candidate or candidate.role != "candidate":
        raise RoleDiscoveryError("NOT_FOUND", 404)

    fingerprint = _filters_fingerprint(specialization, grade, work_format, saved_only)
    after = _decode_cursor(cursor, fingerprint) if cursor else None
    cutoff = now() - FRESHNESS
    base_query = (
        select(HiringNeed, RoleVersion, EmployerProfile, User)
        .join(RoleVersion, and_(RoleVersion.need_id == HiringNeed.id,
                                RoleVersion.version == HiringNeed.current_role_version))
        .join(User, User.id == HiringNeed.employer_id)
        .outerjoin(EmployerProfile, EmployerProfile.user_id == HiringNeed.employer_id)
        .where(HiringNeed.publication_state == "active", HiringNeed.discoverable.is_(True),
               HiringNeed.confirmed_at.is_not(None), HiringNeed.confirmed_at > cutoff,
               User.role == "employer")
    )
    if specialization:
        base_query = base_query.where(HiringNeed.specialization == specialization)
    if grade:
        base_query = base_query.where(HiringNeed.grade == grade)
    if work_format:
        base_query = base_query.where(RoleVersion.payload["work_format"].as_string() == work_format)
    profile = db.get(CandidateProfile, candidate_id)
    preferences = preferences_data(profile)
    page_size = max(50, limit + 1)
    scan_after = after
    evaluated: list[tuple[CandidateRoleFeedItem, datetime]] = []
    has_more = False
    saw_role = False
    saw_preference_match = False

    while len(evaluated) <= limit:
        query = base_query
        if scan_after:
            after_at, after_id = scan_after
            query = query.where(or_(HiringNeed.confirmed_at < after_at,
                                    and_(HiringNeed.confirmed_at == after_at,
                                         HiringNeed.id > after_id)))
        rows = db.execute(query.order_by(HiringNeed.confirmed_at.desc(), HiringNeed.id.asc())
                          .limit(page_size)).all()
        if not rows:
            break
        saw_role = True
        decisions = db.scalars(select(RoleDecision).where(
            RoleDecision.candidate_id == candidate_id,
            RoleDecision.need_id.in_([need.id for need, *_ in rows]),
        )).all()
        decision_by_need = {decision.need_id: decision for decision in decisions}
        last_scanned: tuple[datetime, str] | None = None

        for need, version, company, employer in rows:
            if not need.confirmed_at:
                continue
            last_scanned = (need.confirmed_at, need.id)
            if not is_role_fresh(need.confirmed_at, now()):
                continue
            if profile and is_blocked(profile, employer.id):
                continue
            safe_role = _public_role(version.payload or {})
            if not safe_role or version.terms_hash != terms_hash(version.payload or {}):
                continue
            company_name = _company_name(company)
            if _contains_contact_details(safe_role, company_name):
                continue

            report: CompatibilityReport | None = None
            match_state: Literal["compatible", "needs_clarification", "not_assessed"] = "not_assessed"
            if profile:
                report = evaluate_compatibility(profile, safe_role.model_dump(mode="json"), mode="search",
                                                role_version_id=version.id)
                if report.status == "incompatible":
                    continue
                saw_preference_match = True
                has_category = bool(profile.verified_specialization and profile.verified_grade)
                if has_category:
                    same_category = (profile.verified_specialization, profile.verified_grade) == (
                        safe_role.specialization, safe_role.grade
                    )
                    match_state = report.status if same_category else "needs_clarification"
                else:
                    if report.status == "needs_clarification":
                        match_state = "needs_clarification"
                    else:
                        report = None

            stored_decision = decision_by_need.get(need.id)
            action: RoleAction = "none"
            if (stored_decision and stored_decision.role_version_id == version.id
                    and stored_decision.preferences_version == preferences["version"]
                    and stored_decision.action in ("saved", "hidden", "none")):
                action = stored_decision.action
            if action == "hidden" or (saved_only and action != "saved"):
                continue

            item = CandidateRoleFeedItem(
                need_id=need.id,
                role_version_id=version.id,
                role_version=version.version,
                company_name=company_name,
                role=safe_role,
                confirmed_at=need.confirmed_at,
                preferences_version=preferences["version"],
                data_mode=_data_mode(version, employer),
                match_state=match_state,
                compatibility=report,
                decision=action,
            )
            evaluated.append((item, need.confirmed_at))
            if len(evaluated) > limit:
                has_more = True
                break

        if has_more or len(rows) < page_size or not last_scanned:
            break
        scan_after = last_scanned

    page = evaluated[:limit]
    next_cursor = None
    if has_more and page:
        last_item, last_confirmed_at = page[-1]
        next_cursor = _encode_cursor(last_confirmed_at, last_item.need_id, fingerprint)
    empty_state = None
    if not page:
        empty_state = ("no_saved_roles" if saved_only else
                       "no_compatible_roles" if profile and saw_role and not saw_preference_match
                       else "no_active_roles")
    return RoleFeedOut(items=[item for item, _ in page], next_cursor=next_cursor, limit=limit,
                       empty_state=empty_state)


def save_role_decision(db: Session, candidate_id: str, need_id: str, action: RoleAction,
                       expected_role_version: str, expected_preferences_version: int,
                       at: datetime) -> RoleDecisionOut:
    candidate = db.get(User, candidate_id)
    if not candidate or candidate.role != "candidate":
        raise RoleDiscoveryError("NOT_FOUND", 404)
    need = db.scalar(select(HiringNeed).where(HiringNeed.id == need_id).with_for_update())
    if (not need or need.publication_state != "active" or not need.discoverable
            or not need.confirmed_at or not is_role_fresh(need.confirmed_at, at)):
        raise RoleDiscoveryError("ROLE_NOT_AVAILABLE", 404)
    employer = db.get(User, need.employer_id)
    if not employer or employer.role != "employer":
        raise RoleDiscoveryError("ROLE_NOT_AVAILABLE", 404)
    profile = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == candidate_id
    ).with_for_update())
    if profile and is_blocked(profile, employer.id):
        raise RoleDiscoveryError("ROLE_NOT_AVAILABLE", 404)

    version = db.scalar(select(RoleVersion).where(
        RoleVersion.need_id == need.id, RoleVersion.version == need.current_role_version
    ))
    safe_role = _public_role(version.payload or {}) if version else None
    if not version or not safe_role or version.terms_hash != terms_hash(version.payload or {}):
        raise RoleDiscoveryError("ROLE_NOT_AVAILABLE", 404)
    company = db.get(EmployerProfile, employer.id)
    if _contains_contact_details(safe_role, _company_name(company)):
        raise RoleDiscoveryError("ROLE_NOT_AVAILABLE", 404)
    if expected_role_version != version.id:
        raise RoleDiscoveryError("ROLE_VERSION_CONFLICT", 409)

    preferences = preferences_data(profile)
    if expected_preferences_version != preferences["version"]:
        raise RoleDiscoveryError("PREFERENCES_VERSION_CONFLICT", 409)
    if profile and evaluate_compatibility(
        profile, safe_role.model_dump(mode="json"), mode="search", role_version_id=version.id
    ).status == "incompatible":
        raise RoleDiscoveryError("ROLE_NOT_AVAILABLE", 409)

    decision = db.scalar(select(RoleDecision).where(
        RoleDecision.candidate_id == candidate_id,
        RoleDecision.need_id == need_id,
    ).with_for_update())
    if decision is None:
        decision = RoleDecision(
            candidate_id=candidate_id,
            need_id=need_id,
            role_version_id=version.id,
            action=action,
            preferences_version=preferences["version"],
            updated_at=at,
        )
        db.add(decision)
    else:
        decision.role_version_id = version.id
        decision.action = action
        decision.preferences_version = preferences["version"]
        decision.updated_at = at
    db.flush()
    return RoleDecisionOut(
        need_id=need_id,
        action=action,
        role_version_id=version.id,
        preferences_version=preferences["version"],
        updated_at=at,
    )
