"""
Nipype workflow engine tool implementation.

Provides a flexible framework for creating and executing neuroimaging pipelines.
Supports workflow composition, parallel execution, and provenance tracking.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class WorkflowPlugin(str, Enum):
    """Available workflow execution plugins."""

    LINEAR = "Linear"
    MULTIPROC = "MultiProc"
    SLURM = "SLURM"
    SGE = "SGE"
    PBS = "PBS"
    CONDOR = "HTCondor"
    LSF = "LSF"


class DataGrabberType(str, Enum):
    """Types of data grabbing patterns."""

    BIDS = "bids"
    FREESURFER = "freesurfer"
    CUSTOM = "custom"
    XNAT = "xnat"
    FLYWHEEL = "flywheel"


class InterfaceType(str, Enum):
    """Common Nipype interface categories."""

    FSL = "fsl"
    SPM = "spm"
    FREESURFER = "freesurfer"
    ANTS = "ants"
    AFNI = "afni"
    MRTRIX = "mrtrix"
    DIPY = "dipy"
    NILEARN = "nilearn"


@dataclass
class NipypeConfig:
    """Configuration for Nipype workflows."""

    working_dir: str
    crash_dir: Optional[str] = None
    plugin: str = "Linear"
    plugin_args: Dict[str, Any] = field(default_factory=dict)
    use_relative_paths: bool = True
    hash_method: str = "timestamp"
    keep_inputs: bool = True
    remove_unnecessary_outputs: bool = True
    stop_on_first_crash: bool = False

    def get_config_dict(self) -> Dict[str, Any]:
        """Get configuration as dictionary."""
        config = {
            "execution": {
                "plugin": self.plugin,
                "plugin_args": self.plugin_args,
                "stop_on_first_crash": self.stop_on_first_crash,
                "hash_method": self.hash_method,
                "keep_inputs": self.keep_inputs,
                "remove_unnecessary_outputs": self.remove_unnecessary_outputs,
                "use_relative_paths": self.use_relative_paths,
            },
            "logging": {
                "workflow_level": "INFO",
                "interface_level": "INFO",
                "log_directory": self.working_dir,
            }
        }

        if self.crash_dir:
            config["execution"]["crashdump_dir"] = self.crash_dir

        return config


# =============================================================================
# Nipype Workflow Builder Tool
# =============================================================================


class NipypeWorkflowBuilderArgs(BaseModel):
    """Arguments for Nipype workflow builder."""

    name: str = Field(description="Workflow name")
    base_dir: str = Field(description="Base directory for workflow")
    nodes: List[Dict[str, Any]] = Field(
        description="List of workflow nodes with configurations"
    )
    connections: List[Tuple[str, str, str, str]] = Field(
        default=[],
        description="Node connections [(from_node, from_field, to_node, to_field)]"
    )
    iterables: Optional[Dict[str, List[Any]]] = Field(
        default=None,
        description="Iterables for parametric execution"
    )
    plugin: str = Field(
        default="Linear",
        description="Execution plugin (Linear, MultiProc, SLURM, etc.)"
    )
    plugin_args: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Plugin-specific arguments"
    )


class NipypeWorkflowBuilderTool(NeuroToolWrapper):
    """Nipype workflow builder tool."""

    def get_tool_name(self) -> str:
        return "nipype_workflow_builder"

    def get_tool_description(self) -> str:
        return (
            "Build and configure Nipype workflows for neuroimaging pipelines. "
            "Supports node creation, connections, iterables, and various execution plugins."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return NipypeWorkflowBuilderArgs

    def _run(
        self,
        name: str,
        base_dir: str,
        nodes: List[Dict[str, Any]],
        connections: List[Tuple[str, str, str, str]] = None,
        iterables: Optional[Dict[str, List[Any]]] = None,
        plugin: str = "Linear",
        plugin_args: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Build Nipype workflow."""

        if connections is None:
            connections = []

        # Create base directory
        Path(base_dir).mkdir(parents=True, exist_ok=True)

        # Generate workflow Python script
        script_lines = [
            "#!/usr/bin/env python",
            '"""',
            f"Nipype workflow: {name}",
            f"Generated workflow for neuroimaging pipeline",
            '"""',
            "",
            "import os",
            "from pathlib import Path",
            "import nipype.pipeline.engine as pe",
            "import nipype.interfaces.utility as util",
            "from nipype import config, logging",
            "",
        ]

        # Add interface imports based on nodes
        interfaces_needed = set()
        for node in nodes:
            if "interface" in node:
                interface_type = node["interface"].get("type", "utility")
                interfaces_needed.add(interface_type)

        for interface in interfaces_needed:
            if interface == "fsl":
                script_lines.append("import nipype.interfaces.fsl as fsl")
            elif interface == "spm":
                script_lines.append("import nipype.interfaces.spm as spm")
            elif interface == "freesurfer":
                script_lines.append("import nipype.interfaces.freesurfer as fs")
            elif interface == "ants":
                script_lines.append("import nipype.interfaces.ants as ants")
            elif interface == "afni":
                script_lines.append("import nipype.interfaces.afni as afni")
            elif interface == "mrtrix":
                script_lines.append("import nipype.interfaces.mrtrix3 as mrt")
            elif interface == "io":
                script_lines.append("import nipype.interfaces.io as nio")
            elif interface == "nilearn":
                script_lines.append("import nipype.interfaces.nilearn as nil")

        script_lines.extend([
            "",
            "# Configure Nipype",
            "config.update_config({'execution': {'plugin': '" + plugin + "'}})",
            "logging.update_logging(config)",
            "",
            f"def create_{name}_workflow():",
            '    """Create the workflow."""',
            f'    workflow = pe.Workflow(name="{name}")',
            f'    workflow.base_dir = "{base_dir}"',
            "",
            "    # Create nodes",
        ])

        # Create nodes
        node_names = []
        for node_config in nodes:
            node_name = node_config["name"]
            node_names.append(node_name)

            if "interface" in node_config:
                interface_info = node_config["interface"]
                interface_type = interface_info.get("type", "utility")
                interface_name = interface_info.get("name", "IdentityInterface")
                interface_params = interface_info.get("params", {})

                # Generate interface creation code
                if interface_type == "utility":
                    interface_code = f"util.{interface_name}("
                    # Special-case Function: allow inline function_str/input_names/output_names in params
                    if interface_name == "Function" and "params" in interface_info:
                        # Function accepts function_str or function plus input_names/output_names
                        pass
                elif interface_type == "fsl":
                    interface_code = f"fsl.{interface_name}("
                elif interface_type == "spm":
                    interface_code = f"spm.{interface_name}("
                elif interface_type == "freesurfer":
                    interface_code = f"fs.{interface_name}("
                elif interface_type == "io":
                    interface_code = f"nio.{interface_name}("
                elif interface_type == "nilearn":
                    interface_code = f"nil.{interface_name}("
                else:
                    interface_code = f"util.IdentityInterface("

                # Add parameters
                param_strs = []
                for key, value in interface_params.items():
                    if isinstance(value, str):
                        param_strs.append(f'{key}="{value}"')
                    else:
                        param_strs.append(f"{key}={value}")

                interface_code += ", ".join(param_strs) + ")"

                script_lines.append(
                    f'    {node_name} = pe.Node({interface_code}, name="{node_name}")'
                )
            else:
                # Default to IdentityInterface
                fields = node_config.get("fields", ["in_file"])
                script_lines.append(
                    f'    {node_name} = pe.Node(util.IdentityInterface(fields={fields}), name="{node_name}")'
                )

            # Add iterables if specified
            if "iterables" in node_config:
                iter_field = node_config["iterables"]["field"]
                iter_values = node_config["iterables"]["values"]
                script_lines.append(
                    f'    {node_name}.iterables = ("{iter_field}", {iter_values})'
                )

        script_lines.append("")

        # Add connections
        if connections:
            script_lines.append("    # Connect nodes")
            for from_node, from_field, to_node, to_field in connections:
                script_lines.append(
                    f'    workflow.connect({from_node}, "{from_field}", {to_node}, "{to_field}")'
                )
            script_lines.append("")

        # Add workflow to the function
        script_lines.append("    return workflow")
        script_lines.append("")

        # Add main execution block
        script_lines.extend([
            "",
            'if __name__ == "__main__":',
            f'    wf = create_{name}_workflow()',
            '    print(f"Workflow created: {wf.name}")',
            '    print(f"Base directory: {wf.base_dir}")',
            "",
            "    # Write workflow graph",
            '    wf.write_graph(graph2use="colored", format="png", simple_form=True)',
            "",
            "    # Run workflow",
        ])

        if plugin_args:
            script_lines.append(f'    plugin_args = {plugin_args}')
            script_lines.append(f'    wf.run(plugin="{plugin}", plugin_args=plugin_args)')
        else:
            script_lines.append(f'    wf.run(plugin="{plugin}")')

        script_lines.append('    print("Workflow execution complete!")')

        # Save workflow script
        workflow_file = Path(base_dir) / f"{name}_workflow.py"
        workflow_file.write_text("\n".join(script_lines))
        workflow_file.chmod(0o755)

        # Generate config file
        config = NipypeConfig(
            working_dir=base_dir,
            plugin=plugin,
            plugin_args=plugin_args or {}
        )

        config_file = Path(base_dir) / "nipype.cfg"
        config_dict = config.get_config_dict()

        # Write config in INI format
        config_lines = []
        for section, params in config_dict.items():
            config_lines.append(f"[{section}]")
            for key, value in params.items():
                if isinstance(value, dict):
                    value = json.dumps(value)
                config_lines.append(f"{key} = {value}")
            config_lines.append("")

        config_file.write_text("\n".join(config_lines))

        return ToolResult(
            status="success",
            data={
                "workflow_name": name,
                "workflow_file": str(workflow_file),
                "config_file": str(config_file),
                "base_dir": base_dir,
                "n_nodes": len(nodes),
                "n_connections": len(connections),
                "plugin": plugin,
                "node_names": node_names,
                "command": f"python {workflow_file}"
            }
        )


