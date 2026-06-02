"""Behavior paradigm planner workflow wrapper.

Resolves a free-text behavior/task description to canonical paradigm labels
via `TaskMatcher.match_candidates`, and proposes a lightweight ingest/QC/export
plan referencing the existing `behavior.*` tools.

Design notes
------------
- Heavy dependencies (TaskMatcher, embeddings, faiss) are imported lazily
  inside `_run` only when the caller did not inject a `task_matcher`.
- Research-event logging uses a thin local helper `record_research_event`
  that accepts None / list / callable sinks; it never raises. We intentionally
  do NOT import from `services/review/*` or `services/mcp/server` so this
  module stays usable outside the MCP runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


def record_research_event(
    sink: Any,
    *,
    kind: str,
    content: str,
    context: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Record a planner research event into ``sink`` without raising.

    ``sink`` may be:
      - ``None``: returns the event dict only.
      - ``list``: appends the event dict and returns it.
      - ``callable``: invoked with the event dict; exceptions are swallowed.
      - anything else: ignored; event dict is still returned.
    """
    try:
        event: dict[str, Any] = {
            "kind": str(kind),
            "content": str(content),
            "context": dict(context or {}),
            "tags": list(tags or []),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        # Absolute fallback: never raise from the helper.
        return {
            "kind": str(kind) if kind is not None else "",
            "content": str(content) if content is not None else "",
            "context": {},
            "tags": [],
            "ts": "",
        }

    if sink is None:
        return event
    if isinstance(sink, list):
        try:
            sink.append(event)
        except Exception:
            pass
        return event
    if callable(sink):
        try:
            sink(event)
        except Exception:
            pass
        return event
    return event


class BehaviorParadigmPlanArgs(BaseModel):
    """Arguments for the behavior paradigm planner workflow."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    query: str = Field(..., description="Free-text task/paradigm description")
    modality: str | None = Field(
        default="behavior", description="Primary modality hint"
    )
    n_subjects: int | None = Field(
        default=None, ge=1, description="Optional subject-count hint"
    )
    expected_rt_sec: float | None = Field(
        default=None, gt=0, description="Optional expected RT (seconds)"
    )
    top_k: int = Field(
        default=5, ge=1, le=20, description="Top-K paradigm candidates to resolve"
    )
    policy_path: str = Field(
        default="configs/behavior_outlier_policy.yaml",
        description="Behavior outlier policy YAML path propagated into the QC step",
    )
    drop_excluded: bool = Field(
        default=True,
        description="Whether the export step should drop QC-excluded trials",
    )
    task_matcher: Any | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="Optional pre-built TaskMatcher (injection for tests/runtime reuse)",
    )
    event_sink: Any | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="Optional research-event sink (list | callable | None)",
    )

    @field_validator("query")
    @classmethod
    def _strip_query(cls, v: str) -> str:
        stripped = (v or "").strip()
        if not stripped:
            raise ValueError("query must be non-empty")
        return stripped


class BehaviorParadigmPlannerTool(NeuroToolWrapper):
    """Resolve canonical paradigms and propose an ingest/QC/export plan."""

    def get_tool_name(self) -> str:
        return "behavior.paradigm_planner"

    def get_tool_description(self) -> str:
        return (
            "Resolve a free-text behavior task description to canonical paradigms "
            "and propose an ingest/QC/export plan"
        )

    def get_args_schema(self):
        return BehaviorParadigmPlanArgs

    def _run(
        self,
        query: str,
        modality: str | None = "behavior",
        n_subjects: int | None = None,
        expected_rt_sec: float | None = None,
        top_k: int = 5,
        policy_path: str = "configs/behavior_outlier_policy.yaml",
        drop_excluded: bool = True,
        task_matcher: Any | None = None,
        event_sink: Any | None = None,
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            notes: list[str] = []
            sink: Any = event_sink if event_sink is not None else []
            from brain_researcher.behavior.planner import plan_task_from_prompt

            raw_candidates: list[dict[str, Any]] = []
            matcher = task_matcher
            if matcher is None:
                try:
                    from brain_researcher.services.br_kg.utils.task_matcher import (
                        TaskMatcher,
                    )

                    matcher = TaskMatcher()
                except Exception as exc:  # pragma: no cover - exercised via stub
                    notes.append(f"task_matcher_unavailable: {exc}")
                    matcher = None
            if matcher is not None:
                try:
                    raw_candidates = matcher.match_candidates(query, top_k=top_k) or []
                except Exception as exc:
                    notes.append(f"task_matcher_unavailable: {exc}")

            resolved = plan_task_from_prompt(
                query,
                raw_candidates=raw_candidates,
                task_matcher=None,
                top_k=top_k,
            )
            candidates = list(resolved.get("candidates") or [])
            top = candidates[0] if candidates else None
            record_research_event(
                sink,
                kind="paradigm_resolved",
                content=(f"resolved {resolved['resolution']} for: {query[:200]}"),
                context={
                    "query": query,
                    "top": top,
                    "count": len(candidates),
                    "resolution": resolved["resolution"],
                    "paradigm": resolved.get("paradigm"),
                },
                tags=["behavior", "planner", "paradigm"],
            )

            plan: dict[str, dict[str, Any]] = {
                "ingest": {
                    "tool": "behavior.ingest_taps",
                    "config": {"task_dir": None},
                    "rationale": (
                        "Normalize TAPS/psyflow/PsychoPy CSV into canonical "
                        "BehaviorTrial rows."
                    ),
                },
                "qc": {
                    "tool": "behavior.qc_scan",
                    "config": {"policy_path": policy_path},
                    "rationale": f"Apply outlier/QC policy from {policy_path}.",
                },
                "export": {
                    "tool": "behavior.export_bids",
                    "config": {
                        "drop_excluded": bool(drop_excluded),
                        "write_sidecar": True,
                        "include_hash": True,
                    },
                    "rationale": "Emit BIDS events.tsv with sidecar for downstream GLM.",
                },
            }

            if resolved["resolution"] == "matched":
                notes.append(f"top_paradigm: {resolved['paradigm']}")
            elif resolved["resolution"] == "ambiguous":
                notes.append(f"ambiguous_prompt: {resolved.get('reason')}")
            else:
                notes.append(f"abstained: {resolved.get('reason')}")
            if modality and modality != "behavior":
                notes.append(f"modality_hint: {modality}")
            if n_subjects is not None:
                notes.append(f"n_subjects_hint: {int(n_subjects)}")
            if expected_rt_sec is not None:
                notes.append(f"expected_rt_hint_sec: {float(expected_rt_sec):.3f}")

            record_research_event(
                sink,
                kind="plan_proposed",
                content=f"proposed ingest/qc/export plan for: {query[:200]}",
                context={
                    "resolution": resolved["resolution"],
                    "paradigm": resolved.get("paradigm"),
                    "overrides": resolved.get("overrides"),
                    "plan": plan,
                    "policy_path": policy_path,
                    "drop_excluded": bool(drop_excluded),
                },
                tags=["behavior", "planner", "plan"],
            )

            data = {
                "query": query,
                "resolution": resolved["resolution"],
                "paradigm": resolved.get("paradigm"),
                "reason": resolved.get("reason"),
                "clarifying_questions": resolved.get("clarifying_questions") or [],
                "overrides": resolved.get("overrides") or {},
                "scanner_profile": resolved.get("scanner_profile"),
                "candidates": candidates,
                "plan": plan,
                "notes": notes,
                "events": sink if isinstance(sink, list) else [],
            }
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


__all__ = [
    "BehaviorParadigmPlannerTool",
    "BehaviorParadigmPlanArgs",
    "record_research_event",
]
