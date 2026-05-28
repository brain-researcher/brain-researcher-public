"""Legacy integration coverage for the retired standalone API gateway."""

import os
import pytest
from unittest.mock import AsyncMock, Mock
from fastapi.testclient import TestClient

if os.getenv("BR_ENABLE_LEGACY_GATEWAY_TESTS", "0").lower() not in {"1", "true", "yes", "on"}:
    pytest.skip(
        "Legacy api_gateway compatibility coverage is disabled by default. Set BR_ENABLE_LEGACY_GATEWAY_TESTS=1 to run it.",
        allow_module_level=True,
    )

from brain_researcher.legacy.api_gateway.gateway import APIGateway
from brain_researcher.legacy.api_gateway.service_registry import Service


@pytest.fixture
def gateway_app(monkeypatch):
    """Create an API gateway instance with dependencies stubbed for testing."""

    # Avoid real redis/network work during tests
    monkeypatch.setattr(APIGateway, "_init_redis", lambda self: Mock())
    monkeypatch.setattr(APIGateway, "_register_lifecycle_events", lambda self: None)

    gateway = APIGateway()

    # Allow all requests through the rate limiter
    gateway.rate_limiter.check_rate_limit = AsyncMock(return_value=(True, None))

    # Simulate a service without any healthy instances
    empty_service = Service(
        name="orchestrator",
        url="http://orchestrator:3001",
        instances=[],
    )
    gateway.service_registry.get_service = AsyncMock(return_value=empty_service)

    # Load balancer should surface the absence of targets
    gateway.load_balancer.select_instance = Mock(return_value=None)

    return gateway


def test_gateway_returns_503_when_no_backend_instances(gateway_app):
    """Ensure the gateway fails open with 503 when no service instances are available."""

    client = TestClient(gateway_app.app)

    response = client.get("/api/orchestrator/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service orchestrator not available"
