"""FSP Signal API. Business decisions remain on the server."""

from datetime import timedelta
from contextlib import asynccontextmanager
import json
import secrets

from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .assessment import BLUEPRINT_VERSION, COMPETENCIES, grade_attempt, make_assessment, public_questions
from .config import settings
from .db import Base, get_db
from .evidence import (build_achievement_narrative, build_achievement_story_record,
                       list_candidate_evidence)
from .invitations import (InvitationError, confirm_interview_held,
                          create_invitation as create_invitation_record, transition_invitation)
from .matching import (can_search, eligible, evaluate_compatibility, explain_profile, fsp_bonus,
                       public_candidate, score_profile, score_profile_v2, suggest_competencies)
from .models import (AssessmentAttempt, CandidateProfile, ContactGrant, EmailToken, EmployerProfile,
                     HiringNeed, Invitation, LoginSession, MailOutbox, RoleVersion,
                     SearchSnapshot, User, now)
from .passport import render_passport
from .preferences import (PreferencesError, is_blocked, preferences_data,
                          save_profile_preferences)
from .resume_import import MAX_PDF_BYTES, ResumeImportError, preview_pdf
from .role_cards import create_initial_draft
from .routes_v2 import candidate_router, router as v2_router
from .schemas import (AcceptInvitationIn, AnswersIn, CandidateIn, EmployerIn, FspLinkIn,
                      InterviewHeldConfirmationOut, InvitationCommandIn, InvitationOut,
                      InvitationV2In, LoginIn, NeedIn, RegisterIn, RoleCardIn, SearchIn,
                      SearchOut, StartAssessmentIn, VerifyIn)
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
        "achievement_story": ({**(profile.achievement_story or {}),
                                "formatted_narrative": build_achievement_narrative(profile.achievement_story)}
                               if profile.achievement_story else None),
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
            "role_version_id": invite.role_version_id,
            "offer_text": invite.offer_text, "reason": invite.reason,
            "employer_contact": invite.employer_contact,
            "salary_min_rub": invite.salary_min_rub, "salary_max_rub": invite.salary_max_rub,
            "salary_period": "month", "salary_basis": "gross", "work_format": invite.work_format,
            "state": "expired" if invite.state in ("sent", "viewed") and aware(invite.expires_at) <= now() else invite.state,
            "created_at": invite.created_at.isoformat(),
            "expires_at": invite.expires_at.isoformat(),
            "terms_snapshot": invite.terms_snapshot, "terms_hash": invite.terms_hash,
            "evidence_refs": invite.evidence_refs or [],
            "explanation_snapshot": invite.explanation_snapshot,
            "state_version": invite.state_version,
            "response_due_at": invite.response_due_at.isoformat() if invite.response_due_at else None,
            "candidate_interview_confirmed": invite.candidate_interview_confirmed_at is not None,
            "employer_interview_confirmed": invite.employer_interview_confirmed_at is not None}


