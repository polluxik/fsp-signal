# Backend taxonomy, assessment and candidate-bank expansion

Date: 2026-10-07
Branch: `codex/signal-product-polish`

## Delivered

- Added a single backend taxonomy for Backend, Frontend, QA and Data Analyst at Junior/Middle. `GET /api/v1/taxonomy/categories` publishes category IDs, labels, competency IDs/labels, availability and blueprint versions, with a typed OpenAPI response model.
- Removed hard-coded Backend/Frontend specialization gates from the role-card and candidate role-feed API schemas/routes. Unsupported specialties and competency/category combinations fail closed at their HTTP boundary.
- Added versioned QA and Data Analyst assessment blueprints with track-specific prompts, exact competency ownership and 100-point rubrics. Each competency has a phase-two mutation gate; unknown pairs cannot fall through to Frontend Middle. Existing `2026.1`/`2026.2` grading remains supported.
- Connected the taxonomy labels and category-specific competency suggestions to backend matching/evidence descriptions. Search scores remain category-local; new categories do not cross-match.
- Expanded the synthetic bank from 48 to 96 records: 12 per each of eight specialization/grade pairs. Added four active synthetic discovery roles, for at least one per pair. Profiles and role versions retain explicit synthetic provenance.
- Employer category counts and bank filters, plus candidate role-feed filters, now include all eight pairs. A track-change integration test confirms the existing 30-day cooldown and singular verified category remain intact.
- Left all frontend source selectors unchanged, as requested for this backend-only bank expansion. The existing browser test now verifies the 10-role feed and visibility of new QA/Data Analyst examples.

## RED/GREEN evidence

- Before implementation, the taxonomy endpoint returned 404, `RoleCardIn` rejected QA, the assessment registry lacked the new categories/version resolver, and the seed exposed only five discovery roles and 48 profiles.
- New tests first failed on those missing contracts. The OpenAPI assertion also caught an untyped endpoint response; adding explicit response models made the catalog schema visible to generated clients.
- The first full E2E after seed expansion failed because it still expected 6 roles; the product now seeds 10 roles. The browser assertion was updated to the new fixture count and additionally checks that QA Junior and Data Analyst Junior roles appear. That targeted case and the full suite passed afterward.

## Verification

- `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest -p no:cacheprovider -q` — 101 passed, 8 PostgreSQL-only tests skipped, one existing Starlette/httpx deprecation warning.
- `cd frontend && npm run build` — passed; frontend source was unchanged in this backend-only expansion.
- `cd frontend && FSP_SIGNAL_E2E_PYTHON=/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python npm run test:e2e` — 6 passed on isolated localhost services and a synthetic SQLite database.
- The focused candidate discovery browser scenario also passed with 10 seeded roles, including the new QA and Data Analyst examples.
- Focused taxonomy/assessment/role API/matching/evidence/seed regressions passed (44 passed before the final OpenAPI/alias additions; the subsequent full suite includes those additions).
- `git diff --check` — passed before review/commit.

## Limitations

- PostgreSQL runtime behavior was not re-run in this task; 8 PostgreSQL-only tests were skipped in the SQLite environment.
- The frontend assessment, role-editor and filter selectors still show Backend/Frontend only; this is intentionally deferred to the separate UI workstream and means users cannot yet select the new tracks through those controls.
- The new blueprints are deterministic engineering rubrics, not externally calibrated assessments; the 96 seeded profiles are synthetic demos, not evidence of real candidate quality or hiring outcomes.
