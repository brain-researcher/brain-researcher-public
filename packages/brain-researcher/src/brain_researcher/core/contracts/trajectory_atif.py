"""Harbor Trajectory Format (ATIF v1.4).

This contract mirrors Harbor's "ATIF-v1.4" schema so Brain Researcher can export
trajectories that are compatible with Harbor tooling.

Reference:
https://harborframework.com/docs/trajectory-format
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ATIFToolCall(BaseModel):
    tool_call_id: str
    function_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] | None = None


class ATIFObservationResult(BaseModel):
    source_call_id: str
    content: Any
    extra: dict[str, Any] | None = None


class ATIFObservation(BaseModel):
    results: list[ATIFObservationResult] = Field(default_factory=list)
    extra: dict[str, Any] | None = None


class ATIFMetrics(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None
    logprobs: list[float] | None = None
    completion_token_ids: list[int] | None = None
    extra: dict[str, Any] | None = None


class ATIFStep(BaseModel):
    step_id: int
    timestamp: str
    source: Literal["system", "user", "agent"]
    message: str

    # Agent-only fields (must be absent on user/system steps).
    model_name: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ATIFToolCall] | None = None
    observation: ATIFObservation | None = None
    metrics: ATIFMetrics | None = None

    extra: dict[str, Any] | None = None

    @field_validator("step_id")
    @classmethod
    def _require_positive_step_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("step_id must be a positive integer")
        return value

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        # Harbor expects ISO-8601. Accept "Z" suffix by translating to "+00:00".
        normalized = value.replace("Z", "+00:00")
        datetime.fromisoformat(normalized)
        return value

    @model_validator(mode="after")
    def _validate_agent_fields(self) -> "ATIFStep":
        if self.source != "agent":
            if self.model_name is not None:
                raise ValueError("model_name is only allowed on agent steps")
            if self.reasoning_content is not None:
                raise ValueError("reasoning_content is only allowed on agent steps")
            if self.tool_calls not in (None, []):
                raise ValueError("tool_calls is only allowed on agent steps")
            if self.observation is not None:
                raise ValueError("observation is only allowed on agent steps")
            if self.metrics is not None:
                raise ValueError("metrics is only allowed on agent steps")
        return self


class ATIFAgent(BaseModel):
    name: str
    version: str
    model_name: str
    extra: dict[str, Any] | None = None


class ATIFFinalMetrics(BaseModel):
    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    total_cached_tokens: int | None = None
    total_cost_usd: float | None = None
    total_steps: int | None = None
    extra: dict[str, Any] | None = None


class ATIFTrajectory(BaseModel):
    schema_version: Literal["ATIF-v1.4"] = "ATIF-v1.4"
    session_id: str
    agent: ATIFAgent
    steps: list[ATIFStep]
    final_metrics: ATIFFinalMetrics | None = None
    extra: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_steps(self) -> "ATIFTrajectory":
        ids = [s.step_id for s in self.steps]
        if ids != list(range(1, len(self.steps) + 1)):
            raise ValueError("step_id must be sequential integers starting at 1")

        for step in self.steps:
            if step.source != "agent":
                continue
            call_ids = {c.tool_call_id for c in step.tool_calls or []}
            if step.observation is not None:
                for res in step.observation.results:
                    if res.source_call_id not in call_ids:
                        raise ValueError(
                            f"source_call_id '{res.source_call_id}' does not match "
                            f"any tool_call_id in step {step.step_id}"
                        )
        return self

    def to_json_dict(self) -> dict[str, Any]:
        """Harbor-style JSON dict (omit nulls)."""
        return self.model_dump(exclude_none=True)


__all__ = [
    "ATIFTrajectory",
    "ATIFAgent",
    "ATIFStep",
    "ATIFToolCall",
    "ATIFObservation",
    "ATIFObservationResult",
    "ATIFMetrics",
    "ATIFFinalMetrics",
]

