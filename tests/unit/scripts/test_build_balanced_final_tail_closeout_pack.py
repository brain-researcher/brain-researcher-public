from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_balanced_final_tail_closeout_pack as module


def test_final_tail_closeout_pack_splits_hold_and_retry(monkeypatch, tmp_path: Path) -> None:
    residual = tmp_path / "residual.jsonl"
    retry = tmp_path / "retry.jsonl"
    output_dir = tmp_path / "out"

    residual.write_text(
        json.dumps(
            {
                "paper_id": "paper:hold",
                "paper_title": "Hold title",
                "claim_id": "claim:hold",
                "run_id": "run:hold",
                "target_type": "Concept",
                "target_id": "concept:amyloid",
                "target_label": "Amyloid",
                "evidence_section": "title",
                "rejection_reasons": ["benchmark_title_only_suppressed"],
                "mapping_confidence": 0.0,
                "claim_strength": 0.5,
                "method_rigor": 0.1,
                "ledger_bucket": "broad_biomarker_hold",
                "source_review_bucket": "broad_biomarker_hold",
                "source_bucket_reason": "broad_biomarker_scope_hold",
                "source_stage": "balanced_biomarker_policy",
                "source_artifact_path": "/tmp/broad_biomarker_hold.jsonl",
                "blocking_reason": "not_benchmark_ready",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    retry.write_text(
        json.dumps(
            {
                "paper_id": "paper:retry",
                "paper_title": "Retry title",
                "target_type": "Region",
                "target_id": "region:left_inferior_frontal_gyrus",
                "target_label": "left inferior frontal gyrus",
                "claim_id": "claim:retry",
                "run_id": "run:retry",
                "source_ledger_bucket": "task_region_parse_error",
                "source_review_bucket": "salvage_task_or_region",
                "source_bucket_reason": "title_only_after_retry",
                "source_stage": "balanced_title_only_regeneration_run",
                "source_artifact_path": "/tmp/retry_now_pack.jsonl",
                "retry_mode": "retry_now",
                "blocking_reason": "parse_error_during_task_region_regeneration",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_resolve_live_claim_state",
        lambda claim_ids: {
            "claim:hold": {
                "claim_id": "claim:hold",
                "live_target_id": "concept:amyloid",
                "live_paper_id": "paper:hold",
            }
        },
    )

    exit_code = module.main(
        [
            "--residual-ledger",
            str(residual),
            "--retry-now-pack",
            str(retry),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "final_tail_closeout_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 2
    assert summary["counts"]["candidate_only"] == 1
    assert summary["counts"]["retire_benchmark"] == 1
    assert summary["counts"]["live_claim_present"] == 1

    candidate_only_rows = [
        json.loads(line)
        for line in (output_dir / "candidate_only.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert candidate_only_rows[0]["target_id"] == "concept:amyloid"
    assert candidate_only_rows[0]["source_stage"] == "balanced_biomarker_policy"
    assert (
        candidate_only_rows[0]["source_artifact_path"]
        == "/tmp/broad_biomarker_hold.jsonl"
    )

    retire_rows = [
        json.loads(line)
        for line in (output_dir / "retire_benchmark.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert retire_rows[0]["target_id"] == "region:left_inferior_frontal_gyrus"
    assert retire_rows[0]["source_stage"] == "balanced_title_only_regeneration_run"

    queue_rows = [
        json.loads(line)
        for line in (output_dir / "review_queue_candidate_only.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert queue_rows[0]["record"]["source_review_bucket"] == "broad_biomarker_hold"
    assert queue_rows[0]["record"]["source_bucket_reason"] == "broad_biomarker_scope_hold"
    assert queue_rows[0]["record"]["source_stage"] == "balanced_biomarker_policy"
    assert queue_rows[0]["record"]["source_ledger_bucket"] == "broad_biomarker_hold"
    assert queue_rows[0]["record"]["closeout_stage"] == "balanced_final_tail_closeout"
    assert (
        queue_rows[0]["record"]["closeout_input_artifact_path"]
        == str(residual.resolve())
    )
    assert queue_rows[0]["record"]["terminal_resolution_bucket"] == "candidate_only"
    assert queue_rows[0]["record"]["terminal_resolution_reason"] == (
        "broad_or_manual_concept_not_benchmark_ready"
    )
    assert queue_rows[0]["record"]["live_claim_present"] is True
    assert queue_rows[0]["record"]["live_target_id"] == "concept:amyloid"


def test_final_tail_closeout_pack_marks_non_region_retry_rows_as_generic_retire(
    monkeypatch, tmp_path: Path
) -> None:
    residual = tmp_path / "residual.jsonl"
    retry = tmp_path / "retry.jsonl"
    output_dir = tmp_path / "out"

    residual.write_text("", encoding="utf-8")
    retry.write_text(
        json.dumps(
            {
                "paper_id": "paper:retry-task",
                "paper_title": "Retry title",
                "target_type": "Task",
                "target_id": "task:trust_game",
                "target_label": "Trust Game",
                "source_ledger_bucket": "task_region_parse_error",
                "blocking_reason": "parse_error_during_task_region_regeneration",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "_resolve_live_claim_state", lambda claim_ids: {})

    exit_code = module.main(
        [
            "--residual-ledger",
            str(residual),
            "--retry-now-pack",
            str(retry),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    retire_rows = [
        json.loads(line)
        for line in (output_dir / "retire_benchmark.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert retire_rows[0]["terminal_resolution_bucket"] == "retire_benchmark"
    assert (
        retire_rows[0]["terminal_resolution_reason"]
        == "non_region_retry_now_row_defaults_to_retire"
    )
