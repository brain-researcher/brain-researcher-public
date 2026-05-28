from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import run_claim_snapshot_v4_b2_baseline_eval as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_run_claim_snapshot_v4_b2_baseline_eval_reports_metadata_heuristic(
    tmp_path: Path,
) -> None:
    split_manifest = tmp_path / "split_manifest.json"
    train_jsonl = tmp_path / "train.jsonl"
    dev_jsonl = tmp_path / "dev.jsonl"
    test_jsonl = tmp_path / "test.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        train_jsonl,
        [
            {"example_id": "train:1", "gold_label": "retain_singleton_with_warning", "failure_tags": ["granularity_mismatch"], "snapshot_role": "singleton_warning", "adjudication_status": "reviewed_singleton_warning"},
            {"example_id": "train:2", "gold_label": "retain_singleton_with_warning", "failure_tags": ["granularity_mismatch"], "snapshot_role": "singleton_warning", "adjudication_status": "reviewed_singleton_warning"},
        ],
    )
    _write_jsonl(
        dev_jsonl,
        [
            {
                "example_id": "dev:conflict",
                "gold_label": "retain_conflict_cluster_with_warning",
                "failure_tags": ["polarity_or_antonym_confusion"],
                "snapshot_role": "conflict_cluster_warning",
                "adjudication_status": "reviewed_conflict_cluster_warning",
            },
            {
                "example_id": "dev:exclude",
                "gold_label": "exclude_from_snapshot",
                "failure_tags": ["modality_or_method_leakage"],
                "snapshot_role": "excluded_failure",
                "adjudication_status": "pending",
            },
            {
                "example_id": "dev:clean",
                "gold_label": "retain_singleton",
                "failure_tags": [],
                "snapshot_role": "control",
                "adjudication_status": "reviewed_singleton_control",
            },
        ],
    )
    _write_jsonl(
        test_jsonl,
        [
            {
                "example_id": "test:warn",
                "gold_label": "retain_singleton_with_warning",
                "failure_tags": ["granularity_mismatch"],
                "snapshot_role": "singleton_warning",
                "adjudication_status": "reviewed_singleton_warning",
            }
        ],
    )
    split_manifest.write_text(
        json.dumps(
            {
                "split_id": "claim_snapshot_v4_b2_split_20260314",
                "task_manifest_id": "claim_snapshot_v4_b2_review_seed_20260314",
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
            "--split-manifest-json",
            str(split_manifest),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    summary = json.loads(
        (output_dir / "claim_snapshot_v4_b2_baseline_eval_summary.json").read_text(encoding="utf-8")
    )
    assert summary["partitions"]["dev"]["majority_label"] == "retain_singleton_with_warning"
    assert summary["partitions"]["dev"]["heuristic_accuracy"] == 1.0
    assert summary["partitions"]["test"]["heuristic_accuracy"] == 1.0
