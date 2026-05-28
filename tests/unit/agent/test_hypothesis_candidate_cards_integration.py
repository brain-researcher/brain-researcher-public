"""Integration-style test for hypothesis candidate card generation workflow."""

from __future__ import annotations

from brain_researcher.services.agent.hypothesis_candidate_cards import (
    build_candidate_cards_from_workflow_result,
)
from brain_researcher.services.tools.runner import execute_tool


def _iter_string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_string_values(item)
    elif isinstance(value, list | tuple | set):
        for item in value:
            yield from _iter_string_values(item)


def _assert_novelty_calibration_payload(rewrite_result, card_ids):
    questions = rewrite_result["novelty_calibration_questions"]
    meta = rewrite_result["novelty_calibration_meta"]

    assert questions
    assert meta["total_questions"] > 0
    assert meta["total_questions"] == len(questions)
    assert any(
        any(card_id in text for card_id in card_ids)
        for question in questions
        for text in _iter_string_values(question)
    )


def _structured_ood_hypothesis(
    *,
    rank: int,
    candidate_kg_id: str,
    candidate_label: str,
    query: str,
    relation_hint: str = "ASSOCIATED_WITH",
) -> dict[str, object]:
    return {
        "rank": rank,
        "seed_kg_id": "node:seed",
        "candidate_kg_id": candidate_kg_id,
        "statement": (
            f"{candidate_label} may preserve {query} when matched control trials are "
            "held constant."
        ),
        "mechanism": (
            f"{candidate_label} may maintain the task-relevant representation needed "
            f"for {query}."
        ),
        "prediction": (
            f"The {candidate_label}-linked signal should remain stronger during {query} "
            "than in matched control trials."
        ),
        "relation_hint": relation_hint,
        "claim_type": "mechanism",
        "novelty_score": 0.82,
        "ood_score": 0.91,
    }


