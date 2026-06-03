"""
REST API Endpoints for Adaptive Execution Strategy (AGENT-021)

This module provides HTTP endpoints for monitoring and controlling
the adaptive execution system including metrics, strategy selection,
and performance monitoring.
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

from brain_researcher.services.agent.system_monitor import SystemHealth
from brain_researcher.services.agent.adaptive_scheduler import TaskPriority
from brain_researcher.services.agent.strategy_selector import ExecutionStrategy

logger = logging.getLogger(__name__)

# Pydantic models for API contracts

class SystemMetricsResponse(BaseModel):
    """System metrics response model."""
    timestamp: float
    cpu_usage: float = Field(..., description="CPU usage percentage")
    memory_usage: float = Field(..., description="Memory usage percentage")
    memory_available: float = Field(..., description="Available memory in GB")
    disk_io_read: float = Field(..., description="Disk read rate in MB/s")
    disk_io_write: float = Field(..., description="Disk write rate in MB/s")
    network_sent: float = Field(..., description="Network sent rate in MB/s")
    network_recv: float = Field(..., description="Network recv rate in MB/s")
    load_average: list[float] = Field(..., description="System load averages")
    active_processes: int = Field(..., description="Number of active processes")
    queue_depth: int = Field(..., description="Task queue depth")
    gpu_usage: Optional[float] = Field(None, description="GPU usage percentage")
    gpu_memory: Optional[float] = Field(None, description="GPU memory usage percentage")
    health_status: str = Field(..., description="Overall system health")


class PerformanceAnalysisResponse(BaseModel):
    """Performance analysis response model."""
    overall_health: str = Field(..., description="System health status")
    bottlenecks: list[str] = Field(..., description="Identified bottlenecks")
    recommendations: list[str] = Field(..., description="Performance recommendations")
    trend_direction: str = Field(..., description="Performance trend")
    predicted_capacity: float = Field(..., description="Predicted capacity percentage")


class ResourceLimitsModel(BaseModel):
    """Resource limits configuration model."""
    max_parallel: int = Field(..., ge=1, le=32, description="Maximum parallel tasks")
    cpu_limit: float = Field(..., ge=10.0, le=100.0, description="CPU usage limit percentage")
    memory_limit: float = Field(..., ge=10.0, le=100.0, description="Memory usage limit percentage")
    io_limit: float = Field(..., ge=10.0, le=1000.0, description="I/O limit in MB/s")
    preemption_enabled: bool = Field(..., description="Enable task preemption")
    timeout_multiplier: float = Field(..., ge=0.1, le=5.0, description="Timeout multiplier")


class StrategySelectionRequest(BaseModel):
    """Strategy selection request model."""
    strategy: ExecutionStrategy = Field(..., description="Execution strategy to set")
    force: bool = Field(False, description="Force strategy change ignoring cooldown")


class StrategySelectionResponse(BaseModel):
    """Strategy selection response model."""
    current_strategy: str = Field(..., description="Current execution strategy")
    previous_strategy: Optional[str] = Field(None, description="Previous strategy")
    switch_reason: str = Field(..., description="Reason for strategy selection")
    config: ResourceLimitsModel = Field(..., description="Strategy configuration")


class QueueStatusResponse(BaseModel):
    """Queue status response model."""
    queued_tasks: int = Field(..., description="Number of queued tasks")
    running_tasks: int = Field(..., description="Number of running tasks")
    completed_tasks: int = Field(..., description="Number of completed tasks")
    queue_by_priority: Dict[str, int] = Field(..., description="Queue count by priority")
    preemption_stats: Dict[str, Any] = Field(..., description="Preemption statistics")


class PerformanceMetricsResponse(BaseModel):
    """Performance metrics response model."""
    system: Optional[Dict[str, Any]] = Field(None, description="System metrics")
    scheduler: Optional[Dict[str, Any]] = Field(None, description="Scheduler metrics")
    strategy: Optional[Dict[str, Any]] = Field(None, description="Strategy metrics")
    performance: Optional[Dict[str, Any]] = Field(None, description="Performance history")


class StrategyRecommendationsResponse(BaseModel):
    """Strategy recommendations response model."""
    recommendations: Dict[str, Dict[str, Any]] = Field(..., description="Strategy recommendations")
    current_conditions: Dict[str, Any] = Field(..., description="Current system conditions")


# Router setup
adaptive_router = APIRouter(prefix="/api/adaptive", tags=["adaptive"])

# Global orchestrator reference (will be set by the main service)
_orchestrator = None


def set_orchestrator(orchestrator):
    """Set the global orchestrator reference."""
    global _orchestrator
    _orchestrator = orchestrator


def get_orchestrator():
    """Get the orchestrator instance."""
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not available")

    if not _orchestrator.enable_adaptive:
        raise HTTPException(
            status_code=501,
            detail="Adaptive features not enabled in orchestrator"
        )

    return _orchestrator


@adaptive_router.get("/metrics", response_model=SystemMetricsResponse)
async def get_system_metrics():
    """Get current system metrics."""
    try:
        orchestrator = get_orchestrator()
        metrics = orchestrator.system_monitor.get_system_metrics()

        if not metrics:
            raise HTTPException(status_code=503, detail="System metrics not available")

        health = orchestrator.system_monitor.get_health_status()

        return SystemMetricsResponse(
            timestamp=metrics.timestamp,
            cpu_usage=metrics.cpu_usage,
            memory_usage=metrics.memory_usage,
            memory_available=metrics.memory_available,
            disk_io_read=metrics.disk_io_read,
            disk_io_write=metrics.disk_io_write,
            network_sent=metrics.network_sent,
            network_recv=metrics.network_recv,
            load_average=list(metrics.load_average),
            active_processes=metrics.active_processes,
            queue_depth=metrics.queue_depth,
            gpu_usage=metrics.gpu_usage,
            gpu_memory=metrics.gpu_memory,
            health_status=health.value
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get system metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.get("/metrics/average")
async def get_average_metrics(
    window_seconds: int = Query(60, ge=10, le=3600, description="Time window in seconds")
):
    """Get average system metrics over a time window."""
    try:
        orchestrator = get_orchestrator()
        avg_metrics = orchestrator.system_monitor.get_average_metrics(window_seconds)

        if not avg_metrics:
            raise HTTPException(status_code=404, detail="No metrics available for the specified window")

        health = orchestrator.system_monitor.get_health_status()

        return SystemMetricsResponse(
            timestamp=avg_metrics.timestamp,
            cpu_usage=avg_metrics.cpu_usage,
            memory_usage=avg_metrics.memory_usage,
            memory_available=avg_metrics.memory_available,
            disk_io_read=avg_metrics.disk_io_read,
            disk_io_write=avg_metrics.disk_io_write,
            network_sent=avg_metrics.network_sent,
            network_recv=avg_metrics.network_recv,
            load_average=list(avg_metrics.load_average),
            active_processes=avg_metrics.active_processes,
            queue_depth=avg_metrics.queue_depth,
            gpu_usage=avg_metrics.gpu_usage,
            gpu_memory=avg_metrics.gpu_memory,
            health_status=health.value
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get average metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.get("/performance/analysis", response_model=PerformanceAnalysisResponse)
async def get_performance_analysis():
    """Get current performance analysis and recommendations."""
    try:
        orchestrator = get_orchestrator()
        analysis = orchestrator.system_monitor.get_performance_analysis()

        if not analysis:
            raise HTTPException(status_code=503, detail="Performance analysis not available")

        return PerformanceAnalysisResponse(
            overall_health=analysis.overall_health.value,
            bottlenecks=analysis.bottlenecks,
            recommendations=analysis.recommendations,
            trend_direction=analysis.trend_direction,
            predicted_capacity=analysis.predicted_capacity
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get performance analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.get("/strategy", response_model=StrategySelectionResponse)
async def get_current_strategy():
    """Get current execution strategy."""
    try:
        orchestrator = get_orchestrator()
        current_strategy = orchestrator.get_current_strategy()

        if not current_strategy:
            raise HTTPException(status_code=503, detail="Strategy information not available")

        config = orchestrator.strategy_selector.get_strategy_config(current_strategy)

        return StrategySelectionResponse(
            current_strategy=current_strategy.value,
            switch_reason="Current active strategy",
            config=ResourceLimitsModel(
                max_parallel=config.max_parallel,
                cpu_limit=config.cpu_limit,
                memory_limit=config.memory_limit,
                io_limit=config.io_limit,
                preemption_enabled=config.preemption_enabled,
                timeout_multiplier=config.timeout_multiplier
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get current strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.post("/strategy", response_model=StrategySelectionResponse)
async def set_execution_strategy(request: StrategySelectionRequest):
    """Set execution strategy."""
    try:
        orchestrator = get_orchestrator()
        previous_strategy = orchestrator.get_current_strategy()

        if request.force:
            orchestrator.force_strategy(request.strategy)
            switch_reason = "Forced by user request"
        else:
            # Let the strategy selector decide based on current conditions
            recommendations = orchestrator.get_strategy_recommendations()
            if request.strategy.value not in recommendations:
                raise HTTPException(
                    status_code=400,
                    detail=f"Strategy {request.strategy.value} not recommended for current conditions"
                )
            orchestrator.force_strategy(request.strategy)
            switch_reason = "User requested with validation"

        config = orchestrator.strategy_selector.get_strategy_config(request.strategy)

        return StrategySelectionResponse(
            current_strategy=request.strategy.value,
            previous_strategy=previous_strategy.value if previous_strategy else None,
            switch_reason=switch_reason,
            config=ResourceLimitsModel(
                max_parallel=config.max_parallel,
                cpu_limit=config.cpu_limit,
                memory_limit=config.memory_limit,
                io_limit=config.io_limit,
                preemption_enabled=config.preemption_enabled,
                timeout_multiplier=config.timeout_multiplier
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set execution strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.get("/strategy/recommendations", response_model=StrategyRecommendationsResponse)
async def get_strategy_recommendations():
    """Get strategy recommendations for current conditions."""
    try:
        orchestrator = get_orchestrator()
        recommendations = orchestrator.get_strategy_recommendations()

        if not recommendations:
            raise HTTPException(status_code=503, detail="Strategy recommendations not available")

        # Get current system conditions
        metrics = orchestrator.system_monitor.get_system_metrics()
        health = orchestrator.system_monitor.get_health_status()
        resource_util = orchestrator.system_monitor.get_resource_utilization()

        current_conditions = {
            "system_health": health.value,
            "resource_utilization": resource_util,
            "timestamp": metrics.timestamp if metrics else None
        }

        return StrategyRecommendationsResponse(
            recommendations=recommendations,
            current_conditions=current_conditions
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get strategy recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.get("/queue/status", response_model=QueueStatusResponse)
async def get_queue_status():
    """Get current task queue status."""
    try:
        orchestrator = get_orchestrator()
        queue_status = orchestrator.adaptive_scheduler.get_queue_status()
        preemption_stats = orchestrator.adaptive_scheduler.preemption_manager.get_preemption_stats()

        return QueueStatusResponse(
            queued_tasks=queue_status["queued_tasks"],
            running_tasks=queue_status["running_tasks"],
            completed_tasks=queue_status["completed_tasks"],
            queue_by_priority=queue_status["queue_by_priority"],
            preemption_stats=preemption_stats
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get queue status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.get("/performance", response_model=PerformanceMetricsResponse)
async def get_performance_metrics():
    """Get comprehensive performance metrics."""
    try:
        orchestrator = get_orchestrator()
        metrics = orchestrator.get_adaptive_metrics()

        return PerformanceMetricsResponse(
            system=metrics.get("system"),
            scheduler=metrics.get("scheduler"),
            strategy=metrics.get("strategy"),
            performance=metrics.get("performance")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.post("/tasks/priority/{task_id}")
async def adjust_task_priority(
    task_id: str,
    priority: TaskPriority = Body(..., description="New task priority")
):
    """Adjust priority of a queued task."""
    try:
        orchestrator = get_orchestrator()
        success = await orchestrator.adaptive_scheduler.adjust_task_priority(task_id, priority)

        if not success:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found in queue")

        return {"success": True, "task_id": task_id, "new_priority": priority.name}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to adjust task priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.get("/health")
async def get_adaptive_health():
    """Get health status of adaptive components."""
    try:
        orchestrator = get_orchestrator()

        health_status = {
            "adaptive_enabled": orchestrator.enable_adaptive,
            "system_monitor": {
                "active": orchestrator.system_monitor._monitoring if orchestrator.system_monitor else False,
                "last_metrics": orchestrator.system_monitor.get_system_metrics() is not None if orchestrator.system_monitor else False
            },
            "scheduler": {
                "active": orchestrator.adaptive_scheduler._scheduler_running if orchestrator.adaptive_scheduler else False,
                "queue_depth": orchestrator.adaptive_scheduler.get_queue_status()["queued_tasks"] if orchestrator.adaptive_scheduler else 0
            },
            "strategy_selector": {
                "current_strategy": orchestrator.current_strategy.value if orchestrator.current_strategy else None,
                "last_switch": orchestrator.strategy_start_time
            }
        }

        return health_status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get adaptive health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.post("/control/start")
async def start_adaptive_components():
    """Start adaptive monitoring and scheduling components."""
    try:
        orchestrator = get_orchestrator()
        await orchestrator.start_adaptive_components()
        return {"success": True, "message": "Adaptive components started"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start adaptive components: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@adaptive_router.post("/control/stop")
async def stop_adaptive_components():
    """Stop adaptive components."""
    try:
        orchestrator = get_orchestrator()
        await orchestrator.stop_adaptive_components()
        return {"success": True, "message": "Adaptive components stopped"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop adaptive components: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Error handlers would be added to the main app, not the router


# Export the router
__all__ = ["adaptive_router", "set_orchestrator"]