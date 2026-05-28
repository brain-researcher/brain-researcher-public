"""Planner trace builder (events + derived state) for UI + logging.

This module converts an Agent plan payload into:
- PlannerEvent list (append-only diffs)
- Final PlannerState (via replay)

It is intentionally schema-tolerant because the agent currently emits multiple
candidate shapes (catalog-driven vs intent-router debug rows).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from brain_researcher.services.agent.planner_state import (
    PlannerEvent,
    PlannerEventType,
    replay_planner_events,
)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_tool_id(candidate: Dict[str, Any]) -> Optional[str]:
    return (
        candidate.get("tool_id")
        or candidate.get("tool")
        or candidate.get("tool_name")  # last resort
    )


def _candidate_tool_name(candidate: Dict[str, Any]) -> Optional[str]:
    return (
        candidate.get("tool_name") or candidate.get("tool") or candidate.get("tool_id")
    )


def _candidate_score(candidate: Dict[str, Any]) -> Optional[float]:
    # Catalog selection uses final_score; intent-router debug uses score.
    return _float_or_none(candidate.get("final_score", candidate.get("score")))


def build_planner_trace(
    plan_payload: Dict[str, Any],
    *,
    request_payload: Optional[Dict[str, Any]] = None,
) -> Tuple[List[PlannerEvent], Dict[str, Any]]:
    """Build planner events + final state from a plan payload dict."""

    events: List[PlannerEvent] = []

    pipeline = (request_payload or {}).get("pipeline") or plan_payload.get("query")
    mode = plan_payload.get("mode")

    events.append(
        PlannerEvent(
            event_type=PlannerEventType.PLANNER_STATE_INIT,
            payload={
                "pipeline": pipeline,
                "mode": mode,
                "routing_diagnostics": plan_payload.get("routing_diagnostics"),
            },
            diff={
                "routing_diagnostics_set": plan_payload.get("routing_diagnostics"),
            }
            if isinstance(plan_payload.get("routing_diagnostics"), dict)
            else {},
        )
    )

    # Candidates from catalog selection (preferred) or debug selection reasons.
    candidates: List[Dict[str, Any]] = []
    if isinstance(plan_payload.get("candidates"), list):
        candidates = list(plan_payload["candidates"])
    elif isinstance(plan_payload.get("selection_reasons"), list):
        # selection_reasons rows look like {tool, score, reasons}
        candidates = list(plan_payload["selection_reasons"])

    chosen_tool = plan_payload.get("chosen_tool") or (
        plan_payload.get("dag", {}).get("steps", [{}])[0] or {}
    ).get("tool")

    dag_steps = (
        plan_payload.get("dag", {}).get("steps", [])
        if isinstance(plan_payload.get("dag"), dict)
        else []
    )
    first_step_id = (dag_steps[0] if dag_steps else {}).get("id")
    dag_branch_steps = []
    for idx, step in enumerate(dag_steps):
        if not isinstance(step, dict):
            continue
        tool_id = step.get("tool")
        if not tool_id:
            continue
        step_id = step.get("id") or f"step_{idx + 1:03d}"
        dag_branch_steps.append({"step_id": step_id, "tool_id": tool_id})

    hypothesis_ids: List[str] = []
    branch_ids: List[str] = []

    for idx, candidate in enumerate(candidates):
        tool_id = _candidate_tool_id(candidate)
        if not tool_id:
            continue
        tool_name = _candidate_tool_name(candidate)
        score = _candidate_score(candidate)
        preflight_passed = candidate.get("preflight_passed")

        hypothesis_id = f"hyp:{tool_id}"
        branch_id = f"br:{tool_id}"
        hypothesis_ids.append(hypothesis_id)
        branch_ids.append(branch_id)

        hypothesis = {
            "hypothesis_id": hypothesis_id,
            "rank": idx + 1,
            "tool_id": tool_id,
            "tool_name": tool_name,
            "score": score,
            "preflight_passed": preflight_passed,
            "raw": candidate,
        }
        if tool_id == chosen_tool and dag_branch_steps:
            branch_steps = list(dag_branch_steps)
        elif first_step_id:
            branch_steps = [{"step_id": first_step_id, "tool_id": tool_id}]
        else:
            branch_steps = [{"tool_id": tool_id}]

        branch = {
            "branch_id": branch_id,
            "hypothesis_id": hypothesis_id,
            "steps": branch_steps,
        }

        events.append(
            PlannerEvent(
                event_type=PlannerEventType.HYPOTHESIS_ADDED,
                payload={"hypothesis": hypothesis},
                diff={
                    "hypotheses_add": [hypothesis],
                    "pending_add": [hypothesis_id],
                },
            )
        )
        events.append(
            PlannerEvent(
                event_type=PlannerEventType.BRANCH_SPAWNED,
                payload={"branch": branch},
                diff={"branches_add": [branch]},
            )
        )

    # If no candidates were provided, still create a minimal hypothesis for chosen tool.
    if not hypothesis_ids and chosen_tool:
        hypothesis_id = f"hyp:{chosen_tool}"
        branch_id = f"br:{chosen_tool}"
        hypothesis_ids = [hypothesis_id]
        branch_ids = [branch_id]
        hypothesis = {
            "hypothesis_id": hypothesis_id,
            "rank": 1,
            "tool_id": chosen_tool,
            "tool_name": chosen_tool,
            "score": None,
            "preflight_passed": None,
            "raw": {},
        }
        if dag_branch_steps:
            branch_steps = list(dag_branch_steps)
        elif first_step_id:
            branch_steps = [{"step_id": first_step_id, "tool_id": chosen_tool}]
        else:
            branch_steps = [{"tool_id": chosen_tool}]

        branch = {
            "branch_id": branch_id,
            "hypothesis_id": hypothesis_id,
            "steps": branch_steps,
        }
        events.append(
            PlannerEvent(
                event_type=PlannerEventType.HYPOTHESIS_ADDED,
                payload={"hypothesis": hypothesis},
                diff={"hypotheses_add": [hypothesis], "pending_add": [hypothesis_id]},
            )
        )
        events.append(
            PlannerEvent(
                event_type=PlannerEventType.BRANCH_SPAWNED,
                payload={"branch": branch},
                diff={"branches_add": [branch]},
            )
        )

    # Detect branch-fallback mode (multiple branch_group_id steps).
    branch_group_ids = []
    for step in dag_steps:
        if not isinstance(step, dict):
            continue
        meta = step.get("metadata") or {}
        group_id = meta.get("branch_group_id")
        if group_id:
            branch_group_ids.append(group_id)
    branch_mode = len(branch_group_ids) >= 2

    # Commit decision (select chosen tool/branch).
    selected_hypothesis_id = f"hyp:{chosen_tool}" if chosen_tool else None
    selected_branch_id = f"br:{chosen_tool}" if chosen_tool else None

    pending_remove = (
        []
        if branch_mode
        else [hid for hid in hypothesis_ids if hid != selected_hypothesis_id]
    )
    events.append(
        PlannerEvent(
            event_type=PlannerEventType.DECISION_COMMITTED,
            payload={
                "chosen_tool": chosen_tool,
                "selected_branch_id": selected_branch_id,
            },
            diff={
                "selected_branch_id_set": selected_branch_id,
                "selected_tool_ids_set": [chosen_tool] if chosen_tool else [],
                "pending_remove": pending_remove,
            },
        )
    )

    # Mark non-selected hypotheses as rejected (informational).
    if not branch_mode:
        for hid in hypothesis_ids:
            if hid == selected_hypothesis_id:
                continue
            events.append(
                PlannerEvent(
                    event_type=PlannerEventType.HYPOTHESIS_REJECTED,
                    payload={"hypothesis_id": hid, "reason": "not_selected"},
                    diff={"rejected_add": [hid]},
                )
            )

    state = replay_planner_events(events)
    return events, state
