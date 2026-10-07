# Signal AI Drafting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional, consented AI drafts for candidate preferences/achievement stories and employer role briefs without automatic saves or AI hiring decisions.

**Architecture:** A backend-only adapter sends only the text and intent explicitly submitted by the user to the configured OpenAI-compatible chat endpoint. Typed output is validated against intent-specific Pydantic schemas, returned as an editable draft, and saved only through existing profile/preferences/role actions. Provider errors leave the normal forms usable.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, HTTPX (already installed), pytest, React 19, TypeScript, Playwright.

**Spec:** [Signal product polish design](../specs/2026-10-07-signal-product-polish-design.md)

## Global Constraints

- Use `https://gateway.frontierai.ru/v1/chat/completions` and model `qwen3.8-27b-4a100` only from the backend.
- The API key is read from server configuration; it must not be put in source, frontend bundles, committed `.env` files, logs, test snapshots or user-visible errors.
- Before each provider transmission, disclose that the text will be sent to the configured external AI provider and require a deliberate send action.
- Send only the text for that intent; do not attach names, emails, contact details, stored resumes, assessment results, private preferences, full profiles or other conversation history.
- Never call the model for candidate scoring, selection, eligibility or ranking.
- All AI outputs remain drafts until human confirmation.
- Tests use a stubbed provider and synthetic content. No real candidate data is sent in local tests.

## Review Focus

- Consent false/missing must prevent any outbound provider request; pin `tests/test_ai_assistant.py::test_requires_external_provider_consent`.
- Prompt injection or extra/wrong-type keys in model JSON must not become a saved profile or role; pin `tests/test_ai_assistant.py::test_rejects_unrecognized_provider_output`.
- Provider timeout, HTTP error and malformed JSON must not erase user input or make manual forms unavailable; pin the respective transport tests and `frontend/tests/ai-drafting.spec.ts`.
- The request body must contain only intent and submitted text, never profile, resume, contacts, assessment results or previous turns; pin `tests/test_ai_assistant.py::test_provider_request_excludes_profile_and_contact_data`, and redact contact patterns from typed text before transmission.
- Rate exhaustion and oversize input must return bounded errors without recording raw prompt text; pin `tests/test_ai_assistant.py::test_rate_limit_and_text_length_are_enforced_without_content_storage`.

---

### Task 1: Define strict draft contracts and provider configuration

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/schemas.py`
- Create: `backend/ai_assistant.py`
- Create: `tests/test_ai_assistant.py`

**Interfaces:**
- Consumes: existing `CandidatePreferencesIn`, `CandidatePreferencesOut`, `AchievementStoryIn` and `RoleCardIn` contracts.
- Produces: `POST /api/v1/assistant/candidate/preferences`, `POST /api/v1/assistant/candidate/achievement`, and `POST /api/v1/assistant/employer/role` request/response schemas; provider adapter `generate_draft(intent, text) -> DraftModel`.

- [ ] **Step 1: Add failing schema tests for exactly three intent-specific outputs**

  Preferences may contain only existing private preference fields; achievement draft may contain context, personal contribution, approach/decisions, outcome, evidence basis and focused follow-up questions; role draft may contain only fields accepted by the existing role editor plus explicit missing/ambiguous fields. Set `extra="forbid"` on all provider response models.

- [ ] **Step 2: Add failing configuration tests**

  Defaults: `FRONTIERAI_BASE_URL=https://gateway.frontierai.ru/v1/chat/completions`, `FRONTIERAI_MODEL=qwen3.8-27b-4a100`, secret `FRONTIERAI_API_KEY` with no default, maximum input 2,000 characters, maximum output 800 tokens, provider timeout 12 seconds. Missing key disables the adapter without exposing a secret.

- [ ] **Step 3: Add provider transport tests with `httpx.MockTransport`**

  Assert the request has model/messages/max-token limit, authorization is sourced from settings, no `response_format`/unverified gateway extension is assumed, and invalid status/content/JSON/schema is rejected.

  Assert email and phone-like strings in the user's text are redacted before request construction; disclose that users should not enter personal/contact details.

- [ ] **Step 4: Run schema/configuration/provider tests and verify the expected failures with no outbound network request**
- [ ] **Step 5: Implement bounded HTTPX request/response parsing, contact-pattern redaction and strict Pydantic validation**

  Never log headers, raw input, raw output or provider error bodies. Convert failures to typed internal errors; do not include the key in exception text.

- [ ] **Step 6: Run `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest tests/test_ai_assistant.py -q`; expected: PASS with no network access**
- [ ] **Step 7: Commit the provider/schema slice with mock-only tests passing**

