"""Abstract base class for execution backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime


class JobState(Enum):
    """Job execution states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ResourceRequirements:
    """Resource requirements for job execution."""
    cpu: float = 1.0
    memory_gb: float = 4.0
    gpu: int = 0
    storage_gb: float = 10.0
    walltime_minutes: int = 60
    node_count: int = 1


@dataclass
class JobSpecification:
    """Job specification for backend execution."""
    name: str
    command: str
    image: str
    environment: Dict[str, str]
    resources: ResourceRequirements
    working_dir: str = "/workspace"
    output_path: str = "/outputs"
    input_files: List[str] = None
    output_files: List[str] = None
    
    def __post_init__(self):
        if self.input_files is None:
            self.input_files = []
        if self.output_files is None:
            self.output_files = []


@dataclass
class JobStatus:
    """Job status information."""
    job_id: str
    backend: str
    state: JobState
    submitted_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[float] = None
    message: Optional[str] = None
    exit_code: Optional[int] = None
    resource_usage: Optional[Dict[str, Any]] = None


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
    
    def __init__(self, name: str, config: Dict[str, Any]):
        """Initialize backend with configuration.
        
        Args:
            name: Backend identifier
            config: Backend-specific configuration
        """
        self.name = name
        self.config = config
        self._jobs: Dict[str, JobStatus] = {}
    
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