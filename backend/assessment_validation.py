"""Deterministic synthetic stress test for assessment scoring mechanics.

This does not estimate real human item difficulty. It checks how the published
scoring rule behaves for stable latent profiles under small retest noise.
"""

from hashlib import sha256
from math import exp, sqrt
from statistics import mean

from .assessment import COMPETENCIES, grade_attempt, make_assessment


PROFILE_GROUPS = {
    "weak": -1.35,
    "boundary": 0.45,
    "strong": 2.0,
}


def _unit(*parts: object) -> float:
    digest = sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def _normal(*parts: object) -> float:
    return sum(_unit(*parts, index) for index in range(12)) - 6


def _logistic(value: float) -> float:
    if value >= 0:
        return 1 / (1 + exp(-value))
    scaled = exp(value)
    return scaled / (1 + scaled)


def _wrong(expected):
    if isinstance(expected, int):
        return expected + 1_000_003
    return "__synthetic_incorrect__"


def _answers_for_profile(category: str, profile_id: str, ability: float, form: int,
                         questions: list[dict], answer_key: dict) -> dict:
    answers = {}
    specialization, grade = category.split(":")
    del specialization, grade
    for question in questions:
        question_id = question["id"]
        expected = answer_key[question_id]
        targets = list(expected) if isinstance(expected, dict) else [None]
        submitted = {} if isinstance(expected, dict) else None
        for field_id in targets:
            item_id = f"{question_id}:{field_id or '-'}"
            difficulty = (_unit("difficulty", category, item_id) - 0.5) * 1.5
            if question["phase"] == 2:
                difficulty += 0.1
            stable_profile_effect = 0.22 * _normal("profile-item", category, profile_id, item_id)
            retest_noise = 0.18 * _normal("occasion", category, profile_id, form, item_id)
            probability = _logistic(2.25 * (ability - difficulty)
                                    + stable_profile_effect + retest_noise)
            correct = _unit("response", category, profile_id, item_id) < probability
            expected_value = expected[field_id] if field_id is not None else expected
            value = expected_value if correct else _wrong(expected_value)
            if field_id is None:
                submitted = value
            else:
                submitted[field_id] = value
        answers[question_id] = submitted
    return answers


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for index in ordered[start:end]:
            ranks[index] = average_rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float:
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((a - left_mean) ** 2 for a in left)
    right_ss = sum((b - right_mean) ** 2 for b in right)
    if not left_ss or not right_ss:
        return 0.0
    return numerator / sqrt(left_ss * right_ss)


def _spearman(left: list[float], right: list[float]) -> float:
    return _pearson(_ranks(left), _ranks(right))


def simulate_category(category: str, profiles_per_group: int = 20) -> dict:
    if category not in COMPETENCIES:
        raise ValueError("unsupported category")
    specialization, grade = category.split(":")
    records = []
    for group, center in PROFILE_GROUPS.items():
        for offset in range(profiles_per_group):
            profile_id = f"{group}-{offset + 1:02d}"
            ability = center + 0.28 * _normal("ability", category, profile_id)
            attempts = []
            for form in (1, 2):
                questions, answer_key = make_assessment(
                    specialization, grade,
                    sha256(f"{category}|{profile_id}|form-{form}".encode()).hexdigest(),
                )
                answers = _answers_for_profile(
                    category, profile_id, ability, form, questions, answer_key,
                )
                score, passed, _, _ = grade_attempt(questions, answer_key, answers)
                attempts.append({"score": score, "passed": passed})
            records.append({"group": group, "profile_id": profile_id, "attempts": attempts})

    first = [record["attempts"][0]["score"] for record in records]
    second = [record["attempts"][1]["score"] for record in records]
    crossings = sum(record["attempts"][0]["passed"] != record["attempts"][1]["passed"]
                    for record in records)
    group_summary = {}
    for group in PROFILE_GROUPS:
        group_attempts = [attempt for record in records if record["group"] == group
                          for attempt in record["attempts"]]
        group_summary[group] = {
            "profiles": profiles_per_group,
            "mean_score": round(mean(attempt["score"] for attempt in group_attempts), 3),
            "pass_rate": round(mean(attempt["passed"] for attempt in group_attempts), 4),
        }
    return {
        "category": category,
        "profiles": len(records),
        "forms_per_profile": 2,
        "pass_fail_agreement": round(1 - crossings / len(records), 4),
        "threshold_crossing_rate": round(crossings / len(records), 4),
        "mean_absolute_score_difference": round(
            mean(abs(a - b) for a, b in zip(first, second)), 3
        ),
        "spearman_score_correlation": round(_spearman(first, second), 4),
        "form_1_mean_score": round(mean(first), 3),
        "form_2_mean_score": round(mean(second), 3),
        "absolute_form_mean_gap": round(abs(mean(first) - mean(second)), 3),
        "groups": group_summary,
        "strong_minus_weak_mean_score": round(
            group_summary["strong"]["mean_score"] - group_summary["weak"]["mean_score"], 3
        ),
        "strong_minus_weak_pass_rate": round(
            group_summary["strong"]["pass_rate"] - group_summary["weak"]["pass_rate"], 4
        ),
    }


