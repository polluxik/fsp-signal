"""Four fixed blueprints. The answer key never leaves the API."""

import random
import secrets
from typing import Any

BLUEPRINT_VERSION = "2026.1"
COMPETENCIES = {
    "backend:junior": ["data_trace", "validation", "http_api"],
    "backend:middle": ["event_idempotency", "data_integrity", "failure_recovery"],
    "frontend:junior": ["javascript_trace", "ui_state", "forms"],
    "frontend:middle": ["request_races", "derived_state", "error_recovery"],
}


def part(identifier: str, prompt: str, points: int, answer: Any, phase: int = 1, options: list | None = None):
    public = {"id": identifier, "prompt": prompt, "points": points, "phase": phase,
              "type": "choice" if options else "number"}
    if options:
        public["options"] = options
    return public, answer


def make_assessment(specialization: str, grade: str, seed: str | None = None):
    key = f"{specialization}:{grade}"
    if key not in COMPETENCIES:
        raise ValueError("unsupported category")
    rng = random.Random(int(seed, 16) if seed is not None else secrets.randbits(128))
    groups = []

    if key == "backend:middle":
        a, b = rng.randint(30, 180), rng.randint(20, 140)
        groups = [
            ("event_idempotency", [
                part("bm1", f"Баланс 0. События (A,+{a}), (B,+{b}), (A,+{a}). Сколько начислит ошибочный обработчик без проверки event_id?", 8, 2*a+b),
                part("bm2", "Каков баланс после устранения повторов по event_id?", 8, a+b),
                part("bm3", "Изменение условия: ID третьего события теперь C. Каков корректный баланс?", 14, 2*a+b, phase=2),
            ]),
            ("data_integrity", [
                part("bm4", "Два потока одновременно создают запись с одним event_id. Как обеспечить отсутствие дублей?", 20, "unique",
                     options=[{"value":"unique","label":"Уникальное ограничение БД и транзакция"}, {"value":"check","label":"Предварительная проверка SELECT, затем INSERT"}, {"value":"memory","label":"Локальный lock только в одном процессе"}]),
                part("bm5", "Какой вариант может допустить гонку между проверкой и записью?", 15, "check",
                     options=[{"value":"unique","label":"INSERT с уникальным ограничением"}, {"value":"check","label":"SELECT, затем INSERT без ограничения"}, {"value":"upsert","label":"Атомарный UPSERT"}]),
            ]),
            ("failure_recovery", [
                part("bm6", "Ответ POST потерялся после успешной записи. Что позволяет безопасно повторить запрос?", 20, "key",
                     options=[{"value":"key","label":"Ключ идемпотентности и сохранённый результат"}, {"value":"sleep","label":"Ожидание фиксированные 5 секунд"}, {"value":"get","label":"Замена любого POST на GET"}]),
                part("bm7", "Какой результат должен увидеть клиент после повторного POST с тем же ключом и телом?", 15, "same",
                     options=[{"value":"same","label":"Тот же логический результат без второй записи"}, {"value":"second","label":"Вторую независимую операцию"}, {"value":"blocked","label":"Постоянную блокировку всех запросов"}]),
            ]),
        ]
    elif key == "backend:junior":
        a, b = rng.randint(2, 20), rng.randint(2, 20)
        groups = [
            ("data_trace", [
                part("bj1", f"Функция sum([a,b]) получает [{a},{b}]. Какой результат?", 10, a+b),
                part("bj2", f"Какой результат max([{a},{b}])?", 10, max(a,b)),
                part("bj3", f"Изменение: к списку добавили {a}. Какова новая сумма?", 10, 2*a+b, phase=2),
            ]),
            ("validation", [
                part("bj4", "Тело запроса не содержит обязательное поле. Что сделать?", 20, "reject",
                     options=[{"value":"reject","label":"Отклонить запрос и показать ошибку поля"}, {"value":"guess","label":"Угадать значение поля"}, {"value":"save","label":"Сохранить неполный объект"}]),
                part("bj5", "Должна ли запись создаваться при ошибке валидации?", 15, "no", options=[{"value":"no","label":"Нет"},{"value":"yes","label":"Да"}]),
            ]),
            ("http_api", [
                part("bj6", "Как безопасно передать введённый пользователем параметр в SQL-запрос?", 20, "parameter",
                     options=[{"value":"parameter","label":"Параметризованный запрос"},{"value":"concat","label":"Конкатенация строк"}]),
                part("bj7", "Невалидный JSON от клиента: какой класс HTTP-ответа подходит?", 15, "4xx",
                     options=[{"value":"4xx","label":"4xx"},{"value":"2xx","label":"2xx"},{"value":"5xx","label":"5xx"}]),
            ]),
        ]
    elif key == "frontend:junior":
        a, b = rng.randint(2, 15), rng.randint(2, 15)
        groups = [
            ("javascript_trace", [
                part("fj1", f"Массив [{a},{b}]. Чему равна сумма после map(x => x * 2)?", 10, 2*(a+b)),
                part("fj2", f"Какова длина массива [{a},{b}] после map?", 10, 2),
                part("fj3", f"Изменение: к массиву добавили {a}. Чему равна сумма после map(x => x * 2)?", 10, 2*(2*a+b), phase=2),
            ]),
            ("ui_state", [
                part("fj4", "Два быстрых обновления счётчика зависят от предыдущего значения. Какой подход безопаснее?", 20, "functional",
                     options=[{"value":"functional","label":"Функциональное обновление состояния"},{"value":"captured","label":"Дважды записать захваченное старое значение"}]),
                part("fj5", "Где хранить видимое значение счётчика для повторного рендера?", 15, "state",
                     options=[{"value":"state","label":"В состоянии компонента"},{"value":"global","label":"В локальной переменной обработчика"}]),
            ]),
            ("forms", [
                part("fj6", "Как связать видимую подпись с полем ввода?", 20, "label",
                     options=[{"value":"label","label":"label с htmlFor и id поля"},{"value":"placeholder","label":"Только placeholder"}]),
                part("fj7", "Что сделать при ошибке отправки формы?", 15, "feedback",
                     options=[{"value":"feedback","label":"Показать ошибку и сохранить ввод"},{"value":"erase","label":"Удалить введённые данные без пояснения"}]),
            ]),
        ]
    else:
        a, b = rng.randint(1, 9), rng.randint(10, 19)
        groups = [
            ("request_races", [
                part("fm1", f"Запрос #{a} начался раньше запроса #{b}; ответ #{b} пришёл первым. Какой ответ соответствует самому свежему запросу?", 10, b),
                part("fm2", f"Позднее пришёл ответ #{a}. Следует ли заменять им актуальную выдачу?", 10, "no", options=[{"value":"no","label":"Нет"},{"value":"yes","label":"Да"}]),
                part("fm3", f"Изменение: запрос #{b} отменён, а активен снова #{a}. Ответ какого запроса теперь допустим?", 10, a, phase=2),
            ]),
            ("derived_state", [
                part("fm4", "Куда поместить значение, которое полностью вычисляется из props и не редактируется отдельно?", 20, "derive",
                     options=[{"value":"derive","label":"Вычислять из props в рендере"},{"value":"duplicate","label":"Дублировать в независимом state без синхронизации"}]),
                part("fm5", "При изменении исходных props нужно ли сохранять старое производное значение?", 15, "no", options=[{"value":"no","label":"Нет"},{"value":"yes","label":"Да"}]),
            ]),
            ("error_recovery", [
                part("fm6", "Последний запрос завершился ошибкой. Что должен видеть пользователь?", 20, "error",
                     options=[{"value":"error","label":"Понятную ошибку и возможность повтора"},{"value":"stale","label":"Новый успех, которого не было"}]),
                part("fm7", "Повтор запроса успешен. Как обновить состояние ошибки?", 15, "clear",
                     options=[{"value":"clear","label":"Убрать старую ошибку и показать данные"},{"value":"keep","label":"Оставить ошибку как текущую"}]),
            ]),
        ]

    questions, answer_key = [], {}
    for competency, parts in groups:
        for public, answer in parts:
            public["competency"] = competency
            questions.append(public)
            answer_key[public["id"]] = answer
    return questions, answer_key


def public_questions(questions: list, phase: int) -> list:
    return [q for q in questions if q["phase"] <= phase]


def grade_attempt(questions: list, answer_key: dict, answers: dict):
    group_scores: dict[str, int] = {}
    group_max: dict[str, int] = {}
    mutation_correct = True
    for question in questions:
        skill = question["competency"]
        group_max[skill] = group_max.get(skill, 0) + question["points"]
        submitted = answers.get(question["id"])
        expected = answer_key[question["id"]]
        if isinstance(expected, int):
            correct = str(submitted).strip() == str(expected)
        else:
            correct = isinstance(submitted, str) and submitted.strip().lower() == expected
        if question["phase"] == 2 and not correct:
            mutation_correct = False
        group_scores[skill] = group_scores.get(skill, 0) + (question["points"] if correct else 0)
    score = sum(group_scores.values())
    passed = (score >= 70 and mutation_correct and
              all(group_scores[name] * 2 >= max_points for name, max_points in group_max.items()))
    competencies = {name: round(group_scores[name] / group_max[name], 3) for name in group_max}
    return score, passed, competencies, group_scores
