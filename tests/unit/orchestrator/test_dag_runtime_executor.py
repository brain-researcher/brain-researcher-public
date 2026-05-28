from __future__ import annotations

import time

import pytest

from brain_researcher.services.orchestrator.dag_runtime import (
    DAGExecutor,
    WorkflowDefinition,
    WorkflowStep,
    WorkflowState,
)


class DummyToolExecutor:
    def __init__(self):
        self.calls = []

    def run_tool(self, tool_name: str, **kwargs):
        self.calls.append((tool_name, kwargs))
        if tool_name == "fail_once":
            attempt = kwargs.get("attempt", 1)
            if attempt == 1:
                return {"status": "error", "error": "boom"}
        if tool_name == "sleepy":
            time.sleep(0.2)
        return {"status": "success", "data": {"outputs": {f"out_{tool_name}": tool_name}}}


def _wf(*steps: WorkflowStep) -> WorkflowDefinition:
    return WorkflowDefinition(workflow_id="wf", steps=list(steps))


def test_exec_respects_dependencies_and_concurrency():
    exec_calls = []

    class Recorder(DummyToolExecutor):
        def run_tool(self, tool_name: str, **kwargs):
            exec_calls.append(tool_name)
            return super().run_tool(tool_name, **kwargs)

    tool_exec = Recorder()
    executor = DAGExecutor(tool_executor=tool_exec, max_concurrency=2)
    wf = _wf(
        WorkflowStep("a", "tool_a", {}),
        WorkflowStep("b", "tool_b", {}, depends_on=["a"]),
        WorkflowStep("c", "tool_c", {}, depends_on=["a"]),
    )

    result = executor.execute(wf)

    assert result.state == WorkflowState.SUCCEEDED
    # a must run before b/c, but b and c order between them is free
    assert exec_calls[0] == "tool_a"
    assert set(exec_calls[1:]) == {"tool_b", "tool_c"}


def test_exec_passes_run_context_to_tool_executor():
    captured_context = {}

    class Recorder(DummyToolExecutor):
        def run_tool(self, tool_name: str, **kwargs):
            captured_context.update(kwargs.get("_execution_context") or {})
            return super().run_tool(tool_name, **kwargs)

    tool_exec = Recorder()
    executor = DAGExecutor(tool_executor=tool_exec, max_concurrency=1)
    wf = WorkflowDefinition(
        workflow_id="wf_ctx",
        steps=[WorkflowStep("a", "tool_a", {})],
        metadata={"run_dir": "/tmp/dag-run"},
    )

    result = executor.execute(wf)

    assert result.state == WorkflowState.SUCCEEDED
    assert captured_context.get("parent_run_id") == "wf_ctx"
    assert captured_context.get("step_id") == "a"
    assert captured_context.get("work_dir") == "/tmp/dag-run"
    assert str(captured_context.get("output_dir", "")).endswith("/tmp/dag-run/outputs")


def test_retry_and_timeout_events(monkeypatch):
    events = []

    def emit(evt, payload):
        events.append((evt, payload))

    class FailThenOk(DummyToolExecutor):
        def run_tool(self, tool_name: str, **kwargs):
            attempt = kwargs.pop("_attempt", 0)
            return {"status": "error", "error": "boom"} if attempt == 0 else {"status": "success"}

    tool_exec = FailThenOk()

    # monkeypatch runner to pass attempt count
    original = tool_exec.run_tool
    call_counter = {"n": 0}

    def wrapped(name, **kw):
        n = call_counter["n"]
        call_counter["n"] += 1
        kw["_attempt"] = n
        return original(name, **kw)

    tool_exec.run_tool = wrapped  # type: ignore

    executor = DAGExecutor(tool_executor=tool_exec, event_callback=emit)
    wf = _wf(
        WorkflowStep("x", "fail_once", {}, metadata={"retries": 1, "retry_delay": 0.01}),
    )
    result = executor.execute(wf)

    assert result.state == WorkflowState.SUCCEEDED
    retry_events = [p for evt, p in events if evt == "step_retry"]
    assert retry_events, "retry event missing"
    assert retry_events[0].get("error") is not None
    assert retry_events[0].get("status") in {"error", "timeout", "unknown"}


def test_timeout_returns_failed():
    tool_exec = DummyToolExecutor()
    events = []

    def emit(evt, payload):
        events.append((evt, payload))

    executor = DAGExecutor(tool_executor=tool_exec, max_concurrency=1, event_callback=emit)
    wf = _wf(
        WorkflowStep("s", "sleepy", {}, metadata={"timeout_sec": 0.05}),
    )
    result = executor.execute(wf)

    assert result.state == WorkflowState.FAILED
    step = result.step_results[0]
    assert step["status"] == "timeout"
    completed = [p for evt, p in events if evt == "step_completed"]
    assert completed and completed[0].get("status") == "timeout"
    assert completed[0].get("error")
