# Signal Core Journey Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the candidate/employer journeys so preferences, compatibility, invitation states, evidence labels, and contact consent stay correct across edits, refreshes, and failures.

**Architecture:** Preserve the existing FastAPI/SQLAlchemy contracts and React feature boundaries. Add regression tests first, fix backend invariants at their owning routes/services, then make the UI consume authoritative responses and expose recoverable states. Keep matching, assessment and provenance distinct.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest, React 19, TypeScript, Vite, Playwright.

**Spec:** [Signal product polish design](../specs/2026-10-07-signal-product-polish-design.md)

## Global Constraints

- Contacts remain hidden until the candidate accepts a specific invitation.
- Candidate assessment, match quality, source provenance, and unknown information remain distinct concepts.
- A numeric score is not a probability of hiring.
- Never identify synthetic records as real, verified or hired.
- Preserve historical scoring behavior for old records.
- Make all interactive controls work with pointer, touch and keyboard, with visible focus and accessible names.
- Preserve clear loading, error, empty, success, disabled and stale/conflict states.

## Review Focus

- A preference write in one tab followed by a stale profile save in another must not silently restore old preferences; pin this in `tests/test_preferences.py::test_profile_update_cannot_overwrite_newer_preferences` and a two-context browser test.
- Opening/reloading an invitation after preference changes must show current compatibility or an explicit unknown state, never replace it with null; pin this in `tests/test_invitations_v2.py::test_viewed_invitation_retains_candidate_compatibility`.
- A first-time employer missing company details must get a navigable setup path, not an opaque API code; pin the mapping in `frontend/tests/core-flow.spec.ts`.
- Legacy or unknown evidence provenance must not be labeled “verified”; pin the visible label in `frontend/tests/core-flow.spec.ts`.
- An accepted invitation must not count as a held interview until each participant confirms it; pin this in `tests/test_invitations_v2.py::test_interview_is_counted_only_after_both_parties_confirm`.

---

### Task 1: Pin the backend journey invariants before changing behavior

**Files:**
- Modify: `tests/test_preferences.py`
- Modify: `tests/test_invitations_v2.py`
- Modify: `tests/test_product_events.py`
- Modify: `tests/test_employer_evidence_api.py`
- Modify: `frontend/tests/core-flow.spec.ts`

**Interfaces:**
- Consumes: existing authenticated test clients and seeded candidate/employer fixtures.
- Produces: regression coverage for stale preferences, invitation compatibility, provenance labels and stale feed decisions.

- [ ] **Step 1: Add the failing preference, invitation and two-party interview tests**

  Assert that a newer `CandidatePreferencesIn` value is not overwritten by an older profile snapshot; candidate invitation GET and POST-view both include the same compatibility status/checks; an accepted invitation is not counted held after one confirmation and becomes held only after both.

- [ ] **Step 2: Add failing preference-cache, visible-provenance and held-interview event tests; retain the existing stale-decision test**

  Assert preference GET/PUT return `Cache-Control: no-store`; in Playwright assert unknown/legacy provenance is not rendered as verified. Only an accepted invitation's two authenticated participants may confirm a held interview; repeat confirmation is idempotent and the event is emitted once after the second confirmation. `tests/test_role_discovery.py::test_stale_role_and_preferences_versions_do_not_mutate_a_saved_decision` already covers stale role decisions and must remain green; do not duplicate it.

- [ ] **Step 3: Run the focused tests and verify they fail for the reported behavior**

  Run: `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest tests/test_preferences.py tests/test_invitations_v2.py tests/test_product_events.py tests/test_employer_evidence_api.py tests/test_role_discovery.py -q`

  Expected: failures identify stale preference overwrite, invitation serialization, missing cache headers or missing held-interview contract; the existing stale-decision test remains green.

### Task 2: Repair authoritative state and server response contracts

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/invitations.py`
- Modify: `backend/routes_v2.py`
- Modify: `backend/preferences.py`
- Modify: `backend/schemas.py`
- Modify: `backend/models.py`
- Create: `backend/migrations/versions/5d7a9b2c4f11_interview_outcome.py` (revision `5d7a9b2c4f11`, down-revision `e8a1c4d57b20`)
- Modify: `backend/product_events.py`
- Modify: `tests/test_preferences.py`
- Modify: `tests/test_invitations_v2.py`
- Modify: `tests/test_product_events.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: Task 1 regression tests.
- Produces: stable candidate invitation serialization, conflict-safe preference writes, private/no-store preference responses, explicit evidence provenance, and `confirm_interview_held(db, actor_id, invitation_id, at)`.

- [ ] **Step 1: Set `Cache-Control: no-store` on candidate preference GET and PUT, making the failing assertions from Task 1 pass**
- [ ] **Step 2: Fix candidate invitation view serialization to return the profile-specific compatibility report**

  Preserve the employer-facing invitation contract; use the candidate-specific serializer only for the candidate's view/action response.

- [ ] **Step 3: Make preference/profile synchronization reject or preserve stale values using the current preference version**

  Keep the existing first-profile creation path working; on conflict return a typed `409` and current state without committing stale preferences.

