from __future__ import annotations

import csv
import json
from pathlib import Path

from brain_researcher.services.agent.router import LLMChatResult, LLMRouteMetadata
from brain_researcher.services.neurokg.etl import gabriel_generator as gg


def test_generate_writes_shards_and_manifest(monkeypatch, tmp_path: Path) -> None:
    seeds = [
        gg.PublicationSeed(
            paper_id="pmid:101",
            pmid="101",
            title="Working memory and dlPFC",
            abstract="We found significant dlPFC effects in working memory.",
            year=2025,
            journal="NeuroImage",
            source="neo4j",
        ),
        gg.PublicationSeed(
            paper_id="pmid:102",
            pmid="102",
            title="Attention and frontoparietal control",
            abstract="Attention effects were reported in frontoparietal cortex.",
            year=2024,
            journal="HBM",
            source="neo4j",
        ),
    ]

    def fake_load_publications(*, limit: int, offset: int, use_cache_fallback: bool):
        del limit, offset, use_cache_fallback
        return seeds, {"source": "neo4j", "count": len(seeds)}

    generator = gg.GabrielPipelineGenerator(
        output_root=tmp_path,
        cache_dir=tmp_path / "cache",
        model_hint="heuristic",
        max_records_per_publication=1,
    )
    monkeypatch.setattr(generator, "_load_publications", fake_load_publications)

    manifest = generator.generate(
        limit=2,
        offset=0,
        shard_size=1,
        run_id="unit-run",
        use_cache_fallback=False,
        force_heuristic=True,
    )

    manifest_path = Path(manifest["paths"]["manifest_path"])
    assert manifest_path.exists()
    assert manifest["counts"]["publications_selected"] == 2
    assert manifest["counts"]["records_generated"] == 2
    assert manifest["counts"]["shards"] == 2

    status = gg.load_manifest_status(manifest_path)
    assert status["summary"]["shards_total"] == 2
    assert status["summary"]["records_expected"] == 2
    assert status["summary"]["records_on_disk"] == 2


