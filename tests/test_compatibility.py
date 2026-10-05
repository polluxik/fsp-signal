from backend.matching import evaluate_compatibility
from backend.models import CandidateProfile, now
from backend.schemas import RoleCardIn


def role(**overrides):
    payload = {
        "title": "Backend-разработчик", "description": "Развивать системы данных",
        "specialization": "backend", "grade": "middle", "competencies": ["event_idempotency"],
        "stack": ["Python"], "salary_min_rub": 180000, "salary_max_rub": 250000,
        "work_format": "remote", "work_city": None, "industry": "fintech",
        "first_30_days": "Устранить повторы при обработке платежей.",
        "interview_steps": [{"title": "Разговор", "duration_minutes": 45}],
        "take_home_minutes": 60, "response_sla_hours": 48,
        "employer_contact": "team@example.test", "active_headcount_attested": True,
    }
    return RoleCardIn.model_validate(payload | overrides)


def candidate(**preferences):
    defaults = {
        "salary_min_rub": 220000, "allowed_work_formats": ["remote"],
        "allowed_cities": [], "excluded_industries": [],
        "preferred_stack": [], "preferred_tasks": [],
        "max_take_home_minutes": None, "available": True,
    }
    return CandidateProfile(user_id="candidate-id", preferences=defaults | preferences,
                            preferences_version=2, work_format="remote", min_salary_rub=220000,
                            adult_attested_at=now())


def test_search_salary_range_and_specific_offer_are_distinct():
    profile = candidate()
    posted_role = role()
    assert evaluate_compatibility(profile, posted_role, mode="search").status == "compatible"
    low_offer = evaluate_compatibility(profile, posted_role, mode="invitation",
                                       offer_terms={"salary_min_rub": 180000,
                                                    "salary_max_rub": 250000,
                                                    "work_format": "remote"})
    assert low_offer.status == "incompatible"
    assert "220000" not in " ".join(check.public_text for check in low_offer.checks)
    fitting_offer = evaluate_compatibility(profile, posted_role, mode="invitation",
                                           offer_terms={"salary_min_rub": 220000,
                                                        "salary_max_rub": 250000,
                                                        "work_format": "remote"})
    assert fitting_offer.status == "compatible"


def test_zero_take_home_conflicts_and_unreported_city_or_industry_is_unknown():
    no_homework = evaluate_compatibility(candidate(max_take_home_minutes=0), role(), mode="search")
    assert no_homework.status == "incompatible"
    assert next(check for check in no_homework.checks if check.code == "take_home").status == "fail"

    needs_city = candidate(allowed_work_formats=["hybrid"], allowed_cities=["Москва"],
                           excluded_industries=["gambling"])
    legacy_unknowns = {
        **role().model_dump(mode="json"), "work_format": "hybrid", "work_city": None, "industry": None,
    }
    unknown = evaluate_compatibility(needs_city, legacy_unknowns, mode="search")
    assert unknown.status == "needs_clarification"
    assert {item.code for item in unknown.checks if item.status == "unknown"} == {"location", "industry"}


def test_preferred_stack_is_soft_and_never_a_hard_failure():
    report = evaluate_compatibility(candidate(preferred_stack=["Rust"]), role(), mode="search")
    assert report.status == "compatible"
    assert report.soft_signals[0].code == "preferred_stack"
    assert report.soft_signals[0].matched is False


def test_unpinned_invitation_does_not_claim_soft_preferences_without_role_evidence():
    report = evaluate_compatibility(
        candidate(preferred_stack=["Rust"], preferred_tasks=["data systems"]), {},
        mode="invitation", offer_terms={"salary_min_rub": 220000, "work_format": "remote"},
    )
    assert report.status == "compatible"
    assert report.soft_signals == []
