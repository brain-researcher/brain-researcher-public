"""Adapter for converting Plan DAG to Nipype workflow builder arguments.

Transforms Plan/PlanDAG/StepSpec from the shared planning contract into
the format expected by NipypeWorkflowBuilderTool.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.adapters.tool_interface_map import (
    InterfaceSpec,
    get_interface_spec,
    load_tool_interface_map,
)
from brain_researcher.services.shared.planner.models import Plan, RuntimeKind, StepSpec

logger = logging.getLogger(__name__)

# Runtime kinds that can be exported to Nipype
SUPPORTED_RUNTIME_KINDS: set[RuntimeKind] = {"container", "python"}
UNSUPPORTED_RUNTIME_KINDS: set[RuntimeKind] = {"api"}


@dataclass
class NipypeExportResult:
    """Result of plan-to-Nipype conversion."""

    # Arguments for NipypeWorkflowBuilderTool._run()
    builder_args: dict[str, Any]

    # Metadata
    plan_id: str
    exported_steps: list[str]
    skipped_steps: list[str]
    warnings: list[str]

    # Mapping of step_id -> node_name for reference
    step_to_node: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "builder_args": self.builder_args,
            "plan_id": self.plan_id,
            "exported_steps": self.exported_steps,
            "skipped_steps": self.skipped_steps,
            "warnings": self.warnings,
            "step_to_node": self.step_to_node,
        }


def _sanitize_node_name(step_id: str) -> str:
    """Convert step ID to valid Nipype node name.

    Nipype node names must be valid Python identifiers.
    """
    # Replace hyphens and other invalid chars with underscores
    sanitized = step_id.replace("-", "_").replace(".", "_").replace(" ", "_")
    # Ensure it starts with a letter
    if sanitized and sanitized[0].isdigit():
        sanitized = "n_" + sanitized
    return sanitized or "node"


def _map_step_to_node(
    step: StepSpec,
    interface_map: dict[str, InterfaceSpec],
) -> tuple[dict[str, Any] | None, str | None]:
    """Convert a StepSpec to a Nipype node configuration.

    Args:
        step: The StepSpec to convert
        interface_map: Tool-to-interface mapping

    Returns:
        Tuple of (node_config, warning_message)
        - node_config is None if step cannot be converted
        - warning_message explains why if conversion failed
    """
    node_name = _sanitize_node_name(step.id)

    # Get interface spec
    iface_spec = get_interface_spec(step.tool, interface_map)

    if iface_spec is None:
        # Fallback to IdentityInterface with fields from consumes/produces
        fields = list(step.consumes.keys()) or ["in_file"]
        return {
            "name": node_name,
            "fields": fields,
        }, f"No interface mapping for tool '{step.tool}', using IdentityInterface"

    # Build node configuration
    node_config: dict[str, Any] = {
        "name": node_name,
        "interface": {
            "type": iface_spec.get("type", "utility"),
            "name": iface_spec.get("name", "IdentityInterface"),
            "params": dict(step.params) if step.params else {},
        },
    }

    return node_config, None


def _derive_connections(
    steps: list[StepSpec],
    step_to_node: dict[str, str],
    interface_map: dict[str, InterfaceSpec],
) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """Derive DAG connections from produces/consumes relationships.

    Strategy:
    1. Match by resource NAME (not just type) - e.g., "preproc_bold"
    2. Use io_map to translate logical names to Nipype field names
    3. Only connect steps where produces resource matches consumes resource

    Args:
        steps: List of StepSpec objects
        step_to_node: Mapping from step.id to node_name
        interface_map: Tool-to-interface mapping

    Returns:
        Tuple of (connections, warnings)
    """
    connections: list[tuple[str, str, str, str]] = []
    warnings: list[str] = []

    # Build index of which steps produce which resources
    resource_producers: dict[str, tuple[StepSpec, str]] = (
        {}
    )  # resource_name -> (step, resource_type)
    for step in steps:
        for res_name, res_type in (step.produces or {}).items():
            if res_name in resource_producers:
                prev_step, _ = resource_producers[res_name]
                warnings.append(
                    f"Resource '{res_name}' produced by multiple steps: "
                    f"{prev_step.id} and {step.id}; using {step.id}"
                )
            resource_producers[res_name] = (step, res_type)

    # For each consumer, find matching producers
    for consumer_step in steps:
        consumer_iface = get_interface_spec(consumer_step.tool, interface_map)
        consumer_io_map = consumer_iface.get("io_map", {}) if consumer_iface else {}
        consumer_consumes_map = consumer_io_map.get("consumes", {})

        for res_name, res_type in (consumer_step.consumes or {}).items():
            if res_name not in resource_producers:
                # No producer for this resource - might be an input
                continue

            producer_step, producer_res_type = resource_producers[res_name]

            # Skip self-connections
            if producer_step.id == consumer_step.id:
                continue

            # Optional: warn if types don't match
            if producer_res_type != res_type:
                warnings.append(
                    f"Type mismatch for resource '{res_name}': "
                    f"producer {producer_step.id} has type '{producer_res_type}', "
                    f"consumer {consumer_step.id} expects '{res_type}'"
                )

            # Get Nipype field names from io_map
            producer_iface = get_interface_spec(producer_step.tool, interface_map)
            producer_io_map = producer_iface.get("io_map", {}) if producer_iface else {}
            producer_produces_map = producer_io_map.get("produces", {})

            # Map logical resource names to Nipype field names
            from_field = producer_produces_map.get(res_name, "out_file")
            to_field = consumer_consumes_map.get(res_name, "in_file")

            # Add connection
            from_node = step_to_node.get(
                producer_step.id, _sanitize_node_name(producer_step.id)
            )
            to_node = step_to_node.get(
                consumer_step.id, _sanitize_node_name(consumer_step.id)
            )

            connections.append((from_node, from_field, to_node, to_field))
            logger.debug(
                "Added connection: %s.%s -> %s.%s (resource: %s)",
                from_node,
                from_field,
                to_node,
                to_field,
                res_name,
            )

    # Fallback: if no explicit resources connect steps, create a linear chain.
    if not connections and len(steps) > 1:
        warnings.append(
            "No produces/consumes links found; using linear step connections"
        )
        for idx in range(len(steps) - 1):
            producer_step = steps[idx]
            consumer_step = steps[idx + 1]

            producer_iface = get_interface_spec(producer_step.tool, interface_map)
            consumer_iface = get_interface_spec(consumer_step.tool, interface_map)
            producer_io = producer_iface.get("io_map", {}) if producer_iface else {}
            consumer_io = consumer_iface.get("io_map", {}) if consumer_iface else {}

            produces_map = producer_io.get("produces", {}) or {}
            consumes_map = consumer_io.get("consumes", {}) or {}

            # Choose first mapped field if available, otherwise defaults.
            from_field = next(iter(produces_map.values()), "out_file")
            to_field = next(iter(consumes_map.values()), "in_file")

            from_node = step_to_node.get(
                producer_step.id, _sanitize_node_name(producer_step.id)
            )
            to_node = step_to_node.get(
                consumer_step.id, _sanitize_node_name(consumer_step.id)
            )

            connections.append((from_node, from_field, to_node, to_field))

    return connections, warnings


def plan_to_nipype_builder_args(
    plan: Plan,
    base_dir: str,
    plugin: str = "MultiProc",
    plugin_args: dict[str, Any] | None = None,
    strict: bool = False,
    interface_map: dict[str, InterfaceSpec] | None = None,
) -> NipypeExportResult:
    """Convert a Plan to NipypeWorkflowBuilderTool arguments.

    Args:
        plan: The Plan object to convert
        base_dir: Base directory for the workflow
        plugin: Execution plugin (Linear, MultiProc, SLURM, etc.)
        plugin_args: Plugin-specific arguments
        strict: If True, raise error for unsupported steps; if False, skip with warning
        interface_map: Optional pre-loaded interface mapping

    Returns:
        NipypeExportResult containing builder args and metadata

    Raises:
        ValueError: If strict=True and plan contains unsupported steps
    """
    if interface_map is None:
        interface_map = load_tool_interface_map()

    nodes: list[dict[str, Any]] = []
    exported_steps: list[str] = []
    skipped_steps: list[str] = []
    warnings: list[str] = []
    step_to_node: dict[str, str] = {}

    # Process each step
    for step in plan.dag.steps:
        # Check runtime_kind
        if step.runtime_kind in UNSUPPORTED_RUNTIME_KINDS:
            msg = f"Step '{step.id}' has unsupported runtime_kind='{step.runtime_kind}'"
            if strict:
                raise ValueError(msg)
            warnings.append(f"{msg}, skipped")
            skipped_steps.append(step.id)
            continue

        # Convert step to node
        node_config, warning = _map_step_to_node(step, interface_map)

        if node_config is None:
            msg = f"Failed to convert step '{step.id}' to node"
            if strict:
                raise ValueError(msg)
            warnings.append(msg)
            skipped_steps.append(step.id)
            continue

        if warning:
            warnings.append(warning)

        nodes.append(node_config)
        exported_steps.append(step.id)
        step_to_node[step.id] = node_config["name"]

    # Derive connections from produces/consumes
    # Only consider exported steps
    exported_step_specs = [s for s in plan.dag.steps if s.id in exported_steps]
    connections, conn_warnings = _derive_connections(
        exported_step_specs, step_to_node, interface_map
    )
    warnings.extend(conn_warnings)

    # Build result
    builder_args: dict[str, Any] = {
        "name": f"plan_{plan.plan_id.replace('-', '_')}",
        "base_dir": base_dir,
        "nodes": nodes,
        "connections": connections,
        "plugin": plugin,
        "plugin_args": plugin_args or {},
    }

    return NipypeExportResult(
        builder_args=builder_args,
        plan_id=plan.plan_id,
        exported_steps=exported_steps,
        skipped_steps=skipped_steps,
        warnings=warnings,
        step_to_node=step_to_node,
    )


def export_plan_to_nipype(
    plan: Plan,
    output_dir: str,
    plugin: str = "MultiProc",
    plugin_args: dict[str, Any] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Export a Plan to Nipype workflow files.

    This is the high-level function that:
    1. Converts Plan to builder args
    2. Calls NipypeWorkflowBuilderTool
    3. Saves original plan for provenance
    4. Returns paths and metadata

    Args:
        plan: The Plan object to export
        output_dir: Directory to write workflow files (plan_id subfolder will be created)
        plugin: Execution plugin
        plugin_args: Plugin-specific arguments
        strict: If True, fail on unsupported steps

    Returns:
        Dictionary with workflow_file, config_file, graph_file, etc.
    """
    from brain_researcher.services.tools.nipype_tool import NipypeWorkflowBuilderTool

    # Create output directory with plan_id
    workflow_dir = Path(output_dir) / plan.plan_id
    workflow_dir.mkdir(parents=True, exist_ok=True)

    # Convert plan to builder args
    export_result = plan_to_nipype_builder_args(
        plan=plan,
        base_dir=str(workflow_dir),
        plugin=plugin,
        plugin_args=plugin_args,
        strict=strict,
    )

    # Save original plan for provenance
    plan_file = workflow_dir / "plan.json"
    plan_file.write_text(plan.model_dump_json(indent=2))

    # Call the builder tool
    tool = NipypeWorkflowBuilderTool()
    tool_result = tool._run(**export_result.builder_args)

    if tool_result.status != "success":
        return {
            "status": "error",
            "error": tool_result.error,
            "plan_id": plan.plan_id,
            "skipped_steps": export_result.skipped_steps,
            "warnings": export_result.warnings,
        }

    # Extract file paths from tool result
    tool_data = tool_result.data or {}

    graph_file = tool_data.get("graph_file")

    response = {
        "status": "success",
        "plan_id": plan.plan_id,
        "workflow_file": tool_data.get("workflow_file"),
        "config_file": tool_data.get("config_file"),
        "original_plan_file": str(plan_file),
        "run_command": f"python {tool_data.get('workflow_file', '')}",
        "exported_steps": export_result.exported_steps,
        "skipped_steps": export_result.skipped_steps,
        "warnings": export_result.warnings,
        "step_to_node": export_result.step_to_node,
        "graph_generated": bool(graph_file),
    }

    # Only include graph_file if builder returned one to avoid confusing clients
    if graph_file:
        response["graph_file"] = graph_file

    return response


__all__ = [
    "NipypeExportResult",
    "plan_to_nipype_builder_args",
    "export_plan_to_nipype",
    "SUPPORTED_RUNTIME_KINDS",
    "UNSUPPORTED_RUNTIME_KINDS",
]
