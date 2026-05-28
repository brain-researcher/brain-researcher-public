from __future__ import annotations

import pytest

from brain_researcher.research.predictive.gates import (
    build_null_diagnosis,
    build_pivot_trigger,
    evaluate_so_what,
)

DEFAULTS = {
    "minimum_interesting_r2": 0.05,
    "so_what_delta_threshold_r2": 0.10,
    "unexpected_winner_margin_r2": 0.01,
    "unexpected_winner_min_r2": 0.02,
    "pipeline_spread_threshold_r2": 0.02,
    "term_signal_range_threshold_r2": 0.01,
}


def _record(
    *,
    target: str = "PicSeq_Unadj",
    backbone: str = "FTTransformerRegressor",
    term_index: int = 17,
    term_name: str = "term17",
    score: float = 0.03,
    run_id: str | None = None,
) -> dict:
    return {
        "run_id": run_id or f"{backbone}-{term_index}-{score}",
        "config": {
            "target": target,
            "backbone": backbone,
            "hyperparameters": {
                "term_index": term_index,
                "term_name": term_name,
            },
        },
        "scores": {"gold_r2": score},
    }


def test_evaluate_so_what_tracks_delta_against_comparator() -> None:
    evaluation = evaluate_so_what(
        {
            "leader_backbone": "FTTransformerRegressor",
            "leader_term_index": 17,
            "leader_score": 0.17,
            "comparator_backbone": "RidgeRegression",
            "comparator_term_index": 40,
            "comparator_score": 0.05,
        },
        DEFAULTS,
    )

    assert evaluation["delta_vs_comparator"] == pytest.approx(0.12)
    assert evaluation["minimum_interesting_r2"] == 0.05
    assert evaluation["pass"] is True


def test_build_null_diagnosis_marks_pipeline_axis_when_shared_term_spread_is_large() -> None:
    diagnosis = build_null_diagnosis(
        [
            _record(backbone="FTTransformerRegressor", term_index=17, score=0.01),
            _record(backbone="GraphTransformerRegressor", term_index=17, score=0.05),
        ],
        {
            "backbone": "GraphTransformerRegressor",
            "best_gold_r2": 0.05,
            "term_index": 17,
            "term_name": "term17",
            "run_id": "leader",
        },
        DEFAULTS,
    )

    assert diagnosis["axis"] == "pipeline"
    assert diagnosis["next_axis_to_change"] == "change_pipeline_axis"
    assert diagnosis["pipeline_spread_term_index"] == 17


def test_build_null_diagnosis_marks_term_axis_when_leader_backbone_varies_by_term() -> None:
    diagnosis = build_null_diagnosis(
        [
            _record(backbone="FTTransformerRegressor", term_index=17, score=0.03),
            _record(backbone="FTTransformerRegressor", term_index=19, score=0.005),
            _record(backbone="RidgeRegression", term_index=21, score=-0.01),
        ],
        {
            "backbone": "FTTransformerRegressor",
            "best_gold_r2": 0.03,
            "term_index": 17,
            "term_name": "term17",
            "run_id": "leader",
        },
        DEFAULTS,
    )

    assert diagnosis["axis"] == "term"
    assert diagnosis["next_axis_to_change"] == "change_term_axis"


def test_build_pivot_trigger_requires_follow_up_for_unexpected_winner() -> None:
    pivot = build_pivot_trigger(
        [
            _record(backbone="FTTransformerRegressor", term_index=17, score=0.031),
            _record(backbone="RidgeRegression", term_index=40, score=0.012),
            _record(backbone="GraphTransformerRegressor", term_index=19, score=0.026),
        ],
        {
            "backbone": "FTTransformerRegressor",
            "best_gold_r2": 0.031,
            "term_index": 17,
            "term_name": "term17",
            "run_id": "leader",
        },
        {
            "backbone": "RidgeRegression",
            "best_gold_r2": 0.012,
            "term_index": 40,
            "term_name": "term40",
            "run_id": "cmp",
        },
        DEFAULTS,
    )

    assert pivot["pass"] is True
    assert pivot["required_next_step"] == "probe_unexpected_winner"
    assert pivot["unexpected_winners"][0]["term_index"] == 17


def test_build_pivot_trigger_broadens_search_without_competitive_signal() -> None:
    pivot = build_pivot_trigger(
        [
            _record(backbone="FTTransformerRegressor", term_index=17, score=0.005),
        ],
        {
            "backbone": "FTTransformerRegressor",
            "best_gold_r2": 0.005,
            "term_index": 17,
            "term_name": "term17",
            "run_id": "leader",
        },
        None,
        DEFAULTS,
    )

    assert pivot == {
        "unexpected_winners": [],
        "required_next_step": "broaden_term_search",
        "pass": False,
    }
