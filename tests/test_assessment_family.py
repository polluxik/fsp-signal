"""Behavioral tests for the deliberately narrow backend-middle assessment pilot."""

from backend.assessment import BLUEPRINT_VERSION, COMPETENCIES, grade_attempt, make_assessment


def _grade(questions, answer_key, answers):
    return grade_attempt(questions, answer_key, answers)


def test_backend_middle_event_family_distinguishes_replay_from_changed_payload():
    questions, answer_key = make_assessment("backend", "middle", "a11ce")
    event_questions = [q for q in questions if q["competency"] == "event_idempotency"]

    assert [q["id"] for q in event_questions] == ["bm1", "bm2", "bm3"]
    assert event_questions[0]["type"] == "structured"
    assert {field["id"] for field in event_questions[0]["fields"]} == {
        "dedupe_key", "concurrency_control", "replay_result",
    }
    assert event_questions[2]["phase"] == 2

    score, passed, competencies, _ = _grade(questions, answer_key, answer_key)
    assert score == 100 and passed
    assert competencies["event_idempotency"] == 1

    wrong_design = dict(answer_key)
    wrong_design["bm1"] = dict(answer_key["bm1"], dedupe_key="payload_hash")
    _, _, wrong_competencies, _ = _grade(questions, answer_key, wrong_design)
    assert wrong_competencies["event_idempotency"] < 1

    wrong_mutation = dict(answer_key)
    wrong_mutation["bm3"] = "apply_again"
    _, passed, _, _ = _grade(questions, answer_key, wrong_mutation)
    assert not passed

    incomplete = dict(answer_key)
    incomplete.pop("bm3")
    score, passed, _, _ = _grade(questions, answer_key, incomplete)
    assert score < 100 and not passed


def test_saved_2026_1_attempt_remains_gradable_after_blueprint_upgrade():
    legacy_questions = [
        {"id": "old-number", "competency": "event_idempotency", "points": 8,
         "phase": 1, "type": "number"},
        {"id": "old-number-two", "competency": "event_idempotency", "points": 8,
         "phase": 1, "type": "number"},
        {"id": "old-mutation", "competency": "event_idempotency", "points": 14,
         "phase": 2, "type": "number"},
        {"id": "old-choice", "competency": "data_integrity", "points": 8,
         "phase": 1, "type": "choice"},
        {"id": "old-choice-two", "competency": "data_integrity", "points": 27,
         "phase": 1, "type": "choice"},
        {"id": "old-choice-three", "competency": "failure_recovery", "points": 20,
         "phase": 1, "type": "choice"},
        {"id": "old-choice-four", "competency": "failure_recovery", "points": 15,
         "phase": 1, "type": "choice"},
    ]
    old_key = {"old-number": 42, "old-number-two": 18, "old-mutation": 91,
               "old-choice": "unique", "old-choice-two": "check",
               "old-choice-three": "key", "old-choice-four": "same"}

    assert BLUEPRINT_VERSION == "2026.2"
    assert set(COMPETENCIES) == {
        "backend:junior", "backend:middle", "frontend:junior", "frontend:middle",
    }
    score, passed, _, _ = _grade(legacy_questions, old_key, old_key)
    assert (score, passed) == (100, True)


def test_seeded_variants_keep_all_categories_complete_and_mutation_gated():
    for category in COMPETENCIES:
        specialization, grade = category.split(":")
        for seed in range(100):
            questions, answer_key = make_assessment(specialization, grade, f"{seed:032x}")
            assert sum(q["points"] for q in questions) == 100
            assert {q["phase"] for q in questions} == {1, 2}
            assert len({q["id"] for q in questions}) == len(questions)
            assert _grade(questions, answer_key, answer_key)[:2] == (100, True)

            first_question = questions[0]
            wrong_regular = dict(answer_key)
            expected_regular = answer_key[first_question["id"]]
            if isinstance(expected_regular, dict):
                wrong_value = dict(expected_regular)
                field_id = next(iter(wrong_value))
                wrong_value[field_id] = "__incorrect__"
                wrong_regular[first_question["id"]] = wrong_value
            elif isinstance(expected_regular, int):
                wrong_regular[first_question["id"]] = expected_regular + 1
            else:
                wrong_regular[first_question["id"]] = "__incorrect__"
            assert _grade(questions, answer_key, wrong_regular)[0] < 100

            mutation = next(q for q in questions if q["phase"] == 2)
            wrong_mutation = dict(answer_key)
            expected_mutation = answer_key[mutation["id"]]
            if isinstance(expected_mutation, dict):
                wrong_mutation[mutation["id"]] = {key: "__incorrect__" for key in expected_mutation}
            elif isinstance(expected_mutation, int):
                wrong_mutation[mutation["id"]] = expected_mutation + 1
            else:
                wrong_mutation[mutation["id"]] = "__incorrect__"
            assert not _grade(questions, answer_key, wrong_mutation)[1]

            phase_two_ids = {q["id"] for q in questions if q["phase"] == 2}
            incomplete_mutation = {key: value for key, value in answer_key.items()
                                   if key not in phase_two_ids}
            assert not _grade(questions, answer_key, incomplete_mutation)[1]
