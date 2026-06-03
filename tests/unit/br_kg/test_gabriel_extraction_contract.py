from __future__ import annotations

from pathlib import Path

from brain_researcher.services.br_kg.etl import gabriel_generator as gg
from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (
    compute_gabriel_variables,
)


def test_heuristic_record_demotes_ungrounded_specific_match() -> None:
    generator = gg.GabrielPipelineGenerator(
        output_root=Path("/tmp"),
        cache_dir=Path("/tmp"),
        model_hint="heuristic",
    )
    publication = gg.PublicationSeed(
        paper_id="pmid:1",
        title="Cerebellar changes in NMOSD",
        abstract="The cerebellum’s role in neuromyelitis optica spectrum disorder remains inadequately explored.",
        keywords="attention",
        source="pubget_extracted_data",
    )

    record = generator._heuristic_record(publication)

    assert record["target"]["id"] == "concept:cognitive_control"
    assert record["mapping"]["mapping_confidence"] <= 0.30
    assert record["claim"]["polarity"] == "uncertain"
    assert record["claim"]["claim_strength"] <= 0.35
    assert record["signals"]["grounded_trigger_match"] is False


def test_heuristic_record_prefers_grounded_non_title_quote() -> None:
    generator = gg.GabrielPipelineGenerator(
        output_root=Path("/tmp"),
        cache_dir=Path("/tmp"),
        model_hint="heuristic",
    )
    publication = gg.PublicationSeed(
        paper_id="pmid:2",
        title="Lifespan network analysis",
        abstract="Default mode network connectivity decreased across the lifespan in the cohort.",
        source="pubget_extracted_data",
    )

    record = generator._heuristic_record(publication)

    assert record["target"]["id"] == "concept:default_mode_network"
    assert "default mode network" in record["evidence"]["quote"].lower()
    assert record["evidence"]["section"] == "abstract"
    assert record["signals"]["grounded_trigger_match"] is True


def test_finalize_record_demotes_title_only_when_abstract_available() -> None:
    generator = gg.GabrielPipelineGenerator(
        output_root=Path("/tmp"),
        cache_dir=Path("/tmp"),
        model_hint="heuristic",
    )
    publication = gg.PublicationSeed(
        paper_id="pmid:3",
        title="Levodopa improves response inhibition",
        abstract="Participants showed improved response inhibition after levodopa.",
        source="neo4j",
    )

    finalized = generator._finalize_record(
        publication=publication,
        base_record={
            "target": {
                "type": "Task",
                "id": "task:response_inhibition",
                "label": "response inhibition",
            },
            "mapping": {
                "canonical_id": "task:response_inhibition",
                "mapping_type": "exact",
                "mapping_confidence": 0.95,
            },
            "claim": {
                "text": "Levodopa improves response inhibition",
                "polarity": "supports",
                "claim_strength": 0.95,
            },
            "evidence": {
                "quote": "Levodopa improves response inhibition",
                "section": "title",
                "locatable": True,
                "direct_quote": True,
                "has_statistical_detail": False,
            },
            "signals": {
                "mention_frequency": 1,
                "max_frequency": 1,
                "title_hit": True,
                "abstract_hit": False,
                "semantic_similarity": 0.95,
                "ontology_match": True,
                "context_overlap": 0.95,
                "modal_density": 0.05,
                "statistical_density": 0.05,
                "assertive_verb_ratio": 0.95,
            },
        },
        run_id="run-1",
        raw_response_path="/tmp/raw.json",
        prompt_hash="phash",
        template_hash="thash",
        model_name="gemini-2.5-flash",
        timestamp="2026-03-10T00:00:00Z",
        measurement_index=1,
    )

    assert finalized["mapping"]["mapping_confidence"] <= 0.35
    assert finalized["claim"]["claim_strength"] <= 0.35
    assert finalized["signals"]["title_only_evidence"] is True
    assert finalized["signals"]["section_level_evidence"] is False
    assert finalized["evidence"]["locatable"] is False


