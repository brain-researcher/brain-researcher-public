from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_clustering_eval_pack as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_clustering_eval_pack_dedupes_and_groups_claims(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.jsonl"
    heldout = tmp_path / "heldout.jsonl"
    adjudication = tmp_path / "adjudication.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        calibration,
        [
            {
                "hypothesis_id": "claim:wm",
                "text": "Working memory load recruits dlPFC.",
                "expected_verdict": "supported",
                "review_status": "accepted_high_precision",
                "source_records": [
                    {
                        "paper_id": "pmid:1",
                        "target_id": "concept:working_memory",
                        "target_type": "Concept",
                        "claim_id": "claim:wm",
                        "span_id": "evidence:wm",
                        "polarity": "supports",
                        "gate_profile": "high_precision",
                        "accepted_under_gate": True,
                        "review_status": "accepted_high_precision",
                        "path": "a.jsonl",
                        "line_number": 1,
                    }
                ],
            }
        ],
    )
    _write_jsonl(
        heldout,
        [
            {
                "hypothesis_id": "bootstrap:attention_mixed",
                "text": "Attention effects are uniformly positive across the bounded bootstrap sample.",
                "expected_verdict": "mixed",
                "review_status": "accepted_bootstrap_adjudicated_mixed",
                "source_records": [
                    {
                        "paper_id": "pmid:2",
                        "target_id": "concept:attention",
                        "target_type": "Concept",
                        "claim_id": "claim:attn_support",
                        "span_id": "evidence:attn_support",
                        "polarity": "supports",
                        "gate_profile": "kg_bootstrap",
                        "accepted_under_gate": True,
                        "review_status": "accepted_bootstrap",
                        "path": "b.jsonl",
                        "line_number": 2,
                    },
                    {
                        "paper_id": "pmid:3",
                        "target_id": "concept:attention",
                        "target_type": "Concept",
                        "claim_id": "claim:attn_refute",
                        "span_id": "evidence:attn_refute",
                        "polarity": "refutes",
                        "gate_profile": "kg_bootstrap",
                        "accepted_under_gate": True,
                        "review_status": "accepted_bootstrap",
                        "path": "c.jsonl",
                        "line_number": 3,
                    },
                ],
            }
        ],
    )
    _write_jsonl(
        adjudication,
        [
            {
                "hypothesis_id": "bootstrap:attention_mixed",
                "text": "Attention effects are uniformly positive across the bounded bootstrap sample.",
                "expected_verdict": "mixed",
                "review_status": "accepted_bootstrap_adjudicated_mixed",
                "notes": "Attention mixed adjudication example.",
                "warnings": [
                    "title_only_evidence_present",
                    "claim_evidence_semantic_mismatch_present",
                ],
                "adjudication": {"status": "pending"},
                "source_records": [
                    {
                        "paper_id": "pmid:2",
                        "target_id": "concept:attention",
                        "target_type": "Concept",
                        "claim_id": "claim:attn_support",
                        "span_id": "evidence:attn_support",
                        "polarity": "supports",
                        "gate_profile": "kg_bootstrap",
                        "accepted_under_gate": True,
                        "review_status": "accepted_bootstrap",
                        "path": "b.jsonl",
                        "line_number": 2,
                    }
                ],
                "review_material": {
                    "evidence_anchors": [
                        {
                            "claim_id": "claim:attn_support",
                            "evidence_depth": "title_only",
                            "warnings": ["evidence_depth_title_only"],
                        }
                    ]
                },
            }
        ],
    )

    exit_code = module.main(
        [
            "--calibration-manifest",
            str(calibration),
            "--heldout-manifest",
            str(heldout),
            "--adjudication-pack",
            str(adjudication),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "claim_clustering_eval_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 3
    assert summary["counts"]["canonical_clusters_total"] == 2
    assert summary["counts"]["multi_member_clusters"] == 1
    assert summary["counts"]["clusters_with_failure_tags"] == 1
    assert summary["counts"]["clusters_with_opposing_polarity"] == 1
    assert summary["counts"]["clusters_spanning_multiple_source_packs"] == 1
    assert summary["counts"]["slice_same_target_opposing_stance"] == 2
    assert summary["counts"]["slice_stable_single_paper_control"] == 1
    assert summary["counts"]["action_merge_with_warning"] == 2
    assert summary["counts"]["action_singleton"] == 1
    assert summary["counts"]["eligibility_benchmark_eligible_high_precision"] == 1
    assert summary["counts"]["eligibility_bootstrap_only_pre_gate_b"] == 2
    assert summary["counts"]["failure_title_only_or_insufficient_text"] == 1
    assert summary["counts"]["failure_polarity_or_antonym_confusion"] == 2

    rows = [
        json.loads(line)
        for line in (output_dir / "claim_clustering_eval_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    row_by_claim = {row["source_claim_id"]: row for row in rows}

    assert row_by_claim["claim:wm"]["proposed_action"] == "singleton"
    assert row_by_claim["claim:wm"]["benchmark_eligibility"] == "benchmark_eligible_high_precision"
    assert row_by_claim["claim:wm"]["claim_text"] == "Working memory load recruits dlPFC."
    assert row_by_claim["claim:wm"]["claim_kind"] == "claim"
    assert row_by_claim["claim:wm"]["quality_profile"] == "high_precision"
    assert row_by_claim["claim:wm"]["review_status"] == "accepted_high_precision"
    assert row_by_claim["claim:wm"]["adjudication_status"] == "not_adjudicated"
    assert (
        row_by_claim["claim:wm"]["canonical_claim_id"]
        == row_by_claim["claim:wm"]["proposed_canonical_claim_id"]
    )

    assert row_by_claim["claim:attn_support"]["evaluation_slice"] == "same_target_opposing_stance"
    assert row_by_claim["claim:attn_refute"]["evaluation_slice"] == "same_target_opposing_stance"
    assert (
        row_by_claim["claim:attn_support"]["proposed_canonical_claim_id"]
        == row_by_claim["claim:attn_refute"]["proposed_canonical_claim_id"]
    )
    assert row_by_claim["claim:attn_support"]["proposed_action"] == "merge_with_warning"
    assert "title_only_or_insufficient_text" in row_by_claim["claim:attn_support"]["failure_tags"]
    assert "polarity_or_antonym_confusion" in row_by_claim["claim:attn_support"]["failure_tags"]
    assert row_by_claim["claim:attn_support"]["claim_kind"] == "claim"
    assert row_by_claim["claim:attn_support"]["adjudication_status"] == "pending"
    assert "Attention mixed adjudication example." in row_by_claim["claim:attn_support"]["notes"]


def test_build_claim_clustering_eval_pack_emits_target_mismatch_when_adjudicated_target_changes(
    tmp_path: Path,
) -> None:
    calibration = tmp_path / "calibration.jsonl"
    heldout = tmp_path / "heldout.jsonl"
    adjudication = tmp_path / "adjudication.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(calibration, [])
    _write_jsonl(heldout, [])
    _write_jsonl(
        adjudication,
        [
            {
                "hypothesis_id": "claim:swap",
                "text": "Amygdala activity increases reward sensitivity.",
                "expected_verdict": "supported",
                "review_status": "pending_adjudication",
                "adjudication": {"status": "pending"},
                "target_after_adjudication": {"target_id": "concept:reward_sensitivity"},
                "source_records": [
                    {
                        "paper_id": "pmid:9",
                        "target_id": "region:amygdala",
                        "target_type": "Region",
                        "claim_id": "claim:swap",
                        "span_id": "evidence:swap",
                        "polarity": "supports",
                        "gate_profile": "kg_bootstrap",
                        "accepted_under_gate": True,
                        "review_status": "accepted_bootstrap",
                        "path": "swap.jsonl",
                        "line_number": 9,
                    }
                ],
            }
        ],
    )

    exit_code = module.main(
        [
            "--calibration-manifest",
            str(calibration),
            "--heldout-manifest",
            str(heldout),
            "--adjudication-pack",
            str(adjudication),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    rows = [
        json.loads(line)
        for line in (output_dir / "claim_clustering_eval_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["target_after_adjudication"] == "concept:reward_sensitivity"
    assert "target_mismatch" in rows[0]["failure_tags"]
