# Task 3 — candidate/employer UI state repair

Date: 2026-10-07
Branch: `codex/signal-product-polish`

## Delivered

- Candidate profile saves now include the version attached to the profile when loaded, preventing a stale profile snapshot from silently restoring newer private preferences.
- Invitation view merging preserves the existing compatibility/evidence snapshot when a partial server response omits either field.
- Employer invitation setup errors map to a clear message and preserve the selected candidate and draft. A failed company-profile save remains visible, retains entered values, and leaves a route back to the invitation.
- Employer cards separate role match, assessment score, evidence coverage, source/category status, and unknown competency data. Missing signals are not represented as zero or as proof of no skill.
- Evidence provenance has explicit labels for verified actions, candidate declarations, aggregate assessments and synthetic examples; unknown provenance is not called verified.
- Accepted invitations expose bilateral held-interview confirmation to each participant. Invitation reads now return each participant's confirmation state so the UI can survive reloads; the meeting is reported as held only after both confirm.
- Extracted shared Playwright sign-in/user helpers and configured discovery for all `*.spec.ts` files.

## RED/GREEN evidence

- Before production changes, the preference-save/profile-save E2E failed with `PREFERENCES_VERSION_REQUIRED`; this verified that the existing profile path omitted the version required by the backend.
- Before adding invitation confirmation booleans to the response, the API regression failed with `KeyError: candidate_interview_confirmed` after one participant confirmed.
- A new company-save failure regression first failed because no alert was rendered after an intercepted HTTP 503. After leaving the setup-only error branch on failure, the same test passed and confirmed the error, retained company input, return action and preserved invitation draft.
- Independent review found two additional gaps: a profile form was attaching a freshly fetched preference version to stale values, and `COMPANY_PROFILE_REQUIRED` on role creation lacked a setup action. New E2E tests failed before the fixes. Profile saves now use the version from the loaded profile; same-tab preference saves synchronize only the coupled profile fields/version, and a different-session update causes a conflict without overwriting the saved values. Role creation now preserves the role draft while routing to company setup and back.
- A delayed initial profile response also reproduced a safe-but-unnecessary version conflict after same-tab preferences were saved. The merge now keeps a newer client preference version and its coupled fields while still hydrating the rest of the profile. The delayed-response browser regression first failed at profile-save status, then passed after the merge guard.
- The cross-session test initially affected a later test because the E2E suite shares synthetic fixtures. It now restores that candidate's previous salary/city preferences through the UI before ending.

## Verification

- `cd frontend && npm run build` — passed (TypeScript and Vite; final bundle 335.17 kB JS, 19.81 kB CSS before gzip).
- `cd frontend && FSP_SIGNAL_E2E_PYTHON=/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python npm run test:e2e -- --grep "role facts"` — 1 passed after the error-state fix.
- `cd frontend && FSP_SIGNAL_E2E_PYTHON=/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python npm run test:e2e` — 6 passed (13.1s), using Playwright's isolated localhost services, temporary SQLite and synthetic test records; the original port 5173 was not used.
- `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider -q` — 84 passed, 8 PostgreSQL-only tests skipped, one existing Starlette/httpx deprecation warning.
- `git diff --check` — passed.

## Limitations

- PostgreSQL-specific runtime behavior remains unverified in this environment; 8 PostgreSQL-only tests were skipped.
- This task's browser checks exercise critical desktop flows, not a complete visual, mobile, keyboard-only or reduced-motion audit. Those checks remain in the separate UI live-audit workstream.
- Playwright emitted an environment warning that `NO_COLOR` is ignored when `FORCE_COLOR` is set; it did not affect test results.
