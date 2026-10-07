from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from .taxonomy import get_category


class ApiError(BaseModel):
    """Stable error envelope returned by application and security checks."""

    detail: str | list[dict[str, Any]]


class RegisterIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    role: str


class LoginIn(BaseModel):
    email: str
    password: str


class VerifyIn(BaseModel):
    token: str


class AchievementStoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=120)
    context: str = Field(min_length=8, max_length=700)
    personal_contribution: str = Field(min_length=8, max_length=700)
    decision: str = Field(default="", max_length=700)
    result: str = Field(min_length=8, max_length=700)
    result_scope: Literal["individual", "team"] = "individual"
    basis: str = Field(default="", max_length=500)
    share_with_employers: bool = False
    formatted_narrative: str | None = Field(default=None, max_length=5000)

    @field_validator("title", "context", "personal_contribution", "decision", "result", "basis", mode="before")
    @classmethod
    def trim_story_text(cls, value: str):
        return value.strip() if isinstance(value, str) else value


class CandidateIn(BaseModel):
    full_name: str = Field(max_length=160)
    contact_email: str = Field(max_length=254)
    contact_phone: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=4000)
    achievement_story: AchievementStoryIn | None = None
    skills: list[str] = Field(default_factory=list, max_length=30)
    experience_months: int = Field(default=0, ge=0, le=720)
    min_salary_rub: int = Field(default=0, ge=0)
    work_format: str = "remote"
    consent_processing: bool = False
    published: bool = False
    available: bool = True
    adult_hiring_confirmed: bool | None = None
    expected_preferences_version: int | None = Field(default=None, ge=1)


class EmployerIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=4000)
    industry: str = Field(default="", max_length=120)
    contact_email: str = Field(min_length=5, max_length=254)


class TaxonomyCompetencyOut(BaseModel):
    id: str
    label: str


