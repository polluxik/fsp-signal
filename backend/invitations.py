"""Version-pinned invitation creation and compare-and-set state transitions."""

from datetime import datetime, timedelta, timezone
import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .domain_errors import DomainError
from .evidence import build_interview_agenda, resolve_evidence_refs
from .matching import can_search, evaluate_compatibility, explain_profile
from .models import (CandidateProfile, ContactGrant, EmployerProfile, HiringNeed, Invitation,
                     MailOutbox, RoleVersion, User)
from .preferences import is_blocked, preferences_data
from .product_events import write_invitation_event
from .role_cards import is_role_fresh, terms_hash
from .schemas import AcceptInvitationIn, InvitationV2In, RoleCardIn


class InvitationError(DomainError):
    pass


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _fingerprint(payload: InvitationV2In) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotent_result(db: Session, employer_id: str, key: str, request_hash: str) -> Invitation | None:
    existing = db.scalar(select(Invitation).where(
        Invitation.employer_id == employer_id, Invitation.idempotency_key == key
    ))
    if not existing:
        return None
    if existing.request_hash != request_hash:
        raise InvitationError("IDEMPOTENCY_KEY_REUSED")
    return existing


def _event(db: Session, invitation: Invitation, event_type: str, actor_id: str | None,
           at: datetime, *, state_version: int | None = None) -> None:
    write_invitation_event(
        db, invitation, event_type, actor_id, at, state_version=state_version,
    )


def _outbox(db: Session, recipient: str, subject: str, body: str, at: datetime) -> None:
    db.add(MailOutbox(recipient=recipient, subject=subject, body=body, created_at=at,
                      next_attempt_at=at))


def _close_expired_pair_rows(db: Session, employer_id: str, candidate_id: str, at: datetime) -> None:
    pending = db.scalars(select(Invitation).where(
        Invitation.employer_id == employer_id,
        Invitation.candidate_id == candidate_id,
        Invitation.state.in_(('sent', 'viewed')),
        Invitation.expires_at <= at,
    ).with_for_update()).all()
    for invitation in pending:
        old_version = invitation.state_version
        changed = db.execute(update(Invitation).where(
            Invitation.id == invitation.id,
            Invitation.state.in_(('sent', 'viewed')),
            Invitation.state_version == old_version,
            Invitation.expires_at <= at,
        ).values(state="expired", state_version=old_version + 1, decided_at=at)
          .execution_options(synchronize_session=False))
        if changed.rowcount == 1:
            invitation.state = "expired"
            invitation.state_version = old_version + 1
            invitation.decided_at = at
            _event(db, invitation, "invitation_expired", None, at)


def _active_pair_invitation(db: Session, employer_id: str, candidate_id: str) -> Invitation | None:
    return db.scalar(select(Invitation).where(
        Invitation.employer_id == employer_id,
        Invitation.candidate_id == candidate_id,
        Invitation.state.in_(('sent', 'viewed')),
    ).with_for_update())


def _validate_role_for_send(db: Session, employer_id: str, data: InvitationV2In,
                            at: datetime) -> tuple[RoleCardIn | None, HiringNeed | None, RoleVersion | None]:
    if data.role_version_id:
        version = db.get(RoleVersion, data.role_version_id)
        if not version:
            raise InvitationError("NOT_FOUND", 404)
        need = db.scalar(select(HiringNeed).where(
            HiringNeed.id == version.need_id, HiringNeed.employer_id == employer_id
        ).with_for_update())
        if not need or (data.need_id and data.need_id != need.id):
            raise InvitationError("NOT_FOUND", 404)
        current_version = db.scalar(select(RoleVersion).where(
            RoleVersion.need_id == need.id, RoleVersion.version == need.current_role_version
        ))
        if not current_version or current_version.id != version.id:
            raise InvitationError("ROLE_VERSION_CONFLICT")
        if need.publication_state != "active":
            raise InvitationError("ROLE_NOT_ACTIVE")
        if not is_role_fresh(need.confirmed_at, at):
            raise InvitationError("ROLE_STALE")
        if version.terms_hash != terms_hash(version.payload or {}):
            raise InvitationError("ROLE_TERMS_HASH_INVALID")
        try:
            role = RoleCardIn.model_validate(version.payload)
        except Exception as exc:
            raise InvitationError("ROLE_INCOMPLETE") from exc
        return role, need, version

    if data.inline_role_card is None:
        if data.need_id:
            need = db.scalar(select(HiringNeed).where(
                HiringNeed.id == data.need_id, HiringNeed.employer_id == employer_id
            ).with_for_update())
            if not need:
                raise InvitationError("NOT_FOUND", 404)
        else:
            need = None
        return None, need, None  # Legacy invitation path.

    role = data.inline_role_card
    if not role.active_headcount_attested:
        raise InvitationError("ROLE_ATTESTATION_REQUIRED")
    if data.need_id:
        need = db.scalar(select(HiringNeed).where(
            HiringNeed.id == data.need_id, HiringNeed.employer_id == employer_id
        ).with_for_update())
        if not need:
            raise InvitationError("NOT_FOUND", 404)
    else:
        need = None
    return role, need, None


