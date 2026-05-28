"""Recovery-policy-driven retry tests for ToolExecutor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from brain_researcher.services.agent.subagents.contracts import CriticVerdict
from brain_researcher.services.agent.tool_executor import (
    ExecutionMode,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutor,
)
from brain_researcher.services.agent.tool_qc import (
    ToolQCEvaluation,
    ToolQCJudgeResult,
    ToolQCRetryDecision,
)


class _MinimalExecutor(ToolExecutor):
    def _get_tool(self, tool_name: str):
        return None

    def _allocate_resources(self, tool_name: str, priority, execution_id: str = None):
        return None

    def _infer_parameters(
        self, tool, parameters: dict[str, Any], context: dict[str, Any]
    ):
        return parameters

    def _validate_parameters(self, tool_name: str, parameters: dict[str, Any]):
        return {"valid": True}


class _PythonRetryExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        if self.calls == 1:
            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error="connection refused",
                result={"error": "connection refused"},
            )
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"status": "success"},
        )


class _PythonNoRetryExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="error",
            error="missing required parameter: foo",
            result={"error": "missing required parameter: foo"},
        )


class _PythonAdjustExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.seen_params = []

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        self.seen_params.append(dict(request.parameters))
        batch_size = request.parameters.get("batch_size", 0)
        timeout = request.parameters.get("timeout", 0)
        if batch_size >= 8 or timeout <= 10:
            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error="singular matrix",
                result={"error": "singular matrix"},
            )
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"status": "success"},
        )


class _PythonFallbackExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls.append(request.tool_name)
        if request.tool_name == "primary":
            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error="tool execution failed",
                result={"error": "tool execution failed"},
            )
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"status": "success"},
        )


class _SemanticQCAdjustExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.seen_params = []

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        self.seen_params.append(dict(request.parameters))
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"data": {"outputs": {"qc_png": "/tmp/qc.png"}}},
        )

    def _evaluate_semantic_qc(self, request, exec_result, *, attempt_index: int):
        if request.parameters.get("fractional_intensity") == 0.3:
            return ToolQCEvaluation(
                status="pass",
                judge_result=ToolQCJudgeResult(
                    passed=True,
                    confidence=0.95,
                    summary="mask looks good",
                    failure_modes=[],
                    evidence=[],
                ),
            )
        return ToolQCEvaluation(
            status="fail",
            judge_result=ToolQCJudgeResult(
                passed=False,
                confidence=0.9,
                summary="brain edge clipped",
                failure_modes=["over_strip"],
                evidence=["inferior slices clipped"],
            ),
            retry_decision=ToolQCRetryDecision(
                adjusted_params={"fractional_intensity": 0.3},
                reason="lower threshold",
            ),
        )


class _SemanticQCFallbackExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls.append(request.tool_name)
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"data": {"outputs": {"qc_png": "/tmp/qc.png"}}},
        )

    def _evaluate_semantic_qc(self, request, exec_result, *, attempt_index: int):
        if request.tool_name == "fallback":
            return ToolQCEvaluation(
                status="pass",
                judge_result=ToolQCJudgeResult(
                    passed=True,
                    confidence=0.95,
                    summary="fallback passed",
                    failure_modes=[],
                    evidence=[],
                ),
            )
        return ToolQCEvaluation(
            status="fail",
            judge_result=ToolQCJudgeResult(
                passed=False,
                confidence=0.88,
                summary="registration misaligned",
                failure_modes=["misalignment"],
                evidence=["checkerboard mismatch"],
            ),
            retry_decision=ToolQCRetryDecision(
                adjusted_params=request.parameters,
                fallback_tool="fallback",
                reason="switch tool",
            ),
        )


class _SemanticQCFailureExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"data": {"outputs": {"qc_png": "/tmp/qc.png"}}},
        )

    def _evaluate_semantic_qc(self, request, exec_result, *, attempt_index: int):
        return ToolQCEvaluation(
            status="fail",
            judge_result=ToolQCJudgeResult(
                passed=False,
                confidence=0.94,
                summary="semantic QC failed",
                failure_modes=["over_strip"],
                evidence=["inferior cortex clipped"],
            ),
        )


class _CachedPythonExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__(enable_caching=True)
        self.calls = 0

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"status": "success", "call": self.calls},
            metadata={},
        )


class _SemanticQCApiAdjustExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.seen_params = []

    def _execute_api_call(self, request: ToolExecutionRequest, retry_count: int = 0):
        self.calls += 1
        self.seen_params.append(dict(request.parameters))
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"status": "success", "outputs": {"qc_png": "/tmp/qc.png"}},
            metadata={},
        )

    def _evaluate_semantic_qc(self, request, exec_result, *, attempt_index: int):
        if request.parameters.get("fractional_intensity") == 0.3:
            return ToolQCEvaluation(
                status="pass",
                judge_result=ToolQCJudgeResult(
                    passed=True,
                    confidence=0.97,
                    summary="api qc passed",
                    failure_modes=[],
                    evidence=[],
                ),
            )
        return ToolQCEvaluation(
            status="fail",
            judge_result=ToolQCJudgeResult(
                passed=False,
                confidence=0.92,
                summary="api qc failed",
                failure_modes=["over_strip"],
                evidence=["inferior cortex clipped"],
            ),
            retry_decision=ToolQCRetryDecision(
                adjusted_params={"fractional_intensity": 0.3},
                reason="lower threshold",
            ),
        )


class _SemanticQCBatchFallbackExecutor(_MinimalExecutor):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _execute_batch(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls.append(request.tool_name)
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"status": "success", "outputs": {"qc_png": "/tmp/qc.png"}},
            metadata={
                "mode": "batch",
                "batch_size": len(request.parameters.get("batch", [])),
                "successful": len(request.parameters.get("batch", [])),
                "failed": 0,
                "results": [],
            },
        )

    def _evaluate_semantic_qc(self, request, exec_result, *, attempt_index: int):
        if request.tool_name == "fallback_batch":
            return ToolQCEvaluation(
                status="pass",
                judge_result=ToolQCJudgeResult(
                    passed=True,
                    confidence=0.95,
                    summary="batch fallback passed",
                    failure_modes=[],
                    evidence=[],
                ),
            )
        return ToolQCEvaluation(
            status="fail",
            judge_result=ToolQCJudgeResult(
                passed=False,
                confidence=0.89,
                summary="batch misregistration",
                failure_modes=["misregistration"],
                evidence=["checkerboard mismatch"],
            ),
            retry_decision=ToolQCRetryDecision(
                fallback_tool="fallback_batch",
                reason="switch batch tool",
            ),
        )


class _FakeTool:
    def __init__(self, name: str):
        self._name = name

    def get_tool_name(self) -> str:
        return self._name


def test_recovery_policy_blocks_retry_for_user_input(monkeypatch):
    calls = {"count": 0}

    def fake_execute_tool(*args, **kwargs):
        calls["count"] += 1
        return {"status": "error", "error": "missing required parameter: foo"}

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.execute_tool",
        fake_execute_tool,
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _MinimalExecutor()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={},
        max_retries=2,
        retry_on_failure=True,
    )

    result = executor.execute(request)

    assert calls["count"] == 1
    assert result.status == "error"
    assert result.recovery_strategy == "ask_user"


def test_semantic_qc_fallback_uses_runtime_canonical_tool_id() -> None:
    runtime_tool = _FakeTool("fsl_bet")
    fake_registry = MagicMock()
    fake_registry.get_tool.side_effect = (
        lambda name: runtime_tool if name == "fsl_bet" else None
    )
    fake_neurodesk = MagicMock()
    fake_neurodesk.get_tool_by_name.return_value = None

    executor = ToolExecutor(tool_registry=fake_registry, neurodesk_tools=fake_neurodesk)
    seen_tools: list[str] = []

    def executor_fn(request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.tool_name == "primary":
            seen_tools.append("primary")
        else:
            seen_tools.append(executor._get_tool(request.tool_name).get_tool_name())
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success",
            result={"data": {"outputs": {"qc_png": "/tmp/qc.png"}}},
        )

    def evaluate(request, exec_result, *, attempt_index: int):
        if request.tool_name == "fsl_bet":
            return ToolQCEvaluation(
                status="pass",
                judge_result=ToolQCJudgeResult(
                    passed=True,
                    confidence=0.96,
                    summary="fallback passed",
                    failure_modes=[],
                    evidence=[],
                ),
            )
        return ToolQCEvaluation(
            status="fail",
            judge_result=ToolQCJudgeResult(
                passed=False,
                confidence=0.91,
                summary="needs BET fallback",
                failure_modes=["misalignment"],
                evidence=["mask poor"],
            ),
            retry_decision=ToolQCRetryDecision(
                fallback_tool="fsl_bet",
                reason="switch to BET",
            ),
        )

    executor._evaluate_semantic_qc = evaluate  # type: ignore[method-assign]

    result = executor._execute_with_policy_retry(
        ToolExecutionRequest(tool_name="primary", parameters={}, max_retries=1),
        executor_fn,
    )

    assert result.status == "success"
    assert seen_tools == ["primary", "fsl_bet"]


def test_recovery_policy_allows_retry_for_infra(monkeypatch):
    calls = {"count": 0}
    responses = [
        {"status": "error", "error": "connection refused"},
        {"status": "success", "data": {"ok": True}},
    ]

    def fake_execute_tool(*args, **kwargs):
        calls["count"] += 1
        return responses.pop(0)

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.execute_tool",
        fake_execute_tool,
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _MinimalExecutor()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={},
        max_retries=1,
        retry_on_failure=True,
    )

    result = executor.execute(request)

    assert calls["count"] == 2
    assert result.status == "success"


def test_recovery_policy_blocks_retry_for_stats(monkeypatch):
    calls = {"count": 0}

    def fake_execute_tool(*args, **kwargs):
        calls["count"] += 1
        return {"status": "error", "error": "singular matrix"}

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.execute_tool",
        fake_execute_tool,
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _MinimalExecutor()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={},
        max_retries=1,
        retry_on_failure=True,
    )

    result = executor.execute(request)

    assert calls["count"] == 1
    assert result.status == "error"
    assert result.recovery_strategy == "relax_constraint"


def test_recovery_policy_retries_python_backend_for_infra(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _PythonRetryExecutor()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={},
        max_retries=1,
        retry_on_failure=True,
        runtime_kind="python",
    )

    result = executor.execute(request)

    assert executor.calls == 2
    assert result.status == "success"


def test_recovery_policy_blocks_retry_python_backend_for_user_input(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _PythonNoRetryExecutor()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={},
        max_retries=2,
        retry_on_failure=True,
        runtime_kind="python",
    )

    result = executor.execute(request)

    assert executor.calls == 1
    assert result.status == "error"
    assert result.recovery_strategy == "ask_user"


def test_recovery_policy_adjusts_params_for_stats(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _PythonAdjustExecutor()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={"batch_size": 8, "timeout": 10},
        max_retries=2,
        retry_on_failure=True,
        runtime_kind="python",
    )

    result = executor.execute(request)

    assert executor.calls == 2
    assert executor.seen_params[0]["batch_size"] == 8
    assert executor.seen_params[1]["batch_size"] == 4
    assert executor.seen_params[1]["timeout"] == 20
    assert result.status == "success"


def test_recovery_policy_fallback_tool_substitution(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _PythonFallbackExecutor()
    request = ToolExecutionRequest(
        tool_name="primary",
        parameters={},
        max_retries=2,
        retry_on_failure=True,
        runtime_kind="python",
        context={"step_metadata": {"fallback_tools": ["fallback"]}},
    )

    result = executor.execute(request)

    assert executor.calls == ["primary", "fallback"]
    assert result.status == "success"


def test_recovery_policy_retries_after_semantic_qc_param_adjustment(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _SemanticQCAdjustExecutor()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={"fractional_intensity": 0.5},
        max_retries=2,
        retry_on_failure=True,
        runtime_kind="python",
    )

    result = executor.execute(request)

    assert executor.calls == 2
    assert executor.seen_params == [
        {"fractional_intensity": 0.5},
        {"fractional_intensity": 0.3},
    ]
    assert result.status == "success"
    assert result.metadata["semantic_qc"]["status"] == "pass"


def test_recovery_policy_switches_tool_after_semantic_qc_fallback(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _SemanticQCFallbackExecutor()
    request = ToolExecutionRequest(
        tool_name="primary",
        parameters={"metric": "MI"},
        max_retries=2,
        retry_on_failure=True,
        runtime_kind="python",
    )

    result = executor.execute(request)

    assert executor.calls == ["primary", "fallback"]
    assert result.status == "success"
    assert result.metadata["semantic_qc"]["status"] == "pass"


def test_semantic_qc_failure_attaches_failure_taxonomy(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _SemanticQCFailureExecutor()
    request = ToolExecutionRequest(
        tool_name="primary",
        parameters={"fractional_intensity": 0.5},
        max_retries=0,
        retry_on_failure=True,
        runtime_kind="python",
    )

    result = executor.execute(request)

    assert executor.calls == 1
    assert result.status == "error"
    assert result.error == "semantic_qc_failed"
    assert result.error_category is not None
    assert result.recovery_strategy is not None
    assert result.metadata["semantic_qc"]["status"] == "fail"
    assert result.metadata["error_taxonomy"]["category"] == result.error_category


def test_execute_bypasses_cache_for_semantic_qc_requests(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _CachedPythonExecutor()
    monkeypatch.setattr(executor, "_request_has_semantic_qc", lambda request: True)

    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={"x": 1},
        runtime_kind="python",
    )

    result1 = executor.execute(request)
    result2 = executor.execute(request)

    assert executor.calls == 2
    assert result1.result["call"] == 1
    assert result2.result["call"] == 2
    assert result2.metadata.get("from_cache") is not True


def test_api_call_mode_retries_after_semantic_qc_param_adjustment(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _SemanticQCApiAdjustExecutor()
    request = ToolExecutionRequest(
        tool_name="api_tool",
        parameters={"fractional_intensity": 0.5},
        mode=ExecutionMode.API_CALL,
        max_retries=2,
        retry_on_failure=True,
    )

    result = executor.execute(request)

    assert executor.calls == 2
    assert executor.seen_params == [
        {"fractional_intensity": 0.5},
        {"fractional_intensity": 0.3},
    ]
    assert result.status == "success"
    assert result.metadata["semantic_qc"]["status"] == "pass"


def test_batch_mode_switches_tool_after_semantic_qc_fallback(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.time.sleep",
        lambda *_: None,
    )

    executor = _SemanticQCBatchFallbackExecutor()
    request = ToolExecutionRequest(
        tool_name="primary_batch",
        parameters={"batch": [{"x": 1}, {"x": 2}]},
        mode=ExecutionMode.BATCH,
        max_retries=2,
        retry_on_failure=True,
    )

    result = executor.execute(request)

    assert executor.calls == ["primary_batch", "fallback_batch"]
    assert result.status == "success"
    assert result.metadata["semantic_qc"]["status"] == "pass"


def test_multiagent_tool_gate_blocks_execution(monkeypatch):
    class StubMultiAgentRouter:
        def review_tool_call(self, **kwargs):
            return CriticVerdict(
                decision="block",
                risk_level="high",
                reason="blocked_for_test",
            )

    monkeypatch.setenv("BR_AGENT_MULTIAGENT_ENABLED", "1")
    monkeypatch.setenv("BR_AGENT_CRITIC_TOOL_GATE", "1")

    executor = _PythonRetryExecutor()
    executor._multiagent_router = StubMultiAgentRouter()
    request = ToolExecutionRequest(
        tool_name="dummy",
        parameters={},
        max_retries=1,
        retry_on_failure=True,
        runtime_kind="python",
    )

    result = executor.execute(request)

    assert result.status == "error"
    assert result.error == "blocked_by_multiagent_critic"
    assert executor.calls == 0
