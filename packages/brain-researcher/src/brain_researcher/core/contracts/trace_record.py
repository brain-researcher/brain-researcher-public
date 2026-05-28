"""Trace record schema (v1) for learnable traces."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel

from brain_researcher.core.contracts.violation import Violation


class TraceRecordV1(BaseModel):
    """Single step/action record suitable for JSONL export."""

    schema_version: Literal["trace-v1"] = "trace-v1"
    run_id: str
    step_id: str
    step_index: int | None = None
    phase: Literal["plan", "tool"] = "plan"
    tool: str | None = None
    state: str | None = None
    status: str | None = None
    timestamp: int | None = None

    preflight_result: dict[str, Any] | None = None
    exec_result: dict[str, Any] | None = None
    postcheck_result: dict[str, Any] | None = None

    violations: list[Violation] | None = None
    mask_reasons: list[Violation] | None = None
    recovery: dict[str, Any] | None = None

    planner_events: list[dict[str, Any]] | None = None
    duration_ms: int | None = None
    branch_group_id: str | None = None
    branch_rank: int | None = None
    cost: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


__all__ = ["TraceRecordV1"]
