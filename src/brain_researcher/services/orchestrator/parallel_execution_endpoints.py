"""
Parallel Execution API Endpoints for Brain Researcher Orchestrator (AGENT-015)

This module provides REST API endpoints for parallel execution orchestration,
execution graph management, and performance metrics.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from brain_researcher.services.agent.parallel_executor import (
    ParallelExecutionOrchestrator,
    Task,
    ResourceType,
    ResourceRequirement,
    create_parallel_orchestrator
)
from brain_researcher.services.agent.dependency_resolver import (
    DependencyResolver,
    ExecutionGraph,
    create_dependency_resolver
)
from brain_researcher.services.agent.execution_status import (
    ExecutionTracker,
    ExecutionStatus
)

logger = logging.getLogger(__name__)

# Global orchestrator instance
_orchestrator: Optional[ParallelExecutionOrchestrator] = None
_dependency_resolver: Optional[DependencyResolver] = None


def get_orchestrator() -> ParallelExecutionOrchestrator:
    """Get or create global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = create_parallel_orchestrator(max_workers=4)
    return _orchestrator


def get_dependency_resolver() -> DependencyResolver:
    """Get or create global dependency resolver instance."""
    global _dependency_resolver
    if _dependency_resolver is None:
        _dependency_resolver = create_dependency_resolver()
    return _dependency_resolver


# Request/Response Models
class ResourceLimitRequest(BaseModel):
    """Resource limit specification."""
    resource_type: str = Field(..., description="Type of resource (cpu, gpu, memory, storage, network)")
    limit: float = Field(..., description="Maximum available amount")


class ResourceRequirementRequest(BaseModel):
    """Resource requirement specification."""
    resource_type: str = Field(..., description="Type of resource")
    amount: float = Field(..., description="Required amount")
    unit: str = Field("", description="Unit of measurement")
    priority: int = Field(1, description="Priority level (1=low, 2=medium, 3=high)")


class TaskRequest(BaseModel):
    """Task specification for parallel execution."""
    task_id: Optional[str] = Field(None, description="Task identifier (auto-generated if not provided)")
    name: str = Field(..., description="Human-readable task name")
    tool_name: str = Field(..., description="Name of the tool to execute")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    dependencies: List[str] = Field(default_factory=list, description="List of dependent task IDs")
    resource_requirements: List[ResourceRequirementRequest] = Field(
        default_factory=list, description="Resource requirements"
    )
    estimated_duration: float = Field(60.0, description="Estimated execution time in seconds")
    timeout: Optional[float] = Field(None, description="Execution timeout in seconds")
    max_retries: int = Field(2, description="Maximum retry attempts")


class ExecutionGraphRequest(BaseModel):
    """Execution graph specification."""
    tasks: List[TaskRequest] = Field(..., description="List of tasks to execute")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ParallelExecutionRequest(BaseModel):
    """Request for parallel execution."""
    execution_graph: ExecutionGraphRequest = Field(..., description="Execution graph")
    max_parallelism: Optional[int] = Field(None, description="Maximum parallel tasks")
    resource_limits: Optional[List[ResourceLimitRequest]] = Field(
        None, description="Resource capacity limits"
    )
    timeout: Optional[float] = Field(None, description="Overall execution timeout")
    enable_monitoring: bool = Field(True, description="Enable progress monitoring")


class ParallelExecutionResponse(BaseModel):
    """Response from parallel execution."""
    execution_id: str = Field(..., description="Unique execution identifier")
    status: str = Field(..., description="Execution status")
    parallel_tasks: int = Field(..., description="Number of tasks running in parallel")
    estimated_speedup: float = Field(..., description="Estimated speedup factor")
    results: Dict[str, Any] = Field(default_factory=dict, description="Task results")
    errors: Dict[str, str] = Field(default_factory=dict, description="Task errors")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Performance metrics")