def simulate_all(profiles_per_group: int = 20) -> dict:
    categories = [simulate_category(category, profiles_per_group) for category in sorted(COMPETENCIES)]
    return {
        "status": "synthetic_mechanics_only",
        "model_version": "assessment-stress-v1",
        "profiles_per_group_per_category": profiles_per_group,
        "groups": list(PROFILE_GROUPS),
        "limitations": [
            "Ответы сгенерированы явной latent-ability моделью, а не получены от людей.",
            "Сложность и дискриминативность заданий заданы как допущения и не подтверждают релевантность роли.",
            "Результат проверяет только устойчивость scoring mechanics; человеческий пилот и экспертный rubric review рекомендованы, но Q&A не требует их для MVP.",
            "В двух формах используется общая стабильная случайная величина ответа на item; высокая agreement зависит от этой модели и не является независимым измерением поведения людей.",
        ],
        "proposed_gates": {
            "minimum_pass_fail_agreement": 0.8,
            "maximum_threshold_crossing_rate": 0.1,
            "maximum_absolute_form_mean_gap": 5.0,
            "minimum_strong_minus_weak_mean_score": 30.0,
        },
        "categories": categories,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Синтетический отчёт assessment test-retest",
        "",
        "**Статус: синтетический mechanics-only stress test. Это не человеческая калибровка и не доказательство валидности заданий.**",
        "",
        "Детерминированный симулятор заранее задаёт latent ability слабых, пограничных и сильных профилей,",
        "после чего формирует две независимые формы, добавляет небольшой retest noise и применяет production",
        "grading rule. Организатор явно разрешил синтетическую симуляцию кандидатов, но экспертный rubric",
        "review и добровольный человеческий пилот рекомендованы, но не обязательны по Q&A.",
        "",
        "| Категория | N | Agreement | Crossing | Средняя абсолютная Δ score | Spearman | Form gap | Strong−weak score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in report["categories"]:
        lines.append(
            f"| `{result['category']}` | {result['profiles']} | "
            f"{result['pass_fail_agreement']:.1%} | {result['threshold_crossing_rate']:.1%} | "
            f"{result['mean_absolute_score_difference']:.1f} | "
            f"{result['spearman_score_correlation']:.3f} | "
            f"{result['absolute_form_mean_gap']:.1f} | "
            f"{result['strong_minus_weak_mean_score']:.1f} |"
        )
    gates = report["proposed_gates"]
    failed = []
    for result in report["categories"]:
        if result["pass_fail_agreement"] < gates["minimum_pass_fail_agreement"]:
            failed.append(f"{result['category']}: agreement")
        if result["threshold_crossing_rate"] > gates["maximum_threshold_crossing_rate"]:
            failed.append(f"{result['category']}: crossing")
        if result["absolute_form_mean_gap"] > gates["maximum_absolute_form_mean_gap"]:
            failed.append(f"{result['category']}: form gap")
        if result["strong_minus_weak_mean_score"] < gates["minimum_strong_minus_weak_mean_score"]:
            failed.append(f"{result['category']}: separation")
    lines.extend([
        "",
        "## Результат gates",
        "",
        ("Все предложенные synthetic-mechanics gates пройдены."
         if not failed else "Не пройдены: " + ", ".join(failed) + "."),
        "",
        "## Ограничения",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
    ])
    return "\n".join(lines)
