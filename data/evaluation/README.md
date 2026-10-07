# Matching evaluation data

`qrels.template.csv` and `rankings.template.json` demonstrate the file contract only. They are not product results.

For a real run, copy the templates to owned result files and collect labels independently from the ranking implementation. Each query should use the complete eligible candidate pool. Two reviewers assign 0–3 relevance labels without seeing algorithm score, rank, FSP result or the other reviewer's label.

Run:

```bash
python scripts/evaluate_matching.py \
  --qrels data/evaluation/qrels.csv \
  --rankings data/evaluation/rankings.json \
  --split holdout \
  --output docs/validation/v2-results.json
```

Do not commit personal data. Synthetic and voluntary real-user evaluations must be stored and reported separately.
