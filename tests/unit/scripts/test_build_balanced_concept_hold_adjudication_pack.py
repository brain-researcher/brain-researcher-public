from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_concept_hold_adjudication_pack import (
    classify_concept_hold_row,
    main,
)


def test_classify_concept_hold_row_buckets() -> None:
    assert classify_concept_hold_row({"target_label": "resting state networks"})[0] == "candidate_only_composite_or_analysis"
    assert classify_concept_hold_row({"target_label": "Crohn's disease"})[0] == "scope_review_clinical_or_biomarker"
    assert classify_concept_hold_row({"target_label": "Time Perception"})[0] == "specific_concept_regeneration"


def test_build_balanced_concept_hold_adjudication_pack_exports_rows(
    tmp_path: Path,
) -> None:
    hold_path = tmp_path / "hold.jsonl"
    rows = [
        {
            "paper_id": "paper:1",
            "paper_title": "Networks title",
            "claim_id": "claim:1",
            "run_id": "run:1",
            "target_type": "Concept",
            "target_id": "concept:resting_state_networks",
            "target_label": "resting state networks",
            "review_bucket": "substantive_concept_hold",
            "bucket_reason": "substantive_concept_title_row",
            "evidence_section": "title",
            "method_rigor": 0.0,
            "mapping_confidence": 0.1,
            "claim_strength": 0.4,
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "paper:2",
            "paper_title": "Disease title",
            "claim_id": "claim:2",
            "run_id": "run:2",
            "target_type": "Concept",
            "target_id": "concept:crohn_s_disease",
            "target_label": "Crohn's disease",
            "review_bucket": "substantive_concept_hold",
            "bucket_reason": "substantive_concept_title_row",
            "evidence_section": "title",
            "method_rigor": 0.0,
            "mapping_confidence": 0.1,
            "claim_strength": 0.4,
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "paper:3",
            "paper_title": "Time title",
            "claim_id": "claim:3",
            "run_id": "run:3",
            "target_type": "Concept",
            "target_id": "concept:time_perception",
            "target_label": "Time Perception",
            "review_bucket": "substantive_concept_hold",
            "bucket_reason": "substantive_concept_title_row",
            "evidence_section": "title",
            "method_rigor": 0.0,
            "mapping_confidence": 0.1,
            "claim_strength": 0.4,
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
    ]
    hold_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "--hold-rows",
            str(hold_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    summary = json.loads(
        (output_dir / "concept_hold_adjudication_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"]["rows_total"] == 3
    assert summary["counts"]["candidate_only_composite_or_analysis"] == 1
    assert summary["counts"]["scope_review_clinical_or_biomarker"] == 1
    assert summary["counts"]["specific_concept_regeneration"] == 1

