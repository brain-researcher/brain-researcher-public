"""Compact planner handoff helpers shared across services."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pydantic import BaseModel, Field

HANDOFF_SCHEMA_VERSION = "br-plan-handoff-v1"


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text) if "." in text else int(text)
    except Exception:
        return None


def _string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    normalized: List[str] = []
    seen: set[str] = set()
    for item in values:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _max_approval_level(*levels: str | None) -> str:
    order = {"none": 0, "confirm": 1, "admin": 2}
    best = "none"
    for level in levels:
        candidate = _text(level) or "none"
        if order.get(candidate, 0) > order.get(best, 0):
            best = candidate
    return best


def _jsonish(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    mapping = _as_mapping(value)
    if mapping is not None:
        normalized: Dict[str, Any] = {}
        for key, item in mapping.items():
            key_text = _text(key)
            if not key_text:
                continue
            normalized[key_text] = _jsonish(item)
        return normalized
    if isinstance(value, (list, tuple, set)):
        return [_jsonish(item) for item in value]
    return str(value)


def _dict(value: Any) -> Dict[str, Any]:
    mapping = _as_mapping(value)
    if mapping is None:
        return {}
    normalized = _jsonish(mapping)
    return normalized if isinstance(normalized, dict) else {}


def _pick_string(container: Any, *keys: str) -> str | None:
    mapping = _as_mapping(container)
    if mapping is None:
        return None
    for key in keys:
        value = _text(mapping.get(key))
        if value:
            return value
    return None


def _pick_inputs(
    plan_payload: Mapping[str, Any], context: Mapping[str, Any]
) -> Dict[str, Any]:
    top_level_inputs = _dict(plan_payload.get("inputs"))
    context_inputs = _dict(context.get("inputs"))
    return top_level_inputs or context_inputs


def _pick_workflow_id(
    *,
    plan_payload: Mapping[str, Any],
    context: Mapping[str, Any],
    chosen_tool: str | None,
    explicit_workflow_id: str | None,
) -> str | None:
    if explicit_workflow_id:
        return explicit_workflow_id

    context_workflow_id = _pick_string(context, "workflow_id")
    if context_workflow_id:
        return context_workflow_id

    if chosen_tool and chosen_tool.startswith("workflow_"):
        return chosen_tool

    dag = _dict(plan_payload.get("dag"))
    steps = dag.get("steps") or plan_payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            tool_id = _pick_string(step, "tool")
            if tool_id and tool_id.startswith("workflow_"):
                return tool_id

    return _pick_string(plan_payload, "plan_id")


def _pick_dataset_ref(
    *,
    plan_payload: Mapping[str, Any],
    inputs: Mapping[str, Any],
    context: Mapping[str, Any],
) -> str | None:
    for source in (plan_payload, inputs, context):
        dataset_ref = _pick_string(source, "dataset_ref", "dataset_id")
        if dataset_ref:
            return dataset_ref

    for source in (
        plan_payload.get("query_understanding"),
        context.get("query_understanding"),
        plan_payload.get("cross_stage_context"),
    ):
        mapping = _dict(source)
        dataset_ref = _pick_string(mapping, "dataset_ref", "dataset_id")
        if dataset_ref:
            return dataset_ref
        for key in ("resolved_datasets", "candidate_datasets", "datasets"):
            items = mapping.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                dataset_ref = _pick_string(
                    item, "dataset_id", "id", "ref", "openneuro_id"
                )
                if dataset_ref:
                    return dataset_ref
    return None


def _pick_chosen_tool(plan_payload: Mapping[str, Any]) -> str | None:
    chosen_tool = _pick_string(plan_payload, "chosen_tool")
    if chosen_tool:
        return chosen_tool
    dag = _dict(plan_payload.get("dag"))
    steps = dag.get("steps") or plan_payload.get("steps")
    if isinstance(steps, list) and steps:
        return _pick_string(steps[0], "tool")
    return None


def _plan_step_tool_ids(plan_payload: Mapping[str, Any]) -> List[str]:
    collected: List[str] = []

    def _add(tool_id: Any) -> None:
        text = _text(tool_id)
        if text and text not in collected:
            collected.append(text)

    _add(plan_payload.get("chosen_tool"))

    dag = _dict(plan_payload.get("dag"))
    steps = dag.get("steps") or plan_payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            _add(step.get("tool"))

    return collected


def _toolspec_metadata(tool_id: str) -> tuple[list[str], str]:
    try:
        from brain_researcher.services.tools.catalog_loader import get_toolspec_by_name

        spec = get_toolspec_by_name(tool_id)
    except Exception:
        spec = None

    if spec is None:
        if tool_id in {"pipeline_execute", "tool_execute"}:
            return ["admin"], "admin"
        if str(tool_id).startswith("workflow_"):
            return ["plan"], "none"
        return ["execute"], "confirm"
    return list(spec.allowed_phases or []), str(spec.approval_level or "none")


def _pick_allowed_tools(plan_payload: Mapping[str, Any]) -> List[str]:
    provided = _string_list(plan_payload.get("allowed_tools"))
    if provided:
        return provided

    allowed: List[str] = []
    for tool_id in _plan_step_tool_ids(plan_payload):
        phases, approval_level = _toolspec_metadata(tool_id)
        if "execute" in phases and approval_level != "admin" and tool_id not in allowed:
            allowed.append(tool_id)
    return allowed


def _pick_approval_level(
    plan_payload: Mapping[str, Any],
    *,
    allowed_tools: List[str],
) -> str:
    explicit = _text(plan_payload.get("approval_level"))
    if explicit:
        return explicit

    approval = "none"
    for tool_id in _plan_step_tool_ids(plan_payload):
        _phases, tool_approval = _toolspec_metadata(tool_id)
        approval = _max_approval_level(approval, tool_approval)

    if approval == "none" and allowed_tools:
        return "confirm"
    return approval


def _pick_run_mode_hint(
    plan_payload: Mapping[str, Any],
    *,
    chosen_tool: str | None,
    allowed_tools: List[str],
    approval_level: str,
) -> str | None:
    explicit = _text(plan_payload.get("run_mode_hint"))
    if explicit:
        return explicit
    if approval_level == "admin":
        return "admin_only"
    if chosen_tool and chosen_tool.startswith("workflow_"):
        return "recipe_required"
    if not allowed_tools:
        return "manual_review"
    if approval_level == "confirm":
        return "confirm_before_execute"
    return "direct_execute"


def _build_validation_summary(
    plan_payload: Mapping[str, Any],
    *,
    warnings: List[str],
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"warning_count": len(warnings)}

    resolvable = plan_payload.get("resolvable")
    if isinstance(resolvable, bool):
        summary["resolvable"] = resolvable

    mask_reasons = plan_payload.get("mask_reasons")
    if isinstance(mask_reasons, list):
        summary["mask_reason_count"] = len(mask_reasons)

    run_summary = _dict(plan_payload.get("run_summary"))
    if "plan_conf" in run_summary:
        plan_conf_source = run_summary.get("plan_conf")
    elif "plan_conf" in plan_payload:
        plan_conf_source = plan_payload.get("plan_conf")
    else:
        plan_conf_source = plan_payload.get("confidence_score")
    plan_conf = _number(plan_conf_source)
    if plan_conf is not None:
        summary["plan_conf"] = plan_conf

    notes = _string_list(run_summary.get("notes"))
    if notes:
        summary["notes"] = notes

    return summary


class PlannerHandoff(BaseModel):
    """Minimal handoff payload carried alongside workflow metadata."""

    schema_version: str = HANDOFF_SCHEMA_VERSION
    plan_id: str | None = None
    version: int | float | None = None
    pipeline: str | None = None
    workflow_id: str | None = None
    chosen_tool: str | None = None
    dataset_ref: str | None = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    approval_level: str = "none"
    allowed_tools: List[str] = Field(default_factory=list)
    run_mode_hint: str | None = None


def build_handoff_from_plan_payload(
    plan_payload: Mapping[str, Any],
    *,
    workflow_id: str | None = None,
) -> Dict[str, Any]:
    context = _dict(plan_payload.get("context"))
    inputs = _pick_inputs(plan_payload, context)
    warnings = _string_list(plan_payload.get("warnings")) + _string_list(
        _dict(plan_payload.get("constraints")).get("warnings")
    )
    warnings = _string_list(warnings)
    chosen_tool = _pick_chosen_tool(plan_payload)
    allowed_tools = _pick_allowed_tools(plan_payload)
    approval_level = _pick_approval_level(
        plan_payload,
        allowed_tools=allowed_tools,
    )

    handoff = PlannerHandoff(
        plan_id=_pick_string(plan_payload, "plan_id"),
        version=_number(plan_payload.get("version")),
        pipeline=_pick_string(plan_payload, "pipeline")
        or _pick_string(context, "pipeline"),
        workflow_id=_pick_workflow_id(
            plan_payload=plan_payload,
            context=context,
            chosen_tool=chosen_tool,
            explicit_workflow_id=workflow_id,
        ),
        chosen_tool=chosen_tool,
        dataset_ref=_pick_dataset_ref(
            plan_payload=plan_payload,
            inputs=inputs,
            context=context,
        ),
        inputs=inputs,
        warnings=warnings,
        validation_summary=_build_validation_summary(
            plan_payload,
            warnings=warnings,
        ),
        approval_level=approval_level,
        allowed_tools=allowed_tools,
        run_mode_hint=_pick_run_mode_hint(
            plan_payload,
            chosen_tool=chosen_tool,
            allowed_tools=allowed_tools,
            approval_level=approval_level,
        ),
    )
    return handoff.model_dump()


def build_handoff_from_recipe_context(
    *,
    tool_id: str,
    params: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    workflow_id: str | None = None,
    target_runtime: str | None = None,
) -> Dict[str, Any]:
    metadata_dict = _dict(metadata)
    payload = {
        "pipeline": metadata_dict.get("pipeline"),
        "chosen_tool": tool_id,
        "resolvable": True,
        "warnings": metadata_dict.get("warnings") or [],
        "dag": {"steps": [{"tool": tool_id}]},
        "context": {
            "pipeline": metadata_dict.get("pipeline"),
            "inputs": _dict(params),
        },
    }
    handoff = build_handoff_from_plan_payload(payload, workflow_id=workflow_id)
    handoff["execution"] = {
        "target_runtime": _text(target_runtime),
        "execution_story_kind": _text(metadata_dict.get("execution_story_kind")),
    }
    return handoff


__all__ = [
    "HANDOFF_SCHEMA_VERSION",
    "PlannerHandoff",
    "build_handoff_from_plan_payload",
    "build_handoff_from_recipe_context",
]
