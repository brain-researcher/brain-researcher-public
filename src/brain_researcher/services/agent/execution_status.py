"""
Execution Status Tracking System for Brain Researcher Agent.

Provides real-time status updates, progress tracking, ETA calculation,
and status persistence for long-running neuroimaging analyses.
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

import redis
from fakeredis import FakeRedis, FakeServer

logger = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
    """Status states for execution tracking."""

    PENDING = "pending"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class StepStatus(str, Enum):
    """Status for individual execution steps."""

    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExecutionStep:
    """Represents a single step in the execution."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    status: StepStatus = StepStatus.WAITING
    progress: float = 0.0  # 0-100
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    estimated_duration: Optional[float] = None  # seconds
    actual_duration: Optional[float] = None  # seconds
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def start(self):
        """Mark step as started."""
        self.status = StepStatus.RUNNING
        self.started_at = time.time()

    def complete(self, error: Optional[str] = None):
        """Mark step as completed."""
        self.completed_at = time.time()
        if error:
            self.status = StepStatus.FAILED
            self.error = error
        else:
            self.status = StepStatus.COMPLETED
            self.progress = 100.0

        if self.started_at and self.actual_duration is None:
            self.actual_duration = self.completed_at - self.started_at

    def skip(self, reason: str = ""):
        """Mark step as skipped."""
        self.status = StepStatus.SKIPPED
        self.completed_at = time.time()
        if reason:
            self.metadata["skip_reason"] = reason

    def update_progress(self, progress: float):
        """Update step progress."""
        self.progress = min(100.0, max(0.0, progress))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ExecutionMetrics:
    """Metrics for execution tracking."""

    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    total_duration: float = 0.0
    average_step_duration: float = 0.0
    estimated_time_remaining: float = 0.0
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    gpu_usage: Optional[float] = None

    def update_from_steps(self, steps: List[ExecutionStep]):
        """Update metrics from execution steps."""
        self.total_steps = len(steps)
        self.completed_steps = sum(1 for s in steps if s.status == StepStatus.COMPLETED)
        self.failed_steps = sum(1 for s in steps if s.status == StepStatus.FAILED)
        self.skipped_steps = sum(1 for s in steps if s.status == StepStatus.SKIPPED)

        # Calculate durations
        completed_durations = [
            s.actual_duration for s in steps
            if s.actual_duration is not None and s.actual_duration > 0
        ]

        if completed_durations:
            self.average_step_duration = sum(completed_durations) / len(completed_durations)
        else:
            # Use estimated durations if no actual durations yet
            estimated_durations = [
                s.estimated_duration for s in steps
                if s.estimated_duration is not None
            ]
            if estimated_durations:
                self.average_step_duration = sum(estimated_durations) / len(estimated_durations)

        # Estimate remaining time
        pending_steps = sum(1 for s in steps if s.status == StepStatus.WAITING)
        if pending_steps > 0 and self.average_step_duration > 0:
            self.estimated_time_remaining = pending_steps * self.average_step_duration

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ExecutionTracker:
    """Tracks execution status with progress and ETA calculation."""

    def __init__(
        self,
        execution_id: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
        persistence_ttl: int = 86400,  # 24 hours
        update_callback: Optional[callable] = None
    ):
        """
        Initialize execution tracker.

        Args:
            execution_id: Unique execution ID
            redis_client: Redis client for persistence
            persistence_ttl: TTL for status persistence in seconds
            update_callback: Callback for status updates
        """
        self.execution_id = execution_id or str(uuid4())
        self.redis_client = redis_client or self._get_redis_client()
        self.persistence_ttl = persistence_ttl
        self.update_callback = update_callback

        # Execution state
        self.status = ExecutionStatus.PENDING
        self.steps: List[ExecutionStep] = []
        self.current_step_index: Optional[int] = None
        self.metrics = ExecutionMetrics()

        # Timing
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.last_updated: float = time.time()

        # Metadata
        self.metadata: Dict[str, Any] = {}
        self.error: Optional[str] = None
        self.result: Optional[Any] = None

        # Progress
        self.overall_progress: float = 0.0

        # Load existing state if available
        self._load_state()

    def _get_redis_client(self) -> redis.Redis:
        """Get Redis client (real or fake)."""
        try:
            import os
            # Prefer a fake Redis by default in dev/test environments (even if
            # REDIS_URL is set), to avoid state leakage across runs
            # (execution_id may be deterministic). Opt into real Redis by
            # explicitly setting USE_FAKE_REDIS=false (and providing REDIS_URL).
            use_fake = os.environ.get("USE_FAKE_REDIS", "true").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if use_fake:
                return FakeRedis(server=FakeServer())
            redis_url = os.environ.get("REDIS_URL")
            if redis_url:
                return redis.from_url(redis_url)
        except Exception:
            pass
        # Use an isolated FakeServer per tracker to avoid state leakage between tests.
        return FakeRedis(server=FakeServer())

    def add_step(
        self,
        name: str,
        description: str = "",
        estimated_duration: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ExecutionStep:
        """
        Add a step to the execution plan.

        Args:
            name: Step name
            description: Step description
            estimated_duration: Estimated duration in seconds
            metadata: Additional metadata

        Returns:
            Created execution step
        """
        step = ExecutionStep(
            name=name,
            description=description,
            estimated_duration=estimated_duration,
            metadata=metadata or {}
        )
        self.steps.append(step)
        self._update_metrics()
        self._persist_state()
        return step

    def start_execution(self):
        """Start the execution."""
        self.status = ExecutionStatus.RUNNING
        self.started_at = time.time()
        self._trigger_update("execution_started")
        self._persist_state()

    def start_step(self, step_index: Optional[int] = None) -> Optional[ExecutionStep]:
        """
        Start a specific step or the next pending step.

        Args:
            step_index: Optional specific step index

        Returns:
            Started step or None
        """
        if step_index is not None:
            if 0 <= step_index < len(self.steps):
                step = self.steps[step_index]
                self.current_step_index = step_index
            else:
                return None
        else:
            # Find next pending step
            for i, step in enumerate(self.steps):
                if step.status == StepStatus.WAITING:
                    self.current_step_index = i
                    break
            else:
                return None

        if self.current_step_index is not None:
            step = self.steps[self.current_step_index]
            if self.status in {ExecutionStatus.PENDING, ExecutionStatus.INITIALIZING, ExecutionStatus.PAUSED}:
                self.status = ExecutionStatus.RUNNING
                if self.started_at is None:
                    self.started_at = time.time()
            step.start()
            self._update_metrics()
            self._trigger_update("step_started", {"step": step.to_dict()})
            self._persist_state()
            return step

        return None

    def update_step_progress(
        self,
        progress: float,
        step_index: Optional[int] = None,
        message: Optional[str] = None
    ):
        """
        Update progress for current or specific step.

        Args:
            progress: Progress percentage (0-100)
            step_index: Optional specific step index
            message: Optional progress message
        """
        index = step_index if step_index is not None else self.current_step_index

        if index is not None and 0 <= index < len(self.steps):
            step = self.steps[index]
            step.update_progress(progress)

            if message:
                step.metadata["progress_message"] = message

            self._update_metrics()
            self._calculate_overall_progress()
            self._trigger_update("step_progress", {
                "step": step.to_dict(),
                "overall_progress": self.overall_progress
            })
            self._persist_state()

    def get_current_step(self) -> Optional[ExecutionStep]:
        """Return the currently active step, if any."""
        if self.current_step_index is None:
            return None
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def complete_step(
        self,
        step_index: Optional[int] = None,
        error: Optional[str] = None,
        result: Optional[Any] = None
    ):
        """
        Complete a step.

        Args:
            step_index: Optional specific step index
            error: Optional error message
            result: Optional step result
        """
        index = step_index if step_index is not None else self.current_step_index

        if index is not None and 0 <= index < len(self.steps):
            step = self.steps[index]
            step.complete(error)

            if result is not None:
                step.metadata["result"] = result

            self._update_metrics()
            self._calculate_overall_progress()

            # Auto-start next step if no error (only if there was no specific index)
            if not error and self.status == ExecutionStatus.RUNNING and step_index is None:
                self.start_step()

            self._trigger_update("step_completed", {
                "step": step.to_dict(),
                "overall_progress": self.overall_progress
            })
            self._persist_state()

    def skip_step(
        self,
        step_index: int,
        reason: str = ""
    ):
        """
        Skip a step.

        Args:
            step_index: Step index to skip
            reason: Reason for skipping
        """
        if 0 <= step_index < len(self.steps):
            step = self.steps[step_index]
            step.skip(reason)
            self._update_metrics()
            self._calculate_overall_progress()
            self._trigger_update("step_skipped", {
                "step": step.to_dict(),
                "reason": reason
            })
            self._persist_state()

    def complete_execution(
        self,
        error: Optional[str] = None,
        result: Optional[Any] = None
    ):
        """
        Complete the execution.

        Args:
            error: Optional error message
            result: Optional execution result
        """
        self.completed_at = time.time()

        if error:
            self.status = ExecutionStatus.FAILED
            self.error = error
        else:
            self.status = ExecutionStatus.COMPLETED
            self.overall_progress = 100.0

        if result is not None:
            self.result = result

        self.metrics.total_duration = self.completed_at - self.started_at if self.started_at else 0

        self._trigger_update("execution_completed", {
            "status": self.status,
            "duration": self.metrics.total_duration,
            "error": error
        })
        self._persist_state()

    def cancel_execution(self, reason: str = ""):
        """
        Cancel the execution.

        Args:
            reason: Cancellation reason
        """
        self.status = ExecutionStatus.CANCELLED
        self.completed_at = time.time()
        self.metadata["cancellation_reason"] = reason

        # Cancel pending steps
        for step in self.steps:
            if step.status == StepStatus.WAITING:
                step.skip("Execution cancelled")

        self._update_metrics()
        self._trigger_update("execution_cancelled", {"reason": reason})
        self._persist_state()

    def pause_execution(self):
        """Pause the execution."""
        if self.status == ExecutionStatus.RUNNING:
            self.status = ExecutionStatus.PAUSED
            self.metadata["paused_at"] = time.time()
            self._trigger_update("execution_paused")
            self._persist_state()

    def resume_execution(self):
        """Resume paused execution."""
        if self.status == ExecutionStatus.PAUSED:
            self.status = ExecutionStatus.RUNNING
            paused_duration = time.time() - self.metadata.get("paused_at", time.time())
            self.metadata["total_pause_duration"] = \
                self.metadata.get("total_pause_duration", 0) + paused_duration
            self._trigger_update("execution_resumed")
            self._persist_state()

    def retry_execution(self):
        """Retry failed execution."""
        if self.status == ExecutionStatus.FAILED:
            self.status = ExecutionStatus.RETRYING
            self.error = None

            # Reset failed steps
            for step in self.steps:
                if step.status == StepStatus.FAILED:
                    step.status = StepStatus.WAITING
                    step.error = None
                    step.progress = 0.0

            self._update_metrics()
            self._trigger_update("execution_retrying")
            self._persist_state()

            # Start execution again
            self.start_execution()

    def get_status(self) -> Dict[str, Any]:
        """
        Get current execution status.

        Returns:
            Complete status dictionary
        """
        return {
            "execution_id": self.execution_id,
            "status": self.status,
            "overall_progress": self.overall_progress,
            "current_step": self.steps[self.current_step_index].to_dict()
                if self.current_step_index is not None else None,
            "steps": [s.to_dict() for s in self.steps],
            "metrics": self.metrics.to_dict(),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "last_updated": self.last_updated,
            "metadata": self.metadata,
            "error": self.error,
            "eta": self._calculate_eta()
        }

    def get_progress_summary(self) -> Dict[str, Any]:
        """
        Get a summary of execution progress.

        Returns:
            Progress summary
        """
        return {
            "execution_id": self.execution_id,
            "status": self.status,
            "overall_progress": self.overall_progress,
            "steps_completed": f"{self.metrics.completed_steps}/{self.metrics.total_steps}",
            "current_step": self.steps[self.current_step_index].name
                if self.current_step_index is not None else None,
            "eta": self._calculate_eta(),
            "elapsed_time": self._format_duration(
                time.time() - self.started_at if self.started_at else 0
            )
        }

    def _calculate_overall_progress(self):
        """Calculate overall execution progress."""
        if not self.steps:
            self.overall_progress = 0.0
            return

        total_weight = len(self.steps)
        completed_weight = 0.0

        for step in self.steps:
            if step.status == StepStatus.COMPLETED:
                completed_weight += 1.0
            elif step.status == StepStatus.SKIPPED:
                completed_weight += 1.0
            elif step.status == StepStatus.RUNNING:
                completed_weight += step.progress / 100.0

        self.overall_progress = (completed_weight / total_weight) * 100.0

    def _calculate_eta(self) -> Optional[str]:
        """
        Calculate estimated time of arrival.

        Returns:
            ETA as formatted string or None
        """
        if self.metrics.estimated_time_remaining > 0:
            eta_timestamp = time.time() + self.metrics.estimated_time_remaining
            eta_datetime = datetime.fromtimestamp(eta_timestamp)

            # Format based on duration
            if self.metrics.estimated_time_remaining < 60:
                return f"< 1 minute"
            elif self.metrics.estimated_time_remaining < 3600:
                minutes = int(self.metrics.estimated_time_remaining / 60)
                return f"~{minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return eta_datetime.strftime("%H:%M")

        return None

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"

    def _update_metrics(self):
        """Update execution metrics."""
        self.metrics.update_from_steps(self.steps)
        self.last_updated = time.time()

        # Update resource usage if available
        try:
            import psutil
            process = psutil.Process()
            self.metrics.cpu_usage = process.cpu_percent()
            self.metrics.memory_usage = process.memory_percent()
        except ImportError:
            pass

    def _persist_state(self):
        """Persist execution state to Redis."""
        if self.redis_client:
            try:
                key = f"execution:{self.execution_id}"
                state = self.get_status()
                self.redis_client.setex(
                    key,
                    self.persistence_ttl,
                    json.dumps(state, default=str)
                )
            except Exception as e:
                logger.error(f"Failed to persist execution state: {e}")

    def _load_state(self):
        """Load execution state from Redis."""
        if self.redis_client:
            try:
                key = f"execution:{self.execution_id}"
                data = self.redis_client.get(key)
                if data:
                    state = json.loads(data)
                    self._restore_from_state(state)
            except Exception as e:
                logger.error(f"Failed to load execution state: {e}")

    def _restore_from_state(self, state: Dict[str, Any]):
        """Restore execution from persisted state."""
        self.status = ExecutionStatus(state.get("status", ExecutionStatus.PENDING))
        self.overall_progress = state.get("overall_progress", 0.0)
        self.created_at = state.get("created_at", time.time())
        self.started_at = state.get("started_at")
        self.completed_at = state.get("completed_at")
        self.last_updated = state.get("last_updated", time.time())
        self.metadata = state.get("metadata", {})
        self.error = state.get("error")

        # Restore steps
        self.steps = []
        for step_data in state.get("steps", []):
            step = ExecutionStep(**{
                k: v for k, v in step_data.items()
                if k in ExecutionStep.__dataclass_fields__
            })
            step.status = StepStatus(step_data.get("status", StepStatus.WAITING))
            self.steps.append(step)

        # Find current step
        for i, step in enumerate(self.steps):
            if step.status == StepStatus.RUNNING:
                self.current_step_index = i
                break

        # Restore metrics
        metrics_data = state.get("metrics", {})
        self.metrics = ExecutionMetrics(**{
            k: v for k, v in metrics_data.items()
            if k in ExecutionMetrics.__dataclass_fields__
        })

    def _trigger_update(self, event: str, data: Optional[Dict[str, Any]] = None):
        """
        Trigger update callback.

        Args:
            event: Event name
            data: Optional event data
        """
        if self.update_callback:
            try:
                self.update_callback({
                    "execution_id": self.execution_id,
                    "event": event,
                    "timestamp": time.time(),
                    "data": data or {}
                })
            except Exception as e:
                logger.error(f"Update callback failed: {e}")


class AsyncExecutionTracker(ExecutionTracker):
    """Async version of ExecutionTracker with WebSocket support."""

    def __init__(self, *args, **kwargs):
        """Initialize async tracker."""
        super().__init__(*args, **kwargs)
        self.update_listeners: List[callable] = []

    async def add_listener(self, listener: callable):
        """Add an update listener."""
        self.update_listeners.append(listener)

    def _trigger_update(self, event: str, data: Optional[Dict[str, Any]] = None):
        """Trigger update callbacks and async listeners from sync code paths."""
        super()._trigger_update(event, data)

        if not self.update_listeners:
            return

        update = {
            "execution_id": self.execution_id,
            "event": event,
            "timestamp": time.time(),
            "data": data or {},
        }

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        for listener in list(self.update_listeners):
            if asyncio.iscoroutinefunction(listener):
                if loop:
                    loop.create_task(listener(update))
            else:
                listener(update)

    async def remove_listener(self, listener: callable):
        """Remove an update listener."""
        if listener in self.update_listeners:
            self.update_listeners.remove(listener)

    async def _trigger_update_async(self, event: str, data: Optional[Dict[str, Any]] = None):
        """Trigger async update to all listeners."""
        update = {
            "execution_id": self.execution_id,
            "event": event,
            "timestamp": time.time(),
            "data": data or {}
        }

        # Notify all listeners
        tasks = []
        for listener in self.update_listeners:
            if asyncio.iscoroutinefunction(listener):
                tasks.append(listener(update))
            else:
                listener(update)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # Async versions of key methods
    async def start_step_async(self, step_index: Optional[int] = None) -> Optional[ExecutionStep]:
        """Async version of start_step."""
        step = self.start_step(step_index)
        await self._trigger_update_async(
            "step_started", {"step": step.to_dict() if step else None}
        )
        return step

    async def update_step_progress_async(
        self,
        progress: float,
        step_index: Optional[int] = None,
        message: Optional[str] = None
    ):
        """Async version of update_step_progress."""
        self.update_step_progress(progress, step_index, message)

        index = step_index if step_index is not None else self.current_step_index
        step = self.steps[index] if index is not None and 0 <= index < len(self.steps) else None
        await self._trigger_update_async(
            "step_progress",
            {
                "step": step.to_dict() if step else None,
                "overall_progress": self.overall_progress,
            },
        )

    async def complete_step_async(
        self,
        step_index: Optional[int] = None,
        error: Optional[str] = None,
        result: Optional[Any] = None
    ):
        """Async version of complete_step."""
        index = step_index if step_index is not None else self.current_step_index
        # Pass explicit index to avoid auto-starting the next step in async flows.
        self.complete_step(index, error, result)

        step = self.steps[index] if index is not None and 0 <= index < len(self.steps) else None
        await self._trigger_update_async(
            "step_completed",
            {
                "step": step.to_dict() if step else None,
                "overall_progress": self.overall_progress,
            },
        )
