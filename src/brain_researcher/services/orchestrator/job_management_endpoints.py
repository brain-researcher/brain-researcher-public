"""
Enhanced job management endpoints with detailed progress tracking, analytics, and monitoring.
Provides comprehensive job lifecycle management with real-time updates.
"""

import asyncio
import base64
import copy
import json
import logging
import os
import shutil
import statistics
import sys
import time as time_module
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator
from sse_starlette.sse import EventSourceResponse

from brain_researcher.config.run_artifacts import (
    get_recorder_config,
    get_recorder_roots_for_read,
    resolve_recorded_path_for_read,
)
from brain_researcher.core.contracts.job import JobRecordV1

from . import models as core_models
from .env import AGENT_URL, BR_KG_URL
from .job_adapter import JobAdapter
from .job_state import jobs_db as core_jobs_db
from .job_store import JobEvent, JobRecord, LogChunk
from .models import CacheMetadata
from .pipeline_graph import build_job_graph_snapshot

logger = logging.getLogger(__name__)

# Admission control / queue limits
MAX_QUEUE_LENGTH = int(os.getenv("BR_MAX_QUEUE_LENGTH", "500"))
QUEUE_RETRY_AFTER_SEC = int(os.getenv("BR_QUEUE_RETRY_AFTER_SEC", "30"))
_OBS_INTERNAL_ARTIFACT_FILENAMES = {
    "observation.json",
    "analysis_bundle.json",
    "analysis.json",
    "artifact_manifest.json",
    "inputs_manifest.json",
    "provenance.json",
    "trace.jsonl",
    "trajectory.json",
    "reward_breakdown.json",
    "stdout.txt",
    "stderr.txt",
    "hash.json",
    "research_episode.json",
    "option_set.json",
    "evidence_gate.json",
    "commitment.json",
    "claim_report.json",
    "claim_update.json",
}


def _is_test_env() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


# Initialize router
router = APIRouter(prefix="/api/jobs", tags=["job-management"])

# ============================================================================
# Enhanced Models
# ============================================================================


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CANCELLING = "cancelling"
    SKIPPED = "skipped"
    PAUSED = "paused"
    RETRYING = "retrying"
    TIMEOUT = "timeout"


class JobPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class ResourceType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    GPU = "gpu"
    STORAGE = "storage"
    NETWORK = "network"


class JobMetrics(BaseModel):
    """Job performance metrics"""

    cpu_usage: float | None = Field(
        None, ge=0.0, le=100.0, description="CPU usage percentage"
    )
    memory_usage: float | None = Field(None, ge=0.0, description="Memory usage in GB")
    gpu_usage: float | None = Field(
        None, ge=0.0, le=100.0, description="GPU usage percentage"
    )
    disk_io: float | None = Field(None, ge=0.0, description="Disk I/O rate in MB/s")
    network_io: float | None = Field(
        None, ge=0.0, description="Network I/O rate in MB/s"
    )
    peak_memory: float | None = Field(
        None, ge=0.0, description="Peak memory usage in GB"
    )
    total_compute_time: float | None = Field(
        None, ge=0.0, description="Total compute time in seconds"
    )


class JobStep(BaseModel):
    """Enhanced job step with detailed tracking"""

    id: str = Field(..., description="Step identifier")
    name: str = Field(..., description="Step name")
    description: str | None = Field(None, description="Step description")
    tool: str = Field(..., description="Tool/service executing this step")
    status: StepStatus = Field(default=StepStatus.PENDING)
    progress: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Progress percentage"
    )

    # Timing information
    start_time: datetime | None = None
    end_time: datetime | None = None
    estimated_duration: int | None = Field(
        None, description="Estimated duration in seconds"
    )

    # Step details
    args: dict[str, Any] = Field(default_factory=dict)
    preview: str | None = Field(None, description="Step output preview")
    error: str | None = Field(None, description="Error message if failed")

    # Dependencies and ordering
    depends_on: list[str] = Field(
        default_factory=list, description="Step IDs this step depends on"
    )
    order: int = Field(default=0, description="Execution order")

    # Resource usage
    metrics: JobMetrics | None = None

    # Retry information
    retry_count: int = Field(default=0, description="Number of retries attempted")
    max_retries: int = Field(default=3, description="Maximum retry attempts")

    # Phase 3: Cache integration
    cache_metadata: CacheMetadata | None = Field(
        None, description="Cache hit/miss metadata for this step"
    )


class JobArtifact(BaseModel):
    """Job output artifact"""

    id: str = Field(..., description="Artifact identifier")
    name: str = Field(..., description="Artifact name")
    type: str = Field(..., description="Artifact type")
    path: str | None = Field(None, description="File path")
    url: str | None = Field(None, description="Access URL")
    size: int | None = Field(None, description="File size in bytes")
    checksum: str | None = Field(None, description="File checksum")
    mime_type: str | None = Field(None, description="MIME type")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class JobDependency(BaseModel):
    """Job dependency specification"""

    job_id: str = Field(..., description="Dependent job ID")
    dependency_type: str = Field(default="completion", description="Type of dependency")
    required_status: JobStatus = Field(default=JobStatus.COMPLETED)


class Job(BaseModel):
    """Enhanced job model with comprehensive tracking"""

    id: str = Field(..., description="Job identifier")
    name: str | None = Field(None, description="Job name")
    description: str | None = Field(None, description="Job description")
    prompt: str = Field(..., description="Original user prompt")

    # Status and lifecycle
    status: JobStatus = Field(default=JobStatus.PENDING)
    priority: JobPriority = Field(default=JobPriority.NORMAL)
    progress: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Overall progress percentage"
    )

    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    estimated_completion: datetime | None = None

    # User and context
    user_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None

    # Execution details
    steps: list[JobStep] = Field(default_factory=list)
    current_step_index: int = Field(
        default=0, description="Index of currently executing step"
    )
    artifacts: list[JobArtifact] = Field(default_factory=list)

    # Resource requirements and usage
    resource_requirements: dict[str, Any] = Field(default_factory=dict)
    resource_usage: JobMetrics | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat: datetime | None = None
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    gpu_count_required: int = Field(default=0, ge=0)
    gpu_type: str | None = None
    assigned_gpu_slots: list[int] = Field(default_factory=list)
    run_id: str | None = None
    run_dir: str | None = None
    provenance_path: str | None = None

    # Dependencies
    dependencies: list[JobDependency] = Field(default_factory=list)
    dependent_jobs: list[str] = Field(
        default_factory=list, description="Jobs that depend on this job"
    )

    # Error handling
    error: str | None = None
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)

    # Metadata
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    plan_of_record: dict[str, Any] | None = None
    plan_events: list[dict[str, Any]] = Field(default_factory=list)
    por_token: str | None = None

    # Phase 3: Cache integration
    cache_metadata: CacheMetadata | None = Field(
        None, description="Cache hit/miss metadata"
    )

    # Cancellation
    cancellation_requested: bool = Field(default=False)
    cancellation_reason: str | None = None


class JobProgressUpdate(BaseModel):
    """Job progress update event"""

    job_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    update_type: str = Field(..., description="Type of update")
    data: dict[str, Any] = Field(default_factory=dict)


class PlanOfRecordResponse(BaseModel):
    plan: dict[str, Any]
    por_token: str | None = None


class PlanEventsResponse(BaseModel):
    plan_id: str
    events: list[dict[str, Any]] = Field(default_factory=list)


class JobSearchRequest(BaseModel):
    """Job search and filter request"""

    user_id: str | None = None
    status: list[JobStatus] | None = None
    priority: list[JobPriority] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    tags: list[str] | None = None
    search_query: str | None = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)
    sort_by: str = Field("created_at", description="Sort field")
    sort_desc: bool = Field(True, description="Sort descending")


class JobStatistics(BaseModel):
    """Job execution statistics"""

    total_jobs: int
    status_breakdown: dict[JobStatus, int]
    priority_breakdown: dict[JobPriority, int]
    avg_execution_time: float
    success_rate: float
    retry_rate: float
    most_common_errors: list[dict[str, Any]]
    resource_utilization: dict[str, float]
    throughput_per_hour: float


