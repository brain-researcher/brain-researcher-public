#!/usr/bin/env python3
"""Adjudicate the bounded clustering pack and cut claim_snapshot_v1."""

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
    "claim:wm_dlpfc": {
        "adjudication_bucket": "stable_singleton_control",
        "adjudicated_action": "retain_singleton",
        "snapshot_v1_included": True,
        "snapshot_role": "control",
        "cluster_review_status": "reviewed_singleton_control",
        "decision_reason": (
            "Clean high-precision concept control with no failure tags; keep as the "
            "stable singleton fixture for claim_snapshot_v1."
        ),
    },
    "claim:conflict_lcont7": {
        "adjudication_bucket": "retain_singleton_with_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v1_included": True,
        "snapshot_role": "singleton_warning",
        "cluster_review_status": "reviewed_singleton_warning",
        "decision_reason": (
            "High-precision parcel seed remains narrow and anchored; keep in the "
            "snapshot with an explicit semantic-composite warning rather than "
            "excluding a useful spatial control."
        ),
    },
    "claim:7a8efe1e555248f8e432e37a6515b852": {
        "adjudication_bucket": "retain_singleton_with_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v1_included": True,
        "snapshot_role": "singleton_warning",
        "cluster_review_status": "reviewed_singleton_warning",
        "decision_reason": (
            "Context-bound region claim has non-title evidence and is useful as a "
            "warning-tagged singleton example; keep with context mismatch visible."
        ),
    },
    "claim:08d8acd1a4f1cc397140594f824bab95": {
        "adjudication_bucket": "include_conflict_cluster_with_warning",
        "adjudicated_action": "retain_conflict_cluster_with_warning",
        "snapshot_v1_included": True,
        "snapshot_role": "conflict_cluster_warning",
        "cluster_review_status": "reviewed_conflict_cluster_warning",
        "decision_reason": (
            "Only opposing-stance cluster in the bounded pack. Keep the shared "
            "canonical claim family, preserve stance disagreement, and keep all "
            "failure tags visible."
        ),
    },
    "claim:592e21efcf95e2cb37890b1bd835ef03": {
        "adjudication_bucket": "include_conflict_cluster_with_warning",
        "adjudicated_action": "retain_conflict_cluster_with_warning",
        "snapshot_v1_included": True,
        "snapshot_role": "conflict_cluster_warning",
        "cluster_review_status": "reviewed_conflict_cluster_warning",
        "decision_reason": (
            "Only opposing-stance cluster in the bounded pack. Keep the shared "
            "canonical claim family, preserve stance disagreement, and keep all "
            "failure tags visible."
        ),
    },
    "claim:88f2eb8941c9228d0071651be108fa58": {
        "adjudication_bucket": "exclude_title_only_task_seed",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v1_included": False,
        "snapshot_role": "excluded_failure",
        "cluster_review_status": "reviewed_excluded_failure",
        "decision_reason": (
            "Task seed is title-only and pre-Gate-B; do not let it define the first "
            "claim snapshot."
        ),
    },
    "claim:028fee000c3903b1e325ecc2bbaf4286": {
        "adjudication_bucket": "exclude_composite_scope_conflict",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v1_included": False,
        "snapshot_role": "excluded_failure",
        "cluster_review_status": "reviewed_excluded_failure",
        "decision_reason": (
            "Conflict wording is broad, cohort-bound, and composite; keep it out of "
            "claim_snapshot_v1 until scope and proposition granularity are tighter."
        ),
    },
    "claim:872fcaaffec17ba363216ac5eb04c317": {
        "adjudication_bucket": "exclude_intervention_method_title_only",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v1_included": False,
        "snapshot_role": "excluded_failure",
        "cluster_review_status": "reviewed_excluded_failure",
        "decision_reason": (
            "Intervention-specific neurofeedback row is title-only and method-heavy; "
            "exclude from the first canonical snapshot."
        ),
    },
    "claim:bcbf3a40052599b6c72c9a7c38585e6f": {
        "adjudication_bucket": "exclude_method_analysis_claim",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v1_included": False,
        "snapshot_role": "excluded_failure",
        "cluster_review_status": "reviewed_excluded_failure",
        "decision_reason": (
            "This row behaves more like a method/analysis marker than a reusable "
            "biological proposition; exclude from snapshot_v1."
        ),
    },
    "claim:7b858b2e0cfe374856830def8df4a681": {
        "adjudication_bucket": "exclude_title_only_disease_scope",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v1_included": False,
        "snapshot_role": "excluded_failure",
        "cluster_review_status": "reviewed_excluded_failure",
        "decision_reason": (
            "Disease-scoped title-only region row is not strong enough for the first "
            "canonical snapshot."
        ),
    },
    "claim:b16751b473f09874df8053775fbb35f0": {
        "adjudication_bucket": "exclude_title_only_composite_scope",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v1_included": False,
        "snapshot_role": "excluded_failure",
        "cluster_review_status": "reviewed_excluded_failure",
        "decision_reason": (
            "Composite concept row is title-only and population-scoped; exclude until "
            "non-title grounding exists."
        ),
    },
    "claim:28fcbcec2470e0c24db5a5fc716143cc": {
        "adjudication_bucket": "exclude_title_only_region_seed",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v1_included": False,
        "snapshot_role": "excluded_failure",
        "cluster_review_status": "reviewed_excluded_failure",
        "decision_reason": (
            "Exact TPJ mapping is helpful, but title-only evidence is still too weak "
            "for claim_snapshot_v1."
        ),
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-pack", type=Path, required=True)
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


def build_outputs(eval_pack: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = [row for row in _iter_jsonl(eval_pack)]
    seen_ids = {str(row.get("source_claim_id") or "").strip() for row in rows}
    missing = sorted(seen_ids - set(DECISIONS_BY_CLAIM_ID))
    extra = sorted(set(DECISIONS_BY_CLAIM_ID) - seen_ids)
    if missing:
        raise SystemExit(f"Fail-closed adjudication mismatch: missing decisions for: {missing}")

    adjudication_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    snapshot_role_counts: Counter[str] = Counter()

    for row in rows:
        claim_id = str(row.get("source_claim_id") or "").strip()
        decision = DECISIONS_BY_CLAIM_ID[claim_id]
        adjudicated = {
            **row,
            "reviewed_by": REVIEWER,
            "reviewed_at": _utc_now_iso(),
            "adjudication_bucket": decision["adjudication_bucket"],
            "adjudicated_action": decision["adjudicated_action"],
            "snapshot_v1_included": bool(decision["snapshot_v1_included"]),
            "snapshot_role": decision["snapshot_role"],
            "cluster_review_status": decision["cluster_review_status"],
            "decision_reason": decision["decision_reason"],
        }
        adjudication_rows.append(adjudicated)
        bucket_counts[adjudicated["adjudication_bucket"]] += 1
        action_counts[adjudicated["adjudicated_action"]] += 1
        if adjudicated["snapshot_v1_included"]:
            snapshot_role_counts[adjudicated["snapshot_role"]] += 1
            snapshot_rows.append(
                {
                    "source_claim_id": adjudicated["source_claim_id"],
                    "paper_id": adjudicated["paper_id"],
                    "target_id": adjudicated["target_id"],
                    "target_type": adjudicated["target_type"],
                    "claim_text": adjudicated["claim_text"],
                    "claim_kind": adjudicated["claim_kind"],
                    "polarity": adjudicated["polarity"],
                    "quality_profile": adjudicated["quality_profile"],
                    "benchmark_eligibility": adjudicated["benchmark_eligibility"],
                    "candidate_lane_present": adjudicated["candidate_lane_present"],
                    "canonical_claim_id": adjudicated["canonical_claim_id"],
                    "cluster_confidence": adjudicated["cluster_confidence"],
                    "failure_tags": adjudicated["failure_tags"],
                    "adjudication_status": adjudicated["cluster_review_status"],
                    "snapshot_role": adjudicated["snapshot_role"],
                    "decision_reason": adjudicated["decision_reason"],
                    "reviewed_by": adjudicated["reviewed_by"],
                    "reviewed_at": adjudicated["reviewed_at"],
                }
            )

    canonical_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot_rows:
        canonical_to_rows[str(row["canonical_claim_id"])].append(row)

    snapshot_rows.sort(
        key=lambda row: (
            row["snapshot_role"],
            row["canonical_claim_id"],
            row["source_claim_id"],
        )
    )
    adjudication_rows.sort(
        key=lambda row: (
            row["snapshot_v1_included"] is False,
            row["adjudication_bucket"],
            row["canonical_claim_id"],
            row["source_claim_id"],
        )
    )

    summary = {
        "generated_at": _utc_now_iso(),
        "reviewed_by": REVIEWER,
        "source_eval_pack": str(eval_pack),
        "counts": {
            "adjudication_rows_total": len(adjudication_rows),
            "unused_decisions_total": len(extra),
            "snapshot_rows_total": len(snapshot_rows),
            "snapshot_excluded_rows_total": len(adjudication_rows) - len(snapshot_rows),
            "snapshot_canonical_clusters_total": len(canonical_to_rows),
            "snapshot_multi_member_clusters": sum(
                1 for members in canonical_to_rows.values() if len(members) > 1
            ),
            "snapshot_conflict_clusters": sum(
                1
                for members in canonical_to_rows.values()
                if len({str(member.get('polarity') or '') for member in members}) > 1
            ),
            **{bucket: bucket_counts[bucket] for bucket in sorted(bucket_counts)},
            **{f"action_{action}": action_counts[action] for action in sorted(action_counts)},
            **{
                f"snapshot_role_{role}": snapshot_role_counts[role]
                for role in sorted(snapshot_role_counts)
            },
        },
    }
    return adjudication_rows, snapshot_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    eval_pack = args.eval_pack.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    adjudication_rows, snapshot_rows, summary = build_outputs(eval_pack)
    adjudication_jsonl = output_dir / "claim_clustering_adjudication_pack.jsonl"
    adjudication_tsv = output_dir / "claim_clustering_adjudication_pack.tsv"
    snapshot_jsonl = output_dir / "claim_snapshot_v1.jsonl"
    snapshot_tsv = output_dir / "claim_snapshot_v1.tsv"
    summary_json = output_dir / "claim_snapshot_v1_summary.json"

    _write_jsonl(adjudication_jsonl, adjudication_rows)
    _write_tsv(
        adjudication_tsv,
        adjudication_rows,
        [
            "snapshot_v1_included",
            "adjudication_bucket",
            "adjudicated_action",
            "snapshot_role",
            "source_claim_id",
            "paper_id",
            "target_type",
            "target_id",
            "polarity",
            "canonical_claim_id",
            "cluster_review_status",
            "decision_reason",
        ],
    )
    _write_jsonl(snapshot_jsonl, snapshot_rows)
    _write_tsv(
        snapshot_tsv,
        snapshot_rows,
        [
            "snapshot_role",
            "source_claim_id",
            "paper_id",
            "target_type",
            "target_id",
            "polarity",
            "canonical_claim_id",
            "adjudication_status",
            "failure_tags",
            "decision_reason",
        ],
    )

    summary["artifacts"] = {
        "adjudication_pack_jsonl": str(adjudication_jsonl),
        "adjudication_pack_tsv": str(adjudication_tsv),
        "claim_snapshot_v1_jsonl": str(snapshot_jsonl),
        "claim_snapshot_v1_tsv": str(snapshot_tsv),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