- [ ] **Step 4: Add two-party held-interview confirmation state and endpoint**

  Add candidate/employer confirmation timestamps to `Invitation`; expose `POST /api/v1/invitations/{invitation_id}/interview-held-confirmation`. Require an accepted invitation and the authenticated participant. Lock the invitation while updating; emit the deduplicated `interview_held` event only when both parties have confirmed. Repeated clicks are idempotent; a single confirmation is never counted as held.

- [ ] **Step 4a: Test upgrade/backfill behavior for the additive invitation columns and event contract**

  Upgrade a pre-change SQLite schema to head and verify old invitation states remain intact with neither party spuriously confirmed.

- [ ] **Step 5: Run focused tests, then the complete backend suite**

  Run: `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest tests/test_preferences.py tests/test_invitations_v2.py tests/test_product_events.py tests/test_migrations.py tests/test_employer_evidence_api.py tests/test_role_discovery.py -q`

  Expected: PASS; then `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -q` passes SQLite-supported tests, with only the documented PostgreSQL-only skips.

- [ ] **Step 6: Commit the backend contract/consent repair after the focused and full backend suites pass**

### Task 3: Keep candidate/employer UI in sync with server state

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/features/preferences/PreferencesPanel.tsx`
- Modify: `frontend/src/features/invitations/InvitationPanel.tsx`
- Modify: `frontend/src/features/roles/RoleFeed.tsx`
- Modify: `frontend/src/features/evidence/EvidencePanel.tsx`
- Modify: `frontend/playwright.config.ts`
- Create: `frontend/tests/test-support.ts`
- Modify: `frontend/tests/core-flow.spec.ts`

**Interfaces:**
- Consumes: Task 2 response contracts.
- Produces: synchronized profile/preference client state; preserved compatibility after viewing an invitation; clear conflict/setup/error states; honest source and match/evidence labels; optional two-sided meeting confirmation after acceptance.

- [ ] **Step 1: Add Playwright regressions for preference-save → profile-save → reload, invitation-view → compatibility display, and two-party held confirmation**
- [ ] **Step 1a: Restore the frontend test environment from the committed lockfile if dependencies are absent**

  Run `npm ci` inside `frontend/` in this isolated worktree only; do not alter `package.json` or the lockfile just to satisfy the environment. Keep the existing app on port 5173 untouched; all live checks for this worktree use dedicated ports (frontend 5174, API 8001) and a synthetic temporary database.
- [ ] **Step 2: Run the new browser cases and capture their failing state**

  Run: `cd frontend && FSP_SIGNAL_E2E_PYTHON=/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python npm run test:e2e -- --grep "preference state|invitation compatibility"`

- [ ] **Step 3: Update parent profile state from the confirmed preferences response and keep invitation response merging null-safe**
- [ ] **Step 4: Map `COMPANY_PROFILE_REQUIRED` to a message and direct setup action; preserve input on recoverable errors**
- [ ] **Step 5: Render fit, assessment score, evidence coverage and unknown competencies as separate labeled values**
- [ ] **Step 6: Correct visible evidence badges so only `verified_action` is called verified; preserve `synthetic_fixture`, aggregate and unknown labels**
- [ ] **Step 7: Show the held-interview confirmation control only after acceptance; show a confirmed outcome only after both parties confirm**
- [ ] **Step 8: Extract `signIn` and `currentUserId` to `frontend/tests/test-support.ts`, set Playwright `testMatch` to `**/*.spec.ts`, then run `cd frontend && npm run build` and the focused browser cases; expected: PASS with no TypeScript errors or console exceptions**
- [ ] **Step 9: Commit the core candidate/employer UI state repair after build and focused E2E pass**

### Task 4: Close and verify the core flow

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/matching.py`
- Modify: `backend/main.py`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/features/invitations/InvitationPanel.tsx`
- Modify: `tests/test_invitations_v2.py`
- Modify: `tests/test_product_events.py`
- Modify: `frontend/tests/core-flow.spec.ts`

**Interfaces:**
- Consumes: the repaired user-state contracts from Tasks 2–3.
- Produces: neutral matching default for new searches, unchanged historical snapshots, reliable invitation status/contact boundary and complete employer setup/recovery path.

- [ ] **Step 1: Add score and candidate-bank regression tests proving new searches/bank ordering do not receive an unvalidated FSP ranking bonus while old snapshots remain unchanged**
- [ ] **Step 2: Run the failing algorithm-default regression**
- [ ] **Step 3: Set the new-search default to the reviewed non-FSP-bonus algorithm; do not rewrite stored snapshots**
- [ ] **Step 4: Extend browser E2E for company setup, invite view/accept/reject/withdraw, refresh, contact access, and two-party held-interview confirmation**
- [ ] **Step 5: Run `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -q`, `cd frontend && npm run build`, and the complete E2E suite; expected: all SQLite/backend/browser checks pass and PostgreSQL-only skips are reported explicitly**
- [ ] **Step 6: Commit this independently reviewable core-journey change**
