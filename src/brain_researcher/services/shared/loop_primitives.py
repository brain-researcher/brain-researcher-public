"""Loop-profile and run-comparison helpers for MCP clients."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from brain_researcher.core.artifact_validator import (
    CORE_RUN_ARTIFACT_COMPONENTS,
    build_artifact_contract_summary,
    infer_artifact_profile,
)

DEFAULT_LOOP_PROFILE_ID = "external_coding_v1"
SUPPORTED_LOOP_PROFILE_IDS = [DEFAULT_LOOP_PROFILE_ID]
__all__ = [
    "DEFAULT_LOOP_PROFILE_ID",
    "SUPPORTED_LOOP_PROFILE_IDS",
    "build_artifact_index",
    "build_run_bundle_payload",
    "build_run_scorecard",
    "compare_run_scorecards",
    "get_loop_profile",
    "normalize_completion_state",
]
_BUNDLE_COMPONENT_FILES = CORE_RUN_ARTIFACT_COMPONENTS
_COMPLETION_ORDER = {
    "succeeded": 4,
    "running": 3,
    "queued": 2,
    "cancelled": 1,
    "failed": 0,
    "unknown": -1,
}
_METRIC_SPECS = {
    "duration_s": ("timing", "duration_s", "lower"),
    "execution_time_s_sum": ("timing", "execution_time_s_sum", "lower"),
    "tokens_sum": ("cost", "tokens_sum", "lower"),
    "cost_usd_sum": ("cost", "cost_usd_sum", "lower"),
    "policy_issue_count": ("summary_metrics", "policy_issue_count", "lower"),
    "artifact_completeness_ratio": (
        "summary_metrics",
        "artifact_completeness_ratio",
        "higher",
    ),
    "warning_count": ("summary_metrics", "warning_count", "lower"),
    "error_count": ("summary_metrics", "error_count", "lower"),
    "step_success_rate": ("summary_metrics", "step_success_rate", "higher"),
}


def get_loop_profile(profile_id: str = DEFAULT_LOOP_PROFILE_ID) -> dict[str, Any]:
    """Return the versioned loop profile for external coding agents."""

    normalized = str(profile_id or "").strip() or DEFAULT_LOOP_PROFILE_ID
    if normalized != DEFAULT_LOOP_PROFILE_ID:
        raise ValueError(f"unknown loop profile: {profile_id}")

    return {
        "profile_id": DEFAULT_LOOP_PROFILE_ID,
        "title": "External Coding Harness",
        "summary": (
            "Use Brain Researcher MCP as a deterministic harness around external "
            "coding agents. MCP handles discovery, recipes, run observation, and "
            "comparison; the client owns code mutation."
        ),
        "audience": "external_mcp_clients",
        "recommended_call_order": [
            "loop_profile_get",
            "tool_search",
            "tool_get",
            "get_execution_recipe",
            "pipeline_plan_validate",
            "run_bundle_get",
            "run_scorecard",
            "run_compare",
        ],
        "mutation_policy": {
            "mcp_edits_repo": False,
            "mutable_scope_source": "client_supplied_focus_paths",
            "allowed_mutation_pattern": (
                "External coding agents may edit only the repo paths explicitly "
                "selected by the user. Brain Researcher MCP never writes code into "
                "the repo."
            ),
            "promotion_policy": (
                "Promotion/merge decisions remain outside MCP in v1. Use "
                "run_scorecard and run_compare to make keep/discard decisions."
            ),
        },
        "clarification_policy": {
            "mode": "single_question_blocking",
            "summary": (
                "When Brain Researcher requests clarification, stop execution and "
                "ask the user exactly one unresolved question before continuing."
            ),
            "question_extraction_order": [
                "metadata.questions[0]",
                "question",
            ],
            "block_execution_until_answered": True,
            "resume_with_accumulated_answers": True,
            "rules": [
                "Ask only one clarification question per turn.",
                "If metadata.type == 'clarification', ask metadata.questions[0].",
                "Otherwise, if clarification_needed == true and question is present, ask question.",
                "Do not combine multiple unresolved ambiguities into one message.",
                "Do not add extra follow-up questions in the same turn.",
                "After the user answers, resume the original task with accumulated clarification answers.",
            ],
        },
        "tool_families": [
            {
                "family": "discovery",
                "for_agents": True,
                "recommended_tools": [
                    "tool_search",
                    "tool_get",
                    "tool_resolve",
                    "workflow_search",
                ],
            },
            {
                "family": "local_recipe_generation",
                "for_agents": True,
                "recommended_tools": ["get_execution_recipe"],
            },
            {
                "family": "validation",
                "for_agents": True,
                "recommended_tools": ["pipeline_plan_validate"],
            },
            {
                "family": "run_observation",
                "for_agents": True,
                "recommended_tools": [
                    "run_get",
                    "run_bundle_get",
                    "run_scorecard",
                    "run_compare",
                    "artifact_list",
                    "artifact_read_text",
                    "run_metrics",
                ],
            },
            {
                "family": "manual_admin_execution",
                "for_agents": False,
                "recommended_tools": ["tool_execute", "pipeline_execute"],
                "notes": [
                    "These remain manual/admin paths and are intentionally gated.",
                ],
            },
        ],
        "review_flow": {
            "baseline": "Capture a baseline run and scorecard before comparing variants.",
            "compare": (
                "Use run_compare after each candidate run. Treat mixed or "
                "incomparable results as non-promotable until manually reviewed."
            ),
            "keep_discard": (
                "Keep/discard remains a client-side decision in v1; MCP only "
                "returns normalized evidence."
            ),
        },
        "notes": [
            "Prefer local recipe execution or hosted MCP calls over generic remote execution.",
            "Preview semantics are exposed through get_execution_recipe agent metadata.",
            "MCP observation bundles are intended to be machine-readable inputs to external loops.",
        ],
    }


def build_run_bundle_payload(
    run_id: str,
    *,
    record: dict[str, Any],
    run_dir: Path,
) -> tuple[dict[str, Any], list[str]]:
    """Build a normalized run bundle payload from persisted MCP artifacts."""

    warnings: list[str] = []
    component_status: dict[str, str] = {}
    loaded_components: dict[str, Any] = {}
    for component, relpath in _BUNDLE_COMPONENT_FILES.items():
        if component == "trace_jsonl":
            payload = None
            state, warning = _trace_component_status(run_dir / relpath, component)
        else:
            payload, state, warning = _load_json_component(run_dir / relpath, component)
        if payload is None:
            component_status[component] = state
            if warning:
                warnings.append(warning)
        else:
            component_status[component] = state
        loaded_components[component] = payload

    trace_summary, trace_warnings = _summarize_trace(run_dir / "trace.jsonl")
    trajectory_summary = _summarize_trajectory(
        loaded_components.get("trajectory_json"),
        component_status.get("trajectory_json") == "present",
    )
    warnings.extend(trace_warnings)
    artifact_contract = build_artifact_contract_summary(
        run_dir=run_dir,
        job_profile=_artifact_contract_profile_for_record(record),
        state=str(record.get("status") or ""),
    )

    payload = {
        "profile_id": DEFAULT_LOOP_PROFILE_ID,
        "run_id": run_id,
        "run": record,
        "observation": loaded_components.get("observation_json"),
        "analysis_bundle": loaded_components.get("analysis_bundle_json"),
        "trajectory_summary": trajectory_summary,
        "trace_summary": trace_summary,
        "artifact_index": build_artifact_index(run_dir),
        "component_status": component_status,
        "artifact_contract": artifact_contract,
    }
    return payload, _dedupe_strings(warnings)


def _artifact_contract_profile_for_record(record: dict[str, Any]) -> str:
    explicit = str(record.get("artifact_contract_profile") or "").strip()
    if explicit:
        return explicit

    payload = record.get("payload")
    if not isinstance(payload, dict):
        payload_json = record.get("payload_json")
        if isinstance(payload_json, str) and payload_json.strip():
            try:
                parsed = json.loads(payload_json)
            except Exception:
                parsed = None
            payload = parsed if isinstance(parsed, dict) else None

    inferred = infer_artifact_profile(
        job_kind=str(record.get("kind") or ""),
        payload=payload if isinstance(payload, dict) else None,
    )
    return "run_bundle" if inferred == "default" else inferred


def build_run_scorecard(
    run_id: str,
    *,
    profile_id: str,
    record: dict[str, Any],
    run_dir: Path,
    metrics: dict[str, Any],
    bundle_payload: dict[str, Any],
    bundle_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a normalized scorecard for a persisted MCP run."""

    policy_issues: list[dict[str, Any]] = []
    step_cards: list[dict[str, Any]] = []
    errors: list[str] = []
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_policy_issues = [
            issue
            for issue in (step.get("policy_issues") or [])
            if isinstance(issue, dict)
        ]
        policy_issues.extend(step_policy_issues)
        step_error = str(step.get("error") or "").strip()
        if step_error:
            errors.append(step_error)
        step_cards.append(
            {
                "step_id": step.get("step_id"),
                "tool_id": step.get("tool_id"),
                "status": step.get("status"),
                "started_at": step.get("started_at"),
                "finished_at": step.get("finished_at"),
                "policy_issue_count": len(step_policy_issues),
                "error": step_error or None,
            }
        )

    record_error = str(record.get("error") or "").strip()
    if record_error:
        errors.append(record_error)

    artifact_status = (
        bundle_payload.get("artifact_contract")
        if isinstance(bundle_payload.get("artifact_contract"), dict)
        else _artifact_completeness(run_dir)
    )
    totals = metrics.get("totals") if isinstance(metrics.get("totals"), dict) else {}
    succeeded_steps = sum(1 for step in step_cards if step.get("status") == "succeeded")
    total_steps = len(step_cards)
    warnings = _dedupe_strings(
        list(bundle_warnings or []) + _bundle_status_warnings(bundle_payload)
    )

    return {
        "profile_id": profile_id,
        "run_id": run_id,
        "status": record.get("status", "unknown"),
        "completion_state": normalize_completion_state(record.get("status")),
        "policy": {
            "issue_count": len(policy_issues),
            "issues": policy_issues,
        },
        "artifacts": artifact_status,
        "timing": {
            "duration_s": metrics.get("duration_s"),
            "execution_time_s_sum": totals.get("execution_time_s_sum"),
            "steps_total": totals.get("steps"),
            "steps_succeeded": totals.get("succeeded"),
            "steps_failed": totals.get("failed"),
            "steps_skipped": totals.get("skipped"),
        },
        "cost": {
            "tokens_sum": totals.get("tokens_sum"),
            "cost_usd_sum": totals.get("cost_usd_sum"),
        },
        "steps": step_cards,
        "warnings": warnings,
        "errors": _dedupe_strings(errors),
        "summary_metrics": {
            "policy_issue_count": len(policy_issues),
            "artifact_completeness_ratio": artifact_status["completeness_ratio"],
            "warning_count": len(warnings),
            "error_count": len(_dedupe_strings(errors)),
            "step_success_rate": (
                round(succeeded_steps / total_steps, 4) if total_steps else None
            ),
        },
    }


