from dataclasses import replace
from importlib import import_module
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.db import SessionLocal
from backend.config import settings
from backend.matching import eligible
from backend.main import app
from backend.models import CandidateProfile, HiringNeed, RoleVersion, now
from backend.schemas import RoleCardIn
from test_flow import csrf, register_verified
from test_role_cards import role_payload


def make_search_context(employer, candidate, *, extra_skills=None):
    suffix = uuid4().hex[:10]
    employer_user = register_verified(employer, f"snapshot-{suffix}-employer@example.test", "employer")
    candidate_user = make_candidate_profile(candidate, extra_skills=extra_skills,
                                            email=f"snapshot-{suffix}-candidate@example.test")
    employer.put("/api/v1/employer/company", json={
        "company_name": "Snapshot Demo", "description": "", "industry": "ИТ",
        "contact_email": "team@example.test",
    }, headers=csrf(employer))
    need = employer.post("/api/v1/employer/needs", json={
        "title": "Backend Middle", "description": "Обработка событий надёжно",
        "specialization": "backend", "grade": "middle",
        "competencies": ["event_idempotency"], "stack": ["Python"],
        "salary_min_rub": 180000, "salary_max_rub": 230000, "work_format": "remote",
    }, headers=csrf(employer))
    assert need.status_code == 201, need.text
    need_id = need.json()["id"]
    with SessionLocal() as db:
        need_row = db.get(HiringNeed, need_id)
        role = db.query(RoleVersion).filter_by(need_id=need_id, version=need_row.current_role_version).one()
        role_version_id = role.id
    return employer_user, candidate_user, need_id, role_version_id


def make_candidate_profile(candidate, *, extra_skills=None, email=None):
    suffix = uuid4().hex[:10]
    candidate_user = register_verified(
        candidate, email or f"snapshot-{suffix}-candidate@example.test", "candidate"
    )
    with SessionLocal() as db:
        profile = CandidateProfile(user_id=candidate_user["id"])
        profile.verified_specialization = "backend"
        profile.verified_grade = "middle"
        profile.test_score = 90
        profile.verification_source = "assessment"
        profile.test_verified_at = now()
        profile.competencies = {"event_idempotency": 0.8}
        profile.skills = ["Python", *(extra_skills or [])]
        profile.consent_processing_at = now()
        profile.published_at = now()
        profile.adult_attested_at = now()
        profile.available = True
        profile.preferences = {
            "salary_min_rub": 220000,
            "allowed_work_formats": ["remote"],
            "allowed_cities": [], "excluded_industries": [],
            "preferred_stack": [], "preferred_tasks": [],
            "max_take_home_minutes": None, "available": True,
        }
        profile.preferences_version = 1
        db.add(profile)
        db.commit()
    return candidate_user


def test_snapshot_pins_search_inputs_and_reports_changed_candidate_values():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, role_version_id = make_search_context(employer, candidate)
        listed_need = next(item for item in employer.get("/api/v1/employer/needs").json()
                           if item["id"] == need_id)
        assert listed_need["stack"] == ["Python"]
        assert listed_need["role_version_id"] == role_version_id

        found = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": role_version_id,
        }, headers=csrf(employer))
        assert found.status_code == 201, found.text
        snapshot = found.json()
        assert snapshot["role_version_id"] == role_version_id
        assert snapshot["algorithm_version"] == "match_v1"
        row = next(item for item in snapshot["results"] if item["id"] == candidate_user["id"])
        assert row["snapshot_inputs"]["test_score"] == 90
        assert row["snapshot_inputs"]["competencies"] == {"event_idempotency": 0.8}
        assert row["snapshot_inputs"]["preferences_version"] == 1
        assert row["snapshot_inputs"]["assessment_source"]["type"] == "assessment"
        assert row["match"]["explanation"]["reasons"]
        assert row["match"]["algorithm_version"] == "match_v1"
        assert "salary_min_rub" not in str(snapshot)
        assert "achievement_story" not in str(snapshot)

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.test_score = 75
            profile.competencies = {"event_idempotency": 0.2}
            profile.preferences_version = 2
            db.commit()

        restored = employer.get(f"/api/v1/employer/searches/{snapshot['id']}")
        assert restored.status_code == 200, restored.text
        restored_row = next(item for item in restored.json()["results"]
                            if item["id"] == candidate_user["id"])
        assert restored_row["test_score"] == 75
        assert restored_row["match"] == row["match"]
        assert restored_row["snapshot_inputs"]["test_score"] == 90
        assert restored_row["snapshot_inputs"]["competencies"] == {"event_idempotency": 0.8}
        assert restored_row["changed_since_search"] is True


def test_snapshot_rechecks_current_consent_availability_and_block_state():
    with TestClient(app) as employer, TestClient(app) as candidate:
        employer_user, candidate_user, need_id, role_version_id = make_search_context(employer, candidate)
        found = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": role_version_id,
        }, headers=csrf(employer))
        snapshot_id = found.json()["id"]

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.consent_processing_at = None
            db.commit()
        def assert_candidate_is_hidden():
            restored = employer.get(f"/api/v1/employer/searches/{snapshot_id}")
            assert restored.status_code == 200
            assert candidate_user["id"] not in {row["id"] for row in restored.json()["results"]}
            assert restored.json()["unavailable_count"] >= 1

        assert_candidate_is_hidden()

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.consent_processing_at = now()
            profile.available = False
            db.commit()
        assert_candidate_is_hidden()

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.available = True
            profile.blocked_employer_ids = [employer_user["id"]]
            db.commit()
        assert_candidate_is_hidden()


