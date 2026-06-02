from __future__ import annotations


def test_registered_declarative_workflow_steps_resolve_runtime_tools(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mplconfig"))

    from brain_researcher.services.tools.tool_registry import ToolRegistry

    registry = ToolRegistry.from_env(
        light_mode=True,
        use_capabilities=False,
        enable_integrations=False,
    )

    candidate_cards = registry.get_runtime_tool("workflow_hypothesis_candidate_cards")
    assert candidate_cards is not None
    candidate_step_tools = {
        step.tool for step in getattr(candidate_cards, "_steps", [])
    }
    assert {
        "br_kg.find_structural_leverage",
        "br_kg.sample_ood_hypothesis",
        "br_kg.verify_sampled_hypotheses",
        "br_kg.detect_contradiction_motifs",
        "br_kg.detect_topology_shifts",
        "br_kg.synthesize_hypothesis_candidate_cards",
    } <= candidate_step_tools
    assert not any(tool_id.startswith("br-kg.") for tool_id in candidate_step_tools)

    missing_by_workflow: dict[str, list[str]] = {}
    for workflow_id, tool in sorted(registry.tools.items()):
        steps = getattr(tool, "_steps", None)
        if not steps:
            continue
        missing = [
            f"{step.step_id}:{step.tool}"
            for step in steps
            if registry.get_runtime_tool(step.tool) is None
        ]
        if missing:
            missing_by_workflow[workflow_id] = missing

    assert missing_by_workflow == {}
