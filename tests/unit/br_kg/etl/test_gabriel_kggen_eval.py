from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.br_kg.etl.evaluation.gabriel_kggen_eval import (
    evaluate_kggen_coverage,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def _strong_record(
    *,
    run_id: str,
    paper_id: str,
    title: str,
    target_id: str,
    target_label: str,
    claim_text: str,
) -> dict:
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
            "title": title,
            "year": 2025,
            "journal": "NeuroImage",
        },
        "target": {"type": "Concept", "id": target_id, "label": target_label},
        "mapping": {
            "canonical_id": target_id,
            "mapping_type": "exact",
            "mapping_confidence": 0.95,
        },
        "claim": {
            "id": f"claim:{run_id}",
            "text": claim_text,
            "polarity": "supports",
            "claim_strength": 0.85,
        },
        "evidence": {
            "span_id": f"evidence:{run_id}",
            "quote": "Results showed robust effects after FWE correction.",
            "section": "results",
            "page": 4,
            "char_start": 120,
            "char_end": 188,
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


def _build_manifest(run_dir: Path, shard_path: Path) -> Path:
    manifest_path = run_dir / "manifest.json"
    manifest = {
        "run_id": "baseline-run",
        "created_at": "2026-02-25T00:00:00Z",
        "paths": {
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
        },
        "counts": {
            "records_generated": 1,
            "records_llm": 1,
            "records_heuristic": 0,
            "llm_errors": 0,
        },
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
    return manifest_path


def test_evaluate_kggen_reports_new_high_conf_edges(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "baseline-run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    baseline_record = _strong_record(
        run_id="base-1",
        paper_id="pmid:500001",
        title="Working memory network study",
        target_id="concept:working_memory",
        target_label="Working Memory",
        claim_text="Working memory recruits prefrontal cortex.",
    )
    shard_path = shard_dir / "shard_0000.jsonl"
    _write_jsonl(shard_path, [baseline_record])
    manifest_path = _build_manifest(run_dir, shard_path)

    kggen_overlap = _strong_record(
        run_id="kg-1",
        paper_id="pmid:500001",
        title="Working memory network study",
        target_id="concept:working_memory",
        target_label="Working Memory",
        claim_text="Working memory recruits prefrontal cortex.",
    )
    kggen_relation = {
        "paper_id": "pmid:500001",
        "title": "Working memory network study",
        "subject": "Working memory",
        "predicate": "engages",
        "object": "Dorsolateral prefrontal cortex",
        "confidence": 0.93,
        "mention_frequency": 5,
        "max_frequency": 5,
        "title_hit": True,
        "abstract_hit": True,
        "context_overlap": 0.8,
        "modal_density": 0.1,
        "statistical_density": 0.85,
        "assertive_verb_ratio": 0.8,
        "sample_size_adequacy": 0.8,
        "roi_definition_clear": True,
        "evidence_quote": "Results showed a robust frontoparietal effect (p < 0.01).",
        "section": "results",
        "has_statistical_detail": True,
    }
    kggen_path = tmp_path / "kggen.jsonl"
    _write_jsonl(kggen_path, [kggen_overlap, kggen_relation])

    output_dir = tmp_path / "eval-output"
    report = evaluate_kggen_coverage(
        kggen_input=kggen_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        sample_size=1,
        seed=7,
        quality_profile="balanced",
        strict_provenance=True,
    )

    assert report["coverage"]["baseline_high_conf_edges"] == 1
    assert report["coverage"]["kggen_high_conf_edges"] == 2
    assert report["coverage"]["new_high_conf_edges"] == 1
    assert report["kggen"]["parse_errors"] == 0
    assert Path(report["artifacts"]["report_path"]).exists()
    assert Path(report["artifacts"]["review_queue_path"]).exists()
    assert Path(report["artifacts"]["kggen_adapted_path"]).exists()


def test_evaluate_kggen_tracks_parse_and_adapter_errors(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "baseline-run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    baseline_record = _strong_record(
        run_id="base-2",
        paper_id="pmid:500002",
        title="Attention control",
        target_id="concept:attention",
        target_label="Attention",
        claim_text="Attention improves control network activation.",
    )
    shard_path = shard_dir / "shard_0000.jsonl"
    _write_jsonl(shard_path, [baseline_record])
    manifest_path = _build_manifest(run_dir, shard_path)

    kggen_path = tmp_path / "kggen_bad.jsonl"
    kggen_path.write_text(
        "\n".join(
            [
                '{"paper":{"id":"pmid:500002","title":"Attention control"},"target":{"type":"Concept","id":"concept:attention","label":"Attention"},"claim":{"text":"Attention improves control network activation.","polarity":"supports"},"evidence":{"quote":"Strong effect.","section":"results","locatable":true,"direct_quote":true},"run":{"run_id":"kg-ok","tool":"kggen","model":"m","prompt_hash":"h1","template_hash":"h2","raw_response_path":"x","loader_version":"v","timestamp":"2026-02-25T00:00:00Z"}}',
                '{"foo":"bar"}',
                '{"bad_json":',
            ]
        ),
        encoding="utf-8",
    )

    report = evaluate_kggen_coverage(
        kggen_input=kggen_path,
        output_dir=tmp_path / "eval-output",
        manifest_path=manifest_path,
        sample_size=1,
        seed=11,
        quality_profile="balanced",
        strict_provenance=True,
    )

    assert report["kggen"]["parse_errors"] >= 2
    assert report["coverage"]["baseline_high_conf_edges"] == 1
    assert report["coverage"]["kggen_high_conf_edges"] == 0


def test_evaluate_kggen_rejects_weak_relation_defaults(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "baseline-run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    baseline_record = _strong_record(
        run_id="base-3",
        paper_id="pmid:500003",
        title="Control network study",
        target_id="concept:cognitive_control",
        target_label="Cognitive Control",
        claim_text="Cognitive control recruits frontoparietal networks.",
    )
    shard_path = shard_dir / "shard_0000.jsonl"
    _write_jsonl(shard_path, [baseline_record])
    manifest_path = _build_manifest(run_dir, shard_path)

    kggen_path = tmp_path / "kggen_weak.jsonl"
    _write_jsonl(
        kggen_path,
        [
            {
                "paper_id": "pmid:500003",
                "title": "Control network study",
                "subject": "control process",
                "predicate": "related_to",
                "object": "network dynamics",
            }
        ],
    )

    report = evaluate_kggen_coverage(
        kggen_input=kggen_path,
        output_dir=tmp_path / "eval-output",
        manifest_path=manifest_path,
        sample_size=1,
        seed=23,
        quality_profile="balanced",
        strict_provenance=True,
    )

    assert report["coverage"]["baseline_high_conf_edges"] == 1
    assert report["coverage"]["kggen_high_conf_edges"] == 0
    assert report["kggen"]["records_accepted"] == 0
    assert report["kggen"]["records_rejected"] == 1


def test_evaluate_kggen_infers_nonconstant_method_rigor_for_task_panel_rows(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "baseline-run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    baseline_record = _strong_record(
        run_id="base-4",
        paper_id="pmid:500004",
        title="Task panel synthesis study",
        target_id="concept:working_memory",
        target_label="Working Memory",
        claim_text="Working memory recruits frontoparietal cortex.",
    )
    shard_path = shard_dir / "shard_0000.jsonl"
    _write_jsonl(shard_path, [baseline_record])
    manifest_path = _build_manifest(run_dir, shard_path)

    kggen_path = tmp_path / "kggen_task_panel.jsonl"
    _write_jsonl(
        kggen_path,
        [
            {
                "paper_id": "pmid:500004",
                "title": "Task panel synthesis study",
                "subject": "working memory load",
                "predicate": "engages",
                "object": "dorsolateral prefrontal cortex",
                "confidence": 0.86,
                "mention_frequency": 4,
                "max_frequency": 5,
                "title_hit": True,
                "abstract_hit": True,
                "context_overlap": 0.80,
                "modal_density": 0.25,
                "statistical_density": 0.62,
                "assertive_verb_ratio": 0.72,
                "sample_size_adequacy": 0.62,
                "section": "abstract",
                "evidence_quote": "Working memory load engaged dorsolateral prefrontal cortex.",
                "has_statistical_detail": True,
            },
            {
                "paper_id": "pmid:500004",
                "title": "Task panel synthesis study",
                "subject": "cognitive process",
                "predicate": "related_to",
                "object": "network dynamics",
                "confidence": 0.82,
                "mention_frequency": 4,
                "max_frequency": 5,
                "title_hit": True,
                "abstract_hit": True,
                "context_overlap": 0.72,
                "modal_density": 0.45,
                "statistical_density": 0.40,
                "assertive_verb_ratio": 0.55,
                "sample_size_adequacy": 0.50,
                "section": "abstract",
                "evidence_quote": "The process was related to network dynamics.",
                "has_statistical_detail": False,
            },
        ],
    )

    report = evaluate_kggen_coverage(
        kggen_input=kggen_path,
        output_dir=tmp_path / "eval-output",
        manifest_path=manifest_path,
        sample_size=1,
        seed=31,
        quality_profile="balanced",
        strict_provenance=True,
    )

    adapted = _read_jsonl(Path(report["artifacts"]["kggen_adapted_path"]))
    rigor_scores = [row.get("signals", {}).get("method_rigor") for row in adapted]
    rigor_values = [float(score) for score in rigor_scores if score is not None]

    assert len(rigor_values) == 2
    assert len({round(score, 3) for score in rigor_values}) == 2
    assert max(rigor_values) >= 0.40
    assert min(rigor_values) < 0.40
    assert report["kggen"]["records_accepted"] == 1
    assert report["kggen"]["records_rejected"] == 1
