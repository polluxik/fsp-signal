from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from backend.db import SessionLocal
from backend.main import app
from backend.models import HiringNeed, Invitation, ProductEvent, RoleVersion, User, now
from backend.role_cards import RoleVersionError, create_role_version, is_role_fresh, terms_hash
from backend.schemas import RoleCardIn
from test_flow import csrf, register_verified


def role_payload(**overrides):
    payload = {
        "title": "Backend-разработчик",
        "description": "Надёжная обработка событий",
        "specialization": "backend",
        "grade": "middle",
        "competencies": ["event_idempotency"],
        "stack": ["Python", "PostgreSQL"],
        "salary_min_rub": 180000,
        "salary_max_rub": 230000,
        "work_format": "remote",
        "work_city": None,
        "first_30_days": "Устранить повторную обработку платежных событий",
        "interview_steps": [{"title": "Знакомство с командой", "duration_minutes": 45}],
        "take_home_minutes": 0,
        "response_sla_hours": 48,
        "employer_contact": "team@example.test",
        "active_headcount_attested": True,
    }
    return payload | overrides


def test_role_card_requires_city_for_onsite_and_concrete_publication_terms():
    with pytest.raises(ValidationError):
        RoleCardIn.model_validate(role_payload(work_format="office", work_city=None))
    with pytest.raises(ValidationError):
        RoleCardIn.model_validate(role_payload(work_format="any"))
    with pytest.raises(ValidationError):
        RoleCardIn.model_validate(role_payload(interview_steps=[]))
    with pytest.raises(ValidationError):
        RoleCardIn.model_validate(role_payload(description="          "))
    with pytest.raises(ValidationError):
        RoleCardIn.model_validate(role_payload(employer_contact="not-an-email"))


def test_terms_hash_is_stable_and_ignores_non_terms_metadata():
    card = RoleCardIn.model_validate(role_payload())
    changed_metadata = card.model_dump(mode="json") | {
        "employer_contact": "different@example.test",
        "active_headcount_attested": False,
    }
    assert terms_hash(card.model_dump(mode="json")) == terms_hash(changed_metadata)
    assert terms_hash(card.model_dump(mode="json") | {"salary_max_rub": 240000}) != terms_hash(
        card.model_dump(mode="json")
    )


def test_role_versions_are_immutable_and_stale_cas_has_no_side_effect():
    with TestClient(app) as employer_client:
        employer = register_verified(employer_client, "role-owner@example.test", "employer")
        employer_client.put("/api/v1/employer/company", json={
            "company_name": "Signal Demo", "description": "", "industry": "ИТ",
            "contact_email": "team@example.test",
        }, headers=csrf(employer_client))
        need_response = employer_client.post("/api/v1/employer/needs", json={
            "title": "Backend Middle", "description": "Обработка событий надежно",
            "specialization": "backend", "grade": "middle",
            "competencies": ["event_idempotency"], "stack": ["Python"],
            "salary_min_rub": 180000, "salary_max_rub": 230000, "work_format": "remote",
        }, headers=csrf(employer_client))
        assert need_response.status_code == 201, need_response.text
        need_id = need_response.json()["id"]

        first = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 1, "card": role_payload()}, headers=csrf(employer_client),
        )
        assert first.status_code == 201, first.text
        v1 = first.json()
        assert v1["version"] == 2

        changed = role_payload(salary_max_rub=240000)
        second = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 2, "card": changed}, headers=csrf(employer_client),
        )
        assert second.status_code == 201, second.text
        assert second.json()["version"] == 3

        stale = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 2, "card": role_payload(salary_max_rub=250000)},
            headers=csrf(employer_client),
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == "ROLE_VERSION_CONFLICT"

        with SessionLocal() as db:
            versions = db.scalars(select(RoleVersion).where(RoleVersion.need_id == need_id)
                                  .order_by(RoleVersion.version)).all()
            events = db.scalars(select(ProductEvent).where(ProductEvent.entity_id == need_id)).all()
            need = db.get(HiringNeed, need_id)
            assert [version.version for version in versions] == [1, 2, 3]
            assert versions[1].payload["salary_max_rub"] == 230000
            assert need.current_role_version == 3
            assert len(events) == 3


