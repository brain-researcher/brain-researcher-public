"""
Integration module for connecting Resource Management with existing systems.

Provides hooks and decorators for seamless integration with ExecutionTracker,
PlanningEngine, and CoreStateMachine.
"""

import functools
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from brain_researcher.services.agent.execution_status import ExecutionTracker, ExecutionStatus
from brain_researcher.services.agent.planning import ExecutionPlan
from brain_researcher.services.agent.resources.resource_manager import ResourceManager
from brain_researcher.services.agent.resources.resource_monitor import ResourceMonitor
from brain_researcher.services.agent.resources.queue_manager import Priority
from brain_researcher.services.agent.resources.resource_limits import get_tool_profile

logger = logging.getLogger(__name__)

# Global resource manager instance (singleton)
_resource_manager: Optional[ResourceManager] = None
_resource_monitor: Optional[ResourceMonitor] = None


def initialize_resource_management(
    max_cpu_cores: float = 4.0,
    max_memory_gb: float = 8.0,
    max_gpus: int = 0,
    enable_monitoring: bool = True,
) -> Tuple[ResourceManager, ResourceMonitor]:
    """
    Initialize global resource management system.

    Args:
        max_cpu_cores: Maximum CPU cores
        max_memory_gb: Maximum memory in GB
        max_gpus: Maximum GPU count
        enable_monitoring: Enable resource monitoring

    Returns:
        Tuple of (ResourceManager, ResourceMonitor)
    """
    global _resource_manager, _resource_monitor

    _resource_manager = ResourceManager(
        max_cpu_cores=max_cpu_cores,
        max_memory_gb=max_memory_gb,
        max_gpus=max_gpus,
    )

    _resource_monitor = ResourceMonitor(enable_monitoring=enable_monitoring)

    logger.info("Resource management system initialized")
    return _resource_manager, _resource_monitor


def get_resource_manager() -> Optional[ResourceManager]:
    """Get global resource manager instance."""
    return _resource_manager


def get_resource_monitor() -> Optional[ResourceMonitor]:
    """Get global resource monitor instance."""
    return _resource_monitor


