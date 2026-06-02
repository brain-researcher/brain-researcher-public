"""Tool call trace contract (v1).

This captures an individual tool execution in a way that can be surfaced in:
- API responses (debug payloads)
- persistent run bundles (analysis_bundle.json)
- benchmark graders
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallTraceV1(BaseModel):
    schema_version: Literal["tool-call-trace-v1"] = "tool-call-trace-v1"

    tool_call_id: str
    tool_id: str
    tool_version: str | None = None

    params: dict[str, Any] = Field(default_factory=dict)
    resolved_inputs: dict[str, Any] | None = None

    started_at: int | None = None
    finished_at: int | None = None
    status: str = "scheduled"

    run_dir: str | None = None
    provenance_ref: str | None = None

    stdout_ref: str | None = None
    stderr_ref: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)

    error_class: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ToolCallTraceV1"]
