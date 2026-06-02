"""Workflow templates for common neuroimaging analysis patterns."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import yaml

# Try to import Jinja2 for template processing
try:
    from jinja2 import Environment, FileSystemLoader, Template

    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False


class WorkflowType(str, Enum):
    """Types of workflow templates."""

    # Analysis workflows
    STANDARD_GLM = "standard_glm"
    GROUP_COMPARISON = "group_comparison"
    CONNECTIVITY_ANALYSIS = "connectivity_analysis"
    REGION_OF_INTEREST = "roi_analysis"
    META_ANALYSIS = "meta_analysis"

    # Data processing workflows
    PREPROCESSING = "preprocessing"
    QUALITY_CONTROL = "quality_control"
    DATA_INGESTION = "data_ingestion"

    # Exploration workflows
    EXPLORATORY = "exploratory"
    HYPOTHESIS_TESTING = "hypothesis_testing"
    VISUALIZATION = "visualization"

    # Custom workflows
    CUSTOM = "custom"


@dataclass
class WorkflowStep:
    """Single step in a workflow."""

    name: str
    tool: str
    description: str
    parameters: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    optional: bool = False
    timeout_seconds: int = 300
    retry_on_failure: bool = True
    max_retries: int = 3

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "tool": self.tool,
            "description": self.description,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "optional": self.optional,
            "timeout_seconds": self.timeout_seconds,
            "retry_on_failure": self.retry_on_failure,
            "max_retries": self.max_retries,
        }


@dataclass
class WorkflowTemplate:
    """Workflow template definition."""

    id: str
    name: str
    type: WorkflowType
    description: str
    version: str
    steps: List[WorkflowStep]
    parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        """Validate workflow template.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check for duplicate step names
        step_names = [step.name for step in self.steps]
        if len(step_names) != len(set(step_names)):
            errors.append("Duplicate step names found")

        # Check dependencies
        for step in self.steps:
            for dep in step.dependencies:
                if dep not in step_names:
                    errors.append(f"Step '{step.name}' has invalid dependency '{dep}'")

        # Check for circular dependencies
        if self._has_circular_dependencies():
            errors.append("Circular dependencies detected")

        return errors

    def _has_circular_dependencies(self) -> bool:
        """Check for circular dependencies."""
        visited = set()
        rec_stack = set()

        def has_cycle(step_name: str) -> bool:
            visited.add(step_name)
            rec_stack.add(step_name)

            step = next((s for s in self.steps if s.name == step_name), None)
            if step:
                for dep in step.dependencies:
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True

            rec_stack.remove(step_name)
            return False

        for step in self.steps:
            if step.name not in visited:
                if has_cycle(step.name):
                    return True

        return False

    def get_execution_order(self) -> List[str]:
        """Get topologically sorted execution order.

        Returns:
            List of step names in execution order
        """
        # Build adjacency list
        graph = {step.name: step.dependencies for step in self.steps}

        # Topological sort
        visited = set()
        stack = []

        def topo_sort(node: str):
            visited.add(node)
            for dep in graph.get(node, []):
                if dep not in visited:
                    topo_sort(dep)
            stack.append(node)

        for step_name in graph:
            if step_name not in visited:
                topo_sort(step_name)

        return list(reversed(stack))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "version": self.version,
            "steps": [step.to_dict() for step in self.steps],
            "parameters": self.parameters,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowTemplate":
        """Create from dictionary."""
        steps = [
            WorkflowStep(
                name=s["name"],
                tool=s["tool"],
                description=s["description"],
                parameters=s["parameters"],
                dependencies=s.get("dependencies", []),
                optional=s.get("optional", False),
                timeout_seconds=s.get("timeout_seconds", 300),
                retry_on_failure=s.get("retry_on_failure", True),
                max_retries=s.get("max_retries", 3),
            )
            for s in data["steps"]
        ]

        return cls(
            id=data["id"],
            name=data["name"],
            type=WorkflowType(data["type"]),
            description=data["description"],
            version=data["version"],
            steps=steps,
            parameters=data.get("parameters", {}),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(
                data.get("created_at", datetime.now().isoformat())
            ),
            tags=data.get("tags", []),
        )