### Task 2: Add consent gate, data minimization and persistent rate limit

**Files:**
- Modify: `backend/models.py`
- Create: `backend/migrations/versions/3b9ef2c7d41a_assistant_usage.py` (revision `3b9ef2c7d41a`, down-revision `5d7a9b2c4f11`)
- Modify: `backend/config.py`
- Modify: `backend/ai_assistant.py`
- Modify: `backend/routes_v2.py`
- Modify: `tests/test_ai_assistant.py`
- Modify: `tests/test_preferences.py`

**Interfaces:**
- Consumes: Task 1 schemas/provider adapter and authenticated role/CSRF dependencies.
- Produces: three role-gated endpoints; `AssistantUsage` stores only `user_id`, `intent` and `created_at` (no prompt/response); 10 requests per user per rolling hour; preference GET/PUT responses set `Cache-Control: no-store`.

- [ ] **Step 1: Add failing tests for missing/false consent, role mismatch, text length 2,001, the 11th request in one hour, and reset after an hour**
- [ ] **Step 2: Add migration/model and assert `AssistantUsage` has no text/content columns**
- [ ] **Step 3: Run the new consent/rate/migration tests and verify expected failures without a provider call**
- [ ] **Step 4: Implement pre-provider consent/role/size/rate checks, commit one privacy-minimal usage row, then call the provider**

  Do not persist drafts. Lock the authenticated user row while counting and inserting usage so PostgreSQL requests cannot race past the hourly limit. Store no text or output.

- [ ] **Step 5: Add a request-capture test proving outbound JSON contains only `intent` and the submitted text**
- [ ] **Step 6: Assert GET and PUT `/candidate/preferences` return `Cache-Control: no-store`**
- [ ] **Step 7: Run migration tests and `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest tests/test_ai_assistant.py tests/test_preferences.py tests/test_migrations.py -q`; expected: PASS on SQLite and PostgreSQL-compatible schema operations**
- [ ] **Step 8: Commit the consent/rate-limit/API slice after tests pass**

### Task 3: Add editable candidate and employer draft UI

**Files:**
- Create: `frontend/src/features/assistant/AssistantPanel.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/features/preferences/PreferencesPanel.tsx`
- Modify: `frontend/src/features/roles/RoleEditor.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/styles.css`
- Create: `frontend/tests/ai-drafting.spec.ts`

**Interfaces:**
- Consumes: Task 2 endpoint contracts and shared `frontend/tests/test-support.ts` helper; `**/*.spec.ts` discovery from the core-journey plan.
- Produces: an explicit external-AI disclosure and send confirmation per draft; editable proposal preview; independent “Применить в форму” and existing “Сохранить” actions; accessible pending/error/retry states.

- [ ] **Step 1: Add failing browser tests for opt-in, editable fields, no auto-save, rejection/error fallback, and retained form text after timeout**
- [ ] **Step 2: Run the new E2E tests against stubbed API responses and confirm the current UI lacks the assistant flow**
- [ ] **Step 3: Implement the isolated assistant component and connect preference, achievement and employer-role intents**

  Keep normal forms usable when AI is disabled. Show a concise disclosure immediately before sending text. The candidate must review all story fields and separately opt in before exposing a story to employers.

- [ ] **Step 4: Add `prefers-reduced-motion` and keyboard/focus behavior for assistant states without adding a new UI dependency**
- [ ] **Step 5: Run `cd frontend && npm run build` and focused AI E2E; expected: PASS, no auto-save, no console/page errors**
- [ ] **Step 6: Commit the editable-draft UI after focused E2E passes**

### Task 4: Review and verify the AI boundary

**Files:**
- Review: `backend/config.py`, `backend/ai_assistant.py`, `backend/routes_v2.py`, `backend/models.py`, `frontend/src/features/assistant/AssistantPanel.tsx`
- Test: `tests/test_ai_assistant.py`, `frontend/tests/ai-drafting.spec.ts`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: a documented security/privacy review and tested disabled-provider fallback; no code path requires a live API in CI.

- [ ] **Step 1: Run secret scanning/diff search for `sk-`, raw prompt logging, client-side Authorization headers, PII fields in request construction, and hidden save calls**
- [ ] **Step 2: Run tests with missing key, mock success, malformed output, 429, 5xx and timeout; expected: manual flow remains usable**
- [ ] **Step 3: Run one synthetic live provider smoke only after an explicit cost ceiling is agreed; otherwise report provider live behavior as unverified**
- [ ] **Step 4: Run complete backend, build and E2E suites; commit the AI slice independently**
