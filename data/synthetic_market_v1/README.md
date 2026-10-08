# Synthetic IT market dataset v1

This package contains original, fully synthetic Russian-language candidate CVs and vacancies for product demos and matching experiments. It is a data artifact only: it does not change the application, API, matcher, or UI.

## Contents

- `profiles.jsonl` — 200 structured CVs, one JSON object per line.
- `vacancies.jsonl` — 120 structured vacancies, one JSON object per line.
- `taxonomy.json` — 32 role families, Russian/English labels, aliases, subtypes, and canonical skill vocabulary (`it_roles_v1`).
- `profiles.csv` and `vacancies.csv` — spreadsheet-friendly views; nested fields remain JSON-encoded in their cells.
- `quality_report.json` — generated counts, coverage, and diversity checks.
- `generate_market.py` — deterministic generator and validation rules; no network or model calls.

## Coverage and interpretation

All 32 role families in the approved specification are covered. Every family has at least five profiles and three or four vacancies. The 200 profiles cover four self-declared levels with 50 profiles per level; the 120 demo vacancies have 30 roles per level. They use eight career-path patterns and varied histories, projects, education, language and certificate sections. Empty optional sections are explicitly marked `unknown`; they do not mean the candidate lacks that experience.

Candidate levels are self-described and intentionally not derived from experience duration. Every profile is marked `synthetic`, `synthetic_fixture`, and `not_assessed`; listed skills and outcomes are claims inside fictional examples, not verified evidence. Example outcomes and salary ranges are illustrative, not labor-market estimates, measured results, or hiring-quality labels. No profile contains a real person's name, email, phone, or source CV text. Fictional employer labels are not real companies and have no contact details.

Some achievement stories include a numeric illustration to make the narrative shape concrete. Each such value is explicitly marked as invented demo data, not a real measurement; the rest use qualitative outcomes.

Vacancies include family/subtype/level, responsibilities, expected results, required and preferred skills, stack, monthly gross salary range, work format and location when relevant, a first-30-days outline, interview stages, response SLA, and synthetic provenance. Their `active` and `discoverable_demo` fields mean active only inside a demo seed; they are not live openings.

The source documents supplied by the user were not read or used as content, and no public resume or vacancy prose was copied. Dataset/license research is documented separately in `docs/research/RESUME_DATASET_REVIEW.md`; that review informed scope only, not the wording of these records.

## Rebuild and validation

From the repository root:

```sh
python data/synthetic_market_v1/generate_market.py
```

The fixed seed is `20261008`, so output IDs, ordering, and content are stable. The generator asserts exact totals, all-family coverage, at least five profiles per family, three-to-four vacancies per family, 25+ profiles per level, diverse career/completeness patterns, unique candidate narratives and vacancy texts, valid salary/chronology, synthetic provenance, and contact-free records.

Before using the dataset in a product demo, keep the `synthetic`/`not_assessed` markers visible. Do not use these fixtures as evidence that the matcher is accurate on real candidates or that the salary ranges reflect the market.
