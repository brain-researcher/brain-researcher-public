"""Task-engine program contract (v1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskInterventionRefV1(BaseModel):
    """Declarative intervention/config patch applied to a task program."""

    name: str
    kind: str
    target: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskProgramV1(BaseModel):
    """Portable task-engine contract for compiled task programs."""

    schema_version: Literal["task-program-v1"] = "task-program-v1"

    program_id: str
    canonical_task_id: str
    engine: str = Field(
        description="Task engine identifier such as neurogym or custom."
    )
    environment_id: str
    environment_config: dict[str, Any] | None = None
    asset_ids: list[str] = Field(default_factory=list)
    intervention_refs: list[TaskInterventionRefV1] = Field(default_factory=list)
    observation_schema: str | None = Field(
        default="behavior-trial-v1",
        description="Canonical downstream observation contract emitted by this program.",
    )
    metadata: dict[str, Any] | None = None


__all__ = ["TaskInterventionRefV1", "TaskProgramV1"]
