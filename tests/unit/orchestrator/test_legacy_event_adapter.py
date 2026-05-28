"""T7: legacy stream replay adapter tests."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter


def test_adapt_trace_fixture_to_typed_analysis_stream_events():
    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisCompletedEventV1,
        AnalysisStreamEventV1,
        JobStartedEventV1,
        ToolCallFinishedEventV1,
        ToolCallStartedEventV1,
        UnknownEventV1,
    )
    from brain_researcher.services.orchestrator.legacy_event_adapter import (
        adapt_trace_event,
    )

    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "orchestrator"
        / "legacy_trace_sample.jsonl"
    )
    lines = fixture_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 5

    adapter = TypeAdapter(AnalysisStreamEventV1)
    events = []
    for line in lines:
        raw = json.loads(line)
        evt = adapt_trace_event(raw)
        # Ensure it passes union validation (typed contract).
        validated = adapter.validate_python(evt.model_dump(exclude_none=True))
        events.append(validated)

    assert isinstance(events[0], JobStartedEventV1)
    assert events[0].seq == 1
    assert isinstance(events[1], ToolCallStartedEventV1)
    assert events[1].seq == 2
    assert isinstance(events[2], ToolCallFinishedEventV1)
    assert events[2].seq == 3
    assert isinstance(events[3], UnknownEventV1)
    assert events[3].payload.raw_event_type == "legacy_custom"
    assert isinstance(events[4], AnalysisCompletedEventV1)
    assert events[4].seq == 5


def test_adapt_job_event_infers_ids_and_timestamp():
    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisStreamEventV1,
        JobStartedEventV1,
    )
    from brain_researcher.core.contracts.job import JobRecordV1
    from brain_researcher.services.orchestrator.job_store import JobEvent
    from brain_researcher.services.orchestrator.legacy_event_adapter import (
        adapt_job_event,
    )

    record = JobRecordV1(job_id="job_1", status="queued")
    job_evt = JobEvent(
        event_id=12,
        job_id="job_1",
        event_type="job_started",
        payload={"worker_id": "w1"},
        created_at=1,
    )
    typed = adapt_job_event(job_evt, record=record, run_id="run_1")
    validated = TypeAdapter(AnalysisStreamEventV1).validate_python(
        typed.model_dump(exclude_none=True)
    )
    assert isinstance(validated, JobStartedEventV1)
    assert validated.seq == 12
    assert validated.ids.job_id == "job_1"
    assert validated.ids.run_id == "run_1"


def test_adapt_trace_event_maps_stage_warning_and_agent_tool_events():
    from brain_researcher.core.contracts.analysis_stream import (
        StageEventV1,
        StageStatusV1,
        ToolCallFinishedEventV1,
        ToolCallStartedEventV1,
        WarningEventV1,
    )
    from brain_researcher.services.orchestrator.legacy_event_adapter import (
        adapt_trace_event,
    )

    tool_started = adapt_trace_event(
        {
            "schema_version": "trace-event-v1",
            "run_id": "run_1",
            "event_type": "tool.started",
            "timestamp": "2026-01-31T00:00:01Z",
            "event_id": "1",
            "payload": {
                "job_id": "job_1",
                "tool_call_id": "tc_1",
                "tool_id": "fsl.bet",
            },
        }
    )
    assert isinstance(tool_started, ToolCallStartedEventV1)
    assert tool_started.payload.tool_id == "fsl.bet"

    tool_finished = adapt_trace_event(
        {
            "schema_version": "trace-event-v1",
            "run_id": "run_1",
            "event_type": "tool.finished",
            "timestamp": "2026-01-31T00:00:02Z",
            "event_id": "2",
            "payload": {
                "job_id": "job_1",
                "tool_call_id": "tc_1",
                "tool_id": "fsl.bet",
                "status": "success",
                "run_dir": "/tmp/run_1",
                "provenance_path": "/tmp/run_1/provenance.json",
            },
        }
    )
    assert isinstance(tool_finished, ToolCallFinishedEventV1)
    assert tool_finished.payload.artifacts

    stage_evt = adapt_trace_event(
        {
            "schema_version": "trace-event-v1",
            "run_id": "run_1",
            "event_type": "step_started",
            "timestamp": "2026-01-31T00:00:03Z",
            "event_id": "3",
            "payload": {
                "job_id": "job_1",
                "step_id": "step_1",
                "tool": "fsl.bet",
                "attempt": 1,
            },
        }
    )
    assert isinstance(stage_evt, StageEventV1)
    assert stage_evt.payload.stage == "step"
    assert stage_evt.payload.status == StageStatusV1.started
    assert stage_evt.payload.stage_id == "step_1"

    warning = adapt_trace_event(
        {
            "schema_version": "trace-event-v1",
            "run_id": "run_1",
            "event_type": "tool.blocked",
            "timestamp": "2026-01-31T00:00:04Z",
            "event_id": "4",
            "payload": {
                "job_id": "job_1",
                "tool_call_id": "tc_2",
                "tool_id": "bad.tool",
                "violations": [],
            },
        }
    )
    assert isinstance(warning, WarningEventV1)


def test_adapt_job_event_maps_state_changed_audit_events_to_typed_statuses():
    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisCompletedEventV1,
        JobStartedEventV1,
        StageEventV1,
    )
    from brain_researcher.services.orchestrator.job_store import JobEvent
    from brain_researcher.services.orchestrator.legacy_event_adapter import (
        adapt_job_event,
    )

    running = adapt_job_event(
        JobEvent(
            event_id=1,
            job_id="job_1",
            event_type="state_changed:JobStatusV1.running",
            payload={},
            created_at=1,
        ),
        run_id="run_1",
    )
    assert isinstance(running, JobStartedEventV1)
    assert running.payload.status == "running"

    queued = adapt_job_event(
        JobEvent(
            event_id=2,
            job_id="job_1",
            event_type="state_changed:queued",
            payload={},
            created_at=2,
        ),
        run_id="run_1",
    )
    assert isinstance(queued, StageEventV1)
    assert queued.payload.stage == "job"
    assert queued.payload.status == "scheduled"

    failed = adapt_job_event(
        JobEvent(
            event_id=3,
            job_id="job_1",
            event_type="state_changed:JobStatusV1.failed",
            payload={"error_message": "runner failed"},
            created_at=3,
        ),
        run_id="run_1",
    )
    assert isinstance(failed, AnalysisCompletedEventV1)
    assert failed.payload.status == "failed"
    assert failed.payload.message == "runner failed"
