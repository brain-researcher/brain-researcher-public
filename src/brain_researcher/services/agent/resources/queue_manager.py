"""
Queue Management System for Resource Allocation.

Provides priority-based queueing for resource requests.
"""

import heapq
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from uuid import uuid4

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Priority levels for resource requests."""

    HIGH = 1  # Interactive user requests
    NORMAL = 2  # Standard analysis requests
    LOW = 3  # Background batch jobs

    @classmethod
    def from_string(cls, value: str) -> "Priority":
        """Convert string to Priority."""
        mapping = {
            "high": cls.HIGH,
            "normal": cls.NORMAL,
            "low": cls.LOW,
        }
        return mapping.get(value.lower(), cls.NORMAL)


@dataclass(order=True)
class QueueEntry:
    """Entry in the resource request queue."""

    # Priority for heap ordering (lower number = higher priority)
    priority: Priority = field(compare=True)

    # Timestamp for FIFO within same priority
    timestamp: datetime = field(default_factory=datetime.now, compare=True)

    # Request details (not used for ordering)
    entry_id: str = field(default_factory=lambda: str(uuid4()), compare=False)
    tool_name: str = field(compare=False, default="")
    execution_id: str = field(compare=False, default="")
    resource_request: dict = field(default_factory=dict, compare=False)
    enqueued_at: datetime = field(default_factory=datetime.now, compare=False)

    @property
    def wait_time(self) -> float:
        """Get time spent waiting in queue (seconds)."""
        return (datetime.now() - self.enqueued_at).total_seconds()

    @property
    def priority_name(self) -> str:
        """Get human-readable priority name."""
        return self.priority.name


class QueueManager:
    """Manages priority queue for resource requests."""

    def __init__(self, max_size: int = 100, enable_backpressure: bool = True):
        """
        Initialize queue manager.

        Args:
            max_size: Maximum queue size
            enable_backpressure: Enable backpressure when queue is full
        """
        self.max_size = max_size
        self.enable_backpressure = enable_backpressure

        # Priority queue (min-heap)
        self._queue: list[QueueEntry] = []

        # Track entries by execution_id for fast lookup
        self._entries_by_execution: dict[str, QueueEntry] = {}

        # Track queue depth by priority
        self._depth_by_priority = {
            Priority.HIGH: 0,
            Priority.NORMAL: 0,
            Priority.LOW: 0,
        }

        # Thread safety
        self._lock = threading.RLock()

        # Metrics
        self._total_enqueued = 0
        self._total_dequeued = 0
        self._total_rejected = 0
        self._max_wait_time = 0.0

        logger.info(f"QueueManager initialized with max_size={max_size}")

    def enqueue(self, entry: QueueEntry) -> bool:
        """
        Add entry to queue.

        Args:
            entry: Queue entry to add

        Returns:
            True if enqueued, False if rejected (queue full)
        """
        with self._lock:
            # Check if already in queue
            if entry.execution_id in self._entries_by_execution:
                logger.warning(f"Execution {entry.execution_id} already in queue")
                return False

            # Check queue size
            if len(self._queue) >= self.max_size:
                if self.enable_backpressure:
                    # Try to drop lowest priority item
                    if not self._make_room_for(entry):
                        logger.warning(
                            f"Queue full ({self.max_size}), rejecting {entry.tool_name}"
                        )
                        self._total_rejected += 1
                        return False
                else:
                    logger.warning(f"Queue full, rejecting {entry.tool_name}")
                    self._total_rejected += 1
                    return False

            # Add to queue
            heapq.heappush(self._queue, entry)
            self._entries_by_execution[entry.execution_id] = entry
            self._depth_by_priority[entry.priority] += 1
            self._total_enqueued += 1

            logger.debug(
                f"Enqueued {entry.tool_name} with {entry.priority_name} priority "
                f"(queue size: {len(self._queue)})"
            )

            return True

    def dequeue(self) -> QueueEntry | None:
        """
        Remove and return highest priority entry.

        Returns:
            Queue entry or None if queue is empty
        """
        with self._lock:
            if not self._queue:
                return None

            entry = heapq.heappop(self._queue)
            del self._entries_by_execution[entry.execution_id]
            self._depth_by_priority[entry.priority] -= 1
            self._total_dequeued += 1

            # Update max wait time metric
            wait_time = entry.wait_time
            if wait_time > self._max_wait_time:
                self._max_wait_time = wait_time

            logger.debug(
                f"Dequeued {entry.tool_name} after {wait_time:.1f}s wait "
                f"(queue size: {len(self._queue)})"
            )

            return entry

    def dequeue_if_ready(
        self, ready_check: Callable[[QueueEntry], bool]
    ) -> QueueEntry | None:
        """
        Dequeue first entry that passes ready check.

        Args:
            ready_check: Function to check if entry can be processed

        Returns:
            Queue entry that passed check, or None
        """
        with self._lock:
            # Find first entry that passes ready check
            for i, entry in enumerate(self._queue):
                if ready_check(entry):
                    # Remove from heap and reheapify
                    self._queue[i] = self._queue[-1]
                    self._queue.pop()
                    if i < len(self._queue):
                        heapq.heapify(self._queue)

                    # Update tracking
                    del self._entries_by_execution[entry.execution_id]
                    self._depth_by_priority[entry.priority] -= 1
                    self._total_dequeued += 1

                    wait_time = entry.wait_time
                    if wait_time > self._max_wait_time:
                        self._max_wait_time = wait_time

                    logger.debug(
                        f"Dequeued {entry.tool_name} (ready check passed) "
                        f"after {wait_time:.1f}s wait"
                    )

                    return entry

            return None

    def peek(self) -> QueueEntry | None:
        """Peek at highest priority entry without removing."""
        with self._lock:
            return self._queue[0] if self._queue else None

    def remove(self, execution_id: str) -> bool:
        """
        Remove specific entry from queue.

        Args:
            execution_id: Execution ID to remove

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            entry = self._entries_by_execution.get(execution_id)
            if not entry:
                return False

            # Remove from heap (expensive but rare operation)
            self._queue = [e for e in self._queue if e.execution_id != execution_id]
            heapq.heapify(self._queue)

            # Update tracking
            del self._entries_by_execution[execution_id]
            self._depth_by_priority[entry.priority] -= 1

            logger.debug(f"Removed {entry.tool_name} from queue")
            return True

    def _make_room_for(self, new_entry: QueueEntry) -> bool:
        """
        Try to make room for new entry by dropping lower priority items.

        Args:
            new_entry: Entry trying to be added

        Returns:
            True if room was made, False otherwise
        """
        # Find lowest priority entry
        if not self._queue:
            return True

        # Get the lowest priority in queue
        lowest_entry = max(self._queue, key=lambda e: (e.priority, e.timestamp))

        # Only drop if new entry has higher priority
        if new_entry.priority < lowest_entry.priority:
            logger.info(
                f"Dropping {lowest_entry.tool_name} ({lowest_entry.priority_name}) "
                f"to make room for {new_entry.tool_name} ({new_entry.priority_name})"
            )
            self.remove(lowest_entry.execution_id)
            return True

        return False

    def clear(self):
        """Clear all entries from queue."""
        with self._lock:
            self._queue.clear()
            self._entries_by_execution.clear()
            for priority in self._depth_by_priority:
                self._depth_by_priority[priority] = 0
            logger.info("Queue cleared")

    def get_status(self) -> dict:
        """Get queue status and metrics."""
        with self._lock:
            entries_by_priority = {}
            for entry in self._queue:
                priority_name = entry.priority_name
                if priority_name not in entries_by_priority:
                    entries_by_priority[priority_name] = []
                entries_by_priority[priority_name].append(
                    {
                        "tool": entry.tool_name,
                        "wait_time": f"{entry.wait_time:.1f}s",
                    }
                )

            return {
                "size": len(self._queue),
                "max_size": self.max_size,
                "depth_by_priority": {
                    "HIGH": self._depth_by_priority[Priority.HIGH],
                    "NORMAL": self._depth_by_priority[Priority.NORMAL],
                    "LOW": self._depth_by_priority[Priority.LOW],
                },
                "entries": entries_by_priority,
                "metrics": {
                    "total_enqueued": self._total_enqueued,
                    "total_dequeued": self._total_dequeued,
                    "total_rejected": self._total_rejected,
                    "max_wait_time": f"{self._max_wait_time:.1f}s",
                    "avg_wait_time": f"{self._calculate_avg_wait_time():.1f}s",
                },
            }

    def _calculate_avg_wait_time(self) -> float:
        """Calculate average wait time for entries in queue."""
        if not self._queue:
            return 0.0

        total_wait = sum(entry.wait_time for entry in self._queue)
        return total_wait / len(self._queue)

    def get_position(self, execution_id: str) -> int | None:
        """
        Get queue position for an execution.

        Args:
            execution_id: Execution ID to find

        Returns:
            Position in queue (0-based) or None if not found
        """
        with self._lock:
            if execution_id not in self._entries_by_execution:
                return None

            # Sort queue to get actual position
            sorted_queue = sorted(self._queue)
            for i, entry in enumerate(sorted_queue):
                if entry.execution_id == execution_id:
                    return i

            return None

    def __len__(self) -> int:
        """Get queue size."""
        return len(self._queue)

    def __bool__(self) -> bool:
        """Check if queue has entries."""
        return bool(self._queue)
