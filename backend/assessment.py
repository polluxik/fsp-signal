"""Versioned category-specific assessment blueprints. Keys remain server-side."""

import random
import secrets
from .assessment_data_analyst import make_data_analyst_groups
from .assessment_parts import part, structured_part
from .assessment_qa import make_qa_groups
from .taxonomy import available_categories, get_category

BLUEPRINT_VERSION = "2026.2"  # Historical/default version retained for the original four tracks.
COMPETENCIES = {
    f"{category.specialization}:{category.grade}": [item.id for item in category.competencies]
    for category in available_categories()
}


def blueprint_version_for(specialization: str, grade: str) -> str:
    category = get_category(specialization, grade)
    if category is None:
        raise ValueError("unsupported category")
    return category.blueprint_version


def make_assessment(specialization: str, grade: str, seed: str | None = None):
    key = f"{specialization}:{grade}"
    if get_category(specialization, grade) is None:
        raise ValueError("unsupported category")
    rng = random.Random(int(seed, 16) if seed is not None else secrets.randbits(128))
    groups = []

    if key.startswith("qa:"):
        groups = make_qa_groups(grade, rng)
    elif key.startswith("data_analyst:"):
        groups = make_data_analyst_groups(grade, rng)
    elif key == "backend:middle":
        groups = [
            ("event_idempotency", [
                structured_part("bm1", "После сетевого таймаута одно платёжное событие может прийти повторно. Составьте правило обработки: ключ дедупликации, защита от параллельной записи и ответ на повтор.", 12, [
                    {"id": "dedupe_key", "label": "Стабильный ключ события", "points": 4,
                     "options": [{"value": "event_id", "label": "Исходный event_id"},
                                 {"value": "payload_hash", "label": "Хеш текущего payload"},
                                 {"value": "request_id", "label": "ID HTTP-запроса"}]},
                    {"id": "concurrency_control", "label": "Защита от параллельной обработки", "points": 4,
                     "options": [{"value": "unique_constraint", "label": "Уникальное ограничение в БД и транзакция"},
                                 {"value": "select_then_insert", "label": "Сначала SELECT, потом INSERT без ограничения"},
                                 {"value": "process_lock", "label": "Локальная блокировка одного процесса"}]},
                    {"id": "replay_result", "label": "Ответ при повторной доставке", "points": 4,
                     "options": [{"value": "stored_result", "label": "Вернуть сохранённый результат без второго эффекта"},
                                 {"value": "apply_again", "label": "Применить событие ещё раз"},
                                 {"value": "reject_all", "label": "Отклонить все последующие запросы"}]},
                ], {"dedupe_key": "event_id", "concurrency_control": "unique_constraint",
                    "replay_result": "stored_result"}),
                part("bm2", "Минимальный тест, который отличает безопасный обработчик от ошибочного: какое событие повторить и что проверить?", 8, "same_id_once",
                     options=[{"value": "same_id_once", "label": "Отправить один event_id дважды и проверить один побочный эффект"},
                              {"value": "two_ids", "label": "Отправить два разных event_id и проверить два эффекта"},
                              {"value": "same_body", "label": "Отправить одинаковый body с новыми event_id"}]),
                part("bm3", "Изменение условия: тот же event_id повторно пришёл с другим payload. Как должен ответить обработчик?", 10, "conflict", phase=2,
                     options=[{"value": "conflict", "label": "Вернуть конфликт и не повторять побочный эффект"},
                              {"value": "apply_again", "label": "Применить новые данные как ещё одно событие"},
                              {"value": "return_old", "label": "Молча вернуть старый результат, не проверяя payload"}]),
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
    elif key == "frontend:middle":
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
    else:
        raise ValueError("unsupported category")

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
        if isinstance(expected, dict):
            correct_points = 0
            submitted_values = submitted if isinstance(submitted, dict) else {}
            for field in question.get("fields", []):
                field_id = field.get("id")
                if field_id in expected and submitted_values.get(field_id) == expected[field_id]:
                    correct_points += field.get("points", 0)
            awarded = min(question["points"], correct_points)
            correct = awarded == question["points"]
        elif isinstance(expected, int):
            correct = str(submitted).strip() == str(expected)
            awarded = question["points"] if correct else 0
        else:
            correct = isinstance(submitted, str) and submitted.strip().lower() == expected
            awarded = question["points"] if correct else 0
        if question["phase"] == 2 and not correct:
            mutation_correct = False
        group_scores[skill] = group_scores.get(skill, 0) + awarded
    score = sum(group_scores.values())
    passed = (score >= 70 and mutation_correct and
              all(group_scores[name] * 2 >= max_points for name, max_points in group_max.items()))
    competencies = {name: round(group_scores[name] / group_max[name], 3) for name in group_max}
    return score, passed, competencies, group_scores
