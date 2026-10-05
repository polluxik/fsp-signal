"""End-to-end API rules, using the real evaluator and separate users."""

import re
from datetime import timedelta
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from backend.assessment import COMPETENCIES, grade_attempt, make_assessment  # noqa: E402
from backend.db import SessionLocal  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import AssessmentAttempt, CandidateProfile, Invitation, MailOutbox, now  # noqa: E402


def csrf(client: TestClient):
    return {"x-csrf-token": client.cookies.get("fsp_csrf")}


def register_verified(client: TestClient, email: str, role: str) -> dict:
    created = client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse123!", "role": role})
    assert created.status_code == 201, created.text
    with SessionLocal() as db:
        mail = db.scalar(select(MailOutbox).where(MailOutbox.recipient == email).order_by(MailOutbox.created_at.desc()))
        token = parse_qs(urlparse(re.search(r"https?://\S+", mail.body).group()).query)["token"][0]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "CorrectHorse123!"}).status_code == 200
    return created.json()


def test_assessment_variants_are_correct_for_all_categories():
    for spec_grade in COMPETENCIES:
        spec, grade = spec_grade.split(":")
        for _ in range(100):
            questions, key = make_assessment(spec, grade)
            assert sum(q["points"] for q in questions) == 100
            assert {q["phase"] for q in questions} == {1, 2}
            assert len({q["id"] for q in questions}) == len(questions)
            repeat_questions, repeat_key = make_assessment(spec, grade, "abcdef1234567890")
            repeat_questions_again, repeat_key_again = make_assessment(spec, grade, "abcdef1234567890")
            assert (repeat_questions, repeat_key) == (repeat_questions_again, repeat_key_again)
            score, passed, evidence, _ = grade_attempt(questions, key, key)
            assert (score, passed) == (100, True)
            assert all(value == 1 for value in evidence.values())
            without_mutation = {part_id: answer for part_id, answer in key.items()
                                if part_id not in {q["id"] for q in questions if q["phase"] == 2}}
            _, passed, _, _ = grade_attempt(questions, key, without_mutation)
            assert not passed
            score, passed, _, _ = grade_attempt(questions, key, {})
            assert (score, passed) == (0, False)


def test_resume_preview_is_private_and_requires_explicit_save():
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    for index, line in enumerate(("Ivan Petrov", "ivan@example.test", "+7 999 000 11 22",
                                  "Experience 3 years", "Python, FastAPI, PostgreSQL and Docker developer")):
        pdf.drawString(40, 760-index*20, line)
    pdf.save()
    with TestClient(app) as candidate, TestClient(app) as employer:
        register_verified(candidate, "resume@example.test", "candidate")
        register_verified(employer, "resume-company@example.test", "employer")
        preview = candidate.post("/api/v1/candidate/resume/preview",
                                 files={"file":("resume.pdf", stream.getvalue(), "application/pdf")},
                                 headers=csrf(candidate))
        assert preview.status_code == 200, preview.text
        draft = preview.json()
        assert draft["full_name"] == "Ivan Petrov"
        assert draft["contact_email"] == "ivan@example.test"
        assert draft["experience_months"] == 36
        assert {"Python", "FastAPI", "PostgreSQL"}.issubset(set(draft["skills"]))
        assert candidate.get("/api/v1/candidate/profile").json() is None
        assert employer.post("/api/v1/candidate/resume/preview",
                             files={"file":("resume.pdf", stream.getvalue(), "application/pdf")},
                             headers=csrf(employer)).status_code == 403
        bad = candidate.post("/api/v1/candidate/resume/preview",
                             files={"file":("bad.pdf", b"not pdf", "application/pdf")}, headers=csrf(candidate))
        assert bad.status_code == 422 and bad.json()["detail"] == "NOT_A_PDF"


