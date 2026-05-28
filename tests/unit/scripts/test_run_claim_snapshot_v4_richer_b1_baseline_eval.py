from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import run_claim_snapshot_v4_richer_b1_baseline_eval as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_run_claim_snapshot_v4_richer_b1_baseline_eval_uses_metadata_heuristics(
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
                "snapshot_roles": ["singleton_warning"],
                "failure_tags_union": ["granularity_mismatch"],
                "target_types": ["Region"],
                "warning_or_conflict_family": True,
                "source_rows": [{"snapshot_role": "singleton_warning", "quality_profile": "high_precision"}],
            }
        ],
    )
    _write_jsonl(
        dev_jsonl,
        [
            {
                "example_id": "dev:conflict",
                "canonical_claim_id": "canonical_claim:conflict",
                "gold_label": "conflict_bearing",
                "snapshot_roles": ["conflict_cluster_warning"],
                "failure_tags_union": ["polarity_or_antonym_confusion"],
                "target_types": ["Concept"],
                "warning_or_conflict_family": True,
                "source_rows": [{"snapshot_role": "conflict_cluster_warning", "quality_profile": "kg_bootstrap"}],
            }
        ],
    )
    _write_jsonl(
        test_jsonl,
        [
            {
                "example_id": "test:refute",
                "canonical_claim_id": "canonical_claim:refute",
                "gold_label": "refute_only",
                "snapshot_roles": ["singleton_bridge_conflict_warning"],
                "failure_tags_union": ["population_or_disease_scope_mismatch"],
                "target_types": ["Concept"],
                "warning_or_conflict_family": True,
                "source_rows": [
                    {
                        "snapshot_role": "singleton_bridge_conflict_warning",
                        "quality_profile": "kg_bootstrap",
                    }
                ],
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
        (output_dir / "claim_snapshot_v4_richer_b1_baseline_eval_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["partitions"]["dev"]["accuracy"] == 1.0
    assert summary["partitions"]["test"]["accuracy"] == 1.0

    dev_predictions = [
        json.loads(line)
        for line in (output_dir / "dev_predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    test_predictions = [
        json.loads(line)
        for line in (output_dir / "test_predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert dev_predictions[0]["prediction"] == "conflict_bearing"
    assert test_predictions[0]["prediction"] == "refute_only"