def compare_run_scorecards(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    metric_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Compare two normalized run scorecards."""

    criteria: list[dict[str, Any]] = []
    warnings: list[str] = []
    wins = {"baseline": 0, "candidate": 0}

    for name, baseline_value, candidate_value, direction in [
        (
            "completion_state",
            _COMPLETION_ORDER.get(str(baseline.get("status", "unknown")), -1),
            _COMPLETION_ORDER.get(str(candidate.get("status", "unknown")), -1),
            "higher",
        ),
        (
            "policy_issue_count",
            _metric_value(baseline, "policy_issue_count"),
            _metric_value(candidate, "policy_issue_count"),
            "lower",
        ),
        (
            "artifact_completeness_ratio",
            _metric_value(baseline, "artifact_completeness_ratio"),
            _metric_value(candidate, "artifact_completeness_ratio"),
            "higher",
        ),
    ]:
        _append_comparison(
            criteria, wins, name, baseline_value, candidate_value, direction
        )

    for metric_key in metric_keys or []:
        metric_value = _resolve_metric_key(metric_key)
        if metric_value is None:
            warnings.append(f"unsupported metric key: {metric_key}")
            continue
        normalized_key, direction = metric_value
        _append_comparison(
            criteria,
            wins,
            normalized_key,
            _metric_value(baseline, normalized_key),
            _metric_value(candidate, normalized_key),
            direction,
            requested_key=metric_key,
        )

    for metric_key in ("duration_s", "cost_usd_sum"):
        metric_value = _resolve_metric_key(metric_key)
        if metric_value is None:
            continue
        normalized_key, direction = metric_value
        _append_comparison(
            criteria,
            wins,
            normalized_key,
            _metric_value(baseline, normalized_key),
            _metric_value(candidate, normalized_key),
            direction,
        )

    if wins["candidate"] and not wins["baseline"]:
        decision_hint = "candidate_better"
    elif wins["baseline"] and not wins["candidate"]:
        decision_hint = "baseline_better"
    elif wins["baseline"] and wins["candidate"]:
        decision_hint = "mixed"
    else:
        decision_hint = "incomparable"

    return {
        "decision_hint": decision_hint,
        "criteria": criteria,
        "warnings": _dedupe_strings(warnings),
    }


def normalize_completion_state(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"succeeded", "failed", "cancelled"}:
        return normalized
    if normalized in {"queued", "running"}:
        return "in_progress"
    return "unknown"


def build_artifact_index(run_dir: Path) -> list[dict[str, Any]]:
    """List run-relative artifact files under the artifacts directory."""

    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(artifacts_dir.rglob("*")):
        if path.is_dir():
            continue
        items.append(
            {
                "relpath": str(path.relative_to(run_dir)),
                "size_bytes": path.stat().st_size,
            }
        )
    return items


def _artifact_completeness(run_dir: Path) -> dict[str, Any]:
    return build_artifact_contract_summary(
        run_dir=run_dir,
        job_profile="run_bundle",
        state="succeeded",
    )


def _bundle_status_warnings(bundle_payload: dict[str, Any]) -> list[str]:
    status = (
        bundle_payload.get("component_status")
        if isinstance(bundle_payload.get("component_status"), dict)
        else {}
    )
    warnings: list[str] = []
    for component, state in status.items():
        if state != "present":
            warnings.append(f"{component} missing from persisted run bundle")
    return warnings


def _append_comparison(
    criteria: list[dict[str, Any]],
    wins: dict[str, int],
    name: str,
    baseline_value: Any,
    candidate_value: Any,
    direction: str,
    *,
    requested_key: str | None = None,
) -> None:
    if baseline_value is None or candidate_value is None:
        criteria.append(
            {
                "name": name,
                "requested_key": requested_key,
                "baseline": baseline_value,
                "candidate": candidate_value,
                "winner": "incomparable",
            }
        )
        return

    winner = "tie"
    if baseline_value != candidate_value:
        if direction == "higher":
            winner = "candidate" if candidate_value > baseline_value else "baseline"
        else:
            winner = "candidate" if candidate_value < baseline_value else "baseline"

    if winner in wins:
        wins[winner] += 1
    criteria.append(
        {
            "name": name,
            "requested_key": requested_key,
            "baseline": baseline_value,
            "candidate": candidate_value,
            "winner": winner,
        }
    )


def _resolve_metric_key(metric_key: str) -> tuple[str, str] | None:
    normalized = str(metric_key or "").strip()
    if not normalized:
        return None
    if normalized in _METRIC_SPECS:
        section, key, direction = _METRIC_SPECS[normalized]
        return f"{section}.{key}", direction
    if "." in normalized:
        return normalized, "lower"
    return None


def _metric_value(scorecard: dict[str, Any], metric_key: str) -> Any:
    if metric_key in _METRIC_SPECS:
        section, key, _ = _METRIC_SPECS[metric_key]
        metric_key = f"{section}.{key}"

    cursor: Any = scorecard
    for part in metric_key.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    if isinstance(cursor, bool):
        return int(cursor)
    return cursor if isinstance(cursor, int | float) else cursor


def _load_json_component(
    path: Path, component_name: str
) -> tuple[dict[str, Any] | list[Any] | None, str, str | None]:
    if not path.exists():
        return None, "missing", f"{component_name} is missing"
    try:
        if path.stat().st_size == 0:
            return None, "empty", f"{component_name} is empty"
    except OSError:
        pass
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return None, "unreadable", f"{component_name} is unreadable: {type(exc).__name__}"
    if isinstance(payload, dict | list):
        return payload, "present", None
    return (
        None,
        "unreadable",
        f"{component_name} does not contain JSON object/array content",
    )


def _trace_component_status(path: Path, component_name: str) -> tuple[str, str | None]:
    if not path.exists():
        return "missing", f"{component_name} is missing"
    try:
        if path.stat().st_size == 0:
            return "empty", f"{component_name} is empty"
    except OSError:
        return "unreadable", f"{component_name} is unreadable: OSError"
    return "present", None


def _summarize_trace(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, ["trace_jsonl is missing"]
    warnings: list[str] = []
    line_count = 0
    parsed_count = 0
    event_counts: Counter[str] = Counter()
    first_event: str | None = None
    last_event: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        line_count += 1
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            warnings.append("trace_jsonl contains non-JSON lines")
            continue
        if not isinstance(payload, dict):
            warnings.append("trace_jsonl contains non-object entries")
            continue
        parsed_count += 1
        event_type = str(payload.get("event_type") or payload.get("type") or "unknown")
        event_counts[event_type] += 1
        if first_event is None:
            first_event = event_type
        last_event = event_type
    return (
        {
            "path": "trace.jsonl",
            "line_count": line_count,
            "parsed_event_count": parsed_count,
            "event_types": dict(event_counts),
            "first_event_type": first_event,
            "last_event_type": last_event,
        },
        _dedupe_strings(warnings),
    )


def _summarize_trajectory(payload: Any, exists: bool) -> dict[str, Any] | None:
    if not exists:
        return None
    if not isinstance(payload, dict):
        return {"exists": True, "schema_version": None, "step_count": None}
    steps = payload.get("steps")
    return {
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "step_count": len(steps) if isinstance(steps, list) else None,
        "status": payload.get("status") or payload.get("state"),
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