def test_ingest_uses_balanced_profile_and_updates_manifest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "unit-run"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_one = (shard_dir / "shard_0000.jsonl").resolve()
    shard_two = (shard_dir / "shard_0001.jsonl").resolve()
    shard_one.write_text("{}\n", encoding="utf-8")
    shard_two.write_text("{}\n", encoding="utf-8")

    manifest_path = run_dir / "manifest.json"
    manifest = {
        "run_id": "unit-run",
        "created_at": "2026-02-24T00:00:00Z",
        "paths": {
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
        },
        "counts": {
            "records_generated": 2,
            "records_llm": 0,
            "records_heuristic": 2,
            "llm_errors": 0,
        },
        "shards": [
            {
                "shard_id": 0,
                "path": str(shard_one),
                "records": 1,
                "errors": 0,
                "ingest": {"status": "pending", "records_ingested": 0},
            },
            {
                "shard_id": 1,
                "path": str(shard_two),
                "records": 1,
                "errors": 0,
                "ingest": {"status": "pending", "records_ingested": 0},
            },
        ],
        "ingest": {
            "status": "not_started",
            "started_at": None,
            "completed_at": None,
            "records_ingested": 0,
            "shards_completed": 0,
            "shards_failed": 0,
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class DummyDB:
        def close(self) -> None:
            return

    class FakeLoader:
        captured_config: dict | None = None

        def __init__(self, db, config):
            del db
            FakeLoader.captured_config = dict(config)

        def load(self, mode: str = "spine"):
            del mode
            config = FakeLoader.captured_config or {}
            input_paths = [str(Path(p).resolve()) for p in config.get("input_paths", [])]
            checkpoint_path = Path(config["ingest_checkpoint_path"])
            files_payload = {}
            per_file = {}
            for input_path in input_paths:
                files_payload[input_path] = {
                    "input_path": input_path,
                    "status": "completed",
                    "started_at": "2026-02-24T00:00:00Z",
                    "finished_at": "2026-02-24T00:01:00Z",
                    "stats": {"records_total": 1, "records_accepted": 1},
                }
                per_file[input_path] = {
                    "records_total": 1,
                    "records_parsed": 1,
                    "records_accepted": 1,
                    "records_rejected": 0,
                    "review_queue_items": 0,
                    "nodes_created": 5,
                    "relationships_created": 5,
                    "parse_errors": 0,
                }
            checkpoint_path.write_text(
                json.dumps({"files": files_payload}),
                encoding="utf-8",
            )
            return {
                "per_file": per_file,
                "records_total": len(per_file),
                "records_parsed": len(per_file),
                "records_accepted": len(per_file),
                "records_rejected": 0,
                "review_queue_items": 0,
                "nodes_created": 5 * len(per_file),
                "relationships_created": 5 * len(per_file),
                "parse_errors": 0,
            }

    monkeypatch.setattr(gg, "require_neo4j_db", lambda preload_cache=False: DummyDB())
    monkeypatch.setattr(gg, "GabrielMeasurementLoader", FakeLoader)

    generator = gg.GabrielPipelineGenerator(output_root=tmp_path, cache_dir=tmp_path / "cache")
    result = generator.ingest(
        manifest_path=manifest_path,
        mode="spine",
        resume=True,
        quality_profile="balanced",
    )

    assert result["status"] == "completed"
    assert result["quality_profile"] == "balanced"
    assert result["shards_completed"] == 2
    assert result["records_ingested"] == 2
    assert FakeLoader.captured_config is not None
    assert FakeLoader.captured_config["quality_profile"] == "balanced"
    assert "candidate_only_review_queue_path" in FakeLoader.captured_config

    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest["ingest"]["status"] == "completed"
    assert updated_manifest["ingest"]["quality_profile"] == "balanced"
    assert updated_manifest["ingest"]["candidate_only_review_queue_path"].endswith(
        "review_queue_candidate_only.jsonl"
    )
    for shard in updated_manifest["shards"]:
        assert shard["ingest"]["status"] == "completed"
        assert shard["ingest"]["records_ingested"] == 1


def test_ingest_rejects_exact_id_migration_only_manifest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "concept-reroute"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_path = (shard_dir / "shard_0000.jsonl").resolve()
    shard_path.write_text("{}\n", encoding="utf-8")

    manifest_path = run_dir / "manifest_task_panel.json"
    manifest = {
        "run_id": "concept-reroute",
        "created_at": "2026-03-13T00:00:00Z",
        "source": "kggen_onvoc_postprocess",
        "source_details": {
            "promotion_strategy": "exact_id_migration_only",
            "reroute_target_type": "Concept",
            "reroute_target_id": "concept:feature_processing",
        },
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
                "ingest": {"status": "not_started", "records_ingested": 0},
            }
        ],
        "ingest": {
            "status": "not_started",
            "started_at": None,
            "completed_at": None,
            "records_ingested": 0,
            "shards_completed": 0,
            "shards_failed": 0,
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loader_called = {"value": False}

    class FakeLoader:
        def __init__(self, db, config):
            del db, config
            loader_called["value"] = True

        def load(self, mode: str = "spine"):
            del mode
            return {}

    monkeypatch.setattr(gg, "GabrielMeasurementLoader", FakeLoader)
    monkeypatch.setattr(gg, "require_neo4j_db", lambda preload_cache=False: None)

    generator = gg.GabrielPipelineGenerator(
        output_root=tmp_path, cache_dir=tmp_path / "cache"
    )
    try:
        generator.ingest(
            manifest_path=manifest_path,
            mode="spine",
            resume=True,
            quality_profile="kg_task_panel",
        )
    except RuntimeError as exc:
        assert "promotion_strategy=exact_id_migration_only" in str(exc)
        assert "--exact-prefix concept:" in str(exc)
    else:
        raise AssertionError("Expected concept reroute manifest ingest to be rejected")

    assert loader_called["value"] is False


def test_parse_json_payload_salvages_fenced_trailing_commas(tmp_path: Path) -> None:
    generator = gg.GabrielPipelineGenerator(output_root=tmp_path, cache_dir=tmp_path / "cache")
    response_text = """
Here is the JSON:
```json
{
  "records": [
    {
      "target": {"type": "Concept", "label": "Working Memory"},
      "claim": {"text": "Supports working memory signal", "polarity": "supports", "claim_strength": 0.8},
      "evidence": {"quote": "Results showed WM effect", "section": "results", "locatable": true,},
      "mapping": {"canonical_id": "concept:working_memory", "mapping_type": "exact", "mapping_confidence": 0.9}
    }
  ],
}
```
"""
    payload = generator._parse_json_payload(response_text)
    assert isinstance(payload, dict)
    assert payload["records"][0]["target"]["label"] == "Working Memory"


def test_generate_tracks_llm_failure_reasons(monkeypatch, tmp_path: Path) -> None:
    seeds = [
        gg.PublicationSeed(
            paper_id="pmid:201",
            pmid="201",
            title="Conflict monitoring and ACC",
            abstract="Results discuss conflict monitoring and ACC activity.",
            year=2025,
            journal="NeuroImage",
            source="neo4j",
        )
    ]

    def fake_load_publications(*, limit: int, offset: int, use_cache_fallback: bool):
        del limit, offset, use_cache_fallback
        return seeds, {"source": "neo4j", "count": len(seeds)}

    generator = gg.GabrielPipelineGenerator(
        output_root=tmp_path,
        cache_dir=tmp_path / "cache",
        model_hint="gemini-2.5-flash",
        max_records_per_publication=1,
    )
    monkeypatch.setattr(generator, "_load_publications", fake_load_publications)

    call_counter = {"count": 0}

    def fake_route_chat(*, prompt: str, model_hint: str | None, strict_json: bool):
        del prompt, model_hint, strict_json
        call_counter["count"] += 1
        return LLMChatResult(
            text='{"records": []}',
            metadata=LLMRouteMetadata(
                provider="google",
                model="gemini-2.5-flash",
                route="primary",
                transport="cli",
            ),
        )

    monkeypatch.setattr(generator.router, "route_chat", fake_route_chat)

    manifest = generator.generate(
        limit=1,
        offset=0,
        shard_size=1,
        run_id="unit-failure-reasons",
        use_cache_fallback=False,
        force_heuristic=False,
    )
    manifest_path = Path(manifest["paths"]["manifest_path"])

    assert call_counter["count"] == 2  # Gemini path retries once for zero-record JSON.
    assert manifest["counts"]["records_generated"] == 1
    assert manifest["counts"]["records_llm"] == 0
    assert manifest["counts"]["records_heuristic"] == 1
    assert manifest["counts"]["llm_errors"] == 1
    assert manifest["counts"]["llm_failure_reasons"]["zero_records"] == 1

    raw_dir = Path(manifest["shards"][0]["raw_dir"])
    raw_files = sorted(raw_dir.glob("pub_*.json"))
    assert len(raw_files) == 1
    raw_payload = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert raw_payload["mode"] == "heuristic"
    assert raw_payload["failure_reason"] == "zero_records"

    status = gg.load_manifest_status(manifest_path)
    assert status["summary"]["llm_failure_reasons"]["zero_records"] == 1


def test_generate_from_pubget_extracted_data(monkeypatch, tmp_path: Path) -> None:
    extracted_dir = tmp_path / "subset_allArticles_extractedData"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    metadata_csv = extracted_dir / "metadata.csv"
    with metadata_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "pmcid",
                "pmid",
                "doi",
                "title",
                "journal",
                "publication_year",
                "license",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "pmcid": "PMC1001",
                "pmid": "500001",
                "doi": "10.1000/alpha",
                "title": "Pubget WM paper",
                "journal": "NeuroImage",
                "publication_year": "2024",
                "license": "CC-BY",
            }
        )
        writer.writerow(
            {
                "pmcid": "PMC1002",
                "pmid": "",
                "doi": "",
                "title": "Pubget PMCID-only paper",
                "journal": "HBM",
                "publication_year": "2023",
                "license": "CC-BY",
            }
        )

    text_csv = extracted_dir / "text.csv"
    with text_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["pmcid", "title", "keywords", "abstract", "body"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "pmcid": "PMC1001",
                "title": "Pubget WM paper",
                "keywords": "working memory; n-back",
                "abstract": "Working memory recruited dorsolateral prefrontal cortex.",
                "body": "Results: n-back showed strong dlPFC activity at p < 0.05 FWE.",
            }
        )
        writer.writerow(
            {
                "pmcid": "PMC1002",
                "title": "Pubget PMCID-only paper",
                "keywords": "emotion regulation",
                "abstract": "Emotion regulation effects were observed in amygdala.",
                "body": "Methods and results section text.",
            }
        )

    generator = gg.GabrielPipelineGenerator(
        output_root=tmp_path,
        cache_dir=tmp_path / "cache",
        model_hint="heuristic",
        max_records_per_publication=1,
    )
    monkeypatch.setattr(generator.router, "route_chat", lambda **kwargs: None)

    manifest = generator.generate(
        limit=0,
        offset=0,
        shard_size=2,
        run_id="unit-pubget-run",
        pubget_extracted_dir=extracted_dir,
        pubget_include_body=True,
        pubget_body_char_limit=500,
        force_heuristic=True,
    )

    assert manifest["source"] == "pubget_extracted_data"
    source_details = manifest["source_details"]
    assert source_details["records_unique_publications"] == 2
    assert source_details["records_text_rows"] == 2
    assert source_details["include_body"] is True

    shard_path = Path(manifest["shards"][0]["path"])
    rows = [
        json.loads(line)
        for line in shard_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    paper_ids = {row["paper"]["id"] for row in rows}
    # Prefer pmid when available; fallback to pmcid when pmid/doi absent.
    assert "pmid:500001" in paper_ids
    assert "pmcid:1002" in paper_ids


def test_heuristic_record_emits_structured_method_block(tmp_path: Path) -> None:
    generator = gg.GabrielPipelineGenerator(output_root=tmp_path, cache_dir=tmp_path / "cache")
    record = generator._heuristic_record(
        gg.PublicationSeed(
            paper_id="pmid:777",
            pmid="777",
            title="Semantic localizer study",
            abstract=(
                "We preregistered the study. In 64 participants, semantic localizer "
                "contrast showed effects surviving FDR correction."
            ),
            body="Code available on GitHub.",
            year=2025,
            journal="NeuroImage",
            source="neo4j",
        )
    )

    method = record["method"]
    assert method["sample_size"]["status"] == "reported"
    assert method["sample_size"]["reported_n"] == 64
    assert method["threshold_correction"]["status"] == "yes"
    assert method["preregistration"]["status"] == "yes"
    assert "operationalization" in method


def test_finalize_record_preserves_unknown_method_fields_without_forcing_false(
    tmp_path: Path,
) -> None:
    generator = gg.GabrielPipelineGenerator(output_root=tmp_path, cache_dir=tmp_path / "cache")
    publication = gg.PublicationSeed(
        paper_id="pmid:778",
        pmid="778",
        title="Task study",
        abstract="A semantic localizer was used.",
        year=2025,
        journal="HBM",
        source="neo4j",
    )
    record = generator._finalize_record(
        publication=publication,
        base_record={
            "target": {"type": "Task", "label": "Semantic Localizer", "id": "task:semantic_localizer"},
            "mapping": {"canonical_id": "task:semantic_localizer", "mapping_type": "exact", "mapping_confidence": 0.9},
            "claim": {"text": "Semantic localizer engaged the language system.", "polarity": "supports", "claim_strength": 0.7},
            "evidence": {"quote": "A semantic localizer was used.", "section": "abstract", "locatable": True, "direct_quote": True, "has_statistical_detail": False},
            "method": {
                "operationalization": {"status": "clear", "quote": "A semantic localizer was used.", "section": "abstract"},
                "preregistration": {"status": "unknown", "quote": None, "section": "unknown"},
            },
            "signals": {"mention_frequency": 1, "max_frequency": 5},
        },
        run_id="unit-method-finalize",
        raw_response_path=str(tmp_path / "raw.json"),
        prompt_hash="p",
        template_hash="t",
        model_name="gemini-2.5-flash",
        timestamp="2026-03-13T00:00:00Z",
        measurement_index=0,
    )

    assert record["method"]["operationalization"]["status"] == "clear"
    assert record["signals"]["operationalization_status"] == "clear"
    assert record["signals"]["preregistration"] is None


def test_ingest_candidate_only_uses_loader_and_updates_manifest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "candidate-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    queue_path = run_dir / "review_queue_candidate_only.jsonl"
    queue_path.write_text("{}\n", encoding="utf-8")

    manifest_path = run_dir / "manifest.json"
    manifest = {
        "run_id": "candidate-run",
        "created_at": "2026-03-13T00:00:00Z",
        "paths": {
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
        },
        "counts": {"records_generated": 1},
        "shards": [],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class DummyDB:
        def close(self) -> None:
            return

    class FakeLoader:
        captured_config: dict | None = None
        captured_queue_paths: list[str] | None = None
        captured_quality_profile: str | None = None

        def __init__(self, db, config):
            del db
            FakeLoader.captured_config = dict(config)

        def load_candidate_only_queue(
            self,
            *,
            queue_paths,
            source_quality_profile,
            mode="spine",
        ):
            del mode
            FakeLoader.captured_queue_paths = [
                str(Path(path).resolve()) for path in queue_paths
            ]
            FakeLoader.captured_quality_profile = source_quality_profile
            return {
                "files_processed": 1,
                "files_failed": 0,
                "queue_rows_total": 1,
                "queue_rows_loaded": 1,
                "queue_rows_skipped": 0,
                "nodes_created": 4,
                "relationships_created": 5,
                "parse_errors": 0,
                "queue_paths": FakeLoader.captured_queue_paths,
            }

    monkeypatch.setattr(gg, "require_neo4j_db", lambda preload_cache=False: DummyDB())
    monkeypatch.setattr(gg, "GabrielMeasurementLoader", FakeLoader)

    generator = gg.GabrielPipelineGenerator(
        output_root=tmp_path,
        cache_dir=tmp_path / "cache",
    )
    result = generator.ingest_candidate_only(
        manifest_path=manifest_path,
        source_quality_profile="balanced_marginal",
    )

    assert result["queue_path"] == str(queue_path.resolve())
    assert result["source_quality_profile"] == "balanced_marginal"
    assert result["stats"]["queue_rows_loaded"] == 1
    assert FakeLoader.captured_config is not None
    assert (
        FakeLoader.captured_config["candidate_only_review_queue_path"]
        == str(queue_path.resolve())
    )
    assert FakeLoader.captured_queue_paths == [str(queue_path.resolve())]
    assert FakeLoader.captured_quality_profile == "balanced_marginal"

    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest["candidate_lane_ingest"]["queue_path"] == str(
        queue_path.resolve()
    )
    assert updated_manifest["candidate_lane_ingest"]["stats"]["queue_rows_loaded"] == 1


def test_ingest_candidate_only_queue_path_overrides_manifest(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "review_queue_candidate_only.jsonl"
    queue_path.write_text("{}\n", encoding="utf-8")

    class DummyDB:
        def close(self) -> None:
            return

    class FakeLoader:
        def __init__(self, db, config):
            del db
            self.config = dict(config)

        def load_candidate_only_queue(
            self,
            *,
            queue_paths,
            source_quality_profile,
            mode="spine",
        ):
            del source_quality_profile, mode
            return {
                "files_processed": 1,
                "files_failed": 0,
                "queue_rows_total": 1,
                "queue_rows_loaded": 1,
                "queue_rows_skipped": 0,
                "overlay_conflicts": 0,
                "nodes_created": 1,
                "relationships_created": 1,
                "parse_errors": 0,
                "queue_paths": [str(Path(path).resolve()) for path in queue_paths],
            }

    monkeypatch.setattr(gg, "require_neo4j_db", lambda preload_cache=False: DummyDB())
    monkeypatch.setattr(gg, "GabrielMeasurementLoader", FakeLoader)

    generator = gg.GabrielPipelineGenerator(
        output_root=tmp_path,
        cache_dir=tmp_path / "cache",
    )
    result = generator.ingest_candidate_only(
        manifest_path=tmp_path / "missing-manifest.json",
        queue_path=queue_path,
    )

    assert result["queue_path"] == str(queue_path.resolve())
    assert "manifest_path" not in result
    assert result["status"] == "completed"


def test_ingest_candidate_only_marks_failed_manifest_when_loader_reports_failed_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "candidate-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    queue_path = run_dir / "review_queue_candidate_only.jsonl"
    queue_path.write_text("{}\n", encoding="utf-8")

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "paths": {
                    "run_dir": str(run_dir),
                    "manifest_path": str(manifest_path),
                }
            }
        ),
        encoding="utf-8",
    )

    class DummyDB:
        def close(self) -> None:
            return

    class FakeLoader:
        def __init__(self, db, config):
            del db, config

        def load_candidate_only_queue(
            self,
            *,
            queue_paths,
            source_quality_profile,
            mode="spine",
        ):
            del queue_paths, source_quality_profile, mode
            return {
                "files_processed": 0,
                "files_failed": 1,
                "queue_rows_total": 1,
                "queue_rows_loaded": 0,
                "queue_rows_skipped": 1,
                "overlay_conflicts": 0,
                "nodes_created": 0,
                "relationships_created": 0,
                "parse_errors": 0,
                "queue_paths": [str(queue_path.resolve())],
            }

    monkeypatch.setattr(gg, "require_neo4j_db", lambda preload_cache=False: DummyDB())
    monkeypatch.setattr(gg, "GabrielMeasurementLoader", FakeLoader)

    generator = gg.GabrielPipelineGenerator(
        output_root=tmp_path,
        cache_dir=tmp_path / "cache",
    )
    result = generator.ingest_candidate_only(manifest_path=manifest_path)

    assert result["status"] == "failed"
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest["candidate_lane_ingest"]["status"] == "failed"