class ResourceAwareExecutionTracker(ExecutionTracker):
    """
    Extended ExecutionTracker with resource management integration.

    Automatically manages resource allocation/deallocation during execution lifecycle.
    """

    def __init__(
        self,
        execution_id: Optional[str] = None,
        redis_client: Optional[Any] = None,
        resource_manager: Optional[ResourceManager] = None,
        resource_monitor: Optional[ResourceMonitor] = None,
    ):
        """
        Initialize resource-aware execution tracker.

        Args:
            execution_id: Unique execution ID
            redis_client: Redis client for persistence
            resource_manager: Resource manager instance
            resource_monitor: Resource monitor instance
        """
        super().__init__(execution_id, redis_client)

        self.resource_manager = resource_manager or get_resource_manager()
        self.resource_monitor = resource_monitor or get_resource_monitor()
        self.resource_allocation = None
        self.resource_metrics = None

    def start_step(self, step_index: Optional[int] = None):
        """
        Start a step with resource allocation.

        Args:
            step_index: Step index to start
        """
        # Start the step normally
        super().start_step(step_index)

        # Get current step
        current_step = self.get_current_step()
        if not current_step:
            return

        # Extract tool name from step (assuming it's in step data)
        tool_name = current_step.data.get("tool") if current_step.data else None

        if tool_name and self.resource_manager:
            # Determine priority based on step type
            priority = self._determine_priority(current_step)

            # Request resources
            logger.info(f"Requesting resources for {tool_name} (step {current_step.name})")
            self.resource_allocation = self.resource_manager.request_resources(
                tool_name=tool_name,
                execution_id=self.execution_id,
                priority=priority,
                timeout=30.0,  # 30 second timeout
            )

            if self.resource_allocation:
                logger.info(
                    f"Allocated {self.resource_allocation.cpu_cores} CPU, "
                    f"{self.resource_allocation.memory_gb}GB memory for {tool_name}"
                )

                # Start resource monitoring
                if self.resource_monitor:
                    self.resource_metrics = self.resource_monitor.start_tracking(
                        tool_name=tool_name,
                        execution_id=self.execution_id,
                    )
            else:
                logger.warning(f"Failed to allocate resources for {tool_name}")
                # Could mark step as failed here if strict resource enforcement

    def complete_step(self, step_index: Optional[int] = None):
        """
        Complete a step and release resources.

        Args:
            step_index: Step index to complete
        """
        # Complete the step normally
        super().complete_step(step_index)

        # Release resources if allocated
        if self.resource_allocation and self.resource_manager:
            self.resource_manager.release_resources(self.execution_id)
            logger.info(f"Released resources for execution {self.execution_id[:8]}")
            self.resource_allocation = None

        # Stop resource monitoring
        if self.resource_metrics and self.resource_monitor:
            metrics = self.resource_monitor.stop_tracking(self.execution_id)
            if metrics:
                # Add metrics to step data
                current_step = self.get_current_step()
                if current_step and current_step.data:
                    current_step.data["resource_metrics"] = metrics.to_dict()
            self.resource_metrics = None

    def fail_step(self, step_index: Optional[int] = None, error: Optional[str] = None):
        """
        Fail a step and release resources.

        Args:
            step_index: Step index to fail
            error: Error message
        """
        # Fail the step normally
        super().fail_step(step_index, error)

        # Release resources if allocated
        if self.resource_allocation and self.resource_manager:
            self.resource_manager.release_resources(self.execution_id)
            logger.info(f"Released resources after failure for {self.execution_id[:8]}")
            self.resource_allocation = None

        # Stop resource monitoring
        if self.resource_metrics and self.resource_monitor:
            self.resource_monitor.stop_tracking(self.execution_id)
            self.resource_metrics = None

    def cancel(self):
        """Cancel execution and release all resources."""
        # Cancel normally
        super().cancel()

        # Clean up resources
        if self.resource_allocation and self.resource_manager:
            self.resource_manager.release_resources(self.execution_id)
            self.resource_allocation = None

        if self.resource_metrics and self.resource_monitor:
            self.resource_monitor.stop_tracking(self.execution_id)
            self.resource_metrics = None

    def _determine_priority(self, step) -> Priority:
        """Determine priority for resource allocation based on step."""
        # Interactive/user-facing steps get high priority
        if step.data and step.data.get("interactive"):
            return Priority.HIGH

        # Background/batch processing gets low priority
        if step.data and step.data.get("batch"):
            return Priority.LOW

        # Default to normal priority
        return Priority.NORMAL