# =============================================================================
# Nipype BIDS App Tool
# =============================================================================


class NipypeBIDSAppArgs(BaseModel):
    """Arguments for Nipype BIDS app."""

    bids_dir: str = Field(description="BIDS dataset directory")
    output_dir: str = Field(description="Output directory")
    analysis_level: str = Field(
        default="participant",
        description="Analysis level (participant or group)"
    )
    participant_label: Optional[List[str]] = Field(
        default=None,
        description="Participant labels to process"
    )
    task: Optional[str] = Field(
        default=None,
        description="Task to process"
    )
    pipeline: str = Field(
        default="preprocessing",
        description="Pipeline to run (preprocessing, first_level, etc.)"
    )
    fwhm: float = Field(
        default=6.0,
        description="Smoothing kernel FWHM in mm"
    )
    tr: Optional[float] = Field(
        default=None,
        description="Repetition time (if not in BIDS)"
    )


class NipypeBIDSAppTool(NeuroToolWrapper):
    """Nipype BIDS app tool."""

    def get_tool_name(self) -> str:
        return "nipype_bids_app"

    def get_tool_description(self) -> str:
        return (
            "Create BIDS-compatible Nipype pipelines. Automatically detects BIDS structure "
            "and creates appropriate workflows for preprocessing or analysis."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return NipypeBIDSAppArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        analysis_level: str = "participant",
        participant_label: Optional[List[str]] = None,
        task: Optional[str] = None,
        pipeline: str = "preprocessing",
        fwhm: float = 6.0,
        tr: Optional[float] = None,
    ) -> ToolResult:
        """Create BIDS app workflow."""

        # Validate BIDS directory
        if not os.path.exists(bids_dir):
            return ToolResult(
                status="error",
                error=f"BIDS directory not found: {bids_dir}"
            )

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate BIDS app script
        script_lines = [
            "#!/usr/bin/env python",
            '"""',
            "Nipype BIDS App",
            f"Pipeline: {pipeline}",
            f"Analysis level: {analysis_level}",
            '"""',
            "",
            "import os",
            "import json",
            "from pathlib import Path",
            "from bids import BIDSLayout",
            "import nipype.pipeline.engine as pe",
            "import nipype.interfaces.utility as util",
            "import nipype.interfaces.io as nio",
            "import nipype.interfaces.fsl as fsl",
            "from nipype import config, logging",
            "",
            "# Configure Nipype",
            "config.update_config({",
            "    'execution': {",
            "        'crashdump_dir': os.path.join(os.getcwd(), 'crash'),",
            "        'hash_method': 'timestamp',",
            "        'stop_on_first_crash': False",
            "    }",
            "})",
            "logging.update_logging(config)",
            "",
            f'def create_bids_{pipeline}_workflow(bids_dir, output_dir, subjects=None):',
            '    """Create BIDS workflow."""',
            "    ",
            "    # Initialize BIDS layout",
            '    layout = BIDSLayout(bids_dir, validate=False)',
            "    ",
            "    # Get subjects",
            "    if subjects is None:",
            "        subjects = layout.get_subjects()",
            "    ",
            f'    # Create main workflow',
            f'    workflow = pe.Workflow(name="bids_{pipeline}")',
            f'    workflow.base_dir = output_dir',
            "    ",
        ]

        if pipeline == "preprocessing":
            script_lines.extend([
                "    # Create preprocessing nodes",
                "    for subject in subjects:",
                f"        # Get functional files",
                "        func_files = layout.get(",
                "            subject=subject,",
                "            extension='nii.gz',",
                "            suffix='bold',",
                f"            task={repr(task) if task else None},",
                "            return_type='file'",
                "        )",
                "        ",
                "        if not func_files:",
                "            continue",
                "        ",
                "        # Get anatomical file",
                "        anat_files = layout.get(",
                "            subject=subject,",
                "            extension='nii.gz',",
                "            suffix='T1w',",
                "            return_type='file'",
                "        )",
                "        ",
                "        if not anat_files:",
                "            continue",
                "        ",
                f"        # Create subject workflow",
                f'        subj_wf = pe.Workflow(name=f"sub_{{subject}}")',
                "        ",
                "        # Motion correction",
                '        mcflirt = pe.Node(fsl.MCFLIRT(), name="motion_correction")',
                "        mcflirt.inputs.in_file = func_files[0]",
                "        ",
                "        # Slice timing correction",
                '        slicetimer = pe.Node(fsl.SliceTimer(), name="slice_timing")',
                f"        slicetimer.inputs.time_repetition = {tr or 2.0}",
                "        ",
                "        # Brain extraction",
                '        bet = pe.Node(fsl.BET(), name="brain_extraction")',
                "        bet.inputs.frac = 0.5",
                "        bet.inputs.functional = True",
                "        ",
                "        # Smoothing",
                '        smooth = pe.Node(fsl.Smooth(), name="smoothing")',
                f"        smooth.inputs.fwhm = {fwhm}",
                "        ",
                "        # Connect nodes",
                '        subj_wf.connect(mcflirt, "out_file", slicetimer, "in_file")',
                '        subj_wf.connect(slicetimer, "slice_time_corrected_file", bet, "in_file")',
                '        subj_wf.connect(bet, "out_file", smooth, "in_file")',
                "        ",
                "        # Add to main workflow",
                "        workflow.add_nodes([subj_wf])",
                "    ",
            ])

        elif pipeline == "first_level":
            script_lines.extend([
                "    # Create first-level analysis nodes",
                "    for subject in subjects:",
                "        # Get preprocessed functional files",
                "        func_files = layout.get(",
                "            subject=subject,",
                "            extension='nii.gz',",
                "            suffix='bold',",
                f"            task={repr(task) if task else None},",
                "            return_type='file'",
                "        )",
                "        ",
                "        if not func_files:",
                "            continue",
                "        ",
                "        # Get events files",
                "        event_files = layout.get(",
                "            subject=subject,",
                "            extension='tsv',",
                "            suffix='events',",
                f"            task={repr(task) if task else None},",
                "            return_type='file'",
                "        )",
                "        ",
                f'        # Create subject workflow',
                f'        subj_wf = pe.Workflow(name=f"sub_{{subject}}_glm")',
                "        ",
                "        # Specify model",
                '        modelspec = pe.Node(fsl.SpecifyModel(), name="modelspec")',
                f"        modelspec.inputs.time_repetition = {tr or 2.0}",
                "        modelspec.inputs.input_units = 'secs'",
                "        modelspec.inputs.high_pass_filter_cutoff = 128",
                "        ",
                "        # Generate design",
                '        level1design = pe.Node(fsl.Level1Design(), name="level1design")',
                "        level1design.inputs.interscan_interval = modelspec.inputs.time_repetition",
                "        level1design.inputs.bases = {'dgamma': {'derivs': False}}",
                "        ",
                "        # Estimate model",
                '        modelgen = pe.Node(fsl.FEATModel(), name="modelgen")',
                '        estimate = pe.Node(fsl.FILMGLS(), name="estimate")',
                "        ",
                "        # Connect nodes",
                '        subj_wf.connect(modelspec, "session_info", level1design, "session_info")',
                '        subj_wf.connect(level1design, "fsf_files", modelgen, "fsf_file")',
                '        subj_wf.connect(level1design, "ev_files", modelgen, "ev_files")',
                '        subj_wf.connect(modelgen, "design_file", estimate, "design_file")',
                "        ",
                "        # Add to main workflow",
                "        workflow.add_nodes([subj_wf])",
                "    ",
            ])

        script_lines.extend([
            "    return workflow",
            "",
            "",
            'if __name__ == "__main__":',
            f'    bids_dir = "{bids_dir}"',
            f'    output_dir = "{output_dir}"',
            "    ",
            "    # Participant labels",
            f'    participants = {participant_label or "None"}',
            "    ",
            "    # Create and run workflow",
            f'    wf = create_bids_{pipeline}_workflow(bids_dir, output_dir, participants)',
            '    print(f"Created workflow: {wf.name}")',
            "    ",
            "    # Write graph",
            '    wf.write_graph(graph2use="colored", format="png")',
            "    ",
            "    # Run workflow",
            f'    wf.run(plugin="MultiProc", plugin_args={{"n_procs": 4}})',
            '    print("BIDS app execution complete!")',
        ])

        # Save BIDS app script
        app_file = Path(output_dir) / f"bids_{pipeline}_app.py"
        app_file.write_text("\n".join(script_lines))
        app_file.chmod(0o755)

        # Create dataset description
        dataset_desc = {
            "Name": f"Nipype BIDS {pipeline.title()} Pipeline",
            "BIDSVersion": "1.6.0",
            "PipelineDescription": {
                "Name": f"nipype_{pipeline}",
                "Version": "1.0.0",
                "CodeURL": str(app_file)
            },
            "SourceDatasets": [
                {
                    "URL": bids_dir,
                    "Version": "1.0.0"
                }
            ]
        }

        desc_file = Path(output_dir) / "dataset_description.json"
        desc_file.write_text(json.dumps(dataset_desc, indent=2))

        return ToolResult(
            status="success",
            data={
                "app_file": str(app_file),
                "output_dir": output_dir,
                "bids_dir": bids_dir,
                "pipeline": pipeline,
                "analysis_level": analysis_level,
                "participants": participant_label or "all",
                "command": f"python {app_file}",
                "dataset_description": str(desc_file)
            }
        )


