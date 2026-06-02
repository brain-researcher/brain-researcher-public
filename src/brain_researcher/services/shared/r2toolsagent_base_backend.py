"""Abstract base class for execution backends.

Relocated to ``services.shared`` so tool-layer backends can depend on the
backend contracts without importing up into ``services.agent``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

# ``ResourceRequirements`` and ``JobSpecification`` are pure data classes shared
# with the tools layer (``tools.neurodesk_compiler``). They live in
# ``services.shared`` so the tools layer can reference them without a
# ``tools -> agent`` import back-edge; they are re-exported here for backward
# compatibility.
from brain_researcher.services.shared.r2toolsagent_backend_specs import (  # noqa: F401
    JobSpecification,
    ResourceRequirements,
)


class JobState(Enum):
    """Job execution states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobStatus:
    """Job status information."""

    job_id: str
    backend: str
    state: JobState
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float | None = None
    message: str | None = None
    exit_code: int | None = None
    resource_usage: dict[str, Any] | None = None


@dataclass
class BackendCapacity:
    """Backend resource capacity information."""

    total_cpu: float
    available_cpu: float
    total_memory_gb: float
    available_memory_gb: float
    total_gpu: int
    available_gpu: int
    queue_depth: int


class BaseBackend(ABC):
    """Abstract base class for execution backends."""

    def __init__(self, name: str, config: dict[str, Any]):
        """Initialize backend with configuration.

        Args:
            name: Backend identifier
            config: Backend-specific configuration
        """
        self.name = name
        self.config = config
        self._jobs: dict[str, JobStatus] = {}

    @abstractmethod
    async def submit_job(self, job_spec: JobSpecification) -> str:
        """Submit a job for execution.

        Args:
            job_spec: Job specification with requirements and commands

        Returns:
            Job ID for tracking

        Raises:
            BackendSubmissionError: If job submission fails
        """
        pass

    @abstractmethod
    async def get_job_status(self, job_id: str) -> JobStatus:
        """Get current status of a job.

        Args:
            job_id: Job identifier

        Returns:
            Current job status

        Raises:
            JobNotFoundError: If job doesn't exist
        """
        pass

    @abstractmethod
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job.

        Args:
            job_id: Job identifier

        Returns:
            True if cancellation successful

        Raises:
            JobNotFoundError: If job doesn't exist
        """
        pass

    @abstractmethod
    async def get_logs(self, job_id: str) -> str:
        """Retrieve job execution logs.

        Args:
            job_id: Job identifier

        Returns:
            Job logs as string

        Raises:
            JobNotFoundError: If job doesn't exist
        """
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """Check if backend is healthy and available.

        Returns:
            True if backend is available
        """
        pass

    @abstractmethod
    async def get_capacity(self) -> BackendCapacity:
        """Get current backend capacity and utilization.

        Returns:
            Current resource capacity information
        """
        pass

    def supports_requirements(self, requirements: ResourceRequirements) -> bool:
        """Check if backend can satisfy resource requirements.

        Args:
            requirements: Resource requirements to check

        Returns:
            True if requirements can be satisfied
        """
        # Default implementation - can be overridden by specific backends
        return True

    def estimate_queue_time(self, requirements: ResourceRequirements) -> int:
        """Estimate queue time in minutes for given requirements.

        Args:
            requirements: Resource requirements

        Returns:
            Estimated queue time in minutes
        """
        # Default implementation - should be overridden by specific backends
        return 0

    def get_cost_estimate(self, requirements: ResourceRequirements) -> float:
        """Estimate cost for running job with given requirements.

        Args:
            requirements: Resource requirements

        Returns:
            Estimated cost in USD
        """
        # Default implementation - should be overridden by specific backends
        return 0.0


class BackendError(Exception):
    """Base exception for backend operations."""

    pass


class BackendSubmissionError(BackendError):
    """Exception raised when job submission fails."""

    pass


class JobNotFoundError(BackendError):
    """Exception raised when job is not found."""

    pass


class BackendUnavailableError(BackendError):
    """Exception raised when backend is unavailable."""

    pass


class BackendConfigError(BackendError):
    """Exception raised when backend configuration is invalid."""

    pass
