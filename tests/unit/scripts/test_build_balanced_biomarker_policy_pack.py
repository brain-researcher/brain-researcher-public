from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_biomarker_policy_pack import (
    classify_biomarker_row,
    main,
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_classify_biomarker_row() -> None:
    assert classify_biomarker_row(
        {"target_label": "dopamine D2 receptor availability"}
    ) == (
        "measurable_biomarker_regeneration",
        "regenerate_non_title_concept",
        "measurable_biomarker_or_receptor_surface_form",
    )
    assert classify_biomarker_row({"target_label": "Amyloid"}) == (
        "broad_biomarker_hold",
        "manual_scope_review_or_candidate_only_policy",
        "broad_biomarker_scope_hold",
    )


def test_build_balanced_biomarker_policy_pack(tmp_path: Path) -> None:
    input_path = tmp_path / "biomarker.jsonl"
    rows = [
        {
            "paper_id": "paper:1",
            "paper_title": "Amyloid paper",
            "claim_id": "claim:1",
            "run_id": "run:1",
            "lane": "biomarker_receptor",
            "lane_reason": "biomarker_or_receptor_surface_form",
            "recommended_next_action": "manual_biomarker_scope_review",
            "target_type": "Concept",
            "target_id": "concept:amyloid",
            "target_label": "Amyloid",
            "evidence_section": "title",
            "mapping_confidence": 0.25,
            "claim_strength": 0.35,
            "method_rigor": 0.0,
            "source_review_bucket": "scope_review_clinical_or_biomarker",
            "source_bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "paper:2",
            "paper_title": "D2 paper",
            "claim_id": "claim:2",
            "run_id": "run:2",
            "lane": "biomarker_receptor",
            "lane_reason": "biomarker_or_receptor_surface_form",
            "recommended_next_action": "manual_biomarker_scope_review",
            "target_type": "Concept",
            "target_id": "concept:dopamine_d2_receptor_availability",
            "target_label": "dopamine D2 receptor availability",
            "evidence_section": "title",
            "mapping_confidence": 0.74,
            "claim_strength": 0.81,
            "method_rigor": 0.15,
            "source_review_bucket": "scope_review_clinical_or_biomarker",
            "source_bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "paper:3",
            "paper_title": "Wrong lane paper",
            "claim_id": "claim:3",
            "run_id": "run:3",
            "lane": "behavioral_phenotype",
            "lane_reason": "behavioral_or_clinical_phenotype_surface_form",
            "recommended_next_action": "manual_behavioral_scope_review",
            "target_type": "Concept",
            "target_id": "concept:wrong_lane",
            "target_label": "wrong lane receptor",
        },
        {
            "paper_id": "paper:4",
            "paper_title": "Non concept paper",
            "claim_id": "claim:4",
            "run_id": "run:4",
            "lane": "biomarker_receptor",
            "lane_reason": "biomarker_or_receptor_surface_form",
            "recommended_next_action": "manual_biomarker_scope_review",
            "target_type": "Region",
            "target_id": "region:striatum",
            "target_label": "Striatum",
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    assert (
        main(["--biomarker-rows", str(input_path), "--output-dir", str(output_dir)])
        == 0
    )

    summary = json.loads(
        (output_dir / "biomarker_policy_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 2
    assert summary["counts"]["broad_biomarker_hold"] == 1
    assert summary["counts"]["measurable_biomarker_regeneration"] == 1
    assert summary["counts"]["action_regenerate_non_title_concept"] == 1
    assert summary["counts"]["action_manual_scope_review_or_candidate_only_policy"] == 1
    assert summary["counts"]["skipped_non_biomarker_lane"] == 1
    assert summary["counts"]["skipped_non_concept_target"] == 1

    policy_rows = _read_jsonl(output_dir / "biomarker_policy_pack.jsonl")
    assert [row["policy_bucket"] for row in policy_rows] == [
        "broad_biomarker_hold",
        "measurable_biomarker_regeneration",
    ]
    assert all(
        row["policy_stage"] == "balanced_biomarker_policy" for row in policy_rows
    )
    assert all(
        row["source_artifact_path"] == str(input_path.resolve()) for row in policy_rows
    )

    hold_rows = _read_jsonl(output_dir / "broad_biomarker_hold.jsonl")
    assert len(hold_rows) == 1
    assert hold_rows[0]["bucket_reason"] == "broad_biomarker_scope_hold"
    assert (
        hold_rows[0]["recommended_next_action"]
        == "manual_scope_review_or_candidate_only_policy"
    )
    assert hold_rows[0]["scope_review_bucket"] == "biomarker_receptor"
    assert hold_rows[0]["scope_review_bucket_reason"] == (
        "biomarker_or_receptor_surface_form"
    )

    regen_rows = _read_jsonl(output_dir / "measurable_biomarker_regeneration.jsonl")
    assert len(regen_rows) == 1
    assert regen_rows[0]["regeneration_bucket"] == "measurable_biomarker_regeneration"
    assert regen_rows[0]["bucket_reason"] == (
        "measurable_biomarker_or_receptor_surface_form"
    )
    assert regen_rows[0]["source_evidence_section"] == "title"
    assert regen_rows[0]["mapping_confidence"] == 0.74
    assert regen_rows[0]["scope_review_recommended_next_action"] == (
        "manual_biomarker_scope_review"
    )
    assert regen_rows[0]["source_review_bucket"] == "measurable_biomarker_regeneration"
    assert (
        regen_rows[0]["upstream_review_bucket"]
        == "scope_review_clinical_or_biomarker"
    )
