"""
Dashboard layout management and live metrics endpoints for UI-035.
"""

import json
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Type, TypeVar, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .env import BR_KG_URL
from .job_state import jobs_db
from .job_store import JobState
from .job_store import JobState
from .background_tasks import _render_state_counts
from .models import (
    DashboardLayoutModel,
    DashboardLayoutRequest,
    DashboardLayoutListResponse,
    DashboardExportData,
    ErrorCode,
    ErrorResponse,
    JobStatus
)
from .service_coordinator import ServiceType, ServiceUnavailableError, service_coordinator
from .user_store import UserStore, _get_redis as _get_userstore_redis
from .endpoints.auth import (
    _decode_auth_token,
    _extract_bearer_token,
    _is_admin_role,
    _resolve_authenticated_user,
)
from brain_researcher.services.shared.mcp_tokens import parse_iso_datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class GPUUtilizationPoint(BaseModel):
    """Time-series GPU utilization sample."""

    model_config = ConfigDict(extra="ignore")

    timestamp: datetime
    gpu1: float = 0.0
    gpu2: float = 0.0
    gpu3: float = 0.0
    gpu4: float = 0.0


class QueueStatusModel(BaseModel):
    """Queue snapshot exposed to the dashboard."""

    model_config = ConfigDict(extra="ignore")

    running: int = 0
    queued: int = 0
    completed: int = 0
    failed: int = 0


class ProjectStatus(BaseModel):
    """Dashboard project summary."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    progress: float = 0.0
    subjects: Optional[int] = None
    timeRemaining: Optional[str] = None
    status: Optional[str] = None


class ActivityEvent(BaseModel):
    """Recent team activity entry."""

    model_config = ConfigDict(extra="allow")

    id: str
    timestamp: datetime
    user: str
    action: str
    type: str


class StorageTier(BaseModel):
    """Storage utilisation for a single tier."""

    model_config = ConfigDict(extra="allow")

    used: float = 0.0
    total: float = 0.0


class StorageMetricsModel(BaseModel):
    """Aggregate storage usage."""

    model_config = ConfigDict(extra="allow")

    primary: StorageTier = Field(default_factory=StorageTier)
    archive: StorageTier = Field(default_factory=StorageTier)
    scratch: StorageTier = Field(default_factory=StorageTier)


# Backwards compatibility alias for legacy imports/tests
StorageStatus = StorageMetricsModel


class OutputItem(BaseModel):
    """Recent analysis output."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    type: Optional[str] = None
    size: str = "N/A"
    created: datetime
    url: Optional[str] = None
    jobId: Optional[str] = None


class ClusterStatus(BaseModel):
    """Compute cluster utilisation snapshot."""

    model_config = ConfigDict(extra="allow")

    nodes: Dict[str, Any] = Field(default_factory=dict)
    cpus: Dict[str, Any] = Field(default_factory=dict)
    memory: Dict[str, Any] = Field(default_factory=dict)


class JobMetricsModel(BaseModel):
    """Aggregated job metrics."""

    model_config = ConfigDict(extra="allow")

    queue: QueueStatusModel = Field(default_factory=QueueStatusModel)
    queueSource: str = "in_memory"
    oldestPendingSeconds: Optional[float] = None
    throughputPerMinute: Optional[float] = None
    lastUpdated: datetime = Field(default_factory=datetime.utcnow)


class ResourceMetricsModel(BaseModel):
    """Compute/resource metrics."""

    model_config = ConfigDict(extra="allow")

    gpuSamples: List[GPUUtilizationPoint] = Field(default_factory=list)
    cluster: Optional[ClusterStatus] = None


class McpAdoptionUserModel(BaseModel):
    """Per-user MCP adoption snapshot for admin analytics surfaces."""

    model_config = ConfigDict(extra="ignore")

    userId: str
    username: str
    email: str
    fullName: Optional[str] = None
    role: Optional[str] = None
    createdAt: datetime
    hasAnyToken: bool = False
    hasActiveToken: bool = False
    tokenCount: int = 0
    usedMcp: bool = False
    lastUsedAt: Optional[datetime] = None
    mcpStatus: str = "no_token"


class McpAdoptionSummaryModel(BaseModel):
    """Roll-up MCP adoption counts for admin analytics."""

    model_config = ConfigDict(extra="ignore")

    totalUsers: int = 0
    usedUsers: int = 0
    unusedUsers: int = 0
    tokenNeverUsedUsers: int = 0
    noTokenUsers: int = 0
    adoptionRatePct: float = 0.0


