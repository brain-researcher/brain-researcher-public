"""Tests for postcheck blocking enforcement in JobWorker."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from brain_researcher.config.retry_settings import clear_settings_cache
from brain_researcher.core.gates.engine import GateEngine
from brain_researcher.services.orchestrator import worker as worker_module
from brain_researcher.services.orchestrator.dag_runtime import (
    WorkflowResult,
    WorkflowState,
)
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.worker import JobWorker


@pytest.mark.asyncio
async def test_plan_postcheck_blocks_on_existing_violation(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BR_RETRY_ENABLED", "true")
    clear_settings_cache()

    run_dir = tmp_path / "run-plan"
    run_dir.mkdir(parents=True, exist_ok=True)

    def fake_execute(self, workflow):
        return WorkflowResult(
            state=WorkflowState.SUCCEEDED,
            error=None,
            run_dir=str(run_dir),
            step_results=[
                {
                    "step_id": "s1",
                    "tool": "fsl.bet.run",
                    "status": "succeeded",
                    "violations": [
                        {"code": "V_BLOCK", "message": "blocked", "blocking": True}
                    ],
                }
            ],
        )

    monkeypatch.setattr(worker_module.DAGExecutor, "execute", fake_execute)

    payload = {
        "type": "plan_execution",
        "plan_id": "plan-1",
        "plan": {
            "plan_id": "plan-1",
            "dag": {
                "steps": [{"id": "s1", "tool": "fsl.bet.run", "params": {}}],
                "artifacts": [],
            },
        },
        "steps": [{"id": "s1", "tool": "fsl.bet.run", "params": {}}],
        "context": {"pipeline": "skull_strip"},
        "snapshot": {"intent": ["skull_strip"], "chosen_tool": "fsl.bet.run"},
        "metadata": {"version": 1, "por_token": "tok"},
    }

    job = JobRecord(
        job_id="job-plan-1",
        kind="plan_execution",
        payload_json=json.dumps(payload),
        state=JobState.QUEUED,
        priority=5,
        gpu_req=0,
        worker_id="worker-test",
    )

    job_store = MemoryJobStore(total_gpu_slots=1)
    await job_store.enqueue(job)

    worker = JobWorker(
        job_store=job_store,
        worker_id="worker-test",
        tool_executor=MagicMock(),
        plan_tool_executor=MagicMock(),
    )
    worker.gate_engine = None

    await worker._execute_job(job)

    final_job = await job_store.get("job-plan-1")
    assert final_job.state == JobState.FAILED
    assert final_job.exit_code == 1
    assert "Postcheck blocked" in (final_job.error_message or "")


@pytest.mark.asyncio
async def test_plan_postcheck_blocks_on_gate_violation(monkeypatch, tmp_path: Path):
    """Blocking gate rules at postcheck should fail the plan job."""
    monkeypatch.setenv("BR_RETRY_ENABLED", "true")
    clear_settings_cache()

    run_dir = tmp_path / "run-plan"
    run_dir.mkdir(parents=True, exist_ok=True)

    def fake_execute(self, workflow):
        return WorkflowResult(
            state=WorkflowState.SUCCEEDED,
            error=None,
            run_dir=str(run_dir),
            step_results=[
                {
                    "step_id": "s1",
                    "tool": "glm.fitlins.run",
                    "status": "succeeded",
                    # Triggers QC_MEAN_FD_HIGH in configs/gates.yaml
                    "qc": {"motion": {"mean_fd": 0.8}},
                }
            ],
        )

    monkeypatch.setattr(worker_module.DAGExecutor, "execute", fake_execute)

    payload = {
        "type": "plan_execution",
        "plan_id": "plan-1",
        "plan": {
            "plan_id": "plan-1",
            "dag": {
                "steps": [{"id": "s1", "tool": "glm.fitlins.run", "params": {}}],
                "artifacts": [],
            },
        },
        "steps": [{"id": "s1", "tool": "glm.fitlins.run", "params": {}}],
        "context": {"pipeline": "glm"},
        "snapshot": {"intent": ["glm"], "chosen_tool": "glm.fitlins.run"},
        "metadata": {"version": 1, "por_token": "tok"},
    }

    job = JobRecord(
        job_id="job-plan-2",
        kind="plan_execution",
        payload_json=json.dumps(payload),
        state=JobState.QUEUED,
        priority=5,
        gpu_req=0,
        worker_id="worker-test",
    )

    job_store = MemoryJobStore(total_gpu_slots=1)
    await job_store.enqueue(job)

    worker = JobWorker(
        job_store=job_store,
        worker_id="worker-test",
        tool_executor=MagicMock(),
        plan_tool_executor=MagicMock(),
    )
    gate_path = worker_module._resolve_gate_config_path()
    assert gate_path is not None and gate_path.exists()
    worker.gate_engine = GateEngine.from_yaml(gate_path)

    await worker._execute_job(job)

    final_job = await job_store.get("job-plan-2")
    assert final_job.state == JobState.FAILED
    assert final_job.exit_code == 1
    assert "Postcheck blocked" in (final_job.error_message or "")


pytestmark = pytest.mark.unit