class CreateJobPayload(BaseModel):
    """Request body accepted by POST /api/jobs.

    This is a thin compatibility layer for the Web UI while the system
    converges on contracts-first submission payloads.
    """

    prompt: str = Field(..., description="User prompt / request")
    pipeline: str | None = Field(default=None, description="Requested pipeline/kind")
    dataset_id: str | None = Field(default=None, alias="datasetId")
    parameters: dict[str, Any] = Field(default_factory=dict)
    copilot: bool = False
    attachments: list[Any] = Field(default_factory=list)
    scenario_id: str | None = Field(default=None, alias="scenarioId")
    checkpoint_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_checkpoint_id(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            return values
        if not values.get("checkpoint_id") and values.get("resume_checkpoint_id"):
            values["checkpoint_id"] = values.get("resume_checkpoint_id")
        values.pop("resume_checkpoint_id", None)
        return values

    model_config = {"populate_by_name": True}


# ============================================================================
# In-Memory Storage (Replace with Database in production)
# ============================================================================

# Job storage (router-local; synced from core store on demand)
jobs_db: dict[str, Job] = {}
job_history: dict[str, list[JobProgressUpdate]] = defaultdict(list)

# Real-time updates
job_subscribers: dict[str, set[WebSocket]] = defaultdict(set)  # job_id -> websockets
progress_queues: dict[str, asyncio.Queue] = {}  # job_id -> update queue

# Job execution queue
job_queue: deque = deque()  # Priority queue for pending jobs
running_jobs: set[str] = set()  # Currently running job IDs

# ---------------------------------------------------------------------------
# Helpers to convert orchestrator core jobs into the router's richer schema
# ---------------------------------------------------------------------------


def _coerce_job_status(value: Any) -> JobStatus:
    try:
        if isinstance(value, JobStatus):
            return value
        return JobStatus(value)
    except Exception:
        return JobStatus.PENDING


def _coerce_step_status(value: Any) -> StepStatus:
    try:
        if isinstance(value, StepStatus):
            return value
        return StepStatus(value)
    except Exception:
        return StepStatus.PENDING


def _core_step_to_router_step(step: core_models.JobStep, order: int) -> JobStep:
    timing = getattr(step, "timing", None)
    start_time = getattr(timing, "start_time", None) if timing else None
    end_time = getattr(timing, "end_time", None) if timing else None
    progress_pct = (
        100.0
        if getattr(step, "status", None) == core_models.StepStatus.COMPLETED
        else 0.0
    )

    return JobStep(
        id=getattr(step, "id", f"step_{order}"),
        name=getattr(step, "name", getattr(step, "tool", f"Step {order+1}")),
        description=getattr(step, "description", None),
        tool=getattr(step, "tool", "unknown"),
        status=_coerce_step_status(getattr(step, "status", StepStatus.PENDING)),
        progress=progress_pct,
        start_time=start_time,
        end_time=end_time,
        estimated_duration=None,
        args=getattr(step, "args", {}) or {},
        preview=getattr(step, "preview", None),
        error=getattr(step, "error", None),
        depends_on=[],
        order=order,
        metrics=None,
        retry_count=getattr(step, "retry_count", 0),
        max_retries=getattr(step, "max_retries", 3),
    )


def _core_artifact_to_router_artifact(artifact: core_models.JobArtifact) -> JobArtifact:
    meta = getattr(artifact, "meta", {}) or {}
    artifact_type = getattr(artifact, "type", None)
    if hasattr(artifact_type, "value"):
        artifact_type = artifact_type.value
    return JobArtifact(
        id=getattr(artifact, "id", f"artifact_{uuid.uuid4().hex[:8]}"),
        name=getattr(artifact, "name", "artifact"),
        type=str(artifact_type or "artifact"),
        path=meta.get("path"),
        url=getattr(artifact, "url", None),
        size=getattr(artifact, "size_bytes", None),
        checksum=getattr(artifact, "checksum", None),
        mime_type=meta.get("mime_type"),
        metadata=meta,
    )


def _core_job_to_router_job(core_job: core_models.Job) -> Job:
    metadata = getattr(core_job, "metadata", {}) or {}
    timing = getattr(core_job, "timing", None)
    start_time = getattr(timing, "start_time", None) if timing else None
    end_time = getattr(timing, "end_time", None) if timing else None
    progress_obj = getattr(core_job, "progress", None)
    progress_pct = getattr(progress_obj, "percentage", None)
    if progress_pct is None:
        progress_pct = 0.0

    steps = [
        _core_step_to_router_step(step, idx)
        for idx, step in enumerate(getattr(core_job, "steps", []) or [])
    ]
    artifacts = [
        _core_artifact_to_router_artifact(artifact)
        for artifact in getattr(core_job, "artifacts", []) or []
    ]

    error_obj = getattr(core_job, "error", None)
    if isinstance(error_obj, core_models.ErrorResponse):
        error_message = error_obj.message
    else:
        error_message = error_obj

    return Job(
        id=getattr(core_job, "id", f"job_{uuid.uuid4().hex[:8]}"),
        name=metadata.get("name"),
        description=metadata.get("description"),
        prompt=getattr(core_job, "prompt", ""),
        status=_coerce_job_status(getattr(core_job, "status", JobStatus.PENDING)),
        priority=metadata.get("priority", JobPriority.NORMAL),
        progress=float(progress_pct or 0.0),
        created_at=start_time or datetime.utcnow(),
        queued_at=metadata.get("queued_at", start_time),
        started_at=metadata.get("started_at", start_time),
        completed_at=end_time,
        estimated_completion=metadata.get("estimated_completion"),
        user_id=getattr(core_job, "user_id", None) or metadata.get("user_id"),
        session_id=(
            getattr(core_job, "session_id", None)
            or metadata.get("thread_id")
            or metadata.get("session_id")
        ),
        project_id=getattr(core_job, "project_id", None) or metadata.get("project_id"),
        steps=steps,
        current_step_index=metadata.get("current_step_index", 0),
        artifacts=artifacts,
        resource_requirements=metadata.get("resource_requirements", {}),
        resource_usage=None,
        dependencies=metadata.get("dependencies", []),
        dependent_jobs=metadata.get("dependent_jobs", []),
        error=error_message,
        retry_count=metadata.get("retry_count", 0),
        max_retries=metadata.get("max_retries", 3),
        tags=metadata.get("tags", []),
        metadata=metadata,
        cancellation_requested=metadata.get("cancellation_requested", False),
        cancellation_reason=metadata.get("cancellation_reason"),
    )


def _sync_router_jobs_from_core(job_ids: Iterable[str] | None = None) -> None:
    """Ensure router-visible jobs mirror the latest orchestrator state."""

    if job_ids is None:
        ids_to_sync = list(core_jobs_db.keys())
    else:
        ids_to_sync = list(job_ids)

    if not ids_to_sync:
        return

    for job_id in ids_to_sync:
        core_job = core_jobs_db.get(job_id)
        if not core_job:
            continue
        jobs_db[job_id] = _core_job_to_router_job(core_job)


def _get_router_job(job_id: str) -> Job | None:
    if job_id in core_jobs_db:
        _sync_router_jobs_from_core([job_id])
    return jobs_db.get(job_id)


async def _get_job_with_store(job_id: str, request: Request) -> Job | None:
    job = _get_router_job(job_id)
    if job:
        return _hydrate_plan_metadata(job)

    job_store = getattr(request.app.state, "job_store", None)
    if job_store:
        record = await job_store.get(job_id)
        if record:
            try:
                job_obj = JobAdapter.from_record(record)
                return _hydrate_plan_metadata(job_obj)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("JobAdapter.from_record failed for %s: %s", job_id, exc)
    return None


def _extract_plan_bundle(
    job: Job,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    metadata = getattr(job, "metadata", {}) or {}
    plan = getattr(job, "plan_of_record", None) or metadata.get("plan_of_record")
    events = getattr(job, "plan_events", None) or metadata.get("plan_events") or []
    por_token = getattr(job, "por_token", None) or metadata.get("por_token")
    return plan, events, por_token


def _hydrate_plan_metadata(job: Job | None) -> Job | None:
    """Ensure plan fields live on the Job payload returned to clients."""
    if not job:
        return job

    plan, events, por_token = _extract_plan_bundle(job)
    if plan is not None:
        job.plan_of_record = copy.deepcopy(plan)
    elif getattr(job, "plan_of_record", None) is None:
        job.plan_of_record = None

    job.plan_events = copy.deepcopy(events) if events else []
    job.por_token = por_token
    _hydrate_cache_metadata(job)
    return job


def _hydrate_cache_metadata(job: Job) -> None:
    """Populate structured cache metadata field from legacy metadata dict."""
    metadata = getattr(job, "metadata", {}) or {}
    cache_info = metadata.get("cache") or {}

    cache_key = cache_info.get("key") or metadata.get("cache_key")
    cache_hit = cache_info.get("hit", metadata.get("cache_hit"))
    cached_run_id = cache_info.get("run_id") or cache_info.get("source_run_id")
    cache_timestamp = cache_info.get("timestamp") or metadata.get("cache_timestamp")

    if cache_key or cache_hit is not None or cached_run_id or cache_timestamp:
        job.cache_metadata = CacheMetadata(
            cache_key=cache_key,
            cache_hit=bool(cache_hit),
            cached_run_id=cached_run_id,
            cache_timestamp=cache_timestamp,
        )
    else:
        job.cache_metadata = None


def _build_plan_summary(job: Job) -> dict[str, Any] | None:
    """Create a lightweight summary describing the plan-of-record."""
    plan, events, por_token = _extract_plan_bundle(job)
    if not plan:
        return None

    dag = plan.get("dag") or {}
    if isinstance(dag, dict):
        steps = dag.get("steps", [])
    elif isinstance(dag, list):
        steps = dag
    else:
        steps = []

    last_event = events[-1] if events else None
    last_event_type = last_event.get("event") if isinstance(last_event, dict) else None

    return {
        "plan_id": plan.get("plan_id"),
        "version": plan.get("version", 1),
        "resolvable": plan.get("resolvable"),
        "step_count": len(steps),
        "por_token_set": bool(por_token),
        "plan_status": last_event_type or "planned",
        "plan_conf": plan.get("plan_conf")
        or (plan.get("run_summary") or {}).get("plan_conf"),
        "confidence_score": plan.get("confidence_score")
        or (plan.get("run_summary") or {}).get("plan_conf"),
    }


def _truncate_events(
    events: list[dict[str, Any]], max_events: int = 25
) -> list[dict[str, Any]]:
    """Truncate plan events to most recent N events to avoid bloated payloads."""
    if not events:
        return []
    if len(events) <= max_events:
        return events
    return events[-max_events:]  # Return most recent N events


# Statistics tracking
job_stats_cache: dict[str, Any] = {}
stats_cache_time: datetime | None = None

# Execution history for analytics
execution_history: deque = deque(maxlen=10000)  # Recent job completions

# ============================================================================
# Job Queue Management
# ============================================================================


class JobQueueManager:
    """Manages job queuing and prioritization"""

    @staticmethod
    def add_to_queue(job: Job):
        """Add job to execution queue based on priority"""
        # Higher priority jobs go to the front
        priority_order = {
            JobPriority.CRITICAL: 0,
            JobPriority.HIGH: 1,
            JobPriority.NORMAL: 2,
            JobPriority.LOW: 3,
        }

        job_tuple = (priority_order[job.priority], job.created_at, job.id)

        # Insert in priority order
        inserted = False
        for i, (existing_priority, existing_time, existing_id) in enumerate(job_queue):
            if job_tuple < (existing_priority, existing_time, existing_id):
                job_queue.insert(i, job_tuple)
                inserted = True
                break

        if not inserted:
            job_queue.append(job_tuple)

        logger.info(f"Job {job.id} added to queue (priority: {job.priority})")

    @staticmethod
    def get_next_job() -> str | None:
        """Get next job from queue"""
        if job_queue:
            _, _, job_id = job_queue.popleft()
            return job_id
        return None

    @staticmethod
    def get_queue_status() -> dict[str, Any]:
        """Get current queue status"""
        queue_breakdown = defaultdict(int)
        estimated_wait_times = {}

        for i, (_priority_num, _created_at, job_id) in enumerate(job_queue):
            if job_id in jobs_db:
                job = jobs_db[job_id]
                queue_breakdown[job.priority] += 1

                # Rough estimate: assume 5 minutes per job ahead in queue
                estimated_wait_times[job_id] = i * 5

        return {
            "queue_length": len(job_queue),
            "running_jobs": len(running_jobs),
            "queue_breakdown": dict(queue_breakdown),
            "estimated_wait_times": estimated_wait_times,
        }


# ============================================================================
# Progress Tracking
# ============================================================================


class ProgressTracker:
    """Tracks and manages job progress"""

    @staticmethod
    async def update_job_progress(
        job_id: str, progress: float, message: str | None = None
    ):
        """Update overall job progress"""
        if job_id not in jobs_db:
            return

        job = jobs_db[job_id]
        job.progress = progress

        # Create progress update
        update = JobProgressUpdate(
            job_id=job_id,
            update_type="progress",
            data={"progress": progress, "message": message, "status": job.status},
        )

        job_history[job_id].append(update)

        # Notify subscribers
        await ProgressTracker.notify_subscribers(job_id, update)

    @staticmethod
    async def update_step_progress(
        job_id: str, step_id: str, progress: float, status: StepStatus | None = None
    ):
        """Update individual step progress"""
        if job_id not in jobs_db:
            return

        job = jobs_db[job_id]

        # Find and update step
        for step in job.steps:
            if step.id == step_id:
                step.progress = progress
                if status:
                    step.status = status
                break

        # Recalculate overall job progress
        if job.steps:
            total_progress = sum(step.progress for step in job.steps)
            overall_progress = total_progress / len(job.steps)
            await ProgressTracker.update_job_progress(job_id, overall_progress)

    @staticmethod
    async def notify_subscribers(job_id: str, update: JobProgressUpdate):
        """Notify WebSocket subscribers of updates"""
        if job_id in job_subscribers:
            message = {
                "type": "progress_update",
                "job_id": job_id,
                "timestamp": update.timestamp.isoformat(),
                "data": update.data,
            }

            # Send to all subscribers
            disconnected_sockets = []
            for websocket in job_subscribers[job_id]:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send update to subscriber: {e}")
                    disconnected_sockets.append(websocket)

            # Clean up disconnected sockets
            for ws in disconnected_sockets:
                job_subscribers[job_id].discard(ws)


# ============================================================================
# Job Execution Engine
# ============================================================================


class JobExecutor:
    """Executes jobs and manages their lifecycle"""

    @staticmethod
    async def execute_job(job_id: str):
        """Execute a job with full progress tracking"""
        if job_id not in jobs_db:
            return

        job = jobs_db[job_id]

        try:
            # Mark as running
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            running_jobs.add(job_id)

            await ProgressTracker.update_job_progress(
                job_id, 0.0, "Starting job execution"
            )

            # Execute each step
            for i, step in enumerate(job.steps):
                job.current_step_index = i

                # Check for cancellation
                if job.cancellation_requested:
                    await JobExecutor.cancel_job(job_id, "User requested cancellation")
                    return

                # Execute step
                await JobExecutor.execute_step(job_id, step.id)

                # Update overall progress
                step_progress = (i + 1) / len(job.steps) * 100
                await ProgressTracker.update_job_progress(
                    job_id, step_progress, f"Completed step: {step.name}"
                )

            # Mark as completed
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.progress = 100.0

            await ProgressTracker.update_job_progress(
                job_id, 100.0, "Job completed successfully"
            )

            # Record completion in history
            execution_time = (job.completed_at - job.started_at).total_seconds()
            execution_history.append(
                {
                    "job_id": job_id,
                    "execution_time": execution_time,
                    "status": JobStatus.COMPLETED,
                    "completed_at": job.completed_at,
                    "retry_count": job.retry_count,
                }
            )

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")

            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()

            await ProgressTracker.update_job_progress(
                job_id, job.progress, f"Job failed: {str(e)}"
            )

            # Consider retry
            if job.retry_count < job.max_retries:
                await JobExecutor.retry_job(job_id)

        finally:
            running_jobs.discard(job_id)

    @staticmethod
    async def execute_step(job_id: str, step_id: str):
        """Execute a single job step"""
        if job_id not in jobs_db:
            return

        job = jobs_db[job_id]
        step = next((s for s in job.steps if s.id == step_id), None)

        if not step:
            return

        try:
            step.status = StepStatus.RUNNING
            step.start_time = datetime.utcnow()

            await ProgressTracker.update_step_progress(
                job_id, step_id, 0.0, StepStatus.RUNNING
            )

            # Simulate step execution (replace with actual tool execution)
            if step.tool == "agent":
                # Execute via agent service
                result = await JobExecutor.execute_agent_step(step)
            elif step.tool == "br_kg":
                # Execute via BR-KG service
                result = await JobExecutor.execute_br_kg_step(step)
            else:
                # Simulate generic step
                await asyncio.sleep(2)  # Simulate work
                result = {"success": True, "output": f"Step {step.name} completed"}

            step.status = StepStatus.COMPLETED
            step.end_time = datetime.utcnow()
            step.preview = result.get("preview", "Step completed successfully")

            await ProgressTracker.update_step_progress(
                job_id, step_id, 100.0, StepStatus.COMPLETED
            )

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.end_time = datetime.utcnow()

            await ProgressTracker.update_step_progress(
                job_id, step_id, step.progress, StepStatus.FAILED
            )

            raise e

    @staticmethod
    async def execute_agent_step(step: JobStep) -> dict[str, Any]:
        """Execute step via Agent service"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{AGENT_URL}/execute",
                    json={"tool": step.tool, "args": step.args, "step_id": step.id},
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Agent step execution failed: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def execute_br_kg_step(step: JobStep) -> dict[str, Any]:
        """Execute step via BR-KG service"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{BR_KG_URL}/api/execute",
                    json={
                        "operation": step.tool,
                        "parameters": step.args,
                        "step_id": step.id,
                    },
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"BR-KG step execution failed: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def cancel_job(job_id: str, reason: str | None = None):
        """Cancel a running job"""
        if job_id not in jobs_db:
            return

        job = jobs_db[job_id]
        job.status = JobStatus.CANCELLED
        job.cancellation_requested = True
        job.cancellation_reason = reason or "Job cancelled"
        job.completed_at = datetime.utcnow()

        # Cancel current step
        if job.current_step_index < len(job.steps):
            current_step = job.steps[job.current_step_index]
            current_step.status = StepStatus.SKIPPED
            current_step.end_time = datetime.utcnow()

        await ProgressTracker.update_job_progress(
            job_id, job.progress, f"Job cancelled: {reason}"
        )

        running_jobs.discard(job_id)

    @staticmethod
    async def retry_job(job_id: str):
        """Retry a failed job"""
        if job_id not in jobs_db:
            return

        job = jobs_db[job_id]

        if job.retry_count >= job.max_retries:
            logger.warning(f"Job {job_id} exceeded max retries")
            return

        job.retry_count += 1
        job.status = JobStatus.RETRYING
        job.error = None

        # Reset failed steps
        for step in job.steps:
            if step.status == StepStatus.FAILED:
                step.status = StepStatus.PENDING
                step.error = None
                step.progress = 0.0

        # Add back to queue with higher priority
        if job.priority != JobPriority.CRITICAL:
            if job.priority == JobPriority.LOW:
                job.priority = JobPriority.NORMAL
            elif job.priority == JobPriority.NORMAL:
                job.priority = JobPriority.HIGH

        JobQueueManager.add_to_queue(job)

        await ProgressTracker.update_job_progress(
            job_id, 0.0, f"Retrying job (attempt {job.retry_count + 1})"
        )


# ============================================================================
# Statistics and Analytics
# ============================================================================


def calculate_job_statistics() -> JobStatistics:
    """Calculate comprehensive job statistics"""
    global stats_cache_time, job_stats_cache

    # Use cache if recent
    if stats_cache_time and datetime.utcnow() - stats_cache_time < timedelta(minutes=5):
        return JobStatistics(**job_stats_cache)

    jobs = list(jobs_db.values())
    total_jobs = len(jobs)

    if total_jobs == 0:
        return JobStatistics(
            total_jobs=0,
            status_breakdown={},
            priority_breakdown={},
            avg_execution_time=0.0,
            success_rate=0.0,
            retry_rate=0.0,
            most_common_errors=[],
            resource_utilization={},
            throughput_per_hour=0.0,
        )

    # Status breakdown
    status_breakdown = defaultdict(int)
    for job in jobs:
        status_breakdown[job.status] += 1

    # Priority breakdown
    priority_breakdown = defaultdict(int)
    for job in jobs:
        priority_breakdown[job.priority] += 1

    # Calculate execution times
    execution_times = []
    successful_jobs = 0
    retry_jobs = 0

    for job in jobs:
        if job.status == JobStatus.COMPLETED and job.started_at and job.completed_at:
            execution_time = (job.completed_at - job.started_at).total_seconds()
            execution_times.append(execution_time)
            successful_jobs += 1

        if job.retry_count > 0:
            retry_jobs += 1

    avg_execution_time = statistics.mean(execution_times) if execution_times else 0.0
    success_rate = (successful_jobs / total_jobs) * 100 if total_jobs > 0 else 0.0
    retry_rate = (retry_jobs / total_jobs) * 100 if total_jobs > 0 else 0.0

    # Most common errors
    error_counts = defaultdict(int)
    for job in jobs:
        if job.error:
            error_counts[job.error] += 1

    most_common_errors = [
        {"error": error, "count": count}
        for error, count in sorted(
            error_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]
    ]

    # Calculate throughput (jobs completed in last hour)
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent_completions = len(
        [job for job in jobs if job.completed_at and job.completed_at >= one_hour_ago]
    )

    # Resource utilization (mock data - would come from actual monitoring)
    resource_utilization = {"cpu": 65.5, "memory": 78.2, "gpu": 45.0, "storage": 34.8}

    stats = JobStatistics(
        total_jobs=total_jobs,
        status_breakdown=dict(status_breakdown),
        priority_breakdown=dict(priority_breakdown),
        avg_execution_time=avg_execution_time,
        success_rate=success_rate,
        retry_rate=retry_rate,
        most_common_errors=most_common_errors,
        resource_utilization=resource_utilization,
        throughput_per_hour=recent_completions,
    )

    # Cache results
    job_stats_cache = stats.model_dump()
    stats_cache_time = datetime.utcnow()

    return stats


# ============================================================================
# API Endpoints
# ============================================================================


@router.post("", response_model=JobRecordV1)
async def create_job(
    request: Request,
    payload: CreateJobPayload | None = Body(None),
    prompt: str | None = Query(None, description="Job prompt (legacy query param)"),
    name: str | None = Query(None, description="Job name"),
    priority: JobPriority = Query(JobPriority.NORMAL),
    user_id: str | None = Query(None),
    tags: list[str] | None = Query(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> JobRecordV1:
    """Create and queue a new job"""

    prompt_value = (payload.prompt if payload else None) or prompt
    if not prompt_value:
        raise HTTPException(status_code=422, detail="prompt is required")

    # Admission control: cap queue length to prevent unbounded backlog.
    current_queue_length = len(job_queue)
    job_store = getattr(request.app.state, "job_store", None)
    if job_store is not None:
        try:
            stats = await job_store.get_queue_stats()
            current_queue_length = int(stats.get("queued", 0)) + int(
                stats.get("pending", 0)
            )
        except Exception:
            pass
    if current_queue_length >= MAX_QUEUE_LENGTH:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Queue is full (len={current_queue_length}, "
                f"limit={MAX_QUEUE_LENGTH}); try again later."
            ),
            headers={"Retry-After": str(QUEUE_RETRY_AFTER_SEC)},
        )

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    # Create job with initial steps (this would be determined by job type)
    job = Job(
        id=job_id,
        name=name or f"Job {job_id}",
        prompt=prompt_value,
        priority=priority,
        user_id=user_id,
        tags=tags or [],
        steps=[
            JobStep(
                id="step_1",
                name="Initialize",
                description="Initialize job execution",
                tool="system",
            ),
            JobStep(
                id="step_2",
                name="Process Query",
                description="Process user query through agent",
                tool="agent",
                args={"prompt": prompt_value},
            ),
            JobStep(
                id="step_3",
                name="Finalize",
                description="Finalize results and cleanup",
                tool="system",
            ),
        ],
    )

    # Store job
    jobs_db[job_id] = job
    progress_queues[job_id] = asyncio.Queue()

    # Add to execution queue
    job.status = JobStatus.QUEUED
    job.queued_at = datetime.utcnow()
    JobQueueManager.add_to_queue(job)

    # Start execution in background (disabled in unit tests to avoid slow/flaky
    # network calls to downstream services).
    if not _is_test_env():
        background_tasks.add_task(JobExecutor.execute_job, job_id)

    record: JobRecord | None = None
    if job_store is not None:
        try:
            record = JobAdapter.to_record(job)
            await job_store.enqueue(record)
        except Exception as exc:
            logger.warning("Failed to enqueue job %s into JobStore: %s", job_id, exc)

    if record is None:
        record = JobAdapter.to_record(job)

    return record


@router.get("/{job_id}", response_model=JobRecordV1)
async def get_job(job_id: str, request: Request) -> JobRecordV1:
    """Get job record (contract-first)."""
    job_store = getattr(request.app.state, "job_store", None)
    if job_store is not None:
        try:
            record = await job_store.get(job_id)
            if record is not None:
                return record
        except Exception as exc:
            logger.warning(
                "JobStore lookup failed for %s: %s; falling back to legacy store",
                job_id,
                exc,
            )

    job = _get_router_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobAdapter.to_record(_hydrate_plan_metadata(job))


@router.post("/resolve")
async def resolve_cached_run(
    request: Request,
    cache_key: str = Query(..., description="Cache key to resolve"),
) -> dict[str, Any]:
    """Phase 3.1: Resolve a cache key to a completed run.

    This endpoint checks if a cache key exists and returns the run_dir
    for cache hits, allowing results to be reused without recomputation.

    Args:
        cache_key: Cache key to look up

    Returns:
        Dict with cache_hit, run_id, run_dir if found
    """
    try:
        cache_store = getattr(request.app.state, "cache_store", None)
        if cache_store is None:
            try:
                from brain_researcher.services.orchestrator.main_enhanced import (
                    cache_store as orchestrator_cache,
                )
            except ImportError:
                orchestrator_cache = None
            cache_store = orchestrator_cache

        if cache_store is None:
            raise HTTPException(status_code=503, detail="Cache store not configured")

        entry = await cache_store.lookup(cache_key)

        if entry and entry.state == "completed":
            return {
                "cache_hit": True,
                "run_id": entry.run_id,
                "run_dir": entry.run_dir,
                "cache_timestamp": entry.created_at,
                "cache_metadata": {
                    "tool_version": entry.tool_version,
                    "git_sha": entry.git_sha,
                    "size_bytes": entry.size_bytes,
                },
            }
        else:
            return {
                "cache_hit": False,
                "cache_key": cache_key,
            }
    except Exception as e:
        logger.error(f"Cache lookup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Cache lookup error: {str(e)}")


@router.post("/{job_id}/cancel")
async def cancel_job_endpoint(
    job_id: str, reason: str | None = Query(None, description="Cancellation reason")
) -> dict[str, str]:
    """Cancel a job"""
    job = _get_router_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Cannot cancel terminal states
    if job.status in [
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.TIMEOUT,
        JobStatus.SKIPPED,
    ]:
        raise HTTPException(
            status_code=400, detail=f"Cannot cancel job with status: {job.status}"
        )

    await JobExecutor.cancel_job(job_id, reason)

    return {"status": "cancelled", "job_id": job_id}


@router.post("/{job_id}/retry")
async def retry_job_endpoint(
    job_id: str, background_tasks: BackgroundTasks
) -> dict[str, str]:
    """Retry a failed job"""
    job = _get_router_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="Only failed jobs can be retried")

    background_tasks.add_task(JobExecutor.retry_job, job_id)

    return {"status": "retrying", "job_id": job_id}


@router.post("/search", response_model=dict[str, Any])
async def search_jobs(request: JobSearchRequest) -> dict[str, Any]:
    """Search and filter jobs"""

    _sync_router_jobs_from_core()

    # Filter jobs based on criteria
    filtered_jobs = list(jobs_db.values())

    if request.user_id:
        filtered_jobs = [j for j in filtered_jobs if j.user_id == request.user_id]

    if request.status:
        filtered_jobs = [j for j in filtered_jobs if j.status in request.status]

    if request.priority:
        filtered_jobs = [j for j in filtered_jobs if j.priority in request.priority]

    if request.created_after:
        filtered_jobs = [
            j for j in filtered_jobs if j.created_at >= request.created_after
        ]

    if request.created_before:
        filtered_jobs = [
            j for j in filtered_jobs if j.created_at <= request.created_before
        ]

    if request.tags:
        filtered_jobs = [
            j for j in filtered_jobs if any(tag in j.tags for tag in request.tags)
        ]

    if request.search_query:
        query_lower = request.search_query.lower()
        filtered_jobs = [
            j
            for j in filtered_jobs
            if (
                query_lower in j.prompt.lower()
                or (j.name and query_lower in j.name.lower())
                or (j.description and query_lower in j.description.lower())
            )
        ]

    # Sort jobs
    reverse = request.sort_desc
    if request.sort_by == "created_at":
        filtered_jobs.sort(key=lambda j: j.created_at, reverse=reverse)
    elif request.sort_by == "priority":
        priority_order = {
            JobPriority.CRITICAL: 0,
            JobPriority.HIGH: 1,
            JobPriority.NORMAL: 2,
            JobPriority.LOW: 3,
        }
        filtered_jobs.sort(key=lambda j: priority_order[j.priority], reverse=reverse)
    elif request.sort_by == "progress":
        filtered_jobs.sort(key=lambda j: j.progress, reverse=reverse)
    elif request.sort_by == "status":
        filtered_jobs.sort(key=lambda j: j.status, reverse=reverse)

    # Paginate
    total = len(filtered_jobs)
    paginated_jobs = filtered_jobs[request.offset : request.offset + request.limit]

    serialized_jobs = []
    for job in paginated_jobs:
        hydrated = _hydrate_plan_metadata(job)
        job_payload = hydrated.model_dump()
        # Remove any pre-existing serialized summaries to avoid duplications from metadata
        job_payload.pop("plan_summary", None)
        plan_summary = _build_plan_summary(hydrated)
        if plan_summary:
            job_payload["plan_summary"] = plan_summary
        serialized_jobs.append(job_payload)

    return {
        "jobs": serialized_jobs,
        "total": total,
        "limit": request.limit,
        "offset": request.offset,
        "has_more": request.offset + request.limit < total,
    }


@router.get("/{job_id}/progress")
async def get_job_progress(job_id: str) -> dict[str, Any]:
    """Get detailed job progress information"""
    job = _get_router_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Hydrate plan metadata so plan_summary can be built
    job = _hydrate_plan_metadata(job)
    return _build_job_progress_payload(job_id, job)


def _build_job_progress_payload(job_id: str, job: Job) -> dict[str, Any]:
    """Build the progress payload shared by polling and SSE endpoints."""
    overall_progress = float(getattr(job, "progress", 0.0) or 0.0)
    if job.status == JobStatus.COMPLETED and overall_progress < 100.0:
        overall_progress = 100.0

    step_progress: list[dict[str, Any]] = []
    for step in job.steps:
        step_info: dict[str, Any] = {
            "id": step.id,
            "name": step.name,
            "status": step.status,
            "progress": step.progress,
            "start_time": step.start_time.isoformat() if step.start_time else None,
            "end_time": step.end_time.isoformat() if step.end_time else None,
            "duration": None,
        }

        if step.start_time and step.end_time:
            step_info["duration"] = (step.end_time - step.start_time).total_seconds()
        step_progress.append(step_info)

    time_estimates: dict[str, Any] = {}
    if job.started_at:
        elapsed = (datetime.utcnow() - job.started_at).total_seconds()
        if overall_progress > 0:
            estimated_total = (elapsed / overall_progress) * 100
            time_estimates["estimated_remaining"] = max(0, estimated_total - elapsed)
            time_estimates["estimated_completion"] = datetime.utcnow() + timedelta(
                seconds=time_estimates["estimated_remaining"]
            )
        time_estimates["elapsed"] = elapsed

    response: dict[str, Any] = {
        "job_id": job_id,
        "status": job.status,
        "overall_progress": overall_progress,
        "current_step": job.current_step_index,
        "step_progress": step_progress,
        "time_estimates": time_estimates,
        "resource_usage": (
            job.resource_usage.model_dump() if job.resource_usage else None
        ),
        "last_updated": datetime.utcnow().isoformat(),
    }

    plan_summary = _build_plan_summary(job)
    if plan_summary:
        response["plan_summary"] = plan_summary
        _, plan_events, _ = _extract_plan_bundle(job)
        if plan_events:
            response["plan_events"] = _truncate_events(plan_events, max_events=25)

    return response


@router.websocket("/{job_id}/ws")
async def websocket_job_progress(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job progress updates"""
    job = _get_router_job(job_id)
    if not job:
        await websocket.close(code=4004, reason="Job not found")
        return

    job = _hydrate_plan_metadata(job)
    await websocket.accept()
    job_subscribers[job_id].add(websocket)

    try:
        # Send initial job state with plan_summary if available
        job_dict = job.model_dump()
        plan_summary = _build_plan_summary(job)
        if plan_summary:
            job_dict["plan_summary"] = plan_summary

        initial_message = {
            "type": "initial_state",
            "job": job_dict,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await websocket.send_json(initial_message)

        # Keep connection alive and listen for client messages
        while True:
            try:
                # Wait for client message (for heartbeat/ping)
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                if message == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
                    )

            except asyncio.TimeoutError:
                # Send periodic heartbeat
                await websocket.send_json(
                    {"type": "heartbeat", "timestamp": datetime.utcnow().isoformat()}
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job {job_id}")

    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")

    finally:
        job_subscribers[job_id].discard(websocket)


@router.get("/{job_id}/events")
async def list_job_events(
    job_id: str,
    request: Request,
    since: int = Query(0, ge=0, description="Return events after this event_id"),
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    """List append-only job events (replay/debug)."""
    if not hasattr(request.app.state, "job_store"):
        raise HTTPException(status_code=503, detail="Job store not available")

    job_store = request.app.state.job_store
    record = await job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")

    events = await job_store.list_events(job_id, after_event_id=since, limit=limit)
    return {
        "job_id": job_id,
        "events": [
            {
                "event_id": evt.event_id,
                "job_id": evt.job_id,
                "type": evt.event_type,
                "ts": evt.created_at,
                "payload": evt.payload or {},
            }
            for evt in events
        ],
    }


@router.get("/{job_id}/stream")
async def stream_job_progress(
    job_id: str,
    request: Request = None,
    since: int = Query(0, ge=0, description="Resume event stream after this event_id"),
    since_event_id: int | None = Query(
        None, ge=0, description="Alias for since (resume after event_id)"
    ),
    include_initial_state: bool = Query(
        True, description="Emit an initial_state snapshot before streaming events"
    ),
):
    """Replayable Server-Sent Events endpoint backed by the append-only event log.

    This stream is resumable via `since` / `since_event_id` and does not rely on
    in-memory queues as the source of truth.
    """

    # Unit tests call this endpoint handler directly without a Request object.
    # In that case, fall back to the legacy in-memory snapshot semantics.
    if request is None:
        job = _get_router_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job = _hydrate_plan_metadata(job)

        async def _legacy_generator():
            job_dict = job.model_dump()
            plan_summary = _build_plan_summary(job)
            if plan_summary:
                job_dict["plan_summary"] = plan_summary
            yield {"event": "initial_state", "data": json.dumps(job_dict, default=str)}

        return EventSourceResponse(_legacy_generator())

    if not hasattr(request.app.state, "job_store"):
        raise HTTPException(status_code=503, detail="Job store not available")

    job_store = request.app.state.job_store

    record = await job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")

    def _unwrap_param(value, default):
        return getattr(value, "default", value) if value is not None else default

    since_value = _unwrap_param(since, 0)
    since_event_id_value = _unwrap_param(since_event_id, None)
    include_initial_state_value = bool(_unwrap_param(include_initial_state, True))
    last_event_id_header: int | None = None
    header_value = None
    try:
        header_value = request.headers.get("Last-Event-ID")
    except Exception:
        header_value = None
    if isinstance(header_value, str | int):
        try:
            last_event_id_header = int(header_value)
        except (TypeError, ValueError):
            last_event_id_header = None

    def _serialize_event(evt: JobEvent) -> dict[str, Any]:
        from brain_researcher.core.contracts.ids import IdsV1

        ids = IdsV1(
            analysis_id=evt.job_id,
            job_id=evt.job_id,
            run_id=record.run_id,
            user_id=record.user_id,
            session_id=record.session_id,
        )
        return {
            "schema_version": "stream-event-v1",
            "ids": ids.model_dump(exclude_none=True),
            "source_event_id": str(evt.event_id),
            "event_id": evt.event_id,
            "job_id": evt.job_id,
            "type": evt.event_type,
            "ts": evt.created_at,
            "payload": evt.payload or {},
        }

    async def event_generator():
        resume_candidates = [
            int(since_value or 0),
            int(since_event_id_value or 0),
            int(last_event_id_header or 0),
        ]
        resume_from = max(resume_candidates)
        last_event_id = int(resume_from if resume_from is not None else 0)
        last_ping = time_module.time()

        if include_initial_state_value:
            try:
                latest = await job_store.get(job_id)
                if latest is not None:
                    job = JobAdapter.from_record(latest)
                    job = _hydrate_plan_metadata(job)
                    job_dict = job.model_dump()
                    plan_summary = _build_plan_summary(job)
                    if plan_summary:
                        job_dict["plan_summary"] = plan_summary
                    yield {
                        "event": "initial_state",
                        "data": json.dumps(job_dict, default=str),
                    }
            except Exception:
                # best-effort; stream should still work without snapshot
                pass

        async def emit_progress_update(
            *, source_event_id: int | None = None, as_terminal: bool = False
        ) -> AsyncGenerator[dict[str, Any], None]:
            """Emit a UI-compatible progress_update (and optional job_complete)."""
            from brain_researcher.core.contracts.ids import IdsV1

            ids = IdsV1(
                analysis_id=job_id,
                job_id=job_id,
                run_id=record.run_id,
                user_id=record.user_id,
                session_id=record.session_id,
            )

            payload: dict[str, Any] | None = None
            try:
                job = _get_router_job(job_id)
                if job is not None:
                    payload = _build_job_progress_payload(
                        job_id, _hydrate_plan_metadata(job)
                    )
                else:
                    latest = await job_store.get(job_id)
                    if latest is not None:
                        job = JobAdapter.from_record(latest)
                        payload = _build_job_progress_payload(
                            job_id, _hydrate_plan_metadata(job)
                        )
            except Exception:
                payload = None

            if not payload:
                return

            if source_event_id is not None:
                payload.setdefault("event_id", str(source_event_id))
                payload.setdefault("source_event_id", str(source_event_id))
            payload.setdefault("ids", ids.model_dump(exclude_none=True))

            sse_id = str(source_event_id) if source_event_id is not None else None
            yield {
                **({"id": sse_id} if sse_id else {}),
                "event": "progress_update",
                "data": json.dumps(payload, default=str),
            }

            if as_terminal:
                yield {
                    **({"id": sse_id} if sse_id else {}),
                    "event": "job_complete",
                    "data": json.dumps(payload, default=str),
                }

        terminal_states = {"succeeded", "failed", "cancelled", "timeout", "skipped"}
        poll_interval = 0.5
        keepalive_seconds = 30.0

        async for evt in emit_progress_update(source_event_id=last_event_id):
            yield evt

        while True:
            events = await job_store.list_events(
                job_id, after_event_id=last_event_id, limit=200
            )
            if events:
                saw_terminal = False
                for evt in events:
                    last_event_id = max(last_event_id, int(evt.event_id))
                    yield {
                        "id": str(evt.event_id),
                        "event": evt.event_type,
                        "data": json.dumps(_serialize_event(evt), default=str),
                    }
                    if evt.event_type in {"job_finalized", "analysis.completed"}:
                        saw_terminal = True
                        break

                if saw_terminal:
                    async for evt in emit_progress_update(
                        source_event_id=last_event_id, as_terminal=True
                    ):
                        yield evt
                    return
                async for evt in emit_progress_update(source_event_id=last_event_id):
                    yield evt
            else:
                latest = await job_store.get(job_id)
                if latest is None:
                    return
                state_value = (
                    latest.state.value
                    if hasattr(latest.state, "value")
                    else str(latest.state)
                )
                if state_value in terminal_states:
                    # Ensure clients see a terminal marker even if no explicit
                    # job_finalized / analysis.completed event was emitted.
                    yield {
                        "event": "job_terminal",
                        "data": json.dumps(
                            {
                                "job_id": job_id,
                                "state": state_value,
                                "last_event_id": last_event_id,
                            },
                            default=str,
                        ),
                    }
                    async for evt in emit_progress_update(
                        source_event_id=last_event_id, as_terminal=True
                    ):
                        yield evt
                    return

            now = time_module.time()
            if now - last_ping >= keepalive_seconds:
                last_ping = now
                yield {
                    "event": "ping",
                    "data": json.dumps(
                        {
                            "timestamp": datetime.utcnow().isoformat(),
                            "last_event_id": last_event_id,
                        },
                        default=str,
                    ),
                }

            await asyncio.sleep(poll_interval)

    return EventSourceResponse(event_generator())


@router.get("/{job_id}/analysis-stream")
async def stream_analysis_stream_events(
    job_id: str,
    request: Request,
    since: int = Query(
        0, ge=0, description="Resume stream after this seq (Last-Event-ID compatible)"
    ),
    since_event_id: int | None = Query(
        None, ge=0, description="Alias for since (resume after seq)"
    ),
    source: str | None = Query(
        None, description="Force source: job_store|trace (default: auto)"
    ),
    run_dir: str | None = Query(
        None, description="Run directory for trace replay when job_store is unavailable"
    ),
):
    """Contract-first SSE endpoint emitting AnalysisStreamEventV1 JSON.

    This endpoint is the typed counterpart to `/stream`. It emits only
    `AnalysisStreamEventV1` payloads and is safe to validate end-to-end.

    Notes:
    - Defaults to using the JobStore append-only event log when available.
    - Can replay legacy `trace.jsonl` when `source=trace` (or when JobStore is
      not configured).
    """

    def _unwrap_param(value, default):
        return getattr(value, "default", value) if value is not None else default

    since_value = int(_unwrap_param(since, 0) or 0)
    since_event_id_value = _unwrap_param(since_event_id, None)
    header_value = None
    try:
        header_value = request.headers.get("Last-Event-ID")
    except Exception:
        header_value = None
    last_event_id_header: int | None = None
    if isinstance(header_value, str | int):
        try:
            last_event_id_header = int(header_value)
        except (TypeError, ValueError):
            last_event_id_header = None

    resume_candidates = [
        int(since_value or 0),
        int(since_event_id_value or 0),
        int(last_event_id_header or 0),
    ]
    resume_from = max(resume_candidates)

    job_store = getattr(request.app.state, "job_store", None)

    if source == "trace" or job_store is None:
        # Trace replay mode (best-effort, primarily for historical runs).
        from brain_researcher.core.contracts.analysis_stream import (
            AnalysisStreamEventTypeV1,
            UnknownEventPayloadV1,
            UnknownEventV1,
        )
        from brain_researcher.core.contracts.ids import IdsV1
        from brain_researcher.services.orchestrator.legacy_event_adapter import (
            adapt_trace_event,
        )

        run_path = Path(run_dir) if run_dir else None
        trace_path = run_path / "trace.jsonl" if run_path else None
        if trace_path is None or not trace_path.exists():
            raise HTTPException(status_code=404, detail="trace.jsonl not found")

        async def trace_generator():
            with trace_path.open("r", encoding="utf-8") as fh:
                for line_idx, line in enumerate(fh, start=1):
                    if line_idx <= resume_from:
                        continue
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                        typed = adapt_trace_event(payload, seq=line_idx)
                    except Exception:
                        typed = UnknownEventV1(
                            ids=IdsV1(job_id=job_id, analysis_id=job_id),
                            seq=line_idx,
                            timestamp=datetime.utcnow().isoformat() + "Z",
                            payload=UnknownEventPayloadV1(
                                raw_event_type="trace.parse_error",
                                raw_payload={"line": raw},
                            ),
                        )
                    yield {
                        "id": str(typed.seq),
                        "event": typed.event_type,
                        "data": json.dumps(
                            typed.model_dump(exclude_none=True), default=str
                        ),
                    }
                    if (
                        typed.event_type
                        == AnalysisStreamEventTypeV1.analysis_completed.value
                    ):
                        return

        return EventSourceResponse(trace_generator())

    # JobStore-backed streaming mode.
    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisStreamEventTypeV1,
    )
    from brain_researcher.services.orchestrator.legacy_event_adapter import (
        adapt_job_event,
    )

    record = await job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")

    terminal_states = {"succeeded", "failed", "cancelled", "timeout", "skipped"}
    poll_interval = 0.5

    async def event_generator():
        last_seq = int(resume_from or 0)
        while True:
            events = await job_store.list_events(
                job_id, after_event_id=last_seq, limit=200
            )
            if events:
                for evt in events:
                    typed = adapt_job_event(evt, record=record, run_id=record.run_id)
                    last_seq = max(last_seq, int(evt.event_id))
                    yield {
                        "id": str(typed.seq),
                        "event": typed.event_type,
                        "data": json.dumps(
                            typed.model_dump(exclude_none=True), default=str
                        ),
                    }
                    if (
                        typed.event_type
                        == AnalysisStreamEventTypeV1.analysis_completed.value
                    ):
                        return
            else:
                latest = await job_store.get(job_id)
                if latest is None:
                    return
                state_value = (
                    latest.state.value
                    if hasattr(latest.state, "value")
                    else str(latest.state)
                )
                if state_value in terminal_states:
                    return

            await asyncio.sleep(poll_interval)

    return EventSourceResponse(event_generator())


@router.get("/{job_id}/logs/stream")
async def stream_job_logs(
    job_id: str,
    request: Request,
    run_dir: str | None = Query(
        None, description="Step run directory for per-step log streaming"
    ),
    stream: str | None = Query(
        None, pattern="^(stdout|stderr)$", description="Filter by stream type"
    ),
    start_offset: int = Query(
        0, ge=0, description="Start from byte offset (for resume)"
    ),
    follow: bool = Query(
        True, description="Enable tail-like behavior (stream new logs)"
    ),
):
    """Stream job or step logs via Server-Sent Events."""
    job = _get_router_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if not hasattr(request.app.state, "job_store"):
        raise HTTPException(status_code=503, detail="Job store not available")

    job_store = request.app.state.job_store

    job_record: JobRecord | None = await job_store.get(job_id)
    if job_record is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found in store")

    try:
        stream_names = _normalize_streams(stream)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_dir_path: Path | None = None
    if run_dir:
        try:
            run_dir_path = _resolve_step_log_path(job_record, run_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    poll_interval = 1.0
    keepalive_interval = 30.0
    follow_mode = bool(follow)

    store_offsets = {name: max(0, start_offset) for name in stream_names}
    file_offsets = {name: max(0, start_offset) for name in stream_names}

    async def event_generator():
        nonlocal job_record
        last_activity = time_module.time()

        logger.debug(
            "Starting log stream for job %s (start_offset=%s, stream=%s, follow=%s, run_dir=%s)",
            job_id,
            start_offset,
            stream,
            follow_mode,
            run_dir_path,
        )

        try:
            if run_dir_path is not None:
                initial_chunks = _collect_file_chunks(
                    job_id, run_dir_path, stream_names, file_offsets
                )
            else:
                initial_chunks = await _collect_store_chunks(
                    job_store, job_id, stream, store_offsets
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Error fetching initial logs for job %s", job_id)
            yield {
                "event": "error",
                "data": json.dumps({"error": f"Failed to fetch logs: {str(exc)}"}),
            }
            return

        for chunk in initial_chunks:
            yield _serialize_log_chunk(chunk)
        if initial_chunks:
            last_activity = time_module.time()

        if not follow_mode:
            job_record = await job_store.get(job_id)
            if job_record and _job_is_terminal(job_record.state):
                yield _serialize_log_complete(
                    job_id, job_record.state, stream_names, store_offsets, file_offsets
                )
            return

        while True:
            if await request.is_disconnected():
                logger.debug("Client disconnected from log stream for job %s", job_id)
                break

            try:
                if run_dir_path is not None:
                    new_chunks = _collect_file_chunks(
                        job_id, run_dir_path, stream_names, file_offsets
                    )
                else:
                    new_chunks = await _collect_store_chunks(
                        job_store, job_id, stream, store_offsets
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Error tailing logs for job %s", job_id)
                yield {
                    "event": "error",
                    "data": json.dumps({"error": f"Failed to fetch logs: {str(exc)}"}),
                }
                break

            if new_chunks:
                for chunk in new_chunks:
                    yield _serialize_log_chunk(chunk)
                last_activity = time_module.time()

            job_record = await job_store.get(job_id)
            if job_record is None:
                logger.warning("Job %s disappeared during log streaming", job_id)
                yield {
                    "event": "log_complete",
                    "data": json.dumps(
                        {
                            "job_id": job_id,
                            "status": "unknown",
                            "final_offset": _max_offset(
                                stream_names, store_offsets, file_offsets
                            ),
                            "reason": "job_removed",
                        }
                    ),
                }
                break

            if _job_is_terminal(job_record.state) and not new_chunks:
                logger.debug(
                    "Job %s reached terminal state %s – closing stream",
                    job_id,
                    job_record.state,
                )
                yield _serialize_log_complete(
                    job_id, job_record.state, stream_names, store_offsets, file_offsets
                )
                break

            now = time_module.time()
            if now - last_activity >= keepalive_interval:
                yield {
                    "event": "ping",
                    "data": json.dumps(
                        {
                            "timestamp": int(now),
                            "current_offset": _max_offset(
                                stream_names, store_offsets, file_offsets
                            ),
                        }
                    ),
                }
                last_activity = now

            await asyncio.sleep(poll_interval)

    return EventSourceResponse(event_generator())


_DEFAULT_STREAMS = ("stdout", "stderr")
_TERMINAL_JOB_STATES = {
    "completed",
    "succeeded",
    "failed",
    "cancelled",
    "timeout",
    "skipped",
}
_LOG_FILE_CANDIDATES = {
    "stdout": ("stdout.txt", "stdout.log"),
    "stderr": ("stderr.txt", "stderr.log"),
}


def _normalize_streams(stream: str | None) -> list[str]:
    if stream is None:
        return list(_DEFAULT_STREAMS)
    value = stream.lower()
    if value not in _DEFAULT_STREAMS:
        raise ValueError(
            f"Unsupported stream '{stream}'. Expected 'stdout' or 'stderr'."
        )
    return [value]


def _resolve_step_log_path(job: JobRecord, run_dir: str) -> Path:
    if not run_dir:
        raise ValueError("run_dir parameter must be a non-empty string")

    candidate = Path(run_dir)
    job_root: Path | None = None
    if job.run_dir:
        config = get_recorder_config()
        job_root = _resolve_recorded_job_path(
            job.run_dir,
            run_store_root=config.root.resolve(),
        )

    if not candidate.is_absolute():
        if job_root is None:
            raise ValueError("Job run_dir is not available; run_dir must be absolute")
        candidate = (job_root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if job_root and not _path_is_within(candidate, job_root):
        raise PermissionError(
            f"Step run_dir {candidate} is outside job run_dir {job_root}"
        )

    return candidate


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


async def _collect_store_chunks(
    job_store: Any,
    job_id: str,
    stream_filter: str | None,
    offsets: dict[str, int],
) -> list[LogChunk]:
    start_from = min(offsets.values()) if offsets else 0
    raw_chunks = await job_store.iter_logs(
        job_id=job_id, start_offset=start_from, stream=stream_filter
    )

    result: list[LogChunk] = []
    for raw in raw_chunks:
        current_offset = offsets.setdefault(raw.stream, start_from)
        effective_offset = max(current_offset, raw.offset)
        slice_start = max(effective_offset - raw.offset, 0)
        data = raw.data[slice_start:]
        if not data:
            continue
        adjusted_offset = raw.offset + slice_start
        offsets[raw.stream] = adjusted_offset + len(data)
        result.append(
            LogChunk(
                job_id=raw.job_id,
                stream=raw.stream,
                offset=adjusted_offset,
                data=data,
                created_at=raw.created_at,
            )
        )
    return result


def _collect_file_chunks(
    job_id: str,
    run_dir: Path,
    streams: list[str],
    offsets: dict[str, int],
) -> list[LogChunk]:
    if not run_dir.exists():
        return []

    now = int(time_module.time())
    chunks: list[LogChunk] = []

    for stream_name in streams:
        candidates = _LOG_FILE_CANDIDATES.get(stream_name, ())
        path: Path | None = None
        for candidate_name in candidates:
            candidate_path = run_dir / candidate_name
            if candidate_path.exists():
                path = candidate_path
                break
        if path is None:
            continue

        offset = max(0, offsets.get(stream_name, 0))
        try:
            size = path.stat().st_size
        except OSError:
            logger.warning("Unable to stat log file %s for job %s", path, job_id)
            continue

        if size <= offset:
            continue

        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                data = fh.read()
        except OSError:
            logger.warning("Unable to read log file %s for job %s", path, job_id)
            continue

        if not data:
            continue

        offsets[stream_name] = offset + len(data)
        chunks.append(
            LogChunk(
                job_id=job_id,
                stream=stream_name,
                offset=offset,
                data=data,
                created_at=now,
            )
        )

    return chunks


def _serialize_log_chunk(chunk: LogChunk) -> dict[str, str]:
    data_b64 = base64.b64encode(chunk.data).decode("utf-8")
    return {
        "event": "log_chunk",
        "data": json.dumps(
            {
                "stream": chunk.stream,
                "offset": chunk.offset,
                "data": data_b64,
                "timestamp": chunk.created_at,
                "size": len(chunk.data),
            }
        ),
    }


def _serialize_log_complete(
    job_id: str,
    status: str | None,
    streams: list[str],
    store_offsets: dict[str, int],
    file_offsets: dict[str, int],
) -> dict[str, str]:
    return {
        "event": "log_complete",
        "data": json.dumps(
            {
                "job_id": job_id,
                "status": status,
                "final_offset": _max_offset(streams, store_offsets, file_offsets),
            }
        ),
    }


def _max_offset(
    streams: list[str],
    store_offsets: dict[str, int],
    file_offsets: dict[str, int],
) -> int:
    values = []
    for name in streams:
        if name in store_offsets:
            values.append(store_offsets[name])
        if name in file_offsets:
            values.append(file_offsets[name])
    return max(values) if values else 0


def _job_is_terminal(state: str | None) -> bool:
    if state is None:
        return False
    return state.lower() in _TERMINAL_JOB_STATES


@router.get("/queue/status")
async def get_queue_status() -> dict[str, Any]:
    """Get job queue status"""
    return JobQueueManager.get_queue_status()


@router.get("/statistics")
async def get_job_statistics_endpoint() -> JobStatistics:
    """Get comprehensive job statistics"""
    return calculate_job_statistics()


@router.get("")
async def list_jobs(
    request: Request,
    user_id: str | None = Query(None),
    status: JobStatus | None = Query(None),
    priority: JobPriority | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at"),
    sort_desc: bool = Query(True),
) -> dict[str, Any]:
    """List jobs (contract-first)."""

    job_store = getattr(request.app.state, "job_store", None)

    state_filter: str | None = None
    if status is not None:
        state_filter = str(getattr(status, "value", status))
        if state_filter == JobStatus.COMPLETED.value:
            state_filter = "succeeded"

    if job_store is not None:
        try:
            if state_filter:
                jobs = await job_store.list_by_state(
                    state_filter, user_id=user_id, limit=limit, offset=offset
                )
                total = await job_store.count_by_state(state_filter, user_id=user_id)
            else:
                jobs = await job_store.list_all(
                    user_id=user_id, limit=limit, offset=offset
                )
                total = await job_store.count_all(user_id=user_id)

            return {
                "jobs": jobs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total,
            }
        except Exception as exc:
            logger.warning(
                "JobStore list failed (%s); falling back to legacy store", exc
            )

    _sync_router_jobs_from_core()

    filtered_jobs = list(jobs_db.values())

    if user_id:
        filtered_jobs = [j for j in filtered_jobs if j.user_id == user_id]

    if status:
        filtered_jobs = [j for j in filtered_jobs if j.status == status]

    if priority:
        filtered_jobs = [j for j in filtered_jobs if j.priority == priority]

    reverse = sort_desc
    if sort_by == "created_at":
        filtered_jobs.sort(key=lambda j: j.created_at, reverse=reverse)
    elif sort_by == "priority":
        priority_order = {
            JobPriority.CRITICAL: 0,
            JobPriority.HIGH: 1,
            JobPriority.NORMAL: 2,
            JobPriority.LOW: 3,
        }
        filtered_jobs.sort(key=lambda j: priority_order[j.priority], reverse=reverse)
    elif sort_by == "progress":
        filtered_jobs.sort(key=lambda j: j.progress, reverse=reverse)
    elif sort_by == "status":
        filtered_jobs.sort(key=lambda j: j.status, reverse=reverse)

    total = len(filtered_jobs)
    paginated_jobs = filtered_jobs[offset : offset + limit]
    records = [
        JobAdapter.to_record(_hydrate_plan_metadata(job)) for job in paginated_jobs
    ]

    return {
        "jobs": records,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


@router.get("/{job_id}/graph")
async def get_job_graph(job_id: str, request: Request) -> dict[str, Any]:
    """Return a pipeline graph snapshot for the given job."""
    job = await _get_job_with_store(job_id, request)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_job_graph_snapshot(job, job_id=job_id)


# ---------------------------------------------------------------------------
# Evidence & Provenance Endpoints (for Web UI Evidence Rail)
# ---------------------------------------------------------------------------


@router.get("/{job_id}/provenance-graph")
async def get_job_provenance_graph(job_id: str) -> dict[str, Any]:
    """Return a simple provenance graph for the given job.

    The shape matches the Web UI's expected ProvenanceGraph:
    { nodes: [{id, type, label, metadata}], edges: [{source, target, label}] }
    """
    job = _get_router_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Job node
    nodes.append(
        {
            "id": job.id,
            "type": "job",
            "label": job.name or f"Job {job.id}",
            "metadata": {
                "status": job.status,
                "created_at": job.created_at.isoformat(),
                "pipeline": job.metadata.get("pipeline") if job.metadata else None,
            },
        }
    )

    # Dataset (if present in metadata)
    dataset_id = job.metadata.get("dataset_id") if job.metadata else None
    if dataset_id:
        nodes.append(
            {
                "id": f"dataset:{dataset_id}",
                "type": "dataset",
                "label": str(dataset_id),
                "metadata": {"source": job.metadata.get("dataset_source")},
            }
        )
        edges.append(
            {"source": f"dataset:{dataset_id}", "target": job.id, "label": "used_by"}
        )

    # Steps as tool nodes
    for step in job.steps:
        step_node_id = f"step:{step.id}"
        nodes.append(
            {
                "id": step_node_id,
                "type": "tool",
                "label": step.tool,
                "metadata": {
                    "name": step.name,
                    "status": step.status,
                    "args": step.args,
                    "start_time": (
                        step.start_time.isoformat() if step.start_time else None
                    ),
                    "end_time": step.end_time.isoformat() if step.end_time else None,
                },
            }
        )
        edges.append({"source": job.id, "target": step_node_id, "label": "has_step"})

    # Artifacts as outputs
    for artifact in job.artifacts:
        art_node_id = f"artifact:{artifact.id}"
        nodes.append(
            {
                "id": art_node_id,
                "type": "output",
                "label": artifact.name,
                "metadata": artifact.model_dump(),
            }
        )
        edges.append({"source": job.id, "target": art_node_id, "label": "produces"})

    return {"nodes": nodes, "edges": edges}


@router.get("/{job_id}/runcard")
async def get_job_runcard(job_id: str, request: Request) -> dict[str, Any]:
    """Return a RunCard-like structure for Evidence Rail.

    This is a minimal implementation derived from the in-memory Job.
    """
    # Prefer the canonical observation bundle when available so RunCard,
    # provenance, artifacts, and file refs stay consistent.
    try:
        observation = await get_job_observation(job_id, request)
        run_card = (
            observation.get("run_card") if isinstance(observation, dict) else None
        )
        if isinstance(run_card, dict):
            return run_card
    except HTTPException:
        # Fall back to legacy assembly below.
        pass
    except Exception:
        pass

    job = _get_router_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Derive dataset & tools from metadata/steps when available
    dataset = None
    if job.metadata and job.metadata.get("dataset_id"):
        dataset = {
            "id": str(job.metadata.get("dataset_id")),
            "name": job.metadata.get("dataset_name")
            or str(job.metadata.get("dataset_id")),
            "source": job.metadata.get("dataset_source") or "unknown",
            "n_subjects": job.metadata.get("n_subjects"),
        }

    tools = []
    seen_tools = set()
    for step in job.steps:
        if step.tool and step.tool not in seen_tools:
            tools.append(
                {
                    "name": step.tool,
                    "version": (
                        step.metrics.model_dump().get("tool_version")
                        if step.metrics
                        else "latest"
                    ),
                }
            )
            seen_tools.add(step.tool)

    outputs = [
        {"name": a.name, "type": a.type, "path": a.path, "size": a.size}
        for a in job.artifacts
    ]

    # Very simple citations placeholder
    citations = job.metadata.get("citations") if job.metadata else []

    # Build provenance by reusing the graph endpoint
    provenance = await get_job_provenance(job_id)

    run_card = {
        "id": job.id,
        "version": "1.0",
        "created_at": job.created_at.isoformat(),
        "analysis": {
            "name": job.name or f"Job {job.id}",
            "description": job.metadata.get("description") if job.metadata else None,
            "pipeline": job.metadata.get("pipeline") if job.metadata else None,
        },
        "datasets": [dataset] if dataset else [],
        "tools": tools,
        "parameters": job.metadata.get("parameters") if job.metadata else {},
        "outputs": outputs,
        "provenance": provenance,
        "citations": citations or [],
    }

    from brain_researcher.core.contracts.ids import IdsV1
    from brain_researcher.core.contracts.run_card import RunCardV1

    card = RunCardV1(
        ids=IdsV1(
            analysis_id=job.id,
            run_id=job.id,
            job_id=job.id,
        ),
        id=run_card.get("id"),
        version=run_card.get("version"),
        created_at=run_card.get("created_at"),
        analysis=run_card.get("analysis"),
        datasets=run_card.get("datasets") or [],
        tools=run_card.get("tools") or [],
        parameters=run_card.get("parameters") or {},
        outputs=run_card.get("outputs"),
        provenance=run_card.get("provenance"),
        citations=run_card.get("citations") or [],
    )

    # Best-effort: compute reproducibility score from evidence present in this payload.
    try:
        from brain_researcher.core.reproducibility import compute_reproducibility_v1

        artifact_dicts: list[dict[str, Any]] = []
        for art in job.artifacts or []:
            if hasattr(art, "model_dump"):
                raw = art.model_dump()
                if isinstance(raw, dict):
                    artifact_dicts.append(raw)
            elif isinstance(art, dict):
                artifact_dicts.append(art)

        repro = compute_reproducibility_v1(
            run_dir=None,
            datasets=card.datasets,
            artifacts=artifact_dicts,
            parameters=card.parameters,
            versions=card.versions,
            policy=card.policy,
        )
        card.reproducibility = repro
        card.reproducibility_score = repro.get("score")
    except Exception:
        pass
    dumped = card.model_dump(mode="json", exclude_none=True)
    dumped.setdefault("run_id", job.id)
    return dumped


@router.get("/{job_id}/observation", response_model=dict[str, Any], tags=["provenance"])
async def get_job_observation(job_id: str, request: Request) -> dict[str, Any]:
    """Return the canonical observation document for a job.

    Serves `observation.json` from the run directory when present. If missing,
    synthesizes it best-effort from the JobStore record and `provenance.json`
    and persists it into the run directory.
    """
    job_store = request.app.state.job_store
    job_record = await job_store.get(job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job_record.run_dir:
        raise HTTPException(
            status_code=404, detail="Run directory not available for this job"
        )

    config = get_recorder_config()
    run_store_root = config.root.resolve()
    run_dir = _resolve_recorded_job_path(
        job_record.run_dir,
        run_store_root=run_store_root,
    )

    obs_path = _resolve_recorded_job_path(
        Path(job_record.run_dir) / "observation.json",
        run_store_root=run_store_root,
    )

    if obs_path.exists():
        try:
            with obs_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise HTTPException(status_code=500, detail="Invalid observation file")
            needs_backfill = not isinstance(data.get("diagnostics_summary"), dict)
            if not needs_backfill:
                artifacts = data.get("artifacts")
                if isinstance(artifacts, list):
                    for art in artifacts:
                        if not isinstance(art, dict):
                            continue
                        if not isinstance(art.get("checksum_status"), str):
                            needs_backfill = True
                            break
            if not needs_backfill and _needs_observation_artifact_backfill(
                data, run_dir
            ):
                needs_backfill = True

            if not needs_backfill:
                _ensure_observation_artifact_views(data, run_dir=run_dir)
                return data
        except HTTPException:
            raise
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=500, detail="Observation file contains invalid JSON"
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Error reading observation file: {exc}"
            )

    try:
        from brain_researcher.services.orchestrator.observation import (
            load_or_build_observation,
            persist_observation,
        )

        # NOTE: In some deployment environments, threadpool helpers can stall.
        # This code path should remain reliable even if it runs synchronously.
        resolved_job_record = job_record.model_copy(
            update={
                "run_dir": str(run_dir),
                "provenance_path": (
                    str(
                        _resolve_recorded_job_path(
                            job_record.provenance_path,
                            run_store_root=run_store_root,
                        )
                    )
                    if job_record.provenance_path
                    else None
                ),
            }
        )
        spec = load_or_build_observation(resolved_job_record)
        if spec is None:
            raise HTTPException(
                status_code=404, detail="Observation not available for this job"
            )
        persist_observation(resolved_job_record, spec)
        try:
            if job_record.payload_json:
                await job_store.update_state(
                    job_id,
                    job_record.state,
                    payload_json=job_record.payload_json,
                )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug(
                "Failed to persist updated artifact checksums for job %s: %s",
                job_id,
                exc,
            )
        payload = spec.model_dump()
        _ensure_observation_artifact_views(payload, run_dir=run_dir)
        return payload
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Failed to synthesize observation for job %s: %s", job_id, exc)
        raise HTTPException(status_code=500, detail="Failed to build observation")


def _infer_ui_artifact_type(path: str) -> str:
    lower = (path or "").lower()
    if lower.endswith(
        (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".nii", ".nii.gz")
    ):
        return "image"
    if lower.endswith((".csv", ".tsv", ".parquet", ".xlsx", ".xls")):
        return "table"
    if lower.endswith((".json", ".jsonl")):
        return "json"
    if lower.endswith((".html", ".pdf", ".md", ".txt", ".log")):
        return "report"
    return "file"


def _normalize_observation_artifacts(
    data: dict[str, Any],
    *,
    run_dir: Path | None = None,
) -> list[dict[str, Any]]:
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        data["artifacts"] = []
        return []
    normalized = [item for item in artifacts if isinstance(item, dict)]
    normalized = _merge_artifact_payloads(normalized, run_dir=run_dir)
    data["artifacts"] = normalized
    return normalized


def _artifact_output_views(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.get("name"),
            "type": item.get("type"),
            "path": item.get("path"),
            "size": item.get("size"),
        }
        for item in artifacts
    ]


def _ensure_observation_artifact_views(
    data: dict[str, Any],
    *,
    run_dir: Path | None = None,
) -> None:
    artifacts = _normalize_observation_artifacts(data, run_dir=run_dir)
    if not artifacts:
        return

    run_card = data.get("run_card")
    if not isinstance(run_card, dict):
        return

    run_card["outputs"] = _artifact_output_views(artifacts)
    run_card["artifacts"] = artifacts


def _needs_observation_artifact_backfill(data: dict[str, Any], run_dir: Path) -> bool:
    artifacts = _normalize_observation_artifacts(data, run_dir=run_dir)
    run_card = data.get("run_card")
    run_card_outputs = run_card.get("outputs") if isinstance(run_card, dict) else None
    run_card_artifacts = (
        run_card.get("artifacts") if isinstance(run_card, dict) else None
    )
    run_files = _collect_artifact_files(run_dir)

    has_artifacts = any(isinstance(item, dict) for item in artifacts)
    has_run_card_outputs = isinstance(run_card_outputs, list) and any(
        isinstance(item, dict) for item in run_card_outputs
    )
    has_run_card_artifacts = isinstance(run_card_artifacts, list) and any(
        isinstance(item, dict) for item in run_card_artifacts
    )
    if _artifact_dedupe_keys(run_files, run_dir=run_dir) - _artifact_dedupe_keys(
        artifacts, run_dir=run_dir
    ):
        return True
    if has_artifacts and (has_run_card_outputs or has_run_card_artifacts):
        return False

    return len(run_files) > 0


def _collect_artifact_files(run_dir: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for file_path in run_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name in _OBS_INTERNAL_ARTIFACT_FILENAMES:
            continue
        rel_path = file_path.relative_to(run_dir).as_posix()
        if not rel_path:
            continue
        if any(part.startswith(".") for part in Path(rel_path).parts):
            continue
        stat = file_path.stat()
        files.append(
            {
                "name": file_path.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "path": rel_path,
            }
        )
    files.sort(key=lambda item: str(item.get("path") or ""))
    return files


def _normalized_artifact_path(
    value: Any,
    *,
    run_dir: Path | None = None,
) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    marker = "/artifacts/files/"
    from_artifact_url = False
    if marker in text:
        text = text.split(marker, 1)[1]
        from_artifact_url = True
    else:
        parsed = urlparse(text)
        if parsed.scheme == "file":
            text = parsed.path
        elif parsed.scheme in {"http", "https"}:
            return None
    text = unquote(text).strip()
    if from_artifact_url:
        text = text.lstrip("/")
    if not text:
        return None
    if run_dir is not None:
        try:
            candidate = Path(text)
            if candidate.is_absolute():
                text = candidate.resolve().relative_to(run_dir.resolve()).as_posix()
        except Exception:
            pass
    return text.lower()


def _artifact_dedupe_key(
    artifact: dict[str, Any],
    *,
    run_dir: Path | None = None,
) -> str:
    for field in ("path", "uri", "file_path", "relative_path", "location"):
        path_value = _normalized_artifact_path(artifact.get(field), run_dir=run_dir)
        if path_value:
            return f"path:{path_value}"

    for nested_field in ("meta", "metadata"):
        nested = artifact.get(nested_field)
        if not isinstance(nested, dict):
            continue
        for field in ("path", "uri", "file_path", "relative_path", "location"):
            path_value = _normalized_artifact_path(nested.get(field), run_dir=run_dir)
            if path_value:
                return f"path:{path_value}"

    for field in ("url", "download_url"):
        value = artifact.get(field)
        if not (isinstance(value, str) and "/artifacts/files/" in value):
            continue
        path_value = _normalized_artifact_path(value, run_dir=run_dir)
        if path_value:
            return f"path:{path_value}"

    for field in ("url", "download_url", "name", "artifact_id", "id"):
        value = artifact.get(field)
        if isinstance(value, str) and value.strip():
            return f"{field}:{value.strip().lower()}"
    return ""


def _is_local_artifact_file_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith("/api/jobs/") and "/artifacts/files/" in text


def _merge_artifact_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    for field, value in source.items():
        if field in {"url", "download_url"} and _is_local_artifact_file_url(value):
            target[field] = value
            continue
        current = target.get(field)
        if current in (None, "", [], {}):
            target[field] = value
            continue
        if isinstance(current, dict) and isinstance(value, dict):
            for nested_field, nested_value in value.items():
                if current.get(nested_field) in (None, "", [], {}):
                    current[nested_field] = nested_value


def _merge_artifact_payloads(
    *artifact_lists: list[dict[str, Any]],
    run_dir: Path | None = None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    merged_by_key: dict[str, dict[str, Any]] = {}
    for artifacts in artifact_lists:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            key = _artifact_dedupe_key(artifact, run_dir=run_dir)
            if key and key in merged_by_key:
                _merge_artifact_fields(merged_by_key[key], artifact)
                continue
            artifact_payload = dict(artifact)
            if key:
                merged_by_key[key] = artifact_payload
            merged.append(artifact_payload)
    return merged


def _artifact_dedupe_keys(
    artifacts: list[dict[str, Any]],
    *,
    run_dir: Path | None = None,
) -> set[str]:
    keys: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        key = _artifact_dedupe_key(artifact, run_dir=run_dir)
        if key:
            keys.add(key)
    return keys


def _payload_output_dirs(payload: dict[str, Any]) -> list[str]:
    output_dirs: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text or text in seen:
            return
        seen.add(text)
        output_dirs.append(text)

    parameters = payload.get("parameters")
    if isinstance(parameters, dict):
        add(parameters.get("output_dir"))

    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            args = step.get("args")
            if isinstance(args, dict):
                add(args.get("output_dir"))

    return output_dirs


def _mirror_external_output_artifacts(
    *,
    job_id: str,
    payload: dict[str, Any],
    run_dir: Path,
    run_store_root: Path,
) -> None:
    """Mirror declared workflow output_dir files into the job run_dir.

    Some tools write scientific outputs to a workflow-level output_dir instead
    of the recorder run_dir. The UI artifact download endpoint is intentionally
    scoped to run_dir paths, so copy bounded output files into a stable
    workflow_outputs/ subtree before listing artifacts.
    """

    output_dirs = _payload_output_dirs(payload)
    if not output_dirs:
        return

    max_files = int(os.getenv("BR_JOB_ARTIFACT_OUTPUT_DIR_MAX_FILES", "128"))
    max_per_file = int(os.getenv("BR_JOB_ARTIFACT_OUTPUT_DIR_MAX_BYTES", "104857600"))
    max_total = int(
        os.getenv("BR_JOB_ARTIFACT_OUTPUT_DIR_MAX_TOTAL_BYTES", "1073741824")
    )
    if max_files <= 0 or max_per_file <= 0 or max_total <= 0:
        return

    allowed_roots = get_recorder_roots_for_read(run_store_root)
    run_dir_resolved = run_dir.resolve()
    copied_files = 0
    copied_bytes = 0

    for raw_output_dir in output_dirs:
        if copied_files >= max_files or copied_bytes >= max_total:
            break
        try:
            output_dir = Path(raw_output_dir).expanduser().resolve()
        except (OSError, RuntimeError):
            logger.debug(
                "Skipping invalid output_dir for job %s: %r", job_id, raw_output_dir
            )
            continue
        if not output_dir.exists() or not output_dir.is_dir():
            continue
        try:
            _validate_path_security_against_roots(output_dir, allowed_roots)
            output_dir.relative_to(run_dir_resolved)
            continue
        except HTTPException:
            logger.warning(
                "Skipping output_dir outside allowed roots for job %s: %s",
                job_id,
                output_dir,
            )
            continue
        except ValueError:
            pass

        safe_dir_name = output_dir.name or "output_dir"
        safe_dir_name = (
            "".join(
                char if char.isalnum() or char in "._-" else "_"
                for char in safe_dir_name
            ).strip("._")
            or "output_dir"
        )
        dest_root = run_dir_resolved / "workflow_outputs" / safe_dir_name

        for file_path in sorted(output_dir.rglob("*")):
            if copied_files >= max_files or copied_bytes >= max_total:
                break
            if not file_path.is_file():
                continue
            if file_path.is_symlink():
                continue
            try:
                resolved_source = file_path.resolve()
                resolved_source.relative_to(output_dir)
                _validate_path_security_against_roots(resolved_source, allowed_roots)
            except (OSError, RuntimeError, ValueError, HTTPException):
                continue
            try:
                rel_path = file_path.relative_to(output_dir)
            except ValueError:
                continue
            if any(
                part in {"", ".", ".."} or part.startswith(".")
                for part in rel_path.parts
            ):
                continue
            if file_path.name in _OBS_INTERNAL_ARTIFACT_FILENAMES:
                continue
            if file_path.suffix.lower() in {".tmp", ".part", ".lock"}:
                continue
            try:
                size = file_path.stat().st_size
            except OSError:
                continue
            if size > max_per_file or copied_bytes + size > max_total:
                continue
            dest = (dest_root / rel_path).resolve()
            try:
                _validate_path_security_against_roots(dest, (run_dir_resolved,))
            except HTTPException:
                continue
            if dest.exists():
                try:
                    if dest.stat().st_size == size:
                        continue
                except OSError:
                    pass
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(file_path, dest)
            except OSError as exc:
                logger.debug(
                    "Failed to mirror output artifact for job %s from %s to %s: %s",
                    job_id,
                    file_path,
                    dest,
                    exc,
                )
                continue
            copied_files += 1
            copied_bytes += size


@router.get(
    "/{job_id}/artifacts",
    response_model=dict[str, Any],
    tags=["provenance", "artifacts"],
)
async def get_job_artifacts(job_id: str, request: Request) -> dict[str, Any]:
    """Return UI-ready artifact metadata for a job."""
    observation_artifacts: list[dict[str, Any]] = []
    try:
        observation = await get_job_observation(job_id, request)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        observation = {}

    artifacts = observation.get("artifacts") if isinstance(observation, dict) else None
    if isinstance(artifacts, list):
        observation_artifacts = [item for item in artifacts if isinstance(item, dict)]

    job_store = request.app.state.job_store
    job_record = await job_store.get(job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job_record.run_dir:
        return {"artifacts": observation_artifacts}

    config = get_recorder_config()
    run_store_root = config.root.resolve()
    run_dir = _resolve_recorded_job_path(
        job_record.run_dir,
        run_store_root=run_store_root,
    )

    if not run_dir.exists() or not run_dir.is_dir():
        return {"artifacts": observation_artifacts}

    payload = {}
    if getattr(job_record, "payload_json", None):
        try:
            parsed_payload = json.loads(job_record.payload_json or "{}")
            if isinstance(parsed_payload, dict):
                payload = parsed_payload
        except json.JSONDecodeError:
            payload = {}
    _mirror_external_output_artifacts(
        job_id=job_id,
        payload=payload,
        run_dir=run_dir,
        run_store_root=run_store_root,
    )
    files = _collect_artifact_files(run_dir)
    artifacts_payload: list[dict[str, Any]] = []
    for idx, file_item in enumerate(files):
        rel_path = str(file_item.get("path") or "")
        encoded_rel = quote(rel_path, safe="/._-")
        artifacts_payload.append(
            {
                "id": f"artifact_{idx:04d}",
                "artifact_id": f"artifact_{idx:04d}",
                "name": file_item.get("name"),
                "type": _infer_ui_artifact_type(rel_path),
                "path": rel_path,
                "url": f"/api/jobs/{job_id}/artifacts/files/{encoded_rel}",
                "download_url": f"/api/jobs/{job_id}/artifacts/files/{encoded_rel}",
                "size": file_item.get("size"),
            }
        )

    return {
        "artifacts": _merge_artifact_payloads(
            observation_artifacts,
            artifacts_payload,
            run_dir=run_dir,
        )
    }


@router.post("/{job_id}/artifacts/{artifact_id}/annotate")
async def annotate_artifact(
    job_id: str, artifact_id: str, annotation: str = Query(...)
) -> dict[str, Any]:
    """Add a simple text annotation to an artifact's metadata."""
    job = _get_router_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    target = None
    for a in job.artifacts:
        if a.id == artifact_id:
            target = a
            break
    if not target:
        raise HTTPException(status_code=404, detail="Artifact not found")

    md = target.metadata or {}
    annotations = md.get("annotations", [])
    annotations.append({"text": annotation, "timestamp": datetime.utcnow().isoformat()})
    md["annotations"] = annotations
    target.metadata = md

    return {
        "status": "ok",
        "artifact_id": artifact_id,
        "annotations_count": len(annotations),
    }


# ============================================================================
# Provenance and Artifact File Endpoints
# ============================================================================


def _validate_path_security(target_path: Path, base_path: Path) -> None:
    """
    Validate that target_path is within base_path (path traversal guard).

    Args:
        target_path: Path to validate
        base_path: Allowed base directory

    Raises:
        HTTPException(403): If path traversal attempt detected
    """
    try:
        # Resolve both paths to absolute form
        resolved_target = target_path.resolve()
        resolved_base = base_path.resolve()

        # Check if target is within base
        if not str(resolved_target).startswith(str(resolved_base)):
            logger.warning(
                f"Path traversal attempt detected: {target_path} "
                f"not under {base_path}"
            )
            raise HTTPException(
                status_code=403, detail="Access denied: Path traversal attempt detected"
            )
    except (OSError, RuntimeError) as e:
        logger.error(f"Path validation error: {e}")
        raise HTTPException(status_code=400, detail="Invalid path")


def _validate_path_security_against_roots(
    target_path: Path,
    base_paths: Iterable[Path],
) -> None:
    """Validate that target_path stays within one of the allowed roots."""

    try:
        resolved_target = target_path.resolve()
        resolved_bases = [base.resolve() for base in base_paths]
    except (OSError, RuntimeError) as e:
        logger.error(f"Path validation error: {e}")
        raise HTTPException(status_code=400, detail="Invalid path")

    for resolved_base in resolved_bases:
        try:
            resolved_target.relative_to(resolved_base)
            return
        except ValueError:
            continue

    allowed = ", ".join(str(base) for base in resolved_bases)
    logger.warning(
        "Path traversal attempt detected: %s not under any of [%s]",
        target_path,
        allowed,
    )
    raise HTTPException(
        status_code=403,
        detail="Access denied: Path traversal attempt detected",
    )


def _resolve_recorded_job_path(path_value: str, *, run_store_root: Path) -> Path:
    """Resolve stored run/provenance paths across canonical and legacy roots."""

    resolved = resolve_recorded_path_for_read(path_value, primary_root=run_store_root)
    _validate_path_security_against_roots(
        resolved,
        get_recorder_roots_for_read(run_store_root),
    )
    return resolved


@router.get(
    "/{job_id}/provenance",
    response_model=dict[str, Any],
    responses={
        200: {
            "description": "Provenance metadata retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "run_id": "exec_123",
                        "command": "fsl bet input.nii.gz output.nii.gz",
                        "exit_code": 0,
                        "started_at": "2025-01-01T12:00:00Z",
                        "finished_at": "2025-01-01T12:00:05Z",
                        "environment": {"PATH": "/usr/bin"},
                        "outputs": [{"path": "output.nii.gz", "size": 1024}],
                    }
                }
            },
        },
        404: {"description": "Job not found or provenance not available"},
        500: {"description": "Error reading provenance file"},
    },
    tags=["provenance"],
)
async def get_job_provenance(job_id: str, request: Request) -> dict[str, Any]:
    """
    Get the full provenance JSON for a job.

    Returns the complete provenance.json file capturing execution metadata,
    command, environment, timing, and outputs.

    This endpoint provides access to the raw provenance record generated
    by the RunRecorder during job execution.
    """
    # Get job from JobStore (via app state)
    job_store = request.app.state.job_store
    job_record = await job_store.get(job_id)

    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job has provenance
    if not job_record.provenance_path:
        raise HTTPException(
            status_code=404, detail="Provenance not available for this job"
        )

    # Construct full path
    config = get_recorder_config()
    run_store_root = config.root.resolve()
    provenance_path = _resolve_recorded_job_path(
        job_record.provenance_path,
        run_store_root=run_store_root,
    )

    # Check file exists
    if not provenance_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Provenance file not found at {provenance_path}"
        )

    # Read and return provenance JSON
    try:
        with open(provenance_path) as f:
            provenance_data = json.load(f)

        logger.info(f"Served provenance for job {job_id}")
        return provenance_data

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in provenance file {provenance_path}: {e}")
        raise HTTPException(
            status_code=500, detail="Provenance file contains invalid JSON"
        )
    except Exception as e:
        logger.error(f"Error reading provenance file {provenance_path}: {e}")
        raise HTTPException(status_code=500, detail="Error reading provenance file")


