"""
Tool Composition Pipelines for Complex Neuroimaging Workflows

This module implements intelligent workflow composition capabilities that can
automatically chain tools together to accomplish complex neuroimaging analysis tasks.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import uuid4

import networkx as nx

from brain_researcher.services.tools.enhanced_registry import EnhancedToolRegistry
from brain_researcher.services.tools.tool_base import BRKGToolWrapper
from brain_researcher.services.agent.evidence_collection import EvidenceCollector, EvidenceType
from brain_researcher.services.agent.dependency_resolver import DependencyResolver, ExecutionGraph

logger = logging.getLogger(__name__)


class WorkflowPattern(Enum):
    """Common neuroimaging workflow patterns."""
    PREPROCESSING_TO_ANALYSIS = "preprocessing_to_analysis"
    TASK_ACTIVATION_ANALYSIS = "task_activation_analysis"
    CONNECTIVITY_ANALYSIS = "connectivity_analysis"
    GROUP_COMPARISON = "group_comparison"
    META_ANALYSIS = "meta_analysis"
    MULTIMODAL_FUSION = "multimodal_fusion"
    LONGITUDINAL_ANALYSIS = "longitudinal_analysis"
    QUALITY_CONTROL_PIPELINE = "quality_control_pipeline"


class DataFlowType(Enum):
    """Types of data flow between tools."""
    NIFTI_IMAGE = "nifti_image"
    STATISTICAL_MAP = "statistical_map"
    COORDINATES = "coordinates"
    CONNECTIVITY_MATRIX = "connectivity_matrix"
    TIMESERIES = "timeseries"
    METADATA = "metadata"
    RESULTS_TABLE = "results_table"
    QUALITY_METRICS = "quality_metrics"


@dataclass
class WorkflowStep:
    """Individual step in a workflow pipeline."""
    step_id: str
    tool_name: str
    tool: BRKGToolWrapper
    parameters: Dict[str, Any] = field(default_factory=dict)
    input_requirements: List[DataFlowType] = field(default_factory=list)
    output_types: List[DataFlowType] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    optional: bool = False
    estimated_duration: float = 60.0
    resource_requirements: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowPipeline:
    """Complete workflow pipeline definition."""
    pipeline_id: str
    name: str
    description: str
    pattern: WorkflowPattern
    steps: List[WorkflowStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: WorkflowStep):
        """Add a step to the pipeline."""
        self.steps.append(step)

    def get_step_by_id(self, step_id: str) -> Optional[WorkflowStep]:
        """Get a step by its ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_total_estimated_duration(self) -> float:
        """Get total estimated duration for the pipeline."""
        return sum(step.estimated_duration for step in self.steps)


@dataclass
class WorkflowExecution:
    """Workflow execution state and results."""
    execution_id: str
    pipeline: WorkflowPipeline
    status: str = "pending"
    current_step: Optional[str] = None
    completed_steps: Set[str] = field(default_factory=set)
    failed_steps: Set[str] = field(default_factory=set)
    step_results: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error_message: Optional[str] = None


