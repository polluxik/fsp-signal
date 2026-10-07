# Signal UI Interaction and Live Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every important candidate/employer section and control clear, responsive and functional, then verify the integrated product in real browser flows.

**Architecture:** Keep the existing React feature structure and purple brand. Prefer focused CSS/component fixes; use Playwright for repeatable flow, viewport, keyboard and error-state checks, then perform a visible local-browser pass against the isolated worktree. Add motion only for meaningful state transitions and preserve reduced-motion behavior.

**Tech Stack:** React 19, TypeScript, Vite, CSS, Playwright/Chromium, FastAPI test backend.

**Spec:** [Signal product polish design](../specs/2026-10-07-signal-product-polish-design.md)

## Global Constraints

- Preserve the existing purple brand; avoid a wholesale visual rewrite.
- Use brief transitions only to clarify state changes; respect `prefers-reduced-motion`.
- Avoid animation on repeated/high-frequency interactions and never delay an action for decoration.
- Animate only `transform` and `opacity`; do not animate `top`, `left`, `width` or `height`.
- Replace/style scrollbars only if the live UI demonstrates a real visual/interaction defect; never hide scrolling affordances.
- Make all interactive controls work with pointer, touch and keyboard, with visible focus and accessible names.
- Preserve clear loading, error, empty, success, disabled and stale/conflict states.
- Add no UI dependency without checking `frontend/package.json` and demonstrating a concrete need.

## Review Focus

- A 390×844 viewport must not clip actions or introduce horizontal scroll; test `frontend/tests/ui-audit.spec.ts::candidate_and_employer_pages_fit_mobile_viewport`.
- Reduced-motion users must not receive nonessential motion; test `frontend/tests/ui-audit.spec.ts::reduced_motion_disables_nonessential_transitions`.
- Keyboard users must be able to reach, activate and escape dialogs/actions with visible focus; test `frontend/tests/ui-audit.spec.ts::critical_controls_are_keyboard_operable`.
- Slow/error requests must not create duplicate writes or erase entered content; test `frontend/tests/ui-audit.spec.ts::forms_retain_input_and_expose_retry_on_failure`.
- If employer evidence requests resolve out of order after switching candidates, the open invitation draft must never show or submit evidence belonging to the previously selected candidate; test `frontend/tests/ui-audit.spec.ts::selected_candidate_evidence_never_crosses_on_out_of_order_response`.
- Disabled, stale, missing-data and empty states must be understandable and actionable, not look like working success; cover by route-state assertions in the UI audit suite.

---

### Task 1: Establish a repeatable UI audit suite

**Files:**
- Create: `frontend/tests/ui-audit.spec.ts`

**Interfaces:**
- Consumes: demo credentials/fixture roles from `backend/seed_demo.py` and `frontend/tests/test-support.ts` created by the core-journey plan.
- Produces: Playwright discovery of all `*.spec.ts`; desktop/mobile/keyboard/error assertions without external credentials.

- [ ] **Step 1: Add failing tests for mobile overflow, focus visibility, dialog close, safe navigation, retry/input retention and console/page errors**
- [ ] **Step 2: Run the UI audit suite and record baseline screenshots/traces for candidate and employer**

  Run: `cd frontend && FSP_SIGNAL_E2E_PYTHON=/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python npx playwright test tests/ui-audit.spec.ts --config playwright.config.ts`

- [ ] **Step 3: Reuse the shared helpers and `testMatch: **/*.spec.ts` configuration created in the core-journey plan**
- [ ] **Step 4: Verify focused test discovery and that the existing core-flow suite still runs unchanged**

### Task 2: Fix evidenced interaction and visual defects

