from __future__ import annotations

from brain_researcher.core.contracts import AnalysisBundleV1, RunCardV1
from brain_researcher.core.contracts.loop_signals import (
    ConditionTagSignalV1,
    build_cross_stage_context,
    coerce_cross_stage_context,
    parse_loop_signals,
)


def test_parse_loop_signals_filters_invalid_rows():
    signals = parse_loop_signals(
        [
            {
                "schema_version": "loop-signal-v1",
                "signal_type": "condition_tag",
                "stage": "R1",
                "condition_key": "modality",
                "condition_value": "fmri",
            },
            {"signal_type": "unknown_type"},
            "not-a-dict",
        ]
    )
    assert len(signals) == 1
    assert signals[0].signal_type == "condition_tag"


def test_coerce_cross_stage_context_from_legacy_shape():
    ctx = coerce_cross_stage_context(
        {
            "task_family": "glm",
            "condition_tags": [
                {"key": "task", "value": "motor", "conclusion": "stable effect"}
            ],
            "sensitivity_findings": [
                {"axis": "hrf_model", "eta_squared": 0.42, "recommended_action": "report multi-HRF"}
            ],
        }
    )
    assert ctx is not None
    assert ctx.task_family == "glm"
    assert ctx.condition_constraints[0].condition_key == "task"
    assert ctx.sensitivity_constraints[0].analysis_axis == "hrf_model"


def test_build_cross_stage_context_from_signals():
    signal = ConditionTagSignalV1(
        stage="R1",
        condition_key="population",
        condition_value="healthy_adults",
        conclusion="agreement",
    )
    ctx = build_cross_stage_context(
        task_family="connectome",
        dataset_id="ds:openneuro:ds000001",
        predicted_intents=["connectome"],
        query_understanding=None,
        loop_signals=[signal],
    )
    assert ctx.task_family == "connectome"
    assert ctx.dataset_id == "ds:openneuro:ds000001"
    assert ctx.predicted_intents == ["connectome"]
    assert ctx.condition_constraints[0].condition_key == "population"


def test_run_card_and_analysis_bundle_adapters_backfill_loop_fields():
    run_card = RunCardV1(
        id="job-1",
        cross_stage_context={"task_family": "glm"},
        loop_signals=[
            {
                "signal_type": "condition_tag",
                "stage": "R1",
                "condition_key": "modality",
                "condition_value": "fmri",
            }
        ],
    )
    assert run_card.cross_stage_context is not None
    assert run_card.loop_signals
    assert run_card.loop_signals[0].signal_type == "condition_tag"

    bundle = AnalysisBundleV1(
        generated_at="2026-02-17T00:00:00Z",
        run_card=run_card.model_dump(mode="json"),
    )
    assert bundle.cross_stage_context is not None
    assert bundle.loop_signals
    assert bundle.loop_signals[0].signal_type == "condition_tag"

