#!/usr/bin/env python3
"""Export Layer B comparison summaries as case-condition rows.

The Layer B comparison evaluator writes a nested JSON summary. The diagnostic
axis derivation expects one row per harness episode, including rows where the
evaluator did not discover a valid artifact bundle. This script joins those two
surfaces without rerunning agents.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_RUN_DIR = Path(
    "benchmarks/neurometabench/experiments/agent_condition_matrix/"
    "layer_b_full_model_matrix_20260504"
)
DEFAULT_CASES_PATH = Path("benchmarks/neurometabench/cases.v1.jsonl")
DEFAULT_CONDITIONS_PATH = Path("benchmarks/neurometabench/agent_conditions.v1.jsonl")
BR_MODES_WITH_TOOLS = {"with_br_mcp", "with_br_required"}
SYSTEM_LABELS = {
    "codex_cli_gpt55": "Codex CLI GPT-5.5",
    "claude_code_opus47": "Claude Code Opus",
    "opencode_gemini_pro": "OpenCode Gemini 3.1 Pro Preview",
    "opencode_glm51": "OpenCode GLM 5.1",
    "opencode_deepseek_v4_pro": "OpenCode DeepSeek V4 Pro",
    "opencode_kimi_k25": "OpenCode Kimi K2.5",
    "opencode_qwen36_plus": "OpenCode Qwen3.6 Plus",
}
CONDITION_SUFFIX_RE = re.compile(r"_(?:without_br|with_br_required|with_br)$")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            rows.append(json.loads(stripped))
    return rows


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _bool_text(value: Any) -> str:
    if value is None:
        return ""
    return "true" if bool(value) else "false"


def _json_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _nested(data: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = data or {}
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _metric_value(metric: Any) -> Any:
    return metric.get("value") if isinstance(metric, dict) else None


def _metric_score(metric: Any) -> Any:
    return metric.get("score") if isinstance(metric, dict) else None


def _metric_field(metric: Any, field: str) -> Any:
    return metric.get(field) if isinstance(metric, dict) else None


def _system_key(condition_id: str) -> str:
    return CONDITION_SUFFIX_RE.sub("", condition_id)


def _br_condition(br_mode: str | None) -> str:
    return "with_br" if br_mode in BR_MODES_WITH_TOOLS else "without_br"


def _case_output_dir(producer_output_dir: str, meta_pmid: str, case: dict[str, Any] | None) -> str:
    if case and case.get("case_dir"):
        return str(case["case_dir"])
    if producer_output_dir:
        producer = Path(producer_output_dir)
        matches = sorted(producer.glob(f"layer_b_{meta_pmid}*"))
        if matches:
            return str(matches[0])
    return ""


def _load_case_metadata(cases_path: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl(cases_path):
        meta_pmid = str(row.get("meta_pmid") or "")
        if meta_pmid:
            cases[meta_pmid] = row
    return cases


def _load_condition_metadata(conditions_path: Path) -> dict[str, dict[str, Any]]:
    conditions: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl(conditions_path):
        if row.get("record_type") != "condition":
            continue
        condition_id = str(row.get("condition_id") or "")
        if condition_id:
            conditions[condition_id] = row
    return conditions


def _load_records(run_dir: Path) -> list[dict[str, Any]]:
    episode_records = run_dir / "episode_records.jsonl"
    if episode_records.exists():
        return _load_jsonl(episode_records)
    run_summary = run_dir / "RUN_SUMMARY.json"
    if run_summary.exists():
        records = _read_json(run_summary).get("records", [])
        return records if isinstance(records, list) else []
    return []


def _comparison_case_map(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    cases: dict[tuple[str, str], dict[str, Any]] = {}
    for condition in summary.get("conditions", []):
        name = str(condition.get("name") or "")
        for case in condition.get("cases", []):
            meta_pmid = str(case.get("meta_pmid") or "")
            if name and meta_pmid:
                cases[(name, meta_pmid)] = case
    return cases


def _trace_summary(case: dict[str, Any] | None) -> dict[str, Any]:
    return (
        _nested(case, "metric_layers", "br_relevant_audit", "br_anchor_trace")
        if case
        else {}
    ) or {}


def _normalization(case: dict[str, Any] | None) -> dict[str, Any]:
    return _nested(case, "metric_layers", "normalization") if case else {}


def _row_from_record(
    record: dict[str, Any],
    *,
    run_name: str,
    case_meta: dict[str, dict[str, Any]],
    condition_meta: dict[str, dict[str, Any]],
    comparison_cases: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    condition_id = str(record.get("condition_id") or "")
    condition = condition_meta.get(condition_id, {})
    br_mode = str(record.get("br_mode") or condition.get("br_mode") or "")
    system_key = _system_key(condition_id)
    system = SYSTEM_LABELS.get(system_key) or system_key or condition_id
    meta_pmids = record.get("meta_pmids") or []
    if not isinstance(meta_pmids, list):
        meta_pmids = [meta_pmids]

    for raw_meta_pmid in meta_pmids:
        meta_pmid = str(raw_meta_pmid)
        case = comparison_cases.get((condition_id, meta_pmid))
        case_info = case_meta.get(meta_pmid, {})
        contract = _nested(case, "metric_layers", "metric_contract") or {}
        deterministic = _nested(case, "metric_layers", "deterministic_artifact") or {}
        fallback_map_check = (case or {}).get("fallback_map_check") or deterministic.get(
            "fallback_map_check"
        ) or {}
        reconciliation = contract.get("pmid_study_reconciliation") or {}
        br_anchor_contract = contract.get("br_reconciliation_anchors") or {}
        provenance = contract.get("provenance_completeness") or {}
        claim = contract.get("claim_consistency") or {}
        failure = contract.get("failure_diagnosis_quality") or {}
        control = case.get("control_comparison") if case else {}
        spatial_agreement = (
            control.get("spatial_map_agreement") if isinstance(control, dict) else {}
        ) or {}
        normalization = _normalization(case) or {}
        normalized_coordinates = normalization.get("coordinate_table", {}) if normalization else {}
        normalized_studies = normalization.get("included_studies", {}) if normalization else {}
        normalization_delta = normalization.get("normalization_delta", {}) if normalization else {}
        trace = _trace_summary(case)
        scored = case is not None
        eval_status = str(case.get("status") or "") if case else ""
        correct = scored and eval_status == "evaluable"
        case_output_dir = _case_output_dir(
            str(record.get("producer_output_dir") or ""),
            meta_pmid,
            case,
        )
        episode_dir = str(record.get("episode_dir") or "")

        rows.append(
            {
                "run_name": run_name,
                "condition": condition_id,
                "system_key": system_key,
                "system": system,
                "br_condition": _br_condition(br_mode),
                "br_mode": br_mode,
                "task_id": meta_pmid,
                "case_id": str(
                    (case or {}).get("case_id")
                    or case_info.get("case_id")
                    or f"neurometabench:{meta_pmid}"
                ),
                "meta_pmid": meta_pmid,
                "topic": str((case or {}).get("topic") or case_info.get("topic") or ""),
                "runner": str(record.get("runner") or condition.get("runner") or ""),
                "model": str(
                    record.get("model_target") or condition.get("model_target") or ""
                ),
                "harness_status": str(record.get("status") or ""),
                "returncode": _as_text(record.get("returncode")),
                "json_error_event": _bool_text(record.get("json_error_event")),
                "wall_time_s": _as_text(record.get("wall_time_s")),
                "tool_calls": _as_text(record.get("tool_calls")),
                "retry_count": _as_text(record.get("retry_count")),
                "started_at": str(record.get("started_at") or ""),
                "ended_at": str(record.get("ended_at") or ""),
                "producer_output_dir": str(record.get("producer_output_dir") or ""),
                "case_output_dir": case_output_dir,
                "episode_dir": episode_dir,
                "stdout_path": str(Path(episode_dir) / "stdout.txt") if episode_dir else "",
                "stderr_path": str(Path(episode_dir) / "stderr.txt") if episode_dir else "",
                "record_path": str(Path(episode_dir) / "record.json") if episode_dir else "",
                "scored": _bool_text(scored),
                "evaluator_discovered": _bool_text(scored),
                "eval_status": eval_status,
                "eval_status_reasons": ";".join(case.get("status_reasons") or [])
                if case
                else "",
                "map_generated": _bool_text(case.get("map_generated")) if case else "",
                "degraded_fallback_map": _bool_text(
                    case.get("degraded_fallback_map")
                    if case
                    else deterministic.get("degraded_fallback_map")
                ),
                "degraded_fallback_map_reason": str(
                    fallback_map_check.get("reason") or ""
                ),
                "n_coordinate_rows": _as_text((case or {}).get("n_coordinate_rows")),
                "n_included_studies": _as_text((case or {}).get("n_included_studies")),
                "split_half_status": str((case or {}).get("split_half_status") or ""),
                "split_half_pearson": _as_text(
                    _nested(case, "spatial_metrics", "split_half_z_map", "pearson_union_positive")
                ),
                "split_half_dice": _as_text(
                    _nested(case, "spatial_metrics", "split_half_z_map", "dice_top5_positive")
                ),
                "study_set_precision": _as_text(
                    _metric_field(contract.get("study_set_f1"), "precision")
                ),
                "study_set_recall": _as_text(
                    _metric_field(contract.get("study_set_f1"), "recall")
                ),
                "study_set_f1": _as_text(_metric_field(contract.get("study_set_f1"), "f1")),
                "local_study_set_precision": _as_text(
                    _metric_field(contract.get("local_study_set_f1"), "precision")
                ),
                "local_study_set_recall": _as_text(
                    _metric_field(contract.get("local_study_set_f1"), "recall")
                ),
                "local_study_set_f1": _as_text(
                    _metric_field(contract.get("local_study_set_f1"), "f1")
                ),
                "coordinate_precision": _as_text(
                    _metric_field(contract.get("coordinate_extraction_agreement"), "precision")
                ),
                "coordinate_recall": _as_text(
                    _metric_field(contract.get("coordinate_extraction_agreement"), "recall")
                ),
                "coordinate_f1": _as_text(
                    _metric_field(contract.get("coordinate_extraction_agreement"), "f1")
                ),
                "coordinate_canonical_precision": _as_text(
                    _metric_field(contract.get("coordinate_canonical_f1"), "precision")
                ),
                "coordinate_canonical_recall": _as_text(
                    _metric_field(contract.get("coordinate_canonical_f1"), "recall")
                ),
                "coordinate_canonical_f1": _as_text(
                    _metric_field(contract.get("coordinate_canonical_f1"), "f1")
                ),
                "spatial_correlation": _as_text(
                    _metric_value(contract.get("ale_map_spatial_correlation"))
                    if contract
                    else spatial_agreement.get("spatial_correlation")
                ),
                "dice_top5": _as_text(
                    _metric_value(contract.get("dice_top5"))
                    if contract
                    else spatial_agreement.get("dice_top5")
                ),
                "control_map_exact_match": _bool_text(
                    _metric_field(contract.get("exact_match_to_pure_nimare"), "all_maps")
                    if contract
                    else control.get("all_maps_exact_match") if isinstance(control, dict) else None
                ),
                "control_coordinate_exact_match": _bool_text(
                    _metric_field(
                        contract.get("exact_match_to_pure_nimare"),
                        "coordinate_table",
                    )
                    if contract
                    else control.get("coordinate_table_exact_match")
                    if isinstance(control, dict)
                    else None
                ),
                "control_included_studies_exact_match": _bool_text(
                    _metric_field(
                        contract.get("exact_match_to_pure_nimare"),
                        "included_studies",
                    )
                    if contract
                    else control.get("included_studies_exact_match")
                    if isinstance(control, dict)
                    else None
                ),
                "provenance_complete_score": _as_text(_metric_score(provenance)),
                "br_call_count": _as_text(
                    trace.get("br_call_count")
                    if trace.get("br_call_count") is not None
                    else provenance.get("br_call_count")
                ),
                "br_trace_retrieved_or_audited_anchor_present": _bool_text(
                    trace.get("retrieved_or_audited_anchor_present")
                )
                if trace
                else "",
                "br_trace_artifact_or_report_consumes_br_result": _bool_text(
                    trace.get("artifact_or_report_consumes_br_result")
                )
                if trace
                else "",
                "br_trace_effective_use_pass": _bool_text(
                    trace.get("br_effective_use_pass")
                )
                if trace
                else "",
                "br_reconciliation_anchor_present": _bool_text(
                    trace.get("br_reconciliation_anchor_present")
                    if trace
                    else br_anchor_contract.get("present")
                ),
                "br_reconciliation_anchor_count": _as_text(
                    trace.get("br_reconciliation_anchor_count")
                    if trace
                    else br_anchor_contract.get("n_anchors")
                ),
                "br_reconciliation_anchor_valid_count": _as_text(
                    trace.get("br_reconciliation_anchor_valid_count")
                    if trace
                    else br_anchor_contract.get("n_valid_anchors")
                ),
                "br_reconciliation_anchor_consumed_count": _as_text(
                    trace.get("br_reconciliation_anchor_consumed_count")
                    if trace
                    else br_anchor_contract.get("n_consumed")
                ),
                "br_reconciliation_anchor_changed_count": _as_text(
                    trace.get("br_reconciliation_anchor_changed_count")
                    if trace
                    else br_anchor_contract.get("n_changed_bundle")
                ),
                "br_reconciliation_anchor_changed_consumed_count": _as_text(
                    trace.get("br_reconciliation_anchor_changed_consumed_count")
                    if trace
                    else br_anchor_contract.get("n_changed_consumed")
                ),
                "br_reconciliation_anchor_pass": _bool_text(
                    trace.get("br_reconciliation_anchor_pass")
                    if trace
                    else br_anchor_contract.get("pass")
                ),
                "local_identifier_coverage": _as_text(
                    reconciliation.get("local_identifier_coverage")
                ),
                "public_identifier_coverage": _as_text(
                    reconciliation.get("public_identifier_coverage")
                ),
                "source_provenance_coverage": _as_text(
                    reconciliation.get("source_provenance_coverage")
                ),
                "sample_size_coverage": _as_text(
                    reconciliation.get("sample_size_coverage")
                ),
                "normalization_coordinate_parseability": _as_text(
                    normalized_coordinates.get("coordinate_parseability")
                ),
                "normalization_public_identifier_coverage": _as_text(
                    normalized_studies.get("public_identifier_coverage")
                ),
                "normalization_source_provenance_coverage": _as_text(
                    normalized_studies.get("source_provenance_coverage")
                ),
                "normalization_repairs": _as_text(normalization_delta.get("n_repairs")),
                "claim_consistency_score": _as_text(_metric_score(claim)),
                "failure_diagnosis_quality_score": _as_text(_metric_score(failure)),
                "metric_contract": _json_text(contract),
                "deterministic_artifact": _json_text(deterministic),
                "normalization": _json_text(normalization),
                "br_anchor_trace_summary": _json_text(trace),
                "correct": _bool_text(correct),
            }
        )
    return rows


def export_rows(
    *,
    run_dir: Path,
    comparison_summary: Path,
    output_csv: Path,
    cases_path: Path = DEFAULT_CASES_PATH,
    conditions_path: Path = DEFAULT_CONDITIONS_PATH,
) -> list[dict[str, str]]:
    summary = _read_json(comparison_summary)
    records = _load_records(run_dir)
    case_meta = _load_case_metadata(cases_path)
    condition_meta = _load_condition_metadata(conditions_path)
    comparison_cases = _comparison_case_map(summary)
    rows: list[dict[str, str]] = []
    for record in records:
        rows.extend(
            _row_from_record(
                record,
                run_name=run_dir.name,
                case_meta=case_meta,
                condition_meta=condition_meta,
                comparison_cases=comparison_cases,
            )
        )
    write_csv(output_csv, rows)
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--comparison-summary", type=Path, default=None)
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--conditions", type=Path, default=DEFAULT_CONDITIONS_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    comparison_summary = args.comparison_summary or (
        args.run_dir / "evaluation_v2" / "layer_b_comparison_summary.json"
    )
    output_csv = args.output_csv or (
        args.run_dir / f"{args.run_dir.name}_case_condition_rows_v2.csv"
    )
    rows = export_rows(
        run_dir=args.run_dir,
        comparison_summary=comparison_summary,
        output_csv=output_csv,
        cases_path=args.cases,
        conditions_path=args.conditions,
    )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "output_csv": str(output_csv),
                "comparison_summary": str(comparison_summary),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
