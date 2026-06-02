"""
Workflow Templates Module for Brain Researcher Agent (AGENT-018)

This module implements pre-defined workflow templates for common analysis patterns,
including YAML-based template definitions, parameter substitution with validation,
template inheritance support, and custom template creation.
"""

import asyncio
import json
import logging
import os
import re
import resource
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import yaml
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


class TemplateStatus(str, Enum):
    """Status of workflow templates."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"
    DRAFT = "draft"


class ParameterType(str, Enum):
    """Types of template parameters."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    PATH = "path"
    LIST = "list"
    DICT = "dict"
    DATASET_ID = "dataset_id"
    BRAIN_REGION = "brain_region"
    TASK = "task"
    CONTRAST = "contrast"


@dataclass
class TemplateParameter:
    """Represents a template parameter with validation rules."""

    name: str
    type: ParameterType
    description: str
    required: bool = False
    default: Any = None
    choices: Optional[List[Any]] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    pattern: Optional[str] = None
    validation_rules: List[str] = field(default_factory=list)

    def validate_value(self, value: Any) -> Tuple[bool, Optional[str]]:
        """
        Validate a parameter value against the rules.

        Args:
            value: Value to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check required
        if self.required and value is None:
            return False, f"Parameter '{self.name}' is required"

        if value is None and not self.required:
            return True, None

        # Type validation
        try:
            validated_value = self._convert_type(value)
        except (ValueError, TypeError) as e:
            return False, f"Parameter '{self.name}' type error: {e}"

        # Choices validation
        if self.choices and validated_value not in self.choices:
            return False, f"Parameter '{self.name}' must be one of: {self.choices}"

        # Range validation
        if self.type in [ParameterType.INTEGER, ParameterType.FLOAT]:
            if self.min_value is not None and validated_value < self.min_value:
                return False, f"Parameter '{self.name}' must be >= {self.min_value}"
            if self.max_value is not None and validated_value > self.max_value:
                return False, f"Parameter '{self.name}' must be <= {self.max_value}"

        # Pattern validation
        if self.pattern and self.type == ParameterType.STRING:
            if not re.match(self.pattern, str(validated_value)):
                return False, f"Parameter '{self.name}' does not match required pattern"

        # Path validation
        if self.type == ParameterType.PATH:
            path = Path(str(validated_value))
            if not path.exists():
                return False, f"Path '{self.name}' does not exist: {validated_value}"

        return True, None

    def _convert_type(self, value: Any) -> Any:
        """Convert value to the expected type."""
        if self.type == ParameterType.STRING:
            return str(value)
        elif self.type == ParameterType.INTEGER:
            return int(value)
        elif self.type == ParameterType.FLOAT:
            return float(value)
        elif self.type == ParameterType.BOOLEAN:
            if isinstance(value, str):
                return value.lower() in ["true", "1", "yes", "on"]
            return bool(value)
        elif self.type == ParameterType.LIST:
            if isinstance(value, str):
                return [item.strip() for item in value.split(",")]
            elif isinstance(value, list):
                return value
            else:
                return [value]
        elif self.type in [
            ParameterType.PATH,
            ParameterType.DATASET_ID,
            ParameterType.BRAIN_REGION,
            ParameterType.TASK,
            ParameterType.CONTRAST,
        ]:
            return str(value)
        elif self.type == ParameterType.DICT:
            if isinstance(value, str):
                return json.loads(value)
            elif isinstance(value, dict):
                return value
            else:
                raise ValueError(f"Cannot convert {type(value)} to dict")

        return value


@dataclass
class WorkflowStep:
    """Represents a step in a workflow template."""

    name: str
    tool: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    optional: bool = False
    timeout_seconds: Optional[int] = None
    retry_count: int = 0
    conditions: List[str] = field(default_factory=list)


@dataclass
class WorkflowTemplate:
    """Represents a complete workflow template."""

    id: str
    name: str
    description: str
    version: str
    category: str
    author: str
    created_at: datetime
    status: TemplateStatus = TemplateStatus.ACTIVE
    tags: List[str] = field(default_factory=list)
    parameters: List[TemplateParameter] = field(default_factory=list)
    steps: List[WorkflowStep] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    inherits_from: Optional[str] = None

    def get_required_parameters(self) -> List[TemplateParameter]:
        """Get list of required parameters."""
        return [param for param in self.parameters if param.required]

    def validate_parameters(self, values: Dict[str, Any]) -> List[str]:
        """
        Validate parameter values against template requirements.

        Args:
            values: Parameter values to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        for param in self.parameters:
            value = values.get(param.name)
            is_valid, error_msg = param.validate_value(value)

            if not is_valid:
                errors.append(error_msg)

        return errors


