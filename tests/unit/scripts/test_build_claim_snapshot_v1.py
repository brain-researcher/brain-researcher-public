from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v1 as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v1_materializes_snapshot_and_exclusions(tmp_path: Path) -> None:
    eval_pack = tmp_path / "claim_clustering_eval_pack.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        eval_pack,
        [
            {
                "source_claim_id": "claim:wm_dlpfc",
                "paper_id": "pmid:40000001",
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
            },
            {
                "source_claim_id": "claim:08d8acd1a4f1cc397140594f824bab95",
                "paper_id": "paper:10_1016_j_bbr_2018_02_031",
                "target_id": "concept:attention",
                "target_type": "Concept",
                "claim_text": "Attention effects are uniformly positive across the bounded bootstrap sample.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:attention",
                "cluster_confidence": 0.55,
                "failure_tags": ["polarity_or_antonym_confusion"],
            },
            {
                "source_claim_id": "claim:592e21efcf95e2cb37890b1bd835ef03",
                "paper_id": "pmid:41446878",
                "target_id": "concept:attention",
                "target_type": "Concept",
                "claim_text": "Attention effects are uniformly positive across the bounded bootstrap sample.",
                "claim_kind": "claim",
                "polarity": "refutes",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:attention",
                "cluster_confidence": 0.55,
                "failure_tags": ["polarity_or_antonym_confusion"],
            },
            {
                "source_claim_id": "claim:88f2eb8941c9228d0071651be108fa58",
                "paper_id": "paper:10_1016_j_neurobiolaging_2018_02_003",
                "target_id": "task:response_inhibition",
                "target_type": "Task",
                "claim_text": "Levodopa improves response inhibition",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:ri",
                "cluster_confidence": 0.20,
                "failure_tags": ["title_only_or_insufficient_text"],
            },
        ],
    )

    exit_code = module.main(
        [
            "--eval-pack",
            str(eval_pack),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads((output_dir / "claim_snapshot_v1_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["adjudication_rows_total"] == 4
    assert summary["counts"]["snapshot_rows_total"] == 3
    assert summary["counts"]["snapshot_excluded_rows_total"] == 1
    assert summary["counts"]["snapshot_canonical_clusters_total"] == 2
    assert summary["counts"]["snapshot_multi_member_clusters"] == 1
    assert summary["counts"]["snapshot_conflict_clusters"] == 1
    assert summary["counts"]["snapshot_role_conflict_cluster_warning"] == 2
    assert summary["counts"]["snapshot_role_control"] == 1

    snapshot_rows = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v1.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["source_claim_id"] for row in snapshot_rows} == {
        "claim:wm_dlpfc",
        "claim:08d8acd1a4f1cc397140594f824bab95",
        "claim:592e21efcf95e2cb37890b1bd835ef03",
    }
    conflict_rows = [row for row in snapshot_rows if row["canonical_claim_id"] == "canonical_claim:attention"]
    assert len(conflict_rows) == 2
    assert {row["polarity"] for row in conflict_rows} == {"supports", "refutes"}


def test_build_claim_snapshot_v1_fails_closed_when_decisions_do_not_cover_eval_pack(
    tmp_path: Path,
) -> None:
    eval_pack = tmp_path / "claim_clustering_eval_pack.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(
        eval_pack,
        [
            {
                "source_claim_id": "claim:unknown",
                "paper_id": "pmid:0",
                "target_id": "concept:unknown",
                "target_type": "Concept",
                "claim_text": "Unknown row.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:unknown",
                "cluster_confidence": 0.2,
                "failure_tags": [],
            }
        ],
    )

    try:
        module.main(["--eval-pack", str(eval_pack), "--output-dir", str(output_dir)])
    except SystemExit as exc:
        assert "Fail-closed adjudication mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed adjudication mismatch")
