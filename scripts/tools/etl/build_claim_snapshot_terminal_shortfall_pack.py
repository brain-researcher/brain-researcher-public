#!/usr/bin/env python3
"""Build a compact terminal +3 shortfall pack for the next claim snapshot cut."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRIMARY_CLAIM_IDS = [
    "claim:36440b921722e3394eef114ce3e1be3c",
    "claim:112ab135f7e98e7fef3af9ab0037a729",
    "claim:c1e6f254a408747bef0ff3d56614e4de",
]

RESERVE_CLAIM_IDS = [
    "claim:e0b5a42636c2bf10b5ad1df1fda7fd1d",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v3", type=Path, required=True)
    parser.add_argument(
        "--candidate-jsonl",
        action="append",
        type=Path,
        required=True,
        help="Candidate reviewed packs to source rows from.",
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


def build_outputs(
    snapshot_v3_path: Path,
    candidate_paths: Sequence[Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    snapshot_rows = list(_iter_jsonl(snapshot_v3_path))
    existing_ids = {str(row["source_claim_id"]) for row in snapshot_rows}
    existing_families = {str(row["canonical_claim_id"]) for row in snapshot_rows}

    candidates_by_id: dict[str, dict[str, Any]] = {}
    for candidate_path in candidate_paths:
        for row in _iter_jsonl(candidate_path):
            claim_id = str(row.get("source_claim_id") or "").strip()
            if not claim_id:
                continue
            if claim_id in candidates_by_id:
                continue
            candidates_by_id[claim_id] = {
                **row,
                "candidate_source_path": str(candidate_path),
            }

    primary_rows: list[dict[str, Any]] = []
    for rank, claim_id in enumerate(PRIMARY_CLAIM_IDS, start=1):
        row = candidates_by_id.get(claim_id)
        if row is None:
            raise SystemExit(f"Fail-closed terminal shortfall mismatch: missing {claim_id}")
        if claim_id in existing_ids:
            raise SystemExit(
                f"Fail-closed terminal shortfall mismatch: {claim_id} already exists in snapshot_v3"
            )
        tagged = {
            **row,
            "selected_for_terminal_shortfall": True,
            "terminal_shortfall_rank": rank,
            "terminal_shortfall_reason": "primary_terminal_family_candidate",
            "pack_generated_at": _utc_now_iso(),
        }
        primary_rows.append(tagged)

    reserve_rows: list[dict[str, Any]] = []
    for rank, claim_id in enumerate(RESERVE_CLAIM_IDS, start=1):
        row = candidates_by_id.get(claim_id)
        if row is None:
            raise SystemExit(f"Fail-closed terminal shortfall mismatch: missing reserve {claim_id}")
        if claim_id in existing_ids:
            continue
        tagged = {
            **row,
            "selected_for_terminal_shortfall": False,
            "terminal_shortfall_rank": rank,
            "terminal_shortfall_reason": "reserve_terminal_family_candidate",
            "pack_generated_at": _utc_now_iso(),
        }
        reserve_rows.append(tagged)

    projected_families = set(existing_families) | {
        str(row["canonical_claim_id"]) for row in primary_rows
    }
    target_type_counts = Counter(str(row["target_type"]) for row in primary_rows if row.get("target_type"))

    summary = {
        "generated_at": _utc_now_iso(),
        "source_snapshot_v3": str(snapshot_v3_path),
        "source_candidate_jsonl": [str(path) for path in candidate_paths],
        "counts": {
            "snapshot_v3_families_total": len(existing_families),
            "primary_rows_total": len(primary_rows),
            "primary_new_families_total": len({str(row['canonical_claim_id']) for row in primary_rows}),
            "reserve_rows_total": len(reserve_rows),
            "projected_families_total": len(projected_families),
            "remaining_shortfall_after_primary": max(0, 24 - len(projected_families)),
            "threshold_min_canonical_families": 24,
            "threshold_canonical_families_met_in_projection": len(projected_families) >= 24,
            **{
                f"primary_target_type_{target_type}": count
                for target_type, count in sorted(target_type_counts.items())
            },
        },
    }
    return primary_rows, reserve_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    primary_rows, reserve_rows, summary = build_outputs(
        args.snapshot_v3.expanduser().resolve(),
        [path.expanduser().resolve() for path in args.candidate_jsonl],
    )

    primary_jsonl = output_dir / "terminal_shortfall_pack.jsonl"
    primary_tsv = output_dir / "terminal_shortfall_pack.tsv"
    reserve_jsonl = output_dir / "terminal_shortfall_pack_reserve.jsonl"
    summary_json = output_dir / "terminal_shortfall_pack_summary.json"

    _write_jsonl(primary_jsonl, primary_rows)
    _write_tsv(
        primary_tsv,
        primary_rows,
        [
            "terminal_shortfall_rank",
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "adjudication_bucket",
            "decision_reason",
        ],
    )
    _write_jsonl(reserve_jsonl, reserve_rows)

    summary["artifacts"] = {
        "terminal_shortfall_pack_jsonl": str(primary_jsonl),
        "terminal_shortfall_pack_tsv": str(primary_tsv),
        "terminal_shortfall_pack_reserve_jsonl": str(reserve_jsonl),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
