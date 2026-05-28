"""Unit tests for deterministic novelty-calibration question generation."""

from __future__ import annotations

from brain_researcher.services.agent.novelty_calibration_questions import (
    build_novelty_calibration_context,
    generate_novelty_calibration_questions,
)


def test_novelty_calibration_does_not_match_motion_inside_emotion() -> None:
    context = build_novelty_calibration_context(
        query="Emotion regulation in major depressive disorder",
        candidate_cards=[
            {
                "card_id": "card_01",
                "title": "Bridge to CFS adjacency",
                "hypothesis": "A fatigue-linked subgroup boundary changes regulation failure.",
                "taste_axis": "controlled_ood_search",
                "provenance": {"relation_hint": "ABOUT", "candidate_kg_id": "ONVOC_0000153"},
                "kg_verification": {"verdict": "supported", "evidence_source_scope": "shared"},
            }
        ],
        summary={"n_candidate_cards": 1},
    )

    result = generate_novelty_calibration_questions(context, max_questions=2)

    assert result["novelty_calibration_questions"][0]["problem_target"] == (
        "population_generalization_failure"
    )


def test_novelty_calibration_keeps_explicit_reframe_cards_mechanistic() -> None:
    context = build_novelty_calibration_context(
        query=(
            "Major depressive disorder study testing whether mitochondrial health "
            "influences emotion-regulation brain networks"
        ),
        candidate_cards=[
            {
                "card_id": "card_cfs",
                "title": "Reframe MDD as energy-limited regulation failure with CFS adjacency",
                "hypothesis": (
                    "CFS adjacency suggests energy-limited regulation failure rather than "
                    "static connectivity disorder"
                ),
                "mechanism": "Post-challenge recovery failure in frontolimbic control networks",
                "taste_axis": "controlled_ood_search",
                "provenance": {"relation_hint": "ABOUT", "candidate_kg_id": "ONVOC_0000153"},
                "kg_verification": {"verdict": "supported", "evidence_source_scope": "shared"},
            }
        ],
        summary={"n_candidate_cards": 1},
    )

    result = generate_novelty_calibration_questions(context, max_questions=2)
    first_question = result["novelty_calibration_questions"][0]

    assert first_question["claim_surface"] == "mechanistic_framing"
    assert first_question["precedent_challenge_type"] == "direct_precedent"
    assert "functionally equivalent" in first_question["question"]


def test_novelty_calibration_uses_evidence_summary_in_context() -> None:
    context = build_novelty_calibration_context(
        query="Major depressive disorder study testing whether mitochondrial health influences emotion-regulation brain networks",
        candidate_cards=[
            {
                "card_id": "card_dr",
                "title": "Energy-limited regulation failure",
                "hypothesis": "Post-challenge recovery deficits may organize the disorder.",
                "taste_axis": "controlled_ood_search",
                "evidence_summary": (
                    "Recent literature suggests inflammatory load and bioenergetic stress "
                    "track poorer frontolimbic recovery after affective challenge."
                ),
                "provenance": {
                    "relation_hint": "ABOUT",
                    "candidate_kg_id": "ONVOC_0000153",
                },
                "kg_verification": {
                    "verdict": "supported",
                    "evidence_source_scope": "shared",
                },
            }
        ],
        summary={"n_candidate_cards": 1},
    )

    result = generate_novelty_calibration_questions(context, max_questions=2)
    first_question = result["novelty_calibration_questions"][0]

    assert "Deep research summary:" in first_question["kg_evidence_context"]
    assert "frontolimbic recovery" in first_question["kg_evidence_context"]


def test_novelty_calibration_reads_dr_primary_scope_and_status() -> None:
    context = build_novelty_calibration_context(
        query="MDD study of challenge-recovery dynamics and mitochondrial stress",
        candidate_cards=[
            {
                "card_id": "card_dr_primary",
                "title": "Recovery framing from deep research card",
                "hypothesis": "Challenge-recovery slopes may expose energy-limited regulation failure.",
                "taste_axis": "controlled_ood_search",
                "grounding_status": "grounded",
                "deep_research_status": "ok",
                "evidence_source_scope": "external_literature",
                "provenance": {
                    "supporting_paper_titles": [
                        "Post-challenge recovery in affective networks",
                        "Inflammatory burden and regulation dynamics in MDD",
                    ]
                },
            }
        ],
        summary={"n_candidate_cards": 1, "deep_research_requested": True},
    )

    result = generate_novelty_calibration_questions(context, max_questions=2)
    first_question = result["novelty_calibration_questions"][0]

    assert "evidence scope=external_literature" in first_question["kg_evidence_context"]
    assert "deep_research_status=ok" in first_question["kg_evidence_context"]


def test_novelty_calibration_prioritizes_rank_and_query_relevance_over_input_order() -> None:
    context = build_novelty_calibration_context(
        query=(
            "Major depressive disorder study testing whether mitochondrial health "
            "influences emotion-regulation brain networks"
        ),
        candidate_cards=[
            {
                "card_id": "card_low",
                "rank": 3,
                "query_relevance_score": 0.0,
                "title": "Test energy production: mitochondrial health -> emotion-regulation networks in MDD",
                "hypothesis": "Energy production may mediate the relationship.",
                "taste_axis": "deep_research_mechanism",
                "provenance": {"object_label": "energy production"},
            },
            {
                "card_id": "card_high",
                "rank": 1,
                "query_relevance_score": 0.61,
                "title": "Test mitochondrial protein depletion: mitochondrial health -> emotion-regulation networks in MDD",
                "hypothesis": "Mitochondrial protein depletion may mediate the relationship.",
                "taste_axis": "deep_research_mechanism",
                "provenance": {"object_label": "mitochondrial protein depletion"},
            },
        ],
        summary={"n_candidate_cards": 2},
    )

    result = generate_novelty_calibration_questions(context, max_questions=3)
    first_question = result["novelty_calibration_questions"][0]

    assert first_question["targets_card_id"] == "card_high"
    assert first_question["priority_tier"] == "high"
    assert first_question["priority_score"] > 0.55


def test_novelty_calibration_high_priority_mechanistic_cards_get_stronger_stress_test() -> None:
    context = build_novelty_calibration_context(
        query=(
            "Major depressive disorder study testing whether mitochondrial health "
            "influences emotion-regulation brain networks"
        ),
        candidate_cards=[
            {
                "card_id": "card_mtpd",
                "rank": 1,
                "query_relevance_score": 0.61,
                "title": "Test mitochondrial protein depletion: mitochondrial health -> emotion-regulation networks in MDD",
                "hypothesis": "Mitochondrial protein depletion may mediate the relationship.",
                "taste_axis": "deep_research_mechanism",
                "grounding_status": "grounded",
                "deep_research_status": "ok",
                "evidence_source_scope": "cross_source",
                "provenance": {
                    "object_label": "mitochondrial protein depletion",
                    "supporting_paper_titles": [
                        "Mitochondrial Energy Transformation Capacity Influences Brain Activation",
                    ],
                },
            }
        ],
        summary={"n_candidate_cards": 1, "deep_research_requested": True},
    )

    result = generate_novelty_calibration_questions(context, max_questions=2)
    first_question = result["novelty_calibration_questions"][0]

    assert first_question["precedent_challenge_type"] == "direct_or_near_precedent"
    assert "primary mechanistic mediator" in first_question["question"]
    assert "closest near-precedent" in first_question["question"]
    assert "rank=1" in first_question["kg_evidence_context"]
    assert "query_relevance_score=0.61" in first_question["kg_evidence_context"]
