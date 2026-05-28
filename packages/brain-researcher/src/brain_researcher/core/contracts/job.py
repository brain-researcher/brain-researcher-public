"""Job contracts (v1).

Defines the canonical, strongly-typed representation of a Job.

Notes:
- In P0, `analysis_id == job_id` is treated as an aliasing rule. The contracts
  expose only `job_id` as canonical, while accepting `analysis_id` as an input
  alias for backward compatibility.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from .artifact import ArtifactV1
from .ids import IdsV1
from .policy_ref import PolicyRefV1, build_policy_ref_v1
from .version_ref import VersionRefV1, get_cached_version_ref_v1

JobId = str


class JobStatusV1(str, Enum):
    pending = "pending"
    queued = "queued"
    claimed = "claimed"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    cancelling = "cancelling"
    timeout = "timeout"
    skipped = "skipped"
    paused = "paused"
    retrying = "retrying"


class JobSpecV1(BaseModel):
    """Stable job request/specification (v1)."""

    schema_version: Literal["job-spec-v1"] = "job-spec-v1"

    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    prompt: str | None = Field(default=None, description="User prompt / request")
    pipeline: str | None = Field(default=None, description="Requested pipeline/kind")
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobRecordV1(BaseModel):
    """Durable job record / API-facing job resource (v1)."""

    schema_version: Literal["job-record-v1"] = "job-record-v1"

    # M0 primitives (first-class; stable envelope)
    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    job_id: JobId = Field(
        ...,
        description="Job identifier (canonical; analysis_id is an alias)",
        validation_alias=AliasChoices("job_id", "analysis_id", "id"),
    )
    status: JobStatusV1 = Field(
        ...,
        description="Current job status",
        validation_alias=AliasChoices("status", "state"),
    )

    kind: str | None = Field(default=None, description="Job kind/pipeline")
    spec: JobSpecV1 | dict[str, Any] | None = None

    # Legacy/staging payload used by the orchestrator worker/executor.
    # Prefer `spec` for new integrations.
    payload_json: str | None = Field(
        default="{}",
        description="Legacy opaque job payload (JSON string)",
    )
    priority: int | None = Field(
        default=0, description="Scheduling priority (higher = sooner)"
    )

    created_at: int | None = Field(default_factory=lambda: int(time.time()))
    queued_at: int | None = None
    claimed_at: int | None = None
    started_at: int | None = None
    finished_at: int | None = None
    run_after: int | None = Field(
        default=None, description="Delayed execution timestamp (epoch seconds)"
    )

    # Worker lease management
    worker_id: str | None = None
    lease_expires_at: int | None = None
    last_heartbeat: int | None = None

    attempt: int | None = Field(
        default=0, description="Current attempt number (0-based)"
    )
    max_attempts: int | None = Field(default=3, description="Maximum attempts")

    run_id: str | None = None
    run_dir: str | None = Field(
        default=None,
        description="Run directory reference (prefer a store-relative path when exposed)",
    )
    provenance_path: str | None = Field(
        default=None,
        description="Provenance reference (prefer a store-relative path when exposed)",
    )

    exit_code: int | None = None
    error_message: str | None = None
    cancellation_requested: bool | None = Field(default=False)
    cancel_reason: str | None = None
    skip_reason: str | None = None

    # Resource requirements (best-effort; may be omitted by some backends).
    gpu_req: int | None = Field(default=0, description="GPU slots requested")
    gpu_type: str | None = None
    cpus: int | None = Field(default=1)
    memory_gb: float | None = Field(default=4.0)
    walltime_minutes: int | None = Field(default=60)
    backend: str | None = Field(
        default=None, description="Execution backend (local/slurm/...)"
    )
    job_name: str | None = None

    # User/session tracking (redundant with ids.user_id/session_id for compatibility).
    user_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None

    artifacts: list[ArtifactV1] = Field(default_factory=list)

    @property
    def state(self) -> JobStatusV1:
        """Legacy alias for `status` (used by JobStore)."""
        return self.status

    @state.setter
    def state(self, value: Any) -> None:
        normalized = self._normalize_status(value)
        if isinstance(normalized, JobStatusV1):
            self.status = normalized
            return
        raw = getattr(normalized, "value", normalized)
        if isinstance(raw, str):
            self.status = JobStatusV1(raw)
            return
        self.status = normalized  # type: ignore[assignment]

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> Any:
        """Normalize legacy status values to the canonical enum."""
        if value is None:
            return value
        if isinstance(value, JobStatusV1):
            return value
        raw = getattr(value, "value", value)
        if not isinstance(raw, str):
            return raw
        normalized = raw.strip().lower()
        if normalized in {"completed", "complete", "done", "success", "successful"}:
            return JobStatusV1.succeeded
        if normalized == "canceled":
            return JobStatusV1.cancelled
        return normalized

    @model_validator(mode="after")
    def _backfill_ids(self) -> JobRecordV1:
        if self.ids.job_id is None:
            self.ids.job_id = self.job_id
        if self.ids.analysis_id is None:
            # P0 convention: analysis_id == job_id
            self.ids.analysis_id = self.job_id
        if self.run_id and self.ids.run_id is None:
            self.ids.run_id = self.run_id
        if self.user_id and self.ids.user_id is None:
            self.ids.user_id = self.user_id
        if self.session_id and self.ids.session_id is None:
            self.ids.session_id = self.session_id
        if self.project_id and self.ids.workspace_id is None:
            self.ids.workspace_id = self.project_id
        return self


__all__ = ["JobId", "JobStatusV1", "JobSpecV1", "JobRecordV1"]
