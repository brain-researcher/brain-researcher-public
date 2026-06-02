from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (
    GabrielVariables,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB


def test_review_only_overrides_reject_title_only_low_rigor() -> None:
    reasons = GabrielMeasurementLoader._apply_review_only_overrides(
        record={
            "evidence": {"section": "title"},
            "signals": {"title_only_evidence": True},
        },
        variables=GabrielVariables(
            mention_strength=0.8,
            mapping_confidence=0.9,
            claim_polarity="supports",
            claim_strength=0.9,
            evidence_quality="low",
            evidence_quality_score=0.25,
            method_rigor=0.0,
            provenance_completeness=1.0,
        ),
        reasons=[],
        quality_profile="kg_bootstrap",
    )

    assert "title_only_low_rigor_evidence" in reasons
    assert "benchmark_title_only_suppressed" not in reasons


def test_review_only_overrides_suppress_title_only_in_benchmark_profiles() -> None:
    reasons = GabrielMeasurementLoader._apply_review_only_overrides(
        record={
            "evidence": {"section": "title"},
            "signals": {"title_only_evidence": True},
        },
        variables=GabrielVariables(
            mention_strength=0.8,
            mapping_confidence=0.95,
            claim_polarity="supports",
            claim_strength=0.9,
            evidence_quality="medium",
            evidence_quality_score=0.45,
            method_rigor=0.2,
            provenance_completeness=1.0,
        ),
        reasons=[],
        quality_profile="balanced_marginal",
    )

    assert "benchmark_title_only_suppressed" in reasons
    assert "title_only_low_rigor_evidence" not in reasons


def test_review_only_overrides_marks_generic_title_concepts_for_candidate_only_lane() -> (
    None
):
    reasons = GabrielMeasurementLoader._apply_review_only_overrides(
        record={
            "evidence": {"section": "title"},
            "signals": {"title_only_evidence": True},
            "target": {"type": "Concept", "id": "concept:fmri", "label": "fMRI"},
        },
        variables=GabrielVariables(
            mention_strength=0.8,
            mapping_confidence=0.95,
            claim_polarity="supports",
            claim_strength=0.9,
            evidence_quality="medium",
            evidence_quality_score=0.45,
            method_rigor=0.2,
            provenance_completeness=1.0,
        ),
        reasons=[],
        quality_profile="balanced_marginal",
    )
    routing = GabrielMeasurementLoader._determine_review_routing(
        {
            "evidence": {"section": "title"},
            "signals": {"title_only_evidence": True},
            "target": {"type": "Concept", "id": "concept:fmri", "label": "fMRI"},
        },
        reasons,
        quality_profile="balanced_marginal",
    )

    assert "candidate_only_title_generic_reroute" in reasons
    assert routing is not None
    assert routing["lane"] == "candidate_only"
    assert routing["bucket"] == "title_only_generic_concept"


def test_review_only_overrides_marks_expanded_generic_concept_ids_for_candidate_only_lane() -> (
    None
):
    record = {
        "evidence": {"section": "title"},
        "signals": {"title_only_evidence": True},
        "target": {
            "type": "Concept",
            "id": "concept:neural_activation",
            "label": "Neural Activation",
        },
    }
    variables = GabrielVariables(
        mention_strength=0.8,
        mapping_confidence=0.95,
        claim_polarity="supports",
        claim_strength=0.9,
        evidence_quality="medium",
        evidence_quality_score=0.45,
        method_rigor=0.2,
        provenance_completeness=1.0,
    )
    reasons = GabrielMeasurementLoader._apply_review_only_overrides(
        record,
        variables,
        [],
        quality_profile="balanced_marginal",
    )
    routing = GabrielMeasurementLoader._determine_review_routing(
        record,
        reasons,
        quality_profile="balanced_marginal",
    )

    assert "candidate_only_title_generic_reroute" in reasons
    assert routing is not None
    assert routing["lane"] == "candidate_only"


def test_review_only_overrides_does_not_route_region_title_rows_to_candidate_only_lane() -> (
    None
):
    reasons = GabrielMeasurementLoader._apply_review_only_overrides(
        record={
            "evidence": {"section": "title"},
            "signals": {"title_only_evidence": True},
            "target": {
                "type": "Region",
                "id": "region:left_inferior_frontal_gyrus",
                "label": "left inferior frontal gyrus",
            },
        },
        variables=GabrielVariables(
            mention_strength=0.8,
            mapping_confidence=0.95,
            claim_polarity="supports",
            claim_strength=0.9,
            evidence_quality="medium",
            evidence_quality_score=0.45,
            method_rigor=0.2,
            provenance_completeness=1.0,
        ),
        reasons=[],
        quality_profile="balanced_marginal",
    )
    routing = GabrielMeasurementLoader._determine_review_routing(
        {
            "evidence": {"section": "title"},
            "signals": {"title_only_evidence": True},
            "target": {
                "type": "Region",
                "id": "region:left_inferior_frontal_gyrus",
                "label": "left inferior frontal gyrus",
            },
        },
        reasons,
        quality_profile="balanced_marginal",
    )

    assert "candidate_only_title_generic_reroute" not in reasons
    assert routing is None


def test_review_only_overrides_reject_unverifiable_snippet() -> None:
    reasons = GabrielMeasurementLoader._apply_review_only_overrides(
        record={
            "evidence": {"section": "discussion"},
            "signals": {"unverifiable_snippet": True},
        },
        variables=GabrielVariables(
            mention_strength=0.2,
            mapping_confidence=0.1,
            claim_polarity="uncertain",
            claim_strength=0.1,
            evidence_quality="low",
            evidence_quality_score=0.10,
            method_rigor=0.0,
            provenance_completeness=1.0,
        ),
        reasons=["evidence_quality_low"],
        quality_profile="balanced_marginal",
    )

    assert "evidence_quality_low" in reasons
    assert "unverifiable_snippet" in reasons


def test_queue_for_review_writes_candidate_only_rows_to_separate_queue(
    tmp_path: Path,
) -> None:
    review_queue = tmp_path / "review_queue.jsonl"
    loader = GabrielMeasurementLoader(
        db=None,
        config={"review_queue_path": str(review_queue)},
    )
    record = {
        "evidence": {"section": "title"},
        "signals": {"title_only_evidence": True},
        "target": {"type": "Concept", "id": "concept:fmri", "label": "fMRI"},
    }
    variables = GabrielVariables(
        mention_strength=0.8,
        mapping_confidence=0.95,
        claim_polarity="supports",
        claim_strength=0.9,
        evidence_quality="medium",
        evidence_quality_score=0.45,
        method_rigor=0.2,
        provenance_completeness=1.0,
    )
    reasons = GabrielMeasurementLoader._apply_review_only_overrides(
        record,
        variables,
        [],
        quality_profile="balanced_marginal",
    )
    routing = GabrielMeasurementLoader._determine_review_routing(
        record,
        reasons,
        quality_profile="balanced_marginal",
    )

    loader._queue_for_review(record, variables, reasons, routing=routing)

    candidate_only_path = tmp_path / "review_queue_candidate_only.jsonl"
    assert candidate_only_path.exists()
    assert not review_queue.exists()
    payload = json.loads(candidate_only_path.read_text(encoding="utf-8").strip())
    assert payload["routing"]["lane"] == "candidate_only"
    assert payload["routing"]["bucket"] == "title_only_generic_concept"


def test_load_candidate_only_queue_materializes_candidate_lane_metadata(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "review_queue_candidate_only.jsonl"
    queue_path.write_text(
        json.dumps(
            {
                "queued_at": "2026-03-13T23:00:00+00:00",
                "reasons": [
                    "benchmark_title_only_suppressed",
                    "candidate_only_title_generic_reroute",
                ],
                "variables": {
                    "mention_strength": 0.1,
                    "mapping_confidence": 0.2,
                    "claim_polarity": "uncertain",
                    "claim_strength": 0.3,
                    "evidence_quality": "title_only_hold",
                    "evidence_quality_score": 0.0,
                    "method_rigor": 0.0,
                    "provenance_completeness": 1.0,
                },
                "record": {
                    "paper": {"id": "pmid:101", "title": "Generic fMRI study"},
                    "claim": {"id": "claim:test-candidate", "text": "Candidate claim"},
                    "target": {
                        "type": "Concept",
                        "id": "concept:fmri",
                        "label": "fMRI",
                    },
                    "evidence": {
                        "span_id": "evidence:test-candidate",
                        "section": "title",
                        "quote": "Generic fMRI study",
                    },
                    "run": {"run_id": "candidate-run-101", "tool": "extract"},
                    "source_review_bucket": "generic_title_hold",
                    "source_bucket_reason": "broad_generic_concept",
                },
                "routing": {
                    "lane": "candidate_only",
                    "bucket": "title_only_generic_concept",
                    "policy": "do_not_promote_to_benchmark",
                    "trigger_reason": "candidate_only_title_generic_reroute",
                    "target_id": "concept:fmri",
                    "target_label": "fMRI",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    db = FakeGraphDB()
    loader = GabrielMeasurementLoader(db=db, config={})
    result = loader.load_candidate_only_queue(
        queue_paths=[queue_path],
        source_quality_profile="balanced_marginal",
    )

    assert result["queue_rows_loaded"] == 1
    claim = db.get_node("claim:test-candidate")
    assert claim is not None
    assert claim["candidate_lane_present"] is True
    assert claim["candidate_lane_source_quality_profile"] == "balanced_marginal"
    assert claim["candidate_lane_bucket"] == "title_only_generic_concept"

    evidence = db.get_node("evidence:test-candidate")
    assert evidence is not None
    assert evidence["candidate_lane_trigger_reason"] == (
        "candidate_only_title_generic_reroute"
    )

    rels = db.find_relationships(
        start_node="pmid:101",
        end_node="concept:fmri",
        rel_type="MENTIONS",
    )
    assert rels
    assert rels[0][2]["candidate_lane_present"] is True


def test_load_candidate_only_queue_skips_non_candidate_rows(tmp_path: Path) -> None:
    queue_path = tmp_path / "review_queue_candidate_only.jsonl"
    queue_path.write_text(
        json.dumps(
            {
                "reasons": ["benchmark_title_only_suppressed"],
                "variables": {
                    "mention_strength": 0.1,
                    "mapping_confidence": 0.2,
                    "claim_polarity": "uncertain",
                    "claim_strength": 0.3,
                    "evidence_quality": "title_only_hold",
                    "evidence_quality_score": 0.0,
                    "method_rigor": 0.0,
                    "provenance_completeness": 1.0,
                },
                "record": {
                    "paper": {"id": "pmid:102", "title": "Task title"},
                    "claim": {"id": "claim:skip-me"},
                    "target": {
                        "type": "Task",
                        "id": "task:go_nogo",
                        "label": "Go/NoGo",
                    },
                    "evidence": {"span_id": "evidence:skip-me", "section": "title"},
                    "run": {"run_id": "candidate-run-102"},
                },
                "routing": {"lane": "benchmark"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    db = FakeGraphDB()
    loader = GabrielMeasurementLoader(db=db, config={})
    result = loader.load_candidate_only_queue(queue_paths=[queue_path])

    assert result["queue_rows_loaded"] == 0
    assert result["queue_rows_skipped"] == 1
    assert db.get_node("claim:skip-me") is None


def test_load_candidate_only_queue_skips_overlay_conflicts(tmp_path: Path) -> None:
    queue_path = tmp_path / "review_queue_candidate_only.jsonl"
    queue_path.write_text(
        json.dumps(
            {
                "reasons": ["candidate_only_title_generic_reroute"],
                "variables": {
                    "mention_strength": 0.1,
                    "mapping_confidence": 0.2,
                    "claim_polarity": "uncertain",
                    "claim_strength": 0.3,
                    "evidence_quality": "title_only_hold",
                    "evidence_quality_score": 0.0,
                    "method_rigor": 0.0,
                    "provenance_completeness": 1.0,
                },
                "record": {
                    "paper": {"id": "pmid:200", "title": "Benchmark title"},
                    "claim": {"id": "claim:existing", "text": "Benchmark claim"},
                    "target": {
                        "type": "Concept",
                        "id": "concept:existing",
                        "label": "Existing Concept",
                    },
                    "evidence": {
                        "span_id": "evidence:existing",
                        "section": "title",
                        "quote": "Benchmark title",
                    },
                    "run": {"run_id": "candidate-run-200", "tool": "extract"},
                },
                "routing": {
                    "lane": "candidate_only",
                    "bucket": "title_only_generic_concept",
                    "policy": "do_not_promote_to_benchmark",
                    "trigger_reason": "candidate_only_title_generic_reroute",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    db = FakeGraphDB()
    db.create_node("Publication", {"title": "Benchmark title"}, node_id="pmid:200")
    db.create_node(
        "Concept",
        {"label": "Existing Concept"},
        node_id="concept:existing",
    )
    db.create_node(
        "Claim",
        {"text": "Benchmark claim"},
        node_id="claim:existing",
    )
    db.create_relationship(
        "pmid:200",
        "concept:existing",
        "MENTIONS",
        {"source": "gabriel"},
    )

    loader = GabrielMeasurementLoader(db=db, config={})
    result = loader.load_candidate_only_queue(queue_paths=[queue_path])

    assert result["queue_rows_loaded"] == 0
    assert result["queue_rows_skipped"] == 1
    assert result["overlay_conflicts"] == 1
    claim = db.get_node("claim:existing")
    assert claim is not None
    assert claim.get("candidate_lane_present") is None


def test_load_candidate_only_queue_requires_explicit_candidate_lane(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "review_queue_candidate_only.jsonl"
    queue_path.write_text(
        json.dumps(
            {
                "record": {
                    "paper": {"id": "pmid:300", "title": "Missing routing"},
                    "claim": {"id": "claim:missing-lane"},
                    "target": {
                        "type": "Task",
                        "id": "task:go_nogo",
                        "label": "Go/NoGo",
                    },
                    "evidence": {
                        "span_id": "evidence:missing-lane",
                        "section": "title",
                    },
                    "run": {"run_id": "candidate-run-300"},
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    db = FakeGraphDB()
    loader = GabrielMeasurementLoader(db=db, config={})
    result = loader.load_candidate_only_queue(queue_paths=[queue_path])

    assert result["queue_rows_loaded"] == 0
    assert result["queue_rows_skipped"] == 1
    assert db.get_node("claim:missing-lane") is None
