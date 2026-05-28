from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_terminal_shortfall_pack as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_terminal_shortfall_pack_selects_primary_and_reserve(
    tmp_path: Path,
) -> None:
    snapshot_v3 = tmp_path / "claim_snapshot_v3.jsonl"
    candidate_a = tmp_path / "candidate_a.jsonl"
    candidate_b = tmp_path / "candidate_b.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        snapshot_v3,
        [
            {
                "source_claim_id": "claim:base",
                "canonical_claim_id": "canonical_claim:base",
            }
        ],
    )
    _write_jsonl(
        candidate_a,
        [
            {
                "source_claim_id": "claim:36440b921722e3394eef114ce3e1be3c",
                "canonical_claim_id": "canonical_claim:action",
                "target_type": "Concept",
                "target_id": "concept:action_understanding",
                "decision_reason": "old",
                "adjudication_bucket": "exclude_old",
            },
            {
                "source_claim_id": "claim:112ab135f7e98e7fef3af9ab0037a729",
                "canonical_claim_id": "canonical_claim:olfactory",
                "target_type": "Region",
                "target_id": "region:prefrontal_and_limbic_brain_regions",
                "decision_reason": "old",
                "adjudication_bucket": "exclude_old",
            },
        ],
    )
    _write_jsonl(
        candidate_b,
        [
            {
                "source_claim_id": "claim:c1e6f254a408747bef0ff3d56614e4de",
                "canonical_claim_id": "canonical_claim:circuits",
                "target_type": "Region",
                "target_id": "region:neural_circuits",
                "decision_reason": "old",
                "adjudication_bucket": "exclude_old",
            },
            {
                "source_claim_id": "claim:e0b5a42636c2bf10b5ad1df1fda7fd1d",
                "canonical_claim_id": "canonical_claim:gait",
                "target_type": "Concept",
                "target_id": "concept:gait_speed",
                "decision_reason": "old",
                "adjudication_bucket": "exclude_old",
            },
        ],
    )

    exit_code = module.main(
        [
            "--snapshot-v3",
            str(snapshot_v3),
            "--candidate-jsonl",
            str(candidate_a),
            "--candidate-jsonl",
            str(candidate_b),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "terminal_shortfall_pack_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["snapshot_v3_families_total"] == 1
    assert summary["counts"]["primary_rows_total"] == 3
    assert summary["counts"]["primary_new_families_total"] == 3
    assert summary["counts"]["reserve_rows_total"] == 1
    assert summary["counts"]["projected_families_total"] == 4
    assert summary["counts"]["remaining_shortfall_after_primary"] == 20

    rows = [
        json.loads(line)
        for line in (output_dir / "terminal_shortfall_pack.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["source_claim_id"] for row in rows] == module.PRIMARY_CLAIM_IDS


def test_build_claim_snapshot_terminal_shortfall_pack_fails_on_missing_primary(
    tmp_path: Path,
) -> None:
    snapshot_v3 = tmp_path / "claim_snapshot_v3.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(snapshot_v3, [])
    _write_jsonl(
        candidate,
        [
            {
                "source_claim_id": "claim:36440b921722e3394eef114ce3e1be3c",
                "canonical_claim_id": "canonical_claim:action",
            }
        ],
    )

    try:
        module.main(
            [
                "--snapshot-v3",
                str(snapshot_v3),
                "--candidate-jsonl",
                str(candidate),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed terminal shortfall mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed terminal shortfall mismatch")
