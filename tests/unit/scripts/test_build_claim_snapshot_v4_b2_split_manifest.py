from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v4_b2_split_manifest as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v4_b2_split_manifest_materializes_curated_split(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task_manifest = tmp_path / "task_manifest.json"
    examples_jsonl = tmp_path / "examples.jsonl"
    output_dir = tmp_path / "out"
    rows = [
        {
            "example_id": "claim:dev_conflict_a",
            "paper_id": "paper:dev_conflict_a",
            "canonical_claim_id": "canonical_claim:conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:dev_conflict_b",
            "paper_id": "paper:dev_conflict_b",
            "canonical_claim_id": "canonical_claim:conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:dev_singleton",
            "paper_id": "paper:dev_singleton",
            "canonical_claim_id": "canonical_claim:dev_singleton",
            "gold_label": "retain_singleton",
            "target_type": "Concept",
            "review_stage": "v2",
        },
        {
            "example_id": "claim:dev_exclude",
            "paper_id": "paper:dev_exclude",
            "canonical_claim_id": "canonical_claim:dev_exclude",
            "gold_label": "exclude_from_snapshot",
            "target_type": "Task",
            "review_stage": "v2",
        },
        {
            "example_id": "claim:dev_warn_a",
            "paper_id": "paper:dev_warn_a",
            "canonical_claim_id": "canonical_claim:dev_warn_a",
            "gold_label": "retain_singleton_with_warning",
            "target_type": "Region",
            "review_stage": "v3",
        },
        {
            "example_id": "claim:dev_warn_b",
            "paper_id": "paper:dev_warn_b",
            "canonical_claim_id": "canonical_claim:dev_warn_b",
            "gold_label": "retain_singleton_with_warning",
            "target_type": "Task",
            "review_stage": "v3",
        },
        {
            "example_id": "claim:test_singleton",
            "paper_id": "paper:test_singleton",
            "canonical_claim_id": "canonical_claim:test_singleton",
            "gold_label": "retain_singleton",
            "target_type": "Region",
            "review_stage": "v3",
        },
        {
            "example_id": "claim:test_exclude",
            "paper_id": "paper:test_exclude",
            "canonical_claim_id": "canonical_claim:test_exclude",
            "gold_label": "exclude_from_snapshot",
            "target_type": "Concept",
            "review_stage": "v2",
        },
        {
            "example_id": "claim:test_warn_a",
            "paper_id": "paper:test_warn_a",
            "canonical_claim_id": "canonical_claim:test_warn_a",
            "gold_label": "retain_singleton_with_warning",
            "target_type": "Task",
            "review_stage": "v4",
        },
        {
            "example_id": "claim:test_warn_b",
            "paper_id": "paper:test_warn_b",
            "canonical_claim_id": "canonical_claim:test_warn_b",
            "gold_label": "retain_singleton_with_warning",
            "target_type": "Concept",
            "review_stage": "v4",
        },
        {
            "example_id": "claim:test_conflict_a",
            "paper_id": "paper:test_conflict_a",
            "canonical_claim_id": "canonical_claim:test_conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v5_conflict",
        },
        {
            "example_id": "claim:test_conflict_b",
            "paper_id": "paper:test_conflict_b",
            "canonical_claim_id": "canonical_claim:test_conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v5_conflict",
        },
        {
            "example_id": "claim:train_singleton",
            "paper_id": "paper:train_singleton",
            "canonical_claim_id": "canonical_claim:train_singleton",
            "gold_label": "retain_singleton",
            "target_type": "Concept",
            "review_stage": "v2",
        },
    ]
    _write_jsonl(examples_jsonl, rows)
    task_manifest.write_text(
        json.dumps(
            {
                "task_manifest_id": module.TASK_MANIFEST_ID,
                "artifacts": {"examples_jsonl": str(examples_jsonl)},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "DEV_EXAMPLE_IDS",
        [
            "claim:dev_conflict_a",
            "claim:dev_conflict_b",
            "claim:dev_singleton",
            "claim:dev_exclude",
            "claim:dev_warn_a",
            "claim:dev_warn_b",
        ],
    )
    monkeypatch.setattr(
        module,
        "TEST_EXAMPLE_IDS",
        [
            "claim:test_singleton",
            "claim:test_exclude",
            "claim:test_warn_a",
            "claim:test_warn_b",
            "claim:test_conflict_a",
            "claim:test_conflict_b",
        ],
    )

    exit_code = module.main(
        [
            "--task-manifest-json",
            str(task_manifest),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    summary = json.loads(
        (output_dir / "claim_snapshot_v4_b2_split_summary.json").read_text(encoding="utf-8")
    )
    assert summary["checks"]["paper_leakage_violations"] == 0
    assert summary["checks"]["canonical_leakage_violations"] == 0
    assert summary["checks"]["dev_has_conflict"] is True
    assert summary["checks"]["test_has_conflict"] is True
    assert summary["checks"]["test_has_exclude"] is True


def test_build_claim_snapshot_v4_b2_split_manifest_fails_on_canonical_leakage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task_manifest = tmp_path / "task_manifest.json"
    examples_jsonl = tmp_path / "examples.jsonl"
    _write_jsonl(
        examples_jsonl,
        [
            {
                "example_id": "claim:a",
                "paper_id": "paper:a",
                "canonical_claim_id": "canonical_claim:shared",
                "gold_label": "retain_singleton_with_warning",
                "target_type": "Concept",
                "review_stage": "v1",
            },
            {
                "example_id": "claim:b",
                "paper_id": "paper:b",
                "canonical_claim_id": "canonical_claim:shared",
                "gold_label": "retain_singleton_with_warning",
                "target_type": "Concept",
                "review_stage": "v1",
            },
            {
                "example_id": "claim:c",
                "paper_id": "paper:c",
                "canonical_claim_id": "canonical_claim:c",
                "gold_label": "retain_singleton",
                "target_type": "Concept",
                "review_stage": "v1",
            },
            {
                "example_id": "claim:d",
                "paper_id": "paper:d",
                "canonical_claim_id": "canonical_claim:d",
                "gold_label": "exclude_from_snapshot",
                "target_type": "Task",
                "review_stage": "v1",
            },
            {
                "example_id": "claim:e",
                "paper_id": "paper:e",
                "canonical_claim_id": "canonical_claim:e",
                "gold_label": "retain_singleton_with_warning",
                "target_type": "Region",
                "review_stage": "v1",
            },
        ],
    )
    task_manifest.write_text(
        json.dumps(
            {
                "task_manifest_id": module.TASK_MANIFEST_ID,
                "artifacts": {"examples_jsonl": str(examples_jsonl)},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "DEV_EXAMPLE_IDS", ["claim:a", "claim:c", "claim:d"])
    monkeypatch.setattr(module, "TEST_EXAMPLE_IDS", ["claim:b", "claim:e"])
    try:
        module.main(
            [
                "--task-manifest-json",
                str(task_manifest),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed B2 split manifest mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed B2 split manifest mismatch")


def test_build_claim_snapshot_v4_b2_split_manifest_auto_places_unassigned_conflict_in_test(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task_manifest = tmp_path / "task_manifest.json"
    examples_jsonl = tmp_path / "examples.jsonl"
    rows = [
        {
            "example_id": "claim:dev_conflict_a",
            "paper_id": "paper:dev_conflict_a",
            "canonical_claim_id": "canonical_claim:dev_conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:dev_conflict_b",
            "paper_id": "paper:dev_conflict_b",
            "canonical_claim_id": "canonical_claim:dev_conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:test_singleton",
            "paper_id": "paper:test_singleton",
            "canonical_claim_id": "canonical_claim:test_singleton",
            "gold_label": "retain_singleton",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:test_exclude",
            "paper_id": "paper:test_exclude",
            "canonical_claim_id": "canonical_claim:test_exclude",
            "gold_label": "exclude_from_snapshot",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:test_warn",
            "paper_id": "paper:test_warn",
            "canonical_claim_id": "canonical_claim:test_warn",
            "gold_label": "retain_singleton_with_warning",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:dev_singleton",
            "paper_id": "paper:dev_singleton",
            "canonical_claim_id": "canonical_claim:dev_singleton",
            "gold_label": "retain_singleton",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:dev_warn",
            "paper_id": "paper:dev_warn",
            "canonical_claim_id": "canonical_claim:dev_warn",
            "gold_label": "retain_singleton_with_warning",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:dev_exclude",
            "paper_id": "paper:dev_exclude",
            "canonical_claim_id": "canonical_claim:dev_exclude",
            "gold_label": "exclude_from_snapshot",
            "target_type": "Concept",
            "review_stage": "v1",
        },
        {
            "example_id": "claim:extra_conflict_a",
            "paper_id": "paper:extra_conflict_a",
            "canonical_claim_id": "canonical_claim:extra_conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v5_conflict",
        },
        {
            "example_id": "claim:extra_conflict_b",
            "paper_id": "paper:extra_conflict_b",
            "canonical_claim_id": "canonical_claim:extra_conflict",
            "gold_label": "retain_conflict_cluster_with_warning",
            "target_type": "Concept",
            "review_stage": "v5_conflict",
        },
    ]
    _write_jsonl(examples_jsonl, rows)
    task_manifest.write_text(
        json.dumps(
            {
                "task_manifest_id": module.TASK_MANIFEST_ID,
                "artifacts": {"examples_jsonl": str(examples_jsonl)},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "DEV_EXAMPLE_IDS",
        ["claim:dev_conflict_a", "claim:dev_conflict_b", "claim:dev_singleton", "claim:dev_warn", "claim:dev_exclude"],
    )
    monkeypatch.setattr(
        module,
        "TEST_EXAMPLE_IDS",
        ["claim:test_singleton", "claim:test_exclude", "claim:test_warn"],
    )

    exit_code = module.main(
        [
            "--task-manifest-json",
            str(task_manifest),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 0
    manifest = json.loads(
        (tmp_path / "out" / "claim_snapshot_v4_b2_split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert "claim:extra_conflict_a" in manifest["partition_example_ids"]["test"]
    assert "claim:extra_conflict_b" in manifest["partition_example_ids"]["test"]
    summary = json.loads(
        (tmp_path / "out" / "claim_snapshot_v4_b2_split_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["checks"]["test_has_conflict"] is True
