"""Tests for claim-memory injection into the planning prompt."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from brain_researcher.services.agent.graph import (
    AgentState,
    CoreStateMachine,
    StatePhase,
    _format_claim_memories_as_house_rules,
)

# ---------------------------------------------------------------------------
# _format_claim_memories_as_house_rules
# ---------------------------------------------------------------------------


def _make_claim_card(
    claim_text: str,
    *,
    confidence: str = "preliminary",
    n_supporting: int = 0,
    n_conflicting: int = 0,
) -> dict:
    return {
        "claim_text": claim_text,
        "confidence": confidence,
        "supporting_evidence": [{"run_id": f"r{i}"} for i in range(n_supporting)],
        "conflicting_evidence": [{"run_id": f"c{i}"} for i in range(n_conflicting)],
    }


def test_format_claim_memories_empty():
    assert _format_claim_memories_as_house_rules([]) == ""


def test_format_claim_memories_supporting_and_conflicting():
    cards = [
        _make_claim_card("ACC encodes PE", confidence="moderate", n_supporting=2),
        _make_claim_card("vmPFC contradicts ACC coupling", n_conflicting=1),
        _make_claim_card("Default mode is broad", confidence="preliminary"),
    ]
    result = _format_claim_memories_as_house_rules(cards)
    assert result.startswith("[Prior claims]")
    assert "SUPPORTS" in result
    assert "CONFLICTS" in result
    assert "PRIOR" in result
    assert "ACC encodes PE" in result
    assert "vmPFC contradicts ACC coupling" in result


def test_format_claim_memories_caps_at_five():
    cards = [_make_claim_card(f"claim {i}", n_supporting=1) for i in range(10)]
    result = _format_claim_memories_as_house_rules(cards)
    assert result.count("SUPPORTS") == 5


def test_format_claim_memories_skips_empty_claim_text():
    cards = [
        {"claim_text": "", "confidence": "moderate", "supporting_evidence": [], "conflicting_evidence": []},
        _make_claim_card("valid claim", n_supporting=1),  # confidence="preliminary"
    ]
    result = _format_claim_memories_as_house_rules(cards)
    assert "SUPPORTS" in result
    assert "valid claim" in result
    # Only 1 supporting line (empty text skipped)
    assert result.count("SUPPORTS") == 1


# ---------------------------------------------------------------------------
# _get_relevant_memories includes claim_memory block
# ---------------------------------------------------------------------------


@pytest.fixture()
def sm_with_derived_store():
    """Return a CoreStateMachine with a mocked derived_memory_store."""
    with patch.object(CoreStateMachine, "__init__", lambda self, *a, **kw: None):
        sm = CoreStateMachine.__new__(CoreStateMachine)
    sm.memory_selector = None
    sm.derived_memory_store = MagicMock()
    return sm


def test_get_relevant_memories_injects_claim_block(sm_with_derived_store):
    sm = sm_with_derived_store

    episodic_card = {
        "card_type": "episodic_run_memory",
        "task_description": "run fmri analysis",
        "status": "success",
        "what_worked": ["tool X worked"],
        "what_failed": [],
        "next_time_hints": [],
        "score": 0.9,
    }
    claim_card = _make_claim_card(
        "ACC encodes prediction error", confidence="moderate", n_supporting=1
    )
    conflict_card = _make_claim_card(
        "vmPFC deactivation contradicts ACC", n_conflicting=1
    )

    def _fake_search(query, card_type=None, filters=None, limit=5):
        if card_type == "episodic_run_memory":
            return {"ok": True, "cards": [episodic_card]}
        if card_type == "claim_memory":
            return {"ok": True, "cards": [claim_card, conflict_card]}
        return {"ok": True, "cards": []}

    sm.derived_memory_store.search.side_effect = _fake_search

    # Provide a minimal AgentState
    state: AgentState = {
        "messages": [],
        "current_phase": StatePhase.PLAN,
        "previous_phase": None,
        "plan": None,
        "plan_steps": [],
        "selected_tools": [],
        "tool_args": {},
        "execution_results": {},
        "review_feedback": None,
        "needs_revision": False,
        "error": None,
        "error_recovery_attempts": 0,
        "max_recovery_attempts": 3,
        "thread_id": "t1",
        "session_checkpoint_id": None,
        "hypothesis_cards": None,
        "execution_mode": None,
        "conflict_hint": None,
    }

    result = sm._get_relevant_memories("fmri prediction error ACC", state)
    assert "[Prior claims]" in result
    assert "SUPPORTS" in result
    assert "CONFLICTS" in result
    # Episodic block should also be present
    assert "Runtime Memory" in result or "fmri analysis" in result.lower()


def test_build_graph_routes_memory_before_plan():
    with patch.object(CoreStateMachine, "__init__", lambda self, *a, **kw: None):
        sm = CoreStateMachine.__new__(CoreStateMachine)
    graph = sm._build_graph()

    assert ("__start__", "route_memory") in graph.edges
    assert ("route_memory", "plan") in graph.edges


def test_plan_state_injects_conflict_resolution_prompt_after_routing():
    class RecordingLLM:
        def __init__(self) -> None:
            self.calls: list[list[object]] = []

        def invoke(self, input_data):
            self.calls.append(list(input_data))
            return AIMessage(
                content='{"objectives":["o"],"steps":[],"success_criteria":["s"]}'
            )

    llm = RecordingLLM()
    with patch.object(CoreStateMachine, "__init__", lambda self, *a, **kw: None):
        sm = CoreStateMachine.__new__(CoreStateMachine)
    sm.memory_selector = None
    sm.derived_memory_store = None
    sm.complexity_gate = None
    sm.plan_memory = None
    sm.plan_logger = None
    sm.use_planning_engine = False
    sm.planning_engine = None
    sm.llm = llm

    state: AgentState = {
        "messages": [HumanMessage(content="Test ACC conflict")],
        "current_phase": StatePhase.INIT,
        "previous_phase": None,
        "plan": None,
        "plan_steps": [],
        "selected_tools": [],
        "tool_args": {},
        "execution_results": {},
        "review_feedback": None,
        "needs_revision": False,
        "error": None,
        "error_recovery_attempts": 0,
        "max_recovery_attempts": 3,
        "thread_id": "t1",
        "session_checkpoint_id": None,
        "hypothesis_cards": [
            {
                "claim_memory_priority": "conflict_resolution",
                "claim_memory_reason": "ACC prior claims disagree",
            }
        ],
        "execution_mode": None,
        "conflict_hint": None,
    }

    routed_state = sm.route_by_memory_signal(state)
    sm._plan_state(routed_state)

    assert llm.calls, "Expected planning LLM to be invoked"
    system_message = llm.calls[0][0]
    assert "[Conflict resolution mode]" in system_message.content
    assert "ACC prior claims disagree" in system_message.content


def test_plan_state_injects_planning_policies():
    class RecordingLLM:
        def __init__(self) -> None:
            self.calls: list[list[object]] = []

        def invoke(self, input_data):
            self.calls.append(list(input_data))
            return AIMessage(
                content='{"objectives":["o"],"steps":[],"success_criteria":["s"]}'
            )

    llm = RecordingLLM()
    with patch.object(CoreStateMachine, "__init__", lambda self, *a, **kw: None):
        sm = CoreStateMachine.__new__(CoreStateMachine)
    sm.memory_selector = None
    sm.derived_memory_store = None
    sm.complexity_gate = None
    sm.plan_memory = None
    sm.plan_logger = None
    sm.use_planning_engine = False
    sm.planning_engine = None
    sm.llm = llm

    state: AgentState = {
        "messages": [HumanMessage(content="Explain the n-back task")],
        "current_phase": StatePhase.INIT,
        "previous_phase": None,
        "plan": None,
        "plan_steps": [],
        "selected_tools": [],
        "tool_args": {},
        "execution_results": {},
        "review_feedback": None,
        "needs_revision": False,
        "error": None,
        "error_recovery_attempts": 0,
        "max_recovery_attempts": 3,
        "thread_id": "t1",
        "session_checkpoint_id": None,
        "hypothesis_cards": None,
        "execution_mode": None,
        "conflict_hint": None,
    }

    sm._plan_state(state)

    assert llm.calls, "Expected planning LLM to be invoked"
    system_message = llm.calls[0][0]
    assert "[Planning policies]" in system_message.content
    assert "first normalize it with a cheap grounding step" in system_message.content
    assert "do not repeat the same call with only minor argument changes" in system_message.content
    assert "preserve those fields explicitly in the plan" in system_message.content
