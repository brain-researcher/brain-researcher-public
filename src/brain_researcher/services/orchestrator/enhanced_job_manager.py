"""
Enhanced job management with proper cancellation, retry mechanisms with exponential backoff,
job dependency tracking, and batch job submission capabilities.
"""

import asyncio
import logging
import random
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.shared.retry_timeout import (
    RetryConfig as SharedRetryConfig,
)
from brain_researcher.services.shared.retry_timeout import (
    load_retry_config,
)

from .models import JobStatus
from .websocket_endpoints import JobUpdateMessage, broadcast_job_update

logger = logging.getLogger(__name__)


# ============================================================================
# Enhanced Models
# ============================================================================


class RetryStrategy(str, Enum):
    """Retry strategy types."""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_INTERVAL = "fixed_interval"
    IMMEDIATE = "immediate"


class JobCleanupAction(str, Enum):
    """Actions to perform when cleaning up cancelled jobs."""

    REMOVE_FILES = "remove_files"
    CLEANUP_RESOURCES = "cleanup_resources"
    NOTIFY_DEPENDENCIES = "notify_dependencies"
    ROLLBACK_CHANGES = "rollback_changes"


class BatchJobRequest(BaseModel):
    """Batch job submission request."""

    jobs: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)
    batch_name: str | None = None
    batch_priority: str = "normal"
    dependency_mode: str = "independent"  # "independent", "sequential", "parallel"
    failure_policy: str = "continue"  # "continue", "stop_all", "retry_failed"
    max_concurrent_jobs: int = Field(default=5, ge=1, le=20)


