"""Shared identifier envelope (v1).

This is the small, embeddable "identity" primitive that higher-level contracts
should reference (RunCard, Observation, TraceEvent, Bundle, ...).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IdsV1(BaseModel):
    """Stable identifiers for correlating objects/events across services."""

    schema_version: Literal["ids-v1"] = "ids-v1"

    analysis_id: str | None = Field(
        default=None, description="Analysis identifier if applicable"
    )
    run_id: str | None = Field(default=None, description="Run identifier")
    job_id: str | None = Field(default=None, description="Job identifier")

    request_id: str | None = Field(
        default=None, description="Inbound API/UI request identifier"
    )
    trace_id: str | None = Field(default=None, description="Distributed trace id")

    workspace_id: str | None = Field(default=None, description="Workspace/project id")
    user_id: str | None = Field(default=None, description="End-user id")
    session_id: str | None = Field(
        default=None, description="Conversation/session/thread id"
    )


__all__ = ["IdsV1"]

