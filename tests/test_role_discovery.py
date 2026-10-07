from datetime import timedelta
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend import seed_demo
from backend.db import Base, SessionLocal
from backend.main import app
from backend.models import CandidateProfile, EmployerProfile, HiringNeed, RoleDecision, RoleVersion, User, now
from backend.role_cards import (close_role, create_initial_draft, create_role_version,
                                pause_role, publish_role)
from backend.role_discovery import _data_mode
from backend.schemas import RoleCardIn
from test_flow import csrf, register_verified
from test_role_cards import role_payload


def create_candidate(client: TestClient, email: str, *, assessed: bool) -> dict:
    person = register_verified(client, email, "candidate")
    if not assessed:
        return person
    saved = client.put("/api/v1/candidate/profile", json={
        "full_name": "Кандидат теста", "contact_email": email, "contact_phone": "",
        "city": "Москва", "summary": "Проверка ленты ролей", "skills": ["Python"],
        "experience_months": 24, "min_salary_rub": 0, "work_format": "remote",
        "consent_processing": True, "published": True, "available": True,
        "adult_hiring_confirmed": True,
    }, headers=csrf(client))
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        profile = db.get(CandidateProfile, person["id"])
        profile.verified_specialization = "backend"
        profile.verified_grade = "middle"
        profile.test_score = 85
        profile.competencies = {"event_idempotency": 0.8}
        db.commit()
    return person


def create_public_role(employer_id: str, title: str, *, confirmed_at=None, discoverable=True,
                       **overrides) -> tuple[str, str]:
    at = confirmed_at or now()
    payload = role_payload(title=title, **overrides)
    with SessionLocal() as db:
        employer = db.get(User, employer_id)
        if db.get(EmployerProfile, employer_id) is None:
            db.add(EmployerProfile(user_id=employer_id, company_name=f"{title} — команда",
                                   description="Синтетическая компания", industry="ИТ",
                                   contact_email=employer.email))
        need = HiringNeed(
            employer_id=employer_id, title=title, description=payload["description"],
            specialization=payload["specialization"], grade=payload["grade"],
            competencies=payload["competencies"], stack=payload["stack"],
            salary_min_rub=payload["salary_min_rub"], salary_max_rub=payload["salary_max_rub"],
            work_format=payload["work_format"],
        )
        db.add(need)
        db.flush()
        create_initial_draft(db, need, actor_id=employer_id, at=at)
        version = create_role_version(db, employer_id, need.id, RoleCardIn.model_validate(payload),
                                      expected_version=1, at=at, source="synthetic_demo")
        publish_role(db, employer_id, need.id, expected_version=version.version,
                     active_headcount_attested=True, discoverable=discoverable, at=at)
        db.commit()
        return need.id, version.id


def set_preferences(client: TestClient, *, salary=220000, formats=None, industries=None,
                    take_home=60):
    return client.put("/api/v1/candidate/preferences", json={
        "expected_version": 1, "salary_min_rub": salary,
        "allowed_work_formats": formats or ["remote"], "allowed_cities": [],
        "excluded_industries": industries or [], "preferred_stack": [], "preferred_tasks": [],
        "max_take_home_minutes": take_home, "available": True, "adult_hiring_confirmed": True,
    }, headers=csrf(client))


