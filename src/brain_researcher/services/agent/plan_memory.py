"""Backward-compatible re-export shim for the plan memory store.

The implementation now lives in
``brain_researcher.services.shared.r2toolsagent_plan_memory`` so that lower
layers (e.g. ``services.tools`` via the principle controller) can depend on it
without creating a ``tools -> agent`` import back-edge. Existing callers that
import from ``brain_researcher.services.agent.plan_memory`` continue to work
unchanged.
"""

from __future__ import annotations

from brain_researcher.services.shared.r2toolsagent_plan_memory import (  # noqa: F401
    FailureRecord,
    PlanMemory,
    PlanRecord,
    PrincipleEventRecord,
    PrincipleSessionRecord,
    create_plan_memory,
)

__all__ = [
    "FailureRecord",
    "PlanMemory",
    "PlanRecord",
    "PrincipleEventRecord",
    "PrincipleSessionRecord",
    "create_plan_memory",
]
