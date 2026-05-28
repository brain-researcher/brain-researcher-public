#!/usr/bin/env python3
"""Materialize the first real downstream claim-side split from claim_snapshot_v4."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPLIT_ID = "claim_snapshot_v4_split_20260314"
SNAPSHOT_ID = "claim_snapshot_v4"
POLICY_SOURCE = (
    "/app/brain_researcher/docs/planning/train_dev_test_split_proposal.md"
)

DEV_FAMILY_IDS = [
    "canonical_claim:22928ddcf687f9b3caf9b10048fcadb4",  # working_memory
    "canonical_claim:58e4beac26721fdb79f13ddc26ff2487",  # attention conflict
    "canonical_claim:61df49814632905e5cb7fa8665441539",  # motor_imagery
    "canonical_claim:75b4b300194c03e55559c23173157575",  # nucleus_accumbens
    "canonical_claim:ef65c7ad956c385d067df12e8ffce04e",  # action_understanding
]

TEST_FAMILY_IDS = [
    "canonical_claim:738b2060fd0fff6678b12a848f13174c",  # dopamine_d2_receptor_availability
    "canonical_claim:2698e6b7d7c08e5d9251286be3954bf5",  # default_mode_network conflict
    "canonical_claim:5ff5875f89d68dba1b74889044fa72bd",  # gambling availability
    "canonical_claim:8c6d9ef1d918642fc4829e9352034ce6",  # posterior_lateral_frontal_cortex
    "canonical_claim:f805e4121f40dbbf1d1a8903ce921a12",  # memory_performance_improvement
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-jsonl", type=Path, required=True)
    parser.add_argument("--snapshot-summary-json", type=Path, required=True)
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


def _sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _family_has_warning_or_conflict(members: Sequence[dict[str, Any]]) -> bool:
    polarities = {
        str(member.get("polarity") or "").strip() for member in members if member.get("polarity")
    }
    roles = {str(member.get("snapshot_role") or "") for member in members}
    return len(polarities) > 1 or any("warning" in role for role in roles)


def _family_has_conflict(members: Sequence[dict[str, Any]]) -> bool:
    polarities = {
        str(member.get("polarity") or "").strip() for member in members if member.get("polarity")
    }
    roles = {str(member.get("snapshot_role") or "") for member in members}
    return len(polarities) > 1 or any("conflict" in role for role in roles)


def _family_has_clean_control(members: Sequence[dict[str, Any]]) -> bool:
    roles = {str(member.get("snapshot_role") or "") for member in members}
    clean_roles = {"control", "singleton_expansion_clean", "singleton_breadth_clean"}
    return not roles.isdisjoint(clean_roles)


def build_outputs(
    snapshot_jsonl_path: Path,
    snapshot_summary_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    snapshot_rows = list(_iter_jsonl(snapshot_jsonl_path))
    snapshot_summary = json.loads(snapshot_summary_path.read_text(encoding="utf-8"))
    family_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot_rows:
        family_to_rows[str(row["canonical_claim_id"])].append(row)

    all_family_ids = set(family_to_rows)
    dev_family_ids = set(DEV_FAMILY_IDS)
    test_family_ids = set(TEST_FAMILY_IDS)
    if dev_family_ids & test_family_ids:
        overlap = sorted(dev_family_ids & test_family_ids)
        raise SystemExit(f"Fail-closed split manifest mismatch: dev/test overlap {overlap}")
    missing = sorted((dev_family_ids | test_family_ids) - all_family_ids)
    if missing:
        raise SystemExit(f"Fail-closed split manifest mismatch: missing family ids {missing}")

    train_family_ids = sorted(all_family_ids - dev_family_ids - test_family_ids)
    partitions = {
        "train": sorted(train_family_ids),
        "dev": sorted(dev_family_ids),
        "test": sorted(test_family_ids),
    }

    family_partition_rows: list[dict[str, Any]] = []
    partitioned_rows: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    partition_summary: dict[str, dict[str, Any]] = {}
    paper_to_partitions: dict[str, set[str]] = defaultdict(set)

    for partition, family_ids in partitions.items():
        families = [family_to_rows[family_id] for family_id in family_ids]
        partition_families = 0
        partition_rows_count = 0
        partition_warning_conflict = 0
        partition_conflict = 0
        partition_clean_control = 0
        target_type_counter: Counter[str] = Counter()
        partition_papers: set[str] = set()
        for family_id in family_ids:
            members = family_to_rows[family_id]
            partition_families += 1
            partition_rows_count += len(members)
            if _family_has_warning_or_conflict(members):
                partition_warning_conflict += 1
            if _family_has_conflict(members):
                partition_conflict += 1
            if _family_has_clean_control(members):
                partition_clean_control += 1
            family_papers = sorted(
                {str(member.get("paper_id") or "") for member in members if member.get("paper_id")}
            )
            family_failure_tags = sorted(
                {
                    tag
                    for member in members
                    for tag in list(member.get("failure_tags") or [])
                    if tag
                }
            )
            family_partition_rows.append(
                {
                    "split_id": SPLIT_ID,
                    "snapshot_id": SNAPSHOT_ID,
                    "canonical_claim_id": family_id,
                    "partition": partition,
                    "row_count": len(members),
                    "paper_ids": family_papers,
                    "source_claim_ids": [member["source_claim_id"] for member in members],
                    "target_types": sorted(
                        {str(member.get("target_type") or "") for member in members if member.get("target_type")}
                    ),
                    "polarities": sorted(
                        {str(member.get("polarity") or "") for member in members if member.get("polarity")}
                    ),
                    "family_has_conflict": _family_has_conflict(members),
                    "family_has_warning_or_conflict": _family_has_warning_or_conflict(members),
                    "family_has_clean_control": _family_has_clean_control(members),
                    "snapshot_roles": sorted(
                        {str(member.get("snapshot_role") or "") for member in members if member.get("snapshot_role")}
                    ),
                    "failure_tags_union": family_failure_tags,
                }
            )
            for member in members:
                target_type = str(member.get("target_type") or "")
                if target_type:
                    target_type_counter[target_type] += 1
                paper_id = str(member.get("paper_id") or "")
                if paper_id:
                    partition_papers.add(paper_id)
                    paper_to_partitions[paper_id].add(partition)
                partitioned_rows[partition].append(
                    {
                        **member,
                        "split_id": SPLIT_ID,
                        "partition": partition,
                        "family_partition": partition,
                    }
                )

        partition_summary[partition] = {
            "families_total": partition_families,
            "rows_total": partition_rows_count,
            "papers_total": len(partition_papers),
            "warning_or_conflict_families_total": partition_warning_conflict,
            "conflict_families_total": partition_conflict,
            "clean_control_families_total": partition_clean_control,
            "target_type_Concept_rows": target_type_counter["Concept"],
            "target_type_Region_rows": target_type_counter["Region"],
            "target_type_Task_rows": target_type_counter["Task"],
        }

    family_cross_split_violations = 0
    paper_leakage_violations = 0
    # paper leakage check only within-family is guaranteed by family partitioning.
    # Still report multi-partition papers for visibility.
    multi_partition_papers = sorted(
        paper_id for paper_id, seen in paper_to_partitions.items() if len(seen) > 1
    )

    constraints = {
        "no_family_cross_split": True,
        "no_paper_leakage_within_family": True,
        "min_warning_or_conflict_family_in_dev": 1,
        "min_warning_or_conflict_family_in_test": 1,
        "preserve_clean_controls_in_dev": True,
        "preserve_clean_controls_in_test": True,
    }
    checks = {
        "family_cross_split_violations": family_cross_split_violations,
        "paper_leakage_violations": paper_leakage_violations,
        "multi_partition_papers_total": len(multi_partition_papers),
        "multi_partition_papers": multi_partition_papers,
        "dev_has_warning_or_conflict_family": partition_summary["dev"][
            "warning_or_conflict_families_total"
        ]
        >= 1,
        "test_has_warning_or_conflict_family": partition_summary["test"][
            "warning_or_conflict_families_total"
        ]
        >= 1,
        "dev_has_clean_control_family": partition_summary["dev"]["clean_control_families_total"] >= 1,
        "test_has_clean_control_family": partition_summary["test"]["clean_control_families_total"] >= 1,
    }

    manifest = {
        "split_id": SPLIT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "status": "materialized",
        "split_unit": "canonical_claim_id",
        "source_snapshot_jsonl": str(snapshot_jsonl_path),
        "source_snapshot_summary_json": str(snapshot_summary_path),
        "source_snapshot_sha256": _sha256_text(snapshot_jsonl_path),
        "policy_source": POLICY_SOURCE,
        "allocation_policy": {"train_pct": 0.6, "dev_pct": 0.2, "test_pct": 0.2},
        "constraints": constraints,
        "partition_family_ids": partitions,
    }

    summary = {
        "generated_at": _utc_now_iso(),
        "split_id": SPLIT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "source_snapshot_counts": snapshot_summary.get("counts", {}),
        "partitions": partition_summary,
        "checks": checks,
    }
    return family_partition_rows, partitioned_rows, manifest, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    family_partition_rows, partitioned_rows, manifest, summary = build_outputs(
        args.snapshot_jsonl.expanduser().resolve(),
        args.snapshot_summary_json.expanduser().resolve(),
    )

    manifest_json = output_dir / "claim_snapshot_v4_split_manifest.json"
    family_partitions_jsonl = output_dir / "claim_snapshot_v4_family_partitions.jsonl"
    train_jsonl = output_dir / "claim_snapshot_v4_train.jsonl"
    dev_jsonl = output_dir / "claim_snapshot_v4_dev.jsonl"
    test_jsonl = output_dir / "claim_snapshot_v4_test.jsonl"
    summary_json = output_dir / "claim_snapshot_v4_split_summary.json"

    _write_jsonl(family_partitions_jsonl, family_partition_rows)
    _write_jsonl(train_jsonl, partitioned_rows["train"])
    _write_jsonl(dev_jsonl, partitioned_rows["dev"])
    _write_jsonl(test_jsonl, partitioned_rows["test"])

    manifest["artifacts"] = {
        "family_partitions_jsonl": str(family_partitions_jsonl),
        "train_jsonl": str(train_jsonl),
        "dev_jsonl": str(dev_jsonl),
        "test_jsonl": str(test_jsonl),
        "summary_json": str(summary_json),
    }
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "train_families": len(manifest["partition_family_ids"]["train"]),
                "dev_families": len(manifest["partition_family_ids"]["dev"]),
                "test_families": len(manifest["partition_family_ids"]["test"]),
                "train_rows": len(partitioned_rows["train"]),
                "dev_rows": len(partitioned_rows["dev"]),
                "test_rows": len(partitioned_rows["test"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