def test_workflow_hypothesis_candidate_cards_end_to_end(monkeypatch):
    """Mock KG novelty tool responses and assert candidate-card fields are generated."""

    sampled_call: dict[str, object] = {}

    def _fake_find_structural_leverage(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "structural_leverage",
            "seed_kg_ids": ["node:seed", "node:semantic_seed"],
            "semantic_seed_labels": {
                "node:seed": "Seed Node",
                "node:semantic_seed": "Semantic Seed Node",
            },
            "semantic_seed_types": {
                "node:seed": "Task",
                "node:semantic_seed": "Concept",
            },
            "seed_provenance": {
                "node:seed": ["direct"],
                "node:semantic_seed": ["search_expanded_from:node:seed"],
            },
            "items": [
                {
                    "kg_id": "node:candidate_a",
                    "label": "Candidate A",
                    "leverage_score": 0.91,
                    "novelty_score": 0.82,
                },
                {
                    "kg_id": "node:candidate_b",
                    "label": "Candidate B",
                    "leverage_score": 0.87,
                    "novelty_score": 0.79,
                },
            ],
        }

    def _fake_sample_ood_hypothesis(*args, **kwargs):
        del args
        sampled_call["seed_kg_ids"] = kwargs.get("seed_kg_ids")
        sampled_call["leverage_context"] = kwargs.get("leverage_context")
        candidate_a = _structured_ood_hypothesis(
            rank=1,
            candidate_kg_id="node:candidate_a",
            candidate_label="Candidate A",
            query="fmri based image decoding",
            relation_hint="ASSOCIATED_WITH",
        )
        candidate_b = _structured_ood_hypothesis(
            rank=2,
            candidate_kg_id="node:candidate_b",
            candidate_label="Candidate B",
            query="fmri based image decoding",
            relation_hint="CO_ACTIVATES",
        )
        return {
            "ok": True,
            "mode": "ood_hypothesis_sampling",
            "hypotheses": [candidate_a, candidate_b],
        }

    def _fake_detect_contradiction_motifs(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_motifs",
            "motifs": [
                {
                    "publication_id": "pub:123",
                    "publication_label": "Example Contradiction Paper",
                    "support_count": 3,
                    "conflict_count": 2,
                    "motif_score": 0.71,
                    "contradiction_density": 0.4,
                }
            ],
        }

    def _fake_detect_topology_shifts(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "proposal",
            "proposals": [
                {
                    "edge": {
                        "source_id": "node:seed",
                        "target_id": "node:candidate_a",
                        "rel_type": "ASSOCIATED_WITH",
                    },
                    "delta": 0.22,
                    "target_weight": 0.83,
                }
            ],
        }

    def _fake_find_contradiction_frontiers(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_frontiers",
            "seed_kg_ids": ["node:seed"],
            "frontiers": [],
        }

    def _fake_mine_assumption_cracks(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "assumption_cracks", "cracks": []}

    def _fake_find_analogy_transfers(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "analogy_transfers", "transfers": []}

    def _fake_verify_sampled_hypotheses(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "sampled_hypothesis_verification",
            "candidate_lane_mode": "strict",
            "evidence_items": [],
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate_a",
                    "statement": (
                        "Candidate A may preserve fmri based image decoding when "
                        "matched control trials are held constant."
                    ),
                    "entity_hints_used": ["node:seed", "node:candidate_a"],
                    "kg_verification": {
                        "verdict": "supported",
                        "confidence": 0.67,
                        "evidence_mode": "shared",
                        "evidence_source_scope": "direct",
                    },
                },
                {
                    "rank": 2,
                    "candidate_kg_id": "node:candidate_b",
                    "statement": (
                        "Candidate B may preserve fmri based image decoding when "
                        "matched control trials are held constant."
                    ),
                    "entity_hints_used": ["node:seed", "node:candidate_b"],
                    "kg_verification": {
                        "verdict": "insufficient_evidence",
                        "confidence": 0.31,
                        "evidence_mode": "union",
                        "evidence_source_scope": "expanded_family",
                    },
                },
            ],
            "summary": {"n_tested": 2, "n_supported": 1, "n_insufficient_evidence": 1},
        }

    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_structural_leverage",
        _fake_find_structural_leverage,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.sample_ood_hypothesis",
        _fake_sample_ood_hypothesis,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_contradiction_motifs",
        _fake_detect_contradiction_motifs,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_topology_shifts",
        _fake_detect_topology_shifts,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_contradiction_frontiers",
        _fake_find_contradiction_frontiers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.mine_assumption_cracks",
        _fake_mine_assumption_cracks,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_analogy_transfers",
        _fake_find_analogy_transfers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.verify_sampled_hypotheses",
        _fake_verify_sampled_hypotheses,
    )

    workflow_run = execute_tool(
        "workflow_hypothesis_candidate_cards",
        {
            "query": "fmri based image decoding",
            "seed_kg_ids": ["node:seed"],
            "top_k": 10,
            "n_samples": 2,
            "taste_mode": "novelty_first",
        },
    )

    assert workflow_run.status == "success", workflow_run.error
    assert workflow_run.data and workflow_run.data.get("workflow") == (
        "workflow_hypothesis_candidate_cards"
    )
    rewrite_result = workflow_run.data["steps"]["candidate_card_rewrite"]["data"][
        "result"
    ]
    assert rewrite_result["summary"]["n_candidate_cards"] == 2
    assert rewrite_result["summary"]["quality_bucket_counts"]
    assert len(rewrite_result["candidate_cards"]) == 2
    assert sampled_call["seed_kg_ids"] == ["node:seed", "node:semantic_seed"]
    assert sampled_call["leverage_context"] == {
        "ok": True,
        "mode": "structural_leverage",
        "seed_kg_ids": ["node:seed", "node:semantic_seed"],
        "semantic_seed_labels": {
            "node:seed": "Seed Node",
            "node:semantic_seed": "Semantic Seed Node",
        },
        "semantic_seed_types": {
            "node:seed": "Task",
            "node:semantic_seed": "Concept",
        },
        "seed_provenance": {
            "node:seed": ["direct"],
            "node:semantic_seed": ["search_expanded_from:node:seed"],
        },
        "items": [
            {
                "kg_id": "node:candidate_a",
                "label": "Candidate A",
                "leverage_score": 0.91,
                "novelty_score": 0.82,
            },
            {
                "kg_id": "node:candidate_b",
                "label": "Candidate B",
                "leverage_score": 0.87,
                "novelty_score": 0.79,
            },
        ],
    }

    cards = build_candidate_cards_from_workflow_result(
        workflow_run.data,
        query="fmri based image decoding",
        top_n=2,
    )
    assert len(cards) == 2
    card_ids = {card["card_id"] for card in cards if card.get("card_id")}
    _assert_novelty_calibration_payload(rewrite_result, card_ids)
    for card in cards:
        assert card.get("minimal_discriminating_test")
        assert card.get("falsifier_hint")
        assert card.get("taste_axis")
        assert card.get("contradiction_probe")
        assert card.get("topology_shift_probe")
        assert card.get("kg_verification")
        assert "gap_type" in card
        assert "gap_specification" in card
        assert "gap_actionable" in card
        assert card.get("idea")
        assert card.get("mechanism")
        assert card.get("rewrite_status")
        assert card.get("quality_bucket")
        if card["quality_bucket"] != "off_target":
            assert card.get("testable_hypothesis")
        assert card["provenance"]["sampled_hypothesis_verification"]["kg_verification"]
        assert "gap_type" in card["provenance"]["sampled_hypothesis_verification"]
        assert (
            card["provenance"]["sampled_hypothesis_verification"]["candidate_lane_mode"]
            == "strict"
        )
        assert card.get("provenance")

    cards_by_candidate = {card["provenance"]["candidate_kg_id"]: card for card in cards}
    assert cards_by_candidate["node:candidate_a"]["gap_type"] is None
    assert cards_by_candidate["node:candidate_b"]["gap_type"] == "evidence"


