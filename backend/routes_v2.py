"""Versioned role-card HTTP boundary; business rules live in role_cards."""

from typing import Literal
from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai_assistant import AssistantError, AssistantIntent, generate_draft
from .assessment import COMPETENCIES
from .config import settings
from .db import get_db
from .domain_errors import DomainError
from .evidence import list_candidate_evidence
from .models import AssistantUsage, CandidateProfile, HiringNeed, User, now
from .preferences import block_employer, preferences_data, revoke_employer_contacts, save_preferences
from .promotions import PromotionError, activate_demo_campaign, get_demo_campaign
from .role_discovery import (RoleDiscoveryError, discover_roles, record_sponsored_impression,
                             save_role_decision)
from .role_cards import (
    close_role, create_role_version, pause_role, publish_role,
    reconfirm_role, role_card_data,
)
from .schemas import (
    AccessChangeResult, CandidatePreferencesIn, CandidatePreferencesOut,
    AssistantDraftIn, CandidateAchievementDraft, CandidatePreferencesDraft,
    DemoPromotionOut, EmployerRoleDraft, EvidenceCard, PublishRoleIn, ReconfirmRoleIn, RoleCardOut,
    RoleDecisionIn, RoleDecisionOut, RoleFeedOut, RoleMutationIn, RoleVersionIn,
    SponsoredImpressionOut,
)
from .security import csrf_guard, get_user, require
from .taxonomy import available_categories, get_category


router = APIRouter(prefix="/api/v1/employer/needs", tags=["employer-v2"])
candidate_router = APIRouter(prefix="/api/v1/candidate", tags=["candidate-v2"])
assistant_router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])
_ASSISTANT_RATE_LIMIT = 10
_ASSISTANT_RATE_WINDOW = timedelta(hours=1)


@candidate_router.get("/recommendations/consent")
def read_recommendation_consent(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = db.get(CandidateProfile, user.id)
    return {"consent": bool(profile and profile.recommendation_consent)}


@candidate_router.put("/recommendations/consent", dependencies=[Depends(csrf_guard)])
def save_recommendation_consent(consent: bool = Body(embed=True), user: User = Depends(get_user),
                                db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id).with_for_update())
    if not profile:
        raise HTTPException(409, detail="PROFILE_REQUIRED")
    profile.recommendation_consent = consent
    db.commit()
    return {"consent": profile.recommendation_consent}


def _raise_role_error(exc: DomainError) -> None:
    raise HTTPException(status_code=exc.status, detail=exc.code) from exc


def _owned_need(db: Session, user: User, need_id: str) -> HiringNeed:
    need = db.scalar(select(HiringNeed).where(HiringNeed.id == need_id,
                                              HiringNeed.employer_id == user.id))
    if not need:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return need


def _record_assistant_usage(db: Session, user_id: str, intent: AssistantIntent) -> None:
    locked_user_id = db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    if locked_user_id is None:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    cutoff = now() - _ASSISTANT_RATE_WINDOW
    recent_requests = db.scalar(
        select(func.count(AssistantUsage.id)).where(
            AssistantUsage.user_id == user_id,
            AssistantUsage.created_at >= cutoff,
        )
    ) or 0
    if recent_requests >= _ASSISTANT_RATE_LIMIT:
        db.rollback()
        raise HTTPException(status_code=429, detail="AI_RATE_LIMIT_EXCEEDED")
    db.add(AssistantUsage(user_id=user_id, intent=intent, created_at=now()))
    db.commit()


def _run_assistant_draft(intent: AssistantIntent, expected_role: Literal["candidate", "employer"],
                         response: Response, data: AssistantDraftIn,
                         user: User, db: Session):
    response.headers["Cache-Control"] = "no-store"
    require(user, expected_role)
    if data.external_ai_consent is not True:
        raise HTTPException(status_code=422, detail="EXTERNAL_AI_CONSENT_REQUIRED")
    if not settings.frontierai_api_key or not settings.frontierai_api_key.strip():
        raise HTTPException(status_code=503, detail="AI_PROVIDER_DISABLED")
    if len(data.text) > settings.assistant_max_input_chars:
        raise HTTPException(status_code=422, detail="AI_INPUT_TOO_LONG")

    _record_assistant_usage(db, user.id, intent)
    try:
        return generate_draft(
            intent, data.text, external_ai_consent=data.external_ai_consent, configured=settings,
        )
    except AssistantError as exc:
        _raise_role_error(exc)


