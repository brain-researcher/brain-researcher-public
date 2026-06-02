"""Adapter for converting Plan DAG to Pydra workflow scripts.

Transforms Plan/PlanDAG/StepSpec from the shared planning contract into
runnable Pydra workflow Python scripts.

Pydra is a next-generation workflow engine with:
- ShellCommandTask for CLI tools (FSL, ANTs, etc.)
- FunctionTask for Python functions (nilearn, etc.)
- Lazy connections via .lzout / .lzin attributes
- Built-in container support via container_info
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import yaml

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.shared.planner.models import Plan, RuntimeKind, StepSpec

logger = logging.getLogger(__name__)

# Runtime kinds that can be exported to Pydra
SUPPORTED_RUNTIME_KINDS: set[RuntimeKind] = {"container", "python"}
UNSUPPORTED_RUNTIME_KINDS: set[RuntimeKind] = {"api"}

# Pydra tool interfaces config path.
PYDRA_TOOL_INTERFACES_PATH = resolve_from_config("pydra", "tool_interfaces.yaml")


@dataclass
class PydraInterfaceSpec:
    """Specification for a Pydra task interface."""

    type: Literal["shell", "function", "pydra_package"]
    package: Optional[str] = None  # e.g., "pydra.tasks.fsl"
    task_class: Optional[str] = None  # e.g., "BET"
    executable: Optional[str] = None  # For shell tasks
    function: Optional[str] = None  # For function tasks
    input_spec: Optional[List[Dict[str, Any]]] = None
    output_spec: Optional[List[Dict[str, Any]]] = None
    input_names: Optional[List[str]] = None
    output_names: Optional[List[str]] = None
    container_image: Optional[str] = None
    io_map: Optional[Dict[str, Dict[str, str]]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PydraInterfaceSpec":
        """Create from dictionary."""
        return cls(
            type=data.get("type", "shell"),
            package=data.get("package"),
            task_class=data.get("task_class"),
            executable=data.get("executable"),
            function=data.get("function"),
            input_spec=data.get("input_spec"),
            output_spec=data.get("output_spec"),
            input_names=data.get("input_names"),
            output_names=data.get("output_names"),
            container_image=data.get("container_image"),
            io_map=data.get("io_map"),
        )


@dataclass
class PydraExportResult:
    """Result of plan-to-Pydra conversion."""

    # Generated workflow script content
    workflow_script: str

    # Metadata
    plan_id: str
    exported_steps: List[str]
    skipped_steps: List[str]
    warnings: List[str]

    # Imports needed for the workflow
    imports: List[str] = field(default_factory=list)

    # Task specifications
    tasks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "workflow_script": self.workflow_script,
            "plan_id": self.plan_id,
            "exported_steps": self.exported_steps,
            "skipped_steps": self.skipped_steps,
            "warnings": self.warnings,
            "imports": self.imports,
            "tasks": self.tasks,
        }


def load_pydra_tool_interface_map() -> Dict[str, PydraInterfaceSpec]:
    """Load Pydra tool-to-interface mappings from YAML config.

    Returns:
        Dictionary mapping tool IDs to PydraInterfaceSpec objects
    """
    result: Dict[str, PydraInterfaceSpec] = {}

    # Load from YAML config
    yaml_path = PYDRA_TOOL_INTERFACES_PATH
    if yaml_path.exists():
        try:
            data = yaml.safe_load(yaml_path.read_text())
            tools = data.get("tools", {})
            for tool_id, spec_data in tools.items():
                result[tool_id] = PydraInterfaceSpec.from_dict(spec_data)
        except Exception as e:
            logger.warning(f"Failed to load Pydra tool interfaces: {e}")

    return result


def get_pydra_interface_spec(
    tool_id: str,
    interface_map: Optional[Dict[str, PydraInterfaceSpec]] = None,
) -> Optional[PydraInterfaceSpec]:
    """Get Pydra interface specification for a tool.

    Args:
        tool_id: The tool identifier (e.g., "fsl.bet")
        interface_map: Optional pre-loaded interface map

    Returns:
        PydraInterfaceSpec or None if not found
    """
    if interface_map is None:
        interface_map = load_pydra_tool_interface_map()

    return interface_map.get(tool_id)


def _sanitize_task_name(step_id: str) -> str:
    """Convert step ID to valid Pydra task name.

    Pydra task names must be valid Python identifiers.
    """
    sanitized = step_id.replace("-", "_").replace(".", "_").replace(" ", "_")
    if sanitized and sanitized[0].isdigit():
        sanitized = "t_" + sanitized
    return sanitized or "task"


def _generate_pydra_package_task(
    step: StepSpec,
    spec: PydraInterfaceSpec,
    task_name: str,
) -> Tuple[str, str, List[str], Optional[str]]:
    """Generate code for a Pydra package task (e.g., pydra-fsl).

    Returns:
        Tuple of (import_statement, task_code, input_field_names, warning)
    """
    import_stmt = f"from {spec.package} import {spec.task_class}"

    # Get io_map for field name mapping
    io_map = spec.io_map or {}
    consumes_map = io_map.get("consumes", {})

    # Build params dict, translating logical names to Pydra field names
    params = []
    if step.params:
        for key, value in step.params.items():
            # Translate param name if in io_map
            pydra_key = consumes_map.get(key, key)
            if isinstance(value, str):
                params.append(f'{pydra_key}="{value}"')
            else:
                params.append(f"{pydra_key}={value}")

    params_str = ", ".join(params) if params else ""
    if params_str:
        params_str = ", " + params_str

    task_code = f'    wf.add({spec.task_class}(name="{task_name}"{params_str}))'

    # Return input field names (mapped via io_map)
    input_fields = [consumes_map.get(k, k) for k in (step.consumes or {}).keys()]

    return import_stmt, task_code, input_fields, None


def _generate_shell_task(
    step: StepSpec,
    spec: PydraInterfaceSpec,
    task_name: str,
) -> Tuple[str, str, List[str], Optional[str]]:
    """Generate code for a ShellCommandTask.

    Returns:
        Tuple of (import_statement, task_code, input_field_names, warning)
    """
    import_stmt = "from pydra.engine.task import ShellCommandTask"

    # Get io_map for field name mapping
    io_map = spec.io_map or {}
    consumes_map = io_map.get("consumes", {})
    produces_map = io_map.get("produces", {})

    # Build executable and arguments
    executable = spec.executable or step.tool.split(".")[-1]

    # Build input_spec from the spec or step.consumes with io_map translation
    input_fields = []
    input_field_names = []
    if spec.input_spec:
        for inp in spec.input_spec:
            field_name = inp["name"]
            input_field_names.append(field_name)
            field_def = f'("{field_name}", str'
            if "argstr" in inp:
                field_def += f', {{"argstr": "{inp["argstr"]}"'
                if "position" in inp:
                    field_def += f', "position": {inp["position"]}'
                field_def += "}"
            field_def += ")"
            input_fields.append(field_def)
    elif step.consumes:
        # Fall back to step.consumes with io_map translation
        for idx, (res_name, res_type) in enumerate(step.consumes.items()):
            pydra_field = consumes_map.get(res_name, res_name)
            input_field_names.append(pydra_field)
            field_def = f'("{pydra_field}", str, {{"argstr": "{{{pydra_field}}}", "position": {idx}}})'
            input_fields.append(field_def)

    output_fields = []
    if spec.output_spec:
        for out in spec.output_spec:
            template = out.get("output_file_template", "")
            field_def = (
                f'("{out["name"]}", str, {{"output_file_template": "{template}"}})'
            )
            output_fields.append(field_def)
    elif step.produces:
        # Fall back to step.produces with io_map translation
        for res_name, res_type in step.produces.items():
            pydra_field = produces_map.get(res_name, res_name)
            # Default template based on first input
            first_input = input_field_names[0] if input_field_names else "in_file"
            field_def = f'("{pydra_field}", str, {{"output_file_template": "{{{first_input}}}_{pydra_field}.nii.gz"}})'
            output_fields.append(field_def)

    # Container support
    container_info = ""
    if spec.container_image:
        container_info = f', container_info=("docker", "{spec.container_image}")'

    # Build the task code
    task_code_lines = [
        f"    {task_name}_task = ShellCommandTask(",
        f'        name="{task_name}",',
        f'        executable="{executable}",',
    ]

    if input_fields:
        task_code_lines.append(f'        input_spec=[{", ".join(input_fields)}],')

    if output_fields:
        task_code_lines.append(f'        output_spec=[{", ".join(output_fields)}],')

    if container_info:
        task_code_lines.append(
            f'        container_info=("docker", "{spec.container_image}"),'
        )

    task_code_lines.append("    )")
    task_code_lines.append(f"    wf.add({task_name}_task)")

    return import_stmt, "\n".join(task_code_lines), input_field_names, None


def _generate_function_task(
    step: StepSpec,
    spec: PydraInterfaceSpec,
    task_name: str,
) -> Tuple[str, str, List[str], Optional[str]]:
    """Generate code for a FunctionTask.

    Returns:
        Tuple of (import_statement, task_code, input_field_names, warning)
    """
    import_stmt = "import pydra"

    # Get io_map for field name mapping
    io_map = spec.io_map or {}
    consumes_map = io_map.get("consumes", {})
    produces_map = io_map.get("produces", {})

    # Parse function path
    func_path = spec.function or ""

    if func_path and "." in func_path:
        # Import the function
        module_path = ".".join(func_path.split(".")[:-1])
        func_name = func_path.split(".")[-1]
        func_import = f"from {module_path} import {func_name}"
    else:
        func_import = ""
        func_name = func_path or "identity"

    # Determine input/output field names from spec or step consumes/produces with io_map
    if spec.input_names:
        input_names = spec.input_names
    elif step.consumes:
        input_names = [consumes_map.get(k, k) for k in step.consumes.keys()]
    else:
        input_names = ["in_file"]

    if spec.output_names:
        output_names = spec.output_names
    elif step.produces:
        output_names = [produces_map.get(k, k) for k in step.produces.keys()]
    else:
        output_names = ["out_file"]

    # Build proper annotation dict as a string
    # Format: {"output1": str, "output2": str}
    output_annotations = ", ".join([f'"{o}": str' for o in output_names])
    annotation_str = "{" + output_annotations + "}"

    # Build input parameter list with type annotations
    input_params = ", ".join([f"{i}: str" for i in input_names])

    task_code_lines = []
    if func_import:
        task_code_lines.append(f"    # Import: {func_import}")

    task_code_lines.extend(
        [
            f"    @pydra.mark.task",
            f'    @pydra.mark.annotate({{"return": {annotation_str}}})',
            f"    def {task_name}_func({input_params}):",
            f'        """Generated function task for {step.tool}."""',
        ]
    )

    # Build argument list for call (inputs + params)
    def _fmt_val(val):
        if isinstance(val, str):
            return f'"{val}"'
        return val

    param_args = []
    if step.params:
        for k, v in step.params.items():
            # Translate param name via consumes_map (treat params like inputs)
            pydra_key = consumes_map.get(k, k)
            param_args.append(f"{pydra_key}={_fmt_val(v)}")

    # Generate function body that calls the real function
    if func_path and func_import:
        call_inputs = ", ".join([f"{i}={i}" for i in input_names])
        call_params = ", ".join(param_args)
        call_all = ", ".join([c for c in [call_inputs, call_params] if c])
        task_code_lines.append(f"        result = {func_name}({call_all})")
        if len(output_names) == 1:
            task_code_lines.append(f"        return result")
        else:
            # Return dict for multiple outputs
            output_returns = ", ".join(
                [f'"{o}": result.get("{o}", result)' for o in output_names]
            )
            task_code_lines.append(f"        return {{{output_returns}}}")
    else:
        # Identity/passthrough - return first input for each output
        if len(output_names) == 1:
            task_code_lines.append(
                f'        return {input_names[0] if input_names else "None"}'
            )
        else:
            output_returns = ", ".join(
                [
                    f'"{o}": {input_names[0] if input_names else "None"}'
                    for o in output_names
                ]
            )
            task_code_lines.append(f"        return {{{output_returns}}}")

    task_code_lines.extend(
        [
            f"",
            f'    wf.add({task_name}_func(name="{task_name}"))',
        ]
    )

    combined_import = import_stmt
    if func_import:
        combined_import = f"{import_stmt}\n{func_import}"

    return combined_import, "\n".join(task_code_lines), input_names, None


def _generate_fallback_task(
    step: StepSpec,
    task_name: str,
) -> Tuple[str, str, List[str], str]:
    """Generate a fallback identity task when no interface is found.

    Maps all step.consumes to step.produces for data flow preservation.

    Returns:
        Tuple of (import_statement, task_code, input_field_names, warning)
    """
    import_stmt = "import pydra"

    # Create identity task that maps all inputs to outputs
    input_fields = list(step.consumes.keys()) if step.consumes else ["in_file"]
    output_fields = list(step.produces.keys()) if step.produces else ["out_file"]

    # Build proper annotation dict for outputs
    output_annotations = ", ".join([f'"{o}": str' for o in output_fields])
    annotation_str = "{" + output_annotations + "}"

    # Build input parameter list
    input_params = ", ".join([f"{i}: str" for i in input_fields])

    task_code_lines = [
        f"    # Fallback identity task for unmapped tool: {step.tool}",
        f"    @pydra.mark.task",
        f'    @pydra.mark.annotate({{"return": {annotation_str}}})',
        f"    def {task_name}_func({input_params}):",
        f'        """Identity task - passes inputs to outputs."""',
    ]

    # Return all outputs mapped from inputs (round-robin if counts differ)
    if len(output_fields) == 1:
        task_code_lines.append(
            f'        return {input_fields[0] if input_fields else "None"}'
        )
    else:
        # Map each output to corresponding input (or first input if not enough)
        output_mapping = []
        for idx, out_name in enumerate(output_fields):
            in_idx = idx % len(input_fields) if input_fields else 0
            in_name = input_fields[in_idx] if input_fields else "None"
            output_mapping.append(f'"{out_name}": {in_name}')
        task_code_lines.append(f'        return {{{", ".join(output_mapping)}}}')

    task_code_lines.extend(
        [
            f"",
            f'    wf.add({task_name}_func(name="{task_name}"))',
        ]
    )

    warning = f"No Pydra interface mapping for tool '{step.tool}', using fallback identity task"

    return import_stmt, "\n".join(task_code_lines), input_fields, warning


def _step_to_pydra_task(
    step: StepSpec,
    interface_map: Dict[str, PydraInterfaceSpec],
) -> Tuple[Optional[str], Optional[str], List[str], Optional[str]]:
    """Convert a StepSpec to Pydra task code.

    Args:
        step: The StepSpec to convert
        interface_map: Tool-to-interface mapping

    Returns:
        Tuple of (import_statement, task_code, input_field_names, warning)
    """
    task_name = _sanitize_task_name(step.id)
    spec = get_pydra_interface_spec(step.tool, interface_map)

    if spec is None:
        return _generate_fallback_task(step, task_name)

    if spec.type == "pydra_package":
        return _generate_pydra_package_task(step, spec, task_name)
    elif spec.type == "shell":
        return _generate_shell_task(step, spec, task_name)
    elif spec.type == "function":
        return _generate_function_task(step, spec, task_name)
    else:
        return _generate_fallback_task(step, task_name)


def _derive_pydra_connections(
    steps: List[StepSpec],
    step_to_task: Dict[str, str],
    interface_map: Dict[str, PydraInterfaceSpec],
) -> Tuple[List[str], List[str]]:
    """Derive Pydra workflow connections from produces/consumes relationships.

    Pydra uses lazy outputs via .lzout attribute for connections.

    Args:
        steps: List of StepSpec objects
        step_to_task: Mapping from step.id to task_name
        interface_map: Tool-to-interface mapping

    Returns:
        Tuple of (connection_code_lines, warnings)
    """
    connections: List[str] = []
    warnings: List[str] = []

    # Build index of which steps produce which resources
    resource_producers: Dict[str, Tuple[StepSpec, str]] = {}
    for step in steps:
        for res_name, res_type in (step.produces or {}).items():
            if res_name in resource_producers:
                prev_step, _ = resource_producers[res_name]
                warnings.append(
                    f"Resource '{res_name}' produced by multiple steps: "
                    f"{prev_step.id} and {step.id}; using {step.id}"
                )
            resource_producers[res_name] = (step, res_type)

    # For each consumer, find matching producers and generate connection
    for consumer_step in steps:
        consumer_task = step_to_task.get(
            consumer_step.id, _sanitize_task_name(consumer_step.id)
        )
        consumer_spec = get_pydra_interface_spec(consumer_step.tool, interface_map)
        consumer_io_map = (
            consumer_spec.io_map if consumer_spec and consumer_spec.io_map else {}
        )
        consumer_consumes_map = consumer_io_map.get("consumes", {})

        for res_name, res_type in (consumer_step.consumes or {}).items():
            # Get the Pydra field name for the consumer's input
            pydra_field = consumer_consumes_map.get(res_name, res_name)

            if res_name not in resource_producers:
                # No producer - bind to workflow input via wf.lzin
                connections.append(
                    f"    wf.{consumer_task}.inputs.{pydra_field} = wf.lzin.{res_name}"
                )
                continue

            producer_step, producer_res_type = resource_producers[res_name]

            if producer_step.id == consumer_step.id:
                continue

            if producer_res_type != res_type:
                warnings.append(
                    f"Type mismatch for resource '{res_name}': "
                    f"producer {producer_step.id} has type '{producer_res_type}', "
                    f"consumer {consumer_step.id} expects '{res_type}'"
                )

            producer_task = step_to_task.get(
                producer_step.id, _sanitize_task_name(producer_step.id)
            )
            producer_spec = get_pydra_interface_spec(producer_step.tool, interface_map)
            producer_io_map = (
                producer_spec.io_map if producer_spec and producer_spec.io_map else {}
            )
            producer_produces_map = producer_io_map.get("produces", {})

            # Map logical resource name to Pydra output field name
            from_field = producer_produces_map.get(res_name, res_name)

            # Generate Pydra lazy connection (consumer pydra_field already computed above)
            # In Pydra, connections are set via task inputs
            connections.append(
                f"    wf.{consumer_task}.inputs.{pydra_field} = wf.{producer_task}.lzout.{from_field}"
            )

    return connections, warnings


def plan_to_pydra_workflow(
    plan: Plan,
    base_dir: str,
    strict: bool = False,
    interface_map: Optional[Dict[str, PydraInterfaceSpec]] = None,
) -> PydraExportResult:
    """Convert a Plan to Pydra workflow script.

    Args:
        plan: The Plan object to convert
        base_dir: Base directory for the workflow
        strict: If True, raise error for unsupported steps; if False, skip with warning
        interface_map: Optional pre-loaded interface mapping

    Returns:
        PydraExportResult containing workflow script and metadata

    Raises:
        ValueError: If strict=True and plan contains unsupported steps
    """
    if interface_map is None:
        interface_map = load_pydra_tool_interface_map()

    imports: set[str] = {"import pydra", "from pydra import Workflow"}
    task_code_blocks: List[str] = []
    exported_steps: List[str] = []
    skipped_steps: List[str] = []
    warnings: List[str] = []
    step_to_task: Dict[str, str] = {}
    step_input_fields: Dict[str, List[str]] = {}  # step_id -> input field names

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

        # Convert step to task (now returns 4 elements)
        import_stmt, task_code, input_fields, warning = _step_to_pydra_task(
            step, interface_map
        )

        if import_stmt:
            for line in import_stmt.split("\n"):
                stripped = line.strip()
                if stripped:  # Skip empty lines
                    imports.add(stripped)

        if task_code:
            task_code_blocks.append(task_code)
            exported_steps.append(step.id)
            task_name = _sanitize_task_name(step.id)
            step_to_task[step.id] = task_name
            step_input_fields[step.id] = input_fields

        if warning:
            warnings.append(warning)

    # Derive connections
    exported_step_specs = [s for s in plan.dag.steps if s.id in exported_steps]
    connection_lines, conn_warnings = _derive_pydra_connections(
        exported_step_specs, step_to_task, interface_map
    )
    warnings.extend(conn_warnings)

    # Generate workflow script
    workflow_name = f"plan_{plan.plan_id.replace('-', '_')}"

    # Determine workflow inputs (resources consumed but not produced by any step)
    all_produced: set[str] = set()
    all_consumed: set[str] = set()
    for step in exported_step_specs:
        all_produced.update(step.produces.keys() if step.produces else [])
        all_consumed.update(step.consumes.keys() if step.consumes else [])
    workflow_inputs = all_consumed - all_produced

    # Determine terminal outputs (resources produced but not consumed by any subsequent step)
    # These are the "final" outputs of the pipeline
    terminal_outputs: set[str] = all_produced - all_consumed

    # Build resource->producer mapping for output generation
    resource_producer_map: Dict[str, str] = {}  # resource_name -> step_id
    for step in exported_step_specs:
        for res_name in (step.produces or {}).keys():
            resource_producer_map[res_name] = step.id

    workflow_outputs = []
    for res_name in sorted(terminal_outputs):
        producer_step_id = resource_producer_map.get(res_name)
        if producer_step_id:
            task_name = step_to_task.get(producer_step_id)
            producer_step = next(
                (s for s in exported_step_specs if s.id == producer_step_id), None
            )
            if producer_step:
                spec = get_pydra_interface_spec(producer_step.tool, interface_map)
                io_map = spec.io_map if spec and spec.io_map else {}
                produces_map = io_map.get("produces", {})
                pydra_field = produces_map.get(res_name, "out_file")
                workflow_outputs.append(
                    f'("{res_name}", wf.{task_name}.lzout.{pydra_field})'
                )

    # Build the workflow script
    script_lines = [
        "#!/usr/bin/env python",
        '"""',
        f"Pydra workflow: {workflow_name}",
        "Generated workflow for neuroimaging pipeline",
        '"""',
        "",
        "# Auto-generated imports",
        *sorted(imports),
        "",
        "",
        f"def create_{workflow_name}():",
        f'    """Create the {workflow_name} workflow."""',
        f'    # Workflow inputs: {sorted(workflow_inputs) if workflow_inputs else "none (self-contained)"}',
        f"    wf = Workflow(",
        f'        name="{workflow_name}",',
        (
            f"        input_spec={sorted(workflow_inputs)!r},"
            if workflow_inputs
            else "        # No external inputs needed (self-contained workflow)"
        ),
        f'        cache_dir="{base_dir}",',
        f"    )",
        "",
        "    # Add tasks",
    ]

    # Add task code blocks
    for task_block in task_code_blocks:
        script_lines.append(task_block)
        script_lines.append("")

    # Add connections
    if connection_lines:
        script_lines.append("    # Connect tasks")
        script_lines.extend(connection_lines)
        script_lines.append("")

    # Set outputs
    script_lines.append("    # Set workflow outputs")
    if workflow_outputs:
        script_lines.append(f'    wf.set_output([{", ".join(workflow_outputs)}])')
    else:
        script_lines.append("    # No explicit outputs defined")

    script_lines.append("")
    script_lines.append("    return wf")
    script_lines.append("")
    script_lines.append("")
    script_lines.append('if __name__ == "__main__":')
    script_lines.append(f"    wf = create_{workflow_name}()")
    script_lines.append('    print(f"Workflow created: {wf.name}")')
    script_lines.append("")
    script_lines.append("    # Run the workflow")
    script_lines.append("    # To run with specific inputs:")
    script_lines.append('    # result = wf(in_file="/path/to/input.nii.gz")')
    script_lines.append("    # print(result.output)")
    script_lines.append("")

    workflow_script = "\n".join(script_lines)

    return PydraExportResult(
        workflow_script=workflow_script,
        plan_id=plan.plan_id,
        exported_steps=exported_steps,
        skipped_steps=skipped_steps,
        warnings=warnings,
        imports=list(imports),
        tasks=[{"name": step_to_task.get(s), "step_id": s} for s in exported_steps],
    )


