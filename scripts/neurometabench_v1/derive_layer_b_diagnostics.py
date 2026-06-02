#!/usr/bin/env python3
"""Derive Layer B strict-success and failure-mode diagnostic axes.

This script is intentionally post-hoc: it reads the case-condition CSV produced
by the Layer B agent matrix and writes a richer diagnostic table without
rerunning any agent or evaluator.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SPATIAL_THRESHOLD = 0.8
DEFAULT_DICE_THRESHOLD = 0.5
DEFAULT_PROVENANCE_THRESHOLD = 0.9
DEFAULT_CLAIM_THRESHOLD = 0.75
DEFAULT_LOCAL_STUDY_F1_THRESHOLD = 0.98
DEFAULT_COORDINATE_CANONICAL_F1_THRESHOLD = 0.98


@dataclass(frozen=True)
class DiagnosticThresholds:
    spatial_correlation: float = DEFAULT_SPATIAL_THRESHOLD
    dice_top5: float = DEFAULT_DICE_THRESHOLD
    provenance_complete: float = DEFAULT_PROVENANCE_THRESHOLD
    claim_consistency: float = DEFAULT_CLAIM_THRESHOLD
    local_study_set_f1: float = DEFAULT_LOCAL_STUDY_F1_THRESHOLD
    coordinate_canonical_f1: float = DEFAULT_COORDINATE_CANONICAL_F1_THRESHOLD


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    if text in {"", "none", "null", "nan"}:
        return None
    return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _json(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _pass_text(value: bool) -> str:
    return "true" if value else "false"


def _score_mean(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def _mean_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _score_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _metric_contract_pass(row: dict[str, str]) -> bool:
    contract = _json(row.get("metric_contract"))
    if not contract:
        return False
    required = {
        "map_generated",
        "coordinate_rows",
        "study_rows",
        "provenance_completeness",
        "claim_consistency",
    }
    return required.issubset(contract)


def _contract_metric_f1(row: dict[str, str], key: str) -> float | None:
    direct = _float(row.get(key))
    if direct is not None:
        return direct
    contract = _json(row.get("metric_contract"))
    metric = contract.get(key)
    if isinstance(metric, dict):
        return _float(metric.get("f1"))
    return None


def _coordinate_schema_pass(row: dict[str, str]) -> bool:
    n_coordinate_rows = _float(row.get("n_coordinate_rows"))
    if n_coordinate_rows is None or n_coordinate_rows <= 0:
        return False
    contract = _json(row.get("metric_contract"))
    coordinate_rows = contract.get("coordinate_rows")
    if isinstance(coordinate_rows, dict) and coordinate_rows.get("reason"):
        return False
    return True


def _scientific_similarity_pass(
    row: dict[str, str],
    thresholds: DiagnosticThresholds,
) -> bool:
    if _bool(row.get("map_generated")) is not True:
        return False
    if _bool(row.get("control_map_exact_match")) is True:
        return True
    spatial = _float(row.get("spatial_correlation"))
    dice = _float(row.get("dice_top5"))
    return (
        spatial is not None
        and dice is not None
        and spatial >= thresholds.spatial_correlation
        and dice >= thresholds.dice_top5
    )


def _provenance_pass(row: dict[str, str], thresholds: DiagnosticThresholds) -> bool:
    score = _float(row.get("provenance_complete_score"))
    return score is not None and score >= thresholds.provenance_complete


def _claim_consistency_pass(row: dict[str, str], thresholds: DiagnosticThresholds) -> bool:
    score = _float(row.get("claim_consistency_score"))
    return score is not None and score >= thresholds.claim_consistency


def _local_study_set_pass(row: dict[str, str], thresholds: DiagnosticThresholds) -> bool:
    score = _contract_metric_f1(row, "local_study_set_f1")
    return score is not None and score >= thresholds.local_study_set_f1


def _coordinate_canonical_pass(row: dict[str, str], thresholds: DiagnosticThresholds) -> bool:
    score = _contract_metric_f1(row, "coordinate_canonical_f1")
    return score is not None and score >= thresholds.coordinate_canonical_f1


def _identifier_coverage_score(row: dict[str, str]) -> float | None:
    return _mean_optional(
        [
            _float(row.get("local_identifier_coverage")),
            _float(row.get("public_identifier_coverage")),
            _float(row.get("normalization_public_identifier_coverage")),
        ]
    )


def _provenance_enrichment_score(row: dict[str, str]) -> float | None:
    return _mean_optional(
        [
            _float(row.get("source_provenance_coverage")),
            _float(row.get("sample_size_coverage")),
            _float(row.get("normalization_source_provenance_coverage")),
            _float(row.get("provenance_complete_score")),
        ]
    )


def _br_reconciliation_anchor_score(row: dict[str, str]) -> float | None:
    n_anchors = _float(row.get("br_reconciliation_anchor_count"))
    if n_anchors is None or n_anchors <= 0:
        anchor_pass = _bool(row.get("br_reconciliation_anchor_pass"))
        return 1.0 if anchor_pass is True else None
    valid = _float(row.get("br_reconciliation_anchor_valid_count")) or 0.0
    consumed = _float(row.get("br_reconciliation_anchor_consumed_count")) or 0.0
    valid_ratio = valid / n_anchors
    consumed_ratio = consumed / n_anchors
    changed = _float(row.get("br_reconciliation_anchor_changed_count")) or 0.0
    changed_consumed = _float(
        row.get("br_reconciliation_anchor_changed_consumed_count")
    ) or 0.0
    changed_ratio = 1.0 if changed <= 0 else min(1.0, changed_consumed / changed)
    return _mean_optional([valid_ratio, consumed_ratio, changed_ratio])


def _br_reconciliation_score(row: dict[str, str]) -> float | None:
    return _mean_optional(
        [
            _contract_metric_f1(row, "local_study_set_f1"),
            _contract_metric_f1(row, "coordinate_canonical_f1"),
            _identifier_coverage_score(row),
            _provenance_enrichment_score(row),
            _br_reconciliation_anchor_score(row),
        ]
    )


def _br_effective_use(row: dict[str, str]) -> tuple[bool, str]:
    if row.get("br_condition") != "with_br":
        return False, "not_with_br_condition"
    br_calls = _float(row.get("br_call_count")) or 0.0
    if br_calls <= 0:
        return False, "no_br_calls"

    anchor_pass = _bool(row.get("br_reconciliation_anchor_pass"))
    if anchor_pass is True:
        return True, "br_reconciliation_anchor_contract_pass"

    trace_effective = _bool(row.get("br_trace_effective_use_pass"))
    if trace_effective is True:
        return True, "br_anchor_trace_effective_use_pass"
    if trace_effective is False and row.get("br_trace_effective_use_pass"):
        return False, "br_anchor_trace_effective_use_failed"

    provenance = _float(row.get("provenance_complete_score")) or 0.0
    source_coverage = _float(row.get("source_provenance_coverage")) or 0.0
    public_id = _float(row.get("public_identifier_coverage")) or 0.0
    consumed = any(
        value is not None
        for value in (
            _bool(row.get("map_generated")),
            _float(row.get("claim_consistency_score")),
            _float(row.get("failure_diagnosis_quality_score")),
        )
    )
    anchored = source_coverage > 0 or public_id > 0 or provenance >= DEFAULT_PROVENANCE_THRESHOLD
    if anchored and consumed:
        return True, "br_called_and_artifact_or_report_consumes_auditable_result"
    if consumed:
        return False, "br_called_but_no_retrieved_or_audited_anchor_proxy"
    return False, "br_called_but_no_consumption_proxy"


def derive_row(
    row: dict[str, str],
    thresholds: DiagnosticThresholds = DiagnosticThresholds(),
) -> dict[str, str]:
    completion_pass = row.get("harness_status") == "succeeded"
    evaluator_discovered_pass = _bool(row.get("evaluator_discovered")) is True
    artifact_contract_pass = evaluator_discovered_pass and _metric_contract_pass(row)
    degraded_fallback_map = _bool(row.get("degraded_fallback_map")) is True
    map_generation_pass = (
        _bool(row.get("map_generated")) is True and not degraded_fallback_map
    )
    coordinate_schema_pass = _coordinate_schema_pass(row)
    scientific_similarity_pass = _scientific_similarity_pass(row, thresholds)
    provenance_pass = _provenance_pass(row, thresholds)
    claim_consistency_pass = _claim_consistency_pass(row, thresholds)
    local_study_set_pass = _local_study_set_pass(row, thresholds)
    coordinate_canonical_pass = _coordinate_canonical_pass(row, thresholds)
    br_actual_use_pass = (row.get("br_condition") == "with_br") and (
        (_float(row.get("br_call_count")) or 0.0) > 0
    )
    br_effective_use_pass, br_effective_use_basis = _br_effective_use(row)

    strict_axes = [
        completion_pass,
        artifact_contract_pass,
        evaluator_discovered_pass,
        map_generation_pass,
        coordinate_schema_pass,
        scientific_similarity_pass,
        provenance_pass,
        claim_consistency_pass,
        local_study_set_pass,
        coordinate_canonical_pass,
    ]
    raw_contract_axes = [
        completion_pass,
        evaluator_discovered_pass,
        artifact_contract_pass,
        map_generation_pass,
        coordinate_schema_pass,
    ]
    harness_clean_axes = [
        completion_pass,
        evaluator_discovered_pass,
        artifact_contract_pass,
        map_generation_pass,
        coordinate_schema_pass,
        provenance_pass,
        claim_consistency_pass,
    ]
    normalized_science_axes = [
        map_generation_pass,
        coordinate_schema_pass,
        scientific_similarity_pass,
    ]
    raw_contract_score = _score_mean(raw_contract_axes)
    harness_clean_score = _score_mean(harness_clean_axes)
    normalized_science_score = _score_mean(normalized_science_axes)
    normalized_vs_raw_recovery = normalized_science_score - raw_contract_score
    identifier_coverage_score = _identifier_coverage_score(row)
    provenance_enrichment_score = _provenance_enrichment_score(row)
    br_reconciliation_anchor_score = _br_reconciliation_anchor_score(row)
    br_reconciliation_score = _br_reconciliation_score(row)
    harness_clean_pass = all(harness_clean_axes)
    correct_strict = all(strict_axes)

    recoverable_failure_type = "strict_success"
    if not correct_strict:
        if normalized_science_score == 1.0 and raw_contract_score < 1.0:
            recoverable_failure_type = "scientifically_recoverable_but_contract_failed"
        elif not completion_pass and evaluator_discovered_pass:
            recoverable_failure_type = "partial_output_after_timeout_or_failed_harness"
        elif not completion_pass:
            recoverable_failure_type = "completion_failed_or_timed_out"
        elif not evaluator_discovered_pass:
            recoverable_failure_type = "evaluator_not_discovered"
        elif not artifact_contract_pass:
            recoverable_failure_type = "artifact_contract_failed"
        elif degraded_fallback_map:
            recoverable_failure_type = "degraded_fallback_map"
        elif not map_generation_pass:
            recoverable_failure_type = "missing_ale_map_artifact"
        elif not coordinate_schema_pass:
            recoverable_failure_type = "coordinate_schema_failed"
        elif not scientific_similarity_pass:
            recoverable_failure_type = "scientific_similarity_failed"
        elif not provenance_pass:
            recoverable_failure_type = "provenance_incomplete"
        elif not claim_consistency_pass:
            recoverable_failure_type = "claim_inconsistent"
        elif not local_study_set_pass:
            recoverable_failure_type = "local_study_set_mismatch"
        elif not coordinate_canonical_pass:
            recoverable_failure_type = "coordinate_canonical_mismatch"

    diagnostic_vector = {
        "completion_pass": completion_pass,
        "artifact_contract_pass": artifact_contract_pass,
        "evaluator_discovered": evaluator_discovered_pass,
        "map_generation_pass": map_generation_pass,
        "coordinate_schema_pass": coordinate_schema_pass,
        "scientific_similarity_pass": scientific_similarity_pass,
        "provenance_pass": provenance_pass,
        "claim_consistency_pass": claim_consistency_pass,
        "local_study_set_pass": local_study_set_pass,
        "coordinate_canonical_pass": coordinate_canonical_pass,
        "harness_clean_pass": harness_clean_pass,
    }
    failed_axes = [
        key
        for key, value in diagnostic_vector.items()
        if key != "harness_clean_pass" and not value
    ]

    return {
        "completion_pass": _pass_text(completion_pass),
        "artifact_contract_pass": _pass_text(artifact_contract_pass),
        "evaluator_discovered_pass": _pass_text(evaluator_discovered_pass),
        "map_generation_pass": _pass_text(map_generation_pass),
        "degraded_fallback_map": _pass_text(degraded_fallback_map),
        "coordinate_schema_pass": _pass_text(coordinate_schema_pass),
        "scientific_similarity_pass": _pass_text(scientific_similarity_pass),
        "provenance_pass": _pass_text(provenance_pass),
        "claim_consistency_pass": _pass_text(claim_consistency_pass),
        "local_study_set_pass": _pass_text(local_study_set_pass),
        "coordinate_canonical_pass": _pass_text(coordinate_canonical_pass),
        "harness_clean_pass": _pass_text(harness_clean_pass),
        "correct_strict": _pass_text(correct_strict),
        "raw_contract_score": f"{raw_contract_score:.6f}",
        "harness_clean_score": f"{harness_clean_score:.6f}",
        "normalized_science_score": f"{normalized_science_score:.6f}",
        "normalization_delta": f"{normalized_vs_raw_recovery:.6f}",
        "normalized_vs_raw_recovery": f"{normalized_vs_raw_recovery:.6f}",
        "identifier_coverage_score": _score_text(identifier_coverage_score),
        "provenance_enrichment_score": _score_text(provenance_enrichment_score),
        "br_reconciliation_anchor_score": _score_text(
            br_reconciliation_anchor_score
        ),
        "br_reconciliation_score": _score_text(br_reconciliation_score),
        "recoverable_failure_type": recoverable_failure_type,
        "failed_axes": ";".join(failed_axes),
        "diagnostic_vector": json.dumps(diagnostic_vector, sort_keys=True),
        "br_actual_use_pass": _pass_text(br_actual_use_pass),
        "br_effective_use_pass": _pass_text(br_effective_use_pass),
        "br_effective_use_basis": br_effective_use_basis,
    }


def derive_rows(
    rows: list[dict[str, str]],
    thresholds: DiagnosticThresholds = DiagnosticThresholds(),
) -> list[dict[str, str]]:
    derived = [dict(row, **derive_row(row, thresholds)) for row in rows]
    _annotate_paired_br_reconciliation_deltas(derived)
    return derived


def _annotate_paired_br_reconciliation_deltas(rows: list[dict[str, str]]) -> None:
    pairs: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        system_key = row.get("system_key") or row.get("system") or ""
        task_id = row.get("task_id") or row.get("case_id") or ""
        br_condition = row.get("br_condition") or ""
        if system_key and task_id and br_condition in {"with_br", "without_br"}:
            pairs[(system_key, task_id)][br_condition] = row

    delta_specs = {
        "br_reconciliation_gain": "br_reconciliation_score",
        "identifier_coverage_delta": "identifier_coverage_score",
        "provenance_enrichment_delta": "provenance_enrichment_score",
        "normalized_vs_raw_recovery_delta": "normalized_vs_raw_recovery",
        "br_reconciliation_anchor_score_delta": "br_reconciliation_anchor_score",
    }
    for pair in pairs.values():
        with_row = pair.get("with_br")
        without_row = pair.get("without_br")
        if not with_row or not without_row:
            continue
        for output_field, score_field in delta_specs.items():
            with_score = _float(with_row.get(score_field))
            without_score = _float(without_row.get(score_field))
            if with_score is None or without_score is None:
                continue
            with_row[output_field] = f"{(with_score - without_score):.6f}"


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _row_metric_value(row: dict[str, str], field: str) -> float | None:
    if field in {"local_study_set_f1", "coordinate_canonical_f1"}:
        return _contract_metric_f1(row, field)
    return _float(row.get(field))


def _mean_metric(rows: list[dict[str, str]], field: str) -> float | None:
    values = [
        value
        for row in rows
        if (value := _row_metric_value(row, field)) is not None
    ]
    return _mean(values)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _summary_float(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def _paper_table(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row.get("system") or row.get("system_key") or "unknown",
                row.get("br_condition") or "unknown",
            )
        ].append(row)

    table: list[dict[str, Any]] = []
    for (system, br_condition), group in sorted(grouped.items()):
        n_rows = len(group)
        original_correct = sum(row.get("correct") == "true" for row in group)
        harness_clean = sum(row.get("harness_clean_pass") == "true" for row in group)
        strict = sum(row.get("correct_strict") == "true" for row in group)
        br_effective = sum(row.get("br_effective_use_pass") == "true" for row in group)
        br_anchor_contract = sum(
            row.get("br_reconciliation_anchor_pass") == "true" for row in group
        )
        map_generated = sum(row.get("map_generated") == "true" for row in group)
        table.append(
            {
                "system": system,
                "br_condition": br_condition,
                "rows": n_rows,
                "original_correct": original_correct,
                "harness_clean": harness_clean,
                "strict_success": strict,
                "br_effective_use": br_effective,
                "br_reconciliation_anchor_pass": br_anchor_contract,
                "map_generated": map_generated,
                "original_correct_rate": _summary_float(_ratio(original_correct, n_rows)),
                "harness_clean_rate": _summary_float(_ratio(harness_clean, n_rows)),
                "strict_success_rate": _summary_float(_ratio(strict, n_rows)),
                "mean_raw_contract_score": _summary_float(
                    _mean_metric(group, "raw_contract_score")
                ),
                "mean_harness_clean_score": _summary_float(
                    _mean_metric(group, "harness_clean_score")
                ),
                "mean_normalized_science_score": _summary_float(
                    _mean_metric(group, "normalized_science_score")
                ),
                "mean_normalized_vs_raw_recovery": _summary_float(
                    _mean_metric(group, "normalized_vs_raw_recovery")
                ),
                "mean_local_study_set_f1": _summary_float(
                    _mean_metric(group, "local_study_set_f1")
                ),
                "mean_coordinate_canonical_f1": _summary_float(
                    _mean_metric(group, "coordinate_canonical_f1")
                ),
                "mean_spatial_correlation": _summary_float(
                    _mean_metric(group, "spatial_correlation")
                ),
                "mean_dice_top5": _summary_float(_mean_metric(group, "dice_top5")),
                "mean_provenance_complete_score": _summary_float(
                    _mean_metric(group, "provenance_complete_score")
                ),
                "mean_claim_consistency_score": _summary_float(
                    _mean_metric(group, "claim_consistency_score")
                ),
                "mean_identifier_coverage_score": _summary_float(
                    _mean_metric(group, "identifier_coverage_score")
                ),
                "mean_provenance_enrichment_score": _summary_float(
                    _mean_metric(group, "provenance_enrichment_score")
                ),
                "mean_br_reconciliation_anchor_score": _summary_float(
                    _mean_metric(group, "br_reconciliation_anchor_score")
                ),
                "mean_br_reconciliation_score": _summary_float(
                    _mean_metric(group, "br_reconciliation_score")
                ),
                "mean_br_reconciliation_gain": _summary_float(
                    _mean_metric(group, "br_reconciliation_gain")
                ),
                "mean_identifier_coverage_delta": _summary_float(
                    _mean_metric(group, "identifier_coverage_delta")
                ),
                "mean_provenance_enrichment_delta": _summary_float(
                    _mean_metric(group, "provenance_enrichment_delta")
                ),
                "mean_br_reconciliation_anchor_score_delta": _summary_float(
                    _mean_metric(group, "br_reconciliation_anchor_score_delta")
                ),
            }
        )
    return table


def _readiness_gates(rows: list[dict[str, str]]) -> dict[str, Any]:
    n_rows = len(rows)
    with_br_rows = [row for row in rows if row.get("br_condition") == "with_br"]
    harness_clean_failures = [
        row for row in rows if row.get("harness_clean_pass") != "true"
    ]
    with_br_no_effective = [
        row for row in with_br_rows if row.get("br_effective_use_pass") != "true"
    ]
    failure_type_counts = Counter(
        row.get("recoverable_failure_type") or "unknown"
        for row in harness_clean_failures
    )
    missing_map = failure_type_counts.get("missing_ale_map_artifact", 0)
    degraded_fallback_map = failure_type_counts.get("degraded_fallback_map", 0)
    return {
        "rows": n_rows,
        "harness_clean_pass": n_rows - len(harness_clean_failures),
        "harness_clean_failures": len(harness_clean_failures),
        "with_br_rows": len(with_br_rows),
        "with_br_effective_use_pass": len(with_br_rows) - len(with_br_no_effective),
        "with_br_no_effective_use": len(with_br_no_effective),
        "missing_map_failures": missing_map,
        "degraded_fallback_map_failures": degraded_fallback_map,
        "ready_for_full_rerun": (
            n_rows > 0
            and not harness_clean_failures
            and not with_br_no_effective
        ),
        "blocking_failure_types": dict(failure_type_counts.most_common()),
    }


def summarize_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    by_br: dict[str, Counter[str]] = defaultdict(Counter)
    by_br_effective_use: dict[str, Counter[str]] = defaultdict(Counter)
    by_system: dict[str, Counter[str]] = defaultdict(Counter)
    failure_types: Counter[str] = Counter()
    axes: Counter[str] = Counter()
    totals = Counter()

    for row in rows:
        br = row.get("br_condition") or "unknown"
        system = row.get("system") or row.get("system_key") or "unknown"
        strict = row.get("correct_strict") == "true"
        original = row.get("correct") == "true"
        harness_clean = row.get("harness_clean_pass") == "true"
        actual = row.get("br_actual_use_pass") == "true"
        effective = row.get("br_effective_use_pass") == "true"
        use_key = "effective_use" if effective else "no_effective_use"
        if row.get("br_condition") != "with_br":
            use_key = "not_with_br"
        totals["rows"] += 1
        totals["correct_strict"] += int(strict)
        totals["original_correct"] += int(original)
        totals["harness_clean"] += int(harness_clean)
        totals["br_actual_use"] += int(actual)
        totals["br_effective_use"] += int(effective)
        by_br[br]["rows"] += 1
        by_br[br]["correct_strict"] += int(strict)
        by_br[br]["original_correct"] += int(original)
        by_br[br]["harness_clean"] += int(harness_clean)
        by_br[br]["br_actual_use"] += int(actual)
        by_br[br]["br_effective_use"] += int(effective)
        by_br_effective_use[use_key]["rows"] += 1
        by_br_effective_use[use_key]["correct_strict"] += int(strict)
        by_br_effective_use[use_key]["original_correct"] += int(original)
        by_br_effective_use[use_key]["harness_clean"] += int(harness_clean)
        by_system[system]["rows"] += 1
        by_system[system]["correct_strict"] += int(strict)
        by_system[system]["original_correct"] += int(original)
        by_system[system]["harness_clean"] += int(harness_clean)
        failure_types[row.get("recoverable_failure_type") or "unknown"] += 1
        for axis in (row.get("failed_axes") or "").split(";"):
            if axis:
                axes[axis] += 1

    return {
        "totals": dict(totals),
        "by_br_condition": {key: dict(value) for key, value in sorted(by_br.items())},
        "by_br_effective_use": {
            key: dict(value) for key, value in sorted(by_br_effective_use.items())
        },
        "readiness_gates": _readiness_gates(rows),
        "paper_table": _paper_table(rows),
        "paired_br_delta": _summarize_paired_br_delta(rows),
        "by_system": {key: dict(value) for key, value in sorted(by_system.items())},
        "failure_types": dict(failure_types.most_common()),
        "failed_axes": dict(axes.most_common()),
    }


def _paired_outcome(without_value: bool, with_value: bool) -> str:
    if with_value and not without_value:
        return "with_only"
    if without_value and not with_value:
        return "without_only"
    if without_value and with_value:
        return "both_true"
    return "both_false"


def _delta_bucket(delta: float) -> str:
    if delta > 1e-9:
        return "positive"
    if delta < -1e-9:
        return "negative"
    return "tie"


def _summarize_paired_br_delta(rows: list[dict[str, str]]) -> dict[str, Any]:
    pairs: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        system_key = row.get("system_key") or row.get("system") or ""
        task_id = row.get("task_id") or row.get("case_id") or ""
        br_condition = row.get("br_condition") or ""
        if system_key and task_id and br_condition in {"with_br", "without_br"}:
            pairs[(system_key, task_id)][br_condition] = row

    counters: dict[str, Counter[str]] = {
        "original_correct": Counter(),
        "harness_clean": Counter(),
        "correct_strict": Counter(),
        "raw_contract_score_delta": Counter(),
        "normalized_science_score_delta": Counter(),
        "br_reconciliation_gain": Counter(),
        "identifier_coverage_delta": Counter(),
        "provenance_enrichment_delta": Counter(),
        "normalized_vs_raw_recovery_delta": Counter(),
        "br_reconciliation_anchor_score_delta": Counter(),
    }
    delta_sums: Counter[str] = Counter()
    delta_ns: Counter[str] = Counter()
    by_system: dict[str, Counter[str]] = defaultdict(Counter)
    paired_rows = 0
    for (system_key, _task_id), pair in pairs.items():
        if "with_br" not in pair or "without_br" not in pair:
            continue
        paired_rows += 1
        with_row = pair["with_br"]
        without_row = pair["without_br"]
        for field in ("correct", "harness_clean_pass", "correct_strict"):
            label = {
                "correct": "original_correct",
                "harness_clean_pass": "harness_clean",
            }.get(field, field)
            outcome = _paired_outcome(
                without_row.get(field) == "true",
                with_row.get(field) == "true",
            )
            counters[label][outcome] += 1
            by_system[system_key][f"{label}_{outcome}"] += 1
        for field in ("raw_contract_score", "normalized_science_score"):
            with_score = _float(with_row.get(field)) or 0.0
            without_score = _float(without_row.get(field)) or 0.0
            outcome = _delta_bucket(with_score - without_score)
            counters[f"{field}_delta"][outcome] += 1
            by_system[system_key][f"{field}_delta_{outcome}"] += 1
        for output_field, score_field in (
            ("br_reconciliation_gain", "br_reconciliation_score"),
            ("identifier_coverage_delta", "identifier_coverage_score"),
            ("provenance_enrichment_delta", "provenance_enrichment_score"),
            ("normalized_vs_raw_recovery_delta", "normalized_vs_raw_recovery"),
            (
                "br_reconciliation_anchor_score_delta",
                "br_reconciliation_anchor_score",
            ),
        ):
            with_score = _float(with_row.get(score_field))
            without_score = _float(without_row.get(score_field))
            if with_score is None or without_score is None:
                continue
            delta = with_score - without_score
            outcome = _delta_bucket(delta)
            counters[output_field][outcome] += 1
            delta_sums[output_field] += delta
            delta_ns[output_field] += 1
            by_system[system_key][f"{output_field}_{outcome}"] += 1

    return {
        "paired_cells": paired_rows,
        "original_correct": dict(counters["original_correct"]),
        "harness_clean": dict(counters["harness_clean"]),
        "correct_strict": dict(counters["correct_strict"]),
        "raw_contract_score_delta": dict(counters["raw_contract_score_delta"]),
        "normalized_science_score_delta": dict(
            counters["normalized_science_score_delta"]
        ),
        "br_reconciliation_gain": dict(counters["br_reconciliation_gain"]),
        "identifier_coverage_delta": dict(counters["identifier_coverage_delta"]),
        "provenance_enrichment_delta": dict(
            counters["provenance_enrichment_delta"]
        ),
        "normalized_vs_raw_recovery_delta": dict(
            counters["normalized_vs_raw_recovery_delta"]
        ),
        "br_reconciliation_anchor_score_delta": dict(
            counters["br_reconciliation_anchor_score_delta"]
        ),
        "mean_deltas": {
            key: _summary_float(delta_sums[key] / delta_ns[key])
            for key in sorted(delta_ns)
            if delta_ns[key]
        },
        "by_system": {key: dict(value) for key, value in sorted(by_system.items())},
    }


def _md_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_summary_md(summary: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Layer B Diagnostic Axes Summary",
        "",
        "This is a post-hoc derivation from a Layer B case-condition CSV.",
        "It does not rerun agents or mutate raw evaluator outputs.",
        "",
        "## Thresholds",
        "",
    ]
    thresholds = summary.get("thresholds", {})
    lines.extend(
        [
            f"- Spatial correlation pass: `>= {thresholds.get('spatial_correlation')}`",
            f"- Dice top 5% pass: `>= {thresholds.get('dice_top5')}`",
            f"- Provenance completeness pass: `>= {thresholds.get('provenance_complete')}`",
            f"- Claim consistency pass: `>= {thresholds.get('claim_consistency')}`",
            f"- Local study-set F1 pass: `>= {thresholds.get('local_study_set_f1')}`",
            f"- Coordinate canonical F1 pass: `>= {thresholds.get('coordinate_canonical_f1')}`",
            "",
        ]
    )
    lines.extend(
        [
        "## Totals",
        "",
        ]
    )
    totals = summary["totals"]
    rows = totals.get("rows", 0)
    strict = totals.get("correct_strict", 0)
    original = totals.get("original_correct", 0)
    harness_clean = totals.get("harness_clean", 0)
    actual = totals.get("br_actual_use", 0)
    effective = totals.get("br_effective_use", 0)
    readiness = summary.get("readiness_gates", {})
    lines.extend(
        [
            f"- Rows: `{rows}`",
            f"- Original `correct=True`: `{original}`",
            f"- Harness-clean pass: `{harness_clean}`",
            f"- Strict success: `{strict}`",
            f"- BR actual-use pass: `{actual}`",
            f"- BR effective-use pass: `{effective}`",
            "",
            "## Full Rerun Readiness Gate",
            "",
            f"- Ready for full rerun: `{readiness.get('ready_for_full_rerun')}`",
            f"- Harness-clean failures: `{readiness.get('harness_clean_failures')}`",
            f"- With-BR rows without effective BR use: `{readiness.get('with_br_no_effective_use')}`",
            f"- Missing-map failures: `{readiness.get('missing_map_failures')}`",
            "",
            "## By BR Condition",
            "",
            "| BR condition | Rows | Original correct | Harness clean | Strict success | BR actual-use | BR effective-use |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for br, counts in summary["by_br_condition"].items():
        lines.append(
            f"| {br} | {counts.get('rows', 0)} | {counts.get('original_correct', 0)} | "
            f"{counts.get('harness_clean', 0)} | {counts.get('correct_strict', 0)} | "
            f"{counts.get('br_actual_use', 0)} | "
            f"{counts.get('br_effective_use', 0)} |"
        )
    lines.extend(
        [
            "",
            "## By BR Effective Use",
            "",
            "| Use stratum | Rows | Original correct | Harness clean | Strict success |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for stratum, counts in summary["by_br_effective_use"].items():
        lines.append(
            f"| {stratum} | {counts.get('rows', 0)} | "
            f"{counts.get('original_correct', 0)} | {counts.get('harness_clean', 0)} | "
            f"{counts.get('correct_strict', 0)} |"
        )
    paired = summary["paired_br_delta"]
    lines.extend(
        [
            "",
            "## Paired BR Delta",
            "",
            f"- Paired `(system, task)` cells: `{paired['paired_cells']}`",
            "",
            "| Metric | With only | Without only | Both true | Both false |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for metric in ("original_correct", "harness_clean", "correct_strict"):
        counts = paired[metric]
        lines.append(
            f"| {metric} | {counts.get('with_only', 0)} | "
            f"{counts.get('without_only', 0)} | {counts.get('both_true', 0)} | "
            f"{counts.get('both_false', 0)} |"
        )
    lines.extend(
        [
            "",
            "| Score delta | Positive | Negative | Tie |",
            "|---|---:|---:|---:|",
        ]
    )
    for metric in ("raw_contract_score_delta", "normalized_science_score_delta"):
        counts = paired[metric]
        lines.append(
            f"| {metric} | {counts.get('positive', 0)} | "
            f"{counts.get('negative', 0)} | {counts.get('tie', 0)} |"
        )
    lines.extend(
        [
            "",
            "| BR reconciliation delta | Positive | Negative | Tie | Mean delta |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    mean_deltas = paired.get("mean_deltas", {})
    for metric in (
        "br_reconciliation_gain",
        "identifier_coverage_delta",
        "provenance_enrichment_delta",
        "normalized_vs_raw_recovery_delta",
        "br_reconciliation_anchor_score_delta",
    ):
        counts = paired.get(metric, {})
        lines.append(
            f"| {metric} | {counts.get('positive', 0)} | "
            f"{counts.get('negative', 0)} | {counts.get('tie', 0)} | "
            f"{_md_value(mean_deltas.get(metric))} |"
        )
    lines.extend(
        [
            "",
            "## Paper Table",
            "",
            "| System | BR | Rows | Orig correct | Harness clean | Strict | BR eff | BR anchor | Raw contract | Harness score | Norm science | Raw recovery | Local study F1 | Coord F1 | Spatial r | Dice | Prov | Claim | ID cov | Prov enrich | BR anchor score | BR recon | BR recon gain |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary.get("paper_table", []):
        lines.append(
            f"| {row['system']} | {row['br_condition']} | {row['rows']} | "
            f"{row['original_correct']} | {row['harness_clean']} | "
            f"{row['strict_success']} | {row['br_effective_use']} | "
            f"{row.get('br_reconciliation_anchor_pass', 0)} | "
            f"{_md_value(row.get('mean_raw_contract_score'))} | "
            f"{_md_value(row.get('mean_harness_clean_score'))} | "
            f"{_md_value(row.get('mean_normalized_science_score'))} | "
            f"{_md_value(row.get('mean_normalized_vs_raw_recovery'))} | "
            f"{_md_value(row.get('mean_local_study_set_f1'))} | "
            f"{_md_value(row.get('mean_coordinate_canonical_f1'))} | "
            f"{_md_value(row.get('mean_spatial_correlation'))} | "
            f"{_md_value(row.get('mean_dice_top5'))} | "
            f"{_md_value(row.get('mean_provenance_complete_score'))} | "
            f"{_md_value(row.get('mean_claim_consistency_score'))} | "
            f"{_md_value(row.get('mean_identifier_coverage_score'))} | "
            f"{_md_value(row.get('mean_provenance_enrichment_score'))} | "
            f"{_md_value(row.get('mean_br_reconciliation_anchor_score'))} | "
            f"{_md_value(row.get('mean_br_reconciliation_score'))} | "
            f"{_md_value(row.get('mean_br_reconciliation_gain'))} |"
        )
    lines.extend(["", "## Failure Types", "", "| Type | Count |", "|---|---:|"])
    for kind, count in summary["failure_types"].items():
        lines.append(f"| {kind} | {count} |")
    lines.extend(["", "## Failed Axes", "", "| Axis | Count |", "|---|---:|"])
    for axis, count in summary["failed_axes"].items():
        lines.append(f"| {axis} | {count} |")
    lines.extend(
        [
            "",
            "## By System",
            "",
            "| System | Rows | Original correct | Harness clean | Strict success |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for system, counts in summary["by_system"].items():
        lines.append(
            f"| {system} | {counts.get('rows', 0)} | "
            f"{counts.get('original_correct', 0)} | {counts.get('harness_clean', 0)} | "
            f"{counts.get('correct_strict', 0)} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_csv(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path, help="Layer B case-condition CSV")
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--summary-json", type=Path, default=None)
    parser.add_argument("--summary-md", type=Path, default=None)
    parser.add_argument("--spatial-threshold", type=float, default=DEFAULT_SPATIAL_THRESHOLD)
    parser.add_argument("--dice-threshold", type=float, default=DEFAULT_DICE_THRESHOLD)
    parser.add_argument(
        "--provenance-threshold",
        type=float,
        default=DEFAULT_PROVENANCE_THRESHOLD,
    )
    parser.add_argument("--claim-threshold", type=float, default=DEFAULT_CLAIM_THRESHOLD)
    parser.add_argument(
        "--local-study-f1-threshold",
        type=float,
        default=DEFAULT_LOCAL_STUDY_F1_THRESHOLD,
    )
    parser.add_argument(
        "--coordinate-canonical-f1-threshold",
        type=float,
        default=DEFAULT_COORDINATE_CANONICAL_F1_THRESHOLD,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    thresholds = DiagnosticThresholds(
        spatial_correlation=args.spatial_threshold,
        dice_top5=args.dice_threshold,
        provenance_complete=args.provenance_threshold,
        claim_consistency=args.claim_threshold,
        local_study_set_f1=args.local_study_f1_threshold,
        coordinate_canonical_f1=args.coordinate_canonical_f1_threshold,
    )
    rows = derive_rows(load_csv(args.input_csv), thresholds)
    output_csv = args.output_csv or args.input_csv.with_name(
        f"{args.input_csv.stem}_diagnostic_axes.csv"
    )
    summary_json = args.summary_json or args.input_csv.with_name(
        "LAYER_B_DIAGNOSTIC_AXES_SUMMARY.json"
    )
    summary_md = args.summary_md or args.input_csv.with_name(
        "LAYER_B_DIAGNOSTIC_AXES_SUMMARY.md"
    )
    write_csv(output_csv, rows)
    summary = summarize_rows(rows)
    summary["thresholds"] = {
        "spatial_correlation": thresholds.spatial_correlation,
        "dice_top5": thresholds.dice_top5,
        "provenance_complete": thresholds.provenance_complete,
        "claim_consistency": thresholds.claim_consistency,
        "local_study_set_f1": thresholds.local_study_set_f1,
        "coordinate_canonical_f1": thresholds.coordinate_canonical_f1,
    }
    summary["input_csv"] = str(args.input_csv)
    summary["output_csv"] = str(output_csv)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_summary_md(summary, summary_md)
    print(
        json.dumps(
            {
                "input_csv": str(args.input_csv),
                "output_csv": str(output_csv),
                "summary_json": str(summary_json),
                "summary_md": str(summary_md),
                "totals": summary["totals"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
