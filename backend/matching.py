"""Deterministic, explainable matching over verified categories."""

from collections import Counter
from datetime import datetime, timezone
import math
import re

from .assessment import COMPETENCIES
from .config import settings
from .models import CandidateProfile, HiringNeed
from .preferences import preferences_data
from .schemas import (
    CompatibilityCheck, CompatibilityReport, CompatibilitySoftSignal, RoleCardIn,
)


SKILL_NAMES = {
    "data_trace": "Трассировка данных", "validation": "Валидация входа", "http_api": "HTTP API",
    "event_idempotency": "Повторные события", "data_integrity": "Целостность данных",
    "failure_recovery": "Обработка отказов", "javascript_trace": "JavaScript: выполнение",
    "ui_state": "Состояние интерфейса", "forms": "Формы и доступность",
    "request_races": "Гонки запросов", "derived_state": "Производное состояние",
    "error_recovery": "Ошибки интерфейса",
}

ALIASES = {
    "повтор": "event_idempotency", "идемпотент": "event_idempotency",
    "конкур": "data_integrity", "транзакц": "data_integrity",
    "отказ": "failure_recovery", "api": "http_api", "валидац": "validation",
    "javascript": "javascript_trace", "форм": "forms", "поиск": "request_races",
    "запрос": "request_races", "кеш": "derived_state", "ошиб": "error_recovery",
}


def suggest_competencies(description: str, specialization: str, grade: str) -> list[str]:
    allowed = set(COMPETENCIES.get(f"{specialization}:{grade}", []))
    lowered = description.lower()
    found = {skill for stem, skill in ALIASES.items() if stem in lowered and skill in allowed}
    return sorted(found)


def tokens(text: str) -> Counter:
    return Counter(re.findall(r"[a-zа-яё0-9_]{3,}", text.lower()))


def lexical_similarity(need: HiringNeed, profile: CandidateProfile) -> float:
    verified = [name for name, score in (profile.competencies or {}).items() if score >= 0.5]
    left = tokens(f"{need.title} {need.description} {' '.join(need.competencies or [])}")
    right = tokens(" ".join(f"{name} {SKILL_NAMES.get(name, '')}" for name in verified))
    if not left or not right:
        return 0.0
    overlap = sum(min(left[word], right[word]) for word in left.keys() & right.keys())
    return min(1.0, overlap / math.sqrt(sum(left.values()) * sum(right.values())))


def fsp_bonus(profile: CandidateProfile) -> float:
    valid = profile.fsp_status == "verified_external" or (settings.app_mode == "demo" and profile.fsp_status == "mock")
    if not valid:
        return 0.0
    return {"participant": 0.2, "finalist": 0.6, "prize": 1.0}.get(profile.fsp_result, 0.0)


def can_search(profile: CandidateProfile) -> bool:
    return bool(profile.published_at and profile.consent_processing_at and profile.available and
                profile.adult_attested_at and profile.verified_specialization and
                profile.verified_grade and profile.test_score is not None)


def eligible(profile: CandidateProfile, need: HiringNeed, fsp_only: bool = False, stack: list[str] | None = None) -> bool:
    if not can_search(profile):
        return False
    if (profile.verified_specialization, profile.verified_grade) != (need.specialization, need.grade):
        return False
    preferences = preferences_data(profile)
    salary_floor = preferences["salary_min_rub"]
    if salary_floor is not None and need.salary_max_rub < salary_floor:
        return False
    if need.work_format != "any" and need.work_format not in preferences["allowed_work_formats"]:
        return False
    if fsp_only and not fsp_bonus(profile):
        return False
    if stack and not {x.lower() for x in stack}.issubset({x.lower() for x in (profile.skills or [])}):
        return False
    return True


