"""Unit tests for hypothesis candidate card gap classification."""

from __future__ import annotations

from brain_researcher.services.agent import (
    hypothesis_candidate_cards as candidate_cards_module,
)
from brain_researcher.services.agent.hypothesis_candidate_cards import (
    build_candidate_cards_from_workflow_result,
    rewrite_candidate_cards,
)


def _build_workflow_result(
    *,
    relation_hint: str,
    kg_verification: dict[str, object],
    verify_summary: dict[str, object] | None = None,
    hypotheses: list[dict[str, object]] | None = None,
    tested_hypotheses: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    hypothesis_rows = hypotheses or [
        {
            "rank": 1,
            "seed_kg_id": "node:seed",
            "candidate_kg_id": "node:candidate",
            "statement": "Seed node may couple with candidate node.",
            "relation_hint": relation_hint,
            "novelty_score": 0.72,
            "ood_score": 0.88,
        }
    ]
    tested_rows = tested_hypotheses or [
        {
            "rank": row.get("rank", idx),
            "candidate_kg_id": row.get("candidate_kg_id"),
            "statement": row.get("statement"),
            "entity_hints_used": ["node:seed", row.get("candidate_kg_id", "")],
            "kg_verification": kg_verification,
        }
        for idx, row in enumerate(hypothesis_rows, start=1)
    ]
    return {
        "workflow": "workflow_hypothesis_candidate_cards",
        "steps": {
            "leverage": {
                "data": {
                    "result": {
                        "items": [
                            {
                                "kg_id": "node:candidate",
                                "label": "Candidate Node",
                                "leverage_score": 0.88,
                            }
                        ]
                    },
                    "resolved_seed_kg_ids": ["node:seed"],
                }
            },
            "ood_sampling": {"data": {"result": {"hypotheses": hypothesis_rows}}},
            "verify_sampled_hypotheses": {
                "data": {
                    "result": {
                        "candidate_lane_mode": "strict",
                        "summary": dict(verify_summary or {}),
                        "tested_hypotheses": tested_rows,
                    }
                }
            },
            "contradiction_scan": {"data": {"result": {}}},
            "topology_shift_scan": {"data": {"result": {}}},
            "principle_state_update": {"data": {"result": {}}},
        },
    }


def test_candidate_card_gap_classification_skips_supported_hypotheses():
    workflow_result = _build_workflow_result(
        relation_hint="RELATED_TO",
        kg_verification={
            "verdict": "supported",
            "confidence": 0.81,
            "evidence_source_scope": "direct",
            "summary": {"n_supporting": 1},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Candidate node may dissociate attention control from matched "
                    "control trials."
                ),
                "mechanism": (
                    "Candidate node should support active maintenance of the control "
                    "set rather than passive conflict readout."
                ),
                "prediction": (
                    "The Candidate Node-linked signal should increase during attention "
                    "control trials relative to matched controls."
                ),
                "relation_hint": "RELATED_TO",
                "claim_type": "mechanism",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="attention control",
        top_n=1,
    )

    assert len(cards) == 1
    card = cards[0]
    assert card["gap_type"] is None
    assert card["gap_specification"] is None
    assert card["gap_actionable"] is False
    assert card["provenance"]["sampled_hypothesis_verification"]["gap_type"] is None


def test_candidate_card_gap_classification_marks_generic_bridges_as_ontology_gap():
    workflow_result = _build_workflow_result(
        relation_hint="RELATED_TO",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.18,
            "evidence_source_scope": "none",
            "summary": {
                "n_supporting": 0,
                "n_conflicting": 0,
                "candidate_lane_filtered": 0,
            },
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Candidate node may organize attention control under the anchored "
                    "contrast."
                ),
                "mechanism": (
                    "Candidate node may gate the control-state update that stabilizes "
                    "attention control across matched contrasts."
                ),
                "prediction": (
                    "The Candidate Node-linked signal should rise selectively during "
                    "attention control relative to matched controls."
                ),
                "relation_hint": "RELATED_TO",
                "claim_type": "mechanism",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="attention control",
        top_n=1,
    )

    card = cards[0]
    assert card["gap_type"] == "ontology"
    assert "typed only as 'RELATED_TO'" in card["gap_specification"]
    assert card["gap_actionable"] is False
    assert (
        card["provenance"]["sampled_hypothesis_verification"]["gap_type"] == "ontology"
    )


