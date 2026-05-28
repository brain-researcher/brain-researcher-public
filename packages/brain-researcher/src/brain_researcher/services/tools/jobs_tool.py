"""Jobs management tools for compute job control and monitoring."""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


def _get_event_loop():
    """Get or create an event loop for async execution."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _run_async(coro):
    """Run an async coroutine from sync code."""
    try:
        loop = asyncio.get_running_loop()
        # Already in async context - create task
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        # No running loop - create one
        return asyncio.run(coro)


def _timestamp_to_iso(ts: Optional[int]) -> Optional[str]:
    """Convert Unix timestamp to ISO format string."""
    if ts is None:
        return None
    return datetime.utcfromtimestamp(ts).isoformat() + "Z"


def _detect_queue_backend() -> str:
    """Auto-detect available queue backend."""
    # Check user override first
    user_backend = os.getenv("BR_JOB_BACKEND", "").lower()
    if user_backend and user_backend != "auto":
        return user_backend

    # Auto-detect
    if shutil.which("squeue"):
        return "slurm"
    if shutil.which("qstat"):
        return "pbs"
    return "local"


def _queue_snapshot(store) -> Dict[str, Any]:
    """Return lightweight queue stats plus detected backend."""
    backend = _detect_queue_backend()
    stats: Dict[str, Any] = {"backend": backend}
    try:
        if hasattr(store, "get_queue_stats"):
            snapshot = _run_async(store.get_queue_stats())
            if isinstance(snapshot, dict):
                stats.update(snapshot)
    except Exception:
        # Best-effort only
        pass
    return stats


# =============================================================================
# Pydantic Argument Schemas
# =============================================================================


class ListUserJobsArgs(BaseModel):
    """Arguments for listing user jobs."""

    user_id: Optional[str] = Field(
        default=None,
        description="Filter by user ID (default: current user)",
    )
    state: Optional[str] = Field(
        default=None,
        description="Filter by state: pending, queued, running, succeeded, failed, cancelled",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of jobs to return",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset",
    )


class GetJobStatusArgs(BaseModel):
    """Arguments for getting detailed job status."""

    job_id: str = Field(description="Job identifier (UUID or short ID)")
    include_timing: bool = Field(
        default=True,
        description="Include timing information (created, started, finished timestamps)",
    )


class GetJobLogsArgs(BaseModel):
    """Arguments for retrieving job logs."""

    job_id: str = Field(description="Job identifier")
    stream: Optional[str] = Field(
        default=None,
        description="Filter by stream: 'stdout', 'stderr', or None for both",
    )
    tail: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of recent log lines to retrieve",
    )


class SubmitJobArgs(BaseModel):
    """Arguments for job submission."""

    pipeline: str = Field(
        description="Pipeline to run: fmriprep, mriqc, qsiprep, fitlins, custom",
    )
    dataset_id: str = Field(description="Target dataset ID (e.g., ds000001)")
    name: Optional[str] = Field(
        default=None,
        description="Human-readable job name",
    )
    backend: str = Field(
        default="auto",
        description="Queue backend: auto, slurm, pbs, local",
    )
    cpus: int = Field(default=1, ge=1, le=128, description="Number of CPU cores")
    memory_gb: float = Field(default=4.0, ge=0.5, le=512, description="Memory in GB")
    gpus: int = Field(default=0, ge=0, le=8, description="Number of GPUs")
    walltime_minutes: int = Field(
        default=60, ge=1, le=10080, description="Max runtime in minutes"
    )
    dry_run: bool = Field(
        default=False,
        description="Validate without actually submitting",
    )


class CancelJobArgs(BaseModel):
    """Arguments for job cancellation."""

    job_id: str = Field(description="Job to cancel")
    reason: Optional[str] = Field(
        default=None,
        description="Cancellation reason",
    )


# =============================================================================
# Tool Implementations
# =============================================================================


class ListUserJobsTool(NeuroToolWrapper):
    """List compute jobs with filtering by user and state."""

    TAGS = ["jobs", "monitoring"]

    def get_tool_name(self) -> str:
        return "jobs.list_user_jobs"

    def get_tool_description(self) -> str:
        return (
            "List compute jobs with optional filtering by user ID, job state, "
            "and pagination support."
        )

    def get_args_schema(self):
        return ListUserJobsArgs

    def _run(
        self,
        user_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ToolResult:
        try:
            from brain_researcher.services.orchestrator.job_store_factory import (
                get_job_store,
            )

            store = get_job_store()

            async def _list_jobs():
                if state:
                    jobs = await store.list_by_state(state, user_id=user_id, limit=limit, offset=offset)
                else:
                    jobs = await store.list_all(user_id=user_id, limit=limit, offset=offset)
                return jobs

            jobs = _run_async(_list_jobs())

            # Convert to serializable format
            items = []
            for job in jobs:
                # Parse payload for resource info when available
                resources: Dict[str, Any] = {}
                try:
                    import json

                    payload = json.loads(job.payload_json)
                    resources = payload.get("resources", {}) if isinstance(payload, dict) else {}
                    backend = payload.get("backend") if isinstance(payload, dict) else None
                except Exception:
                    backend = None

                items.append({
                    "job_id": job.job_id,
                    "kind": job.kind,
                    "state": job.state,
                    "priority": job.priority,
                    "created_at": _timestamp_to_iso(job.created_at),
                    "started_at": _timestamp_to_iso(job.started_at),
                    "finished_at": _timestamp_to_iso(job.finished_at),
                    "attempt": job.attempt,
                    "max_attempts": job.max_attempts,
                    "user_id": job.user_id,
                    "resources": resources or None,
                    "backend": backend,
                })

            return ToolResult(
                status="success",
                data={
                    "items": items,
                    "total": len(items),
                    "limit": limit,
                    "offset": offset,
                    "queue": _queue_snapshot(store),
                },
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to list jobs: {str(e)}",
                data=None,
            )


class GetJobStatusTool(NeuroToolWrapper):
    """Get detailed status for a specific job."""

    TAGS = ["jobs", "monitoring"]

    def get_tool_name(self) -> str:
        return "jobs.get_job_status"

    def get_tool_description(self) -> str:
        return (
            "Get detailed status for a specific job including state, timing, "
            "retry info, and error messages."
        )

    def get_args_schema(self):
        return GetJobStatusArgs

    def _run(self, job_id: str, include_timing: bool = True) -> ToolResult:
        try:
            from brain_researcher.services.orchestrator.job_store_factory import (
                get_job_store,
            )

            store = get_job_store()

            async def _get_job():
                return await store.get(job_id)

            job = _run_async(_get_job())

            if not job:
                return ToolResult(
                    status="error",
                    error=f"Job '{job_id}' not found",
                    data=None,
                )

            data: Dict[str, Any] = {
                "job_id": job.job_id,
                "kind": job.kind,
                "state": job.state,
                "priority": job.priority,
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "exit_code": job.exit_code,
                "error_message": job.error_message,
                "worker_id": job.worker_id,
                "user_id": job.user_id,
                "run_id": job.run_id,
                "run_dir": job.run_dir,
            }

            # Decode resources/backend from payload_json when available
            try:
                import json

                payload = json.loads(job.payload_json)
                if isinstance(payload, dict):
                    data["resources"] = payload.get("resources")
                    data["backend"] = payload.get("backend")
            except Exception:
                pass

            if include_timing:
                data["timing"] = {
                    "created_at": _timestamp_to_iso(job.created_at),
                    "queued_at": _timestamp_to_iso(job.queued_at),
                    "claimed_at": _timestamp_to_iso(job.claimed_at),
                    "started_at": _timestamp_to_iso(job.started_at),
                    "finished_at": _timestamp_to_iso(job.finished_at),
                }
                # Calculate duration if completed
                if job.started_at and job.finished_at:
                    data["timing"]["duration_seconds"] = job.finished_at - job.started_at

            # Resource info
            if job.gpu_req > 0:
                data["resources"] = {
                    "gpu_req": job.gpu_req,
                    "gpu_type": job.gpu_type,
                }

            # Cancellation info
            if job.cancellation_requested or job.cancel_reason:
                data["cancellation"] = {
                    "requested": job.cancellation_requested,
                    "reason": job.cancel_reason,
                }

            return ToolResult(status="success", data=data)

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to get job status: {str(e)}",
                data=None,
            )


class GetJobLogsTool(NeuroToolWrapper):
    """Retrieve stdout/stderr logs from a job."""

    TAGS = ["jobs", "monitoring", "debugging"]

    def get_tool_name(self) -> str:
        return "jobs.get_job_logs"

    def get_tool_description(self) -> str:
        return (
            "Retrieve stdout/stderr logs from a job for debugging. "
            "Can filter by stream (stdout/stderr) and limit number of lines."
        )

    def get_args_schema(self):
        return GetJobLogsArgs

    def _run(
        self,
        job_id: str,
        stream: Optional[str] = None,
        tail: int = 100,
    ) -> ToolResult:
        try:
            from brain_researcher.services.orchestrator.job_store_factory import (
                get_job_store,
            )

            store = get_job_store()

            async def _get_logs():
                # First check if job exists
                job = await store.get(job_id)
                if not job:
                    return None, f"Job '{job_id}' not found"

                # Get logs
                logs = await store.iter_logs(job_id, start_offset=0, stream=stream)
                return logs, None

            logs, error = _run_async(_get_logs())

            if error:
                return ToolResult(status="error", error=error, data=None)

            # Process log chunks
            stdout_lines = []
            stderr_lines = []

            for chunk in logs or []:
                text = chunk.data.decode("utf-8", errors="replace") if hasattr(chunk, "data") else str(chunk)
                lines = text.split("\n")
                if hasattr(chunk, "stream"):
                    if chunk.stream == "stdout":
                        stdout_lines.extend(lines)
                    elif chunk.stream == "stderr":
                        stderr_lines.extend(lines)
                else:
                    stdout_lines.extend(lines)

            # Tail the logs
            if stream == "stdout":
                return ToolResult(
                    status="success",
                    data={
                        "job_id": job_id,
                        "stream": "stdout",
                        "lines": stdout_lines[-tail:],
                        "total_lines": len(stdout_lines),
                    },
                )
            elif stream == "stderr":
                return ToolResult(
                    status="success",
                    data={
                        "job_id": job_id,
                        "stream": "stderr",
                        "lines": stderr_lines[-tail:],
                        "total_lines": len(stderr_lines),
                    },
                )
            else:
                return ToolResult(
                    status="success",
                    data={
                        "job_id": job_id,
                        "stdout": {
                            "lines": stdout_lines[-tail:],
                            "total_lines": len(stdout_lines),
                        },
                        "stderr": {
                            "lines": stderr_lines[-tail:],
                            "total_lines": len(stderr_lines),
                        },
                    },
                )

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to get job logs: {str(e)}",
                data=None,
            )


class SubmitJobTool(NeuroToolWrapper):
    """Submit a new compute job (dangerous operation)."""

    TAGS = ["jobs", "write"]
    DANGEROUS = True
    COST_HINT = "expensive"

    def get_tool_name(self) -> str:
        return "jobs.submit"

    def get_tool_description(self) -> str:
        return (
            "Submit a compute job to the queue system. "
            "Supports SLURM, PBS, and local execution backends. "
            "Use dry_run=True to validate without actually submitting."
        )

    def get_args_schema(self):
        return SubmitJobArgs

    def _run(
        self,
        pipeline: str,
        dataset_id: str,
        name: Optional[str] = None,
        backend: str = "auto",
        cpus: int = 1,
        memory_gb: float = 4.0,
        gpus: int = 0,
        walltime_minutes: int = 60,
        dry_run: bool = False,
    ) -> ToolResult:
        try:
            import json
            import uuid

            from brain_researcher.services.orchestrator.job_store import (
                JobRecord,
                JobState,
            )
            from brain_researcher.services.orchestrator.job_store_factory import (
                get_job_store,
            )

            # Resolve backend
            resolved_backend = _detect_queue_backend() if backend == "auto" else backend

            # Build job payload
            payload = {
                "pipeline": pipeline,
                "dataset_id": dataset_id,
                "backend": resolved_backend,
                "resources": {
                    "cpus": cpus,
                    "memory_gb": memory_gb,
                    "gpus": gpus,
                    "walltime_minutes": walltime_minutes,
                },
            }

            job_name = name or f"{pipeline}_{dataset_id}"
            job_id = str(uuid.uuid4())[:8]

            if dry_run:
                return ToolResult(
                    status="success",
                    data={
                        "dry_run": True,
                        "job_id": job_id,
                        "job_name": job_name,
                        "backend": resolved_backend,
                        "payload": payload,
                        "message": "Dry run - job not actually submitted",
                    },
                )

            # Create job record
            job = JobRecord(
                job_id=job_id,
                kind=pipeline,
                payload_json=json.dumps(payload),
                state=JobState.PENDING.value,
                priority=5,  # Normal priority
                gpu_req=gpus,
                cpus=cpus,
                memory_gb=memory_gb,
                walltime_minutes=walltime_minutes,
                backend=resolved_backend,
                job_name=job_name,
            )

            store = get_job_store()

            async def _enqueue():
                return await store.enqueue(job)

            submitted_id = _run_async(_enqueue())

            return ToolResult(
                status="success",
                data={
                    "job_id": submitted_id,
                    "job_name": job_name,
                    "backend": resolved_backend,
                    "state": "pending",
                    "message": f"Job submitted to {resolved_backend} queue",
                    "queue": _queue_snapshot(store),
                },
            )

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to submit job: {str(e)}",
                data=None,
            )


class CancelJobTool(NeuroToolWrapper):
    """Cancel a running or queued job (dangerous operation)."""

    TAGS = ["jobs", "write"]
    DANGEROUS = True

    def get_tool_name(self) -> str:
        return "jobs.cancel"

    def get_tool_description(self) -> str:
        return (
            "Cancel a running or queued job. "
            "For running jobs, signals cancellation - the job may take time to stop."
        )

    def get_args_schema(self):
        return CancelJobArgs

    def _run(self, job_id: str, reason: Optional[str] = None) -> ToolResult:
        try:
            from brain_researcher.services.orchestrator.job_store_factory import (
                get_job_store,
            )

            store = get_job_store()

            async def _cancel():
                # First check job exists
                job = await store.get(job_id)
                if not job:
                    return None, f"Job '{job_id}' not found"

                # Try to cancel
                success = await store.cancel(job_id, reason=reason or "User requested")
                return success, None

            success, error = _run_async(_cancel())

            if error:
                return ToolResult(status="error", error=error, data=None)

            if success:
                return ToolResult(
                    status="success",
                    data={
                        "job_id": job_id,
                        "cancelled": True,
                        "reason": reason or "User requested",
                        "message": "Cancellation requested",
                    },
                )
            else:
                return ToolResult(
                    status="success",
                    data={
                        "job_id": job_id,
                        "cancelled": False,
                        "message": "Job already in terminal state, cannot cancel",
                    },
                )

        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Failed to cancel job: {str(e)}",
                data=None,
            )


# =============================================================================
# Factory
# =============================================================================


class JobsTools:
    """Factory for Jobs management tools."""

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            ListUserJobsTool(),
            GetJobStatusTool(),
            GetJobLogsTool(),
            SubmitJobTool(),
            CancelJobTool(),
        ]


def get_all_tools() -> list[NeuroToolWrapper]:
    """Return all Jobs tools for registration."""
    return JobsTools().get_all_tools()
