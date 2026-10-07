"""Employer-facing evidence stays opt-in and never exposes candidate profile fields."""

from fastapi.testclient import TestClient

from backend.db import SessionLocal
from backend.main import app
from backend.models import CandidateProfile, now
from test_flow import csrf, register_verified


def deactivate_candidate(candidate_id: str) -> None:
    with SessionLocal() as db:
        profile = db.get(CandidateProfile, candidate_id)
        if profile:
            profile.available = False
            db.commit()


def test_employer_can_load_only_candidate_opted_in_evidence(request):
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = register_verified(candidate, "evidence-owner@example.test", "candidate")
        request.addfinalizer(lambda: deactivate_candidate(person["id"]))
        register_verified(employer, "evidence-viewer@example.test", "employer")
        profile = candidate.put("/api/v1/candidate/profile", json={
            "full_name": "Алексей Кандидат", "contact_email": "private@example.test",
            "contact_phone": "+7 900 000-00-00", "city": "Казань",
            "summary": "Личный текст резюме", "skills": ["Python", "PostgreSQL"],
            "experience_months": 24, "min_salary_rub": 180000, "work_format": "remote",
            "consent_processing": True, "published": True, "available": True,
            "adult_hiring_confirmed": True,
            "achievement_story": {
                "title": "Идемпотентная обработка",
                "context": "Повтор события мог создать двойную запись.",
                "personal_contribution": "Добавил обработку повтора по event ID.",
                "decision": "Выбрал уникальное ограничение.",
                "result": "Убрали повторный побочный эффект.",
                "result_scope": "individual", "basis": "PR 184",
                "share_with_employers": False,
            },
        }, headers=csrf(candidate))
        assert profile.status_code == 200, profile.text

        with SessionLocal() as db:
            saved = db.get(CandidateProfile, person["id"])
            saved.achievement_story = dict(saved.achievement_story, share_with_employers=True)
            saved.verified_specialization = "backend"
            saved.verified_grade = "middle"
            saved.test_score = 86
            db.commit()

        response = employer.get(f"/api/v1/employer/candidates/{person['id']}/evidence")
        assert response.status_code == 200, response.text
        cards = response.json()
        assert {card["source_type"] for card in cards} >= {"achievement_story", "skill_claim"}
        story = next(card for card in cards if card["source_type"] == "achievement_story")
        assert story["verification_level"] == "declared"
        assert "Личный текст резюме" not in response.text
        assert "private@example.test" not in response.text
        assert response.headers["cache-control"] == "no-store"

        other = TestClient(app)
        try:
            register_verified(other, "evidence-other@example.test", "employer")
            assert other.get(f"/api/v1/employer/candidates/{person['id']}/evidence").status_code == 200
        finally:
            other.close()


def test_legacy_aggregate_evidence_is_not_serialized_as_a_verified_action(request):
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = register_verified(candidate, "legacy-aggregate-owner@example.test", "candidate")
        request.addfinalizer(lambda: deactivate_candidate(person["id"]))
        register_verified(employer, "legacy-aggregate-viewer@example.test", "employer")
        saved = candidate.put("/api/v1/candidate/profile", json={
            "full_name": "Кандидат со старой записью",
            "contact_email": "private@example.test",
            "contact_phone": "",
            "city": "Казань",
            "summary": "Агрегированная проверка без сохранённой попытки",
            "skills": ["Python"],
            "experience_months": 24,
            "min_salary_rub": 0,
            "work_format": "remote",
            "consent_processing": True,
            "published": True,
            "available": True,
            "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert saved.status_code == 200, saved.text
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person["id"])
            profile.verified_specialization = "backend"
            profile.verified_grade = "middle"
            profile.test_score = 86
            profile.verification_source = "assessment"
            profile.test_verified_at = now()
            profile.verified_attempt_id = None
            db.commit()

        response = employer.get(f"/api/v1/employer/candidates/{person['id']}/evidence")
        assert response.status_code == 200, response.text
        legacy = next(card for card in response.json() if card["source_type"] == "legacy_aggregate")
        assert legacy["verification_level"] == "aggregate"
        assert legacy["scope"] == "aggregate_only"
        assert legacy["verification_level"] != "verified_action"
        assert any("конкретное действие не восстанавливается" in limit.lower()
                   for limit in legacy["limitations"])
