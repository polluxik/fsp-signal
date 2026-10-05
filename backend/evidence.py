"""Candidate-owned stories and evidence derived from persisted assessment actions."""

import hashlib
import json
from typing import Literal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from .assessment import grade_attempt
from .domain_errors import DomainError
from .models import AssessmentAttempt, CandidateProfile, User
from .preferences import is_blocked
from .schemas import AchievementStoryIn, EvidenceCard, MatchExplanation


class EvidenceError(DomainError):
    pass


def build_achievement_story_record(story: AchievementStoryIn) -> dict:
    """Persist only candidate-entered fields; provenance is assigned by the server."""
    return story.model_dump(mode="json", exclude={"formatted_narrative"})


def build_achievement_narrative(story: AchievementStoryIn | dict) -> str:
    values = story.model_dump(mode="json") if isinstance(story, AchievementStoryIn) else dict(story)
    title = (values.get("title") or "").strip()
    lines = []
    if title:
        lines.append(title)
    lines.append(f"Контекст: {(values.get('context') or '').strip()}")
    lines.append(f"Мой вклад: {(values.get('personal_contribution') or '').strip()}")
    decision = (values.get("decision") or "").strip()
    if decision:
        lines.append(f"Почему так: {decision}")
    result = (values.get("result") or "").strip()
    if values.get("result_scope") == "team":
        lines.append(f"Результат команды: {result}")
    else:
        lines.append(f"Заявленный личный результат: {result}")
    basis = (values.get("basis") or "").strip()
    lines.append("Основание: со слов кандидата" + (f"; {basis}" if basis else "; дополнительные материалы не приложены"))
    return "\n".join(lines)


def _stable_id(*parts: str) -> str:
    return hashlib.sha256(":\x1f:".join(parts).encode("utf-8")).hexdigest()[:32]


def _data_mode(user: User) -> str:
    return "synthetic" if user.origin == "synthetic_fixture" else "real"


def _story_card(profile: CandidateProfile, story: dict, mode: str) -> EvidenceCard:
    narrative = build_achievement_narrative(story)
    team_result = story.get("result_scope") == "team"
    content = {key: value for key, value in story.items() if key != "share_with_employers"}
    limitations = ["Рассказ введён кандидатом; платформа не проверяла его независимо."]
    if team_result:
        limitations.append("Результат относится к команде; описанный личный вклад также заявлен кандидатом.")
    return EvidenceCard(
        id=_stable_id(profile.user_id, "achievement_story", json.dumps(content, ensure_ascii=False, sort_keys=True)),
        competency=None,
        action=narrative,
        source_type="achievement_story",
        source_id=None,
        source_version="candidate-story/v1",
        assessed_at=None,
        verification_level="declared",
        scope="declared_team_result" if team_result else "declared_individual_result",
        limitations=limitations,
        data_mode=mode,
    )


def _skill_cards(profile: CandidateProfile, user: User, skills: list) -> list[EvidenceCard]:
    cards = []
    seen = set()
    for raw_skill in skills:
        if not isinstance(raw_skill, str):
            continue
        skill = " ".join(raw_skill.strip().split())[:80]
        normalized = skill.casefold()
        if not skill or normalized in seen:
            continue
        seen.add(normalized)
        cards.append(EvidenceCard(
            id=_stable_id(profile.user_id, "skill_claim", normalized),
            competency=None,
            action=f"Кандидат указал опыт с {skill}.",
            source_type="skill_claim",
            source_id=None,
            source_version="candidate-profile/v1",
            assessed_at=None,
            verification_level="declared",
            scope="candidate_claim",
            limitations=["Навык указан кандидатом и не был сопоставлен с проверенным действием."],
            data_mode=_data_mode(user),
        ))
    return cards


def _assessment_action(attempt: AssessmentAttempt, competency: str, questions: list,
                       answer_key: dict, answers: dict) -> str | None:
    actions: list[str] = []
    event_actions = {
        ("bm1", "dedupe_key"): "выбрал стабильный event_id для дедупликации",
        ("bm1", "concurrency_control"): "предусмотрел защиту от параллельной записи уникальным ограничением",
        ("bm1", "replay_result"): "вернул бы сохранённый результат без второго побочного эффекта",
        ("bm2", None): "определил минимальную проверку повтора одного event_id",
        ("bm3", None): "при изменённом payload того же ID выбрал конфликт без повторного эффекта",
    }
    for question in questions:
        expected = answer_key.get(question["id"])
        if expected is None:
            continue
        question_score, _, _, _ = grade_attempt([question], {question["id"]: expected}, answers)
        if question["competency"] != competency or question_score == 0:
            continue
        if competency == "event_idempotency" and attempt.blueprint_version == "2026.2":
            if question["id"] == "bm1" and isinstance(expected, dict):
                submitted = answers.get("bm1")
                if not isinstance(submitted, dict):
                    continue
                for field_id in ("dedupe_key", "concurrency_control", "replay_result"):
                    if submitted.get(field_id) == expected.get(field_id):
                        actions.append(event_actions[("bm1", field_id)])
            else:
                action = event_actions.get((question["id"], None))
                if action:
                    actions.append(action)
        elif question_score == question["points"]:
            actions.append(f"верно ответил на задание в ограниченном сценарии «{competency}»")
    if not actions:
        return None
    return "В сохранённом assessment кандидат " + "; ".join(actions) + "."