def test_candidate_card_gap_classification_marks_filtered_rows_as_evidence_gap():
    workflow_result = _build_workflow_result(
        relation_hint="ASSOCIATED_WITH",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.22,
            "evidence_source_scope": "none",
            "summary": {"n_supporting": 0, "n_conflicting": 0},
        },
        verify_summary={"candidate_lane_filtered": 2},
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Candidate node may stabilize attention control when the matched "
                    "control condition is held constant."
                ),
                "mechanism": (
                    "Candidate node may maintain the active task set needed for "
                    "attention control."
                ),
                "prediction": (
                    "The Candidate Node-linked signal should remain elevated during "
                    "attention control relative to matched controls."
                ),
                "relation_hint": "ASSOCIATED_WITH",
                "claim_type": "mechanism",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="attention control",
        top_n=1,
    )

    card = cards[0]
    assert card["gap_type"] == "evidence"
    assert "suppressed 2 candidate-lane evidence rows" in card["gap_specification"]
    assert card["gap_actionable"] is True
    assert (
        card["provenance"]["sampled_hypothesis_verification"]["gap_type"] == "evidence"
    )


def test_candidate_card_gap_classification_marks_method_gaps_when_no_callable_tool_exists(
    monkeypatch,
):
    monkeypatch.setattr(
        candidate_cards_module,
        "_probe_method_tool_support",
        lambda goal: {
            "goal": goal,
            "match_count": 2,
            "total": 2,
            "callable_count": 0,
            "callable_tool_names": [],
        },
    )
    workflow_result = _build_workflow_result(
        relation_hint="ASSOCIATED_WITH",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.19,
            "evidence_source_scope": "none",
            "summary": {"n_supporting": 0, "n_conflicting": 0},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:method",
                "statement": "Preprocess signals with the candidate workflow.",
                "relation_hint": "ASSOCIATED_WITH",
                "novelty_score": 0.71,
                "ood_score": 0.77,
            }
        ],
        tested_hypotheses=[
            {
                "rank": 1,
                "candidate_kg_id": "node:method",
                "statement": "Preprocess signals with the candidate workflow.",
                "entity_hints_used": ["node:seed", "node:method"],
                "kg_verification": {
                    "verdict": "insufficient_evidence",
                    "confidence": 0.19,
                    "evidence_source_scope": "none",
                    "summary": {"n_supporting": 0, "n_conflicting": 0},
                },
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="preprocess signals",
        top_n=1,
    )

    card = cards[0]
    assert card["gap_type"] == "method"
    assert card["gap_actionable"] is True
    assert "callable tool" in card["gap_specification"]
    assert card["provenance"]["sampled_hypothesis_verification"]["gap_type"] == "method"


def test_candidate_card_gap_classification_marks_data_gaps_when_dataset_search_is_empty(
    monkeypatch,
):
    monkeypatch.setattr(
        candidate_cards_module,
        "_probe_dataset_support",
        lambda **kwargs: {
            "text": kwargs.get("text"),
            "anchor_kg_id": kwargs.get("anchor_kg_id"),
            "candidate_kg_id": kwargs.get("candidate_kg_id"),
            "related_dataset_counts": {"anchor": 0, "candidate": 0},
            "search_count": 0,
        },
    )
    workflow_result = _build_workflow_result(
        relation_hint="ASSOCIATED_WITH",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.17,
            "evidence_source_scope": "none",
            "summary": {"n_supporting": 0, "n_conflicting": 0},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:data",
                "statement": "Use the dataset-backed fMRI cohort to test the candidate.",
                "relation_hint": "ASSOCIATED_WITH",
                "novelty_score": 0.69,
                "ood_score": 0.74,
            }
        ],
        tested_hypotheses=[
            {
                "rank": 1,
                "candidate_kg_id": "node:data",
                "statement": "Use the dataset-backed fMRI cohort to test the candidate.",
                "entity_hints_used": ["node:seed", "node:data"],
                "kg_verification": {
                    "verdict": "insufficient_evidence",
                    "confidence": 0.17,
                    "evidence_source_scope": "none",
                    "summary": {"n_supporting": 0, "n_conflicting": 0},
                },
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="dataset-backed fMRI cohort",
        top_n=1,
    )

    card = cards[0]
    assert card["gap_type"] == "data"
    assert card["gap_actionable"] is True
    assert "dataset-backed test" in card["gap_specification"]
    assert card["provenance"]["sampled_hypothesis_verification"]["gap_type"] == "data"


def test_candidate_card_reranks_method_gap_ahead_of_ontology_gap(monkeypatch):
    monkeypatch.setattr(
        candidate_cards_module,
        "_probe_method_tool_support",
        lambda goal: {
            "goal": goal,
            "match_count": 1,
            "total": 1,
            "callable_count": 0,
            "callable_tool_names": [],
        },
    )
    workflow_result = _build_workflow_result(
        relation_hint="RELATED_TO",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.14,
            "evidence_source_scope": "none",
            "summary": {"n_supporting": 0, "n_conflicting": 0},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:ontology",
                "statement": (
                    "The candidate workflow may improve preprocess signals under the "
                    "anchored preprocessing contrast."
                ),
                "mechanism": (
                    "The candidate workflow may reduce alignment noise during "
                    "preprocess signals."
                ),
                "prediction": (
                    "The candidate workflow should yield more stable preprocessing "
                    "estimates than the matched control workflow."
                ),
                "relation_hint": "RELATED_TO",
                "claim_type": "mechanism",
                "novelty_score": 0.8,
                "ood_score": 0.9,
            },
            {
                "rank": 2,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:method",
                "statement": (
                    "Preprocess signals with the candidate workflow to test the "
                    "anchored preprocessing hypothesis."
                ),
                "mechanism": (
                    "The candidate workflow may remove preprocessing artifacts before "
                    "model fitting."
                ),
                "prediction": (
                    "The candidate workflow should improve preprocess signals relative "
                    "to the matched baseline pipeline."
                ),
                "relation_hint": "ASSOCIATED_WITH",
                "claim_type": "mechanism",
                "novelty_score": 0.7,
                "ood_score": 0.85,
            },
        ],
        tested_hypotheses=[
            {
                "rank": 1,
                "candidate_kg_id": "node:ontology",
                "statement": (
                    "The candidate workflow may improve preprocess signals under the "
                    "anchored preprocessing contrast."
                ),
                "entity_hints_used": ["node:seed", "node:ontology"],
                "kg_verification": {
                    "verdict": "insufficient_evidence",
                    "confidence": 0.14,
                    "evidence_source_scope": "none",
                    "summary": {"n_supporting": 0, "n_conflicting": 0},
                },
            },
            {
                "rank": 2,
                "candidate_kg_id": "node:method",
                "statement": (
                    "Preprocess signals with the candidate workflow to test the "
                    "anchored preprocessing hypothesis."
                ),
                "entity_hints_used": ["node:seed", "node:method"],
                "kg_verification": {
                    "verdict": "insufficient_evidence",
                    "confidence": 0.14,
                    "evidence_source_scope": "none",
                    "summary": {"n_supporting": 0, "n_conflicting": 0},
                },
            },
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="preprocess signals",
        top_n=2,
    )

    assert [card["gap_type"] for card in cards] == ["method", "ontology"]


