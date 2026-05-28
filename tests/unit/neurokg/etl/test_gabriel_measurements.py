from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.neurokg.etl.loaders.gabriel_measurements import (
    DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    GabrielVariables,
    compute_gabriel_variables,
    compute_method_rigor,
    compute_provenance_completeness,
    evaluate_high_precision_gate,
)


def test_compute_gabriel_variables_from_signals() -> None:
    record = {
        "run": {
            "run_id": "r1",
            "prompt_hash": "p1",
            "template_hash": "t1",
            "model": "gpt-5",
            "raw_response_path": "/tmp/raw.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-02-24T00:00:00Z",
        },
        "signals": {
            "mention_frequency": 4,
            "max_frequency": 5,
            "title_hit": True,
            "abstract_hit": True,
            "semantic_similarity": 0.9,
            "ontology_match": True,
            "context_overlap": 0.5,
            "modal_density": 0.1,
            "statistical_density": 0.8,
            "assertive_verb_ratio": 0.7,
            "preregistration": True,
            "threshold_correction_reported": True,
            "sample_size_adequacy": 0.8,
            "roi_definition_clear": True,
            "open_data_or_code": True,
        },
        "claim": {"polarity": "supports"},
        "evidence": {
            "section": "results",
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
        },
    }

    variables = compute_gabriel_variables(record)

    assert isinstance(variables, GabrielVariables)
    assert 0.0 <= variables.mention_strength <= 1.0
    assert 0.0 <= variables.mapping_confidence <= 1.0
    assert 0.0 <= variables.claim_strength <= 1.0
    assert 0.0 <= variables.method_rigor <= 1.0
    assert variables.claim_polarity == "supports"
    assert variables.evidence_quality in {"low", "medium", "high"}
    assert variables.provenance_completeness == 1.0


def test_compute_provenance_completeness_partial() -> None:
    provenance = {
        "run_id": "abc",
        "prompt_hash": "def",
        "template_hash": "ghi",
    }
    score = compute_provenance_completeness(
        provenance,
        required_fields=DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    )
    assert 0.0 < score < 1.0


def test_high_precision_gate_rejects_low_quality() -> None:
    variables = GabrielVariables(
        mention_strength=0.4,
        mapping_confidence=0.3,
        claim_polarity="uncertain",
        claim_strength=0.2,
        evidence_quality="low",
        evidence_quality_score=0.2,
        method_rigor=0.1,
        provenance_completeness=0.5,
    )

    accepted, reasons = evaluate_high_precision_gate(variables)
    assert not accepted
    assert "mention_strength_below_threshold" in reasons
    assert "mapping_confidence_below_threshold" in reasons
    assert "claim_strength_below_threshold" in reasons
    assert "method_rigor_below_threshold" in reasons
    assert "provenance_incomplete" in reasons
    assert "evidence_quality_low" in reasons


def test_negative_control_fixture_can_have_complete_provenance_and_still_fail_gate() -> (
    None
):
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "fixtures/neurokg/gabriel_measurements.sample.jsonl"
    )
    record = json.loads(fixture_path.read_text(encoding="utf-8").splitlines()[2])

    variables = compute_gabriel_variables(record)
    accepted, reasons = evaluate_high_precision_gate(variables)

    assert variables.provenance_completeness == 1.0
    assert not accepted
    assert "provenance_incomplete" not in reasons
    assert "mention_strength_below_threshold" in reasons
    assert "mapping_confidence_below_threshold" in reasons
    assert "claim_strength_below_threshold" in reasons
    assert "method_rigor_below_threshold" in reasons
    assert "evidence_quality_low" in reasons


def test_compute_method_rigor_treats_unknown_flags_more_gently_than_false() -> None:
    base_signals = {
        "type": "Concept",
        "section": "results",
        "quote": "Results showed a robust concept effect.",
        "has_statistical_detail": True,
        "locatable": True,
        "direct_quote": True,
        "sample_size_adequacy": 0.55,
    }

    unknown_score = compute_method_rigor(
        {
            **base_signals,
            "preregistration": "unknown",
            "threshold_correction_reported": "not reported",
            "open_data_or_code": None,
        }
    )
    explicit_false_score = compute_method_rigor(
        {
            **base_signals,
            "preregistration": False,
            "threshold_correction_reported": False,
            "open_data_or_code": False,
        }
    )

    assert unknown_score > explicit_false_score