def resource_aware_tool(
    cpu_cores: Optional[float] = None,
    memory_gb: Optional[float] = None,
    gpu_count: Optional[int] = None,
    priority: Priority = Priority.NORMAL,
):
    """
    Decorator for making tools resource-aware.

    Args:
        cpu_cores: CPU cores required (overrides profile)
        memory_gb: Memory required in GB (overrides profile)
        gpu_count: GPU count required (overrides profile)
        priority: Execution priority
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get tool name from function
            tool_name = func.__name__

            # Get resource manager
            resource_manager = get_resource_manager()
            resource_monitor = get_resource_monitor()

            if not resource_manager:
                # No resource management, execute directly
                return func(*args, **kwargs)

            # Request resources
            execution_id = kwargs.get("execution_id", f"{tool_name}_{id(args)}")

            allocation = resource_manager.request_resources(
                tool_name=tool_name,
                execution_id=execution_id,
                priority=priority,
            )

            if not allocation:
                raise RuntimeError(f"Failed to allocate resources for {tool_name}")

            # Start monitoring
            metrics = None
            if resource_monitor:
                metrics = resource_monitor.start_tracking(tool_name, execution_id)

            try:
                # Execute the tool
                result = func(*args, **kwargs)

                # Add resource info to result if it's a dict
                if isinstance(result, dict):
                    result["_resource_allocation"] = {
                        "cpu_cores": allocation.cpu_cores,
                        "memory_gb": allocation.memory_gb,
                        "duration": str(allocation.duration),
                    }

                return result

            finally:
                # Release resources
                resource_manager.release_resources(execution_id)

                # Stop monitoring
                if resource_monitor and metrics:
                    final_metrics = resource_monitor.stop_tracking(execution_id)
                    if final_metrics and isinstance(result, dict):
                        result["_resource_metrics"] = final_metrics.to_dict()

        return wrapper
    return decorator


class ResourceAwarePlanningEngine:
    """
    Extension to PlanningEngine that considers resource constraints.
    """

    @staticmethod
    def optimize_plan_for_resources(
        plan: ExecutionPlan,
        resource_manager: ResourceManager,
    ) -> ExecutionPlan:
        """
        Optimize execution plan based on resource availability.

        Args:
            plan: Original execution plan
            resource_manager: Resource manager instance

        Returns:
            Optimized execution plan
        """
        if not resource_manager:
            return plan

        # Get current resource status
        status = resource_manager.get_status()
        available_cpu = status["pool"]["available"]["cpu_cores"]
        available_memory = status["pool"]["available"]["memory_gb"]

        # Check each step in the plan
        for step in plan.steps:
            tool_name = step.get("tool")
            if not tool_name:
                continue

            # Check if tool can be executed with available resources
            if not resource_manager.can_allocate(tool_name):
                # Mark step for queueing
                step["queue_required"] = True
                step["estimated_wait"] = "Resources limited, will be queued"

                logger.info(
                    f"Step '{step.get('name')}' using {tool_name} will require queueing "
                    f"(available: {available_cpu:.1f} CPU, {available_memory:.1f}GB memory)"
                )

        # Add resource summary to plan metadata
        plan.metadata["resource_analysis"] = {
            "available_cpu": available_cpu,
            "available_memory_gb": available_memory,
            "queue_required_steps": sum(1 for s in plan.steps if s.get("queue_required")),
            "estimated_total_cpu": sum(
                get_tool_profile(s.get("tool", "")).cpu_cores
                for s in plan.steps if s.get("tool")
            ),
            "estimated_total_memory_gb": max(
                get_tool_profile(s.get("tool", "")).memory_gb
                for s in plan.steps if s.get("tool")
            ) if plan.steps else 0,
        }

        return plan


def with_resource_management(
    tool_name: str,
    priority: Priority = Priority.NORMAL,
):
    """
    Context manager for resource-managed execution.

    Usage:
        with with_resource_management("glm_analysis") as allocation:
            if allocation:
                # Execute tool
                result = run_glm_analysis()
    """
    class ResourceContext:
        def __init__(self, tool_name: str, priority: Priority):
            self.tool_name = tool_name
            self.priority = priority
            self.allocation = None
            self.execution_id = f"{tool_name}_{id(self)}"
            self.resource_manager = get_resource_manager()
            self.resource_monitor = get_resource_monitor()
            self.metrics = None

        def __enter__(self):
            if self.resource_manager:
                self.allocation = self.resource_manager.request_resources(
                    tool_name=self.tool_name,
                    execution_id=self.execution_id,
                    priority=self.priority,
                )

                if self.allocation and self.resource_monitor:
                    self.metrics = self.resource_monitor.start_tracking(
                        self.tool_name,
                        self.execution_id,
                    )

            return self.allocation

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.allocation and self.resource_manager:
                self.resource_manager.release_resources(self.execution_id)

            if self.metrics and self.resource_monitor:
                self.resource_monitor.stop_tracking(self.execution_id)

    return ResourceContext(tool_name, priority)