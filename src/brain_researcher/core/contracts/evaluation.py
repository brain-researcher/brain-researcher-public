"""Evaluation namespace contract (v1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .scorecard import ScorecardV1
from .task_spec import TaskSpecV1


class EvaluationV1(BaseModel):
    """Optional benchmark/evaluation metadata attached to a run."""

    schema_version: Literal["evaluation-v1"] = "evaluation-v1"

    task: TaskSpecV1 | dict[str, Any] | None = None
    scorecard: ScorecardV1 | dict[str, Any] | None = None

    # Framework-specific payloads (Harbor, internal harnesses, etc.)
    harbor: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


__all__ = ["EvaluationV1"]
