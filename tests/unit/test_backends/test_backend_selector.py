"""Unit tests for backend selector."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from brain_researcher.services.agent.backends.backend_selector import (
    BackendSelector, SelectionStrategy, BackendScore
)
from brain_researcher.services.agent.backends.base_backend import (
    BaseBackend, ResourceRequirements, BackendCapacity, JobState, JobStatus,
    BackendUnavailableError
)


class MockBackend(BaseBackend):
    """Mock backend for testing."""
    
    def __init__(self, name, capacity=None, queue_time=0, cost=0.0, healthy=True):
        super().__init__(name, {})
        self._capacity = capacity or BackendCapacity(
            total_cpu=16.0, available_cpu=12.0,
            total_memory_gb=64.0, available_memory_gb=48.0,
            total_gpu=2, available_gpu=1,
            queue_depth=5
        )
        self._queue_time = queue_time
        self._cost = cost
        self._healthy = healthy
        
    async def submit_job(self, job_spec):
        return f"{self.name}-job-12345"
        
    async def get_job_status(self, job_id):
        return JobStatus(
            job_id=job_id,
            backend=self.name,
            state=JobState.RUNNING,
            submitted_at=datetime.now()
        )
        
    async def cancel_job(self, job_id):
        return True
        
    async def get_logs(self, job_id):
        return f"Logs for job {job_id} on {self.name}"
        
    async def check_health(self):
        return self._healthy
        
    async def get_capacity(self):
        return self._capacity
        
    def estimate_queue_time(self, requirements):
        return self._queue_time
        
    def get_cost_estimate(self, requirements):
        return self._cost


@pytest.fixture
def sample_requirements():
    """Sample resource requirements."""
    return ResourceRequirements(
        cpu=4.0,
        memory_gb=16.0,
        gpu=1,
        storage_gb=50.0,
        walltime_minutes=120
    )


@pytest.fixture
def high_requirements():
    """High resource requirements."""
    return ResourceRequirements(
        cpu=32.0,
        memory_gb=128.0,
        gpu=4,
        storage_gb=500.0,
        walltime_minutes=480
    )


@pytest.fixture
def backends_list():
    """List of mock backends with different characteristics."""
    return [
        MockBackend(
            "fast-backend",
            capacity=BackendCapacity(32.0, 24.0, 128.0, 96.0, 4, 3, 2),
            queue_time=5,
            cost=1.50,
            healthy=True
        ),
        MockBackend(
            "cheap-backend", 
            capacity=BackendCapacity(16.0, 12.0, 64.0, 48.0, 2, 1, 8),
            queue_time=30,
            cost=0.75,
            healthy=True
        ),
        MockBackend(
            "powerful-backend",
            capacity=BackendCapacity(64.0, 48.0, 256.0, 192.0, 8, 6, 3),
            queue_time=15,
            cost=3.00,
            healthy=True
        ),
        MockBackend(
            "unreliable-backend",
            capacity=BackendCapacity(8.0, 4.0, 32.0, 16.0, 1, 0, 12),
            queue_time=60,
            cost=0.50,
            healthy=False
        )
    ]


class TestBackendSelector:
    """Test cases for BackendSelector."""

    def test_init_success(self, backends_list):
        """Test successful initialization."""
        selector = BackendSelector(
            backends=backends_list,
            strategy=SelectionStrategy.MOST_AVAILABLE,
            preferred_order=['fast-backend', 'powerful-backend']
        )
        
        assert len(selector.backends) == 4
        assert selector.strategy == SelectionStrategy.MOST_AVAILABLE
        assert selector.preferred_order == ['fast-backend', 'powerful-backend']
        assert 'fast-backend' in selector.backends
        assert 'cheap-backend' in selector.backends

    def test_init_default_strategy(self, backends_list):
        """Test initialization with default strategy."""
        selector = BackendSelector(backends=backends_list)
        
        assert selector.strategy == SelectionStrategy.MOST_AVAILABLE
        assert selector.preferred_order == []

    @pytest.mark.asyncio
    async def test_select_backend_most_available(self, backends_list, sample_requirements):
        """Test backend selection with MOST_AVAILABLE strategy."""
        selector = BackendSelector(backends=backends_list, strategy=SelectionStrategy.MOST_AVAILABLE)
        
        backend = await selector.select_backend(sample_requirements)
        
        # Should select backend with highest availability ratio
        # powerful-backend: min(48/64, 192/256) = min(0.75, 0.75) = 0.75
        assert backend.name == "powerful-backend"

    @pytest.mark.asyncio
    async def test_select_backend_fastest(self, backends_list, sample_requirements):
        """Test backend selection with FASTEST strategy."""
        selector = BackendSelector(backends=backends_list, strategy=SelectionStrategy.FASTEST)
        
        backend = await selector.select_backend(sample_requirements)
        
        # Should select backend with shortest queue time
        assert backend.name == "fast-backend"  # queue_time = 5

    @pytest.mark.asyncio
    async def test_select_backend_cheapest(self, backends_list, sample_requirements):
        """Test backend selection with CHEAPEST strategy."""
        selector = BackendSelector(backends=backends_list, strategy=SelectionStrategy.CHEAPEST)
        
        backend = await selector.select_backend(sample_requirements)
        
        # Should select backend with lowest cost (excluding unhealthy ones)
        assert backend.name == "cheap-backend"  # cost = 0.75

    @pytest.mark.asyncio
    async def test_select_backend_preferred(self, backends_list, sample_requirements):
        """Test backend selection with PREFERRED strategy."""
        preferred_order = ['cheap-backend', 'powerful-backend', 'fast-backend']
        selector = BackendSelector(
            backends=backends_list, 
            strategy=SelectionStrategy.PREFERRED,
            preferred_order=preferred_order
        )
        
        backend = await selector.select_backend(sample_requirements)
        
        # Should select first available backend in preferred order
        assert backend.name == "cheap-backend"

    @pytest.mark.asyncio
    async def test_select_backend_load_balanced(self, backends_list, sample_requirements):
        """Test backend selection with LOAD_BALANCED strategy."""
        selector = BackendSelector(backends=backends_list, strategy=SelectionStrategy.LOAD_BALANCED)
        
        # Simulate previous usage
        selector._last_selected = {
            'fast-backend': 5,
            'powerful-backend': 2,
            'cheap-backend': 0
        }
        
        backend = await selector.select_backend(sample_requirements)
        
        # Should select backend with least recent usage (cheap-backend has 0 usage)
        assert backend.name == "cheap-backend"

    @pytest.mark.asyncio
    async def test_select_backend_excluded(self, backends_list, sample_requirements):
        """Test backend selection with excluded backends."""
        selector = BackendSelector(backends=backends_list, strategy=SelectionStrategy.FASTEST)
        
        # Exclude the fastest backend
        backend = await selector.select_backend(
            sample_requirements, 
            excluded_backends=['fast-backend']
        )
        
        # Should select next fastest available backend
        assert backend.name != "fast-backend"
        assert backend.name in ["powerful-backend", "cheap-backend"]  # Healthy backends

    @pytest.mark.asyncio
    async def test_select_backend_insufficient_resources(self, backends_list, high_requirements):
        """Test backend selection when resources are insufficient."""
        # Create backends with limited capacity
        limited_backends = [
            MockBackend(
                "small-backend-1",
                capacity=BackendCapacity(8.0, 4.0, 32.0, 16.0, 1, 0, 5)
            ),
            MockBackend(
                "small-backend-2", 
                capacity=BackendCapacity(16.0, 8.0, 64.0, 32.0, 2, 1, 3)
            )
        ]
        
        selector = BackendSelector(backends=limited_backends)
        
        with pytest.raises(BackendUnavailableError, match="No backends can satisfy requirements"):
            await selector.select_backend(high_requirements)

    @pytest.mark.asyncio
    async def test_select_backend_no_healthy_backends(self, sample_requirements):
        """Test backend selection when no backends are healthy."""
        unhealthy_backends = [
            MockBackend("backend-1", healthy=False),
            MockBackend("backend-2", healthy=False)
        ]
        
        selector = BackendSelector(backends=unhealthy_backends)
        
        with pytest.raises(BackendUnavailableError, match="No backends can satisfy requirements"):
            await selector.select_backend(sample_requirements)

    @pytest.mark.asyncio
    async def test_select_backend_no_backends_available(self, sample_requirements):
        """Test backend selection when no backends are available."""
        selector = BackendSelector(backends=[])
        
        with pytest.raises(BackendUnavailableError, match="No backends available"):
            await selector.select_backend(sample_requirements)

    @pytest.mark.asyncio
    async def test_select_with_failover_success(self, backends_list, sample_requirements):
        """Test successful backend selection with failover."""
        selector = BackendSelector(backends=backends_list)
        
        backend = await selector.select_with_failover(sample_requirements, max_attempts=3)
        
        assert backend is not None
        assert backend.name in [b.name for b in backends_list if b._healthy]

    @pytest.mark.asyncio
    async def test_select_with_failover_health_check_failure(self, backends_list, sample_requirements):
        """Test failover when health check fails."""
        selector = BackendSelector(backends=backends_list)
        
        # Mock the first selected backend to fail health check
        original_check_health = backends_list[0].check_health
        backends_list[0].check_health = AsyncMock(return_value=False)
        
        backend = await selector.select_with_failover(sample_requirements, max_attempts=3)
        
        # Should get a different backend after failover
        assert backend is not None
        assert backend != backends_list[0]
        
        # Restore original method
        backends_list[0].check_health = original_check_health

    @pytest.mark.asyncio
    async def test_select_with_failover_all_fail(self, sample_requirements):
        """Test failover when all backends fail."""
        failing_backends = [
            MockBackend("backend-1", healthy=False),
            MockBackend("backend-2", healthy=False)
        ]
        
        selector = BackendSelector(backends=failing_backends)
        
        with pytest.raises(BackendUnavailableError, match="All backends failed after"):
            await selector.select_with_failover(sample_requirements, max_attempts=2)

    @pytest.mark.asyncio
    async def test_score_backends(self, backends_list, sample_requirements):
        """Test backend scoring logic."""
        selector = BackendSelector(backends=backends_list)
        
        scores = await selector._score_backends(backends_list, sample_requirements)
        
        assert len(scores) == 4
        
        # Verify all healthy backends have scores > 0
        healthy_scores = [s for s in scores if s.health_status]
        assert len(healthy_scores) == 3  # Excluding unreliable-backend
        
        for score in healthy_scores:
            assert score.score > 0
            assert score.can_satisfy is True
            assert score.queue_time >= 0
            assert score.cost >= 0.0

    @pytest.mark.asyncio
    async def test_score_backend_individual(self, sample_requirements):
        """Test individual backend scoring."""
        backend = MockBackend(
            "test-backend",
            capacity=BackendCapacity(16.0, 12.0, 64.0, 48.0, 2, 1, 5),
            queue_time=10,
            cost=2.0
        )
        
        selector = BackendSelector(backends=[backend])
        
        score = await selector._score_backend(backend, sample_requirements)
        
        assert score.backend == backend
        assert score.can_satisfy is True
        assert score.health_status is True
        assert score.queue_time == 10
        assert score.cost == 2.0
        assert 0 <= score.availability_ratio <= 1
        assert score.score > 0

    def test_calculate_score(self, backends_list):
        """Test score calculation algorithm."""
        selector = BackendSelector(backends=backends_list)
        
        # Test perfect conditions
        perfect_score = selector._calculate_score(
            availability_ratio=1.0,
            queue_time=0,
            cost=0.0,
            queue_depth=0
        )
        assert perfect_score == 100.0
        
        # Test poor conditions
        poor_score = selector._calculate_score(
            availability_ratio=0.0,
            queue_time=120,  # 2 hours
            cost=20.0,       # High cost
            queue_depth=200  # Deep queue
        )
        assert poor_score == 0.0
        
        # Test mixed conditions
        mixed_score = selector._calculate_score(
            availability_ratio=0.5,
            queue_time=30,   # 30 minutes
            cost=5.0,        # Moderate cost
            queue_depth=50   # Moderate queue
        )
        assert 0 < mixed_score < 100

    def test_apply_strategy_fastest(self, backends_list):
        """Test strategy application for FASTEST."""
        selector = BackendSelector(backends=backends_list)
        
        # Create backend scores
        scores = [
            BackendScore(backends_list[0], 80.0, 5, 1.50, 0.75, True, True, "Available"),
            BackendScore(backends_list[1], 70.0, 30, 0.75, 0.75, True, True, "Available"),
            BackendScore(backends_list[2], 90.0, 15, 3.00, 0.75, True, True, "Available")
        ]
        
        selected = selector._apply_strategy(scores, SelectionStrategy.FASTEST)
        
        assert selected.queue_time == 5  # Fastest queue time

    def test_apply_strategy_cheapest(self, backends_list):
        """Test strategy application for CHEAPEST."""
        selector = BackendSelector(backends=backends_list)
        
        scores = [
            BackendScore(backends_list[0], 80.0, 5, 1.50, 0.75, True, True, "Available"),
            BackendScore(backends_list[1], 70.0, 30, 0.75, 0.75, True, True, "Available"),
            BackendScore(backends_list[2], 90.0, 15, 3.00, 0.75, True, True, "Available")
        ]
        
        selected = selector._apply_strategy(scores, SelectionStrategy.CHEAPEST)
        
        assert selected.cost == 0.75  # Cheapest option

    def test_apply_strategy_preferred_order(self, backends_list):
        """Test strategy application for PREFERRED with order."""
        preferred_order = ['powerful-backend', 'fast-backend']
        selector = BackendSelector(backends=backends_list, preferred_order=preferred_order)
        
        scores = [
            BackendScore(backends_list[0], 80.0, 5, 1.50, 0.75, True, True, "Available"),   # fast-backend
            BackendScore(backends_list[1], 70.0, 30, 0.75, 0.75, True, True, "Available"),  # cheap-backend
            BackendScore(backends_list[2], 90.0, 15, 3.00, 0.75, True, True, "Available")   # powerful-backend
        ]
        
        selected = selector._apply_strategy(scores, SelectionStrategy.PREFERRED)
        
        assert selected.backend.name == "powerful-backend"  # First in preferred order

    def test_apply_strategy_load_balanced(self, backends_list):
        """Test strategy application for LOAD_BALANCED."""
        selector = BackendSelector(backends=backends_list)
        
        # Set usage counts
        selector._last_selected = {
            'fast-backend': 10,     # Heavily used
            'cheap-backend': 2,     # Lightly used
            'powerful-backend': 5   # Moderately used
        }
        
        scores = [
            BackendScore(backends_list[0], 80.0, 5, 1.50, 0.75, True, True, "Available"),   # fast-backend
            BackendScore(backends_list[1], 70.0, 30, 0.75, 0.75, True, True, "Available"),  # cheap-backend
            BackendScore(backends_list[2], 90.0, 15, 3.00, 0.75, True, True, "Available")   # powerful-backend
        ]
        
        selected = selector._apply_strategy(scores, SelectionStrategy.LOAD_BALANCED)
        
        # Should favor lightly used backend despite lower base score
        assert selected.backend.name == "cheap-backend"

    @pytest.mark.asyncio
    async def test_get_cached_health(self, backends_list):
        """Test health status caching."""
        selector = BackendSelector(backends=backends_list)
        backend = backends_list[0]
        
        # First call should query backend
        health1 = await selector._get_cached_health(backend)
        assert health1 is True
        
        # Second call should use cache
        with patch.object(backend, 'check_health', AsyncMock(return_value=False)) as mock_health:
            health2 = await selector._get_cached_health(backend)
            assert health2 is True  # Should use cached value
            mock_health.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_cached_health_expired(self, backends_list):
        """Test health cache expiration."""
        selector = BackendSelector(backends=backends_list)
        backend = backends_list[0]
        
        # Manually set expired cache entry
        import time
        selector._health_cache[backend.name] = (True, time.time() - 120)  # 2 minutes ago
        
        # Should fetch fresh health status
        with patch.object(backend, 'check_health', AsyncMock(return_value=False)) as mock_health:
            health = await selector._get_cached_health(backend)
            assert health is False
            mock_health.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cached_capacity(self, backends_list):
        """Test capacity information caching."""
        selector = BackendSelector(backends=backends_list)
        backend = backends_list[0]
        
        # First call should query backend
        capacity1 = await selector._get_cached_capacity(backend)
        assert capacity1.total_cpu == 32.0
        
        # Second call should use cache
        with patch.object(backend, 'get_capacity', AsyncMock()) as mock_capacity:
            capacity2 = await selector._get_cached_capacity(backend)
            assert capacity2.total_cpu == 32.0  # Should use cached value
            mock_capacity.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_backend_status(self, backends_list):
        """Test getting status of all backends."""
        selector = BackendSelector(backends=backends_list)
        
        status = await selector.get_backend_status()
        
        assert len(status) == 4
        assert 'fast-backend' in status
        assert 'cheap-backend' in status
        assert 'powerful-backend' in status
        assert 'unreliable-backend' in status
        
        # Verify status structure
        fast_status = status['fast-backend']
        assert fast_status['name'] == 'fast-backend'
        assert fast_status['type'] == 'MockBackend'
        assert fast_status['healthy'] is True
        assert 'capacity' in fast_status
        assert fast_status['capacity']['total_cpu'] == 32.0

    @pytest.mark.asyncio
    async def test_get_backend_status_with_error(self, backends_list):
        """Test backend status with error handling."""
        selector = BackendSelector(backends=backends_list)
        
        # Make one backend raise an exception
        backends_list[0].check_health = AsyncMock(side_effect=Exception("Connection failed"))
        
        status = await selector.get_backend_status()
        
        fast_status = status['fast-backend']
        assert fast_status['healthy'] is False
        assert 'error' in fast_status
        assert 'Connection failed' in fast_status['error']

    def test_clear_cache(self, backends_list):
        """Test cache clearing."""
        selector = BackendSelector(backends=backends_list)
        
        # Populate caches
        import time
        selector._health_cache['test'] = (True, time.time())
        selector._capacity_cache['test'] = (Mock(), time.time())
        
        assert len(selector._health_cache) == 1
        assert len(selector._capacity_cache) == 1
        
        selector.clear_cache()
        
        assert len(selector._health_cache) == 0
        assert len(selector._capacity_cache) == 0

    def test_add_backend(self, backends_list):
        """Test adding a new backend."""
        selector = BackendSelector(backends=backends_list)
        
        new_backend = MockBackend("new-backend")
        selector.add_backend(new_backend)
        
        assert 'new-backend' in selector.backends
        assert selector.backends['new-backend'] == new_backend

    def test_remove_backend(self, backends_list):
        """Test removing a backend."""
        selector = BackendSelector(backends=backends_list)
        
        # Add some cache entries
        import time
        selector._health_cache['fast-backend'] = (True, time.time())
        selector._capacity_cache['fast-backend'] = (Mock(), time.time())
        selector._last_selected['fast-backend'] = 5
        
        selector.remove_backend('fast-backend')
        
        assert 'fast-backend' not in selector.backends
        assert 'fast-backend' not in selector._health_cache
        assert 'fast-backend' not in selector._capacity_cache
        assert 'fast-backend' not in selector._last_selected

    def test_get_backend_by_name(self, backends_list):
        """Test getting backend by name."""
        selector = BackendSelector(backends=backends_list)
        
        backend = selector.get_backend_by_name('fast-backend')
        assert backend is not None
        assert backend.name == 'fast-backend'
        
        non_existent = selector.get_backend_by_name('non-existent')
        assert non_existent is None

    @pytest.mark.asyncio
    async def test_concurrent_backend_scoring(self, backends_list, sample_requirements):
        """Test that backend scoring happens concurrently."""
        selector = BackendSelector(backends=backends_list)
        
        # Track call order and timing
        call_times = []
        
        original_score_backend = selector._score_backend
        async def mock_score_backend(backend, requirements):
            call_times.append((backend.name, asyncio.get_event_loop().time()))
            await asyncio.sleep(0.1)  # Simulate work
            return await original_score_backend(backend, requirements)
        
        with patch.object(selector, '_score_backend', side_effect=mock_score_backend):
            await selector._score_backends(backends_list, sample_requirements)
        
        # Verify all backends were scored concurrently (calls should start around same time)
        assert len(call_times) == 4
        start_times = [time for _, time in call_times]
        max_start_diff = max(start_times) - min(start_times)
        assert max_start_diff < 0.05  # Should start within 50ms of each other

    @pytest.mark.asyncio
    async def test_backend_scoring_error_handling(self, sample_requirements):
        """Test error handling during backend scoring."""
        failing_backend = MockBackend("failing-backend")
        failing_backend.check_health = AsyncMock(side_effect=Exception("Health check failed"))
        
        selector = BackendSelector(backends=[failing_backend])
        
        scores = await selector._score_backends([failing_backend], sample_requirements)
        
        assert len(scores) == 1
        score = scores[0]
        assert score.can_satisfy is False
        assert score.health_status is False
        assert "Health check failed" in score.reason

    @pytest.mark.asyncio
    async def test_supports_requirements_validation(self, backends_list, sample_requirements):
        """Test requirements validation during selection."""
        # Create backend that doesn't support requirements
        limited_backend = MockBackend("limited-backend")
        limited_backend.supports_requirements = Mock(return_value=False)
        
        selector = BackendSelector(backends=[limited_backend])
        
        with pytest.raises(BackendUnavailableError, match="No backends can satisfy requirements"):
            await selector.select_backend(sample_requirements)

    @pytest.mark.asyncio
    async def test_selection_with_runtime_strategy_override(self, backends_list, sample_requirements):
        """Test strategy override at selection time."""
        # Initialize with one strategy
        selector = BackendSelector(backends=backends_list, strategy=SelectionStrategy.MOST_AVAILABLE)
        
        # Override strategy at selection time
        backend = await selector.select_backend(sample_requirements, strategy=SelectionStrategy.CHEAPEST)
        
        # Should use the overridden strategy (cheapest)
        assert backend.name == "cheap-backend"