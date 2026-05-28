from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from brain_researcher.services.orchestrator import main_enhanced as orchestrator
from brain_researcher.services.orchestrator.models import RunRequest


@pytest.fixture(autouse=True)
def reset_orchestrator_state(monkeypatch):
    orchestrator.jobs_db.clear()
    orchestrator.job_queue.clear()
    orchestrator.job_updates.clear()
    monkeypatch.setattr(orchestrator, "execute_job", AsyncMock(return_value=None))
    monkeypatch.setattr(
        orchestrator.NotificationManager,
        "create_notification",
        AsyncMock(return_value=None),
    )
    yield
    orchestrator.jobs_db.clear()
    orchestrator.job_queue.clear()
    orchestrator.job_updates.clear()


@pytest.mark.asyncio
async def test_create_run_preflight_hard_fail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BR_PREFLIGHT_MODE", "HARD_FAIL")
    monkeypatch.setenv("BR_PREFLIGHT_MIN_DISK_GB", "0.0001")

    request = RunRequest(prompt="Run analysis", parameters={"input": str(tmp_path / "missing.nii")})
    assert request.parameters == {"input": str(tmp_path / "missing.nii")}

    from brain_researcher.services.agent.preflight import (
        PreflightConfig,
        PreflightMode,
        run_preflight,
    )

    assert PreflightMode.from_env() is PreflightMode.HARD_FAIL
    manual_report = run_preflight(
        tool_name=None,
        params=request.parameters,
        config=PreflightConfig(min_disk_gb=0.0001, check_timeout_sec=2, root_path=tmp_path),
    )
    assert manual_report.ok is False

    from brain_researcher.services.agent.preflight import PreflightItem, PreflightReport

    forced_report = PreflightReport(blockers=[PreflightItem(check="forced", ok=False)])
    monkeypatch.setattr(orchestrator, "run_preflight", lambda *args, **kwargs: forced_report)

    with pytest.raises(HTTPException) as excinfo:
        await orchestrator.create_run(request, current_user=None)

    assert excinfo.value.status_code == 400
    payload = excinfo.value.detail
    assert payload["error"] == "preflight_failed"
    assert payload["report"]["ok"] is False


@pytest.mark.asyncio
async def test_create_run_preflight_warn(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BR_PREFLIGHT_MODE", "WARN")
    monkeypatch.setenv("BR_PREFLIGHT_MIN_DISK_GB", "0.0001")

    request = RunRequest(prompt="Run analysis", parameters={"input": str(tmp_path / "missing.nii")})
    from brain_researcher.services.agent.preflight import PreflightItem, PreflightReport

    forced_report = PreflightReport(blockers=[PreflightItem(check="forced", ok=False)])
    monkeypatch.setattr(orchestrator, "run_preflight", lambda *args, **kwargs: forced_report)

    response = await orchestrator.create_run(request, current_user=None)

    assert response.job_id in orchestrator.jobs_db
    metadata_report = orchestrator.jobs_db[response.job_id].metadata["preflight_report"]
    assert metadata_report["ok"] is False
    assert any(item["check"] == "forced" for item in metadata_report["blockers"])


@pytest.mark.asyncio
async def test_create_run_consumes_forwarded_plan(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BR_PLANNER_MODE", "disabled")

    from brain_researcher.services.agent.preflight import PreflightReport

    monkeypatch.setattr(orchestrator, "run_preflight", lambda *args, **kwargs: PreflightReport())

    forwarded_plan = {
        "plan_id": "client-plan",
        "version": 1,
        "resolvable": True,
        "dag": {"steps": [], "artifacts": []},
        "context": {"query": "Forwarded"},
    }

    request = RunRequest(
        prompt="Use forwarded plan",
        parameters={
            "tool": "fsl.bet",
            "input": str(tmp_path / "input.nii"),
            "_client_metadata": {
                "plan_envelope": forwarded_plan,
                "normalized_tags": ["demo", "fast"],
            },
        },
    )

    response = await orchestrator.create_run(request, current_user=None)

    job = orchestrator.jobs_db[response.job_id]
    assert job.plan_of_record == forwarded_plan
    assert job.metadata["plan_of_record"] == forwarded_plan
    assert job.metadata["client_plan_envelope"] == forwarded_plan
    assert job.metadata["submitted_tags"] == ["demo", "fast"]


@pytest.mark.asyncio
async def test_create_run_normalizes_and_persists_checkpoint_id(monkeypatch) -> None:
    monkeypatch.setenv("BR_PLANNER_MODE", "disabled")

    from brain_researcher.services.agent.preflight import PreflightReport

    monkeypatch.setattr(orchestrator, "run_preflight", lambda *args, **kwargs: PreflightReport())

    request = RunRequest.model_validate(
        {
            "prompt": "Resume checkpointed analysis",
            "pipeline": "chat",
            "resume_checkpoint_id": "ck-run-001",
        }
    )

    assert request.checkpoint_id == "ck-run-001"

    response = await orchestrator.create_run(request, current_user=None)

    job = orchestrator.jobs_db[response.job_id]
    assert job.metadata["checkpoint_id"] == "ck-run-001"
    assert job.metadata["parameters"]["checkpoint_id"] == "ck-run-001"


@pytest.mark.asyncio
async def test_create_run_demo_seed_honors_requested_job_id(monkeypatch) -> None:
    monkeypatch.setenv("BR_PLANNER_MODE", "disabled")

    from brain_researcher.services.agent.preflight import PreflightReport

    monkeypatch.setattr(orchestrator, "run_preflight", lambda *args, **kwargs: PreflightReport())

    request = RunRequest(
        prompt="Seed deterministic demo run",
        pipeline="demo",
        requested_job_id="demo_run_123",
        thread_id="demo_demo-run",
        parameters={
            "demo": True,
            "demo_seed": True,
            "demo_id": "demo-run",
        },
    )

    current_user = SimpleNamespace(id="demo-seed", role="demo", provider="demo-seed")

    response = await orchestrator.create_run(request, current_user=current_user)

    assert response.job_id == "demo_run_123"
    assert response.analysis_id == "demo_run_123"
    job = orchestrator.jobs_db["demo_run_123"]
    assert job.status == orchestrator.JobStatus.COMPLETED
    assert job.run_id == "demo_run_123"
    assert job.metadata["demo_seed"] is True
    assert job.metadata["demo_metadata"]["seeded"] is True
    assert job.steps[0].tool == "demo-seed"
