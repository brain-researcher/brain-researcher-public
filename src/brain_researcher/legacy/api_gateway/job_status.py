"""Job status tracking and retrieval endpoints."""

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .job_submission import Job, JobPriority, JobQueue, JobStatus, WorkflowType


class JobStatusResponse(BaseModel):
    """Response model for job status."""

    job_id: str = Field(..., description="Job identifier")
    status: JobStatus = Field(..., description="Current status")
    progress: float = Field(0.0, description="Progress percentage", ge=0, le=100)
    message: str = Field("", description="Status message")
    submitted_at: datetime = Field(..., description="Submission time")
    started_at: Optional[datetime] = Field(None, description="Start time")
    completed_at: Optional[datetime] = Field(None, description="Completion time")
    runtime_seconds: Optional[float] = Field(None, description="Runtime in seconds")
    queue_position: Optional[int] = Field(None, description="Position in queue")
    retry_count: int = Field(0, description="Number of retries")
    error: Optional[str] = Field(None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class JobDetailsResponse(JobStatusResponse):
    """Detailed job information response."""

    query: str = Field(..., description="Original query")
    workflow_type: WorkflowType = Field(..., description="Workflow type")
    dataset_id: Optional[str] = Field(None, description="Dataset ID")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Job parameters"
    )
    priority: JobPriority = Field(..., description="Job priority")
    tags: List[str] = Field(default_factory=list, description="Job tags")
    result: Optional[Dict[str, Any]] = Field(None, description="Job result")
    artifacts: List[str] = Field(default_factory=list, description="Output artifacts")
    logs: List[str] = Field(default_factory=list, description="Recent log entries")


class JobListResponse(BaseModel):
    """Response for job listing."""

    jobs: List[JobStatusResponse] = Field(..., description="List of jobs")
    total: int = Field(..., description="Total number of jobs")
    page: int = Field(1, description="Current page")
    page_size: int = Field(20, description="Page size")
    has_next: bool = Field(False, description="Has next page")
    has_prev: bool = Field(False, description="Has previous page")


class LogEntry(BaseModel):
    """Log entry model."""

    timestamp: datetime = Field(..., description="Log timestamp")
    level: str = Field(..., description="Log level")
    message: str = Field(..., description="Log message")
    source: Optional[str] = Field(None, description="Log source")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional data"
    )


class ArtifactInfo(BaseModel):
    """Artifact information model."""

    artifact_id: str = Field(..., description="Artifact identifier")
    name: str = Field(..., description="Artifact name")
    type: str = Field(..., description="Artifact type")
    size_bytes: int = Field(..., description="Size in bytes")
    created_at: datetime = Field(..., description="Creation time")
    path: str = Field(..., description="Storage path")
    download_url: str = Field(..., description="Download URL")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Artifact metadata"
    )