def invitation_compatibility(db: Session, profile: CandidateProfile | None, invite: Invitation):
    snapshot_role = (invite.terms_snapshot or {}).get("role")
    role_payload = snapshot_role if isinstance(snapshot_role, dict) else {}
    if not role_payload and invite.role_version_id:
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
    return invitation_data(invite) | {
        "compatibility": compatibility.model_dump(mode="json"),
        "compatibility_at_send": invite.compatibility_snapshot,
    }


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
    profile = db.scalar(select(CandidateProfile).where(
        CandidateProfile.user_id == user.id
    ).with_for_update())
    created = profile is None
    profile = profile or CandidateProfile(user_id=user.id, preferences_version=1)
    at = now()
    try:
        save_profile_preferences(profile, data, at, is_new=created)
    except PreferencesError as exc:
        return JSONResponse(
            status_code=exc.status,
            headers={"Cache-Control": "no-store"},
            content={"detail": exc.code, "current": {
                "profile": candidate_private(profile),
                "preferences": preferences_data(profile),
            }},
        )
    for field in ("full_name", "contact_email", "contact_phone", "city", "summary", "skills",
                  "experience_months"):
        setattr(profile, field, getattr(data, field))
    if "achievement_story" in data.model_fields_set:
        profile.achievement_story = (build_achievement_story_record(data.achievement_story)
                                     if data.achievement_story else {})
    profile.consent_processing_at = profile.consent_processing_at or now() if data.consent_processing else None
    profile.published_at = profile.published_at or now() if data.published else None
    if data.adult_hiring_confirmed is not None:
        profile.adult_attested_at = (profile.adult_attested_at or now()) if data.adult_hiring_confirmed else None
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
    for question in attempt.questions:
        if question["id"] not in data.answers or question.get("type") != "structured":
            continue
        submitted = data.answers[question["id"]]
        required_fields = {field["id"] for field in question.get("fields", [])}
        if (not isinstance(submitted, dict) or set(submitted) != required_fields
                or any(not isinstance(submitted[field], str) or not submitted[field].strip()
                       for field in required_fields)):
            problem("ANSWERS_INCOMPLETE", 409)
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
        profile.verified_attempt_id = attempt.id
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
    if not needs:
        return []
    versions = db.scalars(select(RoleVersion).where(
        RoleVersion.need_id.in_([need.id for need in needs])
    )).all()
    current_versions = {(version.need_id, version.version): version for version in versions}
    return [{"id": n.id, "title": n.title, "description": n.description,
             "specialization": n.specialization, "grade": n.grade,
             "competencies": n.competencies, "stack": n.stack or [],
             "role_version_id": (current_versions.get((n.id, n.current_role_version)).id
                                 if current_versions.get((n.id, n.current_role_version)) else None),
             "salary_min_rub": n.salary_min_rub,
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
    def bank_score(profile: CandidateProfile) -> float:
        if settings.match_algorithm_version == "match_v2":
            return float(profile.test_score or 0)
        return 90 * (profile.test_score or 0) / 100 + 10 * fsp_bonus(profile)

    selected.sort(key=lambda p: (p.verified_specialization, p.verified_grade,
                                 -bank_score(p), p.user_id))
    return [public_candidate(p) | {
        "bank_score": round(bank_score(p), 1),
        "bank_score_algorithm_version": settings.match_algorithm_version,
    }
            for p in selected[:50]]


def _current_role_version(db: Session, need: HiringNeed) -> RoleVersion | None:
    if need.current_role_version < 1:
        return None
    return db.scalar(select(RoleVersion).where(
        RoleVersion.need_id == need.id,
        RoleVersion.version == need.current_role_version,
    ))


def _search_role_data(need: HiringNeed, role_version: RoleVersion | None) -> dict:
    if role_version:
        return dict(role_version.payload or {})
    return {
        "title": need.title, "description": need.description,
        "specialization": need.specialization, "grade": need.grade,
        "competencies": need.competencies or [], "stack": need.stack or [],
        "salary_min_rub": need.salary_min_rub, "salary_max_rub": need.salary_max_rub,
        "work_format": need.work_format,
    }


def _assessment_snapshot_source(db: Session, profile: CandidateProfile) -> dict:
    source = {
        "type": profile.verification_source or ("legacy_aggregate" if profile.test_score is not None else "unknown"),
        "source_id": None,
        "source_version": "legacy-aggregate/v1" if profile.test_score is not None else None,
        "assessed_at": profile.test_verified_at.isoformat() if profile.test_verified_at else None,
    }
    if not profile.verified_attempt_id:
        return source
    attempt = db.get(AssessmentAttempt, profile.verified_attempt_id)
    if (not attempt or attempt.candidate_id != profile.user_id or attempt.state != "scored"
            or attempt.outcome != "passed"
            or (attempt.specialization, attempt.grade) !=
            (profile.verified_specialization, profile.verified_grade)):
        return source
    _, passed, _, _ = grade_attempt(attempt.questions or [], attempt.answer_key or {}, attempt.answers or {})
    if not passed:
        return source
    return {
        "type": "assessment_attempt", "source_id": attempt.id,
        "source_version": f"{attempt.blueprint_version}/fixed-rubric-v1",
        "assessed_at": attempt.submitted_at.isoformat() if attempt.submitted_at else source["assessed_at"],
    }


def _search_input_snapshot(db: Session, profile: CandidateProfile) -> dict:
    prefs = preferences_data(profile)
    return {
        "category": {
            "specialization": profile.verified_specialization,
            "grade": profile.verified_grade,
        },
        "test_score": profile.test_score,
        "competencies": dict(profile.competencies or {}),
        "assessment_source": _assessment_snapshot_source(db, profile),
        "preferences_version": prefs["version"],
    }


@app.post("/api/v1/employer/searches", dependencies=[Depends(csrf_guard)], status_code=201,
          response_model=SearchOut)
def search_candidates(data: SearchIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    need = db.get(HiringNeed, data.need_id)
    if not need or need.employer_id != user.id:
        problem("NOT_FOUND", 404)
    current_role = _current_role_version(db, need)
    if data.role_version_id:
        role_version = db.get(RoleVersion, data.role_version_id)
        if not role_version or role_version.need_id != need.id:
            problem("NOT_FOUND", 404)
        if not current_role or current_role.id != role_version.id:
            problem("ROLE_VERSION_CONFLICT", 409)
    else:
        role_version = current_role
    role_version_id = role_version.id if role_version else None
    if data.parent_snapshot_id:
        parent = db.get(SearchSnapshot, data.parent_snapshot_id)
        if not parent or parent.employer_id != user.id or parent.need_id != need.id:
            problem("NOT_FOUND", 404)
        if parent.role_version_id != role_version_id:
            problem("ROLE_VERSION_CONFLICT", 409)
    role_data = _search_role_data(need, role_version)
    try:
        role_card = RoleCardIn.model_validate(role_data)
    except ValidationError:
        role_card = None
    algorithm_version = settings.match_algorithm_version
    if algorithm_version == "match_v2" and role_card is None:
        problem("ROLE_CARD_INCOMPLETE", 409)
    profiles = db.scalars(select(CandidateProfile)).all()
    scored = []
    for profile in profiles:
        if is_blocked(profile, user.id) or not eligible(profile, role_data, data.fsp_only, data.stack):
            continue
        if algorithm_version == "match_v2":
            result = score_profile_v2(profile, role_card).model_dump(mode="json")
            if result["score"] is None:
                continue
        else:
            result = score_profile(profile, need)
            result["explanation"] = explain_profile(profile, role_data).model_dump(mode="json")
        scored.append((profile, result))
    scored.sort(key=lambda item: (item[1]["score"] is None, -(item[1]["score"] or 0),
                                  -(item[0].test_score or 0), item[0].user_id))
    rows = [{"candidate_id": profile.user_id, "match": result,
             "snapshot_inputs": _search_input_snapshot(db, profile)}
            for profile, result in scored[:50]]
    snapshot = SearchSnapshot(employer_id=user.id, need_id=need.id, parent_id=data.parent_snapshot_id,
                              role_version_id=role_version_id,
                              algorithm_version=algorithm_version,
                              filters={"fsp_only": data.fsp_only, "stack": list(data.stack)}, results=rows)
    db.add(snapshot)
    db.commit()
    return render_search_snapshot(db, snapshot, user.id)


def _changed_candidate_inputs(before: dict, after: dict) -> bool:
    return any(before.get(key) != after.get(key) for key in (
        "category", "test_score", "competencies", "assessment_source", "preferences_version",
    ))


def render_search_snapshot(db: Session, snapshot: SearchSnapshot, employer_id: str) -> dict:
    if snapshot.employer_id != employer_id:
        problem("NOT_FOUND", 404)
    need = db.get(HiringNeed, snapshot.need_id)
    if not need:
        problem("NOT_FOUND", 404)
    current_role = _current_role_version(db, need)
    role_changed = snapshot.role_version_id != (current_role.id if current_role else None)
    pinned_role = db.get(RoleVersion, snapshot.role_version_id) if snapshot.role_version_id else None
    role_data = _search_role_data(need, pinned_role)
    filters = snapshot.filters or {}
    results = []
    for row in snapshot.results or []:
        candidate = db.get(CandidateProfile, row["candidate_id"])
        if (candidate and not is_blocked(candidate, snapshot.employer_id)
                and eligible(candidate, role_data, filters.get("fsp_only", False), filters.get("stack", []))):
            card = public_candidate(candidate, row["match"])
            before = row.get("snapshot_inputs")
            card["snapshot_inputs"] = before
            card["changed_since_search"] = (
                None if before is None else
                role_changed or _changed_candidate_inputs(before, _search_input_snapshot(db, candidate))
            )
            results.append(card)
    return {"id": snapshot.id, "need_id": snapshot.need_id, "parent_snapshot_id": snapshot.parent_id,
            "role_version_id": snapshot.role_version_id,
            "algorithm_version": snapshot.algorithm_version, "created_at": snapshot.created_at.isoformat(),
            "filters": filters, "results": results,
            "unavailable_count": len(snapshot.results or [])-len(results),
            "changed_since_search": role_changed}


def render_snapshot(db: Session, snapshot: SearchSnapshot) -> dict:
    """Compatibility wrapper for callers that already checked snapshot ownership."""
    return render_search_snapshot(db, snapshot, snapshot.employer_id)


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
             "role_version_id": item.role_version_id,
             "algorithm_version": item.algorithm_version, "created_at": item.created_at.isoformat(),
             "filters": item.filters, "result_count": len(item.results or [])}
            for item in snapshots]


@app.get("/api/v1/employer/searches/{snapshot_id}", response_model=SearchOut)
def read_snapshot(snapshot_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    snapshot = db.get(SearchSnapshot, snapshot_id)
    if not snapshot or snapshot.employer_id != user.id:
        problem("NOT_FOUND", 404)
    return render_search_snapshot(db, snapshot, user.id)


@app.get("/api/v1/employer/candidates/{candidate_id}")
def candidate_card(candidate_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    profile = db.get(CandidateProfile, candidate_id)
    if not profile or not can_search(profile) or is_blocked(profile, user.id):
        problem("NOT_FOUND", 404)
    return public_candidate(profile)


@app.get("/api/v1/employer/candidates/{candidate_id}/evidence")
def candidate_evidence(candidate_id: str, response: Response,
                        user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    profile = db.get(CandidateProfile, candidate_id)
    if not profile or not can_search(profile) or is_blocked(profile, user.id):
        problem("NOT_FOUND", 404)
    response.headers["Cache-Control"] = "no-store"
    return [card.model_dump(mode="json")
            for card in list_candidate_evidence(db, candidate_id, audience="employer")]


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


@app.post("/api/v1/employer/invitations", dependencies=[Depends(csrf_guard)], status_code=201,
          response_model=InvitationOut, response_model_exclude_none=True)
def create_invitation(data: InvitationV2In, idempotency_key: str = Header(min_length=8, max_length=100),
                      user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        invitation = create_invitation_record(db, user.id, data, idempotency_key, now())
        db.commit()
    except InvitationError as exc:
        db.rollback()
        problem(exc.code, exc.status)
    except IntegrityError:
        # A concurrent request may have won either the idempotency key or active-pair index.
        db.rollback()
        try:
            invitation = create_invitation_record(db, user.id, data, idempotency_key, now())
            db.commit()
        except InvitationError as exc:
            db.rollback()
            problem(exc.code, exc.status)
        except IntegrityError:
            db.rollback()
            problem("ACTIVE_INVITATION_EXISTS", 409)
    return invitation_data(invitation)


@app.get("/api/v1/employer/invitations", response_model=list[InvitationOut],
         response_model_exclude_none=True)
def sent_invitations(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    invitations = db.scalars(select(Invitation).where(Invitation.employer_id == user.id)
                             .order_by(Invitation.created_at.desc())).all()
    return [invitation_data(x) for x in invitations]


@app.get("/api/v1/candidate/invitations", response_model=list[InvitationOut])
def received_invitations(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = db.get(CandidateProfile, user.id)
    invitations = db.scalars(select(Invitation).where(Invitation.candidate_id == user.id)
                             .order_by(Invitation.created_at.desc())).all()
    return [candidate_invitation_data(db, profile, x) for x in invitations]


@app.post("/api/v1/invitations/{invitation_id}/view", dependencies=[Depends(csrf_guard)],
          response_model=InvitationOut)
def view_invitation(invitation_id: str, data: InvitationCommandIn | None = Body(default=None),
                    user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    try:
        invite = transition_invitation(
            db, user.id, invitation_id, "view",
            data.expected_state_version if data else None, None, now(),
        )
        db.commit()
    except InvitationError as exc:
        db.rollback()
        problem(exc.code, exc.status)
    profile = db.get(CandidateProfile, user.id)
    return candidate_invitation_data(db, profile, invite)


@app.post("/api/v1/invitations/{invitation_id}/interview-held-confirmation",
          dependencies=[Depends(csrf_guard)], response_model=InterviewHeldConfirmationOut)
def confirm_held_interview(invitation_id: str, user: User = Depends(get_user),
                           db: Session = Depends(get_db)):
    try:
        result = confirm_interview_held(db, user.id, invitation_id, now())
        db.commit()
    except InvitationError as exc:
        db.rollback()
        problem(exc.code, exc.status)
    except IntegrityError:
        db.rollback()
        problem("INVITATION_STATE_CONFLICT", 409)
    return result


@app.post("/api/v1/invitations/{invitation_id}/accept", dependencies=[Depends(csrf_guard)],
          response_model=InvitationOut)
def accept_invitation(invitation_id: str, data: AcceptInvitationIn | None = Body(default=None),
                      user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    try:
        invite = transition_invitation(
            db, user.id, invitation_id, "accept",
            data.expected_state_version if data else None, data, now(),
        )
        db.commit()
    except InvitationError as exc:
        db.rollback()
        problem(exc.code, exc.status)
    except IntegrityError:
        db.rollback()
        problem("INVITATION_STATE_CONFLICT", 409)
    return invitation_data(invite)


@app.post("/api/v1/invitations/{invitation_id}/reject", dependencies=[Depends(csrf_guard)],
          response_model=InvitationOut)
def reject_invitation(invitation_id: str, data: InvitationCommandIn | None = Body(default=None),
                      user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    try:
        invite = transition_invitation(
            db, user.id, invitation_id, "reject",
            data.expected_state_version if data else None, None, now(),
        )
        db.commit()
    except InvitationError as exc:
        db.rollback()
        problem(exc.code, exc.status)
    return invitation_data(invite)


@app.post("/api/v1/invitations/{invitation_id}/withdraw", dependencies=[Depends(csrf_guard)],
          response_model=InvitationOut)
def withdraw_invitation(invitation_id: str, data: InvitationCommandIn | None = Body(default=None),
                        user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    try:
        invite = transition_invitation(
            db, user.id, invitation_id, "withdraw",
            data.expected_state_version if data else None, None, now(),
        )
        db.commit()
    except InvitationError as exc:
        db.rollback()
        problem(exc.code, exc.status)
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
