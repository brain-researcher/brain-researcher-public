from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from brain_researcher.services.orchestrator.dag_runtime import (
    WorkflowDefinition,
    WorkflowStep,
)
from brain_researcher.services.shared.planner.handoff import (
    build_handoff_from_plan_payload,
)


def _normalize_step_id(
    raw_id: str | None, fallback_index: int, tool: str | None
) -> str:
    if raw_id:
        return raw_id
    slug = (tool or "step").replace(".", "-").replace(" ", "-")
    return f"{fallback_index:03d}-{slug}"


def _build_producer_index(steps: List[Tuple[Dict[str, Any], str]]) -> Dict[str, str]:
    produced: Dict[str, str] = {}
    for step, step_id in steps:
        for artifact_name in (step.get("produces") or {}).values():
            produced[artifact_name] = step_id
    return produced


def _derive_dependencies(
    step: Dict[str, Any],
    produced_by: Dict[str, str],
    default_step_id: str,
) -> List[str]:
    dependencies: Set[str] = set(step.get("depends_on") or [])
    consumes = step.get("consumes") or {}
    for artifact in consumes.values():
        producer = produced_by.get(artifact)
        if producer and producer != default_step_id:
            dependencies.add(producer)
    return sorted(dependencies)


def plan_to_workflow(plan_payload: Dict[str, Any]) -> WorkflowDefinition:
    """Convert a cached plan payload into a WorkflowDefinition."""

    dag = plan_payload.get("dag") or {}
    raw_steps = dag.get("steps") or plan_payload.get("steps") or []
    workflow_id = plan_payload.get("plan_id", "workflow")

    normalized_steps: List[Tuple[Dict[str, Any], str, str | None]] = []
    for idx, step in enumerate(raw_steps, start=1):
        tool_id = step.get("tool")
        step_id = _normalize_step_id(step.get("id"), idx, tool_id)
        normalized_steps.append((step, step_id, tool_id))

    produced_by = _build_producer_index(
        [(step, step_id) for step, step_id, _ in normalized_steps]
    )

    workflow_steps: List[WorkflowStep] = []
    for step, step_id, tool_id in normalized_steps:
        workflow_steps.append(
            WorkflowStep(
                step_id=step_id,
                tool_name=tool_id,
                parameters=step.get("params", {}),
                depends_on=_derive_dependencies(step, produced_by, step_id),
                metadata={
                    "consumes": step.get("consumes", {}),
                    "produces": step.get("produces", {}),
                    "runtime_kind": step.get("runtime_kind", "container"),
                },
            )
        )

    handoff = build_handoff_from_plan_payload(plan_payload, workflow_id=workflow_id)
    handoff.pop("schema_version", None)

    metadata = {
        "version": plan_payload.get("version"),
        "handoff": handoff,
        "execution": {
            "chosen_tool": handoff.get("chosen_tool"),
            "approval_level": handoff.get("approval_level"),
            "allowed_tools": handoff.get("allowed_tools") or [],
            "run_mode_hint": handoff.get("run_mode_hint"),
        },
    }

    return WorkflowDefinition(
        workflow_id=workflow_id,
        steps=workflow_steps,
        metadata=metadata,
    )
