#!/usr/bin/env python3
"""Build a cleanup protection list from task-panel drift adjudication outputs."""

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
    parser.add_argument("--adjudication-pack", type=Path, required=True)
    parser.add_argument(
        "--protect-action",
        action="append",
        dest="protect_actions",
        default=[],
        help="Adjudication action to protect. Can be repeated. Defaults to keep_namespace_replacement.",
    )
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
        "claim_id",
        "paper_id",
        "run_id",
        "protected_action",
        "old_task_id",
        "current_target_id",
        "mapping_original",
        "decision_reason",
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
    adjudication_pack = args.adjudication_pack.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    protect_actions = list(args.protect_actions or ["keep_namespace_replacement"])
    rows = list(_iter_jsonl(adjudication_pack))
    protected_rows = []
    for row in rows:
        action = str(row.get("proposed_action") or "").strip()
        if action not in protect_actions:
            continue
        protected_rows.append(
            {
                "claim_id": str(row.get("claim_id") or "").strip(),
                "paper_id": str(row.get("paper_id") or "").strip(),
                "run_id": str(row.get("run_id") or "").strip(),
                "protected_action": action,
                "old_task_id": str(row.get("old_task_id") or "").strip(),
                "current_target_id": str(row.get("current_target_id") or "").strip(),
                "mapping_original": str(row.get("mapping_original") or "").strip(),
                "decision_reason": str(row.get("decision_reason") or "").strip(),
                "paper_title": str(row.get("paper_title") or "").strip(),
            }
        )

    claim_ids = sorted({row["claim_id"] for row in protected_rows if row["claim_id"]})
    target_counts = Counter(row["current_target_id"] for row in protected_rows)
    reason_counts = Counter(row["decision_reason"] for row in protected_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "adjudication_pack_path": str(adjudication_pack),
        "protect_actions": protect_actions,
        "counts": {
            "protected_rows": len(protected_rows),
            "protected_claim_ids": len(claim_ids),
        },
        "counts_by_current_target_id": target_counts.most_common(20),
        "counts_by_decision_reason": reason_counts.most_common(20),
        "artifacts": {
            "protected_rows_jsonl": str(output_dir / "cleanup_protection_rows.jsonl"),
            "protected_rows_tsv": str(output_dir / "cleanup_protection_rows.tsv"),
            "protected_claim_ids_txt": str(output_dir / "protected_claim_ids.txt"),
            "summary_json": str(output_dir / "cleanup_protection_summary.json"),
        },
    }

    _write_jsonl(output_dir / "cleanup_protection_rows.jsonl", protected_rows)
    _write_tsv(output_dir / "cleanup_protection_rows.tsv", protected_rows)
    (output_dir / "protected_claim_ids.txt").write_text(
        "\n".join(claim_ids) + ("\n" if claim_ids else ""),
        encoding="utf-8",
    )
    (output_dir / "cleanup_protection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
