# Synthetic IT Market Seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic demo market with 32 IT role families, 120 new active vacancies, 200 original synthetic candidate CVs, and honest profile-based matching while preserving current verified assessment flows.

**Architecture:** Keep the four existing assessment tracks and legacy role-card payloads as schema v1. Add a versioned role taxonomy and a separate v2 CV/role contract; new-family matching uses declared skills and structured work evidence with transparent coverage, never assessment claims. Generate demo records from curated, versioned Russian-language role and scenario data without copying attached or public CV text.

**Tech Stack:** Python 3.12-compatible FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite/PostgreSQL; React 19, TypeScript 7, Vite 8, Playwright; pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-synthetic-market-data-design.md`

## Global Constraints

- Create 120 new active synthetic vacancies and 200 new fully synthetic candidate profiles; retain the current 48 demo candidates, six roles, and four assessment tracks.
- Cover 32 stable role families with Russian and English labels/aliases; declared levels are `junior`, `middle`, `senior`, and `lead`.
- Candidate levels are self-described, not assessed or inferred from years of experience; role-level filtering is explicit, and level difference alone does not silently reject a candidate.
- Seed only in `APP_MODE=demo`; repeated seed runs are idempotent and never overwrite user-created records.
- Do not use attached PDFs, raw public CV text, real personal data, or external LLM calls as seed-generation inputs.
- Store new-family candidate/role taxonomy separately from legacy `verified_specialization`; new-family profiles are `not_assessed`, never falsely verified.
- Preserve old role-card schema/API behavior; new-family role versions use immutable versioned v2 payloads and nullable legacy specialization/grade fields.
- Keep employer privacy, candidate consent, block lists, salary/work-format/location hard preferences, and invitation acceptance/contact-reveal rules intact.
- `profile_fit_v1` uses required-skill coverage, traceable work-action evidence, and preferred-skill coverage with initial weights `50/30/20`; unknown data is not scored as a mismatch, and no observable evidence returns a null score with `insufficient_data`.
- Match only within the same canonical family or an explicitly tested crosswalk; vocabulary coincidence alone is insufficient.
- Every generated record is marked synthetic/demo; fictional metrics are not presented as measured platform or labor-market outcomes.
- New vacancies include structured responsibilities, expected results, required/preferred skills, stack, salary range, work format/location, first-30-day outcomes, interview stages, response SLA, and synthetic employer contact.

---

### Task 1: Role taxonomy and structured candidate CV contract

**Files:**
- Create: `backend/role_taxonomy.py`
- Create: `backend/resume_schemas.py`
- Modify: `backend/models.py`
- Modify: `backend/schemas.py`
- Modify: `backend/main.py`
- Create: one Alembic revision after the current migration head in `backend/migrations/versions/`
- Create: `tests/test_role_taxonomy.py`
- Create: `tests/test_resume_profile.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- `ROLE_TAXONOMY_VERSION: str` is `it_roles_v1`.
- `ROLE_FAMILIES` is an immutable ordered collection of 32 records with stable `id`, Russian/English names, aliases, parent area, and subtypes.
- `resolve_role_family(label: str) -> RoleFamily | None` resolves normalized explicit aliases only; ambiguous and unknown labels return `None`.
- `ResumeV1In` validates desired role family/subtype, declared level, work history, projects, optional education, languages, and certificates; absence of optional sections stays `unknown` rather than being synthesized as a negative signal.
- `CandidateProfile.resume_v1` stores that validated shape without changing legacy `desired_specialization`, `claimed_grade`, preferences, skills, or achievement-story semantics. Rich work-history/project evidence is employer-visible only when the candidate explicitly enables `share_with_employers` for the resume, and the normal publication/consent/block eligibility checks pass.
- Employer search snapshots store the resume version/fingerprint used for matching, never the raw private CV; edits mark the saved result stale through the existing snapshot freshness mechanism.

