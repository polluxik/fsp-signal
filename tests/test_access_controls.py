from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.db import SessionLocal
from backend.main import app
from backend.models import CandidateProfile, ContactGrant, HiringNeed, Invitation, SearchSnapshot, now
from test_flow import csrf, register_verified


def test_block_revokes_every_company_grant_and_pending_invite_but_not_other_employer():
    with TestClient(app) as candidate, TestClient(app) as first, TestClient(app) as second:
        person = register_verified(candidate, "block-candidate@example.test", "candidate")
        first_employer = register_verified(first, "block-first@example.test", "employer")
        second_employer = register_verified(second, "block-second@example.test", "employer")
        saved = candidate.put("/api/v1/candidate/profile", json={
            "full_name": "Кандидат", "contact_email": "candidate-private@example.test",
            "contact_phone": "+79990000000", "city": "Москва", "summary": "Скрытое резюме",
            "skills": ["Python"], "experience_months": 24, "min_salary_rub": 0,
            "work_format": "remote", "consent_processing": True, "published": True,
            "available": True, "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert saved.status_code == 200, saved.text

        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person["id"])
            profile.verified_specialization = "backend"
            profile.verified_grade = "middle"
            profile.test_score = 80
            need = HiringNeed(
                employer_id=first_employer["id"], title="Backend Middle", description="Надёжная обработка событий",
                specialization="backend", grade="middle", competencies=["event_idempotency"],
                stack=["Python"], salary_min_rub=180000, salary_max_rub=230000, work_format="remote",
            )
            db.add(need)
            db.flush()
            snapshot = SearchSnapshot(
                employer_id=first_employer["id"], need_id=need.id, filters={},
                results=[{"candidate_id": person["id"], "match": {"score": 80}}],
            )
            db.add(snapshot)
            invitations = {}
            for employer_id, key, state in (
                (first_employer["id"], "first-accepted", "accepted"),
                (first_employer["id"], "first-accepted-2", "accepted"),
                (first_employer["id"], "first-pending", "viewed"),
                (second_employer["id"], "second-accepted", "accepted"),
                (second_employer["id"], "second-accepted-2", "accepted"),
            ):
                invitation = Invitation(
                    employer_id=employer_id, candidate_id=person["id"], need_id=None,
                    company_name="Test Co", offer_text="Discuss the role with the team.",
                    reason="Relevant declared experience.", employer_contact="team@example.test",
                    salary_min_rub=180000, salary_max_rub=220000, work_format="remote",
                    state=state, idempotency_key=key, request_hash=(key[0] * 64),
                    created_at=now(), expires_at=now() + timedelta(days=7),
                )
                db.add(invitation)
                db.flush()
                invitations[key] = invitation
                if state == "accepted":
                    db.add(ContactGrant(invitation_id=invitation.id, employer_id=employer_id,
                                        candidate_id=person["id"], granted_at=now()))
            db.commit()
            first_pending_id = invitations["first-pending"].id
            snapshot_id = snapshot.id

        assert person["id"] in {row["id"] for row in first.get("/api/v1/employer/candidates").json()}
        assert person["id"] in {row["id"] for row in second.get("/api/v1/employer/candidates").json()}
        assert first.get(f"/api/v1/employer/searches/{snapshot_id}").json()["results"]
        assert first.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 200
        blocked = candidate.post(
            f"/api/v1/candidate/companies/{first_employer['id']}/block",
            headers=csrf(candidate),
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["blocked"] is True
        assert blocked.json()["revoked_grants"] == 2
        assert blocked.json()["withdrawn_invitations"] == 1

        failed_accept = candidate.post(f"/api/v1/invitations/{first_pending_id}/accept",
                                       headers=csrf(candidate))
        assert failed_accept.status_code == 409
        assert failed_accept.json()["detail"] == "COMPANY_BLOCKED"
        assert person["id"] not in {row["id"] for row in first.get("/api/v1/employer/candidates").json()}
        assert person["id"] in {row["id"] for row in second.get("/api/v1/employer/candidates").json()}
        hidden_snapshot = first.get(f"/api/v1/employer/searches/{snapshot_id}")
        assert hidden_snapshot.status_code == 200
        assert hidden_snapshot.json()["results"] == []
        assert hidden_snapshot.json()["unavailable_count"] == 1
        assert first.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 403
        other_contact = second.get(f"/api/v1/employer/candidates/{person['id']}/contact")
        assert other_contact.status_code == 200, other_contact.text
        assert other_contact.json()["email"] == "candidate-private@example.test"

        repeated = candidate.post(
            f"/api/v1/candidate/companies/{first_employer['id']}/block",
            headers=csrf(candidate),
        )
        assert repeated.status_code == 200
        assert repeated.json()["revoked_grants"] == 0
        assert repeated.json()["withdrawn_invitations"] == 0
        with SessionLocal() as db:
            first_grants = db.scalars(select(ContactGrant).where(
                ContactGrant.candidate_id == person["id"],
                ContactGrant.employer_id == first_employer["id"],
            )).all()
            second_grants = db.scalars(select(ContactGrant).where(
                ContactGrant.candidate_id == person["id"],
                ContactGrant.employer_id == second_employer["id"],
            )).all()
            states = {invite.idempotency_key: invite.state
                      for invite in db.scalars(select(Invitation)).all()}
        assert all(grant.revoked_at is not None for grant in first_grants)
        assert second_grants[0].revoked_at is None
        assert states["first-pending"] == "withdrawn"
        assert states["first-accepted"] == "accepted"

        paused = candidate.put("/api/v1/candidate/profile", json={
            "full_name": "Кандидат", "contact_email": "candidate-private@example.test",
            "contact_phone": "+79990000000", "city": "Москва", "summary": "Скрытое резюме",
            "skills": ["Python"], "experience_months": 24, "min_salary_rub": 0,
            "work_format": "remote", "consent_processing": True, "published": False,
            "available": True, "adult_hiring_confirmed": True,
        }, headers=csrf(candidate))
        assert paused.status_code == 200
        assert second.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 200

        revoke = candidate.post(
            f"/api/v1/candidate/companies/{second_employer['id']}/revoke-contact",
            headers=csrf(candidate),
        )
        assert revoke.status_code == 200
        assert revoke.json()["blocked"] is False
        assert revoke.json()["revoked_grants"] == 2
        assert revoke.json()["withdrawn_invitations"] == 0
