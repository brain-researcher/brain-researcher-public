from __future__ import annotations

from datetime import datetime

import pytest

from brain_researcher.services.orchestrator import main_enhanced as orch
from brain_researcher.services.orchestrator.models import Job, JobStatus, StepStatus, TimingInfo


def _plan_with_hyphen_step_id() -> dict:
    return {
        "plan_id": "plan_trace_test",
        "version": 1,
        "schema_version": "1.0",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "resolvable": True,
        "dag": {
            "steps": [
                {
                    "id": "step-001",
                    "tool": "workflow_rest_connectome_e2e",
                    "consumes": {},
                    "produces": {},
                    "params": {
                        "img": "/missing/sub-01_task-rest_bold.nii.gz",
                        "output_dir": "/tmp/br-test",
                    },
                    "metadata": {},
                    "runtime_kind": "python",
                }
            ],
            "artifacts": [],
        },
        "estimates": {},
        "warnings": [],
        "chosen_tool": "workflow_rest_connectome_e2e",
        "selection_reason": "unit_test",
    }


@pytest.mark.asyncio
async def test_agent_plan_failure_preserves_step_trace(monkeypatch):
    async def fake_run_plan(run_request, on_event=None):
        assert run_request.plan_id == "plan_trace_test"
        events = [
            {
                "event": "step_started",
                "data": {"step_id": "step-001", "tool": "workflow_rest_connectome_e2e"},
            },
            {
                "event": "step_failed",
                "data": {
                    "step_id": "step-001",
                    "tool": "workflow_rest_connectome_e2e",
                    "error": "ValueError: File not found",
                },
            },
            {
                "event": "plan_failed",
                "data": {
                    "state": "failed",
                    "error": "ValueError: File not found",
                },
            },
        ]
        for event in events:
            await on_event(event)
        return events

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(orch.EnhancedAgentClient, "run_plan", fake_run_plan)
    monkeypatch.setattr(orch, "notify_job_update", noop)
    monkeypatch.setattr(orch, "update_job_progress", noop)

    job = Job(
        id="job_trace_test",
        status=JobStatus.PENDING,
        prompt="run connectome",
        timing=TimingInfo(start_time=datetime.utcnow()),
        metadata={"plan_execute": True},
        plan_of_record=_plan_with_hyphen_step_id(),
        por_token="por-test-token",
    )

    executed = await orch._run_agent_plan_for_job(job)

    assert executed is True
    assert job.steps[0].id == "step_001"
    assert job.steps[0].metadata["canonical_step_id"] == "step-001"
    assert job.steps[0].status == StepStatus.FAILED
    assert job.steps[0].preview == "ValueError: File not found"
    assert job.status == JobStatus.FAILED
    assert job.error is not None
    assert job.error.error["message"] == "ValueError: File not found"
    assert [event["event"] for event in job.plan_events] == [
        "step_started",
        "step_failed",
        "plan_failed",
    ]
    assert job.metadata["plan_events"] == job.plan_events
