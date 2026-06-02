"""Typed analysis stream events (v1).

This defines a fixed set of replayable, typed events for `analysis.stream`.

Non-scope (by design):
- Does not change orchestrator emitters yet (they currently emit generic StreamEventV1).
- Does not change the web UI event handling yet.

The canonical contract is `AnalysisStreamEventV1`, a discriminated union on
`event_type`.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from .artifact import ArtifactV1
from .ids import IdsV1
from .job import JobStatusV1


class AnalysisStreamEventTypeV1(str, Enum):
    job_started = "job.started"
    tool_call_started = "tool.call.started"
    tool_call_finished = "tool.call.finished"
    artifact_written = "artifact.written"
    log_line = "log.line"
    observation_appended = "observation.appended"
    stage = "stage"
    warning = "warning"
    metric = "metric"
    analysis_completed = "analysis.completed"
    error = "error"
    unknown = "unknown"


class AnalysisStreamBaseEventV1(BaseModel):
    """Shared event envelope fields."""

    schema_version: Literal["analysis-stream-event-v1"] = "analysis-stream-event-v1"
    ids: IdsV1 = Field(default_factory=IdsV1)

    # Monotonic sequence within a job stream (e.g., JobStore event_id).
    seq: int
    timestamp: str

    # Discriminator. Subclasses fix this to a Literal value.
    event_type: str


class JobStartedPayloadV1(BaseModel):
    status: JobStatusV1 = JobStatusV1.running
    message: str | None = None


class JobStartedEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.job_started.value] = (
        AnalysisStreamEventTypeV1.job_started.value
    )
    payload: JobStartedPayloadV1 = Field(default_factory=JobStartedPayloadV1)


class ToolCallStartedPayloadV1(BaseModel):
    tool_call_id: str
    tool_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class ToolCallStartedEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.tool_call_started.value] = (
        AnalysisStreamEventTypeV1.tool_call_started.value
    )
    payload: ToolCallStartedPayloadV1


class ToolCallStatusV1(str, Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    timeout = "timeout"
    cancelled = "cancelled"
    partial = "partial"


class ToolCallFinishedPayloadV1(BaseModel):
    tool_call_id: str
    status: ToolCallStatusV1
    artifacts: list[ArtifactV1] = Field(default_factory=list)
    error_message: str | None = None


class ToolCallFinishedEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.tool_call_finished.value] = (
        AnalysisStreamEventTypeV1.tool_call_finished.value
    )
    payload: ToolCallFinishedPayloadV1


class ArtifactWrittenPayloadV1(BaseModel):
    artifact: ArtifactV1


class ArtifactWrittenEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.artifact_written.value] = (
        AnalysisStreamEventTypeV1.artifact_written.value
    )
    payload: ArtifactWrittenPayloadV1


class LogStreamV1(str, Enum):
    stdout = "stdout"
    stderr = "stderr"


class LogLinePayloadV1(BaseModel):
    stream: LogStreamV1
    line: str


class LogLineEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.log_line.value] = (
        AnalysisStreamEventTypeV1.log_line.value
    )
    payload: LogLinePayloadV1


class ObservationAppendedPayloadV1(BaseModel):
    observation: ArtifactV1


class ObservationAppendedEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.observation_appended.value] = (
        AnalysisStreamEventTypeV1.observation_appended.value
    )
    payload: ObservationAppendedPayloadV1


class StageStatusV1(str, Enum):
    scheduled = "scheduled"
    started = "started"
    retrying = "retrying"
    completed = "completed"
    warned = "warned"
    blocked = "blocked"
    failed = "failed"
    skipped = "skipped"


class StagePayloadV1(BaseModel):
    stage: str
    status: StageStatusV1
    stage_id: str | None = None
    tool_id: str | None = None
    attempt: int | None = None
    duration_ms: int | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class StageEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.stage.value] = (
        AnalysisStreamEventTypeV1.stage.value
    )
    payload: StagePayloadV1


class WarningPayloadV1(BaseModel):
    message: str
    code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WarningEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.warning.value] = (
        AnalysisStreamEventTypeV1.warning.value
    )
    payload: WarningPayloadV1


class MetricPayloadV1(BaseModel):
    name: str
    value: float
    unit: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class MetricEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.metric.value] = (
        AnalysisStreamEventTypeV1.metric.value
    )
    payload: MetricPayloadV1


class AnalysisCompletedPayloadV1(BaseModel):
    status: JobStatusV1
    message: str | None = None


class AnalysisCompletedEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.analysis_completed.value] = (
        AnalysisStreamEventTypeV1.analysis_completed.value
    )
    payload: AnalysisCompletedPayloadV1


class ErrorPayloadV1(BaseModel):
    message: str
    error_class: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.error.value] = (
        AnalysisStreamEventTypeV1.error.value
    )
    payload: ErrorPayloadV1


class UnknownEventPayloadV1(BaseModel):
    raw_event_type: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class UnknownEventV1(AnalysisStreamBaseEventV1):
    event_type: Literal[AnalysisStreamEventTypeV1.unknown.value] = (
        AnalysisStreamEventTypeV1.unknown.value
    )
    payload: UnknownEventPayloadV1


AnalysisStreamEventV1 = Annotated[
    Union[
        JobStartedEventV1,
        ToolCallStartedEventV1,
        ToolCallFinishedEventV1,
        ArtifactWrittenEventV1,
        LogLineEventV1,
        ObservationAppendedEventV1,
        StageEventV1,
        WarningEventV1,
        MetricEventV1,
        AnalysisCompletedEventV1,
        ErrorEventV1,
        UnknownEventV1,
    ],
    Field(discriminator="event_type"),
]


__all__ = [
    "AnalysisStreamEventTypeV1",
    "AnalysisStreamBaseEventV1",
    "JobStartedPayloadV1",
    "JobStartedEventV1",
    "ToolCallStartedPayloadV1",
    "ToolCallStartedEventV1",
    "ToolCallStatusV1",
    "ToolCallFinishedPayloadV1",
    "ToolCallFinishedEventV1",
    "ArtifactWrittenPayloadV1",
    "ArtifactWrittenEventV1",
    "LogStreamV1",
    "LogLinePayloadV1",
    "LogLineEventV1",
    "ObservationAppendedPayloadV1",
    "ObservationAppendedEventV1",
    "StageStatusV1",
    "StagePayloadV1",
    "StageEventV1",
    "WarningPayloadV1",
    "WarningEventV1",
    "MetricPayloadV1",
    "MetricEventV1",
    "AnalysisCompletedPayloadV1",
    "AnalysisCompletedEventV1",
    "ErrorPayloadV1",
    "ErrorEventV1",
    "UnknownEventPayloadV1",
    "UnknownEventV1",
    "AnalysisStreamEventV1",
]
