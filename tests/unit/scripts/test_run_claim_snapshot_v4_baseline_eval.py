from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import run_claim_snapshot_v4_baseline_eval as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_run_claim_snapshot_v4_baseline_eval_reports_majority_and_rule_metrics(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "task_manifest.json"
    train_jsonl = tmp_path / "train.jsonl"
    dev_jsonl = tmp_path / "dev.jsonl"
    test_jsonl = tmp_path / "test.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        train_jsonl,
        [
            {
                "example_id": "train:a",
                "canonical_claim_id": "canonical_claim:a",
                "gold_label": "support_only",
                "support_count": 1,
                "refute_count": 0,
            },
            {
                "example_id": "train:b",
                "canonical_claim_id": "canonical_claim:b",
                "gold_label": "support_only",
                "support_count": 1,
                "refute_count": 0,
            },
        ],
    )
    _write_jsonl(
        dev_jsonl,
        [
            {
                "example_id": "dev:a",
                "canonical_claim_id": "canonical_claim:c",
                "gold_label": "support_only",
                "support_count": 1,
                "refute_count": 0,
            },
            {
                "example_id": "dev:b",
                "canonical_claim_id": "canonical_claim:d",
                "gold_label": "conflict_bearing",
                "support_count": 1,
                "refute_count": 1,
            },
        ],
    )
    _write_jsonl(
        test_jsonl,
        [
            {
                "example_id": "test:a",
                "canonical_claim_id": "canonical_claim:e",
                "gold_label": "refute_only",
                "support_count": 0,
                "refute_count": 1,
            }
        ],
    )

    manifest_path.write_text(
        json.dumps(
            {
                "task_manifest_id": "claim_snapshot_v4_b1_family_stance_20260314",
                "label_space": ["support_only", "refute_only", "conflict_bearing", "insufficient"],
                "artifacts": {
                    "train_jsonl": str(train_jsonl),
                    "dev_jsonl": str(dev_jsonl),
                    "test_jsonl": str(test_jsonl),
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = module.main(
        [
            "--task-manifest-json",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "claim_snapshot_v4_baseline_eval_summary.json").read_text(encoding="utf-8")
    )
    assert summary["baselines"]["majority_label"] == "support_only"
    assert summary["partitions"]["dev"]["majority_accuracy"] == 0.5
    assert summary["partitions"]["dev"]["family_polarity_rule_accuracy"] == 1.0
    assert summary["partitions"]["test"]["family_polarity_rule_accuracy"] == 1.0

    dev_predictions = [
        json.loads(line)
        for line in (output_dir / "dev_predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert dev_predictions[1]["family_polarity_rule_prediction"] == "conflict_bearing"
