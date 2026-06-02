"""Decision record contract (v1).

Decision records capture *why* the agent selected a tool/step. They are meant
to be stable, comparable objects for benchmarking and audit, independent of
UI/streaming transports.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DecisionAlternativeV1(BaseModel):
    tool_id: str
    reason: str | None = None


class DecisionRecordV1(BaseModel):
    schema_version: Literal["decision-record-v1"] = "decision-record-v1"

    step_id: str
    tool_id: str | None = None

    why: str = Field(description="Concise explanation for selecting this step/tool")
    alternatives: list[DecisionAlternativeV1] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    policy_applied: dict[str, Any] | None = Field(
        default=None, description="Policy/guardrails snapshot applied to this decision"
    )

    timestamp: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp when the decision was made"
    )


__all__ = ["DecisionAlternativeV1", "DecisionRecordV1"]
