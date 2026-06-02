"""Job submission endpoint for workflow execution."""

import asyncio
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type
from urllib.parse import urljoin

# FastAPI imports
import httpx
import redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator

# Internal imports
try:
    from brain_researcher.services.agent.kg_resolution import (
        resolve_dataset_reference,
    )
    from brain_researcher.services.agent.planning import PlanningEngine
    from brain_researcher.services.agent.query_models import QueryUnderstandingModel
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    AGENT_AVAILABLE = True
except ImportError:
    AGENT_AVAILABLE = False
    # Fallback placeholder to satisfy Pydantic forward refs when agent deps are absent
    QueryUnderstandingModel = Dict[str, Any]  # type: ignore[misc]

from brain_researcher.legacy.api_gateway.env import ORCHESTRATOR_URL
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.worker import JobWorker


class JobPriority(str, Enum):
    """Job priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class JobStatus(str, Enum):
    """Job execution status."""

    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    CANCELLING = "cancelling"
    SKIPPED = "skipped"
    PAUSED = "paused"
    TIMEOUT = "timeout"


class WorkflowType(str, Enum):
    """Types of workflows."""

    ANALYSIS = "analysis"
    PREPROCESSING = "preprocessing"
    VISUALIZATION = "visualization"
    META_ANALYSIS = "meta_analysis"
    CUSTOM = "custom"


class JobSubmissionRequest(BaseModel):
    """Request model for job submission."""

    query: str = Field(..., description="Natural language query or command")
    workflow_type: WorkflowType = Field(
        WorkflowType.ANALYSIS, description="Type of workflow"
    )
    query_understanding: Optional["QueryUnderstandingModel"] = Field(
        default=None, description="Optional precomputed query understanding payload"
    )
    dataset_id: Optional[str] = Field(None, description="Dataset identifier")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Additional parameters"
    )
    priority: JobPriority = Field(JobPriority.NORMAL, description="Job priority")
    callback_url: Optional[str] = Field(None, description="Webhook URL for completion")
    timeout_seconds: int = Field(
        3600, description="Job timeout in seconds", ge=60, le=86400
    )
    retry_on_failure: bool = Field(True, description="Retry on failure")
    max_retries: int = Field(3, description="Maximum retry attempts", ge=0, le=10)
    tags: List[str] = Field(default_factory=list, description="Job tags for filtering")

    @validator("query")
    def validate_query(cls, v):
        """Validate query is not empty."""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()

    @validator("callback_url")
    def validate_callback_url(cls, v):
        """Validate callback URL format."""
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("Callback URL must be HTTP or HTTPS")
        return v


class JobSubmissionResponse(BaseModel):
    """Response model for job submission."""

    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Current job status")
    message: str = Field(..., description="Status message")
    estimated_completion: Optional[datetime] = Field(
        None, description="Estimated completion time"
    )
    queue_position: Optional[int] = Field(None, description="Position in queue")
    links: Dict[str, str] = Field(default_factory=dict, description="Related links")


# Resolve forward refs for query_understanding (Pydantic v2)
JobSubmissionRequest.model_rebuild()


def _env_flag(name: str, default: bool) -> bool:
    """Return True if the environment flag is explicitly enabled."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


WORKFLOW_TO_PIPELINE = {
    WorkflowType.PREPROCESSING: "preprocessing",
    WorkflowType.VISUALIZATION: "custom",
    WorkflowType.META_ANALYSIS: "custom",
    WorkflowType.ANALYSIS: "custom",
    WorkflowType.CUSTOM: "custom",
}

PRIORITY_TO_VALUE = {
    JobPriority.LOW: 2,
    JobPriority.NORMAL: 5,
    JobPriority.HIGH: 8,
    JobPriority.CRITICAL: 9,
}


