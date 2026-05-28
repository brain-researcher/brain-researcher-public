#!/usr/bin/env python3
"""Build a policy pack for biomarker/receptor scope-review rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGE_NAME = "balanced_biomarker_policy"
EXPECTED_SCOPE_LANE = "biomarker_receptor"
MEASURABLE_BIOMARKER_TOKENS = (
    "receptor",
    "binding",
    "availability",
)
PREFER_SECTIONS = ["abstract", "methods", "results", "discussion"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--biomarker-rows", type=Path, required=True)
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


def _write_tsv(
    path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]
) -> None:
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


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return []


def _matches_scope_contract(row: dict[str, Any]) -> tuple[bool, str | None]:
    lane = str(row.get("lane") or "").strip()
    if lane and lane != EXPECTED_SCOPE_LANE:
        return False, "skipped_non_biomarker_lane"
    target_type = str(row.get("target_type") or "").strip()
    if target_type and target_type != "Concept":
        return False, "skipped_non_concept_target"
    return True, None


def _source_stage(row: dict[str, Any]) -> str:
    explicit = str(row.get("source_stage") or "").strip()
    if explicit:
        return explicit
    if str(row.get("lane") or "").strip():
        return "balanced_scope_review_split"
    return "legacy_scope_review_input"


def classify_biomarker_row(row: dict[str, Any]) -> tuple[str, str, str]:
    label = str(row.get("target_label") or "").strip().lower()
    if any(token in label for token in MEASURABLE_BIOMARKER_TOKENS):
        return (
            "measurable_biomarker_regeneration",
            "regenerate_non_title_concept",
            "measurable_biomarker_or_receptor_surface_form",
        )
    return (
        "broad_biomarker_hold",
        "manual_scope_review_or_candidate_only_policy",
        "broad_biomarker_scope_hold",
    )


def _policy_row(
    row: dict[str, Any],
    *,
    source_path: Path,
    bucket: str,
    action: str,
    bucket_reason: str,
) -> dict[str, Any]:
    return {
        "paper_id": str(row.get("paper_id") or "").strip(),
        "paper_title": str(row.get("paper_title") or "").strip(),
        "claim_id": str(row.get("claim_id") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "target_type": str(row.get("target_type") or "").strip(),
        "target_id": str(row.get("target_id") or "").strip(),
        "target_label": str(row.get("target_label") or "").strip(),
        "evidence_section": str(
            row.get("evidence_section") or row.get("source_evidence_section") or ""
        ).strip(),
        "mapping_confidence": _coerce_float(row.get("mapping_confidence")),
        "claim_strength": _coerce_float(row.get("claim_strength")),
        "method_rigor": _coerce_float(row.get("method_rigor")),
        "rejection_reasons": _coerce_str_list(row.get("rejection_reasons")),
        "source_review_bucket": str(row.get("source_review_bucket") or "").strip(),
        "source_bucket_reason": str(
            row.get("source_bucket_reason") or row.get("bucket_reason") or ""
        ).strip(),
        "scope_review_bucket": str(
            row.get("lane") or row.get("source_review_bucket") or ""
        ).strip(),
        "scope_review_bucket_reason": str(
            row.get("lane_reason")
            or row.get("source_bucket_reason")
            or row.get("bucket_reason")
            or ""
        ).strip(),
        "scope_review_recommended_next_action": str(
            row.get("recommended_next_action") or ""
        ).strip(),
        "source_stage": _source_stage(row),
        "source_artifact_path": str(source_path),
        "policy_stage": STAGE_NAME,
        "policy_bucket": bucket,
        "policy_action": action,
        "recommended_next_action": action,
        "bucket_reason": bucket_reason,
    }


def _regeneration_row(policy_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": str(policy_row.get("paper_id") or "").strip(),
        "paper_title": str(policy_row.get("paper_title") or "").strip(),
        "claim_id": str(policy_row.get("claim_id") or "").strip(),
        "run_id": str(policy_row.get("run_id") or "").strip(),
        "target_type": str(policy_row.get("target_type") or "").strip(),
        "target_id": str(policy_row.get("target_id") or "").strip(),
        "target_label": str(policy_row.get("target_label") or "").strip(),
        "prefer_sections": list(PREFER_SECTIONS),
        "source_review_bucket": str(policy_row.get("policy_bucket") or "").strip(),
        "source_bucket_reason": str(policy_row.get("bucket_reason") or "").strip(),
        "upstream_review_bucket": str(
            policy_row.get("source_review_bucket") or ""
        ).strip(),
        "upstream_bucket_reason": str(
            policy_row.get("source_bucket_reason") or ""
        ).strip(),
        "scope_review_bucket": str(policy_row.get("scope_review_bucket") or "").strip(),
        "scope_review_bucket_reason": str(
            policy_row.get("scope_review_bucket_reason") or ""
        ).strip(),
        "scope_review_recommended_next_action": str(
            policy_row.get("scope_review_recommended_next_action") or ""
        ).strip(),
        "source_stage": STAGE_NAME,
        "source_artifact_path": str(
            policy_row.get("source_artifact_path") or ""
        ).strip(),
        "source_evidence_section": str(
            policy_row.get("evidence_section") or ""
        ).strip(),
        "mapping_confidence": _coerce_float(policy_row.get("mapping_confidence")),
        "claim_strength": _coerce_float(policy_row.get("claim_strength")),
        "method_rigor": _coerce_float(policy_row.get("method_rigor")),
        "regeneration_bucket": str(policy_row.get("policy_bucket") or "").strip(),
        "policy_bucket": str(policy_row.get("policy_bucket") or "").strip(),
        "policy_action": str(policy_row.get("policy_action") or "").strip(),
        "recommended_next_action": str(
            policy_row.get("recommended_next_action") or ""
        ).strip(),
        "bucket_reason": str(policy_row.get("bucket_reason") or "").strip(),
        "proposed_action": str(policy_row.get("policy_action") or "").strip(),
        "rejection_reasons": _coerce_str_list(policy_row.get("rejection_reasons")),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    biomarker_rows = args.biomarker_rows.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    policy_rows: list[dict[str, Any]] = []
    regeneration_rows: list[dict[str, Any]] = []
    hold_rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    skipped_counts: Counter[str] = Counter()

    for row in _iter_jsonl(biomarker_rows):
        matches_contract, skip_reason = _matches_scope_contract(row)
        if not matches_contract:
            skipped_counts[str(skip_reason)] += 1
            continue
        bucket, action, bucket_reason = classify_biomarker_row(row)
        payload = _policy_row(
            row,
            source_path=biomarker_rows,
            bucket=bucket,
            action=action,
            bucket_reason=bucket_reason,
        )
        policy_rows.append(payload)
        bucket_counts[bucket] += 1
        action_counts[action] += 1
        if action == "regenerate_non_title_concept":
            regeneration_rows.append(_regeneration_row(payload))
        else:
            hold_rows.append(payload)

    policy_rows.sort(
        key=lambda row: (
            str(row["policy_bucket"]),
            str(row["target_label"]).lower(),
            str(row["paper_id"]),
        )
    )
    regeneration_rows.sort(
        key=lambda row: (row["target_label"].lower(), row["paper_id"])
    )
    hold_rows.sort(
        key=lambda row: (
            str(row["policy_bucket"]),
            str(row["target_label"]).lower(),
            str(row["paper_id"]),
        )
    )

    _write_jsonl(output_dir / "biomarker_policy_pack.jsonl", policy_rows)
    _write_tsv(
        output_dir / "biomarker_policy_pack.tsv",
        policy_rows,
        [
            "policy_bucket",
            "recommended_next_action",
            "bucket_reason",
            "paper_id",
            "paper_title",
            "target_id",
            "target_label",
            "claim_id",
            "run_id",
            "scope_review_bucket",
            "scope_review_bucket_reason",
            "source_review_bucket",
            "source_bucket_reason",
        ],
    )
    _write_jsonl(
        output_dir / "measurable_biomarker_regeneration.jsonl", regeneration_rows
    )
    _write_jsonl(output_dir / "broad_biomarker_hold.jsonl", hold_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "biomarker_rows_path": str(biomarker_rows),
        "counts": {
            "rows_total": len(policy_rows),
            **{bucket: bucket_counts[bucket] for bucket in sorted(bucket_counts)},
            **{
                f"action_{action}": action_counts[action]
                for action in sorted(action_counts)
            },
            **{
                skip_reason: skipped_counts[skip_reason]
                for skip_reason in sorted(skipped_counts)
            },
        },
        "artifacts": {
            "policy_pack_jsonl": str(output_dir / "biomarker_policy_pack.jsonl"),
            "regeneration_rows_jsonl": str(
                output_dir / "measurable_biomarker_regeneration.jsonl"
            ),
            "hold_rows_jsonl": str(output_dir / "broad_biomarker_hold.jsonl"),
            "summary_json": str(output_dir / "biomarker_policy_summary.json"),
        },
    }
    (output_dir / "biomarker_policy_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
