#!/usr/bin/env python3
"""Generate deterministic synthetic test-retest results for assessment mechanics."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.assessment_validation import render_markdown, simulate_all


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles-per-group", type=int, default=20)
    parser.add_argument("--json-output", type=Path,
                        default=ROOT / "docs/validation/assessment-synthetic-results.json")
    parser.add_argument("--markdown-output", type=Path,
                        default=ROOT / "docs/validation/assessment-synthetic-results.md")
    args = parser.parse_args()
    if args.profiles_per_group < 2:
        parser.error("--profiles-per-group must be at least 2")
    report = simulate_all(args.profiles_per_group)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(f"Synthetic assessment report: {args.markdown_output}")


if __name__ == "__main__":
    main()
