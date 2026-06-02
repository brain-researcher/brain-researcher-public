"""Evaluation task specification contract (v1).

This is a minimal, benchmark-friendly task definition intended to align with
Harbor-style evaluation harnesses without coupling the core product schema to
any single framework.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskSpecV1(BaseModel):
    """Benchmark case specification (v1)."""

    schema_version: Literal["task-spec-v1"] = "task-spec-v1"

    task_id: str = Field(description="Stable identifier for this evaluation task/case")
    name: str | None = None
    description: str | None = None

    # Free-form payloads until the bench harness converges.
    inputs: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] | None = None
    expected_outputs: list[dict[str, Any]] = Field(default_factory=list)
    allowlist: dict[str, Any] | None = None
    scoring: dict[str, Any] | None = None

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


__all__ = ["TaskSpecV1"]