def test_compute_gabriel_variables_penalizes_title_only_and_unverifiable_snippet() -> None:
    baseline_record = {
        "run": {
            "run_id": "r0",
            "prompt_hash": "p0",
            "template_hash": "t0",
            "model": "gpt-5",
            "raw_response_path": "/tmp/raw.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-03-10T00:00:00Z",
        },
        "signals": {
            "mention_frequency": 1,
            "max_frequency": 1,
            "title_hit": True,
            "abstract_hit": False,
            "semantic_similarity": 0.95,
            "ontology_match": True,
            "context_overlap": 0.95,
            "modal_density": 0.05,
            "statistical_density": 0.05,
            "assertive_verb_ratio": 0.95,
        },
        "claim": {"polarity": "supports"},
        "evidence": {
            "section": "title",
            "has_statistical_detail": False,
            "locatable": True,
            "direct_quote": True,
        },
    }
    title_only_record = {
        "run": {
            "run_id": "r1",
            "prompt_hash": "p1",
            "template_hash": "t1",
            "model": "gpt-5",
            "raw_response_path": "/tmp/raw.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-03-10T00:00:00Z",
        },
        "signals": {
            "mention_frequency": 1,
            "max_frequency": 1,
            "title_hit": True,
            "abstract_hit": False,
            "semantic_similarity": 0.95,
            "ontology_match": True,
            "context_overlap": 0.95,
            "modal_density": 0.05,
            "statistical_density": 0.05,
            "assertive_verb_ratio": 0.95,
            "title_only_evidence": True,
        },
        "claim": {"polarity": "supports"},
        "evidence": {
            "section": "title",
            "has_statistical_detail": False,
            "locatable": True,
            "direct_quote": True,
        },
    }
    unverifiable_record = {
        "run": {
            "run_id": "r2",
            "prompt_hash": "p2",
            "template_hash": "t2",
            "model": "gpt-5",
            "raw_response_path": "/tmp/raw.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-03-10T00:00:00Z",
        },
        "signals": {
            "mention_frequency": 1,
            "max_frequency": 5,
            "semantic_similarity": 0.22,
            "ontology_match": False,
            "context_overlap": 0.10,
            "modal_density": 0.92,
            "statistical_density": 0.05,
            "assertive_verb_ratio": 0.08,
            "unverifiable_snippet": True,
        },
        "claim": {"polarity": "uncertain"},
        "evidence": {
            "section": "discussion",
            "has_statistical_detail": False,
            "locatable": False,
            "direct_quote": False,
        },
    }

    baseline_variables = compute_gabriel_variables(baseline_record)
    title_only_variables = compute_gabriel_variables(title_only_record)
    unverifiable_variables = compute_gabriel_variables(unverifiable_record)

    assert title_only_variables.evidence_quality == "low"
    assert title_only_variables.mention_strength < baseline_variables.mention_strength
    assert unverifiable_variables.evidence_quality == "low"


def test_prompt_contract_includes_structured_method_block() -> None:
    assert '"method": {' in gg.PROMPT_TEMPLATE
    assert '"preregistration": {' in gg.PROMPT_TEMPLATE
    assert '"threshold_correction": {' in gg.PROMPT_TEMPLATE
    assert '"sample_size": {' in gg.PROMPT_TEMPLATE
    assert '"roi_definition": {' in gg.PROMPT_TEMPLATE
    assert '"open_data_or_code": {' in gg.PROMPT_TEMPLATE
    assert "Do not infer method absence from omission" in gg.PROMPT_TEMPLATE


def test_finalize_record_preserves_method_statuses_without_boolean_collapse() -> None:
    generator = gg.GabrielPipelineGenerator(
        output_root=Path("/tmp"),
        cache_dir=Path("/tmp"),
        model_hint="heuristic",
    )
    publication = gg.PublicationSeed(
        paper_id="pmid:4",
        title="Cognitive control study",
        abstract="Methods: n = 48 participants; FDR correction was applied. Results showed improved control.",
        source="neo4j",
    )

    finalized = generator._finalize_record(
        publication=publication,
        base_record={
            "target": {
                "type": "Concept",
                "id": "concept:cognitive_control",
                "label": "Cognitive Control",
            },
            "mapping": {
                "canonical_id": "concept:cognitive_control",
                "mapping_type": "exact",
                "mapping_confidence": 0.92,
            },
            "claim": {
                "text": "Cognitive control improved",
                "polarity": "supports",
                "claim_strength": 0.72,
            },
            "evidence": {
                "quote": "Results showed improved control.",
                "section": "results",
                "locatable": True,
                "direct_quote": True,
                "has_statistical_detail": False,
            },
            "method": {
                "preregistration": {"status": "unknown"},
                "threshold_correction": {
                    "status": "yes",
                    "quote": "FDR correction was applied.",
                    "section": "methods",
                    "correction_type": "fdr",
                },
                "sample_size": {
                    "status": "reported",
                    "reported_n": 48,
                    "quote": "n = 48 participants",
                    "section": "methods",
                },
                "roi_definition": {"status": "unknown"},
                "open_data_or_code": {"status": "unknown", "artifact": "unknown"},
            },
            "signals": {
                "mention_frequency": 1,
                "max_frequency": 1,
                "title_hit": False,
                "abstract_hit": True,
                "semantic_similarity": 0.92,
                "ontology_match": True,
                "context_overlap": 0.72,
                "modal_density": 0.10,
                "statistical_density": 0.15,
                "assertive_verb_ratio": 0.80,
            },
        },
        run_id="run-2",
        raw_response_path="/tmp/raw.json",
        prompt_hash="phash",
        template_hash="thash",
        model_name="gemini-2.5-flash",
        timestamp="2026-03-13T00:00:00Z",
        measurement_index=1,
    )

    assert finalized["method"]["preregistration"]["status"] == "unknown"
    assert finalized["method"]["threshold_correction"]["status"] == "yes"
    assert finalized["method"]["threshold_correction"]["correction_type"] == "fdr"
    assert finalized["method"]["sample_size"]["status"] == "reported"
    assert finalized["method"]["sample_size"]["reported_n"] == 48
    assert finalized["signals"]["preregistration_status"] == "unknown"
    assert finalized["signals"]["threshold_correction_status"] == "yes"
    assert finalized["signals"]["threshold_correction_type"] == "fdr"
    assert finalized["signals"]["sample_size_status"] == "reported"
    assert finalized["signals"]["sample_size_reported_n"] == 48


