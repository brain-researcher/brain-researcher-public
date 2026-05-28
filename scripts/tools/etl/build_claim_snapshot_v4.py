#!/usr/bin/env python3
"""Build the next reviewed claim snapshot from the terminal shortfall pack."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVIEWER = "codex"

DECISIONS_BY_CLAIM_ID: dict[str, dict[str, Any]] = {
    "claim:36440b921722e3394eef114ce3e1be3c": {
        "adjudication_bucket": "retain_terminal_shortfall_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v4_included": True,
        "snapshot_role": "singleton_terminal_warning",
        "cluster_review_status": "reviewed_terminal_warning",
        "decision_reason": (
            "Retain as a terminal warning-tier concept family because it is non-title and fills the "
            "remaining breadth gap, even though the proposition stays ASD population-scoped."
        ),
        "additional_failure_tags": [],
    },
    "claim:112ab135f7e98e7fef3af9ab0037a729": {
        "adjudication_bucket": "retain_terminal_shortfall_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v4_included": True,
        "snapshot_role": "singleton_terminal_warning",
        "cluster_review_status": "reviewed_terminal_warning",
        "decision_reason": (
            "Retain as a terminal warning-tier region family because the row is non-title and "
            "empirical, while remaining broad and coarse-grained at the regional scope."
        ),
        "additional_failure_tags": [],
    },
    "claim:c1e6f254a408747bef0ff3d56614e4de": {
        "adjudication_bucket": "retain_terminal_shortfall_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v4_included": True,
        "snapshot_role": "singleton_terminal_warning",
        "cluster_review_status": "reviewed_terminal_warning",
        "decision_reason": (
            "Retain as a terminal warning-tier region family because it is non-title and "
            "proposition-bearing, even though the neural-circuits target is generic and context-bound."
        ),
        "additional_failure_tags": [],
    },
    "claim:e0b5a42636c2bf10b5ad1df1fda7fd1d": {
        "adjudication_bucket": "exclude_terminal_reserve_analysis_like",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v4_included": False,
        "snapshot_role": "excluded_terminal_reserve",
        "cluster_review_status": "reviewed_terminal_reserve_excluded",
        "decision_reason": (
            "Keep reserve gait-speed row excluded because the wording remains analysis-like and less "
            "stable than the three primary shortfall candidates."
        ),
        "additional_failure_tags": [],
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v3", type=Path, required=True)
    parser.add_argument("--terminal-shortfall-pack", type=Path, required=True)
    parser.add_argument("--terminal-shortfall-reserve", type=Path, required=True)
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


def _normalize_review_row(row: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    base_failure_tags = list(row.get("failure_tags") or [])
    merged_failure_tags = list(dict.fromkeys(base_failure_tags + decision["additional_failure_tags"]))
    cluster_confidence = row.get("cluster_confidence")
    if cluster_confidence in (None, ""):
        cluster_confidence = row.get("mapping_confidence")
    if cluster_confidence in (None, ""):
        cluster_confidence = 0.5

    return {
        **row,
        "cluster_confidence": float(cluster_confidence),
        "failure_tags": merged_failure_tags,
        "reviewed_by": REVIEWER,
        "reviewed_at": _utc_now_iso(),
        "adjudication_bucket": decision["adjudication_bucket"],
        "adjudicated_action": decision["adjudicated_action"],
        "snapshot_v4_included": bool(decision["snapshot_v4_included"]),
        "snapshot_role": decision["snapshot_role"],
        "cluster_review_status": decision["cluster_review_status"],
        "decision_reason": decision["decision_reason"],
        "adjudication_status": (
            decision["cluster_review_status"]
            if decision["snapshot_v4_included"]
            else f"{decision['cluster_review_status']}_out"
        ),
    }


def build_outputs(
    snapshot_v3_path: Path,
    terminal_shortfall_pack_path: Path,
    terminal_shortfall_reserve_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    snapshot_rows = list(_iter_jsonl(snapshot_v3_path))
    shortfall_rows = list(_iter_jsonl(terminal_shortfall_pack_path))
    reserve_rows = list(_iter_jsonl(terminal_shortfall_reserve_path))
    candidate_rows = shortfall_rows + reserve_rows

    seen_candidate_ids = {str(row.get("source_claim_id") or "").strip() for row in candidate_rows}
    missing = sorted(seen_candidate_ids - set(DECISIONS_BY_CLAIM_ID))
    extra = sorted(set(DECISIONS_BY_CLAIM_ID) - seen_candidate_ids)
    if missing:
        raise SystemExit(f"Fail-closed v4 adjudication mismatch: missing decisions for {missing}")
    if extra:
        raise SystemExit(f"Fail-closed v4 adjudication mismatch: unused decisions for {extra}")

    reviewed_rows: list[dict[str, Any]] = []
    retained_rows: list[dict[str, Any]] = list(snapshot_rows)
    for row in candidate_rows:
        claim_id = str(row["source_claim_id"])
        decision = DECISIONS_BY_CLAIM_ID[claim_id]
        reviewed = _normalize_review_row(row, decision)
        reviewed_rows.append(reviewed)
        if bool(decision["snapshot_v4_included"]):
            retained_rows.append(reviewed)

    family_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in retained_rows:
        family_to_rows[str(row["canonical_claim_id"])].append(row)

    warning_or_conflict_families = set()
    for family_id, members in family_to_rows.items():
        polarities = {
            str(member.get("polarity") or "").strip() for member in members if member.get("polarity")
        }
        if len(polarities) > 1 or any("warning" in str(member.get("snapshot_role") or "") for member in members):
            warning_or_conflict_families.add(family_id)

    target_type_counts = Counter(str(row["target_type"]) for row in retained_rows if row.get("target_type"))
    reviewed_counter = Counter(str(row["snapshot_role"]) for row in retained_rows)
    adjudication_counter = Counter(str(row["adjudication_bucket"]) for row in reviewed_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "reviewed_by": REVIEWER,
        "source_snapshot_v3": str(snapshot_v3_path),
        "source_terminal_shortfall_pack": str(terminal_shortfall_pack_path),
        "source_terminal_shortfall_reserve": str(terminal_shortfall_reserve_path),
        "counts": {
            "snapshot_v3_rows_total": len(snapshot_rows),
            "terminal_rows_reviewed_total": len(reviewed_rows),
            "terminal_rows_retained_total": sum(1 for row in reviewed_rows if row["snapshot_v4_included"]),
            "terminal_rows_excluded_total": sum(1 for row in reviewed_rows if not row["snapshot_v4_included"]),
            "snapshot_v4_rows_total": len(retained_rows),
            "snapshot_v4_canonical_families_total": len(family_to_rows),
            "snapshot_v4_warning_or_conflict_families_total": len(warning_or_conflict_families),
            "snapshot_v4_target_type_buckets_total": len(target_type_counts),
            "threshold_min_canonical_families": 24,
            "threshold_min_warning_or_conflict_families": 6,
            "threshold_min_target_type_buckets": 3,
            "threshold_canonical_families_met": len(family_to_rows) >= 24,
            "threshold_warning_or_conflict_families_met": len(warning_or_conflict_families) >= 6,
            "threshold_target_type_buckets_met": len(target_type_counts) >= 3,
            "threshold_all_met": (
                len(family_to_rows) >= 24
                and len(warning_or_conflict_families) >= 6
                and len(target_type_counts) >= 3
            ),
            **{
                f"adjudication_bucket_{bucket}": count
                for bucket, count in sorted(adjudication_counter.items())
            },
            **{
                f"snapshot_role_{role}": count for role, count in sorted(reviewed_counter.items())
            },
            **{
                f"snapshot_v4_target_type_{target_type}": count
                for target_type, count in sorted(target_type_counts.items())
            },
        },
    }
    return reviewed_rows, retained_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    reviewed_rows, retained_rows, summary = build_outputs(
        args.snapshot_v3.expanduser().resolve(),
        args.terminal_shortfall_pack.expanduser().resolve(),
        args.terminal_shortfall_reserve.expanduser().resolve(),
    )

    review_pack_jsonl = output_dir / "claim_snapshot_v4_review_pack.jsonl"
    review_pack_tsv = output_dir / "claim_snapshot_v4_review_pack.tsv"
    snapshot_jsonl = output_dir / "claim_snapshot_v4.jsonl"
    snapshot_tsv = output_dir / "claim_snapshot_v4.tsv"
    summary_json = output_dir / "claim_snapshot_v4_summary.json"

    _write_jsonl(review_pack_jsonl, reviewed_rows)
    _write_tsv(
        review_pack_tsv,
        reviewed_rows,
        [
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "adjudication_bucket",
            "snapshot_v4_included",
            "snapshot_role",
            "decision_reason",
        ],
    )
    _write_jsonl(snapshot_jsonl, retained_rows)
    _write_tsv(
        snapshot_tsv,
        retained_rows,
        [
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "snapshot_role",
            "cluster_review_status",
            "failure_tags",
        ],
    )

    summary["artifacts"] = {
        "claim_snapshot_v4_review_pack_jsonl": str(review_pack_jsonl),
        "claim_snapshot_v4_review_pack_tsv": str(review_pack_tsv),
        "claim_snapshot_v4_jsonl": str(snapshot_jsonl),
        "claim_snapshot_v4_tsv": str(snapshot_tsv),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
