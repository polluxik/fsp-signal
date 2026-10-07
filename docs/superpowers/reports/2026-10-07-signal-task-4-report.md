# Task 4 — close and verify the core flow

Date: 2026-10-07  
Branch: `codex/signal-product-polish`

## Delivered

- New searches use neutral `match_v2` by default; it does not add the unvalidated FSP bonus. Historical snapshots still render with the algorithm version stored when the snapshot was created. The bank test score remains category/test-only and does not add an FSP bonus.
- Legacy snapshot tests explicitly select `match_v1`, while the new-default integration test verifies `match_v2` and its bank score. An integrated employer flow now creates and publishes a versioned role before searching, matching the real API lifecycle.
- Employers can withdraw a pending invitation from the offers page, with a disabled/busy state during the request and a visible recoverable error on failure.
- Browser coverage now walks the invitation cycle through send, withdraw, candidate view, rejection without contact disclosure, re-invitation, acceptance, contact access and bilateral interview confirmation. Reloads verify the candidate sees current server state.
- On a stale invitation-state conflict, the employer UI reloads offers and explains that the user should re-check the latest state before retrying; it never blindly repeats a state-changing request.
- Privacy coverage checks that preference fields are absent and searches for the exact private minimum after removing only the explicitly public role salary fields. This catches a number leaking under another key or nested object while allowing an equal public job salary.

## RED/GREEN evidence

- Before changing the configuration default, the new-search regression failed because it received `match_v1`; after the default changed, the focused matching/snapshot suite passed.
- Before adding the employer withdrawal action, the browser scenario failed because no “Отозвать приглашение” control existed. After the action was implemented, the browser completed withdrawal and confirmed the candidate saw a non-actionable withdrawn state.
- The first full backend run exposed the privacy test's false positive: `230000` came from a public role's salary, not the candidate preference. The structural contract assertion passed in isolation and in the subsequent full suite.
- Independent review identified a real stale-version race: the employer may hold a `sent` snapshot after the candidate has viewed the offer. The expanded browser test reproduced the `409`; the UI now reloads current invitations and the same test retries safely after confirming the new state.
- Independent review also asked the privacy assertion to retain its exact-value check. It now excludes only public `role.salary_min_rub`/`role.salary_max_rub` before searching the JSON for the private `230000`, so other forms of the same-value leak remain test failures.

## Verification

- `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider tests/test_matching_v2.py tests/test_search_snapshots.py -q` — 17 passed in the focused matching/snapshot run.
- `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider -q` — 84 passed, 8 PostgreSQL-only tests skipped, one existing Starlette/httpx deprecation warning.
- `cd frontend && npm run build` — passed; Vite output 336.05 kB JS and 19.81 kB CSS before gzip.
- `cd frontend && FSP_SIGNAL_E2E_PYTHON=/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python npm run test:e2e` — 6 passed using isolated localhost services, a temporary SQLite database and synthetic records; the existing app on port 5173 was not used.
- The focused invitation browser scenario passed after adding the reject/re-invite cycle and stale-state retry.
- `git diff --check` — passed.

## Limitations

- PostgreSQL-only behavior remains unverified in this run; 8 tests are explicitly skipped by the SQLite environment.
- The E2E set covers critical desktop flows, not the full mobile, keyboard-only or reduced-motion audit; those remain in the dedicated UI live-audit plan.
- Matching weights remain a documented hypothesis; no labeled employer relevance study or user pilot has validated Precision@5/nDCG@5.
