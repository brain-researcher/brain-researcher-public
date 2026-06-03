"""
Core Resource Manager for Brain Researcher Agent.

Manages CPU and memory allocation for concurrent tool execution.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from brain_researcher.services.agent.resources.queue_manager import (
    Priority,
    QueueEntry,
    QueueManager,
)
from brain_researcher.services.agent.resources.resource_limits import get_tool_profile

logger = logging.getLogger(__name__)


@dataclass
class ResourceAllocation:
    """Represents allocated resources for a tool execution."""

    allocation_id: str
    execution_id: str
    tool_name: str
    cpu_cores: float
    memory_gb: float
    gpu_count: int = 0
    allocated_at: datetime = field(default_factory=datetime.now)
    released_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Check if allocation is still active."""
        return self.released_at is None

    @property
    def duration(self) -> timedelta | None:
        """Get allocation duration."""
        if self.released_at:
            return self.released_at - self.allocated_at
        return datetime.now() - self.allocated_at


class ResourcePool:
    """Manages available system resources."""

    def __init__(
        self, max_cpu_cores: float = 4.0, max_memory_gb: float = 8.0, max_gpus: int = 0
    ):
        """
        Initialize resource pool.

        Args:
            max_cpu_cores: Maximum CPU cores available
            max_memory_gb: Maximum memory in GB
            max_gpus: Maximum GPU count
        """
        self.max_cpu_cores = max_cpu_cores
        self.max_memory_gb = max_memory_gb
        self.max_gpus = max_gpus

        # Available resources
        self.available_cpu = max_cpu_cores
        self.available_memory = max_memory_gb
        self.available_gpus = max_gpus

        # Thread safety
        self._lock = threading.RLock()

        logger.info(
            f"Resource pool initialized: {max_cpu_cores} CPU cores, "
            f"{max_memory_gb}GB memory, {max_gpus} GPUs"
        )

    def can_allocate(
        self, cpu_cores: float, memory_gb: float, gpu_count: int = 0
    ) -> bool:
        """Check if resources can be allocated."""
        with self._lock:
            return (
                self.available_cpu >= cpu_cores
                and self.available_memory >= memory_gb
                and self.available_gpus >= gpu_count
            )

    def allocate(self, cpu_cores: float, memory_gb: float, gpu_count: int = 0) -> bool:
        """
        Allocate resources from pool.

        Returns:
            True if allocation successful, False otherwise
        """
        with self._lock:
            if not self.can_allocate(cpu_cores, memory_gb, gpu_count):
                return False

            self.available_cpu -= cpu_cores
            self.available_memory -= memory_gb
            self.available_gpus -= gpu_count

            logger.debug(
                f"Allocated: {cpu_cores} CPU, {memory_gb}GB memory, {gpu_count} GPU. "
                f"Available: {self.available_cpu} CPU, {self.available_memory}GB memory"
            )
            return True

    def release(self, cpu_cores: float, memory_gb: float, gpu_count: int = 0):
        """Release resources back to pool."""
        with self._lock:
            self.available_cpu = min(self.available_cpu + cpu_cores, self.max_cpu_cores)
            self.available_memory = min(
                self.available_memory + memory_gb, self.max_memory_gb
            )
            self.available_gpus = min(self.available_gpus + gpu_count, self.max_gpus)

            logger.debug(
                f"Released: {cpu_cores} CPU, {memory_gb}GB memory. "
                f"Available: {self.available_cpu} CPU, {self.available_memory}GB memory"
            )

    def get_utilization(self) -> dict[str, float]:
        """Get current resource utilization percentages."""
        with self._lock:
            return {
                "cpu_utilization": (1 - self.available_cpu / self.max_cpu_cores) * 100,
                "memory_utilization": (1 - self.available_memory / self.max_memory_gb)
                * 100,
                "gpu_utilization": (
                    (1 - self.available_gpus / max(1, self.max_gpus)) * 100
                    if self.max_gpus > 0
                    else 0
                ),
            }

    def get_available(self) -> dict[str, float]:
        """Get available resources."""
        with self._lock:
            return {
                "cpu_cores": self.available_cpu,
                "memory_gb": self.available_memory,
                "gpus": self.available_gpus,
            }


