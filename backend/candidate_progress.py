"""Private candidate journey and aggregate assessment feedback, without LLM calls."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assessment import grade_attempt
from .db import get_db
from .matching import can_search
from .models import AssessmentAttempt, CandidateProfile, User, now
from .security import aware, get_user, require
from .taxonomy import competency_labels, get_category

router = APIRouter(prefix="/api/v1/candidate", tags=["Candidate progress"])


class JourneyStep(BaseModel):
    id: str
    label: str
    done: bool
    tab: Literal["profile", "test", "preferences"]


class ActiveAttempt(BaseModel):
    id: str
    expires_at: datetime


class JourneyOut(BaseModel):
    visible_to_employers: bool
    steps: list[JourneyStep]
    blockers: list[str]
    next_step: JourneyStep | None
    active_attempt: ActiveAttempt | None
    fsp_status: str


class CompetencyResult(BaseModel):
    id: str
    label: str
    points: int
    max_points: int
    percent: int
    meets_minimum: bool
    practice: str | None


class AssessmentReportOut(BaseModel):
    attempt_id: str
    category: str
    blueprint_version: str
    submitted_at: datetime | None
    outcome: Literal["passed", "failed"]
    score: int
    score_gate: bool
    competency_gate: bool
    changed_condition_gate: bool
    competencies: list[CompetencyResult]
    next_action: str
    limitations: str


# Exercises teach a skill without revealing a live question or its solution.
PRACTICE = {
    "data_trace": "Возьмите небольшой список чисел и вручную проследите преобразования, включая пустой список и повторяющиеся элементы.",
    "validation": "Составьте таблицу обязательных полей API и негативных примеров; проверьте, что при ошибке данные не записываются.",
    "http_api": "Спроектируйте ответы API для ошибочного ввода, отсутствующего ресурса и сбоя сервера. Объясните выбранные классы статусов.",
    "event_idempotency": "Опишите контракт повторной доставки события: одинаковый идентификатор, изменившееся тело и потерявшийся ответ.",
    "data_integrity": "Нарисуйте параллельное выполнение двух транзакций и определите, какие инварианты должны защищаться в базе.",
    "failure_recovery": "Составьте сценарии потери ответа, таймаута и повторного запроса; для каждого задайте ожидаемый итог операции.",
    "javascript_trace": "Проследите выполнение небольшой цепочки преобразований массива и проверьте результат на нескольких входах.",
    "ui_state": "Смоделируйте несколько обновлений состояния подряд и объясните, откуда каждое обновление берёт исходное значение.",
    "forms": "Проверьте форму только клавиатурой: подписи полей, сообщения об ошибках и сохранение введённых данных.",
    "request_races": "Нарисуйте временную шкалу двух запросов с обратным порядком ответов и отменой одного запроса.",
    "derived_state": "Найдите в компоненте данные, полностью вычисляемые из входных параметров, и опишите поведение при их изменении.",
    "error_recovery": "Опишите переходы интерфейса между загрузкой, ошибкой и успешным повтором с сохранением пользовательского ввода.",
    "test_design": "Для новой формы выделите классы эквивалентности и граничные значения; объясните, почему выбранных проверок достаточно.",
    "bug_reporting": "Напишите баг-репорт с окружением, шагами, ожидаемым и фактическим результатом, затем попросите коллегу воспроизвести его.",
    "api_testing": "Составьте проверки API для валидных, отсутствующих и ошибочных полей и отдельно проверьте побочные эффекты.",
    "risk_based_testing": "Ранжируйте риски небольшой функции по ущербу и вероятности; составьте план проверок при ограниченном времени.",
    "automation_design": "Разделите проверки функции по уровням и определите данные, независимость и причины нестабильности автотестов.",
    "reliability_testing": "Спроектируйте проверки повторов, конкуренции и частичного отказа сервиса; сформулируйте сохраняемые инварианты.",
    "sql_querying": "На небольших таблицах проверьте JOIN и GROUP BY; отдельно рассмотрите NULL, дубликаты и пустой результат.",
    "data_quality": "Составьте правила проверки пропусков, дублей и несогласованных значений перед расчётом отчёта.",
    "metric_definition": "Определите числитель, знаменатель, период и единицу наблюдения продуктовой метрики на небольшом примере.",
    "experiment_analysis": "Составьте план эксперимента: единица рандомизации, основная метрика, контроль утечек и интерпретация неопределённости.",
    "metric_integrity": "Проверьте, как повторы событий и смена периода влияют на числитель и знаменатель одной метрики.",
    "data_validation": "Разработайте проверки свежести, схемы и сверки агрегатов для витрины данных; опишите действия при отклонении.",
}


@router.get("/journey", response_model=JourneyOut)
def candidate_journey(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    profile = db.get(CandidateProfile, user.id)
    # Reading onboarding never creates a profile or changes consent.
    rows = [
        ("profile", "Сохранить имя и контактный email", bool(profile and profile.full_name and profile.contact_email), "profile"),
        ("assessment", "Подтвердить категорию тестом", bool(profile and profile.verified_specialization and profile.verified_grade and profile.test_score is not None), "test"),
        ("processing", "Разрешить обработку профиля", bool(profile and profile.consent_processing_at), "profile"),
        ("adult", "Подтвердить возраст 18+", bool(profile and profile.adult_attested_at), "preferences"),
        ("publication", "Разрешить публикацию профиля", bool(profile and profile.published_at), "profile"),
        ("availability", "Включить получение приглашений", bool(profile and profile.available), "preferences"),
    ]
    steps = [JourneyStep(id=id_, label=label, done=done, tab=tab) for id_, label, done, tab in rows]
    active = db.scalar(select(AssessmentAttempt).where(
        AssessmentAttempt.candidate_id == user.id, AssessmentAttempt.state == "in_progress",
        AssessmentAttempt.expires_at > now()).order_by(AssessmentAttempt.started_at.desc()).limit(1))
    return JourneyOut(
        visible_to_employers=bool(profile and can_search(profile)), steps=steps,
        blockers=[step.label for step in steps if not step.done],
        next_step=next((step for step in steps if not step.done), None),
        active_attempt=ActiveAttempt(id=active.id, expires_at=aware(active.expires_at)) if active else None,
        fsp_status=profile.fsp_status if profile else "unlinked",
    )


@router.get("/assessment-attempts/{attempt_id}/report", response_model=AssessmentReportOut)
def assessment_report(attempt_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    attempt = db.get(AssessmentAttempt, attempt_id)
    if not attempt or attempt.candidate_id != user.id:
        raise HTTPException(404, "NOT_FOUND")
    if attempt.state != "scored":
        raise HTTPException(409, "ASSESSMENT_REPORT_NOT_READY")
    score, _, _, points = grade_attempt(attempt.questions, attempt.answer_key, attempt.answers)
    maximums = {}
    for question in attempt.questions:
        skill = question["competency"]
        maximums[skill] = maximums.get(skill, 0) + question["points"]
    # Reuse the grader on changed-condition questions, including structured partial scoring.
    phase2 = [question for question in attempt.questions if question["phase"] == 2]
    phase2_score, _, _, _ = grade_attempt(phase2, attempt.answer_key, attempt.answers)
    changed_ok = bool(phase2) and phase2_score == sum(question["points"] for question in phase2)
    labels = competency_labels()
    topics = [CompetencyResult(
        id=skill, label=labels.get(skill, skill), points=points[skill], max_points=maximum,
        percent=round(100 * points[skill] / maximum), meets_minimum=points[skill] * 2 >= maximum,
        practice=PRACTICE.get(skill, "Разберите практический пример этой компетенции и проверьте его на граничных случаях.") if points[skill] < maximum else None,
    ) for skill, maximum in maximums.items()]
    category = get_category(attempt.specialization, attempt.grade)
    next_action = "Откройте маршрут кандидата и проверьте согласия и публикацию профиля."
    if attempt.outcome != "passed":
        next_action = ("Пройдите упражнения по пробелам. Повтор того же уровня — через 72 часа, до 3 попыток за 7 дней; "
                       "после неудачного Middle можно выбрать Junior той же специализации без расходования его квоты. "
                       "Другие ограничения проверяет сервер при старте; прежний подтверждённый грейд сохраняется.")
    return AssessmentReportOut(
        attempt_id=attempt.id, category=category.label if category else f"{attempt.specialization} · {attempt.grade}",
        blueprint_version=attempt.blueprint_version, submitted_at=attempt.submitted_at,
        outcome=attempt.outcome, score=attempt.score, score_gate=score >= 70,
        competency_gate=all(topic.meets_minimum for topic in topics), changed_condition_gate=changed_ok,
        competencies=topics, next_action=next_action,
        limitations="Результат этой попытки на небольшом наборе заданий. Это не вероятность найма и не полная оценка навыка. Отчёт доступен только вам.",
    )
