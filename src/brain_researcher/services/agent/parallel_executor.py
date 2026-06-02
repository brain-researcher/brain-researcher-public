"""
Adaptive Parallel Execution Orchestration for Brain Researcher Agent (AGENT-015 + AGENT-021)

This module implements parallel execution of independent tools with dependency management,
resource contention handling, deadlock detection, and adaptive execution strategy.
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from brain_researcher.services.agent.dependency_resolver import (
    DependencyResolver,
    ExecutionGraph,
)
from brain_researcher.services.agent.execution_status import (
    ExecutionStatus,
    ExecutionTracker,
    StepStatus,
)
from brain_researcher.services.agent.system_monitor import (
    SystemMonitor,
    create_system_monitor,
)

if TYPE_CHECKING:
    from brain_researcher.services.agent.adaptive_scheduler import (
        AdaptiveScheduler,
        TaskPriority,
    )
    from brain_researcher.services.agent.strategy_selector import (
        ExecutionContext,
        ExecutionStrategy,
        StrategySelector,
    )

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    """Types of computational resources."""

    CPU = "cpu"
    GPU = "gpu"
    MEMORY = "memory"
    STORAGE = "storage"
    NETWORK = "network"


__all__ = [
    "Task",
    "TaskStatus",
    "ResourceType",
    "ResourceRequirement",
    "ResourceAllocation",
    "ResourceManager",
    "ParallelExecutor",
]


class TaskStatus(str, Enum):
    """Status of individual tasks in parallel execution."""

    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass
class ResourceRequirement:
    """Resource requirement specification."""

    resource_type: ResourceType
    amount: float
    unit: str = ""
    priority: int = 1  # 1=low, 2=medium, 3=high


@dataclass
class Task:
    """Represents a single executable task."""

    task_id: str
    name: str
    tool_name: str
    tool_args: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    resource_requirements: List[ResourceRequirement] = field(default_factory=list)
    estimated_duration: float = 60.0  # seconds
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 2
    status: TaskStatus = TaskStatus.QUEUED
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class ResourceAllocation:
    """Resource allocation tracking."""

    resource_type: ResourceType
    total_capacity: float
    allocated: float = 0.0
    reserved: float = 0.0
    waitlist: List[str] = field(
        default_factory=list
    )  # task_ids waiting for this resource


class ResourceManager:
    """Manages resource allocation and contention."""

    def __init__(self, resource_limits: Optional[Dict[ResourceType, float]] = None):
        """
        Initialize resource manager.

        Args:
            resource_limits: Maximum available resources
        """
        # Default resource limits
        default_limits = {
            ResourceType.CPU: 8.0,  # cores
            ResourceType.GPU: 1.0,  # devices
            ResourceType.MEMORY: 32.0,  # GB
            ResourceType.STORAGE: 1000.0,  # GB
            ResourceType.NETWORK: 1000.0,  # Mbps
        }

        limits = resource_limits or default_limits
        self.allocations = {
            resource_type: ResourceAllocation(resource_type, capacity)
            for resource_type, capacity in limits.items()
        }

        self.task_allocations: Dict[str, List[ResourceRequirement]] = {}
        self._lock = asyncio.Lock()

    async def can_allocate(self, task: Task) -> bool:
        """Check if resources can be allocated for a task."""
        async with self._lock:
            for req in task.resource_requirements:
                allocation = self.allocations.get(req.resource_type)
                if not allocation:
                    continue

                available = (
                    allocation.total_capacity
                    - allocation.allocated
                    - allocation.reserved
                )
                if available < req.amount:
                    return False

            return True

    async def reserve_resources(self, task: Task) -> bool:
        """Reserve resources for a task."""
        async with self._lock:
            # Check if all resources can be reserved
            for req in task.resource_requirements:
                allocation = self.allocations.get(req.resource_type)
                if not allocation:
                    continue

                available = (
                    allocation.total_capacity
                    - allocation.allocated
                    - allocation.reserved
                )
                if available < req.amount:
                    return False

            # Reserve resources
            for req in task.resource_requirements:
                allocation = self.allocations.get(req.resource_type)
                if allocation:
                    allocation.reserved += req.amount

            self.task_allocations[task.task_id] = task.resource_requirements.copy()
            return True

    async def allocate_resources(self, task: Task) -> bool:
        """Allocate reserved resources for execution."""
        async with self._lock:
            requirements = self.task_allocations.get(task.task_id, [])

            for req in requirements:
                allocation = self.allocations.get(req.resource_type)
                if allocation:
                    allocation.reserved -= req.amount
                    allocation.allocated += req.amount

            return True

    async def release_resources(self, task: Task):
        """Release allocated resources."""
        async with self._lock:
            requirements = self.task_allocations.get(task.task_id, [])

            for req in requirements:
                allocation = self.allocations.get(req.resource_type)
                if allocation:
                    allocation.allocated -= req.amount

            if task.task_id in self.task_allocations:
                del self.task_allocations[task.task_id]

    def get_resource_usage(self) -> Dict[str, Dict[str, float]]:
        """Get current resource usage statistics."""
        usage = {}
        for resource_type, allocation in self.allocations.items():
            usage[resource_type.value] = {
                "total": allocation.total_capacity,
                "allocated": allocation.allocated,
                "reserved": allocation.reserved,
                "available": allocation.total_capacity
                - allocation.allocated
                - allocation.reserved,
                "utilization": (allocation.allocated / allocation.total_capacity) * 100,
            }
        return usage


class DeadlockDetector:
    """Detects and prevents deadlocks in parallel execution."""

    def __init__(self):
        """Initialize deadlock detector."""
        self.wait_for_graph: Dict[str, Set[str]] = (
            {}
        )  # task_id -> set of task_ids it waits for
        self.resource_holders: Dict[ResourceType, Set[str]] = (
            {}
        )  # resource -> tasks holding it

    def add_wait_relationship(self, waiting_task: str, blocking_tasks: Set[str]):
        """Add wait relationship for deadlock detection."""
        if waiting_task not in self.wait_for_graph:
            self.wait_for_graph[waiting_task] = set()
        self.wait_for_graph[waiting_task].update(blocking_tasks)

    def remove_wait_relationship(self, task_id: str):
        """Remove task from wait relationships."""
        if task_id in self.wait_for_graph:
            del self.wait_for_graph[task_id]

        # Remove task from other tasks' wait lists
        for waiting_task, blocking_tasks in self.wait_for_graph.items():
            blocking_tasks.discard(task_id)

    def detect_deadlock(self) -> Optional[List[str]]:
        """
        Detect deadlock using cycle detection in wait-for graph.

        Returns:
            List of tasks involved in deadlock cycle, or None if no deadlock
        """
        visited = set()
        rec_stack = set()

        def dfs(task_id: str, path: List[str]) -> Optional[List[str]]:
            if task_id in rec_stack:
                # Found cycle
                cycle_start = path.index(task_id)
                return path[cycle_start:] + [task_id]

            if task_id in visited:
                return None

            visited.add(task_id)
            rec_stack.add(task_id)
            path.append(task_id)

            for blocking_task in self.wait_for_graph.get(task_id, set()):
                cycle = dfs(blocking_task, path.copy())
                if cycle:
                    return cycle

            rec_stack.remove(task_id)
            return None

        for task_id in self.wait_for_graph:
            if task_id not in visited:
                cycle = dfs(task_id, [])
                if cycle:
                    return cycle

        return None

    def prevent_deadlock(self, tasks: List[Task]) -> List[Task]:
        """
        Prevent deadlock by reordering tasks or breaking cycles.

        Args:
            tasks: List of tasks to check for deadlock potential

        Returns:
            Reordered tasks with deadlock prevention
        """

        # Simple prevention: sort by priority and resource requirements
        def task_priority(task: Task) -> Tuple[int, float]:
            # Higher resource requirements get higher priority
            total_resources = sum(req.amount for req in task.resource_requirements)
            return (len(task.dependencies), total_resources)

        return sorted(tasks, key=task_priority)


class AdaptiveParallelExecutionOrchestrator:
    """
    Adaptive orchestrator for parallel execution with intelligent strategy selection.

    Features:
    - DAG-based dependency resolution
    - Adaptive resource allocation based on system load
    - Priority-based scheduling with preemption
    - Dynamic strategy switching
    - Performance feedback loop
    - Real-time system monitoring
    - Deadlock detection and prevention
    """

    def __init__(
        self,
        max_workers: int = 4,
        resource_limits: Optional[Dict[ResourceType, float]] = None,
        enable_deadlock_detection: bool = True,
        enable_adaptive_features: bool = True,
    ):
        """
        Initialize adaptive parallel execution orchestrator.

        Args:
            max_workers: Maximum number of worker threads
            resource_limits: Resource capacity limits
            enable_deadlock_detection: Enable deadlock detection
            enable_adaptive_features: Enable adaptive scheduling and strategy selection
        """
        self.max_workers = max_workers
        self.enable_adaptive = enable_adaptive_features

        # Core components
        self.executor_pool = ThreadPoolExecutor(max_workers=max_workers)
        self.dependency_resolver = DependencyResolver()
        self.resource_manager = ResourceManager(resource_limits)
        self.deadlock_detector = (
            DeadlockDetector() if enable_deadlock_detection else None
        )

        # Adaptive components
        if self.enable_adaptive:
            from brain_researcher.services.agent.adaptive_scheduler import (
                create_adaptive_scheduler,
            )
            from brain_researcher.services.agent.strategy_selector import (
                create_strategy_selector,
            )

            self.system_monitor = create_system_monitor(collection_interval=1.0)
            self.adaptive_scheduler = create_adaptive_scheduler(
                monitor=self.system_monitor, resource_limits=resource_limits
            )
            self.strategy_selector = create_strategy_selector(self.system_monitor)
        else:
            self.system_monitor = None
            self.adaptive_scheduler = None
            self.strategy_selector = None

        # Execution state
        self.active_executions: Dict[str, Dict[str, Any]] = {}
        self.task_futures: Dict[str, asyncio.Future] = {}
        self._shutdown = False

        # Performance tracking
        self.performance_history: List[Dict[str, Any]] = []
        if self.enable_adaptive:
            from brain_researcher.services.agent.strategy_selector import (
                ExecutionStrategy,
            )

            self.current_strategy = ExecutionStrategy.BALANCED
        else:
            self.current_strategy = None
        self.strategy_start_time = time.time()

        logger.info(
            f"{'Adaptive' if enable_adaptive_features else 'Standard'} parallel orchestrator "
            f"initialized with {max_workers} workers"
        )

    async def start_adaptive_components(self):
        """Start adaptive monitoring and scheduling components."""
        if not self.enable_adaptive:
            return

        try:
            await self.system_monitor.start_monitoring()
            await self.adaptive_scheduler.start_scheduler()
            logger.info("Adaptive components started")
        except Exception as e:
            logger.error(f"Failed to start adaptive components: {e}")

    async def stop_adaptive_components(self):
        """Stop adaptive components."""
        if not self.enable_adaptive:
            return

        try:
            if self.adaptive_scheduler:
                await self.adaptive_scheduler.stop_scheduler()
            if self.system_monitor:
                await self.system_monitor.stop_monitoring()
            logger.info("Adaptive components stopped")
        except Exception as e:
            logger.error(f"Failed to stop adaptive components: {e}")

    async def execute_parallel(
        self,
        execution_graph: ExecutionGraph,
        execution_tracker: Optional[ExecutionTracker] = None,
        timeout: Optional[float] = None,
        priority: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute tasks in parallel with adaptive strategy selection.

        Args:
            execution_graph: DAG of tasks with dependencies
            execution_tracker: Optional execution tracker for progress monitoring
            timeout: Optional overall timeout in seconds
            priority: Priority level for task execution (TaskPriority enum)

        Returns:
            Dictionary mapping task_id to execution results
        """
        if self._shutdown:
            raise RuntimeError("Orchestrator is shutting down")

        # Set default priority if not provided
        if priority is None and self.enable_adaptive:
            from brain_researcher.services.agent.adaptive_scheduler import TaskPriority

            priority = TaskPriority.NORMAL

        execution_id = str(uuid4())
        start_time = time.time()

        logger.info(
            f"Starting parallel execution {execution_id} with {len(execution_graph.tasks)} tasks"
        )

        # Start adaptive components if needed
        if self.enable_adaptive and not self.system_monitor._monitoring:
            await self.start_adaptive_components()

        # Select execution strategy
        if self.enable_adaptive:
            context = await self._create_execution_context(execution_graph, priority)
            selected_strategy = self.strategy_selector.select_strategy(context)
            strategy_config = self.strategy_selector.get_strategy_config(
                selected_strategy
            )

            # Update orchestrator settings based on strategy
            self._apply_strategy_config(strategy_config)
            self.current_strategy = selected_strategy
            self.strategy_start_time = time.time()

            logger.info(f"Selected execution strategy: {selected_strategy.value}")

        # Initialize execution tracking
        if execution_tracker:
            execution_tracker.start_execution()
            for task in execution_graph.tasks:
                execution_tracker.add_step(
                    name=task.name,
                    description=f"Execute {task.tool_name}",
                    estimated_duration=task.estimated_duration,
                )

        try:
            # Validate execution graph
            self._validate_execution_graph(execution_graph)

            # Detect and prevent potential deadlocks
            if self.deadlock_detector:
                execution_graph.tasks = self.deadlock_detector.prevent_deadlock(
                    execution_graph.tasks
                )

            # Create task status tracking
            task_status = {task.task_id: task for task in execution_graph.tasks}
            results = {}
            errors = {}

            # Store execution context
            self.active_executions[execution_id] = {
                "graph": execution_graph,
                "task_status": task_status,
                "results": results,
                "errors": errors,
                "started_at": start_time,
                "tracker": execution_tracker,
            }

            # Execute tasks in batches respecting dependencies
            if self.enable_adaptive:
                await self._execute_batches_adaptive(execution_id, timeout, priority)
            else:
                await self._execute_batches(execution_id, timeout)

            # Collect final results
            context = self.active_executions[execution_id]
            results = context["results"]
            errors = context["errors"]

            # Calculate performance metrics
            total_time = time.time() - start_time
            sequential_time = sum(
                task.estimated_duration for task in execution_graph.tasks
            )
            speedup = sequential_time / total_time if total_time > 0 else 1.0

            # Update strategy performance if adaptive
            if self.enable_adaptive and self.current_strategy:
                throughput = len(results) / total_time if total_time > 0 else 0
                avg_latency = (
                    total_time / len(execution_graph.tasks)
                    if execution_graph.tasks
                    else 0
                )
                error_rate = (
                    len(errors) / len(execution_graph.tasks)
                    if execution_graph.tasks
                    else 0
                )
                resource_usage = self.resource_manager.get_resource_usage()
                avg_utilization = (
                    sum(
                        usage.get("utilization", 0) for usage in resource_usage.values()
                    )
                    / len(resource_usage)
                    if resource_usage
                    else 0
                )
                resource_efficiency = min(100, avg_utilization) / 100.0

                self.strategy_selector.update_strategy_performance(
                    strategy=self.current_strategy,
                    throughput=throughput,
                    latency=avg_latency,
                    error_rate=error_rate,
                    resource_efficiency=resource_efficiency,
                    success=len(errors) == 0,
                )

                # Record performance history
                self.performance_history.append(
                    {
                        "execution_id": execution_id,
                        "strategy": self.current_strategy.value,
                        "timestamp": time.time(),
                        "total_time": total_time,
                        "throughput": throughput,
                        "speedup": speedup,
                        "error_rate": error_rate,
                        "resource_efficiency": resource_efficiency,
                    }
                )

                # Trim history
                if len(self.performance_history) > 100:
                    self.performance_history.pop(0)

            logger.info(
                f"Parallel execution {execution_id} completed in {total_time:.2f}s "
                f"(speedup: {speedup:.2f}x, success: {len(results)}/{len(execution_graph.tasks)})"
                f"{f', strategy: {self.current_strategy.value}' if self.enable_adaptive else ''}"
            )

            if execution_tracker:
                if errors:
                    error_msg = f"Failed tasks: {', '.join(errors.keys())}"
                    execution_tracker.complete_execution(error=error_msg)
                else:
                    execution_tracker.complete_execution(result=results)

            metrics = {
                "total_time": total_time,
                "sequential_time": sequential_time,
                "speedup": speedup,
                "tasks_completed": len(results),
                "tasks_failed": len(errors),
                "resource_usage": self.resource_manager.get_resource_usage(),
            }

            if self.enable_adaptive:
                metrics["strategy"] = self.current_strategy.value
                metrics["system_health"] = self.system_monitor.get_health_status().value
                metrics["adaptive_metrics"] = self.get_adaptive_metrics()

            return {
                "execution_id": execution_id,
                "results": results,
                "errors": errors,
                "metrics": metrics,
            }

        except Exception as e:
            logger.error(f"Parallel execution {execution_id} failed: {e}")
            if execution_tracker:
                execution_tracker.complete_execution(error=str(e))
            raise
        finally:
            # Cleanup
            if execution_id in self.active_executions:
                del self.active_executions[execution_id]

    def _validate_execution_graph(self, execution_graph: ExecutionGraph):
        """Validate execution graph for parallel execution."""
        if not execution_graph.tasks:
            raise ValueError("Execution graph has no tasks")

        # Check for duplicate task IDs
        task_ids = [task.task_id for task in execution_graph.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Duplicate task IDs found in execution graph")

        # Validate dependencies
        task_id_set = set(task_ids)
        for task in execution_graph.tasks:
            for dep in task.dependencies:
                if dep not in task_id_set:
                    raise ValueError(
                        f"Task {task.task_id} has invalid dependency: {dep}"
                    )

    async def _execute_batches(self, execution_id: str, timeout: Optional[float]):
        """Execute tasks in batches respecting dependencies."""
        context = self.active_executions[execution_id]
        execution_graph = context["graph"]
        task_status = context["task_status"]

        # Create batches of tasks that can run in parallel
        batches = self.dependency_resolver.create_execution_batches(
            execution_graph.tasks
        )

        logger.info(f"Executing {len(batches)} batches for execution {execution_id}")

        batch_start_time = time.time()

        for batch_idx, batch in enumerate(batches):
            if timeout and (time.time() - batch_start_time) > timeout:
                logger.warning(f"Execution {execution_id} timed out")
                break

            batch_tasks = batch.tasks if hasattr(batch, "tasks") else batch
            logger.info(
                f"Starting batch {batch_idx + 1}/{len(batches)} with {len(batch_tasks)} tasks"
            )

            # Execute batch in parallel
            await self._execute_batch(execution_id, batch_tasks)

            # Check for failures that should stop execution
            failed_tasks = [
                task
                for task in batch_tasks
                if task_status[task.task_id].status == TaskStatus.FAILED
            ]

            if failed_tasks and self._should_stop_on_failure(failed_tasks):
                logger.error(
                    f"Stopping execution {execution_id} due to critical failures"
                )
                break

    async def _execute_batch(self, execution_id: str, batch: List[Task]):
        """Execute a batch of tasks in parallel."""
        context = self.active_executions[execution_id]
        task_status = context["task_status"]
        tracker = context.get("tracker")

        # Create coroutines for batch execution
        batch_tasks = []
        for task in batch:
            coroutine = self._execute_single_task(execution_id, task)
            batch_tasks.append(coroutine)

        # Execute batch with timeout handling
        try:
            await asyncio.gather(*batch_tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Batch execution failed: {e}")

        # Update progress
        if tracker:
            completed_count = sum(
                1
                for task in batch
                if task_status[task.task_id].status
                in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            )

            for i, task in enumerate(batch):
                if task_status[task.task_id].status == TaskStatus.COMPLETED:
                    tracker.complete_step()
                elif task_status[task.task_id].status == TaskStatus.FAILED:
                    tracker.complete_step(error=task_status[task.task_id].error)

    async def _execute_single_task(self, execution_id: str, task: Task):
        """Execute a single task with resource management."""
        context = self.active_executions[execution_id]
        task_status = context["task_status"]
        results = context["results"]
        errors = context["errors"]

        task_ref = task_status[task.task_id]

        try:
            # Wait for resource availability
            await self._wait_for_resources(task_ref)

            # Reserve resources
            if not await self.resource_manager.reserve_resources(task_ref):
                raise Exception("Failed to reserve resources")

            # Allocate resources for execution
            await self.resource_manager.allocate_resources(task_ref)

            # Update task status
            task_ref.status = TaskStatus.RUNNING
            task_ref.started_at = time.time()

            # Execute tool
            result = await self._execute_tool(task_ref)

            # Mark as completed
            task_ref.status = TaskStatus.COMPLETED
            task_ref.completed_at = time.time()
            task_ref.result = result
            results[task.task_id] = result

            logger.info(f"Task {task.task_id} completed successfully")

        except asyncio.CancelledError:
            task_ref.status = TaskStatus.CANCELLED
            task_ref.error = "Cancelled"
            task_ref.completed_at = time.time()
            errors[task.task_id] = "Cancelled"
            raise
        except Exception as e:
            # Handle failure
            task_ref.status = TaskStatus.FAILED
            task_ref.error = str(e)
            task_ref.completed_at = time.time()
            errors[task.task_id] = str(e)

            logger.error(f"Task {task.task_id} failed: {e}")

            # Retry logic
            if task_ref.retry_count < task_ref.max_retries:
                task_ref.retry_count += 1
                task_ref.status = TaskStatus.QUEUED
                logger.info(
                    f"Retrying task {task.task_id} (attempt {task_ref.retry_count + 1})"
                )

                # Recursive retry with exponential backoff
                await asyncio.sleep(min(2**task_ref.retry_count, 30))
                await self._execute_single_task(execution_id, task)

        finally:
            # Release resources
            await self.resource_manager.release_resources(task_ref)

            # Remove from deadlock detection
            if self.deadlock_detector:
                self.deadlock_detector.remove_wait_relationship(task.task_id)

    async def _wait_for_resources(self, task: Task, max_wait: float = 300.0):
        """Wait for required resources to become available."""
        for req in task.resource_requirements:
            allocation = self.resource_manager.allocations.get(req.resource_type)
            if allocation and req.amount > allocation.total_capacity:
                raise Exception(
                    f"Task {task.task_id} requires {req.amount} "
                    f"{req.resource_type.value} but capacity is {allocation.total_capacity}"
                )

        start_wait = time.time()

        while not await self.resource_manager.can_allocate(task):
            if time.time() - start_wait > max_wait:
                raise Exception(
                    f"Timeout waiting for resources for task {task.task_id}"
                )

            # Check for deadlock
            if self.deadlock_detector:
                deadlock_cycle = self.deadlock_detector.detect_deadlock()
                if deadlock_cycle and task.task_id in deadlock_cycle:
                    raise Exception(
                        f"Deadlock detected involving task {task.task_id}: {deadlock_cycle}"
                    )

            await asyncio.sleep(1.0)  # Check every second

    async def _execute_tool(self, task: Task) -> Any:
        """Execute the actual tool for a task."""
        # This would integrate with the existing tool registry
        from brain_researcher.services.tools.tool_registry import ToolRegistry

        tool_registry = ToolRegistry()
        tool = tool_registry.get_tool(task.tool_name)

        if not tool:
            raise Exception(f"Tool {task.tool_name} not found")

        run_fn = tool.run

        if asyncio.iscoroutinefunction(run_fn):
            try:
                if task.timeout:
                    return await asyncio.wait_for(
                        run_fn(**task.tool_args), timeout=task.timeout
                    )
                return await run_fn(**task.tool_args)
            except asyncio.TimeoutError:
                raise Exception(f"Task {task.task_id} timed out after {task.timeout}s")

        try:
            return await self._run_sync_tool(run_fn, task.tool_args, task.timeout)
        except asyncio.TimeoutError:
            raise Exception(f"Task {task.task_id} timed out after {task.timeout}s")

    async def _run_sync_tool(
        self,
        run_fn: Any,
        tool_args: Dict[str, Any],
        timeout: Optional[float],
    ) -> Any:
        """Run a sync tool in a background thread with async polling."""
        result_holder: Dict[str, Any] = {"done": False, "result": None, "error": None}

        def _worker():
            try:
                result_holder["result"] = run_fn(**tool_args)
            except Exception as exc:  # pragma: no cover - pass through
                result_holder["error"] = exc
            finally:
                result_holder["done"] = True

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        start_time = time.time()
        while not result_holder["done"]:
            if timeout and (time.time() - start_time) > timeout:
                raise asyncio.TimeoutError()
            await asyncio.sleep(0.01)

        if result_holder["error"] is not None:
            raise result_holder["error"]

        return result_holder["result"]

    def _should_stop_on_failure(self, failed_tasks: List[Task]) -> bool:
        """Determine if execution should stop due to failures."""
        # Stop if more than 50% of batch failed
        return len(failed_tasks) > len(failed_tasks) * 0.5

    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a running execution."""
        if execution_id not in self.active_executions:
            return None

        context = self.active_executions[execution_id]
        task_status = context["task_status"]

        status_counts = {}
        for status in TaskStatus:
            status_counts[status.value] = sum(
                1 for task in task_status.values() if task.status == status
            )

        return {
            "execution_id": execution_id,
            "started_at": context["started_at"],
            "task_counts": status_counts,
            "results_count": len(context["results"]),
            "errors_count": len(context["errors"]),
            "resource_usage": self.resource_manager.get_resource_usage(),
        }

    def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running execution."""
        if execution_id not in self.active_executions:
            return False

        context = self.active_executions[execution_id]
        task_status = context["task_status"]

        # Mark running tasks as cancelled
        for task in task_status.values():
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.CANCELLED

        logger.info(f"Cancelled execution {execution_id}")
        return True

    async def _create_execution_context(
        self, execution_graph: ExecutionGraph, priority: Any
    ) -> Any:
        """Create execution context for strategy selection."""
        from brain_researcher.services.agent.strategy_selector import ExecutionContext

        metrics = self.system_monitor.get_system_metrics()
        if not metrics:
            # Default metrics if monitoring not available
            from brain_researcher.services.agent.system_monitor import SystemMetrics

            metrics = SystemMetrics(
                timestamp=time.time(),
                cpu_usage=50.0,
                memory_usage=50.0,
                memory_available=16.0,
                disk_io_read=10.0,
                disk_io_write=10.0,
                network_sent=5.0,
                network_recv=5.0,
                load_average=(1.0, 1.0, 1.0),
                active_processes=100,
            )

        health = self.system_monitor.get_health_status()
        resource_util = self.system_monitor.get_resource_utilization()

        # Calculate metrics from execution graph
        avg_duration = sum(
            task.estimated_duration for task in execution_graph.tasks
        ) / len(execution_graph.tasks)
        queue_depth = len(execution_graph.tasks)

        # Calculate error rate from recent history
        recent_executions = [
            h
            for h in self.performance_history
            if time.time() - h["timestamp"] < 3600  # Last hour
        ]
        error_rate = (
            sum(h["error_rate"] for h in recent_executions) / len(recent_executions)
            if recent_executions
            else 0.0
        )

        # Calculate throughput
        throughput = (
            sum(h["throughput"] for h in recent_executions) / len(recent_executions)
            if recent_executions
            else 0.0
        )

        return ExecutionContext(
            system_metrics=metrics,
            system_health=health,
            queue_depth=queue_depth,
            average_task_duration=avg_duration,
            current_throughput=throughput,
            error_rate=error_rate,
            resource_utilization=resource_util,
            user_priority=priority,
            workload_type="mixed",  # Could be enhanced with workload analysis
        )

    def _apply_strategy_config(self, config):
        """Apply strategy configuration to orchestrator settings."""
        # Adjust max workers based on strategy
        new_max_workers = min(config.max_parallel, self.max_workers)
        if new_max_workers != self.executor_pool._max_workers:
            # Note: ThreadPoolExecutor doesn't support dynamic resizing
            # In a production system, you'd implement a more sophisticated approach
            logger.info(
                f"Strategy suggests {new_max_workers} workers (current: {self.executor_pool._max_workers})"
            )

    async def _execute_batches_adaptive(
        self, execution_id: str, timeout: Optional[float], priority: Any
    ):
        """Execute batches with adaptive scheduling."""
        context = self.active_executions[execution_id]
        execution_graph = context["graph"]

        # Use adaptive scheduler for task scheduling
        for task in execution_graph.tasks:
            await self.adaptive_scheduler.schedule_task(
                task=task,
                priority=priority,
                deadline=time.time() + timeout if timeout else None,
            )

        # Monitor execution and adapt as needed
        start_time = time.time()
        while True:
            # Check if all tasks completed
            queue_status = self.adaptive_scheduler.get_queue_status()
            if queue_status["queued_tasks"] == 0 and queue_status["running_tasks"] == 0:
                break

            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                logger.warning(f"Execution {execution_id} timed out")
                break

            # Periodic strategy re-evaluation
            if time.time() - self.strategy_start_time > 60:  # Re-evaluate every minute
                new_context = await self._create_execution_context(
                    execution_graph, priority
                )
                new_strategy = self.strategy_selector.select_strategy(new_context)

                if new_strategy != self.current_strategy:
                    logger.info(
                        f"Strategy changed from {self.current_strategy.value} to {new_strategy.value}"
                    )
                    self.current_strategy = new_strategy
                    self.strategy_start_time = time.time()

                    # Apply new strategy configuration
                    strategy_config = self.strategy_selector.get_strategy_config(
                        new_strategy
                    )
                    self._apply_strategy_config(strategy_config)

            await asyncio.sleep(1.0)  # Check every second

    def get_adaptive_metrics(self) -> Dict[str, Any]:
        """Get adaptive execution metrics."""
        if not self.enable_adaptive:
            return {}

        metrics = {}

        # System monitor metrics
        if self.system_monitor:
            current_metrics = self.system_monitor.get_system_metrics()
            if current_metrics:
                metrics["system"] = {
                    "cpu_usage": current_metrics.cpu_usage,
                    "memory_usage": current_metrics.memory_usage,
                    "load_average": current_metrics.load_average[0],
                    "health": self.system_monitor.get_health_status().value,
                }

        # Scheduler metrics
        if self.adaptive_scheduler:
            metrics["scheduler"] = self.adaptive_scheduler.get_performance_metrics()

        # Strategy metrics
        if self.strategy_selector:
            metrics["strategy"] = self.strategy_selector.get_selection_metrics()

        # Performance history summary
        if self.performance_history:
            recent = [
                h
                for h in self.performance_history
                if time.time() - h["timestamp"] < 3600
            ]
            if recent:
                metrics["performance"] = {
                    "avg_throughput": sum(h["throughput"] for h in recent)
                    / len(recent),
                    "avg_speedup": sum(h["speedup"] for h in recent) / len(recent),
                    "avg_error_rate": sum(h["error_rate"] for h in recent)
                    / len(recent),
                    "executions_last_hour": len(recent),
                }

        return metrics

    def get_current_strategy(self) -> Optional[Any]:
        """Get current execution strategy."""
        return self.current_strategy

    def force_strategy(self, strategy: Any):
        """Force a specific execution strategy."""
        if not self.enable_adaptive:
            logger.warning("Cannot force strategy: adaptive features disabled")
            return

        self.strategy_selector.force_strategy(strategy)
        self.current_strategy = strategy
        self.strategy_start_time = time.time()
        logger.info(f"Forced execution strategy to {strategy.value}")

    def get_strategy_recommendations(self) -> Dict[str, Any]:
        """Get strategy recommendations for current conditions."""
        if not self.enable_adaptive:
            return {}

        # Create mock execution context
        metrics = self.system_monitor.get_system_metrics()
        if not metrics:
            return {}

        from brain_researcher.services.agent.adaptive_scheduler import TaskPriority
        from brain_researcher.services.agent.strategy_selector import ExecutionContext

        context = ExecutionContext(
            system_metrics=metrics,
            system_health=self.system_monitor.get_health_status(),
            queue_depth=0,
            average_task_duration=60.0,
            current_throughput=0.0,
            error_rate=0.0,
            resource_utilization=self.system_monitor.get_resource_utilization(),
            user_priority=TaskPriority.NORMAL,
        )

        return self.strategy_selector.get_strategy_recommendations(context)

    async def shutdown(self, wait_for_completion: bool = True):
        """Shutdown the orchestrator."""
        self._shutdown = True

        # Stop adaptive components
        if self.enable_adaptive:
            await self.stop_adaptive_components()

        if wait_for_completion:
            # Wait for active executions to complete
            while self.active_executions:
                await asyncio.sleep(0.1)

        # Shutdown thread pool
        self.executor_pool.shutdown(wait=wait_for_completion)

        logger.info("Adaptive parallel execution orchestrator shutdown complete")


# Factory functions
def create_parallel_orchestrator(
    max_workers: int = 4,
    resource_limits: Optional[Dict[ResourceType, float]] = None,
    enable_adaptive: bool = True,
) -> AdaptiveParallelExecutionOrchestrator:
    """
    Create an adaptive parallel execution orchestrator.

    Args:
        max_workers: Maximum number of worker threads
        resource_limits: Resource capacity limits
        enable_adaptive: Enable adaptive features

    Returns:
        Configured orchestrator instance
    """
    return AdaptiveParallelExecutionOrchestrator(
        max_workers=max_workers,
        resource_limits=resource_limits,
        enable_adaptive_features=enable_adaptive,
    )


# Backward compatibility alias
ParallelExecutor = AdaptiveParallelExecutionOrchestrator
ParallelExecutionOrchestrator = AdaptiveParallelExecutionOrchestrator