def _role_terms_hash(role_payload: dict, role_version_id: str | None,
                     offer: dict[str, object]) -> str:
    payload = {
        "role_version_id": role_version_id,
        "role_terms_hash": terms_hash(role_payload),
        "offer": {key: offer[key] for key in ("salary_min_rub", "salary_max_rub", "work_format")},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_invitation(db: Session, employer_id: str, payload: InvitationV2In,
                      idempotency_key: str, at: datetime) -> Invitation:
    """Create a pinned invitation without making private compatibility affect the response."""
    employer = db.get(User, employer_id)
    if not employer or employer.role != "employer":
        raise InvitationError("NOT_FOUND", 404)
    company = db.get(EmployerProfile, employer_id)
    if not company:
        raise InvitationError("EMPLOYER_PROFILE_REQUIRED", 409)

    request_hash = _fingerprint(payload)
    existing = _idempotent_result(db, employer_id, idempotency_key, request_hash)
    if existing:
        return existing

    candidate = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == payload.candidate_id
    ).with_for_update())
    # Recheck after the candidate row lock: another request with the same key
    # may have committed while this transaction waited for that lock.
    existing = _idempotent_result(db, employer_id, idempotency_key, request_hash)
    if existing:
        return existing
    if not candidate or not can_search(candidate):
        raise InvitationError("NOT_FOUND", 404)
    if is_blocked(candidate, employer_id):
        raise InvitationError("COMPANY_BLOCKED")

    role, need, version = _validate_role_for_send(db, employer_id, payload, at)
    if need and role is None:
        if (candidate.verified_specialization, candidate.verified_grade) != (
            need.specialization, need.grade
        ):
            raise InvitationError("CATEGORY_MISMATCH")

    if payload.salary_max_rub < payload.salary_min_rub:
        raise InvitationError("SALARY_RANGE_INVALID", 422)
    employer_contact = payload.employer_contact
    role_payload: dict = {}
    role_version_id = version.id if version else None
    terms_snapshot = None
    pinned_terms_hash = None
    evidence_refs: list[dict] = []
    explanation_snapshot = None

    if role is not None:
        role_payload = role.model_dump(mode="json")
        if (candidate.verified_specialization, candidate.verified_grade) != (
            role.specialization, role.grade
        ):
            raise InvitationError("CATEGORY_MISMATCH")
        if (payload.salary_min_rub < role.salary_min_rub
                or payload.salary_max_rub > role.salary_max_rub
                or payload.work_format != role.work_format):
            raise InvitationError("OFFER_OUTSIDE_ROLE_TERMS", 422)
        if payload.employer_contact != role.employer_contact:
            raise InvitationError("ROLE_CONTACT_MISMATCH", 422)
        employer_contact = role.employer_contact
        cards = resolve_evidence_refs(db, candidate.user_id, payload.evidence_ids, employer_id)
        evidence_refs = [card.model_dump(mode="json") for card in cards]
        explanation = explain_profile(candidate, role)
        explanation_snapshot = {
            "reasons": explanation.reasons,
            "gaps": [gap.model_dump(mode="json") for gap in explanation.gaps],
            "agenda": build_interview_agenda(explanation),
        }
        offer = {
            "salary_min_rub": payload.salary_min_rub,
            "salary_max_rub": payload.salary_max_rub,
            "work_format": payload.work_format,
            "employer_contact": employer_contact,
        }
        terms_snapshot = {"role": role_payload, "offer": offer}
        pinned_terms_hash = _role_terms_hash(role_payload, role_version_id, offer)

    compatibility_role = role_payload
    if role is None and need:
        compatibility_role = {
            "specialization": need.specialization,
            "grade": need.grade,
            "salary_max_rub": need.salary_max_rub,
            "work_format": need.work_format,
        }
    compatibility_snapshot = evaluate_compatibility(
        candidate, compatibility_role, mode="invitation",
        role_version_id=role_version_id,
        offer_terms={
            "salary_min_rub": payload.salary_min_rub,
            "salary_max_rub": payload.salary_max_rub,
            "work_format": payload.work_format,
        },
    ).model_dump(mode="json")

    _close_expired_pair_rows(db, employer_id, candidate.user_id, at)
    active = _active_pair_invitation(db, employer_id, candidate.user_id)
    if active:
        raise InvitationError("ACTIVE_INVITATION_EXISTS")

    invitation = Invitation(
        employer_id=employer_id, candidate_id=candidate.user_id,
        need_id=need.id if need else None, role_version_id=role_version_id,
        company_name=company.company_name, offer_text=payload.offer_text, reason=payload.reason,
        employer_contact=employer_contact, salary_min_rub=payload.salary_min_rub,
        salary_max_rub=payload.salary_max_rub, work_format=payload.work_format,
        state="sent", state_version=1, terms_snapshot=terms_snapshot,
        terms_hash=pinned_terms_hash, evidence_refs=evidence_refs,
        explanation_snapshot=explanation_snapshot, compatibility_snapshot=compatibility_snapshot,
        response_due_at=None,
        idempotency_key=idempotency_key, request_hash=request_hash,
        expires_at=at + timedelta(days=7), created_at=at,
    )
    db.add(invitation)
    db.flush()
    _event(db, invitation, "invitation_sent", employer_id, at)
    candidate_user = db.get(User, candidate.user_id)
    _outbox(db, candidate_user.email, "Новое приглашение — ФСП Сигнал",
            f"Компания {company.company_name} прислала предложение. Откройте кабинет: "
            f"{settings.public_base_url}", at)
    return invitation