def test_method_rigor_uses_sample_size_bands_for_nested_method_blocks() -> None:
    base = {
        "run": {
            "run_id": "r-sample",
            "prompt_hash": "p-sample",
            "template_hash": "t-sample",
            "model": "gpt-5",
            "raw_response_path": "/tmp/raw.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
        "target": {"type": "Task", "id": "task:test", "label": "Test Task"},
        "claim": {"polarity": "supports", "claim_strength": 0.6},
        "evidence": {
            "quote": "Participants completed the task.",
            "section": "abstract",
            "has_statistical_detail": False,
            "locatable": True,
            "direct_quote": True,
        },
        "method": {
            "threshold_correction": {
                "status": "yes",
                "quote": "FDR correction",
                "section": "results",
            },
            "operationalization": {
                "status": "clear",
                "quote": "participants completed the task",
                "section": "methods",
            },
        },
    }

    small = compute_gabriel_variables(
        {
            **base,
            "method": {
                **base["method"],
                "sample_size": {
                    "status": "reported",
                    "reported_n": 25,
                    "quote": "n = 25",
                    "section": "methods",
                },
            },
        }
    )
    large = compute_gabriel_variables(
        {
            **base,
            "method": {
                **base["method"],
                "sample_size": {
                    "status": "reported",
                    "reported_n": 120,
                    "quote": "n = 120",
                    "section": "methods",
                },
            },
        }
    )

    assert large.method_rigor > small.method_rigor


def test_method_rigor_does_not_grant_full_credit_to_status_only_method_blocks() -> None:
    unaudited = compute_gabriel_variables(
        {
            "run": {
                "run_id": "r-unaudited",
                "prompt_hash": "p-unaudited",
                "template_hash": "t-unaudited",
                "model": "gpt-5",
                "raw_response_path": "/tmp/raw.jsonl",
                "loader_version": "v1",
                "timestamp": "2026-03-13T00:00:00Z",
            },
            "target": {"type": "Task", "id": "task:test", "label": "Test Task"},
            "claim": {"polarity": "supports", "claim_strength": 0.6},
            "evidence": {
                "quote": "Participants completed the task.",
                "section": "abstract",
                "has_statistical_detail": False,
                "locatable": True,
                "direct_quote": True,
            },
            "method": {
                "threshold_correction": {"status": "yes"},
                "operationalization": {"status": "clear"},
                "sample_size": {"status": "reported", "reported_n": 64},
            },
        }
    )
    audited = compute_gabriel_variables(
        {
            "run": {
                "run_id": "r-audited",
                "prompt_hash": "p-audited",
                "template_hash": "t-audited",
                "model": "gpt-5",
                "raw_response_path": "/tmp/raw.jsonl",
                "loader_version": "v1",
                "timestamp": "2026-03-13T00:00:00Z",
            },
            "target": {"type": "Task", "id": "task:test", "label": "Test Task"},
            "claim": {"polarity": "supports", "claim_strength": 0.6},
            "evidence": {
                "quote": "Participants completed the task.",
                "section": "abstract",
                "has_statistical_detail": False,
                "locatable": True,
                "direct_quote": True,
            },
            "method": {
                "threshold_correction": {
                    "status": "yes",
                    "quote": "FDR correction",
                    "section": "results",
                },
                "operationalization": {
                    "status": "clear",
                    "quote": "participants completed the task",
                    "section": "methods",
                },
                "sample_size": {
                    "status": "reported",
                    "reported_n": 64,
                    "quote": "n = 64",
                    "section": "methods",
                },
            },
        }
    )

    assert audited.method_rigor > unaudited.method_rigor


def test_method_rigor_uses_method_section_when_claim_evidence_is_only_abstract() -> None:
    variables = compute_gabriel_variables(
        {
            "run": {
                "run_id": "r-method-section",
                "prompt_hash": "p-method-section",
                "template_hash": "t-method-section",
                "model": "gpt-5",
                "raw_response_path": "/tmp/raw.jsonl",
                "loader_version": "v1",
                "timestamp": "2026-03-13T00:00:00Z",
            },
            "target": {
                "type": "Task",
                "id": "task:response_inhibition",
                "label": "Response Inhibition",
            },
            "claim": {"polarity": "supports", "claim_strength": 0.62},
            "evidence": {
                "quote": "This study examines response inhibition.",
                "section": "abstract",
                "has_statistical_detail": False,
                "locatable": True,
                "direct_quote": True,
            },
            "method": {
                "threshold_correction": {
                    "status": "yes",
                    "quote": "cluster-level FWE corrected",
                    "section": "results",
                },
                "sample_size": {
                    "status": "reported",
                    "reported_n": 64,
                    "quote": "n = 64",
                    "section": "methods",
                },
                "operationalization": {
                    "status": "clear",
                    "quote": "participants completed a go/no-go task",
                    "section": "methods",
                },
            },
        }
    )

    assert variables.method_rigor >= 0.35
