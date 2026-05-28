#!/usr/bin/env python3
"""Split scope-review concept holds into disease, biomarker, and phenotype lanes."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DISEASE_OR_DIAGNOSIS_TOKENS = (
    "disease",
    "disorder",
)
BIOMARKER_OR_RECEPTOR_TOKENS = (
    "amyloid",
    "receptor",
    "binding",
    "availability",
)
BEHAVIORAL_PHENOTYPE_TOKENS = (
    "aggression",
    "traits",
    "trait",
    "gait speed",
    "consumption",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-review-rows", type=Path, required=True)
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


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = [
        "lane",
        "lane_reason",
        "recommended_next_action",
        "paper_id",
        "paper_title",
        "target_id",
        "target_label",
        "claim_id",
        "run_id",
        "source_review_bucket",
        "source_bucket_reason",
        "source_ledger_bucket",
        "source_resolution_bucket",
    ]
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


def classify_scope_review_row(row: dict[str, Any]) -> tuple[str, str, str]:
    label = str(row.get("target_label") or "").strip().lower()
    if any(token in label for token in BIOMARKER_OR_RECEPTOR_TOKENS):
        return (
            "biomarker_receptor",
            "biomarker_or_receptor_surface_form",
            "manual_biomarker_scope_review",
        )
    if any(token in label for token in DISEASE_OR_DIAGNOSIS_TOKENS):
        return (
            "disease_diagnosis",
            "disease_or_diagnosis_surface_form",
            "manual_disease_scope_review",
        )
    if any(token in label for token in BEHAVIORAL_PHENOTYPE_TOKENS):
        return (
            "behavioral_phenotype",
            "behavioral_or_clinical_phenotype_surface_form",
            "manual_behavioral_scope_review",
        )
    return (
        "behavioral_phenotype",
        "behavioral_phenotype_default_fallback",
        "manual_behavioral_scope_review",
    )


def _source_review_bucket(row: dict[str, Any]) -> str:
    return str(
        row.get("adjudication_bucket")
        or row.get("source_review_bucket")
        or row.get("policy_bucket")
        or row.get("resolution_bucket")
        or row.get("ledger_bucket")
        or ""
    ).strip()


def _source_bucket_reason(row: dict[str, Any]) -> str:
    return str(
        row.get("bucket_reason")
        or row.get("source_bucket_reason")
        or row.get("policy_action")
        or row.get("resolution_reason")
        or row.get("blocking_reason")
        or ""
    ).strip()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    scope_review_rows = args.scope_review_rows.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    split_rows: list[dict[str, Any]] = []
    lane_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()

    for row in _iter_jsonl(scope_review_rows):
        lane, lane_reason, action = classify_scope_review_row(row)
        payload = {
            "paper_id": str(row.get("paper_id") or "").strip(),
            "paper_title": str(row.get("paper_title") or "").strip(),
            "claim_id": str(row.get("claim_id") or "").strip(),
            "run_id": str(row.get("run_id") or "").strip(),
            "target_type": str(row.get("target_type") or "").strip(),
            "target_id": str(row.get("target_id") or "").strip(),
            "target_label": str(row.get("target_label") or "").strip(),
            "source_review_bucket": _source_review_bucket(row),
            "source_bucket_reason": _source_bucket_reason(row),
            "evidence_section": str(row.get("evidence_section") or "").strip(),
            "mapping_confidence": float(row.get("mapping_confidence") or 0.0),
            "claim_strength": float(row.get("claim_strength") or 0.0),
            "method_rigor": float(row.get("method_rigor") or 0.0),
            "rejection_reasons": list(row.get("rejection_reasons") or []),
            "source_stage": str(row.get("source_stage") or "").strip(),
            "source_artifact_path": str(
                row.get("source_artifact_path") or scope_review_rows
            ).strip(),
            "source_ledger_bucket": str(row.get("ledger_bucket") or "").strip(),
            "source_resolution_bucket": str(row.get("resolution_bucket") or "").strip(),
            "source_resolution_reason": str(row.get("resolution_reason") or "").strip(),
            "source_retry_mode": str(row.get("retry_mode") or "").strip(),
            "source_recommended_next_action": str(
                row.get("recommended_next_action") or ""
            ).strip(),
            "lane": lane,
            "lane_reason": lane_reason,
            "recommended_next_action": action,
        }
        split_rows.append(payload)
        lane_counts[lane] += 1
        action_counts[action] += 1

    split_rows.sort(key=lambda row: (row["lane"], row["target_label"].lower(), row["paper_id"]))

    _write_jsonl(output_dir / "scope_review_split_pack.jsonl", split_rows)
    _write_tsv(output_dir / "scope_review_split_pack.tsv", split_rows)
    for lane in sorted(lane_counts):
        lane_rows = [row for row in split_rows if row["lane"] == lane]
        _write_jsonl(output_dir / f"lane_{lane}.jsonl", lane_rows)
        _write_tsv(output_dir / f"lane_{lane}.tsv", lane_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "scope_review_rows_path": str(scope_review_rows),
        "counts": {
            "rows_total": len(split_rows),
            **{lane: lane_counts[lane] for lane in sorted(lane_counts)},
            **{
                f"action_{action}": action_counts[action]
                for action in sorted(action_counts)
            },
        },
        "artifacts": {
            "split_pack_jsonl": str(output_dir / "scope_review_split_pack.jsonl"),
            "split_pack_tsv": str(output_dir / "scope_review_split_pack.tsv"),
            "summary_json": str(output_dir / "scope_review_split_summary.json"),
        },
    }
    (output_dir / "scope_review_split_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
