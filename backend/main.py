"""FSP Signal API. Business decisions remain on the server."""

from datetime import timedelta
from contextlib import asynccontextmanager
import hashlib
import json
import secrets

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .assessment import BLUEPRINT_VERSION, COMPETENCIES, grade_attempt, make_assessment, public_questions
from .config import settings
from .db import Base, get_db
from .matching import (can_search, eligible, evaluate_compatibility, fsp_bonus,
                       public_candidate, score_profile, suggest_competencies)
from .models import (AssessmentAttempt, CandidateProfile, ContactGrant, EmailToken, EmployerProfile,
                     HiringNeed, Invitation, LoginSession, MailOutbox, RoleVersion,
                     SearchSnapshot, User, now)
from .passport import render_passport
from .preferences import formats_from_legacy, is_blocked, preferences_data
from .resume_import import MAX_PDF_BYTES, ResumeImportError, preview_pdf
from .role_cards import create_initial_draft
from .routes_v2 import candidate_router, router as v2_router
from .schemas import (AnswersIn, CandidateIn, EmployerIn, FspLinkIn, InvitationIn, LoginIn,
                      NeedIn, RegisterIn, SearchIn, StartAssessmentIn, VerifyIn)
from .security import aware, check_password, csrf_guard, digest, get_user, hasher, new_session, require, set_auth_cookies

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="ФСП Сигнал", version="0.1.0", description="Демонстрационный API обратного найма",
              docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.include_router(v2_router)
app.include_router(candidate_router)


def problem(code: str, status: int = 422) -> None:
    raise HTTPException(status_code=status, detail=code)


def profile_for(db: Session, user: User) -> CandidateProfile:
    profile = db.get(CandidateProfile, user.id)
    if not profile:
        problem("PROFILE_REQUIRED", 409)
    return profile


def employer_for(db: Session, user: User) -> EmployerProfile:
    employer = db.get(EmployerProfile, user.id)
    if not employer or not employer.company_name:
        problem("COMPANY_PROFILE_REQUIRED", 409)
    return employer


def candidate_private(profile: CandidateProfile) -> dict:
    return {
        "id": profile.user_id, "full_name": profile.full_name,
        "contact_email": profile.contact_email, "contact_phone": profile.contact_phone,
        "city": profile.city, "summary": profile.summary, "skills": profile.skills or [],
        "experience_months": profile.experience_months,
        "desired_specialization": profile.desired_specialization, "claimed_grade": profile.claimed_grade,
        "verified_specialization": profile.verified_specialization, "verified_grade": profile.verified_grade,
        "test_score": profile.test_score, "competencies": profile.competencies or {},
        "verification_source": profile.verification_source,
        "published": bool(profile.published_at), "consent_processing": bool(profile.consent_processing_at),
        "available": profile.available, "min_salary_rub": profile.min_salary_rub,
        "preferences_version": profile.preferences_version,
        "adult_hiring_confirmed": bool(profile.adult_attested_at),
        "work_format": profile.work_format, "fsp_id": profile.fsp_id,
        "fsp_status": profile.fsp_status, "fsp_result": profile.fsp_result,
        "next_grade_change_at": (aware(profile.grade_changed_at)+timedelta(days=30)).isoformat()
        if profile.grade_changed_at else None,
    }


def invitation_data(invite: Invitation) -> dict:
    return {"id": invite.id, "candidate_id": invite.candidate_id, "company_name": invite.company_name,
            "employer_id": invite.employer_id, "need_id": invite.need_id,
            "offer_text": invite.offer_text, "reason": invite.reason,
            "employer_contact": invite.employer_contact,
            "salary_min_rub": invite.salary_min_rub, "salary_max_rub": invite.salary_max_rub,
            "salary_period": "month", "salary_basis": "gross", "work_format": invite.work_format,
            "state": "expired" if invite.state in ("sent", "viewed") and aware(invite.expires_at) <= now() else invite.state,
            "created_at": invite.created_at.isoformat(),
            "expires_at": invite.expires_at.isoformat()}