def test_candidate_card_builder_drops_low_confidence_insufficient_evidence_cards():
    workflow_result = _build_workflow_result(
        relation_hint="ASSOCIATED_WITH",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.03,
            "evidence_source_scope": "expanded_family",
            "summary": {
                "n_supporting": 41,
                "n_conflicting": 37,
                "n_external_literature_supporting": 0,
            },
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Candidate node may carry information required for the decoding "
                    "effect, rather than reflecting a passive correlate."
                ),
                "relation_hint": "ASSOCIATED_WITH",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="fmri based image decoding",
        top_n=1,
    )

    assert cards == []


def test_candidate_card_builder_drops_net_negative_cards():
    workflow_result = _build_workflow_result(
        relation_hint="ASSOCIATED_WITH",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.45,
            "evidence_source_scope": "direct",
            "summary": {
                "n_supporting": 2,
                "n_conflicting": 50,
                "n_external_literature_supporting": 0,
            },
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Candidate node should show stronger conflict-related activation "
                    "than matched controls under the anchored manipulation."
                ),
                "relation_hint": "ASSOCIATED_WITH",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="conflict monitoring",
        top_n=1,
    )

    assert cards == []


def test_candidate_card_builder_emits_structured_hypothesis_fields_for_supported_cards():
    workflow_result = _build_workflow_result(
        relation_hint="MAPS_TO",
        kg_verification={
            "verdict": "supported",
            "confidence": 0.81,
            "evidence_source_scope": "direct",
            "summary": {"n_supporting": 3, "n_conflicting": 0},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Candidate node may isolate a cleaner operational variant because "
                    "it sharpens the task-switching maintenance process."
                ),
                "relation_hint": "MAPS_TO",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="task switching",
        top_n=1,
    )

    assert len(cards) == 1
    card = cards[0]
    assert card["quality_bucket"] == "actual_idea_like"
    assert card["rewrite_status"] == "rewritten"
    assert card["independent_variable"]
    assert card["dependent_variable"]
    assert card["predicted_direction"]
    assert "Independent variable:" in card["hypothesis"]
    assert "Dependent variable:" in card["hypothesis"]
    assert "Prediction:" in card["hypothesis"]
    assert "Mechanism:" in card["hypothesis"]


