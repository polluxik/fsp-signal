# Candidate Role Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a candidate discover current public roles, keep a private shortlist, and dismiss/restore roles without exposing contact details or creating an application.

**Architecture:** Keep discovery and decisions in a dedicated `role_discovery` service beside the existing role-card lifecycle. The server returns immutable current role versions, applies candidate hard preferences and candidate-text privacy checks before serialization, and persists `saved`/`hidden`/`none` against role and preference versions; React renders those decisions as explicit controls and a paginated feed.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Alembic models already present, React, TypeScript, Vite, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-05-signal-v2-design.md` §§5, 8, 10, 12, 17–20; parent plan `docs/superpowers/plans/2026-10-05-signal-v2.md` T8.

## Global Constraints

- H0 decisions are only `saved`, `hidden`, and `none`; employer-visible `interested` remains out of scope until T10.
- Discovery includes only the current version of an active, discoverable role confirmed within 14 days; paused, closed, private, stale, and blocked roles never appear.
- Candidate hard-preference failures are filtered before results; unknowns are labeled, and private preference values/reasons are never returned.
- Browsing without a profile or verified category is allowed as `not_assessed`; GET must not create a profile or imply a personalized match.
- Role cards must not serialize employer contact, candidate data, assessment answers, or answer keys.
- Default page size is 5, maximum 20; ordering is stable by confirmation time and role id. More results require an explicit user action.
- Save/hide/undo are version-checked, explicit, keyboard-accessible actions; no swipe is required and no action sends an invitation or reveals a contact.

## Review Focus

- A role that becomes paused, stale, private, blocked, or revised between GET and decision is rejected without changing the decision.
- A candidate with no profile can browse but does not get a profile created as a side effect.
- A salary/format/industry/take-home hard failure is absent from results; unknown role data stays visible as `needs_clarification` without disclosing private values. Candidate-visible role/company text with email or phone is excluded, and decision writes apply the same check.
- Provenance is server-authored: demo/test modes are synthetic; synthetic actors/roles stay synthetic; legacy-import roles or actors remain unknown unless the actor or role is itself synthetic.
- A hidden role stays hidden after reload; `none` restores only a currently eligible role.
- Cursor pagination is deterministic across equal timestamps and never repeats/skips a role under fixed inputs; changing filters invalidates the old cursor.
- Candidate responses contain no employer email/contact or unrelated candidate information; `interested` is not accepted in H0.

---

### Task 1: Candidate-safe role feed API

**Files:**
- Modify: `backend/schemas.py`, `backend/routes_v2.py`
- Create: `backend/role_discovery.py`, `tests/test_role_discovery.py`

**Interfaces:**
- `GET /api/v1/candidate/roles?cursor=&limit=5&specialization=&grade=&work_format=&saved_only=false`
- `discover_roles(db, candidate_id, cursor=None, limit=5, *, specialization=None, grade=None, work_format=None, saved_only=False) -> RoleFeedOut`
- `RoleFeedOut` contains `items`, `next_cursor`, `limit`, and a specific `empty_state`; each item has `need_id`, current `role_version_id`/number, `company_name`, contact-free `role`, `confirmed_at`, `preferences_version`, `data_mode`, `match_state`, candidate-only `compatibility`, and current `decision`.
- Cursor encodes the last `(confirmed_at, need_id)` plus a filter fingerprint. Category mismatch is shown as `needs_clarification`; no profile/category is `not_assessed`. Hard incompatibilities are omitted.

- [x] **Step 1: Write failing API tests** for fresh/current/discoverable filtering, role-contact omission, preference hard filters vs unknowns, no-profile browsing without profile creation, and a default five-item page with stable continuation.
- [x] **Step 2: Run `./.venv/bin/pytest -q tests/test_role_discovery.py`** and confirm failures identify the missing API/contract.
- [x] **Step 3: Add typed feed DTOs, keyset cursor validation, and read-only discovery using current `RoleVersion`, `EmployerProfile`, candidate blocks/preferences, and `RoleDecision` state. Never call a create-profile helper from GET.**
- [x] **Step 4: Run the focused test file; confirm private hard values and employer contacts do not occur in serialized results.**

### Task 2: Versioned save, hide, and undo

**Files:**
- Modify: `backend/schemas.py`, `backend/routes_v2.py`
- Modify: `backend/role_discovery.py`
- Test: `tests/test_role_discovery.py`

**Interfaces:**
- `PUT /api/v1/candidate/role-decisions/{need_id}` with `{action, expected_role_version, expected_preferences_version}`.
- `save_role_decision(db, candidate_id, need_id, action, expected_role_version, expected_preferences_version, at) -> RoleDecisionOut`.
- H0 accepts only `saved`, `hidden`, `none`. Missing profile uses preference version 1 without creating a profile. Stale role/preferences return 409; a role that is no longer visible returns 404/409 without leaking hidden values.

- [x] **Step 1: Add failing tests** for save persistence, hide persistence across fresh GET, undo to `none`, stale role/preferences, paused/stale/blocked role rejection, and invalid `interested` action.
- [x] **Step 2: Run the focused test file and verify expected failures.**
- [x] **Step 3: Implement version-checked decision upsert using the existing unique `(candidate_id, need_id)` row; only current eligible roles may be changed. A role revision invalidates an old decision for display, requiring an action against the new version.**
- [x] **Step 4: Re-run focused tests and inspect the stored `RoleDecision` after each transition.**

### Task 3: Synthetic discovery fixtures

**Files:**
- Modify: `backend/seed_demo.py`
- Test: `tests/test_role_discovery.py`

- [x] **Step 1: Add a failing repeatability test** requiring multiple concrete synthetic public roles across categories/conditions while preserving the existing employer's primary role and synthetic candidate provenance.
- [x] **Step 2: Run the focused seed test and verify it fails on the missing feed inventory.**
- [x] **Step 3: Seed a deterministic set of public role cards under the secondary demo employer, with valid conditions and `source="synthetic_demo"`; keep the seed idempotent and do not rewrite historical assessment attempts.**
- [x] **Step 4: Run the seed and discovery tests twice; confirm stable counts/versions and unchanged primary employer workflow.**

### Task 4: Candidate feed UI

**Files:**
- Create: `frontend/src/features/roles/RoleFeed.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/types.ts`, `frontend/src/styles.css`, `frontend/src/features/roles/RoleCard.tsx`, `frontend/tests/core-flow.spec.ts`

- [x] **Step 1: Add a failing browser scenario** for the “Для меня” entry, clear `not_assessed`/`needs_clarification` states, save, saved-only view after reload, hide with inline Undo, and paging by five.
- [x] **Step 2: Run `npm run test:e2e` and verify the feed scenario fails before rendering exists.**
- [x] **Step 3: Implement a focused feed component reusing `RoleCard`; expose visible category/format/saved filters, explicit “Показать ещё 5”, save/hide/Undo buttons, and useful empty-state next actions. Send both current versions with every decision.**
- [x] **Step 4: Make the browser test pass, including stale-version refresh behavior and a serialized-response assertion that no employer contact is shown.**

### Task 5: Verification and handoff

- [x] Run `npm run build` (success), `npm run test:e2e` (4 passed), `./.venv/bin/pytest -q` (73 passed, 7 skipped), and `git diff --check` (clean).
- [x] Update T8 checkboxes in `docs/superpowers/plans/2026-10-05-signal-v2.md`; record unavailable PostgreSQL-only checks as not verified, not passed. Seven PostgreSQL-only tests were skipped because no PostgreSQL service is available in this environment.
- [x] Commit only the plan and T8 implementation files in a scoped local commit; do not push or create a PR unless asked.
