import importlib
import json
from dataclasses import fields

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import schemas
from backend.config import Settings
from backend.main import app
from test_flow import csrf, register_verified


def _assistant_module():
    try:
        return importlib.import_module("backend.ai_assistant")
    except ModuleNotFoundError as error:
        if error.name == "backend.ai_assistant":
            return None
        raise


def test_ai_draft_models_are_intent_specific_and_reject_unrecognized_fields():
    model_names = (
        "AssistantDraftIn",
        "CandidatePreferencesDraft",
        "CandidateAchievementDraft",
        "EmployerRoleDraft",
    )
    models = [getattr(schemas, name, None) for name in model_names]
    assert all(model is not None for model in models)
    request, preferences, achievement, role = models

    assert request.model_validate({"text": "Удалённая работа", "external_ai_consent": False}).external_ai_consent is False
    assert preferences.model_config["extra"] == "forbid"
    assert achievement.model_config["extra"] == "forbid"
    assert role.model_config["extra"] == "forbid"
    assert preferences.model_validate({"salary_min_rub": 150000}).salary_min_rub == 150000
    assert achievement.model_validate({"context": "Команда теряла события.",
                                       "personal_contribution": "Я добавил идемпотентность.",
                                       "result": "Повторы больше не создавали записи."}).result_scope is None
    assert role.model_validate({"title": "QA-инженер", "grade": "junior"}).grade == "junior"

    with pytest.raises(ValidationError):
        request.model_validate({"text": "Удалённая работа"})
    with pytest.raises(ValidationError):
        preferences.model_validate({"salary_min_rub": 150000, "share_with_employers": True})
    with pytest.raises(ValidationError):
        achievement.model_validate({"context": "Контекст достаточно длинный.",
                                    "personal_contribution": "Мой вклад описан здесь.",
                                    "result": "Результат описан здесь.", "verified": True})
    with pytest.raises(ValidationError):
        role.model_validate({"title": "QA-инженер", "employer_contact": "hr@example.test"})
    with pytest.raises(ValidationError):
        role.model_validate({"interview_steps": [{
            "title": "Знакомство", "duration_minutes": 30,
            "unexpected_private_field": "must not be accepted",
        }]})
    with pytest.raises(ValidationError):
        role.model_validate({"specialization": "qa", "grade": "junior",
                             "competencies": ["event_idempotency"]})


def test_frontierai_configuration_has_bounded_defaults_and_never_repr_exposes_key(monkeypatch):
    for name in (
        "FRONTIERAI_BASE_URL", "FRONTIERAI_MODEL", "FRONTIERAI_API_KEY",
        "AI_ASSISTANT_MAX_INPUT_CHARS", "AI_ASSISTANT_MAX_OUTPUT_TOKENS",
        "AI_ASSISTANT_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    configured = Settings()

    assert getattr(configured, "frontierai_base_url", None) == "https://gateway.frontierai.ru/v1/chat/completions"
    assert getattr(configured, "frontierai_model", None) == "qwen3.8-27b-4a100"
    assert getattr(configured, "frontierai_api_key", None) is None
    assert getattr(configured, "assistant_max_input_chars", None) == 2000
    assert getattr(configured, "assistant_max_output_tokens", None) == 800
    assert getattr(configured, "assistant_timeout_seconds", None) == 30
    assert Settings(assistant_timeout_seconds=30).assistant_timeout_seconds == 30
    with pytest.raises(ValueError, match="AI_ASSISTANT_TIMEOUT_SECONDS"):
        Settings(assistant_timeout_seconds=31)
    key_field = next((item for item in fields(configured) if item.name == "frontierai_api_key"), None)
    assert key_field is not None
    assert key_field.repr is False

    monkeypatch.setenv("FRONTIERAI_API_KEY", "unit-test-secret")
    configured_with_key = Settings()
    assert configured_with_key.frontierai_api_key == "unit-test-secret"
    assert "unit-test-secret" not in repr(configured_with_key)


def test_provider_request_is_minimal_redacts_contacts_and_validates_typed_draft():
    assistant = _assistant_module()
    assert assistant is not None
    if assistant is None:
        return

    captured = []
    output = {"salary_min_rub": 160000, "preferred_stack": ["Python"]}
    transport = httpx.MockTransport(lambda request: (
        captured.append(request) or httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(output)}}],
        })
    ))
    configured = Settings(frontierai_api_key="provider-test-key")

    draft = assistant.generate_draft(
        "candidate_preferences",
        "Ищу Python от 160 тыс.; email me@example.test, телефон +7 999 123-45-67",
        external_ai_consent=True,
        configured=configured, transport=transport,
    )

    assert draft.salary_min_rub == 160000
    assert len(captured) == 1
    request = captured[0]
    assert request.headers["Authorization"] == "Bearer provider-test-key"
    assert request.extensions["timeout"] == {
        "connect": 30, "read": 30, "write": 30, "pool": 30,
    }
    body = json.loads(request.content)
    assert set(body) == {"model", "messages", "max_tokens", "chat_template_kwargs"}
    assert body["model"] == "qwen3.8-27b-4a100"
    assert body["max_tokens"] == 800
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "response_format" not in body
    assert len(body["messages"]) == 2
    submitted = json.loads(body["messages"][1]["content"])
    assert set(submitted) == {"intent", "text"}
    assert submitted["intent"] == "candidate_preferences"
    assert "me@example.test" not in submitted["text"]
    assert "+7 999 123-45-67" not in submitted["text"]
    assert "[контакт удалён]" in submitted["text"]