def test_candidate_card_builder_drops_supported_generic_transfer_templates():
    workflow_result = _build_workflow_result(
        relation_hint="BELONGS_TO_FAMILY",
        kg_verification={
            "verdict": "supported",
            "confidence": 0.83,
            "evidence_source_scope": "direct",
            "summary": {"n_supporting": 4, "n_conflicting": 0},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Representations supporting decoding in Task Switching may partially "
                    "transfer to Working Memory because both depend on a shared "
                    "task-family demand profile."
                ),
                "mechanism": (
                    "The proposed mechanism is a shared task-family demand profile "
                    "linking Task Switching to Working Memory."
                ),
                "prediction": (
                    "A decoder trained around Task Switching should generalize above "
                    "matched controls when evaluated on Working Memory."
                ),
                "relation_hint": "BELONGS_TO_FAMILY",
                "claim_type": "transfer",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="task switching",
        top_n=1,
    )

    assert cards == []


def test_rewrite_candidate_cards_revalidates_prefilled_unstructured_cards():
    cards = rewrite_candidate_cards(
        [
            {
                "card_id": "cand_01",
                "title": "Working Memory hypothesis candidate",
                "hypothesis": (
                    "Effects may transfer above matched controls to Working Memory."
                ),
                "idea": "Test whether Working Memory provides a tighter handle.",
                "mechanism": "Shared task-family demand profile.",
                "quality_bucket": "actual_idea_like",
                "rewrite_status": "rewritten",
                "semantic_fidelity_flags": [],
                "provenance": {"relation_hint": "BELONGS_TO_FAMILY"},
                "kg_verification": {
                    "verdict": "supported",
                    "confidence": 0.8,
                    "summary": {"n_supporting": 2, "n_conflicting": 0},
                },
            }
        ],
        query="task switching",
    )

    assert cards == []