def test_reverse_hiring_and_contact_boundary():
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as second_employer:
        person = register_verified(candidate, "candidate@example.test", "candidate")
        company = register_verified(employer, "company@example.test", "employer")
        register_verified(second_employer, "other-company@example.test", "employer")

        profile = {"full_name":"Тестовый Кандидат", "contact_email":"secret@example.test",
                   "contact_phone":"+79990001122", "summary":"Не публиковать этот текст",
                   "skills":["Python","PostgreSQL"], "experience_months":36,
                   "min_salary_rub":180000, "work_format":"remote", "consent_processing":True,
                   "published":True, "adult_hiring_confirmed":True,
                   "achievement_story":{"title":"Устранение дублей",
                       "context":"Повторная доставка события могла создать двойную запись.",
                       "personal_contribution":"Я добавил защиту обработки по event ID.",
                       "decision":"Выбрал уникальное ограничение в базе данных.",
                       "result":"Команда перестала вручную разбирать дубли.",
                       "result_scope":"team", "basis":"Самоописание, метрика не приложена.",
                       "share_with_employers":False}}
        saved = candidate.put("/api/v1/candidate/profile", json=profile, headers=csrf(candidate))
        assert saved.status_code == 200, saved.text
        assert "Результат команды:" in saved.json()["achievement_story"]["formatted_narrative"]
        assert "Основание: со слов кандидата" in saved.json()["achievement_story"]["formatted_narrative"]
        readback_story = candidate.get("/api/v1/candidate/profile").json()["achievement_story"]
        roundtrip = candidate.put("/api/v1/candidate/profile",
                                  json=profile | {"achievement_story":readback_story}, headers=csrf(candidate))
        assert roundtrip.status_code == 200, roundtrip.text
        assert roundtrip.json()["achievement_story"]["formatted_narrative"] == readback_story["formatted_narrative"]

        started = candidate.post("/api/v1/candidate/assessment-attempts",
                                 json={"specialization":"backend","grade":"middle"}, headers=csrf(candidate))
        assert started.status_code == 201, started.text
        attempt = started.json()
        assert "answer_key" not in str(attempt)
        with SessionLocal() as db:
            from backend.models import AssessmentAttempt
            key = db.get(AssessmentAttempt, attempt["id"]).answer_key
        first = {q["id"]: key[q["id"]] for q in attempt["questions"] if q["phase"] == 1}
        incomplete_first = dict(first)
        incomplete_first["bm1"] = dict(key["bm1"], replay_result="")
        rejected_incomplete = candidate.put(
            f"/api/v1/candidate/assessment-attempts/{attempt['id']}/answers",
            json={"answers":incomplete_first}, headers=csrf(candidate))
        assert rejected_incomplete.status_code == 409
        assert rejected_incomplete.json()["detail"] == "ANSWERS_INCOMPLETE"
        assert candidate.put(f"/api/v1/candidate/assessment-attempts/{attempt['id']}/answers",
                             json={"answers":first}, headers=csrf(candidate)).status_code == 200
        advanced = candidate.post(f"/api/v1/candidate/assessment-attempts/{attempt['id']}/advance",
                                  headers=csrf(candidate))
        assert advanced.status_code == 200, advanced.text
        assert candidate.put(f"/api/v1/candidate/assessment-attempts/{attempt['id']}/answers",
                             json={"answers":{"bm3":key["bm3"]}}, headers=csrf(candidate)).status_code == 200
        result = candidate.post(f"/api/v1/candidate/assessment-attempts/{attempt['id']}/submit",
                                headers=csrf(candidate))
        assert result.status_code == 200, result.text
        assert result.json()["verified_category"] == "backend:middle"
        assert result.json()["score"] == 100
        with SessionLocal() as db:
            assert db.get(CandidateProfile, person["id"]).verified_attempt_id == attempt["id"]

        visible_evidence = candidate.get("/api/v1/candidate/evidence")
        assert visible_evidence.status_code == 200, visible_evidence.text
        assert visible_evidence.headers["cache-control"] == "no-store"
        assert any(card["source_id"] == attempt["id"] and card["source_type"] == "assessment_attempt"
                   for card in visible_evidence.json())
        assert "answer_key" not in visible_evidence.text and '"answers"' not in visible_evidence.text

        with SessionLocal() as db:
            failed_questions, failed_key = make_assessment("backend", "middle", "badc0de")
            failed_answers = dict(failed_key, bm3="apply_again")
            failed_attempt = AssessmentAttempt(
                candidate_id=person["id"], specialization="backend", grade="middle",
                blueprint_version="2026.2", seed="badc0de", questions=failed_questions,
                answer_key=failed_key, answers=failed_answers, phase=2, state="in_progress",
                expires_at=now()+timedelta(minutes=5),
            )
            db.add(failed_attempt); db.commit()
            failed_attempt_id = failed_attempt.id
        failed_result = candidate.post(f"/api/v1/candidate/assessment-attempts/{failed_attempt_id}/submit",
                                       headers=csrf(candidate))
        assert failed_result.status_code == 200 and failed_result.json()["outcome"] == "failed"
        with SessionLocal() as db:
            assert db.get(CandidateProfile, person["id"]).verified_attempt_id == attempt["id"]
        assert candidate.get("/api/v1/candidate/passport.pdf").headers["content-type"] == "application/pdf"

        company_profile = {"company_name":"Финтех демо", "description":"Сервис событий",
                           "industry":"ИТ", "contact_email":"team@example.test"}
        assert employer.put("/api/v1/employer/company", json=company_profile, headers=csrf(employer)).status_code == 200
        need = {"title":"Backend Middle", "description":"Нужна обработка повторных событий и отказов",
                "specialization":"backend", "grade":"middle", "competencies":["event_idempotency","failure_recovery"],
                "stack":["Python"], "salary_min_rub":180000, "salary_max_rub":230000, "work_format":"remote"}
        created = employer.post("/api/v1/employer/needs", json=need, headers=csrf(employer))
        assert created.status_code == 201, created.text
        need_id = created.json()["id"]
        found = employer.post("/api/v1/employer/searches", json={"need_id":need_id}, headers=csrf(employer))
        assert found.status_code == 201, found.text
        assert found.json()["results"][0]["id"] == person["id"]
        assert "secret@example.test" not in found.text
        assert "Тестовый Кандидат" not in found.text
        assert "Не публиковать этот текст" not in found.text
        assert "Повторная доставка события могла создать двойную запись." not in found.text
        assert "Я добавил защиту обработки по event ID." not in found.text
        snapshot_id = found.json()["id"]
        history = employer.get("/api/v1/employer/searches").json()
        assert len(history) == 1 and history[0]["id"] == snapshot_id
        assert history[0]["result_count"] == 1
        assert second_employer.get("/api/v1/employer/searches").json() == []
        assert second_employer.get(f"/api/v1/employer/searches/{snapshot_id}").status_code == 404
        assert second_employer.get(f"/api/v1/employer/searches?need_id={need_id}").status_code == 404
        refined = employer.post("/api/v1/employer/searches",
                                json={"need_id":need_id,"parent_snapshot_id":snapshot_id},
                                headers=csrf(employer))
        assert refined.status_code == 201, refined.text
        assert refined.json()["parent_snapshot_id"] == snapshot_id
        assert {item["id"] for item in employer.get("/api/v1/employer/searches").json()} == {
            snapshot_id, refined.json()["id"]}
        another_need = employer.post("/api/v1/employer/needs", json=need | {"title":"Вторая команда"},
                                     headers=csrf(employer)).json()["id"]
        wrong_parent = employer.post("/api/v1/employer/searches",
                                     json={"need_id":another_need,"parent_snapshot_id":snapshot_id},
                                     headers=csrf(employer))
        assert wrong_parent.status_code == 404

        offer = {"candidate_id":person["id"], "need_id":need_id, "offer_text":"Приглашаем обсудить работу с событиями в нашей команде.",
                 "reason":"Подтверждена обработка повторных событий в тесте.",
                 "salary_min_rub":180000, "salary_max_rub":230000, "work_format":"remote",
                 "employer_contact":"team@example.test"}
        blocked_salary = employer.post("/api/v1/employer/invitations", json=offer | {"salary_min_rub":170000},
                                       headers=csrf(employer) | {"Idempotency-Key":"salary-low"})
        assert blocked_salary.status_code == 201, blocked_salary.text
        assert "compatibility" not in employer.get("/api/v1/employer/invitations").text
        low_candidate_invite = candidate.get("/api/v1/candidate/invitations").json()[0]
        assert low_candidate_invite["id"] == blocked_salary.json()["id"]
        assert low_candidate_invite["compatibility"]["status"] == "incompatible"
        assert "180000" not in str(low_candidate_invite["compatibility"])
        rejected_accept = candidate.post(
            f"/api/v1/invitations/{blocked_salary.json()['id']}/accept", headers=csrf(candidate))
        assert rejected_accept.status_code == 409
        assert rejected_accept.json()["detail"] == "INVITATION_NOT_COMPATIBLE"
        assert employer.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 403
        assert candidate.post(f"/api/v1/invitations/{blocked_salary.json()['id']}/reject",
                              headers=csrf(candidate)).status_code == 200
        sent = employer.post("/api/v1/employer/invitations", json=offer,
                             headers=csrf(employer) | {"Idempotency-Key":"good-invite"})
        assert sent.status_code == 201, sent.text
        assert "compatibility" not in employer.get("/api/v1/employer/invitations").text
        invitation_id = sent.json()["id"]
        assert employer.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 403

        assert second_employer.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 403
        received = candidate.get("/api/v1/candidate/invitations").json()[0]
        assert received["salary_min_rub"] == 180000
        assert received["compatibility"]["status"] == "compatible"
        assert "min_salary_rub" not in str(received["compatibility"])
        paused = candidate.put("/api/v1/candidate/profile", json=profile | {"published":False},
                               headers=csrf(candidate))
        assert paused.status_code == 200
        unavailable_accept = candidate.post(f"/api/v1/invitations/{invitation_id}/accept",
                                            headers=csrf(candidate))
        assert unavailable_accept.status_code == 409
        assert unavailable_accept.json()["detail"] == "INVITATION_NOT_AVAILABLE"
        assert employer.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 403
        resumed = candidate.put("/api/v1/candidate/profile", json=profile | {"published":True},
                                headers=csrf(candidate))
        assert resumed.status_code == 200
        accepted = candidate.post(f"/api/v1/invitations/{invitation_id}/accept", headers=csrf(candidate))
        assert accepted.status_code == 200, accepted.text
        assert employer.get(f"/api/v1/employer/candidates/{person['id']}/contact").json()["email"] == "secret@example.test"
        assert second_employer.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 403
        grants = candidate.get("/api/v1/candidate/contact-grants").json()
        assert candidate.post(f"/api/v1/candidate/contact-grants/{grants[0]['id']}/revoke",
                              headers=csrf(candidate)).status_code == 200
        assert employer.get(f"/api/v1/employer/candidates/{person['id']}/contact").status_code == 403

        again = employer.post("/api/v1/employer/invitations", json=offer,
                              headers=csrf(employer) | {"Idempotency-Key":"next-invite"})
        assert again.status_code == 201
        with SessionLocal() as db:
            expired = db.get(Invitation, again.json()["id"])
            expired.expires_at = now()-timedelta(seconds=1)
            db.commit()
        from backend.mail_worker import expire_invitations
        assert expire_invitations() >= 1
        assert candidate.post(f"/api/v1/invitations/{again.json()['id']}/accept", headers=csrf(candidate)).status_code == 409
        assert candidate.put("/api/v1/candidate/profile", json=profile | {"published":False},
                             headers=csrf(candidate)).status_code == 200
        hidden_snapshot = employer.get(f"/api/v1/employer/searches/{snapshot_id}")
        assert hidden_snapshot.status_code == 200
        assert hidden_snapshot.json()["results"] == []
        assert hidden_snapshot.json()["unavailable_count"] == 1
