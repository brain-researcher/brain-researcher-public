"""Unit tests for planner branch fallback DAG output."""

from __future__ import annotations

import os

from brain_researcher.services.agent.planner.catalog_loader import (
    PythonRunnerSpec,
    ResourceSpec,
    ToolCapability,
)
from brain_researcher.services.agent.planner.selection import SelectionCandidate, choose_tool
from brain_researcher.services.shared.planner.models import PlanRequest


def _candidate(tool_id: str, score: float) -> SelectionCandidate:
    tool = ToolCapability(
        id=tool_id,
        name=tool_id,
        package="test",
        description="test tool",
        documentation=None,
        runtime_kind="python",
        entrypoint=None,
        modality=["fmri"],
        capabilities=["demo"],
        intents=[],
        consumes=[],
        produces=[],
        resources=ResourceSpec(cpu_min=1, mem_mb_min=256, time_min_default=1.0),
        python=PythonRunnerSpec(module="tests.tools", function="run"),
    )
    return SelectionCandidate(
        tool=tool,
        scoring_weights={
            "intent_match": 1.0,
            "preflight": 0.0,
            "description": 0.0,
            "metadata": 0.0,
            "resource_fit": 0.0,
            "historical_quality": 0.0,
            "latency_pred": 0.0,
        },
        intent_match_score=score,
        preflight_passed=True,
        description_score=score,
        metadata_score=score,
        resource_fit_score=score,
        historical_quality_score=score,
        latency_score=score,
    )


def test_choose_tool_emits_branch_steps(monkeypatch):
    monkeypatch.setenv("BR_PLANNER_BRANCH_TOP_K", "2")

    candidates = [_candidate("tool.a.run", 0.9), _candidate("tool.b.run", 0.8)]
    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.selection.select_tools",
        lambda **_: candidates,
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.selection.match_intents",
        lambda *_, **__: [],
    )

    request = PlanRequest(
        pipeline="demo plan",
        domain="neuroimaging",
        modality=["fmri"],
        inputs={},
    )
    plan = choose_tool(request)

    assert plan.chosen_tool == "tool.a.run"
    assert len(plan.dag.steps) == 2
    branch_group = plan.dag.steps[0].metadata.get("branch_group_id")
    assert branch_group
    assert plan.dag.steps[0].metadata.get("branch_rank") == 0
    assert plan.dag.steps[1].metadata.get("branch_rank") == 1
    assert plan.dag.steps[1].metadata.get("branch_group_id") == branch_group
    assert plan.dag.steps[0].tool == "tool.a.run"
    assert plan.dag.steps[1].tool == "tool.b.run"

    monkeypatch.delenv("BR_PLANNER_BRANCH_TOP_K", raising=False)
