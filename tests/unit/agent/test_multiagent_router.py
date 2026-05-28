from brain_researcher.services.agent.subagents.router import MultiAgentRouter


def test_tool_gate_blocks_network_tool_when_no_network():
    router = MultiAgentRouter(
        enabled=True,
        critic_plan_gate=False,
        critic_tool_gate=True,
        recovery_agent_enabled=False,
    )

    verdict = router.review_tool_call(
        tool_name="web.search",
        params={},
        context={"no_network": True},
        tool_metadata=None,
    )

    assert verdict.decision == "block"
    assert verdict.reason == "network_disabled"


def test_plan_gate_disabled_is_fail_safe_approve():
    router = MultiAgentRouter(
        enabled=False,
        critic_plan_gate=True,
        critic_tool_gate=True,
        recovery_agent_enabled=False,
    )

    verdict = router.review_plan(
        plan={"tool": "tool_a", "params": {}},
        user_msg="run",
        structured_ctx="",
        context={},
        tool_candidates=[],
    )

    assert verdict.decision == "approve"
    assert "disabled" in verdict.reason


def test_recovery_agent_prefers_fallback_tool():
    router = MultiAgentRouter(
        enabled=True,
        critic_plan_gate=False,
        critic_tool_gate=False,
        recovery_agent_enabled=True,
    )

    proposal = router.propose_recovery(
        taxonomy_category="tool",
        policy_action="tool_substitute",
        fallback_tools=["fallback_a"],
        adjusted_params={},
        failed_tools=None,
        context=None,
    )

    assert proposal is not None
    assert proposal.action_type == "fallback_tool"
    assert proposal.fallback_tools == ["fallback_a"]