class TemplateValidator:
    """Validates workflow templates for correctness and consistency."""

    def __init__(self):
        """Initialize the template validator."""
        self.validation_rules = [
            self._validate_structure,
            self._validate_parameters,
            self._validate_steps,
            self._validate_dependencies,
            self._validate_tools,
        ]

    def validate_template(self, template: WorkflowTemplate) -> List[str]:
        """
        Validate a workflow template.

        Args:
            template: Template to validate

        Returns:
            List of validation issues (empty if valid)
        """
        issues = []

        for rule in self.validation_rules:
            rule_issues = rule(template)
            issues.extend(rule_issues)

        return issues

    def _validate_structure(self, template: WorkflowTemplate) -> List[str]:
        """Validate basic template structure."""
        issues = []

        if not template.id:
            issues.append("Template must have an ID")

        if not template.name:
            issues.append("Template must have a name")

        if not template.steps:
            issues.append("Template must have at least one step")

        if not template.version:
            issues.append("Template must have a version")

        return issues

    def _validate_parameters(self, template: WorkflowTemplate) -> List[str]:
        """Validate template parameters."""
        issues = []

        param_names = set()
        for param in template.parameters:
            if param.name in param_names:
                issues.append(f"Duplicate parameter name: {param.name}")
            param_names.add(param.name)

            # Check for valid parameter names (no spaces, special chars)
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", param.name):
                issues.append(f"Invalid parameter name: {param.name}")

        return issues

    def _validate_steps(self, template: WorkflowTemplate) -> List[str]:
        """Validate workflow steps."""
        issues = []

        step_names = set()
        for step in template.steps:
            if step.name in step_names:
                issues.append(f"Duplicate step name: {step.name}")
            step_names.add(step.name)

            if not step.tool:
                issues.append(f"Step '{step.name}' must specify a tool")

        return issues

    def _validate_dependencies(self, template: WorkflowTemplate) -> List[str]:
        """Validate step dependencies."""
        issues = []

        step_names = {step.name for step in template.steps}

        for step in template.steps:
            for dep in step.depends_on:
                if dep not in step_names:
                    issues.append(f"Step '{step.name}' depends on unknown step: {dep}")

        # Check for circular dependencies
        if self._has_circular_dependencies(template.steps):
            issues.append("Template has circular dependencies")

        return issues

    def _validate_tools(self, template: WorkflowTemplate) -> List[str]:
        """Validate that referenced tools exist."""
        issues = []

        # Get available tools from registry
        try:
            from brain_researcher.services.tools.tool_registry import ToolRegistry

            registry = ToolRegistry()
            available_tools = {
                tool.get_tool_name() for tool in registry.get_all_tools()
            }

            for step in template.steps:
                if step.tool not in available_tools:
                    issues.append(
                        f"Step '{step.name}' references unknown tool: {step.tool}"
                    )

        except Exception as e:
            logger.warning(f"Could not validate tools: {e}")

        return issues

    def _has_circular_dependencies(self, steps: List[WorkflowStep]) -> bool:
        """Check for circular dependencies in workflow steps."""
        # Build adjacency list
        graph = {step.name: step.depends_on for step in steps}

        # DFS to detect cycles
        visited = set()
        rec_stack = set()

        def has_cycle(node):
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for step_name in graph:
            if step_name not in visited:
                if has_cycle(step_name):
                    return True

        return False


