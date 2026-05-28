from unittest.mock import patch

from brain_researcher.services.agent.tool_executor import (
    ExecutionMode,
    ToolCategory,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutor,
)


class _StubExecutor(ToolExecutor):
    def _execute_api_call(self, request, retry_count: int = 0):
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="error",
            error="boom",
            result={"error": "boom"},
        )


def test_tool_call_failed_emits_error_category():
    executor = _StubExecutor()
    request = ToolExecutionRequest(
        tool_name="test.tool",
        parameters={},
        mode=ExecutionMode.API_CALL,
        category=ToolCategory.API_SERVICE,
        context={"job_id": "job_123"},
    )

    with patch(
        "brain_researcher.services.agent.tool_executor.record_telemetry_event"
    ) as record_event:
        executor.execute(request)

    assert record_event.called

    payload = record_event.call_args.args[0]
    event_type = record_event.call_args.kwargs.get("event_type")

    assert event_type == "tool_call_failed"
    assert payload["job_id"] == "job_123"
    assert payload["tool_name"] == "test.tool"
    assert payload["error_category"]