def _transition_update(db: Session, invitation: Invitation, *, new_state: str,
                       at: datetime, require_unexpired: bool = True,
                       response_due_at: datetime | None = None) -> bool:
    conditions = [
        Invitation.id == invitation.id,
        Invitation.state.in_(("sent", "viewed")),
        Invitation.state_version == invitation.state_version,
    ]
    if require_unexpired:
        conditions.append(Invitation.expires_at > at)
    changed = db.execute(update(Invitation).where(*conditions).values(
        state=new_state, state_version=invitation.state_version + 1,
        decided_at=at if new_state in ("accepted", "rejected", "withdrawn", "expired") else None,
        response_due_at=response_due_at,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        return False
    invitation.state = new_state
    invitation.state_version += 1
    invitation.decided_at = at if new_state in ("accepted", "rejected", "withdrawn", "expired") else None
    invitation.response_due_at = response_due_at
    return True


def _current_candidate_profile(db: Session, candidate_id: str) -> CandidateProfile:
    profile = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == candidate_id
    ).with_for_update())
    if not profile:
        raise InvitationError("NOT_FOUND", 404)
    return profile


def _check_acceptance(db: Session, invitation: Invitation, profile: CandidateProfile,
                      command: AcceptInvitationIn | None, at: datetime,
                      locked_need: HiringNeed | None = None) -> datetime | None:
    if not can_search(profile):
        raise InvitationError("INVITATION_NOT_AVAILABLE")
    if is_blocked(profile, invitation.employer_id):
        raise InvitationError("COMPANY_BLOCKED")

    if invitation.terms_snapshot is None:
        if evaluate_compatibility(
            profile, {}, mode="invitation",
            offer_terms={"salary_min_rub": invitation.salary_min_rub,
                         "salary_max_rub": invitation.salary_max_rub,
                         "work_format": invitation.work_format},
        ).status == "incompatible":
            raise InvitationError("INVITATION_NOT_COMPATIBLE")
        return None

    if command is None:
        raise InvitationError("TERMS_CONFIRMATION_REQUIRED", 422)
    if command.expected_terms_hash != invitation.terms_hash:
        raise InvitationError("TERMS_VERSION_CONFLICT")
    if command.expected_preferences_version != preferences_data(profile)["version"]:
        raise InvitationError("PREFERENCES_VERSION_CONFLICT")

    snapshot = invitation.terms_snapshot
    role_data = snapshot["role"]
    if invitation.role_version_id:
        need = locked_need or db.scalar(select(HiringNeed).where(
            HiringNeed.id == invitation.need_id
        ).with_for_update())
        version = db.get(RoleVersion, invitation.role_version_id)
        current = db.scalar(select(RoleVersion).where(
            RoleVersion.need_id == invitation.need_id,
            RoleVersion.version == need.current_role_version if need else -1,
        ))
        if (not need or need.employer_id != invitation.employer_id
                or not version or version.need_id != need.id
                or not current or version.id != current.id
                or need.publication_state != "active"):
            raise InvitationError("ROLE_VERSION_CONFLICT")
        if not is_role_fresh(need.confirmed_at, at):
            raise InvitationError("ROLE_STALE")

    if evaluate_compatibility(
        profile, role_data, mode="invitation", role_version_id=invitation.role_version_id,
        offer_terms=snapshot["offer"],
    ).status == "incompatible":
        raise InvitationError("CONDITIONS_INCOMPATIBLE")

    role_terms = RoleCardIn.model_validate(role_data)
    offer = snapshot["offer"]
    expected_hash = _role_terms_hash(role_data, invitation.role_version_id, offer)
    if expected_hash != invitation.terms_hash:
        raise InvitationError("INVITATION_TERMS_INVALID")
    due_at = at + timedelta(hours=role_terms.response_sla_hours)
    return due_at