@router.get(
    "/{job_id}/plan",
    response_model=dict[str, Any],
    responses={
        200: {
            "description": "Planner trace retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "intent": "skull strip",
                        "candidates": [
                            {
                                "tool_id": "fsl.bet",
                                "tool_name": "bet",
                                "score": 0.85,
                                "image": "/cvmfs/fsl/bet.simg",
                                "preflight_ok": True,
                                "reason": "All checks passed",
                            }
                        ],
                        "chosen": {
                            "tool_id": "fsl.bet",
                            "tool_name": "bet",
                            "score": 0.85,
                        },
                        "plan_id": "uuid-here",
                        "constraints": {"input": "/data/brain.nii.gz"},
                    }
                }
            },
        },
        404: {
            "description": "Job or plan not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Plan not available (planner was not used for this job)"
                    }
                }
            },
        },
    },
)
async def get_job_plan(job_id: str, request: Request) -> dict[str, Any]:
    """
    Get the planner trace for a job.

    Returns intent, ranked candidates, chosen tool, preflight results,
    and reasoning for tool selection.

    Uses a hybrid approach:
    1. First tries in-memory job metadata (fast path for recent jobs)
    2. Falls back to provenance.json (persistent path for completed jobs)

    Returns 404 if:
    - Job not found
    - Plan unavailable (planner was not used)
    - Job has not completed and metadata not available

    Note: Jobs created with BR_PLANNER_MODE=disabled will not have plan traces.
    """

    # STEP 1: Try in-memory first (fast path)
    job = _get_router_job(job_id)
    if job and job.metadata and "planner_trace" in job.metadata:
        logger.info(
            f"Returning planner trace for job {job_id} from metadata (fast path)"
        )
        return job.metadata["planner_trace"]

    # STEP 2: Fall back to JobStore + provenance.json
    job_store = request.app.state.job_store
    job_record = await job_store.get(job_id)

    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job_record.provenance_path:
        raise HTTPException(
            status_code=404,
            detail="Plan not available (job may not have used planner or has not completed)",
        )

    # STEP 3: Read from provenance.json
    recorder_config = get_recorder_config()
    provenance_path = _resolve_recorded_job_path(
        job_record.provenance_path,
        run_store_root=recorder_config.root.resolve(),
    )

    if not provenance_path.exists():
        logger.warning(f"Provenance file not found for job {job_id}: {provenance_path}")
        raise HTTPException(status_code=404, detail="Provenance file not found")

    try:
        with open(provenance_path) as f:
            provenance_data = json.load(f)

        if "plan" not in provenance_data:
            raise HTTPException(
                status_code=404,
                detail="Plan not available (planner was not used for this job)",
            )

        logger.info(f"Returning planner trace for job {job_id} from provenance.json")
        return provenance_data["plan"]

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping them
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in provenance file {provenance_path}: {e}")
        raise HTTPException(
            status_code=500, detail="Provenance file contains invalid JSON"
        )
    except Exception as e:
        logger.error(f"Error reading provenance file {provenance_path}: {e}")
        raise HTTPException(status_code=500, detail="Error reading provenance file")