class WorkflowComposer:
    """Intelligent workflow composer that creates pipelines from user intents."""

    def __init__(self, tool_registry: EnhancedToolRegistry):
        """Initialize workflow composer."""
        self.tool_registry = tool_registry
        self.workflow_patterns: Dict[WorkflowPattern, Dict[str, Any]] = {}
        self.dependency_resolver = DependencyResolver()

        # Initialize common workflow patterns
        self._initialize_workflow_patterns()

        logger.info("Workflow composer initialized")

    def _initialize_workflow_patterns(self):
        """Initialize common neuroimaging workflow patterns."""

        # Preprocessing to Analysis Pattern
        self.workflow_patterns[WorkflowPattern.PREPROCESSING_TO_ANALYSIS] = {
            "description": "Complete preprocessing and statistical analysis pipeline",
            "required_tools": ["fmriprep", "glm_analysis"],
            "optional_tools": ["quality_control", "visualization"],
            "data_flow": [
                (DataFlowType.NIFTI_IMAGE, DataFlowType.NIFTI_IMAGE),
                (DataFlowType.NIFTI_IMAGE, DataFlowType.STATISTICAL_MAP),
                (DataFlowType.STATISTICAL_MAP, DataFlowType.RESULTS_TABLE)
            ]
        }

        # Task Activation Analysis Pattern
        self.workflow_patterns[WorkflowPattern.TASK_ACTIVATION_ANALYSIS] = {
            "description": "Task-based fMRI activation analysis",
            "required_tools": ["glm_analysis", "coordinate_to_concept"],
            "optional_tools": ["contrast_analysis", "multiple_comparison"],
            "data_flow": [
                (DataFlowType.NIFTI_IMAGE, DataFlowType.STATISTICAL_MAP),
                (DataFlowType.STATISTICAL_MAP, DataFlowType.COORDINATES),
                (DataFlowType.COORDINATES, DataFlowType.METADATA)
            ]
        }

        # Connectivity Analysis Pattern
        self.workflow_patterns[WorkflowPattern.CONNECTIVITY_ANALYSIS] = {
            "description": "Functional connectivity analysis pipeline",
            "required_tools": ["connectivity", "network_analysis"],
            "optional_tools": ["graph_theory", "visualization"],
            "data_flow": [
                (DataFlowType.NIFTI_IMAGE, DataFlowType.TIMESERIES),
                (DataFlowType.TIMESERIES, DataFlowType.CONNECTIVITY_MATRIX),
                (DataFlowType.CONNECTIVITY_MATRIX, DataFlowType.RESULTS_TABLE)
            ]
        }

        # Group Comparison Pattern
        self.workflow_patterns[WorkflowPattern.GROUP_COMPARISON] = {
            "description": "Between-group statistical comparison",
            "required_tools": ["group_analysis", "statistical_inference"],
            "optional_tools": ["effect_size", "visualization"],
            "data_flow": [
                (DataFlowType.STATISTICAL_MAP, DataFlowType.STATISTICAL_MAP),
                (DataFlowType.STATISTICAL_MAP, DataFlowType.RESULTS_TABLE)
            ]
        }

        # Meta-Analysis Pattern
        self.workflow_patterns[WorkflowPattern.META_ANALYSIS] = {
            "description": "Coordinate-based meta-analysis",
            "required_tools": ["coordinate_meta_analysis", "literature_search"],
            "optional_tools": ["heterogeneity_analysis", "sensitivity_analysis"],
            "data_flow": [
                (DataFlowType.COORDINATES, DataFlowType.STATISTICAL_MAP),
                (DataFlowType.METADATA, DataFlowType.RESULTS_TABLE)
            ]
        }

    def compose_workflow(
        self,
        intent: str,
        context: Dict[str, Any] = None,
        user_preferences: Dict[str, Any] = None,
        pattern: Optional[WorkflowPattern] = None
    ) -> WorkflowPipeline:
        """
        Compose a workflow pipeline based on user intent.

        Args:
            intent: Natural language description of desired analysis
            context: Analysis context (data types, constraints, etc.)
            user_preferences: User-specific preferences
            pattern: Optional specific workflow pattern to use

        Returns:
            Composed workflow pipeline
        """
        context = context or {}
        user_preferences = user_preferences or {}

        # Detect workflow pattern if not specified
        if pattern is None:
            pattern = self._detect_workflow_pattern(intent, context)

        # Get tool recommendations for the intent
        tool_recommendations = self.tool_registry.get_intelligent_recommendations(
            query=intent,
            context=context,
            user_preferences=user_preferences,
            max_recommendations=10
        )

        # Create pipeline based on pattern and recommendations
        pipeline = self._create_pipeline_from_pattern(
            pattern=pattern,
            intent=intent,
            tool_recommendations=tool_recommendations,
            context=context
        )

        # Optimize pipeline structure
        pipeline = self._optimize_pipeline(pipeline, context)

        logger.info(f"Composed workflow pipeline with {len(pipeline.steps)} steps")
        return pipeline

    def _detect_workflow_pattern(self, intent: str, context: Dict[str, Any]) -> WorkflowPattern:
        """Detect the most appropriate workflow pattern for the intent."""
        intent_lower = intent.lower()

        # Pattern detection based on keywords
        if any(word in intent_lower for word in ['preprocess', 'prepare', 'clean']):
            return WorkflowPattern.PREPROCESSING_TO_ANALYSIS

        elif any(word in intent_lower for word in ['task', 'activation', 'contrast']):
            return WorkflowPattern.TASK_ACTIVATION_ANALYSIS

        elif any(word in intent_lower for word in ['connectivity', 'network', 'functional']):
            return WorkflowPattern.CONNECTIVITY_ANALYSIS

        elif any(word in intent_lower for word in ['group', 'compare', 'difference']):
            return WorkflowPattern.GROUP_COMPARISON

        elif any(word in intent_lower for word in ['meta', 'literature', 'coordinate']):
            return WorkflowPattern.META_ANALYSIS

        elif any(word in intent_lower for word in ['multimodal', 'fusion', 'combine']):
            return WorkflowPattern.MULTIMODAL_FUSION

        elif any(word in intent_lower for word in ['longitudinal', 'time', 'change']):
            return WorkflowPattern.LONGITUDINAL_ANALYSIS

        elif any(word in intent_lower for word in ['quality', 'qc', 'check']):
            return WorkflowPattern.QUALITY_CONTROL_PIPELINE

        # Default to preprocessing-to-analysis
        return WorkflowPattern.PREPROCESSING_TO_ANALYSIS

    def _create_pipeline_from_pattern(
        self,
        pattern: WorkflowPattern,
        intent: str,
        tool_recommendations: List,
        context: Dict[str, Any]
    ) -> WorkflowPipeline:
        """Create pipeline based on workflow pattern and tool recommendations."""
        pattern_config = self.workflow_patterns.get(pattern, {})

        pipeline = WorkflowPipeline(
            pipeline_id=f"pipeline_{uuid4().hex[:8]}",
            name=f"{pattern.value} Pipeline",
            description=pattern_config.get("description", "Custom workflow pipeline"),
            pattern=pattern
        )

        # Map recommended tools to workflow steps
        required_tools = pattern_config.get("required_tools", [])
        optional_tools = pattern_config.get("optional_tools", [])

        step_counter = 1
        added_tools = set()

        # Add required tools first
        for required_tool in required_tools:
            matching_recommendation = self._find_matching_recommendation(
                required_tool, tool_recommendations
            )

            if matching_recommendation:
                step = self._create_workflow_step(
                    step_counter, matching_recommendation, context, required=True
                )
                pipeline.add_step(step)
                added_tools.add(matching_recommendation.tool.get_tool_name())
                step_counter += 1

        # Add highly recommended tools that weren't already added
        for recommendation in tool_recommendations:
            tool_name = recommendation.tool.get_tool_name()
            if (tool_name not in added_tools and
                recommendation.confidence_score > 0.7 and
                step_counter <= 8):  # Limit pipeline length

                step = self._create_workflow_step(
                    step_counter, recommendation, context, required=False
                )
                pipeline.add_step(step)
                added_tools.add(tool_name)
                step_counter += 1

        # Add optional tools if they match and we have space
        for optional_tool in optional_tools:
            if step_counter > 10:  # Hard limit on pipeline length
                break

            matching_recommendation = self._find_matching_recommendation(
                optional_tool, tool_recommendations
            )

            if (matching_recommendation and
                matching_recommendation.tool.get_tool_name() not in added_tools):
                step = self._create_workflow_step(
                    step_counter, matching_recommendation, context, required=False
                )
                step.optional = True
                pipeline.add_step(step)
                added_tools.add(matching_recommendation.tool.get_tool_name())
                step_counter += 1

        # Set up dependencies based on data flow
        self._setup_pipeline_dependencies(pipeline, pattern_config)

        return pipeline

    def _find_matching_recommendation(self, tool_pattern: str, recommendations: List) -> Optional:
        """Find a recommendation that matches a tool pattern."""
        pattern_lower = tool_pattern.lower()

        for recommendation in recommendations:
            tool_name = recommendation.tool.get_tool_name().lower()
            tool_description = recommendation.tool.get_tool_description().lower()

            # Check for direct name match or description match
            if (pattern_lower in tool_name or
                pattern_lower in tool_description or
                any(word in tool_name for word in pattern_lower.split())):
                return recommendation

        return None

    def _create_workflow_step(
        self,
        step_number: int,
        recommendation,
        context: Dict[str, Any],
        required: bool = True
    ) -> WorkflowStep:
        """Create a workflow step from a tool recommendation."""
        tool = recommendation.tool
        tool_name = tool.get_tool_name()

        # Infer input/output types based on tool name and description
        input_types, output_types = self._infer_data_flow_types(tool)

        step = WorkflowStep(
            step_id=f"step_{step_number}",
            tool_name=tool_name,
            tool=tool,
            parameters=recommendation.parameter_suggestions,
            input_requirements=input_types,
            output_types=output_types,
            estimated_duration=recommendation.estimated_execution_time,
            resource_requirements={
                'requirements': recommendation.resource_requirements,
                'success_probability': recommendation.success_probability
            }
        )

        return step

    def _infer_data_flow_types(self, tool: BRKGToolWrapper) -> Tuple[List[DataFlowType], List[DataFlowType]]:
        """Infer input and output data flow types for a tool."""
        tool_name = tool.get_tool_name().lower()
        tool_description = tool.get_tool_description().lower()

        inputs = []
        outputs = []

        # Common input/output patterns for neuroimaging tools
        if 'fmriprep' in tool_name or 'preprocessing' in tool_name:
            inputs = [DataFlowType.NIFTI_IMAGE]
            outputs = [DataFlowType.NIFTI_IMAGE, DataFlowType.QUALITY_METRICS]

        elif 'glm' in tool_name or 'analysis' in tool_name:
            inputs = [DataFlowType.NIFTI_IMAGE]
            outputs = [DataFlowType.STATISTICAL_MAP, DataFlowType.RESULTS_TABLE]

        elif 'connectivity' in tool_name:
            inputs = [DataFlowType.NIFTI_IMAGE, DataFlowType.TIMESERIES]
            outputs = [DataFlowType.CONNECTIVITY_MATRIX, DataFlowType.RESULTS_TABLE]

        elif 'coordinate' in tool_name:
            inputs = [DataFlowType.STATISTICAL_MAP, DataFlowType.COORDINATES]
            outputs = [DataFlowType.METADATA, DataFlowType.RESULTS_TABLE]

        elif 'visualization' in tool_name or 'plot' in tool_name:
            inputs = [DataFlowType.STATISTICAL_MAP, DataFlowType.CONNECTIVITY_MATRIX]
            outputs = [DataFlowType.METADATA]

        elif 'quality' in tool_name or 'qc' in tool_name:
            inputs = [DataFlowType.NIFTI_IMAGE]
            outputs = [DataFlowType.QUALITY_METRICS, DataFlowType.RESULTS_TABLE]

        else:
            # Default assumptions
            inputs = [DataFlowType.NIFTI_IMAGE]
            outputs = [DataFlowType.RESULTS_TABLE]

        return inputs, outputs

    def _setup_pipeline_dependencies(self, pipeline: WorkflowPipeline, pattern_config: Dict[str, Any]):
        """Set up dependencies between pipeline steps based on data flow."""
        data_flow_patterns = pattern_config.get("data_flow", [])

        # Create a simple dependency chain based on data flow types
        steps = pipeline.steps

        for i, step in enumerate(steps):
            if i == 0:
                continue  # First step has no dependencies

            # Find previous steps that produce outputs this step needs
            for j in range(i):
                prev_step = steps[j]

                # Check if previous step's outputs match current step's inputs
                common_types = set(prev_step.output_types) & set(step.input_requirements)

                if common_types:
                    step.dependencies.append(prev_step.step_id)
                    break  # Only depend on the most recent matching step

    def _optimize_pipeline(self, pipeline: WorkflowPipeline, context: Dict[str, Any]) -> WorkflowPipeline:
        """Optimize pipeline structure for efficiency and correctness."""

        # Remove redundant steps
        pipeline = self._remove_redundant_steps(pipeline)

        # Optimize parameter propagation
        pipeline = self._optimize_parameter_propagation(pipeline)

        # Validate dependencies
        pipeline = self._validate_and_fix_dependencies(pipeline)

        return pipeline

    def _remove_redundant_steps(self, pipeline: WorkflowPipeline) -> WorkflowPipeline:
        """Remove redundant or conflicting steps."""
        # Simple implementation: remove duplicate tool types
        seen_tools = set()
        filtered_steps = []

        for step in pipeline.steps:
            tool_type = self._get_tool_type(step.tool_name)
            if tool_type not in seen_tools or step.tool_name in ['visualization', 'quality_control']:
                # Allow multiple visualization/QC steps
                filtered_steps.append(step)
                seen_tools.add(tool_type)

        pipeline.steps = filtered_steps
        return pipeline

    def _get_tool_type(self, tool_name: str) -> str:
        """Get the general type of a tool."""
        tool_name_lower = tool_name.lower()

        if 'prep' in tool_name_lower:
            return 'preprocessing'
        elif 'glm' in tool_name_lower or 'analysis' in tool_name_lower:
            return 'statistical_analysis'
        elif 'connectivity' in tool_name_lower:
            return 'connectivity'
        elif 'coordinate' in tool_name_lower:
            return 'coordinate_analysis'
        elif 'visualization' in tool_name_lower:
            return 'visualization'
        elif 'quality' in tool_name_lower:
            return 'quality_control'
        else:
            return 'general'

    def _optimize_parameter_propagation(self, pipeline: WorkflowPipeline) -> WorkflowPipeline:
        """Optimize parameter sharing between related steps."""
        # Look for parameters that should be shared between steps
        common_params = ['threshold', 'fwhm', 'mask', 'output_dir']

        # Find the first step that has each common parameter
        param_sources = {}
        for step in pipeline.steps:
            for param in common_params:
                if param in step.parameters and param not in param_sources:
                    param_sources[param] = step.parameters[param]

        # Propagate parameters to steps that don't have them
        for step in pipeline.steps:
            for param, value in param_sources.items():
                if param not in step.parameters:
                    # Check if this tool accepts this parameter
                    tool_schema = self._get_tool_schema(step.tool)
                    if param in tool_schema:
                        step.parameters[param] = value

        return pipeline

    def _get_tool_schema(self, tool: BRKGToolWrapper) -> Dict[str, Any]:
        """Get parameter schema for a tool."""
        try:
            langchain_tool = tool.as_langchain_tool()
            if hasattr(langchain_tool, 'args_schema') and langchain_tool.args_schema:
                schema = langchain_tool.args_schema.schema()
                return schema.get('properties', {})
        except:
            pass
        return {}

    def _validate_and_fix_dependencies(self, pipeline: WorkflowPipeline) -> WorkflowPipeline:
        """Validate and fix dependency relationships."""
        # Create dependency graph
        graph = nx.DiGraph()

        # Add nodes
        for step in pipeline.steps:
            graph.add_node(step.step_id)

        # Add edges
        for step in pipeline.steps:
            for dep in step.dependencies:
                if dep in [s.step_id for s in pipeline.steps]:
                    graph.add_edge(dep, step.step_id)

        # Check for cycles
        if not nx.is_directed_acyclic_graph(graph):
            logger.warning("Cycle detected in pipeline dependencies, removing problematic edges")
            # Remove edges that create cycles
            while not nx.is_directed_acyclic_graph(graph):
                try:
                    cycle = nx.find_cycle(graph)
                    # Remove the last edge in the cycle
                    graph.remove_edge(cycle[-1][0], cycle[-1][1])
                    # Update step dependencies
                    for step in pipeline.steps:
                        if step.step_id == cycle[-1][1] and cycle[-1][0] in step.dependencies:
                            step.dependencies.remove(cycle[-1][0])
                except nx.NetworkXNoCycle:
                    break

        return pipeline


