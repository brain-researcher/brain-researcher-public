"""Explicit planner state tracking via append-only state diffs.

TODO-2: Planner State + Confidence + Failure Recovery

This module provides:
- PlannerState: hypotheses/branches/rejected/pending (+ selected branch/tool IDs)
- PlannerEvent: append-only events containing a state diff
- Replay: pure functions to reconstruct final PlannerState from events
- Logging adapter: write events via agent/logging/run_recorder.py JSONL

Design constraints:
- Deterministic + testable (pure replayer).
- Events are append-only; state is derived (never mutated in-place during replay).
- Payloads are JSON-serializable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from brain_researcher.services.agent.logging.run_recorder import RunRecorder


class PlannerEventType(str, Enum):
    PLANNER_STATE_INIT = "planner_state_init"
    HYPOTHESIS_ADDED = "hypothesis_added"
    HYPOTHESIS_REJECTED = "hypothesis_rejected"
    BRANCH_SPAWNED = "branch_spawned"
    DECISION_COMMITTED = "decision_committed"
    RECOVERY_TRIGGERED = "recovery_triggered"
    RESOLUTION_CACHE_HIT = "resolution_cache_hit"
    RESOLUTION_CACHE_MISS = "resolution_cache_miss"
    RESOLUTION_DISCOVERY_BOUNDED = "resolution_discovery_bounded"
    RESOLUTION_DECISION_REQUIRED = "resolution_decision_required"
    RESOLUTION_DECISION_APPLIED = "resolution_decision_applied"


@dataclass(frozen=True)
class PlannerEvent:
    event_type: PlannerEventType
    ts: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: f"pev_{uuid4().hex[:10]}")
    payload: Dict[str, Any] = field(default_factory=dict)
    diff: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "ts": self.ts,
            "event_id": self.event_id,
            "payload": self.payload,
            "diff": self.diff,
        }


def empty_planner_state() -> Dict[str, Any]:
    """Create an empty planner state dict."""

    return {
        "hypotheses": [],
        "branches": [],
        "rejected": [],
        "pending": [],
        "selected_branch_id": None,
        "selected_tool_ids": [],
        "routing_diagnostics": None,
    }


def _dedupe_preserve_order(items: List[Any]) -> List[Any]:
    seen = set()
    out = []
    for item in items:
        key = item if isinstance(item, (str, int, float, tuple)) else repr(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def apply_state_diff(state: Dict[str, Any], diff: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a state diff (pure function)."""

    next_state: Dict[str, Any] = {
        "hypotheses": list(state.get("hypotheses", [])),
        "branches": list(state.get("branches", [])),
        "rejected": list(state.get("rejected", [])),
        "pending": list(state.get("pending", [])),
        "selected_branch_id": state.get("selected_branch_id"),
        "selected_tool_ids": list(state.get("selected_tool_ids", [])),
        "routing_diagnostics": state.get("routing_diagnostics"),
    }

    # Additions
    if diff.get("hypotheses_add"):
        next_state["hypotheses"].extend(diff["hypotheses_add"])
    if diff.get("branches_add"):
        next_state["branches"].extend(diff["branches_add"])
    if diff.get("pending_add"):
        next_state["pending"].extend(diff["pending_add"])
    if diff.get("rejected_add"):
        next_state["rejected"].extend(diff["rejected_add"])

    # Removals (still append-only at the event-log level)
    if diff.get("pending_remove"):
        to_remove = set(diff["pending_remove"])
        next_state["pending"] = [h for h in next_state["pending"] if h not in to_remove]

    # Setters
    if "selected_branch_id_set" in diff:
        next_state["selected_branch_id"] = diff.get("selected_branch_id_set")
    if "selected_tool_ids_set" in diff:
        next_state["selected_tool_ids"] = list(diff.get("selected_tool_ids_set") or [])
    if "routing_diagnostics_set" in diff:
        next_state["routing_diagnostics"] = diff.get("routing_diagnostics_set")

    # Normalize (dedupe)
    next_state["pending"] = _dedupe_preserve_order(next_state["pending"])
    next_state["rejected"] = _dedupe_preserve_order(next_state["rejected"])

    return next_state


def replay_planner_events(
    events: Sequence[Dict[str, Any]] | Sequence[PlannerEvent],
) -> Dict[str, Any]:
    """Replay events into a final PlannerState (pure function)."""

    state = empty_planner_state()
    for event in events:
        diff = (
            event.diff if isinstance(event, PlannerEvent) else (event.get("diff") or {})
        )
        state = apply_state_diff(state, diff)
    return state


class PlannerEventLogger:
    """Append-only logger for planner events using RunRecorder JSONL."""

    def __init__(
        self,
        run_id: str,
        base_path: str | Path | None = None,
        *,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        enable_otel: bool = False,
    ):
        self.run_id = run_id
        self._recorder = RunRecorder(base_path=base_path, enable_otel=enable_otel)
        self._trace_id = trace_id
        self._parent_span_id = parent_span_id

    def log(self, event: PlannerEvent) -> Dict[str, Any]:
        """Write a single planner event record to JSONL."""

        self._recorder.start(
            phase="planning",
            run_id=self.run_id,
            trace_id=self._trace_id,
            parent_span_id=self._parent_span_id,
        )
        return self._recorder.finish(
            {
                "event": event.event_type.value,
                "planner_event": event.to_dict(),
            },
            categories=["agent", "planner"],
        )

    def log_many(self, events: Sequence[PlannerEvent]) -> None:
        for event in events:
            self.log(event)