def invitation_compatibility(db: Session, profile: CandidateProfile | None, invite: Invitation):
    role_payload = {}
    if invite.role_version_id:
        version = db.get(RoleVersion, invite.role_version_id)
        if version and (not invite.need_id or version.need_id == invite.need_id):
            role_payload = version.payload or {}
    return evaluate_compatibility(
        profile, role_payload, mode="invitation",
        offer_terms={"salary_min_rub": invite.salary_min_rub,
                     "salary_max_rub": invite.salary_max_rub,
                     "work_format": invite.work_format},
        role_version_id=invite.role_version_id,
    )


def candidate_invitation_data(db: Session, profile: CandidateProfile | None,
                              invite: Invitation) -> dict:
    compatibility = invitation_compatibility(db, profile, invite)
    return invitation_data(invite) | {"compatibility": compatibility.model_dump(mode="json")}


def attempt_data(attempt: AssessmentAttempt, include_answers: bool = False) -> dict:
    data = {"id": attempt.id, "specialization": attempt.specialization, "grade": attempt.grade,
            "blueprint_version": attempt.blueprint_version, "phase": attempt.phase, "state": attempt.state,
            "questions": public_questions(attempt.questions, attempt.phase),
            "answers": attempt.answers if include_answers else {}, "score": attempt.score,
            "outcome": attempt.outcome, "expires_at": attempt.expires_at.isoformat()}
    return data


def get_attempt(db: Session, user: User, attempt_id: str) -> AssessmentAttempt:
    attempt = db.get(AssessmentAttempt, attempt_id)
    if not attempt or attempt.candidate_id != user.id:
        problem("NOT_FOUND", 404)
    return attempt


def get_invitation(db: Session, user: User, invitation_id: str) -> Invitation:
    invitation = db.get(Invitation, invitation_id)
    if not invitation or user.id not in (invitation.candidate_id, invitation.employer_id):
        problem("NOT_FOUND", 404)
    return invitation


@app.get("/api/v1/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
def ready(db: Session = Depends(get_db)):
    try:
        existing = set(inspect(db.get_bind()).get_table_names())
    except SQLAlchemyError:
        problem("DATABASE_NOT_READY", 503)
    if set(Base.metadata.tables) - existing:
        problem("SCHEMA_NOT_READY", 503)
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/v1/auth/register", status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if "@" not in email or email.startswith("@") or "." not in email.split("@")[-1]:
        problem("INVALID_EMAIL")
    if data.role not in ("candidate", "employer"):
        problem("INVALID_ROLE")
    if db.scalar(select(User).where(User.email == email)):
        problem("EMAIL_ALREADY_USED", 409)
    user = User(email=email, password_hash=hasher.hash(data.password), role=data.role,
                origin="direct_signup")
    db.add(user)
    db.flush()
    raw = secrets.token_urlsafe(36)
    db.add(EmailToken(user_id=user.id, token_hash=digest(raw), expires_at=now()+timedelta(minutes=30)))
    link = f"{settings.public_base_url}/verify?token={raw}"
    db.add(MailOutbox(recipient=email, subject="Подтвердите адрес — ФСП Сигнал",
                      body=f"Перейдите по ссылке в течение 30 минут: {link}"))
    db.commit()
    return {"id": user.id, "email": email, "role": user.role, "email_verification": "queued"}


@app.post("/api/v1/auth/verify-email")
def verify_email(data: VerifyIn, db: Session = Depends(get_db)):
    record = db.scalar(select(EmailToken).where(EmailToken.token_hash == digest(data.token)))
    if not record or record.used_at or aware(record.expires_at) <= now():
        problem("INVALID_OR_EXPIRED_TOKEN", 409)
    user = db.get(User, record.user_id)
    record.used_at = now()
    user.email_verified_at = now()
    db.commit()
    return {"status": "verified"}


@app.post("/api/v1/auth/login")
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if not user or not check_password(data.password, user.password_hash):
        problem("INVALID_CREDENTIALS", 401)
    if not user.email_verified_at:
        problem("EMAIL_NOT_VERIFIED", 403)
    token = new_session(db, user)
    set_auth_cookies(response, token)
    return {"id": user.id, "role": user.role, "email": user.email}


@app.post("/api/v1/auth/logout", dependencies=[Depends(csrf_guard)])
def logout(response: Response, request: Request, user: User = Depends(get_user), db: Session = Depends(get_db)):
    current = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(request.cookies["fsp_session"])))
    if current:
        current.revoked_at = now()
        db.commit()
    response.delete_cookie("fsp_session", path="/")
    response.delete_cookie("fsp_csrf", path="/")
    return {"status": "logged_out"}