def test_legacy_need_is_private_draft_and_role_freshness_is_14_days():
    with TestClient(app) as employer_client:
        register_verified(employer_client, "legacy-role@example.test", "employer")
        employer_client.put("/api/v1/employer/company", json={
            "company_name": "Legacy Demo", "description": "", "industry": "ИТ",
            "contact_email": "team@example.test",
        }, headers=csrf(employer_client))
        need_id = employer_client.post("/api/v1/employer/needs", json={
            "title": "Backend Middle", "description": "Обработка событий надежно",
            "specialization": "backend", "grade": "middle", "competencies": [],
            "stack": [], "salary_min_rub": 180000, "salary_max_rub": 230000,
            "work_format": "remote",
        }, headers=csrf(employer_client)).json()["id"]
        card = employer_client.get(f"/api/v1/employer/needs/{need_id}/role-card")
        assert card.status_code == 200
        assert card.json()["publication_state"] == "draft"
        assert card.json()["discoverable"] is False
        assert card.json()["source"] == "employer_declared"
        assert {"first_30_days", "interview_steps", "employer_contact", "active_headcount_attested"}.issubset(
            set(card.json()["missing_fields"])
        )

    at = now()
    assert is_role_fresh(at, at + timedelta(days=14) - timedelta(microseconds=1))
    assert not is_role_fresh(at, at + timedelta(days=14))
    assert not is_role_fresh(None, at)


def test_publish_requires_attestation_and_pause_hides_role():
    with TestClient(app) as employer_client:
        register_verified(employer_client, "role-publish@example.test", "employer")
        employer_client.put("/api/v1/employer/company", json={
            "company_name": "Signal Demo", "description": "", "industry": "ИТ",
            "contact_email": "team@example.test",
        }, headers=csrf(employer_client))
        need_id = employer_client.post("/api/v1/employer/needs", json={
            "title": "Backend Middle", "description": "Обработка событий надежно",
            "specialization": "backend", "grade": "middle", "competencies": [],
            "stack": [], "salary_min_rub": 180000, "salary_max_rub": 230000,
            "work_format": "remote",
        }, headers=csrf(employer_client)).json()["id"]
        version = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 1, "card": role_payload()}, headers=csrf(employer_client),
        )
        assert version.status_code == 201, version.text

        refused = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/publish",
            json={"expected_version": 2, "active_headcount_attested": False, "discoverable": True},
            headers=csrf(employer_client),
        )
        assert refused.status_code == 409
        assert refused.json()["detail"] == "ROLE_ATTESTATION_REQUIRED"

        published = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/publish",
            json={"expected_version": 2, "active_headcount_attested": True, "discoverable": True},
            headers=csrf(employer_client),
        )
        assert published.status_code == 200, published.text
        assert published.json()["publication_state"] == "active"
        assert published.json()["discoverable"] is True
        pinned_hash = published.json()["terms_hash"]
        assert (published.json()["salary_currency"], published.json()["salary_period"],
                published.json()["salary_basis"]) == ("RUB", "month", "gross")

        with SessionLocal() as db:
            need = db.get(HiringNeed, need_id)
            need.confirmed_at = now() - timedelta(days=14)
            db.commit()
        stale_card = employer_client.get(f"/api/v1/employer/needs/{need_id}/role-card").json()
        assert stale_card["fresh"] is False
        refused_reconfirm = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/reconfirm",
            json={"expected_version": 2, "active_headcount_attested": False},
            headers=csrf(employer_client),
        )
        assert refused_reconfirm.status_code == 409
        reconfirmed = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/reconfirm",
            json={"expected_version": 2, "active_headcount_attested": True},
            headers=csrf(employer_client),
        )
        assert reconfirmed.status_code == 200, reconfirmed.text
        assert reconfirmed.json()["fresh"] is True
        assert reconfirmed.json()["terms_hash"] == pinned_hash

        paused = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/pause",
            json={"expected_version": 2}, headers=csrf(employer_client),
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["publication_state"] == "paused"
        assert paused.json()["discoverable"] is False

        closed = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/close",
            json={"expected_version": 2}, headers=csrf(employer_client),
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["publication_state"] == "closed"
        assert closed.json()["discoverable"] is False
        revision_after_close = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 2, "card": role_payload()}, headers=csrf(employer_client),
        )
        assert revision_after_close.status_code == 409
        assert revision_after_close.json()["detail"] == "ROLE_CLOSED"


