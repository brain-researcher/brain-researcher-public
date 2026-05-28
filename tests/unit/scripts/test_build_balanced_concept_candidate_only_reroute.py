from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_concept_candidate_only_reroute import main


def test_build_balanced_concept_candidate_only_reroute(tmp_path: Path) -> None:
    input_path = tmp_path / "candidate_only.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "paper_id": "paper:1",
                "paper_title": "Example",
                "claim_id": "claim:1",
                "run_id": "run:1",
                "target_type": "Concept",
                "target_id": "concept:hurst_exponent",
                "target_label": "Hurst Exponent",
                "proposed_action": "reroute_candidate_only",
                "adjudication_bucket": "candidate_only_composite_or_analysis",
                "bucket_reason": "network_or_analysis_composite_title_concept",
                "source_review_bucket": "substantive_concept_hold",
                "source_bucket_reason": "substantive_concept_title_row",
                "source_stage": "balanced_concept_hold_adjudication",
                "source_artifact_path": "/tmp/concept_hold_adjudication_pack.jsonl",
                "evidence_section": "title",
                "mapping_confidence": 1.0,
                "claim_strength": 0.8,
                "method_rigor": 0.1,
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
        (output_dir / "review_queue_candidate_only.jsonl").read_text(encoding="utf-8").strip()
    )
    assert payload["routing"]["lane"] == "candidate_only"
    assert payload["routing"]["bucket"] == "concept_hold_candidate_only"
    assert "adjudicated_candidate_only_concept_hold" in payload["reasons"]
    assert payload["record"]["target"]["id"] == "concept:hurst_exponent"
    assert payload["record"]["source_review_bucket"] == "candidate_only_composite_or_analysis"
    assert payload["record"]["source_bucket_reason"] == (
        "network_or_analysis_composite_title_concept"
    )
    assert payload["record"]["upstream_review_bucket"] == "substantive_concept_hold"
    assert payload["record"]["source_stage"] == "balanced_concept_hold_adjudication"
    assert (
        payload["record"]["source_artifact_path"]
        == "/tmp/concept_hold_adjudication_pack.jsonl"
    )
    assert payload["record"]["proposed_action"] == "reroute_candidate_only"
    summary = json.loads(
        (output_dir / "candidate_only_reroute_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 1
