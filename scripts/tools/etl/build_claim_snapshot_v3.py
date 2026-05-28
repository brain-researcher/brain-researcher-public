#!/usr/bin/env python3
"""Build the next reviewed claim snapshot from bridge and breadth candidate packs."""

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
    "claim:028fee000c3903b1e325ecc2bbaf4286": {
        "adjudication_bucket": "retain_bridge_conflict_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_bridge_conflict_warning",
        "cluster_review_status": "reviewed_bridge_conflict_warning",
        "decision_reason": (
            "Retain as an explicitly warning-tagged bridge conflict family because the refute case "
            "is still useful for bounded snapshot diversity, even though the wording remains broad "
            "and cohort-bound."
        ),
        "additional_failure_tags": [],
    },
    "claim:bcbf3a40052599b6c72c9a7c38585e6f": {
        "adjudication_bucket": "exclude_method_analysis_bridge",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v3_included": False,
        "snapshot_role": "excluded_bridge_failure",
        "cluster_review_status": "reviewed_bridge_excluded",
        "decision_reason": (
            "Keep excluded because the insula row is still dominated by analysis-marker wording and "
            "does not read as a stable biological proposition."
        ),
        "additional_failure_tags": [],
    },
    "claim:7b858b2e0cfe374856830def8df4a681": {
        "adjudication_bucket": "retain_bridge_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_bridge_warning",
        "cluster_review_status": "reviewed_bridge_warning",
        "decision_reason": (
            "Retain as a warning-tagged bridge row because the locus coeruleus family is narrow "
            "and reusable, but still title-only and disease-scoped."
        ),
        "additional_failure_tags": [],
    },
    "claim:28fcbcec2470e0c24db5a5fc716143cc": {
        "adjudication_bucket": "retain_bridge_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_bridge_warning",
        "cluster_review_status": "reviewed_bridge_warning",
        "decision_reason": (
            "Retain as a warning-tagged bridge row because the TPJ family is semantically narrow, "
            "while still carrying title-only evidence weakness."
        ),
        "additional_failure_tags": [],
    },
    "claim:88f2eb8941c9228d0071651be108fa58": {
        "adjudication_bucket": "retain_bridge_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_bridge_warning",
        "cluster_review_status": "reviewed_bridge_warning",
        "decision_reason": (
            "Retain as the bounded task-family bridge because response inhibition is the cleanest "
            "available task anchor in the reviewed warning/conflict bridge set, despite title-only "
            "pre-Gate-B provenance."
        ),
        "additional_failure_tags": ["modality_or_method_leakage"],
    },
    "claim:8ef30c3b4f50476f74b87e40414971c4": {
        "adjudication_bucket": "retain_breadth_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_breadth_warning",
        "cluster_review_status": "reviewed_breadth_warning",
        "decision_reason": (
            "Retain as a warning-tagged breadth family because the non-title schizophrenia "
            "connectivity claim is empirically specific, but the regional target is merged/composite "
            "and the cohort framing is narrow."
        ),
        "additional_failure_tags": [
            "granularity_mismatch",
            "population_or_disease_scope_mismatch",
        ],
    },
    "claim:7b323180f7b5cd382b405b8fb556a415": {
        "adjudication_bucket": "retain_breadth_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_breadth_warning",
        "cluster_review_status": "reviewed_breadth_warning",
        "decision_reason": (
            "Retain as a warning-tagged breadth family because the claim is non-title and empirical, "
            "while the intrinsic-network target and methylphenidate mechanism framing remain broad "
            "and intervention-bound."
        ),
        "additional_failure_tags": [
            "granularity_mismatch",
            "intervention_or_context_mismatch",
        ],
    },
    "claim:c1e6f254a408747bef0ff3d56614e4de": {
        "adjudication_bucket": "exclude_composite_region_scope",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v3_included": False,
        "snapshot_role": "excluded_breadth_failure",
        "cluster_review_status": "reviewed_breadth_excluded",
        "decision_reason": (
            "Exclude because the neural-circuits target is too generic and the maternal-caregiving "
            "sentence still reads as broad context framing rather than a portable canonical family."
        ),
        "additional_failure_tags": [
            "granularity_mismatch",
            "intervention_or_context_mismatch",
        ],
    },
    "claim:717aa816a1b759ed0631a31733f83ef0": {
        "adjudication_bucket": "retain_breadth_singleton_clean",
        "adjudicated_action": "retain_singleton",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_breadth_clean",
        "cluster_review_status": "reviewed_breadth_clean",
        "decision_reason": (
            "Retain directly because the rostro-caudal organization claim is non-title, regionally "
            "specific, and propositionally clean."
        ),
        "additional_failure_tags": [],
    },
    "claim:0a454b9f9b9ff3e630176ceb3fde874b": {
        "adjudication_bucket": "retain_breadth_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_breadth_warning",
        "cluster_review_status": "reviewed_breadth_warning",
        "decision_reason": (
            "Retain as a warning-tagged breadth family because the ventral-attention-system row is "
            "non-title and targetable, but still broad at the system level and cohort-specific."
        ),
        "additional_failure_tags": [
            "granularity_mismatch",
            "population_or_disease_scope_mismatch",
        ],
    },
    "claim:9f78b034872ba2ab733d1b43a687804c": {
        "adjudication_bucket": "retain_breadth_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_breadth_warning",
        "cluster_review_status": "reviewed_breadth_warning",
        "decision_reason": (
            "Retain as a warning-tagged task family because the gambling-availability contrast is "
            "paper-local and non-title, even though it stays close to task-design framing."
        ),
        "additional_failure_tags": ["modality_or_method_leakage"],
    },
    "claim:5432581b4cf7885b281b5b3e9a26baba": {
        "adjudication_bucket": "retain_breadth_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v3_included": True,
        "snapshot_role": "singleton_breadth_warning",
        "cluster_review_status": "reviewed_breadth_warning",
        "decision_reason": (
            "Retain as a warning-tagged task family because the motor-imagery row reports a real "
            "neural signature, but the task target is still carried through region-activation wording."
        ),
        "additional_failure_tags": ["granularity_mismatch"],
    },
    "claim:6fa3074f7a6af9cfa41c1db2495d2026": {
        "adjudication_bucket": "exclude_task_topic_marker",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v3_included": False,
        "snapshot_role": "excluded_breadth_failure",
        "cluster_review_status": "reviewed_breadth_excluded",
        "decision_reason": (
            "Exclude because the risky-decision-making sentence is still a study-aim/task-topic marker "
            "rather than a discrete empirical claim family."
        ),
        "additional_failure_tags": ["modality_or_method_leakage"],
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v2", type=Path, required=True)
    parser.add_argument("--warning-conflict-gap-pack", type=Path, required=True)
    parser.add_argument("--substantive-breadth-pack", type=Path, required=True)
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


def _normalize_candidate_row(
    row: dict[str, Any],
    *,
    decision: dict[str, Any],
    review_stage: str,
) -> dict[str, Any]:
    base_failure_tags = list(row.get("failure_tags") or [])
    merged_failure_tags = list(dict.fromkeys(base_failure_tags + decision["additional_failure_tags"]))
    benchmark_eligibility = str(row.get("benchmark_eligibility") or "").strip()
    quality_profile = row.get("quality_profile")
    if not quality_profile and benchmark_eligibility == "benchmark_regenerated_non_title":
        quality_profile = "balanced_marginal_regenerated"

    cluster_confidence = row.get("cluster_confidence")
    if cluster_confidence in (None, ""):
        cluster_confidence = row.get("mapping_confidence")
    if cluster_confidence in (None, ""):
        cluster_confidence = 0.5

    return {
        **row,
        "quality_profile": quality_profile,
        "candidate_lane_present": bool(row.get("candidate_lane_present", False)),
        "cluster_confidence": float(cluster_confidence),
        "failure_tags": merged_failure_tags,
        "review_stage": review_stage,
        "reviewed_by": REVIEWER,
        "reviewed_at": _utc_now_iso(),
        "adjudication_bucket": decision["adjudication_bucket"],
        "adjudicated_action": decision["adjudicated_action"],
        "snapshot_v3_included": bool(decision["snapshot_v3_included"]),
        "snapshot_role": decision["snapshot_role"],
        "cluster_review_status": decision["cluster_review_status"],
        "decision_reason": decision["decision_reason"],
        "adjudication_status": (
            decision["cluster_review_status"]
            if decision["snapshot_v3_included"]
            else f"{decision['cluster_review_status']}_out"
        ),
    }


def build_outputs(
    snapshot_v2_path: Path,
    warning_conflict_gap_pack_path: Path,
    substantive_breadth_pack_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    snapshot_v2_rows = list(_iter_jsonl(snapshot_v2_path))
    bridge_rows = list(_iter_jsonl(warning_conflict_gap_pack_path))
    breadth_rows = list(_iter_jsonl(substantive_breadth_pack_path))

    seen_candidate_ids = {
        str(row.get("source_claim_id") or "").strip() for row in bridge_rows + breadth_rows
    }
    missing = sorted(seen_candidate_ids - set(DECISIONS_BY_CLAIM_ID))
    extra = sorted(set(DECISIONS_BY_CLAIM_ID) - seen_candidate_ids)
    if missing:
        raise SystemExit(f"Fail-closed v3 adjudication mismatch: missing decisions for {missing}")
    if extra:
        raise SystemExit(f"Fail-closed v3 adjudication mismatch: unused decisions for {extra}")

    reviewed_rows: list[dict[str, Any]] = []
    retained_rows: list[dict[str, Any]] = list(snapshot_v2_rows)

    for review_stage, rows in (
        ("bridge", bridge_rows),
        ("breadth", breadth_rows),
    ):
        for row in rows:
            claim_id = str(row["source_claim_id"])
            decision = DECISIONS_BY_CLAIM_ID[claim_id]
            reviewed = _normalize_candidate_row(
                row,
                decision=decision,
                review_stage=review_stage,
            )
            reviewed_rows.append(reviewed)
            if bool(decision["snapshot_v3_included"]):
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

    reviewed_counter = Counter(str(row["snapshot_role"]) for row in retained_rows)
    adjudication_counter = Counter(str(row["adjudication_bucket"]) for row in reviewed_rows)
    target_type_counter = Counter(str(row["target_type"]) for row in retained_rows if row.get("target_type"))

    bridge_reviewed = [row for row in reviewed_rows if row["review_stage"] == "bridge"]
    breadth_reviewed = [row for row in reviewed_rows if row["review_stage"] == "breadth"]
    bridge_retained = [row for row in bridge_reviewed if row["snapshot_v3_included"]]
    breadth_retained = [row for row in breadth_reviewed if row["snapshot_v3_included"]]

    summary = {
        "generated_at": _utc_now_iso(),
        "reviewed_by": REVIEWER,
        "source_snapshot_v2": str(snapshot_v2_path),
        "source_warning_conflict_gap_pack": str(warning_conflict_gap_pack_path),
        "source_substantive_breadth_pack": str(substantive_breadth_pack_path),
        "counts": {
            "snapshot_v2_rows_total": len(snapshot_v2_rows),
            "bridge_rows_reviewed_total": len(bridge_reviewed),
            "bridge_rows_retained_total": len(bridge_retained),
            "bridge_rows_excluded_total": len(bridge_reviewed) - len(bridge_retained),
            "breadth_rows_reviewed_total": len(breadth_reviewed),
            "breadth_rows_retained_total": len(breadth_retained),
            "breadth_rows_excluded_total": len(breadth_reviewed) - len(breadth_retained),
            "snapshot_v3_rows_total": len(retained_rows),
            "snapshot_v3_canonical_families_total": len(family_to_rows),
            "snapshot_v3_warning_or_conflict_families_total": len(warning_or_conflict_families),
            "snapshot_v3_target_type_buckets_total": len(target_type_counter),
            "threshold_min_canonical_families": 24,
            "threshold_min_warning_or_conflict_families": 6,
            "threshold_min_target_type_buckets": 3,
            "threshold_canonical_families_met": len(family_to_rows) >= 24,
            "threshold_warning_or_conflict_families_met": len(warning_or_conflict_families) >= 6,
            "threshold_target_type_buckets_met": len(target_type_counter) >= 3,
            "threshold_all_met": (
                len(family_to_rows) >= 24
                and len(warning_or_conflict_families) >= 6
                and len(target_type_counter) >= 3
            ),
            "remaining_family_shortfall": max(0, 24 - len(family_to_rows)),
            **{
                f"adjudication_bucket_{bucket}": count
                for bucket, count in sorted(adjudication_counter.items())
            },
            **{
                f"snapshot_role_{role}": count for role, count in sorted(reviewed_counter.items())
            },
            **{
                f"snapshot_v3_target_type_{target_type}": count
                for target_type, count in sorted(target_type_counter.items())
            },
        },
    }
    return reviewed_rows, retained_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    reviewed_rows, retained_rows, summary = build_outputs(
        args.snapshot_v2.expanduser().resolve(),
        args.warning_conflict_gap_pack.expanduser().resolve(),
        args.substantive_breadth_pack.expanduser().resolve(),
    )

    review_pack_jsonl = output_dir / "claim_snapshot_v3_review_pack.jsonl"
    review_pack_tsv = output_dir / "claim_snapshot_v3_review_pack.tsv"
    snapshot_jsonl = output_dir / "claim_snapshot_v3.jsonl"
    snapshot_tsv = output_dir / "claim_snapshot_v3.tsv"
    summary_json = output_dir / "claim_snapshot_v3_summary.json"

    _write_jsonl(review_pack_jsonl, reviewed_rows)
    _write_tsv(
        review_pack_tsv,
        reviewed_rows,
        [
            "review_stage",
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "adjudication_bucket",
            "snapshot_v3_included",
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
        "claim_snapshot_v3_review_pack_jsonl": str(review_pack_jsonl),
        "claim_snapshot_v3_review_pack_tsv": str(review_pack_tsv),
        "claim_snapshot_v3_jsonl": str(snapshot_jsonl),
        "claim_snapshot_v3_tsv": str(snapshot_tsv),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
