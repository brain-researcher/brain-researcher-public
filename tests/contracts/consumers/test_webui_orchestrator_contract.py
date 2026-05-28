"""
Consumer contract tests: Web UI -> Orchestrator Service.

These tests define the contract expectations that the Web UI has
when communicating with the Orchestrator service.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from pact import Like, EachLike
try:
    from pact import Consumer, Provider
except ImportError:
    pytest.skip("pact Consumer/Provider not available (pact-python v3?)", allow_module_level=True)

from ..pact_config import pact_config, get_service_config
from ..pact_helpers.pact_client import PactClient, PactMatchers
from ..pact_helpers.mock_data import MockDataGenerator


class TestWebUIToOrchestratorContract:
    """Contract tests from Web UI consumer perspective."""
    
    @pytest.fixture
    def pact_client(self):
        """Create Pact client for Web UI -> Orchestrator contract."""
        web_ui_config = get_service_config("web_ui")
        orchestrator_config = get_service_config("orchestrator")
        return PactClient(web_ui_config, orchestrator_config)
    
    @pytest.mark.asyncio
    async def test_health_check_contract(self, pact_client):
        """Test health check endpoint contract."""
        async with pact_client as pact:
            (pact
             .given("all services are healthy")
             .upon_receiving("a request for health status")
             .with_request(
                 method="GET",
                 path="/health"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body=PactMatchers.health_response()
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", "/health")
            
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "services" in data
            assert "timestamp" in data
            assert data["status"] in ["healthy", "degraded", "unhealthy"]
    
    @pytest.mark.asyncio
    async def test_create_job_contract(self, pact_client):
        """Test job creation endpoint contract."""
        async with pact_client as pact:
            request_data = MockDataGenerator.run_request()
            
            (pact
             .given("orchestrator can accept jobs")
             .upon_receiving("a request to create a new job")
             .with_request(
                 method="POST",
                 path="/run",
                 headers={"Content-Type": "application/json"},
                 body=request_data
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body=PactMatchers.job_response()
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/run",
                headers={"Content-Type": "application/json"},
                json_data=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "job_id" in data
            assert data["job_id"].startswith("job_")
            assert "estimated_duration" in data
            assert "queue_position" in data
            assert "status_url" in data
            assert "stream_url" in data
    
    @pytest.mark.asyncio
    async def test_get_job_status_contract(self, pact_client):
        """Test job status retrieval contract."""
        job_id = "job_test123"
        
        async with pact_client as pact:
            (pact
             .given("a job exists")
             .upon_receiving("a request for job status")
             .with_request(
                 method="GET",
                 path=f"/jobs/{job_id}"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body=PactMatchers.job_details()
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", f"/jobs/{job_id}")
            
            assert response.status_code == 200
            data = response.json()
            assert "id" in data
            assert "status" in data
            assert "prompt" in data
            assert "steps" in data
            assert "artifacts" in data
            assert "timing" in data
    
    @pytest.mark.asyncio
    async def test_job_not_found_contract(self, pact_client):
        """Test job not found error contract."""
        job_id = "job_nonexistent"
        
        async with pact_client as pact:
            (pact
             .given("no jobs exist")
             .upon_receiving("a request for non-existent job")
             .with_request(
                 method="GET",
                 path=f"/jobs/{job_id}"
             )
             .will_respond_with(
                 status=404,
                 headers={"Content-Type": "application/json"},
                 body=PactMatchers.error_response()
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", f"/jobs/{job_id}")
            
            assert response.status_code == 404
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "NOT_FOUND"
    
    @pytest.mark.asyncio
    async def test_create_thread_contract(self, pact_client):
        """Test thread creation contract."""
        async with pact_client as pact:
            request_data = MockDataGenerator.thread_create_request()
            
            (pact
             .given("user is authenticated")
             .upon_receiving("a request to create a thread")
             .with_request(
                 method="POST",
                 path="/threads",
                 headers={"Content-Type": "application/json"},
                 body=request_data
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "thread_id": PactMatchers.thread_id(),
                     "title": request_data["title"],
                     "created_at": PactMatchers.iso_datetime(),
                     "updated_at": PactMatchers.iso_datetime(),
                     "message_count": 0,
                     "context": request_data["context"],
                     "metadata": request_data.get("metadata", {})
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/threads",
                headers={"Content-Type": "application/json"},
                json_data=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "thread_id" in data
            assert data["thread_id"].startswith("thread_")
            assert "title" in data
            assert "created_at" in data
            assert "message_count" in data
    
    @pytest.mark.asyncio
    async def test_add_message_to_thread_contract(self, pact_client):
        """Test adding message to thread contract."""
        thread_id = "thread_test123"
        
        async with pact_client as pact:
            request_data = MockDataGenerator.message_request()
            
            (pact
             .given("a thread exists")
             .upon_receiving("a request to add message to thread")
             .with_request(
                 method="POST",
                 path=f"/threads/{thread_id}/messages",
                 headers={"Content-Type": "application/json"},
                 body=request_data
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "message_id": PactMatchers.message_id(),
                     "job_id": PactMatchers.job_id(),
                     "stream_url": f"/jobs/{PactMatchers.job_id().example}/stream"
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", f"/threads/{thread_id}/messages",
                headers={"Content-Type": "application/json"},
                json_data=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "message_id" in data
            assert "job_id" in data
            assert "stream_url" in data
    
    @pytest.mark.asyncio
    async def test_get_datasets_contract(self, pact_client):
        """Test dataset listing contract."""
        async with pact_client as pact:
            (pact
             .given("datasets are available")
             .upon_receiving("a request for available datasets")
             .with_request(
                 method="GET",
                 path="/datasets",
                 query={"page": "1", "limit": "20"}
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body=PactMatchers.dataset_list()
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "GET", "/datasets", 
                params={"page": 1, "limit": 20}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "datasets" in data
            assert "pagination" in data
            assert "facets" in data
            assert isinstance(data["datasets"], list)
    
    @pytest.mark.asyncio
    async def test_search_datasets_contract(self, pact_client):
        """Test dataset search contract."""
        async with pact_client as pact:
            search_request = {
                "query": {
                    "text": "motor cortex",
                    "filters": {
                        "modality": ["fMRI"],
                        "n_subjects": {"min": 10}
                    }
                }
            }
            
            (pact
             .given("datasets are available")
             .upon_receiving("a request to search datasets")
             .with_request(
                 method="POST",
                 path="/datasets/search",
                 headers={"Content-Type": "application/json"},
                 body=search_request
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body=PactMatchers.dataset_list()
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/datasets/search",
                headers={"Content-Type": "application/json"},
                json_data=search_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "datasets" in data
    
    @pytest.mark.asyncio
    async def test_validation_error_contract(self, pact_client):
        """Test validation error response contract."""
        async with pact_client as pact:
            invalid_request = {
                "prompt": "",  # Empty prompt should trigger validation error
                "pipeline": "glm"
            }
            
            (pact
             .given("orchestrator validates requests")
             .upon_receiving("an invalid job creation request")
             .with_request(
                 method="POST",
                 path="/run",
                 headers={"Content-Type": "application/json"},
                 body=invalid_request
             )
             .will_respond_with(
                 status=422,
                 headers={"Content-Type": "application/json"},
                 body=PactMatchers.error_response()
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/run",
                headers={"Content-Type": "application/json"},
                json_data=invalid_request
            )
            
            assert response.status_code == 422
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "VALIDATION_ERROR"
    
    @pytest.mark.asyncio
    async def test_demo_mode_contract(self, pact_client):
        """Test demo mode execution contract."""
        async with pact_client as pact:
            demo_request = MockDataGenerator.run_request(demo_mode=True)
            
            (pact
             .given("demo data is available")
             .upon_receiving("a demo mode execution request")
             .with_request(
                 method="POST",
                 path="/run",
                 headers={"Content-Type": "application/json"},
                 body=demo_request
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     **PactMatchers.job_response(),
                     "is_demo": True,
                     "cache_hit": True
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/run",
                headers={"Content-Type": "application/json"},
                json_data=demo_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "job_id" in data
            assert data.get("is_demo") is True
    
    @pytest.mark.asyncio
    async def test_ui_config_contract(self, pact_client):
        """Test UI configuration endpoint contract."""
        async with pact_client as pact:
            (pact
             .given("UI configuration is available")
             .upon_receiving("a request for UI configuration")
             .with_request(
                 method="GET",
                 path="/config/ui"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "feature_flags": {
                         "demo_mode": True,
                         "advanced_search": True,
                         "real_time_collaboration": False,
                         "experimental_features": False,
                         "debug_mode": False
                     },
                     "pagination": {
                         "default_page_size": 20,
                         "max_page_size": 100,
                         "mobile_page_size": 10
                     },
                     "timeouts": {
                         "api_timeout_ms": 30000,
                         "upload_timeout_ms": 120000,
                         "websocket_retry_ms": 5000
                     },
                     "limits": {
                         "max_prompt_length": 5000,
                         "max_file_size_mb": 100,
                         "max_concurrent_jobs": 5
                     },
                     "theme": {
                         "default_theme": "light",
                         "available_themes": ["light", "dark", "auto"]
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", "/config/ui")
            
            assert response.status_code == 200
            data = response.json()
            assert "feature_flags" in data
            assert "pagination" in data
            assert "timeouts" in data
            assert "limits" in data
            assert "theme" in data

    @pytest.mark.asyncio
    async def test_get_demo_peaks_contract(self, pact_client):
        """Test peak extraction endpoint contract for 3D brain viewer."""
        demo_id = "glm_motor"
        artifact_id = "sub-01/sub-01_stat-z_statmap.nii.gz"

        async with pact_client as pact:
            (pact
             .given("demo artifacts exist")
             .upon_receiving("a request for peak coordinates")
             .with_request(
                 method="GET",
                 path=f"/api/demo/peaks/{demo_id}/{artifact_id}",
                 query={"threshold": "2.3", "max_peaks": "10", "min_distance": "8.0"}
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "demo_id": Like(demo_id),
                     "artifact_id": Like(artifact_id),
                     "threshold": Like(2.3),
                     "min_distance": Like(8.0),
                     "peaks": EachLike({
                         "x": Like(-40.0),
                         "y": Like(-24.0),
                         "z": Like(48.0),
                         "value": Like(5.2),
                         "cluster_size": Like(350)
                     }, minimum=1),
                     "peak_count": Like(2)
                 }
             ))

            # Execute the request
            response = await pact.execute_request(
                "GET", f"/api/demo/peaks/{demo_id}/{artifact_id}",
                params={"threshold": 2.3, "max_peaks": 10, "min_distance": 8.0}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["demo_id"] == demo_id
            assert data["artifact_id"] == artifact_id
            assert data["threshold"] == 2.3
            assert "peaks" in data
            assert isinstance(data["peaks"], list)
            assert data["peak_count"] == len(data["peaks"])

            # Verify peak structure
            for peak in data["peaks"]:
                assert "x" in peak
                assert "y" in peak
                assert "z" in peak
                assert "value" in peak
                assert "cluster_size" in peak

    @pytest.mark.asyncio
    async def test_get_demo_peaks_empty_response(self, pact_client):
        """Test peaks endpoint with high threshold returns empty peaks."""
        demo_id = "glm_motor"
        artifact_id = "sub-01/sub-01_stat-z_statmap.nii.gz"

        async with pact_client as pact:
            (pact
             .given("demo artifacts exist")
             .upon_receiving("a request for peaks with high threshold")
             .with_request(
                 method="GET",
                 path=f"/api/demo/peaks/{demo_id}/{artifact_id}",
                 query={"threshold": "10.0", "max_peaks": "10"}
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "demo_id": Like(demo_id),
                     "artifact_id": Like(artifact_id),
                     "threshold": Like(10.0),
                     "min_distance": Like(8.0),
                     "peaks": [],
                     "peak_count": Like(0)
                 }
             ))

            # Execute the request
            response = await pact.execute_request(
                "GET", f"/api/demo/peaks/{demo_id}/{artifact_id}",
                params={"threshold": 10.0, "max_peaks": 10}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["peaks"] == []
            assert data["peak_count"] == 0

    @pytest.mark.asyncio
    async def test_get_demo_peaks_invalid_artifact(self, pact_client):
        """Test peaks endpoint with non-existent artifact."""
        demo_id = "glm_motor"
        artifact_id = "nonexistent/artifact.nii.gz"

        async with pact_client as pact:
            (pact
             .given("demo artifacts exist")
             .upon_receiving("a request for peaks from invalid artifact")
             .with_request(
                 method="GET",
                 path=f"/api/demo/peaks/{demo_id}/{artifact_id}"
             )
             .will_respond_with(
                 status=404,
                 headers={"Content-Type": "application/json"},
                 body={
                     "error": "Artifact not found",
                     "detail": f"Artifact '{artifact_id}' not found in demo '{demo_id}'"
                 }
             ))

            # Execute the request
            response = await pact.execute_request(
                "GET", f"/api/demo/peaks/{demo_id}/{artifact_id}"
            )

            assert response.status_code == 404
            data = response.json()
            assert "error" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