class ExecutionGraphResponse(BaseModel):
    """Response containing execution graph information."""
    graph_id: str = Field(..., description="Graph identifier")
    total_tasks: int = Field(..., description="Total number of tasks")
    dependency_count: int = Field(..., description="Number of dependencies")
    max_parallelism: int = Field(..., description="Maximum possible parallelism")
    execution_levels: int = Field(..., description="Number of execution levels")
    estimated_duration: float = Field(..., description="Estimated total duration")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors")


class ExecutionStatusResponse(BaseModel):
    """Response containing execution status."""
    execution_id: str = Field(..., description="Execution identifier")
    status: str = Field(..., description="Current status")
    started_at: Optional[float] = Field(None, description="Start timestamp")
    progress: float = Field(0.0, description="Overall progress percentage")
    task_counts: Dict[str, int] = Field(default_factory=dict, description="Task status counts")
    current_step: Optional[str] = Field(None, description="Currently executing step")
    eta: Optional[str] = Field(None, description="Estimated time to completion")
    resource_usage: Dict[str, Dict[str, float]] = Field(
        default_factory=dict, description="Resource usage statistics"
    )


class ExecutionMetricsResponse(BaseModel):
    """Response containing execution performance metrics."""
    total_executions: int = Field(0, description="Total number of executions")
    successful_executions: int = Field(0, description="Successful executions")
    failed_executions: int = Field(0, description="Failed executions")
    average_speedup: float = Field(1.0, description="Average speedup achieved")
    average_parallel_tasks: float = Field(1.0, description="Average parallel tasks")
    resource_utilization: Dict[str, float] = Field(
        default_factory=dict, description="Resource utilization rates"
    )
    performance_improvements: Dict[str, float] = Field(
        default_factory=dict, description="Performance improvement metrics"
    )


# API Router
router = APIRouter(prefix="/api/execution", tags=["parallel-execution"])


