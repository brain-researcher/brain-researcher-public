import os

import pytest
from pydantic import TypeAdapter, ValidationError

os.environ.setdefault("BR_DISABLE_TOOL_RUNNER_IMPORT", "1")


def test_job_record_accepts_analysis_id_alias_and_normalizes_status():
    from brain_researcher.core.contracts.job import JobRecordV1, JobStatusV1

    payload = {
        "analysis_id": "job_abc123",
        "status": "completed",
        "kind": "glm",
    }

    record = JobRecordV1.model_validate(payload)
    assert record.job_id == "job_abc123"
    assert record.status == JobStatusV1.succeeded

    dumped = record.model_dump()
    assert "job_id" in dumped
    assert "analysis_id" not in dumped


def test_artifact_parses_legacy_checksum_and_size_fields():
    from brain_researcher.core.contracts.artifact import ArtifactKindV1, ArtifactV1

    payload = {
        "analysis_id": "job_1",
        "kind": "json",
        "path": "observation.json",
        "checksum": "sha256:" + ("a" * 64),
        "size": 123,
        "mime_type": "application/json",
        "tags": ["observation"],
    }

    artifact = ArtifactV1.model_validate(payload)
    assert artifact.job_id == "job_1"
    assert artifact.kind == ArtifactKindV1.json
    assert artifact.uri == "observation.json"
    assert artifact.sha256.startswith("sha256:")
    assert artifact.bytes == 123
    assert artifact.media_type == "application/json"
    assert artifact.tags == ["observation"]


def test_provenance_roundtrip_with_artifact_refs():
    from brain_researcher.core.contracts.artifact import ArtifactKindV1, ArtifactV1
    from brain_researcher.core.contracts.provenance import (
        ProvenanceKindV1,
        ProvenanceStatusV1,
        ProvenanceTimestampsV1,
        ProvenanceV1,
    )

    out_artifact = ArtifactV1(
        job_id="job_2",
        kind=ArtifactKindV1.log,
        media_type="text/plain",
        uri="stdout.txt",
        sha256="sha256:" + ("b" * 64),
        bytes=10,
        tags=["stdout"],
    )

    prov = ProvenanceV1(
        run_id="run_2",
        kind=ProvenanceKindV1.tool,
        status=ProvenanceStatusV1.succeeded,
        timestamps=ProvenanceTimestampsV1(
            started_at=1.0, finished_at=2.0, duration_sec=1.0
        ),
        command=["echo", "ok"],
        outputs=[out_artifact],
    )

    dumped = prov.model_dump(exclude_none=True)
    prov2 = ProvenanceV1.model_validate(dumped)
    assert prov2.run_id == "run_2"
    assert prov2.outputs[0].uri == "stdout.txt"
    assert prov2.ids.analysis_id == "job_2"


def test_analysis_stream_event_union_roundtrip_and_rejects_unknown():
    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisCompletedEventV1,
        AnalysisStreamEventTypeV1,
        AnalysisStreamEventV1,
        ErrorEventV1,
        ErrorPayloadV1,
        JobStartedEventV1,
        JobStartedPayloadV1,
        ToolCallFinishedEventV1,
        ToolCallFinishedPayloadV1,
        ToolCallStartedEventV1,
        ToolCallStartedPayloadV1,
        ToolCallStatusV1,
        UnknownEventPayloadV1,
        UnknownEventV1,
    )
    from brain_researcher.core.contracts.ids import IdsV1

    adapter = TypeAdapter(AnalysisStreamEventV1)

    started = JobStartedEventV1(
        ids=IdsV1(job_id="job_1", run_id="run_1", analysis_id="job_1"),
        seq=1,
        timestamp="2026-01-31T00:00:00Z",
        payload=JobStartedPayloadV1(message="started"),
    )
    result = adapter.validate_python(started.model_dump())
    assert isinstance(result, JobStartedEventV1)

    tc_started = ToolCallStartedEventV1(
        ids=IdsV1(job_id="job_1", run_id="run_1", analysis_id="job_1"),
        seq=2,
        timestamp="2026-01-31T00:00:01Z",
        payload=ToolCallStartedPayloadV1(
            tool_call_id="tc_1", tool_id="fsl.bet", params={"infile": "a.nii.gz"}
        ),
    )
    result = adapter.validate_python(tc_started.model_dump())
    assert isinstance(result, ToolCallStartedEventV1)

    tc_done = ToolCallFinishedEventV1(
        ids=IdsV1(job_id="job_1", run_id="run_1", analysis_id="job_1"),
        seq=3,
        timestamp="2026-01-31T00:00:02Z",
        payload=ToolCallFinishedPayloadV1(
            tool_call_id="tc_1", status=ToolCallStatusV1.succeeded, artifacts=[]
        ),
    )
    result = adapter.validate_python(tc_done.model_dump())
    assert isinstance(result, ToolCallFinishedEventV1)

    completed = AnalysisCompletedEventV1(
        ids=IdsV1(job_id="job_1", run_id="run_1", analysis_id="job_1"),
        seq=4,
        timestamp="2026-01-31T00:00:03Z",
        payload={"status": "succeeded"},
    )
    result = adapter.validate_python(completed.model_dump())
    assert isinstance(result, AnalysisCompletedEventV1)
    assert result.event_type == AnalysisStreamEventTypeV1.analysis_completed.value

    err = ErrorEventV1(
        ids=IdsV1(job_id="job_1", run_id="run_1", analysis_id="job_1"),
        seq=5,
        timestamp="2026-01-31T00:00:04Z",
        payload=ErrorPayloadV1(message="boom", error_class="RuntimeError"),
    )
    result = adapter.validate_python(err.model_dump())
    assert isinstance(result, ErrorEventV1)

    unknown = UnknownEventV1(
        ids=IdsV1(job_id="job_1", run_id="run_1", analysis_id="job_1"),
        seq=6,
        timestamp="2026-01-31T00:00:06Z",
        payload=UnknownEventPayloadV1(raw_event_type="legacy.event", raw_payload={"k": "v"}),
    )
    result = adapter.validate_python(unknown.model_dump())
    assert isinstance(result, UnknownEventV1)
    assert result.payload.raw_event_type == "legacy.event"

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "schema_version": "analysis-stream-event-v1",
                "ids": {"job_id": "job_1"},
                "seq": 99,
                "timestamp": "2026-01-31T00:00:05Z",
                "event_type": "unknown.event",
                "payload": {},
            }
        )