class RetryConfig(BaseModel):
    """Retry configuration with exponential backoff."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: float = Field(default=1.0, ge=0.1)
    max_delay_seconds: float = Field(default=300.0, le=3600)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    jitter: bool = True
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF

    @classmethod
    def from_shared(cls, config: SharedRetryConfig) -> "RetryConfig":
        """Map shared retry config (ms) into enhanced job retry config (seconds)."""
        return cls(
            max_attempts=config.max_attempts,
            base_delay_seconds=config.initial_delay_ms / 1000.0,
            max_delay_seconds=config.max_delay_ms / 1000.0,
            backoff_multiplier=config.exponential_base,
            jitter=config.jitter,
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        )


class DependencyRule(BaseModel):
    """Job dependency rule."""

    depends_on_job_id: str
    dependency_type: str = "completion"  # "completion", "start", "artifact"
    required_status: JobStatus = JobStatus.COMPLETED
    required_statuses: list[JobStatus] | None = None
    timeout_seconds: int | None = None
    artifact_path: str | None = None  # For artifact dependencies


class JobCancellationRequest(BaseModel):
    """Job cancellation request with cleanup options."""

    job_id: str
    reason: str
    force: bool = False
    cleanup_actions: list[JobCleanupAction] = Field(default_factory=list)
    cancel_dependent_jobs: bool = False


# ============================================================================
# Enhanced Job Manager
# ============================================================================


class EnhancedJobManager:
    """Enhanced job manager with advanced features."""

    def __init__(self):
        # Job storage
        self.jobs: dict[str, dict[str, Any]] = {}
        self.job_dependencies: dict[str, list[DependencyRule]] = defaultdict(list)
        self.dependent_jobs: dict[str, set[str]] = defaultdict(
            set
        )  # job_id -> dependents

        # Batch processing
        self.batch_jobs: dict[str, list[str]] = {}  # batch_id -> job_ids
        self.batch_metadata: dict[str, dict[str, Any]] = {}

        # Retry management
        self.retry_configs: dict[str, RetryConfig] = {}
        self.retry_schedules: dict[str, datetime] = {}  # job_id -> next_retry_time

        # Cancellation tracking
        self.cancellation_handlers: dict[str, list[Callable]] = defaultdict(list)
        self.cleanup_tasks: dict[str, asyncio.Task] = {}

        # Background tasks
        self.dependency_checker_task: asyncio.Task | None = None
        self.retry_processor_task: asyncio.Task | None = None
        self.cleanup_task: asyncio.Task | None = None

        # Statistics
        self.stats = {
            "jobs_created": 0,
            "jobs_completed": 0,
            "jobs_failed": 0,
            "jobs_cancelled": 0,
            "jobs_retried": 0,
            "batch_jobs_processed": 0,
            "dependency_violations": 0,
        }

        logger.info("Enhanced Job Manager initialized")

    async def start(self):
        """Start background tasks."""
        self.dependency_checker_task = asyncio.create_task(
            self._dependency_checker_loop()
        )
        self.retry_processor_task = asyncio.create_task(self._retry_processor_loop())
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("Enhanced Job Manager background tasks started")

    async def stop(self):
        """Stop background tasks and cleanup."""
        for task in [
            self.dependency_checker_task,
            self.retry_processor_task,
            self.cleanup_task,
        ]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Cancel all cleanup tasks
        for cleanup_task in list(self.cleanup_tasks.values()):
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("Enhanced Job Manager stopped")

    # ========================================================================
    # Job Creation with Dependencies
    # ========================================================================

    async def create_job(
        self,
        job_data: dict[str, Any],
        dependencies: list[DependencyRule] | None = None,
        retry_config: RetryConfig | None = None,
    ) -> str:
        """Create a job with optional dependencies and retry configuration."""
        job_id = job_data.get("id") or f"job_{uuid.uuid4().hex[:12]}"

        # Store job
        self.jobs[job_id] = {
            **job_data,
            "id": job_id,
            "status": JobStatus.PENDING,
            "created_at": datetime.utcnow(),
            "retry_count": 0,
        }

        # Store dependencies
        if dependencies:
            self.job_dependencies[job_id] = dependencies
            for dep in dependencies:
                self.dependent_jobs[dep.depends_on_job_id].add(job_id)

        # Store retry configuration
        if retry_config:
            self.retry_configs[job_id] = retry_config

        self.stats["jobs_created"] += 1
        logger.info(
            f"Job created: {job_id} with {len(dependencies or [])} dependencies"
        )

        # Check if job can be started immediately
        if await self._check_dependencies_satisfied(job_id):
            await self._queue_job(job_id)

        return job_id

    async def create_batch_jobs(self, batch_request: BatchJobRequest) -> dict[str, Any]:
        """Create a batch of jobs with dependency management."""
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        job_ids = []

        try:
            # Create jobs based on dependency mode
            if batch_request.dependency_mode == "sequential":
                job_ids = await self._create_sequential_batch(batch_request, batch_id)
            elif batch_request.dependency_mode == "parallel":
                job_ids = await self._create_parallel_batch(batch_request, batch_id)
            else:  # independent
                job_ids = await self._create_independent_batch(batch_request, batch_id)

            # Store batch metadata
            self.batch_jobs[batch_id] = job_ids
            self.batch_metadata[batch_id] = {
                "name": batch_request.batch_name or f"Batch {batch_id}",
                "created_at": datetime.utcnow(),
                "total_jobs": len(job_ids),
                "dependency_mode": batch_request.dependency_mode,
                "failure_policy": batch_request.failure_policy,
                "max_concurrent_jobs": batch_request.max_concurrent_jobs,
            }

            self.stats["batch_jobs_processed"] += 1
            logger.info(f"Batch created: {batch_id} with {len(job_ids)} jobs")

            return {
                "batch_id": batch_id,
                "job_ids": job_ids,
                "total_jobs": len(job_ids),
                "dependency_mode": batch_request.dependency_mode,
            }

        except Exception as e:
            logger.error(f"Failed to create batch: {str(e)}")
            # Cleanup any partially created jobs
            for job_id in job_ids:
                if job_id in self.jobs:
                    await self._cleanup_job(job_id)
            raise

    async def _create_sequential_batch(
        self, batch_request: BatchJobRequest, batch_id: str
    ) -> list[str]:
        """Create jobs that execute sequentially."""
        job_ids = []
        previous_job_id = None

        for _i, job_data in enumerate(batch_request.jobs):
            job_id = await self.create_job(
                job_data,
                dependencies=(
                    [DependencyRule(depends_on_job_id=previous_job_id)]
                    if previous_job_id
                    else None
                ),
            )
            job_ids.append(job_id)
            previous_job_id = job_id

        return job_ids

    async def _create_parallel_batch(
        self, batch_request: BatchJobRequest, batch_id: str
    ) -> list[str]:
        """Create jobs that can execute in parallel with concurrency limits."""
        job_ids = []

        max_concurrent = max(1, int(batch_request.max_concurrent_jobs))
        terminal_statuses = [
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
            JobStatus.SKIPPED,
        ]

        # Sliding-window dependencies: job[i] waits for job[i-max_concurrent] to finish
        # (success or failure). This caps "eligible to queue" jobs to max_concurrent.
        for i, job_data in enumerate(batch_request.jobs):
            dependencies = None
            if i >= max_concurrent:
                dependencies = [
                    DependencyRule(
                        depends_on_job_id=job_ids[i - max_concurrent],
                        dependency_type="completion",
                        required_statuses=terminal_statuses,
                    )
                ]
            job_id = await self.create_job(job_data, dependencies=dependencies)
            job_ids.append(job_id)

        return job_ids

    async def _create_independent_batch(
        self, batch_request: BatchJobRequest, batch_id: str
    ) -> list[str]:
        """Create independent jobs that don't depend on each other."""
        job_ids = []

        for job_data in batch_request.jobs:
            job_id = await self.create_job(job_data)
            job_ids.append(job_id)

        return job_ids

    # ========================================================================
    # Advanced Job Cancellation
    # ========================================================================

    async def cancel_job(
        self, cancellation_request: JobCancellationRequest
    ) -> dict[str, Any]:
        """Cancel a job with proper cleanup and dependency handling."""
        job_id = cancellation_request.job_id

        if job_id not in self.jobs:
            raise ValueError(f"Job {job_id} not found")

        job = self.jobs[job_id]

        # Check if job can be cancelled
        if not cancellation_request.force and job["status"] in [
            JobStatus.COMPLETED,
            JobStatus.CANCELLED,
        ]:
            return {"status": "already_finished", "job_id": job_id}

        logger.info(f"Cancelling job {job_id}: {cancellation_request.reason}")

        # Update job status
        job["status"] = JobStatus.CANCELLED
        job["cancellation_requested"] = True
        job["cancellation_reason"] = cancellation_request.reason
        job["completed_at"] = datetime.utcnow()

        # Notify via WebSocket
        await broadcast_job_update(
            job_id,
            JobUpdateMessage(
                job_id=job_id,
                status=JobStatus.CANCELLED,
                progress=job.get("progress", 0),
                message=f"Job cancelled: {cancellation_request.reason}",
                timestamp=datetime.utcnow(),
            ),
        )

        # Handle dependent jobs
        cancelled_dependents = []
        if cancellation_request.cancel_dependent_jobs:
            cancelled_dependents = await self._cancel_dependent_jobs(
                job_id, cancellation_request.reason
            )

        # Start cleanup process
        if cancellation_request.cleanup_actions:
            cleanup_task = asyncio.create_task(
                self._perform_cleanup_actions(
                    job_id, cancellation_request.cleanup_actions
                )
            )
            self.cleanup_tasks[job_id] = cleanup_task

        self.stats["jobs_cancelled"] += 1

        return {
            "status": "cancelled",
            "job_id": job_id,
            "cancelled_dependents": cancelled_dependents,
            "cleanup_actions_scheduled": len(cancellation_request.cleanup_actions),
        }

    async def _cancel_dependent_jobs(self, job_id: str, reason: str) -> list[str]:
        """Cancel all jobs that depend on this job."""
        cancelled_jobs = []

        for dependent_job_id in self.dependent_jobs.get(job_id, set()):
            if dependent_job_id in self.jobs:
                dependent_job = self.jobs[dependent_job_id]

                if dependent_job["status"] not in [
                    JobStatus.COMPLETED,
                    JobStatus.CANCELLED,
                ]:
                    await self.cancel_job(
                        JobCancellationRequest(
                            job_id=dependent_job_id,
                            reason=f"Dependency {job_id} cancelled: {reason}",
                            cancel_dependent_jobs=True,
                        )
                    )
                    cancelled_jobs.append(dependent_job_id)

        return cancelled_jobs

    async def _perform_cleanup_actions(
        self, job_id: str, cleanup_actions: list[JobCleanupAction]
    ):
        """Perform cleanup actions for a cancelled job."""
        try:
            for action in cleanup_actions:
                logger.info(f"Performing cleanup action {action} for job {job_id}")

                if action == JobCleanupAction.REMOVE_FILES:
                    await self._cleanup_job_files(job_id)
                elif action == JobCleanupAction.CLEANUP_RESOURCES:
                    await self._cleanup_job_resources(job_id)
                elif action == JobCleanupAction.NOTIFY_DEPENDENCIES:
                    await self._notify_dependent_jobs(job_id)
                elif action == JobCleanupAction.ROLLBACK_CHANGES:
                    await self._rollback_job_changes(job_id)

                await asyncio.sleep(0.1)  # Prevent overwhelming the system

            logger.info(f"Cleanup completed for job {job_id}")

        except Exception as e:
            logger.error(f"Cleanup failed for job {job_id}: {str(e)}")

        finally:
            # Remove cleanup task
            if job_id in self.cleanup_tasks:
                del self.cleanup_tasks[job_id]

    async def _cleanup_job_files(self, job_id: str):
        """Clean up files created by the job."""
        # Implementation would depend on your file storage system
        logger.info(f"Cleaning up files for job {job_id}")

    async def _cleanup_job_resources(self, job_id: str):
        """Clean up resources allocated to the job."""
        # Implementation would clean up compute resources, database connections, etc.
        logger.info(f"Cleaning up resources for job {job_id}")

    async def _notify_dependent_jobs(self, job_id: str):
        """Notify dependent jobs about the cancellation."""
        for dependent_job_id in self.dependent_jobs.get(job_id, set()):
            await broadcast_job_update(
                dependent_job_id,
                JobUpdateMessage(
                    job_id=dependent_job_id,
                    status=self.jobs[dependent_job_id]["status"],
                    progress=self.jobs[dependent_job_id].get("progress", 0),
                    message=f"Dependency {job_id} was cancelled",
                    timestamp=datetime.utcnow(),
                ),
            )

    async def _rollback_job_changes(self, job_id: str):
        """Rollback changes made by the job."""
        # Implementation would depend on what changes need to be rolled back
        logger.info(f"Rolling back changes for job {job_id}")

    # ========================================================================
    # Retry Mechanisms with Exponential Backoff
    # ========================================================================

    async def retry_job(self, job_id: str, force: bool = False) -> dict[str, Any]:
        """Retry a failed job with exponential backoff."""
        if job_id not in self.jobs:
            raise ValueError(f"Job {job_id} not found")

        job = self.jobs[job_id]
        retry_config = self.retry_configs.get(
            job_id, RetryConfig.from_shared(load_retry_config())
        )

        # Check if job can be retried
        if not force:
            if job["status"] != JobStatus.FAILED:
                return {"status": "not_failed", "job_id": job_id}

            if job["retry_count"] >= retry_config.max_attempts:
                return {"status": "max_retries_exceeded", "job_id": job_id}

        # Calculate delay based on strategy
        delay = self._calculate_retry_delay(job["retry_count"], retry_config)
        next_retry_time = datetime.utcnow() + timedelta(seconds=delay)

        # Schedule retry
        self.retry_schedules[job_id] = next_retry_time

        # Update job
        job["retry_count"] += 1
        job["status"] = JobStatus.RETRYING
        job["error"] = None  # Clear previous error

        logger.info(
            f"Job {job_id} scheduled for retry in {delay:.2f} seconds (attempt {job['retry_count']})"
        )

        # Notify via WebSocket
        await broadcast_job_update(
            job_id,
            JobUpdateMessage(
                job_id=job_id,
                status=JobStatus.RETRYING,
                progress=0,
                message=f"Retry scheduled in {delay:.2f} seconds (attempt {job['retry_count']})",
                timestamp=datetime.utcnow(),
            ),
        )

        self.stats["jobs_retried"] += 1

        return {
            "status": "retry_scheduled",
            "job_id": job_id,
            "retry_attempt": job["retry_count"],
            "next_retry_at": next_retry_time.isoformat(),
            "delay_seconds": delay,
        }

    def _calculate_retry_delay(self, retry_count: int, config: RetryConfig) -> float:
        """Calculate retry delay based on strategy."""
        if config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = config.base_delay_seconds * (config.backoff_multiplier**retry_count)
        elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.base_delay_seconds * (1 + retry_count)
        elif config.strategy == RetryStrategy.FIXED_INTERVAL:
            delay = config.base_delay_seconds
        else:  # IMMEDIATE
            delay = 0

        # Apply maximum delay limit
        delay = min(delay, config.max_delay_seconds)

        # Apply jitter if enabled
        if config.jitter and delay > 0:
            jitter_range = delay * 0.1  # 10% jitter
            jitter = random.uniform(-jitter_range, jitter_range)
            delay = max(0.1, delay + jitter)

        return delay

    # ========================================================================
    # Dependency Management
    # ========================================================================

    async def _check_dependencies_satisfied(self, job_id: str) -> bool:
        """Check if all dependencies for a job are satisfied."""
        if job_id not in self.job_dependencies:
            return True  # No dependencies

        for dep in self.job_dependencies[job_id]:
            if not await self._is_dependency_satisfied(dep):
                return False

        return True

    async def _is_dependency_satisfied(self, dependency: DependencyRule) -> bool:
        """Check if a specific dependency is satisfied."""
        dep_job_id = dependency.depends_on_job_id

        if dep_job_id not in self.jobs:
            logger.warning(f"Dependency job {dep_job_id} not found")
            self.stats["dependency_violations"] += 1
            return False

        dep_job = self.jobs[dep_job_id]

        # Check timeout
        if dependency.timeout_seconds:
            if dep_job.get("created_at"):
                elapsed = (datetime.utcnow() - dep_job["created_at"]).total_seconds()
                if elapsed > dependency.timeout_seconds:
                    logger.warning(
                        f"Dependency {dep_job_id} timed out after {elapsed:.2f}s"
                    )
                    self.stats["dependency_violations"] += 1
                    return False

        # Check status requirement
        if dependency.dependency_type == "completion":
            if dependency.required_statuses:
                return dep_job["status"] in dependency.required_statuses
            return dep_job["status"] == dependency.required_status
        elif dependency.dependency_type == "start":
            return dep_job["status"] in [JobStatus.RUNNING, JobStatus.COMPLETED]
        elif dependency.dependency_type == "artifact" and dependency.artifact_path:
            # Check if specific artifact exists
            artifacts = dep_job.get("artifacts", [])
            return any(
                artifact.get("path") == dependency.artifact_path
                for artifact in artifacts
            )

        return False

    # ========================================================================
    # Background Tasks
    # ========================================================================

    async def _dependency_checker_loop(self):
        """Background task to check job dependencies."""
        while True:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds

                # Check pending jobs for satisfied dependencies
                pending_jobs = [
                    job_id
                    for job_id, job in self.jobs.items()
                    if job["status"] == JobStatus.PENDING
                ]

                for job_id in pending_jobs:
                    if await self._check_dependencies_satisfied(job_id):
                        await self._queue_job(job_id)

            except Exception as e:
                logger.error(f"Dependency checker error: {str(e)}")

    async def _retry_processor_loop(self):
        """Background task to process scheduled retries."""
        while True:
            try:
                await asyncio.sleep(1)  # Check every second

                current_time = datetime.utcnow()
                ready_retries = [
                    job_id
                    for job_id, retry_time in self.retry_schedules.items()
                    if current_time >= retry_time
                ]

                for job_id in ready_retries:
                    if (
                        job_id in self.jobs
                        and self.jobs[job_id]["status"] == JobStatus.RETRYING
                    ):
                        await self._queue_job(job_id)
                        del self.retry_schedules[job_id]

            except Exception as e:
                logger.error(f"Retry processor error: {str(e)}")

    async def _cleanup_loop(self):
        """Background task to clean up completed cleanup tasks."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                # Clean up finished cleanup tasks
                finished_tasks = [
                    job_id for job_id, task in self.cleanup_tasks.items() if task.done()
                ]

                for job_id in finished_tasks:
                    task = self.cleanup_tasks[job_id]
                    try:
                        await task  # Ensure any exceptions are handled
                    except Exception as e:
                        logger.error(f"Cleanup task error for job {job_id}: {str(e)}")
                    finally:
                        del self.cleanup_tasks[job_id]

            except Exception as e:
                logger.error(f"Cleanup loop error: {str(e)}")

    async def _queue_job(self, job_id: str):
        """Queue a job for execution."""
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job["status"] = JobStatus.QUEUED
            job["queued_at"] = datetime.utcnow()

            logger.info(f"Job {job_id} queued for execution")

            # Notify via WebSocket
            await broadcast_job_update(
                job_id,
                JobUpdateMessage(
                    job_id=job_id,
                    status=JobStatus.QUEUED,
                    progress=0,
                    message="Job queued for execution",
                    timestamp=datetime.utcnow(),
                ),
            )

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Get job by ID."""
        return self.jobs.get(job_id)

    def get_batch_status(self, batch_id: str) -> dict[str, Any] | None:
        """Get status of a batch job."""
        if batch_id not in self.batch_jobs:
            return None

        job_ids = self.batch_jobs[batch_id]
        metadata = self.batch_metadata[batch_id]

        status_counts = defaultdict(int)
        for job_id in job_ids:
            if job_id in self.jobs:
                status_counts[self.jobs[job_id]["status"]] += 1

        return {
            "batch_id": batch_id,
            "metadata": metadata,
            "job_ids": job_ids,
            "status_breakdown": dict(status_counts),
            "total_jobs": len(job_ids),
            "completion_percentage": (
                (status_counts[JobStatus.COMPLETED] / len(job_ids)) * 100
                if job_ids
                else 0
            ),
        }

    def get_statistics(self) -> dict[str, Any]:
        """Get job manager statistics."""
        return {
            **self.stats,
            "active_jobs": len(
                [
                    j
                    for j in self.jobs.values()
                    if j["status"] in [JobStatus.RUNNING, JobStatus.QUEUED]
                ]
            ),
            "total_jobs": len(self.jobs),
            "jobs_with_dependencies": len(self.job_dependencies),
            "active_batches": len(self.batch_jobs),
            "scheduled_retries": len(self.retry_schedules),
            "active_cleanup_tasks": len(self.cleanup_tasks),
        }


# Global instance
enhanced_job_manager = EnhancedJobManager()
