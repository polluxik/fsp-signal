"""Privacy, provenance, and honest narrative tests for candidate evidence."""

import pytest

from backend.db import SessionLocal
from backend.domain_errors import DomainError
from backend.evidence import (
    build_achievement_narrative,
    build_achievement_story_record,
    build_interview_agenda,
    list_candidate_evidence,
    resolve_evidence_refs,
)
from backend.models import AssessmentAttempt, CandidateProfile, User, now, uid
from backend.schemas import AchievementStoryIn, EvidenceGap, MatchExplanation


def _profile(db, *, origin="direct_signup", skills=None, story=None, verified=False):
    candidate_id = uid()
    db.add(User(id=candidate_id, email=f"{candidate_id}@example.test", password_hash="x",
                role="candidate", origin=origin))
    db.flush()
    profile = CandidateProfile(
        user_id=candidate_id, full_name="Private Name", summary="Private resume text",
        skills=skills or [], achievement_story=story or {}, consent_processing_at=now(),
        published_at=now(), adult_attested_at=now(), available=True,
        verified_specialization="backend" if verified else None,
        verified_grade="middle" if verified else None,
        test_score=86 if verified else None,
        verification_source="assessment" if verified else None,
        competencies={"event_idempotency": 0.9} if verified else {},
    )
    db.add(profile)
    db.flush()
    return profile


def _successful_attempt(db, profile):
    attempt_id = uid()
    questions = [
        {"id": "bm1", "competency": "event_idempotency", "points": 12, "phase": 1,
         "type": "structured", "fields": [
             {"id": "dedupe_key", "points": 4},
             {"id": "concurrency_control", "points": 4},
             {"id": "replay_result", "points": 4},
         ]},
        {"id": "bm4", "competency": "data_integrity", "points": 20, "phase": 1,
         "type": "choice"},
        {"id": "bm5", "competency": "data_integrity", "points": 15, "phase": 1,
         "type": "choice"},
        {"id": "bm6", "competency": "failure_recovery", "points": 20, "phase": 1,
         "type": "choice"},
        {"id": "bm7", "competency": "failure_recovery", "points": 15, "phase": 1,
         "type": "choice"},
        {"id": "bm3", "competency": "event_idempotency", "points": 10, "phase": 2,
         "type": "choice"},
    ]
    answer_key = {
        "bm1": {"dedupe_key": "event_id", "concurrency_control": "unique_constraint",
                "replay_result": "stored_result"},
        "bm4": "unique", "bm5": "check", "bm6": "key", "bm7": "same", "bm3": "conflict",
    }
    attempt = AssessmentAttempt(
        id=attempt_id, candidate_id=profile.user_id, specialization="backend", grade="middle",
        blueprint_version="2026.2", seed="a11ce", questions=questions, answer_key=answer_key,
        answers=answer_key, phase=2, state="scored", outcome="passed", score=86,
        expires_at=now(), submitted_at=now(),
    )
    db.add(attempt)
    db.flush()
    profile.verified_attempt_id = attempt_id
    return attempt


def _story(*, share=False, scope="team"):
    return {
        "title": "Защита обработки событий",
        "context": "Повторная доставка платёжного события могла создать двойную запись.",
        "personal_contribution": "Я добавил обработку повтора по стабильному event ID.",
        "decision": "Выбрал уникальное ограничение вместо локальной проверки в памяти.",
        "result": "Команда перестала вручную разбирать дубли в этом потоке.",
        "result_scope": scope,
        "basis": "Самоописание; метрика или артефакт не приложены.",
        "share_with_employers": share,
    }


def test_short_structured_story_keeps_context_contribution_decision_result_and_basis():
    payload = AchievementStoryIn.model_validate(_story(scope="team"))
    narrative = build_achievement_narrative(payload)

    assert "Контекст:" in narrative
    assert "Мой вклад:" in narrative
    assert "Почему так:" in narrative
    assert "Результат команды:" in narrative
    assert "Основание: со слов кандидата" in narrative
    assert "не приложены" in narrative
    assert "дубли" in narrative


def test_story_rejects_whitespace_that_would_create_an_empty_profile_claim():
    with pytest.raises(ValueError):
        AchievementStoryIn(
            context="        ", personal_contribution="Есть конкретный личный вклад", result="Есть результат",
        )


def test_story_preview_echo_is_rebuilt_from_candidate_facts_not_persisted_as_authority():
    payload = AchievementStoryIn.model_validate(_story() | {"formatted_narrative": "подменённый рассказ"})
    record = build_achievement_story_record(payload)

    assert "formatted_narrative" not in record
    assert "подменённый рассказ" not in build_achievement_narrative(record)