def evaluate_compatibility(
    profile: CandidateProfile, role: RoleCardIn | dict, *,
    mode: str, offer_terms: dict | None = None, role_version_id: str | None = None,
) -> CompatibilityReport:
    """Evaluate declared hard constraints without including private values in explanations."""
    if mode not in ("search", "invitation"):
        raise ValueError("mode must be 'search' or 'invitation'")
    role_data = role.model_dump(mode="json") if isinstance(role, RoleCardIn) else dict(role)
    prefs = preferences_data(profile)
    checks: list[CompatibilityCheck] = []

    floor = prefs["salary_min_rub"]
    if floor is None:
        salary_status, salary_text = "pass", "Минимальное зарплатное ограничение не задано."
    elif mode == "search":
        maximum = role_data.get("salary_max_rub")
        if maximum is None:
            salary_status, salary_text = "unknown", "Не хватает сведений о верхней границе зарплаты."
        elif maximum >= floor:
            salary_status, salary_text = "pass", "Опубликованный диапазон не противоречит зарплатному ожиданию."
        else:
            salary_status, salary_text = "fail", "Опубликованный диапазон не совпадает с вашим ограничением."
    else:
        terms = offer_terms or {}
        offered_minimum = terms.get("salary_min_rub")
        if offered_minimum is None:
            salary_status, salary_text = "unknown", "Не хватает сведений о конкретном предложении."
        elif offered_minimum >= floor:
            salary_status, salary_text = "pass", "Конкретное предложение проходит зарплатное ограничение."
        else:
            salary_status, salary_text = "fail", "Конкретное предложение не совпадает с вашим ограничением."
    checks.append(CompatibilityCheck(code="salary", status=salary_status, public_text=salary_text))

    formats = prefs["allowed_work_formats"]
    work_format = (offer_terms or {}).get("work_format", role_data.get("work_format")) if mode == "invitation" else role_data.get("work_format")
    if not formats or work_format is None:
        format_status, format_text = "unknown", "Не хватает сведений для сравнения формата работы."
    elif work_format in formats:
        format_status, format_text = "pass", "Формат работы совместим с выбранными условиями."
    else:
        format_status, format_text = "fail", "Формат работы не совпадает с выбранными условиями."
    checks.append(CompatibilityCheck(code="work_format", status=format_status, public_text=format_text))

    city = role_data.get("work_city")
    if work_format in ("office", "hybrid") and prefs["allowed_cities"]:
        if not city:
            location_status, location_text = "unknown", "Не хватает сведений о городе для оценки поездок в офис."
        elif city.casefold() in {value.casefold() for value in prefs["allowed_cities"]}:
            location_status, location_text = "pass", "Город роли входит в допустимые варианты."
        else:
            location_status, location_text = "fail", "Город роли не входит в допустимые варианты."
    else:
        location_status, location_text = "pass", "Ограничение по городу не задано для этого формата."
    checks.append(CompatibilityCheck(code="location", status=location_status, public_text=location_text))

    excluded = {value.casefold() for value in prefs["excluded_industries"]}
    industry = role_data.get("industry")
    if excluded and not industry:
        industry_status, industry_text = "unknown", "Не хватает сведений об отрасли роли."
    elif excluded and industry.casefold() in excluded:
        industry_status, industry_text = "fail", "Отрасль роли отмечена как нежелательная."
    else:
        industry_status, industry_text = "pass", "Ограничения по отрасли соблюдены."
    checks.append(CompatibilityCheck(code="industry", status=industry_status, public_text=industry_text))

    max_take_home = prefs["max_take_home_minutes"]
    duration = role_data.get("take_home_minutes")
    if max_take_home is None:
        take_home_status, take_home_text = "pass", "Лимит дополнительного задания не задан."
    elif duration is None:
        take_home_status, take_home_text = "unknown", "Не хватает сведений о дополнительном задании."
    elif duration > max_take_home:
        take_home_status, take_home_text = "fail", "Нагрузка дополнительного задания превышает выбранный лимит."
    else:
        take_home_status, take_home_text = "pass", "Нагрузка дополнительного задания укладывается в выбранный лимит."
    checks.append(CompatibilityCheck(code="take_home", status=take_home_status, public_text=take_home_text))

    available = prefs["available"]
    checks.append(CompatibilityCheck(
        code="availability", status="pass" if available else "fail",
        public_text="Поиск включён." if available else "Поиск сейчас на паузе.",
    ))
    checks.append(CompatibilityCheck(
        code="adult_attestation", status="pass" if prefs["adult_hiring_confirmed"] else "unknown",
        public_text="Возрастное условие подтверждено самим кандидатом." if prefs["adult_hiring_confirmed"]
        else "Для наймового действия требуется подтверждение кандидата.",
    ))

    soft_signals: list[CompatibilitySoftSignal] = []
    preferred_stack = prefs["preferred_stack"]
    if preferred_stack and "stack" in role_data:
        role_stack = {value.casefold() for value in role_data.get("stack") or []}
        matched = bool(role_stack & {value.casefold() for value in preferred_stack})
        soft_signals.append(CompatibilitySoftSignal(
            code="preferred_stack", matched=matched,
            public_text="Совпадают предпочитаемые технологии." if matched
            else "Заявленный стек не совпал с мягким предпочтением; это не hard-фильтр.",
        ))
    preferred_tasks = prefs["preferred_tasks"]
    if preferred_tasks and any(role_data.get(field) for field in ("title", "description", "first_30_days")):
        role_text = " ".join((role_data.get("title") or "", role_data.get("description") or "",
                              role_data.get("first_30_days") or "")).casefold()
        matched = any(value.casefold() in role_text for value in preferred_tasks)
        soft_signals.append(CompatibilitySoftSignal(
            code="preferred_tasks", matched=matched,
            public_text="Описание связано с предпочитаемыми задачами." if matched
            else "Описание не совпало с мягким предпочтением по задачам.",
        ))

    states = {item.status for item in checks}
    status = "incompatible" if "fail" in states else (
        "needs_clarification" if "unknown" in states else "compatible"
    )
    return CompatibilityReport(
        status=status, checks=checks, soft_signals=soft_signals,
        preference_version=prefs["version"], role_version_id=role_version_id,
    )


