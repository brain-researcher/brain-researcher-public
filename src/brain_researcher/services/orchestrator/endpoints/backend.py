"""REST API endpoints for multi-backend job execution."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from brain_researcher.services.agent.backends import (
    AWSBatchBackend,
    BackendSelector,
    BackendSubmissionError,
    BackendUnavailableError,
    JobNotFoundError,
    JobSpecification,
    KubernetesBackend,
    ResourceRequirements,
    SelectionStrategy,
    SLURMBackend,
)

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/backends", tags=["backends"])

# Global backend selector instance
backend_selector: BackendSelector | None = None


# Pydantic models for API
class ResourceRequirementsModel(BaseModel):
    """Resource requirements for job execution."""

    cpu: float = Field(default=1.0, ge=0.1, le=1024, description="CPU cores required")
    memory_gb: float = Field(default=4.0, ge=0.1, le=2048, description="Memory in GB")
    gpu: int = Field(default=0, ge=0, le=16, description="Number of GPUs")
    storage_gb: float = Field(
        default=10.0, ge=1.0, le=10240, description="Storage in GB"
    )
    walltime_minutes: int = Field(
        default=60, ge=1, le=10080, description="Walltime in minutes"
    )
    node_count: int = Field(default=1, ge=1, le=1000, description="Number of nodes")


class JobSpecificationModel(BaseModel):
    """Job specification for backend execution."""

    name: str = Field(..., min_length=1, max_length=100, description="Job name")
    command: str = Field(..., min_length=1, description="Command to execute")
    image: str = Field(..., description="Container image")
    environment: dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    resources: ResourceRequirementsModel = Field(
        ..., description="Resource requirements"
    )
    working_dir: str = Field(default="/workspace", description="Working directory")
    output_path: str = Field(default="/outputs", description="Output path")
    input_files: list[str] = Field(default_factory=list, description="Input file paths")
    output_files: list[str] = Field(
        default_factory=list, description="Output file paths"
    )


class JobSubmissionModel(BaseModel):
    """Job submission request."""

    job_spec: JobSpecificationModel = Field(..., description="Job specification")
    backend: str | None = Field(None, description="Preferred backend name")
    strategy: SelectionStrategy | None = Field(None, description="Selection strategy")
    priority: int | None = Field(None, ge=1, le=10, description="Job priority (1-10)")


class JobSubmissionResponse(BaseModel):
    """Job submission response."""

    job_id: str = Field(..., description="Unique job identifier")
    backend: str = Field(..., description="Selected backend name")
    status: str = Field(..., description="Initial job status")
    estimated_queue_time: int = Field(
        ..., description="Estimated queue time in minutes"
    )
    estimated_cost: float = Field(..., description="Estimated cost in USD")


class JobStatusResponse(BaseModel):
    """Job status response."""

    job_id: str
    backend: str
    state: str
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float | None = None
    message: str | None = None
    exit_code: int | None = None
    resource_usage: dict[str, Any] | None = None


class BackendStatusResponse(BaseModel):
    """Backend status response."""

    name: str
    type: str
    healthy: bool
    capacity: dict[str, Any] | None = None
    usage_count: int | None = None
    error: str | None = None


class BackendListResponse(BaseModel):
    """List of available backends."""

    backends: list[BackendStatusResponse]
    total_count: int


# Dependency to get backend selector
async def get_backend_selector() -> BackendSelector:
    """Get the global backend selector instance."""
    global backend_selector
    if backend_selector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backend selector not initialized",
        )
    return backend_selector


def initialize_backends(config: dict[str, Any]) -> BackendSelector:
    """Initialize backends from configuration.

    Args:
        config: Configuration dictionary with backend settings

    Returns:
        Initialized backend selector
    """
    global backend_selector

    backends = []
    backend_configs = config.get("backends", {})

    # Initialize Kubernetes backend
    if "kubernetes" in backend_configs:
        k8s_config = backend_configs["kubernetes"]
        if k8s_config.get("enabled", False):
            try:
                backend = KubernetesBackend("kubernetes", k8s_config)
                backends.append(backend)
                logger.info("Initialized Kubernetes backend")
            except Exception as e:
                logger.error(f"Failed to initialize Kubernetes backend: {e}")

    # Initialize SLURM backend
    if "slurm" in backend_configs:
        slurm_config = backend_configs["slurm"]
        if slurm_config.get("enabled", False):
            try:
                backend = SLURMBackend("slurm", slurm_config)
                backends.append(backend)
                logger.info("Initialized SLURM backend")
            except Exception as e:
                logger.error(f"Failed to initialize SLURM backend: {e}")

    # Initialize AWS Batch backend
    if "aws_batch" in backend_configs:
        aws_config = backend_configs["aws_batch"]
        if aws_config.get("enabled", False):
            try:
                backend = AWSBatchBackend("aws_batch", aws_config)
                backends.append(backend)
                logger.info("Initialized AWS Batch backend")
            except Exception as e:
                logger.error(f"Failed to initialize AWS Batch backend: {e}")

    if not backends:
        logger.warning("No backends initialized")

    # Create backend selector
    strategy = SelectionStrategy(config.get("default_strategy", "most_available"))
    preferred_order = config.get("preferred_order", [])

    backend_selector = BackendSelector(backends, strategy, preferred_order)

    logger.info(f"Initialized backend selector with {len(backends)} backends")
    return backend_selector


@router.get("/available", response_model=BackendListResponse)
async def list_available_backends(
    selector: BackendSelector = Depends(get_backend_selector),
) -> BackendListResponse:
    """Get list of available backends and their status."""
    try:
        backend_status = await selector.get_backend_status()

        backends = []
        for _name, status in backend_status.items():
            backends.append(BackendStatusResponse(**status))

        return BackendListResponse(backends=backends, total_count=len(backends))

    except Exception as e:
        logger.error(f"Error listing backends: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list backends: {str(e)}",
        )


@router.post("/submit", response_model=JobSubmissionResponse)
async def submit_job(
    submission: JobSubmissionModel,
    background_tasks: BackgroundTasks,
    selector: BackendSelector = Depends(get_backend_selector),
) -> JobSubmissionResponse:
    """Submit a job for execution on selected backend."""
    try:
        # Convert Pydantic models to domain objects
        resources = ResourceRequirements(
            cpu=submission.job_spec.resources.cpu,
            memory_gb=submission.job_spec.resources.memory_gb,
            gpu=submission.job_spec.resources.gpu,
            storage_gb=submission.job_spec.resources.storage_gb,
            walltime_minutes=submission.job_spec.resources.walltime_minutes,
            node_count=submission.job_spec.resources.node_count,
        )

        job_spec = JobSpecification(
            name=submission.job_spec.name,
            command=submission.job_spec.command,
            image=submission.job_spec.image,
            environment=submission.job_spec.environment,
            resources=resources,
            working_dir=submission.job_spec.working_dir,
            output_path=submission.job_spec.output_path,
            input_files=submission.job_spec.input_files,
            output_files=submission.job_spec.output_files,
        )

        # Select backend
        if submission.backend:
            # Use specific backend
            backend = selector.get_backend_by_name(submission.backend)
            if not backend:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Backend '{submission.backend}' not found",
                )
        else:
            # Use selector to choose best backend
            backend = await selector.select_with_failover(
                resources, strategy=submission.strategy
            )

        # Get estimates before submission
        queue_time = backend.estimate_queue_time(resources)
        cost = backend.get_cost_estimate(resources)

        # Submit job
        job_id = await backend.submit_job(job_spec)

        logger.info(f"Submitted job {job_id} to backend {backend.name}")

        return JobSubmissionResponse(
            job_id=job_id,
            backend=backend.name,
            status="pending",
            estimated_queue_time=queue_time,
            estimated_cost=cost,
        )

    except BackendUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except BackendSubmissionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit job: {str(e)}",
        )


@router.get("/job/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str, selector: BackendSelector = Depends(get_backend_selector)
) -> JobStatusResponse:
    """Get status of a specific job."""
    try:
        # Find which backend has this job
        backend = None
        for _backend_name, backend_instance in selector.backends.items():
            try:
                job_status = await backend_instance.get_job_status(job_id)
                backend = backend_instance
                break
            except JobNotFoundError:
                continue

        if not backend:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found in any backend",
            )

        job_status = await backend.get_job_status(job_id)

        return JobStatusResponse(
            job_id=job_status.job_id,
            backend=job_status.backend,
            state=job_status.state.value,
            submitted_at=job_status.submitted_at,
            started_at=job_status.started_at,
            completed_at=job_status.completed_at,
            progress=job_status.progress,
            message=job_status.message,
            exit_code=job_status.exit_code,
            resource_usage=job_status.resource_usage,
        )

    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job status: {str(e)}",
        )


@router.delete("/job/{job_id}")
async def cancel_job(
    job_id: str, selector: BackendSelector = Depends(get_backend_selector)
) -> dict[str, Any]:
    """Cancel a running job."""
    try:
        # Find which backend has this job
        backend = None
        for _backend_name, backend_instance in selector.backends.items():
            try:
                await backend_instance.get_job_status(job_id)
                backend = backend_instance
                break
            except JobNotFoundError:
                continue

        if not backend:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found in any backend",
            )

        success = await backend.cancel_job(job_id)

        if success:
            logger.info(f"Cancelled job {job_id} on backend {backend.name}")
            return {"message": f"Job {job_id} cancelled successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to cancel job {job_id}",
            )

    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Error cancelling job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel job: {str(e)}",
        )


@router.get("/job/{job_id}/logs")
async def get_job_logs(
    job_id: str, selector: BackendSelector = Depends(get_backend_selector)
) -> dict[str, str]:
    """Get logs for a specific job."""
    try:
        # Find which backend has this job
        backend = None
        for _backend_name, backend_instance in selector.backends.items():
            try:
                await backend_instance.get_job_status(job_id)
                backend = backend_instance
                break
            except JobNotFoundError:
                continue

        if not backend:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found in any backend",
            )

        logs = await backend.get_logs(job_id)

        return {"job_id": job_id, "logs": logs}

    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Error getting job logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job logs: {str(e)}",
        )


@router.post("/health-check")
async def check_backend_health(
    selector: BackendSelector = Depends(get_backend_selector),
) -> dict[str, Any]:
    """Perform health check on all backends."""
    try:
        # Clear cache to force fresh health checks
        selector.clear_cache()

        backend_status = await selector.get_backend_status()

        healthy_count = sum(
            1 for status in backend_status.values() if status.get("healthy", False)
        )

        return {
            "overall_health": healthy_count > 0,
            "healthy_backends": healthy_count,
            "total_backends": len(backend_status),
            "backends": backend_status,
        }

    except Exception as e:
        logger.error(f"Error checking backend health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check backend health: {str(e)}",
        )


@router.post("/cache/clear")
async def clear_cache(
    selector: BackendSelector = Depends(get_backend_selector),
) -> dict[str, str]:
    """Clear backend selector cache."""
    try:
        selector.clear_cache()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}",
        )
