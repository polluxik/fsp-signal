# Signal product polish: trustworthy matching, useful assistance, and complete UI flows

Date: 7 October 2026. Branch: `codex/signal-product-polish`. Status: approved product direction; implementation has not started. This design extends [Signal v2](2026-10-05-signal-v2-design.md), the [product research](../../research/PRODUCT_RESEARCH.md), and the [FSP product requirements](../../PRODUCT_SPEC.md). The scope is intentionally broader than a visual restyle: it covers user-facing contracts, backend validation, tests, and live browser verification.

## 1. Product direction

Improve the existing reverse-hiring product around one outcome: the candidate can quickly understand a real, relevant opportunity and decide whether to share contact details; the employer can make a clear offer from evidence that is honestly described. Every new feature must shorten or improve this path, not merely add another screen.

Preserve the existing purple brand and the core consent boundary. Contacts remain hidden until the candidate accepts a specific invitation. Candidate assessment, match quality, source provenance, and unknown information remain distinct concepts. Do not claim predicted hiring success or verified competence without an actual reviewed verification process.

### Considered directions

1. A swipe-first marketplace with AI ranking and paid boosts is rejected as the product's core: it can make browsing feel fast but does not repair trust, eligibility, role quality, or the hand-off to an interview; paid ranking would also undermine the relevance promise.
2. A conversational AI as the whole product is rejected: it adds latency and data-handling risk while leaving the user with the same opaque results.
3. **Recommended: evidence-first reverse hiring with optional, bounded assistants.** Keep matching and consent deterministic and explainable; use AI only to turn user-provided text into an editable, reviewable draft; make any paid exposure visibly separate from organic relevance.

## 2. Scope and workstreams

### 2.1. Repair the core journeys

Audit and fix the current candidate and employer journeys, including:

- Correctly retain/render invitation compatibility after a candidate opens it; never overwrite a valid report with a null response.
- Keep structured private preferences and the profile form on one current source of truth so saving one cannot silently restore stale values from the other.
- Make first-time company setup actionable when role creation requires a company profile.
- Ensure invitations, statuses, loading, empty, errors, expiry, withdrawal, accept/reject and contact disclosure remain coherent across refresh and role changes.
- Make hide/undo behavior reliable for multiple decisions, and do not show unverified or unknown-source profiles as “verified.”
- Distinguish fit, assessment result, evidence coverage, source and unknown/missing competencies. A numeric score is not a probability of hiring.
- Review the active matching algorithm default. Use the neutral, non-FSP-bonus version for relevance and sponsored-placement demonstrations unless a separately reviewed product decision says otherwise; preserve historical scoring behavior for old records.

The audit will include every visible navigation destination, primary/secondary action, form validation, modal, menu and role-specific empty/error state discovered in the running app. Findings will be converted into regression tests; no promise of “all bugs” will be made without a bounded tested surface.

### 2.2. Add QA and Data Analyst taxonomy safely

Support `backend`, `frontend`, `qa`, and `data_analyst`, each at `junior` and `middle`, subject to a reviewed assessment blueprint for that exact specialization/grade pair. Use stable IDs, labels, competency IDs, competency labels, availability and a pair-specific blueprint version from one backend catalog. Candidate assessments, role creation/editing, employer search and candidate-feed filters consume the same catalog instead of maintaining divergent hard-coded lists.

QA and Data Analyst blueprints require role-specific tasks, rubrics, deterministic scoring/variants, competency thresholds and evidence generation. The system must not fall through to the Frontend Middle assessment for an unknown pair. Unsupported or not-yet-reviewed pairs are not offered as verified assessments. Tests must cover all eight pairs and preserve grading/evidence for existing blueprint versions.

Expand the existing 48 synthetic candidate records to 72 by adding 12 synthetic profiles for each new category, with matching synthetic roles as needed for an end-to-end demo. Synthetic identities and evidence must be visibly and consistently marked; never imply that these are real or independently verified people. Preserve the current single active verified category and cooldown contract; do not imply simultaneous credentials across tracks.

### 2.3. Add bounded AI-assisted drafting