def score_profile(profile: CandidateProfile, need: HiringNeed) -> dict:
    allowed = COMPETENCIES[f"{need.specialization}:{need.grade}"]
    chosen = [x for x in (need.competencies or []) if x in allowed] or allowed
    skills = profile.competencies or {}
    c = sum(float(skills.get(name, 0)) for name in chosen) / len(chosen)
    t = (profile.test_score or 0) / 100
    f = fsp_bonus(profile)
    checked = profile.test_verified_at
    if checked:
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - checked).days
        r = 1.0 if days <= 30 else (0.5 if days <= 90 else 0.0)
    else:
        r = 0.0
    n = lexical_similarity(need, profile)
    components = {
        "competencies": round(50*c, 1), "assessment": round(30*t, 1),
        "fsp": round(10*f, 1), "freshness": round(5*r, 1), "text": round(5*n, 1),
    }
    score = round(sum(components.values()), 1)
    top = sorted(chosen, key=lambda item: skills.get(item, 0), reverse=True)
    reasons = [f"Подтверждена категория {need.specialization} {need.grade}"]
    reasons.extend(f"Проверено: {SKILL_NAMES.get(name, name)} ({round(float(skills.get(name, 0))*100)}%)"
                   for name in top if skills.get(name, 0) >= .5)
    gaps = [f"Не подтверждено: {SKILL_NAMES.get(name, name)}" for name in chosen if skills.get(name, 0) < .5]
    if f:
        reasons.append("Есть достижение ФСП (демонстрационная запись)" if profile.fsp_status == "mock"
                       else "Есть подтверждённое достижение ФСП")
    return {"score": score, "components": components, "reasons": reasons, "gaps": gaps,
            "algorithm_version": "match_v1"}


def public_candidate(profile: CandidateProfile, result: dict | None = None) -> dict:
    card = {
        "id": profile.user_id, "alias": f"Кандидат #{profile.user_id[:8]}",
        "specialization": profile.verified_specialization, "grade": profile.verified_grade,
        "test_score": profile.test_score, "competencies": profile.competencies or {},
        "verification_source": profile.verification_source or "unknown",
        "assessed_at": profile.test_verified_at.isoformat() if profile.test_verified_at else None,
        "skills_declared": profile.skills or [], "experience_months_declared": profile.experience_months,
        "work_format": profile.work_format,
        "fsp_status": profile.fsp_status, "fsp_result": profile.fsp_result if fsp_bonus(profile) else None,
    }
    if result is not None:
        card["match"] = result
    return card
