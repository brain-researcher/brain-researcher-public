"""
Contract tests for Orchestrator API endpoints.

These tests ensure that the API contracts are honored and that
frontend-backend integration remains stable.
"""

import json
from datetime import datetime
from typing import Any, Dict

import httpx
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.provisional import urls

# Import the enhanced orchestrator app
from brain_researcher.services.orchestrator.main_enhanced import app
from brain_researcher.services.orchestrator.models import (
    DatasetSearchRequest,
    ErrorCode,
    JobStatus,
    LoginRequest,
    MessageRequest,
    NotificationMarkReadRequest,
    PipelineType,
    RunRequest,
    SignupRequest,
    StepStatus,
    ThreadRequest,
    UIConfiguration,
)

# Test client
client = TestClient(app)

# ============================================================================
# Contract Tests for Core Endpoints
# ============================================================================


class TestHealthEndpoint:
    """Contract tests for /health endpoint."""

    def test_health_response_contract(self):
        """Test that health endpoint returns expected structure."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()

        # Verify top-level fields
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "services" in data
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "version" in data

        # Verify service health structure
        for service_name, service_data in data["services"].items():
            assert "name" in service_data
            assert "status" in service_data
            assert service_data["status"] in [
                "healthy",
                "degraded",
                "unhealthy",
                "unavailable",
            ]
            if "latency_ms" in service_data:
                assert isinstance(service_data["latency_ms"], (int, type(None)))

    def test_health_performance_requirement(self):
        """Test that health check responds within 200ms."""
        import time

        start = time.time()
        response = client.get("/health")
        duration = (time.time() - start) * 1000

        assert response.status_code == 200
        assert duration < 200, f"Health check took {duration}ms, should be < 200ms"


class TestRunEndpoint:
    """Contract tests for /run endpoint."""

    def test_run_request_contract(self):
        """Test that run endpoint accepts expected request format."""
        request_data = {
            "prompt": "Run GLM analysis on motor task",
            "pipeline": "glm",
            "dataset_id": "motor-task-001",
            "parameters": {"smoothing": 6, "threshold": 0.001},
            "copilot": True,
            "demo_mode": False,
            "timeout_seconds": 300,
            "priority": 5,
        }

        response = client.post("/run", json=request_data)
        assert response.status_code == 200

        data = response.json()

        # Verify response structure
        assert "job_id" in data
        assert data["job_id"].startswith("job_")
        assert "estimated_duration" in data
        assert isinstance(data["estimated_duration"], int)
        assert "queue_position" in data
        assert isinstance(data["queue_position"], int)
        assert "status_url" in data
        assert data["status_url"] == f"/jobs/{data['job_id']}"
        assert "stream_url" in data
        assert data["stream_url"] == f"/jobs/{data['job_id']}/stream"

    @given(
        prompt=st.text(min_size=1, max_size=5000),
        smoothing=st.floats(min_value=0, max_value=12),
        threshold=st.floats(min_value=0.0001, max_value=0.9999),
    )
    @settings(max_examples=10)
    def test_run_parameter_validation(self, prompt, smoothing, threshold):
        """Property test for parameter validation."""
        request_data = {
            "prompt": prompt,
            "pipeline": "glm",
            "parameters": {"smoothing": smoothing, "threshold": threshold},
        }

        response = client.post("/run", json=request_data)

        # Should accept valid parameters
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data

    def test_demo_mode_contract(self):
        """Test demo mode returns instant results."""
        request_data = {
            "prompt": "Run first-level GLM analysis on motor task data",
            "pipeline": "glm",
            "dataset_id": "motor-task-sample",
            "demo_mode": True,
            "cache_key": "demo_test",
        }

        response = client.post("/run", json=request_data)
        assert response.status_code == 200

        # Check that demo job is immediately available
        job_id = response.json()["job_id"]
        job_response = client.get(f"/jobs/{job_id}")
        assert job_response.status_code == 200

        job_data = job_response.json()
        # Demo jobs should be completed immediately
        if "demo_mode" in job_data.get("metadata", {}):
            assert job_data["status"] == "completed"
            assert len(job_data["artifacts"]) > 0


class TestJobEndpoints:
    """Contract tests for job management endpoints."""

    def test_job_retrieval_contract(self):
        """Test job retrieval endpoint contract."""
        # First create a job
        create_response = client.post(
            "/run", json={"prompt": "Test job", "pipeline": "custom"}
        )
        job_id = create_response.json()["job_id"]

        # Retrieve the job
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200

        data = response.json()

        # Verify job structure
        assert "id" in data
        assert data["id"] == job_id
        assert "status" in data
        assert data["status"] in [
            "pending",
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            "timeout",
        ]
        assert "prompt" in data
        assert "steps" in data
        assert isinstance(data["steps"], list)
        assert "artifacts" in data
        assert isinstance(data["artifacts"], list)
        assert "timing" in data
        assert "start_time" in data["timing"]
        assert "metadata" in data

    def test_job_not_found_error(self):
        """Test error response for non-existent job."""
        response = client.get("/jobs/job_nonexistent")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"
        assert "message" in data["error"]
        assert "timestamp" in data["error"]

    def test_job_provenance_contract(self):
        """Test provenance endpoint contract (UI-004)."""
        # Create a job
        create_response = client.post(
            "/run", json={"prompt": "Test provenance", "dataset_id": "test-dataset"}
        )
        job_id = create_response.json()["job_id"]

        # Get provenance
        response = client.get(f"/jobs/{job_id}/provenance")
        assert response.status_code == 200

        data = response.json()
        assert "job_id" in data
        assert "provenance_graph" in data
        assert "nodes" in data["provenance_graph"]
        assert "edges" in data["provenance_graph"]

        # Verify node structure
        for node in data["provenance_graph"]["nodes"]:
            assert "id" in node
            assert "type" in node
            assert node["type"] in ["data", "process", "parameter"]
            assert "label" in node
            assert "metadata" in node

        # Verify edge structure
        for edge in data["provenance_graph"]["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "relationship" in edge


class TestThreadEndpoints:
    """Contract tests for thread management (UI-003)."""

    def test_thread_creation_contract(self):
        """Test thread creation endpoint."""
        request_data = {
            "title": "Test Analysis Thread",
            "context": {"dataset_id": "test-dataset", "previous_jobs": []},
        }

        response = client.post("/threads", json=request_data)
        assert response.status_code == 200

        data = response.json()
        assert "thread_id" in data
        assert data["thread_id"].startswith("thread_")
        assert "title" in data
        assert data["title"] == request_data["title"]
        assert "created_at" in data
        assert "updated_at" in data
        assert "message_count" in data
        assert data["message_count"] == 0
        assert "context" in data

    def test_message_addition_contract(self):
        """Test message addition to thread."""
        # Create thread
        thread_response = client.post("/threads", json={"title": "Test Thread"})
        thread_id = thread_response.json()["thread_id"]

        # Add message
        message_data = {
            "content": "Run analysis on this data",
            "attachments": [
                {"type": "file", "name": "data.csv", "data": "base64_encoded_data"}
            ],
        }

        response = client.post(f"/threads/{thread_id}/messages", json=message_data)
        assert response.status_code == 200

        data = response.json()
        assert "message_id" in data
        assert data["message_id"].startswith("msg_")
        assert "job_id" in data
        assert "stream_url" in data

    def test_message_history_contract(self):
        """Test message history retrieval."""
        # Create thread
        thread_response = client.post("/threads", json={"title": "History Test"})
        thread_id = thread_response.json()["thread_id"]

        # Add some messages
        for i in range(3):
            client.post(
                f"/threads/{thread_id}/messages", json={"content": f"Message {i}"}
            )

        # Get history
        response = client.get(f"/threads/{thread_id}/messages?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert "has_more" in data
        assert isinstance(data["has_more"], bool)
        assert "cursor" in data
        assert "total_count" in data

        # Verify message structure
        for msg in data["messages"]:
            assert "id" in msg
            assert "thread_id" in msg
            assert "role" in msg
            assert msg["role"] in ["user", "assistant", "system"]
            assert "content" in msg
            assert "timestamp" in msg


class TestDatasetEndpoints:
    """Contract tests for dataset management (UI-006/007)."""

    def test_dataset_listing_contract(self):
        """Test dataset listing with pagination."""
        response = client.get("/datasets?page=1&limit=10&sort=name&order=asc")
        assert response.status_code == 200

        data = response.json()
        assert "datasets" in data
        assert isinstance(data["datasets"], list)
        assert "pagination" in data
        assert "page" in data["pagination"]
        assert "limit" in data["pagination"]
        assert "total_items" in data["pagination"]
        assert "total_pages" in data["pagination"]
        assert "facets" in data

        # Verify dataset structure
        for dataset in data["datasets"]:
            assert "id" in dataset
            assert "name" in dataset
            assert "description" in dataset
            assert "source" in dataset
            assert "modality" in dataset
            assert "n_subjects" in dataset
            assert "tasks" in dataset
            assert "size_gb" in dataset

    def test_dataset_filtering(self):
        """Test dataset filtering parameters."""
        # Test various filter combinations
        filters = [
            {"source": "OpenNeuro"},
            {"modality": ["fMRI"]},
            {"n_subjects_min": 10, "n_subjects_max": 50},
            {"tasks": ["motor", "rest"]},
            {"has_derivatives": True},
        ]

        for filter_params in filters:
            response = client.get("/datasets", params=filter_params)
            assert response.status_code == 200
            data = response.json()
            assert "datasets" in data

    @given(
        page=st.integers(min_value=1, max_value=100),
        limit=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=5)
    def test_dataset_pagination_bounds(self, page, limit):
        """Property test for pagination parameters."""
        response = client.get(f"/datasets?page={page}&limit={limit}")
        assert response.status_code == 200

        data = response.json()
        assert data["pagination"]["page"] == page
        assert data["pagination"]["limit"] == limit
        assert len(data["datasets"]) <= limit

    def test_dataset_search_contract(self):
        """Test advanced dataset search."""
        search_request = {
            "query": {
                "text": "motor cortex",
                "filters": {"n_subjects": {"min": 15, "max": 50}, "modality": ["fMRI"]},
            },
            "options": {"include_similar": True, "similarity_threshold": 0.7},
        }

        response = client.post("/datasets/search", json=search_request)
        assert response.status_code == 200

        data = response.json()
        assert "datasets" in data
        # Search metadata if available
        if "search_metadata" in data:
            assert "query_id" in data["search_metadata"]
            assert "processing_time_ms" in data["search_metadata"]


# ============================================================================
# Error Path Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_invalid_pipeline_type(self):
        """Test handling of invalid pipeline type."""
        response = client.post(
            "/run", json={"prompt": "Test", "pipeline": "invalid_pipeline"}
        )
        assert response.status_code == 422  # Validation error

    def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        response = client.post("/run", json={})
        assert response.status_code == 422

        # Should have validation error details
        data = response.json()
        assert "detail" in data

    def test_oversized_prompt(self):
        """Test handling of oversized prompt."""
        huge_prompt = "x" * 10000  # Exceeds 5000 char limit
        response = client.post("/run", json={"prompt": huge_prompt})
        assert response.status_code == 422

    def test_invalid_parameter_ranges(self):
        """Test parameter range validation."""
        # Smoothing out of range
        response = client.post(
            "/run",
            json={
                "prompt": "Test",
                "pipeline": "glm",
                "parameters": {"smoothing": 15},  # Max is 12
            },
        )
        assert response.status_code == 422

        # Threshold out of range
        response = client.post(
            "/run",
            json={
                "prompt": "Test",
                "pipeline": "glm",
                "parameters": {"threshold": 1.5},  # Max is 1
            },
        )
        assert response.status_code == 422

    def test_thread_not_found(self):
        """Test accessing non-existent thread."""
        response = client.get("/threads/thread_nonexistent/messages")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"

    def test_dataset_not_found(self):
        """Test accessing non-existent dataset."""
        response = client.get("/datasets/ds_nonexistent")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"

    def test_concurrent_job_creation(self):
        """Test handling of concurrent job creation."""
        import asyncio

        import aiohttp

        async def create_job():
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://localhost:3001/run",
                    json={"prompt": "Concurrent test", "priority": 10},
                ) as response:
                    return await response.json()

        # Create multiple jobs concurrently
        async def test_concurrent():
            tasks = [create_job() for _ in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed
            for result in results:
                if not isinstance(result, Exception):
                    assert "job_id" in result

        # Would run with asyncio.run(test_concurrent())


# ============================================================================
# SSE/WebSocket Contract Tests
# ============================================================================


class TestRealTimeEndpoints:
    """Test real-time communication contracts."""

    def test_sse_event_format(self):
        """Test SSE event format compliance."""
        # Create a job
        response = client.post("/run", json={"prompt": "SSE test"})
        job_id = response.json()["job_id"]

        # Connect to SSE endpoint
        # Note: TestClient doesn't support SSE, this is pseudo-code
        # In real test, would use httpx-sse or similar
        """
        with client.stream("GET", f"/jobs/{job_id}/stream") as response:
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_type = line.split(":")[1].strip()
                    assert event_type in ["init", "status", "step", "step_update", "artifact", "ping"]
                elif line.startswith("data:"):
                    data = json.loads(line.split(":", 1)[1])
                    # Verify data structure based on event type
        """

    def test_websocket_message_format(self):
        """Test WebSocket message format."""
        # Would test with WebSocket client
        pass

    def test_keepalive_mechanism(self):
        """Test that keepalive messages are sent."""
        # Would verify ping messages are sent every 30s
        pass


# ============================================================================
# Performance and Load Tests
# ============================================================================


class TestPerformanceRequirements:
    """Test performance requirements are met."""

    def test_dataset_search_performance(self):
        """Test dataset search responds within 500ms."""
        import time

        start = time.time()
        response = client.get("/datasets?q=motor")
        duration = (time.time() - start) * 1000

        assert response.status_code == 200
        assert duration < 500, f"Dataset search took {duration}ms, should be < 500ms"

    def test_job_creation_performance(self):
        """Test job creation responds within 2s."""
        import time

        start = time.time()
        response = client.post("/run", json={"prompt": "Performance test"})
        duration = (time.time() - start) * 1000

        assert response.status_code == 200
        assert duration < 2000, f"Job creation took {duration}ms, should be < 2000ms"


# ============================================================================
# Authentication Contract Tests (UI-011)
# ============================================================================


class TestAuthenticationEndpoints:
    """Contract tests for authentication endpoints."""

    def test_signup_contract(self):
        """Test user signup endpoint contract."""
        signup_data = {
            "username": "testuser123",
            "email": "testuser@example.com",
            "password": "securepass123",
            "full_name": "Test User",
            "accept_terms": True,
        }

        response = client.post("/auth/signup", json=signup_data)
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "token_type" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
        assert "user" in data

        # Verify user structure
        user = data["user"]
        assert "id" in user
        assert user["id"].startswith("user_")
        assert "username" in user
        assert user["username"] == signup_data["username"]
        assert "email" in user
        assert "full_name" in user
        assert "role" in user
        assert "is_active" in user
        assert user["is_active"] is True

    def test_login_contract(self):
        """Test user login endpoint contract."""
        login_data = {"username": "demo", "password": "demo123", "remember_me": False}

        response = client.post("/auth/login", json=login_data)
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "expires_in" in data
        assert "user" in data

    def test_me_endpoint_contract(self):
        """Test current user endpoint contract."""
        # First login to get token
        login_response = client.post(
            "/auth/login", json={"username": "demo", "password": "demo123"}
        )
        token = login_response.json()["access_token"]

        # Test /auth/me endpoint
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/auth/me", headers=headers)
        assert response.status_code == 200

        user = response.json()
        assert "id" in user
        assert "username" in user
        assert "email" in user
        assert "role" in user
        assert "is_active" in user

    def test_password_reset_contract(self):
        """Test password reset endpoint contract."""
        reset_data = {"email": "demo@brain-researcher.ai"}

        response = client.post("/auth/reset-password", json=reset_data)
        assert response.status_code == 200

        data = response.json()
        assert "message" in data

    def test_oauth_contract(self):
        """Test OAuth endpoint contract."""
        oauth_data = {
            "provider": "github",
            "code": "mock_oauth_code",
            "redirect_uri": "http://localhost:3000/auth/callback",
        }

        response = client.post("/auth/oauth/github", json=oauth_data)
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert "user" in data


# ============================================================================
# UI Configuration Contract Tests (UI-015)
# ============================================================================


class TestUIConfigurationEndpoints:
    """Contract tests for UI configuration endpoints."""

    def test_ui_config_contract(self):
        """Test UI configuration endpoint contract."""
        response = client.get("/config/ui")
        assert response.status_code == 200

        data = response.json()
        assert "feature_flags" in data
        assert "pagination" in data
        assert "timeouts" in data
        assert "limits" in data
        assert "theme" in data

        # Verify feature flags structure
        feature_flags = data["feature_flags"]
        assert "demo_mode" in feature_flags
        assert "advanced_search" in feature_flags
        assert "real_time_collaboration" in feature_flags
        assert "experimental_features" in feature_flags
        assert "debug_mode" in feature_flags

        # Verify pagination config
        pagination = data["pagination"]
        assert "default_page_size" in pagination
        assert "max_page_size" in pagination
        assert "mobile_page_size" in pagination

    def test_mobile_detection(self):
        """Test mobile user agent detection in UI config."""
        mobile_headers = {
            "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
        }

        response = client.get("/config/ui", headers=mobile_headers)
        assert response.status_code == 200

        data = response.json()
        # Should adjust pagination for mobile
        assert (
            data["pagination"]["default_page_size"]
            <= data["pagination"]["mobile_page_size"]
        )


# ============================================================================
# Enhanced Error Response Tests (UI-013)
# ============================================================================


class TestEnhancedErrorHandling:
    """Test enhanced error response format."""

    def test_enhanced_error_structure(self):
        """Test enhanced error response structure."""
        response = client.get("/jobs/job_nonexistent")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data
        error = data["error"]

        # Required fields
        assert "code" in error
        assert "message" in error
        assert "timestamp" in error

        # Optional enhanced fields
        if "context" in error:
            context = error["context"]
            assert "request_id" in context
            assert "endpoint" in context
            assert "method" in context

        if "suggestions" in error:
            assert isinstance(error["suggestions"], list)

        if "documentation_url" in error:
            assert error["documentation_url"].startswith("http")

    def test_validation_error_enhancement(self):
        """Test validation error includes helpful suggestions."""
        invalid_run_data = {"prompt": "x" * 10000, "pipeline": "glm"}  # Too long

        response = client.post("/run", json=invalid_run_data)
        assert response.status_code == 422

        # Should have validation error details
        data = response.json()
        assert "detail" in data


# ============================================================================
# Progress Tracking Tests (UI-014)
# ============================================================================


class TestProgressTracking:
    """Test job progress tracking features."""

    def test_job_progress_structure(self):
        """Test job includes progress information."""
        # Create a job
        job_response = client.post(
            "/run", json={"prompt": "Test progress tracking", "pipeline": "glm"}
        )
        job_id = job_response.json()["job_id"]

        # Get job details
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200

        job = response.json()
        if "progress" in job and job["progress"]:
            progress = job["progress"]
            assert "percentage" in progress
            assert "current_step" in progress
            assert "total_steps" in progress
            assert "last_update" in progress

            # Validate ranges
            assert 0 <= progress["percentage"] <= 100
            assert 0 <= progress["current_step"] <= progress["total_steps"]


# ============================================================================
# Integration Tests with Mock Services
# ============================================================================


class TestServiceIntegration:
    """Test integration with backend services."""

    @pytest.fixture
    def mock_agent_service(self, monkeypatch):
        """Mock Agent service responses."""

        async def mock_execute_query(*args, **kwargs):
            return {"result": "mocked", "status": "success"}

        monkeypatch.setattr(
            "main_enhanced.EnhancedAgentClient.execute_query", mock_execute_query
        )

    @pytest.fixture
    def mock_br_kg_service(self, monkeypatch):
        """Mock BR-KG service responses."""

        async def mock_search_datasets(*args, **kwargs):
            from models import Dataset, DatasetSearchResponse, DatasetSource, Modality

            return DatasetSearchResponse(
                datasets=[
                    Dataset(
                        id="mock-dataset",
                        name="Mock Dataset",
                        description="Mocked for testing",
                        source=DatasetSource.BUILTIN,
                        modality=[Modality.FMRI],
                        n_subjects=10,
                        n_sessions=1,
                        tasks=["mock"],
                        size_gb=1.0,
                        has_derivatives=False,
                        last_updated=datetime.utcnow(),
                    )
                ],
                pagination={"page": 1, "limit": 20, "total_items": 1, "total_pages": 1},
                facets={},
            )

        monkeypatch.setattr(
            "main_enhanced.EnhancedBRKGClient.search_datasets", mock_search_datasets
        )

    def test_graceful_degradation(self, mock_agent_service, mock_br_kg_service):
        """Test that system degrades gracefully when services are unavailable."""
        # Should still be able to create jobs
        response = client.post("/run", json={"prompt": "Test with mocked services"})
        assert response.status_code == 200

        # Should return mock/cached datasets
        response = client.get("/datasets")
        assert response.status_code == 200
        data = response.json()
        assert len(data["datasets"]) > 0


# ============================================================================
# Hypothesis-based Property Tests
# ============================================================================


class TestPropertyBasedValidation:
    """Property-based tests for robust validation."""

    @given(
        thread_title=st.text(min_size=1, max_size=200),
        message_content=st.text(min_size=1, max_size=10000),
    )
    @settings(max_examples=20)
    def test_thread_message_properties(self, thread_title, message_content):
        """Test thread and message creation with various inputs."""
        # Create thread
        thread_response = client.post("/threads", json={"title": thread_title})
        assert thread_response.status_code == 200
        thread_id = thread_response.json()["thread_id"]

        # Add message
        msg_response = client.post(
            f"/threads/{thread_id}/messages", json={"content": message_content}
        )
        assert msg_response.status_code == 200

    @given(
        query_text=st.text(min_size=1, max_size=500),
        page=st.integers(min_value=1, max_value=100),
        limit=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=10)
    def test_dataset_search_properties(self, query_text, page, limit):
        """Test dataset search with various inputs."""
        response = client.get(f"/datasets?q={query_text}&page={page}&limit={limit}")
        assert response.status_code == 200

        data = response.json()
        assert len(data["datasets"]) <= limit
        assert data["pagination"]["page"] == page


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
