# Signal Taxonomy and Assessment Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely add QA and Data Analyst at Junior/Middle with category-correct assessments, evidence, matching, role API support and synthetic bank fixtures.

**Architecture:** A single backend taxonomy catalog owns category IDs, labels, competency metadata, availability and blueprint versions. Assessment generation dispatches explicitly to a matching track; unsupported pairs fail closed. Existing categories and saved attempt versions remain backward compatible. Frontend selector integration is deferred to the separate UI audit.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/JSON, pytest, React 19, TypeScript, Vite, Playwright.

**Spec:** [Signal product polish design](../specs/2026-10-07-signal-product-polish-design.md)

**Execution scope:** The requested candidate-bank expansion is backend-only. This plan covers catalog, assessment, matching, API and synthetic-fixture support without changing frontend selectors.

## Global Constraints

- Support `backend`, `frontend`, `qa`, and `data_analyst`, each at `junior` and `middle`, subject to a reviewed assessment blueprint for that exact specialization/grade pair.
- The system must not fall through to the Frontend Middle assessment for an unknown pair.
- Unsupported or not-yet-reviewed pairs are not offered as verified assessments.
- Never identify synthetic records as real, verified or hired.
- Preserve the current single active verified category and cooldown contract; do not imply simultaneous credentials across tracks.
- Do not claim predicted hiring success or professional readiness from an assessment score.

## Review Focus

- Unknown specialization/grade must return a validation error, not a frontend fallback; test `tests/test_assessment_family.py::test_unsupported_category_fails_closed`.
- A generated seed must be reproducible for each new pair and each variant must total 100 points with phase-two mutation gating; test `tests/test_assessment_family.py::test_new_tracks_have_stable_complete_variants`.
- Existing `2026.1`/`2026.2` attempts must remain gradable and explainable; retain `tests/test_assessment_family.py::test_saved_2026_1_attempt_remains_gradable_after_blueprint_upgrade` and add an explicit `2026.2` snapshot regression.
- New competencies must not cross-match another category in candidate feed or employer bank; test `tests/test_matching_v2.py::test_new_categories_do_not_cross_match`.
- Candidate with one active verified track must not silently gain a second credential when selecting another track; add `tests/test_flow.py::test_track_change_respects_cooldown_and_single_verified_category`.

---

### Task 1: Introduce a single category and competency catalog

**Files:**
- Create: `backend/taxonomy.py`
- Modify: `backend/assessment.py`
- Modify: `backend/schemas.py`
- Modify: `backend/routes_v2.py`
- Modify: `backend/main.py`
- Test: `tests/test_assessment_family.py`
- Test: `tests/test_role_cards.py`

**Interfaces:**
- Consumes: existing specialization/grade strings and four current blueprints.
- Produces: `available_categories() -> list[CategoryDefinition]`, `get_category(specialization: str, grade: str) -> CategoryDefinition | None`, `competencies_for(specialization: str, grade: str) -> tuple[str, ...]`; public `GET /api/v1/taxonomy/categories` returns available pairs and labeled competencies.

- [x] **Step 1: Add failing catalog/API tests for the supported pairs and rejected unknown pairs**

  Assert the response shape contains `id`, `specialization`, `grade`, `label`, `blueprint_version`, `available` and competency IDs/labels; assert unavailable categories are not selectable.

- [x] **Step 2: Run focused tests and confirm that unknown pairs currently fail to enumerate correctly or are accepted through scattered literals**
- [x] **Step 3: Add the catalog and endpoint, then replace `Literal`/hard-coded validation sites with catalog-backed validation while keeping stable existing IDs**
- [x] **Step 4: Run focused taxonomy, assessment, role-card and matching tests; expected: PASS and OpenAPI exposes the catalog endpoint**
- [ ] **Step 5: Commit the catalog/API slice after tests pass**

### Task 2: Add QA and Data Analyst blueprint modules

**Files:**
- Create: `backend/assessment_qa.py`
- Create: `backend/assessment_data_analyst.py`
- Modify: `backend/assessment.py`
- Modify: `backend/evidence.py`
- Modify: `backend/matching.py`
- Modify: `tests/test_assessment_family.py`
- Modify: `tests/test_evidence.py`
- Modify: `tests/test_matching_v2.py`

**Interfaces:**
- Consumes: Task 1 category catalog.
- Produces: explicit assessment dispatch by `(specialization, grade)`; pair-specific blueprint version; complete public questions, answer keys and competency scores; readable competency labels and evidence provenance.

- [x] **Step 1: Write failing deterministic tests for the four new pairs**

  Pin the competencies: QA Junior `test_design`, `bug_reporting`, `api_testing`; QA Middle `risk_based_testing`, `automation_design`, `reliability_testing`; Data Analyst Junior `sql_querying`, `data_quality`, `metric_definition`; Data Analyst Middle `experiment_analysis`, `metric_integrity`, `data_validation`. For 100 seeds assert unique question IDs, exactly 100 maximum points, all categories represented, phase-two mutation gates pass/fail correctly, and output has the matching pair-specific blueprint version.

- [x] **Step 2: Add fail-closed and historical-attempt grading tests**

  Assert an unknown pair raises `ValueError("unsupported category")`; stored `2026.1` and `2026.2` snapshots still grade through their saved questions/key.

- [x] **Step 3: Run assessment-family tests before implementation; expected: fail for missing blueprints/dispatch and preserve current legacy tests**
- [x] **Step 4: Implement task families with role-specific scenarios and rubrics**

  QA tasks cover risk/design, reproducible bug report and API behavior; Data Analyst tasks cover SQL/quality/metric interpretation and experiment pitfalls. Do not duplicate the same question set across grades.

- [x] **Step 5: Implement explicit dispatch and evidence/matching labels; remove the generic final Frontend Middle fallback**
- [x] **Step 6: Run focused assessment, evidence and matching tests; expected: PASS for all eight pairs and preserved legacy grading**
- [ ] **Step 7: Commit the assessment blueprints and evidence/matching integration after tests pass**

### Task 3: Propagate the catalog through search and demo fixtures

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/routes_v2.py`
- Modify: `backend/main.py`
- Modify: `backend/seed_demo.py`
- Modify: `tests/test_role_discovery.py`

**Interfaces:**
- Consumes: Task 1 catalog and Task 2 blueprints.
- Produces: consistent category options and counts across assessment, employer role creation, candidate role filters, employer bank filters, seed data and matching.

- [x] **Step 1: Add failing API and seed tests for category isolation and 96 synthetic profiles**

  Assert 12 synthetic candidates for each of eight pairs (48 existing + 48 new), one synthetic role per pair, correct label/stack and no cross-category discovery.

- [x] **Step 2: Run failing backend tests for new categories and synthetic fixtures**
- [x] **Step 3: Expand demo fixtures from 48 to 96, deriving counts and competency labels from the catalog; preserve `origin="synthetic_fixture"`**
- [x] **Step 4: Add four synthetic discoverable role fixtures and verify candidate-bank/API filtering remains category-correct**
- [x] **Step 5: Run the complete backend suite, frontend build and E2E; expected: PASS, old fixtures and profile cooldown tests remain intact**
- [ ] **Step 6: Commit the backend taxonomy/assessment/bank expansion independently**

Task 1–3 RED/GREEN evidence and verification: [Taxonomy expansion report](../reports/2026-10-07-signal-taxonomy-report.md).