@assistant_router.post("/candidate/preferences", response_model=CandidatePreferencesDraft,
                       dependencies=[Depends(csrf_guard)])
def draft_candidate_preferences(data: AssistantDraftIn, response: Response,
                                user: User = Depends(get_user), db: Session = Depends(get_db)):
    return _run_assistant_draft("candidate_preferences", "candidate", response, data, user, db)


@assistant_router.post("/candidate/achievement", response_model=CandidateAchievementDraft,
                       dependencies=[Depends(csrf_guard)])
def draft_candidate_achievement(data: AssistantDraftIn, response: Response,
                                user: User = Depends(get_user), db: Session = Depends(get_db)):
    return _run_assistant_draft("candidate_achievement", "candidate", response, data, user, db)


@assistant_router.post("/employer/role", response_model=EmployerRoleDraft,
                       dependencies=[Depends(csrf_guard)])
def draft_employer_role(data: AssistantDraftIn, response: Response,
                        user: User = Depends(get_user), db: Session = Depends(get_db)):
    return _run_assistant_draft("employer_role", "employer", response, data, user, db)


@candidate_router.get("/evidence", response_model=list[EvidenceCard])
def get_candidate_evidence(response: Response, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    response.headers["Cache-Control"] = "no-store"
    return list_candidate_evidence(db, user.id, audience="self")


@candidate_router.get("/roles", response_model=RoleFeedOut)
def get_candidate_roles(response: Response, cursor: str | None = Query(default=None, max_length=512),
                        limit: int = Query(default=5, ge=1, le=20),
                        specialization: str | None = None,
                        grade: str | None = None,
                        work_format: Literal["remote", "hybrid", "office"] | None = None,
                        saved_only: bool = False,
                        user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    response.headers["Cache-Control"] = "no-store"
    categories = available_categories()
    if specialization and not any(category.specialization == specialization for category in categories):
        raise HTTPException(status_code=422, detail="UNSUPPORTED_CATEGORY")
    if grade and grade not in {category.grade for category in categories}:
        raise HTTPException(status_code=422, detail="UNSUPPORTED_GRADE")
    if specialization and grade and get_category(specialization, grade) is None:
        raise HTTPException(status_code=422, detail="UNSUPPORTED_CATEGORY")
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
            data.expected_preferences_version, now(), data.source_campaign_id,
        )
        db.commit()
        return result
    except RoleDiscoveryError as exc:
        db.rollback()
        _raise_role_error(exc)
    except IntegrityError as exc:
        db.rollback()
        _raise_role_error(RoleDiscoveryError("ROLE_DECISION_CONFLICT", 409))


@candidate_router.post("/promotions/{campaign_id}/impression", response_model=SponsoredImpressionOut,
                       dependencies=[Depends(csrf_guard)])
def post_sponsored_impression(campaign_id: str, user: User = Depends(get_user),
                              db: Session = Depends(get_db)):
    require(user, "candidate")
    try:
        record_sponsored_impression(db, user.id, campaign_id, now())
        db.commit()
        return {"recorded": True}
    except RoleDiscoveryError as exc:
        db.rollback()
        _raise_role_error(exc)


@router.get("/{need_id}/role-card", response_model=RoleCardOut)
def get_role_card(need_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    need = _owned_need(db, user, need_id)
    return role_card_data(db, need, now())


def _demo_promotion_out(campaign) -> dict:
    return {
        "id": campaign.id,
        "need_id": campaign.need_id,
        "role_version_id": campaign.role_version_id,
        "active_from": campaign.active_from,
        "active_until": campaign.active_until,
        "demo_only": True,
        "revenue_rub": 0,
    }


@router.get("/{need_id}/promotion/demo", response_model=DemoPromotionOut | None)
def get_demo_role_promotion(need_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        campaign = get_demo_campaign(db, user.id, need_id, now())
        return _demo_promotion_out(campaign) if campaign else None
    except PromotionError as exc:
        _raise_role_error(exc)


@router.post("/{need_id}/promotion/demo", response_model=DemoPromotionOut, status_code=201,
             dependencies=[Depends(csrf_guard)])
def post_demo_role_promotion(need_id: str, response: Response,
                             user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        campaign, created = activate_demo_campaign(db, user.id, need_id, now())
        db.commit()
        if not created:
            response.status_code = 200
        return _demo_promotion_out(campaign)
    except PromotionError as exc:
        db.rollback()
        _raise_role_error(exc)


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