def test_role_version_is_pinned_and_stale_parent_cannot_start_a_new_search():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, _, need_id, initial_role_version_id = make_search_context(employer, candidate)
        first = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": initial_role_version_id,
        }, headers=csrf(employer))
        assert first.status_code == 201, first.text

        revised = employer.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 1, "card": role_payload(description="Обработка событий новой версии")},
            headers=csrf(employer),
        )
        assert revised.status_code == 201, revised.text
        with SessionLocal() as db:
            current = db.query(RoleVersion).filter_by(need_id=need_id, version=2).one()
            current_role_version_id = current.id

        stale = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": initial_role_version_id,
        }, headers=csrf(employer))
        assert stale.status_code == 409
        assert stale.json()["detail"] == "ROLE_VERSION_CONFLICT"

        wrong_parent = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": current_role_version_id,
            "parent_snapshot_id": first.json()["id"],
        }, headers=csrf(employer))
        assert wrong_parent.status_code == 409
        assert wrong_parent.json()["detail"] == "ROLE_VERSION_CONFLICT"


def test_search_filter_stack_is_unioned_with_role_stack():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, role_version_id = make_search_context(
            employer, candidate, extra_skills=["Rust"]
        )

        found = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": role_version_id, "stack": ["Rust"],
        }, headers=csrf(employer))

        assert found.status_code == 201, found.text
        assert candidate_user["id"] in {row["id"] for row in found.json()["results"]}

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.skills = ["Python"]
            db.commit()
        excluded = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": role_version_id, "stack": ["Rust"],
        }, headers=csrf(employer))
        assert excluded.status_code == 201
        assert candidate_user["id"] not in {row["id"] for row in excluded.json()["results"]}


def test_match_v2_is_selected_by_config_and_bank_score_has_no_fsp_bonus(monkeypatch):
    main_module = import_module("backend.main")
    matching_module = import_module("backend.matching")
    v2_settings = replace(settings, match_algorithm_version="match_v2")
    monkeypatch.setattr(main_module, "settings", v2_settings)
    monkeypatch.setattr(matching_module, "settings", v2_settings)

    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(
            employer, candidate, extra_skills=["PostgreSQL"]
        )
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.fsp_status = "verified_external"
            profile.fsp_result = "prize"
            db.commit()
        revised = employer.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 1, "card": role_payload()},
            headers=csrf(employer),
        )
        assert revised.status_code == 201, revised.text
        with SessionLocal() as db:
            role_version_id = db.query(RoleVersion).filter_by(need_id=need_id, version=2).one().id

        found = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": role_version_id,
        }, headers=csrf(employer))
        assert found.status_code == 201, found.text
        row = next(item for item in found.json()["results"] if item["id"] == candidate_user["id"])
        assert found.json()["algorithm_version"] == "match_v2"
        assert row["match"]["algorithm_version"] == "match_v2"
        assert row["match"]["score"] == 90.0
        assert row["match"]["components"] == {
            "competencies": None, "assessment": 0.9, "text": None,
        }
        assert row["match"]["evidence_coverage"] == 0.35
        assert set(row["match"]["components"]) == {"competencies", "assessment", "text"}

        bank = employer.get("/api/v1/employer/candidates?specialization=backend&grade=middle").json()
        candidate_card = next(item for item in bank if item["id"] == candidate_user["id"])
        assert candidate_card["bank_score"] == 90.0
        assert candidate_card["bank_score_algorithm_version"] == "match_v2"


def test_search_result_ties_use_test_score_then_stable_candidate_id():
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as second_candidate:
        _, candidate_user, need_id, role_version_id = make_search_context(employer, candidate)
        second_user = make_candidate_profile(second_candidate)
        with SessionLocal() as db:
            for candidate_id in (candidate_user["id"], second_user["id"]):
                profile = db.get(CandidateProfile, candidate_id)
                profile.test_score = 88
                profile.competencies = {"event_idempotency": 0.75}
            db.commit()

        def search_ids():
            response = employer.post("/api/v1/employer/searches", json={
                "need_id": need_id, "role_version_id": role_version_id,
            }, headers=csrf(employer))
            assert response.status_code == 201, response.text
            return [item["id"] for item in response.json()["results"]]

        first = search_ids()
        second = search_ids()
        assert first == second
        tied_ids = {candidate_user["id"], second_user["id"]}
        assert [candidate_id for candidate_id in first if candidate_id in tied_ids] == sorted(tied_ids)


def test_search_applies_private_hard_preferences_without_serializing_them():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(
            employer, candidate, extra_skills=["PostgreSQL"]
        )
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.preferences = {
                "salary_min_rub": 220000,
                "allowed_work_formats": ["remote"],
                "allowed_cities": ["Санкт-Петербург"],
                "excluded_industries": ["gambling"],
                "preferred_stack": [], "preferred_tasks": [],
                "max_take_home_minutes": 0, "available": True,
            }
            db.commit()
        role = role_payload(
            salary_min_rub=80000, salary_max_rub=100000,
            work_format="office", work_city="Москва", industry="gambling",
            take_home_minutes=60,
        )
        revised = employer.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 1, "card": role},
            headers=csrf(employer),
        )
        assert revised.status_code == 201, revised.text
        with SessionLocal() as db:
            role_version_id = db.query(RoleVersion).filter_by(need_id=need_id, version=2).one().id
            profile = db.get(CandidateProfile, candidate_user["id"])
            assert eligible(profile, RoleCardIn.model_validate(role)) is False

        found = employer.post("/api/v1/employer/searches", json={
            "need_id": need_id, "role_version_id": role_version_id,
        }, headers=csrf(employer))
        assert found.status_code == 201, found.text
        assert candidate_user["id"] not in {row["id"] for row in found.json()["results"]}
        assert "220000" not in found.text
        assert "gambling" not in found.text
