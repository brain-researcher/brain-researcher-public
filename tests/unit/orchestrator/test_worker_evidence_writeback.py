"""Unit tests for KG evidence writeback hook in JobWorker."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.worker import JobWorker


class FakeEvidenceWriter:
    def __init__(self) -> None:
        self.writes = []

    def write(self, records):
        self.writes.append(list(records))


@pytest.mark.asyncio
async def test_plan_execution_writes_evidence_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("BR_KG_WRITEBACK", "1")

    # Minimal plan_execution payload (DAGExecutor is no-op; will mark steps skipped)
    payload = {
        "type": "plan_execution",
        "plan_id": "plan-1",
        "plan": {
            "plan_id": "plan-1",
            "dag": {"steps": [{"id": "s1", "tool": "fsl.bet.run", "params": {}}], "artifacts": []},
        },
        "steps": [{"id": "s1", "tool": "fsl.bet.run", "params": {}}],
        "context": {"pipeline": "skull_strip"},
        "snapshot": {"intent": ["skull_strip"], "chosen_tool": "fsl.bet.run"},
        "metadata": {"version": 1, "por_token": "tok"},
    }

    job = JobRecord(
        job_id="job-1",
        kind="plan_execution",
        payload_json=json.dumps(payload),
        state=JobState.SUCCEEDED,
        priority=5,
        gpu_req=0,
        worker_id="worker-test",
    )

    job_store = AsyncMock()
    job_store.get.return_value = job
    job_store.update_state.return_value = True
    job_store.heartbeat.return_value = 1

    fake_writer = FakeEvidenceWriter()
    worker = JobWorker(
        job_store=job_store,
        worker_id="worker-test",
        tool_executor=MagicMock(),
        plan_tool_executor=object(),
        evidence_writer=fake_writer,
    )

    await worker._execute_job(job)

    assert fake_writer.writes, "Expected evidence writeback to occur"
    written = fake_writer.writes[0]
    assert any(r.tool_id == "fsl.bet.run" for r in written)
    assert all(r.task_family == "skull_strip" for r in written)


pytestmark = pytest.mark.unit