@router.get("/{job_id}/plan/por", response_model=PlanOfRecordResponse)
async def get_job_plan_of_record(job_id: str, request: Request) -> PlanOfRecordResponse:
    """Return the committed Plan-of-Record and POR token for a job."""

    job = await _get_job_with_store(job_id, request)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    plan, _, por_token = _extract_plan_bundle(job)
    if not plan:
        raise HTTPException(
            status_code=404,
            detail="Plan-of-record not available (planner was not used for this job)",
        )

    return PlanOfRecordResponse(plan=plan, por_token=por_token)


@router.get("/{job_id}/plan/events", response_model=PlanEventsResponse)
async def get_job_plan_events(job_id: str, request: Request) -> PlanEventsResponse:
    """Return the Agent plan execution events recorded for a job."""

    job = await _get_job_with_store(job_id, request)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    plan, events, _ = _extract_plan_bundle(job)
    if not plan:
        raise HTTPException(
            status_code=404,
            detail="Plan events unavailable (planner was not used for this job)",
        )

    plan_id = plan.get("plan_id") or job.id
    return PlanEventsResponse(plan_id=plan_id, events=events)


@router.get(
    "/{job_id}/artifacts/files",
    response_model=dict[str, Any],
    responses={
        200: {
            "description": "File list retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "run_id": "exec_123",
                        "run_dir": "/tmp/runs/exec_123",
                        "file_count": 2,
                        "files": [
                            {
                                "name": "output.nii.gz",
                                "size": 1048576,
                                "modified": "2025-01-01T12:00:05",
                            },
                            {
                                "name": "results.csv",
                                "size": 2048,
                                "modified": "2025-01-01T12:00:06",
                            },
                        ],
                    }
                }
            },
        },
        404: {"description": "Job not found or run directory not available"},
    },
    tags=["provenance", "artifacts"],
)
async def list_artifact_files(job_id: str, request: Request) -> dict[str, Any]:
    """
    List all artifact files in the job's run directory.

    Returns a list of files with metadata (name, size, modified time).
    Does not include the provenance.json file itself.

    Use this endpoint to discover what output files are available for download
    from a job's execution.
    """
    # Get job from JobStore
    job_store = request.app.state.job_store
    job_record = await job_store.get(job_id)

    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job has run_dir
    if not job_record.run_dir:
        raise HTTPException(
            status_code=404, detail="Run directory not available for this job"
        )

    config = get_recorder_config()
    run_store_root = config.root.resolve()
    run_dir = _resolve_recorded_job_path(
        job_record.run_dir,
        run_store_root=run_store_root,
    )

    # Check directory exists
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(
            status_code=404, detail=f"Run directory not found: {run_dir}"
        )

    # List files recursively (exclude provenance.json)
    try:
        files = _collect_artifact_files(run_dir)

        logger.info(f"Listed {len(files)} artifact files for job {job_id}")

        return {
            "run_id": job_record.run_id,
            "run_dir": str(run_dir),
            "file_count": len(files),
            "files": files,
        }

    except Exception as e:
        logger.error(f"Error listing files in {run_dir}: {e}")
        raise HTTPException(status_code=500, detail="Error listing artifact files")


