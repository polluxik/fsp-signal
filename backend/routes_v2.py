"""Versioned role-card HTTP boundary; business rules live in role_cards."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assessment import COMPETENCIES
from .db import get_db
from .domain_errors import DomainError
from .models import HiringNeed, User, now
from .role_cards import (
    close_role, create_role_version, pause_role, publish_role,
    reconfirm_role, role_card_data,
)
from .schemas import (
    PublishRoleIn, ReconfirmRoleIn, RoleCardOut, RoleMutationIn, RoleVersionIn,
)
from .security import csrf_guard, get_user, require


router = APIRouter(prefix="/api/v1/employer/needs", tags=["employer-v2"])


def _raise_role_error(exc: DomainError) -> None:
    raise HTTPException(status_code=exc.status, detail=exc.code) from exc


def _owned_need(db: Session, user: User, need_id: str) -> HiringNeed:
    need = db.scalar(select(HiringNeed).where(HiringNeed.id == need_id,
                                              HiringNeed.employer_id == user.id))
    if not need:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return need


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
