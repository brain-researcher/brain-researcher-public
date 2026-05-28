from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v3 as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v3_combines_snapshot_bridge_and_breadth_rows(
    tmp_path: Path,
) -> None:
    snapshot_v2 = tmp_path / "claim_snapshot_v2.jsonl"
    warning_gap = tmp_path / "warning_conflict_gap_pack.jsonl"
    breadth_pack = tmp_path / "claim_snapshot_substantive_breadth_pack.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        snapshot_v2,
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
                "cluster_review_status": "reviewed_singleton_control",
                "decision_reason": "Keep control.",
            }
        ],
    )
    _write_jsonl(
        warning_gap,
        [
            {
                "source_claim_id": "claim:028fee000c3903b1e325ecc2bbaf4286",
                "paper_id": "pmid:2",
                "target_id": "concept:default_mode_network",
                "target_type": "Concept",
                "claim_text": "Default mode network connectivity remains unchanged across lifespan and Alzheimer's disease cohorts.",
                "claim_kind": "claim",
                "polarity": "refutes",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:dmn",
                "cluster_confidence": 0.2,
                "failure_tags": ["granularity_mismatch"],
            },
            {
                "source_claim_id": "claim:bcbf3a40052599b6c72c9a7c38585e6f",
                "paper_id": "pmid:3",
                "target_id": "region:insula",
                "target_type": "Region",
                "claim_text": "Distributed fMRI patterns coupled to low-frequency cardiorespiratory dynamics provide markers of aging",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:insula",
                "cluster_confidence": 0.2,
                "failure_tags": ["semantic_composite_or_analysis_claim"],
            },
            {
                "source_claim_id": "claim:7b858b2e0cfe374856830def8df4a681",
                "paper_id": "pmid:3b",
                "target_id": "region:locus_coeruleus",
                "target_type": "Region",
                "claim_text": "Locus Coeruleus Activity Mediates Hyperresponsiveness in Posttraumatic Stress Disorder.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:locus",
                "cluster_confidence": 0.2,
                "failure_tags": ["population_or_disease_scope_mismatch"],
            },
            {
                "source_claim_id": "claim:28fcbcec2470e0c24db5a5fc716143cc",
                "paper_id": "pmid:3c",
                "target_id": "region:temporoparietal_junction",
                "target_type": "Region",
                "claim_text": "The role of the temporoparietal junction (TPJ) in action observation is agent detection rather than visuospatial transformation.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:tpj",
                "cluster_confidence": 0.2,
                "failure_tags": [],
            },
            {
                "source_claim_id": "claim:88f2eb8941c9228d0071651be108fa58",
                "paper_id": "pmid:4",
                "target_id": "task:response_inhibition",
                "target_type": "Task",
                "claim_text": "Levodopa improves response inhibition",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": "canonical_claim:response_inhibition",
                "cluster_confidence": 0.2,
                "failure_tags": [],
            },
        ],
    )
    _write_jsonl(
        breadth_pack,
        [
            {
                "source_claim_id": "claim:8ef30c3b4f50476f74b87e40414971c4",
                "paper_id": "paper:caudate",
                "target_id": "region:caudate_and_anterior_cingulate_cortex",
                "target_type": "Region",
                "claim_text": "Participants with schizophrenia had significantly decreased connectivity between the right caudate and dACC compared to controls.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:caudate_acc",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 0.8,
            },
            {
                "source_claim_id": "claim:7b323180f7b5cd382b405b8fb556a415",
                "paper_id": "paper:network",
                "target_id": "region:intrinsic_functional_brain_network",
                "target_type": "Region",
                "claim_text": "functional segregation of the large-scale intrinsic functional network could be associated with the neural mechanism of methylphenidate treatment.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:network",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 1.0,
            },
            {
                "source_claim_id": "claim:c1e6f254a408747bef0ff3d56614e4de",
                "paper_id": "paper:circuits",
                "target_id": "region:neural_circuits",
                "target_type": "Region",
                "claim_text": "specific neural circuits support positive maternal caregiving in the context of maternal anxiety",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:circuits",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 1.0,
            },
            {
                "source_claim_id": "claim:717aa816a1b759ed0631a31733f83ef0",
                "paper_id": "paper:posterior_frontal",
                "target_id": "region:posterior_lateral_frontal_cortex",
                "target_type": "Region",
                "claim_text": "The posterior motor/premotor region of the lateral frontal cortex is functionally organized along a rostro-caudal axis.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:posterior_frontal",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 0.9,
            },
            {
                "source_claim_id": "claim:0a454b9f9b9ff3e630176ceb3fde874b",
                "paper_id": "paper:attention",
                "target_id": "region:ventral_attention_system",
                "target_type": "Region",
                "claim_text": "Significant differences in neural activation patterns were identified within brain regions supporting the ventral attention system.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:attention",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 1.0,
            },
            {
                "source_claim_id": "claim:9f78b034872ba2ab733d1b43a687804c",
                "paper_id": "paper:gambling",
                "target_id": "task:gambling_availability_during_sports_picture_exposure",
                "target_type": "Task",
                "claim_text": "The study examined the neural responses to stimuli that represent sporting events available for betting as compared to sporting events without a gambling opportunity.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:gambling",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 1.0,
            },
            {
                "source_claim_id": "claim:5432581b4cf7885b281b5b3e9a26baba",
                "paper_id": "paper:motor_imagery",
                "target_id": "task:motor_imagery",
                "target_type": "Task",
                "claim_text": "Increased blood oxygenation level-dependent signals were observed bilaterally in the premotor areas and supplementary motor area during performance of motor imagery tasks.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:motor_imagery",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 1.0,
            },
            {
                "source_claim_id": "claim:6fa3074f7a6af9cfa41c1db2495d2026",
                "paper_id": "paper:risky",
                "target_id": "task:risky_decision_making",
                "target_type": "Task",
                "claim_text": "The study aimed to identify the neural substrates of risky decision making.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:risky",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 1.0,
            },
        ],
    )

    exit_code = module.main(
        [
            "--snapshot-v2",
            str(snapshot_v2),
            "--warning-conflict-gap-pack",
            str(warning_gap),
            "--substantive-breadth-pack",
            str(breadth_pack),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads((output_dir / "claim_snapshot_v3_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["bridge_rows_reviewed_total"] == 5
    assert summary["counts"]["bridge_rows_retained_total"] == 4
    assert summary["counts"]["bridge_rows_excluded_total"] == 1
    assert summary["counts"]["breadth_rows_reviewed_total"] == 8
    assert summary["counts"]["breadth_rows_retained_total"] == 6
    assert summary["counts"]["breadth_rows_excluded_total"] == 2
    assert summary["counts"]["snapshot_v3_rows_total"] == 11
    assert summary["counts"]["snapshot_v3_canonical_families_total"] == 11
    assert summary["counts"]["snapshot_v3_warning_or_conflict_families_total"] == 9
    assert summary["counts"]["snapshot_v3_target_type_buckets_total"] == 3

    rows = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v3.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["source_claim_id"] for row in rows} == {
        "claim:wm_dlpfc",
        "claim:028fee000c3903b1e325ecc2bbaf4286",
        "claim:7b858b2e0cfe374856830def8df4a681",
        "claim:28fcbcec2470e0c24db5a5fc716143cc",
        "claim:88f2eb8941c9228d0071651be108fa58",
        "claim:8ef30c3b4f50476f74b87e40414971c4",
        "claim:7b323180f7b5cd382b405b8fb556a415",
        "claim:717aa816a1b759ed0631a31733f83ef0",
        "claim:0a454b9f9b9ff3e630176ceb3fde874b",
        "claim:9f78b034872ba2ab733d1b43a687804c",
        "claim:5432581b4cf7885b281b5b3e9a26baba",
    }
    bridge_task = next(
        row for row in rows if row["source_claim_id"] == "claim:88f2eb8941c9228d0071651be108fa58"
    )
    assert "modality_or_method_leakage" in bridge_task["failure_tags"]
    breadth_region = next(
        row for row in rows if row["source_claim_id"] == "claim:717aa816a1b759ed0631a31733f83ef0"
    )
    assert breadth_region["snapshot_role"] == "singleton_breadth_clean"


def test_build_claim_snapshot_v3_fails_closed_on_missing_decision(tmp_path: Path) -> None:
    snapshot_v2 = tmp_path / "claim_snapshot_v2.jsonl"
    warning_gap = tmp_path / "warning_conflict_gap_pack.jsonl"
    breadth_pack = tmp_path / "claim_snapshot_substantive_breadth_pack.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(snapshot_v2, [])
    _write_jsonl(warning_gap, [])
    _write_jsonl(
        breadth_pack,
        [
            {
                "source_claim_id": "claim:unknown",
                "paper_id": "paper:x",
                "target_id": "concept:x",
                "target_type": "Concept",
                "claim_text": "Unknown row.",
                "claim_kind": "claim",
                "polarity": "supports",
                "canonical_claim_id": "canonical_claim:x",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "mapping_confidence": 0.8,
            }
        ],
    )

    try:
        module.main(
            [
                "--snapshot-v2",
                str(snapshot_v2),
                "--warning-conflict-gap-pack",
                str(warning_gap),
                "--substantive-breadth-pack",
                str(breadth_pack),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed v3 adjudication mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed v3 adjudication mismatch")