class WorkflowTemplateEngine:
    """
    Main workflow template engine for loading, validating, and instantiating templates.

    Features:
    - YAML-based template definitions
    - Parameter substitution with validation
    - Template inheritance support
    - Custom template creation
    - Version control for templates
    """

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize the workflow template engine.

        Args:
            template_dir: Directory containing template files
        """
        self.template_dir = (
            Path(template_dir) if template_dir else self._get_default_template_dir()
        )
        self.templates: Dict[str, WorkflowTemplate] = {}
        self.validator = TemplateValidator()

        # Load templates
        self.load_templates()

        logger.info(f"Template engine initialized with {len(self.templates)} templates")

    def _get_default_template_dir(self) -> Path:
        """Get the default template directory."""
        env_dir = os.getenv("BR_TEMPLATE_DIR") or os.getenv(
            "BRAIN_RESEARCHER_TEMPLATE_DIR"
        )
        if env_dir:
            return Path(env_dir)

        # Prefer config-managed templates at the repo level
        current_dir = Path(__file__).resolve().parent
        repo_root = current_dir.parents[3]
        config_dir = repo_root / "configs" / "workflow_templates"

        possible_dirs = [
            config_dir,
            current_dir / "templates",
            current_dir.parent / "templates",
            current_dir.parents[2] / "templates",
        ]

        for dir_path in possible_dirs:
            if dir_path.exists():
                return dir_path

        # Create default directory if none found
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    def load_templates(self):
        """Load all templates from the template directory."""
        if not self.template_dir.exists():
            logger.warning(f"Template directory does not exist: {self.template_dir}")
            return

        template_files = list(self.template_dir.glob("*.yaml")) + list(
            self.template_dir.glob("*.yml")
        )

        for template_file in template_files:
            try:
                templates = self._load_template_file(template_file)
                for template in templates:
                    self.templates[template.id] = template
                    logger.debug(f"Loaded template: {template.id}")
            except Exception as e:
                logger.error(f"Failed to load template {template_file}: {e}")

        # Resolve inheritance after all templates are loaded
        self._resolve_inheritance()

    def _load_template_file(self, file_path: Path) -> List[WorkflowTemplate]:
        """Load a single template file."""
        with open(file_path, "r", encoding="utf-8") as f:
            template_data = yaml.safe_load(f)

        templates: List[WorkflowTemplate] = []
        if template_data is None:
            return templates

        if isinstance(template_data, dict):
            if "templates" in template_data and isinstance(
                template_data["templates"], dict
            ):
                for template_id, data in template_data["templates"].items():
                    if isinstance(data, dict) and "id" not in data:
                        data = {**data, "id": template_id}
                    template = self._parse_template_data(data)
                    if template:
                        templates.append(template)
            elif {"id", "name", "steps"}.issubset(template_data.keys()):
                template = self._parse_template_data(template_data)
                if template:
                    templates.append(template)
            else:
                logger.debug("Skipping non-template yaml: %s", file_path)
        else:
            logger.debug("Skipping non-dict yaml: %s", file_path)

        return templates

    def _parse_template_data(self, data: Dict[str, Any]) -> Optional[WorkflowTemplate]:
        """Parse template data from YAML into WorkflowTemplate object."""
        try:
            # Parse parameters
            parameters = []
            for param_data in data.get("parameters", []):
                param = TemplateParameter(
                    name=param_data["name"],
                    type=ParameterType(param_data["type"]),
                    description=param_data.get("description", ""),
                    required=param_data.get("required", False),
                    default=param_data.get("default"),
                    choices=param_data.get("choices"),
                    min_value=param_data.get("min_value"),
                    max_value=param_data.get("max_value"),
                    pattern=param_data.get("pattern"),
                    validation_rules=param_data.get("validation_rules", []),
                )
                parameters.append(param)

            # Parse steps
            steps = []
            for step_data in data.get("steps", []):
                step = WorkflowStep(
                    name=step_data["name"],
                    tool=step_data["tool"],
                    description=step_data.get("description", ""),
                    parameters=step_data.get("parameters", {}),
                    depends_on=step_data.get("depends_on", []),
                    optional=step_data.get("optional", False),
                    timeout_seconds=step_data.get("timeout_seconds"),
                    retry_count=step_data.get("retry_count", 0),
                    conditions=step_data.get("conditions", []),
                )
                steps.append(step)

            # Parse metadata
            created_str = data.get("created_at", datetime.now().isoformat())
            if isinstance(created_str, str):
                created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            else:
                created_at = created_str

            template = WorkflowTemplate(
                id=data["id"],
                name=data["name"],
                description=data.get("description", ""),
                version=data.get("version", "1.0.0"),
                category=data.get("category", "general"),
                author=data.get("author", "unknown"),
                created_at=created_at,
                status=TemplateStatus(data.get("status", "active")),
                tags=data.get("tags", []),
                parameters=parameters,
                steps=steps,
                outputs=data.get("outputs", {}),
                metadata=data.get("metadata", {}),
                inherits_from=data.get("inherits_from"),
            )

            return template

        except Exception as e:
            logger.error(f"Failed to parse template data: {e}")
            return None

    def _resolve_inheritance(self):
        """Resolve template inheritance relationships."""
        for template_id, template in self.templates.items():
            if template.inherits_from:
                parent = self.templates.get(template.inherits_from)
                if parent:
                    self._inherit_from_parent(template, parent)
                else:
                    logger.warning(
                        f"Template {template_id} inherits from unknown template: {template.inherits_from}"
                    )

    def _inherit_from_parent(self, child: WorkflowTemplate, parent: WorkflowTemplate):
        """Apply inheritance from parent template to child."""
        # Inherit parameters (child overrides parent)
        parent_param_names = {p.name for p in parent.parameters}
        child_param_names = {p.name for p in child.parameters}

        for param in parent.parameters:
            if param.name not in child_param_names:
                child.parameters.append(param)

        # Inherit steps (child can override by name)
        parent_step_names = {s.name for s in parent.steps}
        child_step_names = {s.name for s in child.steps}

        for step in parent.steps:
            if step.name not in child_step_names:
                child.steps.append(step)

        # Inherit outputs (child overrides parent)
        inherited_outputs = parent.outputs.copy()
        inherited_outputs.update(child.outputs)
        child.outputs = inherited_outputs

    def instantiate(
        self, template_id: str, parameters: Dict[str, Any], validate_only: bool = False
    ) -> Union[Dict[str, Any], List[str]]:
        """
        Instantiate a workflow template with given parameters.

        Args:
            template_id: ID of the template to instantiate
            parameters: Parameter values for substitution
            validate_only: If True, only validate parameters without instantiation

        Returns:
            Instantiated workflow dict or list of validation errors
        """
        if template_id not in self.templates:
            return [f"Template not found: {template_id}"]

        template = self.templates[template_id]

        # Validate template structure
        validation_issues = self.validator.validate_template(template)
        if validation_issues:
            return validation_issues

        # Validate parameters
        param_errors = template.validate_parameters(parameters)
        if param_errors:
            return param_errors

        if validate_only:
            return []  # No errors

        # Apply default values
        final_parameters = self._apply_defaults(template, parameters)

        # Substitute parameters in steps
        instantiated_steps = self._substitute_parameters(
            template.steps, final_parameters
        )

        # Create instantiated workflow
        workflow = {
            "template_id": template_id,
            "template_name": template.name,
            "template_version": template.version,
            "parameters": final_parameters,
            "steps": instantiated_steps,
            "outputs": template.outputs,
            "metadata": {
                **template.metadata,
                "instantiated_at": datetime.now().isoformat(),
                "parameter_count": len(final_parameters),
            },
        }

        logger.info(
            f"Instantiated template {template_id} with {len(instantiated_steps)} steps"
        )

        return workflow

    def _apply_defaults(
        self, template: WorkflowTemplate, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply default values to missing parameters."""
        final_params = parameters.copy()

        for param in template.parameters:
            if param.name not in final_params and param.default is not None:
                final_params[param.name] = param.default

        return final_params

    def _substitute_parameters(
        self, steps: List[WorkflowStep], parameters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Substitute parameters in workflow steps."""
        substituted_steps = []

        for step in steps:
            # Convert step to dict for substitution
            step_dict = {
                "name": step.name,
                "tool": step.tool,
                "description": step.description,
                "parameters": step.parameters.copy(),
                "depends_on": step.depends_on.copy(),
                "optional": step.optional,
                "timeout_seconds": step.timeout_seconds,
                "retry_count": step.retry_count,
                "conditions": step.conditions.copy(),
            }

            # Perform parameter substitution
            step_dict = self._substitute_dict(step_dict, parameters)

            substituted_steps.append(step_dict)

        return substituted_steps

    def _substitute_dict(self, obj: Any, parameters: Dict[str, Any]) -> Any:
        """Recursively substitute parameters in nested dictionaries."""
        if isinstance(obj, dict):
            return {
                key: self._substitute_dict(value, parameters)
                for key, value in obj.items()
            }
        elif isinstance(obj, list):
            return [self._substitute_dict(item, parameters) for item in obj]
        elif isinstance(obj, str):
            return self._substitute_string(obj, parameters)
        else:
            return obj

    def _substitute_string(self, text: str, parameters: Dict[str, Any]) -> str:
        """Substitute parameters in a string using ${param_name} syntax."""

        def replace_param(match):
            param_name = match.group(1)
            if param_name in parameters:
                return str(parameters[param_name])
            else:
                logger.warning(f"Parameter not found for substitution: {param_name}")
                return match.group(0)  # Return original text

        # Replace ${param_name} patterns
        return re.sub(r"\$\{([^}]+)\}", replace_param, text)

    def get_template(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Get a template by ID."""
        return self.templates.get(template_id)

    def list_templates(
        self,
        category: Optional[str] = None,
        status: Optional[TemplateStatus] = None,
        tags: Optional[List[str]] = None,
    ) -> List[WorkflowTemplate]:
        """
        List templates with optional filtering.

        Args:
            category: Filter by category
            status: Filter by status
            tags: Filter by tags (must have all specified tags)

        Returns:
            List of matching templates
        """
        filtered_templates = []

        for template in self.templates.values():
            # Category filter
            if category and template.category != category:
                continue

            # Status filter
            if status and template.status != status:
                continue

            # Tags filter
            if tags:
                if not all(tag in template.tags for tag in tags):
                    continue

            filtered_templates.append(template)

        # Sort by name
        filtered_templates.sort(key=lambda t: t.name)

        return filtered_templates

    def create_custom_template(
        self, template_data: Dict[str, Any], save_to_file: bool = True
    ) -> Union[WorkflowTemplate, List[str]]:
        """
        Create a new custom template.

        Args:
            template_data: Template data in YAML format
            save_to_file: Whether to save the template to file

        Returns:
            Created template or list of validation errors
        """
        template = self._parse_template_data(template_data)
        if not template:
            return ["Failed to parse template data"]

        # Validate template
        validation_issues = self.validator.validate_template(template)
        if validation_issues:
            return validation_issues

        # Check for ID conflicts
        if template.id in self.templates:
            return [f"Template ID already exists: {template.id}"]

        # Add to templates
        self.templates[template.id] = template

        # Save to file if requested
        if save_to_file:
            try:
                self._save_template_to_file(template, template_data)
            except Exception as e:
                logger.error(f"Failed to save template to file: {e}")

        logger.info(f"Created custom template: {template.id}")

        return template

    def _save_template_to_file(
        self, template: WorkflowTemplate, original_data: Dict[str, Any]
    ):
        """Save template to YAML file."""
        file_path = self.template_dir / f"{template.id}.yaml"

        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(original_data, f, default_flow_style=False, sort_keys=False)

    def get_template_categories(self) -> List[str]:
        """Get list of all template categories."""
        categories = set()
        for template in self.templates.values():
            categories.add(template.category)
        return sorted(list(categories))

    def get_template_tags(self) -> List[str]:
        """Get list of all template tags."""
        tags = set()
        for template in self.templates.values():
            tags.update(template.tags)
        return sorted(list(tags))


class TemplateValidationError(Exception):
    """Raised when a template or its parameters are invalid."""


class ExecutionError(Exception):
    """Raised when template execution fails."""


@dataclass
class ExecutionContext:
    """Execution context shared across steps."""

    parameters: Dict[str, Any]
    data: Dict[str, Any] = field(default_factory=dict)

    def update(self, payload: Dict[str, Any]) -> None:
        for key, value in payload.items():
            if key == "status":
                continue
            self.data[key] = value

    def as_dict(self) -> Dict[str, Any]:
        return {**self.parameters, **self.data}


@dataclass
class ExecutionStep:
    """Execution result for a single step."""

    step_name: str
    status: str
    start_time: float
    end_time: float
    error_message: str | None = None
    result: Any | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


@dataclass
class ExecutionResult:
    """Aggregated execution result for a template run."""

    template_name: str
    status: str
    step_results: List[ExecutionStep]
    execution_context: Dict[str, Any]
    error_message: Optional[str] = None
    total_duration: float = 0.0
    step_count: int = 0
    parallel_step_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    resource_usage: Optional[Dict[str, Any]] = None
    resource_metrics: Optional[Dict[str, Any]] = None


class WorkflowExecutor:
    """Execute workflow templates with dependency resolution and parallel steps."""

    def __init__(
        self,
        template_engine: WorkflowTemplateEngine,
        tool_registry: Any,
        max_parallel_steps: int = 4,
        step_timeout: float = 30.0,
    ) -> None:
        self.template_engine = template_engine
        self.tool_registry = tool_registry
        self.max_parallel_steps = max_parallel_steps
        self.step_timeout = step_timeout
        self.enable_resource_monitoring = False
        self.collect_resource_metrics = False
        self.run_sync_in_executor = False

    async def execute_template(
        self,
        template_name: str,
        params: Dict[str, Any],
    ) -> ExecutionResult:
        template = self.template_engine.templates.get(template_name)
        if template is None:
            template = self._build_builtin_template(template_name)
        if template is None:
            raise TemplateValidationError(f"Template '{template_name}' not found")

        errors = template.validate_parameters(params)
        if errors:
            raise TemplateValidationError("; ".join(errors))

        execution_start = time.time()
        cpu_start = time.process_time()
        execution_context = ExecutionContext(parameters=params.copy())
        step_results: List[ExecutionStep] = []
        step_status: Dict[str, str] = {}

        ordered_steps = self._topological_sort(template.steps)
        overall_status = "success"
        error_message: Optional[str] = None

        for step in ordered_steps:
            if not self._conditions_met(step, execution_context):
                step_status[step.name] = "skipped"
                continue

            failed_deps = [
                dep for dep in step.depends_on if step_status.get(dep) == "failed"
            ]
            if failed_deps:
                step_results.append(
                    ExecutionStep(
                        step_name=step.name,
                        status="skipped",
                        start_time=time.time(),
                        end_time=time.time(),
                        error_message=f"Dependencies failed: {failed_deps}",
                    )
                )
                step_status[step.name] = "skipped"
                continue

            kwargs = self._resolve_step_parameters(step, execution_context)

            if isinstance(kwargs.get("input_data"), list) and self._is_parallel_step(
                step.name
            ):
                subject_results, subject_status = await self._execute_parallel_subjects(
                    step, kwargs
                )
                step_results.extend(subject_results)
                step_status[step.name] = subject_status
                if subject_status == "failed":
                    overall_status = "failed"
                elif (
                    subject_status == "partial_success" and overall_status == "success"
                ):
                    overall_status = "partial_success"
                continue

            start = time.time()
            try:
                result = await self._run_tool(step, kwargs)
                execution_context.update(result if isinstance(result, dict) else {})
                end = time.time()
                step_results.append(
                    ExecutionStep(
                        step_name=step.name,
                        status="success",
                        start_time=start,
                        end_time=end,
                        result=result,
                    )
                )
                step_status[step.name] = "success"
            except asyncio.TimeoutError:
                end = time.time()
                step_results.append(
                    ExecutionStep(
                        step_name=step.name,
                        status="failed",
                        start_time=start,
                        end_time=end,
                        error_message="Step timeout",
                    )
                )
                step_status[step.name] = "failed"
                overall_status = "failed"
                error_message = "Execution timed out"
                break
            except Exception as exc:
                end = time.time()
                step_results.append(
                    ExecutionStep(
                        step_name=step.name,
                        status="failed",
                        start_time=start,
                        end_time=end,
                        error_message=str(exc),
                    )
                )
                step_status[step.name] = "failed"
                overall_status = "failed"
                error_message = str(exc)
                break

        total_duration = time.time() - execution_start
        step_count = len(step_results)
        success_count = sum(1 for step in step_results if step.status == "success")
        failure_count = sum(1 for step in step_results if step.status == "failed")
        parallel_step_count = sum(
            1
            for step in step_results
            if any(
                token in step.step_name
                for token in ["subject_analysis", "within_subject"]
            )
        )
        success_rate = (
            success_count / (success_count + failure_count)
            if (success_count + failure_count) > 0
            else 0.0
        )

        resource_usage = None
        resource_metrics = None
        if self.enable_resource_monitoring:
            resource_usage = self._collect_resource_usage(
                execution_start, total_duration, cpu_start
            )
        if self.collect_resource_metrics:
            resource_metrics = self._collect_resource_metrics(
                execution_start, total_duration, cpu_start
            )

        return ExecutionResult(
            template_name=template_name,
            status=overall_status,
            step_results=step_results,
            execution_context=execution_context.as_dict(),
            error_message=error_message,
            total_duration=total_duration,
            step_count=step_count,
            parallel_step_count=parallel_step_count,
            success_count=success_count,
            failure_count=failure_count,
            success_rate=success_rate,
            resource_usage=resource_usage,
            resource_metrics=resource_metrics,
        )

    async def _execute_parallel_subjects(
        self, step: WorkflowStep, kwargs: Dict[str, Any]
    ) -> Tuple[List[ExecutionStep], str]:
        subjects = kwargs.get("input_data", [])
        semaphore = asyncio.Semaphore(self.max_parallel_steps)
        results: List[ExecutionStep] = []

        async def _run_for_subject(idx: int, subject_item: Any) -> ExecutionStep:
            async with semaphore:
                subject_kwargs = {**kwargs, "input_data": subject_item}
                start = time.time()
                try:
                    result = await self._run_tool(step, subject_kwargs)
                    end = time.time()
                    return ExecutionStep(
                        step_name=f"{step.name}_{idx}",
                        status="success",
                        start_time=start,
                        end_time=end,
                        result=result,
                    )
                except asyncio.TimeoutError:
                    end = time.time()
                    return ExecutionStep(
                        step_name=f"{step.name}_{idx}",
                        status="failed",
                        start_time=start,
                        end_time=end,
                        error_message="Step timeout",
                    )
                except Exception as exc:
                    end = time.time()
                    return ExecutionStep(
                        step_name=f"{step.name}_{idx}",
                        status="failed",
                        start_time=start,
                        end_time=end,
                        error_message=str(exc),
                    )

        tasks = [
            asyncio.create_task(_run_for_subject(i, item))
            for i, item in enumerate(subjects)
        ]
        if tasks:
            results = await asyncio.gather(*tasks)

        successes = sum(1 for step in results if step.status == "success")
        failures = len(results) - successes
        if failures and successes:
            status = "partial_success"
        elif failures:
            status = "failed"
        else:
            status = "success"

        return results, status

    async def _run_tool(self, step: WorkflowStep, kwargs: Dict[str, Any]) -> Any:
        tool = self.tool_registry.get_tool(step.tool)
        timeout = step.timeout_seconds or self.step_timeout

        if asyncio.iscoroutinefunction(tool):
            return await asyncio.wait_for(tool(**kwargs), timeout=timeout)

        if callable(tool):
            if self.run_sync_in_executor:
                return await asyncio.wait_for(
                    asyncio.to_thread(tool, **kwargs), timeout=timeout
                )
            return tool(**kwargs)

        raise ExecutionError(f"Tool '{step.tool}' is not callable")

    def _topological_sort(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        ordered: List[WorkflowStep] = []
        resolved: Set[str] = set()
        remaining = steps[:]

        while remaining:
            progressed = False
            for step in list(remaining):
                if all(dep in resolved for dep in step.depends_on):
                    ordered.append(step)
                    resolved.add(step.name)
                    remaining.remove(step)
                    progressed = True
            if not progressed:
                ordered.extend(remaining)
                break
        return ordered

    def _conditions_met(self, step: WorkflowStep, context: ExecutionContext) -> bool:
        if not step.conditions:
            return True
        locals_map = context.as_dict()
        for condition in step.conditions:
            expr = condition.replace("true", "True").replace("false", "False")
            try:
                if not eval(expr, {"__builtins__": {}}, locals_map):
                    return False
            except Exception:
                return False
        return True

    def _resolve_step_parameters(
        self, step: WorkflowStep, context: ExecutionContext
    ) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for key, value in step.parameters.items():
            resolved[key] = self._resolve_value(value, context)
        merged = {**context.as_dict(), **resolved}
        if isinstance(context.parameters.get("input_data"), dict):
            data_map = context.parameters["input_data"]
            if "rest" in step.name and "rest" in data_map:
                merged["input_data"] = data_map["rest"]
            if "task" in step.name and "task" in data_map:
                merged["input_data"] = data_map["task"]

        if isinstance(merged.get("input_data"), list) and not self._is_parallel_step(
            step.name
        ):
            merged["input_data"] = (
                merged["input_data"][0]
                if merged["input_data"]
                else merged["input_data"]
            )
        return merged

    def _resolve_value(self, value: Any, context: ExecutionContext) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            key = value[2:-1]
            return context.as_dict().get(key)
        return value

    def _is_parallel_step(self, step_name: str) -> bool:
        return any(
            token in step_name for token in ["subject_analysis", "within_subject"]
        )

    def _build_builtin_template(self, template_name: str) -> Optional[WorkflowTemplate]:
        if template_name == "fmri_analysis":
            return WorkflowTemplate(
                id="fmri_analysis",
                name="fMRI Analysis",
                description="Basic fMRI analysis workflow",
                version="1.0.0",
                category="neuroimaging",
                author="system",
                created_at=datetime.utcnow(),
                steps=[
                    WorkflowStep(
                        name="load_data", tool="load_data", description="Load data"
                    ),
                    WorkflowStep(
                        name="motion_correction",
                        tool="preprocess_fmri",
                        description="Optional motion correction",
                        depends_on=["load_data"],
                        conditions=["motion_correction == True"],
                    ),
                    WorkflowStep(
                        name="preprocessing",
                        tool="preprocess_fmri",
                        description="Preprocess data",
                        depends_on=["load_data"],
                    ),
                    WorkflowStep(
                        name="compute_glm",
                        tool="compute_glm",
                        description="Compute GLM",
                        depends_on=["preprocessing"],
                    ),
                    WorkflowStep(
                        name="save_results",
                        tool="save_results",
                        description="Save results",
                        depends_on=["compute_glm"],
                    ),
                ],
            )
        if template_name == "connectivity_analysis":
            base = self._build_builtin_template("fmri_analysis")
            if base is None:
                return None
            base.id = "connectivity_analysis"
            base.name = "Connectivity Analysis"
            base.steps.append(
                WorkflowStep(
                    name="compute_connectivity",
                    tool="compute_connectivity",
                    description="Compute connectivity",
                    depends_on=["preprocessing"],
                )
            )
            return base
        if template_name == "group_analysis":
            return WorkflowTemplate(
                id="group_analysis",
                name="Group Analysis",
                description="Group-level analysis with subject parallelism",
                version="1.0.0",
                category="neuroimaging",
                author="system",
                created_at=datetime.utcnow(),
                steps=[
                    WorkflowStep(
                        name="preparation",
                        tool="preprocess_fmri",
                        description="Prepare data",
                    ),
                    WorkflowStep(
                        name="subject_analysis",
                        tool="compute_glm",
                        description="Per-subject analysis",
                        depends_on=["preparation"],
                        parameters={"input_data": "${input_data}"},
                    ),
                    WorkflowStep(
                        name="group_statistics",
                        tool="group_analysis",
                        description="Group statistics",
                        depends_on=["subject_analysis"],
                    ),
                ],
            )
        if template_name == "multi_task_connectivity":
            return WorkflowTemplate(
                id="multi_task_connectivity",
                name="Multi-task Connectivity",
                description="Connectivity across rest and task",
                version="1.0.0",
                category="neuroimaging",
                author="system",
                created_at=datetime.utcnow(),
                steps=[
                    WorkflowStep(
                        name="rest_preparation",
                        tool="preprocess_fmri",
                        description="Prepare rest",
                    ),
                    WorkflowStep(
                        name="rest_subject_analysis",
                        tool="compute_connectivity",
                        description="Rest connectivity",
                        depends_on=["rest_preparation"],
                        parameters={"input_data": "${rest_data}"},
                    ),
                    WorkflowStep(
                        name="task_preparation",
                        tool="preprocess_fmri",
                        description="Prepare task",
                    ),
                    WorkflowStep(
                        name="task_subject_analysis",
                        tool="compute_connectivity",
                        description="Task connectivity",
                        depends_on=["task_preparation"],
                        parameters={"input_data": "${task_data}"},
                    ),
                    WorkflowStep(
                        name="comparison",
                        tool="compute_connectivity",
                        description="Compare rest/task",
                        depends_on=["rest_subject_analysis", "task_subject_analysis"],
                    ),
                ],
            )
        if template_name == "longitudinal_analysis":
            return WorkflowTemplate(
                id="longitudinal_analysis",
                name="Longitudinal Analysis",
                description="Within-subject longitudinal analysis",
                version="1.0.0",
                category="neuroimaging",
                author="system",
                created_at=datetime.utcnow(),
                steps=[
                    WorkflowStep(
                        name="baseline_preparation",
                        tool="preprocess_fmri",
                        description="Baseline prep",
                    ),
                    WorkflowStep(
                        name="within_subject_analysis",
                        tool="compute_glm",
                        description="Within-subject analysis",
                        depends_on=["baseline_preparation"],
                        parameters={"input_data": "${baseline_data}"},
                    ),
                    WorkflowStep(
                        name="change_analysis",
                        tool="group_analysis",
                        description="Change analysis",
                        depends_on=["within_subject_analysis"],
                    ),
                ],
            )
        return None

    def _collect_resource_usage(
        self, execution_start: float, total_duration: float, cpu_start: float
    ) -> Dict[str, Any]:
        peak_memory_mb = self._get_peak_memory_mb()
        cpu_percent = self._estimate_cpu_percent(cpu_start, total_duration)
        return {
            "peak_memory_mb": max(peak_memory_mb, 0.1),
            "avg_cpu_percent": cpu_percent,
            "execution_duration_seconds": total_duration,
        }

    def _collect_resource_metrics(
        self, execution_start: float, total_duration: float, cpu_start: float
    ) -> Dict[str, Any]:
        peak_memory_mb = self._get_peak_memory_mb()
        avg_memory_mb = peak_memory_mb
        cpu_percent = self._estimate_cpu_percent(cpu_start, total_duration)
        return {
            "peak_memory_usage_mb": peak_memory_mb,
            "avg_memory_usage_mb": avg_memory_mb,
            "peak_cpu_percent": cpu_percent,
            "avg_cpu_percent": cpu_percent,
            "disk_io_read_mb": 0.0,
            "disk_io_write_mb": 0.0,
            "network_io_mb": 0.0,
        }

    def _get_peak_memory_mb(self) -> float:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # ru_maxrss is KB on Linux, bytes on macOS; normalize to MB.
            if usage > 10**7:
                return usage / (1024 * 1024)
            return usage / 1024
        except Exception:
            return 0.1

    def _estimate_cpu_percent(self, cpu_start: float, total_duration: float) -> float:
        if total_duration <= 0:
            return 0.0
        cpu_time = time.process_time() - cpu_start
        return max(0.0, min(100.0, (cpu_time / total_duration) * 100.0))


# Factory function
def create_template_engine(
    template_dir: Optional[str] = None,
) -> WorkflowTemplateEngine:
    """
    Create a workflow template engine instance.

    Args:
        template_dir: Directory containing template files

    Returns:
        Configured template engine
    """
    return WorkflowTemplateEngine(template_dir)
