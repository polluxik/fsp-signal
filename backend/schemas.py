from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class RegisterIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    role: str


class LoginIn(BaseModel):
    email: str
    password: str


class VerifyIn(BaseModel):
    token: str


class CandidateIn(BaseModel):
    full_name: str = Field(max_length=160)
    contact_email: str = Field(max_length=254)
    contact_phone: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=4000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    experience_months: int = Field(default=0, ge=0, le=720)
    min_salary_rub: int = Field(default=0, ge=0)
    work_format: str = "remote"
    consent_processing: bool = False
    published: bool = False
    available: bool = True


class EmployerIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=4000)
    industry: str = Field(default="", max_length=120)
    contact_email: str = Field(min_length=5, max_length=254)


class NeedIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=10, max_length=5000)
    specialization: str
    grade: str
    competencies: list[str] = Field(default_factory=list)
    stack: list[str] = Field(default_factory=list)
    salary_min_rub: int = Field(gt=0)
    salary_max_rub: int = Field(gt=0)
    work_format: str = "remote"


class InterviewStepIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    duration_minutes: int = Field(ge=1, le=240)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("title must contain at least two non-space characters")
        return value


class RoleCardIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=10, max_length=2000)
    specialization: Literal["backend", "frontend"]
    grade: Literal["junior", "middle"]
    competencies: list[str] = Field(min_length=1, max_length=12)
    stack: list[str] = Field(default_factory=list, max_length=20)
    salary_min_rub: int = Field(gt=0)
    salary_max_rub: int = Field(gt=0)
    work_format: Literal["remote", "hybrid", "office"]
    work_city: str | None = Field(default=None, max_length=120)
    first_30_days: str = Field(min_length=10, max_length=2000)
    interview_steps: list[InterviewStepIn] = Field(min_length=1, max_length=5)
    take_home_minutes: int = Field(ge=0, le=240)
    response_sla_hours: Literal[24, 48, 72]
    employer_contact: str = Field(min_length=5, max_length=254)
    active_headcount_attested: bool

    @field_validator("title", "description", "first_30_days", "employer_contact")
    @classmethod
    def trim_text(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        minimum = {"title": 3, "description": 10, "first_30_days": 10, "employer_contact": 5}
        if len(value) < minimum[info.field_name]:
            raise ValueError(f"{info.field_name} is too short after trimming")
        if info.field_name == "employer_contact":
            local, separator, domain = value.rpartition("@")
            if not separator or not local or "." not in domain:
                raise ValueError("employer_contact must be an email address")
        return value

    @field_validator("competencies", "stack")
    @classmethod
    def normalize_labels(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("duplicate values are not allowed")
        return cleaned

    @model_validator(mode="after")
    def check_role_terms(self):
        if self.salary_max_rub < self.salary_min_rub:
            raise ValueError("salary_max_rub must be >= salary_min_rub")
        if not self.competencies:
            raise ValueError("at least one competency is required")
        if self.work_format in ("office", "hybrid") and not self.work_city:
            raise ValueError("work_city is required for office or hybrid roles")
        if self.work_city is not None:
            self.work_city = self.work_city.strip() or None
        return self


class RoleVersionIn(BaseModel):
    expected_version: int = Field(ge=0)
    card: RoleCardIn


class PublishRoleIn(BaseModel):
    expected_version: int = Field(ge=1)
    active_headcount_attested: bool
    discoverable: bool = False


class ReconfirmRoleIn(BaseModel):
    expected_version: int = Field(ge=1)
    active_headcount_attested: bool


class RoleMutationIn(BaseModel):
    expected_version: int = Field(ge=1)


class RoleCardOut(BaseModel):
    need_id: str
    version: int | None
    schema_version: int | None
    payload: dict
    terms_hash: str | None
    source: str | None
    current_role_version: int
    publication_state: Literal["draft", "active", "paused", "closed"]
    discoverable: bool
    confirmed_at: datetime | None
    fresh: bool
    missing_fields: list[str] = Field(default_factory=list)
    salary_currency: Literal["RUB"] = "RUB"
    salary_period: Literal["month"] = "month"
    salary_basis: Literal["gross"] = "gross"


class StartAssessmentIn(BaseModel):
    industry: str = "it"
    specialization: str
    grade: str


class AnswersIn(BaseModel):
    answers: dict[str, str | int]


class SearchIn(BaseModel):
    need_id: str
    parent_snapshot_id: str | None = None
    fsp_only: bool = False
    stack: list[str] = Field(default_factory=list)


class InvitationIn(BaseModel):
    candidate_id: str
    need_id: str | None = None
    offer_text: str = Field(min_length=20, max_length=4000)
    reason: str = Field(min_length=10, max_length=1500)
    salary_min_rub: int = Field(gt=0)
    salary_max_rub: int = Field(gt=0)
    work_format: str
    employer_contact: str = Field(min_length=5, max_length=254)


class FspLinkIn(BaseModel):
    participant_id: str = Field(min_length=5, max_length=80)
