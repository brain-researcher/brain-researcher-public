#!/usr/bin/env python3
"""Build an adjudication pack for substantive title-only concept holds."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NETWORK_OR_ANALYSIS_TOKENS = (
    "connectivity",
    "network",
    "networks",
    "activation",
    "overactivation",
    "responses",
    "response",
    "analysis",
    "correlation",
    "hurst exponent",
)
CLINICAL_OR_BIOMARKER_TOKENS = (
    "disease",
    "disorder",
    "traits",
    "trait",
    "amyloid",
    "receptor",
    "binding",
    "availability",
    "consumption",
    "gait speed",
    "aggression",
)
REGENERATE_SPECIFIC_CONCEPT_TOKENS = (
    "understanding",
    "learning",
    "bias",
    "regulation",
    "exploration",
    "exploitation",
    "knowledge",
    "flexibility",
    "perception",
    "viewpoint",
    "concepts",
    "performance",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-rows", type=Path, required=True)
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
        "adjudication_bucket",
        "proposed_action",
        "bucket_reason",
        "paper_id",
        "paper_title",
        "target_id",
        "target_label",
        "claim_id",
        "run_id",
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


def classify_concept_hold_row(row: dict[str, Any]) -> tuple[str, str, str]:
    label = str(row.get("target_label") or "").strip().lower()
    if any(token in label for token in NETWORK_OR_ANALYSIS_TOKENS):
        return (
            "candidate_only_composite_or_analysis",
            "reroute_candidate_only",
            "network_or_analysis_composite_title_concept",
        )
    if any(token in label for token in CLINICAL_OR_BIOMARKER_TOKENS):
        return (
            "scope_review_clinical_or_biomarker",
            "manual_scope_review",
            "clinical_trait_or_biomarker_title_concept",
        )
    if any(token in label for token in REGENERATE_SPECIFIC_CONCEPT_TOKENS):
        return (
            "specific_concept_regeneration",
            "regenerate_non_title_concept",
            "specific_cognitive_or_behavioral_concept",
        )
    return (
        "manual_concept_review",
        "manual_concept_review",
        "concept_title_row_needs_manual_semantic_review",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    hold_rows_path = args.hold_rows.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    adjudication_rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()

    for row in _iter_jsonl(hold_rows_path):
        if str(row.get("review_bucket") or "").strip() != "substantive_concept_hold":
            continue
        bucket, action, reason = classify_concept_hold_row(row)
        adjudicated = {
            "paper_id": str(row.get("paper_id") or "").strip(),
            "paper_title": str(row.get("paper_title") or "").strip(),
            "claim_id": str(row.get("claim_id") or "").strip(),
            "run_id": str(row.get("run_id") or "").strip(),
            "target_type": str(row.get("target_type") or "").strip(),
            "target_id": str(row.get("target_id") or "").strip(),
            "target_label": str(row.get("target_label") or "").strip(),
            "adjudication_bucket": bucket,
            "proposed_action": action,
            "bucket_reason": reason,
            "source_review_bucket": "substantive_concept_hold",
            "source_bucket_reason": str(row.get("bucket_reason") or "").strip(),
            "evidence_section": str(row.get("evidence_section") or "").strip(),
            "mapping_confidence": float(row.get("mapping_confidence") or 0.0),
            "claim_strength": float(row.get("claim_strength") or 0.0),
            "method_rigor": float(row.get("method_rigor") or 0.0),
            "rejection_reasons": list(row.get("rejection_reasons") or []),
            "review_questions": [
                "Is this concept specific enough to merit non-title regeneration?",
                "Would a regenerated abstract/body quote still represent a benchmark-grade target rather than a candidate-only concept?",
                "Should this row stay in benchmark review, move to candidate-only, or be excluded entirely?",
            ],
        }
        adjudication_rows.append(adjudicated)
        bucket_counts[bucket] += 1
        action_counts[action] += 1

    adjudication_rows.sort(
        key=lambda row: (
            row["adjudication_bucket"],
            row["target_label"].lower(),
            row["paper_id"],
        )
    )

    _write_jsonl(output_dir / "concept_hold_adjudication_pack.jsonl", adjudication_rows)
    _write_tsv(output_dir / "concept_hold_adjudication_pack.tsv", adjudication_rows)
    for bucket in sorted(bucket_counts):
        bucket_rows = [row for row in adjudication_rows if row["adjudication_bucket"] == bucket]
        _write_jsonl(output_dir / f"{bucket}.jsonl", bucket_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "hold_rows_path": str(hold_rows_path),
        "counts": {
            "rows_total": len(adjudication_rows),
            **{bucket: bucket_counts[bucket] for bucket in sorted(bucket_counts)},
            **{f"action_{action}": action_counts[action] for action in sorted(action_counts)},
        },
        "artifacts": {
            "adjudication_pack_jsonl": str(output_dir / "concept_hold_adjudication_pack.jsonl"),
            "adjudication_pack_tsv": str(output_dir / "concept_hold_adjudication_pack.tsv"),
            "summary_json": str(output_dir / "concept_hold_adjudication_summary.json"),
        },
    }
    (output_dir / "concept_hold_adjudication_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