@app.get("/api/v1/me")
def me(user: User = Depends(get_user)):
    return {"id": user.id, "email": user.email, "role": user.role,
            "email_verified": bool(user.email_verified_at)}


@app.put("/api/v1/candidate/profile", dependencies=[Depends(csrf_guard)])
def save_candidate(data: CandidateIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    if data.published and not data.consent_processing:
        problem("CONSENT_REQUIRED")
    if data.work_format not in ("remote", "hybrid", "office", "any"):
        problem("INVALID_WORK_FORMAT")
    profile = db.get(CandidateProfile, user.id)
    created = profile is None
    profile = profile or CandidateProfile(user_id=user.id, preferences_version=1)
    prior_preferences = preferences_data(profile)
    for field in ("full_name", "contact_email", "contact_phone", "city", "summary", "skills",
                  "experience_months", "min_salary_rub", "work_format", "available"):
        setattr(profile, field, getattr(data, field))
    profile.consent_processing_at = profile.consent_processing_at or now() if data.consent_processing else None
    profile.published_at = profile.published_at or now() if data.published else None
    if data.adult_hiring_confirmed is not None:
        profile.adult_attested_at = (profile.adult_attested_at or now()) if data.adult_hiring_confirmed else None
    formats = formats_from_legacy(data.work_format)
    if created or (
        prior_preferences["salary_min_rub"] != (data.min_salary_rub or None)
        or prior_preferences["allowed_work_formats"] != formats
        or prior_preferences["available"] != data.available
    ):
        preference_fields = (
            "salary_min_rub", "allowed_work_formats", "allowed_cities", "excluded_industries",
            "preferred_stack", "preferred_tasks", "max_take_home_minutes", "available",
        )
        existing_preferences = profile.preferences or {}
        preferences = {field: existing_preferences.get(field, prior_preferences[field])
                       for field in preference_fields}
        preferences.update({
            "salary_min_rub": data.min_salary_rub or None,
            "allowed_work_formats": formats,
            "available": data.available,
        })
        profile.preferences = preferences
        profile.preferences_version = max(1, profile.preferences_version) + (0 if created else 1)
        profile.preferences_confirmed_at = now()
    db.add(profile)
    db.commit()
    return candidate_private(profile)


@app.get("/api/v1/candidate/profile")
def candidate_profile(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = db.get(CandidateProfile, user.id)
    return candidate_private(profile) if profile else None


@app.post("/api/v1/candidate/resume/preview", dependencies=[Depends(csrf_guard)])
async def preview_resume(file: UploadFile = File(...), user: User = Depends(get_user)):
    require(user, "candidate")
    if file.content_type != "application/pdf":
        problem("NOT_A_PDF")
    content = await file.read(MAX_PDF_BYTES + 1)
    await file.close()
    try:
        return preview_pdf(content)
    except ResumeImportError as exc:
        problem(str(exc))


@app.post("/api/v1/candidate/fsp-link", dependencies=[Depends(csrf_guard)])
def fsp_link(data: FspLinkIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = profile_for(db, user)
    profile.fsp_id = data.participant_id
    if settings.app_mode == "demo" and settings.fsp_provider == "mock" and data.participant_id == f"demo-{user.id}":
        profile.fsp_status, profile.fsp_result = "mock", "finalist"
    else:
        profile.fsp_status, profile.fsp_result = "unverified", None
    db.commit()
    return {"fsp_id": profile.fsp_id, "status": profile.fsp_status,
            "result": profile.fsp_result, "demo_expected_id": f"demo-{user.id}" if settings.app_mode == "demo" else None}


@app.delete("/api/v1/candidate/fsp-link", dependencies=[Depends(csrf_guard)])
def unlink_fsp(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = profile_for(db, user)
    profile.fsp_id, profile.fsp_status, profile.fsp_result = None, "unlinked", None
    db.commit()
    return {"status": "unlinked"}


@app.post("/api/v1/candidate/assessment-attempts", dependencies=[Depends(csrf_guard)], status_code=201)
def start_assessment(data: StartAssessmentIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = profile_for(db, user)
    if data.industry != "it":
        problem("UNSUPPORTED_INDUSTRY")
    key = f"{data.specialization}:{data.grade}"
    if key not in COMPETENCIES:
        problem("UNSUPPORTED_CATEGORY")
    recent = db.scalars(select(AssessmentAttempt).where(
        AssessmentAttempt.candidate_id == user.id,
        AssessmentAttempt.started_at >= now()-timedelta(days=7)).order_by(AssessmentAttempt.started_at.desc())).all()
    if len(recent) >= 3:
        problem("ASSESSMENT_ATTEMPT_LIMIT", 429)
    if any(a.state == "in_progress" and aware(a.expires_at) > now() for a in recent):
        problem("ASSESSMENT_ALREADY_IN_PROGRESS", 409)
    if profile.verified_grade and (profile.verified_specialization, profile.verified_grade) != (data.specialization, data.grade):
        if profile.grade_changed_at and aware(profile.grade_changed_at)+timedelta(days=30) > now():
            problem("GRADE_CHANGE_COOLDOWN", 409)
    same = [a for a in recent if (a.specialization, a.grade) == (data.specialization, data.grade)]
    if same and aware(same[0].started_at)+timedelta(hours=72) > now():
        problem("ASSESSMENT_RETRY_COOLDOWN", 409)
    seed = secrets.token_hex(16)
    questions, key_answers = make_assessment(data.specialization, data.grade, seed)
    attempt = AssessmentAttempt(candidate_id=user.id, specialization=data.specialization, grade=data.grade,
                                blueprint_version=BLUEPRINT_VERSION, seed=seed, questions=questions, answer_key=key_answers,
                                answers={}, expires_at=now()+timedelta(minutes=20))
    profile.desired_specialization, profile.claimed_grade = data.specialization, data.grade
    db.add(attempt)
    db.commit()
    return attempt_data(attempt)


@app.get("/api/v1/candidate/assessment-attempts/{attempt_id}")
def read_assessment(attempt_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    return attempt_data(get_attempt(db, user, attempt_id), include_answers=True)


@app.put("/api/v1/candidate/assessment-attempts/{attempt_id}/answers", dependencies=[Depends(csrf_guard)])
def save_answers(attempt_id: str, data: AnswersIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    attempt = get_attempt(db, user, attempt_id)
    if attempt.state != "in_progress" or aware(attempt.expires_at) <= now():
        problem("ASSESSMENT_CLOSED", 409)
    editable = {q["id"] for q in attempt.questions if q["phase"] == attempt.phase}
    if not set(data.answers).issubset(editable):
        problem("QUESTION_NOT_EDITABLE", 409)
    merged = dict(attempt.answers or {})
    merged.update(data.answers)
    attempt.answers = merged
    db.commit()
    return attempt_data(attempt, include_answers=True)


@app.post("/api/v1/candidate/assessment-attempts/{attempt_id}/advance", dependencies=[Depends(csrf_guard)])
def advance_assessment(attempt_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    attempt = get_attempt(db, user, attempt_id)
    if attempt.state != "in_progress" or aware(attempt.expires_at) <= now():
        problem("ASSESSMENT_CLOSED", 409)
    if attempt.phase != 1:
        problem("PHASE_ALREADY_ADVANCED", 409)
    needed = {q["id"] for q in attempt.questions if q["phase"] == 1}
    if not needed.issubset(attempt.answers or {}):
        problem("ANSWERS_INCOMPLETE", 409)
    attempt.phase = 2
    db.commit()
    return attempt_data(attempt, include_answers=True)


@app.post("/api/v1/candidate/assessment-attempts/{attempt_id}/submit", dependencies=[Depends(csrf_guard)])
def submit_assessment(attempt_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    attempt = get_attempt(db, user, attempt_id)
    if attempt.state == "scored":
        return attempt_data(attempt, include_answers=True)
    if attempt.state != "in_progress" or aware(attempt.expires_at) <= now():
        problem("ASSESSMENT_CLOSED", 409)
    if attempt.phase != 2 or not {q["id"] for q in attempt.questions}.issubset(attempt.answers or {}):
        problem("ANSWERS_INCOMPLETE", 409)
    score, passed, competencies, groups = grade_attempt(attempt.questions, attempt.answer_key, attempt.answers)
    attempt.score, attempt.outcome, attempt.state, attempt.submitted_at = score, "passed" if passed else "failed", "scored", now()
    profile = profile_for(db, user)
    if passed:
        changing = (profile.verified_specialization, profile.verified_grade) != (attempt.specialization, attempt.grade)
        if changing and profile.grade_changed_at and aware(profile.grade_changed_at)+timedelta(days=30) > now():
            problem("GRADE_CHANGE_COOLDOWN", 409)
        profile.verified_specialization, profile.verified_grade = attempt.specialization, attempt.grade
        profile.test_score, profile.competencies, profile.test_verified_at = score, competencies, now()
        profile.verification_source = "assessment"
        if changing:
            profile.grade_changed_at = now()
    db.commit()
    result = attempt_data(attempt, include_answers=True)
    result["group_scores"] = groups
    result["verified_category"] = f"{profile.verified_specialization}:{profile.verified_grade}" if profile.verified_grade else None
    return result


@app.get("/api/v1/candidate/assessment-history")
def assessment_history(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    attempts = db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.candidate_id == user.id)
                          .order_by(AssessmentAttempt.started_at.desc())).all()
    return [{"id": a.id, "category": f"{a.specialization}:{a.grade}", "state": a.state,
             "outcome": a.outcome, "score": a.score, "started_at": a.started_at.isoformat()} for a in attempts]


@app.put("/api/v1/employer/company", dependencies=[Depends(csrf_guard)])
def save_employer(data: EmployerIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    employer = db.get(EmployerProfile, user.id) or EmployerProfile(user_id=user.id)
    for field in ("company_name", "description", "industry", "contact_email"):
        setattr(employer, field, getattr(data, field))
    db.add(employer)
    db.commit()
    return {"company_name": employer.company_name, "description": employer.description,
            "industry": employer.industry, "contact_email": employer.contact_email}


@app.get("/api/v1/employer/company")
def employer_profile(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    p = db.get(EmployerProfile, user.id)
    return {"company_name": p.company_name, "description": p.description,
            "industry": p.industry, "contact_email": p.contact_email} if p else None


@app.post("/api/v1/employer/needs/parse", dependencies=[Depends(csrf_guard)])
def parse_need(data: NeedIn, user: User = Depends(get_user)):
    require(user, "employer")
    return {"suggested_competencies": suggest_competencies(data.description, data.specialization, data.grade),
            "requires_confirmation": True}


@app.post("/api/v1/employer/needs", dependencies=[Depends(csrf_guard)], status_code=201)
def create_need(data: NeedIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    employer_for(db, user)
    if f"{data.specialization}:{data.grade}" not in COMPETENCIES:
        problem("UNSUPPORTED_CATEGORY")
    if data.salary_max_rub < data.salary_min_rub:
        problem("SALARY_RANGE_INVALID")
    if data.work_format not in ("remote", "hybrid", "office", "any"):
        problem("INVALID_WORK_FORMAT")
    allowed = set(COMPETENCIES[f"{data.specialization}:{data.grade}"])
    if not set(data.competencies).issubset(allowed):
        problem("INVALID_COMPETENCY")
    need = HiringNeed(employer_id=user.id, **data.model_dump())
    db.add(need)
    db.flush()
    create_initial_draft(db, need, actor_id=user.id)
    db.commit()
    return {"id": need.id, **data.model_dump()}


@app.get("/api/v1/employer/needs")
def list_needs(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    needs = db.scalars(select(HiringNeed).where(HiringNeed.employer_id == user.id).order_by(HiringNeed.created_at.desc())).all()
    return [{"id": n.id, "title": n.title, "description": n.description,
             "specialization": n.specialization, "grade": n.grade,
             "competencies": n.competencies, "salary_min_rub": n.salary_min_rub,
             "salary_max_rub": n.salary_max_rub, "work_format": n.work_format} for n in needs]


@app.get("/api/v1/employer/categories")
def categories(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    profiles = db.scalars(select(CandidateProfile)).all()
    return [{"specialization": spec, "grade": grade,
             "count": sum(can_search(p) and (p.verified_specialization, p.verified_grade) == (spec, grade) for p in profiles)}
            for spec in ("backend", "frontend") for grade in ("junior", "middle")]


@app.get("/api/v1/employer/candidates")
def bank_candidates(specialization: str | None = None, grade: str | None = None, stack: str | None = None,
                    fsp_only: bool = False, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    profiles = db.scalars(select(CandidateProfile)).all()
    selected = [p for p in profiles if can_search(p) and not is_blocked(p, user.id) and
                (not specialization or p.verified_specialization == specialization) and
                (not grade or p.verified_grade == grade) and
                (not stack or stack.lower() in {x.lower() for x in (p.skills or [])}) and
                (not fsp_only or bool(fsp_bonus(p)))]
    selected.sort(key=lambda p: (p.verified_specialization, p.verified_grade,
                                 -(90*(p.test_score or 0)/100 + 10*fsp_bonus(p)), p.user_id))
    return [public_candidate(p) | {"bank_score": round(90*(p.test_score or 0)/100 + 10*fsp_bonus(p), 1)}
            for p in selected[:50]]


@app.post("/api/v1/employer/searches", dependencies=[Depends(csrf_guard)], status_code=201)
def search_candidates(data: SearchIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    need = db.get(HiringNeed, data.need_id)
    if not need or need.employer_id != user.id:
        problem("NOT_FOUND", 404)
    if data.parent_snapshot_id:
        parent = db.get(SearchSnapshot, data.parent_snapshot_id)
        if not parent or parent.employer_id != user.id or parent.need_id != need.id:
            problem("NOT_FOUND", 404)
    profiles = db.scalars(select(CandidateProfile)).all()
    scored = [(p, score_profile(p, need)) for p in profiles
              if not is_blocked(p, user.id) and eligible(p, need, data.fsp_only, data.stack)]
    scored.sort(key=lambda item: (-item[1]["score"], -(item[0].test_score or 0), item[0].user_id))
    rows = [{"candidate_id": p.user_id, "match": result} for p, result in scored[:50]]
    snapshot = SearchSnapshot(employer_id=user.id, need_id=need.id, parent_id=data.parent_snapshot_id,
                              filters={"fsp_only": data.fsp_only, "stack": data.stack}, results=rows)
    db.add(snapshot)
    db.commit()
    return render_snapshot(db, snapshot)


def render_snapshot(db: Session, snapshot: SearchSnapshot) -> dict:
    need = db.get(HiringNeed, snapshot.need_id)
    results = []
    for row in snapshot.results:
        candidate = db.get(CandidateProfile, row["candidate_id"])
        if (candidate and not is_blocked(candidate, snapshot.employer_id)
                and eligible(candidate, need, snapshot.filters.get("fsp_only", False), snapshot.filters.get("stack", []))):
            results.append(public_candidate(candidate, row["match"]))
    return {"id": snapshot.id, "need_id": snapshot.need_id, "parent_snapshot_id": snapshot.parent_id,
            "algorithm_version": snapshot.algorithm_version, "created_at": snapshot.created_at.isoformat(),
            "filters": snapshot.filters, "results": results,
            "unavailable_count": len(snapshot.results)-len(results)}


@app.get("/api/v1/employer/searches")
def list_searches(need_id: str | None = None, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    if need_id:
        need = db.get(HiringNeed, need_id)
        if not need or need.employer_id != user.id:
            problem("NOT_FOUND", 404)
    query = select(SearchSnapshot).where(SearchSnapshot.employer_id == user.id)
    if need_id:
        query = query.where(SearchSnapshot.need_id == need_id)
    snapshots = db.scalars(query.order_by(SearchSnapshot.created_at.desc(), SearchSnapshot.id.desc()).limit(30)).all()
    return [{"id": item.id, "need_id": item.need_id, "parent_snapshot_id": item.parent_id,
             "algorithm_version": item.algorithm_version, "created_at": item.created_at.isoformat(),
             "filters": item.filters, "result_count": len(item.results or [])}
            for item in snapshots]


@app.get("/api/v1/employer/searches/{snapshot_id}")
def read_snapshot(snapshot_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    snapshot = db.get(SearchSnapshot, snapshot_id)
    if not snapshot or snapshot.employer_id != user.id:
        problem("NOT_FOUND", 404)
    return render_snapshot(db, snapshot)


@app.get("/api/v1/employer/candidates/{candidate_id}")
def candidate_card(candidate_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    profile = db.get(CandidateProfile, candidate_id)
    if not profile or not can_search(profile) or is_blocked(profile, user.id):
        problem("NOT_FOUND", 404)
    return public_candidate(profile)


@app.get("/api/v1/employer/candidates/{candidate_id}/contact")
def candidate_contact(candidate_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    profile = db.get(CandidateProfile, candidate_id)
    if not profile or is_blocked(profile, user.id):
        problem("CONTACT_LOCKED", 403)
    grant = db.scalar(select(ContactGrant).join(
        Invitation, Invitation.id == ContactGrant.invitation_id
    ).where(ContactGrant.candidate_id == candidate_id,
             ContactGrant.employer_id == user.id,
             ContactGrant.revoked_at.is_(None), Invitation.state == "accepted").limit(1))
    if not grant:
        problem("CONTACT_LOCKED", 403)
    return Response(content=json.dumps({"full_name": profile.full_name, "email": profile.contact_email,
                                        "phone": profile.contact_phone}, ensure_ascii=False),
                    media_type="application/json", headers={"Cache-Control": "no-store"})


@app.post("/api/v1/employer/invitations", dependencies=[Depends(csrf_guard)], status_code=201)
def create_invitation(data: InvitationIn, idempotency_key: str = Header(min_length=8, max_length=100),
                      user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    employer = employer_for(db, user)
    fingerprint = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    existing = db.scalar(select(Invitation).where(Invitation.employer_id == user.id,
                                                   Invitation.idempotency_key == idempotency_key))
    if existing:
        if existing.request_hash != fingerprint:
            problem("IDEMPOTENCY_KEY_REUSED", 409)
        return invitation_data(existing)
    candidate = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == data.candidate_id
    ).with_for_update())
    if not candidate or not can_search(candidate):
        problem("NOT_FOUND", 404)
    if is_blocked(candidate, user.id):
        problem("COMPANY_BLOCKED", 409)
    if data.salary_max_rub < data.salary_min_rub:
        problem("SALARY_RANGE_INVALID")
    need = db.get(HiringNeed, data.need_id) if data.need_id else None
    if data.need_id and (not need or need.employer_id != user.id):
        problem("NOT_FOUND", 404)
    if need and (candidate.verified_specialization, candidate.verified_grade) != (need.specialization, need.grade):
        problem("CATEGORY_MISMATCH")
    active = db.scalar(select(Invitation).where(Invitation.employer_id == user.id,
                                                Invitation.candidate_id == data.candidate_id,
                                                Invitation.state.in_(["sent", "viewed"])))
    if active and aware(active.expires_at) > now():
        problem("ACTIVE_INVITATION_EXISTS", 409)
    invite = Invitation(employer_id=user.id, candidate_id=data.candidate_id, need_id=data.need_id,
                        company_name=employer.company_name, offer_text=data.offer_text, reason=data.reason,
                        employer_contact=data.employer_contact, salary_min_rub=data.salary_min_rub,
                        salary_max_rub=data.salary_max_rub, work_format=data.work_format,
                        idempotency_key=idempotency_key, request_hash=fingerprint,
                        expires_at=now()+timedelta(days=7))
    db.add(invite)
    db.flush()
    recipient = db.get(User, candidate.user_id)
    db.add(MailOutbox(recipient=recipient.email, subject="Новое приглашение — ФСП Сигнал",
                      body=f"Компания {employer.company_name} прислала предложение. Откройте кабинет: {settings.public_base_url}"))
    db.commit()
    return invitation_data(invite)


@app.get("/api/v1/employer/invitations")
def sent_invitations(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    invitations = db.scalars(select(Invitation).where(Invitation.employer_id == user.id)
                             .order_by(Invitation.created_at.desc())).all()
    return [invitation_data(x) for x in invitations]


@app.get("/api/v1/candidate/invitations")
def received_invitations(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = db.get(CandidateProfile, user.id)
    invitations = db.scalars(select(Invitation).where(Invitation.candidate_id == user.id)
                             .order_by(Invitation.created_at.desc())).all()
    return [candidate_invitation_data(db, profile, x) for x in invitations]


@app.post("/api/v1/invitations/{invitation_id}/view", dependencies=[Depends(csrf_guard)])
def view_invitation(invitation_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    invite = get_invitation(db, user, invitation_id)
    if invite.candidate_id != user.id:
        problem("NOT_FOUND", 404)
    if invite.state == "sent" and aware(invite.expires_at) > now():
        invite.state = "viewed"
        db.commit()
    return invitation_data(invite)


@app.post("/api/v1/invitations/{invitation_id}/accept", dependencies=[Depends(csrf_guard)])
def accept_invitation(invitation_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    invite = get_invitation(db, user, invitation_id)
    if invite.candidate_id != user.id:
        problem("NOT_FOUND", 404)
    if invite.state == "accepted":
        return invitation_data(invite)
    candidate = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == user.id
    ).with_for_update())
    if not candidate or is_blocked(candidate, invite.employer_id):
        problem("COMPANY_BLOCKED", 409)
    if not can_search(candidate):
        problem("INVITATION_NOT_AVAILABLE", 409)
    if invitation_compatibility(db, candidate, invite).status == "incompatible":
        problem("INVITATION_NOT_COMPATIBLE", 409)
    if invite.state not in ("sent", "viewed") or aware(invite.expires_at) <= now():
        problem("INVITATION_STATE_CONFLICT", 409)
    changed = db.execute(update(Invitation).where(Invitation.id == invite.id,
                                                  Invitation.state.in_(["sent", "viewed"]),
                                                  Invitation.expires_at > now())
                         .values(state="accepted", decided_at=now()).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        problem("INVITATION_STATE_CONFLICT", 409)
    db.add(ContactGrant(invitation_id=invite.id, employer_id=invite.employer_id, candidate_id=invite.candidate_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        problem("INVITATION_STATE_CONFLICT", 409)
    db.refresh(invite)
    return invitation_data(invite)


@app.post("/api/v1/invitations/{invitation_id}/reject", dependencies=[Depends(csrf_guard)])
def reject_invitation(invitation_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    invite = get_invitation(db, user, invitation_id)
    if invite.candidate_id != user.id or invite.state not in ("sent", "viewed") or aware(invite.expires_at) <= now():
        problem("INVITATION_STATE_CONFLICT", 409)
    invite.state, invite.decided_at = "rejected", now()
    db.commit()
    return invitation_data(invite)


@app.post("/api/v1/invitations/{invitation_id}/withdraw", dependencies=[Depends(csrf_guard)])
def withdraw_invitation(invitation_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    invite = get_invitation(db, user, invitation_id)
    if invite.employer_id != user.id or invite.state not in ("sent", "viewed"):
        problem("INVITATION_STATE_CONFLICT", 409)
    invite.state, invite.decided_at = "withdrawn", now()
    db.commit()
    return invitation_data(invite)


@app.get("/api/v1/candidate/contact-grants")
def list_grants(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    grants = db.scalars(select(ContactGrant).where(ContactGrant.candidate_id == user.id)).all()
    return [{"id": g.id, "employer_id": g.employer_id, "invitation_id": g.invitation_id,
             "granted_at": g.granted_at.isoformat(), "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None}
            for g in grants]


@app.post("/api/v1/candidate/contact-grants/{grant_id}/revoke", dependencies=[Depends(csrf_guard)])
def revoke_grant(grant_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    grant = db.get(ContactGrant, grant_id)
    if not grant or grant.candidate_id != user.id:
        problem("NOT_FOUND", 404)
    if not grant.revoked_at:
        grant.revoked_at = now()
        db.commit()
    return {"id": grant.id, "status": "revoked"}


@app.get("/api/v1/candidate/passport.pdf")
def passport_pdf(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = profile_for(db, user)
    try:
        output = render_passport(profile)
    except FileNotFoundError:
        problem("PDF_FONT_UNAVAILABLE", 503)
    return StreamingResponse(output, media_type="application/pdf", headers={"Cache-Control": "no-store",
                                                                    "Content-Disposition": "attachment; filename=passport.pdf"})
