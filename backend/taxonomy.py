"""The reviewed specialization/grade catalog shared by assessment and matching."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompetencyDefinition:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    id: str
    specialization: str
    grade: str
    label: str
    blueprint_version: str
    competencies: tuple[CompetencyDefinition, ...]
    available: bool = True


_CATEGORY_ROWS = (
    ("backend", "junior", "Backend · Junior", "2026.2", (
        ("data_trace", "Трассировка данных"),
        ("validation", "Валидация входа"),
        ("http_api", "HTTP API"),
    )),
    ("backend", "middle", "Backend · Middle", "2026.2", (
        ("event_idempotency", "Повторные события"),
        ("data_integrity", "Целостность данных"),
        ("failure_recovery", "Обработка отказов"),
    )),
    ("frontend", "junior", "Frontend · Junior", "2026.2", (
        ("javascript_trace", "JavaScript: выполнение"),
        ("ui_state", "Состояние интерфейса"),
        ("forms", "Формы и доступность"),
    )),
    ("frontend", "middle", "Frontend · Middle", "2026.2", (
        ("request_races", "Гонки запросов"),
        ("derived_state", "Производное состояние"),
        ("error_recovery", "Ошибки интерфейса"),
    )),
    ("qa", "junior", "QA · Junior", "qa-junior-2026.1", (
        ("test_design", "Проектирование проверок"),
        ("bug_reporting", "Воспроизводимый баг-репорт"),
        ("api_testing", "Проверка API"),
    )),
    ("qa", "middle", "QA · Middle", "qa-middle-2026.1", (
        ("risk_based_testing", "Приоритизация рисков"),
        ("automation_design", "Проектирование автотестов"),
        ("reliability_testing", "Надёжность и отказоустойчивость"),
    )),
    ("data_analyst", "junior", "Аналитик данных · Junior", "data-analyst-junior-2026.1", (
        ("sql_querying", "SQL-запросы"),
        ("data_quality", "Качество данных"),
        ("metric_definition", "Определение метрик"),
    )),
    ("data_analyst", "middle", "Аналитик данных · Middle", "data-analyst-middle-2026.1", (
        ("experiment_analysis", "Анализ эксперимента"),
        ("metric_integrity", "Целостность метрик"),
        ("data_validation", "Валидация данных"),
    )),
)

CATEGORY_CATALOG = tuple(
    CategoryDefinition(
        id=f"{specialization}:{grade}", specialization=specialization, grade=grade,
        label=label, blueprint_version=blueprint_version,
        competencies=tuple(CompetencyDefinition(id=skill_id, label=skill_label)
                           for skill_id, skill_label in competencies),
    )
    for specialization, grade, label, blueprint_version, competencies in _CATEGORY_ROWS
)
_BY_ID = {category.id: category for category in CATEGORY_CATALOG}


def available_categories() -> tuple[CategoryDefinition, ...]:
    return tuple(category for category in CATEGORY_CATALOG if category.available)


def get_category(specialization: str, grade: str) -> CategoryDefinition | None:
    category = _BY_ID.get(f"{specialization}:{grade}")
    return category if category and category.available else None


def competencies_for(specialization: str, grade: str) -> tuple[str, ...]:
    category = get_category(specialization, grade)
    return tuple(item.id for item in category.competencies) if category else ()


def competency_labels() -> dict[str, str]:
    return {
        competency.id: competency.label
        for category in available_categories()
        for competency in category.competencies
    }


def catalog_payload() -> list[dict]:
    return [{
        "id": category.id,
        "specialization": category.specialization,
        "grade": category.grade,
        "label": category.label,
        "blueprint_version": category.blueprint_version,
        "available": category.available,
        "competencies": [{"id": item.id, "label": item.label} for item in category.competencies],
    } for category in available_categories()]
