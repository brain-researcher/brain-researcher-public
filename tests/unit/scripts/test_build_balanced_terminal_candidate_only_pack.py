from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_balanced_terminal_candidate_only_pack as module


def test_terminal_candidate_only_pack_builds_queue_and_live_state(
    monkeypatch, tmp_path: Path
) -> None:
    unresolved = tmp_path / "unresolved.jsonl"
    source = tmp_path / "source.jsonl"
    output_dir = tmp_path / "out"

    unresolved.write_text(
        json.dumps(
            {
                "paper_id": "paper:1",
                "paper_title": "Example title",
                "target_id": "task:trust_game",
                "target_label": "Trust Game",
                "reason": "publication_unresolved_or_no_non_title_text",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source.write_text(
        json.dumps(
            {
                "paper_id": "paper:1",
                "paper_title": "Example title",
                "claim_id": "claim:1",
                "run_id": "run:1",
                "target_type": "Task",
                "target_id": "task:trust_game",
                "target_label": "Trust Game",
                "evidence_section": "title",
                "rejection_reasons": ["benchmark_title_only_suppressed"],
                "method_rigor": 0.1,
                "mapping_confidence": 0.0,
                "claim_strength": 0.8,
                "source_review_bucket": "salvage_task_or_region",
                "bucket_reason": "specific_task_or_region_target",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_resolve_live_claim_state",
        lambda claim_ids: {
            "claim:1": {
                "claim_id": "claim:1",
                "live_target_id": "task:trust_game",
                "live_paper_id": "paper:1",
            }
        },
    )

    exit_code = module.main(
        [
            "--unresolved-rows",
            str(unresolved),
            "--source-review-pack",
            str(source),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "terminal_candidate_only_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 1
    assert summary["counts"]["candidate_only"] == 1
    assert summary["counts"]["live_claim_present"] == 1

    terminal_rows = [
        json.loads(line)
        for line in (output_dir / "terminal_resolution_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert terminal_rows[0]["terminal_resolution_bucket"] == "candidate_only"
    assert terminal_rows[0]["live_claim_present"] is True

    queue_rows = [
        json.loads(line)
        for line in (output_dir / "review_queue_candidate_only.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert queue_rows[0]["routing"]["lane"] == "candidate_only"
    assert queue_rows[0]["record"]["claim"]["id"] == "claim:1"
    assert queue_rows[0]["record"]["source_bucket_reason"] == "specific_task_or_region_target"
    assert queue_rows[0]["record"]["source_join_status"] == "matched"
    assert (
        queue_rows[0]["record"]["terminal_resolution_bucket"] == "candidate_only"
    )


def test_terminal_candidate_only_pack_join_miss_defaults_unknowns_to_safe_retire(
    monkeypatch, tmp_path: Path
) -> None:
    unresolved = tmp_path / "unresolved.jsonl"
    source = tmp_path / "source.jsonl"
    output_dir = tmp_path / "out"

    unresolved.write_text(
        json.dumps(
            {
                "paper_id": "paper:2",
                "paper_title": "Region title",
                "target_id": "region:left_amygdala",
                "target_label": "left amygdala",
                "reason": "publication_unresolved_or_no_non_title_text",
                "source_ledger_bucket": "biomarker_unresolved_no_non_title_text",
                "blocking_reason": "fulltext_retry_exhausted",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "_resolve_live_claim_state", lambda claim_ids: {})

    exit_code = module.main(
        [
            "--unresolved-rows",
            str(unresolved),
            "--source-review-pack",
            str(source),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "terminal_candidate_only_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 1
    assert summary["counts"]["retire_benchmark"] == 1
    assert "candidate_only" not in summary["counts"]

    terminal_rows = [
        json.loads(line)
        for line in (output_dir / "terminal_resolution_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert terminal_rows[0]["target_type"] == "Region"
    assert terminal_rows[0]["source_join_status"] == "missing"
    assert terminal_rows[0]["terminal_resolution_bucket"] == "retire_benchmark"
    assert (
        terminal_rows[0]["terminal_resolution_reason"]
        == "missing_terminal_source_review_join_defaults_to_retire"
    )
    assert (
        terminal_rows[0]["source_review_bucket"]
        == "biomarker_unresolved_no_non_title_text"
    )

    assert (
        output_dir / "review_queue_candidate_only.jsonl"
    ).read_text(encoding="utf-8") == ""


def test_terminal_candidate_only_pack_duplicate_join_defaults_to_safe_retire(
    monkeypatch, tmp_path: Path
) -> None:
    unresolved = tmp_path / "unresolved.jsonl"
    source = tmp_path / "source.jsonl"
    output_dir = tmp_path / "out"

    unresolved.write_text(
        json.dumps(
            {
                "paper_id": "paper:3",
                "paper_title": "Concept title",
                "target_id": "concept:emotion_regulation",
                "target_label": "emotion regulation",
                "reason": "publication_unresolved_or_no_non_title_text",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "paper_id": "paper:3",
                        "paper_title": "Concept title",
                        "claim_id": "claim:3a",
                        "run_id": "run:3a",
                        "target_type": "Concept",
                        "target_id": "concept:emotion_regulation",
                        "target_label": "emotion regulation",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "paper:3",
                        "paper_title": "Concept title",
                        "claim_id": "claim:3b",
                        "run_id": "run:3b",
                        "target_type": "Concept",
                        "target_id": "concept:emotion_regulation",
                        "target_label": "emotion regulation",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "_resolve_live_claim_state", lambda claim_ids: {})

    exit_code = module.main(
        [
            "--unresolved-rows",
            str(unresolved),
            "--source-review-pack",
            str(source),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    terminal_rows = [
        json.loads(line)
        for line in (output_dir / "terminal_resolution_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert terminal_rows[0]["source_join_status"] == "duplicate"
    assert terminal_rows[0]["terminal_resolution_bucket"] == "retire_benchmark"
    assert (
        terminal_rows[0]["terminal_resolution_reason"]
        == "ambiguous_terminal_source_review_join_defaults_to_retire"
    )
    assert (
        output_dir / "review_queue_candidate_only.jsonl"
    ).read_text(encoding="utf-8") == ""
