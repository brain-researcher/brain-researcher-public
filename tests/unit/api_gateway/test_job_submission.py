"""Legacy api_gateway compatibility tests for job submission helpers."""

import os

import pytest
from fastapi import HTTPException

if os.getenv("BR_ENABLE_LEGACY_GATEWAY_TESTS", "0").lower() not in {"1", "true", "yes", "on"}:
    pytest.skip(
        "Legacy api_gateway compatibility coverage is disabled by default. Set BR_ENABLE_LEGACY_GATEWAY_TESTS=1 to run it.",
        allow_module_level=True,
    )

import brain_researcher.legacy.api_gateway.job_submission as job_submission
from brain_researcher.legacy.api_gateway.job_submission import (
    Job,
    JobPriority,
    JobStatus,
    JobSubmissionRequest,
    JobSubmissionService,
    WorkflowType,
)


class DummyJobQueue:
    def __init__(self):
        self.submitted = []
        self.updated = []

    def submit(self, job: Job):
        self.submitted.append(job)

    def get_queue_position(self, job_id: str):
        return 1

    def _update_job(self, job: Job):
        self.updated.append((job.job_id, job.status))


class FakeOrchestratorClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.base_url = "https://orch.test"

    async def submit_run(self, payload):
        self.calls.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def absolute_url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{suffix}"


def make_service(*, delegate_runs: bool = False, orchestrator_client=None):
    job_submission.AGENT_AVAILABLE = False
    queue = DummyJobQueue()
    service = JobSubmissionService(
        queue,
        delegate_runs=delegate_runs,
        orchestrator_client=orchestrator_client,
    )
    return service, queue


@pytest.mark.asyncio
async def test_submit_job_delegates_to_orchestrator_returns_links():
    fake_response = (
        200,
        {
            "job_id": "job_remote",
            "cached": False,
            "estimated_duration": 45,
            "queue_position": 2,
            "status_url": "/jobs/job_remote",
            "stream_url": "/jobs/job_remote/stream",
        },
    )
    client = FakeOrchestratorClient([fake_response])
    service, _ = make_service(delegate_runs=True, orchestrator_client=client)

    request = JobSubmissionRequest(
        query="run connectivity",
        workflow_type=WorkflowType.PREPROCESSING,
        dataset_id="ds001",
        parameters={"tool": "fsl.bet"},
        priority=JobPriority.HIGH,
        timeout_seconds=600,
        retry_on_failure=True,
        max_retries=1,
        tags=["Demo", " demo ", "EXTRA"],
    )

    response = await service.submit_job(request)

    assert response.job_id == "job_remote"
    assert response.status == JobStatus.PENDING
    assert "status" in response.links and response.links["status"].startswith("https://orch.test")
    payload = client.calls[0]
    assert payload["pipeline"] == "preprocessing"
    assert payload["parameters"]["tool"] == "fsl.bet"
    assert payload["parameters"]["tags"] == ["demo", "extra"]
    meta = payload["parameters"].get("_client_metadata", {})
    assert meta.get("normalized_tags") == ["demo", "extra"]
    assert meta.get("plan_envelope", {}).get("context", {}).get("tags") == ["demo", "extra"]


@pytest.mark.asyncio
async def test_submit_job_delegation_handles_cache_hits():
    fake_response = (
        200,
        {
            "job_id": "job_cached",
            "cached": True,
            "run_dir": "/tmp/run",
            "cache_key": "sha256:abc",
            "status_url": "/jobs/job_cached",
        },
    )
    client = FakeOrchestratorClient([fake_response])
    service, _ = make_service(delegate_runs=True, orchestrator_client=client)

    request = JobSubmissionRequest(
        query="reuse result",
        workflow_type=WorkflowType.ANALYSIS,
        dataset_id=None,
        parameters={},
        priority=JobPriority.NORMAL,
        timeout_seconds=300,
        retry_on_failure=False,
        max_retries=0,
        tags=["Reuse", "RESULT", "reuse"],
    )

    response = await service.submit_job(request)

    assert response.status == JobStatus.COMPLETED
    assert "cache_resolve" in response.links
    assert response.message.startswith("Result")
    payload = client.calls[0]
    assert payload["parameters"]["tags"] == ["reuse", "result"]
    cache_meta = payload["parameters"].get("_client_metadata", {})
    assert cache_meta.get("normalized_tags") == ["reuse", "result"]
    assert "plan_envelope" in cache_meta


@pytest.mark.asyncio
async def test_submit_job_delegation_propagates_http_errors():
    err = HTTPException(status_code=409, detail={"error": "duplicate"})
    client = FakeOrchestratorClient([err])
    service, _ = make_service(delegate_runs=True, orchestrator_client=client)

    request = JobSubmissionRequest(
        query="rerun",
        workflow_type=WorkflowType.CUSTOM,
        dataset_id=None,
        parameters={},
        priority=JobPriority.LOW,
        timeout_seconds=120,
        retry_on_failure=False,
        max_retries=0,
        tags=[],
    )

    with pytest.raises(HTTPException) as exc:
        await service.submit_job(request)

    assert exc.value.status_code == 409


def test_attach_plan_envelope_creates_stub_plan():
    service, _ = make_service()
    job = Job(
        job_id="job-123",
        query="skull strip",
        workflow_type=WorkflowType.ANALYSIS,
        dataset_id=None,
        parameters={},
        priority=JobPriority.NORMAL,
        status=JobStatus.PENDING,
        callback_url=None,
        timeout_seconds=3600,
        retry_on_failure=True,
        max_retries=1,
        tags=job_submission._normalize_tags(["Alpha", "BETA", "alpha"]),
    )
    request = JobSubmissionRequest(
        query="skull strip",
        workflow_type=WorkflowType.ANALYSIS,
        dataset_id=None,
        parameters={},
        priority=JobPriority.NORMAL,
        callback_url=None,
        timeout_seconds=3600,
        retry_on_failure=True,
        max_retries=1,
        tags=["Alpha", "BETA", "alpha"],
    )

    plan = service._attach_plan_envelope(job, request, job.tags)

    assert job.metadata["plan"] == plan
    assert plan["plan_id"] == job.job_id
    assert "dag" in plan and plan["dag"].get("steps") == []
    assert plan["context"].get("tags") == job.tags


@pytest.mark.asyncio
async def test_process_job_uses_plan_runner(monkeypatch):
    service, queue = make_service()
    job = Job(
        job_id="job-runner",
        query="noop",
        workflow_type=WorkflowType.ANALYSIS,
        dataset_id=None,
        parameters={},
        priority=JobPriority.NORMAL,
        status=JobStatus.PENDING,
        callback_url=None,
        timeout_seconds=3600,
        retry_on_failure=True,
        max_retries=1,
        tags=[],
    )
    job.metadata["plan"] = {
        "plan_id": job.job_id,
        "dag": {"steps": [], "artifacts": []},
        "context": {},
    }

    called = False

    class FakeRunner:
        async def run(self, run_job: Job):
            nonlocal called
            called = True
            run_job.status = JobStatus.COMPLETED
            run_job.completed_at = None

    service.plan_runner = FakeRunner()

    await service._process_job(job)

    assert called is True
    assert job.status == JobStatus.COMPLETED
    assert len(queue.updated) >= 1