def test_unassessed_agenda_uses_unknown_language_and_caps_one_per_competency():
    agenda = build_interview_agenda(MatchExplanation(gaps=[
        EvidenceGap(competency="event_idempotency", status="unknown", question="Разберите повтор события."),
        EvidenceGap(competency="event_idempotency", status="gap", question="Покажите обработку гонки."),
        EvidenceGap(competency="data_integrity", status="gap", question="Расскажите о целостности данных."),
        EvidenceGap(competency="failure_recovery", status="unknown", question="Что делаете после сбоя?"),
    ]))

    assert len(agenda) == 3
    assert sum("event_idempotency" in item for item in agenda) == 1
    assert any("пока не оценивали" in item for item in agenda)
    assert all("не умеет" not in item.lower() for item in agenda)


def test_evidence_is_owner_scoped_opt_in_and_never_contains_private_assessment_payloads():
    with SessionLocal() as db:
        try:
            profile = _profile(db, skills=["Kafka", "QuasarDB"], story=_story(share=False), verified=True)
            attempt = _successful_attempt(db, profile)
            employer_id = uid()
            db.add(User(id=employer_id, email=f"{employer_id}@example.test", password_hash="x",
                        role="employer", origin="direct_signup"))
            db.flush()

            private_cards = list_candidate_evidence(db, profile.user_id, audience="self")
            story_card = next(card for card in private_cards if card.source_type == "achievement_story")
            assert "Результат команды:" in story_card.action
            assert story_card.verification_level == "declared"
            assert {card.action for card in private_cards if card.source_type == "skill_claim"} == {
                "Кандидат указал опыт с Kafka.", "Кандидат указал опыт с QuasarDB.",
            }
            assert all(card.verification_level == "declared" for card in private_cards
                       if card.source_type == "skill_claim")
            assert all(card.competency is None for card in private_cards if card.source_type == "skill_claim")

            employer_cards = list_candidate_evidence(db, profile.user_id, audience="employer")
            assert all(card.source_type != "achievement_story" for card in employer_cards)
            with pytest.raises(DomainError, match="EVIDENCE_NOT_AVAILABLE"):
                resolve_evidence_refs(db, profile.user_id, [story_card.id], employer_id)

            profile.achievement_story = dict(profile.achievement_story, share_with_employers=True)
            db.flush()
            shared = resolve_evidence_refs(db, profile.user_id, [story_card.id], employer_id)
            assert len(shared) == 1 and shared[0].verification_level == "declared"
            assert shared[0].source_type == "achievement_story"

            assessment_cards = [card for card in list_candidate_evidence(db, profile.user_id, audience="self")
                                if card.source_type == "assessment_attempt"]
            assert assessment_cards
            assert {card.source_id for card in assessment_cards} == {attempt.id}
            assert {card.id for card in assessment_cards} == {
                card.id for card in list_candidate_evidence(db, profile.user_id, audience="self")
                if card.source_type == "assessment_attempt"
            }
            serialized = [card.model_dump(mode="json") for card in assessment_cards + shared]
            assert all("answer_key" not in card and "answers" not in card for card in serialized)
            assert all("Private resume text" not in str(card) and "Private Name" not in str(card)
                       for card in serialized)
        finally:
            db.rollback()


def test_foreign_evidence_id_cannot_be_attached_to_another_candidates_invitation():
    with SessionLocal() as db:
        try:
            owner = _profile(db, story=_story(share=True))
            other = _profile(db, story=_story(share=True))
            employer_id = uid()
            db.add(User(id=employer_id, email=f"{employer_id}@example.test", password_hash="x",
                        role="employer", origin="direct_signup"))
            db.flush()
            foreign_card = next(card for card in list_candidate_evidence(db, other.user_id, audience="employer")
                                if card.source_type == "achievement_story")

            with pytest.raises(DomainError, match="EVIDENCE_NOT_AVAILABLE"):
                resolve_evidence_refs(db, owner.user_id, [foreign_card.id], employer_id)
        finally:
            db.rollback()


def test_fixture_without_attempt_emits_only_an_aggregate_with_no_invented_action_source():
    with SessionLocal() as db:
        try:
            profile = _profile(db, origin="synthetic_fixture", verified=True)
            profile.verification_source = "synthetic_fixture"
            profile.verified_attempt_id = None
            db.flush()

            cards = list_candidate_evidence(db, profile.user_id, audience="self")
            aggregate = next(card for card in cards if card.source_type == "legacy_aggregate")
            assert aggregate.source_id is None
            assert aggregate.data_mode == "synthetic"
            assert aggregate.verification_level == "synthetic_fixture"
            assert "конкретное действие не сохранено" in aggregate.action
        finally:
            db.rollback()