# =============================================================================
# Nipype Interface Wrapper Tool
# =============================================================================


class NipypeInterfaceWrapperArgs(BaseModel):
    """Arguments for Nipype interface wrapper."""

    interface_type: str = Field(
        description="Interface type (fsl, spm, freesurfer, ants, etc.)"
    )
    interface_name: str = Field(
        description="Interface name (e.g., BET, FLIRT, Smooth)"
    )
    inputs: Dict[str, Any] = Field(
        description="Input parameters for the interface"
    )
    output_dir: str = Field(
        description="Output directory for results"
    )
    run_interface: bool = Field(
        default=False,
        description="Whether to run the interface immediately"
    )


class NipypeInterfaceWrapperTool(NeuroToolWrapper):
    """Nipype interface wrapper tool."""

    def get_tool_name(self) -> str:
        return "nipype_interface_wrapper"

    def get_tool_description(self) -> str:
        return (
            "Wrap and execute individual Nipype interfaces. Provides access to "
            "FSL, SPM, FreeSurfer, ANTS, and other neuroimaging tools through "
            "a unified interface."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return NipypeInterfaceWrapperArgs

    def _run(
        self,
        interface_type: str,
        interface_name: str,
        inputs: Dict[str, Any],
        output_dir: str,
        run_interface: bool = False,
    ) -> ToolResult:
        """Wrap and optionally execute Nipype interface."""

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate interface script
        script_lines = [
            "#!/usr/bin/env python",
            '"""',
            f"Nipype Interface: {interface_type}.{interface_name}",
            '"""',
            "",
            "import os",
            "from pathlib import Path",
        ]

        # Import appropriate interface module
        if interface_type == "fsl":
            script_lines.append("import nipype.interfaces.fsl as fsl")
            interface_module = "fsl"
        elif interface_type == "spm":
            script_lines.append("import nipype.interfaces.spm as spm")
            interface_module = "spm"
        elif interface_type == "freesurfer":
            script_lines.append("import nipype.interfaces.freesurfer as fs")
            interface_module = "fs"
        elif interface_type == "ants":
            script_lines.append("import nipype.interfaces.ants as ants")
            interface_module = "ants"
        elif interface_type == "afni":
            script_lines.append("import nipype.interfaces.afni as afni")
            interface_module = "afni"
        elif interface_type == "mrtrix":
            script_lines.append("import nipype.interfaces.mrtrix3 as mrt")
            interface_module = "mrt"
        else:
            script_lines.append("import nipype.interfaces.utility as util")
            interface_module = "util"

        script_lines.extend([
            "",
            f"# Create interface",
            f"interface = {interface_module}.{interface_name}()",
            "",
            "# Set inputs",
        ])

        # Set input parameters
        for key, value in inputs.items():
            if isinstance(value, str):
                script_lines.append(f'interface.inputs.{key} = "{value}"')
            elif isinstance(value, (list, tuple)):
                script_lines.append(f"interface.inputs.{key} = {value}")
            else:
                script_lines.append(f"interface.inputs.{key} = {value}")

        script_lines.extend([
            "",
            "# Print interface details",
            'print("Interface:", interface)',
            'print("\\nInputs:")',
            "print(interface.inputs)",
            "",
        ])

        if run_interface:
            script_lines.extend([
                "# Run interface",
                "try:",
                "    result = interface.run()",
                '    print("\\nInterface executed successfully!")',
                '    print("\\nOutputs:")',
                "    print(result.outputs)",
                "except Exception as e:",
                '    print(f"\\nError running interface: {e}")',
                "    import traceback",
                "    traceback.print_exc()",
            ])
        else:
            script_lines.extend([
                "# To run the interface, uncomment the following:",
                "# result = interface.run()",
                "# print(result.outputs)",
            ])

        # Add command line generation
        script_lines.extend([
            "",
            "# Generate command line",
            "try:",
            "    cmdline = interface.cmdline",
            '    print("\\nCommand line:")',
            "    print(cmdline)",
            "except Exception:",
            '    print("\\nCommand line generation not available for this interface")',
        ])

        # Save interface script
        script_file = Path(output_dir) / f"{interface_type}_{interface_name}.py"
        script_file.write_text("\n".join(script_lines))
        script_file.chmod(0o755)

        # Generate JSON config for the interface
        config = {
            "interface_type": interface_type,
            "interface_name": interface_name,
            "inputs": inputs,
            "output_dir": output_dir
        }

        config_file = Path(output_dir) / f"{interface_type}_{interface_name}_config.json"
        config_file.write_text(json.dumps(config, indent=2))

        # Try to get command line preview (if possible)
        cmdline_preview = None
        if interface_type == "fsl" and interface_name in ["BET", "FLIRT", "FNIRT", "FAST"]:
            if interface_name == "BET" and "in_file" in inputs:
                cmdline_preview = f"bet {inputs['in_file']} output"
            elif interface_name == "FLIRT" and "in_file" in inputs and "reference" in inputs:
                cmdline_preview = f"flirt -in {inputs['in_file']} -ref {inputs['reference']} -out output"

        return ToolResult(
            status="success",
            data={
                "script_file": str(script_file),
                "config_file": str(config_file),
                "interface": f"{interface_type}.{interface_name}",
                "inputs": inputs,
                "output_dir": output_dir,
                "command": f"python {script_file}",
                "cmdline_preview": cmdline_preview,
                "run_interface": run_interface
            }
        )


# =============================================================================
# Nipype Distributed Execution Tool
# =============================================================================


class NipypeDistributedArgs(BaseModel):
    """Arguments for Nipype distributed execution."""

    workflow_file: str = Field(description="Workflow Python file to execute")
    plugin: str = Field(
        default="MultiProc",
        description="Execution plugin (MultiProc, SLURM, SGE, etc.)"
    )
    n_procs: int = Field(
        default=4,
        description="Number of processes for MultiProc plugin"
    )
    memory_gb: int = Field(
        default=4,
        description="Memory per process in GB"
    )
    queue: Optional[str] = Field(
        default=None,
        description="Queue name for cluster execution"
    )
    walltime: Optional[str] = Field(
        default=None,
        description="Wall time for cluster jobs (HH:MM:SS)"
    )
    working_dir: str = Field(
        description="Working directory for execution"
    )


class NipypeDistributedTool(NeuroToolWrapper):
    """Nipype distributed execution tool."""

    def get_tool_name(self) -> str:
        return "nipype_distributed"

    def get_tool_description(self) -> str:
        return (
            "Configure and execute Nipype workflows with distributed computing. "
            "Supports local multiprocessing and various cluster environments "
            "(SLURM, SGE, PBS, HTCondor, LSF)."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return NipypeDistributedArgs

    def _run(
        self,
        workflow_file: str,
        plugin: str = "MultiProc",
        n_procs: int = 4,
        memory_gb: int = 4,
        queue: Optional[str] = None,
        walltime: Optional[str] = None,
        working_dir: str = None,
    ) -> ToolResult:
        """Configure distributed execution."""

        if not os.path.exists(workflow_file):
            return ToolResult(
                status="error",
                error=f"Workflow file not found: {workflow_file}"
            )

        if working_dir is None:
            working_dir = os.path.dirname(workflow_file)

        Path(working_dir).mkdir(parents=True, exist_ok=True)

        # Generate execution script
        script_lines = [
            "#!/usr/bin/env python",
            '"""',
            "Nipype Distributed Execution Script",
            f"Plugin: {plugin}",
            '"""',
            "",
            "import os",
            "import sys",
            "from pathlib import Path",
            "from nipype import config, logging",
            "",
            "# Add workflow directory to path",
            f'sys.path.insert(0, "{os.path.dirname(workflow_file)}")',
            "",
            "# Import workflow",
            f'workflow_module = __import__("{Path(workflow_file).stem}")',
            "",
            "# Configure Nipype",
            "config_dict = {",
            "    'execution': {",
            f"        'plugin': '{plugin}',",
            f"        'crashdump_dir': '{working_dir}/crash',",
            "        'hash_method': 'timestamp',",
            "        'stop_on_first_crash': False,",
            "        'keep_inputs': True,",
            "        'remove_unnecessary_outputs': False,",
            "        'poll_sleep_duration': 2",
            "    },",
            "    'logging': {",
            "        'workflow_level': 'INFO',",
            "        'interface_level': 'INFO',",
            f"        'log_directory': '{working_dir}/logs'",
            "    }",
            "}",
            "config.update_config(config_dict)",
            "logging.update_logging(config)",
            "",
        ]

        # Configure plugin arguments
        plugin_args = {}

        if plugin == "MultiProc":
            plugin_args = {
                "n_procs": n_procs,
                "memory_gb": memory_gb,
                "maxtasksperchild": 1
            }

        elif plugin == "SLURM":
            plugin_args = {
                "template": "#!/bin/bash\n#SBATCH --nodes=1\n#SBATCH --ntasks=1",
                "sbatch_args": f"--mem={memory_gb}G"
            }
            if queue:
                plugin_args["sbatch_args"] += f" --partition={queue}"
            if walltime:
                plugin_args["sbatch_args"] += f" --time={walltime}"

        elif plugin == "SGE":
            plugin_args = {
                "template": f"#!/bin/bash\n#$ -l h_vmem={memory_gb}G",
                "qsub_args": "-V -cwd"
            }
            if queue:
                plugin_args["qsub_args"] += f" -q {queue}"

        elif plugin == "PBS":
            plugin_args = {
                "template": f"#!/bin/bash\n#PBS -l mem={memory_gb}gb",
                "qsub_args": ""
            }
            if queue:
                plugin_args["qsub_args"] += f" -q {queue}"
            if walltime:
                plugin_args["qsub_args"] += f" -l walltime={walltime}"

        script_lines.extend([
            "# Plugin configuration",
            f"plugin_args = {plugin_args}",
            "",
            "# Get workflow",
            "# Try different common workflow creation function names",
            "workflow = None",
            "for func_name in ['create_workflow', 'get_workflow', 'main', 'build_workflow']:",
            "    if hasattr(workflow_module, func_name):",
            "        workflow_func = getattr(workflow_module, func_name)",
            "        try:",
            "            workflow = workflow_func()",
            "            break",
            "        except TypeError:",
            "            # Function might require arguments",
            "            pass",
            "",
            "if workflow is None:",
            '    print("Could not find or create workflow from file")',
            "    sys.exit(1)",
            "",
            'print(f"Running workflow: {workflow.name}")',
            f'print(f"Plugin: {plugin}")',
            'print(f"Plugin args: {plugin_args}")',
            "",
            "# Create directories",
            "Path(config_dict['execution']['crashdump_dir']).mkdir(parents=True, exist_ok=True)",
            "Path(config_dict['logging']['log_directory']).mkdir(parents=True, exist_ok=True)",
            "",
            "# Run workflow",
            "try:",
            f'    result = workflow.run(plugin="{plugin}", plugin_args=plugin_args)',
            '    print("\\nWorkflow completed successfully!")',
            "except Exception as e:",
            '    print(f"\\nWorkflow failed: {e}")',
            "    import traceback",
            "    traceback.print_exc()",
            "    sys.exit(1)",
        ])

        # Save execution script
        exec_file = Path(working_dir) / f"run_{plugin.lower()}.py"
        exec_file.write_text("\n".join(script_lines))
        exec_file.chmod(0o755)

        # Generate submission script for cluster execution
        submit_script = None
        if plugin in ["SLURM", "SGE", "PBS"]:
            submit_lines = []

            if plugin == "SLURM":
                submit_lines = [
                    "#!/bin/bash",
                    f"#SBATCH --job-name=nipype_workflow",
                    f"#SBATCH --output={working_dir}/slurm-%j.out",
                    f"#SBATCH --error={working_dir}/slurm-%j.err",
                    f"#SBATCH --mem={memory_gb}G",
                    f"#SBATCH --cpus-per-task={n_procs}",
                ]
                if queue:
                    submit_lines.append(f"#SBATCH --partition={queue}")
                if walltime:
                    submit_lines.append(f"#SBATCH --time={walltime}")
                submit_lines.extend([
                    "",
                    f"python {exec_file}"
                ])
                submit_cmd = "sbatch"

            elif plugin == "SGE":
                submit_lines = [
                    "#!/bin/bash",
                    f"#$ -N nipype_workflow",
                    f"#$ -o {working_dir}",
                    f"#$ -e {working_dir}",
                    f"#$ -l h_vmem={memory_gb}G",
                    f"#$ -pe smp {n_procs}",
                    "#$ -V",
                    "#$ -cwd",
                ]
                if queue:
                    submit_lines.append(f"#$ -q {queue}")
                submit_lines.extend([
                    "",
                    f"python {exec_file}"
                ])
                submit_cmd = "qsub"

            elif plugin == "PBS":
                submit_lines = [
                    "#!/bin/bash",
                    f"#PBS -N nipype_workflow",
                    f"#PBS -o {working_dir}",
                    f"#PBS -e {working_dir}",
                    f"#PBS -l mem={memory_gb}gb",
                    f"#PBS -l ncpus={n_procs}",
                ]
                if queue:
                    submit_lines.append(f"#PBS -q {queue}")
                if walltime:
                    submit_lines.append(f"#PBS -l walltime={walltime}")
                submit_lines.extend([
                    "",
                    f"cd {working_dir}",
                    f"python {exec_file}"
                ])
                submit_cmd = "qsub"

            submit_script = Path(working_dir) / f"submit_{plugin.lower()}.sh"
            submit_script.write_text("\n".join(submit_lines))
            submit_script.chmod(0o755)

        return ToolResult(
            status="success",
            data={
                "execution_script": str(exec_file),
                "submit_script": str(submit_script) if submit_script else None,
                "working_dir": working_dir,
                "plugin": plugin,
                "plugin_args": plugin_args,
                "command": f"python {exec_file}",
                "submit_command": f"{submit_cmd} {submit_script}" if submit_script else None,
                "n_procs": n_procs,
                "memory_gb": memory_gb
            }
        )


# =============================================================================
# Nipype Tools Collection
# =============================================================================


class NipypeTools:
    """Collection of Nipype tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all Nipype tools."""
        return [
            NipypeWorkflowBuilderTool(),
            NipypeBIDSAppTool(),
            NipypeInterfaceWrapperTool(),
            NipypeDistributedTool(),
        ]
