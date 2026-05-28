"""Integration tests for backend API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock

from brain_researcher.services.agent.backends.base_backend import JobNotFoundError

from brain_researcher.services.orchestrator.backend_endpoints import (
    router, initialize_backends, backend_selector
)
from brain_researcher.services.agent.backends import (
    BackendSelector, SelectionStrategy
)


@pytest.fixture
def mock_backend_selector():
    """Mock backend selector for testing."""
    selector = Mock(spec=BackendSelector)
    backend_instance = Mock(name='test-backend')
    backend_instance.get_job_status = AsyncMock(side_effect=JobNotFoundError())
    backend_instance.get_logs = AsyncMock(side_effect=JobNotFoundError())
    backend_instance.cancel_job = AsyncMock(return_value=False)

    selector.backends = {
        'test-backend': backend_instance
    }
    
    # Mock async methods
    selector.get_backend_status = AsyncMock(return_value={
        'test-backend': {
            'name': 'test-backend',
            'type': 'MockBackend',
            'healthy': True,
            'capacity': {
                'total_cpu': 16,
                'available_cpu': 12,
                'total_memory_gb': 64,
                'available_memory_gb': 48,
                'total_gpu': 2,
                'available_gpu': 1,
                'queue_depth': 3
            },
            'usage_count': 0
        }
    })
    
    selector.select_with_failover = AsyncMock()
    selector.get_backend_by_name = Mock(return_value=None)
    selector.clear_cache = Mock()
    
    return selector


@pytest.fixture
def app_with_mock_selector(mock_backend_selector):
    """FastAPI app with mocked backend selector."""
    from fastapi import FastAPI
    from brain_researcher.services.orchestrator.backend_endpoints import get_backend_selector
    
    app = FastAPI()
    app.include_router(router)
    
    # Replace the dependency
    def get_mock_selector():
        return mock_backend_selector
    
    # Override the dependency
    app.dependency_overrides[get_backend_selector] = get_mock_selector
    
    return app


class TestBackendEndpoints:
    """Test backend API endpoints."""
    
    def test_list_available_backends(self, app_with_mock_selector, mock_backend_selector):
        """Test listing available backends."""
        client = TestClient(app_with_mock_selector)
        
        response = client.get("/api/backends/available")
        
        assert response.status_code == 200
        data = response.json()
        assert "backends" in data
        assert "total_count" in data
        assert data["total_count"] == 1
        assert len(data["backends"]) == 1
        
        backend = data["backends"][0]
        assert backend["name"] == "test-backend"
        assert backend["type"] == "MockBackend"
        assert backend["healthy"] is True
    
    def test_submit_job_validation(self, app_with_mock_selector):
        """Test job submission with validation."""
        client = TestClient(app_with_mock_selector)
        
        # Valid job submission
        job_data = {
            "job_spec": {
                "name": "test-job",
                "command": "echo hello",
                "image": "ubuntu:latest",
                "environment": {"TEST": "value"},
                "resources": {
                    "cpu": 2.0,
                    "memory_gb": 8.0,
                    "gpu": 0,
                    "storage_gb": 10.0,
                    "walltime_minutes": 60,
                    "node_count": 1
                }
            }
        }
        
        # This will fail because no real backend, but should pass validation
        response = client.post("/api/backends/submit", json=job_data)
        
        # Should get service unavailable since we don't have real backends
        assert response.status_code in [503, 500]  # Service unavailable or error
    
    def test_submit_job_invalid_data(self, app_with_mock_selector):
        """Test job submission with invalid data."""
        client = TestClient(app_with_mock_selector)
        
        # Invalid job submission (missing required fields)
        invalid_job = {
            "job_spec": {
                "name": "",  # Empty name should fail validation
                "command": "echo hello",
                "image": "ubuntu:latest"
            }
        }
        
        response = client.post("/api/backends/submit", json=invalid_job)
        
        # Should get validation error
        assert response.status_code == 422  # Unprocessable Entity
    
    def test_get_job_status_not_found(self, app_with_mock_selector):
        """Test getting status of non-existent job."""
        client = TestClient(app_with_mock_selector)
        
        response = client.get("/api/backends/job/nonexistent-job")
        
        # Should get not found
        assert response.status_code == 404
    
    def test_cancel_job_not_found(self, app_with_mock_selector):
        """Test cancelling non-existent job."""
        client = TestClient(app_with_mock_selector)
        
        response = client.delete("/api/backends/job/nonexistent-job")
        
        # Should get not found
        assert response.status_code == 404
    
    def test_get_job_logs_not_found(self, app_with_mock_selector):
        """Test getting logs of non-existent job."""
        client = TestClient(app_with_mock_selector)
        
        response = client.get("/api/backends/job/nonexistent-job/logs")
        
        # Should get not found
        assert response.status_code == 404
    
    def test_health_check(self, app_with_mock_selector, mock_backend_selector):
        """Test backend health check endpoint."""
        client = TestClient(app_with_mock_selector)
        
        response = client.post("/api/backends/health-check")
        
        assert response.status_code == 200
        data = response.json()
        assert "overall_health" in data
        assert "healthy_backends" in data
        assert "total_backends" in data
        assert "backends" in data
        
        # Should have called clear_cache
        mock_backend_selector.clear_cache.assert_called_once()
    
    def test_clear_cache(self, app_with_mock_selector, mock_backend_selector):
        """Test cache clearing endpoint."""
        client = TestClient(app_with_mock_selector)
        
        response = client.post("/api/backends/cache/clear")
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Cache cleared successfully"
        
        # Should have called clear_cache
        mock_backend_selector.clear_cache.assert_called_once()


class TestBackendInitialization:
    """Test backend initialization."""
    
    def test_initialize_empty_config(self):
        """Test initialization with empty config."""
        config = {
            'backends': {},
            'default_strategy': 'most_available',
            'preferred_order': []
        }
        
        selector = initialize_backends(config)
        
        assert isinstance(selector, BackendSelector)
        assert len(selector.backends) == 0
        assert selector.strategy == SelectionStrategy.MOST_AVAILABLE
    
    def test_initialize_with_disabled_backends(self):
        """Test initialization with disabled backends."""
        config = {
            'backends': {
                'kubernetes': {'enabled': False},
                'slurm': {'enabled': False},
                'aws_batch': {'enabled': False}
            },
            'default_strategy': 'fastest',
            'preferred_order': ['kubernetes', 'slurm']
        }
        
        selector = initialize_backends(config)
        
        assert isinstance(selector, BackendSelector)
        assert len(selector.backends) == 0
        assert selector.strategy == SelectionStrategy.FASTEST
        assert selector.preferred_order == ['kubernetes', 'slurm']
    
    def test_initialize_with_invalid_strategy(self):
        """Test initialization with invalid strategy."""
        config = {
            'backends': {},
            'default_strategy': 'invalid_strategy',
            'preferred_order': []
        }
        
        # Should handle invalid strategy gracefully
        try:
            selector = initialize_backends(config)
            # If it doesn't raise an exception, check default behavior
            assert isinstance(selector, BackendSelector)
        except ValueError:
            # Expected if strategy validation is strict
            pass


@pytest.mark.asyncio
class TestAsyncEndpoints:
    """Test async behavior of endpoints."""
    
    async def test_backend_selector_async_methods(self, mock_backend_selector):
        """Test that async methods are properly awaited."""
        
        # Test that async methods can be called
        status = await mock_backend_selector.get_backend_status()
        assert isinstance(status, dict)
        
        # Verify mock was called
        mock_backend_selector.get_backend_status.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
