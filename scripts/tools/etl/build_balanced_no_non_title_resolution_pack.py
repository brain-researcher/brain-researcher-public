#!/usr/bin/env python3
"""Split no-non-title residual rows into fuller-text retry vs retire/candidate-only."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NO_NON_TITLE_BUCKETS = {
    "task_region_unresolved_no_non_title_text",
    "specific_concept_unresolved_no_non_title_text",
    "biomarker_unresolved_no_non_title_text",
}
SPECIFIC_REGION_RETRY_IDS = {
    "region:anterior_cingulate_cortex",
    "region:human_amygdala",
    "region:intraparietal_sulcus",
    "region:posterior_lateral_frontal_cortex",
    "region:primary_motor_cortex",
}
RETIRE_TASK_IDS = {
    "task:gambling_availability_during_sports_picture_exposure",
}
GENERIC_REGION_RETIRE_IDS = {
    "region:adolescent_brain",
    "region:brain_structure",
    "region:frontal_lobe",
    "region:intrinsic_functional_brain_network",
    "region:neural_circuits",
    "region:thalamic_volume",
    "region:ventral_attention_system",
}
SPECIFIC_CONCEPT_RETRY_IDS = {
    "concept:dance_learning",
    "concept:mental_flexibility",
    "concept:viewpoint_tolerance",
}
CANDIDATE_ONLY_CONCEPT_IDS = {
    "concept:emotion_regulation",
    "concept:knowledge_acquisition",
    "concept:temporal_concepts",
    "concept:time_perception",
}
MEASURABLE_BIOMARKER_TOKENS = (
    "receptor",
    "binding",
    "availability",
)
PREFER_SECTIONS = ["discussion", "results", "methods", "abstract"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-ledger", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write(
                "\t".join(
                    str(row.get(column, "")).replace("\t", " ").replace("\n", " ")
                    for column in columns
                )
                + "\n"
            )


def _normalized_target_type(row: dict[str, Any]) -> str:
    target_type = str(row.get("target_type") or "").strip()
    if target_type:
        return target_type
    target_id = str(row.get("target_id") or "").strip()
    if target_id.startswith("task:"):
        return "Task"
    if target_id.startswith("region:"):
        return "Region"
    if target_id.startswith("concept:"):
        return "Concept"
    return ""


def _normalized_label(row: dict[str, Any]) -> str:
    return str(row.get("target_label") or "").strip().lower()


def classify_resolution(row: dict[str, Any]) -> tuple[str, str]:
    ledger_bucket = str(row.get("ledger_bucket") or "").strip()
    target_id = str(row.get("target_id") or "").strip()
    target_type = _normalized_target_type(row)
    target_label = _normalized_label(row)

    if target_id in RETIRE_TASK_IDS:
        return "retire_benchmark", "situational_task_label_not_worth_fulltext_retry"
    if target_id in SPECIFIC_REGION_RETRY_IDS or target_id.startswith("task:"):
        return "fulltext_retry", "specific_task_or_region_needs_fuller_text"
    if target_id in GENERIC_REGION_RETIRE_IDS:
        return "retire_benchmark", "generic_region_not_worth_fulltext_retry"
    if target_id in SPECIFIC_CONCEPT_RETRY_IDS:
        return "fulltext_retry", "specific_concept_needs_fuller_text"
    if target_id in CANDIDATE_ONLY_CONCEPT_IDS:
        return "candidate_only", "broad_concept_better_suited_for_candidate_only"
    if target_id == "concept:serotonin_1a_receptor_binding":
        return "fulltext_retry", "specific_biomarker_needs_fuller_text"
    if ledger_bucket == "biomarker_unresolved_no_non_title_text":
        if any(token in target_label for token in MEASURABLE_BIOMARKER_TOKENS):
            return (
                "fulltext_retry",
                "measurable_biomarker_surface_form_needs_fuller_text",
            )
        return "scope_review", "broad_biomarker_requires_scope_review"
    if target_type == "Task":
        return "fulltext_retry", "task_target_should_get_fulltext_retry"
    if target_type == "Region":
        return "retire_benchmark", "unclassified_region_defaults_to_retire"
    if target_type == "Concept":
        return "candidate_only", "unclassified_concept_defaults_to_candidate_only"
    return "retire_benchmark", "unclassified_target_defaults_to_retire"


def _recommended_action(resolution: str) -> str:
    if resolution == "fulltext_retry":
        return "retry_with_fulltext_harvest"
    if resolution == "candidate_only":
        return "move_to_candidate_only_lane"
    if resolution == "scope_review":
        return "route_to_scope_review_policy"
    return "retire_from_benchmark_followup"


def _resolution_payload(row: dict[str, Any], *, resolution: str, reason: str) -> dict[str, Any]:
    target_type = _normalized_target_type(row)
    payload = {
        "paper_id": str(row.get("paper_id") or "").strip(),
        "paper_title": str(row.get("paper_title") or "").strip(),
        "claim_id": str(row.get("claim_id") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "target_type": target_type,
        "target_id": str(row.get("target_id") or "").strip(),
        "target_label": str(row.get("target_label") or "").strip(),
        "evidence_section": str(row.get("evidence_section") or "").strip(),
        "mapping_confidence": float(row.get("mapping_confidence") or 0.0),
        "claim_strength": float(row.get("claim_strength") or 0.0),
        "method_rigor": float(row.get("method_rigor") or 0.0),
        "rejection_reasons": list(row.get("rejection_reasons") or []),
        "entry_kind": str(row.get("entry_kind") or "").strip(),
        "ledger_bucket": str(row.get("ledger_bucket") or "").strip(),
        "source_ledger_bucket": str(row.get("ledger_bucket") or "").strip(),
        "source_stage": str(row.get("source_stage") or "").strip(),
        "source_artifact_path": str(row.get("source_artifact_path") or "").strip(),
        "source_review_bucket": str(row.get("source_review_bucket") or "").strip(),
        "source_bucket_reason": str(row.get("source_bucket_reason") or "").strip(),
        "source_blocking_reason": str(row.get("blocking_reason") or "").strip(),
        "source_retry_mode": str(row.get("retry_mode") or "").strip(),
        "source_reason": str(row.get("source_reason") or "").strip(),
        "source_recommended_next_action": str(
            row.get("recommended_next_action") or ""
        ).strip(),
        "resolution_bucket": resolution,
        "resolution_reason": reason,
        "recommended_next_action": _recommended_action(resolution),
    }
    if resolution == "fulltext_retry":
        payload["prefer_sections"] = list(PREFER_SECTIONS)
        payload["proposed_action"] = "retry_with_fulltext_harvest"
        payload["bucket_reason"] = reason
    elif resolution == "candidate_only":
        payload["proposed_action"] = "reroute_candidate_only"
        payload["adjudication_bucket"] = "no_non_title_candidate_only"
        payload["bucket_reason"] = reason
    elif resolution == "scope_review":
        payload["proposed_action"] = "route_to_scope_review_policy"
        payload["adjudication_bucket"] = "no_non_title_scope_review"
        payload["bucket_reason"] = reason
    else:
        payload["proposed_action"] = "retire_benchmark_followup"
        payload["adjudication_bucket"] = "no_non_title_retire_benchmark"
        payload["bucket_reason"] = reason
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    residual_ledger = args.residual_ledger.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    decision_counts: Counter[str] = Counter()

    for row in _iter_jsonl(residual_ledger):
        bucket = str(row.get("ledger_bucket") or "").strip()
        if bucket not in NO_NON_TITLE_BUCKETS:
            continue
        resolution, reason = classify_resolution(row)
        payload = _resolution_payload(row, resolution=resolution, reason=reason)
        rows.append(payload)
        decision_counts[resolution] += 1

    rows.sort(key=lambda row: (row["resolution_bucket"], row["target_label"].lower(), row["paper_id"]))

    _write_jsonl(output_dir / "no_non_title_resolution_pack.jsonl", rows)
    _write_tsv(
        output_dir / "no_non_title_resolution_pack.tsv",
        rows,
        [
            "resolution_bucket",
            "resolution_reason",
            "paper_id",
            "paper_title",
            "target_type",
            "target_id",
            "target_label",
            "proposed_action",
            "recommended_next_action",
            "ledger_bucket",
            "source_review_bucket",
            "source_bucket_reason",
            "source_stage",
            "source_artifact_path",
            "source_blocking_reason",
        ],
    )
    for resolution in sorted(decision_counts):
        _write_jsonl(
            output_dir / f"{resolution}.jsonl",
            [row for row in rows if row["resolution_bucket"] == resolution],
        )

    summary = {
        "generated_at": _utc_now_iso(),
        "residual_ledger_path": str(residual_ledger),
        "counts": {
            "rows_total": len(rows),
            **{resolution: decision_counts[resolution] for resolution in sorted(decision_counts)},
        },
        "artifacts": {
            "resolution_pack_jsonl": str(output_dir / "no_non_title_resolution_pack.jsonl"),
            "resolution_pack_tsv": str(output_dir / "no_non_title_resolution_pack.tsv"),
            "summary_json": str(output_dir / "no_non_title_resolution_summary.json"),
        },
    }
    (output_dir / "no_non_title_resolution_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