**Files:**
- Modify as evidence requires: `frontend/src/App.tsx`
- Modify as evidence requires: `frontend/src/features/preferences/PreferencesPanel.tsx`
- Modify as evidence requires: `frontend/src/features/invitations/InvitationPanel.tsx`
- Modify as evidence requires: `frontend/src/features/roles/RoleCard.tsx`
- Modify as evidence requires: `frontend/src/features/roles/RoleEditor.tsx`
- Modify as evidence requires: `frontend/src/features/roles/RoleFeed.tsx`
- Modify as evidence requires: `frontend/src/features/evidence/EvidencePanel.tsx`
- Modify as evidence requires: `frontend/src/features/assistant/AssistantPanel.tsx`
- Modify as evidence requires: `frontend/src/features/invitations/InvitationPanel.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/ui-audit.spec.ts`

**Interfaces:**
- Consumes: Task 1 audit results and completed feature contracts from the journey, taxonomy, AI and sponsored-role plans.
- Produces: focused component/CSS corrections only for reproduced defects, consistent button states, visible scrollbar affordance, keyboard/focus support and motion honoring reduced-motion preference.

- [ ] **Step 1: Walk every candidate/employer navigation section and safe visible control in the running app; record action, expected result and actual result; include rapid employer candidate switching with delayed/out-of-order evidence responses**
- [ ] **Step 2: Reproduce each actionable defect as an assertion or deterministic test before editing the component**
- [ ] **Step 3: Fix one defect class at a time; keep colors, spacing and transitions consistent with the existing purple system**
- [ ] **Step 4: Add 150–220ms transform/opacity transitions only for state changes where feedback improves comprehension; disable nonessential transitions under `prefers-reduced-motion: reduce`**
- [ ] **Step 5: Style a scrollbar only if screenshots/live interaction show it obscures or clashes with content; maintain sufficient contrast and native scroll behavior**
- [ ] **Step 6: Re-run the corresponding failing test after each fix; expected: PASS with no new console, accessibility-name or overflow regression**
- [ ] **Step 7: Commit the verified UI corrections after the audit suite passes**

### Task 3: Full live E2E and UI performance verification

**Files:**
- Modify: `frontend/tests/core-flow.spec.ts`
- Modify: `frontend/tests/ui-audit.spec.ts`
- Modify: `frontend/tests/ai-drafting.spec.ts`
- Modify: `frontend/tests/sponsored-roles.spec.ts`
- Modify: `docs/implementation-status.md`

**Interfaces:**
- Consumes: all completed feature plans and synthetic-only local demo data.
- Produces: reproducible E2E coverage and a truthful verification report listing browsers, viewports, sections, flows, checks, timings and remaining gaps.

- [ ] **Step 1: Run backend unit/integration suite and frontend build before browser testing; expected: PASS or triage every failure before proceeding**
- [ ] **Step 1a: If this isolated worktree lacks frontend dependencies, run `npm ci` in `frontend/` using the committed lockfile; do not change dependency manifests without a demonstrated need**
- [ ] **Step 2: Run full Playwright E2E across candidate preferences/profile, assessment/category, role feed/save/hide, invitations/consent, employer setup/role creation/search, AI draft review and sponsored role exposure**
- [ ] **Step 3: Run visible browser verification against the isolated worktree on dedicated ports (frontend 5174, API 8001), using a synthetic temporary database; click through all sections and safe actions for candidate and employer; inspect desktop 1365×920 and mobile 390×844. Do not stop or replace the existing app on port 5173**
- [ ] **Step 4: Capture route/interaction timings and traces; optimize only measured slow requests/renders; rerun the affected tests**
- [ ] **Step 5: Run keyboard and reduced-motion passes; verify no dead controls, focus traps, horizontal overflow, unhandled requests, React warnings or console errors**
- [ ] **Step 6: Run full PostgreSQL Compose tests in addition to SQLite; report PostgreSQL-only status separately**
- [ ] **Step 7: Ask a fresh reviewer to inspect the whole branch and all feature/test diffs; fix validated findings and rerun affected checks**
- [ ] **Step 8: Update implementation status with exact commands/results and commit the UI audit separately**
