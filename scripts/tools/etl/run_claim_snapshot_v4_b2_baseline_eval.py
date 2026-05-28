#!/usr/bin/env python3
"""Run metadata baselines over the bounded B2 split."""

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
    parser.add_argument("--split-manifest-json", type=Path, required=True)
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


def _predict_metadata_heuristic(example: dict[str, Any]) -> str:
    failure_tags = {str(tag) for tag in list(example.get("failure_tags") or []) if str(tag)}
    snapshot_role = str(example.get("snapshot_role") or "")
    adjudication_status = str(example.get("adjudication_status") or "")

    if "conflict_cluster" in snapshot_role or "conflict_cluster" in adjudication_status:
        return "retain_conflict_cluster_with_warning"
    if "modality_or_method_leakage" in failure_tags:
        return "exclude_from_snapshot"
    if not failure_tags:
        return "retain_singleton"
    return "retain_singleton_with_warning"


def run_eval(split_manifest_path: Path, eval_partitions: Sequence[str]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    labels = [
        "retain_singleton",
        "retain_singleton_with_warning",
        "retain_conflict_cluster_with_warning",
        "exclude_from_snapshot",
    ]
    artifacts = dict(split_manifest["artifacts"])
    train_examples = list(_iter_jsonl(Path(artifacts["train_jsonl"])))
    train_counts = Counter(str(example["gold_label"]) for example in train_examples)
    majority_label = sorted(labels, key=lambda label: (-train_counts[label], label))[0]

    summary_partitions: dict[str, dict[str, Any]] = {}
    predictions: dict[str, list[dict[str, Any]]] = {}
    for partition in eval_partitions:
        examples = list(_iter_jsonl(Path(artifacts[f"{partition}_jsonl"])))
        golds = [str(example["gold_label"]) for example in examples]
        majority_preds = [majority_label for _ in examples]
        heuristic_preds = [_predict_metadata_heuristic(example) for example in examples]
        predictions[partition] = [
            {
                "split_id": split_manifest["split_id"],
                "partition": partition,
                "example_id": example["example_id"],
                "gold_label": example["gold_label"],
                "majority_prediction": majority_pred,
                "heuristic_prediction": heuristic_pred,
                "heuristic_correct": heuristic_pred == example["gold_label"],
            }
            for example, majority_pred, heuristic_pred in zip(examples, majority_preds, heuristic_preds)
        ]
        summary_partitions[partition] = {
            "examples_total": len(examples),
            "majority_label": majority_label,
            "majority_accuracy": (
                sum(1 for gold, pred in zip(golds, majority_preds) if gold == pred) / len(examples)
                if examples
                else 0.0
            ),
            "majority_macro_f1": _macro_f1(golds, majority_preds, labels),
            "heuristic_accuracy": (
                sum(1 for gold, pred in zip(golds, heuristic_preds) if gold == pred) / len(examples)
                if examples
                else 0.0
            ),
            "heuristic_macro_f1": _macro_f1(golds, heuristic_preds, labels),
            "gold_label_distribution": dict(sorted(Counter(golds).items())),
            "heuristic_prediction_distribution": dict(sorted(Counter(heuristic_preds).items())),
        }

    summary = {
        "generated_at": _utc_now_iso(),
        "split_id": split_manifest["split_id"],
        "task_manifest_id": split_manifest["task_manifest_id"],
        "eval_partitions": list(eval_partitions),
        "baselines": {
            "majority_label": majority_label,
            "metadata_heuristic": (
                "conflict role -> conflict retain; modality leakage -> exclude; "
                "no failure tags -> retain_singleton; else retain_singleton_with_warning"
            ),
        },
        "partitions": summary_partitions,
    }
    return summary, predictions


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary, predictions = run_eval(args.split_manifest_json, args.eval_partitions)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "claim_snapshot_v4_b2_baseline_eval_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for partition, rows in predictions.items():
        _write_jsonl(args.output_dir / f"{partition}_predictions.jsonl", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
