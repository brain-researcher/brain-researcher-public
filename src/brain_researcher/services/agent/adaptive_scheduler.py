"""
Adaptive Scheduler for Priority-based Task Scheduling (AGENT-021)

This module implements priority-based task scheduling with preemption capabilities,
load balancing, and adaptive resource allocation based on system conditions.
"""

import asyncio
import heapq
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brain_researcher.services.agent.parallel_executor import (
    ResourceType,
    Task,
    TaskStatus,
)
from brain_researcher.services.agent.system_monitor import SystemHealth, SystemMonitor

logger = logging.getLogger(__name__)


class TaskPriority(int, Enum):
    """Task priority levels (lower number = higher priority)."""

    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5


class SchedulingPolicy(str, Enum):
    """Scheduling policy types."""

    PRIORITY_FIRST = "priority_first"
    FAIR_SHARE = "fair_share"
    SHORTEST_JOB_FIRST = "shortest_job_first"
    LOAD_BALANCED = "load_balanced"


@dataclass
class ScheduledTask:
    """Task wrapper with scheduling metadata."""

    task: Task
    priority: TaskPriority
    submission_time: float
    deadline: float | None = None
    preemptible: bool = True
    resource_weight: float = 1.0  # Multiplier for resource requirements
    retry_penalty: float = 1.0  # Increases with each retry

    def __post_init__(self):
        """Calculate priority score for heap ordering."""
        self.priority_score = self._calculate_priority_score()

    def _calculate_priority_score(self) -> float:
        """Calculate composite priority score (lower = higher priority)."""
        base_score = self.priority.value

        # Age bonus (waiting time reduces priority score)
        age_bonus = min(
            (time.time() - self.submission_time) / 300.0, 2.0
        )  # Max 2 points for 5min wait

        # Deadline urgency
        deadline_urgency = 0.0
        if self.deadline:
            time_to_deadline = self.deadline - time.time()
            if time_to_deadline > 0:
                deadline_urgency = max(
                    0, 3.0 - (time_to_deadline / 600.0)
                )  # Urgent if <10min

        # Retry penalty
        retry_penalty = (self.retry_penalty - 1.0) * 0.5

        return base_score - age_bonus - deadline_urgency + retry_penalty

    def __lt__(self, other):
        """Priority queue ordering (lower score = higher priority)."""
        return self.priority_score < other.priority_score


@dataclass
class ResourcePool:
    """Resource pool with allocation tracking."""

    resource_type: ResourceType
    total_capacity: float
    allocated: float = 0.0
    reserved: float = 0.0
    allocations: dict[str, float] = field(default_factory=dict)  # task_id -> amount

    @property
    def available(self) -> float:
        """Get available capacity."""
        return max(0.0, self.total_capacity - self.allocated - self.reserved)

    @property
    def utilization(self) -> float:
        """Get utilization percentage."""
        return (
            (self.allocated / self.total_capacity) * 100
            if self.total_capacity > 0
            else 0.0
        )


class PreemptionManager:
    """Manages task preemption and resumption."""

    def __init__(self):
        """Initialize preemption manager."""
        self.preempted_tasks: dict[str, ScheduledTask] = {}
        self.preemption_history: list[dict[str, Any]] = []

    def can_preempt(self, running_task: ScheduledTask, new_task: ScheduledTask) -> bool:
        """Check if running task can be preempted for new task."""
        if not running_task.preemptible:
            return False

        # Preempt if new task has significantly higher priority
        priority_diff = running_task.priority.value - new_task.priority.value

        # Consider deadlines
        if new_task.deadline:
            time_to_deadline = new_task.deadline - time.time()
            if time_to_deadline < 300:  # Less than 5 minutes
                return priority_diff >= 0  # Preempt if equal or lower priority

        return priority_diff >= 2  # Preempt only if 2+ priority levels higher

    def preempt_task(self, task: ScheduledTask, reason: str) -> bool:
        """Preempt a running task."""
        try:
            # Stop the task execution
            task.task.status = TaskStatus.BLOCKED

            # Store for later resumption
            self.preempted_tasks[task.task.task_id] = task

            # Record preemption
            self.preemption_history.append(
                {
                    "task_id": task.task.task_id,
                    "reason": reason,
                    "timestamp": time.time(),
                    "priority": task.priority.value,
                }
            )

            logger.info(f"Preempted task {task.task.task_id}: {reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to preempt task {task.task.task_id}: {e}")
            return False

    def resume_task(self, task_id: str) -> ScheduledTask | None:
        """Resume a preempted task."""
        if task_id not in self.preempted_tasks:
            return None

        task = self.preempted_tasks.pop(task_id)
        task.task.status = TaskStatus.QUEUED

        # Add small retry penalty for preemption
        task.retry_penalty *= 1.1
        task.priority_score = task._calculate_priority_score()

        logger.info(f"Resumed preempted task {task_id}")
        return task

    def get_preemption_stats(self) -> dict[str, Any]:
        """Get preemption statistics."""
        if not self.preemption_history:
            return {"total_preemptions": 0}

        recent_preemptions = [
            p
            for p in self.preemption_history
            if time.time() - p["timestamp"] < 3600  # Last hour
        ]

        return {
            "total_preemptions": len(self.preemption_history),
            "recent_preemptions": len(recent_preemptions),
            "preempted_tasks_waiting": len(self.preempted_tasks),
            "avg_preemptions_per_hour": len(recent_preemptions),
        }


