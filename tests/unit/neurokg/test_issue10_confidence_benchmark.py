import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "neurokg" / "issue10_confidence_benchmark.py"
SPEC = importlib.util.spec_from_file_location(
    "issue10_confidence_benchmark", MODULE_PATH
)
BENCH = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = BENCH
SPEC.loader.exec_module(BENCH)


def _case(
    case_id: str,
    *,
    v1: float = 0.6,
    v2: float = 0.6,
    contradiction_density: float = 0.0,
    uncertainty_density: float = 0.0,
    n_evidence: int = 6,
    support_count: int = 1,
    conflict_count: int = 0,
    uncertain_count: int = 0,
    focus_bucket: str = "baseline",
) -> BENCH.ScoredCase:
    return BENCH.ScoredCase(
        case_id=case_id,
        confidence_v1=v1,
        confidence_v2=v2,
        delta_v2_minus_v1=round(v2 - v1, 4),
        contradiction_density=contradiction_density,
        uncertainty_density=uncertainty_density,
        n_evidence=n_evidence,
        silver_label="supported_proxy",
        predicted_label="supported_proxy",
        support_count=support_count,
        conflict_count=conflict_count,
        uncertain_count=uncertain_count,
        focus_bucket=focus_bucket,
    )


def test_stratified_targeted_sample_prefers_conflict_then_uncertainty():
    scored = [
        _case(
            "conflict-1",
            contradiction_density=0.9,
            uncertainty_density=0.2,
            support_count=2,
            conflict_count=2,
            uncertain_count=0,
        ),
        _case(
            "conflict-2",
            contradiction_density=0.8,
            uncertainty_density=0.2,
            support_count=2,
            conflict_count=2,
            uncertain_count=0,
        ),
        _case(
            "uncertain-1",
            contradiction_density=0.0,
            uncertainty_density=0.9,
            support_count=1,
            conflict_count=0,
            uncertain_count=3,
        ),
        _case(
            "uncertain-2",
            contradiction_density=0.0,
            uncertainty_density=0.8,
            support_count=1,
            conflict_count=0,
            uncertain_count=3,
        ),
        _case(
            "baseline-1",
            v2=0.85,
            support_count=1,
            conflict_count=0,
            uncertain_count=0,
        ),
        _case(
            "baseline-2",
            v2=0.83,
            support_count=1,
            conflict_count=0,
            uncertain_count=0,
        ),
    ]

    sampled, stats = BENCH.stratified_targeted_sample(
        scored,
        target_conflict_cases=2,
        target_uncertainty_cases=2,
        target_baseline_cases=2,
    )

    assert len(sampled) == 6
    assert stats["selected_conflict_cases"] == 2
    assert stats["selected_uncertainty_cases"] == 2
    assert stats["selected_baseline_cases"] == 2
    assert stats["available_baseline_cases"] == 4


def test_summarize_reports_denominators_and_uncertain_only_metric():
    cases = [
        _case(
            "a", v1=0.8, v2=0.82, support_count=1, conflict_count=0, uncertain_count=0
        ),
        _case(
            "b",
            v1=0.75,
            v2=0.4,
            support_count=0,
            conflict_count=0,
            uncertain_count=3,
            uncertainty_density=1.0,
        ),
        _case(
            "c",
            v1=0.72,
            v2=0.2,
            support_count=1,
            conflict_count=1,
            uncertain_count=1,
            contradiction_density=0.8,
            uncertainty_density=0.4,
            focus_bucket="conflict",
        ),
    ]
    summary = BENCH.summarize(cases, high_conf_threshold=0.7, sample_stats={})
    assert summary["n_high_conf_v1"] == 3
    assert summary["n_high_conf_v2"] == 1
    assert summary["n_top_decile"] >= 1
    assert summary["median_confidence_v2_uncertain_only"] == 0.4
    assert summary["n_uncertain_only"] == 1


def test_threshold_gate_fails_on_positive_conflict_delta():
    summary_sampled = {
        "median_delta_sampled_conflict_bucket": 0.05,
        "median_delta_sampled_uncertainty_bucket": -0.01,
        "median_confidence_v2_uncertain_only": 0.01,
        "median_delta_sampled_baseline_bucket": 0.1,
        "high_conf_precision_v1": 0.9,
        "high_conf_precision_v2": 0.9,
        "n_high_conf_v1": 10,
        "n_high_conf_v2": 10,
        "top_decile_precision_v1": 0.9,
        "top_decile_precision_v2": 0.9,
        "n_top_decile": 20,
    }
    sample_stats = {
        "selected_conflict_cases": 120,
        "selected_uncertainty_cases": 120,
        "selected_baseline_cases": 200,
    }
    independent_eval = {
        "status": "ok",
        "n_cases": 8,
        "independent_accuracy_v1": 0.5,
        "independent_accuracy_v2": 0.6,
        "independent_non_supported_high_conf_rate_v1": 0.5,
        "independent_non_supported_high_conf_rate_v2": 0.4,
    }
    thresholds = BENCH.evaluate_thresholds(
        profile="issue10_strong",
        summary_sampled=summary_sampled,
        sample_stats=sample_stats,
        independent_eval=independent_eval,
        target_conflict_cases=120,
        target_uncertainty_cases=120,
        target_baseline_cases=200,
    )
    assert thresholds["passed"] is False
    by_name = {item["name"]: item for item in thresholds["checks"]}
    assert by_name["effect_conflict_delta"]["passed"] is False


