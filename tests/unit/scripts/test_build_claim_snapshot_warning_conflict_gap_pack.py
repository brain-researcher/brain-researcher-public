from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_warning_conflict_gap_pack as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_warning_conflict_gap_pack_projects_from_snapshot_v2(
    tmp_path: Path,
) -> None:
    snapshot_v2 = tmp_path / "claim_snapshot_v2.jsonl"
    prior = tmp_path / "claim_clustering_adjudication_pack.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        snapshot_v2,
        [
            {
                "source_claim_id": "claim:wm_dlpfc",
                "target_id": "concept:working_memory",
                "target_type": "Concept",
                "canonical_claim_id": "canonical_claim:wm",
                "polarity": "supports",
                "snapshot_role": "control",
            },
            {
                "source_claim_id": "claim:region_warn",
                "target_id": "region:insula",
                "target_type": "Region",
                "canonical_claim_id": "canonical_claim:insula",
                "polarity": "supports",
                "snapshot_role": "singleton_expansion_warning",
            },
        ],
    )
    prior_rows = []
    for claim_id, target_type, target_id, canonical_id in [
        ("claim:028fee000c3903b1e325ecc2bbaf4286", "Concept", "concept:default_mode_network", "canonical_claim:dmn"),
        ("claim:bcbf3a40052599b6c72c9a7c38585e6f", "Region", "region:insula_other", "canonical_claim:insula_other"),
        ("claim:7b858b2e0cfe374856830def8df4a681", "Region", "region:locus_coeruleus", "canonical_claim:locus"),
        ("claim:28fcbcec2470e0c24db5a5fc716143cc", "Region", "region:temporoparietal_junction", "canonical_claim:tpj"),
        ("claim:88f2eb8941c9228d0071651be108fa58", "Task", "task:response_inhibition", "canonical_claim:ri"),
        ("claim:reserve", "Concept", "concept:reserve", "canonical_claim:reserve"),
    ]:
        prior_rows.append(
            {
                "source_claim_id": claim_id,
                "target_type": target_type,
                "target_id": target_id,
                "canonical_claim_id": canonical_id,
                "polarity": "supports",
                "snapshot_v1_included": False,
                "adjudication_bucket": "exclude",
                "decision_reason": "keep for later",
            }
        )
    _write_jsonl(prior, prior_rows)

    exit_code = module.main(
        [
            "--snapshot-v2",
            str(snapshot_v2),
            "--prior-adjudication-pack",
            str(prior),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "warning_conflict_gap_pack_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["snapshot_v2_families_total"] == 2
    assert summary["counts"]["snapshot_v2_warning_or_conflict_families_total"] == 1
    assert summary["counts"]["minimal_gap_pack_rows_total"] == 5
    assert summary["counts"]["reserve_gap_pack_rows_total"] == 1
    assert summary["counts"]["minimal_gap_pack_new_families_total"] == 5
    assert summary["counts"]["projected_families_total"] == 7
    assert summary["counts"]["projected_warning_or_conflict_families_total"] == 6
    assert summary["counts"]["projected_target_type_buckets_total"] == 3
    assert summary["counts"]["threshold_warning_or_conflict_families_met"] is True
    assert summary["counts"]["threshold_target_type_buckets_met"] is True

    minimal_rows = [
        json.loads(line)
        for line in (output_dir / "warning_conflict_gap_pack.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["source_claim_id"] for row in minimal_rows] == module.PRIORITY_CLAIM_IDS
    assert minimal_rows[-1]["would_add_target_type_bucket"] is True


def test_build_claim_snapshot_warning_conflict_gap_pack_fails_if_priority_row_missing(
    tmp_path: Path,
) -> None:
    snapshot_v2 = tmp_path / "claim_snapshot_v2.jsonl"
    prior = tmp_path / "claim_clustering_adjudication_pack.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(snapshot_v2, [])
    _write_jsonl(prior, [])

    try:
        module.main(
            [
                "--snapshot-v2",
                str(snapshot_v2),
                "--prior-adjudication-pack",
                str(prior),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed warning/conflict pack mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed warning/conflict pack mismatch")