def test_candidate_role_feed_filters_private_hard_preferences_and_omits_contact():
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = create_candidate(candidate, "role-feed-candidate@example.test", assessed=True)
        owner = register_verified(employer, "role-feed-employer@example.test", "employer")
        assert set_preferences(candidate, salary=230000, industries=["gambling"], take_home=30).status_code == 200

        compatible_id, _ = create_public_role(owner["id"], "Backend Events — совместимо",
                                              salary_min_rub=220000, salary_max_rub=250000,
                                              industry="ИТ", take_home_minutes=20)
        unknown_id, _ = create_public_role(owner["id"], "Backend Events — неизвестная отрасль",
                                           salary_min_rub=220000, salary_max_rub=250000,
                                           industry=None, take_home_minutes=20)
        low_salary_id, _ = create_public_role(owner["id"], "Backend Events — ниже минимума",
                                              salary_min_rub=150000, salary_max_rub=200000,
                                              industry="ИТ", take_home_minutes=20)
        office_id, _ = create_public_role(owner["id"], "Backend Events — офис",
                                          salary_min_rub=220000, salary_max_rub=250000,
                                          work_format="office", work_city="Москва", industry="ИТ", take_home_minutes=20)
        long_test_id, _ = create_public_role(owner["id"], "Backend Events — длинное тестовое",
                                             salary_min_rub=220000, salary_max_rub=250000,
                                             industry="ИТ", take_home_minutes=90)
        excluded_industry_id, _ = create_public_role(owner["id"], "Backend Events — исключённая отрасль",
                                                     salary_min_rub=220000, salary_max_rub=250000,
                                                     industry="gambling", take_home_minutes=20)

        response = candidate.get("/api/v1/candidate/roles")
        assert response.status_code == 200, response.text
        feed = response.json()
        by_id = {item["need_id"]: item for item in feed["items"]}
        assert {compatible_id, unknown_id}.issubset(by_id)
        assert not {low_salary_id, office_id, long_test_id, excluded_industry_id}.intersection(by_id)
        assert by_id[compatible_id]["match_state"] == "compatible"
        assert by_id[unknown_id]["match_state"] == "needs_clarification"
        # Public role salary values may coincidentally equal the candidate's
        # private minimum, so verify the response contract rather than searching
        # the whole JSON for a number that is legitimately present in a role.
        assert all(not {"preferences", "candidate_preferences", "min_salary_rub", "salary_min_rub"}.intersection(item)
                   for item in feed["items"])
        assert all("salary_min_rub" in item["role"] for item in feed["items"])
        without_public_role_salaries = [
            {**item, "role": {key: value for key, value in item["role"].items()
                              if key not in {"salary_min_rub", "salary_max_rub"}}}
            for item in feed["items"]
        ]
        assert "230000" not in json.dumps(without_public_role_salaries, ensure_ascii=False)
        assert "gambling" not in response.text
        assert all("employer_contact" not in item["role"] for item in feed["items"])
        assert all("role-feed-employer@example.test" not in str(item) for item in feed["items"])
        assert by_id[compatible_id]["data_mode"] == "synthetic"


def test_role_feed_and_decisions_reject_contact_details_embedded_in_public_text():
    with (TestClient(app) as candidate, TestClient(app) as email_employer,
          TestClient(app) as phone_employer, TestClient(app) as international_phone_employer,
          TestClient(app) as company_employer):
        create_candidate(candidate, "role-feed-contact-text@example.test", assessed=False)
        email_owner = register_verified(email_employer, "role-feed-contact-email@example.test", "employer")
        phone_owner = register_verified(phone_employer, "role-feed-contact-phone@example.test", "employer")
        international_phone_owner = register_verified(
            international_phone_employer, "role-feed-contact-international@example.test", "employer",
        )
        company_owner = register_verified(company_employer, "role-feed-contact-company@example.test", "employer")

        email_need_id, email_version_id = create_public_role(
            email_owner["id"], "Backend Middle — email в описании",
            description="Команда ищет инженера; напишите talent@example.test для связи.",
        )
        phone_need_id, _ = create_public_role(
            phone_owner["id"], "Backend Middle — телефон в плане",
            first_30_days="Позвоните нам по номеру +7 999 123-45-67 и обсудим первые задачи.",
        )
        dated_need_id, _ = create_public_role(
            phone_owner["id"], "Backend Middle — дата релиза",
            description="Релиз запланирован на 2026-10-06; дата входит в план работ.",
        )
        international_phone_need_id, _ = create_public_role(
            international_phone_owner["id"], "Backend Middle — международный телефон",
            first_30_days="Позвоните по номеру 415-555-2671, чтобы обсудить первые задачи.",
        )
        company_need_id, _ = create_public_role(
            company_owner["id"], "Backend Middle — email в названии компании",
        )
        with SessionLocal() as db:
            company = db.get(EmployerProfile, company_owner["id"])
            company.company_name = "Команда — hr@example.test"
            db.commit()

        response = candidate.get("/api/v1/candidate/roles")
        assert response.status_code == 200, response.text
        visible_ids = {item["need_id"] for item in response.json()["items"]}
        assert not {email_need_id, phone_need_id, international_phone_need_id,
                    company_need_id}.intersection(visible_ids)
        assert dated_need_id in visible_ids
        assert "talent@example.test" not in response.text
        assert "+7 999 123-45-67" not in response.text
        assert "415-555-2671" not in response.text
        assert "hr@example.test" not in response.text

        decision = candidate.put(f"/api/v1/candidate/role-decisions/{email_need_id}", json={
            "action": "saved", "expected_role_version": email_version_id,
            "expected_preferences_version": 1,
        }, headers=csrf(candidate))
        assert decision.status_code == 404


