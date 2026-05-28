"""
Smoke tests for health endpoints - validates /api/health/full contract.

Run with: pytest tests/integration/test_smoke_health.py -v

Environment variables:
    AGENT_URL: Agent service URL (default: http://localhost:8000)
    NEUROKG_URL: BR-KG service URL (default: http://localhost:5000)
"""

import os

import pytest

try:
    import httpx
except ImportError:
    httpx = None

AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8000")
NEUROKG_URL = os.getenv("NEUROKG_URL", "http://localhost:5000")


@pytest.fixture
def http_client():
    """Create an HTTP client for testing."""
    if httpx is None:
        pytest.skip("httpx not installed")
    return httpx.Client(timeout=10.0)


class TestAgentHealthSmoke:
    """Smoke tests for Agent aggregated health endpoint."""

    def test_agent_health_full_returns_200(self, http_client):
        """Agent /api/health/full should return 200 with required fields."""
        try:
            response = http_client.get(f"{AGENT_URL}/api/health/full")
            assert response.status_code == 200

            data = response.json()
            assert "status" in data
            assert data["status"] in ("ok", "degraded", "down")
            assert "services" in data
            assert isinstance(data["services"], list)
            assert "timestamp" in data

        except httpx.ConnectError:
            pytest.skip("Agent service not running")

    def test_agent_health_includes_services(self, http_client):
        """Health response should include service component details."""
        try:
            response = http_client.get(f"{AGENT_URL}/api/health/full")
            data = response.json()

            service_names = [s["name"] for s in data.get("services", [])]
            assert "agent" in service_names

            for svc in data["services"]:
                assert "name" in svc
                assert "status" in svc
                assert svc["status"] in ("ok", "degraded", "down")

        except httpx.ConnectError:
            pytest.skip("Agent service not running")

    def test_agent_health_includes_queue_stats(self, http_client):
        """Health response should include queue statistics."""
        try:
            response = http_client.get(f"{AGENT_URL}/api/health/full")
            data = response.json()

            assert "queue" in data
            queue = data["queue"]
            assert isinstance(queue, dict)

        except httpx.ConnectError:
            pytest.skip("Agent service not running")

    def test_agent_health_includes_neo4j_stats(self, http_client):
        """Health response should include Neo4j statistics."""
        try:
            response = http_client.get(f"{AGENT_URL}/api/health/full")
            data = response.json()

            # neo4j should be present after implementation
            assert "neo4j" in data, "neo4j field missing from health response"
            neo4j = data["neo4j"]

            # Should have status or counts
            assert "node_count" in neo4j or "status" in neo4j

        except httpx.ConnectError:
            pytest.skip("Agent service not running")

    def test_agent_health_includes_metadata(self, http_client):
        """Health response should include build/env metadata."""
        try:
            response = http_client.get(f"{AGENT_URL}/api/health/full")
            data = response.json()

            assert "env" in data
            assert "duration_ms" in data
            # build_git_sha may be None but should be present
            assert "build_git_sha" in data

        except httpx.ConnectError:
            pytest.skip("Agent service not running")


class TestNeuroKGHealthSmoke:
    """Smoke tests for BR-KG health endpoints."""

    def test_neurokg_health_returns_200(self, http_client):
        """BR-KG /health should return 200."""
        try:
            response = http_client.get(f"{NEUROKG_URL}/health")
            assert response.status_code == 200

            data = response.json()
            assert "status" in data
            assert data["status"] in ("healthy", "ok")

        except httpx.ConnectError:
            pytest.skip("BR-KG service not running")

    def test_neurokg_health_stats_endpoint(self, http_client):
        """BR-KG /health/stats should return node/relationship counts."""
        try:
            response = http_client.get(f"{NEUROKG_URL}/health/stats")

            # 200 = Neo4j connected, 503 = SQLite mock mode
            assert response.status_code in (200, 503)

            data = response.json()
            assert "status" in data
            assert "node_count" in data
            assert "relationship_count" in data

            if response.status_code == 200:
                assert data["status"] == "ok"
                assert isinstance(data["node_count"], int)
                assert isinstance(data["relationship_count"], int)

        except httpx.ConnectError:
            pytest.skip("BR-KG service not running")

    def test_neurokg_metrics_endpoint(self, http_client):
        """BR-KG /metrics should return Prometheus-format metrics."""
        try:
            response = http_client.get(f"{NEUROKG_URL}/metrics")
            assert response.status_code == 200

            content = response.text
            assert "neurokg_up" in content

        except httpx.ConnectError:
            pytest.skip("BR-KG service not running")


class TestAgentMetricsSmoke:
    """Smoke tests for Agent metrics endpoint."""

    def test_agent_metrics_endpoint(self, http_client):
        """Agent /metrics should return Prometheus-format metrics or 404 if disabled."""
        try:
            response = http_client.get(f"{AGENT_URL}/metrics")

            # 200 = metrics enabled, 404 = disabled
            assert response.status_code in (200, 404)

            if response.status_code == 200:
                assert "text/plain" in response.headers.get("content-type", "")

        except httpx.ConnectError:
            pytest.skip("Agent service not running")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
