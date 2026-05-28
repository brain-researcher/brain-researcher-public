from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.worker import JobWorker


@dataclass
class _StubToolExecutionResult:
    status: str = "success"
    error: str | None = None
    result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class _StubToolExecutor:
    def __init__(self, *, result: _StubToolExecutionResult):
        self._result = result

    def execute(self, request: Any) -> _StubToolExecutionResult:  # noqa: ARG002
        return self._result


@pytest.mark.asyncio
async def test_worker_emits_retry_delay_metric_event():
    store = MemoryJobStore(total_gpu_slots=0)
    worker = JobWorker(job_store=store, worker_id="events-worker")

    job = JobRecord(
        job_id="job_retry_metric_001",
        kind="tool",
        user_id="user_test",
        state=JobState.QUEUED,
        priority=5,
        payload_json=json.dumps(
            {"tool_name": "test", "parameters": {}, "metadata": {}}
        ),
        created_at=int(time.time()),
        attempt=1,
        max_attempts=5,
    )
    await store.enqueue(job)

    await worker._finalize_job(
        job_id=job.job_id,
        exit_code=124,
        error_message="Command timed out",
    )

    events = await store.list_events(job.job_id, after_event_id=0)
    assert any(ev.event_type == "retry_scheduled" for ev in events)

    metric_events = [ev for ev in events if ev.event_type == "metric"]
    assert metric_events, "expected retry delay metric event"
    payload = metric_events[-1].payload or {}
    assert payload.get("name") == "retry.delay_seconds"
    assert payload.get("unit") == "s"
    assert isinstance(payload.get("value"), (int, float))


@pytest.mark.asyncio
async def test_worker_emits_tool_call_started_finished_events(tmp_path: Path):
    # Skip if ToolExecutor dependency wasn't importable in this environment.
    import brain_researcher.services.orchestrator.worker as worker_mod

    if not getattr(worker_mod, "TOOL_EXECUTOR_AVAILABLE", False):
        pytest.skip("ToolExecutor not available")

    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    result = _StubToolExecutionResult(
        status="success",
        error=None,
        result={
            "data": {
                "artifact": {
                    "id": "artifact_1",
                    "type": "text",
                    "name": "stub",
                    "path": "artifact.txt",
                }
            }
        },
        metadata={
            "run_id": "run-1",
            "run_dir": str(run_dir),
            "provenance_path": str(run_dir / "provenance.json"),
            "resource_usage": {"wall_time_sec": 0.01},
        },
    )
    worker = JobWorker(
        job_store=MemoryJobStore(total_gpu_slots=0),
        worker_id="events-worker",
        tool_executor=_StubToolExecutor(result=result),  # type: ignore[arg-type]
    )
    store = worker.job_store

    job = JobRecord(
        job_id="job_tool_call_001",
        kind="tool",
        user_id="user_test",
        state=JobState.QUEUED,
        priority=5,
        payload_json=json.dumps(
            {
                "tool_name": "my_tool",
                "parameters": {"x": 1},
                "execution_mode": "direct_execution",
                "metadata": {"runtime_kind": "python"},
            }
        ),
        created_at=int(time.time()),
        attempt=1,
        max_attempts=1,
    )
    await store.enqueue(job)

    await worker._execute_job(job)

    events = await store.list_events(job.job_id, after_event_id=0)
    started = next(ev for ev in events if ev.event_type == "tool.call.started")
    finished = next(ev for ev in events if ev.event_type == "tool.call.finished")

    assert (started.payload or {}).get("tool_call_id") == job.job_id
    assert (started.payload or {}).get("tool_id") == "my_tool"
    assert (started.payload or {}).get("params") == {"x": 1}
    assert (started.payload or {}).get("execution_mode") == "direct_execution"
    assert (started.payload or {}).get("runtime_kind") == "python"

    assert (finished.payload or {}).get("tool_call_id") == job.job_id
    assert (finished.payload or {}).get("tool_id") == "my_tool"
    assert (finished.payload or {}).get("status") == "success"
    assert (finished.payload or {}).get("exit_code") == 0
    assert (finished.payload or {}).get("error_message") is None
    assert ((finished.payload or {}).get("artifact") or {}).get("id") == "artifact_1"