class WorkflowTemplateLibrary:
    """Library of predefined workflow templates."""

    def __init__(self):
        """Initialize template library."""
        self.templates: Dict[str, WorkflowTemplate] = {}
        self._load_builtin_templates()

    def _load_builtin_templates(self):
        """Load built-in workflow templates."""

        # Standard GLM Analysis
        self.templates["standard_glm"] = WorkflowTemplate(
            id="standard_glm_v1",
            name="Standard GLM Analysis",
            type=WorkflowType.STANDARD_GLM,
            description="Standard General Linear Model analysis for fMRI data",
            version="1.0.0",
            steps=[
                WorkflowStep(
                    name="load_data",
                    tool="fmri_data_loader",
                    description="Load fMRI data and experimental design",
                    parameters={
                        "data_path": "${data_path}",
                        "design_matrix_path": "${design_matrix_path}",
                        "mask_path": "${mask_path}",
                    },
                ),
                WorkflowStep(
                    name="preprocess",
                    tool="preprocessing",
                    description="Preprocess fMRI data",
                    parameters={
                        "smoothing_fwhm": 6,
                        "high_pass_filter": 0.01,
                        "standardize": True,
                    },
                    dependencies=["load_data"],
                    optional=True,
                ),
                WorkflowStep(
                    name="fit_glm",
                    tool="glm_analysis",
                    description="Fit GLM to fMRI data",
                    parameters={
                        "model_type": "standard",
                        "drift_model": "cosine",
                        "noise_model": "ar1",
                    },
                    dependencies=["preprocess"],
                ),
                WorkflowStep(
                    name="compute_contrasts",
                    tool="contrast_analysis",
                    description="Compute statistical contrasts",
                    parameters={
                        "contrasts": "${contrasts}",
                        "correction_method": "fdr",
                        "alpha": 0.05,
                    },
                    dependencies=["fit_glm"],
                ),
                WorkflowStep(
                    name="visualize_results",
                    tool="visualization",
                    description="Generate brain maps and plots",
                    parameters={
                        "plot_type": "statistical_map",
                        "threshold": 2.3,
                        "colormap": "hot",
                    },
                    dependencies=["compute_contrasts"],
                ),
            ],
            parameters={
                "data_path": None,
                "design_matrix_path": None,
                "mask_path": None,
                "contrasts": [],
            },
            tags=["fmri", "glm", "statistics"],
        )

        # Group Comparison
        self.templates["group_comparison"] = WorkflowTemplate(
            id="group_comparison_v1",
            name="Group Comparison Analysis",
            type=WorkflowType.GROUP_COMPARISON,
            description="Compare brain activity between groups",
            version="1.0.0",
            steps=[
                WorkflowStep(
                    name="load_groups",
                    tool="group_data_loader",
                    description="Load data for multiple groups",
                    parameters={
                        "group1_data": "${group1_data}",
                        "group2_data": "${group2_data}",
                        "covariates": "${covariates}",
                    },
                ),
                WorkflowStep(
                    name="normalize",
                    tool="spatial_normalization",
                    description="Normalize to standard space",
                    parameters={"template": "MNI152", "resolution": 2},
                    dependencies=["load_groups"],
                ),
                WorkflowStep(
                    name="statistical_test",
                    tool="group_statistics",
                    description="Perform group comparison",
                    parameters={
                        "test_type": "${test_type}",
                        "correction": "cluster",
                        "threshold": 0.001,
                    },
                    dependencies=["normalize"],
                ),
                WorkflowStep(
                    name="effect_size",
                    tool="effect_size_calculator",
                    description="Calculate effect sizes",
                    parameters={"metric": "cohen's d"},
                    dependencies=["statistical_test"],
                    optional=True,
                ),
                WorkflowStep(
                    name="report",
                    tool="report_generator",
                    description="Generate analysis report",
                    parameters={"format": "html", "include_plots": True},
                    dependencies=["statistical_test", "effect_size"],
                ),
            ],
            parameters={
                "group1_data": None,
                "group2_data": None,
                "covariates": [],
                "test_type": "t-test",
            },
            tags=["group", "comparison", "statistics"],
        )

        # Connectivity Analysis
        self.templates["connectivity"] = WorkflowTemplate(
            id="connectivity_v1",
            name="Functional Connectivity Analysis",
            type=WorkflowType.CONNECTIVITY_ANALYSIS,
            description="Analyze functional connectivity patterns",
            version="1.0.0",
            steps=[
                WorkflowStep(
                    name="extract_timeseries",
                    tool="timeseries_extractor",
                    description="Extract ROI timeseries",
                    parameters={
                        "atlas": "${atlas}",
                        "detrend": True,
                        "standardize": True,
                    },
                ),
                WorkflowStep(
                    name="compute_connectivity",
                    tool="connectivity_calculator",
                    description="Calculate connectivity matrix",
                    parameters={
                        "method": "${connectivity_method}",
                        "regularization": 0.1,
                    },
                    dependencies=["extract_timeseries"],
                ),
                WorkflowStep(
                    name="graph_analysis",
                    tool="graph_metrics",
                    description="Compute graph theory metrics",
                    parameters={
                        "metrics": ["degree", "betweenness", "clustering"],
                        "threshold": "${threshold}",
                    },
                    dependencies=["compute_connectivity"],
                    optional=True,
                ),
                WorkflowStep(
                    name="visualize_network",
                    tool="network_visualization",
                    description="Visualize connectivity network",
                    parameters={
                        "layout": "spring",
                        "node_size": "degree",
                        "edge_threshold": 0.3,
                    },
                    dependencies=["compute_connectivity"],
                ),
            ],
            parameters={
                "atlas": "AAL",
                "connectivity_method": "correlation",
                "threshold": 0.2,
            },
            tags=["connectivity", "network", "graph"],
        )

        # Meta-analysis
        self.templates["meta_analysis"] = WorkflowTemplate(
            id="meta_analysis_v1",
            name="Coordinate-based Meta-analysis",
            type=WorkflowType.META_ANALYSIS,
            description="Perform coordinate-based meta-analysis",
            version="1.0.0",
            steps=[
                WorkflowStep(
                    name="collect_studies",
                    tool="study_collector",
                    description="Collect studies from databases",
                    parameters={
                        "databases": "${databases}",
                        "search_terms": "${search_terms}",
                        "inclusion_criteria": "${inclusion_criteria}",
                    },
                ),
                WorkflowStep(
                    name="extract_coordinates",
                    tool="coordinate_extractor",
                    description="Extract peak coordinates",
                    parameters={"space": "MNI", "min_cluster_size": 10},
                    dependencies=["collect_studies"],
                ),
                WorkflowStep(
                    name="ale_analysis",
                    tool="ale_calculator",
                    description="Perform ALE meta-analysis",
                    parameters={"fwhm": 10, "threshold": 0.001, "n_simulations": 5000},
                    dependencies=["extract_coordinates"],
                ),
                WorkflowStep(
                    name="cluster_analysis",
                    tool="cluster_analyzer",
                    description="Analyze significant clusters",
                    parameters={"min_cluster_size": 200, "anatomical_labels": True},
                    dependencies=["ale_analysis"],
                ),
            ],
            parameters={
                "databases": ["neurosynth", "brainmap"],
                "search_terms": [],
                "inclusion_criteria": {},
            },
            tags=["meta-analysis", "ale", "coordinates"],
        )

    def get_template(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Get template by ID."""
        return self.templates.get(template_id)

    def list_templates(
        self,
        type_filter: Optional[WorkflowType] = None,
        tags: Optional[List[str]] = None,
    ) -> List[WorkflowTemplate]:
        """List available templates.

        Args:
            type_filter: Filter by workflow type
            tags: Filter by tags

        Returns:
            List of matching templates
        """
        templates = list(self.templates.values())

        if type_filter:
            templates = [t for t in templates if t.type == type_filter]

        if tags:
            templates = [t for t in templates if any(tag in t.tags for tag in tags)]

        return templates

    def add_template(self, template: WorkflowTemplate) -> bool:
        """Add custom template to library.

        Args:
            template: Template to add

        Returns:
            True if added successfully
        """
        errors = template.validate()
        if errors:
            raise ValueError(f"Invalid template: {', '.join(errors)}")

        self.templates[template.id] = template
        return True

    def remove_template(self, template_id: str) -> bool:
        """Remove template from library."""
        if template_id in self.templates:
            del self.templates[template_id]
            return True
        return False

    def export_template(self, template_id: str, format: str = "json") -> str:
        """Export template to string.

        Args:
            template_id: Template to export
            format: Export format ('json' or 'yaml')

        Returns:
            Serialized template
        """
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        data = template.to_dict()

        if format == "json":
            return json.dumps(data, indent=2)
        elif format == "yaml":
            return yaml.dump(data, default_flow_style=False)
        else:
            raise ValueError(f"Unknown format: {format}")

    def import_template(self, data: str, format: str = "json") -> WorkflowTemplate:
        """Import template from string.

        Args:
            data: Serialized template
            format: Data format ('json' or 'yaml')

        Returns:
            Imported template
        """
        if format == "json":
            template_data = json.loads(data)
        elif format == "yaml":
            template_data = yaml.safe_load(data)
        else:
            raise ValueError(f"Unknown format: {format}")

        template = WorkflowTemplate.from_dict(template_data)
        self.add_template(template)

        return template


class WorkflowExecutor:
    """Execute workflow templates."""

    def __init__(self, tool_registry: Optional[Dict[str, Callable]] = None):
        """Initialize workflow executor.

        Args:
            tool_registry: Registry of available tools
        """
        self.tool_registry = tool_registry or {}
        self.execution_history: List[Dict[str, Any]] = []

        if JINJA2_AVAILABLE:
            self.jinja_env = Environment()

    def register_tool(self, name: str, tool: Callable):
        """Register a tool for workflow execution."""
        self.tool_registry[name] = tool

    def execute(
        self,
        template: WorkflowTemplate,
        parameters: Dict[str, Any],
        skip_optional: bool = False,
    ) -> Dict[str, Any]:
        """Execute a workflow template.

        Args:
            template: Workflow template to execute
            parameters: Parameters for the workflow
            skip_optional: Skip optional steps

        Returns:
            Execution results
        """
        # Validate template
        errors = template.validate()
        if errors:
            raise ValueError(f"Invalid template: {', '.join(errors)}")

        # Merge parameters
        merged_params = {**template.parameters, **parameters}

        # Render parameters if Jinja2 available
        if JINJA2_AVAILABLE:
            merged_params = self._render_parameters(merged_params)

        # Get execution order
        execution_order = template.get_execution_order()

        # Execute steps
        results = {}
        execution_record = {
            "template_id": template.id,
            "started_at": datetime.now(),
            "parameters": merged_params,
            "steps": [],
        }

        for step_name in execution_order:
            step = next(s for s in template.steps if s.name == step_name)

            # Skip optional steps if requested
            if skip_optional and step.optional:
                continue

            # Check dependencies
            for dep in step.dependencies:
                if dep not in results:
                    raise RuntimeError(
                        f"Dependency '{dep}' not satisfied for step '{step_name}'"
                    )

            # Execute step
            step_result = self._execute_step(step, merged_params, results)
            results[step_name] = step_result

            execution_record["steps"].append(
                {
                    "name": step_name,
                    "tool": step.tool,
                    "started_at": step_result.get("started_at"),
                    "completed_at": step_result.get("completed_at"),
                    "status": step_result.get("status"),
                    "result": step_result.get("result"),
                }
            )

        execution_record["completed_at"] = datetime.now()
        execution_record["status"] = "completed"

        self.execution_history.append(execution_record)

        return {
            "template": template.name,
            "execution_id": str(uuid.uuid4()),
            "results": results,
            "execution_record": execution_record,
        }

    def _execute_step(
        self,
        step: WorkflowStep,
        parameters: Dict[str, Any],
        previous_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single workflow step.

        Args:
            step: Step to execute
            parameters: Workflow parameters
            previous_results: Results from previous steps

        Returns:
            Step execution result
        """
        if step.tool not in self.tool_registry:
            raise ValueError(f"Tool '{step.tool}' not found in registry")

        tool = self.tool_registry[step.tool]

        # Prepare step parameters
        step_params = self._prepare_step_parameters(
            step.parameters, parameters, previous_results
        )

        # Execute with retry logic
        attempts = 0
        last_error = None

        started_at = datetime.now()

        while attempts < step.max_retries:
            try:
                result = tool(**step_params)

                return {
                    "status": "success",
                    "result": result,
                    "started_at": started_at.isoformat(),
                    "completed_at": datetime.now().isoformat(),
                    "attempts": attempts + 1,
                }

            except Exception as e:
                last_error = e
                attempts += 1

                if not step.retry_on_failure or attempts >= step.max_retries:
                    break

        # Step failed
        return {
            "status": "failed",
            "error": str(last_error),
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now().isoformat(),
            "attempts": attempts,
        }

    def _prepare_step_parameters(
        self,
        step_params: Dict[str, Any],
        workflow_params: Dict[str, Any],
        previous_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Prepare parameters for step execution.

        Args:
            step_params: Step parameter template
            workflow_params: Workflow parameters
            previous_results: Results from previous steps

        Returns:
            Resolved parameters
        """
        resolved = {}

        for key, value in step_params.items():
            if isinstance(value, str):
                # Check for parameter references
                if value.startswith("${") and value.endswith("}"):
                    param_name = value[2:-1]

                    # Check workflow parameters
                    if param_name in workflow_params:
                        resolved[key] = workflow_params[param_name]
                    # Check previous results
                    elif "." in param_name:
                        step_name, result_key = param_name.split(".", 1)
                        if step_name in previous_results:
                            step_result = previous_results[step_name]
                            if (
                                "result" in step_result
                                and result_key in step_result["result"]
                            ):
                                resolved[key] = step_result["result"][result_key]
                    else:
                        resolved[key] = None
                else:
                    resolved[key] = value
            else:
                resolved[key] = value

        return resolved

    def _render_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Render parameters using Jinja2 templates.

        Args:
            parameters: Parameters with potential templates

        Returns:
            Rendered parameters
        """
        if not JINJA2_AVAILABLE:
            return parameters

        rendered = {}

        for key, value in parameters.items():
            if isinstance(value, str) and "{{" in value:
                template = self.jinja_env.from_string(value)
                rendered[key] = template.render(**parameters)
            else:
                rendered[key] = value

        return rendered

    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent execution history.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of execution records
        """
        return self.execution_history[-limit:]

    def clear_history(self):
        """Clear execution history."""
        self.execution_history = []


# Create global template library instance
_global_library = WorkflowTemplateLibrary()


def get_template_library() -> WorkflowTemplateLibrary:
    """Get global template library."""
    return _global_library


def create_custom_workflow(
    name: str,
    steps: List[Dict[str, Any]],
    description: str = "",
    parameters: Dict[str, Any] = None,
) -> WorkflowTemplate:
    """Create a custom workflow template.

    Args:
        name: Workflow name
        steps: List of step definitions
        description: Workflow description
        parameters: Default parameters

    Returns:
        Created workflow template
    """
    workflow_steps = []

    for step_data in steps:
        step = WorkflowStep(
            name=step_data["name"],
            tool=step_data["tool"],
            description=step_data.get("description", ""),
            parameters=step_data.get("parameters", {}),
            dependencies=step_data.get("dependencies", []),
            optional=step_data.get("optional", False),
        )
        workflow_steps.append(step)

    template = WorkflowTemplate(
        id=f"custom_{uuid.uuid4().hex[:8]}",
        name=name,
        type=WorkflowType.CUSTOM,
        description=description,
        version="1.0.0",
        steps=workflow_steps,
        parameters=parameters or {},
    )

    return template