def transition_invitation(db: Session, actor_id: str | None, invitation_id: str, command: str,
                          expected_state_version: int | None,
                          accept_terms: AcceptInvitationIn | None, at: datetime) -> Invitation:
    initial = db.get(Invitation, invitation_id)
    if not initial:
        raise InvitationError("NOT_FOUND", 404)
    profile = _current_candidate_profile(db, initial.candidate_id) if command == "accept" else None
    # A transition can acquire a key-share lock on HiringNeed when PostgreSQL
    # checks the invitation's FK. Lock it first for every command, so accept,
    # reject, withdraw and expire use the same order as role lifecycle updates.
    locked_need = None
    if initial.need_id:
        locked_need = db.scalar(select(HiringNeed).where(
            HiringNeed.id == initial.need_id
        ).with_for_update())
    invitation = db.scalar(select(Invitation).where(
        Invitation.id == invitation_id
    ).with_for_update())
    if not invitation:
        raise InvitationError("NOT_FOUND", 404)

    if command == "expire":
        if invitation.state == "expired":
            return invitation
        if invitation.state not in ("sent", "viewed") or _utc(invitation.expires_at) > _utc(at):
            raise InvitationError("INVITATION_STATE_CONFLICT")
        if not _transition_update(db, invitation, new_state="expired", at=at, require_unexpired=False):
            raise InvitationError("INVITATION_STATE_CONFLICT")
        _event(db, invitation, "invitation_expired", actor_id, at)
        return invitation

    if actor_id is None:
        raise InvitationError("FORBIDDEN", 403)
    is_candidate = actor_id == invitation.candidate_id
    is_employer = actor_id == invitation.employer_id
    if command in ("view", "accept", "reject") and not is_candidate:
        raise InvitationError("NOT_FOUND", 404)
    if command == "withdraw" and not is_employer:
        raise InvitationError("NOT_FOUND", 404)
    if command not in ("view", "accept", "reject", "withdraw"):
        raise InvitationError("INVALID_INVITATION_COMMAND", 422)

    if command == "accept" and invitation.state == "accepted":
        return invitation
    if command == "accept" and profile and is_blocked(profile, invitation.employer_id):
        raise InvitationError("COMPANY_BLOCKED")
    if expected_state_version is not None and expected_state_version != invitation.state_version:
        raise InvitationError("INVITATION_STATE_CONFLICT")
    if invitation.state not in ("sent", "viewed") or _utc(invitation.expires_at) <= _utc(at):
        raise InvitationError("INVITATION_STATE_CONFLICT")

    if command == "view":
        if invitation.state == "viewed":
            return invitation
        if not _transition_update(db, invitation, new_state="viewed", at=at):
            raise InvitationError("INVITATION_STATE_CONFLICT")
        _event(db, invitation, "invitation_viewed", actor_id, at)
        return invitation

    if command == "accept":
        if profile is None:
            raise InvitationError("INVITATION_NOT_AVAILABLE")
        response_due_at = _check_acceptance(
            db, invitation, profile, accept_terms, at, locked_need,
        )
        if not _transition_update(db, invitation, new_state="accepted", at=at,
                                  response_due_at=response_due_at):
            raise InvitationError("INVITATION_STATE_CONFLICT")
        db.add(ContactGrant(invitation_id=invitation.id, employer_id=invitation.employer_id,
                            candidate_id=invitation.candidate_id, granted_at=at))
        _event(db, invitation, "invitation_accepted", actor_id, at)
        employer = db.get(User, invitation.employer_id)
        _outbox(db, employer.email, "Кандидат принял приглашение — ФСП Сигнал",
                f"Кандидат принял приглашение. Следующий шаг отмечен в кабинете: "
                f"{settings.public_base_url}", at)
        return invitation

    new_state = "rejected" if command == "reject" else "withdrawn"
    if not _transition_update(db, invitation, new_state=new_state, at=at):
        raise InvitationError("INVITATION_STATE_CONFLICT")
    event_type = "invitation_rejected" if command == "reject" else "invitation_withdrawn"
    _event(db, invitation, event_type, actor_id, at)
    recipient = db.get(User, invitation.employer_id if command == "reject" else invitation.candidate_id)
    subject = "Приглашение отклонено — ФСП Сигнал" if command == "reject" else "Приглашение отозвано — ФСП Сигнал"
    _outbox(db, recipient.email, subject,
            f"Статус приглашения изменён. Откройте кабинет: {settings.public_base_url}", at)
    return invitation