def test_candidate_can_browse_without_profile_and_get_is_read_only():
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = create_candidate(candidate, "role-feed-no-profile@example.test", assessed=False)
        owner = register_verified(employer, "role-feed-no-profile-employer@example.test", "employer")
        need_id, _ = create_public_role(owner["id"], "Backend Events — до теста")

        response = candidate.get("/api/v1/candidate/roles")
        assert response.status_code == 200, response.text
        item = next(role for role in response.json()["items"] if role["need_id"] == need_id)
        assert item["match_state"] == "not_assessed"
        assert item["compatibility"] is None
        with SessionLocal() as db:
            assert db.get(CandidateProfile, person["id"]) is None


def test_unknown_hard_preference_stays_needs_clarification_without_verified_category():
    with TestClient(app) as candidate, TestClient(app) as employer:
        create_candidate(candidate, "role-feed-unknown-no-category@example.test", assessed=False)
        owner = register_verified(employer, "role-feed-unknown-no-category-employer@example.test", "employer")
        assert set_preferences(candidate, salary=100000, industries=["gambling"]).status_code == 200
        need_id, _ = create_public_role(
            owner["id"], "Backend Middle — отрасль не указана", industry=None,
        )

        response = candidate.get("/api/v1/candidate/roles")
        assert response.status_code == 200, response.text
        item = next(role for role in response.json()["items"] if role["need_id"] == need_id)
        assert item["match_state"] == "needs_clarification"
        assert "gambling" not in response.text
        assert "100000" not in response.text


def test_candidate_role_feed_uses_stable_five_item_keyset_pages():
    with TestClient(app) as candidate, TestClient(app) as employer:
        create_candidate(candidate, "role-feed-pages@example.test", assessed=True)
        owner = register_verified(employer, "role-feed-pages-employer@example.test", "employer")
        created_at = now()
        expected_ids = {
            create_public_role(
                owner["id"], f"Frontend Junior — страница {index}", confirmed_at=created_at,
                specialization="frontend", grade="junior", competencies=["javascript_trace"],
            )[0]
            for index in range(7)
        }

        filters = {"specialization": "frontend", "grade": "junior", "work_format": "remote"}
        first = candidate.get("/api/v1/candidate/roles", params=filters)
        assert first.status_code == 200, first.text
        first_page = first.json()
        assert first_page["limit"] == 5
        assert len(first_page["items"]) == 5
        assert first_page["next_cursor"]
        second = candidate.get("/api/v1/candidate/roles", params=filters | {"cursor": first_page["next_cursor"]})
        assert second.status_code == 200, second.text
        second_page = second.json()
        all_ids = [item["need_id"] for item in first_page["items"] + second_page["items"]]
        assert len(all_ids) == len(set(all_ids)) == 7
        assert set(all_ids) == expected_ids
        replay = candidate.get("/api/v1/candidate/roles", params=filters | {"cursor": first_page["next_cursor"]})
        assert replay.json() == second_page
        wrong_filters = candidate.get("/api/v1/candidate/roles", params={
            "cursor": first_page["next_cursor"], "specialization": "backend", "grade": "junior",
        })
        assert wrong_filters.status_code == 422
        assert candidate.get("/api/v1/candidate/roles", params={"limit": 21}).status_code == 422


def test_discovery_excludes_stale_paused_closed_private_and_blocked_roles():
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as blocked_employer:
        person = create_candidate(candidate, "role-visibility-candidate@example.test", assessed=True)
        owner = register_verified(employer, "role-visibility-employer@example.test", "employer")
        blocked_owner = register_verified(blocked_employer, "role-visibility-blocked@example.test", "employer")
        active_id, _ = create_public_role(owner["id"], "Backend Middle — публичная")
        stale_id, _ = create_public_role(owner["id"], "Backend Middle — устарела",
                                         confirmed_at=now() - timedelta(days=15))
        paused_id, _ = create_public_role(owner["id"], "Backend Middle — пауза")
        closed_id, _ = create_public_role(owner["id"], "Backend Middle — закрыта")
        private_id, _ = create_public_role(owner["id"], "Backend Middle — приватная", discoverable=False)
        blocked_id, _ = create_public_role(blocked_owner["id"], "Backend Middle — заблокирована")
        with SessionLocal() as db:
            for need_id, transition in ((paused_id, pause_role), (closed_id, close_role)):
                need = db.get(HiringNeed, need_id)
                transition(db, owner["id"], need_id,
                           expected_version=need.current_role_version, at=now())
            profile = db.get(CandidateProfile, person["id"])
            profile.blocked_employer_ids = [blocked_owner["id"]]
            db.commit()

        feed = candidate.get("/api/v1/candidate/roles").json()
        visible_ids = {item["need_id"] for item in feed["items"]}
        assert active_id in visible_ids
        assert not {stale_id, paused_id, closed_id, private_id, blocked_id}.intersection(visible_ids)