@pytest.mark.parametrize(("intent", "expected_fields", "enum_fields"), [
    (
        "candidate_preferences",
        {"salary_min_rub", "allowed_work_formats", "preferred_stack", "missing_fields", "follow_up_questions"},
        {
            "allowed_work_formats": ["remote", "hybrid", "office"],
            "missing_fields": [
                "salary_min_rub", "allowed_work_formats", "allowed_cities", "excluded_industries",
                "preferred_stack", "preferred_tasks", "max_take_home_minutes",
            ],
        },
    ),
    (
        "candidate_achievement",
        {"context", "personal_contribution", "result", "result_scope", "missing_fields", "follow_up_questions"},
        {
            "result_scope": ["individual", "team"],
            "missing_fields": ["context", "personal_contribution", "decision", "result", "result_scope", "basis"],
        },
    ),
    (
        "employer_role",
        {"title", "specialization", "grade", "work_format", "missing_fields", "ambiguous_fields"},
        {
            "specialization": ["backend", "frontend", "qa", "data_analyst"],
            "grade": ["junior", "middle"],
            "work_format": ["remote", "hybrid", "office"],
            "missing_fields": [
                "title", "description", "specialization", "grade", "competencies", "stack",
                "salary_min_rub", "salary_max_rub", "work_format", "work_city", "industry",
                "first_30_days", "interview_steps", "take_home_minutes", "response_sla_hours",
            ],
        },
    ),
])
def test_provider_receives_strict_intent_schema_for_reliable_draft_fields(intent, expected_fields, enum_fields):
    assistant = _assistant_module()
    assert assistant is not None
    if assistant is None:
        return

    captured = []
    transport = httpx.MockTransport(lambda request: (
        captured.append(request) or httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}],
        })
    ))
    assistant.generate_draft(
        intent, "Только факты, без контактов", external_ai_consent=True,
        configured=Settings(frontierai_api_key="provider-test-key"), transport=transport,
    )

    body = json.loads(captured[0].content)
    system_prompt = body["messages"][0]["content"]
    schema_marker = "JSON Schema:\n"
    assert schema_marker in system_prompt
    schema = json.loads(system_prompt.split(schema_marker, 1)[1])
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert expected_fields.issubset(schema["properties"])

    for field, allowed_values in enum_fields.items():
        field_schema = schema["properties"][field]
        enum_schema = field_schema.get("items", field_schema)
        if "enum" not in enum_schema:
            enum_schema = next(item for item in field_schema["anyOf"] if "enum" in item)
        assert enum_schema["enum"] == allowed_values


