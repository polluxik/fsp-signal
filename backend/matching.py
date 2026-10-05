"""Deterministic, explainable matching over verified categories."""

from collections import Counter
from datetime import datetime, timezone
import math
import re

from .assessment import COMPETENCIES
from .config import settings
from .models import CandidateProfile, HiringNeed


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
                profile.verified_specialization and profile.verified_grade and profile.test_score is not None)


def eligible(profile: CandidateProfile, need: HiringNeed, fsp_only: bool = False, stack: list[str] | None = None) -> bool:
    if not can_search(profile):
        return False
    if (profile.verified_specialization, profile.verified_grade) != (need.specialization, need.grade):
        return False
    if need.salary_max_rub < profile.min_salary_rub:
        return False
    if need.work_format != "any" and profile.work_format not in (need.work_format, "any"):
        return False
    if fsp_only and not fsp_bonus(profile):
        return False
    if stack and not {x.lower() for x in stack}.issubset({x.lower() for x in (profile.skills or [])}):
        return False
    return True


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
        "work_format": profile.work_format, "min_salary_rub": profile.min_salary_rub,
        "fsp_status": profile.fsp_status, "fsp_result": profile.fsp_result if fsp_bonus(profile) else None,
    }
    if result is not None:
        card["match"] = result
    return card