def test_threshold_gate_passes_on_target_metrics():
    summary_sampled = {
        "median_delta_sampled_conflict_bucket": -0.04,
        "median_delta_sampled_uncertainty_bucket": -0.01,
        "median_confidence_v2_uncertain_only": 0.01,
        "median_delta_sampled_baseline_bucket": 0.08,
        "high_conf_precision_v1": 0.92,
        "high_conf_precision_v2": 0.91,
        "n_high_conf_v1": 10,
        "n_high_conf_v2": 11,
        "top_decile_precision_v1": 0.9,
        "top_decile_precision_v2": 0.9,
        "n_top_decile": 20,
    }
    sample_stats = {
        "selected_conflict_cases": 120,
        "selected_uncertainty_cases": 120,
        "selected_baseline_cases": 200,
    }
    independent_eval = {
        "status": "ok",
        "n_cases": 8,
        "independent_accuracy_v1": 0.62,
        "independent_accuracy_v2": 0.66,
        "independent_non_supported_high_conf_rate_v1": 0.50,
        "independent_non_supported_high_conf_rate_v2": 0.40,
    }
    thresholds = BENCH.evaluate_thresholds(
        profile="issue10_strong",
        summary_sampled=summary_sampled,
        sample_stats=sample_stats,
        independent_eval=independent_eval,
        target_conflict_cases=120,
        target_uncertainty_cases=120,
        target_baseline_cases=200,
    )
    assert thresholds["passed"] is True


def test_threshold_gate_fails_when_v2_has_no_high_confidence_outputs():
    summary_sampled = {
        "median_delta_sampled_conflict_bucket": -0.04,
        "median_delta_sampled_uncertainty_bucket": -0.01,
        "median_confidence_v2_uncertain_only": 0.01,
        "n_uncertain_only": 10,
        "median_delta_sampled_baseline_bucket": 0.08,
        "high_conf_precision_v1": 0.92,
        "high_conf_precision_v2": None,
        "n_high_conf_v1": 10,
        "n_high_conf_v2": 0,
        "top_decile_precision_v1": 0.9,
        "top_decile_precision_v2": 0.9,
        "n_top_decile": 20,
    }
    sample_stats = {
        "selected_conflict_cases": 120,
        "selected_uncertainty_cases": 120,
        "selected_baseline_cases": 200,
    }
    independent_eval = {
        "status": "ok",
        "n_cases": 8,
        "independent_accuracy_v1": 0.62,
        "independent_accuracy_v2": 0.66,
        "independent_non_supported_high_conf_rate_v1": 0.5,
        "independent_non_supported_high_conf_rate_v2": 0.4,
    }
    thresholds = BENCH.evaluate_thresholds(
        profile="issue10_strong",
        summary_sampled=summary_sampled,
        sample_stats=sample_stats,
        independent_eval=independent_eval,
        target_conflict_cases=120,
        target_uncertainty_cases=120,
        target_baseline_cases=200,
    )
    by_name = {item["name"]: item for item in thresholds["checks"]}
    assert by_name["stability_high_conf_precision"]["passed"] is False
    assert thresholds["passed"] is False


def test_threshold_gate_handles_zero_non_supported_rate_baseline():
    summary_sampled = {
        "median_delta_sampled_conflict_bucket": -0.04,
        "median_delta_sampled_uncertainty_bucket": -0.01,
        "median_confidence_v2_uncertain_only": 0.01,
        "n_uncertain_only": 5,
        "median_delta_sampled_baseline_bucket": 0.08,
        "high_conf_precision_v1": 0.92,
        "high_conf_precision_v2": 0.91,
        "n_high_conf_v1": 10,
        "n_high_conf_v2": 10,
        "top_decile_precision_v1": 0.9,
        "top_decile_precision_v2": 0.9,
        "n_top_decile": 20,
    }
    sample_stats = {
        "selected_conflict_cases": 120,
        "selected_uncertainty_cases": 120,
        "selected_baseline_cases": 200,
    }
    independent_eval = {
        "status": "ok",
        "n_cases": 8,
        "independent_accuracy_v1": 0.8,
        "independent_accuracy_v2": 0.8,
        "independent_non_supported_high_conf_rate_v1": 0.0,
        "independent_non_supported_high_conf_rate_v2": 0.0,
    }
    thresholds = BENCH.evaluate_thresholds(
        profile="issue10_strong",
        summary_sampled=summary_sampled,
        sample_stats=sample_stats,
        independent_eval=independent_eval,
        target_conflict_cases=120,
        target_uncertainty_cases=120,
        target_baseline_cases=200,
    )
    by_name = {item["name"]: item for item in thresholds["checks"]}
    assert by_name["independent_non_supported_high_conf_rate"]["passed"] is True
