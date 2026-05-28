from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v2 as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v2_combines_prior_snapshot_with_retained_expansion_rows(
    tmp_path: Path,
) -> None:
    snapshot_v1 = tmp_path / "claim_snapshot_v1.jsonl"
    expansion_pack = tmp_path / "claim_snapshot_v1_expansion_pack.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        snapshot_v1,
        [
            {
                "source_claim_id": "claim:wm_dlpfc",
                "paper_id": "pmid:1",
                "target_id": "concept:working_memory",
                "target_type": "Concept",
                "claim_text": "Working memory load robustly recruits dlPFC.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "high_precision",
                "benchmark_eligibility": "benchmark_eligible_high_precision",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:wm",
                "cluster_confidence": 0.95,
                "failure_tags": [],
                "snapshot_role": "control",
                "adjudication_status": "reviewed_singleton_control",
                "decision_reason": "Keep control.",
            }
        ],
    )
    _write_jsonl(
        expansion_pack,
        [
            {
                "source_claim_id": "claim:8001f8113f2ab080a140bf1d0b8db42f",
                "paper_id": "paper:palatable",
                "target_id": "concept:palatable_food_consumption",
                "target_type": "Concept",
                "claim_text": "mCPP decreased intake of a palatable snack.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "balanced_marginal_regenerated",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:palatable",
                "cluster_confidence": 0.85,
                "failure_tags": [],
                "warnings": [],
                "notes": "behavioral",
            },
            {
                "source_claim_id": "claim:ae95759619d6ef7c80f772c4f85f2265",
                "paper_id": "paper:exploration",
                "target_id": "concept:exploration_and_exploitation",
                "target_type": "Concept",
                "claim_text": "Balancing exploration and exploitation is a fundamental problem in reinforcement learning.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "balanced_marginal_regenerated",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:exploration",
                "cluster_confidence": 0.85,
                "failure_tags": [],
                "warnings": [],
                "notes": "background",
            },
            {
                "source_claim_id": "claim:f5fab8f10f831984cf211ae410af8738",
                "paper_id": "paper:region",
                "target_id": "region:caudate_and_anterior_cingulate_cortex",
                "target_type": "Region",
                "claim_text": "Nicotine induced activation in the right caudate and anterior cingulate cortex (dACC/rACC) in response to errors.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "balanced_marginal_regenerated",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:caudate_acc",
                "cluster_confidence": 0.85,
                "failure_tags": [],
                "warnings": [],
                "notes": "region",
            },
        ],
    )

    exit_code = module.main(
        [
            "--snapshot-v1",
            str(snapshot_v1),
            "--expansion-pack",
            str(expansion_pack),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads((output_dir / "claim_snapshot_v2_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["expansion_rows_reviewed_total"] == 3
    assert summary["counts"]["expansion_rows_retained_total"] == 2
    assert summary["counts"]["expansion_rows_excluded_total"] == 1
    assert summary["counts"]["snapshot_v2_rows_total"] == 3
    assert summary["counts"]["snapshot_v2_canonical_families_total"] == 3
    assert summary["counts"]["snapshot_v2_warning_or_conflict_families_total"] == 1
    assert summary["counts"]["snapshot_role_singleton_expansion_clean"] == 1
    assert summary["counts"]["snapshot_role_singleton_expansion_warning"] == 1

    rows = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v2.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["source_claim_id"] for row in rows} == {
        "claim:wm_dlpfc",
        "claim:8001f8113f2ab080a140bf1d0b8db42f",
        "claim:f5fab8f10f831984cf211ae410af8738",
    }
    region_row = next(row for row in rows if row["source_claim_id"] == "claim:f5fab8f10f831984cf211ae410af8738")
    assert "granularity_mismatch" in region_row["failure_tags"]


def test_build_claim_snapshot_v2_fails_closed_on_missing_decision(tmp_path: Path) -> None:
    snapshot_v1 = tmp_path / "claim_snapshot_v1.jsonl"
    expansion_pack = tmp_path / "claim_snapshot_v1_expansion_pack.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(snapshot_v1, [])
    _write_jsonl(
        expansion_pack,
        [
            {
                "source_claim_id": "claim:unknown",
                "paper_id": "paper:x",
                "target_id": "concept:x",
                "target_type": "Concept",
                "claim_text": "Unknown row.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "balanced_marginal_regenerated",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:x",
                "cluster_confidence": 0.8,
                "failure_tags": [],
                "warnings": [],
                "notes": "",
            }
        ],
    )

    try:
        module.main(
            [
                "--snapshot-v1",
                str(snapshot_v1),
                "--expansion-pack",
                str(expansion_pack),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed expansion adjudication mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed expansion adjudication mismatch")