- [ ] Write failing tests for all 32 stable IDs, Russian/English alias lookup, case/Ё normalization, unknown labels, and ambiguous aliases.
- [ ] Write failing schema/API tests for varied CV completeness, detailed achievement fields, valid experience periods, invalid family IDs, and round-trip persistence without mutating old profile fields.
- [ ] Stabilize the pre-existing migration test fixture: its `2026-10-08T00:00:00+00:00` pending invitation is already expired at the current test time, so migration expires both duplicates before the duplicate diagnostic. Set duplicate/accepted fixture expiry to `2099-10-08T00:00:00+00:00`, and add a separate test proving past-due duplicate invitations become `expired` before uniqueness validation.
- [ ] Run `python -m pytest tests/test_role_taxonomy.py tests/test_resume_profile.py tests/test_migrations.py -q` and confirm failures identify missing behavior.
- [ ] Add the taxonomy registry and typed `ResumeV1In`; keep family aliases unique and map only explicit, tested crosswalks.
- [ ] Add `resume_v1` JSON storage and additive Alembic columns for role-family/level metadata; make only the legacy specialization/grade columns nullable, preserving existing values and constraints for current records.
- [ ] Extend candidate read/write DTOs to validate and round-trip `resume_v1`; do not expose private salary floors or contact fields through employer DTOs.
- [ ] Include `resume_v1` in the candidate's own private profile endpoint only; add employer evidence cards for opted-in work-history/project entries, with declared provenance, only after the existing publication/consent/block checks.
- [ ] Add a resume version/fingerprint to role-specific employer search snapshots and stale-input detection; do not persist resume contents in the snapshot.
- [ ] Re-run `python -m pytest tests/test_role_taxonomy.py tests/test_resume_profile.py tests/test_migrations.py -q`; expected result is all selected tests passing with no migration data loss.
- [ ] Commit as `feat: add versioned IT taxonomy and candidate CV schema`.

### Task 2: Versioned v2 vacancies and evidence-first matching

**Files:**
- Create: `backend/role_card_v2.py`
- Modify: `backend/role_cards.py`
- Modify: `backend/routes_v2.py`
- Modify: `backend/role_discovery.py`
- Modify: `backend/matching.py`
- Modify: `backend/invitations.py`
- Modify: `backend/schemas.py`
- Modify: `backend/main.py`
- Modify: `backend/evidence.py`
- Create: `tests/test_role_cards_v2.py`
- Modify: `tests/test_matching_v2.py`
- Modify: `tests/test_role_discovery.py`
- Modify: `tests/test_invitations_v2.py`
- Modify: `tests/test_employer_search.py`
- Modify: `tests/test_evidence.py`

**Interfaces:**
- `RoleCardV2In` requires `schema_version=2`, a known `role_family_id`, subtype, declared `role_level`, canonical required/preferred skill IDs, structured role terms, and synthetic provenance when created by the demo seed.
- `profile_fit_v1(profile: CandidateProfile, role: RoleCardV2In) -> MatchResult` returns score/null, `score_status`, score version, observed coverage, hard-compatibility report, per-signal evidence source, and verification status.
- Employer's existing role-specific `POST /api/v1/employer/searches` accepts v2 role snapshots and ranks eligible declared profiles through `profile_fit_v1`; saved results show family/declared level, honest score coverage, evidence, and not-assessed status without treating candidates as assessment-verified.
- Candidate discovery returns a backwards-compatible union of v1 and v2 cards; v2 cards carry family and declared level, optional family/level filters, profile fit and coverage, and existing hard preference checks.
- Existing v1 `RoleCardIn`, v1 role versions, and v1 invitations remain valid and retain current matching behavior.

