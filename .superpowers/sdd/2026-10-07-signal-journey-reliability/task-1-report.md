# Task 1 — candidate/employer journey regression tests (RED phase)

**Status:** Complete. Regression tests were added and run against the unchanged production code. No production files or runtime UI files were modified.

## Changed files

- `tests/test_preferences.py`
  - Added a stale profile-snapshot regression: after a newer `CandidatePreferencesIn` save, submitting the old profile snapshot with its old preference version must return `409 PREFERENCES_VERSION_CONFLICT`; the current preferences and profile must remain unchanged.
  - Added independent GET and PUT assertions that candidate preference responses set `Cache-Control: no-store`.
- `tests/test_invitations_v2.py`
  - Added a comparison of candidate invitation GET compatibility status/checks against the response from POST `/view`.
  - Added the two-party held-interview lifecycle: pending invitation cannot be confirmed; non-participants cannot confirm; one participant and repeated confirmations do not emit the held event; both participants confirming emits exactly one event, including after retries.
- `tests/test_product_events.py`
  - Added an allowlist and deduplication regression for `interview_held` events.
- `tests/test_employer_evidence_api.py`
  - Added a realistic opted-in legacy aggregate profile and asserted the API labels it `aggregate` / `aggregate_only`, not `verified_action`, while preserving the limitation that no concrete action can be reconstructed.
- `frontend/tests/core-flow.spec.ts`
  - Added browser assertions that legacy aggregate and declared-skill evidence have distinct visible provenance labels and neither is shown as “Действие проверено заданием”.

`tests/test_role_discovery.py` was intentionally not changed. Its existing `test_stale_role_and_preferences_versions_do_not_mutate_a_saved_decision` remains intact and passed in the focused run.

## Verification

Baseline before test edits:

```text
/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest tests/test_preferences.py tests/test_invitations_v2.py tests/test_product_events.py tests/test_employer_evidence_api.py tests/test_role_discovery.py -q
24 passed, 2 warnings in 4.94s
```

Required focused command after edits:

```text
/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest tests/test_preferences.py tests/test_invitations_v2.py tests/test_product_events.py tests/test_employer_evidence_api.py tests/test_role_discovery.py -q
.FFF..FF.........F.............                                          [100%]
6 failed, 25 passed, 3 warnings in 6.07s
```

All six final failures are the intended RED evidence:

1. `test_profile_update_cannot_overwrite_newer_preferences` — stale profile update returned `200` instead of `409`; response shows old salary/work format overwrote the newer snapshot. Assertions for the resulting persisted values are present after the expected conflict assertion.
2. `test_candidate_preferences_get_returns_no_store` — GET returned no `Cache-Control` header.
3. `test_candidate_preferences_put_returns_no_store` — PUT returned no `Cache-Control` header.
4. `test_viewed_invitation_retains_candidate_compatibility` — POST `/view` returned `compatibility: null` while candidate GET contained a populated report.
5. `test_interview_is_counted_only_after_both_parties_confirm` — confirming an unaccepted invitation returned generic `404 Not Found` because the confirmation endpoint/contract is absent; the test expects a state conflict and then verifies authorization, two-party counting, and retry idempotency.
6. `test_held_interview_event_is_allowlisted_and_deduplicated` — `write_product_event` rejects `interview_held` as not allowlisted.

The other 25 tests passed, including the existing stale-role-decision regression and the new legacy aggregate API test. The earlier first run had a missing test import (`now`), which was fixed before the final exact run; it is not a remaining failure.

Focused browser check for the new visible provenance assertions:

```text
FSP_SIGNAL_E2E_PYTHON=/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python npm run test:e2e -- --grep "role facts, selected evidence, explicit acceptance, and pair-scoped contact access work end to end"
1 passed (8.6s)
```

Playwright used its randomized localhost ports and a temporary SQLite database; port `5173` was not used. The first browser attempt exposed a strict-mode ambiguity because the fixture contains two declared-skill cards; the test now checks both cards individually and passes. The initial sandbox attempt to bind a randomized port was denied; rerunning the same test with permission for its isolated localhost servers succeeded.

## Warnings and concerns

- Pytest reported the installed Starlette/httpx deprecation warning.
- Pytest also warned that it could not write `.pytest_cache` under this worktree because of filesystem permissions. This did not affect test execution or results.
- The focused backend run is intentionally red; no implementation was attempted in this task. The test report should not be interpreted as a green feature state.
- No frontend build was run. The relevant browser test itself compiled and executed successfully.

## Self-review

- All backend scenarios use authenticated `TestClient` sessions, real route handlers, persisted test-database state, and existing invitation/search fixtures; no production behavior is mocked.
- Assertions target HTTP responses, persisted preference outcomes, event emission/count, and visible UI labels rather than implementation source text.
- Edge cases covered include stale versions, unaccepted invitations, candidate/employer outsiders, repeated confirmation, no-store on both read and write, and the difference between aggregate, synthetic, and declared evidence.
- The pre-existing stale feed-decision test was verified by the required command and left unchanged.
- `git diff --check` passed before commit. Only the five listed test files and this report are in scope; pre-existing untracked planning documents are being left untouched.