def test_provider_disabled_without_key_never_sends_request():
    assistant = _assistant_module()
    assert assistant is not None
    if assistant is None:
        return

    captured = []
    transport = httpx.MockTransport(lambda request: (
        captured.append(request) or httpx.Response(200, json={})
    ))
    with pytest.raises(assistant.AssistantError) as error:
        assistant.generate_draft(
            "candidate_preferences", "Ищу удалённую работу",
            external_ai_consent=True,
            configured=Settings(frontierai_api_key=None), transport=transport,
        )
    assert error.value.code == "AI_PROVIDER_DISABLED"
    assert captured == []


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_provider_http_errors_are_bounded_and_never_echo_provider_body(status_code):
    assistant = _assistant_module()
    assert assistant is not None
    if assistant is None:
        return

    transport = httpx.MockTransport(lambda _request: httpx.Response(
        status_code, text="sensitive-provider-error provider-test-key",
    ))
    with pytest.raises(assistant.AssistantError) as error:
        assistant.generate_draft(
            "candidate_preferences", "Текст без личных данных",
            external_ai_consent=True,
            configured=Settings(frontierai_api_key="provider-test-key"), transport=transport,
        )
    assert error.value.code == "AI_PROVIDER_UNAVAILABLE"
    assert "sensitive-provider-error" not in str(error.value)
    assert "provider-test-key" not in str(error.value)


@pytest.mark.parametrize("content", [
    "not-json PII should not escape",
    json.dumps({"salary_min_rub": 100000, "unknown_provider_field": "not allowed"}),
])
def test_provider_rejects_malformed_or_extra_output_without_echoing_it(content):
    assistant = _assistant_module()
    assert assistant is not None
    if assistant is None:
        return

    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={
        "choices": [{"message": {"content": content}}],
    }))
    with pytest.raises(assistant.AssistantError) as error:
        assistant.generate_draft(
            "candidate_preferences", "Ищу подходящую работу",
            external_ai_consent=True,
            configured=Settings(frontierai_api_key="provider-test-key"), transport=transport,
        )
    assert error.value.code == "AI_PROVIDER_INVALID_RESPONSE"
    assert "PII should not escape" not in str(error.value)
    assert "not allowed" not in str(error.value)


def test_provider_timeout_is_reported_without_exposing_transport_details():
    assistant = _assistant_module()
    assert assistant is not None
    if assistant is None:
        return

    def timeout(_request):
        raise httpx.ReadTimeout("provider-test-key timeout detail")

    transport = httpx.MockTransport(timeout)
    with pytest.raises(assistant.AssistantError) as error:
        assistant.generate_draft(
            "candidate_preferences", "Ищу подходящую работу",
            external_ai_consent=True,
            configured=Settings(frontierai_api_key="provider-test-key"), transport=transport,
        )
    assert error.value.code == "AI_PROVIDER_TIMEOUT"
    assert "provider-test-key" not in str(error.value)


def test_provider_requires_deliberate_external_consent_before_any_request():
    assistant = _assistant_module()
    assert assistant is not None
    if assistant is None:
        return

    captured = []
    transport = httpx.MockTransport(lambda request: (
        captured.append(request) or httpx.Response(200, json={})
    ))
    with pytest.raises(assistant.AssistantError) as error:
        assistant.generate_draft(
            "candidate_preferences", "Ищу удалённую работу",
            external_ai_consent=False,
            configured=Settings(frontierai_api_key="provider-test-key"), transport=transport,
        )
    assert error.value.code == "EXTERNAL_AI_CONSENT_REQUIRED"
    assert captured == []


def test_candidate_assistant_endpoint_rejects_missing_external_consent_before_provider(monkeypatch):
    from backend import routes_v2
    from backend.db import SessionLocal
    from backend.models import AssistantUsage

    provider_calls = []
    monkeypatch.setattr(
        routes_v2, "generate_draft",
        lambda *args, **kwargs: provider_calls.append((args, kwargs)), raising=False,
    )
    with TestClient(app) as candidate:
        person = register_verified(candidate, "assistant-consent-candidate@example.test", "candidate")
        response = candidate.post("/api/v1/assistant/candidate/preferences", json={
            "text": "Ищу удалённую работу",
            "external_ai_consent": False,
        }, headers=csrf(candidate))
        missing = candidate.post("/api/v1/assistant/candidate/preferences", json={
            "text": "Не отправлять это без согласия",
        }, headers=csrf(candidate))

    assert response.status_code == 422
    assert response.json()["detail"] == "EXTERNAL_AI_CONSENT_REQUIRED"
    assert missing.status_code == 422
    assert "Не отправлять это без согласия" not in missing.text
    assert provider_calls == []
    with SessionLocal() as db:
        assert db.query(AssistantUsage).filter(AssistantUsage.user_id == person["id"]).count() == 0


