"""Optional provider adapter for consented, editable user-authored drafts."""

import json
import re
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings, settings
from .domain_errors import DomainError
from .schemas import CandidateAchievementDraft, CandidatePreferencesDraft, EmployerRoleDraft
from .taxonomy import available_categories


AssistantIntent = Literal["candidate_preferences", "candidate_achievement", "employer_role"]
_ROLE_CATEGORY_GUIDANCE = "; ".join(
    f"{category.specialization}/{category.grade}: {', '.join(item.id for item in category.competencies)}"
    for category in available_categories()
)


class AssistantError(DomainError):
    pass


_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_PATTERNS = (
    re.compile(r"(?<!\w)(?:\+7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{2}[\s().-]*\d{2}(?!\d)"),
    re.compile(r"(?<!\w)(?:\+\d{1,3}[ .()-]*)?(?:\d{2,4}[ .()-]+){2,4}\d{2,4}(?!\w)"),
)

_DRAFTS: dict[str, tuple[type[BaseModel], str]] = {
    "candidate_preferences": (
        CandidatePreferencesDraft,
        "Извлеки только явно названные пожелания к работе. Не выводи доступность, согласие, имя, контакты или зарплату из контекста. "
        "Не додумывай города, формат, навыки или условия; неизвестные поля укажи в missing_fields и задай максимум пять коротких вопросов. "
        "Верни один JSON-объект, допустимые поля: salary_min_rub, allowed_work_formats, allowed_cities, excluded_industries, "
        "preferred_stack, preferred_tasks, max_take_home_minutes, missing_fields, follow_up_questions.",
    ),
    "candidate_achievement": (
        CandidateAchievementDraft,
        "Собери только черновик рассказа из фактов в тексте. Не выдумывай метрики, инструменты, личное владение задачей или результат. "
        "Для result_scope используй individual, если автор явно говорит, что сделал работу самостоятельно или лично; "
        "team — если явно описан совместный результат команды. Если область результата неясна, оставь result_scope null. "
        "Если факта нет, оставь поле пустым или null, перечисли его в missing_fields и задай максимум пять точечных вопросов. "
        "Не утверждай, что рассказ проверен или должен быть опубликован. Верни один JSON-объект с полями модели.",
    ),
    "employer_role": (
        EmployerRoleDraft,
        "Сформируй только редактируемый черновик роли из явно переданного текста. Не выдумывай зарплату, формат, город, культуру, "
        "льготы, обязанности или этапы отбора. Неизвестные и неоднозначные поля укажи в missing_fields и ambiguous_fields; "
        "задай максимум пять коротких уточнений. Не добавляй контакты работодателя и не публикуй роль. "
        f"Если предлагаешь competencies, выбери ID только из каталога для указанной specialization/grade: {_ROLE_CATEGORY_GUIDANCE}. "
        "Если категорию или компетенции нельзя определить, оставь их пустыми и запроси уточнение. Верни один JSON-объект с полями модели.",
    ),
}


def redact_contact_details(text: str) -> str:
    redacted = _EMAIL_PATTERN.sub("[контакт удалён]", text)
    for pattern in _PHONE_PATTERNS:
        def replace_phone(match: re.Match[str]) -> str:
            digits = sum(character.isdigit() for character in match.group())
            return "[контакт удалён]" if 10 <= digits <= 15 else match.group()

        redacted = pattern.sub(replace_phone, redacted)
    return redacted


def _provider_content(response: httpx.Response) -> str:
    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise AssistantError("AI_PROVIDER_INVALID_RESPONSE", 502) from None
    if not isinstance(content, str):
        raise AssistantError("AI_PROVIDER_INVALID_RESPONSE", 502)
    return content


def generate_draft(intent: AssistantIntent, text: str, *, external_ai_consent: bool,
                   configured: Settings = settings,
                   transport: httpx.BaseTransport | None = None) -> BaseModel:
    """Send only redacted, intent-specific text after explicit user consent."""
    if external_ai_consent is not True:
        raise AssistantError("EXTERNAL_AI_CONSENT_REQUIRED", 422)
    if not isinstance(intent, str) or intent not in _DRAFTS:
        raise AssistantError("AI_INTENT_INVALID", 422)
    if not isinstance(text, str) or not text.strip():
        raise AssistantError("AI_INPUT_REQUIRED", 422)
    if len(text) > configured.assistant_max_input_chars:
        raise AssistantError("AI_INPUT_TOO_LONG", 422)
    if not configured.frontierai_api_key or not configured.frontierai_api_key.strip():
        raise AssistantError("AI_PROVIDER_DISABLED", 503)

    draft_model, instructions = _DRAFTS[intent]
    instructions = (
        f"{instructions}\n\n"
        "Ответь ровно одним JSON-объектом, строго соответствующим JSON Schema ниже. "
        "Используй только указанные имена полей и значения enum; не добавляй ключи, "
        "пояснения или Markdown. Для missing_fields и ambiguous_fields используй только "
        "ID полей, перечисленные в схеме.\n"
        "JSON Schema:\n"
        f"{json.dumps(draft_model.model_json_schema(), ensure_ascii=False, separators=(',', ':'))}"
    )
    user_content = json.dumps({
        "intent": intent,
        "text": redact_contact_details(text.strip()),
    }, ensure_ascii=False, separators=(",", ":"))
    request_body = {
        "model": configured.frontierai_model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": configured.assistant_max_output_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        with httpx.Client(transport=transport, timeout=configured.assistant_timeout_seconds) as client:
            response = client.post(
                configured.frontierai_base_url,
                json=request_body,
                headers={"Authorization": f"Bearer {configured.frontierai_api_key}"},
            )
    except httpx.TimeoutException:
        raise AssistantError("AI_PROVIDER_TIMEOUT", 504) from None
    except httpx.HTTPError:
        raise AssistantError("AI_PROVIDER_UNAVAILABLE", 503) from None

    if not response.is_success:
        raise AssistantError("AI_PROVIDER_UNAVAILABLE", 503)
    content = _provider_content(response)
    try:
        output = json.loads(content)
        if not isinstance(output, dict):
            raise ValueError("draft JSON must be an object")
        return draft_model.model_validate(output)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        raise AssistantError("AI_PROVIDER_INVALID_RESPONSE", 502) from None