- [ ] Add failing v2 contract tests for valid/invalid family, subtype, level, skill ID, salary bounds, office/hybrid city, and immutable v2 snapshot versioning.
- [ ] Add failing matcher tests for exact-family acceptance, explicit crosswalk, lexical-only rejection, unknown evidence, normalized observed weights, zero-evidence null score, and `declared` versus `not_assessed` versus `verified` labels.
- [ ] Add failing regression tests for legacy v1 matching, preference/block/privacy constraints, and v2 invitation acceptance with contacts hidden until acceptance.
- [ ] Add failing tests for employer-selected v2 role search, stable/stale snapshots after resume edits, candidate-visible feed/filtering of v2 roles, and score rendering when there are insufficient observations.
- [ ] Run the focused new and existing role/matching/discovery/invitation tests; confirm failures are due to missing v2 behavior, not fixture or import errors.
- [ ] Implement v2 validation and snapshot serialization in a separate module; branch on snapshot schema version rather than guessing from role-title text.
- [ ] Extend candidate discovery to filter new roles by `role_family_id` and `role_level`, apply existing hard constraints first, then rank only compatible roles using `profile_fit_v1`.
- [ ] Extend the existing employer role-specific search path to validate v2 immutable snapshots and use the v2 eligibility/matcher; preserve the separate legacy verified candidate-bank behavior and do not invent a bank score for unassessed profiles.
- [ ] Render employer candidate cards with v2 family/declared level, score status/coverage, and evidence provenance; ensure `None` score does not render as `0`, `undefined`, or a verified badge.
- [ ] Keep unknown features unknown, expose score coverage/source labels, and prevent automated rejection/invitation or assessment fabrication.
- [ ] Extend invitation serialization to pin v2 snapshots while retaining legacy v1 parsing and the existing consent/contact-reveal transaction.
- [ ] Ensure the v2 candidate feed union and invitation flow preserve v1 DTO compatibility and do not reveal profile contacts before candidate acceptance.
- [ ] Re-run focused tests, then `python -m pytest tests/test_role_cards.py tests/test_role_cards_v2.py tests/test_matching_v2.py tests/test_role_discovery.py tests/test_invitations_v2.py -q`.
- [ ] Commit as `feat: add v2 role cards and profile-fit matching`.

### Task 3: Diverse deterministic synthetic profiles and vacancies

**Files:**
- Create: `backend/synthetic_market_data.py`
- Create: `backend/synthetic_market.py`
- Modify: `backend/seed_demo.py`
- Create: `tests/test_synthetic_market.py`
- Modify: `tests/test_role_discovery.py`

**Interfaces:**
- `build_synthetic_market(seed: int) -> SyntheticMarket` returns stable role and candidate fixture records without database side effects.
- `validate_synthetic_market(market: SyntheticMarket) -> None` rejects duplicate IDs/text, unknown taxonomies, invalid chronology/salaries, unsafe contacts, incomplete role cards, and unmet diversity quotas.
- `seed_demo.seed()` persists those fixtures only in demo mode, marks origin/data mode synthetic, and leaves existing user records untouched.

- [ ] Write failing tests for exact totals, all-family coverage, per-family/per-level minimums, six career scenarios, optional-section variation, distinct profiles/job descriptions, and detailed achievement narratives.
- [ ] Write failing seed tests for demo-mode rejection, stable IDs/counts across a second run, no overwrite of existing non-demo records, and preservation of the existing 48 assessment fixtures/six role cards.
- [ ] Run `python -m pytest tests/test_synthetic_market.py tests/test_role_discovery.py -q` and confirm failures demonstrate missing generated data/behavior.
- [ ] Build an original Russian-language fixture library with role-specific skill/action vocabulary and varied work histories, projects, transitions, education, narrative depth, and qualitative/clearly fictional quantitative outcomes; do not paraphrase attached or public CV text.
- [ ] Generate 120 active discoverable v2 roles distributed 3–4 per family and 200 new candidates with at least five target profiles per family and at least 25 per declared level.
- [ ] Use reserved `.test` email addresses, no callable phone numbers, synthetic employer identities, stable fixture IDs, and explicit `not_assessed` status; do not modify current 48 candidates or fabricate assessment scores for new families.
- [ ] Persist roles and profiles idempotently, without calling any external LLM, modifying existing non-fixture users, or enabling the seed outside `APP_MODE=demo`.
- [ ] Re-run focused tests and `python -m pytest tests/test_synthetic_market.py tests/test_role_discovery.py tests/test_matching_v2.py -q`.
- [ ] Commit as `feat: seed diverse synthetic IT market`.

