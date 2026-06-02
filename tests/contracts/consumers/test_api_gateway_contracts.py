"""
Legacy consumer contract tests: API Gateway -> All Services.

These tests define the contract expectations that the API Gateway has
when communicating with backend services for the retired standalone gateway
surface. They are disabled by default and run only for explicit legacy
compatibility checks.
"""

import asyncio
import os
from pathlib import Path

import pytest

try:
    from pact import Consumer, Provider
except ImportError:
    pytest.skip(
        "pact Consumer/Provider not available (pact-python v3?)",
        allow_module_level=True,
    )

from ..pact_config import (
    LEGACY_GATEWAY_CONTRACT_ENV,
    get_service_config,
    legacy_gateway_contracts_enabled,
    pact_config,
)
from ..pact_helpers.mock_data import MockDataGenerator
from ..pact_helpers.pact_client import PactClient, PactMatchers

if not legacy_gateway_contracts_enabled():
    pytest.skip(
        f"Legacy API gateway contract coverage is disabled by default. Set {LEGACY_GATEWAY_CONTRACT_ENV}=1 to run it.",
        allow_module_level=True,
    )


class TestAPIGatewayToOrchestratorContract:
    """Contract tests from API Gateway consumer perspective to Orchestrator provider."""

    @pytest.fixture
    def pact_client(self):
        """Create Pact client for API Gateway -> Orchestrator contract."""
        gateway_config = get_service_config("api_gateway")
        orchestrator_config = get_service_config("orchestrator")
        return PactClient(gateway_config, orchestrator_config)

    @pytest.mark.asyncio
    async def test_gateway_health_check_contract(self, pact_client):
        """Test health check routing through gateway."""
        async with pact_client as pact:
            (
                pact.given("orchestrator is healthy")
                .upon_receiving("a health check request from API gateway")
                .with_request(
                    method="GET",
                    path="/health",
                    headers={"X-Forwarded-By": "api-gateway"},
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=PactMatchers.health_response(),
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "GET", "/health", headers={"X-Forwarded-By": "api-gateway"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "services" in data

    @pytest.mark.asyncio
    async def test_gateway_job_routing_contract(self, pact_client):
        """Test job creation routing through gateway."""
        async with pact_client as pact:
            request_data = MockDataGenerator.run_request()

            (
                pact.given("orchestrator can accept jobs")
                .upon_receiving("a job creation request from API gateway")
                .with_request(
                    method="POST",
                    path="/run",
                    headers={
                        "Content-Type": "application/json",
                        "X-Forwarded-By": "api-gateway",
                        "X-Request-ID": "req_gateway_123",
                    },
                    body=request_data,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=PactMatchers.job_response(),
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/run",
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-By": "api-gateway",
                    "X-Request-ID": "req_gateway_123",
                },
                json_data=request_data,
            )

            assert response.status_code == 200
            data = response.json()
            assert "job_id" in data

    @pytest.mark.asyncio
    async def test_gateway_rate_limiting_contract(self, pact_client):
        """Test rate limiting response from orchestrator."""
        async with pact_client as pact:
            request_data = MockDataGenerator.run_request()

            (
                pact.given("orchestrator is rate limiting requests")
                .upon_receiving("a rate-limited request from API gateway")
                .with_request(
                    method="POST",
                    path="/run",
                    headers={
                        "Content-Type": "application/json",
                        "X-Forwarded-By": "api-gateway",
                    },
                    body=request_data,
                )
                .will_respond_with(
                    status=429,
                    headers={
                        "Content-Type": "application/json",
                        "Retry-After": "60",
                        "X-RateLimit-Remaining": "0",
                    },
                    body={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many requests",
                            "retry_after": 60,
                            "timestamp": PactMatchers.iso_datetime(),
                        }
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/run",
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-By": "api-gateway",
                },
                json_data=request_data,
            )

            assert response.status_code == 429
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "RATE_LIMITED"


class TestAPIGatewayToAgentContract:
    """Contract tests from API Gateway consumer perspective to Agent provider."""

    @pytest.fixture
    def pact_client(self):
        """Create Pact client for API Gateway -> Agent contract."""
        gateway_config = get_service_config("api_gateway")
        agent_config = get_service_config("agent")
        return PactClient(gateway_config, agent_config)

    @pytest.mark.asyncio
    async def test_gateway_agent_health_contract(self, pact_client):
        """Test agent health check routing through gateway."""
        async with pact_client as pact:
            (
                pact.given("agent service is running")
                .upon_receiving("an agent health check from API gateway")
                .with_request(
                    method="GET",
                    path="/health",
                    headers={"X-Forwarded-By": "api-gateway"},
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "status": "healthy",
                        "queue_length": 0,
                        "active_jobs": 2,
                        "available_tools": 45,
                        "timestamp": PactMatchers.iso_datetime(),
                        "version": "1.0.0",
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "GET", "/health", headers={"X-Forwarded-By": "api-gateway"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_gateway_direct_execution_contract(self, pact_client):
        """Test direct execution routing through gateway."""
        async with pact_client as pact:
            execute_request = {
                "query": "Run GLM analysis",
                "context": {"dataset_id": "motor-task-001"},
                "parameters": {"smoothing": 6},
            }

            (
                pact.given("agent can execute queries")
                .upon_receiving("a direct execution request from API gateway")
                .with_request(
                    method="POST",
                    path="/execute",
                    headers={
                        "Content-Type": "application/json",
                        "X-Forwarded-By": "api-gateway",
                    },
                    body=execute_request,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "execution_id": PactMatchers.uuid(),
                        "status": "accepted",
                        "estimated_duration": 120,
                        "stream_url": f"/executions/{PactMatchers.uuid().example}/stream",
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/execute",
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-By": "api-gateway",
                },
                json_data=execute_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "execution_id" in data
            assert data["status"] == "accepted"


class TestAPIGatewayToBRKGContract:
    """Contract tests from API Gateway consumer perspective to BR-KG provider."""

    @pytest.fixture
    def pact_client(self):
        """Create Pact client for API Gateway -> BR-KG contract."""
        gateway_config = get_service_config("api_gateway")
        br_kg_config = get_service_config("br_kg")
        return PactClient(gateway_config, br_kg_config)

    @pytest.mark.asyncio
    async def test_gateway_br_kg_health_contract(self, pact_client):
        """Test BR-KG health check routing through gateway."""
        async with pact_client as pact:
            (
                pact.given("br_kg service is running")
                .upon_receiving("a br_kg health check from API gateway")
                .with_request(
                    method="GET",
                    path="/health",
                    headers={"X-Forwarded-By": "api-gateway"},
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "status": "healthy",
                        "database": {
                            "connected": True,
                            "nodes": 10000,
                            "relationships": 50000,
                        },
                        "search_indices": {
                            "concepts": "ready",
                            "datasets": "ready",
                            "tasks": "ready",
                        },
                        "timestamp": PactMatchers.iso_datetime(),
                        "version": "1.0.0",
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "GET", "/health", headers={"X-Forwarded-By": "api-gateway"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "database" in data

    @pytest.mark.asyncio
    async def test_gateway_public_dataset_search_contract(self, pact_client):
        """Test public dataset search routing through gateway."""
        async with pact_client as pact:
            search_request = {
                "query": "motor",
                "filters": {"modality": ["fMRI"]},
                "limit": 10,
            }

            (
                pact.given("knowledge graph has datasets")
                .upon_receiving("a public dataset search from API gateway")
                .with_request(
                    method="POST",
                    path="/api/public/datasets/search",
                    headers={
                        "Content-Type": "application/json",
                        "X-Forwarded-By": "api-gateway",
                    },
                    body=search_request,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "datasets": [
                            {
                                "id": PactMatchers.dataset_id(),
                                "name": "Motor Task Dataset",
                                "description": "Public motor task data",
                                "source": "OpenNeuro",
                                "modality": ["fMRI"],
                                "n_subjects": 24,
                                "tasks": ["motor"],
                                "public": True,
                            }
                        ],
                        "total_count": 1,
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/public/datasets/search",
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-By": "api-gateway",
                },
                json_data=search_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "datasets" in data

    @pytest.mark.asyncio
    async def test_gateway_circuit_breaker_contract(self, pact_client):
        """Test circuit breaker response when service is down."""
        async with pact_client as pact:
            search_request = {"query": "motor", "limit": 10}

            (
                pact.given("br_kg service is temporarily down")
                .upon_receiving("a request when br_kg circuit breaker is open")
                .with_request(
                    method="POST",
                    path="/api/datasets/search",
                    headers={
                        "Content-Type": "application/json",
                        "X-Forwarded-By": "api-gateway",
                    },
                    body=search_request,
                )
                .will_respond_with(
                    status=503,
                    headers={
                        "Content-Type": "application/json",
                        "X-Circuit-Breaker": "OPEN",
                    },
                    body={
                        "error": {
                            "code": "SERVICE_UNAVAILABLE",
                            "message": "BR-KG service is temporarily unavailable",
                            "circuit_breaker_state": "OPEN",
                            "retry_after": 60,
                            "timestamp": PactMatchers.iso_datetime(),
                        }
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/datasets/search",
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-By": "api-gateway",
                },
                json_data=search_request,
            )

            assert response.status_code == 503
            data = response.json()
            assert "error" in data
            assert data["error"]["circuit_breaker_state"] == "OPEN"


class TestAPIGatewayAuthenticationContract:
    """Contract tests for authentication and authorization routing."""

    @pytest.fixture
    def pact_client(self):
        """Create Pact client for API Gateway -> Orchestrator auth contract."""
        gateway_config = get_service_config("api_gateway")
        orchestrator_config = get_service_config("orchestrator")
        return PactClient(gateway_config, orchestrator_config)

    @pytest.mark.asyncio
    async def test_gateway_auth_verification_contract(self, pact_client):
        """Test authentication verification routing."""
        async with pact_client as pact:
            (
                pact.given("user has valid JWT token")
                .upon_receiving("an auth verification request from API gateway")
                .with_request(
                    method="GET",
                    path="/auth/verify",
                    headers={
                        "Authorization": "Bearer valid_jwt_token",
                        "X-Forwarded-By": "api-gateway",
                    },
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "valid": True,
                        "user": {
                            "id": PactMatchers.user_id(),
                            "username": "testuser",
                            "role": "researcher",
                            "permissions": ["read", "execute"],
                        },
                        "expires_at": PactMatchers.iso_datetime(),
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "GET",
                "/auth/verify",
                headers={
                    "Authorization": "Bearer valid_jwt_token",
                    "X-Forwarded-By": "api-gateway",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is True
            assert "user" in data

    @pytest.mark.asyncio
    async def test_gateway_invalid_token_contract(self, pact_client):
        """Test invalid token handling."""
        async with pact_client as pact:
            (
                pact.given("user has invalid JWT token")
                .upon_receiving("an invalid auth verification from API gateway")
                .with_request(
                    method="GET",
                    path="/auth/verify",
                    headers={
                        "Authorization": "Bearer invalid_token",
                        "X-Forwarded-By": "api-gateway",
                    },
                )
                .will_respond_with(
                    status=401,
                    headers={"Content-Type": "application/json"},
                    body={
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Invalid or expired token",
                            "timestamp": PactMatchers.iso_datetime(),
                        }
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "GET",
                "/auth/verify",
                headers={
                    "Authorization": "Bearer invalid_token",
                    "X-Forwarded-By": "api-gateway",
                },
            )

            assert response.status_code == 401
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "UNAUTHORIZED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
