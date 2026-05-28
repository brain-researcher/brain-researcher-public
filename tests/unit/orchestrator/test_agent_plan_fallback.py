from datetime import datetime

import pytest

from brain_researcher.services.orchestrator import main_enhanced
from brain_researcher.services.orchestrator.job_management_endpoints import Job, JobStatus


def _make_plan_execution_job() -> Job:
    return Job(
        id="job_plan_fallback",
        name="plan fallback",
        prompt="run connectivity",
        status=JobStatus.PENDING,
        created_at=datetime.utcnow(),
        steps=[],
        artifacts=[],
        metadata={
            "plan_execute": True,
            "por_token": "dev-token",
            "parameters": {"tool": "workflow_rest_connectome_e2e"},
        },
        por_token="dev-token",
        plan_of_record={
            "plan_id": "plan_fallback",
            "version": 1,
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "dag": {
                "steps": [
                    {
                        "id": "workflow_rest_connectome_e2e",
                        "tool": "workflow_rest_connectome_e2e",
                        "params": {},
                    }
                ]
            },
        },
    )


@pytest.mark.asyncio
async def test_agent_plan_failure_before_step_start_falls_back_to_direct_tool(monkeypatch):
    job = _make_plan_execution_job()
    synced_jobs: list[Job] = []

    async def fake_run_plan(*args, **kwargs):
        raise RuntimeError("500 Internal Server Error")

    async def fake_sync_job_in_store(updated_job: Job):
        synced_jobs.append(updated_job)

    monkeypatch.setenv("BR_POR_TOKEN_ENFORCE", "false")
    monkeypatch.delenv("BR_POR_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("POR_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("BRAIN_RESEARCHER_POR_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(main_enhanced.EnhancedAgentClient, "run_plan", fake_run_plan)
    monkeypatch.setattr(
        main_enhanced.EnhancedJobManager,
        "_sync_job_in_store",
        fake_sync_job_in_store,
    )

    executed = await main_enhanced._run_agent_plan_for_job(job)

    assert executed is False
    assert job.steps == []
    assert job.metadata["plan_execution_fallback"] == "generic_pipeline"
    assert job.metadata["plan_execution_fallback_tool"] == "workflow_rest_connectome_e2e"
    assert "500 Internal Server Error" in job.metadata["plan_execution_error"]
    assert synced_jobs == [job]
