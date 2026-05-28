from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_method_audit_pack import main


def test_build_balanced_method_audit_pack_outputs_rejected_and_accepted_rows(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True)

    accepted_record = {
        "run": {
            "run_id": "accepted-1",
            "prompt_hash": "p1",
            "template_hash": "t1",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/accepted.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
        "paper": {"id": "pmid:1", "title": "Accepted paper"},
        "target": {"type": "Task", "id": "task:semantic_localizer", "label": "Semantic Localizer"},
        "claim": {"id": "claim:1", "text": "Accepted claim", "polarity": "supports", "claim_strength": 0.6},
        "evidence": {
            "quote": "Participants completed a semantic localizer task (n = 64).",
            "section": "methods",
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
        },
        "method": {
            "sample_size": {"status": "reported", "reported_n": 64, "quote": "n = 64", "section": "methods"},
            "threshold_correction": {"status": "yes", "quote": "FDR correction", "section": "results", "correction_type": "fdr"},
            "operationalization": {"status": "clear", "quote": "semantic localizer task", "section": "methods"},
        },
        "signals": {
            "mention_strength": 0.7,
            "mapping_confidence": 0.86,
            "claim_strength": 0.6,
            "preregistration": "unknown",
            "open_data_or_code": "unknown",
        },
        "prov": {
            "run_id": "accepted-1",
            "prompt_hash": "p1",
            "template_hash": "t1",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/accepted.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
    }
    rejected_record = {
        "run": {
            "run_id": "rejected-1",
            "prompt_hash": "p2",
            "template_hash": "t2",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/rejected.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
        "paper": {"id": "pmid:2", "title": "Rejected paper"},
        "target": {"type": "Concept", "id": "concept:emotion_regulation", "label": "Emotion Regulation"},
        "claim": {"id": "claim:2", "text": "Rejected claim", "polarity": "supports", "claim_strength": 0.62},
        "evidence": {
            "quote": "Emotion regulation effects were observed.",
            "section": "abstract",
            "has_statistical_detail": False,
            "locatable": True,
            "direct_quote": True,
        },
        "method": {
            "sample_size": {"status": "unknown", "reported_n": None, "quote": None, "section": "unknown"},
            "threshold_correction": {"status": "unknown", "quote": None, "section": "unknown", "correction_type": None},
            "operationalization": {"status": "unknown", "quote": None, "section": "unknown"},
        },
        "signals": {
            "mention_strength": 0.75,
            "mapping_confidence": 0.84,
            "claim_strength": 0.62,
        },
        "prov": {
            "run_id": "rejected-1",
            "prompt_hash": "p2",
            "template_hash": "t2",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/rejected.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
    }

    shard_path = shard_dir / "shard_0000.jsonl"
    shard_path.write_text(
        json.dumps(accepted_record) + "\n" + json.dumps(rejected_record) + "\n",
        encoding="utf-8",
    )
    review_queue_path = run_dir / "review_queue.jsonl"
    review_queue_path.write_text(
        json.dumps(
            {
                "queued_at": "2026-03-13T00:00:00Z",
                "reasons": ["method_rigor_below_threshold"],
                "variables": {
                    "mention_strength": 0.75,
                    "mapping_confidence": 0.84,
                    "claim_polarity": "supports",
                    "claim_strength": 0.62,
                    "evidence_quality": "medium",
                    "evidence_quality_score": 0.60,
                    "method_rigor": 0.22,
                    "provenance_completeness": 1.0,
                },
                "record": rejected_record,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "paths": {"run_dir": str(run_dir)},
                "ingest": {"review_queue_path": str(review_queue_path)},
                "shards": [{"path": str(shard_path)}],
            }
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--max-rejected",
            "10",
            "--max-accepted",
            "10",
        ]
    )

    assert exit_code == 0
    summary = json.loads(
        (output_dir / "balanced_method_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["rejected_rows_total"] == 1
    assert summary["accepted_controls_total"] == 1

    rows = [
        json.loads(line)
        for line in (output_dir / "balanced_method_audit_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    buckets = {row["bucket"] for row in rows}
    assert "rejected_method_only" in buckets
    assert "accepted_near_threshold_control" in buckets


def test_build_balanced_method_audit_pack_dedupes_review_rows_and_excludes_mixed_failures(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True)

    rejected_record = {
        "run": {
            "run_id": "rejected-dup",
            "prompt_hash": "p2",
            "template_hash": "t2",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/rejected.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
        "paper": {"id": "pmid:2", "title": "Rejected paper"},
        "target": {"type": "Concept", "id": "concept:emotion_regulation", "label": "Emotion Regulation"},
        "claim": {"id": "claim:2", "text": "Rejected claim", "polarity": "supports", "claim_strength": 0.62},
        "evidence": {
            "quote": "Emotion regulation effects were observed.",
            "section": "abstract",
            "has_statistical_detail": False,
            "locatable": True,
            "direct_quote": True,
        },
        "method": {
            "sample_size": {"status": "unknown", "reported_n": None, "quote": None, "section": "unknown"},
            "threshold_correction": {"status": "unknown", "quote": None, "section": "unknown", "correction_type": None},
            "operationalization": {"status": "unknown", "quote": None, "section": "unknown"},
        },
        "signals": {
            "mention_strength": 0.75,
            "mapping_confidence": 0.84,
            "claim_strength": 0.62,
        },
        "prov": {
            "run_id": "rejected-dup",
            "prompt_hash": "p2",
            "template_hash": "t2",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/rejected.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
    }

    shard_path = shard_dir / "shard_0000.jsonl"
    shard_path.write_text(json.dumps(rejected_record) + "\n", encoding="utf-8")
    review_queue_path = run_dir / "review_queue.jsonl"
    review_queue_rows = [
        {
            "reasons": ["method_rigor_below_threshold"],
            "variables": {"method_rigor": 0.22},
            "record": rejected_record,
        },
        {
            "reasons": ["method_rigor_below_threshold"],
            "variables": {"method_rigor": 0.22},
            "record": rejected_record,
        },
        {
            "reasons": [
                "method_rigor_below_threshold",
                "mapping_confidence_below_threshold",
                "title_only_low_rigor_evidence",
            ],
            "variables": {"method_rigor": 0.2},
            "record": {
                **rejected_record,
                "run": {**rejected_record["run"], "run_id": "rejected-mixed"},
                "claim": {**rejected_record["claim"], "id": "claim:mixed"},
            },
        },
    ]
    review_queue_path.write_text(
        "\n".join(json.dumps(row) for row in review_queue_rows) + "\n",
        encoding="utf-8",
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
                {
                    "paths": {"run_dir": "."},
                    "ingest": {"review_queue_path": "review_queue.jsonl"},
                    "shards": [{"path": "shards/shard_0000.jsonl"}],
                }
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--max-rejected",
            "10",
            "--max-accepted",
            "0",
        ]
    )

    assert exit_code == 0
    summary = json.loads(
        (output_dir / "balanced_method_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["rejected_rows_total"] == 1
    assert summary["review_rows_deduped"] == 2
    assert summary["duplicate_review_rows_skipped"] == 1
    assert summary["rejection_bucket_counts"]["rejected_method_only"] == 1
    assert summary["rejection_bucket_counts"]["review_mixed_method_mapping"] == 1

    rows = [
        json.loads(line)
        for line in (output_dir / "balanced_method_audit_pack.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["bucket"] == "rejected_method_only"


def test_build_balanced_method_audit_pack_falls_back_to_shards_dir_when_manifest_omits_shards(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True)
    accepted_record = {
        "run": {
            "run_id": "accepted-1",
            "prompt_hash": "p1",
            "template_hash": "t1",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/accepted.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
        "paper": {"id": "pmid:1", "title": "Accepted paper"},
        "target": {"type": "Task", "id": "task:semantic_localizer", "label": "Semantic Localizer"},
        "claim": {"id": "claim:1", "text": "Accepted claim", "polarity": "supports", "claim_strength": 0.6},
        "evidence": {
            "quote": "Participants completed a semantic localizer task (n = 64).",
            "section": "methods",
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
        },
        "method": {
            "sample_size": {"status": "reported", "reported_n": 64, "quote": "n = 64", "section": "methods"},
            "threshold_correction": {"status": "yes", "quote": "FDR correction", "section": "results", "correction_type": "fdr"},
            "operationalization": {"status": "clear", "quote": "semantic localizer task", "section": "methods"},
        },
        "signals": {
            "mention_strength": 0.7,
            "mapping_confidence": 0.86,
            "claim_strength": 0.6,
            "preregistration": "unknown",
            "open_data_or_code": "unknown",
        },
        "prov": {
            "run_id": "accepted-1",
            "prompt_hash": "p1",
            "template_hash": "t1",
            "model": "gemini-2.5-flash",
            "raw_response_path": "/tmp/accepted.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
    }
    (shard_dir / "shard_0000.jsonl").write_text(
        json.dumps(accepted_record) + "\n",
        encoding="utf-8",
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "paths": {"run_dir": "."},
                "ingest": {"review_queue_path": "review_queue.jsonl"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "review_queue.jsonl").write_text("", encoding="utf-8")

    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--max-rejected",
            "0",
            "--max-accepted",
            "10",
        ]
    )

    assert exit_code == 0
    summary = json.loads(
        (output_dir / "balanced_method_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["accepted_controls_total"] == 1