@router.get(
    "/{job_id}/artifacts/files/{filename:path}",
    response_class=FileResponse,
    responses={
        200: {
            "description": "File download successful",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "application/json": {},
                "text/plain": {},
                "application/x-nifti": {},
            },
        },
        400: {"description": "Invalid filename (contains path separators)"},
        403: {
            "description": "Access denied (provenance.json or path traversal attempt)"
        },
        404: {"description": "Job, run directory, or file not found"},
    },
    tags=["provenance", "artifacts"],
)
async def download_artifact_file(
    job_id: str, filename: str, request: Request
) -> FileResponse:
    """
    Download a specific artifact file from the job's run directory.

    Security features:
    - Rejects path traversal segments
    - Blocks access to provenance.json (use /provenance endpoint)
    - Validates file is within run directory
    - Auto-detects content type based on file extension
    """
    normalized = filename.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or normalized.startswith("/")
        or normalized.startswith("\\")
        or "\0" in normalized
    ):
        raise HTTPException(status_code=400, detail="Invalid filename")

    requested = Path(normalized)
    if any(part in {"", ".", ".."} for part in requested.parts):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Get job from JobStore
    job_store = request.app.state.job_store
    job_record = await job_store.get(job_id)

    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job has run_dir
    if not job_record.run_dir:
        raise HTTPException(
            status_code=404, detail="Run directory not available for this job"
        )

    config = get_recorder_config()
    run_store_root = config.root.resolve()
    run_dir = _resolve_recorded_job_path(
        job_record.run_dir,
        run_store_root=run_store_root,
    )
    file_path = (run_dir / requested).resolve()

    # Validate path security
    _validate_path_security_against_roots(
        file_path,
        get_recorder_roots_for_read(run_store_root),
    )
    resolved_run_dir = run_dir.resolve()
    try:
        file_path.relative_to(resolved_run_dir)
    except ValueError:
        raise HTTPException(
            status_code=403, detail="Access denied: Path traversal attempt detected"
        )

    # Check file exists
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # Don't allow downloading provenance.json via this endpoint
    if file_path.name == "provenance.json":
        raise HTTPException(
            status_code=403, detail="Use /provenance endpoint to access provenance.json"
        )

    # Return file
    logger.info(f"Serving artifact file {normalized} for job {job_id}")

    # Determine media type based on extension
    media_type = "application/octet-stream"
    if normalized.endswith(".json"):
        media_type = "application/json"
    elif normalized.endswith(".txt") or normalized.endswith(".log"):
        media_type = "text/plain"
    elif normalized.endswith(".nii.gz") or normalized.endswith(".nii"):
        media_type = "application/x-nifti"

    if _is_test_env():
        return Response(
            content=file_path.read_bytes(),
            media_type=media_type,
        )

    return FileResponse(
        path=str(file_path), filename=file_path.name, media_type=media_type
    )


