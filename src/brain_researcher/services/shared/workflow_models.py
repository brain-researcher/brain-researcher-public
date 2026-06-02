"""Shared workflow model types.

These are pure data containers used across service boundaries. Runtime
execution remains in ``services.orchestrator.dag_runtime``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowStep:
    step_id: str
    tool_name: str
    parameters: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["WorkflowStep"]