class WorkflowExecutor:
    """Executes composed workflow pipelines with monitoring and error recovery."""

    def __init__(self, tool_registry: EnhancedToolRegistry):
        """Initialize workflow executor."""
        self.tool_registry = tool_registry
        self.active_executions: Dict[str, WorkflowExecution] = {}
        self.dependency_resolver = DependencyResolver()

        logger.info("Workflow executor initialized")

    async def execute_workflow(
        self,
        pipeline: WorkflowPipeline,
        context: Dict[str, Any] = None,
        parallel_execution: bool = True
    ) -> WorkflowExecution:
        """
        Execute a workflow pipeline.

        Args:
            pipeline: Workflow pipeline to execute
            context: Execution context
            parallel_execution: Whether to use parallel execution when possible

        Returns:
            Workflow execution result
        """
        execution = WorkflowExecution(
            execution_id=f"exec_{uuid4().hex[:8]}",
            pipeline=pipeline,
            status="running",
            start_time=asyncio.get_event_loop().time()
        )

        self.active_executions[execution.execution_id] = execution

        logger.info(f"Starting workflow execution {execution.execution_id}")

        try:
            if parallel_execution and len(pipeline.steps) > 1:
                await self._execute_parallel_workflow(execution, context)
            else:
                await self._execute_sequential_workflow(execution, context)

            execution.status = "completed"
            execution.end_time = asyncio.get_event_loop().time()

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            execution.status = "failed"
            execution.error_message = str(e)
            execution.end_time = asyncio.get_event_loop().time()

        finally:
            # Clean up active execution
            if execution.execution_id in self.active_executions:
                del self.active_executions[execution.execution_id]

        return execution

    async def _execute_sequential_workflow(self, execution: WorkflowExecution, context: Dict[str, Any]):
        """Execute workflow steps sequentially."""
        pipeline = execution.pipeline

        # Sort steps by dependencies (topological sort)
        sorted_steps = self._topological_sort_steps(pipeline.steps)

        for step in sorted_steps:
            if step.optional and execution.status == "running":
                # Skip optional steps if previous required steps failed
                required_deps_failed = any(
                    dep in execution.failed_steps for dep in step.dependencies
                    if not pipeline.get_step_by_id(dep).optional
                )
                if required_deps_failed:
                    logger.info(f"Skipping optional step {step.step_id} due to failed dependencies")
                    continue

            execution.current_step = step.step_id

            logger.info(f"Executing step {step.step_id}: {step.tool_name}")

            try:
                # Prepare step parameters with outputs from previous steps
                step_params = self._prepare_step_parameters(step, execution)

                # Execute step
                result = await self.tool_registry.execute_with_monitoring(
                    tool=step.tool,
                    parameters=step_params,
                    context=context
                )

                if result['status'] == 'success':
                    execution.completed_steps.add(step.step_id)
                    execution.step_results[step.step_id] = result['result']
                    execution.step_outputs[step.step_id] = {
                        'execution_id': result['execution_id'],
                        'execution_time': result['execution_time'],
                        'evidence_chain_id': result.get('evidence_chain_id')
                    }
                else:
                    execution.failed_steps.add(step.step_id)
                    if not step.optional:
                        raise Exception(f"Required step {step.step_id} failed: {result['error']}")

            except Exception as e:
                logger.error(f"Step {step.step_id} failed: {e}")
                execution.failed_steps.add(step.step_id)

                if not step.optional:
                    raise Exception(f"Required step {step.step_id} failed: {e}")

        execution.current_step = None

    async def _execute_parallel_workflow(self, execution: WorkflowExecution, context: Dict[str, Any]):
        """Execute workflow steps in parallel where possible."""
        pipeline = execution.pipeline

        # Create execution graph for parallel processing
        tasks = []
        for step in pipeline.steps:
            from brain_researcher.services.agent.parallel_executor import Task as ParallelTask
            task = ParallelTask(
                task_id=step.step_id,
                name=f"Execute {step.tool_name}",
                tool_name=step.tool_name,
                tool_args=step.parameters,
                dependencies=step.dependencies,
                estimated_duration=step.estimated_duration,
                resource_requirements=[]  # Will be filled by dependency resolver
            )
            tasks.append(task)

        # Resolve dependencies
        execution_graph = self.dependency_resolver.resolve(tasks)

        # Execute with parallel orchestrator
        from brain_researcher.services.agent.parallel_executor import create_parallel_orchestrator
        orchestrator = create_parallel_orchestrator(max_workers=4)

        try:
            from brain_researcher.services.agent.execution_status import ExecutionTracker
            tracker = ExecutionTracker(execution_id=execution.execution_id)

            parallel_result = await orchestrator.execute_parallel(execution_graph, tracker)

            # Process results
            for step_id, result in parallel_result["results"].items():
                step = pipeline.get_step_by_id(step_id)
                if step:
                    execution.completed_steps.add(step_id)
                    execution.step_results[step_id] = result

            for step_id, error in parallel_result["errors"].items():
                step = pipeline.get_step_by_id(step_id)
                if step:
                    execution.failed_steps.add(step_id)
                    if not step.optional:
                        raise Exception(f"Required step {step_id} failed: {error}")

        finally:
            await orchestrator.shutdown()

    def _topological_sort_steps(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """Topologically sort steps based on dependencies."""
        # Create dependency graph
        graph = nx.DiGraph()

        # Add nodes
        step_map = {step.step_id: step for step in steps}
        for step in steps:
            graph.add_node(step.step_id)

        # Add edges
        for step in steps:
            for dep in step.dependencies:
                if dep in step_map:
                    graph.add_edge(dep, step.step_id)

        # Perform topological sort
        try:
            sorted_ids = list(nx.topological_sort(graph))
            return [step_map[step_id] for step_id in sorted_ids]
        except nx.NetworkXError:
            # Fallback to original order if cycle detected
            logger.warning("Cycle detected in step dependencies, using original order")
            return steps

    def _prepare_step_parameters(self, step: WorkflowStep, execution: WorkflowExecution) -> Dict[str, Any]:
        """Prepare parameters for a step, including outputs from previous steps."""
        params = step.parameters.copy()

        # Add outputs from dependency steps
        for dep_id in step.dependencies:
            if dep_id in execution.step_results:
                dep_result = execution.step_results[dep_id]

                # Simple output propagation based on data types
                if isinstance(dep_result, dict):
                    # Propagate common output fields
                    for key in ['output_file', 'result_file', 'statistical_map', 'connectivity_matrix']:
                        if key in dep_result and key not in params:
                            params[f"input_{key}"] = dep_result[key]

        return params

    def get_execution_status(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get status of a workflow execution."""
        return self.active_executions.get(execution_id)

    def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running workflow execution."""
        if execution_id in self.active_executions:
            execution = self.active_executions[execution_id]
            execution.status = "cancelled"
            execution.error_message = "Execution cancelled by user"
            execution.end_time = asyncio.get_event_loop().time()
            del self.active_executions[execution_id]
            return True
        return False


# Factory function for easy integration
def create_workflow_system(tool_registry: EnhancedToolRegistry) -> Tuple[WorkflowComposer, WorkflowExecutor]:
    """Create workflow composer and executor instances."""
    composer = WorkflowComposer(tool_registry)
    executor = WorkflowExecutor(tool_registry)
    return composer, executor