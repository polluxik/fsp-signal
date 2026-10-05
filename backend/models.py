from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(30), default="legacy_import")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint("origin IN ('direct_signup','synthetic_fixture','legacy_import')", name="user_origin"),
    )


class EmailToken(Base):
    __tablename__ = "email_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    contact_email: Mapped[str] = mapped_column(String(254), default="")
    contact_phone: Mapped[str] = mapped_column(String(80), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    experience_months: Mapped[int] = mapped_column(Integer, default=0)
    desired_specialization: Mapped[str | None] = mapped_column(String(30))
    claimed_grade: Mapped[str | None] = mapped_column(String(20))
    verified_specialization: Mapped[str | None] = mapped_column(String(30), index=True)
    verified_grade: Mapped[str | None] = mapped_column(String(20), index=True)
    test_score: Mapped[int | None] = mapped_column(Integer)
    verification_source: Mapped[str | None] = mapped_column(String(30))
    competencies: Mapped[dict] = mapped_column(JSON, default=dict)
    test_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grade_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    min_salary_rub: Mapped[int] = mapped_column(Integer, default=0)
    work_format: Mapped[str] = mapped_column(String(20), default="remote")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    preferences_version: Mapped[int] = mapped_column(Integer, default=1)
    preferences_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adult_attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_employer_ids: Mapped[list] = mapped_column(JSON, default=list)
    verified_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("assessment_attempts.id"))
    fsp_id: Mapped[str | None] = mapped_column(String(80))
    fsp_status: Mapped[str] = mapped_column(String(30), default="unlinked")
    fsp_result: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (
        CheckConstraint("min_salary_rub >= 0", name="candidate_min_salary_nonnegative"),
        CheckConstraint("preferences_version >= 1", name="candidate_preferences_version"),
    )


class EmployerProfile(Base):
    __tablename__ = "employer_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    contact_email: Mapped[str] = mapped_column(String(254), default="")


class HiringNeed(Base):
    __tablename__ = "hiring_needs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    specialization: Mapped[str] = mapped_column(String(30))
    grade: Mapped[str] = mapped_column(String(20))
    competencies: Mapped[list] = mapped_column(JSON, default=list)
    stack: Mapped[list] = mapped_column(JSON, default=list)
    salary_min_rub: Mapped[int] = mapped_column(Integer)
    salary_max_rub: Mapped[int] = mapped_column(Integer)
    work_format: Mapped[str] = mapped_column(String(20))
    current_role_version: Mapped[int] = mapped_column(Integer, default=0)
    publication_state: Mapped[str] = mapped_column(String(20), default="draft")
    discoverable: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint("salary_min_rub > 0 AND salary_max_rub >= salary_min_rub", name="need_salary_range"),
        CheckConstraint("current_role_version >= 0", name="need_role_version_nonnegative"),
        CheckConstraint("publication_state IN ('draft','active','paused','closed')", name="need_publication_state"),
    )


class RoleVersion(Base):
    __tablename__ = "role_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    need_id: Mapped[str] = mapped_column(ForeignKey("hiring_needs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON)
    terms_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("need_id", "version", name="role_version_need_version"),
        CheckConstraint("version > 0", name="role_version_positive"),
        CheckConstraint("source IN ('employer_declared','legacy_import','synthetic_demo')", name="role_version_source"),
    )


class RoleDecision(Base):
    __tablename__ = "role_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    need_id: Mapped[str] = mapped_column(ForeignKey("hiring_needs.id"), index=True)
    role_version_id: Mapped[str] = mapped_column(ForeignKey("role_versions.id"))
    action: Mapped[str] = mapped_column(String(20), default="none")
    preferences_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("candidate_id", "need_id", name="role_decision_candidate_need"),
        CheckConstraint("action IN ('saved','hidden','interested','none')", name="role_decision_action"),
    )


class ProductEvent(Base):
    __tablename__ = "product_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    type: Mapped[str] = mapped_column(String(50), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    employer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data_mode: Mapped[str] = mapped_column(String(20), default="real")
    dedupe_key: Mapped[str] = mapped_column(String(180), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        CheckConstraint("data_mode IN ('real','synthetic')", name="product_event_data_mode"),
    )


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    specialization: Mapped[str] = mapped_column(String(30))
    grade: Mapped[str] = mapped_column(String(20))
    blueprint_version: Mapped[str] = mapped_column(String(60))
    seed: Mapped[str | None] = mapped_column(String(32))
    questions: Mapped[list] = mapped_column(JSON)
    answer_key: Mapped[dict] = mapped_column(JSON)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    phase: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(20), default="in_progress")
    score: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchSnapshot(Base):
    __tablename__ = "search_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    need_id: Mapped[str] = mapped_column(ForeignKey("hiring_needs.id"))
    role_version_id: Mapped[str | None] = mapped_column(ForeignKey("role_versions.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("search_snapshots.id"))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list] = mapped_column(JSON, default=list)
    algorithm_version: Mapped[str] = mapped_column(String(30), default="match_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    need_id: Mapped[str | None] = mapped_column(ForeignKey("hiring_needs.id"))
    role_version_id: Mapped[str | None] = mapped_column(ForeignKey("role_versions.id"))
    company_name: Mapped[str] = mapped_column(String(160))
    offer_text: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    employer_contact: Mapped[str] = mapped_column(String(254))
    salary_min_rub: Mapped[int] = mapped_column(Integer)
    salary_max_rub: Mapped[int] = mapped_column(Integer)
    work_format: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="sent")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("salary_min_rub > 0 AND salary_max_rub >= salary_min_rub", name="invitation_salary_range"),
        UniqueConstraint("employer_id", "idempotency_key", name="invitation_idempotency"),
    )


class ContactGrant(Base):
    __tablename__ = "contact_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    invitation_id: Mapped[str] = mapped_column(ForeignKey("invitations.id"), unique=True)
    employer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MailOutbox(Base):
    __tablename__ = "mail_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    recipient: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_error: Mapped[str | None] = mapped_column(String(200))
