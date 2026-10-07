from datetime import datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.db import SessionLocal
from backend.main import app
from backend.models import CandidateProfile, HiringNeed, ProductEvent, PromotionCampaign, RoleVersion, now
from backend.role_cards import close_role, create_role_version, pause_role
from backend.schemas import RoleCardIn
from test_flow import csrf, register_verified
from test_role_discovery import create_candidate, create_public_role, set_preferences
from test_role_cards import role_payload


def activate(client: TestClient, need_id: str):
    return client.post(f"/api/v1/employer/needs/{need_id}/promotion/demo", headers=csrf(client))


def clear_campaigns():
    with SessionLocal() as db:
        db.query(PromotionCampaign).delete()
        db.query(ProductEvent).filter(ProductEvent.type.in_(
            ("promotion_demo_activated", "sponsored_role_impression", "sponsored_role_decision"),
        )).delete()
        db.commit()


@pytest.fixture(autouse=True)
def isolate_campaign_state():
    clear_campaigns()
    yield
    clear_campaigns()


def test_demo_campaign_is_owned_current_and_lasts_fourteen_days():
    with (TestClient(app) as employer, TestClient(app) as other_employer,
          TestClient(app) as candidate):
        owner = register_verified(employer, "promotion-owner@example.test", "employer")
        other = register_verified(other_employer, "promotion-other@example.test", "employer")
        create_candidate(candidate, "promotion-candidate@example.test", assessed=False)
        need_id, role_version_id = create_public_role(owner["id"], "Promoted backend role")

        response = activate(employer, need_id)
        assert response.status_code == 201, response.text
        campaign = response.json()
        assert campaign["need_id"] == need_id
        assert campaign["role_version_id"] == role_version_id
        assert campaign["demo_only"] is True
        assert campaign["revenue_rub"] == 0
        assert (datetime.fromisoformat(campaign["active_until"]) -
                datetime.fromisoformat(campaign["active_from"])) == timedelta(days=14)
        assert activate(candidate, need_id).status_code == 403

        replay = activate(employer, need_id)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == campaign["id"]
        assert activate(other_employer, need_id).status_code == 404

        with SessionLocal() as db:
            stored = db.get(HiringNeed, need_id)
            assert stored is not None and stored.publication_state == "active"
            assert not hasattr(stored, "promotion_price_rub")
            event = db.scalar(select(ProductEvent).where(
                ProductEvent.type == "promotion_demo_activated",
                ProductEvent.entity_id == campaign["id"],
            ))
            assert event is not None
            assert event.data_mode == "synthetic"
            assert event.payload == {"role_version_id": role_version_id}
            assert event.payload.get("revenue_rub", 0) == 0


def test_demo_campaign_activation_requires_active_discoverable_current_role():
    with TestClient(app) as employer:
        owner = register_verified(employer, "promotion-state-owner@example.test", "employer")
        need_id, _ = create_public_role(owner["id"], "Paused promoted role")
        with SessionLocal() as db:
            pause_role(db, owner["id"], need_id, expected_version=2, at=now())
            db.commit()
        assert activate(employer, need_id).status_code == 409

        closed_id, _ = create_public_role(owner["id"], "Closed promoted role")
        with SessionLocal() as db:
            close_role(db, owner["id"], closed_id, expected_version=2, at=now())
            db.commit()
        assert activate(employer, closed_id).status_code == 409

        undiscoverable_id, _ = create_public_role(
            owner["id"], "Private promoted role", discoverable=False,
        )
        assert activate(employer, undiscoverable_id).status_code == 409

        draft = employer.post("/api/v1/employer/needs", json={
            "title": "Draft role", "description": "Role still needs details",
            "specialization": "backend", "grade": "middle", "competencies": ["event_idempotency"],
            "stack": ["Python"], "salary_min_rub": 100000, "salary_max_rub": 180000,
            "work_format": "remote",
        }, headers=csrf(employer))
        assert draft.status_code in (200, 201), draft.text
        draft_need = draft.json()["id"]
        assert activate(employer, draft_need).status_code == 409


