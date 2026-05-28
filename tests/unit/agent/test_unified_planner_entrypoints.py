"""Unit tests for unified planner entrypoint wiring (chat + contract planner)."""

from __future__ import annotations

from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest


def test_unified_planner_candidate_set_shared_between_entrypoints(monkeypatch):
    """Both chat rebinding and /agent/plan (catalog) should use the same planner core."""

    from brain_researcher.services.agent.planner.unified_planner import (
        UnifiedPlannerResult,
    )
    from brain_researcher.core.contracts.violation import Violation

    fake_result = UnifiedPlannerResult(
        candidates=[
            {"tool_id": "tool.a", "tool_name": "Tool A", "final_score": 0.9},
            {"tool_id": "tool.b", "tool_name": "Tool B", "final_score": 0.8},
        ],
        scores={"tool.a": 0.9, "tool.b": 0.8},
        selection_reasons=[{"tool_id": "tool.a"}, {"tool_id": "tool.b"}],
        constraints_applied=["unit_test"],
        confidence_score=0.75,
        chosen_tool_id="tool.a",
        intent=["skull_strip"],
        task_family="skull_strip",
        kg_families=["fsl"],
        mask_reasons=[Violation(code="DEPENDENCY_MISSING", message="Preflight failed")],
        predicted_capabilities=["skull_strip"],
        predicted_intents=["skull_strip"],
        capability_prediction={"confidence": 0.9, "matched_crosswalk_keys": []},
        cross_stage_context={
            "schema_version": "cross-stage-context-v1",
            "task_family": "skull_strip",
            "predicted_intents": ["skull_strip"],
            "condition_constraints": [],
            "sensitivity_constraints": [],
            "design_constraints": [],
            "notes": [],
        },
        loop_signals=[
            {
                "schema_version": "loop-signal-v1",
                "signal_id": "ls_test_1",
                "signal_type": "condition_tag",
                "stage": "R1",
                "condition_key": "modality",
                "condition_value": "smri",
            }
        ],
    )

    class FakePlanner:
        def plan(self, *args, **kwargs):  # noqa: D401 - mimic planner interface
            return fake_result

    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.unified_planner.get_default_unified_planner",
        lambda *args, **kwargs: FakePlanner(),
    )

    # --- Chat entrypoint (NeuroAgentLLM._rebind_tools_for_query) ---
    from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM

    tool_a = SimpleNamespace(name="tool.a")
    tool_b = SimpleNamespace(name="tool.b")

    class DummyAgent:
        pass

    mock_agent = DummyAgent()
    mock_agent.tools = [tool_a, tool_b]
    mock_agent.llm = MagicMock()
    mock_agent.tool_retriever = MagicMock()
    mock_agent.retriever_max_families = 3
    mock_agent.retriever_top_k = 10
    mock_agent.max_bound_tools = 10
    mock_agent._convert_planner_tool_ids_to_registry_tools = (
        NeuroAgentLLM._convert_planner_tool_ids_to_registry_tools.__get__(
            mock_agent, NeuroAgentLLM
        )
    )

    ok = NeuroAgentLLM._rebind_tools_for_query(
        mock_agent, "skull strip T1", complexity="moderate"
    )
    assert ok is True

    bound_tools = mock_agent.llm.bind_tools.call_args.args[0]
    bound_names = [t.name for t in bound_tools]
    assert "tool.a" in bound_names
    assert "tool.b" in bound_names
    assert bound_names.index("tool.a") < bound_names.index("tool.b")

    # --- Contract entrypoint (/agent/plan, catalog mode) ---
    from brain_researcher.services.agent.web_service import app

    client = app.test_client()
    resp = client.post(
        "/agent/plan",
        json={
            "pipeline": "skull strip T1",
            "domain": "neuroimaging",
            "modality": ["smri"],
            "inputs": {},
            "mode": "catalog",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    tool_ids = [c.get("tool_id") for c in (body.get("candidates") or [])]
    assert tool_ids[:2] == ["tool.a", "tool.b"]
    assert body.get("predicted_capabilities") == ["skull_strip"]
    assert body.get("predicted_intents") == ["skull_strip"]
    assert isinstance(body.get("capability_prediction"), dict)
    assert isinstance(body.get("cross_stage_context"), dict)
    assert body["cross_stage_context"]["schema_version"] == "cross-stage-context-v1"
    assert isinstance(body.get("loop_signals"), list)
    assert body["loop_signals"][0]["signal_type"] == "condition_tag"
    assert body.get("mask_reasons") and body["mask_reasons"][0]["code"] == "DEPENDENCY_MISSING"
    assert body["mask_reasons"][0].get("schema_version") == "violation-v1"


pytestmark = pytest.mark.unit
