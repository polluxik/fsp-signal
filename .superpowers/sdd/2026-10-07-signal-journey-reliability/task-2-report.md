# Task 2 — Backend authoritative contracts and interview outcome

**Status:** COMPLETE
**Base:** `2118ab2bfc07a28ad18a6b310b72cf40e8bad2f1`
**Commit:** `4a79a3e` — `fix: version profile preferences and confirm interviews`

## Scope delivered

- Candidate preference GET/PUT responses set `Cache-Control: no-store`.
- Candidate invitation `POST /view` returns current candidate-specific compatibility; employer creation/list/transition responses remain on the employer-safe serializer.
- Existing-profile PUT requires `expected_preferences_version`. Missing and stale versions return typed 409 responses with the current profile and preference state, without mutating either. First profile creation remains version-exempt. Legacy preference fields change structured preferences only after a current-version check.
- Added an additive Alembic migration (`5d7a9b2c4f11`, after `e8a1c4d57b20`) with nullable candidate/employer interview-confirmation timestamps. Existing rows are not rewritten.
- Added authenticated, participant-only held-interview confirmation. It requires an accepted invitation, locks the invitation row, records each participant idempotently, and emits the allowlisted/deduplicated `interview_held` event only after both confirmations. The event is represented as a bilateral outcome, not attributed to the last confirmer.
- Updated existing test clients for the versioned profile contract and the expected migration head. No frontend code or backend runtime module was changed.

## RED evidence

1. Migration regression, before production changes:

   ```text
   python -m pytest -p no:cacheprovider tests/test_migrations.py::test_interview_outcome_migration_preserves_existing_invitations -q
   FAILED — sqlite3.OperationalError: no such column: candidate_interview_confirmed_at
   1 failed
   ```

2. Task 1 backend regressions, before production changes:

   ```text
   python -m pytest -p no:cacheprovider tests/test_preferences.py tests/test_invitations_v2.py tests/test_product_events.py tests/test_employer_evidence_api.py tests/test_role_discovery.py -q
   6 failed, 25 passed, 1 warning
   ```

   The six expected failures were stale profile overwrite, missing no-store on preference GET and PUT, missing invitation-view compatibility, missing held-interview endpoint, and the event allowlist rejection.

3. Missing-version edge case, before production changes:

   ```text
   python -m pytest -p no:cacheprovider tests/test_preferences.py::test_profile_update_without_preference_version_cannot_overwrite_structured_preferences -q
   FAILED — endpoint returned 200 instead of required 409
   1 failed, 1 warning
   ```

4. After rereading the updated brief and before implementation, the migration test, stale-version test, and missing-version test were rerun together:

   ```text
   3 failed, 1 warning
   ```

   The migration failure was the absent column; both preference failures were incorrectly accepted with HTTP 200.

## GREEN and verification

- Focused Task 2 suite:

  ```text
  python -m pytest -p no:cacheprovider tests/test_preferences.py tests/test_invitations_v2.py tests/test_product_events.py tests/test_migrations.py tests/test_employer_evidence_api.py tests/test_role_discovery.py -q
  37 passed, 1 warning in 9.93s
  ```

- Full backend suite:

  ```text
  python -m pytest -p no:cacheprovider -q
  83 passed, 8 skipped, 1 warning in 12.35s
  ```

  The 8 skips are PostgreSQL-only checks. The remaining warning is environmental: installed Starlette deprecates using `httpx` with `starlette.testclient` and recommends `httpx2`.

- Migration metadata: `alembic heads` returned `5d7a9b2c4f11 (head)`.
- A SQLite downgrade smoke test confirmed the prior invitation-state triggers still reject an invalid state after downgrading to `e8a1c4d57b20`.
- `git diff --check` and `git diff --cached --check` completed without findings.

The first full-suite pass after implementation found three test-contract updates: two existing profile-save scenarios lacked the newly required version, and the migration-head assertion still named `e8a1c4d57b20`. Updated `tests/test_access_controls.py`, `tests/test_flow.py`, and `tests/test_runtime.py` as included in the regenerated brief; the final full-suite result above is after those changes.

