from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v4_b2_task_manifest as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v4_b2_task_manifest_dedupes_latest_review_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    v1 = tmp_path / "v1.jsonl"
    v2 = tmp_path / "v2.jsonl"
    v3 = tmp_path / "v3.jsonl"
    v4 = tmp_path / "v4.jsonl"
    v5 = tmp_path / "v5.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        v1,
        [
            {
                "source_claim_id": "claim:a",
                "adjudicated_action": "retain_singleton",
                "target_type": "Concept",
                "failure_tags": [],
            }
        ],
    )
    _write_jsonl(
        v2,
        [
            {
                "source_claim_id": "claim:a",
                "adjudicated_action": "exclude_from_snapshot",
                "target_type": "Concept",
                "failure_tags": ["semantic_composite_or_analysis_claim"],
            },
            {
                "source_claim_id": "claim:b",
                "adjudicated_action": "retain_singleton_with_warning",
                "target_type": "Region",
                "failure_tags": ["granularity_mismatch"],
            },
        ],
    )
    _write_jsonl(v3, [])
    _write_jsonl(
        v4,
        [
            {
                "source_claim_id": "claim:c",
                "adjudicated_action": "retain_conflict_cluster_with_warning",
                "target_type": "Task",
                "failure_tags": ["polarity_or_antonym_confusion"],
            }
        ],
    )
    _write_jsonl(
        v5,
        [
            {
                "source_claim_id": "claim:d",
                "adjudicated_action": "retain_conflict_cluster_with_warning",
                "target_type": "Concept",
                "failure_tags": ["polarity_or_antonym_confusion"],
            }
        ],
    )

    monkeypatch.setattr(
        module,
        "DEFAULT_INPUTS",
        [("v1", v1), ("v2", v2), ("v3", v3), ("v4", v4), ("v5_conflict", v5)],
    )

    exit_code = module.main(["--output-dir", str(output_dir)])
    assert exit_code == 0

    manifest = json.loads(
        (output_dir / "claim_snapshot_v4_b2_task_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["task_family"] == module.TASK_FAMILY
    assert manifest["label_space"] == module.LABEL_SPACE

    rows = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v4_b2_examples.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 4
    by_id = {row["source_claim_id"]: row for row in rows}
    assert by_id["claim:a"]["gold_label"] == "exclude_from_snapshot"
    assert by_id["claim:a"]["review_stage"] == "v2"
    assert by_id["claim:c"]["gold_label"] == "retain_conflict_cluster_with_warning"
    assert by_id["claim:d"]["review_stage"] == "v5_conflict"

    summary = json.loads(
        (output_dir / "claim_snapshot_v4_b2_task_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["duplicate_overwrites_total"] == 1
    assert summary["counts"]["label_exclude_from_snapshot"] == 1
    assert summary["counts"]["label_retain_singleton_with_warning"] == 1
    assert summary["counts"]["label_retain_conflict_cluster_with_warning"] == 2
    assert summary["counts"]["review_stage_v5_conflict"] == 1


def test_build_claim_snapshot_v4_b2_task_manifest_fails_on_unknown_label(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bad = tmp_path / "bad.jsonl"
    _write_jsonl(
        bad,
        [
            {
                "source_claim_id": "claim:a",
                "adjudicated_action": "mystery_label",
                "target_type": "Concept",
                "failure_tags": [],
            }
        ],
    )
    monkeypatch.setattr(module, "DEFAULT_INPUTS", [("v1", bad)])
    try:
        module.main(["--output-dir", str(tmp_path / "out")])
    except SystemExit as exc:
        assert "Fail-closed B2 task manifest mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed B2 task manifest mismatch")


def test_build_claim_snapshot_v4_b2_task_manifest_accepts_extra_review_pack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base = tmp_path / "base.jsonl"
    extra = tmp_path / "extra.jsonl"
    _write_jsonl(
        base,
        [
            {
                "source_claim_id": "claim:a",
                "adjudicated_action": "retain_singleton",
                "target_type": "Concept",
                "failure_tags": [],
            }
        ],
    )
    _write_jsonl(
        extra,
        [
            {
                "source_claim_id": "claim:b",
                "adjudicated_action": "retain_conflict_cluster_with_warning",
                "target_type": "Concept",
                "failure_tags": ["polarity_or_antonym_confusion"],
            }
        ],
    )
    monkeypatch.setattr(module, "DEFAULT_INPUTS", [("v1", base)])

    exit_code = module.main(
        [
            "--output-dir",
            str(tmp_path / "out"),
            "--extra-review-pack",
            f"hotload={extra}",
        ]
    )
    assert exit_code == 0
    summary = json.loads(
        (tmp_path / "out" / "claim_snapshot_v4_b2_task_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["deduped_examples_total"] == 2
    assert summary["counts"]["review_stage_hotload"] == 1
