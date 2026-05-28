from __future__ import annotations

from brain_researcher.research.discovery.gates.evidence_gate import (
    generic_failure_modes,
    summary_next_step_decision,
    support_contrasts_from_summary,
)
from brain_researcher.research.discovery.gates.novelty_gate import (
    decision_and_rationale,
    global_recommendation,
)
from brain_researcher.research.discovery.hypothesis_schema import HypothesisEntryV1


def test_support_contrasts_from_summary_prefers_explicit_backticked_variants() -> None:
    support = support_contrasts_from_summary(
        "Primary winner is `math_vs_language`, but `math_vs_rest` still matters.",
        "math_vs_language",
        "",
    )

    assert support == ["math_vs_rest"]


def test_summary_next_step_decision_detects_freeze_from_summary_bullet() -> None:
    decision, rationale = summary_next_step_decision(
        "- Freeze this branch until a new battery arrives.\n- Keep note for later."
    )

    # LLM-said "freeze" is mapped to freeze_candidate so the controller
    # review + human-approval gate still applies (unified with
    # controller-proposed freeze_candidate promotion).
    assert decision == "freeze_candidate"
    assert rationale == "Freeze this branch until a new battery arrives."


def test_generic_failure_modes_flags_under_specified_biological_motion_runs() -> None:
    failures = generic_failure_modes(
        branch_id="biological_motion",
        manifest={"condition_counts": {"intact_biological_motion": 12}},
        contrast_rows=[],
        nearest_rows=[],
        best_score=0.0,
    )

    assert failures == ["weak_effect", "format_mismatch"]


def test_generic_failure_modes_consumes_typed_ledger_entries() -> None:
    failures = generic_failure_modes(
        branch_id="math",
        manifest={"condition_counts": {"math": 10}},
        contrast_rows=[{"contrast_id": "math_vs_language", "score": 0.22}],
        nearest_rows=[],
        best_score=0.22,
        ledger_entries=[
            HypothesisEntryV1(
                hypothesis_id="hyp_001",
                branch_id="math",
                failure_modes=["visual_format_confound"],
                decision="pivot_baseline",
                posterior_confidence=0.2,
            )
        ],
    )

    assert "visual_format_confound" in failures
    assert "weak_effect" in failures


def test_decision_and_rationale_uses_kg_method_compatibility() -> None:
    def fake_kg_context_builder(**_kwargs: object) -> dict[str, object]:
        return {
            "method_compatibility": {
                "compatible": False,
                "design": {"canonical": "repeated_measures"},
                "method": {"canonical": "independent_t_test"},
            }
        }

    decision, rationale = decision_and_rationale(
        branch_id="math",
        manifest={
            "priority": "targeted_follow_up",
            "design": "within-subject",
            "method": "independent samples t-test",
        },
        best_score=0.31,
        contrast_rows=[{"contrast_id": "math_vs_language", "score": 0.31}],
        failure_modes=[],
        kg_context_builder=fake_kg_context_builder,
    )

    assert decision == "pivot_baseline"
    assert "incompatible" in rationale


def test_decision_and_rationale_pivots_math_branch_when_baseline_is_confounded() -> None:
    decision, rationale = decision_and_rationale(
        branch_id="math",
        manifest={"priority": "targeted_follow_up"},
        best_score=0.31,
        contrast_rows=[{"contrast_id": "math_vs_language", "score": 0.31}],
        failure_modes=["visual_format_confound"],
    )

    assert decision == "pivot_baseline"
    assert "confounded" in rationale


def test_global_recommendation_orders_open_branches_by_priority() -> None:
    recommendation = global_recommendation(
        [
            {"branch_id": "auditory", "status": "open"},
            {"branch_id": "tom", "status": "frozen"},
            {"branch_id": "biological_motion", "status": "open"},
        ],
        open_branch_priority=["biological_motion", "rsvp_language", "auditory"],
    )

    assert recommendation == {
        "mode": "continue_open_branches",
        "priority_branch_ids": ["biological_motion", "auditory"],
    }
