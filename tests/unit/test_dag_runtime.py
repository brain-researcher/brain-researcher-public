"""Unit tests for orchestrator DAG runtime executor."""

from typing import Any, Dict

from brain_researcher.services.orchestrator.dag_runtime import (
    DAGExecutor,
    WorkflowDefinition,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)


class DummyExecutor:
    def __init__(self, responses: Dict[str, Dict[str, Any]]):
        self._responses = responses

    def run_tool(self, tool_name: str, **kwargs):
        return self._responses.get(tool_name, {"status": "error", "error": "missing"})


def test_dag_executor_attaches_taxonomy_on_failure():
    executor = DummyExecutor(
        {
            "tool.fail": {"status": "error", "error": "connection refused"},
        }
    )
    dag_executor = DAGExecutor(tool_executor=executor)
    workflow = WorkflowDefinition(
        workflow_id="wf1",
        steps=[WorkflowStep(step_id="s1", tool_name="tool.fail", parameters={})],
    )
    result: WorkflowResult = dag_executor.execute(workflow)

    assert result.state == WorkflowState.FAILED
    assert result.step_results
    step = result.step_results[0]
    assert step.get("error_taxonomy")
    assert step.get("error_category")


def test_dag_executor_fallback_tool_recovery():
    executor = DummyExecutor(
        {
            "tool.primary": {"status": "error", "error": "timeout"},
            "tool.fallback": {"status": "success", "data": {"outputs": {"x": 1}}},
        }
    )
    dag_executor = DAGExecutor(tool_executor=executor)
    workflow = WorkflowDefinition(
        workflow_id="wf2",
        steps=[
            WorkflowStep(
                step_id="s1",
                tool_name="tool.primary",
                parameters={},
                metadata={"fallback_tool": "tool.fallback"},
            )
        ],
    )
    result: WorkflowResult = dag_executor.execute(workflow)

    assert result.state == WorkflowState.SUCCEEDED
    step = result.step_results[0]
    assert step.get("status") in {"success", "succeeded"}
    assert step.get("recovery") == {"from_tool": "tool.primary", "to_tool": "tool.fallback"}
