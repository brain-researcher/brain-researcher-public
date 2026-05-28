"""
JobStore Protocol: Pluggable storage backend for job orchestration.

Provides abstraction over in-memory, SQLite, and future storage backends
while maintaining backwards compatibility with existing job_management_endpoints.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Protocol
from dataclasses import dataclass, field
from enum import Enum

from brain_researcher.core.contracts.job import JobRecordV1

class JobState(str, Enum):
    """Job state enumeration matching existing JobStatus."""
    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"  # New: worker has claimed but not started
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    CANCELLING = "cancelling"  # New: cancellation requested but not finalized
    SKIPPED = "skipped"  # New: DAG node skipped due to upstream failure
    PAUSED = "paused"
    RETRYING = "retrying"


JobRecord = JobRecordV1


class JobStore(Protocol):
    """
    Abstract job storage interface.

    Implementations:
    - MemoryJobStore: Wraps existing jobs_db dict
    - SqliteJobStore: Persistent SQLite backend with WAL mode
    - DualJobStore: Dual-write to memory+SQLite for validation
    """

    async def enqueue(self, job: JobRecord) -> str:
        """
        Add job to queue.

        Args:
            job: Job record to enqueue

        Returns:
            job_id of enqueued job
        """
        ...

    async def claim_next(
        self,
        worker_id: str,
        lease_ttl: int = 60,
        gpu_filter: Optional[bool] = None
    ) -> Optional[JobRecord]:
        """
        Atomically claim next job and reserve GPU slots if needed.

        This is the most critical operation - must be race-free.
        For SQLite implementation, uses single-transaction CTE with:
        1. Pick highest-priority queued job
        2. UPDATE to claimed state with worker_id
        3. Verify changes() == 1 (atomic claim succeeded)
        4. Reserve GPU slots if gpu_req > 0
        5. Verify changes() == gpu_req (reservation succeeded)
        6. ROLLBACK if either verification fails

        Args:
            worker_id: Unique worker identifier
            lease_ttl: Lease duration in seconds (default 60)
            gpu_filter: If True, only claim GPU jobs; if False, only CPU jobs; if None, claim either

        Returns:
            Claimed job record, or None if no jobs available
        """
        ...

    async def heartbeat(
        self,
        worker_id: str,
        job_id: Optional[str] = None,
        lease_ttl: int = 60,
    ) -> int:
        """
        Update worker and optional job heartbeat, extend lease.

        Args:
            worker_id: Worker sending heartbeat
            job_id: Optional job currently being executed
            lease_ttl: Lease extension duration in seconds

        Returns:
            Number of jobs updated (0 means heartbeat rejected / no matching lease)
        """
        ...

    async def update_state(
        self,
        job_id: str,
        state: str | JobState | None = None,
        **fields
    ) -> bool:
        """
        Update job state and optional fields.

        Args:
            job_id: Job to update
            state: New state (if provided)
            **fields: Additional fields to update (e.g., exit_code=0, error_message="...")

        Returns:
            True if job was updated, False if job not found
        """
        ...

    async def get(self, job_id: str) -> Optional[JobRecord]:
        """
        Get job by ID.

        Args:
            job_id: Job identifier

        Returns:
            Job record, or None if not found
        """
        ...

    async def list_by_state(
        self,
        state: str,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[JobRecord]:
        """
        List jobs in given state with pagination.

        Args:
            state: Job state to filter by
            limit: Maximum number of jobs to return
            offset: Pagination offset

        Returns:
            List of job records
        """
        ...

    async def list_all(
        self,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[JobRecord]:
        """
        List all jobs with pagination.

        Args:
            limit: Maximum number of jobs to return
            offset: Pagination offset

        Returns:
            List of job records
        """
        ...

    async def count_by_state(
        self,
        state: str,
        user_id: Optional[str] = None,
    ) -> int:
        """Return total number of jobs in the given state."""
        ...

    async def count_all(
        self,
        user_id: Optional[str] = None,
    ) -> int:
        """Return total number of jobs."""
        ...

    async def cancel(
        self,
        job_id: str,
        reason: str = "User requested"
    ) -> bool:
        """
        Request job cancellation.

        State transitions:
        - queued/claimed → cancelled (immediate)
        - running → cancelling (worker must finalize)
        - terminal states → no-op (return False)

        Args:
            job_id: Job to cancel
            reason: Cancellation reason

        Returns:
            True if cancellation requested, False if already terminal
        """
        ...

    async def release_gpus(self, job_id: str) -> None:
        """
        Release GPU slots held by job.

        For SQLite, this is handled by trigger on terminal state.
        For in-memory, manually updates gpu_slots tracking.

        Args:
            job_id: Job whose GPUs should be released
        """
        ...

    async def recover_stale(self, lease_timeout: int = 120) -> Dict[str, int]:
        """
        Requeue jobs with expired leases, return stats.

        Finds jobs in claimed/running state where:
        - lease_expires_at < now - lease_timeout

        Actions:
        - Update state to 'queued'
        - Increment attempt counter
        - Clear worker_id, lease fields
        - Release GPU slots

        Args:
            lease_timeout: Lease expiration threshold in seconds

        Returns:
            Stats dict: {'jobs_requeued': N, 'gpu_slots_freed': M, 'timestamp': T}
        """
        ...

    async def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.

        Returns:
            Dict with counts by state, GPU slot usage, oldest pending job age
        """
        ...

    async def append_event(
        self,
        job_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        created_at: Optional[int] = None,
    ) -> int:
        """Append an event to the job's append-only event log.

        Events support replayable SSE/WS streams via `since_event_id`.

        Returns:
            Monotonic event id for resume/replay.
        """
        ...

    async def list_events(
        self,
        job_id: str,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> List["JobEvent"]:
        """List events for a job ordered by event id ascending."""
        ...

    async def append_log(
        self,
        job_id: str,
        stream: str,
        data: bytes,
        offset: int
    ) -> None:
        """
        Append log chunk for job.

        Args:
            job_id: Job identifier
            stream: Stream name ('stdout' or 'stderr')
            data: Log data bytes
            offset: Byte offset in stream

        Notes:
            - For SQLite: stores in job_logs table
            - For Memory: stores in memory buffer (optional)
            - Offsets allow resume on reconnect
        """
        ...

    async def iter_logs(
        self,
        job_id: str,
        start_offset: int = 0,
        stream: Optional[str] = None
    ) -> List['LogChunk']:
        """
        Iterate log chunks for job.

        Args:
            job_id: Job identifier
            start_offset: Start from this byte offset
            stream: Filter by stream ('stdout', 'stderr'), or None for both

        Returns:
            List of LogChunk records sorted by offset

        Notes:
            - Used by SSE endpoint to stream logs
            - Used by long-poll fallback for chunk retrieval
        """
        ...


@dataclass
class LogChunk:
    """Log chunk record."""
    job_id: str
    stream: str  # 'stdout' or 'stderr'
    offset: int  # Byte offset in stream
    data: bytes  # Log data
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class JobEvent:
    """Append-only job event record."""

    event_id: int
    job_id: str
    event_type: str
    payload: Dict[str, Any] | None = None
    created_at: int = field(default_factory=lambda: int(time.time()))


class GPUSlotManager(Protocol):
    """
    GPU slot allocation interface.

    Separate from JobStore for clarity, but typically implemented
    by the same class (e.g., SqliteJobStore also implements GPUSlotManager).
    """

    async def reserve_slots(
        self,
        job_id: str,
        count: int,
        gpu_type: Optional[str] = None
    ) -> bool:
        """
        Reserve GPU slots for job.

        Args:
            job_id: Job claiming slots
            count: Number of slots to reserve
            gpu_type: Optional GPU type filter

        Returns:
            True if reservation succeeded, False if insufficient slots
        """
        ...

    async def release_slots(self, job_id: str) -> int:
        """
        Release GPU slots for job.

        Args:
            job_id: Job releasing slots

        Returns:
            Number of slots released
        """
        ...

    async def get_slot_stats(self) -> Dict[str, int]:
        """
        Get GPU slot statistics.

        Returns:
            Dict: {'total': N, 'in_use': M, 'available': K}
        """
        ...

    async def get_assigned_devices(self, job_id: str) -> List[int]:
        """
        Get CUDA device IDs assigned to job.

        Args:
            job_id: Job ID

        Returns:
            List of device IDs (e.g., [0, 1] for GPU 0 and 1)
        """
        ...
