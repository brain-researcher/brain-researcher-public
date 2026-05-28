from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_no_non_title_resolution_pack import (
    classify_resolution,
    main,
)


def test_classify_resolution() -> None:
    assert (
        classify_resolution({"target_id": "task:trust_game", "target_type": "Task"})[0]
        == "fulltext_retry"
    )
    assert (
        classify_resolution(
            {
                "target_id": "task:gambling_availability_during_sports_picture_exposure",
                "target_type": "Task",
            }
        )[0]
        == "retire_benchmark"
    )
    assert (
        classify_resolution(
            {"target_id": "region:brain_structure", "target_type": "Region"}
        )[0]
        == "retire_benchmark"
    )
    assert (
        classify_resolution(
            {"target_id": "concept:emotion_regulation", "target_type": "Concept"}
        )[0]
        == "candidate_only"
    )
    assert (
        classify_resolution(
            {
                "target_id": "concept:serotonin_1a_receptor_binding",
                "target_type": "Concept",
            }
        )[0]
        == "fulltext_retry"
    )
    assert (
        classify_resolution(
            {
                "target_id": "concept:amyloid",
                "target_type": "Concept",
                "target_label": "Amyloid",
                "ledger_bucket": "biomarker_unresolved_no_non_title_text",
            }
        )[0]
        == "scope_review"
    )
    assert (
        classify_resolution(
            {
                "target_id": "concept:dopamine_d2_receptor_availability",
                "target_type": "Concept",
                "target_label": "dopamine D2 receptor availability",
                "ledger_bucket": "biomarker_unresolved_no_non_title_text",
            }
        )[0]
        == "fulltext_retry"
    )


def test_build_balanced_no_non_title_resolution_pack(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    rows = [
        {
            "paper_id": "paper:1",
            "paper_title": "Trust game paper",
            "target_type": "Task",
            "target_id": "task:trust_game",
            "target_label": "Trust Game",
            "ledger_bucket": "task_region_unresolved_no_non_title_text",
        },
        {
            "paper_id": "paper:2",
            "paper_title": "Broad region paper",
            "target_type": "Region",
            "target_id": "region:brain_structure",
            "target_label": "brain structure",
            "ledger_bucket": "task_region_unresolved_no_non_title_text",
        },
        {
            "paper_id": "paper:3",
            "paper_title": "Emotion regulation paper",
            "target_type": "Concept",
            "target_id": "concept:emotion_regulation",
            "target_label": "emotion regulation",
            "ledger_bucket": "specific_concept_unresolved_no_non_title_text",
            "source_stage": "balanced_specific_concept_regeneration_run",
            "source_artifact_path": "/tmp/specific.jsonl",
            "source_review_bucket": "substantive_concept_hold",
            "source_bucket_reason": "substantive_concept_title_row",
            "blocking_reason": "no_non_title_text_after_specific_concept_regeneration",
            "recommended_next_action": "retry_with_fulltext_or_candidate_only",
        },
        {
            "paper_id": "paper:4",
            "paper_title": "Amyloid paper",
            "target_type": "Concept",
            "target_id": "concept:amyloid",
            "target_label": "Amyloid",
            "ledger_bucket": "biomarker_unresolved_no_non_title_text",
            "source_stage": "balanced_biomarker_regeneration_run",
            "source_artifact_path": "/tmp/biomarker.jsonl",
            "source_review_bucket": "scope_review_clinical_or_biomarker",
            "source_bucket_reason": "clinical_trait_or_biomarker_title_concept",
            "blocking_reason": "no_non_title_text_after_biomarker_regeneration",
            "recommended_next_action": "retry_with_fulltext_or_hold",
        },
    ]
    ledger_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    assert main(["--residual-ledger", str(ledger_path), "--output-dir", str(output_dir)]) == 0

    summary = json.loads(
        (output_dir / "no_non_title_resolution_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"]["rows_total"] == 4
    assert summary["counts"]["fulltext_retry"] == 1
    assert summary["counts"]["retire_benchmark"] == 1
    assert summary["counts"]["candidate_only"] == 1
    assert summary["counts"]["scope_review"] == 1

    rows_out = [
        json.loads(line)
        for line in (output_dir / "no_non_title_resolution_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    by_target = {row["target_id"]: row for row in rows_out}
    assert by_target["concept:amyloid"]["resolution_bucket"] == "scope_review"
    assert (
        by_target["concept:amyloid"]["recommended_next_action"]
        == "route_to_scope_review_policy"
    )
    assert (
        by_target["concept:amyloid"]["source_ledger_bucket"]
        == "biomarker_unresolved_no_non_title_text"
    )
    assert (
        by_target["concept:emotion_regulation"]["source_recommended_next_action"]
        == "retry_with_fulltext_or_candidate_only"
    )
    assert by_target["concept:emotion_regulation"]["proposed_action"] == "reroute_candidate_only"
    assert (
        by_target["concept:emotion_regulation"]["adjudication_bucket"]
        == "no_non_title_candidate_only"
    )
    assert by_target["region:brain_structure"]["proposed_action"] == "retire_benchmark_followup"
