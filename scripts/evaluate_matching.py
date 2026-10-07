#!/usr/bin/env python3
"""Score saved rankings against independently authored relevance labels."""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.evaluation import evaluate_rankings, quadratic_weighted_kappa


def load_qrels(path: Path, split: str) -> tuple[dict[str, dict[str, float]], dict[str, list[int]]]:
    ratings: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_rater: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if row["split"] != split:
                continue
            label = int(row["label"])
            if label not in (0, 1, 2, 3):
                raise ValueError(f"label must be 0..3: {row}")
            key = (row["query_id"], row["candidate_id"])
            if key in by_rater[row["rater"]]:
                raise ValueError(f"duplicate rater label: {row}")
            ratings[key].append(label)
            by_rater[row["rater"]][key] = label
    qrels: dict[str, dict[str, float]] = defaultdict(dict)
    for (query_id, candidate_id), labels in ratings.items():
        qrels[query_id][candidate_id] = mean(labels)

    raters = sorted(by_rater)
    agreement: dict[str, list[int]] = {}
    if len(raters) == 2:
        shared = sorted(set(by_rater[raters[0]]) & set(by_rater[raters[1]]))
        agreement = {
            "left": [by_rater[raters[0]][key] for key in shared],
            "right": [by_rater[raters[1]][key] for key in shared],
        }
    return dict(qrels), agreement


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--rankings", type=Path, required=True)
    parser.add_argument("--split", default="holdout")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    qrels, agreement = load_qrels(args.qrels, args.split)
    rankings = json.loads(args.rankings.read_text(encoding="utf-8"))
    report = {
        "split": args.split,
        "k": args.k,
        "rater_pair_count": len(agreement.get("left", [])),
        "quadratic_weighted_kappa": (
            quadratic_weighted_kappa(agreement["left"], agreement["right"])
            if agreement else None
        ),
        "algorithms": {
            name: evaluate_rankings(qrels, algorithm_rankings, args.k)
            for name, algorithm_rankings in rankings.items()
        },
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
