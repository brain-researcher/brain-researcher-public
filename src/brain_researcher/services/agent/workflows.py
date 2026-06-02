"""
Pre-configured LangGraph workflows for common neuroimaging analysis tasks.
These leverage the existing state machine and tool registry.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from brain_researcher.services.agent.graph import AgentState, CoreStateMachine
from brain_researcher.services.agent.monitoring import metrics_collector
from brain_researcher.services.tools.spec import spec_from_tool
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class WorkflowType(Enum):
    """Pre-defined workflow types."""

    FMRI_STANDARD = "fmri_standard"
    CLINICAL_ASSESSMENT = "clinical_assessment"
    CONNECTIVITY_ANALYSIS = "connectivity_analysis"
    ML_CLASSIFICATION = "ml_classification"
    DIFFUSION_ANALYSIS = "diffusion_analysis"
    MULTIMODAL = "multimodal"
    QUALITY_CONTROL = "quality_control"
    META_ANALYSIS = "meta_analysis"


@dataclass
class WorkflowDefinition:
    """Definition of a neuroimaging workflow."""

    name: str
    description: str
    required_tools: List[str]
    optional_tools: List[str]
    required_inputs: List[str]
    expected_outputs: List[str]
    estimated_duration: str


class NeuroimagingWorkflows:
    """
    Pre-configured workflows that use the LangGraph state machine.
    These are templates that guide the agent through common analysis pipelines.
    """

    def __init__(self):
        self.state_machine = CoreStateMachine()
        self.registry = ToolRegistry.from_env(auto_discover=True)
        self.workflows = self._define_workflows()

    def _define_workflows(self) -> Dict[WorkflowType, WorkflowDefinition]:
        """Define standard neuroimaging workflows."""
        return {
            WorkflowType.FMRI_STANDARD: WorkflowDefinition(
                name="Standard fMRI Analysis",
                description="Complete fMRI preprocessing and analysis pipeline",
                required_tools=[
                    "skull_stripping",
                    "motion_quantification",
                    "glm_analysis",
                    "contrast_analysis",
                    "multiple_comparison_correction",
                ],
                optional_tools=[
                    "bias_field_correction",
                    "coregistration",
                    "functional_connectivity",
                ],
                required_inputs=["fmri_file", "t1_file", "design_matrix"],
                expected_outputs=[
                    "statistical_maps",
                    "motion_parameters",
                    "glm_results",
                ],
                estimated_duration="15-30 minutes",
            ),
            WorkflowType.CLINICAL_ASSESSMENT: WorkflowDefinition(
                name="Clinical Neuroimaging Assessment",
                description="Comprehensive clinical evaluation with automated reporting",
                required_tools=[
                    "brain_segmentation",
                    "quality_control",
                    "clinical_decision_support",
                ],
                optional_tools=[
                    "lesion_detection",
                    "surface_analysis",
                    "radiomics_extraction",
                ],
                required_inputs=["t1_file"],
                expected_outputs=["clinical_report", "segmentation", "volumetrics"],
                estimated_duration="10-20 minutes",
            ),
            WorkflowType.CONNECTIVITY_ANALYSIS: WorkflowDefinition(
                name="Brain Connectivity Analysis",
                description="Functional and effective connectivity analysis",
                required_tools=["functional_connectivity", "graph_network_analysis"],
                optional_tools=[
                    "dynamic_connectivity",
                    "effective_connectivity",
                    "gnn_connectivity",
                ],
                required_inputs=["fmri_file", "atlas_file"],
                expected_outputs=[
                    "connectivity_matrix",
                    "graph_metrics",
                    "network_visualization",
                ],
                estimated_duration="20-40 minutes",
            ),
            WorkflowType.ML_CLASSIFICATION: WorkflowDefinition(
                name="Machine Learning Classification",
                description="MVPA and deep learning classification pipeline",
                required_tools=[
                    "feature_selection",
                    "mvpa_classification",
                    "cross_validation",
                ],
                optional_tools=[
                    "deep_learning_fmri",
                    "permutation_testing",
                    "searchlight_analysis",
                ],
                required_inputs=["fmri_file", "labels_file"],
                expected_outputs=[
                    "classification_accuracy",
                    "feature_importance",
                    "cv_results",
                ],
                estimated_duration="30-60 minutes",
            ),
            WorkflowType.DIFFUSION_ANALYSIS: WorkflowDefinition(
                name="Diffusion MRI Analysis",
                description="DTI/DWI processing and tractography",
                required_tools=["qsiprep_preprocessing", "diffusion_tractography"],
                optional_tools=["graph_network_analysis", "structural_connectivity"],
                required_inputs=["dwi_file", "bvals_file", "bvecs_file"],
                expected_outputs=["fa_map", "tractography", "structural_connectivity"],
                estimated_duration="45-90 minutes",
            ),
            WorkflowType.MULTIMODAL: WorkflowDefinition(
                name="Multimodal Integration",
                description="Integrate multiple imaging modalities",
                required_tools=["coregistration", "multimodal_integration"],
                optional_tools=["advanced_brain_plotting", "interactive_visualization"],
                required_inputs=["t1_file", "fmri_file", "dwi_file"],
                expected_outputs=["integrated_maps", "cross_modal_features"],
                estimated_duration="30-45 minutes",
            ),
            WorkflowType.QUALITY_CONTROL: WorkflowDefinition(
                name="Quality Control Pipeline",
                description="Comprehensive QC and artifact detection",
                required_tools=["quality_control", "motion_quantification"],
                optional_tools=["mriqc_individual_report", "visual_qc_launch"],
                required_inputs=["imaging_file"],
                expected_outputs=["qc_report", "quality_metrics", "artifact_mask"],
                estimated_duration="5-10 minutes",
            ),
            WorkflowType.META_ANALYSIS: WorkflowDefinition(
                name="Meta-Analysis Pipeline",
                description="Coordinate-based or image-based meta-analysis",
                required_tools=["meta_analysis", "literature_search"],
                optional_tools=["ale_meta_analysis", "sdm_meta_analysis"],
                required_inputs=["coordinates_file"],
                expected_outputs=["meta_map", "cluster_report", "forest_plot"],
                estimated_duration="15-30 minutes",
            ),
        }

    def create_workflow_prompt(
        self, workflow_type: WorkflowType, inputs: Dict[str, Any]
    ) -> str:
        """
        Create a prompt that guides the LangGraph agent through a workflow.

        This prompt will be used by the state machine to plan and execute
        the appropriate sequence of tools.
        """
        workflow = self.workflows[workflow_type]

        prompt = f"""