def _assessment_cards(profile: CandidateProfile, user: User, attempt: AssessmentAttempt) -> list[EvidenceCard]:
    if (attempt.candidate_id != profile.user_id or attempt.state != "scored" or attempt.outcome != "passed"
            or (attempt.specialization, attempt.grade) != (profile.verified_specialization, profile.verified_grade)):
        return []
    _, passed, competency_scores, _ = grade_attempt(attempt.questions or [], attempt.answer_key or {}, attempt.answers or {})
    if not passed:
        return []
    cards = []
    for competency, ratio in competency_scores.items():
        if ratio <= 0:
            continue
        questions = [q for q in attempt.questions if q.get("competency") == competency]
        action = _assessment_action(attempt, competency, questions, attempt.answer_key or {}, attempt.answers or {})
        if not action:
            continue
        cards.append(EvidenceCard(
            id=_stable_id("assessment", attempt.id, competency),
            competency=competency,
            action=action,
            source_type="assessment_attempt",
            source_id=attempt.id,
            source_version=f"{attempt.blueprint_version}/fixed-rubric-v1",
            assessed_at=attempt.submitted_at,
            verification_level="synthetic_fixture" if _data_mode(user) == "synthetic" else "verified_action",
            scope="bounded_simulated_assessment",
            limitations=["Подтверждает только отмеченные действия в этом ограниченном сценарии; не доказывает production-опыт."],
            data_mode=_data_mode(user),
        ))
    return cards


def _legacy_aggregate_card(profile: CandidateProfile, user: User) -> EvidenceCard | None:
    if not profile.verified_grade or not profile.verified_specialization or profile.test_score is None:
        return None
    synthetic = user.origin == "synthetic_fixture" or profile.verification_source == "synthetic_fixture"
    if profile.verification_source not in ("assessment", "synthetic_fixture"):
        return None
    data_mode = "synthetic" if synthetic else "real"
    prefix = "Синтетическая демонстрационная запись" if synthetic else "Ранее подтверждена категория"
    return EvidenceCard(
        id=_stable_id(profile.user_id, "legacy_aggregate", profile.verified_specialization, profile.verified_grade),
        competency=None,
        action=(f"{prefix}: {profile.verified_specialization} {profile.verified_grade}; "
                "конкретное действие не сохранено."),
        source_type="legacy_aggregate",
        source_id=None,
        source_version="legacy-aggregate/v1",
        assessed_at=profile.test_verified_at,
        verification_level="synthetic_fixture" if synthetic else "aggregate",
        scope="aggregate_only",
        limitations=["Нет сохранённой попытки и item-level ответов; конкретное действие не восстанавливается."],
        data_mode=data_mode,
    )


def list_candidate_evidence(db: Session, candidate_id: str, *, audience: Literal["self", "employer"]) -> list[EvidenceCard]:
    if audience not in ("self", "employer"):
        raise ValueError("audience must be 'self' or 'employer'")
    user = db.get(User, candidate_id)
    profile = db.get(CandidateProfile, candidate_id)
    if not user or user.role != "candidate" or not profile:
        return []
    employer_eligible = bool(profile.published_at and profile.consent_processing_at and profile.available
                             and profile.adult_attested_at)
    if audience == "employer" and not employer_eligible:
        return []

    cards: list[EvidenceCard] = []
    story = profile.achievement_story or {}
    if story and (audience == "self" or story.get("share_with_employers") is True):
        try:
            AchievementStoryIn.model_validate(story)
        except ValidationError:
            pass
        else:
            cards.append(_story_card(profile, story, _data_mode(user)))

    cards.extend(_skill_cards(profile, user, profile.skills or []))
    if profile.verified_attempt_id:
        attempt = db.get(AssessmentAttempt, profile.verified_attempt_id)
        if attempt:
            cards.extend(_assessment_cards(profile, user, attempt))
    else:
        aggregate = _legacy_aggregate_card(profile, user)
        if aggregate:
            cards.append(aggregate)
    return cards


def resolve_evidence_refs(db: Session, candidate_id: str, evidence_ids: list[str], employer_id: str) -> list[EvidenceCard]:
    employer = db.get(User, employer_id)
    profile = db.get(CandidateProfile, candidate_id)
    if not employer or employer.role != "employer" or not profile:
        raise EvidenceError("EVIDENCE_NOT_AVAILABLE", 404)
    if is_blocked(profile, employer_id):
        raise EvidenceError("EVIDENCE_NOT_AVAILABLE", 404)
    if len(evidence_ids) > 12:
        raise EvidenceError("EVIDENCE_NOT_AVAILABLE", 404)
    cards = list_candidate_evidence(db, candidate_id, audience="employer")
    by_id = {card.id: card for card in cards}
    requested = list(dict.fromkeys(evidence_ids))
    if any(evidence_id not in by_id for evidence_id in requested):
        raise EvidenceError("EVIDENCE_NOT_AVAILABLE", 404)
    return [by_id[evidence_id] for evidence_id in requested]


def build_interview_agenda(explanation: MatchExplanation) -> list[str]:
    agenda = []
    seen = set()
    for gap in explanation.gaps:
        competency = gap.competency.strip()
        if not competency or competency in seen:
            continue
        seen.add(competency)
        if gap.status == "unknown":
            agenda.append(f"{competency}: пока не оценивали. Обсудить: {gap.question.strip()}")
        else:
            agenda.append(f"{competency}: подтверждений в текущих данных мало. Уточнить: {gap.question.strip()}")
        if len(agenda) == 3:
            break
    return agenda
