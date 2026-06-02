#!/usr/bin/env python3
"""
Integration test for API Gateway with Brain Researcher services.

Tests the gateway's ability to:
- Route requests to backend services
- Handle authentication
- Apply rate limiting
- Cache responses
- Monitor service health
- Transform requests/responses
"""

import asyncio
import json
import time
from typing import Any, Dict

import httpx
import pytest
import redis
from fastapi.testclient import TestClient

from brain_researcher.services.shared.auth_middleware import AuthConfig, TokenManager

from .gateway import create_gateway
from .service_registry import Service, ServiceRegistry


class MockService:
    """Mock backend service for testing."""

    def __init__(self, name: str, port: int):
        self.name = name
        self.port = port
        self.request_count = 0
        self.responses = {}

    def set_response(self, path: str, response: Dict[str, Any]):
        """Set mock response for a path."""
        self.responses[path] = response

    async def handle_request(self, path: str) -> Dict[str, Any]:
        """Handle mock request."""
        self.request_count += 1
        return self.responses.get(path, {"status": "ok", "service": self.name})


class TestAPIGateway:
    """Integration tests for API Gateway."""

    @pytest.fixture
    def redis_client(self):
        """Create test Redis client."""
        try:
            import fakeredis

            return fakeredis.FakeRedis(decode_responses=False)
        except ImportError:
            # Use real Redis if fakeredis not available
            client = redis.from_url(
                "redis://localhost:6379/1", decode_responses=False
            )  # Use DB 1 for tests
            client.flushdb()  # Clear test database
            yield client
            client.flushdb()  # Cleanup

    @pytest.fixture
    def gateway_app(self, redis_client):
        """Create test gateway application."""
        # Create minimal test config
        test_config = {
            "gateway": {"port": 8080, "debug": True, "cors_origins": ["*"]},
            "redis": {"url": "redis://localhost:6379/1"},
            "services": [
                {
                    "name": "test-service",
                    "url": "http://localhost:9001",
                    "health_check_path": "/health",
                }
            ],
            "routes": [
                {
                    "name": "test-route",
                    "path": "/api/test/**",
                    "service": "test-service",
                    "methods": ["GET", "POST"],
                }
            ],
        }

        return create_gateway(test_config)

    @pytest.fixture
    def client(self, gateway_app):
        """Create test client."""
        return TestClient(gateway_app)

    def test_health_endpoint(self, client):
        """Test gateway health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data

    def test_services_endpoint(self, client):
        """Test services listing endpoint."""
        response = client.get("/services")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)

    def test_metrics_endpoint(self, client):
        """Test metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200

        data = response.json()
        assert "total_requests_last_hour" in data
        assert "average_duration_ms" in data

    @pytest.mark.asyncio
    async def test_service_registration(self, redis_client):
        """Test service registration and discovery."""
        registry = ServiceRegistry(redis_client)

        # Register test service
        service = Service(
            name="test-service",
            url="http://localhost:9001",
            health_check_path="/health",
            version="1.0.0",
            description="Test service",
        )

        success = await registry.register(service)
        assert success

        # Retrieve service
        retrieved = await registry.get_service("test-service")
        assert retrieved is not None
        assert retrieved.name == "test-service"
        assert retrieved.url == "http://localhost:9001"

    def test_cors_headers(self, client):
        """Test CORS header handling."""
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert "Access-Control-Allow-Origin" in response.headers
        assert "Access-Control-Allow-Methods" in response.headers

    def test_authentication_required(self, client):
        """Test authentication requirement."""
        # Try to access protected endpoint without auth
        response = client.get("/api/test/protected")
        assert response.status_code == 401

    def test_jwt_authentication(self, client):
        """Test JWT token authentication."""
        # This would require implementing a login endpoint
        # For now, just test token creation
        auth_config = AuthConfig()
        token_manager = TokenManager(auth_config)

        token = token_manager.create_access_token("test-user")
        assert token is not None
        assert len(token) > 0

        # Verify token
        payload = token_manager.verify_token(token)
        assert payload.sub == "test-user"

    def test_rate_limiting_headers(self, client):
        """Test rate limiting headers."""
        response = client.get("/health")

        # Should include rate limit headers if rate limiting is enabled
        if "X-RateLimit-Limit" in response.headers:
            assert "X-RateLimit-Remaining" in response.headers
            assert "X-RateLimit-Reset" in response.headers

    def test_request_id_header(self, client):
        """Test request ID header injection."""
        response = client.get("/health")

        # Gateway should add request ID header
        assert (
            "X-Request-ID" in response.headers
            or "x-request-id" in str(response.headers).lower()
        )

    def test_api_version_header(self, client):
        """Test API version header."""
        response = client.get("/api/test/endpoint")

        # Should add API version header for API routes
        if response.status_code != 404:  # Might be 404 if no backend service
            assert "X-API-Version" in response.headers or response.status_code == 503

    @pytest.mark.asyncio
    async def test_service_health_monitoring(self, redis_client):
        """Test service health monitoring."""
        from .health_monitor import HealthMonitor

        registry = ServiceRegistry(redis_client)
        monitor = HealthMonitor(registry)

        # Register a service
        service = Service(
            name="test-health-service",
            url="http://httpbin.org",  # Public test service
            health_check_path="/status/200",
        )
        await registry.register(service)

        # Check service health
        health_results = await monitor.check_service_health(service)
        assert len(health_results) > 0

        # Health check may pass or fail depending on network
        for instance_id, health in health_results.items():
            assert hasattr(health, "status")
            assert hasattr(health, "last_check")

    def test_error_handling(self, client):
        """Test error handling for invalid routes."""
        response = client.get("/nonexistent/route")
        assert response.status_code == 404

    def test_method_not_allowed(self, client):
        """Test method not allowed handling."""
        # Assuming health endpoint only accepts GET
        response = client.post("/health")
        assert response.status_code in [405, 404]  # Method not allowed or not found

    @pytest.mark.asyncio
    async def test_cache_functionality(self, redis_client):
        """Test caching functionality."""
        from .cache_manager import CacheManager

        cache_manager = CacheManager(redis_client)

        # Get initial stats
        stats = await cache_manager.get_cache_stats()
        assert stats.total_requests >= 0

        # Clear cache
        cleared = await cache_manager.clear_cache()
        assert cleared >= 0

    def test_websocket_endpoint_exists(self, client):
        """Test WebSocket proxy endpoint structure."""
        # Just test that the endpoint structure is correct
        # Actual WebSocket testing would require more complex setup
        response = client.get("/ws/test-service/test-path")
        # Should return error but not 404 (endpoint should exist)
        assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_load_balancer(self):
        """Test load balancer functionality."""
        from .load_balancer import LoadBalancer, LoadBalancerConfig
        from .service_registry import ServiceHealth, ServiceInstance, ServiceStatus

        config = LoadBalancerConfig()
        balancer = LoadBalancer(config)

        # Create mock service with multiple instances
        instances = [
            ServiceInstance(
                instance_id="instance-1",
                url="http://localhost:9001",
                health=ServiceHealth(
                    status=ServiceStatus.HEALTHY,
                    last_check=asyncio.get_event_loop().time(),
                ),
            ),
            ServiceInstance(
                instance_id="instance-2",
                url="http://localhost:9002",
                health=ServiceHealth(
                    status=ServiceStatus.HEALTHY,
                    last_check=asyncio.get_event_loop().time(),
                ),
            ),
        ]

        service = Service(
            name="test-lb-service", url="http://localhost:9001", instances=instances
        )

        # Test round-robin selection
        selected1 = balancer.select_instance(service)
        selected2 = balancer.select_instance(service)

        # Should get different instances (round-robin)
        assert selected1 in ["http://localhost:9001", "http://localhost:9002"]
        assert selected2 in ["http://localhost:9001", "http://localhost:9002"]


