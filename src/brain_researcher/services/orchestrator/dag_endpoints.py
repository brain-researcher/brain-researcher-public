"""
Complex DAG Execution API Endpoints

This module provides FastAPI endpoints for complex DAG workflow management including:
- DAG definition validation and parsing
- DAG execution with real-time status tracking
- Execution monitoring and cancellation
- DAG visualization and analysis
- Template management and reuse
"""

import json
import logging
from datetime import datetime
from typing import Any

import yaml
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator

from ..agent.dag_executor import ComplexDAGExecutor

# Import DAG execution components
from ..agent.dag_language import DAGDefinition, ParameterResolver

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/dag", tags=["DAG Execution"])

# Global executor instance (in production, use dependency injection)
dag_executor = ComplexDAGExecutor()


# Pydantic models for API contracts
class DAGExecutionRequest(BaseModel):
    """Request to execute a DAG"""

    dag_definition: str = Field(..., description="YAML or JSON DAG definition")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Initial parameters"
    )
    execution_mode: str = Field(
        default="strict", description="Execution mode: strict or best_effort"
    )
    scheduling_strategy: str = Field(
        default="eager", description="Scheduling strategy: eager, lazy, or batch"
    )
    max_concurrent_nodes: int = Field(
        default=10, description="Maximum concurrent node executions"
    )
    checkpoint_id: str | None = Field(
        default=None, description="Resume from a saved checkpoint id"
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_checkpoint_id(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            return values
        if not values.get("checkpoint_id") and values.get("resume_checkpoint_id"):
            values["checkpoint_id"] = values.get("resume_checkpoint_id")
        values.pop("resume_checkpoint_id", None)
        return values


class DAGValidationRequest(BaseModel):
    """Request to validate a DAG definition"""

    dag_definition: str = Field(..., description="YAML or JSON DAG definition")
    parameters: dict[str, Any] | None = Field(
        default=None, description="Parameters for validation"
    )


class DAGNode(BaseModel):
    """DAG node representation for API"""

    id: str
    type: str
    dependencies: list[str] = []
    parameters: dict[str, Any] = {}
    tool: str | None = None
    condition: str | None = None
    true_branch: list[str] = []
    false_branch: list[str] = []
    loop_config: dict[str, Any] | None = None
    timeout: int | None = None
    retry_policy: dict[str, Any] | None = None


class DAGDefinitionResponse(BaseModel):
    """DAG definition response"""

    name: str
    version: str
    description: str
    parameters: dict[str, Any]
    nodes: dict[str, DAGNode]
    edges: list[dict[str, str]]
    validation_errors: list[str] = []
    metadata: dict[str, Any] = {}


class ExecutionStatusResponse(BaseModel):
    """Execution status response"""

    execution_id: str
    dag_name: str
    status: str
    start_time: str | None
    end_time: str | None
    duration_seconds: float | None
    total_nodes: int
    completed_nodes: int
    failed_nodes: int
    active_nodes: int
    progress_percentage: float
    node_statuses: dict[str, str] = {}
    checkpoint_id: str | None = None


class NodeExecutionDetail(BaseModel):
    """Detailed node execution information"""

    node_id: str
    status: str
    start_time: str | None
    end_time: str | None
    attempt: int
    max_attempts: int
    result: Any | None
    error: str | None
    duration_seconds: float | None


class ExecutionDetailResponse(BaseModel):
    """Detailed execution response"""

    execution_id: str
    dag: DAGDefinitionResponse
    status: str
    start_time: str | None
    end_time: str | None
    duration_seconds: float | None
    global_context: dict[str, Any]
    node_executions: dict[str, NodeExecutionDetail]
    expanded_nodes: dict[str, list[str]] = {}
    checkpoint_id: str | None = None


class VisualizationResponse(BaseModel):
    """DAG visualization data"""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    layout: dict[str, Any]
    execution_overlay: dict[str, Any] | None = None


# API Endpoints


@router.post("/validate", response_model=DAGDefinitionResponse)
async def validate_dag(request: DAGValidationRequest):
    """Validate a DAG definition without executing it"""
    try:
        # Parse DAG definition
        dag = _parse_dag_definition(request.dag_definition)

        # Validate structure
        validation_errors = dag.validate()

        # Test parameter resolution if provided
        if request.parameters:
            try:
                ParameterResolver.resolve_parameters(dag.parameters, request.parameters)
            except Exception as e:
                validation_errors.append(f"Parameter resolution error: {str(e)}")

        # Convert to response format
        return DAGDefinitionResponse(
            name=dag.name,
            version=dag.version,
            description=dag.description,
            parameters=dag.parameters,
            nodes={
                node_id: DAGNode(
                    id=node.id,
                    type=node.type.value,
                    dependencies=node.dependencies,
                    parameters=node.parameters,
                    tool=node.tool,
                    condition=node.condition,
                    true_branch=node.true_branch,
                    false_branch=node.false_branch,
                    loop_config=node.loop_config.__dict__ if node.loop_config else None,
                    timeout=node.timeout,
                    retry_policy=(
                        node.retry_policy.__dict__ if node.retry_policy else None
                    ),
                )
                for node_id, node in dag.nodes.items()
            },
            edges=[{"from": edge[0], "to": edge[1]} for edge in dag.edges],
            validation_errors=validation_errors,
            metadata=dag.metadata,
        )

    except Exception as e:
        logger.error(f"DAG validation error: {e}")
        raise HTTPException(status_code=400, detail=f"DAG validation failed: {str(e)}")


@router.post("/execute", response_model=dict[str, str])
async def execute_dag(request: DAGExecutionRequest, background_tasks: BackgroundTasks):
    """Execute a DAG workflow asynchronously"""
    try:
        # Parse DAG definition
        dag = _parse_dag_definition(request.dag_definition)

        # Validate DAG
        validation_errors = dag.validate()
        if validation_errors:
            raise HTTPException(
                status_code=400, detail=f"DAG validation failed: {validation_errors}"
            )

        # Configure executor
        if request.max_concurrent_nodes:
            dag_executor.max_concurrent_nodes = request.max_concurrent_nodes

        import uuid

        execution_id = str(uuid.uuid4())

        # Start execution in background (pass resume checkpoint and fixed execution id)
        background_tasks.add_task(
            _execute_dag_background,
            dag,
            request.parameters,
            request.execution_mode,
            execution_id,
            request.checkpoint_id,
        )

        return {
            "execution_id": execution_id,
            "status": "started",
            "message": "DAG execution started successfully",
            "checkpoint_id": request.checkpoint_id,
        }

    except Exception as e:
        logger.error(f"DAG execution error: {e}")
        raise HTTPException(status_code=500, detail=f"DAG execution failed: {str(e)}")


@router.get("/status/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status(execution_id: str):
    """Get the status of a DAG execution"""
    try:
        execution = dag_executor.get_execution_status(execution_id)
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        summary = dag_executor.get_execution_summary(execution_id)
        if not summary:
            raise HTTPException(
                status_code=404, detail="Execution summary not available"
            )

        # Get node statuses
        node_statuses = {
            node_id: node_exec.status.value
            for node_id, node_exec in execution.node_executions.items()
        }

        checkpoint_id = summary.pop("checkpoint_id", None) or summary.pop(
            "last_checkpoint_id", None
        )
        return ExecutionStatusResponse(
            **summary,
            node_statuses=node_statuses,
            checkpoint_id=checkpoint_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution_detail(execution_id: str):
    """Get detailed information about a DAG execution"""
    try:
        execution = dag_executor.get_execution_status(execution_id)
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        # Convert execution to detailed response
        duration = None
        if execution.start_time:
            end_time = execution.end_time or datetime.now()
            duration = (end_time - execution.start_time).total_seconds()

        node_executions = {}
        for node_id, node_exec in execution.node_executions.items():
            node_duration = None
            if node_exec.start_time and node_exec.end_time:
                node_duration = (
                    node_exec.end_time - node_exec.start_time
                ).total_seconds()

            node_executions[node_id] = NodeExecutionDetail(
                node_id=node_exec.node_id,
                status=node_exec.status.value,
                start_time=(
                    node_exec.start_time.isoformat() if node_exec.start_time else None
                ),
                end_time=node_exec.end_time.isoformat() if node_exec.end_time else None,
                attempt=node_exec.attempt,
                max_attempts=node_exec.max_attempts,
                result=node_exec.result,
                error=node_exec.error,
                duration_seconds=node_duration,
            )

        return ExecutionDetailResponse(
            execution_id=execution_id,
            dag=DAGDefinitionResponse(
                name=execution.dag.name,
                version=execution.dag.version,
                description=execution.dag.description,
                parameters=execution.dag.parameters,
                nodes={
                    node_id: DAGNode(
                        id=node.id,
                        type=node.type.value,
                        dependencies=node.dependencies,
                        parameters=node.parameters,
                        tool=node.tool,
                        condition=node.condition,
                        true_branch=node.true_branch,
                        false_branch=node.false_branch,
                        loop_config=(
                            node.loop_config.__dict__ if node.loop_config else None
                        ),
                        timeout=node.timeout,
                        retry_policy=(
                            node.retry_policy.__dict__ if node.retry_policy else None
                        ),
                    )
                    for node_id, node in execution.dag.nodes.items()
                },
                edges=[
                    {"from": edge[0], "to": edge[1]} for edge in execution.dag.edges
                ],
                metadata=execution.dag.metadata,
            ),
            status=execution.status.value,
            start_time=(
                execution.start_time.isoformat() if execution.start_time else None
            ),
            end_time=execution.end_time.isoformat() if execution.end_time else None,
            duration_seconds=duration,
            global_context=execution.global_context,
            node_executions=node_executions,
            expanded_nodes=execution.expanded_nodes,
            checkpoint_id=getattr(execution, "last_checkpoint_id", None),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel/{execution_id}")
async def cancel_execution(execution_id: str):
    """Cancel a running DAG execution"""
    try:
        success = dag_executor.cancel_execution(execution_id)
        if success:
            return {"message": f"Execution {execution_id} cancelled successfully"}
        else:
            raise HTTPException(
                status_code=400, detail="Execution not found or not cancellable"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/visualize/{execution_id}", response_model=VisualizationResponse)
async def visualize_execution(execution_id: str):
    """Get DAG visualization data with execution overlay"""
    try:
        execution = dag_executor.get_execution_status(execution_id)
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        # Generate visualization data
        nodes = []
        edges = []

        # Process nodes
        for node_id, node in execution.dag.nodes.items():
            node_exec = execution.node_executions.get(node_id)
            status = node_exec.status.value if node_exec else "unknown"

            nodes.append(
                {
                    "id": node_id,
                    "label": node_id,
                    "type": node.type.value,
                    "status": status,
                    "tool": node.tool,
                    "condition": node.condition,
                    "parameters": node.parameters,
                }
            )

        # Process edges
        for from_node, to_node in execution.dag.edges:
            edges.append({"from": from_node, "to": to_node, "type": "dependency"})

        # Add conditional edges
        for node_id, node in execution.dag.nodes.items():
            if node.type.value == "conditional":
                for branch_node in node.true_branch:
                    edges.append(
                        {"from": node_id, "to": branch_node, "type": "true_branch"}
                    )
                for branch_node in node.false_branch:
                    edges.append(
                        {"from": node_id, "to": branch_node, "type": "false_branch"}
                    )

        # Create layout (simple hierarchical layout)
        layout = _create_dag_layout(nodes, edges)

        # Create execution overlay
        execution_overlay = {
            "status_colors": {
                "pending": "#gray",
                "running": "#blue",
                "success": "#green",
                "failed": "#red",
                "cancelled": "#orange",
                "skipped": "#yellow",
            },
            "progress": {
                "completed": len(execution.completed_nodes),
                "total": len(execution.node_executions),
                "percentage": (
                    len(execution.completed_nodes)
                    / len(execution.node_executions)
                    * 100
                    if execution.node_executions
                    else 0
                ),
            },
        }

        return VisualizationResponse(
            nodes=nodes, edges=edges, layout=layout, execution_overlay=execution_overlay
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating visualization: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=DAGDefinitionResponse)
async def upload_dag_file(file: UploadFile = File(...)):
    """Upload and validate a DAG definition file"""
    try:
        # Read file content
        content = await file.read()

        # Parse based on file extension
        if file.filename.endswith((".yaml", ".yml")):
            dag_definition = content.decode("utf-8")
        elif file.filename.endswith(".json"):
            dag_definition = content.decode("utf-8")
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file format. Use .yaml, .yml, or .json",
            )

        # Validate the DAG
        validation_request = DAGValidationRequest(dag_definition=dag_definition)
        return await validate_dag(validation_request)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading DAG file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates", response_model=list[dict[str, Any]])
async def list_dag_templates():
    """List available DAG templates"""
    # In practice, this would read from a template repository
    templates = [
        {
            "id": "neuroimaging_analysis",
            "name": "Neuroimaging Analysis Pipeline",
            "description": "Standard fMRI analysis with preprocessing and statistics",
            "category": "neuroimaging",
            "parameters": ["subject_id", "threshold", "smoothing_fwhm"],
            "estimated_duration": "2-4 hours",
        },
        {
            "id": "group_comparison",
            "name": "Group Comparison Analysis",
            "description": "Compare two groups with multiple subjects",
            "category": "statistics",
            "parameters": ["group1_subjects", "group2_subjects", "contrast"],
            "estimated_duration": "1-2 hours",
        },
        {
            "id": "longitudinal_analysis",
            "name": "Longitudinal Analysis",
            "description": "Analyze changes over time for subjects",
            "category": "longitudinal",
            "parameters": ["subjects", "timepoints", "model_type"],
            "estimated_duration": "3-6 hours",
        },
    ]

    return templates


@router.get("/template/{template_id}", response_model=DAGDefinitionResponse)
async def get_dag_template(template_id: str):
    """Get a specific DAG template"""
    # In practice, this would load from a template repository
    if template_id == "neuroimaging_analysis":
        from ..agent.dag_language import EXAMPLE_DAG_YAML

        validation_request = DAGValidationRequest(dag_definition=EXAMPLE_DAG_YAML)
        return await validate_dag(validation_request)
    else:
        raise HTTPException(status_code=404, detail="Template not found")


# Helper functions


def _parse_dag_definition(dag_definition: str) -> DAGDefinition:
    """Parse DAG definition from YAML or JSON string"""
    try:
        # Try YAML first
        yaml.safe_load(dag_definition)
        return DAGDefinition.from_yaml(dag_definition)
    except yaml.YAMLError:
        try:
            # Try JSON
            return DAGDefinition.from_json(dag_definition)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid YAML or JSON format: {e}")


async def _execute_dag_background(
    dag: DAGDefinition,
    parameters: dict[str, Any],
    execution_mode: str,
    execution_id: str,
    resume_checkpoint_id: str | None,
):
    """Execute DAG in background task"""
    try:
        execution = await dag_executor.execute_dag(
            dag,
            parameters,
            execution_id=execution_id,
            resume_checkpoint_id=resume_checkpoint_id,
        )
        logger.info(f"DAG execution completed: {execution.execution_id}")
    except Exception as e:
        logger.error(f"Background DAG execution failed: {e}")


def _create_dag_layout(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """Create a simple hierarchical layout for DAG visualization"""
    # Simple layout algorithm - in practice, use a proper graph layout library
    node_positions = {}

    # Find root nodes (no incoming edges)
    incoming_edges = {edge["to"] for edge in edges}
    root_nodes = [node["id"] for node in nodes if node["id"] not in incoming_edges]

    # Assign positions in levels
    level = 0
    current_level_nodes = root_nodes
    processed = set()

    while current_level_nodes:
        for i, node_id in enumerate(current_level_nodes):
            node_positions[node_id] = {"x": i * 200, "y": level * 150}
            processed.add(node_id)

        # Find next level nodes
        next_level_nodes = []
        for edge in edges:
            if edge["from"] in processed and edge["to"] not in processed:
                if edge["to"] not in next_level_nodes:
                    next_level_nodes.append(edge["to"])

        current_level_nodes = next_level_nodes
        level += 1

    return {
        "type": "hierarchical",
        "direction": "top-bottom",
        "node_positions": node_positions,
        "spacing": {"x": 200, "y": 150},
    }
