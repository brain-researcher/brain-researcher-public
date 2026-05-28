"""Trace event schema (v1) for append-only event logs.

This is the internal, crash-tolerant event stream written to `trace.jsonl`.
It is intentionally different from ATIF: ATIF is a final aggregated document,
while trace events are streaming/debug-oriented.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .ids import IdsV1
from .policy_ref import PolicyRefV1, build_policy_ref_v1
from .version_ref import VersionRefV1, get_cached_version_ref_v1


class TraceEventV1(BaseModel):
    schema_version: Literal["trace-event-v1"] = "trace-event-v1"

    # M0 primitives (first-class; stable envelope)
    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    run_id: str
    event_type: str
    timestamp: str
    # M1: Stable identifier for stream↔trace correlation (may be overridden by callers).
    event_id: str = Field(default_factory=lambda: f"tev_{_uuid.uuid4().hex[:10]}")
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _backfill_ids(self) -> TraceEventV1:
        if self.ids.run_id is None:
            self.ids.run_id = self.run_id

        payload = self.payload if isinstance(self.payload, dict) else {}
        for key in (
            "job_id",
            "analysis_id",
            "request_id",
            "trace_id",
            "workspace_id",
            "user_id",
            "session_id",
        ):
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            if getattr(self.ids, key) is None:
                setattr(self.ids, key, value)

        if self.ids.analysis_id is None and self.ids.job_id is not None:
            self.ids.analysis_id = self.ids.job_id

        return self


__all__ = ["TraceEventV1"]