def _normalize_tags(tags: Optional[List[str]]) -> List[str]:
    """Return lower-cased, de-duplicated tags while preserving order."""

    normalized: List[str] = []
    seen: set[str] = set()
    if not tags:
        return normalized

    for raw in tags:
        if not isinstance(raw, str):
            continue
        slug = raw.strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        normalized.append(slug)
    return normalized


class OrchestratorRunClient:
    """Thin HTTP client for delegating run submissions to the orchestrator."""

    def __init__(self, base_url: str = ORCHESTRATOR_URL, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout, connect=min(timeout / 2, 5.0))

    async def submit_run(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        url = self._url("/run")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network path
            detail = self._extract_detail(exc.response)
            raise HTTPException(
                status_code=exc.response.status_code, detail=detail
            ) from exc
        return response.status_code, response.json()

    def absolute_url(self, path: str) -> str:
        return self._url(path)

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    @staticmethod
    def _extract_detail(response: httpx.Response) -> Any:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "Upstream error"
        return payload.get("detail") or payload


@dataclass
class Job:
    """Internal job representation."""

    job_id: str
    query: str
    workflow_type: WorkflowType
    dataset_id: Optional[str]
    parameters: Dict[str, Any]
    priority: JobPriority
    status: JobStatus
    callback_url: Optional[str]
    timeout_seconds: int
    retry_on_failure: bool
    max_retries: int
    worker_id: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    attempt: int = 0
    gpu_count_required: int = 0
    gpu_type: Optional[str] = None
    assigned_gpu_slots: List[int] = field(default_factory=list)
    retry_count: int = 0
    tags: List[str] = field(default_factory=list)
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    artifacts: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        # Convert datetime objects
        for key in ["submitted_at", "started_at", "completed_at"]:
            if data[key]:
                data[key] = data[key].isoformat()
        # Convert enums
        data["workflow_type"] = self.workflow_type.value
        data["priority"] = self.priority.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create from dictionary."""
        # Convert datetime strings
        for key in ["submitted_at", "started_at", "completed_at"]:
            if data.get(key) and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key])

        # Convert enums
        if "workflow_type" in data:
            data["workflow_type"] = WorkflowType(data["workflow_type"])
        if "priority" in data:
            data["priority"] = JobPriority(data["priority"])
        if "status" in data:
            data["status"] = JobStatus(data["status"])

        return cls(**data)


class JobQueue:
    """Priority job queue manager."""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """Initialize job queue.

        Args:
            redis_client: Redis client for persistence
        """
        self.redis_client = redis_client or self._create_redis_client()
        self.jobs: Dict[str, Job] = {}
        self.queue_keys = {
            JobPriority.CRITICAL: "queue:critical",
            JobPriority.HIGH: "queue:high",
            JobPriority.NORMAL: "queue:normal",
            JobPriority.LOW: "queue:low",
        }

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback."""
        try:
            import os

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = redis.from_url(redis_url, decode_responses=False)
            client.ping()
            return client
        except:
            # Use fakeredis for testing
            try:
                import fakeredis

                return fakeredis.FakeRedis(decode_responses=False)
            except ImportError:
                raise RuntimeError("Redis not available")

    def submit(self, job: Job) -> str:
        """Submit job to queue.

        Args:
            job: Job to submit

        Returns:
            Job ID
        """
        # Store job
        self.jobs[job.job_id] = job

        # Persist to Redis
        job_data = json.dumps(job.to_dict())
        self.redis_client.hset("jobs", job.job_id, job_data)

        # Add to priority queue
        queue_key = self.queue_keys[job.priority]
        score = -time.time() if job.priority == JobPriority.CRITICAL else time.time()
        self.redis_client.zadd(queue_key, {job.job_id: score})

        # Update status
        job.status = JobStatus.QUEUED
        self._update_job(job)

        return job.job_id

    def get_next(self) -> Optional[Job]:
        """Get next job from queue by priority.

        Returns:
            Next job or None
        """
        # Check queues in priority order
        for priority in [
            JobPriority.CRITICAL,
            JobPriority.HIGH,
            JobPriority.NORMAL,
            JobPriority.LOW,
        ]:
            queue_key = self.queue_keys[priority]

            # Get first job from queue
            job_ids = self.redis_client.zrange(queue_key, 0, 0)
            if job_ids:
                job_id = (
                    job_ids[0].decode() if isinstance(job_ids[0], bytes) else job_ids[0]
                )

                # Remove from queue
                self.redis_client.zrem(queue_key, job_id)

                # Get job
                job = self.get_job(job_id)
                if job:
                    return job

        return None

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID.

        Args:
            job_id: Job ID

        Returns:
            Job or None
        """
        # Check memory cache
        if job_id in self.jobs:
            return self.jobs[job_id]

        # Load from Redis
        job_data = self.redis_client.hget("jobs", job_id)
        if job_data:
            data = json.loads(job_data)
            job = Job.from_dict(data)
            self.jobs[job_id] = job
            return job

        return None

    def _update_job(self, job: Job):
        """Update job in storage."""
        job_data = json.dumps(job.to_dict())
        self.redis_client.hset("jobs", job.job_id, job_data)

    def get_queue_position(self, job_id: str) -> Optional[int]:
        """Get position of job in queue.

        Args:
            job_id: Job ID

        Returns:
            Queue position or None
        """
        job = self.get_job(job_id)
        if not job or job.status != JobStatus.QUEUED:
            return None

        queue_key = self.queue_keys[job.priority]
        rank = self.redis_client.zrank(queue_key, job_id)

        return rank + 1 if rank is not None else None

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job.

        Args:
            job_id: Job ID

        Returns:
            True if cancelled
        """
        job = self.get_job(job_id)
        if not job:
            return False

        if job.status in [JobStatus.PENDING, JobStatus.QUEUED]:
            # Remove from queue
            for queue_key in self.queue_keys.values():
                self.redis_client.zrem(queue_key, job_id)

            # Update status
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now()
            self._update_job(job)

            return True

        return False

    def get_statistics(self) -> Dict[str, Any]:
        """Get queue statistics.

        Returns:
            Queue statistics
        """
        stats = {
            "total_jobs": self.redis_client.hlen("jobs"),
            "queue_sizes": {},
            "status_counts": {},
        }

        # Queue sizes by priority
        for priority, queue_key in self.queue_keys.items():
            stats["queue_sizes"][priority.value] = self.redis_client.zcard(queue_key)

        # Count by status
        status_counts = {status.value: 0 for status in JobStatus}

        for job_id in self.redis_client.hkeys("jobs"):
            job = self.get_job(job_id.decode() if isinstance(job_id, bytes) else job_id)
            if job:
                status_counts[job.status.value] += 1

        stats["status_counts"] = status_counts

        return stats


class GatewayJobStoreAdapter:
    """Shim that maps JobWorker state updates to local JobQueue jobs."""

    STATE_MAP = {
        JobState.PENDING: JobStatus.PENDING,
        JobState.QUEUED: JobStatus.QUEUED,
        JobState.CLAIMED: JobStatus.RUNNING,
        JobState.RUNNING: JobStatus.RUNNING,
        JobState.SUCCEEDED: JobStatus.COMPLETED,
        JobState.FAILED: JobStatus.FAILED,
        JobState.CANCELLED: JobStatus.CANCELLED,
        JobState.TIMEOUT: JobStatus.TIMEOUT,
        JobState.RETRYING: JobStatus.RETRYING,
    }

    def __init__(self, job: Job, job_queue: JobQueue):
        self.job = job
        self.job_queue = job_queue

    async def update_state(
        self, job_id: str, new_state: Optional[JobState] = None, **fields
    ) -> bool:
        if job_id != self.job.job_id:
            return False

        if new_state is not None:
            state_enum = (
                new_state if isinstance(new_state, JobState) else JobState(new_state)
            )
            mapped = self.STATE_MAP.get(state_enum)
            if mapped:
                self.job.status = mapped

        started_at = fields.get("started_at")
        if started_at is not None:
            self.job.started_at = datetime.fromtimestamp(started_at)

        finished_at = fields.get("finished_at") or fields.get("completed_at")
        if finished_at is not None:
            self.job.completed_at = datetime.fromtimestamp(finished_at)

        if "error" in fields and fields["error"]:
            self.job.error_message = fields["error"]

        if "payload_json" in fields:
            self.job.metadata["payload_json"] = fields["payload_json"]

        if "run_dir" in fields:
            self.job.metadata["run_dir"] = fields["run_dir"]

        if "provenance_path" in fields:
            self.job.metadata["provenance_path"] = fields["provenance_path"]

        self.job_queue._update_job(self.job)
        return True

    async def enqueue(self, job: JobRecord) -> str:  # pragma: no cover
        raise NotImplementedError

    async def claim_next(
        self, worker_id: str, lease_ttl: int = 60, gpu_filter: Optional[bool] = None
    ):  # pragma: no cover
        raise NotImplementedError

    async def heartbeat(
        self, worker_id: str, job_id: Optional[str] = None
    ):  # pragma: no cover
        raise NotImplementedError

    async def cancel(self, job_id: str) -> bool:  # pragma: no cover
        return False

    async def get(self, job_id: str) -> Optional[JobRecord]:  # pragma: no cover
        return None

    async def get_queue_stats(self) -> Dict[str, Any]:  # pragma: no cover
        return {}

    async def get_slot_stats(self) -> Dict[str, int]:  # pragma: no cover
        return {}

    async def get_assigned_devices(self, job_id: str) -> List[int]:  # pragma: no cover
        return []


class PlanExecutionRunner:
    """Run plan envelopes through the orchestrator JobWorker pipeline."""

    def __init__(self, job_queue: JobQueue, worker_cls: Type[JobWorker] = JobWorker):
        self.job_queue = job_queue
        self.worker_cls = worker_cls

    async def run(self, job: Job) -> None:
        plan = job.metadata.get("plan")
        if not plan:
            raise ValueError("Job missing plan envelope")

        payload = self._build_payload(job, plan)
        adapter = GatewayJobStoreAdapter(job, self.job_queue)
        worker = self.worker_cls(
            job_store=adapter, worker_id=f"gateway-runner-{job.job_id}"
        )
        job_record = JobRecord(
            job_id=job.job_id,
            kind="plan_execution",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
        )

        await worker.run_plan_payload(job_record, payload)

    def _build_payload(self, job: Job, plan: Dict[str, Any]) -> Dict[str, Any]:
        plan_id = plan.get("plan_id") or job.job_id
        plan["plan_id"] = plan_id
        dag = plan.get("dag") or {"steps": [], "artifacts": []}

        snapshot = {
            "intent": plan.get("intent"),
            "candidates": plan.get("candidates"),
            "chosen_tool": plan.get("chosen_tool"),
            "selection_reason": plan.get("selection_reason"),
        }

        return {
            "plan_id": plan_id,
            "plan": plan,
            "dag": dag,
            "steps": dag.get("steps", []),
            "artifacts": dag.get("artifacts", {}),
            "context": plan.get("context"),
            "snapshot": snapshot,
            "metadata": {
                "version": plan.get("version", 1),
                "por_token": plan.get("por_token"),
            },
        }


class JobSubmissionService:
    """Service for handling job submissions."""

    def __init__(
        self,
        job_queue: JobQueue,
        executor: Optional[ThreadPoolExecutor] = None,
        *,
        delegate_runs: Optional[bool] = None,
        orchestrator_client: Optional[OrchestratorRunClient] = None,
    ):
        """Initialize job submission service.

        Args:
            job_queue: Job queue manager
            executor: Thread pool executor for background tasks
            delegate_runs: Force delegation to orchestrator if set
            orchestrator_client: Optional orchestrator client override
        """
        self.job_queue = job_queue
        self.executor = executor or ThreadPoolExecutor(max_workers=4)
        self.delegate_runs = (
            _env_flag("BR_GATEWAY_DELEGATE_TO_ORCH", True)
            if delegate_runs is None
            else delegate_runs
        )
        self.orchestrator_client = orchestrator_client or OrchestratorRunClient()
        self.plan_runner: Optional[PlanExecutionRunner] = None
        if not self.delegate_runs:
            self.plan_runner = PlanExecutionRunner(job_queue)

        if not self.delegate_runs and AGENT_AVAILABLE:
            self.planning_engine = PlanningEngine()
            self.tool_registry = ToolRegistry.from_env(auto_discover=True)

    async def submit_job(self, request: JobSubmissionRequest) -> JobSubmissionResponse:
        """Submit a new job via orchestrator delegation or legacy local mode."""

        if self.delegate_runs:
            return await self._submit_via_orchestrator(request)
        return await self._submit_locally(request)

    async def _submit_via_orchestrator(
        self, request: JobSubmissionRequest
    ) -> JobSubmissionResponse:
        payload = self._build_orchestrator_payload(request)
        _, response_json = await self.orchestrator_client.submit_run(payload)
        return self._convert_orchestrator_response(response_json)

    async def _submit_locally(
        self, request: JobSubmissionRequest
    ) -> JobSubmissionResponse:
        normalized_tags = _normalize_tags(request.tags)
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            query=request.query,
            workflow_type=request.workflow_type,
            dataset_id=request.dataset_id,
            parameters=request.parameters,
            priority=request.priority,
            status=JobStatus.PENDING,
            callback_url=request.callback_url,
            timeout_seconds=request.timeout_seconds,
            retry_on_failure=request.retry_on_failure,
            max_retries=request.max_retries,
            tags=normalized_tags,
        )
        self._attach_plan_envelope(job, request, normalized_tags)
        self.job_queue.submit(job)
        queue_position = self.job_queue.get_queue_position(job_id)
        estimated_completion = self._estimate_completion(job, queue_position)

        asyncio.create_task(self._process_job(job))

        return JobSubmissionResponse(
            job_id=job_id,
            status=job.status,
            message="Job submitted successfully",
            estimated_completion=estimated_completion,
            queue_position=queue_position,
            links={
                "status": f"/api/v1/jobs/{job_id}",
                "logs": f"/api/v1/jobs/{job_id}/logs",
                "artifacts": f"/api/v1/jobs/{job_id}/artifacts",
                "cancel": f"/api/v1/jobs/{job_id}/cancel",
            },
        )

    def _build_orchestrator_payload(
        self, request: JobSubmissionRequest
    ) -> Dict[str, Any]:
        pipeline = WORKFLOW_TO_PIPELINE.get(request.workflow_type, "custom")
        priority_value = PRIORITY_TO_VALUE.get(request.priority, 5)
        parameters = dict(request.parameters or {})
        normalized_tags = _normalize_tags(request.tags)
        if request.dataset_id:
            parameters.setdefault("dataset_id", request.dataset_id)
        parameters["tags"] = normalized_tags

        # Attach query understanding if provided, otherwise build a minimal one
        qur_payload: Optional[Dict[str, Any]] = None
        if request.query_understanding:
            qur_payload = request.query_understanding.model_dump()
        else:
            try:
                # Minimal attempt: resolve dataset mention from query
                ds = resolve_dataset_reference(request.query)
                entities = []
                if ds:
                    entities.append({"text": ds.dataset_id, "type": "dataset"})
                qur_payload = QueryUnderstandingModel(
                    original_query=request.query,
                    entities=entities,
                    resolved_datasets=[],
                    kg_nodes=[],
                    ambiguities=[],
                    existing_derivatives=[],
                ).model_dump()
            except Exception:
                qur_payload = None

        client_meta = parameters.setdefault("_client_metadata", {})
        client_meta["normalized_tags"] = normalized_tags
        client_meta["plan_envelope"] = self._generate_plan_envelope(
            plan_id=f"client_plan_{uuid.uuid4().hex[:8]}",
            query=request.query,
            parameters=request.parameters or {},
            tags=normalized_tags,
            query_understanding=qur_payload,
        )

        return {
            "prompt": request.query,
            "pipeline": pipeline,
            "dataset_id": request.dataset_id,
            "parameters": parameters,
            "timeout_seconds": request.timeout_seconds,
            "priority": priority_value,
            "copilot": False,
            "demo_mode": False,
            **({"query_understanding": qur_payload} if qur_payload else {}),
        }

    def _convert_orchestrator_response(
        self, payload: Dict[str, Any]
    ) -> JobSubmissionResponse:
        job_id = payload.get("job_id") or payload.get("run_id")
        if not job_id:
            raise HTTPException(
                status_code=502, detail="Orchestrator response missing job_id"
            )

        cached = bool(payload.get("cached"))
        status = JobStatus.COMPLETED if cached else JobStatus.PENDING
        message = (
            "Result retrieved from cache" if cached else "Job submitted to orchestrator"
        )

        eta_seconds = payload.get("estimated_duration")
        estimated_completion: Optional[datetime] = None
        if isinstance(eta_seconds, (int, float)):
            estimated_completion = datetime.now(timezone.utc) + timedelta(
                seconds=int(eta_seconds)
            )

        queue_position = payload.get("queue_position")
        links: Dict[str, str] = {}
        status_url = payload.get("status_url")
        if status_url:
            links["status"] = self.orchestrator_client.absolute_url(status_url)
        stream_url = payload.get("stream_url")
        if stream_url:
            links["stream"] = self.orchestrator_client.absolute_url(stream_url)
        cache_key = payload.get("cache_key")
        if cache_key:
            links["cache_resolve"] = self.orchestrator_client.absolute_url(
                f"/api/runs/resolve?cache_key={cache_key}"
            )

        return JobSubmissionResponse(
            job_id=job_id,
            status=status,
            message=message,
            estimated_completion=estimated_completion,
            queue_position=queue_position,
            links=links,
        )

    def _estimate_completion(self, job: Job, queue_position: Optional[int]) -> datetime:
        """Estimate job completion time.

        Args:
            job: Job to estimate
            queue_position: Position in queue

        Returns:
            Estimated completion time
        """
        # Base estimation
        base_time = 300  # 5 minutes base time

        # Adjust by workflow type
        workflow_times = {
            WorkflowType.PREPROCESSING: 1800,  # 30 minutes
            WorkflowType.ANALYSIS: 900,  # 15 minutes
            WorkflowType.VISUALIZATION: 300,  # 5 minutes
            WorkflowType.META_ANALYSIS: 2400,  # 40 minutes
            WorkflowType.CUSTOM: 600,  # 10 minutes
        }

        estimated_seconds = workflow_times.get(job.workflow_type, base_time)

        # Add queue wait time
        if queue_position:
            estimated_seconds += queue_position * 60  # 1 minute per position

        return datetime.now() + timedelta(seconds=estimated_seconds)

    async def _process_job(self, job: Job):
        """Process a job asynchronously."""
        if not self.plan_runner:
            raise RuntimeError(
                "Plan execution runner is not configured for delegated mode"
            )
        # Update job status
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()
        self.job_queue._update_job(job)

        try:
            await self.plan_runner.run(job)
            if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now()
                job.result = {"message": "Workflow completed successfully"}
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now()
            job.error_message = str(exc)
        finally:
            self.job_queue._update_job(job)
        if job.callback_url:
            await self._send_webhook(job)

    def _attach_plan_envelope(
        self,
        job: Job,
        request: JobSubmissionRequest,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create and store a plan envelope for the submitted job."""

        plan = self._generate_plan_envelope(
            plan_id=job.job_id,
            query=job.query,
            parameters=request.parameters or {},
            tags=tags or job.tags,
            query_understanding=(
                job.parameters.get("query_understanding")
                if isinstance(job.parameters, dict)
                else None
            ),
        )
        job.metadata["plan"] = plan
        return plan

    def _generate_plan_envelope(
        self,
        *,
        plan_id: str,
        query: str,
        parameters: Dict[str, Any],
        tags: Optional[List[str]] = None,
        query_understanding: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        base_plan: Dict[str, Any] = {
            "plan_id": plan_id,
            "version": 1,
            "resolvable": True,
            "timestamp": int(time.time()),
            "intent": [query] if query else [],
            "candidates": [],
            "chosen_tool": None,
            "selection_reason": "Auto-generated plan envelope",
            "dag": {"steps": [], "artifacts": []},
            "context": {
                "query": query,
                "parameters": parameters,
                "tags": tags or [],
                "query_understanding": query_understanding or {},
            },
        }

        if (
            not self.delegate_runs
            and AGENT_AVAILABLE
            and hasattr(self, "planning_engine")
            and hasattr(self.planning_engine, "create_plan")
        ):
            try:
                plan_response = self.planning_engine.create_plan(query, parameters)
            except Exception as exc:  # pragma: no cover - diagnostic only
                base_plan.setdefault("dag", {"steps": [], "artifacts": []})
                base_plan.setdefault("context", {}).setdefault("errors", []).append(
                    str(exc)
                )
            else:
                if isinstance(plan_response, dict):
                    for key in (
                        "dag",
                        "intent",
                        "candidates",
                        "chosen_tool",
                        "selection_reason",
                        "context",
                        "version",
                        "timestamp",
                        "por_token",
                    ):
                        if key in plan_response:
                            base_plan[key] = plan_response[key]

        base_plan.setdefault("dag", {"steps": [], "artifacts": []})

        # Best-effort confidence summary (step/branch/plan)
        try:
            from brain_researcher.services.agent.planner_confidence import (
                compute_confidence_summary,
            )

            run_summary = compute_confidence_summary(base_plan)
            base_plan["run_summary"] = run_summary
            base_plan["plan_conf"] = run_summary.get("plan_conf")
            base_plan["confidence_score"] = run_summary.get("plan_conf")
        except Exception:
            pass
        return base_plan

    async def _send_webhook(self, job: Job):
        """Send webhook notification.

        Args:
            job: Completed job
        """
        # Would implement actual webhook delivery
        pass


# Create router
router = APIRouter(prefix="/api/v1", tags=["jobs"])


# Dependency to get service
def get_job_service() -> JobSubmissionService:
    """Get job submission service."""
    job_queue = JobQueue()
    delegate_runs = _env_flag("BR_GATEWAY_DELEGATE_TO_ORCH", True)
    return JobSubmissionService(job_queue, delegate_runs=delegate_runs)


@router.post(
    "/run", response_model=JobSubmissionResponse, status_code=status.HTTP_202_ACCEPTED
)
async def submit_job(
    request: JobSubmissionRequest,
    background_tasks: BackgroundTasks,
    service: JobSubmissionService = Depends(get_job_service),
) -> JobSubmissionResponse:
    """Submit a new job for execution.

    Args:
        request: Job submission request
        background_tasks: FastAPI background tasks
        service: Job submission service

    Returns:
        Job submission response
    """
    try:
        response = await service.submit_job(request)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit job: {str(e)}",
        )


@router.post(
    "/jobs", response_model=JobSubmissionResponse, status_code=status.HTTP_202_ACCEPTED
)
async def submit_job_alt(
    request: JobSubmissionRequest,
    service: JobSubmissionService = Depends(get_job_service),
) -> JobSubmissionResponse:
    """Alternative endpoint for job submission.

    Args:
        request: Job submission request
        service: Job submission service

    Returns:
        Job submission response
    """
    return await submit_job(request, BackgroundTasks(), service)