### Task 4: Candidate/employer UI, end-to-end validation, and usage docs

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/features/roles/RoleFeed.tsx`
- Modify: `frontend/src/features/roles/RoleCard.tsx`
- Modify: `frontend/src/features/evidence/EvidencePanel.tsx` if required to display v2 evidence source/status without duplicating labels
- Modify: employer search/result components in `frontend/src/App.tsx` (or extract focused components if appropriate)
- Create: a focused candidate resume editor component under `frontend/src/features/profile/` if this keeps the existing profile screen maintainable
- Modify: `frontend/tests/core-flow.spec.ts`
- Modify: `frontend/tests/employer-search.spec.ts` if role-search flow is separate
- Modify: `README.md`
- Modify: `docs/implementation-status.md`

**Interfaces:**
- Frontend DTOs consume server-provided family labels, declared level, fit score/status/coverage, synthetic data mode, and per-signal evidence/verification status.
- Candidate discovery supports taxonomy-family/level filters without changing legacy assessment screens or existing v1 flows.
- Candidate profile editor can manage varied role targets, work history and projects, optional education/languages/certificates, and an explicit employer-sharing control; absent optional sections remain unknown.
- Employer role-specific search renders v2 profiles with honest declared/not-assessed status, score coverage and evidence; the legacy verified candidate bank keeps its established semantics.
- Synthetic/demo banners distinguish fixture profiles and vacancies from live marketplace records.

- [ ] Add failing Playwright coverage for rendering/filtering a new-family role, showing `not_assessed` and evidence coverage honestly, viewing detailed profile/achievement evidence, and completing a v2 invitation through acceptance without early contact reveal.
- [ ] Add failing Playwright coverage for editing/saving a structured CV and opting in/out of employer evidence sharing; assert private contact/salary data remain absent from the employer view until the normal reveal transaction.
- [ ] Add failing Playwright coverage for employer selecting a seeded v2 role, running a search, inspecting evidence/score coverage, and seeing an insufficient-data state without a fabricated numeric score.
- [ ] Run `npm run build` and the focused Playwright test to verify the new contract fails before implementation.
- [ ] Extend TypeScript API types and UI rendering from response DTOs; avoid a front-end duplicate taxonomy and avoid a broad visual redesign.
- [ ] Keep all interactive controls keyboard-operable, loading/error/empty states explicit, and old Backend/Frontend role flows intact.
- [ ] Document the local demo seed command, counts, data provenance, synthetic labels, and the fact that generated fixture matches are not hiring-quality validation.
- [ ] Re-run `npm run build`, focused Playwright tests, and the full existing `npm run test:e2e`.
- [ ] Commit as `feat: show synthetic role families in discovery UI`.

## Final Verification and Download Archive

- [ ] Run full backend suite: `python -m pytest -q`.
- [ ] Run migration tests on clean SQLite and, when Docker is available, the documented PostgreSQL/Compose path.
- [ ] Run frontend production build: `npm run build`.
- [ ] Run complete browser suite: `npm run test:e2e`.
- [ ] Start from a clean demo database, run migrations and seed twice, and verify 126 discoverable roles including 120 new v2 vacancies, 200 new candidates, 32 represented families, and retained legacy fixtures.
- [ ] Review final branch diff and privacy scan: no PDF, extracted CV text, secrets, real contacts, or generated non-demo fixtures.
- [ ] Build a source archive from the committed branch state, excluding `.git`, `.env`, virtualenvs, `node_modules`, caches, and local databases; save as `/Users/danielbubusan/Downloads/fsp-signal-synthetic-market-seed.zip`.
