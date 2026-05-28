#!/usr/bin/env python3
"""Build an immediate retry pack from the residual benchmark ledger."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RETRY_NOW_BUCKETS = {
    "task_region_parse_error",
    "task_region_title_only_after_regeneration",
}
PREFER_SECTIONS = ["abstract", "methods", "results", "discussion"]


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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    residual_ledger = args.residual_ledger.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pack_rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()

    for row in _iter_jsonl(residual_ledger):
        bucket = str(row.get("ledger_bucket") or "").strip()
        if bucket not in RETRY_NOW_BUCKETS:
            continue
        payload = {
            "paper_id": str(row.get("paper_id") or "").strip(),
            "paper_title": str(row.get("paper_title") or "").strip(),
            "claim_id": str(row.get("claim_id") or "").strip(),
            "run_id": str(row.get("run_id") or "").strip(),
            "target_type": str(row.get("target_type") or "").strip(),
            "target_id": str(row.get("target_id") or "").strip(),
            "target_label": str(row.get("target_label") or "").strip(),
            "evidence_section": str(row.get("evidence_section") or "").strip(),
            "source_review_bucket": str(row.get("source_review_bucket") or "").strip(),
            "source_bucket_reason": str(row.get("source_bucket_reason") or "").strip(),
            "rejection_reasons": list(row.get("rejection_reasons") or []),
            "mapping_confidence": float(row.get("mapping_confidence") or 0.0),
            "claim_strength": float(row.get("claim_strength") or 0.0),
            "method_rigor": float(row.get("method_rigor") or 0.0),
            "prefer_sections": list(PREFER_SECTIONS),
            "source_ledger_bucket": bucket,
            "source_stage": str(row.get("source_stage") or "").strip(),
            "source_artifact_path": str(row.get("source_artifact_path") or "").strip(),
            "retry_mode": str(row.get("retry_mode") or "").strip(),
            "recommended_next_action": str(row.get("recommended_next_action") or "").strip(),
            "blocking_reason": str(row.get("blocking_reason") or "").strip(),
        }
        pack_rows.append(payload)
        bucket_counts[bucket] += 1

    pack_rows.sort(key=lambda row: (row["source_ledger_bucket"], row["target_label"].lower()))
    _write_jsonl(output_dir / "retry_now_pack.jsonl", pack_rows)
    _write_tsv(
        output_dir / "retry_now_pack.tsv",
        pack_rows,
        [
            "source_ledger_bucket",
            "paper_id",
            "paper_title",
            "claim_id",
            "run_id",
            "target_type",
            "target_id",
            "target_label",
            "recommended_next_action",
            "blocking_reason",
        ],
    )

    summary = {
        "generated_at": _utc_now_iso(),
        "residual_ledger_path": str(residual_ledger),
        "counts": {
            "rows_total": len(pack_rows),
            **{bucket: bucket_counts[bucket] for bucket in sorted(bucket_counts)},
        },
        "artifacts": {
            "retry_now_pack_jsonl": str(output_dir / "retry_now_pack.jsonl"),
            "retry_now_pack_tsv": str(output_dir / "retry_now_pack.tsv"),
            "summary_json": str(output_dir / "retry_now_pack_summary.json"),
        },
    }
    (output_dir / "retry_now_pack_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