class JobStatusService:
    """Service for job status operations."""

    def __init__(self, job_queue: JobQueue):
        """Initialize status service.

        Args:
            job_queue: Job queue manager
        """
        self.job_queue = job_queue
        self.redis_client = job_queue.redis_client

    def get_job_status(self, job_id: str) -> JobStatusResponse:
        """Get job status.

        Args:
            job_id: Job identifier

        Returns:
            Job status response

        Raises:
            HTTPException: If job not found
        """
        job = self.job_queue.get_job(job_id)

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
            )

        # Calculate runtime
        runtime_seconds = None
        if job.started_at:
            end_time = job.completed_at or datetime.now()
            runtime_seconds = (end_time - job.started_at).total_seconds()

        # Get queue position
        queue_position = None
        if job.status == JobStatus.QUEUED:
            queue_position = self.job_queue.get_queue_position(job_id)

        # Get progress
        progress = self._calculate_progress(job)

        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            progress=progress,
            message=self._get_status_message(job),
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            runtime_seconds=runtime_seconds,
            queue_position=queue_position,
            retry_count=job.retry_count,
            error=job.error_message,
            metadata=job.metadata,
        )

    def get_job_details(self, job_id: str) -> JobDetailsResponse:
        """Get detailed job information.

        Args:
            job_id: Job identifier

        Returns:
            Detailed job response

        Raises:
            HTTPException: If job not found
        """
        job = self.job_queue.get_job(job_id)

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
            )

        # Get base status
        status_response = self.get_job_status(job_id)

        return JobDetailsResponse(
            **status_response.dict(),
            query=job.query,
            workflow_type=job.workflow_type,
            dataset_id=job.dataset_id,
            parameters=job.parameters,
            priority=job.priority,
            tags=job.tags,
            result=job.result,
            artifacts=job.artifacts,
            logs=job.logs[-20:] if job.logs else [],  # Last 20 log entries
        )

    def list_jobs(
        self,
        status_filter: Optional[JobStatus] = None,
        priority_filter: Optional[JobPriority] = None,
        tag_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "submitted_at",
        ascending: bool = False,
    ) -> JobListResponse:
        """List jobs with filtering and pagination.

        Args:
            status_filter: Filter by status
            priority_filter: Filter by priority
            tag_filter: Filter by tag
            page: Page number
            page_size: Items per page
            sort_by: Sort field
            ascending: Sort order

        Returns:
            Job list response
        """
        # Get all job IDs
        job_ids = []
        for job_id_bytes in self.redis_client.hkeys("jobs"):
            job_id = (
                job_id_bytes.decode()
                if isinstance(job_id_bytes, bytes)
                else job_id_bytes
            )
            job_ids.append(job_id)

        # Load and filter jobs
        jobs = []
        for job_id in job_ids:
            job = self.job_queue.get_job(job_id)
            if not job:
                continue

            # Apply filters
            if status_filter and job.status != status_filter:
                continue
            if priority_filter and job.priority != priority_filter:
                continue
            if tag_filter and tag_filter not in job.tags:
                continue

            jobs.append(job)

        # Sort jobs
        sort_key = {
            "submitted_at": lambda j: j.submitted_at,
            "started_at": lambda j: j.started_at or datetime.min,
            "completed_at": lambda j: j.completed_at or datetime.min,
            "priority": lambda j: j.priority.value,
            "status": lambda j: j.status.value,
        }.get(sort_by, lambda j: j.submitted_at)

        jobs.sort(key=sort_key, reverse=not ascending)

        # Paginate
        total = len(jobs)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_jobs = jobs[start_idx:end_idx]

        # Convert to responses
        job_responses = []
        for job in page_jobs:
            status_response = self.get_job_status(job.job_id)
            job_responses.append(status_response)

        return JobListResponse(
            jobs=job_responses,
            total=total,
            page=page,
            page_size=page_size,
            has_next=end_idx < total,
            has_prev=page > 1,
        )

    def get_job_logs(
        self,
        job_id: str,
        limit: int = 100,
        offset: int = 0,
        level_filter: Optional[str] = None,
    ) -> List[LogEntry]:
        """Get job logs.

        Args:
            job_id: Job identifier
            limit: Maximum logs to return
            offset: Log offset
            level_filter: Filter by log level

        Returns:
            List of log entries

        Raises:
            HTTPException: If job not found
        """
        job = self.job_queue.get_job(job_id)

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
            )

        # Get logs from Redis
        log_key = f"logs:{job_id}"
        logs_data = self.redis_client.lrange(log_key, offset, offset + limit - 1)

        logs = []
        for log_bytes in logs_data:
            log_str = log_bytes.decode() if isinstance(log_bytes, bytes) else log_bytes
            try:
                log_data = json.loads(log_str)

                # Apply level filter
                if level_filter and log_data.get("level") != level_filter:
                    continue

                logs.append(
                    LogEntry(
                        timestamp=datetime.fromisoformat(log_data["timestamp"]),
                        level=log_data.get("level", "INFO"),
                        message=log_data.get("message", ""),
                        source=log_data.get("source"),
                        metadata=log_data.get("metadata", {}),
                    )
                )
            except:
                # Handle malformed logs
                logs.append(
                    LogEntry(
                        timestamp=datetime.now(),
                        level="INFO",
                        message=log_str,
                        source="unknown",
                    )
                )

        return logs

    async def stream_logs(self, job_id: str) -> AsyncGenerator[str, None]:
        """Stream job logs in real-time.

        Args:
            job_id: Job identifier

        Yields:
            Log entries as SSE events

        Raises:
            HTTPException: If job not found
        """
        job = self.job_queue.get_job(job_id)

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
            )

        # Subscribe to Redis pubsub
        pubsub = self.redis_client.pubsub()
        channel = f"logs:{job_id}"
        pubsub.subscribe(channel)

        try:
            # Send existing logs first
            existing_logs = self.get_job_logs(job_id, limit=20)
            for log in existing_logs:
                yield json.dumps(log.dict())

            # Stream new logs
            while job.status in [JobStatus.RUNNING, JobStatus.QUEUED]:
                message = pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    log_data = message["data"]
                    if isinstance(log_data, bytes):
                        log_data = log_data.decode()
                    yield log_data

                # Check if job is still running
                job = self.job_queue.get_job(job_id)
                if not job or job.status not in [JobStatus.RUNNING, JobStatus.QUEUED]:
                    break

                await asyncio.sleep(0.1)

        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    def get_job_artifacts(self, job_id: str) -> List[ArtifactInfo]:
        """Get job artifacts.

        Args:
            job_id: Job identifier

        Returns:
            List of artifact information

        Raises:
            HTTPException: If job not found
        """
        job = self.job_queue.get_job(job_id)

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
            )

        artifacts = []

        # Get artifact metadata from Redis
        for artifact_path in job.artifacts:
            artifact_key = f"artifact:{job_id}:{artifact_path}"
            artifact_data = self.redis_client.get(artifact_key)

            if artifact_data:
                try:
                    artifact_info = json.loads(artifact_data)
                    artifacts.append(
                        ArtifactInfo(
                            artifact_id=artifact_info.get("id", artifact_path),
                            name=artifact_info.get(
                                "name", artifact_path.split("/")[-1]
                            ),
                            type=artifact_info.get("type", "unknown"),
                            size_bytes=artifact_info.get("size_bytes", 0),
                            created_at=datetime.fromisoformat(
                                artifact_info.get(
                                    "created_at", datetime.now().isoformat()
                                )
                            ),
                            path=artifact_path,
                            download_url=f"/api/v1/jobs/{job_id}/artifacts/{artifact_path}",
                            metadata=artifact_info.get("metadata", {}),
                        )
                    )
                except:
                    # Handle malformed artifact data
                    artifacts.append(
                        ArtifactInfo(
                            artifact_id=artifact_path,
                            name=artifact_path.split("/")[-1],
                            type="unknown",
                            size_bytes=0,
                            created_at=datetime.now(),
                            path=artifact_path,
                            download_url=f"/api/v1/jobs/{job_id}/artifacts/{artifact_path}",
                            metadata={},
                        )
                    )

        return artifacts

    def _calculate_progress(self, job: Job) -> float:
        """Calculate job progress percentage.

        Args:
            job: Job to calculate progress for

        Returns:
            Progress percentage
        """
        # Terminal states
        if job.status == JobStatus.COMPLETED:
            return 100.0
        elif job.status in [
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
            JobStatus.SKIPPED,
        ]:
            return 0.0

        # Active states
        elif job.status == JobStatus.RUNNING:
            # Estimate based on runtime
            if job.started_at and job.timeout_seconds:
                elapsed = (datetime.now() - job.started_at).total_seconds()
                progress = min(95.0, (elapsed / job.timeout_seconds) * 100)
                return progress
            return 50.0

        elif job.status == JobStatus.CANCELLING:
            # Keep last known progress during cancellation
            return job.progress if hasattr(job, "progress") else 50.0

        elif job.status == JobStatus.PAUSED:
            # Keep progress at pause point
            return job.progress if hasattr(job, "progress") else 50.0

        elif job.status == JobStatus.RETRYING:
            # Show retry in progress
            return 25.0

        # Pre-execution states
        elif job.status == JobStatus.CLAIMED:
            return 10.0  # Claimed by worker, about to start

        elif job.status == JobStatus.QUEUED:
            return 5.0

        elif job.status == JobStatus.PENDING:
            return 0.0

        else:
            return 0.0

    def _get_status_message(self, job: Job) -> str:
        """Get human-readable status message.

        Args:
            job: Job to get message for

        Returns:
            Status message
        """
        messages = {
            JobStatus.PENDING: "Job is pending submission",
            JobStatus.QUEUED: f"Job is queued (position: {self.job_queue.get_queue_position(job.job_id) or 'unknown'})",
            JobStatus.CLAIMED: "Job claimed by worker, starting soon",
            JobStatus.RUNNING: "Job is running",
            JobStatus.COMPLETED: "Job completed successfully",
            JobStatus.FAILED: f"Job failed: {job.error_message or 'Unknown error'}",
            JobStatus.CANCELLED: "Job was cancelled",
            JobStatus.CANCELLING: "Job cancellation in progress",
            JobStatus.TIMEOUT: (
                f"Job timed out after {getattr(job, 'timeout_seconds', 'unknown')} seconds"
                if getattr(job, "timeout_seconds", None) is not None
                else "Job timed out"
            ),
            JobStatus.SKIPPED: "Job skipped due to dependency failure",
            JobStatus.PAUSED: "Job is paused",
            JobStatus.RETRYING: f"Job is retrying (attempt {job.retry_count}/{job.max_retries})",
        }

        return messages.get(job.status, "Unknown status")