def test_workflow_hypothesis_candidate_cards_emits_step_progress_and_respects_verify_external_override(
    monkeypatch,
):
    progress_events: list[dict[str, object]] = []
    verify_external_flags: list[object] = []

    def _fake_find_structural_leverage(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "structural_leverage",
            "seed_kg_ids": ["node:seed"],
            "items": [
                {
                    "kg_id": "node:candidate_a",
                    "label": "Candidate A",
                    "leverage_score": 0.9,
                    "novelty_score": 0.8,
                }
            ],
        }

    def _fake_sample_ood_hypothesis(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "ood_hypothesis_sampling",
            "hypotheses": [
                _structured_ood_hypothesis(
                    rank=1,
                    candidate_kg_id="node:candidate_a",
                    candidate_label="Candidate A",
                    query="fmri based image decoding",
                )
            ],
        }

    def _fake_verify_sampled_hypotheses(*args, **kwargs):
        del args
        verify_external_flags.append(kwargs.get("use_external_literature"))
        return {
            "ok": True,
            "mode": "sampled_hypothesis_verification",
            "candidate_lane_mode": "broad",
            "evidence_items": [],
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate_a",
                    "statement": "Candidate A may preserve fmri based image decoding.",
                    "entity_hints_used": ["node:seed", "node:candidate_a"],
                    "kg_verification": {
                        "verdict": "supported",
                        "confidence": 0.7,
                        "evidence_mode": "shared",
                        "evidence_source_scope": "direct",
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_supported": 1},
        }

    def _fake_detect_contradiction_motifs(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "contradiction_motifs", "motifs": []}

    def _fake_detect_topology_shifts(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "proposal", "proposals": []}

    def _fake_find_contradiction_frontiers(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_frontiers",
            "seed_kg_ids": ["node:seed"],
            "frontiers": [],
        }

    def _fake_mine_assumption_cracks(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "assumption_cracks", "cracks": []}

    def _fake_find_analogy_transfers(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "analogy_transfers", "transfers": []}

    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_structural_leverage",
        _fake_find_structural_leverage,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.sample_ood_hypothesis",
        _fake_sample_ood_hypothesis,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.verify_sampled_hypotheses",
        _fake_verify_sampled_hypotheses,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_contradiction_motifs",
        _fake_detect_contradiction_motifs,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_topology_shifts",
        _fake_detect_topology_shifts,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_contradiction_frontiers",
        _fake_find_contradiction_frontiers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.mine_assumption_cracks",
        _fake_mine_assumption_cracks,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_analogy_transfers",
        _fake_find_analogy_transfers,
    )

    workflow_run = execute_tool(
        "workflow_hypothesis_candidate_cards",
        {
            "query": "fmri based image decoding",
            "seed_kg_ids": ["node:seed"],
            "top_k": 5,
            "n_samples": 1,
            "use_external_literature": True,
            "verify_use_external_literature": False,
            "_progress_callback": progress_events.append,
        },
    )

    assert workflow_run.status == "success", workflow_run.error
    assert verify_external_flags == [False]
    assert any(
        event.get("step_id") == "verify_sampled_hypotheses"
        and event.get("status") == "running"
        for event in progress_events
    )
    assert any(
        event.get("step_id") == "verify_sampled_hypotheses"
        and event.get("status") == "completed"
        for event in progress_events
    )

    verify_external_flags.clear()
    followup_run = execute_tool(
        "workflow_hypothesis_candidate_cards",
        {
            "query": "fmri based image decoding",
            "seed_kg_ids": ["node:seed"],
            "top_k": 5,
            "n_samples": 1,
            "use_external_literature": True,
        },
    )

    assert followup_run.status == "success", followup_run.error
    assert verify_external_flags == [True]


