from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_title_only_regeneration_pack import main


def test_build_balanced_title_only_regeneration_pack_exports_salvage_rows(
    tmp_path: Path,
) -> None:
    salvage_path = tmp_path / "salvage.jsonl"
    rows = [
        {
            "paper_id": "pmid:1",
            "paper_title": "Trust Game title",
            "claim_id": "claim:1",
            "run_id": "run:1",
            "target_type": "Task",
            "target_id": "task:trust_game",
            "target_label": "Trust Game",
            "review_bucket": "salvage_task_or_region",
            "bucket_reason": "specific_task_or_region_target",
            "method_rigor": 0.0,
            "mapping_confidence": 0.82,
            "claim_strength": 0.72,
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "pmid:2",
            "paper_title": "Amygdala title",
            "claim_id": "claim:2",
            "run_id": "run:2",
            "target_type": "Region",
            "target_id": "region:human_amygdala",
            "target_label": "Human Amygdala",
            "review_bucket": "salvage_task_or_region",
            "bucket_reason": "specific_task_or_region_target",
            "evidence_section": "title",
            "method_rigor": 0.0,
            "mapping_confidence": 0.85,
            "claim_strength": 0.74,
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "pmid:3",
            "paper_title": "Hold title",
            "claim_id": "claim:3",
            "run_id": "run:3",
            "target_type": "Concept",
            "target_id": "concept:egocentric_bias",
            "target_label": "egocentric bias",
            "review_bucket": "substantive_concept_hold",
            "bucket_reason": "substantive_concept_title_row",
            "evidence_section": "title",
            "method_rigor": 0.0,
            "mapping_confidence": 0.85,
            "claim_strength": 0.74,
            "rejection_reasons": ["benchmark_title_only_suppressed"],
        },
        {
            "paper_id": "pmid:4",
            "paper_title": "Task without title suppression",
            "claim_id": "claim:4",
            "run_id": "run:4",
            "target_type": "Task",
            "target_id": "task:response_inhibition",
            "target_label": "Response Inhibition",
            "review_bucket": "salvage_task_or_region",
            "bucket_reason": "specific_task_or_region_target",
            "evidence_section": "abstract",
            "method_rigor": 0.2,
            "mapping_confidence": 0.9,
            "claim_strength": 0.8,
            "rejection_reasons": ["method_rigor_below_threshold"],
        },
    ]
    salvage_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "--salvage-rows",
            str(salvage_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    summary = json.loads(
        (output_dir / "title_only_regeneration_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"]["regeneration_rows"] == 2
    assert summary["counts"]["task_rows"] == 1
    assert summary["counts"]["region_rows"] == 1
    assert summary["counts"]["skipped_non_title_suppressed"] == 1
    assert summary["counts"]["skipped_invalid_target_type"] == 0

    pack_rows = [
        json.loads(line)
        for line in (output_dir / "title_only_regeneration_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert {row["target_id"] for row in pack_rows} == {
        "task:trust_game",
        "region:human_amygdala",
    }
    task_row = next(row for row in pack_rows if row["target_type"] == "Task")
    region_row = next(row for row in pack_rows if row["target_type"] == "Region")
    assert task_row["evidence_requirement"] == "abstract_or_body_required"
    assert task_row["suppress_title_only"] is True
    assert task_row["source_review_bucket"] == "salvage_task_or_region"
    assert "task paradigm results" in task_row["search_query"]
    assert "activation connectivity region" in region_row["search_query"]
