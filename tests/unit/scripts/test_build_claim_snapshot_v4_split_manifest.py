from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v4_split_manifest as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v4_split_manifest_materializes_family_partitions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot_jsonl = tmp_path / "claim_snapshot_v4.jsonl"
    snapshot_summary = tmp_path / "claim_snapshot_v4_summary.json"
    output_dir = tmp_path / "out"

    monkeypatch.setattr(module, "DEV_FAMILY_IDS", ["canonical_claim:dev_conflict", "canonical_claim:dev_clean"])
    monkeypatch.setattr(module, "TEST_FAMILY_IDS", ["canonical_claim:test_warning", "canonical_claim:test_clean"])

    _write_jsonl(
        snapshot_jsonl,
        [
            {
                "source_claim_id": "claim:train_1",
                "canonical_claim_id": "canonical_claim:train_1",
                "paper_id": "paper:train_1",
                "target_type": "Region",
                "target_id": "region:train_1",
                "polarity": "supports",
                "snapshot_role": "singleton_warning",
                "failure_tags": ["granularity_mismatch"],
            },
            {
                "source_claim_id": "claim:train_2",
                "canonical_claim_id": "canonical_claim:train_2",
                "paper_id": "paper:train_2",
                "target_type": "Task",
                "target_id": "task:train_2",
                "polarity": "supports",
                "snapshot_role": "singleton_warning",
                "failure_tags": [],
            },
            {
                "source_claim_id": "claim:dev_conflict_a",
                "canonical_claim_id": "canonical_claim:dev_conflict",
                "paper_id": "paper:dev_conflict",
                "target_type": "Concept",
                "target_id": "concept:dev_conflict",
                "polarity": "supports",
                "snapshot_role": "conflict_cluster_warning",
                "failure_tags": [],
            },
            {
                "source_claim_id": "claim:dev_conflict_b",
                "canonical_claim_id": "canonical_claim:dev_conflict",
                "paper_id": "paper:dev_conflict",
                "target_type": "Concept",
                "target_id": "concept:dev_conflict",
                "polarity": "refutes",
                "snapshot_role": "conflict_cluster_warning",
                "failure_tags": [],
            },
            {
                "source_claim_id": "claim:dev_clean",
                "canonical_claim_id": "canonical_claim:dev_clean",
                "paper_id": "paper:dev_clean",
                "target_type": "Concept",
                "target_id": "concept:dev_clean",
                "polarity": "supports",
                "snapshot_role": "control",
                "failure_tags": [],
            },
            {
                "source_claim_id": "claim:test_warning",
                "canonical_claim_id": "canonical_claim:test_warning",
                "paper_id": "paper:test_warning",
                "target_type": "Task",
                "target_id": "task:test_warning",
                "polarity": "supports",
                "snapshot_role": "singleton_warning",
                "failure_tags": ["modality_or_method_leakage"],
            },
            {
                "source_claim_id": "claim:test_clean",
                "canonical_claim_id": "canonical_claim:test_clean",
                "paper_id": "paper:test_clean",
                "target_type": "Region",
                "target_id": "region:test_clean",
                "polarity": "supports",
                "snapshot_role": "singleton_breadth_clean",
                "failure_tags": [],
            },
        ],
    )
    snapshot_summary.write_text(json.dumps({"counts": {"snapshot_v4_rows_total": 7}}), encoding="utf-8")

    exit_code = module.main(
        [
            "--snapshot-jsonl",
            str(snapshot_jsonl),
            "--snapshot-summary-json",
            str(snapshot_summary),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    manifest = json.loads(
        (output_dir / "claim_snapshot_v4_split_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["split_unit"] == "canonical_claim_id"
    assert manifest["partition_family_ids"]["dev"] == sorted(module.DEV_FAMILY_IDS)
    assert manifest["partition_family_ids"]["test"] == sorted(module.TEST_FAMILY_IDS)
    assert manifest["partition_family_ids"]["train"] == ["canonical_claim:train_1", "canonical_claim:train_2"]

    summary = json.loads(
        (output_dir / "claim_snapshot_v4_split_summary.json").read_text(encoding="utf-8")
    )
    assert summary["partitions"]["dev"]["warning_or_conflict_families_total"] == 1
    assert summary["partitions"]["dev"]["clean_control_families_total"] == 1
    assert summary["checks"]["dev_has_warning_or_conflict_family"] is True
    assert summary["checks"]["test_has_clean_control_family"] is True

    dev_rows = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v4_dev.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["partition"] for row in dev_rows} == {"dev"}
    assert {row["family_partition"] for row in dev_rows} == {"dev"}


def test_build_claim_snapshot_v4_split_manifest_fails_on_missing_family(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot_jsonl = tmp_path / "claim_snapshot_v4.jsonl"
    snapshot_summary = tmp_path / "claim_snapshot_v4_summary.json"
    output_dir = tmp_path / "out"

    monkeypatch.setattr(module, "DEV_FAMILY_IDS", ["canonical_claim:missing"])
    monkeypatch.setattr(module, "TEST_FAMILY_IDS", [])

    _write_jsonl(snapshot_jsonl, [])
    snapshot_summary.write_text(json.dumps({"counts": {}}), encoding="utf-8")

    try:
        module.main(
            [
                "--snapshot-jsonl",
                str(snapshot_jsonl),
                "--snapshot-summary-json",
                str(snapshot_summary),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed split manifest mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed split manifest mismatch")
