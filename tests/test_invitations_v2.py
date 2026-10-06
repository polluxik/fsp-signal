"""API contract tests for evidence-linked, versioned invitations."""

from datetime import timedelta

from sqlalchemy import func, select
from fastapi.testclient import TestClient

from backend.config import settings
from backend.db import SessionLocal
from backend.invitations import expire_due_invitations
from backend.main import app
from backend.models import (CandidateProfile, ContactGrant, EmployerProfile, Invitation,
                            MailOutbox, ProductEvent, RoleVersion, now)
from backend.security import aware
from test_flow import csrf
from test_flow import register_verified
from test_role_cards import role_payload
from test_search_snapshots import make_search_context


def _publish_role(employer, need_id):
    versioned = employer.post(
        f"/api/v1/employer/needs/{need_id}/versions",
        json={"expected_version": 1, "card": role_payload()},
        headers=csrf(employer),
    )
    assert versioned.status_code == 201, versioned.text
    with SessionLocal() as db:
        role_version_id = db.query(RoleVersion).filter_by(need_id=need_id, version=2).one().id
    published = employer.post(
        f"/api/v1/employer/needs/{need_id}/publish",
        json={"expected_version": 2, "active_headcount_attested": True, "discoverable": False},
        headers=csrf(employer),
    )
    assert published.status_code == 200, published.text
    return role_version_id


def _candidate_evidence_id(candidate):
    response = candidate.get("/api/v1/candidate/evidence")
    assert response.status_code == 200, response.text
    card = next(item for item in response.json() if item["source_type"] == "skill_claim")
    return card["id"]


def _invitation_payload(candidate_id, need_id, role_version_id, evidence_id):
    return {
        "candidate_id": candidate_id,
        "need_id": need_id,
        "role_version_id": role_version_id,
        "offer_text": "Приглашаем обсудить задачу обработки повторных событий.",
        "reason": "Стек Python указан кандидатом; конкретное действие обсудим на встрече.",
        "salary_min_rub": 220000,
        "salary_max_rub": 230000,
        "work_format": "remote",
        "employer_contact": "team@example.test",
        "evidence_ids": [evidence_id],
    }


