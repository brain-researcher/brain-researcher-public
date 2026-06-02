"""Provenance contract (v1).

Standardized execution evidence for a single tool/run invocation.

This is the target contract for RunRecorder / tool execution runtimes, but
existing producers may emit best-effort JSON that is not yet fully aligned.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .artifact import ArtifactV1
from .ids import IdsV1
from .policy_ref import PolicyRefV1, build_policy_ref_v1
from .version_ref import VersionRefV1, get_cached_version_ref_v1


class ProvenanceKindV1(str, Enum):
    tool = "tool"
    step = "step"
    workflow = "workflow"
    stage = "stage"
    pipeline = "pipeline"


class ProvenanceStatusV1(str, Enum):
    scheduled = "scheduled"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"
    timeout = "timeout"
    cancelled = "cancelled"


class ProvenanceTimestampsV1(BaseModel):
    started_at: float | None = None
    finished_at: float | None = None
    duration_sec: float | None = None


class ProvenanceRuntimeV1(BaseModel):
    container: dict[str, Any] | None = None
    sandbox: dict[str, Any] | None = None
    host: dict[str, Any] | None = None
    git: dict[str, Any] | None = None


class ProvenanceV1(BaseModel):
    schema_version: Literal["provenance-v1"] = "provenance-v1"

    # M0 primitives (first-class; stable envelope)
    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    run_id: str = Field(description="Execution run identifier (tool/run recorder id)")
    kind: ProvenanceKindV1 = ProvenanceKindV1.tool
    status: ProvenanceStatusV1 = ProvenanceStatusV1.succeeded

    timestamps: ProvenanceTimestampsV1 | None = None

    command: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)

    inputs: list[ArtifactV1] = Field(default_factory=list)
    outputs: list[ArtifactV1] = Field(default_factory=list)

    exit_code: int | None = None
    error_message: str | None = None

    runtime: ProvenanceRuntimeV1 | None = None
    resources: dict[str, Any] | None = None

    # Optional log pointers (prefer representing logs as ArtifactV1 in inputs/outputs).
    logs: dict[str, Any] | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _backfill_ids(self) -> "ProvenanceV1":
        if self.ids.run_id is None and self.run_id:
            self.ids.run_id = self.run_id
        if self.ids.job_id is None:
            # Best-effort: infer from embedded artifacts if present.
            for art in self.outputs or []:
                if art.job_id:
                    self.ids.job_id = art.job_id
                    break
        if self.ids.analysis_id is None and self.ids.job_id is not None:
            self.ids.analysis_id = self.ids.job_id
        return self


__all__ = [
    "ProvenanceKindV1",
    "ProvenanceStatusV1",
    "ProvenanceTimestampsV1",
    "ProvenanceRuntimeV1",
    "ProvenanceV1",
]
