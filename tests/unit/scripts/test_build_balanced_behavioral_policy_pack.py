from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_behavioral_policy_pack import (
    classify_behavioral_row,
    main,
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_classify_behavioral_row() -> None:
    assert classify_behavioral_row({"target_label": "gait speed"}) == (
        "measurable_behavioral_regeneration",
        "regenerate_non_title_concept",
        "measurable_behavioral_phenotype_surface_form",
    )
    assert classify_behavioral_row({"target_label": "Psychopathic traits"}) == (
        "broad_behavioral_trait_hold",
        "manual_scope_review_or_candidate_only_policy",
        "broad_behavioral_trait_scope_hold",
    )


def test_build_balanced_behavioral_policy_pack(tmp_path: Path) -> None:
    input_path = tmp_path / "behavioral.jsonl"
    rows = [
        {
            "paper_id": "paper:1",
            "paper_title": "Gait paper",
            "claim_id": "claim:1",
            "run_id": "run:1",
            "lane": "behavioral_phenotype",
            "lane_reason": "behavioral_or_clinical_phenotype_surface_form",
            "recommended_next_action": "manual_behavioral_scope_review",
            "target_type": "Concept",
            "target_id": "concept:gait_speed",
            "target_label": "gait speed",
            "evidence_section": "title",
            "mapping_confidence": 0.61,
            "claim_strength": 0.73,
            "method_rigor": 0.12,
            "source_review_bucket": "scope_review_clinical_or_biomarker",
            "source_bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "paper:2",
            "paper_title": "Trait paper",
            "claim_id": "claim:2",
            "run_id": "run:2",
            "lane": "behavioral_phenotype",
            "lane_reason": "behavioral_or_clinical_phenotype_surface_form",
            "recommended_next_action": "manual_behavioral_scope_review",
            "target_type": "Concept",
            "target_id": "concept:psychopathic_traits",
            "target_label": "Psychopathic traits",
            "evidence_section": "title",
            "mapping_confidence": 0.33,
            "claim_strength": 0.22,
            "method_rigor": 0.0,
            "source_review_bucket": "scope_review_clinical_or_biomarker",
            "source_bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "paper:3",
            "paper_title": "Wrong lane paper",
            "claim_id": "claim:3",
            "run_id": "run:3",
            "lane": "biomarker_receptor",
            "lane_reason": "biomarker_or_receptor_surface_form",
            "recommended_next_action": "manual_biomarker_scope_review",
            "target_type": "Concept",
            "target_id": "concept:behavioral_noise",
            "target_label": "behavioral noise",
        },
        {
            "paper_id": "paper:4",
            "paper_title": "Non concept paper",
            "claim_id": "claim:4",
            "run_id": "run:4",
            "lane": "behavioral_phenotype",
            "lane_reason": "behavioral_or_clinical_phenotype_surface_form",
            "recommended_next_action": "manual_behavioral_scope_review",
            "target_type": "Task",
            "target_id": "task:go_nogo",
            "target_label": "Go/NoGo",
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    assert (
        main(["--behavioral-rows", str(input_path), "--output-dir", str(output_dir)])
        == 0
    )

    summary = json.loads(
        (output_dir / "behavioral_policy_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 2
    assert summary["counts"]["measurable_behavioral_regeneration"] == 1
    assert summary["counts"]["broad_behavioral_trait_hold"] == 1
    assert summary["counts"]["action_regenerate_non_title_concept"] == 1
    assert summary["counts"]["action_manual_scope_review_or_candidate_only_policy"] == 1
    assert summary["counts"]["skipped_non_behavioral_lane"] == 1
    assert summary["counts"]["skipped_non_concept_target"] == 1

    policy_rows = _read_jsonl(output_dir / "behavioral_policy_pack.jsonl")
    assert [row["policy_bucket"] for row in policy_rows] == [
        "broad_behavioral_trait_hold",
        "measurable_behavioral_regeneration",
    ]
    assert all(
        row["policy_stage"] == "balanced_behavioral_policy" for row in policy_rows
    )
    assert all(
        row["source_artifact_path"] == str(input_path.resolve()) for row in policy_rows
    )

    hold_rows = _read_jsonl(output_dir / "broad_behavioral_trait_hold.jsonl")
    assert len(hold_rows) == 1
    assert hold_rows[0]["bucket_reason"] == "broad_behavioral_trait_scope_hold"
    assert (
        hold_rows[0]["recommended_next_action"]
        == "manual_scope_review_or_candidate_only_policy"
    )
    assert hold_rows[0]["scope_review_bucket"] == "behavioral_phenotype"
    assert (
        hold_rows[0]["scope_review_bucket_reason"]
        == "behavioral_or_clinical_phenotype_surface_form"
    )

    regen_rows = _read_jsonl(output_dir / "measurable_behavioral_regeneration.jsonl")
    assert len(regen_rows) == 1
    assert regen_rows[0]["regeneration_bucket"] == "measurable_behavioral_regeneration"
    assert (
        regen_rows[0]["bucket_reason"] == "measurable_behavioral_phenotype_surface_form"
    )
    assert regen_rows[0]["source_evidence_section"] == "title"
    assert regen_rows[0]["mapping_confidence"] == 0.61
    assert regen_rows[0]["scope_review_recommended_next_action"] == (
        "manual_behavioral_scope_review"
    )
    assert regen_rows[0]["source_review_bucket"] == "measurable_behavioral_regeneration"
    assert (
        regen_rows[0]["upstream_review_bucket"]
        == "scope_review_clinical_or_biomarker"
    )