def test_candidate_can_save_hide_and_undo_without_creating_a_profile():
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = create_candidate(candidate, "role-decisions-no-profile@example.test", assessed=False)
        owner = register_verified(employer, "role-decisions-no-profile-employer@example.test", "employer")
        need_id, version_id = create_public_role(
            owner["id"], "Frontend Junior — личная подборка", specialization="frontend",
            grade="junior", competencies=["javascript_trace"],
        )
        filters = {"specialization": "frontend", "grade": "junior"}
        feed = candidate.get("/api/v1/candidate/roles", params=filters).json()
        item = next(role for role in feed["items"] if role["need_id"] == need_id)
        assert item["decision"] == "none"

        def decide(action: str):
            return candidate.put(f"/api/v1/candidate/role-decisions/{need_id}", json={
                "action": action, "expected_role_version": version_id,
                "expected_preferences_version": 1,
            }, headers=csrf(candidate))

        saved = decide("saved")
        assert saved.status_code == 200, saved.text
        saved_feed = candidate.get("/api/v1/candidate/roles", params=filters | {"saved_only": "true"}).json()
        saved_item = next(role for role in saved_feed["items"] if role["need_id"] == need_id)
        assert saved_item["decision"] == "saved"

        hidden = decide("hidden")
        assert hidden.status_code == 200, hidden.text
        hidden_feed = candidate.get("/api/v1/candidate/roles", params=filters).json()
        assert need_id not in {role["need_id"] for role in hidden_feed["items"]}
        assert need_id not in {role["need_id"] for role in candidate.get(
            "/api/v1/candidate/roles", params=filters | {"saved_only": "true"}
        ).json()["items"]}

        undone = decide("none")
        assert undone.status_code == 200, undone.text
        restored = candidate.get("/api/v1/candidate/roles", params=filters).json()
        restored_item = next(role for role in restored["items"] if role["need_id"] == need_id)
        assert restored_item["decision"] == "none"
        with SessionLocal() as db:
            assert db.get(CandidateProfile, person["id"]) is None