def test_candidate_card_builder_uses_claim_memory_for_conflict_resolution_guidance():
    workflow_result = _build_workflow_result(
        relation_hint="ASSOCIATED_WITH",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.22,
            "evidence_source_scope": "none",
            "summary": {"n_supporting": 0, "n_conflicting": 0},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:candidate",
                "statement": (
                    "Candidate node may stabilize spatial navigation under the "
                    "anchored contrast."
                ),
                "mechanism": (
                    "Candidate node may preserve route-state maintenance during "
                    "navigation updates."
                ),
                "prediction": (
                    "The Candidate Node-linked signal should remain elevated during "
                    "spatial navigation relative to matched controls."
                ),
                "relation_hint": "ASSOCIATED_WITH",
                "claim_type": "mechanism",
                "novelty_score": 0.72,
                "ood_score": 0.88,
                "derived_memory": {
                    "claim_memory": {
                        "count": 1,
                        "cards": [
                            {
                                "claim_text": (
                                    "Navigation effects diverge across preprocessing "
                                    "choices."
                                ),
                                "analytic_conditions": ["with GSR", "without GSR"],
                                "canonical_claim_id": "canonical_claim:navigation_gsr",
                                "canonical_target_id": "task:navigation|effect|preprocessing:gsr",
                            }
                        ],
                        "conflicting_claims": [
                            {"claim_text": "Navigation effects diverge."}
                        ],
                        "summary": {
                            "n_conflicting": 1,
                            "n_claim_families": 1,
                            "n_target_families": 1,
                        },
                        "claim_family_summary": {
                            "n_claim_families": 1,
                            "n_target_families": 1,
                            "claim_families": [
                                {
                                    "canonical_claim_id": "canonical_claim:navigation_gsr",
                                    "canonical_target_id": "task:navigation|effect|preprocessing:gsr",
                                    "n_cards": 1,
                                }
                            ],
                            "target_families": [
                                {
                                    "canonical_target_id": "task:navigation|effect|preprocessing:gsr",
                                    "n_cards": 1,
                                }
                            ],
                            "dominant_claim_family": {
                                "canonical_claim_id": "canonical_claim:navigation_gsr",
                                "canonical_target_id": "task:navigation|effect|preprocessing:gsr",
                                "n_cards": 1,
                            },
                            "dominant_target_family": {
                                "canonical_target_id": "task:navigation|effect|preprocessing:gsr",
                                "n_cards": 1,
                            },
                        },
                    }
                },
            }
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="spatial navigation",
        top_n=1,
    )

    assert len(cards) == 1
    card = cards[0]
    assert card["claim_memory_profile"]["n_conflicting"] == 1
    assert card["claim_memory_profile"]["n_claim_families"] == 1
    assert card["claim_memory_profile"]["canonical_claim_ids"] == [
        "canonical_claim:navigation_gsr"
    ]
    assert "conflicting prior claim" in card["claim_memory_summary"]
    assert "1 canonical claim family" in card["claim_memory_summary"]
    assert "with GSR" in card["claim_memory_resolution_hint"]
    assert "resolve the prior conflicting claims" in card["minimal_discriminating_test"]
    assert "conflict remains unexplained" in card["falsifier_hint"]
    assert card["claim_family_summary"]["n_claim_families"] == 1
    assert (
        card["provenance"]["claim_family_summary"]["dominant_claim_family"][
            "canonical_claim_id"
        ]
        == "canonical_claim:navigation_gsr"
    )
    assert (
        "Prior run-derived claim memory already records conflicting experience"
        in (card["gap_specification"])
    )


def test_candidate_card_builder_reranks_conflict_resolution_cards_ahead_of_plain_cards():
    workflow_result = _build_workflow_result(
        relation_hint="ASSOCIATED_WITH",
        kg_verification={
            "verdict": "insufficient_evidence",
            "confidence": 0.22,
            "evidence_source_scope": "none",
            "summary": {"n_supporting": 0, "n_conflicting": 0},
        },
        hypotheses=[
            {
                "rank": 1,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:plain",
                "statement": "Plain candidate may support navigation control.",
                "mechanism": "Plain candidate may support route-state maintenance.",
                "prediction": (
                    "The plain candidate-linked signal should increase relative to "
                    "matched controls."
                ),
                "relation_hint": "ASSOCIATED_WITH",
                "claim_type": "mechanism",
                "novelty_score": 0.72,
                "ood_score": 0.88,
            },
            {
                "rank": 2,
                "seed_kg_id": "node:seed",
                "candidate_kg_id": "node:conflict",
                "statement": "Conflict candidate may support navigation control.",
                "mechanism": "Conflict candidate may support route-state maintenance.",
                "prediction": (
                    "The conflict candidate-linked signal should increase relative to "
                    "matched controls."
                ),
                "relation_hint": "ASSOCIATED_WITH",
                "claim_type": "mechanism",
                "novelty_score": 0.72,
                "ood_score": 0.88,
                "derived_memory": {
                    "claim_memory": {
                        "count": 1,
                        "cards": [{"claim_text": "Prior navigation claims conflict."}],
                        "conflicting_claims": [
                            {"claim_text": "Prior navigation claims conflict."}
                        ],
                        "summary": {"n_conflicting": 1},
                    }
                },
            },
        ],
        tested_hypotheses=[
            {
                "rank": 1,
                "candidate_kg_id": "node:plain",
                "statement": "Plain candidate may support navigation control.",
                "entity_hints_used": ["node:seed", "node:plain"],
                "kg_verification": {
                    "verdict": "insufficient_evidence",
                    "confidence": 0.22,
                    "evidence_source_scope": "none",
                    "summary": {"n_supporting": 0, "n_conflicting": 0},
                },
            },
            {
                "rank": 2,
                "candidate_kg_id": "node:conflict",
                "statement": "Conflict candidate may support navigation control.",
                "entity_hints_used": ["node:seed", "node:conflict"],
                "kg_verification": {
                    "verdict": "insufficient_evidence",
                    "confidence": 0.22,
                    "evidence_source_scope": "none",
                    "summary": {"n_supporting": 0, "n_conflicting": 0},
                },
            },
        ],
    )

    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="navigation control",
        top_n=2,
    )

    assert len(cards) == 2
    assert cards[0]["provenance"]["candidate_kg_id"] == "node:conflict"
    assert cards[0]["claim_memory_profile"]["n_conflicting"] == 1