def test_send_pins_role_terms_and_evidence_without_disclosing_private_compatibility():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(employer, candidate)
        role_version_id = _publish_role(employer, need_id)
        evidence_id = _candidate_evidence_id(candidate)
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.preferences = dict(profile.preferences or {}, salary_min_rub=500000)
            db.commit()

        request_payload = _invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id)
        send_headers = csrf(employer) | {"Idempotency-Key": "invite-v2-private-1"}
        sent = employer.post(
            "/api/v1/employer/invitations",
            json=request_payload,
            headers=send_headers,
        )

        assert sent.status_code == 201, sent.text
        invitation = sent.json()
        assert invitation["role_version_id"] == role_version_id
        assert invitation["state_version"] == 1
        assert invitation["terms_snapshot"]["role"]["salary_min_rub"] == 180000
        assert invitation["terms_snapshot"]["offer"]["salary_min_rub"] == 220000
        assert invitation["terms_snapshot"]["offer"]["salary_max_rub"] == 230000
        assert invitation["terms_hash"]
        assert [item["id"] for item in invitation["evidence_refs"]] == [evidence_id]
        assert "compatibility" not in employer.get("/api/v1/employer/invitations").text
        assert "compatibility_at_send" not in sent.text
        assert "500000" not in sent.text
        with SessionLocal() as db:
            sent_event = db.scalar(select(ProductEvent).where(
                ProductEvent.entity_id == invitation["id"],
                ProductEvent.type == "invitation_sent",
            ))
            assert sent_event.data_mode == "synthetic"
        replay = employer.post("/api/v1/employer/invitations", json=request_payload, headers=send_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["id"] == invitation["id"]
        reused_key = employer.post(
            "/api/v1/employer/invitations", json=request_payload | {"reason": "Different reason."},
            headers=send_headers,
        )
        assert reused_key.status_code == 409
        assert reused_key.json()["detail"] == "IDEMPOTENCY_KEY_REUSED"
        duplicate = employer.post(
            "/api/v1/employer/invitations", json=request_payload,
            headers=csrf(employer) | {"Idempotency-Key": "invite-v2-private-2"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "ACTIVE_INVITATION_EXISTS"
        with SessionLocal() as db:
            notification = db.scalar(select(MailOutbox).where(
                MailOutbox.recipient == candidate_user["email"],
                MailOutbox.subject == "Новое приглашение — ФСП Сигнал",
            ))
            assert notification is not None
            assert settings.public_base_url in notification.body
        candidate_view = candidate.get("/api/v1/candidate/invitations").json()[0]
        assert candidate_view["compatibility"]["status"] == "incompatible"
        assert candidate_view["compatibility_at_send"]["status"] == "incompatible"
        assert "500000" not in str(candidate_view["compatibility_at_send"])

        refused = candidate.post(
            f"/api/v1/invitations/{invitation['id']}/accept",
            json={"expected_terms_hash": invitation["terms_hash"], "expected_preferences_version": 1},
            headers=csrf(candidate),
        )
        assert refused.status_code == 409
        assert refused.json()["detail"] == "CONDITIONS_INCOMPATIBLE"
        assert employer.get(f"/api/v1/employer/candidates/{candidate_user['id']}/contact").status_code == 403


def test_accept_is_pinned_idempotent_and_creates_one_grant_event_and_sla():
    with TestClient(app) as employer, TestClient(app) as candidate:
        employer_user, candidate_user, need_id, _ = make_search_context(employer, candidate)
        role_version_id = _publish_role(employer, need_id)
        evidence_id = _candidate_evidence_id(candidate)
        sent = employer.post(
            "/api/v1/employer/invitations",
            json=_invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id),
            headers=csrf(employer) | {"Idempotency-Key": "invite-v2-accept-1"},
        )
        assert sent.status_code == 201, sent.text
        invitation = sent.json()

        missing_confirmation = candidate.post(
            f"/api/v1/invitations/{invitation['id']}/accept", headers=csrf(candidate)
        )
        assert missing_confirmation.status_code == 422

        accepted = candidate.post(
            f"/api/v1/invitations/{invitation['id']}/accept",
            json={"expected_terms_hash": invitation["terms_hash"], "expected_preferences_version": 1},
            headers=csrf(candidate),
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["state"] == "accepted"
        assert accepted.json()["terms_snapshot"] == invitation["terms_snapshot"]
        assert accepted.json()["response_due_at"]

        replay = candidate.post(
            f"/api/v1/invitations/{invitation['id']}/accept",
            json={"expected_terms_hash": invitation["terms_hash"], "expected_preferences_version": 1},
            headers=csrf(candidate),
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == invitation["id"]
        with SessionLocal() as db:
            assert len(db.scalars(select(ContactGrant).where(
                ContactGrant.invitation_id == invitation["id"], ContactGrant.revoked_at.is_(None)
            )).all()) == 1
            assert len(db.scalars(select(ProductEvent).where(
                ProductEvent.entity_id == invitation["id"], ProductEvent.type == "invitation_accepted"
            )).all()) == 1
            assert len(db.scalars(select(MailOutbox).where(
                MailOutbox.recipient == employer_user["email"],
                MailOutbox.subject == "Кандидат принял приглашение — ФСП Сигнал",
            )).all()) == 1
            saved = db.get(Invitation, invitation["id"])
            assert saved.state_version == 2
            assert aware(saved.response_due_at) > now()
            assert aware(saved.response_due_at) - aware(saved.decided_at) == timedelta(hours=48)


def test_inline_role_compatibility_uses_the_role_snapshot_without_a_vacancy():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, _, _ = make_search_context(employer, candidate)
        evidence_id = _candidate_evidence_id(candidate)
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.preferences = dict(
                profile.preferences or {},
                allowed_work_formats=["office"],
                allowed_cities=["Казань"],
            )
            profile.preferences_version = 2
            db.commit()

        inline_role = role_payload(work_format="office", work_city="Москва")
        payload = _invitation_payload(candidate_user["id"], "", "", evidence_id)
        payload.pop("need_id")
        payload.pop("role_version_id")
        payload.update({
            "inline_role_card": inline_role,
            "salary_min_rub": 220000,
            "salary_max_rub": 230000,
            "work_format": "office",
            "employer_contact": inline_role["employer_contact"],
        })
        sent = employer.post(
            "/api/v1/employer/invitations",
            json=payload,
            headers=csrf(employer) | {"Idempotency-Key": "inline-role-no-vacancy"},
        )

        assert sent.status_code == 201, sent.text
        assert "need_id" not in sent.json()
        assert "role_version_id" not in sent.json()
        assert sent.json()["terms_snapshot"]["role"]["work_city"] == "Москва"
        compatibility = candidate.get("/api/v1/candidate/invitations").json()[0]["compatibility"]
        location = next(check for check in compatibility["checks"] if check["code"] == "location")
        assert compatibility["status"] == "incompatible"
        assert location["status"] == "fail"

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.preferences = dict(profile.preferences or {}, allowed_cities=["Москва"])
            profile.preferences_version = 3
            db.commit()
        accepted = candidate.post(
            f"/api/v1/invitations/{sent.json()['id']}/accept",
            json={"expected_terms_hash": sent.json()["terms_hash"],
                  "expected_preferences_version": 3},
            headers=csrf(candidate),
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["state"] == "accepted"
        refreshed_view = candidate.get("/api/v1/candidate/invitations").json()[0]
        sent_location = next(check for check in refreshed_view["compatibility_at_send"]["checks"]
                             if check["code"] == "location")
        current_location = next(check for check in refreshed_view["compatibility"]["checks"]
                                if check["code"] == "location")
        assert sent_location["status"] == "fail"
        assert current_location["status"] == "pass"
        assert employer.get(f"/api/v1/employer/candidates/{candidate_user['id']}/contact").status_code == 200


def test_paused_role_cannot_be_accepted_from_an_old_invitation():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(employer, candidate)
        role_version_id = _publish_role(employer, need_id)
        evidence_id = _candidate_evidence_id(candidate)
        sent = employer.post(
            "/api/v1/employer/invitations",
            json=_invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id),
            headers=csrf(employer) | {"Idempotency-Key": "invite-before-pause"},
        )
        assert sent.status_code == 201, sent.text

        paused = employer.post(
            f"/api/v1/employer/needs/{need_id}/pause",
            json={"expected_version": 2}, headers=csrf(employer),
        )
        assert paused.status_code == 200, paused.text
        accepted = candidate.post(
            f"/api/v1/invitations/{sent.json()['id']}/accept",
            json={"expected_terms_hash": sent.json()["terms_hash"],
                  "expected_preferences_version": 1},
            headers=csrf(candidate),
        )
        assert accepted.status_code == 409
        assert accepted.json()["detail"] == "INVITATION_STATE_CONFLICT"
        assert employer.get(f"/api/v1/employer/candidates/{candidate_user['id']}/contact").status_code == 403


def test_accept_requires_the_terms_and_preferences_versions_the_candidate_reviewed():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(employer, candidate)
        role_version_id = _publish_role(employer, need_id)
        evidence_id = _candidate_evidence_id(candidate)
        sent = employer.post(
            "/api/v1/employer/invitations",
            json=_invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id),
            headers=csrf(employer) | {"Idempotency-Key": "invite-versions-reviewed"},
        )
        assert sent.status_code == 201, sent.text
        invitation_id = sent.json()["id"]

        stale_terms = candidate.post(
            f"/api/v1/invitations/{invitation_id}/accept",
            json={"expected_terms_hash": "0" * 64, "expected_preferences_version": 1},
            headers=csrf(candidate),
        )
        assert stale_terms.status_code == 409
        assert stale_terms.json()["detail"] == "TERMS_VERSION_CONFLICT"

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.preferences_version = 2
            db.commit()
        stale_preferences = candidate.post(
            f"/api/v1/invitations/{invitation_id}/accept",
            json={"expected_terms_hash": sent.json()["terms_hash"],
                  "expected_preferences_version": 1},
            headers=csrf(candidate),
        )
        assert stale_preferences.status_code == 409
        assert stale_preferences.json()["detail"] == "PREFERENCES_VERSION_CONFLICT"
        assert employer.get(f"/api/v1/employer/candidates/{candidate_user['id']}/contact").status_code == 403

        accepted = candidate.post(
            f"/api/v1/invitations/{invitation_id}/accept",
            json={"expected_terms_hash": sent.json()["terms_hash"],
                  "expected_preferences_version": 2},
            headers=csrf(candidate),
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["state"] == "accepted"


def test_candidate_may_explicitly_accept_a_role_with_an_unknown_hard_condition():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(employer, candidate)
        role_version_id = _publish_role(employer, need_id)
        evidence_id = _candidate_evidence_id(candidate)
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, candidate_user["id"])
            profile.preferences = dict(profile.preferences or {}, excluded_industries=["finance"])
            profile.preferences_version = 2
            db.commit()
        sent = employer.post(
            "/api/v1/employer/invitations",
            json=_invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id),
            headers=csrf(employer) | {"Idempotency-Key": "invite-unknown-industry"},
        )
        assert sent.status_code == 201, sent.text
        candidate_view = candidate.get("/api/v1/candidate/invitations").json()[0]
        industry = next(check for check in candidate_view["compatibility"]["checks"]
                        if check["code"] == "industry")
        assert candidate_view["compatibility"]["status"] == "needs_clarification"
        assert industry["status"] == "unknown"

        accepted = candidate.post(
            f"/api/v1/invitations/{sent.json()['id']}/accept",
            json={"expected_terms_hash": sent.json()["terms_hash"],
                  "expected_preferences_version": 2},
            headers=csrf(candidate),
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["state"] == "accepted"


def test_expiry_worker_moves_a_due_invitation_once():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(employer, candidate)
        role_version_id = _publish_role(employer, need_id)
        evidence_id = _candidate_evidence_id(candidate)
        sent = employer.post(
            "/api/v1/employer/invitations",
            json=_invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id),
            headers=csrf(employer) | {"Idempotency-Key": "invite-expiry-once"},
        )
        assert sent.status_code == 201, sent.text
        invitation_id = sent.json()["id"]
        due_at = now()
        with SessionLocal() as db:
            saved = db.get(Invitation, invitation_id)
            saved.expires_at = due_at - timedelta(seconds=1)
            db.commit()
        with SessionLocal() as db:
            assert expire_due_invitations(db, due_at) == 1
            db.commit()
        with SessionLocal() as db:
            assert expire_due_invitations(db, due_at) == 0
            db.commit()
            saved = db.get(Invitation, invitation_id)
            assert saved.state == "expired"
            assert saved.state_version == 2
            assert db.scalar(select(func.count(ProductEvent.id)).where(
                ProductEvent.entity_id == invitation_id,
                ProductEvent.type == "invitation_expired",
            )) == 1


def test_new_send_expires_old_pending_pair_in_the_same_transaction():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, candidate_user, need_id, _ = make_search_context(employer, candidate)
        role_version_id = _publish_role(employer, need_id)
        evidence_id = _candidate_evidence_id(candidate)
        payload = _invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id)
        first = employer.post(
            "/api/v1/employer/invitations", json=payload,
            headers=csrf(employer) | {"Idempotency-Key": "invite-old-expired"},
        )
        assert first.status_code == 201, first.text
        with SessionLocal() as db:
            old = db.get(Invitation, first.json()["id"])
            old.expires_at = now() - timedelta(seconds=1)
            db.commit()

        replacement = employer.post(
            "/api/v1/employer/invitations", json=payload,
            headers=csrf(employer) | {"Idempotency-Key": "invite-expired-replaced"},
        )
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["id"] != first.json()["id"]
        with SessionLocal() as db:
            old = db.get(Invitation, first.json()["id"])
            new = db.get(Invitation, replacement.json()["id"])
            assert (old.state, old.state_version) == ("expired", 2)
            assert (new.state, new.state_version) == ("sent", 1)
            assert db.scalar(select(func.count(ProductEvent.id)).where(
                ProductEvent.entity_id == old.id,
                ProductEvent.type == "invitation_expired",
            )) == 1


def test_employer_can_withdraw_a_legacy_invitation_without_candidate_profile():
    with TestClient(app) as employer, TestClient(app) as candidate:
        employer_user = register_verified(employer, "legacy-withdraw-employer@example.test", "employer")
        candidate_user = register_verified(candidate, "legacy-withdraw-candidate@example.test", "candidate")
        employer.put("/api/v1/employer/company", json={
            "company_name": "Legacy Co", "description": "", "industry": "ИТ",
            "contact_email": "team@example.test",
        }, headers=csrf(employer))
        with SessionLocal() as db:
            assert db.get(CandidateProfile, candidate_user["id"]) is None
            invitation = Invitation(
                employer_id=employer_user["id"], candidate_id=candidate_user["id"], need_id=None,
                company_name="Legacy Co", offer_text="Discuss the role with our team.",
                reason="A legacy proposal.", employer_contact="team@example.test",
                salary_min_rub=180000, salary_max_rub=220000, work_format="remote",
                state="sent", idempotency_key="legacy-withdraw", request_hash="l" * 64,
                created_at=now(), expires_at=now() + timedelta(days=7),
            )
            db.add(invitation)
            db.commit()
            invitation_id = invitation.id

        response = employer.post(
            f"/api/v1/invitations/{invitation_id}/withdraw", headers=csrf(employer),
        )

        assert response.status_code == 200, response.text
        assert response.json()["state"] == "withdrawn"
        assert response.json()["state_version"] == 2
