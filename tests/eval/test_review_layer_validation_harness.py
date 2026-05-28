"""Regression tests for review-layer validation mutation harness."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "review_layer_validation_harness.py"
SPEC = importlib.util.spec_from_file_location("review_layer_validation_harness", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def _manifest() -> dict:
    return {
        "run_sets": {
            "control_60": [
                {
                    "run_id": "br_control_1",
                    "route": "tool_execute",
                    "primary_tool": "run_fitlins_recipe",
                },
                {
                    "run_id": "br_control_2",
                    "route": "pipeline_execute",
                    "primary_tool": "workflow_rest_connectome_e2e",
                },
            ],
            "mutation_base_20": [
                {
                    "run_id": "br_mutation_1",
                    "route": "tool_execute",
                    "primary_tool": "run_fitlins_recipe",
                }
            ],
            "natural_bad_12": [
                {
                    "run_id": "br_bad_1",
                    "code_review_decision": "block",
                    "scientific_review_overall": None,
                    "code_review_rule_ids": ["REVIEW_STEP_SUCCESS_RATE_LOW"],
                }
            ],
        },
        "fault_injection_families": [
            {
                "family_id": "design_matrix_rank",
                "label": "rank failure",
                "target_level": "L1_deterministic",
                "expected_rule_ids": ["DESIGN_MATRIX_RANK"],
            },
            {
                "family_id": "cv_split_leakage",
                "label": "CV leakage",
                "target_level": "L1_deterministic",
                "expected_rule_ids": ["PREDICTIVE_CV_LEAKAGE"],
            },
        ],
    }


def test_build_validation_cases_uses_manifest_sets() -> None:
    cases = harness.build_validation_cases(_manifest())

    assert [case["case_type"] for case in cases].count("control") == 2
    assert [case["case_type"] for case in cases].count("mutation") == 2
    assert [case["case_type"] for case in cases].count("natural_bad_regression") == 1
    assert cases[2]["family_id"] == "design_matrix_rank"
    assert cases[2]["expected_rule_ids"] == [
        "REVIEW_DESIGN_MATRIX_RANK_DEFICIENT",
        "REVIEW_CONTRAST_NOT_ESTIMABLE",
    ]


def test_clean_controls_have_no_findings_and_mutations_are_caught() -> None:
    cases = harness.build_validation_cases(_manifest())
    results = [harness.evaluate_case(case) for case in cases]
    by_id = {result["case_id"]: result for result in results}

    assert by_id["control_001"]["actual_rule_ids"] == []
    assert by_id["control_001"]["false_positive"] is False
    assert "REVIEW_DESIGN_MATRIX_RANK_DEFICIENT" in by_id[
        "design_matrix_rank_001"
    ]["actual_rule_ids"]
    assert "REVIEW_PREDICTIVE_CV_LEAKAGE" in by_id["cv_split_leakage_001"][
        "actual_rule_ids"
    ]
    assert by_id["natural_bad_001"]["caught"] is True

    summary = harness.summarize_results(results)
    assert summary["control_false_positive_rate"] == 0.0
    assert summary["control_specificity"] == 1.0
    assert summary["mutation_sensitivity"] == 1.0
    assert summary["level_metrics"]["L1_deterministic"]["catch_rate"] == 1.0
    assert summary["natural_bad_manifest_catch_rate"] == 1.0


def test_all_default_manifest_mutations_are_caught() -> None:
    manifest = {
        "run_sets": {
            "control_60": [],
            "mutation_base_20": [
                {
                    "run_id": "br_mutation_1",
                    "route": "tool_execute",
                    "primary_tool": "run_fitlins_recipe",
                }
            ],
            "natural_bad_12": [],
        },
        "fault_injection_families": [
            {"family_id": family_id, "label": family_id}
            for family_id in harness.MUTATIONS
        ],
    }

    results = [harness.evaluate_case(case) for case in harness.build_validation_cases(manifest)]

    assert results
    assert all(result["caught"] for result in results)
