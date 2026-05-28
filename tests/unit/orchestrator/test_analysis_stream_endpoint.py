"""Unit tests for typed analysis stream SSE endpoint (T7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from brain_researcher.services.orchestrator.job_management_endpoints import router
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore


def _parse_sse_payloads(text: str) -> list[dict]:
    payloads: list[dict] = []
    current_event: str | None = None
    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            if not current_event:
                continue
            payloads.append(json.loads(line[6:]))
    return payloads


@pytest.fixture
def app_with_job_store():
    app = FastAPI()
    app.include_router(router)
    app.state.job_store = MemoryJobStore(total_gpu_slots=0)
    return app


@pytest.mark.asyncio
async def test_analysis_stream_emits_typed_events_from_job_store(app_with_job_store):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    job_id = "job_test_analysis_stream_001"
    await job_store.enqueue(
        JobRecord(
            job_id=job_id,
            kind="test",
            payload_json="{}",
            state=JobState.QUEUED,
        )
    )

    await job_store.append_event(job_id, "job.started", payload={"status": "running"})
    await job_store.append_event(
        job_id,
        "tool.call.started",
        payload={
            "tool_call_id": job_id,
            "tool_id": "fsl.bet",
            "params": {"infile": "a.nii.gz"},
        },
    )
    await job_store.append_event(
        job_id,
        "stage",
        payload={
            "stage": "preflight",
            "status": "warned",
            "stage_id": "step_1",
            "details": {"preflight_result": {"status": "warn", "violations": []}},
        },
    )
    await job_store.append_event(job_id, "legacy_custom", payload={"foo": "bar"})
    await job_store.append_event(
        job_id, "analysis.completed", payload={"status": "succeeded"}
    )

    with TestClient(app) as client:
        with client.stream(
            "GET",
            f"/api/jobs/{job_id}/analysis-stream?since=0",
            headers={"Accept": "text/event-stream"},
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())

    payloads = _parse_sse_payloads(content)
    assert payloads, content

    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisStreamEventTypeV1,
        AnalysisStreamEventV1,
        UnknownEventV1,
    )

    adapter = TypeAdapter(AnalysisStreamEventV1)
    events = [adapter.validate_python(p) for p in payloads]

    event_types = [e.event_type for e in events]
    assert AnalysisStreamEventTypeV1.job_started.value in event_types
    assert AnalysisStreamEventTypeV1.tool_call_started.value in event_types
    assert AnalysisStreamEventTypeV1.stage.value in event_types
    assert AnalysisStreamEventTypeV1.analysis_completed.value in event_types

    unknowns = [e for e in events if isinstance(e, UnknownEventV1)]
    assert unknowns, events
    assert unknowns[0].payload.raw_event_type == "legacy_custom"

    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))


@pytest.mark.asyncio
async def test_analysis_stream_resumes_after_since_and_last_event_id(
    app_with_job_store,
):
    app = app_with_job_store
    job_store: MemoryJobStore = app.state.job_store

    job_id = "job_test_analysis_stream_resume_001"
    await job_store.enqueue(
        JobRecord(
            job_id=job_id,
            kind="test",
            payload_json="{}",
            state=JobState.QUEUED,
        )
    )

    await job_store.append_event(
        job_id, "job.started", payload={"status": "running"}
    )  # 1
    await job_store.append_event(
        job_id,
        "stage",
        payload={
            "stage": "preflight",
            "status": "completed",
            "stage_id": "step_1",
            "details": {"preflight_result": {"status": "ok", "violations": []}},
        },
    )  # 2
    await job_store.append_event(
        job_id, "analysis.completed", payload={"status": "succeeded"}
    )  # 3

    with TestClient(app) as client:
        with client.stream(
            "GET",
            f"/api/jobs/{job_id}/analysis-stream?since=1",
            headers={"Accept": "text/event-stream"},
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())
    payloads = _parse_sse_payloads(content)
    assert payloads
    seqs = [p.get("seq") for p in payloads]
    assert all(isinstance(s, int) and s > 1 for s in seqs)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            f"/api/jobs/{job_id}/analysis-stream?since=0",
            headers={"Accept": "text/event-stream", "Last-Event-ID": "2"},
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())
    payloads = _parse_sse_payloads(content)
    assert payloads
    seqs = [p.get("seq") for p in payloads]
    assert seqs == [3]


def test_analysis_stream_replays_trace_jsonl_without_job_store(tmp_path: Path):
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "orchestrator"
        / "legacy_trace_sample.jsonl"
    )
    (tmp_path / "trace.jsonl").write_text(
        fixture_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/jobs/job_1/analysis-stream",
            params={"source": "trace", "run_dir": str(tmp_path), "since": 0},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())

    payloads = _parse_sse_payloads(content)
    assert payloads

    from brain_researcher.core.contracts.analysis_stream import AnalysisStreamEventV1

    adapter = TypeAdapter(AnalysisStreamEventV1)
    events = [adapter.validate_python(p) for p in payloads]
    assert events[0].seq == 1
    assert events[-1].event_type in {"analysis.completed", "unknown"}


def test_analysis_stream_trace_replay_resumes_after_last_event_id(tmp_path: Path):
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "orchestrator"
        / "legacy_trace_sample.jsonl"
    )
    (tmp_path / "trace.jsonl").write_text(
        fixture_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/jobs/job_1/analysis-stream",
            params={"source": "trace", "run_dir": str(tmp_path), "since": 0},
            headers={"Accept": "text/event-stream", "Last-Event-ID": "4"},
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())

    payloads = _parse_sse_payloads(content)
    assert payloads
    assert [p.get("seq") for p in payloads] == [5]


def test_analysis_stream_replays_typed_trace_jsonl_without_job_store(tmp_path: Path):
    (tmp_path / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "analysis-stream-event-v1",
                        "ids": {
                            "job_id": "job_1",
                            "analysis_id": "job_1",
                            "run_id": "run_1",
                        },
                        "seq": 1,
                        "timestamp": "2026-01-31T00:00:00Z",
                        "event_type": "job.started",
                        "payload": {"message": "started"},
                    }
                ),
                json.dumps(
                    {
                        "schema_version": "analysis-stream-event-v1",
                        "ids": {
                            "job_id": "job_1",
                            "analysis_id": "job_1",
                            "run_id": "run_1",
                        },
                        "seq": 2,
                        "timestamp": "2026-01-31T00:00:01Z",
                        "event_type": "analysis.completed",
                        "payload": {"status": "succeeded"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/jobs/job_1/analysis-stream",
            params={"source": "trace", "run_dir": str(tmp_path), "since": 0},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            assert resp.status_code == 200
            content = "".join(resp.iter_text())

    payloads = _parse_sse_payloads(content)
    assert payloads

    from brain_researcher.core.contracts.analysis_stream import AnalysisStreamEventV1

    adapter = TypeAdapter(AnalysisStreamEventV1)
    events = [adapter.validate_python(p) for p in payloads]
    assert [e.seq for e in events] == [1, 2]
    assert events[0].event_type == "job.started"
    assert events[-1].event_type == "analysis.completed"