class ResourceManager:
    """Central resource management system."""

    def __init__(
        self,
        max_cpu_cores: float = 4.0,
        max_memory_gb: float = 8.0,
        max_gpus: int = 0,
        enable_queueing: bool = True,
        max_queue_size: int = 100,
    ):
        """
        Initialize resource manager.

        Args:
            max_cpu_cores: Maximum CPU cores to manage
            max_memory_gb: Maximum memory in GB
            max_gpus: Maximum GPU count
            enable_queueing: Enable request queueing
            max_queue_size: Maximum queue size
        """
        self.pool = ResourcePool(max_cpu_cores, max_memory_gb, max_gpus)
        self.queue_manager = (
            QueueManager(max_size=max_queue_size) if enable_queueing else None
        )

        # Track active allocations
        self.allocations: dict[str, ResourceAllocation] = {}
        self.execution_to_allocation: dict[str, str] = {}

        # Thread safety
        self._lock = threading.RLock()

        # Cleanup thread for timed-out allocations
        self._cleanup_interval = 60  # seconds
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

        logger.info(
            f"ResourceManager initialized with {max_cpu_cores} CPU cores, "
            f"{max_memory_gb}GB memory, queueing={'enabled' if enable_queueing else 'disabled'}"
        )

    def request_resources(
        self,
        tool_name: str,
        execution_id: str,
        priority: Priority = Priority.NORMAL,
        timeout: float | None = None,
    ) -> ResourceAllocation | None:
        """
        Request resources for tool execution.

        Args:
            tool_name: Name of the tool
            execution_id: Unique execution ID
            priority: Request priority
            timeout: Maximum time to wait for resources (seconds)

        Returns:
            ResourceAllocation if successful, None if failed or timed out
        """
        # Get tool resource profile
        profile = get_tool_profile(tool_name)

        # Check if we can allocate immediately
        with self._lock:
            if self.pool.can_allocate(
                profile.cpu_cores, profile.memory_gb, profile.gpu_count
            ):
                return self._allocate_resources(
                    tool_name,
                    execution_id,
                    profile.cpu_cores,
                    profile.memory_gb,
                    profile.gpu_count,
                )

        # If queueing is disabled, fail immediately
        if self.queue_manager is None:
            logger.warning(
                f"Cannot allocate resources for {tool_name} (needs {profile.cpu_cores} CPU, "
                f"{profile.memory_gb}GB memory), queueing disabled"
            )
            return None

        # Queue the request
        adjusted_priority_value = int(priority)
        boost = getattr(profile, "priority_boost", 0)
        if boost:
            adjusted_priority_value = adjusted_priority_value - boost
            adjusted_priority_value = max(
                int(Priority.HIGH),
                min(int(Priority.LOW), adjusted_priority_value),
            )
        adjusted_priority = Priority(adjusted_priority_value)

        entry = QueueEntry(
            tool_name=tool_name,
            execution_id=execution_id,
            priority=adjusted_priority,
            resource_request={
                "cpu_cores": profile.cpu_cores,
                "memory_gb": profile.memory_gb,
                "gpu_count": profile.gpu_count,
            },
        )

        if not self.queue_manager.enqueue(entry):
            logger.error(f"Failed to queue resource request for {tool_name}")
            return None

        logger.info(
            f"Queued resource request for {tool_name} (execution: {execution_id})"
        )

        # Wait for resources with timeout
        start_time = time.time()
        check_interval = 0.1  # seconds

        while True:
            # If resources were allocated by another thread, return them.
            with self._lock:
                allocation_id = self.execution_to_allocation.get(execution_id)
                if allocation_id:
                    allocation = self.allocations.get(allocation_id)
                    if allocation and allocation.is_active:
                        return allocation

            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                logger.warning(f"Resource request timed out for {tool_name}")
                self.queue_manager.remove(execution_id)
                return None

            # Try to process queue
            allocation = self._process_queue()
            if allocation and allocation.execution_id == execution_id:
                return allocation

            # Wait before next check
            time.sleep(check_interval)

    def _allocate_resources(
        self,
        tool_name: str,
        execution_id: str,
        cpu_cores: float,
        memory_gb: float,
        gpu_count: int = 0,
    ) -> ResourceAllocation | None:
        """Internal method to allocate resources."""
        with self._lock:
            if not self.pool.allocate(cpu_cores, memory_gb, gpu_count):
                return None

            # Create allocation record
            allocation = ResourceAllocation(
                allocation_id=str(uuid4()),
                execution_id=execution_id,
                tool_name=tool_name,
                cpu_cores=cpu_cores,
                memory_gb=memory_gb,
                gpu_count=gpu_count,
            )

            self.allocations[allocation.allocation_id] = allocation
            self.execution_to_allocation[execution_id] = allocation.allocation_id

            logger.info(
                f"Allocated resources for {tool_name}: {cpu_cores} CPU, "
                f"{memory_gb}GB memory (allocation: {allocation.allocation_id[:8]})"
            )

            return allocation

    def release_resources(self, execution_id: str) -> bool:
        """
        Release resources for an execution.

        Args:
            execution_id: Execution ID to release resources for

        Returns:
            True if resources were released, False if not found
        """
        with self._lock:
            allocation_id = self.execution_to_allocation.get(execution_id)
            if not allocation_id:
                # Idempotent release: nothing to release
                return False

            allocation = self.allocations.get(allocation_id)
            if not allocation:
                # Already cleaned up; idempotent
                self.execution_to_allocation.pop(execution_id, None)
                return False

            if not allocation.is_active:
                return False

            # Release resources back to pool
            self.pool.release(
                allocation.cpu_cores, allocation.memory_gb, allocation.gpu_count
            )

            # Mark as released
            allocation.released_at = datetime.now()

            # Clean up mappings
            del self.execution_to_allocation[execution_id]

            logger.info(
                f"Released resources for {allocation.tool_name}: "
                f"{allocation.cpu_cores} CPU, {allocation.memory_gb}GB memory "
                f"(duration: {allocation.duration})"
            )

            # Try to process queued requests
            self._process_queue()

            return True

    def _process_queue(self) -> ResourceAllocation | None:
        """Process queued requests if resources available."""
        if not self.queue_manager:
            return None

        with self._lock:
            # Try to dequeue and allocate
            entry = self.queue_manager.dequeue_if_ready(
                lambda e: self.pool.can_allocate(
                    e.resource_request["cpu_cores"],
                    e.resource_request["memory_gb"],
                    e.resource_request.get("gpu_count", 0),
                )
            )

            if entry:
                return self._allocate_resources(
                    entry.tool_name,
                    entry.execution_id,
                    entry.resource_request["cpu_cores"],
                    entry.resource_request["memory_gb"],
                    entry.resource_request.get("gpu_count", 0),
                )

        return None

    def can_allocate(self, tool_name: str) -> bool:
        """Check if resources are available for a tool."""
        profile = get_tool_profile(tool_name)
        return self.pool.can_allocate(
            profile.cpu_cores, profile.memory_gb, profile.gpu_count
        )

    def get_status(self) -> dict:
        """Get current resource manager status."""
        with self._lock:
            active_allocations = [
                alloc for alloc in self.allocations.values() if alloc.is_active
            ]

            return {
                "pool": {
                    "available": self.pool.get_available(),
                    "utilization": self.pool.get_utilization(),
                    "max_resources": {
                        "cpu_cores": self.pool.max_cpu_cores,
                        "memory_gb": self.pool.max_memory_gb,
                        "gpus": self.pool.max_gpus,
                    },
                },
                "allocations": {
                    "active": len(active_allocations),
                    "total": len(self.allocations),
                    "by_tool": self._get_allocations_by_tool(active_allocations),
                },
                "queue": (
                    self.queue_manager.get_status() if self.queue_manager else None
                ),
            }

    def _get_allocations_by_tool(self, allocations: list) -> dict[str, int]:
        """Get allocation count by tool."""
        by_tool = {}
        for alloc in allocations:
            by_tool[alloc.tool_name] = by_tool.get(alloc.tool_name, 0) + 1
        return by_tool

    def _cleanup_loop(self):
        """Background thread to clean up stale allocations."""
        max_allocation_time = timedelta(hours=1)  # Maximum time for an allocation

        while True:
            try:
                time.sleep(self._cleanup_interval)

                with self._lock:
                    now = datetime.now()
                    stale_allocations = []

                    for alloc_id, alloc in self.allocations.items():
                        if (
                            alloc.is_active
                            and (now - alloc.allocated_at) > max_allocation_time
                        ):
                            logger.warning(
                                f"Cleaning up stale allocation {alloc_id[:8]} "
                                f"for {alloc.tool_name} (age: {now - alloc.allocated_at})"
                            )
                            stale_allocations.append(alloc.execution_id)

                    # Release stale allocations
                    for exec_id in stale_allocations:
                        self.release_resources(exec_id)

            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    def shutdown(self):
        """Shutdown resource manager and release all resources."""
        logger.info("Shutting down ResourceManager")

        with self._lock:
            # Release all active allocations
            active_executions = list(self.execution_to_allocation.keys())
            for exec_id in active_executions:
                self.release_resources(exec_id)

            # Clear queue if exists
            if self.queue_manager:
                self.queue_manager.clear()

        logger.info("ResourceManager shutdown complete")