Please execute the {workflow.name} workflow.

**Workflow Description**: {workflow.description}

**Available Input Data**:
{self._format_inputs(inputs)}

**Required Analysis Steps** (execute in order):
{self._format_required_tools(workflow.required_tools)}

**Optional Enhancements** (include if beneficial):
{self._format_optional_tools(workflow.optional_tools)}

**Expected Outputs**:
{', '.join(workflow.expected_outputs)}

**Estimated Duration**: {workflow.estimated_duration}

Please proceed with the analysis, ensuring data quality checks at each step.
Report any issues or unexpected findings during the analysis.
"""
        return prompt

    def validate_inputs(
        self, workflow_type: WorkflowType, inputs: Dict[str, Any]
    ) -> tuple[bool, List[str]]:
        """Validate that required inputs are provided for a workflow."""
        workflow = self.workflows[workflow_type]
        missing = []

        for required_input in workflow.required_inputs:
            if required_input not in inputs:
                missing.append(required_input)

        return len(missing) == 0, missing

    def get_workflow_tools(self, workflow_type: WorkflowType) -> List[str]:
        """Get all tools needed for a workflow."""
        workflow = self.workflows[workflow_type]
        resolved = self.get_workflow_candidates(workflow_type)

        def pick(name: str) -> str:
            if name in resolved and resolved[name]:
                return resolved[name][0]
            return name

        return [pick(t) for t in workflow.required_tools] + [
            pick(t) for t in workflow.optional_tools
        ]

    def suggest_tools_by_metadata(
        self,
        domain: str,
        function: str | None = None,
        risk: str | None = None,
        limit: int = 5,
    ) -> List[str]:
        """Return top tool ids matching domain/function/risk using a weighted score."""
        specs = []
        for tool in self.registry.get_all_tools():
            spec = spec_from_tool(tool)
            if spec:
                specs.append(spec)

        def score(spec):
            tags = {t.lower() for t in (spec.tags or [])}
            s = 0
            if domain and domain.lower() in tags:
                s += 5
            if function and function.lower() in tags:
                s += 3
            if "dangerous" in tags or "high_cost" in tags:
                s -= 2
            if function and function.lower() in spec.name.lower():
                s += 1
            return s

        ranked = sorted(
            ((score(s), s.name) for s in specs), key=lambda x: x[0], reverse=True
        )
        return [name for sc, name in ranked if sc > 0][:limit]

    def get_workflow_candidates(
        self, workflow_type: WorkflowType
    ) -> Dict[str, List[str]]:
        """Suggest concrete tool ids for each required step based on domain/function tags."""
        workflow = self.workflows[workflow_type]
        # Simple mapping from step name keywords to domain/function
        hints = {
            "skull": ("fmri.preproc", "preproc"),
            "motion": ("fmri.qc", "qc"),
            "glm": ("fmri.glm", "glm"),
            "contrast": ("fmri.glm", "glm"),
            "multiple_comparison": ("fmri.glm", "glm"),
            "functional_connectivity": ("fmri.connectivity", "connectivity"),
            "qsiprep": ("dmri.preproc", "preproc"),
            "tractography": ("dmri.tractography", "connectivity"),
            "parcellation": ("surface.parcellation", "analysis"),
            "meta": ("meta", "meta"),
            "quality_control": ("fmri.qc", "qc"),
            "visual": ("fmri.viz", "visualization"),
        }
        suggestions: Dict[str, List[str]] = {}
        for step in workflow.required_tools:
            key = step.lower()
            domain = function = None
            for kw, (d, f) in hints.items():
                if kw in key:
                    domain, function = d, f
                    break
            if domain:
                suggestions[step] = self.suggest_tools_by_metadata(
                    domain=domain, function=function, limit=5
                )
        return suggestions

    def estimate_workflow_duration(self, workflow_type: WorkflowType) -> str:
        """Get estimated duration for a workflow."""
        return self.workflows[workflow_type].estimated_duration

    def _format_inputs(self, inputs: Dict[str, Any]) -> str:
        """Format input dictionary for prompt."""
        lines = []
        for key, value in inputs.items():
            if isinstance(value, str):
                lines.append(f"- {key}: {value}")
            else:
                lines.append(f"- {key}: {type(value).__name__}")
        return "\n".join(lines)

    def _format_required_tools(self, tools: List[str]) -> str:
        """Format required tools for prompt."""
        lines = []
        for i, tool in enumerate(tools, 1):
            tool_obj = self.registry.get_tool(tool)
            if tool_obj:
                desc = None
                try:
                    if hasattr(tool_obj, "get_tool_description"):
                        desc = tool_obj.get_tool_description()
                    else:
                        desc = getattr(tool_obj, "description", None)
                except Exception:
                    desc = None
                if desc:
                    lines.append(f"{i}. {tool}: {desc}")
                else:
                    lines.append(f"{i}. {tool}")
            else:
                lines.append(f"{i}. {tool}")
        return "\n".join(lines)

    def _format_optional_tools(self, tools: List[str]) -> str:
        """Format optional tools for prompt."""
        lines = []
        for tool in tools:
            tool_obj = self.registry.get_tool(tool)
            if tool_obj:
                desc = None
                try:
                    if hasattr(tool_obj, "get_tool_description"):
                        desc = tool_obj.get_tool_description()
                    else:
                        desc = getattr(tool_obj, "description", None)
                except Exception:
                    desc = None
                if desc:
                    lines.append(f"- {tool}: {desc}")
                else:
                    lines.append(f"- {tool}")
            else:
                lines.append(f"- {tool}")
        return "\n".join(lines)

    async def execute_workflow(
        self,
        workflow_type: WorkflowType,
        inputs: Dict[str, Any],
        thread_id: Optional[str] = None,
        resume_checkpoint_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a workflow using the LangGraph state machine.

        This is the main entry point for running pre-configured workflows.
        """
        # Validate inputs
        valid, missing = self.validate_inputs(workflow_type, inputs)
        if not valid:
            return {
                "status": "error",
                "error": f"Missing required inputs: {', '.join(missing)}",
            }

        # Start monitoring
        workflow_id = f"{workflow_type.value}_{thread_id or 'default'}"
        workflow_metrics = metrics_collector.start_workflow(workflow_id)

        try:
            # Create workflow prompt
            prompt = self.create_workflow_prompt(workflow_type, inputs)

            # Execute through state machine
            result = await self.state_machine.run_async(
                prompt,
                thread_id=thread_id,
                resume_checkpoint_id=resume_checkpoint_id,
            )

            checkpoint_id = None
            try:
                checkpoint_id = self.state_machine.get_last_checkpoint_id(
                    thread_id or ""
                )
            except Exception:
                checkpoint_id = None

            # Mark workflow as successful
            metrics_collector.end_workflow(workflow_id, success=True)

            return {
                "status": "success",
                "workflow_type": workflow_type.value,
                "result": result,
                "checkpoint_id": checkpoint_id,
                "metrics": {
                    "duration": workflow_metrics.total_time,
                    "tools_used": workflow_metrics.tools_used,
                    "state_transitions": workflow_metrics.state_transitions,
                },
            }

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            metrics_collector.end_workflow(workflow_id, success=False)

            return {
                "status": "error",
                "workflow_type": workflow_type.value,
                "error": str(e),
            }


