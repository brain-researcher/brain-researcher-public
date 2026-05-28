#!/usr/bin/env python3
"""Review the first expansion pack and cut claim_snapshot_v2."""

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
    "claim:8001f8113f2ab080a140bf1d0b8db42f": {
        "adjudication_bucket": "retain_expansion_singleton_clean",
        "adjudicated_action": "retain_singleton",
        "snapshot_v2_included": True,
        "snapshot_role": "singleton_expansion_clean",
        "cluster_review_status": "reviewed_expansion_singleton_clean",
        "decision_reason": (
            "Behavioral concept claim is narrow, non-title, and propositionally specific enough "
            "to add as a clean singleton family."
        ),
        "additional_failure_tags": [],
    },
    "claim:058715fda88bc99ff8a9936630079971": {
        "adjudication_bucket": "retain_expansion_singleton_clean",
        "adjudicated_action": "retain_singleton",
        "snapshot_v2_included": True,
        "snapshot_role": "singleton_expansion_clean",
        "cluster_review_status": "reviewed_expansion_singleton_clean",
        "decision_reason": (
            "Specific biomarker/receptor availability claim is empirically narrow and reusable "
            "as a clean singleton family."
        ),
        "additional_failure_tags": [],
    },
    "claim:e63c9d3560f5d95497afbd977b5e9a9d": {
        "adjudication_bucket": "retain_expansion_singleton_clean",
        "adjudicated_action": "retain_singleton",
        "snapshot_v2_included": True,
        "snapshot_role": "singleton_expansion_clean",
        "cluster_review_status": "reviewed_expansion_singleton_clean",
        "decision_reason": (
            "Egocentric-bias claim is a semantically narrow cognitive proposition with non-title "
            "grounding; retain directly."
        ),
        "additional_failure_tags": [],
    },
    "claim:f7d233d0bcfc58990b508608df4d31e4": {
        "adjudication_bucket": "retain_expansion_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v2_included": True,
        "snapshot_role": "singleton_expansion_warning",
        "cluster_review_status": "reviewed_expansion_singleton_warning",
        "decision_reason": (
            "Retain as a warning-tagged singleton because the claim is non-title and specific, "
            "but remains context-bound to dialysis-linked memory improvement."
        ),
        "additional_failure_tags": ["intervention_or_context_mismatch"],
    },
    "claim:f5fab8f10f831984cf211ae410af8738": {
        "adjudication_bucket": "retain_expansion_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v2_included": True,
        "snapshot_role": "singleton_expansion_warning",
        "cluster_review_status": "reviewed_expansion_singleton_warning",
        "decision_reason": (
            "Retain regional activation claim with a warning because the merged regional target is "
            "composite and context-specific."
        ),
        "additional_failure_tags": [
            "granularity_mismatch",
            "intervention_or_context_mismatch",
        ],
    },
    "claim:bb60c12136f31d767883a7cf31b85e58": {
        "adjudication_bucket": "retain_expansion_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v2_included": True,
        "snapshot_role": "singleton_expansion_warning",
        "cluster_review_status": "reviewed_expansion_singleton_warning",
        "decision_reason": (
            "Retain as a warning-tagged singleton because the NAcc effect is empirically useful "
            "but conditional on low cognitive load."
        ),
        "additional_failure_tags": ["intervention_or_context_mismatch"],
    },
    "claim:f77b041f02b033e7512a3a81a86bb3fc": {
        "adjudication_bucket": "retain_expansion_singleton_warning",
        "adjudicated_action": "retain_singleton_with_warning",
        "snapshot_v2_included": True,
        "snapshot_role": "singleton_expansion_warning",
        "cluster_review_status": "reviewed_expansion_singleton_warning",
        "decision_reason": (
            "Retain with warning because the regional target is broad/composite, but the empirical "
            "claim is non-title and reviewable."
        ),
        "additional_failure_tags": ["granularity_mismatch"],
    },
    "claim:ae95759619d6ef7c80f772c4f85f2265": {
        "adjudication_bucket": "exclude_generic_background_concept",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Exploration/exploitation sentence is generic background framing rather than a paper-local "
            "empirical proposition."
        ),
        "additional_failure_tags": ["semantic_composite_or_analysis_claim"],
    },
    "claim:e0b5a42636c2bf10b5ad1df1fda7fd1d": {
        "adjudication_bucket": "exclude_analysis_like_behavioral_concept",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Gait-speed row is too analysis-like and propositionally loose for the reviewed snapshot."
        ),
        "additional_failure_tags": ["semantic_composite_or_analysis_claim"],
    },
    "claim:36440b921722e3394eef114ce3e1be3c": {
        "adjudication_bucket": "exclude_population_scope_background_concept",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Action-understanding sentence reads as broad ASD population framing, not as a discrete "
            "paper-local empirical claim."
        ),
        "additional_failure_tags": [
            "population_or_disease_scope_mismatch",
            "semantic_composite_or_analysis_claim",
        ],
    },
    "claim:112ab135f7e98e7fef3af9ab0037a729": {
        "adjudication_bucket": "exclude_composite_region_scope",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Prefrontal/limbic region row remains too broad and coarse-grained for the reviewed snapshot."
        ),
        "additional_failure_tags": ["granularity_mismatch"],
    },
    "claim:dd8d5d617e23d7d2933eb69d294b85a7": {
        "adjudication_bucket": "exclude_task_topic_marker",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Prosocial-decisions sentence is a task/topic marker rather than a reusable empirical claim."
        ),
        "additional_failure_tags": ["modality_or_method_leakage"],
    },
    "claim:a79c3cab1197d8ceea87112cc10e8116": {
        "adjudication_bucket": "exclude_task_method_marker",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Inhibition-control sentence is still a task-use marker anchored to study design rather "
            "than a substantive proposition."
        ),
        "additional_failure_tags": ["modality_or_method_leakage"],
    },
    "claim:60de6863de404dd92ddf6113b0296d84": {
        "adjudication_bucket": "exclude_analysis_method_task_marker",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Searchlight-MVPA sentence is analysis/method content, not a reviewed claim family."
        ),
        "additional_failure_tags": [
            "modality_or_method_leakage",
            "semantic_composite_or_analysis_claim",
        ],
    },
    "claim:3f7954fb1ea68cce5deef1cce4a0e910": {
        "adjudication_bucket": "exclude_task_utilization_marker",
        "adjudicated_action": "exclude_from_snapshot",
        "snapshot_v2_included": False,
        "snapshot_role": "excluded_expansion_failure",
        "cluster_review_status": "reviewed_expansion_excluded",
        "decision_reason": (
            "Sequential risk-taking sentence is task-utilization metadata rather than a reusable empirical proposition."
        ),
        "additional_failure_tags": ["modality_or_method_leakage"],
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v1", type=Path, required=True)
    parser.add_argument("--expansion-pack", type=Path, required=True)
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
    snapshot_v1_path: Path,
    expansion_pack_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    snapshot_v1_rows = [row for row in _iter_jsonl(snapshot_v1_path)]
    expansion_rows = [row for row in _iter_jsonl(expansion_pack_path)]

    seen_expansion_ids = {str(row.get("source_claim_id") or "").strip() for row in expansion_rows}
    missing = sorted(seen_expansion_ids - set(DECISIONS_BY_CLAIM_ID))
    extra = sorted(set(DECISIONS_BY_CLAIM_ID) - seen_expansion_ids)
    if missing:
        raise SystemExit(
            f"Fail-closed expansion adjudication mismatch: missing decisions for {missing}"
        )

    reviewed_expansion_rows: list[dict[str, Any]] = []
    retained_rows: list[dict[str, Any]] = list(snapshot_v1_rows)
    reviewed_bucket_counts: Counter[str] = Counter()
    reviewed_role_counts: Counter[str] = Counter()
    target_type_counts: Counter[str] = Counter()

    for row in expansion_rows:
        claim_id = str(row.get("source_claim_id") or "").strip()
        decision = DECISIONS_BY_CLAIM_ID[claim_id]
        failure_tags = sorted(
            set(str(tag).strip() for tag in row.get("failure_tags") or [])
            | set(decision.get("additional_failure_tags") or [])
        )
        reviewed = {
            **row,
            "reviewed_by": REVIEWER,
            "reviewed_at": _utc_now_iso(),
            "adjudication_bucket": decision["adjudication_bucket"],
            "adjudicated_action": decision["adjudicated_action"],
            "snapshot_v2_included": bool(decision["snapshot_v2_included"]),
            "snapshot_role": decision["snapshot_role"],
            "cluster_review_status": decision["cluster_review_status"],
            "decision_reason": decision["decision_reason"],
            "failure_tags": failure_tags,
        }
        reviewed_expansion_rows.append(reviewed)
        reviewed_bucket_counts[reviewed["adjudication_bucket"]] += 1
        if reviewed["snapshot_v2_included"]:
            reviewed_role_counts[reviewed["snapshot_role"]] += 1
            retained_rows.append(
                {
                    **row,
                    "failure_tags": failure_tags,
                    "reviewed_by": REVIEWER,
                    "reviewed_at": reviewed["reviewed_at"],
                    "snapshot_role": reviewed["snapshot_role"],
                    "adjudication_status": reviewed["cluster_review_status"],
                    "decision_reason": reviewed["decision_reason"],
                }
            )

    family_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in retained_rows:
        family_to_rows[str(row["canonical_claim_id"])].append(row)
        target_type_counts[str(row["target_type"])] += 1

    warning_families = 0
    for members in family_to_rows.values():
        polarities = {str(member.get("polarity") or "").strip() for member in members if member.get("polarity")}
        if len(polarities) > 1:
            warning_families += 1
            continue
        if any("warning" in str(member.get("snapshot_role") or "") for member in members):
            warning_families += 1

    retained_rows.sort(
        key=lambda row: (
            row.get("snapshot_role") not in {"control", "singleton_warning", "conflict_cluster_warning"},
            row["target_type"],
            row["canonical_claim_id"],
            row["source_claim_id"],
        )
    )
    reviewed_expansion_rows.sort(
        key=lambda row: (
            row["snapshot_v2_included"] is False,
            row["target_type"],
            row["canonical_claim_id"],
            row["source_claim_id"],
        )
    )

    summary = {
        "generated_at": _utc_now_iso(),
        "reviewed_by": REVIEWER,
        "source_snapshot_v1": str(snapshot_v1_path),
        "source_expansion_pack": str(expansion_pack_path),
        "counts": {
            "snapshot_v1_rows_total": len(snapshot_v1_rows),
            "expansion_rows_reviewed_total": len(expansion_rows),
            "expansion_rows_retained_total": sum(
                1 for row in reviewed_expansion_rows if row["snapshot_v2_included"]
            ),
            "expansion_rows_excluded_total": sum(
                1 for row in reviewed_expansion_rows if not row["snapshot_v2_included"]
            ),
            "snapshot_v2_rows_total": len(retained_rows),
            "snapshot_v2_canonical_families_total": len(family_to_rows),
            "snapshot_v2_warning_or_conflict_families_total": warning_families,
            "snapshot_v2_target_type_buckets_total": len(target_type_counts),
            "threshold_min_canonical_families": 24,
            "threshold_min_warning_or_conflict_families": 6,
            "threshold_min_target_type_buckets": 3,
            "threshold_canonical_families_met": len(family_to_rows) >= 24,
            "threshold_warning_or_conflict_families_met": warning_families >= 6,
            "threshold_target_type_buckets_met": len(target_type_counts) >= 3,
            "threshold_all_met": (
                len(family_to_rows) >= 24
                and warning_families >= 6
                and len(target_type_counts) >= 3
            ),
            **{
                f"review_bucket_{bucket}": reviewed_bucket_counts[bucket]
                for bucket in sorted(reviewed_bucket_counts)
            },
            **{
                f"snapshot_role_{role}": reviewed_role_counts[role]
                for role in sorted(reviewed_role_counts)
            },
            **{
                f"snapshot_v2_target_type_{target_type}": target_type_counts[target_type]
                for target_type in sorted(target_type_counts)
            },
            "unused_decisions_total": len(extra),
        },
    }
    return reviewed_expansion_rows, retained_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    reviewed_expansion_rows, retained_rows, summary = build_outputs(
        args.snapshot_v1.expanduser().resolve(),
        args.expansion_pack.expanduser().resolve(),
    )
    reviewed_jsonl = output_dir / "claim_snapshot_v2_expansion_review_pack.jsonl"
    reviewed_tsv = output_dir / "claim_snapshot_v2_expansion_review_pack.tsv"
    snapshot_jsonl = output_dir / "claim_snapshot_v2.jsonl"
    snapshot_tsv = output_dir / "claim_snapshot_v2.tsv"
    summary_json = output_dir / "claim_snapshot_v2_summary.json"

    _write_jsonl(reviewed_jsonl, reviewed_expansion_rows)
    _write_tsv(
        reviewed_tsv,
        reviewed_expansion_rows,
        [
            "snapshot_v2_included",
            "adjudication_bucket",
            "snapshot_role",
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "decision_reason",
        ],
    )
    _write_jsonl(snapshot_jsonl, retained_rows)
    _write_tsv(
        snapshot_tsv,
        retained_rows,
        [
            "snapshot_role",
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "polarity",
            "adjudication_status",
            "decision_reason",
        ],
    )

    summary["artifacts"] = {
        "claim_snapshot_v2_expansion_review_pack_jsonl": str(reviewed_jsonl),
        "claim_snapshot_v2_expansion_review_pack_tsv": str(reviewed_tsv),
        "claim_snapshot_v2_jsonl": str(snapshot_jsonl),
        "claim_snapshot_v2_tsv": str(snapshot_tsv),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
