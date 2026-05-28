from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from brain_researcher.cli.main import app

runner = CliRunner()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _record(paper_id: str, run_id: str) -> dict:
    return {
        "run": {
            "run_id": run_id,
            "tool": "extract",
            "model": "gpt-5",
            "prompt_hash": f"prompt-{run_id}",
            "template_hash": "gabriel-template-v1",
            "raw_response_path": f"/tmp/{run_id}.json",
            "loader_version": "gabriel-loader/v1",
            "timestamp": "2026-02-25T00:00:00Z",
        },
        "paper": {
            "id": paper_id,
            "pmid": paper_id.replace("pmid:", ""),
            "title": "Attention paper",
            "year": 2025,
        },
        "target": {"type": "Concept", "id": "concept:attention", "label": "Attention"},
        "mapping": {
            "canonical_id": "concept:attention",
            "mapping_type": "exact",
            "mapping_confidence": 0.95,
        },
        "claim": {
            "id": f"claim:{run_id}",
            "text": "Attention supports control networks.",
            "polarity": "supports",
            "claim_strength": 0.85,
        },
        "evidence": {
            "quote": "Strong effect after correction.",
            "section": "results",
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
        },
        "signals": {
            "mention_frequency": 5,
            "max_frequency": 5,
            "title_hit": True,
            "abstract_hit": True,
            "semantic_similarity": 0.95,
            "ontology_match": True,
            "context_overlap": 0.80,
            "modal_density": 0.10,
            "statistical_density": 0.90,
            "assertive_verb_ratio": 0.85,
            "preregistration": True,
            "threshold_correction_reported": True,
            "sample_size_adequacy": 0.80,
            "roi_definition_clear": True,
            "open_data_or_code": True,
        },
    }


def test_gabriel_eval_kggen_command_outputs_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "base-run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_path = shard_dir / "shard_0000.jsonl"
    _write_jsonl(shard_path, [_record("pmid:700001", "base-1")])

    manifest_path = run_dir / "manifest.json"
    manifest = {
        "run_id": "base-run",
        "created_at": "2026-02-25T00:00:00Z",
        "paths": {"run_dir": str(run_dir), "manifest_path": str(manifest_path)},
        "counts": {"records_generated": 1, "records_llm": 1, "records_heuristic": 0, "llm_errors": 0},
        "shards": [
            {
                "shard_id": 0,
                "path": str(shard_path),
                "records": 1,
                "errors": 0,
                "ingest": {"status": "pending", "records_ingested": 0},
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    kggen_path = tmp_path / "kggen.jsonl"
    _write_jsonl(
        kggen_path,
        [
            _record("pmid:700001", "kg-1"),
            {
                "paper_id": "pmid:700001",
                "title": "Attention paper",
                "subject": "Attention",
                "predicate": "engages",
                "object": "Frontoparietal network",
                "confidence": 0.9,
                "mention_frequency": 5,
                "max_frequency": 5,
                "title_hit": True,
                "abstract_hit": True,
                "sample_size_adequacy": 0.8,
                "roi_definition_clear": True,
                "threshold_correction_reported": True,
                "evidence_quote": "Results showed increased frontoparietal coupling (p<0.05).",
                "section": "results",
                "has_statistical_detail": True,
            },
        ],
    )

    output_dir = tmp_path / "eval-output"
    result = runner.invoke(
        app,
        [
            "gabriel",
            "eval-kggen",
            "--manifest",
            str(manifest_path),
            "--kggen-input",
            str(kggen_path),
            "--output-dir",
            str(output_dir),
            "--sample-size",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    report_path = output_dir / "report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "gabriel-kggen-eval-v1"
    assert report["coverage"]["new_high_conf_edges"] >= 1


def test_gabriel_map_onvoc_command_outputs_report(tmp_path: Path) -> None:
    kggen_path = tmp_path / "kggen_adapted.jsonl"
    _write_jsonl(kggen_path, [_record("pmid:700002", "kg-map-1")])

    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    crosswalk_path.write_text(
        json.dumps(
            {
                "concepts": {
                    "concept:attention": {
                        "primary": "ONVOC_9990001",
                        "labels": ["Attention"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    tree_path = tmp_path / "onvoc_tree.yaml"
    tree_path.write_text(
        json.dumps(
            {
                "tree": [
                    {
                        "id": "ONVOC_9990001",
                        "uri": "https://w3id.org/onvoc/ONVOC_9990001",
                        "label": "Attention",
                        "level": 3,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "onvoc-output"
    result = runner.invoke(
        app,
        [
            "gabriel",
            "map-onvoc",
            "--kggen-input",
            str(kggen_path),
            "--output-dir",
            str(output_dir),
            "--crosswalk-path",
            str(crosswalk_path),
            "--tree-path",
            str(tree_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    report_path = output_dir / "report_onvoc.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "gabriel-onvoc-map-v1"
    assert report["summary"]["maps_to_edges"] == 1
    assert report["summary"]["same_as_edges"] == 1


def test_gabriel_ingest_help_lists_progress_logging_options() -> None:
    result = runner.invoke(app, ["gabriel", "ingest", "--help"])

    assert result.exit_code == 0
    assert "--progress-log" in result.stdout
    assert "--stall-warn" in result.stdout
    assert "--log-timing" in result.stdout
    assert "--progress-log-l" in result.stdout