class McpAdoptionMetricsModel(BaseModel):
    """MCP adoption snapshot for admin dashboard views."""

    model_config = ConfigDict(extra="ignore")

    generatedAt: datetime = Field(default_factory=datetime.utcnow)
    summary: McpAdoptionSummaryModel = Field(default_factory=McpAdoptionSummaryModel)
    users: List[McpAdoptionUserModel] = Field(default_factory=list)


class DashboardMetricsResponse(BaseModel):
    """Combined dashboard metrics contract."""

    model_config = ConfigDict(extra="allow")

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    jobMetrics: JobMetricsModel = Field(default_factory=JobMetricsModel)
    resourceMetrics: ResourceMetricsModel = Field(default_factory=ResourceMetricsModel)
    projects: List[ProjectStatus] = Field(default_factory=list)
    activity: List[ActivityEvent] = Field(default_factory=list)
    storageMetrics: StorageMetricsModel = Field(default_factory=StorageMetricsModel)
    outputs: List[OutputItem] = Field(default_factory=list)
    mcpAdoption: Optional[McpAdoptionMetricsModel] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


DEFAULT_STORAGE_TEMPLATE = {
    "primary": {"used": 0.0, "total": 0.0},
    "archive": {"used": 0.0, "total": 0.0},
    "scratch": {"used": 0.0, "total": 0.0},
}
MCP_ADOPTION_EMAIL_ALLOWLIST_ENV = "BR_MCP_ADOPTION_DASHBOARD_ALLOWLIST"
SEED_USER_IDS = {"user_demo", "user_admin", "user_researcher"}
SEED_USER_EMAILS = {
    "demo@brain-researcher.ai",
    "admin@brain-researcher.ai",
    "researcher@university.edu",
}
ADMIN_DASHBOARD_ROLES = {"admin", "dev"}

BR_KG_DASHBOARD_PATH = "/api/dashboard/metrics"
HTTP_TIMEOUT = httpx.Timeout(5.0, connect=2.0)

T = TypeVar("T", bound=BaseModel)
QUEUE_STATE_MAPPING = {
    JobState.RUNNING.value: "running",
    JobState.CLAIMED.value: "queued",
    JobState.QUEUED.value: "queued",
    JobState.PENDING.value: "queued",
    JobState.SUCCEEDED.value: "completed",
    JobState.FAILED.value: "failed",
    JobState.CANCELLED.value: "failed",
    JobState.TIMEOUT.value: "failed",
}


def _collect_gpu_metrics() -> List[Dict[str, Any]]:
    """Collect GPU utilization metrics from nvidia-smi if available."""
    import subprocess
    import shutil

    gpu_data = []

    # Check if nvidia-smi is available
    if not shutil.which("nvidia-smi"):
        logger.debug("nvidia-smi not available, skipping GPU metrics")
        return gpu_data

    try:
        # Query nvidia-smi for GPU utilization
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            timeout=2.0
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            gpu_metrics = {}

            for line in lines:
                parts = line.split(',')
                if len(parts) >= 4:
                    index = int(parts[0].strip())
                    util = float(parts[1].strip())
                    # Create GPU field names: gpu1, gpu2, gpu3, gpu4
                    gpu_metrics[f"gpu{index + 1}"] = util

            # Return single sample with current timestamp
            if gpu_metrics:
                gpu_data.append({
                    "timestamp": datetime.utcnow(),
                    **gpu_metrics
                })

    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError) as exc:
        logger.warning("Failed to collect GPU metrics: %s", exc)

    return gpu_data


def _get_job_store():
    """Retrieve the configured JobStore from the FastAPI app if available."""
    try:
        from .main_enhanced import app  # type: ignore

        return getattr(app.state, "job_store", None)
    except Exception:
        return None


def _collect_storage_metrics() -> Dict[str, Dict[str, float]]:
    """Collect real storage metrics from filesystem."""
    import shutil

    storage = {}

    # Define storage paths to monitor - use project data directory by default
    project_root = Path(__file__).parent.parent.parent.parent
    default_data_path = str(project_root / "data")

    storage_paths = {
        "primary": os.environ.get("PRIMARY_STORAGE_PATH", default_data_path),
        "archive": os.environ.get("ARCHIVE_STORAGE_PATH", str(project_root / "data" / "archive")),
        "scratch": os.environ.get("SCRATCH_STORAGE_PATH", "/tmp/brain_researcher"),
    }

    for tier, path in storage_paths.items():
        try:
            # Avoid mutating the filesystem during metrics collection. If the path
            # doesn't exist or isn't accessible, fall back to defaults.
            usage = shutil.disk_usage(path)
            storage[tier] = {
                "used": round(usage.used / (1024**3), 2),  # Convert to GB
                "total": round(usage.total / (1024**3), 2)
            }
        except Exception as exc:
            logger.debug("Failed to collect storage for %s (%s): %s", tier, path, exc)
            # Use defaults
            storage[tier] = DEFAULT_STORAGE_TEMPLATE[tier].copy()

    return storage