@router.post("/parallel", response_model=ParallelExecutionResponse)
async def execute_parallel(
    request: ParallelExecutionRequest,
    background_tasks: BackgroundTasks,
    orchestrator: ParallelExecutionOrchestrator = Depends(get_orchestrator),
    resolver: DependencyResolver = Depends(get_dependency_resolver)
):
    """
    Execute tasks in parallel with dependency management.

    Args:
        request: Parallel execution request
        background_tasks: FastAPI background tasks
        orchestrator: Parallel execution orchestrator
        resolver: Dependency resolver

    Returns:
        Parallel execution response
    """
    try:
        # Convert request to internal format
        tasks = []
        for task_req in request.execution_graph.tasks:
            # Generate task ID if not provided
            task_id = task_req.task_id or f"task_{uuid4().hex[:8]}"

            # Convert resource requirements
            resource_requirements = []
            for req in task_req.resource_requirements:
                try:
                    resource_type = ResourceType(req.resource_type.lower())
                    resource_requirements.append(
                        ResourceRequirement(
                            resource_type=resource_type,
                            amount=req.amount,
                            unit=req.unit,
                            priority=req.priority
                        )
                    )
                except ValueError:
                    logger.warning(f"Unknown resource type: {req.resource_type}")

            task = Task(
                task_id=task_id,
                name=task_req.name,
                tool_name=task_req.tool_name,
                tool_args=task_req.tool_args,
                dependencies=task_req.dependencies,
                resource_requirements=resource_requirements,
                estimated_duration=task_req.estimated_duration,
                timeout=task_req.timeout,
                max_retries=task_req.max_retries
            )
            tasks.append(task)

        # Resolve dependencies and create execution graph
        try:
            execution_graph = resolver.resolve(tasks)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to resolve task dependencies: {str(e)}"
            )

        # Validate execution graph
        validation_errors = resolver.validate_execution_graph(execution_graph)
        if validation_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Execution graph validation failed: {'; '.join(validation_errors)}"
            )

        # Convert resource limits if provided
        resource_limits = None
        if request.resource_limits:
            resource_limits = {}
            for limit in request.resource_limits:
                try:
                    resource_type = ResourceType(limit.resource_type.lower())
                    resource_limits[resource_type] = limit.limit
                except ValueError:
                    logger.warning(f"Unknown resource type in limits: {limit.resource_type}")

        # Update orchestrator resource limits if provided
        if resource_limits:
            orchestrator.resource_manager = type(orchestrator.resource_manager)(resource_limits)

        # Create execution tracker if monitoring is enabled
        execution_tracker = None
        if request.enable_monitoring:
            execution_id = f"parallel_{uuid4().hex[:8]}"
            execution_tracker = ExecutionTracker(execution_id=execution_id)

        # Execute in parallel
        parallel_result = await orchestrator.execute_parallel(
            execution_graph,
            execution_tracker=execution_tracker,
            timeout=request.timeout
        )

        # Calculate performance metrics
        metrics = parallel_result.get("metrics", {})
        speedup = metrics.get("speedup", 1.0)
        parallel_tasks = max(1, len([t for t in tasks if len(t.dependencies) == 0]))

        # Prepare response
        response = ParallelExecutionResponse(
            execution_id=parallel_result["execution_id"],
            status="completed" if not parallel_result["errors"] else "partial_failure",
            parallel_tasks=parallel_tasks,
            estimated_speedup=speedup,
            results=parallel_result["results"],
            errors=parallel_result["errors"],
            metrics=metrics
        )

        logger.info(
            f"Parallel execution completed: {len(parallel_result['results'])} successful, "
            f"{len(parallel_result['errors'])} failed, {speedup:.2f}x speedup"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Parallel execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/{execution_id}", response_model=ExecutionGraphResponse)
async def get_execution_graph(
    execution_id: str,
    orchestrator: ParallelExecutionOrchestrator = Depends(get_orchestrator)
):
    """
    Get execution graph information.

    Args:
        execution_id: Execution identifier
        orchestrator: Parallel execution orchestrator

    Returns:
        Execution graph information
    """
    try:
        # Get execution status
        status_info = orchestrator.get_execution_status(execution_id)

        if not status_info:
            raise HTTPException(
                status_code=404,
                detail=f"Execution {execution_id} not found"
            )

        # Extract graph information from status
        # Note: In a real implementation, we'd store the graph information
        response = ExecutionGraphResponse(
            graph_id=execution_id,
            total_tasks=sum(status_info["task_counts"].values()),
            dependency_count=0,  # Would need to be stored separately
            max_parallelism=status_info["task_counts"].get("running", 0),
            execution_levels=1,  # Simplified
            estimated_duration=0.0,  # Would need calculation
            validation_errors=[]
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status(
    execution_id: str,
    orchestrator: ParallelExecutionOrchestrator = Depends(get_orchestrator)
):
    """
    Get execution status and progress.

    Args:
        execution_id: Execution identifier
        orchestrator: Parallel execution orchestrator

    Returns:
        Execution status information
    """
    try:
        status_info = orchestrator.get_execution_status(execution_id)

        if not status_info:
            raise HTTPException(
                status_code=404,
                detail=f"Execution {execution_id} not found"
            )

        # Calculate progress
        task_counts = status_info["task_counts"]
        total_tasks = sum(task_counts.values())
        completed_tasks = task_counts.get("completed", 0) + task_counts.get("failed", 0)
        progress = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0

        response = ExecutionStatusResponse(
            execution_id=execution_id,
            status=_determine_overall_status(task_counts),
            started_at=status_info.get("started_at"),
            progress=progress,
            task_counts=task_counts,
            current_step=_get_current_step(task_counts),
            eta=None,  # Would need calculation based on progress
            resource_usage=status_info.get("resource_usage", {})
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cancel/{execution_id}")
async def cancel_execution(
    execution_id: str,
    orchestrator: ParallelExecutionOrchestrator = Depends(get_orchestrator)
):
    """
    Cancel a running execution.

    Args:
        execution_id: Execution identifier
        orchestrator: Parallel execution orchestrator

    Returns:
        Cancellation confirmation
    """
    try:
        success = orchestrator.cancel_execution(execution_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Execution {execution_id} not found or not cancellable"
            )

        return {"execution_id": execution_id, "cancelled": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics", response_model=ExecutionMetricsResponse)
async def get_execution_metrics(
    orchestrator: ParallelExecutionOrchestrator = Depends(get_orchestrator)
):
    """
    Get overall execution performance metrics.

    Args:
        orchestrator: Parallel execution orchestrator

    Returns:
        Performance metrics
    """
    try:
        # Get resource usage from orchestrator
        resource_usage = orchestrator.resource_manager.get_resource_usage()

        # Calculate utilization rates
        resource_utilization = {}
        for resource_type, usage_info in resource_usage.items():
            resource_utilization[resource_type] = usage_info.get("utilization", 0.0)

        # In a real implementation, these metrics would be tracked over time
        response = ExecutionMetricsResponse(
            total_executions=len(orchestrator.active_executions),
            successful_executions=0,  # Would need historical tracking
            failed_executions=0,  # Would need historical tracking
            average_speedup=1.0,  # Would need historical tracking
            average_parallel_tasks=2.0,  # Would need historical tracking
            resource_utilization=resource_utilization,
            performance_improvements={
                "parallel_execution_enabled": True,
                "dependency_resolution_enabled": True,
                "resource_management_enabled": True
            }
        )

        return response

    except Exception as e:
        logger.error(f"Failed to get execution metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate-graph")
async def validate_execution_graph(
    request: ExecutionGraphRequest,
    resolver: DependencyResolver = Depends(get_dependency_resolver)
):
    """
    Validate an execution graph without executing it.

    Args:
        request: Execution graph to validate
        resolver: Dependency resolver

    Returns:
        Validation results
    """
    try:
        # Convert request to internal format (simplified)
        tasks = []
        for task_req in request.tasks:
            task_id = task_req.task_id or f"task_{uuid4().hex[:8]}"

            # Create minimal task for validation
            task = Task(
                task_id=task_id,
                name=task_req.name,
                tool_name=task_req.tool_name,
                tool_args={},
                dependencies=task_req.dependencies
            )
            tasks.append(task)

        # Try to resolve dependencies
        try:
            execution_graph = resolver.resolve(tasks)
            validation_errors = resolver.validate_execution_graph(execution_graph)
        except Exception as e:
            validation_errors = [str(e)]
            execution_graph = None

        # Calculate metrics if graph is valid
        if execution_graph and not validation_errors:
            max_parallelism = execution_graph.metadata.get("max_parallelism", 1)
            dependency_count = execution_graph.metadata.get("dependency_count", 0)
        else:
            max_parallelism = 1
            dependency_count = 0

        return {
            "valid": len(validation_errors) == 0,
            "validation_errors": validation_errors,
            "max_parallelism": max_parallelism,
            "dependency_count": dependency_count,
            "total_tasks": len(tasks)
        }

    except Exception as e:
        logger.error(f"Graph validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper functions
def _determine_overall_status(task_counts: Dict[str, int]) -> str:
    """Determine overall execution status from task counts."""
    if task_counts.get("running", 0) > 0:
        return "running"
    elif task_counts.get("failed", 0) > 0:
        return "failed"
    elif task_counts.get("completed", 0) > 0 and task_counts.get("queued", 0) == 0:
        return "completed"
    else:
        return "pending"


def _get_current_step(task_counts: Dict[str, int]) -> Optional[str]:
    """Get description of current execution step."""
    if task_counts.get("running", 0) > 0:
        return f"{task_counts['running']} tasks running"
    elif task_counts.get("queued", 0) > 0:
        return f"{task_counts['queued']} tasks queued"
    else:
        return None


# Cleanup on shutdown
@router.on_event("shutdown")
async def shutdown_orchestrator():
    """Cleanup orchestrator on shutdown."""
    global _orchestrator
    if _orchestrator:
        await _orchestrator.shutdown()
        _orchestrator = None