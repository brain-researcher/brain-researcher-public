from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_specific_concept_regeneration_pack import main


def test_build_balanced_specific_concept_regeneration_pack(tmp_path: Path) -> None:
    input_path = tmp_path / "specific.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "paper_id": "paper:1",
                "paper_title": "Example",
                "claim_id": "claim:1",
                "run_id": "run:1",
                "target_type": "Concept",
                "target_id": "concept:action_understanding",
                "target_label": "Action Understanding",
                "proposed_action": "regenerate_non_title_concept",
                "adjudication_bucket": "specific_concept_regeneration",
                "bucket_reason": "specific_cognitive_or_behavioral_concept",
                "source_review_bucket": "substantive_concept_hold",
                "source_bucket_reason": "substantive_concept_title_row",
                "rejection_reasons": ["benchmark_title_only_suppressed"],
                "review_questions": ["q1"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    assert main(["--adjudication-rows", str(input_path), "--output-dir", str(output_dir)]) == 0

    payload = json.loads(
        (output_dir / "specific_concept_regeneration_pack.jsonl").read_text(encoding="utf-8").strip()
    )
    assert payload["target_type"] == "Concept"
    assert payload["target_id"] == "concept:action_understanding"
    assert payload["prefer_sections"] == ["abstract", "methods", "results", "discussion"]
    summary = json.loads(
        (output_dir / "specific_concept_regeneration_pack_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 1