class TaxonomyCategoryOut(BaseModel):
    id: str
    specialization: Literal["backend", "frontend", "qa", "data_analyst"]
    grade: str
    label: str
    blueprint_version: str
    available: bool
    competencies: list[TaxonomyCompetencyOut]


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
    specialization: str
    grade: Literal["junior", "middle"]
    competencies: list[str] = Field(min_length=1, max_length=12)
    stack: list[str] = Field(default_factory=list, max_length=20)
    salary_min_rub: int = Field(gt=0)
    salary_max_rub: int = Field(gt=0)
    work_format: Literal["remote", "hybrid", "office"]
    work_city: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=120)
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

    @field_validator("industry", "work_city")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("competencies", "stack")
    @classmethod
    def normalize_labels(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("duplicate values are not allowed")
        return cleaned

    @model_validator(mode="after")
    def check_role_terms(self):
        category = get_category(self.specialization, self.grade)
        if category is None:
            raise ValueError("unsupported role category")
        allowed_competencies = {item.id for item in category.competencies}
        if not set(self.competencies).issubset(allowed_competencies):
            raise ValueError("competencies must belong to the selected role category")
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


class CandidateRoleCard(BaseModel):
    title: str
    description: str
    specialization: Literal["backend", "frontend", "qa", "data_analyst"]
    grade: Literal["junior", "middle"]
    competencies: list[str]
    stack: list[str]
    salary_min_rub: int
    salary_max_rub: int
    work_format: Literal["remote", "hybrid", "office"]
    work_city: str | None = None
    industry: str | None = None
    first_30_days: str
    interview_steps: list[InterviewStepIn]
    take_home_minutes: int
    response_sla_hours: Literal[24, 48, 72]


class RoleDecisionIn(BaseModel):
    action: Literal["saved", "hidden", "none"]
    expected_role_version: str = Field(min_length=36, max_length=36)
    expected_preferences_version: int = Field(ge=1)
    source_campaign_id: str | None = Field(default=None, min_length=36, max_length=36)


class RoleDecisionOut(BaseModel):
    need_id: str
    action: Literal["saved", "hidden", "none"]
    role_version_id: str
    preferences_version: int
    updated_at: datetime


class CandidatePreferencesIn(BaseModel):
    expected_version: int = Field(ge=1)
    salary_min_rub: int | None = Field(default=None, ge=1)
    allowed_work_formats: list[Literal["remote", "hybrid", "office"]] = Field(min_length=1, max_length=3)
    allowed_cities: list[str] = Field(default_factory=list, max_length=20)
    excluded_industries: list[str] = Field(default_factory=list, max_length=20)
    preferred_stack: list[str] = Field(default_factory=list, max_length=30)
    preferred_tasks: list[str] = Field(default_factory=list, max_length=30)
    max_take_home_minutes: int | None = Field(default=None, ge=0, le=240)
    available: bool = True
    adult_hiring_confirmed: bool

    @field_validator("allowed_cities", "excluded_industries", "preferred_stack", "preferred_tasks")
    @classmethod
    def normalize_preferences(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("duplicate preference values are not allowed")
        return cleaned

    @field_validator("allowed_work_formats")
    @classmethod
    def normalize_formats(cls, values: list[str]) -> list[str]:
        result = list(dict.fromkeys(values))
        if not result:
            raise ValueError("at least one work format is required")
        return result


class CandidatePreferencesOut(BaseModel):
    version: int
    salary_min_rub: int | None
    allowed_work_formats: list[str]
    allowed_cities: list[str]
    excluded_industries: list[str]
    preferred_stack: list[str]
    preferred_tasks: list[str]
    max_take_home_minutes: int | None
    available: bool
    adult_hiring_confirmed: bool


class CompatibilityCheck(BaseModel):
    code: str
    status: Literal["pass", "unknown", "fail"]
    public_text: str


class CompatibilitySoftSignal(BaseModel):
    code: str
    matched: bool
    public_text: str


class CompatibilityReport(BaseModel):
    status: Literal["compatible", "needs_clarification", "incompatible"]
    checks: list[CompatibilityCheck]
    soft_signals: list[CompatibilitySoftSignal] = Field(default_factory=list)
    preference_version: int
    role_version_id: str | None = None
    compatibility_version: Literal["compat_v2"] = "compat_v2"


class CandidateRoleFeedItem(BaseModel):
    need_id: str
    role_version_id: str
    role_version: int
    company_name: str
    role: CandidateRoleCard
    confirmed_at: datetime
    preferences_version: int
    data_mode: Literal["real", "synthetic", "unknown"]
    match_state: Literal["compatible", "needs_clarification", "not_assessed"]
    compatibility: CompatibilityReport | None = None
    decision: Literal["saved", "hidden", "none"] = "none"
    discovery_match: dict | None = None


class SponsoredCandidateRoleFeedItem(CandidateRoleFeedItem):
    campaign_id: str
    sponsor_label: Literal["Продвигаемая роль"] = "Продвигаемая роль"


class RoleFeedOut(BaseModel):
    items: list[CandidateRoleFeedItem]
    sponsored_items: list[SponsoredCandidateRoleFeedItem] = Field(default_factory=list)
    next_cursor: str | None = None
    limit: int
    empty_state: Literal["no_active_roles", "no_compatible_roles", "no_saved_roles"] | None = None


class DemoPromotionOut(BaseModel):
    id: str
    need_id: str
    role_version_id: str
    active_from: datetime
    active_until: datetime
    demo_only: Literal[True] = True
    revenue_rub: Literal[0] = 0


class SponsoredImpressionOut(BaseModel):
    recorded: bool = True


class AccessChangeResult(BaseModel):
    employer_id: str
    blocked: bool
    revoked_grants: int
    withdrawn_invitations: int


class StartAssessmentIn(BaseModel):
    industry: str = "it"
    specialization: str
    grade: str


class AnswersIn(BaseModel):
    answers: dict[str, str | int | dict[str, str | int]]


class EvidenceCard(BaseModel):
    id: str
    competency: str | None
    action: str
    source_type: Literal[
        "assessment_attempt", "fsp_achievement", "achievement_story", "skill_claim", "legacy_aggregate"
    ]
    source_id: str | None
    source_version: str
    assessed_at: datetime | None
    verification_level: Literal[
        "verified_action", "verified_credential", "declared", "aggregate", "synthetic_fixture"
    ]
    scope: str
    limitations: list[str]
    data_mode: Literal["real", "synthetic"]


class EvidenceGap(BaseModel):
    competency: str = Field(min_length=1, max_length=80)
    status: Literal["unknown", "gap"]
    question: str = Field(min_length=5, max_length=300)

    @field_validator("competency", "question", mode="before")
    @classmethod
    def trim_gap_text(cls, value: str):
        return value.strip() if isinstance(value, str) else value


class MatchExplanation(BaseModel):
    reasons: list[str] = Field(default_factory=list)
    gaps: list[EvidenceGap] = Field(default_factory=list, max_length=20)


class MatchResult(BaseModel):
    score: float | None
    components: dict[str, float | None]
    evidence_coverage: float
    reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    explanation: MatchExplanation
    algorithm_version: Literal["match_v1", "match_v2"]


class SearchIn(BaseModel):
    need_id: str
    role_version_id: str | None = None
    parent_snapshot_id: str | None = None
    fsp_only: bool = False
    stack: list[str] = Field(default_factory=list)


class SearchOut(BaseModel):
    id: str
    need_id: str
    parent_snapshot_id: str | None
    role_version_id: str | None = None
    algorithm_version: str
    created_at: datetime
    filters: dict[str, Any]
    results: list[dict[str, Any]]
    unavailable_count: int
    changed_since_search: bool = False


class InvitationIn(BaseModel):
    candidate_id: str
    need_id: str | None = None
    offer_text: str = Field(min_length=20, max_length=4000)
    reason: str = Field(min_length=10, max_length=1500)
    salary_min_rub: int = Field(gt=0)
    salary_max_rub: int = Field(gt=0)
    work_format: str
    employer_contact: str = Field(min_length=5, max_length=254)


class InvitationV2In(InvitationIn):
    model_config = ConfigDict(extra="forbid")

    role_version_id: str | None = Field(default=None, min_length=1, max_length=36)
    inline_role_card: RoleCardIn | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("evidence_ids must be non-empty and unique")
        return values

    @model_validator(mode="after")
    def validate_v2_reference(self):
        has_version = self.role_version_id is not None
        has_inline = self.inline_role_card is not None
        is_v2 = has_version or has_inline or bool(self.evidence_ids)
        if has_version and has_inline:
            raise ValueError("choose either role_version_id or inline_role_card")
        if is_v2 and not (has_version or has_inline):
            raise ValueError("v2 invitation requires a pinned role or inline role card")
        if is_v2 and not self.evidence_ids:
            raise ValueError("v2 invitation requires at least one evidence reference")
        return self


class InvitationCommandIn(BaseModel):
    expected_state_version: int | None = Field(default=None, ge=1)


class AcceptInvitationIn(InvitationCommandIn):
    expected_terms_hash: str = Field(min_length=64, max_length=64)
    expected_preferences_version: int = Field(ge=1)


class InvitationOut(BaseModel):
    id: str
    candidate_id: str
    company_name: str
    employer_id: str
    need_id: str | None
    role_version_id: str | None = None
    offer_text: str
    reason: str
    employer_contact: str
    salary_min_rub: int
    salary_max_rub: int
    salary_period: Literal["month"] = "month"
    salary_basis: Literal["gross"] = "gross"
    work_format: str
    state: Literal["sent", "viewed", "accepted", "rejected", "withdrawn", "expired"]
    created_at: datetime
    expires_at: datetime
    terms_snapshot: dict[str, Any] | None = None
    terms_hash: str | None = None
    evidence_refs: list[EvidenceCard] = Field(default_factory=list)
    explanation_snapshot: dict[str, Any] | None = None
    compatibility_at_send: CompatibilityReport | None = None
    state_version: int = 1
    response_due_at: datetime | None = None
    compatibility: CompatibilityReport | None = None
    candidate_interview_confirmed: bool
    employer_interview_confirmed: bool


class InterviewHeldConfirmationOut(BaseModel):
    invitation_id: str
    candidate_confirmed: bool
    employer_confirmed: bool
    interview_held: bool


class FspLinkIn(BaseModel):
    participant_id: str = Field(min_length=5, max_length=80)


class FspAchievementOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_version: Literal["fsp-achievement-v1"] = "fsp-achievement-v1"
    issuer: str = Field(min_length=2, max_length=160)
    discipline: str = Field(min_length=2, max_length=120)
    event_name: str = Field(min_length=2, max_length=240)
    event_date: str = Field(min_length=10, max_length=10)
    result: Literal["participant", "finalist", "prize"]
    result_scope: Literal["individual", "team"]
    personal_role: str = Field(default="", max_length=500)
    evidence_url: str | None = Field(default=None, max_length=1000)
    mapped_specializations: list[Literal["backend", "frontend", "qa", "data_analyst"]] = Field(
        default_factory=list, max_length=4
    )
    verified_at: datetime
    source: Literal["fsp_registry", "synthetic_fixture"]


class AssistantDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=2000)
    external_ai_consent: bool

    @field_validator("text", mode="before")
    @classmethod
    def trim_assistant_input(cls, value: str):
        return value.strip() if isinstance(value, str) else value


class CandidatePreferencesDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    salary_min_rub: int | None = Field(default=None, ge=1)
    allowed_work_formats: list[Literal["remote", "hybrid", "office"]] = Field(default_factory=list, max_length=3)
    allowed_cities: list[str] = Field(default_factory=list, max_length=20)
    excluded_industries: list[str] = Field(default_factory=list, max_length=20)
    preferred_stack: list[str] = Field(default_factory=list, max_length=30)
    preferred_tasks: list[str] = Field(default_factory=list, max_length=30)
    max_take_home_minutes: int | None = Field(default=None, ge=0, le=240)
    missing_fields: list[Literal[
        "salary_min_rub", "allowed_work_formats", "allowed_cities", "excluded_industries",
        "preferred_stack", "preferred_tasks", "max_take_home_minutes",
    ]] = Field(default_factory=list, max_length=7)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


class CandidateAchievementDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(default="", max_length=120)
    context: str = Field(default="", max_length=700)
    personal_contribution: str = Field(default="", max_length=700)
    decision: str = Field(default="", max_length=700)
    result: str = Field(default="", max_length=700)
    result_scope: Literal["individual", "team"] | None = None
    basis: str = Field(default="", max_length=500)
    missing_fields: list[Literal[
        "context", "personal_contribution", "decision", "result", "result_scope", "basis",
    ]] = Field(default_factory=list, max_length=6)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


class AssistantInterviewStepDraft(InterviewStepIn):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmployerRoleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    specialization: Literal["backend", "frontend", "qa", "data_analyst"] | None = None
    grade: Literal["junior", "middle"] | None = None
    competencies: list[str] = Field(default_factory=list, max_length=12)
    stack: list[str] = Field(default_factory=list, max_length=20)
    salary_min_rub: int | None = Field(default=None, gt=0)
    salary_max_rub: int | None = Field(default=None, gt=0)
    work_format: Literal["remote", "hybrid", "office"] | None = None
    work_city: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=120)
    first_30_days: str | None = Field(default=None, max_length=2000)
    interview_steps: list[AssistantInterviewStepDraft] = Field(default_factory=list, max_length=5)
    take_home_minutes: int | None = Field(default=None, ge=0, le=240)
    response_sla_hours: Literal[24, 48, 72] | None = None
    missing_fields: list[Literal[
        "title", "description", "specialization", "grade", "competencies", "stack",
        "salary_min_rub", "salary_max_rub", "work_format", "work_city", "industry",
        "first_30_days", "interview_steps", "take_home_minutes", "response_sla_hours",
    ]] = Field(default_factory=list, max_length=15)
    ambiguous_fields: list[Literal[
        "title", "description", "specialization", "grade", "competencies", "stack",
        "salary_min_rub", "salary_max_rub", "work_format", "work_city", "industry",
        "first_30_days", "interview_steps", "take_home_minutes", "response_sla_hours",
    ]] = Field(default_factory=list, max_length=15)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_competency_category(self):
        if not self.competencies:
            return self
        if self.specialization is None or self.grade is None:
            raise ValueError("role category is required when competencies are proposed")
        category = get_category(self.specialization, self.grade)
        if category is None:
            raise ValueError("unsupported role category")
        allowed_competencies = {item.id for item in category.competencies}
        if not set(self.competencies).issubset(allowed_competencies):
            raise ValueError("competencies must belong to the selected role category")
        return self