# Create router
router = APIRouter(prefix="/api/v1/jobs", tags=["job-status"])


# Dependency to get service
def get_status_service() -> JobStatusService:
    """Get job status service."""
    job_queue = JobQueue()
    return JobStatusService(job_queue)


@router.get("/{job_id}", response_model=JobDetailsResponse)
async def get_job_status(
    job_id: str, service: JobStatusService = Depends(get_status_service)
) -> JobDetailsResponse:
    """Get detailed job status.

    Args:
        job_id: Job identifier
        service: Status service

    Returns:
        Job details
    """
    return service.get_job_details(job_id)


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status_brief(
    job_id: str, service: JobStatusService = Depends(get_status_service)
) -> JobStatusResponse:
    """Get brief job status.

    Args:
        job_id: Job identifier
        service: Status service

    Returns:
        Job status
    """
    return service.get_job_status(job_id)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
    priority: Optional[JobPriority] = Query(None, description="Filter by priority"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    sort_by: str = Query("submitted_at", description="Sort field"),
    ascending: bool = Query(False, description="Sort ascending"),
    service: JobStatusService = Depends(get_status_service),
) -> JobListResponse:
    """List jobs with filtering and pagination.

    Args:
        status: Status filter
        priority: Priority filter
        tag: Tag filter
        page: Page number
        page_size: Page size
        sort_by: Sort field
        ascending: Sort order
        service: Status service

    Returns:
        Job list
    """
    return service.list_jobs(
        status_filter=status,
        priority_filter=priority,
        tag_filter=tag,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        ascending=ascending,
    )