# ---------------------------------------------------------------------------
# Novelty pre-filter (M2)
# ---------------------------------------------------------------------------


class _FakeMemoryStore:
    """Minimal memory store stub for novelty pre-filter tests.

    call_responses is a list of card-lists returned in round-robin order
    (one per search() call, wrapping around).
    """

    def __init__(self, call_responses: list | None = None):
        self._responses = call_responses or []
        self._call_count = 0

    def search(self, query="", *, card_type=None, filters=None, limit=5):
        if card_type != "claim_memory" or not self._responses:
            return {"ok": True, "cards": []}
        cards = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return {"ok": True, "cards": cards}


def _make_claim_card_dict(*, n_supporting: int = 0, n_conflicting: int = 0, claim_text: str = "x") -> dict:
    return {
        "claim_text": claim_text,
        "confidence": "preliminary",
        "status": "active",
        "supporting_evidence": [{"run_id": f"s{i}"} for i in range(n_supporting)],
        "conflicting_evidence": [{"run_id": f"c{i}"} for i in range(n_conflicting)],
    }


def test_score_novelty_from_memory_conflict_resolution():
    """_score_novelty_from_memory returns conflict_resolution when a conflicting claim is found."""
    memory_store = _FakeMemoryStore(
        call_responses=[
            [_make_claim_card_dict(n_conflicting=1, claim_text="ACC conflict claim")],
        ]
    )
    from brain_researcher.services.agent.hypothesis_candidate_cards import (
        _score_novelty_from_memory,
    )
    signal, priority, reason = _score_novelty_from_memory(
        "ACC encodes prediction error", memory_store
    )
    assert signal == "conflict_resolution"
    assert priority == "conflict_resolution"
    assert "ACC conflict claim" in reason


def test_score_novelty_from_memory_low_when_many_supporting():
    """_score_novelty_from_memory returns 'low' when ≥2 supporting and no conflicting claims."""
    memory_store = _FakeMemoryStore(
        call_responses=[
            [
                _make_claim_card_dict(n_supporting=1),
                _make_claim_card_dict(n_supporting=1),
            ]
        ]
    )
    from brain_researcher.services.agent.hypothesis_candidate_cards import (
        _score_novelty_from_memory,
    )
    signal, priority, reason = _score_novelty_from_memory("well-known claim", memory_store)
    assert signal == "low"
    assert priority == "low"


def test_novelty_pre_filter_conflict_card_sorts_first():
    """Explicit claim_memory_priority wins over quality-only ordering."""
    from brain_researcher.services.agent.hypothesis_candidate_cards import (
        _rerank_candidate_cards,
    )

    ranked = _rerank_candidate_cards(
        [
            {
                "title": "low-priority quality winner",
                "quality_bucket": "actual_idea_like",
                "gap_type": "evidence",
                "claim_memory_priority": "low",
            },
            {
                "title": "conflict resolver",
                "quality_bucket": "template_only",
                "gap_type": "evidence",
                "claim_memory_priority": "conflict_resolution",
            },
        ]
    )

    assert ranked[0]["title"] == "conflict resolver"
    assert ranked[0]["claim_memory_priority"] == "conflict_resolution"


def test_novelty_pre_filter_no_store_returns_unknown():
    """Without a memory store all cards get novelty_signal='unknown'."""
    workflow_result = _build_workflow_result(
        relation_hint="modulates",
        kg_verification={"verdict": "insufficient_evidence", "confidence": 0.3,
                         "evidence_source_scope": "none", "summary": {"n_supporting": 0, "n_conflicting": 0}},
    )
    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query="test query",
        top_n=5,
        memory_store=None,
    )
    for card in cards:
        assert card.get("novelty_signal") == "unknown"
