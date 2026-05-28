from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v4_downstream_task_manifest as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v4_downstream_task_manifest_groups_families(tmp_path: Path) -> None:
    split_manifest = tmp_path / "split_manifest.json"
    train_jsonl = tmp_path / "train.jsonl"
    dev_jsonl = tmp_path / "dev.jsonl"
    test_jsonl = tmp_path / "test.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        train_jsonl,
        [
            {
                "source_claim_id": "claim:train_support",
                "canonical_claim_id": "canonical_claim:train_support",
                "partition": "train",
                "paper_id": "paper:train_support",
                "target_id": "concept:memory",
                "target_type": "Concept",
                "claim_text": "Memory improves.",
                "polarity": "supports",
                "snapshot_role": "control",
                "failure_tags": [],
                "quality_profile": "high_precision",
                "benchmark_eligibility": "eligible",
                "candidate_lane_present": False,
            }
        ],
    )
    _write_jsonl(
        dev_jsonl,
        [
            {
                "source_claim_id": "claim:dev_a",
                "canonical_claim_id": "canonical_claim:dev_conflict",
                "partition": "dev",
                "paper_id": "paper:dev_a",
                "target_id": "concept:attention",
                "target_type": "Concept",
                "claim_text": "Attention increases.",
                "polarity": "supports",
                "snapshot_role": "conflict_cluster_warning",
                "failure_tags": ["granularity_mismatch"],
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only",
                "candidate_lane_present": False,
            },
            {
                "source_claim_id": "claim:dev_b",
                "canonical_claim_id": "canonical_claim:dev_conflict",
                "partition": "dev",
                "paper_id": "paper:dev_b",
                "target_id": "concept:attention",
                "target_type": "Concept",
                "claim_text": "Attention decreases.",
                "polarity": "refutes",
                "snapshot_role": "conflict_cluster_warning",
                "failure_tags": ["granularity_mismatch"],
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only",
                "candidate_lane_present": False,
            },
        ],
    )
    _write_jsonl(
        test_jsonl,
        [
            {
                "source_claim_id": "claim:test_refute",
                "canonical_claim_id": "canonical_claim:test_refute",
                "partition": "test",
                "paper_id": "paper:test_refute",
                "target_id": "concept:default_mode_network",
                "target_type": "Concept",
                "claim_text": "DMN unchanged.",
                "polarity": "refutes",
                "snapshot_role": "singleton_bridge_conflict_warning",
                "failure_tags": ["population_or_disease_scope_mismatch"],
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only",
                "candidate_lane_present": False,
            }
        ],
    )

    split_manifest.write_text(
        json.dumps(
            {
                "split_id": "split:test",
                "snapshot_id": "claim_snapshot_v4",
                "split_unit": "canonical_claim_id",
                "partition_family_ids": {
                    "train": ["canonical_claim:train_support"],
                    "dev": ["canonical_claim:dev_conflict"],
                    "test": ["canonical_claim:test_refute"],
                },
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

    manifest = json.loads(
        (output_dir / "claim_snapshot_v4_downstream_task_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["task_family"] == module.TASK_FAMILY
    assert manifest["label_space"] == module.LABEL_SPACE

    dev_examples = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v4_b1_dev.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(dev_examples) == 1
    assert dev_examples[0]["gold_label"] == "conflict_bearing"
    assert dev_examples[0]["support_count"] == 1
    assert dev_examples[0]["refute_count"] == 1

    test_examples = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v4_b1_test.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert test_examples[0]["gold_label"] == "refute_only"

    summary = json.loads(
        (output_dir / "claim_snapshot_v4_downstream_task_summary.json").read_text(encoding="utf-8")
    )
    assert summary["partitions"]["train"]["label_support_only"] == 1
    assert summary["partitions"]["dev"]["label_conflict_bearing"] == 1
    assert summary["partitions"]["test"]["label_refute_only"] == 1


def test_build_claim_snapshot_v4_downstream_task_manifest_fails_on_family_mismatch(
    tmp_path: Path,
) -> None:
    split_manifest = tmp_path / "split_manifest.json"
    train_jsonl = tmp_path / "train.jsonl"
    dev_jsonl = tmp_path / "dev.jsonl"
    test_jsonl = tmp_path / "test.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(train_jsonl, [])
    _write_jsonl(dev_jsonl, [])
    _write_jsonl(test_jsonl, [])

    split_manifest.write_text(
        json.dumps(
            {
                "split_id": "split:test",
                "snapshot_id": "claim_snapshot_v4",
                "split_unit": "canonical_claim_id",
                "partition_family_ids": {
                    "train": ["canonical_claim:missing"],
                    "dev": [],
                    "test": [],
                },
                "artifacts": {
                    "train_jsonl": str(train_jsonl),
                    "dev_jsonl": str(dev_jsonl),
                    "test_jsonl": str(test_jsonl),
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        module.main(
            [
                "--split-manifest-json",
                str(split_manifest),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed downstream task manifest mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed downstream task manifest mismatch")
