#!/usr/bin/env python3
"""Run a metadata-only richer baseline for the B1 claim_snapshot_v4 task."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_EVAL_PARTITIONS = ("dev", "test")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--eval-partitions",
        nargs="+",
        default=list(DEFAULT_EVAL_PARTITIONS),
        choices=["train", "dev", "test"],
    )
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


def _macro_f1(golds: Sequence[str], preds: Sequence[str], labels: Sequence[str]) -> float:
    f1s: list[float] = []
    for label in labels:
        tp = sum(1 for gold, pred in zip(golds, preds) if gold == label and pred == label)
        fp = sum(1 for gold, pred in zip(golds, preds) if gold != label and pred == label)
        fn = sum(1 for gold, pred in zip(golds, preds) if gold == label and pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)
        f1s.append(f1)
    return sum(f1s) / len(f1s) if f1s else 0.0


def _family_role_signature(example: dict[str, Any]) -> set[str]:
    roles = {str(role) for role in list(example.get("snapshot_roles") or []) if str(role)}
    for source_row in list(example.get("source_rows") or []):
        role = str(source_row.get("snapshot_role") or "")
        if role:
            roles.add(role)
    return roles


def _union_failure_tags(example: dict[str, Any]) -> set[str]:
    tags = {str(tag) for tag in list(example.get("failure_tags_union") or []) if str(tag)}
    for source_row in list(example.get("source_rows") or []):
        tags.update(str(tag) for tag in list(source_row.get("failure_tags") or []) if str(tag))
    return tags


def _quality_profiles(example: dict[str, Any]) -> set[str]:
    profiles = set()
    for source_row in list(example.get("source_rows") or []):
        profile = str(source_row.get("quality_profile") or "")
        if profile:
            profiles.add(profile)
    return profiles


def _predict_richer_metadata_heuristic(example: dict[str, Any]) -> str:
    roles = _family_role_signature(example)
    failure_tags = _union_failure_tags(example)
    quality_profiles = _quality_profiles(example)

    if "conflict_cluster_warning" in roles:
        return "conflict_bearing"
    if (
        "singleton_bridge_conflict_warning" in roles
        or ("bridge_conflict" in " ".join(sorted(roles)))
    ) and "kg_bootstrap" in quality_profiles:
        return "refute_only"
    if (
        example.get("warning_or_conflict_family")
        and "population_or_disease_scope_mismatch" in failure_tags
        and "kg_bootstrap" in quality_profiles
        and "Concept" in list(example.get("target_types") or [])
    ):
        return "refute_only"
    return "support_only"


def run_eval(task_manifest_path: Path, eval_partitions: Sequence[str]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest = json.loads(task_manifest_path.read_text(encoding="utf-8"))
    label_space = list(manifest["label_space"])
    artifacts = dict(manifest["artifacts"])
    train_examples = list(_iter_jsonl(Path(artifacts["train_jsonl"])))
    train_counts = Counter(str(example["gold_label"]) for example in train_examples)
    train_majority_label = sorted(label_space, key=lambda label: (-train_counts[label], label))[0]

    prediction_rows: dict[str, list[dict[str, Any]]] = {}
    partition_summary: dict[str, dict[str, Any]] = {}
    for partition in eval_partitions:
        examples = list(_iter_jsonl(Path(artifacts[f"{partition}_jsonl"])))
        golds = [str(example["gold_label"]) for example in examples]
        preds = [_predict_richer_metadata_heuristic(example) for example in examples]
        prediction_rows[partition] = [
            {
                "task_manifest_id": manifest["task_manifest_id"],
                "partition": partition,
                "example_id": example["example_id"],
                "canonical_claim_id": example["canonical_claim_id"],
                "gold_label": example["gold_label"],
                "prediction": pred,
                "correct": pred == example["gold_label"],
                "snapshot_roles": list(example.get("snapshot_roles") or []),
                "failure_tags_union": list(example.get("failure_tags_union") or []),
            }
            for example, pred in zip(examples, preds)
        ]
        partition_summary[partition] = {
            "examples_total": len(examples),
            "train_majority_label": train_majority_label,
            "accuracy": (
                sum(1 for gold, pred in zip(golds, preds) if gold == pred) / len(examples)
                if examples
                else 0.0
            ),
            "macro_f1": _macro_f1(golds, preds, label_space),
            "gold_label_distribution": dict(sorted(Counter(golds).items())),
            "prediction_distribution": dict(sorted(Counter(preds).items())),
        }

    summary = {
        "generated_at": _utc_now_iso(),
        "task_manifest_id": manifest["task_manifest_id"],
        "eval_partitions": list(eval_partitions),
        "baseline": {
            "name": "metadata_richer_b1_heuristic",
            "description": (
                "Uses snapshot-role, failure-tag, target-type, and quality-profile metadata "
                "without consulting support_count/refute_count."
            ),
            "train_majority_label": train_majority_label,
        },
        "partitions": partition_summary,
    }
    return summary, prediction_rows


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary, prediction_rows = run_eval(args.task_manifest_json, args.eval_partitions)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "claim_snapshot_v4_richer_b1_baseline_eval_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for partition, rows in prediction_rows.items():
        _write_jsonl(args.output_dir / f"{partition}_predictions.jsonl", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