def test_candidate_preferences_assistant_returns_draft_without_saving_preferences(monkeypatch):
    from backend import routes_v2

    provider_calls = []

    def fake_generate(intent, text, *, external_ai_consent, **_kwargs):
        provider_calls.append((intent, text, external_ai_consent))
        return schemas.CandidatePreferencesDraft(salary_min_rub=150000, preferred_stack=["Python"])

    monkeypatch.setattr(routes_v2, "generate_draft", fake_generate, raising=False)
    monkeypatch.setattr(routes_v2, "settings", Settings(frontierai_api_key="provider-test-key"))
    with TestClient(app) as candidate:
        register_verified(candidate, "assistant-draft-candidate@example.test", "candidate")
        response = candidate.post("/api/v1/assistant/candidate/preferences", json={
            "text": "Удалённая работа, зарплата от 150000 рублей, стек Python",
            "external_ai_consent": True,
        }, headers=csrf(candidate))

        assert response.status_code == 200, response.text
        assert response.headers.get("cache-control") == "no-store"
        assert response.json()["salary_min_rub"] == 150000
        assert response.json()["preferred_stack"] == ["Python"]
        assert candidate.get("/api/v1/candidate/preferences").json()["salary_min_rub"] is None

    assert provider_calls == [(
        "candidate_preferences", "Удалённая работа, зарплата от 150000 рублей, стек Python", True,
    )]


def test_assistant_rate_limit_allows_ten_requests_and_blocks_the_eleventh(monkeypatch):
    from backend import routes_v2

    provider_calls = []

    def fake_generate(intent, text, *, external_ai_consent, **_kwargs):
        provider_calls.append(intent)
        return schemas.CandidatePreferencesDraft(salary_min_rub=150000)

    monkeypatch.setattr(routes_v2, "generate_draft", fake_generate, raising=False)
    monkeypatch.setattr(routes_v2, "settings", Settings(frontierai_api_key="provider-test-key"))
    with TestClient(app) as candidate:
        person = register_verified(candidate, "assistant-rate-candidate@example.test", "candidate")
        payload = {"text": "Ищу удалённую работу", "external_ai_consent": True}
        responses = [candidate.post(
            "/api/v1/assistant/candidate/preferences", json=payload, headers=csrf(candidate),
        ) for _ in range(11)]

    assert [response.status_code for response in responses] == [200] * 10 + [429]
    assert responses[-1].json()["detail"] == "AI_RATE_LIMIT_EXCEEDED"
    assert len(provider_calls) == 10
    from backend.db import SessionLocal
    from backend.models import AssistantUsage

    with SessionLocal() as db:
        assert db.query(AssistantUsage).filter(AssistantUsage.user_id == person["id"]).count() == 10


def test_assistant_usage_schema_contains_no_user_text_or_provider_output():
    from backend import models

    usage_model = getattr(models, "AssistantUsage", None)
    assert usage_model is not None
    if usage_model is None:
        return
    assert set(usage_model.__table__.columns.keys()) == {"id", "user_id", "intent", "created_at"}


def test_assistant_rate_limit_ignores_requests_older_than_one_hour(monkeypatch):
    from datetime import timedelta

    from backend import models, routes_v2
    from backend.db import SessionLocal
    from backend.models import now

    usage_model = getattr(models, "AssistantUsage", None)
    assert usage_model is not None
    if usage_model is None:
        return

    provider_calls = []
    monkeypatch.setattr(
        routes_v2, "generate_draft",
        lambda intent, *_args, **_kwargs: provider_calls.append(intent)
        or schemas.CandidatePreferencesDraft(salary_min_rub=150000), raising=False,
    )
    monkeypatch.setattr(routes_v2, "settings", Settings(frontierai_api_key="provider-test-key"))
    with TestClient(app) as candidate:
        person = register_verified(candidate, "assistant-rate-reset@example.test", "candidate")
        with SessionLocal() as db:
            db.add(usage_model(
                user_id=person["id"], intent="candidate_preferences",
                created_at=now() - timedelta(hours=1, seconds=1),
            ))
            db.commit()
        response = candidate.post("/api/v1/assistant/candidate/preferences", json={
            "text": "Ищу удалённую работу", "external_ai_consent": True,
        }, headers=csrf(candidate))

    assert response.status_code == 200, response.text
    assert provider_calls == ["candidate_preferences"]


