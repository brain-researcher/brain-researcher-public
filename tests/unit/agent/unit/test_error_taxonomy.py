import pytest

from brain_researcher.services.agent.tool_executor import (
    ExecutionMode,
    ToolExecutionRequest,
    ToolExecutor,
)


def test_tool_timeout_classified_as_infra_retryable():
    executor = ToolExecutor(enable_caching=False, safe_mode=True, default_timeout=1.0)
    try:
        request = ToolExecutionRequest(
            tool_name="direct_exec_timeout_test",
            parameters={"command": "sleep 1"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            timeout=0.05,
        )
        result = executor.execute(request)

        assert result.status == "timeout"
        assert result.error_category == "infra"
        assert result.is_retryable is True
        assert result.recovery_strategy == "retry_backoff"
        assert result.recovery_suggestions
        assert "error_taxonomy" in (result.metadata or {})
    finally:
        # Best-effort cleanup (avoids lingering threads in some environments)
        executor.shutdown()

