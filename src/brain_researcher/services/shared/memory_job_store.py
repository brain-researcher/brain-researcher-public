"""
MemoryJobStore: In-memory implementation of JobStore protocol.

Wraps existing jobs_db dictionary to provide JobStore interface
without breaking existing code. This is the default implementation
for development and testing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from .job_store import GPUSlotManager, JobEvent, JobRecord, JobState, JobStore

logger = logging.getLogger(__name__)


class MemoryJobStore(JobStore, GPUSlotManager):
    """
    In-memory job store backed by Python dicts.

    Thread-safe via asyncio locks. Suitable for single-process orchestrators.
    Jobs are lost on restart (non-persistent).
    """

    def __init__(
        self, total_gpu_slots: int = 2, jobs_dict: dict[str, JobRecord] | None = None
    ):
        """
        Initialize in-memory job store.

        Args:
            total_gpu_slots: Number of GPU slots available (default 2)
            jobs_dict: Optional existing job dictionary to wrap
        """
        self._jobs: dict[str, JobRecord] = jobs_dict if jobs_dict is not None else {}
        self._lock = asyncio.Lock()

        # GPU slot tracking
        self._total_gpu_slots = total_gpu_slots
        self._gpu_slots_in_use: set[int] = set()  # Slot IDs currently allocated
        self._gpu_assignments: dict[str, list[int]] = {}  # job_id → [slot_id, ...]

        # Worker tracking
        self._worker_heartbeats: dict[str, int] = {}  # worker_id → timestamp

        # Append-only job event log (non-persistent)
        self._events_by_job: dict[str, list[JobEvent]] = defaultdict(list)
        self._next_event_id = 1

        logger.info(f"Initialized MemoryJobStore with {total_gpu_slots} GPU slots")

    async def enqueue(self, job: JobRecord) -> str:
        """Add job to queue."""
        async with self._lock:
            if job.job_id in self._jobs:
                raise ValueError(f"Job {job.job_id} already exists")

            # Set state to queued only if not already set
            if not job.state or job.state == JobState.PENDING:
                job.state = JobState.QUEUED

            # Set queued_at timestamp if transitioning to QUEUED
            if job.state == JobState.QUEUED and job.queued_at is None:
                job.queued_at = int(time.time())

            self._jobs[job.job_id] = job
            logger.debug(
                f"Enqueued job {job.job_id} with priority {job.priority}, state={job.state}"
            )
            return job.job_id

    async def claim_next(
        self, worker_id: str, lease_ttl: int = 60, gpu_filter: bool | None = None
    ) -> JobRecord | None:
        """
        Atomically claim next job and reserve GPU slots.

        Implements two-phase lock:
        1. Find highest-priority queued job
        2. Reserve GPU slots if needed
        3. Claim job with worker_id
        4. Rollback if GPU reservation fails
        """
        async with self._lock:
            now = int(time.time())

            # Find eligible jobs (priority order)
            eligible = []
            for job in self._jobs.values():
                # Must be queued
                if job.state != JobState.QUEUED:
                    continue

                # Check run_after delay
                if job.run_after is not None and job.run_after > now:
                    continue

                # Apply GPU filter
                if gpu_filter is not None:
                    if gpu_filter and job.gpu_req == 0:
                        continue  # Want GPU jobs only
                    if not gpu_filter and job.gpu_req > 0:
                        continue  # Want CPU jobs only

                # Check GPU availability
                if job.gpu_req > 0:
                    available_slots = self._total_gpu_slots - len(
                        self._gpu_slots_in_use
                    )
                    if available_slots < job.gpu_req:
                        continue  # Not enough GPUs

                eligible.append(job)

            # P2.6: Opportunistic retry check - if no QUEUED jobs, check RETRYING
            if not eligible:
                # Try to find RETRYING jobs ready to retry
                for job in self._jobs.values():
                    # Must be RETRYING with run_after <= now
                    if job.state != JobState.RETRYING:
                        continue
                    if job.run_after is None or job.run_after > now:
                        continue

                    # Apply GPU filter
                    if gpu_filter is not None:
                        if gpu_filter and job.gpu_req == 0:
                            continue  # Want GPU jobs only
                        if not gpu_filter and job.gpu_req > 0:
                            continue  # Want CPU jobs only

                    # Check GPU availability
                    if job.gpu_req > 0:
                        available_slots = self._total_gpu_slots - len(
                            self._gpu_slots_in_use
                        )
                        if available_slots < job.gpu_req:
                            continue  # Not enough GPUs

                    eligible.append(job)

                if eligible:
                    # Found RETRYING job(s) ready to retry
                    # Sort and pick best one
                    eligible.sort(key=lambda j: (-j.priority, j.created_at))
                    job = eligible[0]

                    # Promote to QUEUED
                    job.state = JobState.QUEUED
                    job.run_after = None

                    logger.info(
                        f"Opportunistically promoted job {job.job_id} "
                        f"from RETRYING to QUEUED in claim_next() "
                        f"(attempt {job.attempt}/{job.max_attempts})"
                    )
                    # Continue to claim this job below
                else:
                    # No jobs available at all
                    return None

            # Sort by priority (descending), then created_at (ascending)
            eligible.sort(key=lambda j: (-j.priority, j.created_at))
            job = eligible[0]

            # Reserve GPU slots if needed
            if job.gpu_req > 0:
                # Find available slots
                all_slots = set(range(self._total_gpu_slots))
                available = all_slots - self._gpu_slots_in_use

                if len(available) < job.gpu_req:
                    # Race condition: another thread claimed slots
                    logger.warning(
                        f"GPU slot race: job {job.job_id} needs {job.gpu_req} but only {len(available)} available"
                    )
                    return None

                # Allocate slots
                assigned = sorted(available)[: job.gpu_req]
                self._gpu_slots_in_use.update(assigned)
                self._gpu_assignments[job.job_id] = assigned

                logger.debug(f"Reserved GPU slots {assigned} for job {job.job_id}")

            # Claim job
            job.state = JobState.CLAIMED
            job.claimed_at = now
            job.worker_id = worker_id
            job.lease_expires_at = now + lease_ttl
            job.last_heartbeat = now

            logger.info(
                f"Worker {worker_id} claimed job {job.job_id} (priority={job.priority}, gpu_req={job.gpu_req})"
            )
            return job

    async def heartbeat(
        self,
        worker_id: str,
        job_id: str | None = None,
        lease_ttl: int = 60,
    ) -> int:
        """Update worker and job heartbeat."""
        async with self._lock:
            now = int(time.time())
            updated = 0

            # Update worker heartbeat
            self._worker_heartbeats[worker_id] = now

            if job_id:
                # Heartbeat a specific job
                job = self._jobs.get(job_id)
                if (
                    job
                    and job.worker_id == worker_id
                    and job.state
                    in (
                        JobState.CLAIMED,
                        JobState.RUNNING,
                    )
                ):
                    job.last_heartbeat = now
                    job.lease_expires_at = now + max(int(lease_ttl), 1)
                    updated = 1
                    logger.debug(f"Heartbeat from worker {worker_id} for job {job_id}")
            else:
                # Heartbeat all active jobs for this worker
                for job in self._jobs.values():
                    if job.worker_id != worker_id:
                        continue
                    if job.state not in (JobState.CLAIMED, JobState.RUNNING):
                        continue
                    job.last_heartbeat = now
                    job.lease_expires_at = now + max(int(lease_ttl), 1)
                    updated += 1

            return updated

    async def update_state(
        self, job_id: str, state: str | None = None, **fields
    ) -> bool:
        """Update job state and fields."""
        async with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]

            # Update state if provided
            if state:
                old_state = job.state
                job.state = state
                logger.debug(f"Job {job_id} state: {old_state} → {state}")

                # Auto-release GPUs on terminal states
                if state in [
                    JobState.SUCCEEDED,
                    JobState.FAILED,
                    JobState.CANCELLED,
                    JobState.TIMEOUT,
                    JobState.SKIPPED,
                ]:
                    if job_id in self._gpu_assignments:
                        freed = self._gpu_assignments.pop(job_id)
                        self._gpu_slots_in_use -= set(freed)
                        logger.debug(f"Released GPU slots {freed} for job {job_id}")

            # Update additional fields
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)

            return True

    async def append_event(
        self,
        job_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        created_at: int | None = None,
    ) -> int:
        async with self._lock:
            event_id = self._next_event_id
            self._next_event_id += 1
            created_ts = int(created_at if created_at is not None else time.time())
            self._events_by_job[job_id].append(
                JobEvent(
                    event_id=event_id,
                    job_id=job_id,
                    event_type=str(event_type),
                    payload=payload if isinstance(payload, dict) else None,
                    created_at=created_ts,
                )
            )
            return event_id

    async def list_events(
        self,
        job_id: str,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> list[JobEvent]:
        async with self._lock:
            events = self._events_by_job.get(job_id, [])
            filtered = [ev for ev in events if ev.event_id > int(after_event_id)]
            return filtered[: max(1, int(limit))]

    async def get(self, job_id: str) -> JobRecord | None:
        """Get job by ID."""
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_by_state(
        self,
        state: str,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        project_id: str | None = None,
    ) -> list[JobRecord]:
        """List jobs in given state."""
        async with self._lock:
            jobs = [j for j in self._jobs.values() if j.state == state]
            if user_id:
                jobs = [j for j in jobs if j.user_id == user_id]
            if project_id:
                jobs = [j for j in jobs if (j.project_id or "default") == project_id]
            # Sort by created_at descending (newest first)
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            return jobs[offset : offset + limit]

    async def list_all(
        self,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        project_id: str | None = None,
    ) -> list[JobRecord]:
        """List all jobs."""
        async with self._lock:
            jobs = list(self._jobs.values())
            if user_id:
                jobs = [j for j in jobs if j.user_id == user_id]
            if project_id:
                jobs = [j for j in jobs if (j.project_id or "default") == project_id]
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            return jobs[offset : offset + limit]

    async def count_by_state(
        self,
        state: str,
        user_id: str | None = None,
    ) -> int:
        async with self._lock:
            jobs = [j for j in self._jobs.values() if j.state == state]
            if user_id:
                jobs = [j for j in jobs if j.user_id == user_id]
            return len(jobs)

    async def count_all(self, user_id: str | None = None) -> int:
        async with self._lock:
            if user_id:
                return len([j for j in self._jobs.values() if j.user_id == user_id])
            return len(self._jobs)

    async def cancel(self, job_id: str, reason: str = "User requested") -> bool:
        """
        Request job cancellation.

        Implements cancel-wins rule:
        - queued/claimed → immediate cancellation
        - running → mark as cancelling (worker finalizes)
        - terminal → no-op
        """
        async with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]

            # Check if already terminal
            if job.state in [
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.TIMEOUT,
                JobState.SKIPPED,
            ]:
                logger.debug(
                    f"Job {job_id} already terminal ({job.state}), cannot cancel"
                )
                return False

            # Set cancellation flag
            job.cancel_reason = reason
            job.cancellation_requested = True

            # State transition
            if job.state in [JobState.PENDING, JobState.QUEUED, JobState.CLAIMED]:
                # Not started yet - cancel immediately
                job.state = JobState.CANCELLED
                job.finished_at = int(time.time())

                # Release GPUs
                if job_id in self._gpu_assignments:
                    freed = self._gpu_assignments.pop(job_id)
                    self._gpu_slots_in_use -= set(freed)
                    logger.debug(
                        f"Released GPU slots {freed} for cancelled job {job_id}"
                    )

                logger.info(f"Job {job_id} cancelled immediately (was {job.state})")

            elif job.state == JobState.RUNNING:
                # Running - mark as cancelling (worker will finalize)
                job.state = JobState.CANCELLING
                logger.info(f"Job {job_id} marked as cancelling, worker will finalize")

            else:
                logger.warning(
                    f"Unexpected state for cancel: job {job_id} in state {job.state}"
                )

            return True

    async def release_gpus(self, job_id: str) -> None:
        """Release GPU slots for job."""
        async with self._lock:
            if job_id in self._gpu_assignments:
                freed = self._gpu_assignments.pop(job_id)
                self._gpu_slots_in_use -= set(freed)
                logger.debug(f"Released GPU slots {freed} for job {job_id}")

    async def recover_stale(self, lease_timeout: int = 120) -> dict[str, int]:
        """
        Requeue jobs with expired leases.

        Args:
            lease_timeout: Jobs with lease expiration older than this are considered stale

        Returns:
            Stats: jobs_requeued, gpu_slots_freed, timestamp
        """
        async with self._lock:
            now = int(time.time())
            now - lease_timeout

            jobs_requeued = 0
            gpu_slots_freed = 0

            for job in self._jobs.values():
                # Check if stale
                if job.state not in [JobState.CLAIMED, JobState.RUNNING]:
                    continue

                # Lease has expired if lease_expires_at < current time
                if job.lease_expires_at is None or job.lease_expires_at > now:
                    continue

                # Requeue stale job
                logger.warning(
                    f"Requeuing stale job {job.job_id} (worker={job.worker_id}, lease_expired={job.lease_expires_at})"
                )

                job.state = JobState.QUEUED
                job.attempt += 1
                job.worker_id = None
                job.claimed_at = None
                job.lease_expires_at = None

                # Append recovery note
                if job.error_message:
                    job.error_message += " [recovered-stale]"
                else:
                    job.error_message = "[recovered-stale]"

                jobs_requeued += 1

                # Release GPUs
                if job.job_id in self._gpu_assignments:
                    freed = self._gpu_assignments.pop(job.job_id)
                    self._gpu_slots_in_use -= set(freed)
                    gpu_slots_freed += len(freed)

            if jobs_requeued > 0:
                logger.warning(
                    f"Recovery: requeued {jobs_requeued} jobs, freed {gpu_slots_freed} GPU slots"
                )

            return {
                "jobs_requeued": jobs_requeued,
                "gpu_slots_freed": gpu_slots_freed,
                "timestamp": now,
            }

    async def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        async with self._lock:
            stats = defaultdict(int)

            # Count by state
            for job in self._jobs.values():
                stats[job.state] += 1

            # GPU stats
            stats["gpu_total"] = self._total_gpu_slots
            stats["gpu_in_use"] = len(self._gpu_slots_in_use)
            stats["gpu_available"] = self._total_gpu_slots - len(self._gpu_slots_in_use)

            # Oldest pending job
            queued_jobs = [j for j in self._jobs.values() if j.state == JobState.QUEUED]
            if queued_jobs:
                oldest = min(queued_jobs, key=lambda j: j.created_at)
                stats["oldest_pending_age_sec"] = int(time.time()) - oldest.created_at
            else:
                stats["oldest_pending_age_sec"] = 0

            # Active workers
            stats["active_workers"] = len(self._worker_heartbeats)

            return dict(stats)

    # GPUSlotManager implementation

    async def reserve_slots(
        self, job_id: str, count: int, gpu_type: str | None = None
    ) -> bool:
        """Reserve GPU slots (already done in claim_next)."""
        # This is a no-op for MemoryJobStore since claim_next handles reservation
        return job_id in self._gpu_assignments

    async def release_slots(self, job_id: str) -> int:
        """Release GPU slots."""
        async with self._lock:
            if job_id in self._gpu_assignments:
                freed = self._gpu_assignments.pop(job_id)
                self._gpu_slots_in_use -= set(freed)
                return len(freed)
            return 0

    async def get_slot_stats(self) -> dict[str, int]:
        """Get GPU slot statistics."""
        async with self._lock:
            return {
                "total": self._total_gpu_slots,
                "in_use": len(self._gpu_slots_in_use),
                "available": self._total_gpu_slots - len(self._gpu_slots_in_use),
            }

    async def get_assigned_devices(self, job_id: str) -> list[int]:
        """Get CUDA device IDs assigned to job."""
        async with self._lock:
            return self._gpu_assignments.get(job_id, [])

    # Log persistence methods

    async def append_log(
        self, job_id: str, stream: str, data: bytes, offset: int
    ) -> None:
        """
        Append log chunk for job (in-memory buffer).

        Args:
            job_id: Job identifier
            stream: Stream name ('stdout' or 'stderr')
            data: Log data bytes
            offset: Byte offset in stream

        Note:
            Logs are stored in memory and lost on restart.
            For production, use SqliteJobStore.
        """
        # Initialize log storage on first access
        if not hasattr(self, "_logs"):
            self._logs: dict[str, list[Any]] = {}

        async with self._lock:
            # Ensure job exists (optional validation)
            if job_id not in self._jobs:
                logger.warning(f"Appending log for non-existent job {job_id}")

            # Store log chunk
            key = job_id
            if key not in self._logs:
                self._logs[key] = []

            # Import LogChunk here to avoid circular dependency
            from .job_store import LogChunk

            chunk = LogChunk(
                job_id=job_id,
                stream=stream,
                offset=offset,
                data=data,
                created_at=int(time.time()),
            )

            self._logs[key].append(chunk)
            logger.debug(
                f"Appended {len(data)} bytes to {stream} for job {job_id} at offset {offset}"
            )

    async def iter_logs(
        self, job_id: str, start_offset: int = 0, stream: str | None = None
    ) -> list[Any]:
        """
        Iterate log chunks for job.

        Args:
            job_id: Job identifier
            start_offset: Start from this byte offset
            stream: Filter by stream ('stdout', 'stderr'), or None for both

        Returns:
            List of LogChunk records sorted by offset
        """
        # Initialize log storage if not present
        if not hasattr(self, "_logs"):
            self._logs: dict[str, list[Any]] = {}

        async with self._lock:
            key = job_id
            if key not in self._logs:
                return []

            # Filter and sort chunks
            chunks = self._logs[key]

            # Apply filters
            filtered = [
                c
                for c in chunks
                if c.offset >= start_offset and (stream is None or c.stream == stream)
            ]

            # Sort by offset
            filtered.sort(key=lambda c: c.offset)

            return filtered
