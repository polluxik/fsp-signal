"""Reproducible offline metrics for independently labelled matching results.

The functions deliberately know nothing about the production ranking formula.
Labels must come from a separate review process, never from ``match_v1`` or
``match_v2`` scores.
"""
import math
from collections import Counter
from statistics import mean


def precision_at_k(labels: list[float], k: int = 5, relevant_at: float = 2.0) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    return sum(label >= relevant_at for label in labels[:k]) / k


def ndcg_at_k(ranked_labels: list[float], all_labels: list[float], k: int = 5) -> float | None:
    if k < 1:
        raise ValueError("k must be positive")

    def dcg(values: list[float]) -> float:
        return sum((2 ** value - 1) / math.log2(index + 2)
                   for index, value in enumerate(values[:k]))

    ideal = dcg(sorted(all_labels, reverse=True))
    if ideal == 0:
        return None
    return dcg(ranked_labels) / ideal


def quadratic_weighted_kappa(left: list[int], right: list[int], minimum: int = 0,
                             maximum: int = 3) -> float | None:
    if len(left) != len(right):
        raise ValueError("rater lists must have equal length")
    if not left:
        return None
    if maximum <= minimum:
        raise ValueError("maximum must exceed minimum")
    allowed = set(range(minimum, maximum + 1))
    if any(value not in allowed for value in [*left, *right]):
        raise ValueError("ratings are outside the configured scale")

    size = maximum - minimum + 1
    observed = Counter(zip(left, right))
    left_counts, right_counts = Counter(left), Counter(right)
    total = len(left)
    observed_disagreement = 0.0
    expected_disagreement = 0.0
    denominator = (size - 1) ** 2
    for first in allowed:
        for second in allowed:
            weight = ((first - second) ** 2) / denominator
            observed_disagreement += weight * observed[(first, second)] / total
            expected_disagreement += weight * left_counts[first] * right_counts[second] / (total * total)
    if expected_disagreement == 0:
        return 1.0 if observed_disagreement == 0 else None
    return 1 - observed_disagreement / expected_disagreement


def evaluate_rankings(qrels: dict[str, dict[str, float]], rankings: dict[str, list[str]],
                      k: int = 5) -> dict:
    rows = []
    missing_queries = sorted(set(qrels) - set(rankings))
    unknown_queries = sorted(set(rankings) - set(qrels))
    if missing_queries or unknown_queries:
        raise ValueError({"missing_queries": missing_queries, "unknown_queries": unknown_queries})

    for query_id in sorted(qrels):
        labels = qrels[query_id]
        ranked_ids = rankings[query_id]
        if len(set(ranked_ids)) != len(ranked_ids):
            raise ValueError(f"duplicate candidate in ranking for {query_id}")
        unknown_candidates = sorted(set(ranked_ids) - set(labels))
        if unknown_candidates:
            raise ValueError({"query_id": query_id, "unknown_candidates": unknown_candidates})
        ranked_labels = [labels[candidate_id] for candidate_id in ranked_ids]
        ndcg = ndcg_at_k(ranked_labels, list(labels.values()), k)
        rows.append({
            "query_id": query_id,
            "candidate_count": len(labels),
            "relevant_count": sum(value >= 2 for value in labels.values()),
            f"precision_at_{k}": precision_at_k(ranked_labels, k),
            f"ndcg_at_{k}": ndcg,
        })

    precision_key, ndcg_key = f"precision_at_{k}", f"ndcg_at_{k}"
    ndcg_values = [row[ndcg_key] for row in rows if row[ndcg_key] is not None]
    return {
        "query_count": len(rows),
        "pair_count": sum(row["candidate_count"] for row in rows),
        f"macro_{precision_key}": mean(row[precision_key] for row in rows) if rows else None,
        f"macro_{ndcg_key}": mean(ndcg_values) if ndcg_values else None,
        "queries_without_relevant": [row["query_id"] for row in rows if row["relevant_count"] == 0],
        "queries": rows,
    }