def export_plan_to_pydra(
    plan: Plan,
    output_dir: str,
    strict: bool = False,
) -> Dict[str, Any]:
    """Export a Plan to Pydra workflow files.

    This is the high-level function that:
    1. Converts Plan to Pydra workflow script
    2. Saves workflow.py and spec.yaml
    3. Saves original plan for provenance
    4. Returns paths and metadata

    Args:
        plan: The Plan object to export
        output_dir: Directory to write workflow files (plan_id subfolder will be created)
        strict: If True, fail on unsupported steps

    Returns:
        Dictionary with workflow_file, spec_file, etc.
    """
    # Create output directory with plan_id
    workflow_dir = Path(output_dir) / plan.plan_id
    workflow_dir.mkdir(parents=True, exist_ok=True)

    # Convert plan to Pydra workflow
    export_result = plan_to_pydra_workflow(
        plan=plan,
        base_dir=str(workflow_dir),
        strict=strict,
    )

    # Save workflow script
    workflow_file = workflow_dir / "workflow.py"
    workflow_file.write_text(export_result.workflow_script)

    # Save original plan for provenance
    plan_file = workflow_dir / "plan.json"
    plan_file.write_text(plan.model_dump_json(indent=2))

    # Save workflow spec as YAML
    spec_file = workflow_dir / "spec.yaml"
    spec_data = {
        "workflow_name": f"plan_{plan.plan_id.replace('-', '_')}",
        "exported_steps": export_result.exported_steps,
        "imports": export_result.imports,
        "tasks": export_result.tasks,
    }
    spec_file.write_text(yaml.dump(spec_data, default_flow_style=False))

    return {
        "status": "success",
        "plan_id": plan.plan_id,
        "format": "pydra",
        "workflow_file": str(workflow_file),
        "spec_file": str(spec_file),
        "original_plan_file": str(plan_file),
        "run_command": f"python {workflow_file}",
        "exported_steps": export_result.exported_steps,
        "skipped_steps": export_result.skipped_steps,
        "warnings": export_result.warnings,
    }


__all__ = [
    "PydraExportResult",
    "PydraInterfaceSpec",
    "plan_to_pydra_workflow",
    "export_plan_to_pydra",
    "load_pydra_tool_interface_map",
    "get_pydra_interface_spec",
    "SUPPORTED_RUNTIME_KINDS",
    "UNSUPPORTED_RUNTIME_KINDS",
]