class LoadBalancer:
    """Balances load across available resources."""

    def __init__(self, resource_pools: dict[ResourceType, ResourcePool]):
        """Initialize load balancer."""
        self.resource_pools = resource_pools
        self.balancing_strategies = {
            "round_robin": self._round_robin_balance,
            "least_loaded": self._least_loaded_balance,
            "resource_aware": self._resource_aware_balance,
        }
        self._last_assignment = 0

    def select_resource_assignment(
        self, task: ScheduledTask, strategy: str = "resource_aware"
    ) -> dict[ResourceType, float]:
        """Select optimal resource assignment for task."""
        balance_func = self.balancing_strategies.get(
            strategy, self._resource_aware_balance
        )
        return balance_func(task)

    def _round_robin_balance(self, task: ScheduledTask) -> dict[ResourceType, float]:
        """Simple round-robin resource assignment."""
        assignment = {}
        for req in task.task.resource_requirements:
            # Use base requirement without load balancing adjustment
            assignment[req.resource_type] = req.amount
        return assignment

    def _least_loaded_balance(self, task: ScheduledTask) -> dict[ResourceType, float]:
        """Assign to least loaded resources."""
        assignment = {}
        for req in task.task.resource_requirements:
            pool = self.resource_pools.get(req.resource_type)
            if pool and pool.utilization < 80:  # Prefer under-utilized resources
                assignment[req.resource_type] = req.amount
            else:
                # Scale down requirement if resource is heavily utilized
                assignment[req.resource_type] = req.amount * 0.8
        return assignment

    def _resource_aware_balance(self, task: ScheduledTask) -> dict[ResourceType, float]:
        """Balance based on resource availability and task priority."""
        assignment = {}
        priority_multiplier = (
            1.0 + (5 - task.priority.value) * 0.2
        )  # Higher priority gets more resources

        for req in task.task.resource_requirements:
            pool = self.resource_pools.get(req.resource_type)
            if not pool:
                assignment[req.resource_type] = req.amount
                continue

            # Calculate scaling factor based on availability
            if pool.utilization < 50:
                scale_factor = priority_multiplier  # Full resources for low utilization
            elif pool.utilization < 80:
                scale_factor = (
                    priority_multiplier * 0.8
                )  # Reduce for medium utilization
            else:
                scale_factor = (
                    priority_multiplier * 0.6
                )  # Further reduce for high utilization

            assignment[req.resource_type] = (
                req.amount * scale_factor * task.resource_weight
            )

        return assignment

    def get_load_statistics(self) -> dict[str, Any]:
        """Get load balancing statistics."""
        stats = {}
        for resource_type, pool in self.resource_pools.items():
            stats[resource_type.value] = {
                "utilization": pool.utilization,
                "available": pool.available,
                "allocated": pool.allocated,
                "total": pool.total_capacity,
            }

        # Overall system utilization
        total_util = sum(pool.utilization for pool in self.resource_pools.values())
        avg_util = total_util / len(self.resource_pools) if self.resource_pools else 0

        stats["overall"] = {
            "average_utilization": avg_util,
            "hottest_resource": (
                max(
                    self.resource_pools.items(),
                    key=lambda x: x[1].utilization,
                    default=(None, None),
                )[0].value
                if self.resource_pools
                else None
            ),
        }

        return stats


