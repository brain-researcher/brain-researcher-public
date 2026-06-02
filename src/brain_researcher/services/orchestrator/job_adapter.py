"""
Job Adapter: Converts between rich Job model and JobRecord storage model.

The existing codebase uses a complex Job model with steps, artifacts, metrics, etc.
JobStore uses a simpler JobRecord model optimized for persistence.

This adapter handles bidirectional conversion while preserving all data.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from datetime import datetime
from typing import Any

from .job_store import JobRecord, JobState

logger = logging.getLogger(__name__)


# JSON serializer helper
def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_error_message(error_obj: Any) -> str | None:
    if error_obj is None or isinstance(error_obj, str):
        return error_obj
    try:
        if hasattr(error_obj, "model_dump"):
            return json.dumps(error_obj.model_dump(), default=_json_default)
        return json.dumps(error_obj, default=_json_default)
    except TypeError:
        return str(error_obj)


# Lazy import to avoid circular dependency
def _get_job_class():
    """Get the Job model from job_management_endpoints."""
    from brain_researcher.services.orchestrator.job_management_endpoints import Job

    return Job


def _get_build_plan_summary():
    """Get the _build_plan_summary helper from job_management_endpoints."""
    from brain_researcher.services.orchestrator.job_management_endpoints import (
        _build_plan_summary,
    )

    return _build_plan_summary


class JobAdapter:
    """
    Adapter between enhanced Job model and JobRecord storage model.

    Conversion strategy:
    - Simple fields: direct mapping
    - Complex fields (steps, artifacts, metrics): JSON serialization
    - Timestamps: datetime ↔ Unix timestamp (int)
    - State: JobStatus enum ↔ JobState enum
    """

    @staticmethod
    def to_record(job: Any) -> JobRecord:
        """
        Convert enhanced Job to JobRecord for storage.

        Args:
            job: Enhanced job from job_management_endpoints.py

        Returns:
            JobRecord for storage in JobStore
        """
        # Convert complex objects to JSON
        metadata = copy.deepcopy(getattr(job, "metadata", {}) or {})
        parameters = metadata.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        else:
            parameters = copy.deepcopy(parameters)
        metadata["parameters"] = parameters
        client_metadata = parameters.get("_client_metadata", {})
        if not isinstance(client_metadata, dict):
            client_metadata = {}

        tool_name = (
            parameters.get("tool")
            or parameters.get("tool_name")
            or metadata.get("tool_name")
        )
        if tool_name:
            metadata["tool_name"] = tool_name

        plan_payload = copy.deepcopy(
            getattr(job, "plan_of_record", None)
            or metadata.get("plan_of_record")
            or client_metadata.get("canonical_plan")
        )
        plan_events = copy.deepcopy(
            getattr(job, "plan_events", []) or metadata.get("plan_events") or []
        )
        por_token = getattr(job, "por_token", None) or metadata.get("por_token")
        plan_execute = bool(
            metadata.get("plan_execute") or client_metadata.get("canonical_plan")
        )

        if plan_payload:
            metadata["plan_of_record"] = plan_payload
        if plan_events:
            metadata["plan_events"] = plan_events
        if por_token:
            metadata["por_token"] = por_token

        session_id = (
            getattr(job, "session_id", None)
            or metadata.get("thread_id")
            or metadata.get("session_id")
        )
        project_id = (
            getattr(job, "project_id", None)
            or metadata.get("project_id")
            or metadata.get("workspace_id")
        )

        # Build and cache plan_summary to avoid recomputation
        plan_summary = None
        if plan_payload:
            try:
                _build_plan_summary = _get_build_plan_summary()
                plan_summary = _build_plan_summary(job)
            except Exception as e:
                logger.warning(f"Failed to build plan_summary for job {job.id}: {e}")

        payload = {
            "name": getattr(job, "name", None),
            "prompt": getattr(job, "prompt", ""),
            "steps": [step.model_dump() for step in getattr(job, "steps", [])],
            "artifacts": [art.model_dump() for art in getattr(job, "artifacts", [])],
            "dependencies": [
                dep.model_dump() for dep in getattr(job, "dependencies", [])
            ],
            "dependent_jobs": getattr(job, "dependent_jobs", []),
            "resource_requirements": getattr(job, "resource_requirements", {}),
            "resource_usage": (
                getattr(job, "resource_usage", {}).model_dump()
                if hasattr(getattr(job, "resource_usage", None), "model_dump")
                else None
            ),
            "current_step_index": getattr(job, "current_step_index", 0),
            "estimated_completion": getattr(job, "estimated_completion", None),
            "tags": getattr(job, "tags", []),
            "metadata": metadata,
            "parameters": parameters,
            "tool_name": tool_name,
            "plan_of_record": plan_payload,
            "plan_events": plan_events,
            "por_token": por_token,
            "plan_summary": plan_summary,  # Cached summary for API responses
            "plan_execute": plan_execute,
        }
        if plan_payload and plan_execute:
            payload["type"] = "plan_execution"
            payload["plan"] = plan_payload

        # Extract GPU requirements from resource_requirements
        gpu_req = 0
        gpu_type = None
        if hasattr(job, "resource_requirements"):
            res_reqs = job.resource_requirements
            if isinstance(res_reqs, dict):
                gpu_req = res_reqs.get("gpu_count", 0) or res_reqs.get("gpu", 0)
                gpu_type = res_reqs.get("gpu_type")

        # Allow explicit overrides on the job model
        direct_gpu_req = getattr(job, "gpu_count_required", None)
        if direct_gpu_req is not None:
            gpu_req = direct_gpu_req
        direct_gpu_type = getattr(job, "gpu_type", None)
        if direct_gpu_type:
            gpu_type = direct_gpu_type

        # Convert timestamps
        def to_unix_timestamp(dt: datetime | None) -> int | None:
            if dt is None:
                return None
            if isinstance(dt, int):
                return dt
            return int(dt.timestamp())

        lease_expires_at = to_unix_timestamp(getattr(job, "lease_expires_at", None))
        last_heartbeat = to_unix_timestamp(getattr(job, "last_heartbeat", None))
        attempt = getattr(job, "attempt", getattr(job, "retry_count", 0))
        max_attempts = getattr(job, "max_attempts", getattr(job, "max_retries", 3))
        cancel_reason = getattr(
            job, "cancellation_reason", getattr(job, "cancel_reason", None)
        )
        worker_id = getattr(job, "worker_id", None)
        run_id = getattr(job, "run_id", None)
        run_dir = getattr(job, "run_dir", None)
        provenance_path = getattr(job, "provenance_path", None)
        error_message = _serialize_error_message(getattr(job, "error", None))

        # Map status to state
        state = JobAdapter._map_status_to_state(getattr(job, "status", "pending"))

        # Priority mapping
        priority_map = {
            "low": 0,
            "normal": 5,
            "high": 10,
            "critical": 20,
        }
        priority_str = str(getattr(job, "priority", "normal")).lower()
        priority = priority_map.get(priority_str, 5)

        timing = getattr(job, "timing", None)
        created_at_source = getattr(job, "created_at", None)
        if created_at_source is None and timing is not None:
            created_at_source = getattr(timing, "start_time", None)
        started_at_source = getattr(job, "started_at", None)
        if started_at_source is None and timing is not None:
            started_at_source = getattr(timing, "start_time", None)
        finished_at_source = getattr(job, "completed_at", None)
        if finished_at_source is None and timing is not None:
            finished_at_source = getattr(timing, "end_time", None)

        created_at_ts = to_unix_timestamp(created_at_source)
        if created_at_ts is None:
            created_at_ts = int(time.time())

        return JobRecord(
            job_id=job.id,
            kind="enhanced_job",  # Type marker
            payload_json=json.dumps(payload, default=_json_default),
            state=state,
            priority=priority,
            created_at=created_at_ts,
            queued_at=to_unix_timestamp(getattr(job, "queued_at", None)),
            started_at=to_unix_timestamp(started_at_source),
            finished_at=to_unix_timestamp(finished_at_source),
            attempt=attempt,
            max_attempts=max_attempts,
            cancel_reason=cancel_reason,
            cancellation_requested=getattr(job, "cancellation_requested", False),
            error_message=error_message,
            gpu_req=gpu_req,
            gpu_type=gpu_type,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
            last_heartbeat=last_heartbeat,
            run_id=run_id,
            run_dir=run_dir,
            provenance_path=provenance_path,
            user_id=getattr(job, "user_id", None),
            session_id=session_id,
            project_id=project_id,
        )

    @staticmethod
    def from_record(record: JobRecord) -> Any:
        """
        Convert JobRecord back to enhanced Job.

        Args:
            record: JobRecord from JobStore

        Returns:
            Enhanced Job model
        """
        # Parse payload JSON
        try:
            payload = json.loads(record.payload_json)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse payload for job {record.job_id}")
            payload = {}

        # Convert timestamps
        def from_unix_timestamp(ts: int | None) -> datetime | None:
            if ts is None:
                return None
            return datetime.fromtimestamp(ts)

        # Map state back to status
        state_to_status = {
            JobState.PENDING: "pending",
            JobState.QUEUED: "queued",
            JobState.CLAIMED: "claimed",
            JobState.RUNNING: "running",
            JobState.SUCCEEDED: "completed",
            JobState.FAILED: "failed",
            JobState.CANCELLED: "cancelled",
            JobState.TIMEOUT: "timeout",
            JobState.CANCELLING: "cancelling",
            JobState.SKIPPED: "skipped",
            JobState.PAUSED: "paused",
            JobState.RETRYING: "retrying",
        }
        status = state_to_status.get(record.state, "pending")

        # Map priority back
        priority_map = {
            (0, 4): "low",
            (5, 9): "normal",
            (10, 19): "high",
            (20, 100): "critical",
        }
        priority_str = "normal"
        for (min_p, max_p), p_str in priority_map.items():
            if min_p <= record.priority <= max_p:
                priority_str = p_str
                break

        # Calculate progress percentage
        steps = payload.get("steps", [])
        completed_steps = sum(1 for step in steps if step.get("status") == "completed")
        total_steps = len(steps) if steps else 1
        progress_percentage = (
            (completed_steps / total_steps) * 100 if total_steps > 0 else 0.0
        )

        # Reconstruct Job model
        # Note: This uses the Enhanced Job model from job_management_endpoints.py
        # We need to import and construct it properly
        metadata = payload.get("metadata", {}) or {}
        parameters = payload.get("parameters", {}) or {}
        if not isinstance(parameters, dict):
            parameters = {}
        client_metadata = parameters.get("_client_metadata", {})
        if not isinstance(client_metadata, dict):
            client_metadata = {}
        plan_payload = (
            payload.get("plan_of_record")
            or metadata.get("plan_of_record")
            or client_metadata.get("canonical_plan")
        )
        plan_events = payload.get("plan_events") or metadata.get("plan_events") or []
        por_token = payload.get("por_token") or metadata.get("por_token")
        plan_execute = (
            payload.get("plan_execute")
            or metadata.get("plan_execute")
            or client_metadata.get("canonical_plan")
        )
        plan_summary = payload.get("plan_summary")  # Restored cached summary
        if plan_payload and "plan_of_record" not in metadata:
            metadata["plan_of_record"] = plan_payload
        if plan_events and "plan_events" not in metadata:
            metadata["plan_events"] = plan_events
        if por_token and "por_token" not in metadata:
            metadata["por_token"] = por_token
        if plan_summary and "plan_summary" not in metadata:
            metadata["plan_summary"] = plan_summary
        if plan_execute and "plan_execute" not in metadata:
            metadata["plan_execute"] = plan_execute

        job_data = {
            "id": record.job_id,
            "name": payload.get("name"),
            "prompt": payload.get("prompt", ""),
            "status": status,
            "priority": priority_str,
            "progress": progress_percentage,
            "created_at": from_unix_timestamp(record.created_at),
            "queued_at": from_unix_timestamp(record.queued_at),
            "started_at": from_unix_timestamp(record.started_at),
            "completed_at": from_unix_timestamp(record.finished_at),
            "estimated_completion": payload.get("estimated_completion"),
            "steps": payload.get("steps", []),
            "current_step_index": payload.get("current_step_index", 0),
            "artifacts": payload.get("artifacts", []),
            "resource_requirements": payload.get("resource_requirements", {}),
            "resource_usage": payload.get("resource_usage"),
            "cancellation_requested": record.cancellation_requested,
            "cancellation_reason": record.cancel_reason,
            "dependencies": payload.get("dependencies", []),
            "dependent_jobs": payload.get("dependent_jobs", []),
            "retry_count": record.attempt,
            "max_retries": record.max_attempts,
            "attempt": record.attempt,
            "max_attempts": record.max_attempts,
            "tags": payload.get("tags", []),
            "metadata": metadata,
            "plan_of_record": plan_payload,
            "plan_events": plan_events,
            "por_token": por_token,
            "user_id": record.user_id,
            "session_id": record.session_id,
            "project_id": record.project_id,
            "error": record.error_message,
            "worker_id": record.worker_id,
            "lease_expires_at": from_unix_timestamp(record.lease_expires_at),
            "last_heartbeat": from_unix_timestamp(record.last_heartbeat),
            "gpu_count_required": record.gpu_req,
            "gpu_type": record.gpu_type,
            "assigned_gpu_slots": payload.get("assigned_gpu_slots", []),
            "run_id": record.run_id,
            "run_dir": record.run_dir,
            "provenance_path": record.provenance_path,
        }

        # Add JobStore-specific fields
        job_data["_job_record"] = record  # Attach original record for debugging

        # Use the Job model from job_management_endpoints (not models.py)
        JobClass = _get_job_class()
        return JobClass(**job_data)

    @staticmethod
    def sync_fields(job: Any, record: JobRecord) -> None:
        """
        Sync fields from enhanced Job back to JobRecord (for updates).

        This is useful when the Job model is mutated in-place and we need
        to persist the changes back to the JobStore.

        Args:
            job: Enhanced job with potentially modified fields
            record: JobRecord to update
        """
        # Update simple fields
        record.state = JobAdapter._map_status_to_state(job.status)
        priority_attr = getattr(job, "priority", None)
        if priority_attr is None:
            metadata = getattr(job, "metadata", {}) or {}
            priority_attr = metadata.get("priority", "normal")
        record.priority = JobAdapter._map_priority_to_int(str(priority_attr))
        record.cancellation_requested = job.cancellation_requested
        record.cancel_reason = job.cancellation_reason
        record.worker_id = getattr(job, "worker_id", record.worker_id)

        # Update timestamps
        timing = getattr(job, "timing", None)
        queued_at = getattr(job, "queued_at", None)
        if queued_at:
            record.queued_at = (
                int(queued_at.timestamp())
                if isinstance(queued_at, datetime)
                else queued_at
            )
        started_at = getattr(job, "started_at", None)
        if started_at is None and timing is not None:
            started_at = getattr(timing, "start_time", None)
        if started_at:
            record.started_at = (
                int(started_at.timestamp())
                if isinstance(started_at, datetime)
                else started_at
            )
        completed_at = getattr(job, "completed_at", None)
        if completed_at is None and timing is not None:
            completed_at = getattr(timing, "end_time", None)
        if completed_at:
            record.finished_at = (
                int(completed_at.timestamp())
                if isinstance(completed_at, datetime)
                else completed_at
            )
        lease_expires_at = getattr(job, "lease_expires_at", None)
        if lease_expires_at:
            record.lease_expires_at = (
                int(lease_expires_at.timestamp())
                if isinstance(lease_expires_at, datetime)
                else lease_expires_at
            )
        last_heartbeat = getattr(job, "last_heartbeat", None)
        if last_heartbeat:
            record.last_heartbeat = (
                int(last_heartbeat.timestamp())
                if isinstance(last_heartbeat, datetime)
                else last_heartbeat
            )

        # Update retry count
        retry_attr = getattr(job, "retry_count", None)
        record.attempt = getattr(
            job, "attempt", retry_attr if retry_attr is not None else record.attempt
        )
        record.max_attempts = getattr(
            job, "max_attempts", getattr(job, "max_retries", record.max_attempts)
        )

        # Update GPU reservation info
        if getattr(job, "gpu_count_required", None) is not None:
            record.gpu_req = job.gpu_count_required
        if getattr(job, "gpu_type", None) is not None:
            record.gpu_type = job.gpu_type

        # Provenance pointers
        record.run_id = getattr(job, "run_id", record.run_id)
        record.run_dir = getattr(job, "run_dir", record.run_dir)
        record.provenance_path = getattr(job, "provenance_path", record.provenance_path)
        record.error_message = _serialize_error_message(getattr(job, "error", None))
        metadata = getattr(job, "metadata", {}) or {}
        record.session_id = (
            getattr(job, "session_id", None)
            or metadata.get("thread_id")
            or metadata.get("session_id")
            or record.session_id
        )
        record.project_id = (
            getattr(job, "project_id", None)
            or metadata.get("project_id")
            or metadata.get("workspace_id")
            or record.project_id
        )

        # Re-serialize payload (in case steps/artifacts changed)
        parameters = metadata.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        client_metadata = parameters.get("_client_metadata", {})
        if not isinstance(client_metadata, dict):
            client_metadata = {}
        plan_payload = copy.deepcopy(
            getattr(job, "plan_of_record", None)
            or metadata.get("plan_of_record")
            or client_metadata.get("canonical_plan")
        )
        plan_events = copy.deepcopy(
            getattr(job, "plan_events", []) or metadata.get("plan_events") or []
        )
        por_token = getattr(job, "por_token", None) or metadata.get("por_token")
        plan_execute = bool(
            metadata.get("plan_execute") or client_metadata.get("canonical_plan")
        )
        if plan_payload:
            metadata["plan_of_record"] = plan_payload
        if plan_events:
            metadata["plan_events"] = plan_events
        if por_token:
            metadata["por_token"] = por_token

        # Build and cache plan_summary
        plan_summary = None
        if plan_payload:
            try:
                _build_plan_summary = _get_build_plan_summary()
                plan_summary = _build_plan_summary(job)
            except Exception as e:
                logger.warning(f"Failed to build plan_summary for job {job.id}: {e}")

        payload = {
            "name": getattr(job, "name", None),
            "prompt": getattr(job, "prompt", ""),
            "steps": [step.model_dump() for step in getattr(job, "steps", [])],
            "artifacts": [art.model_dump() for art in getattr(job, "artifacts", [])],
            "dependencies": [
                dep.model_dump() for dep in getattr(job, "dependencies", [])
            ],
            "dependent_jobs": getattr(job, "dependent_jobs", []),
            "resource_requirements": getattr(job, "resource_requirements", {}),
            "resource_usage": getattr(
                getattr(job, "resource_usage", None), "model_dump", lambda: None
            )(),
            "current_step_index": getattr(job, "current_step_index", 0),
            "estimated_completion": getattr(job, "estimated_completion", None),
            "tags": getattr(job, "tags", []),
            "metadata": metadata,
            "assigned_gpu_slots": getattr(job, "assigned_gpu_slots", []),
            "plan_of_record": plan_payload,
            "plan_events": plan_events,
            "por_token": por_token,
            "plan_summary": plan_summary,
            "plan_execute": plan_execute,
        }
        if plan_payload and plan_execute:
            payload["type"] = "plan_execution"
            payload["plan"] = plan_payload
        record.payload_json = json.dumps(payload, default=_json_default)

    @staticmethod
    def _map_status_to_state(status: Any) -> str:
        """Map JobStatus to JobState."""
        if hasattr(status, "value"):
            status_str = str(status.value)
        else:
            status_str = str(status)
        status_map = {
            "pending": JobState.PENDING,
            "queued": JobState.QUEUED,
            "claimed": JobState.CLAIMED,
            "running": JobState.RUNNING,
            "completed": JobState.SUCCEEDED,
            "succeeded": JobState.SUCCEEDED,
            "failed": JobState.FAILED,
            "cancelled": JobState.CANCELLED,
            "cancelling": JobState.CANCELLING,
            "skipped": JobState.SKIPPED,
            "paused": JobState.PAUSED,
            "retrying": JobState.RETRYING,
            "timeout": JobState.TIMEOUT,
        }
        return status_map.get(status_str.lower(), JobState.PENDING)

    @staticmethod
    def _map_priority_to_int(priority: str) -> int:
        """Map JobPriority to integer."""
        priority_map = {
            "low": 0,
            "normal": 5,
            "high": 10,
            "critical": 20,
        }
        return priority_map.get(priority.lower(), 5)


class JobStoreAdapter:
    """
    Adapter that wraps JobStore to work with enhanced Job model.

    This allows existing code to continue using the Job model from
    job_management_endpoints.py while transparently storing via JobStore.
    """

    def __init__(self, job_store):
        """
        Initialize adapter.

        Args:
            job_store: JobStore implementation (MemoryJobStore, SqliteJobStore, etc.)
        """
        self.job_store = job_store

    async def create_job(self, job: Any) -> str:
        """Create job (converts to JobRecord)."""
        record = JobAdapter.to_record(job)
        return await self.job_store.enqueue(record)

    async def get_job(self, job_id: str) -> Any | None:
        """Get job (converts from JobRecord)."""
        record = await self.job_store.get(job_id)
        if record is None:
            return None
        return JobAdapter.from_record(record)

    async def update_job(self, job: Any) -> bool:
        """Update job (syncs fields back to record)."""
        # Get current record
        record = await self.job_store.get(job.id)
        if record is None:
            return False

        # Sync fields
        JobAdapter.sync_fields(job, record)

        # Update via JobStore
        return await self.job_store.update_state(
            job.id,
            state=record.state,
            priority=record.priority,
            queued_at=record.queued_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            attempt=record.attempt,
            max_attempts=record.max_attempts,
            cancel_reason=record.cancel_reason,
            cancellation_requested=record.cancellation_requested,
            worker_id=record.worker_id,
            lease_expires_at=record.lease_expires_at,
            last_heartbeat=record.last_heartbeat,
            gpu_req=record.gpu_req,
            gpu_type=record.gpu_type,
            run_id=record.run_id,
            run_dir=record.run_dir,
            provenance_path=record.provenance_path,
            error_message=record.error_message,
            session_id=record.session_id,
            project_id=record.project_id,
            payload_json=record.payload_json,
        )

    async def list_jobs(
        self, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        """List jobs with optional status filter."""
        if status:
            state = JobAdapter._map_status_to_state(status)
            records = await self.job_store.list_by_state(
                state, limit=limit, offset=offset
            )
        else:
            records = await self.job_store.list_all(limit=limit, offset=offset)

        return [JobAdapter.from_record(r) for r in records]

    async def cancel_job(self, job_id: str, reason: str = "User requested") -> bool:
        """Cancel job."""
        return await self.job_store.cancel(job_id, reason)
