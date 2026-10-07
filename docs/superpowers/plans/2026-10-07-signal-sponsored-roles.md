# Signal Sponsored Role Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demonstrate a credible employer-paid role promotion path without checkout, fake revenue, paid candidate ranking or changes to organic relevance.

**Architecture:** Store demo campaign state separately from role match data. Discover and filter eligible roles using the candidate's existing hard preferences first, then return sponsored items in a distinct response section and keep them out of the organic order. Record only privacy-minimal, synthetic-aware product events.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest, React 19, TypeScript, Playwright.

**Spec:** [Signal product polish design](../specs/2026-10-07-signal-product-polish-design.md)

**Status:** Implementation and verification are complete in the isolated worktree; commits/push are intentionally not part of this implementation pass because the branch contains other interdependent uncommitted work.

## Global Constraints

- Apply candidate hard eligibility and preferences before sponsored exposure.
- Do not change match score, organic order, candidate ranking or who can receive an invitation.
- Clearly label sponsored exposure and show “Демо — без оплаты.”
- Demo revenue is always ₽0; no checkout, charge or claim of validated willingness to pay.
- Candidate access remains free; no paid-to-rank candidates or pay-to-pass assessments.
- Never identify synthetic records as real, verified or hired.

## Review Focus

- Expired, paused, closed, stale and superseded campaigns are not returned; tests `tests/test_promotions.py::test_demo_campaign_activation_requires_active_discoverable_current_role` and `::test_campaign_for_superseded_or_expired_role_version_is_not_served`.
- Salary, city, format, blocked-company and hidden-role constraints apply before sponsored selection; saved-only view has no sponsored shelf; test `tests/test_promotions.py::test_only_current_active_campaign_is_sponsored_and_preferences_stay_hard`.
- Promotion preserves the original organic rank window and match results, never duplicates a role within or across feed pages; tests `tests/test_promotions.py::test_promotion_does_not_change_organic_order_or_create_revenue` and `::test_sponsored_role_does_not_return_organically_on_a_later_page`.
- Candidate impression is viewport-triggered and deduplicated per candidate/campaign/day; API test `tests/test_promotions.py::test_sponsored_impression_is_eligibility_checked_and_deduplicated_per_day`, plus mobile E2E.
- Event payloads contain only allowlisted campaign/role/action metadata; tests `tests/test_product_events.py::test_sponsored_impression_is_deduplicated_and_payload_rejects_private_data` and `tests/test_promotions.py::test_demo_campaign_is_owned_current_and_lasts_fourteen_days`.
- Demo activation/impressions never produce a real revenue record or nonzero revenue; campaign and response contract keep demo revenue at ₽0 with no billing fields.

---

### Task 1: Add campaign persistence and strict demo activation

**Files:**
- Modify: `backend/models.py`
- Create: `backend/migrations/versions/81c4a62e7f09_role_promotions.py` (revision `81c4a62e7f09`, down-revision `3b9ef2c7d41a`)
- Create: `backend/promotions.py`
- Modify: `backend/schemas.py`
- Modify: `backend/routes_v2.py`
- Create: `tests/test_promotions.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: existing `HiringNeed`, `RoleVersion`, ownership checks and `publish_role` state.
- Produces: `PromotionCampaign` with `id`, `need_id`, `employer_id`, `role_version_id`, `active_from`, `active_until`, `demo_only`; `POST /api/v1/employer/needs/{need_id}/promotion/demo` activates at most one 14-day campaign for an owned, active, discoverable role.

- [x] **Step 1: Add failing tests for unauthorized employer, draft/paused/closed role, wrong owner, duplicate active campaign and 14-day expiry**
- [x] **Step 2: Run focused tests and verify current API has no promotion contract**
- [x] **Step 3: Add the campaign table/migration and transaction-safe activation service**

  Campaign must reference the exact role version. If that version changes, the campaign stops serving until the employer explicitly reactivates it. Do not add payment or price fields.

- [x] **Step 4: Add an event for demo activation with `data_mode` derived from synthetic fixture/app mode and payload allowlisted to campaign ID/role version only**
- [x] **Step 5: Run `/Users/danielbubusan/Desktop/fsp-signal/.venv/bin/python -m pytest tests/test_promotions.py tests/test_product_events.py tests/test_migrations.py -q`; expected: PASS**
- [ ] **Step 6: Commit the campaign activation slice after tests pass** — intentionally not done: this worktree contains other interdependent requested changes; no commit/push requested in this pass.

### Task 2: Return a separate candidate-sponsored section

**Files:**
- Modify: `backend/role_discovery.py`
- Modify: `backend/schemas.py`
- Modify: `backend/routes_v2.py`
- Modify: `backend/product_events.py`
- Modify: `tests/test_role_discovery.py`
- Modify: `tests/test_promotions.py`

**Interfaces:**
- Consumes: Task 1 `PromotionCampaign` service.
- Produces: `RoleFeedOut.sponsored_items` separate from `items`; each sponsored item includes a visible sponsor label, campaign ID, current role version and match explanation. Organic `items` are byte-for-byte logically unchanged by campaign activation.

- [x] **Step 1: Add failing tests that candidate preferences/blocks/hidden decisions are applied before sponsored selection**
- [x] **Step 2: Assert no role appears in both `sponsored_items` and organic `items`; assert sponsored ranking is separate from score and campaign timing**
- [x] **Step 3: Extend the feed service to select only eligible, current, published, discoverable campaigns after hard filters**
- [x] **Step 4: Add privacy-minimal `sponsored_role_impression` and `sponsored_role_decision` events**

  Deduplicate impressions per candidate/campaign/day. Add optional `source_campaign_id` to a save/hide decision; validate that the campaign is active and references that role version. Record only action, campaign, role version and actor metadata; never expose private save/hide events to the employer.
- [x] **Step 5: Run focused role-discovery/promotion/event tests; expected: PASS and no changes in organic ranking fixtures**
- [ ] **Step 6: Commit the sponsored-feed and attribution slice after tests pass** — intentionally not done; see status above.

### Task 3: Add the employer demo control and candidate shelf

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/features/roles/RoleFeed.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/styles.css`
- Create: `frontend/tests/sponsored-roles.spec.ts`

**Interfaces:**
- Consumes: Task 1–2 API contracts and shared `frontend/tests/test-support.ts` helper.
- Produces: employer CTA “Включить продвижение (демо)” with “Демо — без оплаты”; separate candidate shelf labeled “Продвигаемые роли”; no changes to organic match badge or sort order.

- [x] **Step 1: Add failing E2E for activating a campaign, verifying candidate shelf/label, and asserting organic feed remains unchanged**
- [x] **Step 2: Verify preference-incompatible campaigns are excluded in backend contract tests; the compatible candidate-to-campaign flow is covered by mobile E2E**
- [x] **Step 3: Implement controls and empty/loading/error states; avoid a checkout screen or invented price**
- [x] **Step 4: Run typecheck, production build and browser tests; expected: PASS at desktop and mobile width**
- [x] **Step 5: Run full backend and browser suites; implementation verification is complete. Commit is intentionally deferred as noted above and is outside this pass.**
