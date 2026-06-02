"""
Pytest configuration and fixtures for load balancing tests.

The `api-gateway` fixture entries in this module cover legacy standalone
compatibility only.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, Mock

import docker
import pytest
import redis
import requests

# Test configuration
PLATFORM = os.getenv("PLATFORM", "swarm")
NAMESPACE = os.getenv("NAMESPACE", "brain-researcher-test")
HAPROXY_STATS_URL = os.getenv("HAPROXY_STATS_URL", "http://localhost:8080/stats")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")


@dataclass
class TestConfig:
    """Test configuration settings."""

    platform: str = PLATFORM
    namespace: str = NAMESPACE
    haproxy_stats_url: str = HAPROXY_STATS_URL
    redis_url: str = REDIS_URL
    prometheus_url: str = PROMETHEUS_URL
    load_test_duration: int = 30  # seconds
    load_test_vus: int = 10  # virtual users
    stress_test_vus: int = 50
    timeout: int = 60


@pytest.fixture(scope="session")
def test_config() -> TestConfig:
    """Provide test configuration."""
    return TestConfig()


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def docker_client():
    """Docker client for service management."""
    try:
        client = docker.from_env()
        yield client
    except Exception:
        yield None


@pytest.fixture(scope="session")
def redis_client(test_config: TestConfig):
    """Redis client for metrics storage."""
    try:
        client = redis.from_url(test_config.redis_url)
        client.ping()  # Test connection
        yield client
    except Exception:
        yield None


@pytest.fixture(scope="function")
def clean_redis(redis_client):
    """Clean Redis state before and after tests."""
    if redis_client:
        # Clean before test
        keys_to_clean = ["queue:*", "metrics:*", "autoscaler:*", "test:*"]
        for pattern in keys_to_clean:
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)

    yield redis_client

    if redis_client:
        # Clean after test
        for pattern in keys_to_clean:
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)


@pytest.fixture(scope="session")
def mock_services():
    """Mock service endpoints for testing."""
    services = {
        "orchestrator": "http://mock-orchestrator:3001",
        "br_kg": "http://mock-br_kg:5000",
        "agent": "http://mock-agent:8000",
        "web-ui": "http://mock-web-ui:3000",
        "api-gateway": "http://mock-api-gateway:8080",  # legacy standalone compatibility surface
    }
    return services


@pytest.fixture(scope="function")
def mock_metrics_data():
    """Generate mock metrics data for testing."""
    base_time = datetime.utcnow()

    metrics = []
    for i in range(10):
        timestamp = base_time - timedelta(minutes=i * 5)
        metrics.append(
            {
                "timestamp": timestamp.isoformat(),
                "cpu_percent": 50 + (i * 2),  # Increasing CPU
                "memory_percent": 40 + (i * 1.5),  # Increasing memory
                "active_connections": 10 + (i * 2),
                "response_time_ms": 100 + (i * 10),
                "queue_depth": i * 3,
                "error_rate": i * 0.1,
            }
        )

    return list(reversed(metrics))  # Chronological order


@pytest.fixture(scope="function")
def mock_haproxy_stats():
    """Mock HAProxy statistics data."""
    return {
        "stats": [
            {
                "pxname": "orchestrator_backend",
                "svname": "orch-1",
                "status": "UP",
                "weight": 100,
                "act": 1,
                "bck": 0,
                "chkfail": 0,
                "chkdown": 0,
                "lastchg": 3600,
                "downtime": 0,
                "qlimit": "",
                "pid": 1,
                "iid": 2,
                "sid": 1,
                "throttle": "",
                "lbtot": 1234,
                "tracked": 0,
                "type": 2,
                "rate": 10,
                "rate_lim": 0,
                "rate_max": 50,
                "check_status": "L7OK",
                "check_code": 200,
                "check_duration": 5,
                "hrsp_1xx": 0,
                "hrsp_2xx": 1200,
                "hrsp_3xx": 30,
                "hrsp_4xx": 4,
                "hrsp_5xx": 0,
                "hrsp_other": 0,
                "hanafail": "",
                "req_rate": 10,
                "req_rate_max": 45,
                "req_tot": 1234,
                "cli_abrt": 0,
                "srv_abrt": 0,
                "comp_in": 0,
                "comp_out": 0,
                "comp_byp": 0,
                "comp_rsp": 0,
                "lastsess": 1,
                "last_chk": "OK",
                "last_agt": "",
                "qtime": 0,
                "ctime": 1,
                "rtime": 8,
                "ttime": 9,
            },
            {
                "pxname": "orchestrator_backend",
                "svname": "orch-2",
                "status": "UP",
                "weight": 100,
                "act": 1,
                "bck": 0,
                "chkfail": 0,
                "chkdown": 0,
                "lastchg": 3600,
                "downtime": 0,
                "lbtot": 1156,
                "rate": 9,
                "check_status": "L7OK",
                "check_code": 200,
                "hrsp_2xx": 1100,
                "hrsp_3xx": 50,
                "hrsp_4xx": 6,
                "hrsp_5xx": 0,
            },
        ]
    }


@pytest.fixture(scope="function")
def mock_scaling_decision():
    """Mock auto-scaling decision."""
    return {
        "service_name": "orchestrator",
        "action": "scale_up",
        "current_replicas": 3,
        "target_replicas": 5,
        "confidence": 0.85,
        "reason": "High CPU usage detected (85%) - Load score: 78.5",
        "metrics_summary": {
            "avg_cpu": 85.2,
            "avg_memory": 72.1,
            "avg_response_time": 250.5,
            "queue_depth": 45,
            "load_score": 78.5,
            "predictive_score": 82.3,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@pytest.fixture(scope="function")
def mock_k8s_client():
    """Mock Kubernetes client."""
    mock_client = MagicMock()

    # Mock deployment
    mock_deployment = MagicMock()
    mock_deployment.metadata.name = "test-service"
    mock_deployment.spec.replicas = 3
    mock_deployment.status.ready_replicas = 3

    mock_client.read_namespaced_deployment.return_value = mock_deployment
    mock_client.patch_namespaced_deployment.return_value = mock_deployment
    mock_client.list_namespaced_deployment.return_value.items = [mock_deployment]

    return mock_client


@pytest.fixture(scope="function")
def mock_docker_client():
    """Mock Docker client."""
    mock_client = MagicMock()

    # Mock service
    mock_service = MagicMock()
    mock_service.name = "test-service"
    mock_service.tasks.return_value = [
        {"Status": {"State": "running", "ContainerStatus": {"ContainerID": "abc123"}}}
    ]

    mock_client.services.get.return_value = mock_service
    mock_client.services.list.return_value = [mock_service]

    # Mock container stats
    mock_container = MagicMock()
    mock_container.stats.return_value = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1000000},
            "system_cpu_usage": 2000000,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 500000},
            "system_cpu_usage": 1000000,
        },
        "memory_stats": {"usage": 104857600, "limit": 536870912},  # 100MB  # 512MB
    }
    mock_client.containers.get.return_value = mock_container

    return mock_client


@pytest.fixture(scope="function")
def mock_health_endpoints():
    """Mock health check endpoints."""
    return {
        "orchestrator": {"status": "healthy", "response_time": 50},
        "br_kg": {"status": "healthy", "response_time": 30},
        "agent": {"status": "healthy", "response_time": 100},
        "web-ui": {"status": "healthy", "response_time": 25},
        "api-gateway": {"status": "healthy", "response_time": 15},
    }


@pytest.fixture(scope="function")
def load_test_data():
    """Sample load test results data."""
    return {
        "summary": {
            "duration": "30s",
            "vus": 10,
            "requests": 3000,
            "requests_per_second": 100,
            "avg_response_time": "150ms",
            "p95_response_time": "300ms",
            "p99_response_time": "500ms",
            "error_rate": "0.1%",
            "data_transferred": "15MB",
        },
        "metrics": {
            "http_req_duration": {
                "avg": 150.5,
                "med": 145.2,
                "p90": 250.8,
                "p95": 300.1,
                "p99": 500.5,
                "max": 1200.0,
            },
            "http_req_failed": {"rate": 0.001},
            "http_reqs": {"count": 3000, "rate": 100.0},
            "data_sent": {"count": 1048576},  # 1MB
            "data_received": {"count": 15728640},  # 15MB
        },
        "thresholds": {
            "http_req_duration": {"p95<500": True},
            "http_req_failed": {"rate<0.01": True},
        },
    }


@pytest.fixture(scope="function")
def blue_green_deployment_state():
    """Mock blue-green deployment state."""
    return {
        "service": "orchestrator",
        "active_color": "blue",
        "inactive_color": "green",
        "replicas": 5,
        "deployment_status": "in_progress",
        "traffic_distribution": {"blue": 75, "green": 25},
        "health_status": {"blue": "healthy", "green": "healthy"},
        "rollback_available": True,
        "timestamp": datetime.utcnow().isoformat(),
    }


# Test helper functions
def wait_for_condition(condition_func, timeout: int = 30, interval: int = 1) -> bool:
    """Wait for a condition to be true."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if condition_func():
            return True
        time.sleep(interval)
    return False


def assert_response_time(response_time: float, max_time: float):
    """Assert response time is within acceptable limits."""
    assert (
        response_time <= max_time
    ), f"Response time {response_time}ms exceeds limit {max_time}ms"


def assert_error_rate(error_count: int, total_count: int, max_rate: float):
    """Assert error rate is within acceptable limits."""
    error_rate = (error_count / total_count) * 100 if total_count > 0 else 0
    assert error_rate <= max_rate, f"Error rate {error_rate}% exceeds limit {max_rate}%"


# Pytest markers
pytest.mark.unit = pytest.mark.unit
pytest.mark.integration = pytest.mark.integration
pytest.mark.load = pytest.mark.load
pytest.mark.slow = pytest.mark.slow
pytest.mark.requires_docker = pytest.mark.requires_docker
pytest.mark.requires_k8s = pytest.mark.requires_k8s
