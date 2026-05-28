#!/usr/bin/env python3
"""Run minimal baselines over the claim_snapshot_v4 B1 downstream task manifest."""

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


def _predict_majority(train_examples: Sequence[dict[str, Any]], label_space: Sequence[str]) -> str:
    counts = Counter(str(example["gold_label"]) for example in train_examples)
    return sorted(label_space, key=lambda label: (-counts[label], label))[0]


def _predict_family_polarity_rule(example: dict[str, Any]) -> str:
    support_count = int(example.get("support_count") or 0)
    refute_count = int(example.get("refute_count") or 0)
    if support_count > 0 and refute_count > 0:
        return "conflict_bearing"
    if refute_count > 0:
        return "refute_only"
    if support_count > 0:
        return "support_only"
    return "insufficient"


def run_eval(task_manifest_path: Path, eval_partitions: Sequence[str]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest = json.loads(task_manifest_path.read_text(encoding="utf-8"))
    label_space = list(manifest["label_space"])
    artifacts = dict(manifest["artifacts"])
    train_examples = list(_iter_jsonl(Path(artifacts["train_jsonl"])))
    partition_examples = {
        partition: list(_iter_jsonl(Path(artifacts[f"{partition}_jsonl"])))
        for partition in eval_partitions
    }

    majority_label = _predict_majority(train_examples, label_space)
    all_predictions: dict[str, list[dict[str, Any]]] = {}
    summary_partitions: dict[str, dict[str, Any]] = {}

    for partition, examples in partition_examples.items():
        rows: list[dict[str, Any]] = []
        golds = [str(example["gold_label"]) for example in examples]
        majority_preds = [majority_label for _ in examples]
        rule_preds = [_predict_family_polarity_rule(example) for example in examples]
        for example, majority_pred, rule_pred in zip(examples, majority_preds, rule_preds):
            rows.append(
                {
                    "task_manifest_id": manifest["task_manifest_id"],
                    "partition": partition,
                    "example_id": example["example_id"],
                    "canonical_claim_id": example["canonical_claim_id"],
                    "gold_label": example["gold_label"],
                    "majority_prediction": majority_pred,
                    "majority_correct": majority_pred == example["gold_label"],
                    "family_polarity_rule_prediction": rule_pred,
                    "family_polarity_rule_correct": rule_pred == example["gold_label"],
                }
            )
        all_predictions[partition] = rows
        summary_partitions[partition] = {
            "examples_total": len(examples),
            "majority_label": majority_label,
            "majority_accuracy": (
                sum(1 for gold, pred in zip(golds, majority_preds) if gold == pred) / len(examples)
                if examples
                else 0.0
            ),
            "majority_macro_f1": _macro_f1(golds, majority_preds, label_space),
            "family_polarity_rule_accuracy": (
                sum(1 for gold, pred in zip(golds, rule_preds) if gold == pred) / len(examples)
                if examples
                else 0.0
            ),
            "family_polarity_rule_macro_f1": _macro_f1(golds, rule_preds, label_space),
            "gold_label_distribution": dict(sorted(Counter(golds).items())),
        }

    summary = {
        "generated_at": _utc_now_iso(),
        "task_manifest_id": manifest["task_manifest_id"],
        "eval_partitions": list(eval_partitions),
        "baselines": {
            "majority_label": majority_label,
            "family_polarity_rule": "predict from support_count/refute_count signature",
        },
        "partitions": summary_partitions,
    }
    return summary, all_predictions


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary, predictions = run_eval(args.task_manifest_json, args.eval_partitions)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "claim_snapshot_v4_baseline_eval_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for partition, rows in predictions.items():
        _write_jsonl(args.output_dir / f"{partition}_predictions.jsonl", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
