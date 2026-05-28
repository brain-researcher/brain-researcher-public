"""Unit tests for multi-backend runtime support."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from brain_researcher.services.agent.backends import (
    BaseBackend, JobSpecification, JobStatus, JobState,
    ResourceRequirements, BackendCapacity,
    BackendSelector, SelectionStrategy,
    BackendSubmissionError, JobNotFoundError
)


class MockBackend(BaseBackend):
    """Mock backend for testing."""
    
    def __init__(self, name: str, healthy: bool = True, capacity: BackendCapacity = None):
        super().__init__(name, {})
        self._healthy = healthy
        self._capacity = capacity or BackendCapacity(
            total_cpu=16, available_cpu=12,
            total_memory_gb=64, available_memory_gb=48,
            total_gpu=2, available_gpu=1,
            queue_depth=3
        )
        self._submitted_jobs = {}
    
    async def submit_job(self, job_spec: JobSpecification) -> str:
        if not self._healthy:
            raise BackendSubmissionError("Backend unhealthy")
        
        job_id = f"{self.name}-{len(self._submitted_jobs) + 1}"
        self._submitted_jobs[job_id] = JobStatus(
            job_id=job_id,
            backend=self.name,
            state=JobState.PENDING,
            submitted_at=datetime.utcnow()
        )
        return job_id
    
    async def get_job_status(self, job_id: str) -> JobStatus:
        if job_id not in self._submitted_jobs:
            raise JobNotFoundError(f"Job {job_id} not found")
        return self._submitted_jobs[job_id]
    
    async def cancel_job(self, job_id: str) -> bool:
        if job_id not in self._submitted_jobs:
            raise JobNotFoundError(f"Job {job_id} not found")
        self._submitted_jobs[job_id].state = JobState.CANCELLED
        return True
    
    async def get_logs(self, job_id: str) -> str:
        if job_id not in self._submitted_jobs:
            raise JobNotFoundError(f"Job {job_id} not found")
        return f"Logs for job {job_id}"
    
    async def check_health(self) -> bool:
        return self._healthy
    
    async def get_capacity(self) -> BackendCapacity:
        return self._capacity
    
    def estimate_queue_time(self, requirements: ResourceRequirements) -> int:
        return self._capacity.queue_depth * 2
    
    def get_cost_estimate(self, requirements: ResourceRequirements) -> float:
        return requirements.cpu * 0.1


@pytest.fixture
def sample_job_spec():
    """Sample job specification for testing."""
    return JobSpecification(
        name="test-job",
        command="echo 'Hello World'",
        image="ubuntu:latest",
        environment={"TEST": "value"},
        resources=ResourceRequirements(cpu=2.0, memory_gb=8.0)
    )


@pytest.fixture
def mock_backends():
    """Create mock backends for testing."""
    return [
        MockBackend("fast", healthy=True, capacity=BackendCapacity(
            total_cpu=8, available_cpu=6, total_memory_gb=32, available_memory_gb=24,
            total_gpu=1, available_gpu=1, queue_depth=1
        )),
        MockBackend("cheap", healthy=True, capacity=BackendCapacity(
            total_cpu=16, available_cpu=12, total_memory_gb=64, available_memory_gb=48,
            total_gpu=0, available_gpu=0, queue_depth=5
        )),
        MockBackend("powerful", healthy=True, capacity=BackendCapacity(
            total_cpu=32, available_cpu=24, total_memory_gb=128, available_memory_gb=96,
            total_gpu=4, available_gpu=3, queue_depth=2
        )),
        MockBackend("unhealthy", healthy=False)
    ]


class TestJobSpecification:
    """Test JobSpecification class."""
    
    def test_job_spec_creation(self, sample_job_spec):
        """Test job specification creation."""
        assert sample_job_spec.name == "test-job"
        assert sample_job_spec.command == "echo 'Hello World'"
        assert sample_job_spec.image == "ubuntu:latest"
        assert sample_job_spec.resources.cpu == 2.0
        assert sample_job_spec.resources.memory_gb == 8.0
    
    def test_job_spec_defaults(self):
        """Test job specification defaults."""
        spec = JobSpecification(
            name="test",
            command="echo test",
            image="ubuntu:latest",
            environment={},
            resources=ResourceRequirements()
        )
        
        assert spec.working_dir == "/workspace"
        assert spec.output_path == "/outputs"
        assert spec.input_files == []
        assert spec.output_files == []


class TestResourceRequirements:
    """Test ResourceRequirements class."""
    
    def test_resource_defaults(self):
        """Test default resource requirements."""
        resources = ResourceRequirements()
        
        assert resources.cpu == 1.0
        assert resources.memory_gb == 4.0
        assert resources.gpu == 0
        assert resources.storage_gb == 10.0
        assert resources.walltime_minutes == 60
        assert resources.node_count == 1
    
    def test_resource_custom(self):
        """Test custom resource requirements."""
        resources = ResourceRequirements(
            cpu=4.0,
            memory_gb=16.0,
            gpu=2,
            storage_gb=100.0,
            walltime_minutes=120,
            node_count=2
        )
        
        assert resources.cpu == 4.0
        assert resources.memory_gb == 16.0
        assert resources.gpu == 2
        assert resources.storage_gb == 100.0
        assert resources.walltime_minutes == 120
        assert resources.node_count == 2


class TestMockBackend:
    """Test MockBackend implementation."""
    
    @pytest.mark.asyncio
    async def test_submit_job(self, mock_backends, sample_job_spec):
        """Test job submission."""
        backend = mock_backends[0]  # fast backend
        
        job_id = await backend.submit_job(sample_job_spec)
        assert job_id.startswith("fast-")
        
        status = await backend.get_job_status(job_id)
        assert status.state == JobState.PENDING
        assert status.backend == "fast"
    
    @pytest.mark.asyncio
    async def test_job_not_found(self, mock_backends):
        """Test job not found error."""
        backend = mock_backends[0]
        
        with pytest.raises(JobNotFoundError):
            await backend.get_job_status("nonexistent-job")
    
    @pytest.mark.asyncio
    async def test_cancel_job(self, mock_backends, sample_job_spec):
        """Test job cancellation."""
        backend = mock_backends[0]
        
        job_id = await backend.submit_job(sample_job_spec)
        success = await backend.cancel_job(job_id)
        
        assert success
        status = await backend.get_job_status(job_id)
        assert status.state == JobState.CANCELLED
    
    @pytest.mark.asyncio
    async def test_unhealthy_backend(self, mock_backends, sample_job_spec):
        """Test unhealthy backend behavior."""
        backend = mock_backends[3]  # unhealthy backend
        
        assert not await backend.check_health()
        
        with pytest.raises(BackendSubmissionError):
            await backend.submit_job(sample_job_spec)


class TestBackendSelector:
    """Test BackendSelector functionality."""
    
    @pytest.mark.asyncio
    async def test_select_fastest(self, mock_backends, sample_job_spec):
        """Test fastest backend selection."""
        selector = BackendSelector(mock_backends[:3], SelectionStrategy.FASTEST)
        
        backend = await selector.select_backend(sample_job_spec.resources)
        
        # Should select 'fast' backend (queue_depth=1, estimate=2min)
        assert backend.name == "fast"
    
    @pytest.mark.asyncio
    async def test_select_most_available(self, mock_backends, sample_job_spec):
        """Test most available backend selection."""
        selector = BackendSelector(mock_backends[:3], SelectionStrategy.MOST_AVAILABLE)
        
        backend = await selector.select_backend(sample_job_spec.resources)
        
        # Should select backend with highest availability ratio
        assert backend.name in ["fast", "powerful"]  # Both have good ratios
    
    @pytest.mark.asyncio
    async def test_select_with_failover(self, mock_backends, sample_job_spec):
        """Test backend selection with failover."""
        # Include unhealthy backend
        selector = BackendSelector(mock_backends, SelectionStrategy.FASTEST)
        
        backend = await selector.select_with_failover(sample_job_spec.resources)
        
        # Should get a healthy backend
        assert backend.name in ["fast", "cheap", "powerful"]
        assert await backend.check_health()
    
    @pytest.mark.asyncio
    async def test_no_suitable_backend(self, mock_backends):
        """Test when no backend can satisfy requirements."""
        # Request resources too large for any backend
        large_requirements = ResourceRequirements(cpu=1000.0, memory_gb=10000.0)
        
        selector = BackendSelector(mock_backends[:3])
        
        with pytest.raises(Exception):  # Should raise BackendUnavailableError
            await selector.select_backend(large_requirements)
    
    @pytest.mark.asyncio
    async def test_backend_status(self, mock_backends):
        """Test getting backend status."""
        selector = BackendSelector(mock_backends[:3])
        
        status = await selector.get_backend_status()
        
        assert len(status) == 3
        assert "fast" in status
        assert "cheap" in status
        assert "powerful" in status
        
        # Check status structure
        for name, backend_status in status.items():
            assert "name" in backend_status
            assert "type" in backend_status
            assert "healthy" in backend_status
            assert "capacity" in backend_status
    
    def test_load_balancing(self, mock_backends, sample_job_spec):
        """Test load balancing strategy."""
        selector = BackendSelector(mock_backends[:2], SelectionStrategy.LOAD_BALANCED)
        
        # Track selections - this would need async context in real test
        # For now, just verify the strategy exists
        assert selector.strategy == SelectionStrategy.LOAD_BALANCED
    
    def test_preferred_order(self, mock_backends):
        """Test preferred backend order."""
        preferred_order = ["powerful", "fast", "cheap"]
        selector = BackendSelector(
            mock_backends[:3], 
            SelectionStrategy.PREFERRED, 
            preferred_order
        )
        
        assert selector.preferred_order == preferred_order
    
    def test_add_remove_backend(self, mock_backends):
        """Test adding and removing backends."""
        selector = BackendSelector(mock_backends[:2])
        
        # Initially 2 backends
        assert len(selector.backends) == 2
        
        # Add new backend
        new_backend = MockBackend("new-backend")
        selector.add_backend(new_backend)
        assert len(selector.backends) == 3
        assert "new-backend" in selector.backends
        
        # Remove backend
        selector.remove_backend("new-backend")
        assert len(selector.backends) == 2
        assert "new-backend" not in selector.backends
    
    def test_get_backend_by_name(self, mock_backends):
        """Test getting backend by name."""
        selector = BackendSelector(mock_backends[:2])
        
        backend = selector.get_backend_by_name("fast")
        assert backend is not None
        assert backend.name == "fast"
        
        backend = selector.get_backend_by_name("nonexistent")
        assert backend is None