class AdaptiveScheduler:
    """
    Adaptive scheduler with priority-based queuing and preemption.

    Features:
    - Priority queue with multiple priority levels
    - Preemption based on priority and deadlines
    - Load balancing across resources
    - Adaptive scheduling based on system load
    - Performance feedback loop
    """

    def __init__(
        self,
        monitor: SystemMonitor,
        resource_limits: dict[ResourceType, float] | None = None,
        scheduling_policy: SchedulingPolicy = SchedulingPolicy.PRIORITY_FIRST,
    ):
        """
        Initialize adaptive scheduler.

        Args:
            monitor: System monitor for load information
            resource_limits: Resource capacity limits
            scheduling_policy: Default scheduling policy
        """
        self.monitor = monitor
        self.scheduling_policy = scheduling_policy

        # Initialize resource pools
        default_limits = {
            ResourceType.CPU: 8.0,
            ResourceType.GPU: 1.0,
            ResourceType.MEMORY: 32.0,
            ResourceType.STORAGE: 1000.0,
            ResourceType.NETWORK: 1000.0,
        }
        limits = resource_limits or default_limits
        self.resource_pools = {
            rt: ResourcePool(rt, capacity) for rt, capacity in limits.items()
        }

        # Initialize components
        self.preemption_manager = PreemptionManager()
        self.load_balancer = LoadBalancer(self.resource_pools)

        # Task queues
        self.priority_queue: list[ScheduledTask] = []
        self.running_tasks: dict[str, ScheduledTask] = {}
        self.completed_tasks: dict[str, ScheduledTask] = {}

        # Scheduling state
        self._scheduling_lock = asyncio.Lock()
        self._scheduler_running = False
        self._scheduler_task: asyncio.Task | None = None

        # Performance tracking
        self.scheduling_stats = {
            "tasks_scheduled": 0,
            "tasks_preempted": 0,
            "avg_wait_time": 0.0,
            "avg_execution_time": 0.0,
            "throughput": 0.0,
        }

        logger.info(
            f"Adaptive scheduler initialized with {scheduling_policy.value} policy"
        )

    async def start_scheduler(self):
        """Start the adaptive scheduler loop."""
        if self._scheduler_running:
            logger.warning("Scheduler already running")
            return

        self._scheduler_running = True
        self._scheduler_task = asyncio.create_task(self._scheduling_loop())
        logger.info("Adaptive scheduler started")

    async def stop_scheduler(self):
        """Stop the scheduler."""
        if not self._scheduler_running:
            return

        self._scheduler_running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        logger.info("Adaptive scheduler stopped")

    async def schedule_task(
        self,
        task: Task,
        priority: TaskPriority = TaskPriority.NORMAL,
        deadline: float | None = None,
        preemptible: bool = True,
    ) -> str:
        """
        Schedule a task for execution.

        Args:
            task: Task to schedule
            priority: Task priority level
            deadline: Optional deadline timestamp
            preemptible: Whether task can be preempted

        Returns:
            Task ID for tracking
        """
        async with self._scheduling_lock:
            # Create scheduled task wrapper
            scheduled_task = ScheduledTask(
                task=task,
                priority=priority,
                submission_time=time.time(),
                deadline=deadline,
                preemptible=preemptible,
            )

            # Add to priority queue
            heapq.heappush(self.priority_queue, scheduled_task)

            # Update queue depth in monitor
            self.monitor.update_queue_depth(len(self.priority_queue))

            self.scheduling_stats["tasks_scheduled"] += 1

            logger.info(
                f"Scheduled task {task.task_id} with priority {priority.name} "
                f"(queue depth: {len(self.priority_queue)})"
            )

            return task.task_id

    async def _scheduling_loop(self):
        """Main scheduling loop."""
        try:
            while self._scheduler_running:
                await self._schedule_iteration()
                await asyncio.sleep(0.5)  # Schedule every 500ms
        except asyncio.CancelledError:
            logger.info("Scheduling loop cancelled")
        except Exception as e:
            logger.error(f"Scheduling loop error: {e}")

    async def _schedule_iteration(self):
        """Single iteration of scheduling logic."""
        async with self._scheduling_lock:
            # Check system health
            system_health = self.monitor.get_health_status()

            # Adapt scheduling based on system state
            if system_health == SystemHealth.CRITICAL:
                # Emergency mode: only critical tasks
                await self._emergency_scheduling()
            elif system_health == SystemHealth.STRESSED:
                # Conservative mode: reduce parallelism
                await self._conservative_scheduling()
            else:
                # Normal or aggressive scheduling
                await self._normal_scheduling()

            # Check for preemption opportunities
            await self._check_preemption()

            # Update statistics
            self._update_statistics()

    async def _emergency_scheduling(self):
        """Emergency scheduling mode - only critical tasks."""
        # Preempt all non-critical running tasks
        tasks_to_preempt = [
            task
            for task in self.running_tasks.values()
            if task.priority != TaskPriority.CRITICAL and task.preemptible
        ]

        for task in tasks_to_preempt:
            self.preemption_manager.preempt_task(task, "Emergency: system critical")
            del self.running_tasks[task.task.task_id]

        # Only schedule critical tasks
        await self._schedule_next_tasks(priority_filter=TaskPriority.CRITICAL)

    async def _conservative_scheduling(self):
        """Conservative scheduling mode - reduced parallelism."""
        # Limit concurrent tasks based on system load
        max_concurrent = max(1, len(self.running_tasks) // 2)

        if len(self.running_tasks) >= max_concurrent:
            return

        # Schedule high priority tasks only
        await self._schedule_next_tasks(
            max_tasks=max_concurrent - len(self.running_tasks),
            priority_filter=TaskPriority.HIGH,
        )

    async def _normal_scheduling(self):
        """Normal scheduling mode."""
        # Calculate optimal concurrency based on resources
        max_concurrent = self._calculate_optimal_concurrency()

        if len(self.running_tasks) >= max_concurrent:
            return

        # Schedule next batch of tasks
        await self._schedule_next_tasks(
            max_tasks=max_concurrent - len(self.running_tasks)
        )

    async def _schedule_next_tasks(
        self,
        max_tasks: int | None = None,
        priority_filter: TaskPriority | None = None,
    ):
        """Schedule next tasks from the queue."""
        scheduled_count = 0
        max_to_schedule = max_tasks or 4

        # Get tasks that can be scheduled
        schedulable_tasks = []
        temp_queue = []

        while self.priority_queue and len(schedulable_tasks) < max_to_schedule:
            task = heapq.heappop(self.priority_queue)

            # Apply priority filter
            if priority_filter and task.priority.value > priority_filter.value:
                temp_queue.append(task)
                continue

            # Check resource availability
            if self._can_allocate_resources(task):
                schedulable_tasks.append(task)
            else:
                temp_queue.append(task)

        # Restore unscheduled tasks to queue
        for task in temp_queue:
            heapq.heappush(self.priority_queue, task)

        # Start schedulable tasks
        for task in schedulable_tasks:
            await self._start_task(task)
            scheduled_count += 1

        if scheduled_count > 0:
            logger.info(f"Scheduled {scheduled_count} tasks")

    def _can_allocate_resources(self, task: ScheduledTask) -> bool:
        """Check if resources can be allocated for task."""
        for req in task.task.resource_requirements:
            pool = self.resource_pools.get(req.resource_type)
            if not pool:
                continue

            if pool.available < req.amount * task.resource_weight:
                return False

        return True

    async def _start_task(self, task: ScheduledTask):
        """Start executing a task."""
        # Allocate resources
        assignment = self.load_balancer.select_resource_assignment(task)
        for resource_type, amount in assignment.items():
            pool = self.resource_pools.get(resource_type)
            if pool:
                pool.allocated += amount
                pool.allocations[task.task.task_id] = amount

        # Update task status
        task.task.status = TaskStatus.RUNNING
        task.task.started_at = time.time()

        # Add to running tasks
        self.running_tasks[task.task.task_id] = task

        logger.info(f"Started task {task.task.task_id}")

    async def _check_preemption(self):
        """Check for preemption opportunities."""
        if not self.priority_queue:
            return

        # Get highest priority waiting task
        highest_waiting = min(self.priority_queue)

        # Find preemption candidates
        for running_task in list(self.running_tasks.values()):
            if self.preemption_manager.can_preempt(running_task, highest_waiting):
                # Preempt the running task
                self.preemption_manager.preempt_task(
                    running_task,
                    f"Higher priority task waiting: {highest_waiting.task.task_id}",
                )

                # Release resources
                self._release_task_resources(running_task)
                del self.running_tasks[running_task.task.task_id]

                # Schedule the higher priority task
                heapq.heappop(self.priority_queue)  # Remove from queue
                await self._start_task(highest_waiting)
                break

    def _release_task_resources(self, task: ScheduledTask):
        """Release resources allocated to a task."""
        for _resource_type, pool in self.resource_pools.items():
            if task.task.task_id in pool.allocations:
                amount = pool.allocations.pop(task.task.task_id)
                pool.allocated -= amount

    def _calculate_optimal_concurrency(self) -> int:
        """Calculate optimal number of concurrent tasks."""
        metrics = self.monitor.get_system_metrics()
        if not metrics:
            return 4  # Default

        # Base concurrency on available resources
        cpu_capacity = max(1, int((100 - metrics.cpu_usage) / 100 * 8))
        memory_capacity = max(1, int((100 - metrics.memory_usage) / 100 * 4))

        # Conservative estimate
        optimal = min(cpu_capacity, memory_capacity)

        # Adjust based on system health
        health = self.monitor.get_health_status()
        if health == SystemHealth.HEALTHY:
            optimal = min(optimal * 2, 8)  # Allow higher concurrency
        elif health == SystemHealth.MODERATE:
            optimal = optimal  # Keep calculated value
        else:
            optimal = max(1, optimal // 2)  # Reduce concurrency

        return optimal

    def _update_statistics(self):
        """Update scheduling statistics."""
        current_time = time.time()

        # Calculate throughput (tasks completed in last minute)
        recent_completions = [
            task
            for task in self.completed_tasks.values()
            if task.task.completed_at and (current_time - task.task.completed_at) < 60
        ]
        self.scheduling_stats["throughput"] = len(recent_completions)

        # Update queue depth
        self.monitor.update_queue_depth(len(self.priority_queue))

    async def complete_task(self, task_id: str, result: Any = None, error: str = None):
        """Mark a task as completed."""
        async with self._scheduling_lock:
            if task_id not in self.running_tasks:
                logger.warning(f"Attempted to complete unknown task: {task_id}")
                return

            task = self.running_tasks.pop(task_id)

            # Update task
            task.task.completed_at = time.time()
            if error:
                task.task.status = TaskStatus.FAILED
                task.task.error = error
            else:
                task.task.status = TaskStatus.COMPLETED
                task.task.result = result

            # Release resources
            self._release_task_resources(task)

            # Move to completed
            self.completed_tasks[task_id] = task

            # Update statistics
            if task.task.started_at:
                execution_time = task.task.completed_at - task.task.started_at
                wait_time = task.task.started_at - task.submission_time

                # Update running averages
                self.scheduling_stats["avg_execution_time"] = (
                    self.scheduling_stats["avg_execution_time"] * 0.9
                    + execution_time * 0.1
                )
                self.scheduling_stats["avg_wait_time"] = (
                    self.scheduling_stats["avg_wait_time"] * 0.9 + wait_time * 0.1
                )

            logger.info(
                f"Completed task {task_id} ({'success' if not error else 'failure'})"
            )

    def get_queue_status(self) -> dict[str, Any]:
        """Get current queue status."""
        return {
            "queued_tasks": len(self.priority_queue),
            "running_tasks": len(self.running_tasks),
            "completed_tasks": len(self.completed_tasks),
            "queue_by_priority": {
                priority.name: sum(
                    1 for t in self.priority_queue if t.priority == priority
                )
                for priority in TaskPriority
            },
        }

    def get_performance_metrics(self) -> dict[str, Any]:
        """Get scheduler performance metrics."""
        metrics = self.scheduling_stats.copy()
        metrics.update(
            {
                "preemption_stats": self.preemption_manager.get_preemption_stats(),
                "load_balancing": self.load_balancer.get_load_statistics(),
                "queue_status": self.get_queue_status(),
            }
        )
        return metrics

    async def adjust_task_priority(
        self, task_id: str, new_priority: TaskPriority
    ) -> bool:
        """Adjust priority of a queued task."""
        async with self._scheduling_lock:
            # Find task in queue
            updated_queue = []
            task_found = False

            for task in self.priority_queue:
                if task.task.task_id == task_id:
                    task.priority = new_priority
                    task.priority_score = task._calculate_priority_score()
                    task_found = True
                updated_queue.append(task)

            if task_found:
                # Rebuild heap
                self.priority_queue = updated_queue
                heapq.heapify(self.priority_queue)
                logger.info(f"Updated task {task_id} priority to {new_priority.name}")
                return True

            return False


# Factory function
def create_adaptive_scheduler(
    monitor: SystemMonitor,
    resource_limits: dict[ResourceType, float] | None = None,
    scheduling_policy: SchedulingPolicy = SchedulingPolicy.PRIORITY_FIRST,
) -> AdaptiveScheduler:
    """
    Create an adaptive scheduler instance.

    Args:
        monitor: System monitor for load information
        resource_limits: Resource capacity limits
        scheduling_policy: Scheduling policy to use

    Returns:
        Configured AdaptiveScheduler instance
    """
    return AdaptiveScheduler(
        monitor=monitor,
        resource_limits=resource_limits,
        scheduling_policy=scheduling_policy,
    )
