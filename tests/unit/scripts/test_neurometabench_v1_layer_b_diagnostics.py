from __future__ import annotations

from scripts.neurometabench_v1 import derive_layer_b_diagnostics as module


def _row(**overrides: str) -> dict[str, str]:
    base = {
        "harness_status": "succeeded",
        "evaluator_discovered": "true",
        "eval_status": "evaluable",
        "map_generated": "true",
        "n_coordinate_rows": "10",
        "spatial_correlation": "0.95",
        "dice_top5": "0.8",
        "control_map_exact_match": "false",
        "provenance_complete_score": "1",
        "claim_consistency_score": "1",
        "br_condition": "without_br",
        "br_call_count": "0",
        "local_identifier_coverage": "1",
        "source_provenance_coverage": "1",
        "public_identifier_coverage": "1",
        "sample_size_coverage": "1",
        "normalization_public_identifier_coverage": "1",
        "normalization_source_provenance_coverage": "1",
        "metric_contract": (
            '{"map_generated": {}, "coordinate_rows": {}, "study_rows": {}, '
            '"provenance_completeness": {}, "claim_consistency": {}, '
            '"local_study_set_f1": {"f1": 1.0}, '
            '"coordinate_canonical_f1": {"f1": 1.0}}'
        ),
        "correct": "true",
    }
    base.update(overrides)
    return base


def test_derive_row_marks_strict_success() -> None:
    derived = module.derive_row(_row())

    assert derived["correct_strict"] == "true"
    assert derived["recoverable_failure_type"] == "strict_success"
    assert derived["failed_axes"] == ""
    assert derived["raw_contract_score"] == "1.000000"
    assert derived["harness_clean_pass"] == "true"
    assert derived["harness_clean_score"] == "1.000000"
    assert derived["normalized_science_score"] == "1.000000"
    assert derived["normalized_vs_raw_recovery"] == "0.000000"
    assert derived["identifier_coverage_score"] == "1.000000"
    assert derived["provenance_enrichment_score"] == "1.000000"
    assert derived["br_reconciliation_score"] == "1.000000"


def test_derive_row_separates_harness_clean_from_strict_science_axes() -> None:
    derived = module.derive_row(
        _row(
            local_study_set_f1="0.8",
            metric_contract=(
                '{"map_generated": {}, "coordinate_rows": {}, "study_rows": {}, '
                '"provenance_completeness": {}, "claim_consistency": {}, '
                '"local_study_set_f1": {"f1": 0.8}, '
                '"coordinate_canonical_f1": {"f1": 1.0}}'
            ),
        )
    )

    assert derived["harness_clean_pass"] == "true"
    assert derived["correct_strict"] == "false"
    assert derived["recoverable_failure_type"] == "local_study_set_mismatch"


def test_derive_row_preserves_recoverable_timeout_case() -> None:
    derived = module.derive_row(_row(harness_status="timed_out"))

    assert derived["correct_strict"] == "false"
    assert derived["completion_pass"] == "false"
    assert derived["normalized_science_score"] == "1.000000"
    assert derived["recoverable_failure_type"] == (
        "scientifically_recoverable_but_contract_failed"
    )


def test_derive_row_classifies_missing_map_before_science_similarity() -> None:
    derived = module.derive_row(
        _row(map_generated="false", spatial_correlation="", dice_top5="")
    )

    assert derived["correct_strict"] == "false"
    assert derived["map_generation_pass"] == "false"
    assert derived["recoverable_failure_type"] == "missing_ale_map_artifact"


def test_derive_row_classifies_degraded_fallback_map_before_missing_map() -> None:
    derived = module.derive_row(
        _row(degraded_fallback_map="true", spatial_correlation="0.95", dice_top5="0.8")
    )

    assert derived["correct_strict"] == "false"
    assert derived["map_generation_pass"] == "false"
    assert derived["degraded_fallback_map"] == "true"
    assert derived["recoverable_failure_type"] == "degraded_fallback_map"


def test_br_effective_use_requires_call_and_anchor_proxy() -> None:
    no_call = module.derive_row(_row(br_condition="with_br", br_call_count="0"))
    called_no_anchor = module.derive_row(
        _row(
            br_condition="with_br",
            br_call_count="2",
            provenance_complete_score="0.777778",
            source_provenance_coverage="0",
            public_identifier_coverage="0",
        )
    )
    effective = module.derive_row(
        _row(
            br_condition="with_br",
            br_call_count="2",
            source_provenance_coverage="0.5",
        )
    )

    assert no_call["br_actual_use_pass"] == "false"
    assert no_call["br_effective_use_pass"] == "false"
    assert no_call["br_effective_use_basis"] == "no_br_calls"
    assert called_no_anchor["br_actual_use_pass"] == "true"
    assert called_no_anchor["br_effective_use_pass"] == "false"
    assert "no_retrieved_or_audited_anchor" in called_no_anchor["br_effective_use_basis"]
    assert effective["br_effective_use_pass"] == "true"


