"""Integration-style test: ChatOrchestrator pipeline path via PlanningEngine.

This test verifies that when `use_planning_engine=True`, ChatOrchestrator:
- Calls PlanningEngine.generate_plan
- Executes the returned steps (preview mode)
- Summarizes with the router and returns a pipeline reply
"""
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator, ChatReply
from brain_researcher.services.agent.planning import WorkflowStep, ExecutionPlan
from brain_researcher.services.agent.router import LLMRouter


def _make_plan() -> ExecutionPlan:
    steps = [
        WorkflowStep(
            step_id="s1",
            step_number=1,
            description="do A",
            tool_name="tool_a",
            tool_args={"x": 1},
        ),
        WorkflowStep(
            step_id="s2",
            step_number=2,
            description="do B",
            tool_name="tool_b",
            tool_args={"y": 2},
            dependencies=["s1"],
        ),
    ]
    return ExecutionPlan(
        plan_id="plan1",
        query="analyze motor task",
        objectives=["demo"],
        steps=steps,
        success_criteria=["done"],
        total_estimated_time=1.0,
        total_resource_requirements={},
        confidence_score=0.8,
    )


@patch("brain_researcher.services.agent.chat_orchestrator.PlanningEngine")
@patch("brain_researcher.services.agent.chat_orchestrator.ChatOrchestrator._execute_pipeline_steps")
@patch("brain_researcher.services.agent.chat_orchestrator.LLMRouter")
def test_planning_pipeline_path(mock_router_cls, mock_exec_steps, mock_planner_cls):
    # Mock router to return a summary
    mock_router = MagicMock(spec=LLMRouter)
    mock_router.route_chat.return_value = MagicMock(text="pipeline summary")
    mock_router_cls.return_value = mock_router

    # Mock planner.generate_plan to return an ExecutionPlan with two steps
    async def _plan_coro(*_args, **_kwargs):
        return _make_plan()

    mock_planner = MagicMock()
    mock_planner.generate_plan.side_effect = _plan_coro
    mock_planner_cls.return_value = mock_planner

    # Mock execution results for steps
    mock_exec_steps.return_value = [
        {"step_id": "s1", "status": "success"},
        {"step_id": "s2", "status": "success"},
    ]

    orch = ChatOrchestrator(router=mock_router)
    reply: ChatReply = orch.handle_chat(
        "run imaging pipeline",
        history=[],
        ctx={"use_planning_engine": True, "pipeline_preview": True},
    )

    assert reply.answer == "pipeline summary"
    assert reply.metadata == {"type": "pipeline", "mode": "preview"}
    assert len(reply.tool_calls) == 1
    steps = reply.tool_calls[0]["pipeline_steps"]
    assert len(steps) == 2

    mock_planner.generate_plan.assert_called_once()
    mock_exec_steps.assert_called_once()
    mock_router.route_chat.assert_called()
