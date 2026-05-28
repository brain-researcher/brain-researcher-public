#!/usr/bin/env python3
"""Build a focused review pack for one task-panel drift transition."""

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
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--old-task-id", type=str, required=True)
    parser.add_argument("--current-target-id", type=str, required=True)
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
        "mapping_original",
        "paper_id",
        "claim_id",
        "run_id",
        "old_task_id",
        "current_target_id",
        "onvoc_label",
        "current_target_label",
        "paper_title",
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = args.input_jsonl.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        row
        for row in _iter_jsonl(input_path)
        if str(row.get("old_task_id") or "").strip() == args.old_task_id
        and str(row.get("current_target_id") or "").strip() == args.current_target_id
    ]
    rows.sort(
        key=lambda row: (
            str(row.get("mapping_original") or ""),
            str(row.get("paper_id") or ""),
            str(row.get("claim_id") or ""),
        )
    )

    mapping_counts = Counter(str(row.get("mapping_original") or "").strip() for row in rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "input_jsonl_path": str(input_path),
        "old_task_id": args.old_task_id,
        "current_target_id": args.current_target_id,
        "counts": {
            "transition_rows": len(rows),
        },
        "counts_by_mapping_original": mapping_counts.most_common(50),
        "artifacts": {
            "transition_review_pack_jsonl": str(output_dir / "transition_review_pack.jsonl"),
            "transition_review_pack_tsv": str(output_dir / "transition_review_pack.tsv"),
            "transition_review_summary_json": str(output_dir / "transition_review_summary.json"),
        },
    }

    _write_jsonl(output_dir / "transition_review_pack.jsonl", rows)
    _write_tsv(output_dir / "transition_review_pack.tsv", rows)
    (output_dir / "transition_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
