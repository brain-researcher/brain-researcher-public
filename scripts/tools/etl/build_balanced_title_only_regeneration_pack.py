#!/usr/bin/env python3
"""Build a regeneration pack for title-only Task/Region salvage rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salvage-rows", type=Path, required=True)
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
        "target_type",
        "target_id",
        "target_label",
        "paper_id",
        "paper_title",
        "claim_id",
        "run_id",
        "regeneration_strategy",
        "evidence_requirement",
        "search_query",
        "method_rigor",
        "mapping_confidence",
        "claim_strength",
        "source_review_bucket",
        "source_bucket_reason",
        "source_evidence_section",
        "rejection_reasons",
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


def _search_query(row: dict[str, Any]) -> str:
    title = str(row.get("paper_title") or "").strip()
    label = str(row.get("target_label") or "").strip()
    target_type = str(row.get("target_type") or "").strip().lower()
    if target_type == "region":
        return f"{title} {label} activation connectivity region"
    return f"{title} {label} task paradigm results"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    salvage_path = args.salvage_rows.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    target_type_counts: Counter[str] = Counter()
    skipped_non_title_suppressed = 0
    skipped_invalid_target_type = 0
    for row in _iter_jsonl(salvage_path):
        if str(row.get("review_bucket") or "").strip() != "salvage_task_or_region":
            continue
        rejection_reasons = list(row.get("rejection_reasons") or [])
        if "benchmark_title_only_suppressed" not in rejection_reasons:
            skipped_non_title_suppressed += 1
            continue
        target_type = str(row.get("target_type") or "").strip()
        if target_type not in {"Task", "Region"}:
            skipped_invalid_target_type += 1
            continue
        enriched = {
            "paper_id": str(row.get("paper_id") or "").strip(),
            "paper_title": str(row.get("paper_title") or "").strip(),
            "claim_id": str(row.get("claim_id") or "").strip(),
            "run_id": str(row.get("run_id") or "").strip(),
            "target_type": target_type,
            "target_id": str(row.get("target_id") or "").strip(),
            "target_label": str(row.get("target_label") or "").strip(),
            "regeneration_strategy": "non_title_evidence_regeneration",
            "evidence_requirement": "abstract_or_body_required",
            "suppress_title_only": True,
            "prefer_sections": ["abstract", "methods", "results", "discussion"],
            "search_query": _search_query(row),
            "source_review_bucket": "salvage_task_or_region",
            "source_bucket_reason": str(row.get("bucket_reason") or "").strip(),
            "source_evidence_section": str(row.get("evidence_section") or "").strip(),
            "source_signal_hits": list(row.get("signal_hits") or []),
            "method_rigor": float(row.get("method_rigor") or 0.0),
            "mapping_confidence": float(row.get("mapping_confidence") or 0.0),
            "claim_strength": float(row.get("claim_strength") or 0.0),
            "rejection_reasons": rejection_reasons,
        }
        rows.append(enriched)
        target_type_counts[target_type] += 1

    rows.sort(
        key=lambda row: (
            row["target_type"],
            row["target_label"].lower(),
            row["paper_id"],
        )
    )

    _write_jsonl(output_dir / "title_only_regeneration_pack.jsonl", rows)
    _write_tsv(output_dir / "title_only_regeneration_pack.tsv", rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "salvage_rows_path": str(salvage_path),
        "counts": {
            "regeneration_rows": len(rows),
            "task_rows": target_type_counts["Task"],
            "region_rows": target_type_counts["Region"],
            "skipped_non_title_suppressed": skipped_non_title_suppressed,
            "skipped_invalid_target_type": skipped_invalid_target_type,
        },
        "artifacts": {
            "regeneration_pack_jsonl": str(output_dir / "title_only_regeneration_pack.jsonl"),
            "regeneration_pack_tsv": str(output_dir / "title_only_regeneration_pack.tsv"),
            "summary_json": str(output_dir / "title_only_regeneration_summary.json"),
        },
    }
    (output_dir / "title_only_regeneration_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