def test_stale_role_and_preferences_versions_do_not_mutate_a_saved_decision():
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = create_candidate(candidate, "role-decisions-stale@example.test", assessed=True)
        owner = register_verified(employer, "role-decisions-stale-employer@example.test", "employer")
        assert set_preferences(candidate, salary=180000).status_code == 200
        need_id, old_version_id = create_public_role(owner["id"], "Backend Middle — версии решения")
        saved = candidate.put(f"/api/v1/candidate/role-decisions/{need_id}", json={
            "action": "saved", "expected_role_version": old_version_id,
            "expected_preferences_version": 2,
        }, headers=csrf(candidate))
        assert saved.status_code == 200, saved.text

        with SessionLocal() as db:
            need = db.get(HiringNeed, need_id)
            previous = db.scalar(select(RoleVersion).where(
                RoleVersion.need_id == need_id, RoleVersion.version == need.current_role_version
            ))
            updated_payload = dict(previous.payload, salary_max_rub=260000)
            new_version = create_role_version(
                db, owner["id"], need_id, RoleCardIn.model_validate(updated_payload),
                expected_version=need.current_role_version, at=now(), source="synthetic_demo",
            )
            publish_role(db, owner["id"], need_id, expected_version=new_version.version,
                         active_headcount_attested=True, discoverable=True, at=now())
            new_version_id = new_version.id
            db.commit()

        stale_role = candidate.put(f"/api/v1/candidate/role-decisions/{need_id}", json={
            "action": "hidden", "expected_role_version": old_version_id,
            "expected_preferences_version": 2,
        }, headers=csrf(candidate))
        assert stale_role.status_code == 409
        assert stale_role.json()["detail"] == "ROLE_VERSION_CONFLICT"

        updated_preferences = candidate.put("/api/v1/candidate/preferences", json={
            "expected_version": 2, "salary_min_rub": 190000,
            "allowed_work_formats": ["remote"], "allowed_cities": [], "excluded_industries": [],
            "preferred_stack": [], "preferred_tasks": [], "max_take_home_minutes": 60,
            "available": True, "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert updated_preferences.status_code == 200, updated_preferences.text
        stale_preferences = candidate.put(f"/api/v1/candidate/role-decisions/{need_id}", json={
            "action": "hidden", "expected_role_version": new_version_id,
            "expected_preferences_version": 2,
        }, headers=csrf(candidate))
        assert stale_preferences.status_code == 409
        assert stale_preferences.json()["detail"] == "PREFERENCES_VERSION_CONFLICT"
        with SessionLocal() as db:
            decision = db.scalar(select(RoleDecision).where(
                RoleDecision.candidate_id == person["id"], RoleDecision.need_id == need_id
            ))
            assert decision.action == "saved"
            assert decision.role_version_id == old_version_id
            assert decision.preferences_version == 2


def test_candidate_role_decisions_do_not_accept_interest_in_h0():
    with TestClient(app) as candidate, TestClient(app) as employer:
        create_candidate(candidate, "role-decisions-no-interest@example.test", assessed=True)
        owner = register_verified(employer, "role-decisions-no-interest-employer@example.test", "employer")
        need_id, version_id = create_public_role(owner["id"], "Backend Middle — без интереса")
        response = candidate.put(f"/api/v1/candidate/role-decisions/{need_id}", json={
            "action": "interested", "expected_role_version": version_id,
            "expected_preferences_version": 1,
        }, headers=csrf(candidate))
        assert response.status_code == 422


def test_demo_and_test_app_modes_always_label_direct_signup_roles_synthetic(monkeypatch):
    employer = SimpleNamespace(origin="direct_signup")
    version = SimpleNamespace(source="employer_declared")
    for app_mode in ("demo", "test"):
        monkeypatch.setattr("backend.role_discovery.settings", SimpleNamespace(app_mode=app_mode), raising=False)
        assert _data_mode(version, employer) == "synthetic"

    monkeypatch.setattr("backend.role_discovery.settings", SimpleNamespace(app_mode="live"), raising=False)
    assert _data_mode(version, employer) == "real"
    assert _data_mode(SimpleNamespace(source="legacy_import"), employer) == "unknown"
    assert _data_mode(version, SimpleNamespace(origin="legacy_import")) == "unknown"
    assert _data_mode(SimpleNamespace(source="legacy_import"),
                      SimpleNamespace(origin="synthetic_fixture")) == "synthetic"


def test_demo_seed_has_repeatable_discovery_roles_without_changing_primary_need(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    Base.metadata.create_all(engine)
    local_sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(seed_demo, "SessionLocal", local_sessions)
    monkeypatch.setattr(seed_demo, "settings", SimpleNamespace(app_mode="demo"))

    seed_demo.seed()
    with local_sessions() as db:
        primary = db.scalar(select(User).where(User.email == "employer@demo.test"))
        secondary = db.scalar(select(User).where(User.email == "other@demo.test"))
        primary_needs = db.scalars(select(HiringNeed).where(HiringNeed.employer_id == primary.id)).all()
        discovery_needs = db.scalars(select(HiringNeed).where(HiringNeed.employer_id == secondary.id)).all()
        first_snapshot = sorted((need.id, need.current_role_version, need.publication_state)
                                for need in discovery_needs)
        assert [need.title for need in primary_needs] == ["Backend Middle: события"]
        assert len(discovery_needs) >= 4
        assert {need.specialization for need in discovery_needs} == {"backend", "frontend"}
        assert {need.grade for need in discovery_needs} == {"junior", "middle"}
        assert all(need.publication_state == "active" and need.discoverable for need in discovery_needs)
        assert all(need.confirmed_at is not None for need in discovery_needs)
        assert len({need.confirmed_at for need in discovery_needs}) == len(discovery_needs)
        versions = db.scalars(select(RoleVersion).where(
            RoleVersion.need_id.in_([need.id for need in discovery_needs])
        )).all()
        assert len(versions) == len(discovery_needs)
        assert all(version.source == "synthetic_demo" for version in versions)
        assert {version.payload["work_format"] for version in versions} == {"remote", "hybrid", "office"}
        fixture_profiles = db.scalars(select(CandidateProfile).join(
            User, User.id == CandidateProfile.user_id
        ).where(User.role == "candidate", User.origin == "synthetic_fixture")).all()
        assert len(fixture_profiles) == 48
        browser_candidate = db.scalar(select(User).where(User.email == "new-candidate@demo.test"))
        assert browser_candidate and browser_candidate.origin == "synthetic_fixture"
        assert db.get(CandidateProfile, browser_candidate.id) is None

    seed_demo.seed()
    with local_sessions() as db:
        secondary = db.scalar(select(User).where(User.email == "other@demo.test"))
        discovery_needs = db.scalars(select(HiringNeed).where(HiringNeed.employer_id == secondary.id)).all()
        second_snapshot = sorted((need.id, need.current_role_version, need.publication_state)
                                 for need in discovery_needs)
        assert second_snapshot == first_snapshot
    engine.dispose()
