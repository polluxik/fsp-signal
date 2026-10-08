"""Privacy, true publication guards, and scored-attempt feedback invariants."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.assessment import grade_attempt, make_assessment
from backend.candidate_progress import PRACTICE
from backend.db import SessionLocal
from backend.main import app
from backend.models import AssessmentAttempt, CandidateProfile, now
from backend.taxonomy import available_categories
from test_flow import create_assessment_candidate, register_verified


def stored_attempt(person, specialization="backend", grade="junior", answers_mode="perfect", state="scored"):
    questions, key = make_assessment(specialization, grade, "cab012345678")
    answers = dict(key) if answers_mode == "perfect" else {}
    if answers_mode == "partial":
        answers = dict(key)
        structured = next(q for q in questions if q["type"] == "structured")
        answers[structured["id"]] = {next(iter(key[structured["id"]])): next(iter(key[structured["id"]].values()))}
    score, passed, _, _ = grade_attempt(questions, key, answers)
    with SessionLocal() as db:
        attempt = AssessmentAttempt(candidate_id=person["id"], specialization=specialization, grade=grade,
            blueprint_version="report-fixture-v1", seed="private-seed", questions=questions, answer_key=key,
            answers=answers, state=state, phase=2, score=score if state == "scored" else None,
            outcome=("passed" if passed else "failed") if state == "scored" else None,
            submitted_at=now() if state == "scored" else None, expires_at=now() + timedelta(minutes=20))
        db.add(attempt); db.commit()
        return attempt.id, questions


@pytest.mark.parametrize("category", available_categories(), ids=lambda category: category.id)
def test_perfect_report_for_each_category_has_only_aggregate_feedback(category):
    with TestClient(app) as client:
        person = create_assessment_candidate(client, f"report-{uuid4().hex}@example.test")
        id_, questions = stored_attempt(person, category.specialization, category.grade)
        response = client.get(f"/api/v1/candidate/assessment-attempts/{id_}/report")
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["score"] == 100 and report["outcome"] == "passed"
        assert report["score_gate"] and report["competency_gate"] and report["changed_condition_gate"]
        assert sum(topic["max_points"] for topic in report["competencies"]) == 100
        assert all(topic["practice"] is None for topic in report["competencies"])
        assert {topic["id"] for topic in report["competencies"]} <= PRACTICE.keys()
        assert not ({"answers", "answer_key", "seed", "questions"} & report.keys())
        assert "private-seed" not in response.text
        assert all(question["prompt"] not in response.text for question in questions)


def test_failed_report_has_exercises_and_does_not_change_verified_grade():
    with TestClient(app) as client:
        person = create_assessment_candidate(client, f"failed-report-{uuid4().hex}@example.test")
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person["id"])
            profile.verified_specialization, profile.verified_grade, profile.test_score = "backend", "junior", 91
            db.commit()
        id_, _ = stored_attempt(person, "backend", "middle", "empty")
        report = client.get(f"/api/v1/candidate/assessment-attempts/{id_}/report").json()
        assert report["score"] == 0 and report["outcome"] == "failed"
        assert not report["score_gate"] and not report["competency_gate"] and not report["changed_condition_gate"]
        assert len(report["competencies"]) == 3
        assert all(topic["practice"] for topic in report["competencies"])
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person["id"])
            assert profile.verified_grade == "junior" and profile.test_score == 91


def test_structured_partial_feedback_uses_awarded_points():
    with TestClient(app) as client:
        person = create_assessment_candidate(client, f"partial-report-{uuid4().hex}@example.test")
        id_, _ = stored_attempt(person, "backend", "middle", "partial")
        report = client.get(f"/api/v1/candidate/assessment-attempts/{id_}/report").json()
        assert 0 < report["score"] < 100
        assert sum(topic["points"] for topic in report["competencies"]) == report["score"]
        assert any(0 < topic["points"] < topic["max_points"] for topic in report["competencies"])


def test_private_report_denies_employer_other_candidate_and_unfinished_attempt():
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as employer:
        person = create_assessment_candidate(owner, f"owner-{uuid4().hex}@example.test")
        id_, _ = stored_attempt(person)
        active_id, _ = stored_attempt(person, state="in_progress")
        assert owner.get(f"/api/v1/candidate/assessment-attempts/{active_id}/report").status_code == 409
        register_verified(other, f"other-{uuid4().hex}@example.test", "candidate")
        assert other.get(f"/api/v1/candidate/assessment-attempts/{id_}/report").status_code == 404
        register_verified(employer, f"employer-{uuid4().hex}@example.test", "employer")
        assert employer.get(f"/api/v1/candidate/assessment-attempts/{id_}/report").status_code == 403
        assert employer.get("/api/v1/candidate/journey").status_code == 403


def test_journey_read_does_not_create_profile_and_resume_ignores_expired_attempt():
    with TestClient(app) as client:
        person = register_verified(client, f"journey-{uuid4().hex}@example.test", "candidate")
        journey = client.get("/api/v1/candidate/journey").json()
        assert not journey["visible_to_employers"] and journey["next_step"]["id"] == "profile"
        assert client.get("/api/v1/candidate/profile").json() is None
        id_, _ = stored_attempt(person, state="in_progress")
        assert client.get("/api/v1/candidate/journey").json()["active_attempt"]["id"] == id_
        with SessionLocal() as db:
            db.get(AssessmentAttempt, id_).expires_at = now() - timedelta(seconds=1)
            db.commit()
        assert client.get("/api/v1/candidate/journey").json()["active_attempt"] is None


@pytest.mark.parametrize("guard", ["adult_attested_at", "published_at", "consent_processing_at", "available"])
def test_journey_visibility_tracks_each_publication_guard(guard):
    with TestClient(app) as client:
        person = create_assessment_candidate(client, f"guard-{uuid4().hex}@example.test")
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person["id"])
            profile.verified_specialization, profile.verified_grade, profile.test_score = "backend", "junior", 80
            db.commit()
        assert client.get("/api/v1/candidate/journey").json()["visible_to_employers"]
        with SessionLocal() as db:
            setattr(db.get(CandidateProfile, person["id"]), guard, False if guard == "available" else None)
            db.commit()
        journey = client.get("/api/v1/candidate/journey").json()
        assert not journey["visible_to_employers"] and journey["blockers"]
        assert journey["next_step"] is not None