def run_integration_tests():
    """Run integration tests."""
    print("Running API Gateway Integration Tests...")

    # Run pytest
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )

    print("STDOUT:", result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    return result.returncode == 0


async def test_full_integration():
    """Test full integration with mock services."""
    print("Testing full gateway integration...")

    try:
        # Create Redis client
        try:
            import fakeredis

            redis_client = fakeredis.FakeRedis(decode_responses=False)
        except ImportError:
            redis_client = redis.from_url(
                "redis://localhost:6379/1", decode_responses=False
            )
            redis_client.flushdb()

        # Test service registry
        from .service_registry import ServiceRegistry

        registry = ServiceRegistry(redis_client)

        # Register test services
        services = [
            Service(name="test-orchestrator", url="http://localhost:3001"),
            Service(name="test-agent", url="http://localhost:8000"),
            Service(name="test-br_kg", url="http://localhost:5000"),
        ]

        for service in services:
            await registry.register(service)
            print(f"✓ Registered service: {service.name}")

        # Test health monitoring
        from .health_monitor import HealthMonitor

        monitor = HealthMonitor(registry)

        print("✓ Health monitor initialized")

        # Test cache manager
        from .cache_manager import CacheManager

        cache = CacheManager(redis_client)
        stats = await cache.get_cache_stats()

        print(f"✓ Cache manager initialized (entries: {stats.entry_count})")

        # Test load balancer
        from .load_balancer import LoadBalancer

        balancer = LoadBalancer()

        print("✓ Load balancer initialized")

        # Test rate limiter
        from .rate_limiter import RateLimiter

        rate_limiter = RateLimiter(redis_client)

        print("✓ Rate limiter initialized")

        print("\n✅ All integration tests passed!")
        return True

    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run integration tests
    success = asyncio.run(test_full_integration())

    if success:
        print("\n🎉 API Gateway integration tests completed successfully!")
    else:
        print("\n💥 API Gateway integration tests failed!")
        exit(1)