def test_role_card_owner_scope_and_csrf_are_enforced():
    with TestClient(app) as owner, TestClient(app) as other:
        register_verified(owner, "role-scope-owner@example.test", "employer")
        register_verified(other, "role-scope-other@example.test", "employer")
        owner.put("/api/v1/employer/company", json={
            "company_name": "Owner Co", "description": "", "industry": "ИТ",
            "contact_email": "owner@example.test",
        }, headers=csrf(owner))
        need_id = owner.post("/api/v1/employer/needs", json={
            "title": "Backend Middle", "description": "Обработка событий надежно",
            "specialization": "backend", "grade": "middle", "competencies": [],
            "stack": [], "salary_min_rub": 180000, "salary_max_rub": 230000,
            "work_format": "remote",
        }, headers=csrf(owner)).json()["id"]
        assert other.get(f"/api/v1/employer/needs/{need_id}/role-card").status_code == 404
        forbidden = other.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 1, "card": role_payload()}, headers=csrf(other),
        )
        assert forbidden.status_code == 404
        no_csrf = owner.post(f"/api/v1/employer/needs/{need_id}/pause", json={"expected_version": 1})
        assert no_csrf.status_code == 403


def test_republication_withdraws_only_pending_invites_pinned_to_an_older_version():
    with (TestClient(app) as employer_client, TestClient(app) as candidate_client,
          TestClient(app) as legacy_candidate_client):
        employer = register_verified(employer_client, "role-version-owner@example.test", "employer")
        candidate = register_verified(candidate_client, "role-version-candidate@example.test", "candidate")
        legacy_candidate = register_verified(
            legacy_candidate_client, "role-version-legacy-candidate@example.test", "candidate",
        )
        employer_client.put("/api/v1/employer/company", json={
            "company_name": "Version Co", "description": "", "industry": "ИТ",
            "contact_email": "team@example.test",
        }, headers=csrf(employer_client))
        need_id = employer_client.post("/api/v1/employer/needs", json={
            "title": "Backend Middle", "description": "Обработка событий надежно",
            "specialization": "backend", "grade": "middle", "competencies": [],
            "stack": [], "salary_min_rub": 180000, "salary_max_rub": 230000,
            "work_format": "remote",
        }, headers=csrf(employer_client)).json()["id"]
        created = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": 1, "card": role_payload()}, headers=csrf(employer_client),
        )
        assert created.status_code == 201, created.text
        first_version = created.json()["version"]
        published = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/publish",
            json={"expected_version": first_version, "active_headcount_attested": True, "discoverable": True},
            headers=csrf(employer_client),
        )
        assert published.status_code == 200, published.text

        with SessionLocal() as db:
            pinned = db.scalar(select(RoleVersion).where(
                RoleVersion.need_id == need_id, RoleVersion.version == first_version
            ))
            for state, key in (("sent", "pending-old-role-1"), ("accepted", "accepted-old-role"),
                               ("sent", "legacy-unpinned-role")):
                db.add(Invitation(
                    employer_id=employer["id"],
                    candidate_id=(legacy_candidate["id"] if key == "legacy-unpinned-role"
                                  else candidate["id"]),
                    need_id=need_id,
                    role_version_id=None if key == "legacy-unpinned-role" else pinned.id,
                    company_name="Version Co", offer_text="Discuss this role with the team.",
                    reason="Your tested event-handling work is relevant.", employer_contact="team@example.test",
                    salary_min_rub=180000, salary_max_rub=230000, work_format="remote", state=state,
                    idempotency_key=key, request_hash=(key[0] * 64),
                    created_at=now(), expires_at=now() + timedelta(days=7),
                ))
            db.commit()

        revised = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/versions",
            json={"expected_version": first_version, "card": role_payload(salary_max_rub=240000)},
            headers=csrf(employer_client),
        )
        assert revised.status_code == 201, revised.text
        republished = employer_client.post(
            f"/api/v1/employer/needs/{need_id}/publish",
            json={"expected_version": revised.json()["version"],
                  "active_headcount_attested": True, "discoverable": True},
            headers=csrf(employer_client),
        )
        assert republished.status_code == 200, republished.text
        with SessionLocal() as db:
            invitations = {item.idempotency_key: (item.state, item.state_version)
                           for item in db.scalars(select(Invitation)).all()}
            withdrawn_events = db.scalars(select(ProductEvent).where(
                ProductEvent.entity_id.in_(select(Invitation.id).where(
                    Invitation.idempotency_key == "pending-old-role-1"
                )),
                ProductEvent.type == "invitation_withdrawn",
            )).all()
        assert invitations["pending-old-role-1"] == ("withdrawn", 2)
        assert invitations["accepted-old-role"] == ("accepted", 1)
        assert invitations["legacy-unpinned-role"] == ("sent", 1)
        assert len(withdrawn_events) == 1