def confirm_interview_held(db: Session, actor_id: str, invitation_id: str,
                           at: datetime) -> dict[str, object]:
    """Record one participant's confirmation; count the outcome only after both confirm."""
    initial = db.get(Invitation, invitation_id)
    if not initial or actor_id not in (initial.candidate_id, initial.employer_id):
        raise InvitationError("NOT_FOUND", 404)

    invitation = db.scalar(select(Invitation).where(
        Invitation.id == invitation_id
    ).with_for_update())
    if not invitation or actor_id not in (invitation.candidate_id, invitation.employer_id):
        raise InvitationError("NOT_FOUND", 404)
    if invitation.state != "accepted":
        raise InvitationError("INVITATION_NOT_ACCEPTED", 409)

    if actor_id == invitation.candidate_id:
        if invitation.candidate_interview_confirmed_at is None:
            invitation.candidate_interview_confirmed_at = at
    elif invitation.employer_interview_confirmed_at is None:
        invitation.employer_interview_confirmed_at = at

    candidate_confirmed = invitation.candidate_interview_confirmed_at is not None
    employer_confirmed = invitation.employer_interview_confirmed_at is not None
    interview_held = candidate_confirmed and employer_confirmed
    if interview_held:
        # This is a bilateral outcome, not an event owned by the last confirmer.
        _event(db, invitation, "interview_held", None, at)
    db.flush()
    return {
        "invitation_id": invitation.id,
        "candidate_confirmed": candidate_confirmed,
        "employer_confirmed": employer_confirmed,
        "interview_held": interview_held,
    }


def expire_due_invitations(db: Session, at: datetime) -> int:
    pending_ids = db.scalars(select(Invitation.id).where(
        Invitation.state.in_(("sent", "viewed")), Invitation.expires_at <= at
    ).order_by(Invitation.expires_at, Invitation.id)).all()
    expired = 0
    for invitation_id in pending_ids:
        try:
            transition_invitation(db, None, invitation_id, "expire", None, None, at)
            expired += 1
        except InvitationError as exc:
            if exc.code != "INVITATION_STATE_CONFLICT":
                raise
    return expired