# ============================================================================
# Job Listing
# ============================================================================


class JobSummary(BaseModel):
    """Summary view of a job for list endpoints"""

    job_id: str
    state: str
    tool: str | None = None
    prompt: str | None = None
    created_at: int  # Unix timestamp
    updated_at: int | None = None  # Unix timestamp
    priority: int = 0


@router.get(
    "/summaries",
    response_model=list[JobSummary],
    responses={
        200: {
            "description": "Job list retrieved successfully",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "job_id": "run_abc123",
                            "state": "succeeded",
                            "tool": "fsl.bet",
                            "prompt": "Extract brain from T1",
                            "created_at": 1704067200,
                            "updated_at": 1704067260,
                            "priority": 0,
                        },
                        {
                            "job_id": "run_xyz789",
                            "state": "running",
                            "tool": "afni.3dSkullStrip",
                            "prompt": "Skull strip T1 image",
                            "created_at": 1704067100,
                            "updated_at": 1704067150,
                            "priority": 5,
                        },
                    ]
                }
            },
        }
    },
    tags=["job-management", "jobs"],
)
async def list_job_summaries(
    request: Request,
    state: str | None = Query(
        None, description="Filter by job state (running, succeeded, failed, etc.)"
    ),
    limit: int = Query(
        50, ge=1, le=1000, description="Maximum number of jobs to return"
    ),
    offset: int = Query(0, ge=0, description="Number of jobs to skip"),
) -> list[JobSummary]:
    """
    List jobs with optional filtering.

    Query parameters:
    - state: Filter by job state (optional)
    - limit: Maximum results (default 50, max 1000)
    - offset: Pagination offset (default 0)

    Returns jobs sorted by creation time (newest first).
    """
    job_store = request.app.state.job_store

    # Get all jobs from JobStore (newest -> oldest handled below)
    all_jobs = await job_store.list_all()

    # Filter by state if provided
    if state:
        all_jobs = [job for job in all_jobs if job.state == state]

    # Sort by created_at descending (newest first)
    all_jobs.sort(key=lambda j: j.created_at, reverse=True)

    # Apply pagination
    paginated_jobs = all_jobs[offset : offset + limit]

    # Convert JobRecord to JobSummary
    summaries = []
    for job_record in paginated_jobs:
        # Parse payload to extract tool and prompt
        tool = None
        prompt = None
        try:
            payload = json.loads(job_record.payload_json)
            tool = payload.get("tool")
            prompt = payload.get("prompt") or payload.get("intent")
        except (json.JSONDecodeError, AttributeError):
            pass

        # Determine most recent timestamp available
        timestamps = [
            job_record.finished_at,
            job_record.started_at,
            job_record.claimed_at,
            job_record.queued_at,
            job_record.created_at,
        ]
        updated_at = max(
            (ts for ts in timestamps if ts is not None), default=job_record.created_at
        )

        summary = JobSummary(
            job_id=job_record.job_id,
            state=job_record.state,
            tool=tool,
            prompt=prompt,
            created_at=job_record.created_at,
            updated_at=updated_at,
            priority=job_record.priority,
        )
        summaries.append(summary)

    logger.info(
        f"Returning {len(summaries)} jobs (state={state}, limit={limit}, offset={offset})"
    )
    return summaries