def test_br_effective_use_prefers_explicit_anchor_trace() -> None:
    effective = module.derive_row(
        _row(
            br_condition="with_br",
            br_call_count="1",
            provenance_complete_score="0",
            source_provenance_coverage="0",
            public_identifier_coverage="0",
            br_trace_effective_use_pass="true",
        )
    )
    ineffective = module.derive_row(
        _row(
            br_condition="with_br",
            br_call_count="1",
            br_trace_effective_use_pass="false",
        )
    )

    assert effective["br_effective_use_pass"] == "true"
    assert effective["br_effective_use_basis"] == "br_anchor_trace_effective_use_pass"
    assert ineffective["br_effective_use_pass"] == "false"
    assert ineffective["br_effective_use_basis"] == "br_anchor_trace_effective_use_failed"


def test_br_effective_use_accepts_reconciliation_anchor_contract() -> None:
    derived = module.derive_row(
        _row(
            br_condition="with_br",
            br_call_count="1",
            br_trace_effective_use_pass="false",
            br_reconciliation_anchor_pass="true",
            br_reconciliation_anchor_count="2",
            br_reconciliation_anchor_valid_count="2",
            br_reconciliation_anchor_consumed_count="1",
            br_reconciliation_anchor_changed_count="1",
            br_reconciliation_anchor_changed_consumed_count="1",
        )
    )

    assert derived["br_effective_use_pass"] == "true"
    assert derived["br_effective_use_basis"] == "br_reconciliation_anchor_contract_pass"
    assert derived["br_reconciliation_anchor_score"] == "0.833333"


def test_summarize_rows_counts_original_and_strict_separately() -> None:
    rows = module.derive_rows(
        [
            _row(system="A", system_key="a", task_id="1", br_condition="without_br"),
            _row(
                system="A",
                system_key="a",
                task_id="1",
                br_condition="with_br",
                br_call_count="1",
            ),
            _row(
                system="B",
                system_key="b",
                task_id="1",
                br_condition="without_br",
                correct="false",
                harness_status="failed",
            ),
            _row(
                system="B",
                system_key="b",
                task_id="1",
                br_condition="with_br",
                harness_status="timed_out",
            ),
        ]
    )

    summary = module.summarize_rows(rows)

    assert summary["totals"]["rows"] == 4
    assert summary["totals"]["original_correct"] == 3
    assert summary["totals"]["harness_clean"] == 2
    assert summary["totals"]["correct_strict"] == 2
    assert summary["by_br_condition"]["with_br"]["rows"] == 2
    assert summary["by_br_condition"]["with_br"]["harness_clean"] == 1
    assert summary["by_system"]["A"]["correct_strict"] == 2
    assert summary["readiness_gates"]["ready_for_full_rerun"] is False
    assert summary["readiness_gates"]["harness_clean_failures"] == 2
    assert len(summary["paper_table"]) == 4
    assert summary["paired_br_delta"]["paired_cells"] == 2
    assert summary["paired_br_delta"]["original_correct"]["with_only"] == 1
    assert summary["paired_br_delta"]["harness_clean"]["both_true"] == 1
    assert summary["paired_br_delta"]["correct_strict"]["both_true"] == 1


def test_derive_rows_adds_br_reconciliation_delta_columns() -> None:
    rows = module.derive_rows(
        [
            _row(
                system="A",
                system_key="a",
                task_id="1",
                br_condition="without_br",
                local_study_set_f1="0.5",
                coordinate_canonical_f1="0.5",
                local_identifier_coverage="0.25",
                public_identifier_coverage="0.25",
                source_provenance_coverage="0.25",
                sample_size_coverage="0.25",
                normalization_public_identifier_coverage="0.25",
                normalization_source_provenance_coverage="0.25",
                metric_contract=(
                    '{"map_generated": {}, "coordinate_rows": {}, "study_rows": {}, '
                    '"provenance_completeness": {}, "claim_consistency": {}, '
                    '"local_study_set_f1": {"f1": 0.5}, '
                    '"coordinate_canonical_f1": {"f1": 0.5}}'
                ),
            ),
            _row(
                system="A",
                system_key="a",
                task_id="1",
                br_condition="with_br",
                br_call_count="2",
                local_study_set_f1="1",
                coordinate_canonical_f1="1",
                metric_contract=(
                    '{"map_generated": {}, "coordinate_rows": {}, "study_rows": {}, '
                    '"provenance_completeness": {}, "claim_consistency": {}, '
                    '"local_study_set_f1": {"f1": 1.0}, '
                    '"coordinate_canonical_f1": {"f1": 1.0}}'
                ),
            ),
        ]
    )

    with_br = next(row for row in rows if row["br_condition"] == "with_br")
    without_br = next(row for row in rows if row["br_condition"] == "without_br")
    summary = module.summarize_rows(rows)

    assert without_br.get("br_reconciliation_gain") is None
    assert with_br["identifier_coverage_delta"] == "0.750000"
    assert with_br["provenance_enrichment_delta"] == "0.562500"
    assert with_br["br_reconciliation_gain"] == "0.578125"
    assert summary["paired_br_delta"]["br_reconciliation_gain"]["positive"] == 1
    assert summary["paired_br_delta"]["identifier_coverage_delta"]["positive"] == 1
    assert summary["paired_br_delta"]["provenance_enrichment_delta"]["positive"] == 1