def test_assistant_rejects_oversized_text_before_provider(monkeypatch):
    from backend import routes_v2

    provider_calls = []
    monkeypatch.setattr(
        routes_v2, "generate_draft", lambda *args, **kwargs: provider_calls.append((args, kwargs)),
        raising=False,
    )
    with TestClient(app) as candidate:
        register_verified(candidate, "assistant-oversize@example.test", "candidate")
        response = candidate.post("/api/v1/assistant/candidate/preferences", json={
            "text": "x" * 2001, "external_ai_consent": True,
        }, headers=csrf(candidate))

    assert response.status_code == 422
    assert response.json() == {"detail": "AI_INPUT_TOO_LONG"}
    assert "x" * 50 not in response.text
    assert provider_calls == []


def test_candidate_achievement_endpoint_returns_story_draft_without_publication(monkeypatch):
    from backend import routes_v2

    provider_calls = []

    def fake_generate(intent, text, *, external_ai_consent, **_kwargs):
        provider_calls.append((intent, text, external_ai_consent))
        return schemas.CandidateAchievementDraft(
            context="Команда теряла платёжные события.",
            personal_contribution="Я добавил идемпотентную обработку.",
            result="Повторные события больше не создавали записи.",
            missing_fields=["basis"],
            follow_up_questions=["Как вы проверили результат?"]
        )

    monkeypatch.setattr(routes_v2, "generate_draft", fake_generate, raising=False)
    monkeypatch.setattr(routes_v2, "settings", Settings(frontierai_api_key="provider-test-key"))
    with TestClient(app) as candidate:
        person = register_verified(candidate, "assistant-story-candidate@example.test", "candidate")
        response = candidate.post("/api/v1/assistant/candidate/achievement", json={
            "text": "Команда теряла события. Я добавил идемпотентность; повторов больше нет.",
            "external_ai_consent": True,
        }, headers=csrf(candidate))

    assert response.status_code == 200, response.text
    assert response.json()["missing_fields"] == ["basis"]
    assert "share_with_employers" not in response.json()
    assert "formatted_narrative" not in response.json()
    assert response.headers.get("cache-control") == "no-store"
    assert provider_calls == [(
        "candidate_achievement",
        "Команда теряла события. Я добавил идемпотентность; повторов больше нет.", True,
    )]
    from backend.db import SessionLocal
    from backend.models import CandidateProfile

    with SessionLocal() as db:
        profile = db.get(CandidateProfile, person["id"])
        assert profile is None or not profile.achievement_story


def test_employer_role_endpoint_is_role_gated_and_does_not_create_a_role(monkeypatch):
    from backend import routes_v2
    from backend.db import SessionLocal
    from backend.models import HiringNeed

    provider_calls = []

    def fake_generate(intent, text, *, external_ai_consent, **_kwargs):
        provider_calls.append((intent, text, external_ai_consent))
        return schemas.EmployerRoleDraft(
            title="QA-инженер", specialization="qa", grade="junior",
            competencies=["test_design"], missing_fields=["salary_min_rub", "work_format"],
        )

    monkeypatch.setattr(routes_v2, "generate_draft", fake_generate, raising=False)
    monkeypatch.setattr(routes_v2, "settings", Settings(frontierai_api_key="provider-test-key"))
    with TestClient(app) as employer:
        owner = register_verified(employer, "assistant-role-employer@example.test", "employer")
        response = employer.post("/api/v1/assistant/employer/role", json={
            "text": "Нужен junior QA для тестирования веб-продукта.",
            "external_ai_consent": True,
        }, headers=csrf(employer))
        assert response.status_code == 200, response.text
        assert response.json()["title"] == "QA-инженер"
        assert response.json()["missing_fields"] == ["salary_min_rub", "work_format"]

        with TestClient(app) as candidate:
            register_verified(candidate, "assistant-role-wrong-role@example.test", "candidate")
            forbidden = candidate.post("/api/v1/assistant/employer/role", json={
                "text": "QA engineer", "external_ai_consent": True,
            }, headers=csrf(candidate))

    assert forbidden.status_code == 403
    assert len(provider_calls) == 1
    with SessionLocal() as db:
        assert db.query(HiringNeed).filter(HiringNeed.employer_id == owner["id"]).count() == 0
