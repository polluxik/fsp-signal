"""Versioned role-card HTTP boundary; business rules live in role_cards."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .assessment import COMPETENCIES
from .db import get_db
from .domain_errors import DomainError
from .evidence import list_candidate_evidence
from .models import CandidateProfile, HiringNeed, User, now
from .preferences import block_employer, preferences_data, revoke_employer_contacts, save_preferences
from .role_discovery import RoleDiscoveryError, discover_roles, save_role_decision
from .role_cards import (
    close_role, create_role_version, pause_role, publish_role,
    reconfirm_role, role_card_data,
)
from .schemas import (
    AccessChangeResult, CandidatePreferencesIn, CandidatePreferencesOut,
    EvidenceCard, PublishRoleIn, ReconfirmRoleIn, RoleCardOut, RoleDecisionIn,
    RoleDecisionOut, RoleFeedOut, RoleMutationIn, RoleVersionIn,
)
from .security import csrf_guard, get_user, require


router = APIRouter(prefix="/api/v1/employer/needs", tags=["employer-v2"])
candidate_router = APIRouter(prefix="/api/v1/candidate", tags=["candidate-v2"])


def _raise_role_error(exc: DomainError) -> None:
    raise HTTPException(status_code=exc.status, detail=exc.code) from exc


def _owned_need(db: Session, user: User, need_id: str) -> HiringNeed:
    need = db.scalar(select(HiringNeed).where(HiringNeed.id == need_id,
                                              HiringNeed.employer_id == user.id))
    if not need:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return need


@candidate_router.get("/evidence", response_model=list[EvidenceCard])
def get_candidate_evidence(response: Response, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    response.headers["Cache-Control"] = "no-store"
    return list_candidate_evidence(db, user.id, audience="self")


@candidate_router.get("/roles", response_model=RoleFeedOut)
def get_candidate_roles(response: Response, cursor: str | None = Query(default=None, max_length=512),
                        limit: int = Query(default=5, ge=1, le=20),
                        specialization: Literal["backend", "frontend"] | None = None,
                        grade: Literal["junior", "middle"] | None = None,
                        work_format: Literal["remote", "hybrid", "office"] | None = None,
                        saved_only: bool = False,
                        user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    response.headers["Cache-Control"] = "no-store"
    try:
        return discover_roles(db, user.id, cursor, limit, specialization=specialization,
                              grade=grade, work_format=work_format, saved_only=saved_only)
    except RoleDiscoveryError as exc:
        _raise_role_error(exc)


@candidate_router.put("/role-decisions/{need_id}", response_model=RoleDecisionOut,
                      dependencies=[Depends(csrf_guard)])
def put_candidate_role_decision(need_id: str, data: RoleDecisionIn,
                                user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    try:
        result = save_role_decision(
            db, user.id, need_id, data.action, data.expected_role_version,
            data.expected_preferences_version, now(),
        )
        db.commit()
        return result
    except RoleDiscoveryError as exc:
        db.rollback()
        _raise_role_error(exc)
    except IntegrityError as exc:
        db.rollback()
        _raise_role_error(RoleDiscoveryError("ROLE_DECISION_CONFLICT", 409))


@router.get("/{need_id}/role-card", response_model=RoleCardOut)
def get_role_card(need_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    need = _owned_need(db, user, need_id)
    return role_card_data(db, need, now())


@router.post("/{need_id}/versions", response_model=RoleCardOut, status_code=201,
             dependencies=[Depends(csrf_guard)])
def post_role_version(need_id: str, data: RoleVersionIn, user: User = Depends(get_user),
                      db: Session = Depends(get_db)):
    require(user, "employer")
    if f"{data.card.specialization}:{data.card.grade}" not in COMPETENCIES:
        raise HTTPException(status_code=422, detail="UNSUPPORTED_CATEGORY")
    allowed = set(COMPETENCIES[f"{data.card.specialization}:{data.card.grade}"])
    if not set(data.card.competencies).issubset(allowed):
        raise HTTPException(status_code=422, detail="INVALID_COMPETENCY")
    try:
        create_role_version(db, user.id, need_id, data.card, data.expected_version, now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    need = _owned_need(db, user, need_id)
    return role_card_data(db, need, now())


@router.post("/{need_id}/publish", response_model=RoleCardOut, dependencies=[Depends(csrf_guard)])
def post_publish_role(need_id: str, data: PublishRoleIn, user: User = Depends(get_user),
                      db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        need = publish_role(db, user.id, need_id, expected_version=data.expected_version,
                            active_headcount_attested=data.active_headcount_attested,
                            discoverable=data.discoverable, at=now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    return role_card_data(db, need, now())


@router.post("/{need_id}/reconfirm", response_model=RoleCardOut, dependencies=[Depends(csrf_guard)])
def post_reconfirm_role(need_id: str, data: ReconfirmRoleIn, user: User = Depends(get_user),
                        db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        need = reconfirm_role(db, user.id, need_id, expected_version=data.expected_version,
                              active_headcount_attested=data.active_headcount_attested, at=now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    return role_card_data(db, need, now())


@router.post("/{need_id}/pause", response_model=RoleCardOut, dependencies=[Depends(csrf_guard)])
def post_pause_role(need_id: str, data: RoleMutationIn, user: User = Depends(get_user),
                    db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        need = pause_role(db, user.id, need_id, expected_version=data.expected_version, at=now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    return role_card_data(db, need, now())


@router.post("/{need_id}/close", response_model=RoleCardOut, dependencies=[Depends(csrf_guard)])
def post_close_role(need_id: str, data: RoleMutationIn, user: User = Depends(get_user),
                    db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        need = close_role(db, user.id, need_id, expected_version=data.expected_version, at=now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    return role_card_data(db, need, now())


@candidate_router.get("/preferences", response_model=CandidatePreferencesOut)
def get_candidate_preferences(response: Response, user: User = Depends(get_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    require(user, "candidate")
    return preferences_data(db.get(CandidateProfile, user.id))


@candidate_router.put("/preferences", response_model=CandidatePreferencesOut,
                      dependencies=[Depends(csrf_guard)])
def put_candidate_preferences(response: Response, data: CandidatePreferencesIn, user: User = Depends(get_user),
                              db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    require(user, "candidate")
    try:
        result = save_preferences(db, user.id, data, now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    return result


@candidate_router.post("/companies/{employer_id}/block", response_model=AccessChangeResult,
                       dependencies=[Depends(csrf_guard)])
def post_block_employer(employer_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    try:
        result = block_employer(db, user.id, employer_id, now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    return result.__dict__


@candidate_router.post("/companies/{employer_id}/revoke-contact", response_model=AccessChangeResult,
                       dependencies=[Depends(csrf_guard)])
def post_revoke_employer_contacts(employer_id: str, user: User = Depends(get_user),
                                  db: Session = Depends(get_db)):
    require(user, "candidate")
    try:
        result = revoke_employer_contacts(db, user.id, employer_id, now())
        db.commit()
    except DomainError as exc:
        db.rollback()
        _raise_role_error(exc)
    return result.__dict__
