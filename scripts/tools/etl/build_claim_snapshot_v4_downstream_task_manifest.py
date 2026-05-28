#!/usr/bin/env python3
"""Build the first claim-side downstream task manifest from claim_snapshot_v4 split."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_MANIFEST_ID = "claim_snapshot_v4_b1_family_stance_20260314"
TASK_FAMILY = "B1_canonical_claim_family_support_conflict_reasoning"
TASK_VARIANT = "family_stance_v1"
TASK_CHARTER_SOURCE = (
    "/app/brain_researcher/docs/planning/task_charter.md"
)
TASK_POLICY_SOURCE = (
    "/app/brain_researcher/docs/planning/train_dev_test_split_proposal.md"
)
LABEL_SPACE = ["support_only", "refute_only", "conflict_bearing", "insufficient"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-manifest-json", type=Path, required=True)
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


def _derive_gold_label(members: Sequence[dict[str, Any]]) -> str:
    polarities = {
        str(member.get("polarity") or "").strip()
        for member in members
        if str(member.get("polarity") or "").strip()
    }
    if len(polarities) > 1:
        return "conflict_bearing"
    if polarities == {"supports"}:
        return "support_only"
    if polarities == {"refutes"}:
        return "refute_only"
    return "insufficient"


def _family_has_warning_or_conflict(members: Sequence[dict[str, Any]]) -> bool:
    roles = {str(member.get("snapshot_role") or "") for member in members}
    return any("warning" in role or "conflict" in role for role in roles)


def _family_has_clean_control(members: Sequence[dict[str, Any]]) -> bool:
    roles = {str(member.get("snapshot_role") or "") for member in members}
    clean_roles = {"control", "singleton_expansion_clean", "singleton_breadth_clean"}
    return not roles.isdisjoint(clean_roles)


def build_outputs(split_manifest_path: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    if split_manifest.get("split_unit") != "canonical_claim_id":
        raise SystemExit(
            "Fail-closed downstream task manifest mismatch: split_unit must be canonical_claim_id"
        )

    artifacts = dict(split_manifest.get("artifacts") or {})
    partition_paths = {
        "train": Path(artifacts["train_jsonl"]),
        "dev": Path(artifacts["dev_jsonl"]),
        "test": Path(artifacts["test_jsonl"]),
    }
    partition_family_ids = {
        partition: sorted(str(family_id) for family_id in family_ids)
        for partition, family_ids in dict(split_manifest.get("partition_family_ids") or {}).items()
    }

    partition_examples: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    partition_summary: dict[str, dict[str, Any]] = {}

    for partition, rows_path in partition_paths.items():
        rows = list(_iter_jsonl(rows_path))
        family_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if str(row.get("partition") or partition) != partition:
                raise SystemExit(
                    "Fail-closed downstream task manifest mismatch: "
                    f"row partition mismatch for {row.get('source_claim_id')}"
                )
            family_to_rows[str(row["canonical_claim_id"])].append(row)

        actual_family_ids = sorted(family_to_rows)
        expected_family_ids = partition_family_ids[partition]
        if actual_family_ids != expected_family_ids:
            raise SystemExit(
                "Fail-closed downstream task manifest mismatch: "
                f"{partition} family ids do not match split manifest"
            )

        label_counter: Counter[str] = Counter()
        target_type_counter: Counter[str] = Counter()
        warning_or_conflict_total = 0
        clean_control_total = 0
        for canonical_claim_id in expected_family_ids:
            members = family_to_rows[canonical_claim_id]
            gold_label = _derive_gold_label(members)
            label_counter[gold_label] += 1
            target_type_counter.update(
                str(member.get("target_type") or "")
                for member in members
                if str(member.get("target_type") or "")
            )
            has_warning_or_conflict = _family_has_warning_or_conflict(members)
            has_clean_control = _family_has_clean_control(members)
            if has_warning_or_conflict:
                warning_or_conflict_total += 1
            if has_clean_control:
                clean_control_total += 1
            support_count = sum(1 for member in members if member.get("polarity") == "supports")
            refute_count = sum(1 for member in members if member.get("polarity") == "refutes")
            example = {
                "task_manifest_id": TASK_MANIFEST_ID,
                "task_family": TASK_FAMILY,
                "task_variant": TASK_VARIANT,
                "example_id": f"{partition}:{canonical_claim_id}",
                "partition": partition,
                "canonical_claim_id": canonical_claim_id,
                "gold_label": gold_label,
                "gold_label_source": "member_polarity_signature",
                "family_member_count": len(members),
                "support_count": support_count,
                "refute_count": refute_count,
                "warning_or_conflict_family": has_warning_or_conflict,
                "clean_control_family": has_clean_control,
                "paper_ids": sorted(
                    {str(member.get("paper_id") or "") for member in members if member.get("paper_id")}
                ),
                "target_ids": sorted(
                    {str(member.get("target_id") or "") for member in members if member.get("target_id")}
                ),
                "target_types": sorted(
                    {
                        str(member.get("target_type") or "")
                        for member in members
                        if member.get("target_type")
                    }
                ),
                "snapshot_roles": sorted(
                    {
                        str(member.get("snapshot_role") or "")
                        for member in members
                        if member.get("snapshot_role")
                    }
                ),
                "failure_tags_union": sorted(
                    {
                        tag
                        for member in members
                        for tag in list(member.get("failure_tags") or [])
                        if tag
                    }
                ),
                "source_rows": [
                    {
                        "source_claim_id": member["source_claim_id"],
                        "paper_id": member.get("paper_id"),
                        "target_id": member.get("target_id"),
                        "target_type": member.get("target_type"),
                        "claim_text": member.get("claim_text"),
                        "polarity": member.get("polarity"),
                        "snapshot_role": member.get("snapshot_role"),
                        "failure_tags": list(member.get("failure_tags") or []),
                        "quality_profile": member.get("quality_profile"),
                        "benchmark_eligibility": member.get("benchmark_eligibility"),
                        "candidate_lane_present": bool(member.get("candidate_lane_present")),
                    }
                    for member in members
                ],
            }
            partition_examples[partition].append(example)

        partition_summary[partition] = {
            "examples_total": len(partition_examples[partition]),
            "rows_total": len(rows),
            "label_support_only": label_counter["support_only"],
            "label_refute_only": label_counter["refute_only"],
            "label_conflict_bearing": label_counter["conflict_bearing"],
            "label_insufficient": label_counter["insufficient"],
            "warning_or_conflict_families_total": warning_or_conflict_total,
            "clean_control_families_total": clean_control_total,
            "target_type_Concept_examples": target_type_counter["Concept"],
            "target_type_Region_examples": target_type_counter["Region"],
            "target_type_Task_examples": target_type_counter["Task"],
        }

    manifest = {
        "task_manifest_id": TASK_MANIFEST_ID,
        "status": "materialized",
        "task_family": TASK_FAMILY,
        "task_variant": TASK_VARIANT,
        "input_unit": "canonical_claim_id",
        "task_objective": (
            "Predict the family-level stance label for a reviewed canonical claim family "
            "while preserving paper-level support/refute disagreement."
        ),
        "label_space": LABEL_SPACE,
        "label_notes": {
            "support_only": "All retained family members support the proposition.",
            "refute_only": "All retained family members refute the proposition.",
            "conflict_bearing": "Retained family members contain both support and refute stances.",
            "insufficient": "Family lacks auditable stance-bearing members.",
        },
        "task_charter_source": TASK_CHARTER_SOURCE,
        "task_policy_source": TASK_POLICY_SOURCE,
        "source_split_manifest_json": str(split_manifest_path),
        "source_split_manifest_sha256": _sha256_text(split_manifest_path),
        "source_split_id": split_manifest["split_id"],
        "source_snapshot_id": split_manifest["snapshot_id"],
    }

    summary = {
        "generated_at": _utc_now_iso(),
        "task_manifest_id": TASK_MANIFEST_ID,
        "task_family": TASK_FAMILY,
        "task_variant": TASK_VARIANT,
        "partitions": partition_summary,
        "notes": {
            "bounded_warning_heavy": True,
            "label_space_refines_charter_b1": True,
            "refute_only_is_explicit_not_collapsed_into_insufficient": True,
        },
    }
    return manifest, partition_examples, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest, partition_examples, summary = build_outputs(args.split_manifest_json)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "claim_snapshot_v4_downstream_task_manifest.json"
    train_path = args.output_dir / "claim_snapshot_v4_b1_train.jsonl"
    dev_path = args.output_dir / "claim_snapshot_v4_b1_dev.jsonl"
    test_path = args.output_dir / "claim_snapshot_v4_b1_test.jsonl"
    summary_path = args.output_dir / "claim_snapshot_v4_downstream_task_summary.json"

    manifest["artifacts"] = {
        "train_jsonl": str(train_path),
        "dev_jsonl": str(dev_path),
        "test_jsonl": str(test_path),
        "summary_json": str(summary_path),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_jsonl(train_path, partition_examples["train"])
    _write_jsonl(dev_path, partition_examples["dev"])
    _write_jsonl(test_path, partition_examples["test"])
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
