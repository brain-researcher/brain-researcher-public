import os

from brain_researcher.services.agent.error_taxonomy import RecoveryAction, classify_failure
from brain_researcher.services.agent.recovery_policy import select_recovery_decision
from brain_researcher.services.agent.subagents.contracts import RecoveryProposal


class DummyCandidate:
    def __init__(self, runtime_id: str, family: bool = False):
        self.runtime_id = runtime_id
        self._family = family

    def is_family(self) -> bool:
        return self._family


class DummyRouter:
    def get_candidates(self, query: str):
        return [
            DummyCandidate("tool_a"),
            DummyCandidate("family_tool", family=True),
        ]


def test_recovery_decision_filters_router_candidates(monkeypatch):
    monkeypatch.delenv("BR_RECOVERY_FORCE_LOW_MEM", raising=False)
    taxonomy = classify_failure(error_message="timeout")

    decision = select_recovery_decision(
        taxonomy=taxonomy,
        tool_id="tool_b",
        step_metadata={},
        step_idx=0,
        plan_candidates=None,
        query="analyze fmri",
        router=DummyRouter(),
        failed_tools={"tool_a"},
        params={"batch_size": 4},
    )

    assert "tool_a" not in decision.fallback_tools
    assert "family_tool" not in decision.fallback_tools
    assert decision.adjusted_params.get("batch_size") == 2
    assert "low_mem" not in decision.adjusted_params


def test_recovery_decision_multiagent_overlay(monkeypatch):
    class StubMultiAgentRouter:
        def propose_recovery(self, **kwargs):
            return RecoveryProposal(
                action_type="ask_user",
                confidence=0.9,
                reason="need_user_context",
            )

    monkeypatch.setenv("BR_AGENT_MULTIAGENT_ENABLED", "1")
    monkeypatch.setenv("BR_AGENT_RECOVERY_AGENT", "1")
    monkeypatch.setattr(
        "brain_researcher.services.agent.recovery_policy._get_multiagent_router",
        lambda: StubMultiAgentRouter(),
    )

    taxonomy = classify_failure(error_message="connection refused")
    decision = select_recovery_decision(
        taxonomy=taxonomy,
        tool_id="tool_x",
        step_metadata={},
        step_idx=0,
        plan_candidates=[],
        query="run",
        router=None,
        failed_tools=set(),
        params={},
    )

    assert "multiagent:need_user_context" in decision.reason
    assert isinstance(decision.action, RecoveryAction)
