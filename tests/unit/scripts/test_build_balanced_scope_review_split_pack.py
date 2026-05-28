from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_scope_review_split_pack import (
    classify_scope_review_row,
    main,
)


def test_classify_scope_review_row_buckets() -> None:
    assert classify_scope_review_row({"target_label": "Conduct Disorder"})[0] == "disease_diagnosis"
    assert classify_scope_review_row({"target_label": "dopamine D2 receptor availability"})[0] == "biomarker_receptor"
    assert classify_scope_review_row({"target_label": "gait speed"})[0] == "behavioral_phenotype"


def test_build_balanced_scope_review_split_pack(tmp_path: Path) -> None:
    input_path = tmp_path / "scope.jsonl"
    rows = [
        {
            "paper_id": "paper:1",
            "paper_title": "Conduct Disorder paper",
            "claim_id": "claim:1",
            "run_id": "run:1",
            "target_type": "Concept",
            "target_id": "concept:conduct_disorder",
            "target_label": "Conduct Disorder",
            "adjudication_bucket": "scope_review_clinical_or_biomarker",
            "bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "evidence_section": "title",
            "source_stage": "balanced_concept_hold_adjudication",
        },
        {
            "paper_id": "paper:2",
            "paper_title": "Receptor paper",
            "claim_id": "claim:2",
            "run_id": "run:2",
            "target_type": "Concept",
            "target_id": "concept:dopamine_d2_receptor_availability",
            "target_label": "dopamine D2 receptor availability",
            "source_review_bucket": "scope_review_clinical_or_biomarker",
            "source_bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "evidence_section": "title",
            "ledger_bucket": "biomarker_unresolved_no_non_title_text",
            "resolution_bucket": "scope_review",
            "resolution_reason": "broad_biomarker_requires_scope_review",
            "source_stage": "balanced_no_non_title_resolution",
            "source_artifact_path": "/tmp/no_non_title.jsonl",
            "recommended_next_action": "route_to_scope_review_policy",
        },
        {
            "paper_id": "paper:3",
            "paper_title": "Phenotype paper",
            "claim_id": "claim:3",
            "run_id": "run:3",
            "target_type": "Concept",
            "target_id": "concept:gait_speed",
            "target_label": "gait speed",
            "adjudication_bucket": "scope_review_clinical_or_biomarker",
            "bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "evidence_section": "title",
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    assert main(["--scope-review-rows", str(input_path), "--output-dir", str(output_dir)]) == 0

    summary = json.loads((output_dir / "scope_review_split_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["rows_total"] == 3
    assert summary["counts"]["biomarker_receptor"] == 1
    assert summary["counts"]["disease_diagnosis"] == 1
    assert summary["counts"]["behavioral_phenotype"] == 1
    assert (output_dir / "lane_biomarker_receptor.jsonl").exists()
    assert (output_dir / "lane_disease_diagnosis.jsonl").exists()
    assert (output_dir / "lane_behavioral_phenotype.jsonl").exists()

    split_rows = [
        json.loads(line)
        for line in (output_dir / "scope_review_split_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    by_target = {row["target_id"]: row for row in split_rows}
    receptor_row = by_target["concept:dopamine_d2_receptor_availability"]
    assert receptor_row["lane"] == "biomarker_receptor"
    assert receptor_row["source_review_bucket"] == "scope_review_clinical_or_biomarker"
    assert (
        receptor_row["source_ledger_bucket"]
        == "biomarker_unresolved_no_non_title_text"
    )
    assert receptor_row["source_resolution_bucket"] == "scope_review"
    assert (
        receptor_row["source_resolution_reason"]
        == "broad_biomarker_requires_scope_review"
    )
    assert (
        receptor_row["source_recommended_next_action"]
        == "route_to_scope_review_policy"
    )

    disease_row = by_target["concept:conduct_disorder"]
    assert disease_row["source_stage"] == "balanced_concept_hold_adjudication"
    assert disease_row["source_artifact_path"] == str(input_path.resolve())
