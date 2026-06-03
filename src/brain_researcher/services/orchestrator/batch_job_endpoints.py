"""
Batch job management endpoints with advanced features including dependency tracking,
retry mechanisms, and cancellation with cleanup.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel

from .enhanced_job_manager import (
    enhanced_job_manager, BatchJobRequest, JobCancellationRequest,
    RetryConfig, DependencyRule, JobCleanupAction
)
from .websocket_endpoints import broadcast_job_update, JobUpdateMessage
from .models import JobStatus

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/batch-jobs", tags=["batch-jobs"])


# ============================================================================
# Request/Response Models
# ============================================================================

class BatchJobResponse(BaseModel):
    """Response for batch job creation."""
    batch_id: str
    job_ids: List[str]
    total_jobs: int
    dependency_mode: str
    estimated_completion_minutes: Optional[int] = None


class JobRetryRequest(BaseModel):
    """Request to retry a job."""
    job_id: str
    force: bool = False
    retry_config: Optional[RetryConfig] = None


class JobDependencyRequest(BaseModel):
    """Request to add dependencies to a job."""
    job_id: str
    dependencies: List[DependencyRule]


# ============================================================================
# Batch Job Management Endpoints
# ============================================================================

@router.post("/create", response_model=BatchJobResponse)
async def create_batch_jobs(
    request: BatchJobRequest,
    background_tasks: BackgroundTasks
):
    """Create a batch of jobs with dependency management."""
    try:
        result = await enhanced_job_manager.create_batch_jobs(request)

        # Estimate completion time based on job complexity
        estimated_minutes = len(result["job_ids"]) * 2  # 2 minutes per job estimate

        logger.info(f"Created batch {result['batch_id']} with {result['total_jobs']} jobs")

        return BatchJobResponse(
            batch_id=result["batch_id"],
            job_ids=result["job_ids"],
            total_jobs=result["total_jobs"],
            dependency_mode=result["dependency_mode"],
            estimated_completion_minutes=estimated_minutes
        )

    except Exception as e:
        logger.error(f"Failed to create batch jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch creation failed: {str(e)}")


@router.get("/{batch_id}/status")
async def get_batch_status(batch_id: str):
    """Get status of a batch job."""
    batch_status = enhanced_job_manager.get_batch_status(batch_id)

    if not batch_status:
        raise HTTPException(status_code=404, detail="Batch not found")

    return batch_status


@router.post("/{batch_id}/cancel")
async def cancel_batch_jobs(
    batch_id: str,
    reason: str = "Batch cancelled by user",
    cancel_running_jobs: bool = True,
    cleanup_actions: List[JobCleanupAction] = []
):
    """Cancel all jobs in a batch."""
    batch_status = enhanced_job_manager.get_batch_status(batch_id)

    if not batch_status:
        raise HTTPException(status_code=404, detail="Batch not found")

    cancelled_jobs = []
    failed_cancellations = []

    for job_id in batch_status["job_ids"]:
        try:
            job = enhanced_job_manager.get_job(job_id)
            if job and (cancel_running_jobs or job["status"] not in [JobStatus.RUNNING]):
                cancellation_request = JobCancellationRequest(
                    job_id=job_id,
                    reason=f"Batch {batch_id} cancelled: {reason}",
                    cleanup_actions=cleanup_actions,
                    cancel_dependent_jobs=True
                )

                result = await enhanced_job_manager.cancel_job(cancellation_request)
                if result["status"] == "cancelled":
                    cancelled_jobs.append(job_id)
                else:
                    failed_cancellations.append({"job_id": job_id, "reason": result.get("reason", "Unknown")})

        except Exception as e:
            failed_cancellations.append({"job_id": job_id, "reason": str(e)})

    return {
        "batch_id": batch_id,
        "cancelled_jobs": cancelled_jobs,
        "failed_cancellations": failed_cancellations,
        "total_cancelled": len(cancelled_jobs),
        "total_failed": len(failed_cancellations)
    }


# ============================================================================
# Individual Job Management Endpoints
# ============================================================================

@router.post("/jobs/{job_id}/cancel")
async def cancel_job_enhanced(
    job_id: str,
    request: JobCancellationRequest
):
    """Cancel a job with enhanced cleanup options."""
    try:
        result = await enhanced_job_manager.cancel_job(request)
        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Cancellation failed: {str(e)}")


@router.post("/jobs/{job_id}/retry")
async def retry_job_enhanced(request: JobRetryRequest):
    """Retry a failed job with exponential backoff."""
    try:
        # Update retry config if provided
        if request.retry_config:
            enhanced_job_manager.retry_configs[request.job_id] = request.retry_config

        result = await enhanced_job_manager.retry_job(request.job_id, request.force)
        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to retry job {request.job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Retry failed: {str(e)}")


@router.post("/jobs/{job_id}/dependencies")
async def add_job_dependencies(request: JobDependencyRequest):
    """Add dependencies to an existing job."""
    job = enhanced_job_manager.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Add dependencies
    existing_deps = enhanced_job_manager.job_dependencies.get(request.job_id, [])
    enhanced_job_manager.job_dependencies[request.job_id] = existing_deps + request.dependencies

    # Update dependent job tracking
    for dep in request.dependencies:
        enhanced_job_manager.dependent_jobs[dep.depends_on_job_id].add(request.job_id)

    return {
        "job_id": request.job_id,
        "dependencies_added": len(request.dependencies),
        "total_dependencies": len(enhanced_job_manager.job_dependencies[request.job_id])
    }


@router.get("/jobs/{job_id}/dependencies")
async def get_job_dependencies(job_id: str):
    """Get dependencies for a job."""
    job = enhanced_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    dependencies = enhanced_job_manager.job_dependencies.get(job_id, [])
    dependents = list(enhanced_job_manager.dependent_jobs.get(job_id, set()))

    return {
        "job_id": job_id,
        "dependencies": [dep.model_dump() for dep in dependencies],
        "dependent_jobs": dependents,
        "dependency_count": len(dependencies),
        "dependent_count": len(dependents)
    }


# ============================================================================
# Job Queue Management
# ============================================================================

@router.get("/queue/status")
async def get_queue_status():
    """Get detailed job queue status."""
    stats = enhanced_job_manager.get_statistics()

    # Get jobs by status
    jobs_by_status = {}
    for job_id, job in enhanced_job_manager.jobs.items():
        status = job["status"]
        if status not in jobs_by_status:
            jobs_by_status[status] = []
        jobs_by_status[status].append({
            "job_id": job_id,
            "created_at": job["created_at"].isoformat(),
            "priority": job.get("priority", "normal"),
            "retry_count": job.get("retry_count", 0)
        })

    return {
        "statistics": stats,
        "jobs_by_status": jobs_by_status,
        "scheduled_retries": {
            job_id: retry_time.isoformat()
            for job_id, retry_time in enhanced_job_manager.retry_schedules.items()
        },
        "active_cleanup_tasks": list(enhanced_job_manager.cleanup_tasks.keys())
    }


@router.get("/jobs/{job_id}/detailed")
async def get_job_detailed(job_id: str):
    """Get detailed job information including dependencies and retry history."""
    job = enhanced_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    dependencies = enhanced_job_manager.job_dependencies.get(job_id, [])
    dependents = list(enhanced_job_manager.dependent_jobs.get(job_id, set()))
    retry_config = enhanced_job_manager.retry_configs.get(job_id)
    next_retry = enhanced_job_manager.retry_schedules.get(job_id)

    return {
        "job": job,
        "dependencies": [dep.model_dump() for dep in dependencies],
        "dependent_jobs": dependents,
        "retry_config": retry_config.model_dump() if retry_config else None,
        "next_retry_at": next_retry.isoformat() if next_retry else None,
        "has_active_cleanup": job_id in enhanced_job_manager.cleanup_tasks
    }


# ============================================================================
# Statistics and Monitoring
# ============================================================================

@router.get("/statistics")
async def get_enhanced_statistics():
    """Get comprehensive job management statistics."""
    stats = enhanced_job_manager.get_statistics()

    # Add additional metrics
    job_ages = []
    retry_distribution = {"0": 0, "1": 0, "2": 0, "3+": 0}

    for job in enhanced_job_manager.jobs.values():
        # Calculate job age
        if job.get("created_at"):
            age_hours = (datetime.utcnow() - job["created_at"]).total_seconds() / 3600
            job_ages.append(age_hours)

        # Track retry distribution
        retry_count = job.get("retry_count", 0)
        if retry_count >= 3:
            retry_distribution["3+"] += 1
        else:
            retry_distribution[str(retry_count)] += 1

    avg_job_age_hours = sum(job_ages) / len(job_ages) if job_ages else 0

    return {
        **stats,
        "average_job_age_hours": avg_job_age_hours,
        "retry_distribution": retry_distribution,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/batches")
async def list_batches(
    limit: int = 50,
    offset: int = 0,
    include_completed: bool = True
):
    """List all batch jobs with pagination."""
    all_batches = []

    for batch_id in list(enhanced_job_manager.batch_jobs.keys())[offset:offset+limit]:
        batch_status = enhanced_job_manager.get_batch_status(batch_id)
        if batch_status:
            # Filter out completed batches if requested
            if not include_completed:
                completion_pct = batch_status.get("completion_percentage", 0)
                if completion_pct >= 100:
                    continue

            all_batches.append(batch_status)

    return {
        "batches": all_batches,
        "total_count": len(enhanced_job_manager.batch_jobs),
        "limit": limit,
        "offset": offset
    }


# ============================================================================
# Utility Endpoints
# ============================================================================

@router.post("/cleanup/completed")
async def cleanup_completed_jobs(
    older_than_hours: int = 24,
    keep_failed_jobs: bool = True
):
    """Clean up completed jobs older than specified time."""
    cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)

    jobs_to_remove = []
    for job_id, job in enhanced_job_manager.jobs.items():
        if job.get("completed_at") and job["completed_at"] < cutoff_time:
            # Keep failed jobs if requested
            if keep_failed_jobs and job["status"] == JobStatus.FAILED:
                continue
            jobs_to_remove.append(job_id)

    # Remove jobs and related data
    removed_count = 0
    for job_id in jobs_to_remove:
        try:
            # Remove from main storage
            if job_id in enhanced_job_manager.jobs:
                del enhanced_job_manager.jobs[job_id]

            # Clean up related data
            if job_id in enhanced_job_manager.job_dependencies:
                del enhanced_job_manager.job_dependencies[job_id]

            if job_id in enhanced_job_manager.retry_configs:
                del enhanced_job_manager.retry_configs[job_id]

            if job_id in enhanced_job_manager.retry_schedules:
                del enhanced_job_manager.retry_schedules[job_id]

            # Remove from dependent jobs tracking
            for dependents in enhanced_job_manager.dependent_jobs.values():
                dependents.discard(job_id)

            removed_count += 1

        except Exception as e:
            logger.error(f"Error removing job {job_id}: {str(e)}")

    return {
        "removed_jobs": removed_count,
        "cutoff_time": cutoff_time.isoformat(),
        "remaining_jobs": len(enhanced_job_manager.jobs)
    }


@router.get("/health")
async def get_job_manager_health():
    """Get health status of the job manager."""
    stats = enhanced_job_manager.get_statistics()

    # Calculate health indicators
    total_jobs = stats.get("active_jobs", 0)
    failed_jobs = len([
        job for job in enhanced_job_manager.jobs.values()
        if job["status"] == JobStatus.FAILED
    ])

    health_score = 100
    issues = []

    # Check for high failure rate
    if total_jobs > 0:
        failure_rate = failed_jobs / total_jobs
        if failure_rate > 0.2:  # 20% failure rate
            health_score -= 30
            issues.append(f"High failure rate: {failure_rate:.1%}")

    # Check for stuck retries
    stuck_retries = len([
        job_id for job_id, retry_time in enhanced_job_manager.retry_schedules.items()
        if (datetime.utcnow() - retry_time).total_seconds() > 3600  # Stuck for over 1 hour
    ])

    if stuck_retries > 0:
        health_score -= 20
        issues.append(f"Stuck retries: {stuck_retries}")

    # Check for excessive cleanup tasks
    if len(enhanced_job_manager.cleanup_tasks) > 10:
        health_score -= 10
        issues.append(f"High cleanup task count: {len(enhanced_job_manager.cleanup_tasks)}")

    status = "healthy"
    if health_score < 70:
        status = "unhealthy"
    elif health_score < 85:
        status = "degraded"

    return {
        "status": status,
        "health_score": max(0, health_score),
        "issues": issues,
        "statistics": stats,
        "timestamp": datetime.utcnow().isoformat()
    }