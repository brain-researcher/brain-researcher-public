#!/usr/bin/env python3
"""Materialize reviewed warning/conflict families for the next gap-closing pass."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRIORITY_CLAIM_IDS = [
    "claim:028fee000c3903b1e325ecc2bbaf4286",
    "claim:bcbf3a40052599b6c72c9a7c38585e6f",
    "claim:7b858b2e0cfe374856830def8df4a681",
    "claim:28fcbcec2470e0c24db5a5fc716143cc",
    "claim:88f2eb8941c9228d0071651be108fa58",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v2", type=Path, required=True)
    parser.add_argument("--prior-adjudication-pack", type=Path, required=True)
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
    snapshot_v2_path: Path,
    prior_adjudication_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    snapshot_rows = [row for row in _iter_jsonl(snapshot_v2_path)]
    snapshot_families = {str(row["canonical_claim_id"]) for row in snapshot_rows}
    snapshot_target_types = {str(row["target_type"]) for row in snapshot_rows if row.get("target_type")}

    snapshot_warning_families = set()
    family_to_snapshot_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot_rows:
        family_to_snapshot_rows[str(row["canonical_claim_id"])].append(row)
    for family_id, members in family_to_snapshot_rows.items():
        polarities = {str(member.get("polarity") or "").strip() for member in members if member.get("polarity")}
        if len(polarities) > 1 or any("warning" in str(member.get("snapshot_role") or "") for member in members):
            snapshot_warning_families.add(family_id)

    prior_rows = [row for row in _iter_jsonl(prior_adjudication_path)]
    prior_by_id = {str(row["source_claim_id"]): row for row in prior_rows}

    minimal_rows: list[dict[str, Any]] = []
    for rank, claim_id in enumerate(PRIORITY_CLAIM_IDS, start=1):
        row = prior_by_id.get(claim_id)
        if row is None:
            raise SystemExit(f"Fail-closed warning/conflict pack mismatch: missing {claim_id}")
        if bool(row.get("snapshot_v1_included")):
            raise SystemExit(
                f"Fail-closed warning/conflict pack mismatch: {claim_id} is already included in prior snapshot"
            )
        tagged = {
            **row,
            "selected_for_gap_pack": True,
            "gap_pack_rank": rank,
            "gap_pack_reason": "reviewed_warning_conflict_family",
            "family_is_new_to_snapshot_v2": str(row["canonical_claim_id"]) not in snapshot_families,
            "would_add_target_type_bucket": str(row["target_type"]) not in snapshot_target_types,
            "warning_or_conflict_family": True,
            "pack_generated_at": _utc_now_iso(),
        }
        minimal_rows.append(tagged)

    reserve_rows = [
        {
            **row,
            "selected_for_gap_pack": False,
            "gap_pack_rank": 0,
            "gap_pack_reason": "reviewed_warning_conflict_reserve",
            "family_is_new_to_snapshot_v2": str(row["canonical_claim_id"]) not in snapshot_families,
            "would_add_target_type_bucket": str(row["target_type"]) not in snapshot_target_types,
            "warning_or_conflict_family": True,
            "pack_generated_at": _utc_now_iso(),
        }
        for row in prior_rows
        if not bool(row.get("snapshot_v1_included"))
        and str(row["source_claim_id"]) not in PRIORITY_CLAIM_IDS
    ]
    reserve_rows.sort(key=lambda row: row["source_claim_id"])

    projected_families = set(snapshot_families) | {
        str(row["canonical_claim_id"]) for row in minimal_rows if row["family_is_new_to_snapshot_v2"]
    }
    projected_warning_families = set(snapshot_warning_families) | {
        str(row["canonical_claim_id"]) for row in minimal_rows
    }
    projected_target_types = set(snapshot_target_types) | {str(row["target_type"]) for row in minimal_rows}

    target_type_counts = Counter(str(row["target_type"]) for row in minimal_rows)
    summary = {
        "generated_at": _utc_now_iso(),
        "source_snapshot_v2": str(snapshot_v2_path),
        "source_prior_adjudication_pack": str(prior_adjudication_path),
        "counts": {
            "snapshot_v2_families_total": len(snapshot_families),
            "snapshot_v2_warning_or_conflict_families_total": len(snapshot_warning_families),
            "snapshot_v2_target_type_buckets_total": len(snapshot_target_types),
            "minimal_gap_pack_rows_total": len(minimal_rows),
            "reserve_gap_pack_rows_total": len(reserve_rows),
            "minimal_gap_pack_new_families_total": sum(
                1 for row in minimal_rows if row["family_is_new_to_snapshot_v2"]
            ),
            "minimal_gap_pack_target_type_buckets_total": len(
                {str(row["target_type"]) for row in minimal_rows}
            ),
            "projected_families_total": len(projected_families),
            "projected_warning_or_conflict_families_total": len(projected_warning_families),
            "projected_target_type_buckets_total": len(projected_target_types),
            "threshold_min_canonical_families": 24,
            "threshold_min_warning_or_conflict_families": 6,
            "threshold_min_target_type_buckets": 3,
            "threshold_canonical_families_met": len(projected_families) >= 24,
            "threshold_warning_or_conflict_families_met": len(projected_warning_families) >= 6,
            "threshold_target_type_buckets_met": len(projected_target_types) >= 3,
            "threshold_all_met": (
                len(projected_families) >= 24
                and len(projected_warning_families) >= 6
                and len(projected_target_types) >= 3
            ),
            **{
                f"minimal_gap_pack_target_type_{target_type}": target_type_counts[target_type]
                for target_type in sorted(target_type_counts)
            },
        },
    }
    return minimal_rows, reserve_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    minimal_rows, reserve_rows, summary = build_outputs(
        args.snapshot_v2.expanduser().resolve(),
        args.prior_adjudication_pack.expanduser().resolve(),
    )

    minimal_jsonl = output_dir / "warning_conflict_gap_pack.jsonl"
    minimal_tsv = output_dir / "warning_conflict_gap_pack.tsv"
    reserve_jsonl = output_dir / "warning_conflict_gap_pack_reserve.jsonl"
    summary_json = output_dir / "warning_conflict_gap_pack_summary.json"

    _write_jsonl(minimal_jsonl, minimal_rows)
    _write_tsv(
        minimal_tsv,
        minimal_rows,
        [
            "gap_pack_rank",
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "adjudication_bucket",
            "would_add_target_type_bucket",
            "decision_reason",
        ],
    )
    _write_jsonl(reserve_jsonl, reserve_rows)

    summary["artifacts"] = {
        "warning_conflict_gap_pack_jsonl": str(minimal_jsonl),
        "warning_conflict_gap_pack_tsv": str(minimal_tsv),
        "warning_conflict_gap_pack_reserve_jsonl": str(reserve_jsonl),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
