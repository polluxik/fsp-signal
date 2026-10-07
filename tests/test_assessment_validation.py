from backend.assessment import COMPETENCIES
from backend.assessment_validation import render_markdown, simulate_all, simulate_category


def test_synthetic_assessment_simulation_is_deterministic_and_complete():
    first = simulate_all(profiles_per_group=3)
    second = simulate_all(profiles_per_group=3)
    assert first == second
    assert {item["category"] for item in first["categories"]} == set(COMPETENCIES)
    assert first["status"] == "synthetic_mechanics_only"
    assert all(item["profiles"] == 9 for item in first["categories"])
    assert "не человеческая калибровка" in render_markdown(first).lower()


def test_synthetic_category_metrics_are_bounded_and_separate_profiles():
    result = simulate_category("backend:middle", profiles_per_group=20)
    for key in ("pass_fail_agreement", "threshold_crossing_rate",
                "spearman_score_correlation", "strong_minus_weak_pass_rate"):
        assert -1 <= result[key] <= 1
    assert result["strong_minus_weak_mean_score"] >= 30
    assert result["groups"]["strong"]["mean_score"] > result["groups"]["boundary"]["mean_score"]
    assert result["groups"]["boundary"]["mean_score"] > result["groups"]["weak"]["mean_score"]
