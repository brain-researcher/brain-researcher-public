#!/usr/bin/env python3
"""Materialize a bounded split for the B2 reviewed-seed task manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPLIT_ID = "claim_snapshot_v4_b2_split_conflict_expanded_20260314"
TASK_MANIFEST_ID = "claim_snapshot_v4_b2_review_seed_conflict_expanded_20260314"
POLICY_SOURCE = (
    "/app/brain_researcher/docs/planning/task_charter.md"
)

DEV_EXAMPLE_IDS = [
    "claim:08d8acd1a4f1cc397140594f824bab95",
    "claim:592e21efcf95e2cb37890b1bd835ef03",
    "claim:058715fda88bc99ff8a9936630079971",
    "claim:3f7954fb1ea68cce5deef1cce4a0e910",
    "claim:0a454b9f9b9ff3e630176ceb3fde874b",
    "claim:5432581b4cf7885b281b5b3e9a26baba",
    "claim:bb60c12136f31d767883a7cf31b85e58",
]

TEST_EXAMPLE_IDS = [
    "claim:717aa816a1b759ed0631a31733f83ef0",
    "claim:wm_dlpfc",
    "claim:60de6863de404dd92ddf6113b0296d84",
    "claim:ae95759619d6ef7c80f772c4f85f2265",
    "claim:112ab135f7e98e7fef3af9ab0037a729",
    "claim:36440b921722e3394eef114ce3e1be3c",
    "claim:9f78b034872ba2ab733d1b43a687804c",
    "claim:ebb1be1002d3e248b15edcf1587285ea",
    "claim:b81e188008db904ec71df67f8623f067",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest-json", type=Path, required=True)
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


def _choose_partition_for_extra_conflict(
    *,
    dev_ids: set[str],
    test_ids: set[str],
    by_id: dict[str, dict[str, Any]],
) -> str:
    def _conflict_count(example_ids: set[str]) -> int:
        return sum(
            1
            for example_id in example_ids
            if str(by_id[example_id]["gold_label"]) == "retain_conflict_cluster_with_warning"
        )

    dev_conflict = _conflict_count(dev_ids)
    test_conflict = _conflict_count(test_ids)
    if test_conflict == 0:
        return "test"
    if dev_conflict == 0:
        return "dev"
    return min(
        ("dev", "test"),
        key=lambda partition: (
            _conflict_count(dev_ids if partition == "dev" else test_ids),
            len(dev_ids if partition == "dev" else test_ids),
            partition,
        ),
    )


def build_outputs(task_manifest_path: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    task_manifest = json.loads(task_manifest_path.read_text(encoding="utf-8"))
    examples = list(_iter_jsonl(Path(task_manifest["artifacts"]["examples_jsonl"])))
    by_id = {str(row["example_id"]): row for row in examples}
    all_ids = set(by_id)
    dev_ids = set(DEV_EXAMPLE_IDS)
    test_ids = set(TEST_EXAMPLE_IDS)
    if dev_ids & test_ids:
        overlap = sorted(dev_ids & test_ids)
        raise SystemExit(f"Fail-closed B2 split manifest mismatch: dev/test overlap {overlap}")
    missing = sorted((dev_ids | test_ids) - all_ids)
    if missing:
        raise SystemExit(f"Fail-closed B2 split manifest mismatch: missing example ids {missing}")

    by_canonical: dict[str, list[str]] = defaultdict(list)
    for example_id, row in by_id.items():
        canonical_claim_id = str(row.get("canonical_claim_id") or "").strip()
        if canonical_claim_id:
            by_canonical[canonical_claim_id].append(example_id)
    for canonical_claim_id, example_ids in sorted(by_canonical.items()):
        family_has_conflict = any(
            str(by_id[example_id]["gold_label"]) == "retain_conflict_cluster_with_warning"
            for example_id in example_ids
        )
        if not family_has_conflict:
            continue
        if canonical_claim_id in {
            str(by_id[example_id].get("canonical_claim_id") or "")
            for example_id in (dev_ids | test_ids)
        }:
            continue
        target_partition = _choose_partition_for_extra_conflict(
            dev_ids=dev_ids,
            test_ids=test_ids,
            by_id=by_id,
        )
        if target_partition == "dev":
            dev_ids.update(example_ids)
        else:
            test_ids.update(example_ids)

    partitions = {
        "dev": sorted(dev_ids),
        "test": sorted(test_ids),
        "train": sorted(all_ids - dev_ids - test_ids),
    }

    example_partitions: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    partition_summary: dict[str, dict[str, Any]] = {}
    paper_to_partitions: dict[str, set[str]] = defaultdict(set)
    canonical_to_partitions: dict[str, set[str]] = defaultdict(set)

    for partition, example_ids in partitions.items():
        rows = [by_id[example_id] for example_id in example_ids]
        label_counter: Counter[str] = Counter()
        target_type_counter: Counter[str] = Counter()
        review_stage_counter: Counter[str] = Counter()
        papers: set[str] = set()
        canonicals: set[str] = set()
        for row in rows:
            label_counter[str(row["gold_label"])] += 1
            target_type = str(row.get("target_type") or "")
            if target_type:
                target_type_counter[target_type] += 1
            review_stage_counter[str(row.get("review_stage") or "")] += 1
            paper_id = str(row.get("paper_id") or "")
            if paper_id:
                papers.add(paper_id)
                paper_to_partitions[paper_id].add(partition)
            canonical_claim_id = str(row.get("canonical_claim_id") or "")
            if canonical_claim_id:
                canonicals.add(canonical_claim_id)
                canonical_to_partitions[canonical_claim_id].add(partition)
            example_partitions[partition].append(
                {
                    **row,
                    "split_id": SPLIT_ID,
                    "partition": partition,
                }
            )
        partition_summary[partition] = {
            "examples_total": len(rows),
            "papers_total": len(papers),
            "canonical_families_total": len(canonicals),
            "label_retain_singleton": label_counter["retain_singleton"],
            "label_retain_singleton_with_warning": label_counter["retain_singleton_with_warning"],
            "label_retain_conflict_cluster_with_warning": label_counter[
                "retain_conflict_cluster_with_warning"
            ],
            "label_exclude_from_snapshot": label_counter["exclude_from_snapshot"],
            "target_type_Concept": target_type_counter["Concept"],
            "target_type_Region": target_type_counter["Region"],
            "target_type_Task": target_type_counter["Task"],
            **{
                f"review_stage_{stage}": review_stage_counter[stage]
                for stage in sorted(review_stage_counter)
            },
        }

    paper_leakage = sorted(
        paper_id for paper_id, seen in paper_to_partitions.items() if len(seen) > 1
    )
    canonical_leakage = sorted(
        canonical_id for canonical_id, seen in canonical_to_partitions.items() if len(seen) > 1
    )
    checks = {
        "paper_leakage_violations": len(paper_leakage),
        "paper_leakage_ids": paper_leakage,
        "canonical_leakage_violations": len(canonical_leakage),
        "canonical_leakage_ids": canonical_leakage,
        "dev_has_retain_singleton": partition_summary["dev"]["label_retain_singleton"] >= 1,
        "test_has_retain_singleton": partition_summary["test"]["label_retain_singleton"] >= 1,
        "dev_has_warning_retain": partition_summary["dev"]["label_retain_singleton_with_warning"] >= 1,
        "test_has_warning_retain": partition_summary["test"]["label_retain_singleton_with_warning"] >= 1,
        "dev_has_exclude": partition_summary["dev"]["label_exclude_from_snapshot"] >= 1,
        "test_has_exclude": partition_summary["test"]["label_exclude_from_snapshot"] >= 1,
        "dev_has_conflict": partition_summary["dev"]["label_retain_conflict_cluster_with_warning"] >= 1,
        "test_has_conflict": partition_summary["test"]["label_retain_conflict_cluster_with_warning"] >= 1,
    }
    if checks["paper_leakage_violations"] or checks["canonical_leakage_violations"]:
        raise SystemExit("Fail-closed B2 split manifest mismatch: leakage detected")
    for key, ok in checks.items():
        if key.endswith(("_has_retain_singleton", "_has_warning_retain", "_has_exclude", "_has_conflict")) and not ok:
            raise SystemExit(f"Fail-closed B2 split manifest mismatch: check failed {key}")

    manifest = {
        "split_id": SPLIT_ID,
        "status": "materialized",
        "task_manifest_id": TASK_MANIFEST_ID,
        "split_unit": "example_id",
        "task_policy_source": POLICY_SOURCE,
        "source_task_manifest_json": str(task_manifest_path),
        "source_task_manifest_sha256": _sha256_text(task_manifest_path),
        "partition_example_ids": partitions,
    }
    summary = {
        "generated_at": _utc_now_iso(),
        "split_id": SPLIT_ID,
        "task_manifest_id": TASK_MANIFEST_ID,
        "partitions": partition_summary,
        "checks": checks,
        "notes": {
            "bounded_curated_split": True,
            "conflict_families_present_in_both_eval_partitions": True,
        },
    }
    return manifest, example_partitions, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest, example_partitions, summary = build_outputs(args.task_manifest_json)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "claim_snapshot_v4_b2_split_manifest.json"
    train_path = args.output_dir / "claim_snapshot_v4_b2_train.jsonl"
    dev_path = args.output_dir / "claim_snapshot_v4_b2_dev.jsonl"
    test_path = args.output_dir / "claim_snapshot_v4_b2_test.jsonl"
    summary_path = args.output_dir / "claim_snapshot_v4_b2_split_summary.json"
    manifest["artifacts"] = {
        "train_jsonl": str(train_path),
        "dev_jsonl": str(dev_path),
        "test_jsonl": str(test_path),
        "summary_json": str(summary_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_jsonl(train_path, example_partitions["train"])
    _write_jsonl(dev_path, example_partitions["dev"])
    _write_jsonl(test_path, example_partitions["test"])
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