def test_compute_method_rigor_is_target_aware_for_non_region_claims() -> None:
    base_signals = {
        "section": "results",
        "quote": "Results showed a robust task effect.",
        "has_statistical_detail": True,
        "locatable": True,
        "direct_quote": True,
        "sample_size_adequacy": 0.55,
        "threshold_correction_reported": True,
    }

    concept_score = compute_method_rigor({**base_signals, "type": "Concept"})
    task_score = compute_method_rigor({**base_signals, "type": "Task"})
    region_unknown_score = compute_method_rigor({**base_signals, "type": "Region"})
    region_explicit_score = compute_method_rigor(
        {**base_signals, "type": "Region", "roi_definition_clear": True}
    )

    assert concept_score == task_score
    assert concept_score >= region_unknown_score
    assert region_explicit_score > concept_score


def test_non_region_results_record_can_clear_balanced_marginal_method_gate() -> None:
    record = {
        "run": {
            "run_id": "r-balanced-marginal-concept",
            "prompt_hash": "p-balanced-marginal-concept",
            "template_hash": "t-balanced-marginal-concept",
            "model": "gpt-5",
            "raw_response_path": "/tmp/raw-balanced-marginal-concept.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
        "target": {
            "type": "Concept",
            "id": "concept:reward_processing",
            "label": "Reward Processing",
        },
        "claim": {
            "polarity": "supports",
            "claim_strength": 0.62,
        },
        "evidence": {
            "quote": "Results showed statistically reliable reward-processing effects.",
            "section": "results",
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
        },
        "signals": {
            "mention_strength": 0.62,
            "mapping_confidence": 0.82,
            "claim_strength": 0.62,
            "sample_size_adequacy": 0.45,
            "threshold_correction_reported": "unknown",
            "preregistration": "unknown",
            "open_data_or_code": "unknown",
        },
    }

    variables = compute_gabriel_variables(record)
    accepted, reasons = evaluate_high_precision_gate(
        variables,
        thresholds={
            "mention_strength_min": 0.0,
            "mapping_confidence_min": 0.0,
            "claim_strength_min": 0.0,
            "method_rigor_min": 0.35,
            "provenance_completeness_min": 0.0,
            "allow_low_evidence_quality": True,
        },
    )

    assert variables.method_rigor >= 0.35
    assert accepted
    assert "method_rigor_below_threshold" not in reasons


def test_nested_method_blocks_drive_task_like_rigor() -> None:
    record = {
        "run": {
            "run_id": "r-task-method",
            "prompt_hash": "p-task-method",
            "template_hash": "t-task-method",
            "model": "gpt-5",
            "raw_response_path": "/tmp/raw-task-method.jsonl",
            "loader_version": "v1",
            "timestamp": "2026-03-13T00:00:00Z",
        },
        "target": {
            "type": "Task",
            "id": "task:semantic_localizer",
            "label": "Semantic Localizer",
        },
        "claim": {
            "text": "Participants completed a semantic localizer.",
            "polarity": "supports",
            "claim_strength": 0.58,
        },
        "evidence": {
            "quote": "Participants completed a semantic localizer task (n = 64).",
            "section": "methods",
            "has_statistical_detail": True,
            "locatable": True,
            "direct_quote": True,
        },
        "method": {
            "sample_size": {
                "status": "reported",
                "reported_n": 64,
                "quote": "Participants completed a semantic localizer task (n = 64).",
                "section": "methods",
            },
            "threshold_correction": {
                "status": "yes",
                "quote": "Results survived FDR correction.",
                "section": "results",
                "correction_type": "fdr",
            },
            "operationalization": {
                "status": "clear",
                "quote": "Participants completed a semantic localizer task.",
                "section": "methods",
            },
        },
        "signals": {
            "mention_strength": 0.60,
            "mapping_confidence": 0.86,
            "claim_strength": 0.58,
            "preregistration": "unknown",
            "open_data_or_code": "unknown",
        },
    }

    variables = compute_gabriel_variables(record)
    accepted, reasons = evaluate_high_precision_gate(
        variables,
        thresholds={
            "mention_strength_min": 0.0,
            "mapping_confidence_min": 0.0,
            "claim_strength_min": 0.0,
            "method_rigor_min": 0.35,
            "provenance_completeness_min": 0.0,
            "allow_low_evidence_quality": True,
        },
    )

    assert variables.method_rigor >= 0.35
    assert accepted
    assert "method_rigor_below_threshold" not in reasons
