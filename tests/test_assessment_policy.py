from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.db import SessionLocal
from backend.main import app
from backend.models import AssessmentAttempt, CandidateProfile, now
from test_flow import csrf, register_verified


def failed_history(client, *, verified=False, grade='middle'):
    user = register_verified(client, f'fallback-{now().timestamp()}@example.test', 'candidate')
    with SessionLocal() as db:
        profile = CandidateProfile(user_id=user['id'])
        if verified:
            profile.verified_specialization, profile.verified_grade = 'backend', 'middle'
            profile.grade_changed_at = now() - timedelta(hours=1)
        db.add(profile)
        for elapsed in (timedelta(days=6), timedelta(days=3), timedelta(minutes=1)):
            started = now() - elapsed
            db.add(AssessmentAttempt(candidate_id=user['id'], specialization='backend', grade=grade,
                blueprint_version='policy-fixture', questions=[], answer_key={}, answers={},
                state='scored', outcome='failed', score=0, started_at=started,
                submitted_at=started, expires_at=started + timedelta(minutes=20)))
        db.commit()
    return user


def start(client, specialization='backend', grade='junior'):
    return client.post('/api/v1/candidate/assessment-attempts', headers=csrf(client),
        json={'industry': 'it', 'specialization': specialization, 'grade': grade})


@pytest.mark.parametrize('verified', [False, True])
def test_failed_middle_budget_does_not_block_junior_and_confirmation(verified):
    with TestClient(app) as client:
        user = failed_history(client, verified=verified)
        response = start(client)
        assert response.status_code == 201, response.text
        attempt = response.json()
        with SessionLocal() as db:
            answer_key = db.get(AssessmentAttempt, attempt['id']).answer_key
        for phase in (1, 2):
            answers = {q['id']: answer_key[q['id']] for q in attempt['questions'] if q['phase'] == phase}
            assert client.put(f"/api/v1/candidate/assessment-attempts/{attempt['id']}/answers",
                headers=csrf(client), json={'answers': answers}).status_code == 200
            if phase == 1:
                attempt = client.post(f"/api/v1/candidate/assessment-attempts/{attempt['id']}/advance",
                    headers=csrf(client)).json()
        submitted = client.post(f"/api/v1/candidate/assessment-attempts/{attempt['id']}/submit", headers=csrf(client))
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()['verified_category'] == 'backend:junior'
        with SessionLocal() as db:
            assert db.get(CandidateProfile, user['id']).verified_grade == 'junior'
            # Expire the retry-budget window to isolate the promotion cooldown.
            for stored in db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.candidate_id == user['id'])):
                stored.started_at = now() - timedelta(days=8)
            db.commit()
        assert start(client, grade='middle').json()['detail'] == 'GRADE_CHANGE_COOLDOWN'


@pytest.mark.parametrize('specialization, grade', [('backend', 'middle'), ('qa', 'junior')])
def test_failed_higher_attempts_do_not_refund_same_grade_or_other_specialization(specialization, grade):
    with TestClient(app) as client:
        failed_history(client)
        response = start(client, specialization, grade)
        assert response.status_code == 429
        assert response.json()['detail'] == 'ASSESSMENT_ATTEMPT_LIMIT'


def test_lower_grade_still_has_a_retry_budget():
    with TestClient(app) as client:
        failed_history(client, grade='junior')
        assert start(client).status_code == 429


def test_fallback_does_not_bypass_same_grade_72_hour_wait():
    with TestClient(app) as client:
        failed_history(client)
        response = start(client)
        assert response.status_code == 201
        with SessionLocal() as db:
            attempt = db.get(AssessmentAttempt, response.json()['id'])
            attempt.state, attempt.outcome, attempt.submitted_at = 'scored', 'failed', now()
            db.commit()
        repeated = start(client)
        assert repeated.status_code == 409
        assert repeated.json()['detail'] == 'ASSESSMENT_RETRY_COOLDOWN'
