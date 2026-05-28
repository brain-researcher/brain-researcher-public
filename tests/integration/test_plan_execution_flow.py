"""Integration test covering plan -> run_plan -> SSE handshake."""

import asyncio
import json
from datetime import datetime

from brain_researcher.services.agent.web_service import app
from brain_researcher.services.orchestrator import main_enhanced
from brain_researcher.services.orchestrator.models import JobStatus, TimingInfo
from tests.unit.agent.job_store_test_utils import patched_job_store


def _decode_sse_chunk(chunk: bytes) -> tuple[str, dict]:
    if isinstance(chunk, dict):
        event = chunk.get("event", "")
        data = chunk.get("data")
        payload = json.loads(data) if isinstance(data, str) else (data or {})
        return event, payload

    text = chunk.decode("utf-8")
    event = None
    data_line = None
    for line in text.splitlines():
        if line.startswith("event: "):
            event = line.split(": ", 1)[1]
        if line.startswith("data: "):
            data_line = line.split(": ", 1)[1]
    payload = json.loads(data_line) if data_line else {}
    return event or "", payload


def test_plan_execution_flow_happy_path(monkeypatch):
    client = app.test_client()
    plan_payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {"fmri_img": "bold.nii.gz", "atlas_name": "Schaefer2018_200"},
    }

    plan_response = client.post("/agent/plan", json=plan_payload)
    assert plan_response.status_code == 200
    plan = plan_response.get_json()

    run_request = {
        "plan_id": plan["plan_id"],
        "version": plan["version"],
        "por_token": plan["por_token"],
    }

    with patched_job_store(monkeypatch) as store:
        run_response = client.post("/agent/run_plan", json=run_request)

        assert run_response.status_code == 202
        job_info = run_response.get_json()
        job_id = job_info["job_id"]
        assert job_info["stream_url"].endswith(f"/jobs/{job_id}/stream")
        assert job_info["steps_url"].endswith(f"/api/jobs/{job_id}/steps")
        assert store.enqueued_jobs and store.enqueued_jobs[0].job_id == job_id

        class _StubJob:
            def __init__(self, job_id: str):
                self.id = job_id
                self.status = JobStatus.PENDING
                self.prompt = "plan-execution-flow"
                self.timing = TimingInfo(start_time=datetime.utcnow())

            def model_dump(self, *_, **__):
                return {
                    "id": self.id,
                    "status": self.status.value if hasattr(self.status, "value") else self.status,
                    "prompt": self.prompt,
                    "timing": {
                        "start_time": self.timing.start_time.isoformat() if self.timing.start_time else None
                    },
                }

        main_enhanced.jobs_db[job_id] = _StubJob(job_id)

        queue = main_enhanced.job_updates[job_id]

        async def _exercise_stream():
            await queue.put({"type": "step_started", "step_id": "s-1", "plan_id": plan["plan_id"]})
            await queue.put({"type": "step_completed", "step_id": "s-1", "state": "succeeded"})
            await queue.put({"type": "plan_completed", "plan_id": plan["plan_id"], "state": "completed"})

            response = await main_enhanced.stream_job_updates(job_id)
            generator = response.body_iterator

            init_chunk = await generator.__anext__()
            event_chunk = await generator.__anext__()
            completion_chunk = await generator.__anext__()
            final_chunk = await generator.__anext__()

            init_event, init_payload = _decode_sse_chunk(init_chunk)
            assert init_event == "init"
            assert init_payload["id"] == job_id

            event_name, payload = _decode_sse_chunk(event_chunk)
            assert event_name == "step_started"
            assert payload["step_id"] == "s-1"

            completion_name, completion_payload = _decode_sse_chunk(completion_chunk)
            assert completion_name == "step_completed"
            assert completion_payload["step_id"] == "s-1"

            final_name, final_payload = _decode_sse_chunk(final_chunk)
            assert final_name == "plan_completed"
            assert final_payload["plan_id"] == plan["plan_id"]

        asyncio.run(_exercise_stream())

    # Clean up
    main_enhanced.jobs_db.pop(job_id, None)
