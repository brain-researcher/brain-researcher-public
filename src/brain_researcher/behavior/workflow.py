"""End-to-end behavior task workflow glue.

Stages: plan → resolve → review (approval gate) → generate scaffold →
optional psyflow-validate → optional ingest. Designed to be reusable from
MCP tools, notebooks, or scripts. Never imports psyflow at module level.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.behavior.catalog import (
    config_mapper_for,
    resolve_defaults,
)
from brain_researcher.behavior.psyflow_adapter import (
    PsyflowNotInstalledError,
    ingest_psyflow_run,
    run_psyflow_validate,
    write_psyflow_scaffold,
)
from brain_researcher.behavior.task_spec import (
    BehaviorReviewV1,
    BehaviorTaskSpecV1,
    spec_digest,
)

ParadigmPlanner = Callable[[str, Any], str | None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_research_event(
    sink: Any,
    *,
    kind: str,
    content: str,
    context: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Record an event into ``sink`` without raising. Mirrors behavior_paradigm_planner."""
    event: dict[str, Any] = {
        "kind": str(kind),
        "content": str(content),
        "context": dict(context or {}),
        "tags": list(tags or []),
        "ts": _now(),
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


def run_behavior_workflow(
    query: str,
    *,
    paradigm: str | None = None,
    overrides: dict[str, Any] | None = None,
    review: dict[str, Any] | BehaviorReviewV1 | None = None,
    out_dir: str,
    run_data_dir: str | None = None,
    event_sink: Any = None,
    paradigm_planner: ParadigmPlanner | None = None,
) -> dict[str, Any]:
    """Run the full prompt → generate → (optional) ingest pipeline."""
    sink: Any = event_sink if event_sink is not None else []
    stages: dict[str, Any] = {}

    # 1) Plan
    planned: str | None = paradigm
    if planned is None and paradigm_planner is not None:
        try:
            planned = paradigm_planner(query, sink)
        except Exception:
            planned = None
    if planned is None:
        planned = (overrides or {}).get("paradigm")
    if not planned:
        raise ValueError(
            "unable to determine paradigm; pass `paradigm=`, supply paradigm_planner, "
            "or provide overrides['paradigm']"
        )
    stages["plan"] = {"paradigm": planned, "query": query}
    record_research_event(
        sink,
        kind="paradigm_planned",
        content=f"planned paradigm={planned} for query={query[:120]}",
        context={"paradigm": planned},
        tags=["behavior", "workflow", "plan"],
    )

    # 2) Resolve
    spec: BehaviorTaskSpecV1 = resolve_defaults(planned, overrides or {})
    digest = spec_digest(spec)
    stages["resolve"] = {"spec": spec.model_dump(mode="json"), "spec_digest": digest}
    record_research_event(
        sink,
        kind="spec_resolved",
        content=f"resolved spec for paradigm={spec.paradigm} digest={digest[:12]}",
        context={"paradigm": spec.paradigm, "spec_digest": digest},
        tags=["behavior", "workflow", "resolve"],
    )

    # 3) Review (must be provided explicitly; workflow must not bypass approval)
    if review is None:
        raise ValueError("approved review payload is required before generation")
    parsed_review = (
        review
        if isinstance(review, BehaviorReviewV1)
        else BehaviorReviewV1.model_validate(review)
    )
    if not parsed_review.approved or parsed_review.spec_digest != digest:
        raise ValueError("review must be approved and match the resolved spec digest")
    stages["review"] = parsed_review.model_dump(mode="json")

    # 4) Generate
    mapper = config_mapper_for(spec.paradigm)
    bundle = write_psyflow_scaffold(spec, out_dir, mapper)
    stages["generate"] = bundle.model_dump(mode="json")
    record_research_event(
        sink,
        kind="scaffold_generated",
        content=f"wrote psyflow scaffold for {spec.paradigm} at {bundle.planned_dir}",
        context={"paradigm": spec.paradigm, "planned_dir": bundle.planned_dir},
        tags=["behavior", "workflow", "generate"],
    )

    # 5) Optional psyflow-validate (skipped gracefully if extra missing)
    try:
        stages["validate"] = run_psyflow_validate(bundle)
    except PsyflowNotInstalledError as exc:
        stages["validate"] = {
            "status": "skipped",
            "reason": "psyflow_extra_missing",
            "error": str(exc),
        }
    except Exception as exc:  # pragma: no cover - defensive
        stages["validate"] = {"status": "error", "error": str(exc)}

    # 6) Optional ingest
    if run_data_dir:
        # Ensure planned tree exists; create run root skeleton for convenience.
        Path(out_dir, "run").mkdir(parents=True, exist_ok=True)
        try:
            stages["ingest"] = ingest_psyflow_run(bundle, run_data_dir, out_dir)
        except Exception as exc:
            stages["ingest"] = {"status": "error", "error": str(exc)}

    stages["events"] = sink if isinstance(sink, list) else []
    return stages


__all__ = ["ParadigmPlanner", "record_research_event", "run_behavior_workflow"]
