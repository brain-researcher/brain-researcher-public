from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_title_only_review_pack import main


def test_build_balanced_title_only_review_pack_buckets_remaining_rows(
    tmp_path: Path,
) -> None:
    review_queue_path = tmp_path / "review_queue.jsonl"
    rows = [
        {
            "record": {
                "run": {
                    "run_id": "task-1",
                    "prompt_hash": "p1",
                    "template_hash": "t1",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/task.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
                "paper": {"id": "pmid:1", "title": "Task title"},
                "target": {"type": "Task", "id": "task:trust_game", "label": "Trust Game"},
                "claim": {"id": "claim:1", "text": "Task claim", "polarity": "supports", "claim_strength": 0.8},
                "evidence": {"section": "title", "quote": "Trust Game", "locatable": True, "direct_quote": True, "has_statistical_detail": False},
                "signals": {"title_only_evidence": True, "mapping_confidence": 0.82, "claim_strength": 0.8},
                "method": {},
                "prov": {
                    "run_id": "task-1",
                    "prompt_hash": "p1",
                    "template_hash": "t1",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/task.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
            }
        },
        {
            "record": {
                "run": {
                    "run_id": "generic-1",
                    "prompt_hash": "p2",
                    "template_hash": "t2",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/generic.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
                "paper": {"id": "pmid:2", "title": "Generic title"},
                "target": {"type": "Concept", "id": "concept:neural_activation", "label": "Neural Activation"},
                "claim": {"id": "claim:2", "text": "Generic claim", "polarity": "supports", "claim_strength": 0.8},
                "evidence": {"section": "title", "quote": "Neural Activation", "locatable": True, "direct_quote": True, "has_statistical_detail": False},
                "signals": {"title_only_evidence": True, "mapping_confidence": 0.82, "claim_strength": 0.8},
                "method": {},
                "prov": {
                    "run_id": "generic-1",
                    "prompt_hash": "p2",
                    "template_hash": "t2",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/generic.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
            }
        },
        {
            "record": {
                "run": {
                    "run_id": "hold-1",
                    "prompt_hash": "p3",
                    "template_hash": "t3",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/hold.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
                "paper": {"id": "pmid:3", "title": "Hold title"},
                "target": {"type": "Concept", "id": "concept:egocentric_bias", "label": "egocentric bias"},
                "claim": {"id": "claim:3", "text": "Hold claim", "polarity": "supports", "claim_strength": 0.8},
                "evidence": {"section": "title", "quote": "egocentric bias", "locatable": True, "direct_quote": True, "has_statistical_detail": False},
                "signals": {"title_only_evidence": True, "mapping_confidence": 0.82, "claim_strength": 0.8},
                "method": {},
                "prov": {
                    "run_id": "hold-1",
                    "prompt_hash": "p3",
                    "template_hash": "t3",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/hold.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
            }
        },
        {
            "record": {
                "run": {
                    "run_id": "reroute-1",
                    "prompt_hash": "p4",
                    "template_hash": "t4",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/reroute.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
                "paper": {"id": "pmid:4", "title": "fMRI study"},
                "target": {"type": "Concept", "id": "concept:fmri", "label": "fMRI"},
                "claim": {"id": "claim:4", "text": "fMRI claim", "polarity": "supports", "claim_strength": 0.8},
                "evidence": {"section": "title", "quote": "fMRI study", "locatable": True, "direct_quote": True, "has_statistical_detail": False},
                "signals": {"title_only_evidence": True, "mapping_confidence": 0.82, "claim_strength": 0.8},
                "method": {},
                "prov": {
                    "run_id": "reroute-1",
                    "prompt_hash": "p4",
                    "template_hash": "t4",
                    "model": "gemini-2.5-flash",
                    "raw_response_path": "/tmp/reroute.json",
                    "loader_version": "gabriel-loader/v1",
                    "timestamp": "2026-03-13T00:00:00Z",
                },
            }
        },
    ]
    review_queue_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "--review-queue",
            str(review_queue_path),
            "--output-dir",
            str(output_dir),
            "--quality-profile",
            "balanced_marginal",
        ]
    )

    assert exit_code == 0
    summary = json.loads(
        (output_dir / "title_only_review_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["title_only_rows_reviewed"] == 2
    assert summary["counts"]["salvage_task_or_region"] == 1
    assert summary["counts"]["generic_concept_remainder"] == 0
    assert summary["counts"]["substantive_concept_hold"] == 1

    rows_out = [
        json.loads(line)
        for line in (output_dir / "title_only_review_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    by_target = {row["target_id"]: row for row in rows_out}
    assert by_target["task:trust_game"]["review_bucket"] == "salvage_task_or_region"
    assert (
        by_target["concept:egocentric_bias"]["review_bucket"]
        == "substantive_concept_hold"
    )
    assert "concept:neural_activation" not in by_target
    assert "concept:fmri" not in by_target
