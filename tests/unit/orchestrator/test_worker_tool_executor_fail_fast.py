from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.worker import JobWorker
from brain_researcher.services.orchestrator import worker as worker_module


def test_worker_allows_stub_tool_executor_in_dev(monkeypatch) -> None:
    monkeypatch.delenv("BR_REQUIRE_TOOL_EXECUTOR", raising=False)
    monkeypatch.delenv("BR_WORKER_REQUIRE_TOOL_EXECUTOR", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)

    monkeypatch.setattr(worker_module, "TOOL_EXECUTOR_AVAILABLE", False)
    store = MemoryJobStore(total_gpu_slots=1)

    worker = JobWorker(job_store=store, worker_id="test", tool_executor=None, plan_tool_executor=None)
    assert worker.tool_executor is None


def test_worker_fails_fast_when_tool_executor_required(monkeypatch) -> None:
    monkeypatch.setenv("BR_REQUIRE_TOOL_EXECUTOR", "true")
    monkeypatch.setattr(worker_module, "TOOL_EXECUTOR_AVAILABLE", False)

    store = MemoryJobStore(total_gpu_slots=1)
    with pytest.raises(RuntimeError, match="ToolExecutor is required"):
        JobWorker(
            job_store=store,
            worker_id="test",
            tool_executor=None,
            plan_tool_executor=MagicMock(),
        )

