import pytest

from backend.evaluation import (evaluate_rankings, ndcg_at_k, precision_at_k,
                                quadratic_weighted_kappa)


def test_precision_uses_fixed_k_denominator():
    assert precision_at_k([3, 2, 1], k=5) == 0.4


def test_ndcg_uses_complete_label_pool_for_ideal_order():
    best = ndcg_at_k([3, 2, 1], [0, 1, 2, 3], k=3)
    worse = ndcg_at_k([1, 3, 2], [0, 1, 2, 3], k=3)
    assert best == pytest.approx(1.0)
    assert worse < best
    assert ndcg_at_k([0, 0], [0, 0], k=5) is None


def test_weighted_kappa_handles_agreement_and_disagreement():
    assert quadratic_weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0
    assert quadratic_weighted_kappa([0, 0, 3, 3], [3, 3, 0, 0]) < 0


def test_evaluate_rankings_rejects_partial_or_unknown_inputs():
    qrels = {"q1": {"a": 3, "b": 1}, "q2": {"c": 2}}
    with pytest.raises(ValueError, match="missing_queries"):
        evaluate_rankings(qrels, {"q1": ["a", "b"]})
    with pytest.raises(ValueError, match="unknown_candidates"):
        evaluate_rankings({"q1": {"a": 3}}, {"q1": ["missing"]})


def test_evaluate_rankings_reports_queries_without_relevant_candidates():
    report = evaluate_rankings(
        {"q1": {"a": 3, "b": 1}, "q2": {"c": 1}},
        {"q1": ["a", "b"], "q2": ["c"]},
    )
    assert report["query_count"] == 2
    assert report["pair_count"] == 3
    assert report["queries_without_relevant"] == ["q2"]
