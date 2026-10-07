"""Real multi-connection invitation races; never treat SQLite as concurrency proof."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import os

import pytest
from sqlalchemy import select, func
from sqlalchemy.engine import make_url

from backend.db import SessionLocal
from backend.domain_errors import DomainError
from backend.invitations import create_invitation, expire_due_invitations, transition_invitation
from backend.main import app
from backend.models import ContactGrant, Invitation, MailOutbox, ProductEvent, now
from backend.schemas import AcceptInvitationIn, InvitationV2In
from fastapi.testclient import TestClient
from test_flow import csrf
from test_invitations_v2 import (_candidate_evidence_id, _invitation_payload,
                                 _publish_role)
from test_search_snapshots import make_search_context


_test_url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
_is_postgres_test = make_url(_test_url).get_backend_name() == "postgresql" and \
    (make_url(_test_url).database or "").endswith("_test")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not _is_postgres_test,
                       reason="requires TEST_DATABASE_URL for a dedicated PostgreSQL *_test database"),
]


def _prepared_invitation():
    employer = TestClient(app)
    candidate = TestClient(app)
    employer_user, candidate_user, need_id, _ = make_search_context(employer, candidate)
    role_version_id = _publish_role(employer, need_id)
    evidence_id = _candidate_evidence_id(candidate)
    payload = _invitation_payload(candidate_user["id"], need_id, role_version_id, evidence_id)
    response = employer.post(
        "/api/v1/employer/invitations", json=payload,
        headers=csrf(employer) | {"Idempotency-Key": "race-invitation-setup"},
    )
    assert response.status_code == 201, response.text
    invitation = response.json()
    employer.close()
    candidate.close()
    return employer_user, candidate_user, payload, invitation


@pytest.mark.parametrize("key_mode", ["same_body", "changed_body", "different_keys"])
def test_concurrent_send_obeys_idempotency_and_active_pair_invariants(key_mode):
    employer, candidate, payload, _ = _prepared_invitation()
    with SessionLocal() as db:
        initial = db.scalar(select(Invitation).where(
            Invitation.employer_id == employer["id"], Invitation.candidate_id == candidate["id"],
        ))
        initial_id = initial.id
        initial.state = "withdrawn"
        initial.state_version += 1
        initial.decided_at = now()
        db.commit()

    request = InvitationV2In.model_validate(payload)
    request2 = request if key_mode == "same_body" else InvitationV2In.model_validate(
        payload if key_mode == "different_keys" else payload | {"reason": "A distinct role-specific reason."}
    )
    keys = ("race-same-key", "race-second-key" if key_mode == "different_keys" else "race-same-key")
    barrier = Barrier(2)

    def send(request_body, key):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                invitation = create_invitation(db, employer["id"], request_body, key, now())
                db.commit()
                return "created", invitation.id
            except DomainError as exc:
                db.rollback()
                return "error", exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(send, request, keys[0]), executor.submit(send, request2, keys[1])]
        results = [future.result(timeout=30) for future in futures]

    successes = [value for status, value in results if status == "created"]
    failures = [value for status, value in results if status == "error"]
    if key_mode == "same_body":
        assert len(successes) == 2 and len(set(successes)) == 1
        assert failures == []
    else:
        assert len(successes) == 1 and len(failures) == 1
        expected_error = "IDEMPOTENCY_KEY_REUSED" if key_mode == "changed_body" else "ACTIVE_INVITATION_EXISTS"
        assert failures == [expected_error]

    with SessionLocal() as db:
        active = db.scalars(select(Invitation).where(
            Invitation.employer_id == employer["id"],
            Invitation.candidate_id == candidate["id"],
            Invitation.state.in_(("sent", "viewed")),
        )).all()
        assert len(active) == 1
        assert active[0].id != initial_id
        assert db.scalar(select(func.count(ProductEvent.id)).where(
            ProductEvent.entity_id == active[0].id,
            ProductEvent.type == "invitation_sent",
        )) == 1
        assert db.scalar(select(func.count(MailOutbox.id)).where(
            MailOutbox.recipient == candidate["email"],
            MailOutbox.subject == "Новое приглашение — ФСП Сигнал",
        )) == 2  # one setup send plus one winning raced send


@pytest.mark.parametrize("competing_command", ["reject", "withdraw", "expire"])
def test_accept_race_has_exactly_one_terminal_state_grant_and_event(competing_command):
    employer, candidate, _, invitation = _prepared_invitation()
    invitation_id = invitation["id"]
    if competing_command == "expire":
        with SessionLocal() as db:
            row = db.get(Invitation, invitation_id)
            expires_at = row.expires_at

    barrier = Barrier(2)
    accept_terms = AcceptInvitationIn(
        expected_terms_hash=invitation["terms_hash"], expected_preferences_version=1,
    )

    def perform_accept():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                transition_invitation(db, candidate["id"], invitation_id, "accept", 1,
                                      accept_terms, now())
                db.commit()
                return "accepted"
            except DomainError as exc:
                db.rollback()
                return exc.code

    def perform_competing_transition():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            actor = None if competing_command == "expire" else (
                employer["id"] if competing_command == "withdraw" else candidate["id"]
            )
            command_time = expires_at + timedelta(microseconds=1) if competing_command == "expire" else now()
            try:
                transition_invitation(db, actor, invitation_id, competing_command, 1, None, command_time)
                db.commit()
                return competing_command
            except DomainError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(perform_accept), executor.submit(perform_competing_transition)]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sum(outcome in {"accepted", competing_command} for outcome in outcomes) == 1
    assert sum(outcome.endswith("CONFLICT") for outcome in outcomes) == 1
    with SessionLocal() as db:
        saved = db.get(Invitation, invitation_id)
        terminal_events = db.scalars(select(ProductEvent).where(
            ProductEvent.entity_id == invitation_id,
            ProductEvent.type.in_(("invitation_accepted", "invitation_rejected",
                                   "invitation_withdrawn", "invitation_expired")),
        )).all()
        grants = db.scalars(select(ContactGrant).where(ContactGrant.invitation_id == invitation_id)).all()
        assert saved.state in {"accepted", "rejected", "withdrawn", "expired"}
        assert len(terminal_events) == 1
        assert len(grants) == (1 if saved.state == "accepted" else 0)


def test_worker_expiry_racing_with_accept_keeps_one_terminal_event():
    _, candidate, _, invitation = _prepared_invitation()
    invitation_id = invitation["id"]
    with SessionLocal() as db:
        expires_at = db.get(Invitation, invitation_id).expires_at

    barrier = Barrier(2)

    def accept():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                transition_invitation(
                    db, candidate["id"], invitation_id, "accept", 1,
                    AcceptInvitationIn(
                        expected_terms_hash=invitation["terms_hash"],
                        expected_preferences_version=1,
                    ), now(),
                )
                db.commit()
                return "accepted"
            except DomainError as exc:
                db.rollback()
                return exc.code

    def expire():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            expire_due_invitations(db, expires_at + timedelta(microseconds=1))
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        accept_future = executor.submit(accept)
        expire_future = executor.submit(expire)
        outcome = accept_future.result(timeout=30)
        expire_future.result(timeout=30)

    assert outcome in {"accepted", "INVITATION_STATE_CONFLICT"}
    with SessionLocal() as db:
        saved = db.get(Invitation, invitation_id)
        events = db.scalars(select(ProductEvent).where(
            ProductEvent.entity_id == invitation_id,
            ProductEvent.type.in_(("invitation_accepted", "invitation_expired")),
        )).all()
        grants = db.scalars(select(ContactGrant).where(ContactGrant.invitation_id == invitation_id)).all()
        assert saved.state in {"accepted", "expired"}
        assert len(events) == 1
        assert len(grants) == (1 if saved.state == "accepted" else 0)


def test_contact_read_racing_with_revoke_never_survives_a_completed_revoke():
    with TestClient(app) as employer_client, TestClient(app) as candidate_client:
        employer, candidate, need_id, _ = make_search_context(employer_client, candidate_client)
        role_version_id = _publish_role(employer_client, need_id)
        evidence_id = _candidate_evidence_id(candidate_client)
        sent = employer_client.post(
            "/api/v1/employer/invitations",
            json=_invitation_payload(candidate["id"], need_id, role_version_id, evidence_id),
            headers=csrf(employer_client) | {"Idempotency-Key": "race-revoke-read"},
        )
        assert sent.status_code == 201, sent.text
        accepted = candidate_client.post(
            f"/api/v1/invitations/{sent.json()['id']}/accept",
            json={"expected_terms_hash": sent.json()["terms_hash"],
                  "expected_preferences_version": 1},
            headers=csrf(candidate_client),
        )
        assert accepted.status_code == 200, accepted.text
        grant = candidate_client.get("/api/v1/candidate/contact-grants").json()[0]

        barrier = Barrier(2)

        def read_contact():
            barrier.wait(timeout=10)
            return employer_client.get(f"/api/v1/employer/candidates/{candidate['id']}/contact").status_code

        def revoke_contact():
            barrier.wait(timeout=10)
            response = candidate_client.post(
                f"/api/v1/candidate/contact-grants/{grant['id']}/revoke",
                headers=csrf(candidate_client),
            )
            assert response.status_code == 200, response.text
            return response.json()["status"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            read_future = executor.submit(read_contact)
            revoke_future = executor.submit(revoke_contact)
            read_status = read_future.result(timeout=30)
            revoke_status = revoke_future.result(timeout=30)

        assert read_status in (200, 403)
        assert revoke_status == "revoked"
        assert employer_client.get(
            f"/api/v1/employer/candidates/{candidate['id']}/contact"
        ).status_code == 403
        with SessionLocal() as db:
            saved_grant = db.get(ContactGrant, grant["id"])
            assert saved_grant.revoked_at is not None