def test_only_current_active_campaign_is_sponsored_and_preferences_stay_hard():
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = create_candidate(candidate, "promotion-eligibility-candidate@example.test", assessed=True)
        owner = register_verified(employer, "promotion-eligibility-employer@example.test", "employer")
        assert set_preferences(candidate, salary=230000, formats=["remote", "hybrid"],
                               cities=["Москва"], take_home=30).status_code == 200

        eligible, _ = create_public_role(
            owner["id"], "Eligible promoted backend", salary_min_rub=220000,
            salary_max_rub=260000, work_format="remote", industry="ИТ", take_home_minutes=20,
        )
        low_salary, _ = create_public_role(
            owner["id"], "Too low promoted backend", salary_min_rub=140000,
            salary_max_rub=200000, work_format="remote", industry="ИТ", take_home_minutes=20,
        )
        office, _ = create_public_role(
            owner["id"], "Office promoted backend", salary_min_rub=240000,
            salary_max_rub=260000, work_format="office", work_city="Москва", industry="ИТ",
            take_home_minutes=20,
        )
        distant_hybrid, _ = create_public_role(
            owner["id"], "Distant hybrid promoted backend", salary_min_rub=240000,
            salary_max_rub=260000, work_format="hybrid", work_city="Казань", industry="ИТ",
            take_home_minutes=20,
        )
        for need_id in (eligible, low_salary, office, distant_hybrid):
            assert activate(employer, need_id).status_code == 201

        first = candidate.get("/api/v1/candidate/roles").json()
        sponsored = first["sponsored_items"]
        assert [item["need_id"] for item in sponsored] == [eligible], [
            (item["need_id"], item["role"]["title"], item["role"]["work_format"],
             item["compatibility"]["status"] if item["compatibility"] else None,
             [(check["code"], check["status"]) for check in (item["compatibility"]["checks"] if item["compatibility"] else [])])
            for item in sponsored
        ]
        assert not {eligible}.intersection(item["need_id"] for item in first["items"])
        assert not {low_salary, office, distant_hybrid}.intersection(
            item["need_id"] for item in sponsored
        )
        assert all(item["match_state"] == "compatible" for item in sponsored)

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person["id"])
            profile.blocked_employer_ids = [owner["id"]]
            db.commit()
        blocked = candidate.get("/api/v1/candidate/roles").json()
        assert blocked["sponsored_items"] == []

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person["id"])
            profile.blocked_employer_ids = []
            db.commit()
        save = candidate.put(f"/api/v1/candidate/role-decisions/{eligible}", json={
            "action": "hidden", "expected_role_version": sponsored[0]["role_version_id"],
            "expected_preferences_version": sponsored[0]["preferences_version"],
            "source_campaign_id": sponsored[0]["campaign_id"],
        }, headers=csrf(candidate))
        assert save.status_code == 200, save.text
        hidden = candidate.get("/api/v1/candidate/roles").json()
        assert eligible not in {item["need_id"] for item in hidden["sponsored_items"]}
        with SessionLocal() as db:
            decision_event = db.scalar(select(ProductEvent).where(
                ProductEvent.type == "sponsored_role_decision",
                ProductEvent.entity_id == sponsored[0]["campaign_id"],
            ))
            assert decision_event is not None
            assert decision_event.payload == {
                "role_version_id": sponsored[0]["role_version_id"], "action": "hidden",
            }

        saved_only = candidate.get("/api/v1/candidate/roles", params={"saved_only": "true"}).json()
        assert saved_only["sponsored_items"] == []


def test_sponsored_impression_is_eligibility_checked_and_deduplicated_per_day():
    with TestClient(app) as candidate, TestClient(app) as employer:
        person = create_candidate(candidate, "promotion-impression-candidate@example.test", assessed=True)
        owner = register_verified(employer, "promotion-impression-employer@example.test", "employer")
        need_id, _ = create_public_role(owner["id"], "Visible sponsored role")
        campaign = activate(employer, need_id).json()

        first = candidate.get("/api/v1/candidate/roles").json()
        item = next(item for item in first["sponsored_items"] if item["campaign_id"] == campaign["id"])
        assert item["match_state"] == "compatible"
        for _ in range(3):
            response = candidate.post(
                f"/api/v1/candidate/promotions/{campaign['id']}/impression", headers=csrf(candidate),
            )
            assert response.status_code == 200, response.text

        with SessionLocal() as db:
            events = db.scalars(select(ProductEvent).where(
                ProductEvent.type == "sponsored_role_impression",
                ProductEvent.entity_id == campaign["id"],
                ProductEvent.actor_id == person["id"],
            )).all()
            assert len(events) == 1
            assert events[0].data_mode == "synthetic"
            assert events[0].payload == {
                "role_version_id": item["role_version_id"], "placement": "candidate_roles_shelf",
            }