def test_workflow_hypothesis_candidate_cards_principle_v0_adds_controller_metadata(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("BR_PLAN_MEMORY_DB", str(tmp_path / "plan_memory.db"))
    sampled_call: dict[str, object] = {}

    def _fake_find_structural_leverage(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "structural_leverage",
            "seed_kg_ids": ["node:seed", "node:semantic_seed"],
            "semantic_seed_labels": {
                "node:seed": "Seed Node",
                "node:semantic_seed": "Semantic Seed Node",
            },
            "semantic_seed_types": {
                "node:seed": "Task",
                "node:semantic_seed": "Concept",
            },
            "seed_provenance": {
                "node:seed": ["direct"],
                "node:semantic_seed": ["search_expanded_from:node:seed"],
            },
            "items": [
                {
                    "kg_id": "node:candidate_a",
                    "label": "Candidate A",
                    "node_type": "Task",
                    "candidate_type": "Task",
                    "seeds_touched": ["node:seed"],
                    "relations": ["ASSOCIATED_WITH"],
                    "leverage_score": 0.91,
                    "novelty_score": 0.82,
                    "coherence_score": 0.66,
                    "feasibility_score": 0.55,
                    "score_breakdown": {
                        "novelty_score": 0.82,
                        "coherence_score": 0.66,
                        "feasibility_score": 0.55,
                    },
                }
            ],
        }

    def _fake_sample_ood_hypothesis(*args, **kwargs):
        del args
        sampled_call["seed_kg_ids"] = kwargs.get("seed_kg_ids")
        sampled_call["leverage_context"] = kwargs.get("leverage_context")
        principle_state = kwargs.get("principle_state") or {}
        return {
            "ok": True,
            "mode": "ood_hypothesis_sampling",
            "principle_session_key": principle_state.get("session_key"),
            "active_principle": principle_state.get("active_principle"),
            "principle_confidence": principle_state.get("principle_confidence"),
            "selection_reason": "balanced:weighted_rerank",
            "hypotheses": [
                {
                    **_structured_ood_hypothesis(
                        rank=1,
                        candidate_kg_id="node:candidate_a",
                        candidate_label="Candidate A",
                        query="fmri based image decoding",
                        relation_hint="ASSOCIATED_WITH",
                    ),
                    "principle_score": 0.77,
                }
            ],
            "summary": {
                "n_requested": 1,
                "n_hypotheses": 1,
                "n_returned": 1,
                "n_vetoed": 0,
                "n_rewrite_failed": 0,
            },
        }

    def _fake_detect_contradiction_motifs(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_motifs",
            "motifs": [
                {
                    "publication_id": "pub:123",
                    "publication_label": "Example Contradiction Paper",
                    "support_count": 3,
                    "conflict_count": 2,
                    "motif_score": 0.71,
                    "contradiction_density": 0.4,
                }
            ],
        }

    def _fake_detect_topology_shifts(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "proposal", "proposals": []}

    def _fake_find_contradiction_frontiers(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_frontiers",
            "seed_kg_ids": ["node:seed"],
            "frontiers": [],
        }

    def _fake_mine_assumption_cracks(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "assumption_cracks", "cracks": []}

    def _fake_find_analogy_transfers(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "analogy_transfers", "transfers": []}

    def _fake_verify_sampled_hypotheses(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "sampled_hypothesis_verification",
            "evidence_items": [],
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate_a",
                    "statement": (
                        "Candidate A may preserve fmri based image decoding when "
                        "matched control trials are held constant."
                    ),
                    "entity_hints_used": ["node:seed", "node:candidate_a"],
                    "kg_verification": {
                        "verdict": "supported",
                        "confidence": 0.71,
                        "evidence_mode": "shared",
                        "evidence_source_scope": "direct",
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_supported": 1},
        }

    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_structural_leverage",
        _fake_find_structural_leverage,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.sample_ood_hypothesis",
        _fake_sample_ood_hypothesis,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_contradiction_motifs",
        _fake_detect_contradiction_motifs,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_topology_shifts",
        _fake_detect_topology_shifts,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_contradiction_frontiers",
        _fake_find_contradiction_frontiers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.mine_assumption_cracks",
        _fake_mine_assumption_cracks,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_analogy_transfers",
        _fake_find_analogy_transfers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.verify_sampled_hypotheses",
        _fake_verify_sampled_hypotheses,
    )

    workflow_run = execute_tool(
        "workflow_hypothesis_candidate_cards",
        {
            "query": "fmri based image decoding",
            "seed_kg_ids": ["node:seed"],
            "top_k": 10,
            "n_samples": 1,
            "taste_mode": "balanced",
            "controller_mode": "principle_v0",
        },
    )

    assert workflow_run.status == "success", workflow_run.error
    assert sampled_call["seed_kg_ids"] == ["node:seed", "node:semantic_seed"]
    assert sampled_call["leverage_context"] == {
        "ok": True,
        "mode": "structural_leverage",
        "seed_kg_ids": ["node:seed", "node:semantic_seed"],
        "semantic_seed_labels": {
            "node:seed": "Seed Node",
            "node:semantic_seed": "Semantic Seed Node",
        },
        "semantic_seed_types": {
            "node:seed": "Task",
            "node:semantic_seed": "Concept",
        },
        "seed_provenance": {
            "node:seed": ["direct"],
            "node:semantic_seed": ["search_expanded_from:node:seed"],
        },
        "items": [
            {
                "kg_id": "node:candidate_a",
                "label": "Candidate A",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["node:seed"],
                "relations": ["ASSOCIATED_WITH"],
                "leverage_score": 0.91,
                "novelty_score": 0.82,
                "coherence_score": 0.66,
                "feasibility_score": 0.55,
                "score_breakdown": {
                    "novelty_score": 0.82,
                    "coherence_score": 0.66,
                    "feasibility_score": 0.55,
                },
            }
        ],
    }
    update_result = workflow_run.data["steps"]["principle_state_update"]["data"][
        "result"
    ]
    assert update_result["controller_mode"] == "principle_v0"
    assert update_result["active_principle_id"] == "contradiction_resolving"
    assert update_result["anomaly_flags"] == ["contradiction"]

    cards = build_candidate_cards_from_workflow_result(
        workflow_run.data,
        query="fmri based image decoding",
        top_n=1,
    )

    assert len(cards) == 1
    card = cards[0]
    assert card["quality_bucket"] in {
        "actual_idea_like",
        "template_only",
        "off_target",
    }
    assert card["rewrite_status"] in {"rewritten", "needs_rewrite", "rejected"}
    assert card["principle_session_key"]
    assert card["selection_reason"] == "contradiction_triggered"
    assert card["anomaly_flags"] == ["contradiction"]
    assert card["active_principle"]["principle_id"] == "contradiction_resolving"
    assert card["kg_verification"]["verdict"] == "supported"
    assert (
        card["provenance"]["principle_controller"]["controller_mode"] == "principle_v0"
    )
    assert (
        card["provenance"]["principle_controller"]["active_principle_id"]
        == "contradiction_resolving"
    )
    assert (
        card["provenance"]["sampled_hypothesis_verification"]["kg_verification"][
            "evidence_source_scope"
        ]
        == "direct"
    )


def test_workflow_hypothesis_candidate_cards_tolerates_missing_evidence_items(
    monkeypatch,
):
    def _fake_find_structural_leverage(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "structural_leverage",
            "seed_kg_ids": ["node:seed"],
            "items": [
                {
                    "kg_id": "node:candidate_a",
                    "label": "Candidate A",
                    "leverage_score": 0.91,
                    "novelty_score": 0.82,
                }
            ],
        }

    def _fake_sample_ood_hypothesis(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "ood_hypothesis_sampling",
            "hypotheses": [
                _structured_ood_hypothesis(
                    rank=1,
                    candidate_kg_id="node:candidate_a",
                    candidate_label="Candidate A",
                    query="response streak confounds in pupillometry decision neuroscience",
                    relation_hint="ASSOCIATED_WITH",
                )
            ],
        }

    def _fake_verify_sampled_hypotheses(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "sampled_hypothesis_verification",
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate_a",
                    "statement": (
                        "Candidate A may preserve response streak confounds in "
                        "pupillometry decision neuroscience when matched control "
                        "trials are held constant."
                    ),
                    "entity_hints_used": ["node:seed", "node:candidate_a"],
                    "kg_verification": {
                        "verdict": "supported",
                        "confidence": 0.67,
                        "evidence_mode": "shared",
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_supported": 1},
        }

    def _fake_detect_contradiction_motifs(*args, **kwargs):
        assert kwargs.get("evidence_items") == []
        return {"ok": True, "mode": "contradiction_motifs", "motifs": []}

    def _fake_detect_topology_shifts(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "proposal", "proposals": []}

    def _fake_find_contradiction_frontiers(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_frontiers",
            "seed_kg_ids": ["node:seed"],
            "frontiers": [],
        }

    def _fake_mine_assumption_cracks(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "assumption_cracks", "cracks": []}

    def _fake_find_analogy_transfers(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "analogy_transfers", "transfers": []}

    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_structural_leverage",
        _fake_find_structural_leverage,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.sample_ood_hypothesis",
        _fake_sample_ood_hypothesis,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.verify_sampled_hypotheses",
        _fake_verify_sampled_hypotheses,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_contradiction_motifs",
        _fake_detect_contradiction_motifs,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_topology_shifts",
        _fake_detect_topology_shifts,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_contradiction_frontiers",
        _fake_find_contradiction_frontiers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.mine_assumption_cracks",
        _fake_mine_assumption_cracks,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_analogy_transfers",
        _fake_find_analogy_transfers,
    )

    workflow_run = execute_tool(
        "workflow_hypothesis_candidate_cards",
        {
            "query": "response streak confounds in pupillometry decision neuroscience",
            "seed_kg_ids": ["node:seed"],
            "top_k": 8,
            "n_samples": 1,
        },
    )

    assert workflow_run.status == "success", workflow_run.error
    assert workflow_run.data is not None
    assert workflow_run.data["steps"]["contradiction_scan"]["status"] == "success"
    rewrite_result = workflow_run.data["steps"]["candidate_card_rewrite"]["data"][
        "result"
    ]
    assert rewrite_result["summary"]["n_candidate_cards"] == 1
    assert rewrite_result["candidate_cards"][0]["idea"]
    card_ids = {
        card["card_id"]
        for card in rewrite_result["candidate_cards"]
        if card.get("card_id")
    }
    _assert_novelty_calibration_payload(rewrite_result, card_ids)


def test_workflow_hypothesis_candidate_cards_frontier_mode_merges_frontier_cards(
    monkeypatch,
):
    def _fake_find_structural_leverage(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "structural_leverage",
            "seed_kg_ids": ["node:seed"],
            "items": [
                {
                    "kg_id": "node:candidate_a",
                    "label": "Candidate A",
                    "leverage_score": 0.91,
                    "novelty_score": 0.82,
                }
            ],
        }

    def _fake_sample_ood_hypothesis(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "ood_hypothesis_sampling",
            "hypotheses": [
                _structured_ood_hypothesis(
                    rank=1,
                    candidate_kg_id="node:candidate_a",
                    candidate_label="Candidate A",
                    query="fmri based image decoding",
                    relation_hint="ASSOCIATED_WITH",
                )
            ],
        }

    def _fake_verify_sampled_hypotheses(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "sampled_hypothesis_verification",
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate_a",
                    "statement": (
                        "Candidate A may preserve fmri based image decoding when "
                        "matched control trials are held constant."
                    ),
                    "kg_verification": {
                        "verdict": "supported",
                        "evidence_source_scope": "direct",
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_supported": 1},
        }

    def _fake_detect_contradiction_motifs(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "contradiction_motifs", "motifs": []}

    def _fake_detect_topology_shifts(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "proposal", "proposals": []}

    def _fake_find_contradiction_frontiers(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_frontiers",
            "seed_kg_ids": ["node:seed"],
            "frontiers": [],
        }

    def _fake_mine_assumption_cracks(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "assumption_cracks", "cracks": []}

    def _fake_find_analogy_transfers(*args, **kwargs):
        del args, kwargs
        return {"ok": True, "mode": "analogy_transfers", "transfers": []}

    def _fake_synthesize_wow_candidate_cards(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "wow_candidate_cards",
            "candidate_cards": [
                {
                    "card_id": "wow_transfer_01",
                    "title": "causal transfer transfer",
                    "hypothesis": (
                        "Hypothesis: A causal transfer analysis may sharpen fmri based "
                        "image decoding under matched visual controls.\n"
                        "Mechanism: A causal transfer analysis may isolate the "
                        "task-relevant representational subspace needed for fmri based "
                        "image decoding.\n"
                        "Independent variable: Applying the causal transfer analysis "
                        "versus a matched baseline decoder.\n"
                        "Dependent variable: The preregistered fmri based image "
                        "decoding accuracy metric.\n"
                        "Prediction: The causal transfer analysis should improve the "
                        "decoding metric relative to the matched baseline."
                    ),
                    "idea": (
                        "Test whether a causal transfer analysis isolates a better "
                        "mechanism for fmri based image decoding."
                    ),
                    "mechanism": (
                        "A causal transfer analysis may isolate the task-relevant "
                        "representational subspace needed for fmri based image decoding."
                    ),
                    "independent_variable": (
                        "Applying the causal transfer analysis versus a matched "
                        "baseline decoder."
                    ),
                    "dependent_variable": (
                        "The preregistered fmri based image decoding accuracy metric."
                    ),
                    "predicted_direction": (
                        "The causal transfer analysis should improve the decoding "
                        "metric relative to the matched baseline."
                    ),
                    "testable_hypothesis": (
                        "Hypothesis: A causal transfer analysis may sharpen fmri based "
                        "image decoding under matched visual controls.\n"
                        "Mechanism: A causal transfer analysis may isolate the "
                        "task-relevant representational subspace needed for fmri based "
                        "image decoding.\n"
                        "Independent variable: Applying the causal transfer analysis "
                        "versus a matched baseline decoder.\n"
                        "Dependent variable: The preregistered fmri based image "
                        "decoding accuracy metric.\n"
                        "Prediction: The causal transfer analysis should improve the "
                        "decoding metric relative to the matched baseline."
                    ),
                    "quality_bucket": "actual_idea_like",
                    "rewrite_status": "rewritten",
                    "minimal_discriminating_test": (
                        "Run the causal transfer analysis and compare it with the "
                        "matched baseline decoder."
                    ),
                    "falsifier_hint": (
                        "Reject if the causal transfer analysis provides no decoding "
                        "gain over the matched baseline."
                    ),
                    "provenance": {
                        "source_stage": "analogy_transfers",
                        "query": "fmri based image decoding",
                    },
                }
            ],
            "summary": {"n_candidates": 1},
            "warnings": [],
        }

    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_structural_leverage",
        _fake_find_structural_leverage,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.sample_ood_hypothesis",
        _fake_sample_ood_hypothesis,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.verify_sampled_hypotheses",
        _fake_verify_sampled_hypotheses,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_contradiction_motifs",
        _fake_detect_contradiction_motifs,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_topology_shifts",
        _fake_detect_topology_shifts,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_contradiction_frontiers",
        _fake_find_contradiction_frontiers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.mine_assumption_cracks",
        _fake_mine_assumption_cracks,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_analogy_transfers",
        _fake_find_analogy_transfers,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.synthesize_wow_candidate_cards",
        _fake_synthesize_wow_candidate_cards,
    )

    workflow_run = execute_tool(
        "workflow_hypothesis_candidate_cards",
        {
            "query": "fmri based image decoding",
            "seed_kg_ids": ["node:seed"],
            "n_samples": 2,
            "frontier_mode": "frontier",
        },
    )

    assert workflow_run.status == "success", workflow_run.error
    rewrite_result = workflow_run.data["steps"]["candidate_card_rewrite"]["data"][
        "result"
    ]
    assert rewrite_result["summary"]["frontier_mode"] == "frontier"
    assert rewrite_result["summary"]["n_frontier_cards"] == 1
    assert any(
        card.get("provenance", {}).get("frontier_mode") == "frontier"
        for card in rewrite_result["candidate_cards"]
    )
