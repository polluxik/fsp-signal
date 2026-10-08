"""Owned role pipeline counts and private shortlist; no candidate decisions leak."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .matching import eligible, public_candidate, score_profile_v2
from .models import (CandidateProfile, EmployerShortlistEntry, HiringNeed, InterviewMeeting,
                     Invitation, RoleVersion, SearchSnapshot, User, now)
from .preferences import is_blocked
from .product_events import product_event_data_mode
from .role_cards import is_role_fresh
from .schemas import FspAchievementOut, MatchResult, RoleCardIn
from .security import aware, csrf_guard, get_user, require

router = APIRouter(prefix="/api/v1/employer/needs", tags=["Employer pipeline"])


class ShortlistCommand(BaseModel):
    role_version_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=0)
    saved: bool


class ShortlistState(BaseModel):
    candidate_id: str
    role_version_id: str
    saved: bool
    version: int


class ShortlistCandidate(BaseModel):
    id: str
    alias: str
    specialization: str
    grade: str
    test_score: int
    competencies: dict[str, float]
    verification_source: str
    assessed_at: datetime | None
    skills_declared: list[str]
    experience_months_declared: int
    work_format: str
    fsp_status: str
    fsp_result: str | None
    fsp_achievement: FspAchievementOut | None
    match: MatchResult


class ShortlistItem(ShortlistState):
    candidate: ShortlistCandidate


class PipelineVersion(BaseModel):
    id: str
    version: int
    title: str


class ShortlistOut(BaseModel):
    need_id: str
    role_version_id: str
    role_version: int
    current: bool
    versions: list[PipelineVersion]
    entries: list[ShortlistItem]
    unavailable_count: int


class FunnelCounts(BaseModel):
    matched: int = 0
    invited: int = 0
    accepted: int = 0
    scheduled: int = 0
    held: int = 0


class FunnelOut(BaseModel):
    need_id: str
    role_version_id: str
    role_version: int
    title: str
    current: bool
    versions: list[PipelineVersion]
    real: FunnelCounts
    synthetic: FunnelCounts
    invitation_states: dict[str, int]
    explanation: str


def _role(db, user, need_id, version_id=None, *, lock=False):
    query = select(HiringNeed).where(HiringNeed.id == need_id, HiringNeed.employer_id == user.id)
    need = db.scalar(query.with_for_update() if lock else query)
    if not need:
        raise HTTPException(404, "NOT_FOUND")
    query = select(RoleVersion).where(RoleVersion.need_id == need.id)
    query = query.where(RoleVersion.id == version_id) if version_id else query.where(RoleVersion.version == need.current_role_version)
    version = db.scalar(query)
    if not version:
        raise HTTPException(404, "NOT_FOUND")
    return need, version


def _card(version):
    # The initial, unpublished draft intentionally lacks complete role terms.
    try:
        return RoleCardIn.model_validate(version.payload)
    except ValidationError:
        return None


def _visible(profile, role, employer_id):
    return bool(role and profile and not is_blocked(profile, employer_id) and eligible(profile, role))


def _versions(db, need):
    return [PipelineVersion(id=version.id, version=version.version, title=version.payload.get("title", need.title))
            for version in db.scalars(select(RoleVersion).where(RoleVersion.need_id == need.id)
                                      .order_by(RoleVersion.version.desc()))]


@router.get("/{need_id}/shortlist", response_model=ShortlistOut)
def read_shortlist(need_id: str, role_version_id: str | None = Query(default=None),
                   user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    need, version = _role(db, user, need_id, role_version_id)
    role = _card(version)
    rows = db.scalars(select(EmployerShortlistEntry).where(
        EmployerShortlistEntry.employer_id == user.id, EmployerShortlistEntry.need_id == need.id,
        EmployerShortlistEntry.role_version_id == version.id).order_by(EmployerShortlistEntry.updated_at.desc())).all()
    profiles = {profile.user_id: profile for profile in db.scalars(select(CandidateProfile).where(
        CandidateProfile.user_id.in_([row.candidate_id for row in rows])))} if rows else {}
    entries, unavailable = [], 0
    for row in rows:
        profile = profiles.get(row.candidate_id)
        if not _visible(profile, role, user.id):
            unavailable += int(row.saved)
            continue
        entries.append(ShortlistItem(candidate_id=row.candidate_id, role_version_id=version.id,
            saved=row.saved, version=row.state_version,
            candidate=public_candidate(profile, score_profile_v2(profile, role).model_dump(mode="json"))))
    return ShortlistOut(need_id=need.id, role_version_id=version.id, role_version=version.version,
        current=version.version == need.current_role_version, versions=_versions(db, need),
        entries=entries, unavailable_count=unavailable)


@router.put("/{need_id}/shortlist/{candidate_id}", response_model=ShortlistState, dependencies=[Depends(csrf_guard)])
def change_shortlist(need_id: str, candidate_id: str, data: ShortlistCommand,
                     user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    # Same lock order as invitations: candidate -> need -> private entry.
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == candidate_id).with_for_update())
    need, version = _role(db, user, need_id, data.role_version_id, lock=True)
    if data.saved:
        if version.version != need.current_role_version:
            raise HTTPException(409, "ROLE_VERSION_CONFLICT")
        if need.publication_state != "active":
            raise HTTPException(409, "ROLE_NOT_ACTIVE")
        if not is_role_fresh(need.confirmed_at, now()):
            raise HTTPException(409, "ROLE_STALE")
        role = _card(version)
        if not role:
            raise HTTPException(409, "ROLE_INCOMPLETE")
        if not _visible(profile, role, user.id):
            raise HTTPException(404, "NOT_FOUND")
    row = db.scalar(select(EmployerShortlistEntry).where(
        EmployerShortlistEntry.employer_id == user.id, EmployerShortlistEntry.need_id == need.id,
        EmployerShortlistEntry.role_version_id == version.id,
        EmployerShortlistEntry.candidate_id == candidate_id).with_for_update())
    if data.expected_version != (row.state_version if row else 0):
        raise HTTPException(409, "SHORTLIST_VERSION_CONFLICT")
    if not row and not data.saved:
        return ShortlistState(candidate_id=candidate_id, role_version_id=version.id, saved=False, version=0)
    try:
        if not row:
            row = EmployerShortlistEntry(employer_id=user.id, need_id=need.id,
                role_version_id=version.id, candidate_id=candidate_id, saved=True, state_version=1)
            db.add(row)
        elif row.saved != data.saved:
            changed = db.execute(update(EmployerShortlistEntry).where(
                EmployerShortlistEntry.id == row.id, EmployerShortlistEntry.state_version == data.expected_version)
                .values(saved=data.saved, state_version=data.expected_version + 1, updated_at=now())
                .execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                raise HTTPException(409, "SHORTLIST_VERSION_CONFLICT")
            db.refresh(row)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "SHORTLIST_VERSION_CONFLICT") from exc
    return ShortlistState(candidate_id=candidate_id, role_version_id=version.id,
                          saved=row.saved, version=row.state_version)


@router.get("/{need_id}/funnel", response_model=FunnelOut)
def role_funnel(need_id: str, role_version_id: str | None = Query(default=None),
                user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    need, version = _role(db, user, need_id, role_version_id)
    snapshots = db.scalars(select(SearchSnapshot).where(SearchSnapshot.employer_id == user.id,
        SearchSnapshot.need_id == need.id, SearchSnapshot.role_version_id == version.id)).all()
    invitations = db.scalars(select(Invitation).where(Invitation.employer_id == user.id,
        Invitation.need_id == need.id, Invitation.role_version_id == version.id)).all()
    matched = {row["candidate_id"] for snapshot in snapshots for row in (snapshot.results or [])}
    candidate_ids = matched | {invitation.candidate_id for invitation in invitations}
    users = {candidate.id: candidate for candidate in db.scalars(select(User).where(User.id.in_(candidate_ids)))} if candidate_ids else {}
    stages = {mode: {stage: set() for stage in FunnelCounts.model_fields} for mode in ("real", "synthetic")}
    def mode_for(candidate_id):
        return product_event_data_mode(settings.app_mode, user, users.get(candidate_id))
    for candidate_id in matched:
        stages[mode_for(candidate_id)]["matched"].add(candidate_id)
    by_id = {invitation.id: invitation for invitation in invitations}
    states = {}
    for invitation in invitations:
        bucket = stages[mode_for(invitation.candidate_id)]
        bucket["invited"].add(invitation.candidate_id)
        state = "expired" if invitation.state in ("sent", "viewed") and aware(invitation.expires_at) <= now() else invitation.state
        states[state] = states.get(state, 0) + 1
        if state == "accepted":
            bucket["accepted"].add(invitation.candidate_id)
            if invitation.candidate_interview_confirmed_at and invitation.employer_interview_confirmed_at:
                bucket["held"].add(invitation.candidate_id)
    meetings = db.scalars(select(InterviewMeeting).where(InterviewMeeting.employer_id == user.id,
        InterviewMeeting.invitation_id.in_(by_id), InterviewMeeting.state == "scheduled")).all() if by_id else []
    for meeting in meetings:
        invitation = by_id[meeting.invitation_id]
        if invitation.state == "accepted" and meeting.candidate_id == invitation.candidate_id:
            stages[mode_for(invitation.candidate_id)]["scheduled"].add(invitation.candidate_id)
    return FunnelOut(need_id=need.id, role_version_id=version.id, role_version=version.version,
        title=version.payload.get("title", need.title), current=version.version == need.current_role_version,
        versions=_versions(db, need),
        real=FunnelCounts(**{stage: len(ids) for stage, ids in stages["real"].items()}),
        synthetic=FunnelCounts(**{stage: len(ids) for stage, ids in stages["synthetic"].items()}),
        invitation_states=states,
        explanation="Каждая стадия считает уникальных кандидатов в этой версии роли; повторные подборки и приглашения не увеличивают её. Приглашения из банка могут быть вне подборок. Проведённая встреча требует подтверждения обеих сторон. Это активность сервиса, а не качество matching; контакты и решения кандидата в ленте не раскрываются.")
