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
            "expected_preferences_version": 2,
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


def test_profile_update_cannot_overwrite_newer_preferences():
    with TestClient(app) as candidate:
        register_verified(candidate, "stale-profile-preferences@example.test", "candidate")
        original_profile = {
            "full_name": "Алексей Кандидат",
            "contact_email": "private@example.test",
            "contact_phone": "",
            "city": "Москва",
            "summary": "Профиль до обновления условий",
            "skills": ["Python"],
            "experience_months": 24,
            "min_salary_rub": 120000,
            "work_format": "remote",
            "consent_processing": True,
            "published": True,
            "available": True,
            "adult_hiring_confirmed": True,
        }
        created = candidate.put(
            "/api/v1/candidate/profile", json=original_profile, headers=csrf(candidate),
        )
        assert created.status_code == 200, created.text
        stale_preferences_version = created.json()["preferences_version"]

        newer = candidate.put("/api/v1/candidate/preferences", json={
            "expected_version": stale_preferences_version,
            "salary_min_rub": 260000,
            "allowed_work_formats": ["hybrid", "office"],
            "allowed_cities": ["Казань"],
            "excluded_industries": [],
            "preferred_stack": ["Python"],
            "preferred_tasks": [],
            "max_take_home_minutes": 45,
            "available": True,
            "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert newer.status_code == 200, newer.text
        assert newer.json()["version"] == stale_preferences_version + 1

        stale_profile = candidate.put(
            "/api/v1/candidate/profile",
            json=original_profile | {
                "full_name": "Старый черновик профиля",
                "expected_preferences_version": stale_preferences_version,
            },
            headers=csrf(candidate),
        )
        assert stale_profile.status_code == 409, stale_profile.text
        assert stale_profile.json()["detail"] == "PREFERENCES_VERSION_CONFLICT"
        assert stale_profile.json()["current"]["profile"]["full_name"] == "Алексей Кандидат"
        assert stale_profile.json()["current"]["preferences"]["salary_min_rub"] == 260000

        current_preferences = candidate.get("/api/v1/candidate/preferences")
        assert current_preferences.status_code == 200, current_preferences.text
        assert current_preferences.json()["version"] == stale_preferences_version + 1
        assert current_preferences.json()["salary_min_rub"] == 260000
        assert current_preferences.json()["allowed_work_formats"] == ["hybrid", "office"]
        assert current_preferences.json()["allowed_cities"] == ["Казань"]
        assert candidate.get("/api/v1/candidate/profile").json()["full_name"] == "Алексей Кандидат"


def test_profile_update_without_preference_version_cannot_overwrite_structured_preferences():
    with TestClient(app) as candidate:
        register_verified(candidate, "unversioned-profile-preferences@example.test", "candidate")
        profile = {
            "full_name": "Мария Кандидат",
            "contact_email": "private@example.test",
            "contact_phone": "",
            "city": "Москва",
            "summary": "Исходный профиль",
            "skills": ["Python"],
            "experience_months": 24,
            "min_salary_rub": 120000,
            "work_format": "remote",
            "consent_processing": True,
            "published": True,
            "available": True,
            "adult_hiring_confirmed": True,
        }
        created = candidate.put("/api/v1/candidate/profile", json=profile, headers=csrf(candidate))
        assert created.status_code == 200, created.text

        current = candidate.get("/api/v1/candidate/preferences").json()
        updated = candidate.put("/api/v1/candidate/preferences", json={
            "expected_version": current["version"],
            "salary_min_rub": 260000,
            "allowed_work_formats": ["hybrid", "office"],
            "allowed_cities": ["Казань"],
            "excluded_industries": [],
            "preferred_stack": [],
            "preferred_tasks": [],
            "max_take_home_minutes": None,
            "available": True,
            "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert updated.status_code == 200, updated.text

        current_profile = candidate.get("/api/v1/candidate/profile").json()
        stale_profile = candidate.put(
            "/api/v1/candidate/profile",
            json=profile | {
                "full_name": "Черновик без версии",
                "min_salary_rub": current_profile["min_salary_rub"],
                "work_format": current_profile["work_format"],
                "available": current_profile["available"],
            },
            headers=csrf(candidate),
        )

        assert stale_profile.status_code == 409, stale_profile.text
        assert stale_profile.json()["detail"] == "PREFERENCES_VERSION_REQUIRED"
        assert stale_profile.json()["current"]["profile"]["full_name"] == "Мария Кандидат"
        assert stale_profile.json()["current"]["preferences"]["salary_min_rub"] == 260000
        assert candidate.get("/api/v1/candidate/profile").json()["full_name"] == "Мария Кандидат"
        preserved = candidate.get("/api/v1/candidate/preferences").json()
        assert preserved["salary_min_rub"] == 260000
        assert preserved["allowed_work_formats"] == ["hybrid", "office"]


def test_candidate_preferences_get_returns_no_store():
    with TestClient(app) as candidate:
        register_verified(candidate, "preferences-cache-get@example.test", "candidate")
        response = candidate.get("/api/v1/candidate/preferences")

        assert response.status_code == 200, response.text
        assert response.headers.get("cache-control") == "no-store"


def test_candidate_preferences_put_returns_no_store():
    with TestClient(app) as candidate:
        register_verified(candidate, "preferences-cache-put@example.test", "candidate")
        response = candidate.put("/api/v1/candidate/preferences", json={
            "expected_version": 1,
            "salary_min_rub": 180000,
            "allowed_work_formats": ["remote"],
            "allowed_cities": [],
            "excluded_industries": [],
            "preferred_stack": [],
            "preferred_tasks": [],
            "max_take_home_minutes": None,
            "available": True,
            "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))

        assert response.status_code == 200, response.text
        assert response.headers.get("cache-control") == "no-store"


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
