from datetime import timedelta

import pytest

from backend.assessment import COMPETENCIES
from backend.config import Settings
from backend.matching import score_profile_v2
from backend.models import CandidateProfile, now
from backend.schemas import RoleCardIn


def make_role(specialization="backend", grade="middle", competencies=None, **overrides):
    competencies = competencies or [COMPETENCIES[f"{specialization}:{grade}"][0]]
    payload = {
        "title": "Backend-разработчик",
        "description": "Надёжная обработка событий и данных",
        "specialization": specialization,
        "grade": grade,
        "competencies": competencies,
        "stack": ["Python"],
        "salary_min_rub": 180000,
        "salary_max_rub": 230000,
        "work_format": "remote",
        "work_city": None,
        "industry": "ИТ",
        "first_30_days": "Устранить повторную обработку платежных событий",
        "interview_steps": [{"title": "Знакомство с командой", "duration_minutes": 45}],
        "take_home_minutes": 0,
        "response_sla_hours": 48,
        "employer_contact": "team@example.test",
        "active_headcount_attested": True,
    }
    return RoleCardIn.model_validate(payload | overrides)


def make_profile(specialization="backend", grade="middle", **overrides):
    competency = COMPETENCIES[f"{specialization}:{grade}"][0]
    values = {
        "user_id": "candidate-1",
        "verified_specialization": specialization,
        "verified_grade": grade,
        "verified_attempt_id": "passed-attempt-1",
        "test_score": 90,
        "verification_source": "assessment",
        "competencies": {competency: 0.8},
        "test_verified_at": now(),
        "skills": ["Python"],
    }
    return CandidateProfile(**(values | overrides))


def test_v2_uses_the_frozen_60_35_5_formula_without_fsp_or_freshness(monkeypatch):
    from backend import matching

    role = make_role()
    profile = make_profile(fsp_status="verified_external", fsp_result="prize",
                           test_verified_at=now() - timedelta(days=365))
    monkeypatch.setattr(matching, "lexical_similarity_for_role", lambda _role, _profile: 0.4)

    result = score_profile_v2(profile, role)

    assert result.score == 81.5
    assert result.components == {"competencies": 0.8, "assessment": 0.9, "text": 0.4}
    assert result.evidence_coverage == 1.0
    assert set(result.components) == {"competencies", "assessment", "text"}
    assert result.algorithm_version == "match_v2"
    assert any("Текстовый сигнал" in reason for reason in result.explanation.reasons)


def test_declared_keyword_flood_cannot_change_v2_score():
    role = make_role()
    profile = make_profile(skills=["Python"])
    flooded_profile = make_profile(
        skills=["event_idempotency", "повторные события", "backend", "Python"] * 30
    )
    original = score_profile_v2(profile, role)
    flooded = score_profile_v2(flooded_profile, role)

    assert flooded.score == original.score
    assert flooded.components == original.components


def test_missing_attempt_is_unknown_not_a_zero_competency_score(monkeypatch):
    from backend import matching

    competency = COMPETENCIES["backend:middle"][0]
    role = make_role(competencies=[competency])
    profile = make_profile(verified_attempt_id=None, competencies={competency: 1.0})
    monkeypatch.setattr(matching, "lexical_similarity_for_role", lambda _role, _profile: 0.9)

    result = score_profile_v2(profile, role)

    assert result.components == {"competencies": None, "assessment": 0.9, "text": None}
    assert result.score == 90.0
    assert result.evidence_coverage == 0.35
    assert any(gap.competency == competency and gap.status == "unknown"
               for gap in result.explanation.gaps)
    assert "Пока нет данных по компетенции" in result.gaps[0]
    assert any("неизвестными, а не нулевыми" in reason for reason in result.explanation.reasons)


def test_text_component_does_not_borrow_unrelated_competency_evidence():
    selected, unrelated = COMPETENCIES["backend:middle"][:2]
    role = make_role(competencies=[selected])
    profile = make_profile(competencies={unrelated: 1.0})

    result = score_profile_v2(profile, role)

    assert result.components == {"competencies": None, "assessment": 0.9, "text": None}
    assert result.evidence_coverage == 0.35
    assert result.score == 90.0


def test_evidence_coverage_accounts_for_unassessed_role_competencies():
    selected, missing = COMPETENCIES["backend:middle"][:2]
    role = make_role(competencies=[selected, missing])
    profile = make_profile(competencies={selected: 0.8})

    result = score_profile_v2(profile, role)

    assert result.components["competencies"] == 0.8
    assert result.evidence_coverage == 0.7
    assert any(gap.competency == missing and gap.status == "unknown"
               for gap in result.explanation.gaps)


@pytest.mark.parametrize(
    ("specialization", "grade"),
    [("backend", "junior"), ("backend", "middle"), ("frontend", "junior"), ("frontend", "middle")],
)
def test_v2_scores_only_within_the_same_verified_category(specialization, grade, monkeypatch):
    from backend import matching

    role = make_role(specialization, grade)
    profile = make_profile(specialization, grade)
    monkeypatch.setattr(matching, "lexical_similarity_for_role", lambda _role, _profile: 0.0)

    assert score_profile_v2(profile, role).score is not None
    same_specialization_other_grade = make_role(
        specialization, "middle" if grade == "junior" else "junior"
    )
    assert score_profile_v2(profile, same_specialization_other_grade).score is None
    other = make_role("frontend" if specialization == "backend" else "backend", grade)
    assert score_profile_v2(profile, other).score is None


def test_matching_algorithm_config_accepts_only_supported_versions(monkeypatch):
    monkeypatch.delenv("MATCH_ALGORITHM_VERSION", raising=False)
    assert Settings().match_algorithm_version == "match_v2"
    assert Settings(match_algorithm_version="match_v2").match_algorithm_version == "match_v2"
    with pytest.raises(ValueError, match="MATCH_ALGORITHM_VERSION"):
        Settings(match_algorithm_version="match_v3")
