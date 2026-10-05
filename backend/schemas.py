from pydantic import BaseModel, Field


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
