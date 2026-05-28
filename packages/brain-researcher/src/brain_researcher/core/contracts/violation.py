"""Unified violation contract (v1).

This schema is intended to standardize how gates/action masking/compliance
checks report problems across tools → orchestrator → agent → UI.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ViolationLocation(BaseModel):
    """Where the violation occurred."""

    component: str | None = Field(
        default=None, description="Sub-system name, e.g., planner/worker/tool"
    )
    stage: str | None = Field(
        default=None, description="Phase, e.g., preflight/execute/postcheck"
    )
    step_id: str | None = Field(
        default=None, description="Workflow step identifier if available"
    )
    path: str | None = Field(
        default=None,
        description="File or resource path relevant to the violation (optional)",
    )


class EvidenceRef(BaseModel):
    """Evidence pointer to help UI render and users debug."""

    type: Literal["artifact", "log", "metric", "text", "url"] = "text"
    uri: str | None = Field(
        default=None, description="Path/URL/log cursor pointing to evidence"
    )
    summary: str | None = Field(
        default=None, description="Concise human-readable evidence blurb"
    )
    pointer: str | None = Field(
        default=None, description="Optional JSONPath/line number within the uri"
    )


class Violation(BaseModel):
    """Canonical violation object."""

    schema_version: Literal["violation-v1"] = "violation-v1"

    code: str = Field(..., description="Stable machine code, e.g., QC_MISSING_T1W")
    message: str = Field(..., description="Human-readable description")
    severity: Literal["info", "warn", "error", "critical"] = "warn"
    blocking: bool = Field(
        default=False,
        description="True if this violation should block the run/step by default",
    )

    where: ViolationLocation | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    suggested_fix: str | None = Field(
        default=None, description="Actionable remediation guidance"
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Free-form machine-friendly payload"
    )
    created_at: int | None = Field(
        default=None, description="Unix epoch millis when generated"
    )


__all__ = ["Violation", "ViolationLocation", "EvidenceRef"]
