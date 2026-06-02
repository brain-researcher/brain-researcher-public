"""Evaluation scorecard contract (v1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ScorecardV1(BaseModel):
    """Score output produced by a validator/comparator (v1)."""

    schema_version: Literal["scorecard-v1"] = "scorecard-v1"

    task_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None

    overall_score: float | None = None
    passed: bool | None = None

    metrics: dict[str, float] = Field(default_factory=dict)
    breakdown: dict[str, Any] | None = None

    generated_at: str | None = None
    evaluator: dict[str, Any] | None = None
    notes: str | None = None


__all__ = ["ScorecardV1"]
