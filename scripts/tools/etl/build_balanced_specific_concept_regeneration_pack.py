#!/usr/bin/env python3
"""Build a bounded non-title regeneration pack for specific concept holds."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PREFER_SECTIONS = ["abstract", "methods", "results", "discussion"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adjudication-rows", type=Path, required=True)
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
        "paper_id",
        "paper_title",
        "target_type",
        "target_id",
        "target_label",
        "claim_id",
        "run_id",
        "bucket_reason",
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


def _pack_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": str(row.get("paper_id") or "").strip(),
        "paper_title": str(row.get("paper_title") or "").strip(),
        "claim_id": str(row.get("claim_id") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "target_type": str(row.get("target_type") or "").strip(),
        "target_id": str(row.get("target_id") or "").strip(),
        "target_label": str(row.get("target_label") or "").strip(),
        "prefer_sections": list(PREFER_SECTIONS),
        "source_review_bucket": str(row.get("source_review_bucket") or "").strip(),
        "source_bucket_reason": str(row.get("source_bucket_reason") or "").strip(),
        "regeneration_bucket": str(row.get("adjudication_bucket") or "").strip(),
        "bucket_reason": str(row.get("bucket_reason") or "").strip(),
        "rejection_reasons": list(row.get("rejection_reasons") or []),
        "review_questions": list(row.get("review_questions") or []),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    adjudication_rows = args.adjudication_rows.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pack_rows = [
        _pack_row(row)
        for row in _iter_jsonl(adjudication_rows)
        if str(row.get("proposed_action") or "").strip() == "regenerate_non_title_concept"
    ]
    pack_rows.sort(key=lambda row: (row["target_label"].lower(), row["paper_id"]))

    pack_path = output_dir / "specific_concept_regeneration_pack.jsonl"
    _write_jsonl(pack_path, pack_rows)
    _write_tsv(output_dir / "specific_concept_regeneration_pack.tsv", pack_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "adjudication_rows_path": str(adjudication_rows),
        "counts": {
            "rows_total": len(pack_rows),
        },
        "artifacts": {
            "regeneration_pack_jsonl": str(pack_path),
            "regeneration_pack_tsv": str(output_dir / "specific_concept_regeneration_pack.tsv"),
            "summary_json": str(output_dir / "specific_concept_regeneration_pack_summary.json"),
        },
    }
    (output_dir / "specific_concept_regeneration_pack_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