def test_sponsored_role_does_not_return_organically_on_a_later_page():
    with TestClient(app) as candidate, TestClient(app) as employer:
        create_candidate(candidate, "promotion-pagination-candidate@example.test", assessed=True)
        assert set_preferences(candidate, formats=["hybrid"]).status_code == 200
        owner = register_verified(employer, "promotion-pagination-employer@example.test", "employer")
        promoted, _ = create_public_role(
            owner["id"], "Older promoted hybrid role", confirmed_at=now() - timedelta(hours=1),
            work_format="hybrid", work_city="Казань",
        )
        for index in range(6):
            create_public_role(
                owner["id"], f"Newer organic hybrid role {index}",
                work_format="hybrid", work_city="Казань",
            )
        assert activate(employer, promoted).status_code == 201

        first = candidate.get("/api/v1/candidate/roles", params={"work_format": "hybrid"}).json()
        assert promoted in {item["need_id"] for item in first["sponsored_items"]}
        assert promoted not in {item["need_id"] for item in first["items"]}
        assert first["next_cursor"]

        second = candidate.get("/api/v1/candidate/roles", params={
            "work_format": "hybrid", "cursor": first["next_cursor"],
        }).json()
        assert second["sponsored_items"] == []
        assert promoted not in {item["need_id"] for item in second["items"]}


def test_campaign_for_superseded_or_expired_role_version_is_not_served():
    with TestClient(app) as candidate, TestClient(app) as employer:
        create_candidate(candidate, "promotion-expiry-candidate@example.test", assessed=False)
        owner = register_verified(employer, "promotion-expiry-employer@example.test", "employer")
        superseded, old_version_id = create_public_role(owner["id"], "Superseded promoted role")
        assert activate(employer, superseded).status_code == 201
        with SessionLocal() as db:
            current = db.get(RoleVersion, old_version_id)
            updated_payload = role_payload(title="Superseded promoted role, new conditions")
            create_role_version(db, owner["id"], superseded, RoleCardIn.model_validate(updated_payload),
                                expected_version=current.version, at=now())
            db.commit()

        stale_role, _ = create_public_role(
            owner["id"], "Role with stale confirmation", confirmed_at=now() - timedelta(days=15),
        )
        assert activate(employer, stale_role).status_code == 409

        expired, _ = create_public_role(owner["id"], "Role with expired campaign")
        campaign = activate(employer, expired).json()
        with SessionLocal() as db:
            stored_campaign = db.get(PromotionCampaign, campaign["id"])
            stored_campaign.active_from = now() - timedelta(days=15)
            stored_campaign.active_until = now() - timedelta(seconds=1)
            db.commit()
        feed = candidate.get("/api/v1/candidate/roles").json()
        assert superseded not in {item["need_id"] for item in feed["sponsored_items"]}
        assert expired not in {item["need_id"] for item in feed["sponsored_items"]}


def test_promotion_does_not_change_organic_order_or_create_revenue():
    with TestClient(app) as candidate, TestClient(app) as employer:
        create_candidate(candidate, "promotion-organic-candidate@example.test", assessed=True)
        owner = register_verified(employer, "promotion-organic-employer@example.test", "employer")
        promoted, _ = create_public_role(owner["id"], "Featured organic role")
        first_organic, _ = create_public_role(owner["id"], "Organic role one")
        second_organic, _ = create_public_role(owner["id"], "Organic role two")

        before = candidate.get("/api/v1/candidate/roles").json()
        assert {promoted, first_organic, second_organic}.issubset(
            {item["need_id"] for item in before["items"]}
        )
        assert activate(employer, promoted).status_code == 201
        after = candidate.get("/api/v1/candidate/roles").json()
        assert [item["need_id"] for item in after["sponsored_items"]] == [promoted]
        organic = [item for item in before["items"] if item["need_id"] != promoted]
        assert after["items"] == organic
        assert all(item["need_id"] != promoted for item in after["items"])

        with SessionLocal() as db:
            campaign = after["sponsored_items"][0]["campaign_id"]
            events = db.scalars(select(ProductEvent).where(ProductEvent.entity_id == campaign)).all()
            assert all(event.data_mode == "synthetic" for event in events)
            assert all("revenue" not in event.payload and "price" not in event.payload for event in events)