During the first focused GREEN attempt, repeated confirmation by the other participant exposed an event dedupe conflict because the event actor changed. The handler now records `interview_held` with no single actor; the focused event/endpoint tests passed, followed by the final focused and full-suite runs above.

## Exact files in commit

- `backend/invitations.py`
- `backend/main.py`
- `backend/migrations/versions/5d7a9b2c4f11_interview_outcome.py`
- `backend/models.py`
- `backend/preferences.py`
- `backend/product_events.py`
- `backend/routes_v2.py`
- `backend/schemas.py`
- `tests/test_access_controls.py`
- `tests/test_flow.py`
- `tests/test_migrations.py`
- `tests/test_preferences.py`
- `tests/test_runtime.py`

Task 1's existing tests in `tests/test_invitations_v2.py` and `tests/test_product_events.py` were exercised by the focused suite and passed; they required no additional diff in this commit.

## Self-review and remaining concerns

- Confirmed the candidate-only serializer is used only by the candidate view endpoint; employer invitation output remains unchanged and the employer contract test passes.
- Confirmed conflict checks run before profile fields are changed; the response contains the current state and is `no-store`.
- Confirmed confirmation authorization hides non-participant invitations as 404, rejects non-accepted invitations with 409, and repeated calls do not create duplicate events.
- The migration is additive and PostgreSQL-compatible by construction, but a live PostgreSQL migration/test run was unavailable; the PostgreSQL-only tests remain skipped.
- The existing frontend has not yet been updated in this backend-only task to send `expected_preferences_version` on existing-profile saves. Such saves will now correctly receive 409 until the dependent UI task consumes the version contract.
- The Starlette/httpx deprecation warning remains; pytest cache warnings were avoided with `-p no:cacheprovider`.
- Uncommitted plan documents present before this task were preserved and excluded from the implementation commit.

## Independent review follow-up — concurrent SQLite confirmations

### RED evidence

Added `test_concurrent_participant_confirmations_succeed_and_emit_one_event` using the suite's file-backed SQLite database (`tests/conftest.py`), two separately authenticated `TestClient`s, and two concurrent HTTP requests on independent worker threads/connections. A SQLAlchemy `before_cursor_execute` barrier pauses both handlers immediately before the invitation `UPDATE`. With the original implementation, both handlers had already read and evaluated the invitation before either write was allowed to proceed.

```text
/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider tests/test_invitations_v2.py::test_concurrent_participant_confirmations_succeed_and_emit_one_event -q
FAILED — 1 failed, 1 warning in 0.61s
```

Both HTTP responses were 200, but each response reported only its own participant confirmed, and the final `interview_held` event count was 0 (expected exactly 1). This run reproduced a lost-outcome variant of the reviewed race; the default SQLite test configuration did not happen to raise `OperationalError`.

### Root cause and fix

The previous flow read the invitation, made a decision from those values, then ORM-flushed a timestamp change. SQLite ignores `SELECT FOR UPDATE`, so both handlers could make their decision from the same pre-confirmation row. Their writes could persist both timestamp fields while neither handler observed both confirmations; consequently neither emitted `interview_held`.

Changed the service to issue one conditional SQL `UPDATE` that predicates on invitation ID, accepted state, and participant identity. SQL `CASE` plus `COALESCE` sets only that participant's timestamp and preserves idempotency. This database write serializes competing confirmations across connections/processes (SQLite's writer lock; the row update lock on PostgreSQL); the subsequent locked read sees the post-serialization state, and event creation remains in the same transaction. No process-local lock and no broad `OperationalError` catch were added.

### GREEN and verification

```text
/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider tests/test_invitations_v2.py::test_concurrent_participant_confirmations_succeed_and_emit_one_event -q
1 passed, 1 warning in 0.56s
```

The concurrent test asserts both HTTP responses are 200 and exactly one `interview_held` event exists.

```text
/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider tests/test_invitations_v2.py tests/test_product_events.py -q
14 passed, 1 warning in 2.14s
```

```text
/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider -q
84 passed, 8 skipped, 1 warning in 12.18s
```

The 8 skips remain PostgreSQL-only checks; this follow-up was exercised against file-backed SQLite with independent request connections. The single warning remains the existing Starlette/httpx deprecation.
