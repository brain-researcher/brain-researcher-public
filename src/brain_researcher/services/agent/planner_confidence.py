"""Confidence decomposition for planner branches/steps/plans.

TODO-2: Provide explainable confidence at:
- step_conf: per step/tool choice
- branch_conf: aggregate of steps in a branch (+ penalties)
- plan_conf: overall confidence (best branch - uncertainty penalties)

This module is pure and deterministic so it can be unit-tested.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _geometric_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    eps = 1e-9
    logs = [math.log(max(eps, v)) for v in values]
    return float(math.exp(sum(logs) / len(logs)))


def _index_candidates_by_tool(
    plan_payload: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    candidates = plan_payload.get("candidates")
    if isinstance(candidates, list):
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            tool_id = cand.get("tool_id") or cand.get("tool")
            if tool_id:
                idx[str(tool_id)] = cand

    # Fallback: selection_reasons debug rows from intent-router
    selection_reasons = plan_payload.get("selection_reasons")
    if not idx and isinstance(selection_reasons, list):
        for cand in selection_reasons:
            if not isinstance(cand, dict):
                continue
            tool_id = cand.get("tool_id") or cand.get("tool")
            if tool_id:
                idx[str(tool_id)] = cand

    return idx


def compute_step_confidence(
    *,
    tool_id: str,
    candidate: Optional[Dict[str, Any]],
    constraints: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """Compute step_conf for a single step/tool choice."""

    base_score = 0.5
    hq_score = 0.5
    latency_score = 0.5
    preflight_passed: Optional[bool] = None
    failure_penalty = 0.0
    failed_on_count: Optional[float] = None
    failure_last_seen = None
    evidence_layer = None
    evidence_n: Optional[int] = None

    if candidate:
        base_score = _safe_float(
            candidate.get("final_score", candidate.get("score")), 0.5
        )
        hq_score = _safe_float(candidate.get("historical_quality_score"), 0.5)
        latency_score = _safe_float(candidate.get("latency_score"), 0.5)
        preflight_passed = candidate.get("preflight_passed")
        failure_penalty = _safe_float(candidate.get("failure_penalty"), 0.0)
        failed_on_count = _safe_float(candidate.get("failed_on_count"), None)
        failure_last_seen = candidate.get("failure_last_seen")
        evidence_layer = candidate.get("evidence_layer")
        evidence_n = candidate.get("evidence_n")

    # Step confidence: weighted blend of current match score and historical quality.
    step_conf = 0.8 * base_score + 0.2 * hq_score

    # Preflight penalty: failing preflight means lower confidence.
    if preflight_passed is False:
        step_conf *= 0.6

    # Constraint penalty: tool_allowlist violation -> 0.
    allowlist = (constraints or {}).get("tool_allowlist")
    if isinstance(allowlist, list) and allowlist and tool_id not in allowlist:
        step_conf = 0.0

    # Latency score: small stabilizer (avoid overconfidence on very slow tools).
    step_conf *= 0.9 + 0.1 * latency_score
    # Failure prior penalty
    if failure_penalty > 0:
        step_conf = max(0.0, step_conf - failure_penalty)

    step_conf = _clamp01(step_conf)
    explain = {
        "base_score": base_score,
        "historical_quality_score": hq_score,
        "latency_score": latency_score,
        "preflight_passed": preflight_passed,
        "constraints": {"tool_allowlist_applied": bool(allowlist)},
        "failure_prior": {
            "penalty_applied": failure_penalty,
            "failed_on_count": failed_on_count if failed_on_count is not None else 0,
            "last_seen": failure_last_seen,
        },
        "evidence_prior": {
            "layer": evidence_layer,
            "n": evidence_n if evidence_n is not None else 0,
        },
    }
    return step_conf, explain


def compute_confidence_summary(
    plan_payload: Dict[str, Any],
    *,
    planner_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute plan/branch/step confidence summary for a plan payload."""

    constraints = plan_payload.get("constraints") or {}
    if plan_payload.get("resolvable") is False:
        return {
            "plan_conf": 0.0,
            "branch_conf": [],
            "step_conf": [],
            "notes": ["plan is not resolvable"],
        }

    candidate_by_tool = _index_candidates_by_tool(plan_payload)

    state = plan_payload.get("planner_state") or {}
    branches = state.get("branches") if isinstance(state.get("branches"), list) else []

    # If no explicit branches, treat current plan as single branch with DAG tools.
    if not branches:
        steps = (
            plan_payload.get("dag", {}).get("steps")
            if isinstance(plan_payload.get("dag"), dict)
            else None
        )
        tool_ids = []
        if isinstance(steps, list):
            tool_ids = [
                s.get("tool") for s in steps if isinstance(s, dict) and s.get("tool")
            ]
        chosen_tool = plan_payload.get("chosen_tool")
        if chosen_tool and chosen_tool not in tool_ids:
            tool_ids.insert(0, chosen_tool)
        branches = [
            {
                "branch_id": f"br:{tool_ids[0]}" if tool_ids else "br:default",
                "hypothesis_id": f"hyp:{tool_ids[0]}" if tool_ids else "hyp:default",
                "steps": [{"tool_id": t} for t in tool_ids] if tool_ids else [],
            }
        ]

    # Count recovery events (penalty) per branch.
    recovery_events = []
    if isinstance(planner_events, list):
        recovery_events = [
            e
            for e in planner_events
            if isinstance(e, dict) and e.get("event_type") == "recovery_triggered"
        ]

    step_conf_rows: List[Dict[str, Any]] = []
    branch_conf_rows: List[Dict[str, Any]] = []

    for branch in branches:
        if not isinstance(branch, dict):
            continue
        branch_id = str(branch.get("branch_id") or "br:unknown")
        branch_steps = (
            branch.get("steps") if isinstance(branch.get("steps"), list) else []
        )

        conf_values: List[float] = []
        for idx, step in enumerate(branch_steps):
            if not isinstance(step, dict):
                continue
            tool_id = step.get("tool_id") or step.get("tool") or step.get("id")
            if not tool_id:
                continue
            tool_id = str(tool_id)
            step_id = step.get("step_id") or step.get("id") or f"step_{idx+1:03d}"

            step_conf, explain = compute_step_confidence(
                tool_id=tool_id,
                candidate=candidate_by_tool.get(tool_id),
                constraints=constraints,
            )
            conf_values.append(step_conf)
            step_conf_rows.append(
                {
                    "branch_id": branch_id,
                    "step_id": step_id,
                    "tool_id": tool_id,
                    "step_conf": step_conf,
                    "explain": explain,
                }
            )

        base_branch_conf = _geometric_mean(conf_values)

        # Penalty: if recoveries happened, reduce confidence.
        n_recoveries = 0
        for ev in recovery_events:
            payload = ev.get("payload") or {}
            if payload.get("to_tool") and f"br:{payload.get('to_tool')}" == branch_id:
                n_recoveries += 1
        branch_conf = _clamp01(base_branch_conf * (0.85**n_recoveries))

        branch_conf_rows.append(
            {
                "branch_id": branch_id,
                "branch_conf": branch_conf,
                "base_branch_conf": base_branch_conf,
                "n_recoveries": n_recoveries,
            }
        )

    # Plan confidence = best branch confidence - uncertainty penalty.
    branch_confs = sorted((b["branch_conf"] for b in branch_conf_rows), reverse=True)
    best = branch_confs[0] if branch_confs else 0.0
    second = branch_confs[1] if len(branch_confs) > 1 else None
    uncertainty_penalty = 0.0
    if second is not None:
        gap = best - second
        if gap < 0.05:
            uncertainty_penalty = 0.10
        elif gap < 0.10:
            uncertainty_penalty = 0.05

    plan_conf = _clamp01(best - uncertainty_penalty)

    return {
        "plan_conf": plan_conf,
        "branch_conf": branch_conf_rows,
        "step_conf": step_conf_rows,
        "uncertainty_penalty": uncertainty_penalty,
    }
