from fastapi.testclient import TestClient

from backend.db import SessionLocal
from backend.main import app
from backend.matching import public_candidate
from backend.models import CandidateProfile, now
from test_flow import csrf, register_verified


def test_preferences_are_versioned_private_and_legacy_fields_stay_in_sync():
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = register_verified(candidate, "preferences-owner@example.test", "candidate")
        register_verified(employer, "preferences-viewer@example.test", "employer")

        empty = candidate.get("/api/v1/candidate/preferences")
        assert empty.status_code == 200, empty.text
        assert empty.json()["version"] == 1
        assert empty.json()["salary_min_rub"] is None

        saved = candidate.put("/api/v1/candidate/preferences", json={
            "expected_version": 1, "salary_min_rub": 220000,
            "allowed_work_formats": ["remote", "hybrid"],
            "allowed_cities": ["Москва", "Санкт-Петербург"],
            "excluded_industries": ["gambling"], "preferred_stack": ["Rust"],
            "preferred_tasks": ["data systems"], "max_take_home_minutes": 0,
            "available": True, "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 2
        assert saved.json()["salary_min_rub"] == 220000
        assert saved.json()["adult_hiring_confirmed"] is True

        stale = candidate.put("/api/v1/candidate/preferences", json={
            "expected_version": 1, "salary_min_rub": 180000,
            "allowed_work_formats": ["remote"], "allowed_cities": [],
            "excluded_industries": [], "preferred_stack": [], "preferred_tasks": [],
            "max_take_home_minutes": None, "available": True, "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert stale.status_code == 409
        assert stale.json()["detail"] == "PREFERENCES_VERSION_CONFLICT"

        profile = candidate.put("/api/v1/candidate/profile", json={
            "full_name": "Иван Кандидат", "contact_email": "private@example.test",
            "contact_phone": "", "city": "Москва", "summary": "Опытный специалист",
            "skills": ["Python"], "experience_months": 24, "min_salary_rub": 220000,
            "work_format": "office", "consent_processing": True, "published": True,
            "available": True, "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert profile.status_code == 200, profile.text
        assert "min_salary_rub" not in public_candidate(CandidateProfile(
            user_id=person["id"], min_salary_rub=220000, work_format="office",
            adult_attested_at=now(), published_at=now(), consent_processing_at=now(),
            available=True, verified_specialization="backend", verified_grade="middle", test_score=80,
        ))

        saved_again = candidate.get("/api/v1/candidate/preferences").json()
        assert saved_again["version"] == 3
        assert saved_again["salary_min_rub"] == 220000
        assert saved_again["allowed_work_formats"] == ["office"]
        assert saved_again["allowed_cities"] == ["Москва", "Санкт-Петербург"]
        assert employer.get("/api/v1/candidate/preferences").status_code == 403

        cleared = candidate.put("/api/v1/candidate/preferences", json={
            "expected_version": 3, "salary_min_rub": None,
            "allowed_work_formats": ["remote", "office"],
            "allowed_cities": ["Москва", "Санкт-Петербург"],
            "excluded_industries": ["gambling"], "preferred_stack": ["Rust"],
            "preferred_tasks": ["data systems"], "max_take_home_minutes": 0,
            "available": True, "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["version"] == 4
        assert cleared.json()["salary_min_rub"] is None
        assert cleared.json()["allowed_work_formats"] == ["remote", "office"]
        with SessionLocal() as db:
            legacy = db.get(CandidateProfile, person["id"])
            assert legacy.min_salary_rub == 0
            assert legacy.work_format == "any"


def test_candidate_visibility_requires_explicit_adult_attestation():
    with TestClient(app) as candidate, TestClient(app) as employer:
        register_verified(candidate, "adult-attestation@example.test", "candidate")
        register_verified(employer, "adult-attestation-employer@example.test", "employer")
        response = candidate.put("/api/v1/candidate/profile", json={
            "full_name": "Профиль без возрастной отметки", "contact_email": "private@example.test",
            "contact_phone": "", "city": "Москва", "summary": "Опыт",
            "skills": ["Python"], "experience_months": 24, "min_salary_rub": 0,
            "work_format": "remote", "consent_processing": True, "published": True,
            "available": True,
        }, headers=csrf(candidate))
        assert response.status_code == 200, response.text
        assert response.json()["published"] is True
        assert response.json()["adult_hiring_confirmed"] is False
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, response.json()["id"])
            assert profile.adult_attested_at is None
            assert set(profile.preferences) == {
                "salary_min_rub", "allowed_work_formats", "allowed_cities", "excluded_industries",
                "preferred_stack", "preferred_tasks", "max_take_home_minutes", "available",
            }
            profile.verified_specialization = "backend"
            profile.verified_grade = "middle"
            profile.test_score = 80
            db.commit()
        assert response.json()["id"] not in {
            item["id"] for item in employer.get("/api/v1/employer/candidates").json()
        }
        assert employer.get(f"/api/v1/employer/candidates/{response.json()['id']}").status_code == 404