class WorkflowOrchestrator:
    """
    High-level orchestrator for managing multiple workflows.
    This is different from tool orchestration - it manages LangGraph workflows.
    """

    def __init__(self):
        self.workflows = NeuroimagingWorkflows()
        self.active_sessions = {}

    def list_available_workflows(self) -> List[Dict[str, Any]]:
        """List all available workflow types with descriptions."""
        return [
            {
                "type": wf_type.value,
                "name": wf_def.name,
                "description": wf_def.description,
                "required_inputs": wf_def.required_inputs,
                "estimated_duration": wf_def.estimated_duration,
            }
            for wf_type, wf_def in self.workflows.workflows.items()
        ]

    def get_workflow_requirements(self, workflow_type: str) -> Dict[str, Any]:
        """Get detailed requirements for a workflow."""
        try:
            wf_type = WorkflowType(workflow_type)
            wf_def = self.workflows.workflows[wf_type]

            return {
                "name": wf_def.name,
                "required_inputs": wf_def.required_inputs,
                "optional_inputs": [],  # Could be extended
                "required_tools": wf_def.required_tools,
                "optional_tools": wf_def.optional_tools,
                "expected_outputs": wf_def.expected_outputs,
                "estimated_duration": wf_def.estimated_duration,
            }
        except (ValueError, KeyError):
            return {"error": f"Unknown workflow type: {workflow_type}"}

    async def run_workflow(
        self,
        workflow_type: str,
        inputs: Dict[str, Any],
        session_id: Optional[str] = None,
        resume_checkpoint_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a specific workflow."""
        try:
            wf_type = WorkflowType(workflow_type)
            result = await self.workflows.execute_workflow(
                wf_type,
                inputs,
                thread_id=session_id,
                resume_checkpoint_id=resume_checkpoint_id,
            )
            return result
        except ValueError:
            return {
                "status": "error",
                "error": f"Unknown workflow type: {workflow_type}",
            }

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get status of a workflow session."""
        if session_id in self.active_sessions:
            return self.active_sessions[session_id]
        return {"status": "not_found"}


# Singleton instance
workflow_orchestrator = WorkflowOrchestrator()