def _default_storage(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Return a storage payload that always includes the expected tiers."""
    storage = {
        tier: {"used": float(values["used"]), "total": float(values["total"])}
        for tier, values in DEFAULT_STORAGE_TEMPLATE.items()
    }

    if snapshot and isinstance(snapshot, dict):
        for tier, values in snapshot.items():
            if not isinstance(values, dict):
                continue
            used = values.get("used")
            total = values.get("total")
            storage.setdefault(tier, {"used": 0.0, "total": 0.0})
            if used is not None:
                storage[tier]["used"] = float(used)
            if total is not None:
                storage[tier]["total"] = float(total)

    return storage


def _map_state_counts_to_dashboard(state_counts: Dict[str, int]) -> Dict[str, int]:
    """Map JobState counts to dashboard queue fields."""
    snapshot = {"running": 0, "queued": 0, "completed": 0, "failed": 0}
    for raw_state, count in state_counts.items():
        dashboard_key = QUEUE_STATE_MAPPING.get(raw_state, None)
        if dashboard_key:
            snapshot[dashboard_key] = snapshot.get(dashboard_key, 0) + int(count)
    return snapshot


async def _gather_queue_status() -> Tuple[Dict[str, int], str, Optional[float], Optional[str]]:
    """Pull queue stats from the configured job store when available."""
    job_store = _get_job_store()
    oldest_age: Optional[float] = None
    source = "in_memory"
    error = None
    counts = _calculate_queue_snapshot()

    if job_store is None:
        return counts, source, oldest_age, "job_store_unavailable"

    try:
        stats = await job_store.get_queue_stats()
        state_counts = _render_state_counts(stats)
        counts = _map_state_counts_to_dashboard(state_counts)
        source = "job_store"
        oldest_age = stats.get("oldest_pending_age_sec") or stats.get("oldest_pending_age_seconds")
        if oldest_age is not None:
            oldest_age = float(oldest_age)
    except Exception as exc:
        logger.debug("Failed to load queue stats from job store: %s", exc)
        error = f"job_store_error:{exc}"

    return counts, source, oldest_age, error


def _calculate_queue_snapshot() -> Dict[str, int]:
    """Build a queue status snapshot from orchestrator job state."""
    snapshot = {"running": 0, "queued": 0, "completed": 0, "failed": 0}

    for job in list(jobs_db.values()):
        status = job.status
        if status == JobStatus.RUNNING:
            snapshot["running"] += 1
        elif status in (JobStatus.PENDING, JobStatus.QUEUED):
            snapshot["queued"] += 1
        elif status == JobStatus.COMPLETED:
            snapshot["completed"] += 1
        elif status in (JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT):
            snapshot["failed"] += 1

    return snapshot


def _format_bytes(size_bytes: Optional[int]) -> str:
    """Human readable size helper."""
    if not size_bytes or size_bytes <= 0:
        return "N/A"

    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if size < 1024 or unit == "PB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _safe_trim(value: Optional[str], max_length: int = 96) -> str:
    """Trim long text for dashboard surface."""
    if not value:
        return ""
    value = value.strip()
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def _collect_recent_outputs(limit: int = 10) -> List[Dict[str, Any]]:
    """Surface recent artifacts generated by orchestrator jobs."""
    outputs: List[Dict[str, Any]] = []

    for job in list(jobs_db.values()):
        artifacts = getattr(job, "artifacts", [])
        for artifact in artifacts:
            created_at = None
            if getattr(artifact, "provenance", None) and getattr(artifact.provenance, "timestamp", None):
                created_at = artifact.provenance.timestamp
            elif getattr(job.timing, "end_time", None):
                created_at = job.timing.end_time
            else:
                created_at = job.timing.start_time

            outputs.append(
                {
                    "id": artifact.id,
                    "name": artifact.name,
                    "type": getattr(artifact.type, "value", artifact.type),
                    "size": _format_bytes(getattr(artifact, "size_bytes", None)),
                    "created": created_at,
                    "url": artifact.url,
                    "jobId": job.id,
                }
            )

    outputs.sort(key=lambda item: item["created"] or datetime.utcnow(), reverse=True)
    return outputs[:limit]


def _build_team_activity_snapshot(limit: int = 20) -> List[Dict[str, Any]]:
    """Derive activity entries from recent jobs."""
    events: List[Dict[str, Any]] = []

    for job in list(jobs_db.values()):
        timing = getattr(job, "timing", None)
        metadata = getattr(job, "metadata", {}) or {}
        user_label = metadata.get("user_name") or metadata.get("initiated_by") or job.user_id or "System"
        title = metadata.get("title") or metadata.get("pipeline") or _safe_trim(getattr(job, "prompt", ""), 72)

        if timing and getattr(timing, "start_time", None):
            events.append(
                {
                    "id": f"{job.id}-start",
                    "timestamp": timing.start_time,
                    "user": user_label,
                    "action": f"Started {title or 'analysis job'}",
                    "type": "start",
                }
            )

        if timing and getattr(timing, "end_time", None) and job.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
        ):
            event_type = "complete" if job.status == JobStatus.COMPLETED else "error"
            status_text = (
                "Completed"
                if job.status == JobStatus.COMPLETED
                else "Ended with issues"
            )
            events.append(
                {
                    "id": f"{job.id}-{event_type}",
                    "timestamp": timing.end_time,
                    "user": user_label,
                    "action": f"{status_text} {title or 'analysis job'}",
                    "type": event_type,
                }
            )

    events.sort(key=lambda item: item["timestamp"] or datetime.utcnow(), reverse=True)
    return events[:limit]


def _normalize_gpu_series(samples: Optional[Iterable[Dict[str, Any]]]) -> List[GPUUtilizationPoint]:
    """Validate GPU samples returned by upstream services."""
    if not samples:
        return []

    normalized: List[GPUUtilizationPoint] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        try:
            normalized.append(GPUUtilizationPoint(**sample))
        except ValidationError as exc:
            logger.debug("Skipping invalid GPU sample %s: %s", sample, exc)
    return normalized


def _safe_build_list(model_cls: Type[T], raw_items: Optional[Iterable[Any]]) -> List[T]:
    """Construct a list of pydantic models while skipping invalid entries."""
    if not raw_items:
        return []

    results: List[T] = []
    for item in raw_items:
        if isinstance(item, model_cls):
            results.append(item)
            continue
        if not isinstance(item, dict):
            continue
        try:
            results.append(model_cls(**item))
        except ValidationError as exc:
            logger.debug("Skipping invalid %s entry %s: %s", model_cls.__name__, item, exc)
    return results


async def _fetch_metrics_direct() -> Dict[str, Any]:
    """Fetch dashboard metrics directly from BR-KG."""
    url = f"{BR_KG_URL.rstrip('/')}{BR_KG_DASHBOARD_PATH}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def _load_dashboard_metrics() -> tuple[Dict[str, Any], str, List[str]]:
    """Attempt to load dashboard metrics from upstream services."""
    payload: Optional[Dict[str, Any]] = None
    source = "fallback"
    errors: List[str] = []

    if service_coordinator:
        try:
            response = await service_coordinator.make_request(
                ServiceType.BR_KG, "GET", BR_KG_DASHBOARD_PATH
            )
            payload = response.json()
            source = "br_kg"
        except (ServiceUnavailableError, httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("Coordinator fetch for BR-KG dashboard metrics failed: %s", exc)
            errors.append(f"coordinator:{exc}")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Unexpected error fetching dashboard metrics via coordinator")
            errors.append("coordinator:unexpected")
    else:
        errors.append("coordinator:not_available")

    if payload is None:
        try:
            payload = await _fetch_metrics_direct()
            source = "br_kg"
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("Direct fetch for BR-KG dashboard metrics failed: %s", exc)
            errors.append(f"direct:{exc}")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Unexpected error fetching BR-KG metrics directly")
            errors.append("direct:unexpected")

    if payload is None:
        payload = _build_fallback_metrics()
        source = "fallback"

    return payload, source, errors


def _load_mcp_adoption_email_allowlist() -> set[str]:
    raw = str(os.getenv(MCP_ADOPTION_EMAIL_ALLOWLIST_ENV) or "").strip()
    if not raw:
        return set()
    normalized = raw.replace(";", ",").replace("\n", ",")
    return {
        email.strip().lower()
        for email in normalized.split(",")
        if email and email.strip()
    }


async def _should_include_mcp_adoption(request: Request | None) -> bool:
    """Return True when the caller is allowed to view admin-only MCP adoption data."""
    if request is None:
        return False

    allowlisted_emails = _load_mcp_adoption_email_allowlist()
    try:
        token = _extract_bearer_token(request)
        payload = _decode_auth_token(token)
        role = str(payload.get("role") or "").strip().lower()
        if role in ADMIN_DASHBOARD_ROLES:
            return True
        email = str(payload.get("email") or "").strip().lower()
        if email and email in allowlisted_emails:
            return True
    except Exception:
        pass

    try:
        user, _payload = await _resolve_authenticated_user(request)
    except Exception:
        return False

    email = str(getattr(user, "email", "") or "").strip().lower()
    return _is_admin_role(getattr(user, "role", None)) or (
        bool(email) and email in allowlisted_emails
    )


async def _build_mcp_adoption_metrics() -> McpAdoptionMetricsModel:
    """Build per-user MCP adoption analytics from Redis-backed user/token records."""
    users = await UserStore.list_all()
    non_seed_users = [
        user
        for user in users
        if getattr(user, "id", None) not in SEED_USER_IDS
        and str(getattr(user, "email", "") or "").strip().lower() not in SEED_USER_EMAILS
    ]

    token_records_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    active_token_users: set[str] = set()
    redis_client = await _get_userstore_redis()
    if redis_client is not None:
        async for key in redis_client.scan_iter(match="mcp_token:kid:*"):
            record = await redis_client.hgetall(key)
            user_id = str(record.get("user_id") or "").strip()
            if user_id:
                token_records_by_user[user_id].append(record)

        async for key in redis_client.scan_iter(match="mcp_token:user:*"):
            user_id = str(key).rsplit(":", 1)[-1].strip()
            if user_id:
                active_token_users.add(user_id)

    adoption_users: list[McpAdoptionUserModel] = []
    used_users = 0
    token_never_used_users = 0
    no_token_users = 0

    for user in non_seed_users:
        records = token_records_by_user.get(user.id, [])
        token_count = len(records)
        last_used_candidates = [
            parse_iso_datetime(str(record.get("last_used_at") or "").strip())
            for record in records
            if str(record.get("last_used_at") or "").strip()
        ]
        last_used_candidates = [value for value in last_used_candidates if value is not None]
        last_used_at = max(last_used_candidates) if last_used_candidates else None
        used_mcp = last_used_at is not None

        if used_mcp:
            used_users += 1
            mcp_status = "used"
        elif token_count > 0:
            token_never_used_users += 1
            mcp_status = "token_never_used"
        else:
            no_token_users += 1
            mcp_status = "no_token"

        role_value = getattr(user, "role", None)
        role = role_value.value if hasattr(role_value, "value") else role_value
        adoption_users.append(
            McpAdoptionUserModel(
                userId=user.id,
                username=user.username,
                email=user.email,
                fullName=getattr(user, "full_name", None),
                role=str(role) if role is not None else None,
                createdAt=user.created_at,
                hasAnyToken=token_count > 0,
                hasActiveToken=user.id in active_token_users,
                tokenCount=token_count,
                usedMcp=used_mcp,
                lastUsedAt=last_used_at,
                mcpStatus=mcp_status,
            )
        )

    adoption_users.sort(
        key=lambda item: (
            2 if item.mcpStatus == "no_token" else 1 if item.mcpStatus == "token_never_used" else 0,
            item.createdAt.timestamp(),
        ),
        reverse=True,
    )

    total_users = len(adoption_users)
    unused_users = total_users - used_users
    adoption_rate = round((used_users / total_users) * 100, 1) if total_users else 0.0

    return McpAdoptionMetricsModel(
        summary=McpAdoptionSummaryModel(
            totalUsers=total_users,
            usedUsers=used_users,
            unusedUsers=unused_users,
            tokenNeverUsedUsers=token_never_used_users,
            noTokenUsers=no_token_users,
            adoptionRatePct=adoption_rate,
        ),
        users=adoption_users,
    )


async def build_dashboard_metrics_response(
    request: Request | None = None,
) -> DashboardMetricsResponse:
    """Construct the dashboard metrics payload consumed by HTTP and WebSocket clients."""
    payload, source, errors = await _load_dashboard_metrics()

    # Collect real GPU metrics from nvidia-smi
    gpu_samples = _normalize_gpu_series(_collect_gpu_metrics())

    queue_counts, queue_source, oldest_age, queue_error = await _gather_queue_status()

    # Collect real storage metrics from filesystem
    storage_data = _collect_storage_metrics()

    derived_activity = _build_team_activity_snapshot()
    activity_source = derived_activity if derived_activity else payload.get("teamActivity")

    derived_outputs = _collect_recent_outputs()
    output_source = derived_outputs if derived_outputs else payload.get("outputs")

    projects = _safe_build_list(ProjectStatus, payload.get("projects"))
    activity_events = _safe_build_list(ActivityEvent, activity_source)
    outputs = _safe_build_list(OutputItem, output_source)

    cluster_status = None
    raw_cluster = payload.get("clusterStatus")
    if isinstance(raw_cluster, dict):
        try:
            cluster_status = ClusterStatus(**raw_cluster)
        except ValidationError as exc:
            logger.debug("Ignoring invalid cluster status payload: %s", exc)

    job_metrics = JobMetricsModel(
        queue=QueueStatusModel(**queue_counts),
        queueSource=queue_source,
        oldestPendingSeconds=oldest_age,
        lastUpdated=datetime.utcnow(),
    )

    resource_metrics = ResourceMetricsModel(
        gpuSamples=gpu_samples,
        cluster=cluster_status,
    )

    storage_metrics = StorageMetricsModel(**storage_data)

    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "source": source,
            "fetched_at": datetime.utcnow().isoformat(),
        }
    )
    normalized_errors = list(errors or [])
    if queue_error:
        normalized_errors.append(queue_error)
    if normalized_errors:
        metadata["errors"] = normalized_errors
        metadata["status"] = "degraded"
    else:
        metadata["status"] = "healthy"

    mcp_adoption = None
    if await _should_include_mcp_adoption(request):
        try:
            mcp_adoption = await _build_mcp_adoption_metrics()
        except Exception as exc:
            logger.warning("Failed to build MCP adoption metrics: %s", exc)
            normalized_errors = list(metadata.get("errors") or [])
            normalized_errors.append("mcp_adoption_unavailable")
            metadata["errors"] = normalized_errors
            metadata["status"] = "degraded"

    return DashboardMetricsResponse(
        timestamp=payload.get("timestamp", datetime.utcnow()),
        jobMetrics=job_metrics,
        resourceMetrics=resource_metrics,
        projects=projects,
        activity=activity_events,
        storageMetrics=storage_metrics,
        outputs=outputs,
        mcpAdoption=mcp_adoption,
        metadata=metadata,
    )


@router.get("/metrics", response_model=DashboardMetricsResponse)
async def get_dashboard_metrics(request: Request) -> DashboardMetricsResponse:
    """Expose aggregated dashboard metrics for the UI."""
    return await build_dashboard_metrics_response(request)


def _build_fallback_metrics() -> Dict[str, Any]:
    """Generate a minimal metrics payload from orchestrator state."""
    return {
        "timestamp": datetime.utcnow(),
        "jobMetrics": {
            "queue": _calculate_queue_snapshot(),
            "queueSource": "fallback",
            "oldestPendingSeconds": None,
        },
        "resourceMetrics": {
            "gpuSamples": _collect_gpu_metrics(),
            "cluster": None,
        },
        "projects": [],
        "activity": _build_team_activity_snapshot(),
        "storageMetrics": _collect_storage_metrics(),
        "outputs": _collect_recent_outputs(),
        "metadata": {
            "source": "fallback",
            "status": "degraded",
            "errors": ["br_kg_unavailable"],
        },
    }

# Storage configuration
# Persist layouts and preferences on the shared PVC by default (mounted at
# /app/data/shared in the Helm chart). Allow overrides for local/dev.
DASHBOARD_DATA_DIR = Path(
    os.getenv("BR_DASHBOARD_DATA_DIR", "/app/data/shared/dashboards")
).expanduser()
try:
    DASHBOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception as exc:
    logger.warning(
        "Dashboard data dir is not writable (%s): %s; falling back to /tmp",
        DASHBOARD_DATA_DIR,
        exc,
    )
    try:
        DASHBOARD_DATA_DIR = Path("/tmp/brain_researcher/dashboards")
        DASHBOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc2:
        import tempfile

        logger.warning(
            "Fallback /tmp also not writable (%s); using temp dir: %s",
            exc2,
            tempfile.gettempdir(),
        )
        DASHBOARD_DATA_DIR = Path(tempfile.mkdtemp(prefix="br_dashboards_"))

def get_layout_file_path(layout_id: str) -> Path:
    """Get the file path for a layout."""
    return DASHBOARD_DATA_DIR / f"{layout_id}.json"

def load_layout(layout_id: str) -> Optional[DashboardLayoutModel]:
    """Load a layout from disk."""
    file_path = get_layout_file_path(layout_id)
    if not file_path.exists():
        return None

    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            # Convert datetime strings back to datetime objects
            for widget in data.get('widgets', []):
                if 'created_at' in widget:
                    widget['created_at'] = datetime.fromisoformat(widget['created_at'].replace('Z', '+00:00'))
                if 'updated_at' in widget:
                    widget['updated_at'] = datetime.fromisoformat(widget['updated_at'].replace('Z', '+00:00'))
            if 'created_at' in data:
                data['created_at'] = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00'))
            if 'updated_at' in data:
                data['updated_at'] = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))

            return DashboardLayoutModel(**data)
    except (json.JSONDecodeError, ValidationError, ValueError) as e:
        print(f"Error loading layout {layout_id}: {e}")
        return None

def save_layout(layout: DashboardLayoutModel) -> None:
    """Save a layout to disk."""
    file_path = get_layout_file_path(layout.id)

    # Convert to dict and handle datetime serialization
    data = layout.model_dump()

    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def list_all_layouts() -> List[DashboardLayoutModel]:
    """Load all layouts from disk."""
    layouts = []

    for file_path in DASHBOARD_DATA_DIR.glob("*.json"):
        layout_id = file_path.stem
        layout = load_layout(layout_id)
        if layout:
            layouts.append(layout)

    # Sort by updated_at desc
    layouts.sort(key=lambda l: l.updated_at, reverse=True)
    return layouts

def create_default_layout() -> DashboardLayoutModel:
    """Create a default dashboard layout."""
    from datetime import datetime

    default_layout = DashboardLayoutModel(
        id="default",
        name="Default Dashboard",
        description="Default layout with essential widgets",
        widgets=[
            {
                "id": "analysis_queue",
                "type": "analysis_queue",
                "title": "Analysis Queue",
                "position": {"x": 0, "y": 0, "w": 6, "h": 8, "minW": 4, "minH": 6},
                "config": {"showHeader": True, "refreshInterval": 5000},
                "visible": True,
                "locked": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "id": "recent_results",
                "type": "recent_results",
                "title": "Recent Results",
                "position": {"x": 6, "y": 0, "w": 6, "h": 8, "minW": 4, "minH": 6},
                "config": {"showHeader": True, "refreshInterval": 10000},
                "visible": True,
                "locked": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "id": "resource_usage",
                "type": "resource_usage",
                "title": "Resource Usage",
                "position": {"x": 0, "y": 8, "w": 8, "h": 6, "minW": 6, "minH": 4},
                "config": {"showHeader": True, "refreshInterval": 3000},
                "visible": True,
                "locked": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "id": "quick_actions",
                "type": "quick_actions",
                "title": "Quick Actions",
                "position": {"x": 8, "y": 8, "w": 4, "h": 6, "minW": 3, "minH": 4},
                "config": {"showHeader": True},
                "visible": True,
                "locked": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        ],
        breakpoints={"lg": [], "md": [], "sm": [], "xs": []},
        isDefault=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    return default_layout

@router.get(
    "/layouts",
    response_model=DashboardLayoutListResponse,
    summary="List dashboard layouts",
    description="Get all available dashboard layouts for the current user"
)
async def list_layouts(request: Request) -> DashboardLayoutListResponse:
    """List all dashboard layouts."""
    try:
        layouts = list_all_layouts()

        # Create default layout if none exist
        if not layouts:
            default_layout = create_default_layout()
            save_layout(default_layout)
            layouts = [default_layout]

        # Find default layout
        default_layout_id = None
        for layout in layouts:
            if layout.isDefault:
                default_layout_id = layout.id
                break

        return DashboardLayoutListResponse(
            layouts=layouts,
            total_count=len(layouts),
            user_layouts_count=len([l for l in layouts if not l.isDefault]),
            default_layout_id=default_layout_id
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to list dashboard layouts: {str(e)}"
            ).error
        )

@router.get(
    "/layouts/{layout_id}",
    response_model=DashboardLayoutModel,
    summary="Get dashboard layout",
    description="Get a specific dashboard layout by ID"
)
async def get_layout(layout_id: str, request: Request) -> DashboardLayoutModel:
    """Get a specific dashboard layout."""
    try:
        layout = load_layout(layout_id)
        if not layout:
            # Try to create default layout if requesting default
            if layout_id == "default":
                layout = create_default_layout()
                save_layout(layout)
            else:
                raise HTTPException(
                    status_code=404,
                    detail=ErrorResponse.create(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Dashboard layout '{layout_id}' not found"
                    ).error
                )

        return layout

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to get dashboard layout: {str(e)}"
            ).error
        )

@router.post(
    "/layouts",
    response_model=DashboardLayoutModel,
    summary="Create dashboard layout",
    description="Create a new dashboard layout"
)
async def create_layout(
    layout_request: DashboardLayoutRequest,
    request: Request
) -> DashboardLayoutModel:
    """Create a new dashboard layout."""
    try:
        # Generate unique ID
        layout_id = f"layout_{uuid.uuid4().hex[:8]}"

        # Create layout model
        layout = DashboardLayoutModel(
            id=layout_id,
            name=layout_request.name,
            description=layout_request.description,
            widgets=layout_request.widgets,
            breakpoints=layout_request.breakpoints,
            isDefault=layout_request.isDefault,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        # If this is set as default, unset other defaults
        if layout.isDefault:
            layouts = list_all_layouts()
            for existing_layout in layouts:
                if existing_layout.isDefault:
                    existing_layout.isDefault = False
                    save_layout(existing_layout)

        save_layout(layout)
        return layout

    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse.create(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid layout data",
                details={"errors": str(e)}
            ).error
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to create dashboard layout: {str(e)}"
            ).error
        )

@router.put(
    "/layouts/{layout_id}",
    response_model=DashboardLayoutModel,
    summary="Update dashboard layout",
    description="Update an existing dashboard layout"
)
async def update_layout(
    layout_id: str,
    layout_request: DashboardLayoutRequest,
    request: Request
) -> DashboardLayoutModel:
    """Update an existing dashboard layout."""
    try:
        existing_layout = load_layout(layout_id)
        if not existing_layout:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse.create(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Dashboard layout '{layout_id}' not found"
                ).error
            )

        # Update layout
        updated_layout = DashboardLayoutModel(
            id=layout_id,
            name=layout_request.name,
            description=layout_request.description,
            widgets=layout_request.widgets,
            breakpoints=layout_request.breakpoints,
            isDefault=layout_request.isDefault,
            created_at=existing_layout.created_at,
            updated_at=datetime.utcnow()
        )

        # If this is set as default, unset other defaults
        if updated_layout.isDefault and not existing_layout.isDefault:
            layouts = list_all_layouts()
            for layout in layouts:
                if layout.isDefault and layout.id != layout_id:
                    layout.isDefault = False
                    save_layout(layout)

        save_layout(updated_layout)
        return updated_layout

    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse.create(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid layout data",
                details={"errors": str(e)}
            ).error
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to update dashboard layout: {str(e)}"
            ).error
        )

@router.delete(
    "/layouts/{layout_id}",
    summary="Delete dashboard layout",
    description="Delete a dashboard layout"
)
async def delete_layout(layout_id: str, request: Request) -> Dict[str, str]:
    """Delete a dashboard layout."""
    try:
        if layout_id == "default":
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse.create(
                    code=ErrorCode.INVALID_PARAMETER,
                    message="Cannot delete the default layout"
                ).error
            )

        layout = load_layout(layout_id)
        if not layout:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse.create(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Dashboard layout '{layout_id}' not found"
                ).error
            )

        # Delete file
        file_path = get_layout_file_path(layout_id)
        file_path.unlink()

        return {"message": f"Layout '{layout_id}' deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to delete dashboard layout: {str(e)}"
            ).error
        )

@router.post(
    "/layouts/{layout_id}/export",
    response_model=DashboardExportData,
    summary="Export dashboard layout",
    description="Export a dashboard layout for sharing or backup"
)
async def export_layout(layout_id: str, request: Request) -> DashboardExportData:
    """Export a dashboard layout."""
    try:
        layout = load_layout(layout_id)
        if not layout:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse.create(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Dashboard layout '{layout_id}' not found"
                ).error
            )

        # Create export data (remove ID for import compatibility)
        export_layout = layout.model_copy()
        export_layout.id = ""  # Clear ID for import

        export_data = DashboardExportData(
            layout=export_layout,
            metadata={
                "exported_from": "Brain Researcher Dashboard",
                "original_id": layout_id,
                "original_name": layout.name
            }
        )

        return export_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to export dashboard layout: {str(e)}"
            ).error
        )

@router.post(
    "/layouts/import",
    response_model=DashboardLayoutModel,
    summary="Import dashboard layout",
    description="Import a dashboard layout from export data"
)
async def import_layout(
    export_data: DashboardExportData,
    request: Request
) -> DashboardLayoutModel:
    """Import a dashboard layout."""
    try:
        # Generate new ID and set import name
        import_id = f"layout_{uuid.uuid4().hex[:8]}"
        imported_name = f"{export_data.layout.name} (Imported)"

        # Create new layout
        imported_layout = DashboardLayoutModel(
            id=import_id,
            name=imported_name,
            description=export_data.layout.description,
            widgets=[
                widget.model_copy(update={
                    "id": f"widget_{uuid.uuid4().hex[:8]}",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
                for widget in export_data.layout.widgets
            ],
            breakpoints=export_data.layout.breakpoints,
            isDefault=False,  # Never import as default
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        save_layout(imported_layout)
        return imported_layout

    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse.create(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid import data",
                details={"errors": str(e)}
            ).error
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to import dashboard layout: {str(e)}"
            ).error
        )
