"""Stream event schema (v1) for replayable SSE.

M1 intent:
- Provide a small, stable envelope for SSE/WS events.
- Support correlation back to the durable trace/event log via `source_event_id`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .ids import IdsV1


class StreamEventV1(BaseModel):
    schema_version: Literal["stream-event-v1"] = "stream-event-v1"

    ids: IdsV1 = Field(default_factory=IdsV1)
    source_event_id: str = Field(
        ..., description="Event identifier in the source append-only log/trace"
    )

    event_type: str
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = ["StreamEventV1"]