Use the already supplied `https://gateway.frontierai.ru/v1/chat/completions` endpoint and `qwen3.8-27b-4a100` model only from the backend. The API key is read from server configuration; it must not be put in source, frontend bundles, committed `.env` files, logs, test snapshots or user-visible errors. Provider integration uses the existing HTTP client dependency, bounded timeouts, request-size/token limits, per-user rate limits and redacted observability. If configuration/provider is missing, timed out or returns invalid data, retain a usable deterministic/manual flow.

Provide three explicit draft intents:

1. Candidate preference note → typed, allowlisted preference proposal. Show proposed values and ambiguity/unknowns; candidate edits and explicitly saves through the existing version-checked preference update. Hard preferences continue to act as eligibility filters, not a hidden AI score.
2. Candidate achievement note → a longer, editable evidence story covering context, the candidate's own contribution and decisions, outcome, and evidence basis. Ask only focused follow-ups for missing facts. Never invent metrics, tools, ownership or outcomes. Keep claims traceable to what the candidate supplied and mark unsupported fields as missing. Do not submit this story to employer-visible profile until candidate reviews and confirms it.
3. Employer role brief → a structured, editable draft that surfaces missing salary, format/location, responsibilities, expected first outcome, interview stages and take-home expectations. Employer confirms before creating/publishing the role. Do not fabricate company culture or benefits.

Before each provider transmission, disclose that the text will be sent to the configured external AI provider and require a deliberate send action. Send only the text for that intent; do not attach names, emails, contact details, stored resumes, assessment results, private preferences, full profiles or other conversation history. Never call the model for candidate scoring, selection, eligibility or ranking. Treat user input and model output as untrusted; validate a strict schema and reject out-of-range/unrecognized fields. Do not persist raw provider prompts/responses or log personal text. Preference GET/PUT responses must be `no-store`; apply request rate and size limits. All AI outputs remain drafts until human confirmation.

Tests use a stubbed provider and synthetic content. A live provider smoke test is optional, server-side only and limited to synthetic text; perform it only within an explicitly agreed cost ceiling. No real candidate data is sent in this implementation task.

### 2.4. Demonstrate monetization without corrupting relevance

There is no billing provider or current promotion contract. Add a demo-only employer promotion workflow for a published/current role, clearly labeled “Демо — без оплаты.” Show promoted opportunities in a separate sponsored section. Apply candidate hard eligibility and preferences before exposure; do not change match score, organic order, candidate ranking or who can receive an invitation. Label sponsored exposure separately from match quality and ordinary impressions. No checkout, charge, fabricated revenue or claim of validated willingness to pay.

Record/measure the demo funnel separately: campaign viewed/activated, eligible sponsored impression, candidate save/hide, invitation sent/accepted, and interview held if both parties confirm it. Demo revenue is always ₽0. Real revenue in future reporting requires confirmed successful payment net of refunds. Candidate access remains free. A B2B curated sourcing pilot remains a separate post-liquidity hypothesis, not a validated price or current feature.

## 3. UX and interaction requirements

- Preserve the existing purple brand, visual hierarchy and useful content; restyle only components that demonstrably reduce clarity or usability. Avoid broad redesign for novelty.
- Give each screen a clear primary action and make button labels describe the outcome. Make all interactive controls work with pointer, touch and keyboard, with visible focus and accessible names.
- Cover responsive layouts at narrow/mobile and desktop sizes, including long labels, validation, content overflow, dialogs and sticky controls.
- Use brief transitions only to clarify state changes; respect `prefers-reduced-motion`. Avoid animation on repeated/high-frequency interactions and never delay an action for decoration.
- Keep loaders informative, provide retry/cancel where safe, and prevent duplicate submits. Measure slow routes and expensive UI work before optimizing; prefer fewer requests/parallel independent reads, pagination/cancellation and stable rendering over speculative caching.
- Replace or style scrollbars only if the live UI demonstrates a real visual/interaction defect. Preserve platform scrolling, keyboard behavior and visible affordance; do not hide scrollbars or use a narrow low-contrast thumb.
- Preserve clear loading, error, empty, success, disabled and stale/conflict states. Forms should retain user input on recoverable errors and associate field errors with the relevant controls.

## 4. Success criteria and evidence

These are implementation acceptance criteria, not validated business claims:

- A candidate preference edit followed by a profile edit cannot silently restore stale private preferences; version conflicts are explicit and recoverable.
- Opening an invitation retains a valid compatibility report; contacts remain hidden until acceptance and appear only to the accepting employer.
- All 8 specialization/grade pairs have deterministic, category-correct assessment generation, validation, scoring, evidence and matching contracts; old blueprint attempts still work.
- Seed has the expected explicitly synthetic candidate/category counts and at least one matching demo role per supported pair.
- AI provider stubs verify consent gate, data minimization, schema rejection, timeout/fallback, rate/size limits, no-store and no automatic save; saved values reflect only the user's confirmed draft.
- Sponsored roles never bypass preferences/eligibility and never alter organic fit or ranking; exposure and demo revenue are labeled separately.
- Main navigation, role screens, forms and critical state transitions are covered by API/unit tests and browser tests for candidate and employer. Critical flows pass at desktop and mobile viewport sizes with no console errors, uncaught requests, dead buttons, keyboard traps or horizontal overflow.
- Browser verification walks every available section and control, including back/refresh/reload, invalid input, empty result, loading/error retry, and candidate/employer state hand-off. The verification report names the paths/viewports actually checked and lists any remaining gaps.
- Build, type checking, full backend tests, frontend tests, browser suite and PostgreSQL Compose smoke pass. PostgreSQL-only behavior is not considered verified by SQLite tests.
- For UX/performance changes, capture before/after evidence where feasible: bundle/build output, route/interaction timing or repeated browser trace. No arbitrary “faster” claim without a measurement.

Business metrics to instrument as hypotheses: eligible opportunities seen per active opted-in candidate; preference completion; invitation response/acceptance; confirmed held interviews; employer time-to-shortlist; repeat employer role/pilot. Matching evaluation remains independently labeled Precision@5/nDCG@5; demo activity and synthetic profiles are excluded from real user/business outcomes.

## 5. Privacy, fairness and failure boundaries

- No paid-to-rank candidates or pay-to-pass assessments. Sponsored roles are separately disclosed and preference-gated.
- No employer contact disclosure without candidate acceptance; no candidate PII in employer search before the relevant consent boundary.
- AI may structure text, but cannot invent candidate facts, decide employability, assign grades, change eligibility or affect ranking.
- Never identify synthetic records as real, verified or hired; never report demo impressions as revenue or interviews as held without confirmation.
- Store only confirmed user edits. Keep provider credentials in runtime secret configuration; rotate the previously shared temporary token after the integration test, and keep it out of this repository.
- Existing data and API contracts should be migrated additively. Preserve old assessment and match versions; document any intentional default change and regression-test it.

## 6. Implementation sequence (design-level; detailed plan follows review)

1. Baseline and coverage map: inventory routes, buttons and user roles; run existing test/build baselines on the isolated worktree; create a synthetic local database and dedicated worktree ports.
2. Write regression tests for verified journey defects, then repair those contracts and add browser coverage.
3. Add a reviewed, versioned taxonomy/assessment registry and QA/Data Analyst blueprints; expand synthetic fixtures and complete end-to-end category coverage.
4. Add server-side typed AI draft adapter and its UI, beginning with mocked provider tests; add achievement and vacancy draft intents with explicit per-send disclosure and confirmation.
5. Add demo-only sponsored role workflow and event separation; verify it cannot affect matching or eligibility.
6. Perform UI polish and live browser audit across candidate/employer sections, desktop/mobile, keyboard and reduced motion; optimize only measured slow paths; run full SQLite and PostgreSQL verification and fix regressions.

Implementation order may be adjusted only if the detailed plan identifies a dependency or test risk; do not drop core-flow regression coverage to make room for polish.

## 7. Explicit non-goals

- Production payments, a billing processor, or claims of real commercial validation.
- Candidate paid boosts, paid verification or paid assessment results.
- Autonomous applications/messages, hidden AI decision-making or AI-generated unreviewed profile/vacancy publication.
- New assessment categories without category-specific reviewed tasks/rubrics.
- A wholesale visual rewrite, decorative animation, hidden scrollbars, or added UI dependencies without evidence.
- Sending real candidate or employer data to the external model during local tests.