@router.get("/{job_id}/logs", response_model=List[LogEntry])
async def get_job_logs(
    job_id: str,
    limit: int = Query(100, ge=1, le=1000, description="Maximum logs"),
    offset: int = Query(0, ge=0, description="Log offset"),
    level: Optional[str] = Query(None, description="Filter by level"),
    service: JobStatusService = Depends(get_status_service),
) -> List[LogEntry]:
    """Get job logs.

    Args:
        job_id: Job identifier
        limit: Maximum logs
        offset: Log offset
        level: Level filter
        service: Status service

    Returns:
        Log entries
    """
    return service.get_job_logs(job_id, limit, offset, level)


@router.get("/{job_id}/logs/stream")
async def stream_job_logs(
    job_id: str, service: JobStatusService = Depends(get_status_service)
):
    """Stream job logs in real-time using Server-Sent Events.

    Args:
        job_id: Job identifier
        service: Status service

    Returns:
        SSE stream
    """
    return EventSourceResponse(service.stream_logs(job_id))


@router.get("/{job_id}/artifacts", response_model=List[ArtifactInfo])
async def get_job_artifacts(
    job_id: str, service: JobStatusService = Depends(get_status_service)
) -> List[ArtifactInfo]:
    """Get job artifacts.

    Args:
        job_id: Job identifier
        service: Status service

    Returns:
        Artifact list
    """
    return service.get_job_artifacts(job_id)
