from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v4 as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v4_promotes_terminal_shortfall_primary_rows(
    tmp_path: Path,
) -> None:
    snapshot_v3 = tmp_path / "claim_snapshot_v3.jsonl"
    shortfall_pack = tmp_path / "terminal_shortfall_pack.jsonl"
    reserve_pack = tmp_path / "terminal_shortfall_pack_reserve.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        snapshot_v3,
        [
            {
                "source_claim_id": "claim:base",
                "canonical_claim_id": "canonical_claim:base",
                "target_type": "Concept",
                "polarity": "supports",
                "snapshot_role": "control",
            }
        ],
    )
    _write_jsonl(
        shortfall_pack,
        [
            {
                "source_claim_id": "claim:36440b921722e3394eef114ce3e1be3c",
                "canonical_claim_id": "canonical_claim:action",
                "target_type": "Concept",
                "target_id": "concept:action_understanding",
                "claim_text": "Action understanding can be difficult in ASD.",
                "polarity": "supports",
                "failure_tags": ["population_or_disease_scope_mismatch"],
            },
            {
                "source_claim_id": "claim:112ab135f7e98e7fef3af9ab0037a729",
                "canonical_claim_id": "canonical_claim:olfactory",
                "target_type": "Region",
                "target_id": "region:prefrontal_and_limbic_brain_regions",
                "claim_text": "Olfactory deprivation changes cortical volume in prefrontal and limbic regions.",
                "polarity": "supports",
                "failure_tags": ["granularity_mismatch"],
            },
            {
                "source_claim_id": "claim:c1e6f254a408747bef0ff3d56614e4de",
                "canonical_claim_id": "canonical_claim:circuits",
                "target_type": "Region",
                "target_id": "region:neural_circuits",
                "claim_text": "Specific neural circuits support positive maternal caregiving.",
                "polarity": "supports",
                "failure_tags": ["intervention_or_context_mismatch"],
            },
        ],
    )
    _write_jsonl(
        reserve_pack,
        [
            {
                "source_claim_id": "claim:e0b5a42636c2bf10b5ad1df1fda7fd1d",
                "canonical_claim_id": "canonical_claim:gait",
                "target_type": "Concept",
                "target_id": "concept:gait_speed",
                "claim_text": "Covariance patterns associated with gait speed were identified.",
                "polarity": "supports",
                "failure_tags": ["semantic_composite_or_analysis_claim"],
            }
        ],
    )

    exit_code = module.main(
        [
            "--snapshot-v3",
            str(snapshot_v3),
            "--terminal-shortfall-pack",
            str(shortfall_pack),
            "--terminal-shortfall-reserve",
            str(reserve_pack),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads((output_dir / "claim_snapshot_v4_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["terminal_rows_reviewed_total"] == 4
    assert summary["counts"]["terminal_rows_retained_total"] == 3
    assert summary["counts"]["terminal_rows_excluded_total"] == 1
    assert summary["counts"]["snapshot_v4_rows_total"] == 4
    assert summary["counts"]["snapshot_v4_canonical_families_total"] == 4
    assert summary["counts"]["threshold_canonical_families_met"] is False

    rows = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v4.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["source_claim_id"] for row in rows} == {
        "claim:base",
        "claim:36440b921722e3394eef114ce3e1be3c",
        "claim:112ab135f7e98e7fef3af9ab0037a729",
        "claim:c1e6f254a408747bef0ff3d56614e4de",
    }


def test_build_claim_snapshot_v4_fails_closed_on_missing_decision(tmp_path: Path) -> None:
    snapshot_v3 = tmp_path / "claim_snapshot_v3.jsonl"
    shortfall_pack = tmp_path / "terminal_shortfall_pack.jsonl"
    reserve_pack = tmp_path / "terminal_shortfall_pack_reserve.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(snapshot_v3, [])
    _write_jsonl(
        shortfall_pack,
        [
            {
                "source_claim_id": "claim:unknown",
                "canonical_claim_id": "canonical_claim:x",
            }
        ],
    )
    _write_jsonl(reserve_pack, [])

    try:
        module.main(
            [
                "--snapshot-v3",
                str(snapshot_v3),
                "--terminal-shortfall-pack",
                str(shortfall_pack),
                "--terminal-shortfall-reserve",
                str(reserve_pack),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed v4 adjudication mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed v4 adjudication mismatch")
