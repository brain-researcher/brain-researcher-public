"""
Legacy full-stack integration suite for the pre-cleanup service topology.

The active runtime contract is covered by targeted orchestrator/agent/kg/web
tests and deployment smoke tests. This gateway-oriented suite is preserved only
as historical compatibility scaffolding until it is rewritten against the
current split-service topology.
"""

import pytest
pytest.skip(
    "Legacy full-stack integration suite retired from active runtime coverage.",
    allow_module_level=True,
)
import pytest_asyncio
import asyncio
import httpx
import websockets
import json
import time
from typing import Dict, Any, List
import redis
import logging
from unittest.mock import MagicMock, patch

# Import FastAPI apps for ASGI testing
from brain_researcher.services.orchestrator.main_enhanced import app as orchestrator_app

logger = logging.getLogger(__name__)

# Service URLs (for external service tests only)
ORCHESTRATOR_URL = "http://localhost:3001"
NEUROKG_URL = "http://localhost:5000"
AGENT_URL = "http://localhost:8000"
GATEWAY_URL = "http://localhost:8080"


class TestOrchestratorService:
    """Test Orchestrator Service endpoints and WebSocket connections"""
    
    @pytest_asyncio.fixture
    async def client(self):
        # Use ASGI client instead of real HTTP connection
        transport = httpx.ASGITransport(app=orchestrator_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Test health check endpoint"""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # Health check can be 'healthy' or 'degraded' (when external services unavailable)
        assert data["status"] in ["healthy", "degraded"]
        assert "services" in data
        assert "uptime_seconds" in data
    
    @pytest.mark.asyncio
    async def test_authentication_flow(self, client):
        """Test complete authentication flow"""
        # Test signup
        signup_data = {
            "username": "test_user",
            "email": "test@example.com",
            "password": "SecurePass123!",
            "full_name": "Test User"
        }
        response = await client.post(f"{ORCHESTRATOR_URL}/auth/signup", json=signup_data)
        assert response.status_code == 200
        token_data = response.json()
        assert "access_token" in token_data
        assert "refresh_token" in token_data
        
        # Test login
        login_data = {
            "username": "test_user",
            "password": "SecurePass123!"
        }
        response = await client.post(f"{ORCHESTRATOR_URL}/auth/login", json=login_data)
        assert response.status_code == 200
        token_data = response.json()
        access_token = token_data["access_token"]
        
        # Test authenticated endpoint
        headers = {"Authorization": f"Bearer {access_token}"}
        response = await client.get(f"{ORCHESTRATOR_URL}/auth/me", headers=headers)
        assert response.status_code == 200
        user_data = response.json()
        assert user_data["username"] == "test_user"
    
    @pytest.mark.asyncio
    async def test_job_submission(self, client):
        """Test job submission and monitoring"""
        # Submit job
        job_request = {
            "dataset_id": "ds000114",
            "analysis_type": "glm",
            "parameters": {
                "smoothing_fwhm": 6,
                "tr": 2.0,
                "motion_correction": True
            }
        }
        response = await client.post(f"{ORCHESTRATOR_URL}/run", json=job_request)
        assert response.status_code == 200
        job_data = response.json()
        job_id = job_data["job_id"]
        assert job_id is not None
        
        # Check job status
        response = await client.get(f"{ORCHESTRATOR_URL}/jobs/{job_id}")
        assert response.status_code == 200
        job_status = response.json()
        assert job_status["status"] in ["pending", "running", "completed", "failed"]
        assert job_status["progress"] is not None
    
    @pytest.mark.asyncio
    async def test_batch_job_submission(self, client):
        """Test batch job submission"""
        batch_request = {
            "jobs": [
                {
                    "dataset_id": "ds000114",
                    "analysis_type": "glm",
                    "parameters": {"smoothing_fwhm": 6}
                },
                {
                    "dataset_id": "ds000114",
                    "analysis_type": "connectivity",
                    "parameters": {"roi": "motor_cortex"}
                }
            ],
            "execution_mode": "parallel",
            "retry_failed": True
        }
        response = await client.post(f"{ORCHESTRATOR_URL}/batch/jobs", json=batch_request)
        assert response.status_code == 200
        batch_data = response.json()
        assert "batch_id" in batch_data
        assert len(batch_data["job_ids"]) == 2
    
    @pytest.mark.asyncio
    async def test_websocket_notifications(self):
        """Test WebSocket notification system"""
        # Get auth token first
        async with httpx.AsyncClient() as client:
            login_data = {"username": "demo", "password": "demo123"}
            response = await client.post(f"{ORCHESTRATOR_URL}/auth/login", json=login_data)
            token = response.json()["access_token"]
        
        # Connect to WebSocket
        uri = f"ws://localhost:5000/ws/notifications?token={token}"
        async with websockets.connect(uri) as websocket:
            # Send subscribe message
            await websocket.send(json.dumps({
                "type": "subscribe",
                "channels": ["jobs", "system"]
            }))
            
            # Receive confirmation
            message = await websocket.recv()
            data = json.loads(message)
            assert data["type"] == "subscribed"
            
            # Test ping/pong
            await websocket.send(json.dumps({"type": "ping"}))
            pong = await websocket.recv()
            assert json.loads(pong)["type"] == "pong"
    
    @pytest.mark.asyncio
    async def test_websocket_job_updates(self):
        """Test WebSocket job progress updates"""
        job_id = "test_job_123"
        uri = f"ws://localhost:5000/ws/jobs/{job_id}"
        
        async with websockets.connect(uri) as websocket:
            # Should receive initial status
            message = await websocket.recv()
            data = json.loads(message)
            assert data["type"] == "job_status"
            assert data["job_id"] == job_id


class TestNeuroKGService:
    """Test BR-KG API enhancements"""
    
    @pytest_asyncio.fixture
    async def client(self):
        async with httpx.AsyncClient() as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_graphql_query(self, client):
        """Test GraphQL query execution"""
        query = """
        query GetTasks($limit: Int) {
            tasks(limit: $limit) {
                id
                name
                description
                concepts {
                    name
                    ontology_id
                }
            }
        }
        """
        variables = {"limit": 10}
        
        response = await client.post(
            f"{NEUROKG_URL}/graphql",
            json={"query": query, "variables": variables}
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "tasks" in data["data"]
    
    @pytest.mark.asyncio
    async def test_vector_search(self, client):
        """Test vector similarity search"""
        search_request = {
            "query": "motor cortex activation during finger tapping",
            "top_k": 10,
            "threshold": 0.7
        }
        response = await client.post(f"{NEUROKG_URL}/search/vector", json=search_request)
        assert response.status_code == 200
        results = response.json()
        assert "results" in results
        assert len(results["results"]) <= 10
        if results["results"]:
            assert "score" in results["results"][0]
            assert "document" in results["results"][0]
    
    @pytest.mark.asyncio
    async def test_hybrid_search(self, client):
        """Test hybrid text + vector search"""
        search_request = {
            "query": "fMRI studies of working memory",
            "search_type": "hybrid",
            "filters": {
                "modality": "fMRI",
                "year_min": 2015
            }
        }
        response = await client.post(f"{NEUROKG_URL}/search/hybrid", json=search_request)
        assert response.status_code == 200
        results = response.json()
        assert "text_results" in results
        assert "vector_results" in results
        assert "combined_results" in results
    
    @pytest.mark.asyncio
    async def test_graph_traversal(self, client):
        """Test multi-hop graph traversal"""
        traversal_request = {
            "start_node": "task_001",
            "traversal_type": "breadth_first",
            "max_depth": 3,
            "edge_types": ["MEASURES", "ACTIVATES"],
            "return_paths": True
        }
        response = await client.post(f"{NEUROKG_URL}/traversal/multi-hop", json=traversal_request)
        assert response.status_code == 200
        results = response.json()
        assert "nodes" in results
        assert "paths" in results
        assert "statistics" in results
    
    @pytest.mark.asyncio
    async def test_temporal_query(self, client):
        """Test temporal graph queries"""
        temporal_request = {
            "query_type": "evolution",
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
            "granularity": "monthly",
            "metrics": ["node_count", "edge_count", "density"]
        }
        response = await client.post(f"{NEUROKG_URL}/temporal/query", json=temporal_request)
        assert response.status_code == 200
        results = response.json()
        assert "timeline" in results
        assert "metrics" in results
    
    @pytest.mark.asyncio
    async def test_sparql_federation(self, client):
        """Test SPARQL federation queries"""
        sparql_query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?concept ?label
        WHERE {
            ?concept rdfs:label ?label .
            FILTER(CONTAINS(?label, "memory"))
        }
        LIMIT 10
        """
        response = await client.post(
            f"{NEUROKG_URL}/sparql",
            data=sparql_query,
            headers={"Content-Type": "application/sparql-query"}
        )
        assert response.status_code == 200
        results = response.json()
        assert "results" in results
        assert "bindings" in results["results"]


class TestAgentService:
    """Test Agent Service integration enhancements"""
    
    @pytest_asyncio.fixture
    async def client(self):
        async with httpx.AsyncClient() as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_tool_recommendation(self, client):
        """Test tool recommendation system"""
        request = {
            "query": "I want to analyze motor cortex activation",
            "context": {
                "dataset": "ds000114",
                "modality": "fMRI",
                "previous_tools": ["fsl_feat"]
            }
        }
        response = await client.post(f"{AGENT_URL}/tools/recommend", json=request)
        assert response.status_code == 200
        recommendations = response.json()
        assert "recommendations" in recommendations
        assert len(recommendations["recommendations"]) > 0
        assert "tool_name" in recommendations["recommendations"][0]
        assert "confidence" in recommendations["recommendations"][0]
    
    @pytest.mark.asyncio
    async def test_parameter_inference(self, client):
        """Test parameter inference system"""
        request = {
            "tool": "fsl_feat",
            "context": {
                "dataset_id": "ds000114",
                "task": "finger_tapping",
                "tr": 2.0
            }
        }
        response = await client.post(f"{AGENT_URL}/tools/infer-parameters", json=request)
        assert response.status_code == 200
        parameters = response.json()
        assert "inferred_parameters" in parameters
        assert "confidence_scores" in parameters
        assert "smoothing_fwhm" in parameters["inferred_parameters"]
    
    @pytest.mark.asyncio
    async def test_workflow_composition(self, client):
        """Test workflow composition"""
        request = {
            "intent": "Complete fMRI preprocessing and GLM analysis",
            "dataset": "ds000114",
            "constraints": {
                "max_duration": 3600,
                "preferred_tools": ["fmriprep", "fsl"]
            }
        }
        response = await client.post(f"{AGENT_URL}/workflow/compose", json=request)
        assert response.status_code == 200
        workflow = response.json()
        assert "workflow_id" in workflow
        assert "steps" in workflow
        assert len(workflow["steps"]) > 0
        assert "dependencies" in workflow
    
    @pytest.mark.asyncio
    async def test_evidence_collection(self, client):
        """Test evidence collection and aggregation"""
        request = {
            "job_id": "test_job_123",
            "include_provenance": True,
            "aggregation_method": "consensus"
        }
        response = await client.get(f"{AGENT_URL}/evidence/{request['job_id']}")
        assert response.status_code == 200
        evidence = response.json()
        assert "evidence_items" in evidence
        assert "aggregated_confidence" in evidence
        assert "provenance_graph" in evidence
    
    @pytest.mark.asyncio
    async def test_error_recovery(self, client):
        """Test error recovery mechanisms"""
        request = {
            "job_id": "failed_job_123",
            "error_type": "memory_exceeded",
            "context": {
                "tool": "fsl_feat",
                "dataset_size": "large"
            }
        }
        response = await client.post(f"{AGENT_URL}/recovery/suggest", json=request)
        assert response.status_code == 200
        recovery = response.json()
        assert "recovery_strategies" in recovery
        assert len(recovery["recovery_strategies"]) > 0
        assert "strategy_type" in recovery["recovery_strategies"][0]
        assert "confidence" in recovery["recovery_strategies"][0]


class TestServiceCommunication:
    """Test inter-service communication and service mesh"""
    
    @pytest_asyncio.fixture
    async def client(self):
        async with httpx.AsyncClient() as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_service_discovery(self, client):
        """Test service discovery mechanism"""
        response = await client.get(f"{GATEWAY_URL}/services/discover")
        assert response.status_code == 200
        services = response.json()
        assert "services" in services
        assert len(services["services"]) >= 3  # At least orchestrator, neurokg, agent
        
        for service in services["services"]:
            assert "name" in service
            assert "url" in service
            assert "health" in service
            assert "version" in service
    
    @pytest.mark.asyncio
    async def test_circuit_breaker(self, client):
        """Test circuit breaker functionality"""
        # Simulate multiple failed requests to trigger circuit breaker
        for _ in range(5):
            try:
                await client.get(f"{GATEWAY_URL}/test/failing-endpoint", timeout=1.0)
            except:
                pass
        
        # Circuit should be open now
        response = await client.get(f"{GATEWAY_URL}/circuit-breaker/status")
        assert response.status_code == 200
        status = response.json()
        assert "circuits" in status
        # At least one circuit should be open or half-open
    
    @pytest.mark.asyncio
    async def test_load_balancing(self, client):
        """Test load balancing across service instances"""
        responses = []
        for _ in range(10):
            response = await client.get(f"{GATEWAY_URL}/balanced/test")
            responses.append(response.headers.get("X-Service-Instance"))
        
        # Should have hit multiple instances
        unique_instances = set(responses)
        assert len(unique_instances) > 1
    
    @pytest.mark.asyncio
    async def test_request_transformation(self, client):
        """Test request/response transformation"""
        request = {
            "legacy_field": "value",
            "old_format": {"nested": "data"}
        }
        response = await client.post(
            f"{GATEWAY_URL}/transform/test",
            json=request,
            headers={"X-Transform-Version": "v2"}
        )
        assert response.status_code == 200
        transformed = response.json()
        assert "new_field" in transformed
        assert "legacy_field" not in transformed
    
    @pytest.mark.asyncio
    async def test_blue_green_deployment(self, client):
        """Test blue-green deployment routing"""
        # Check current deployment
        response = await client.get(f"{GATEWAY_URL}/deployment/status")
        assert response.status_code == 200
        deployment = response.json()
        assert "active" in deployment
        assert deployment["active"] in ["blue", "green"]
        
        # Test traffic routing
        response = await client.get(
            f"{GATEWAY_URL}/test/endpoint",
            headers={"X-Deployment-Target": "canary"}
        )
        assert response.status_code == 200
        assert response.headers.get("X-Deployment-Version") is not None


class TestEndToEndScenarios:
    """Test complete end-to-end scenarios"""
    
    @pytest_asyncio.fixture
    async def client(self):
        async with httpx.AsyncClient() as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_complete_analysis_workflow(self, client):
        """Test complete analysis workflow from submission to results"""
        # 1. Authenticate
        login_response = await client.post(
            f"{ORCHESTRATOR_URL}/auth/login",
            json={"username": "demo", "password": "demo123"}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Submit analysis job
        job_request = {
            "dataset_id": "ds000114",
            "analysis_type": "glm",
            "parameters": {
                "smoothing_fwhm": 6,
                "tr": 2.0,
                "motion_correction": True
            }
        }
        job_response = await client.post(
            f"{ORCHESTRATOR_URL}/run",
            json=job_request,
            headers=headers
        )
        job_id = job_response.json()["job_id"]
        
        # 3. Monitor job progress
        max_attempts = 30
        for _ in range(max_attempts):
            status_response = await client.get(
                f"{ORCHESTRATOR_URL}/jobs/{job_id}",
                headers=headers
            )
            status = status_response.json()
            if status["status"] == "completed":
                break
            await asyncio.sleep(1)
        
        assert status["status"] == "completed"
        
        # 4. Get evidence
        evidence_response = await client.get(
            f"{AGENT_URL}/evidence/{job_id}",
            headers=headers
        )
        evidence = evidence_response.json()
        assert len(evidence["evidence_items"]) > 0
        
        # 5. Query results in knowledge graph
        query = f"""
        query {{
            job(id: "{job_id}") {{
                results {{
                    activation_maps {{
                        region
                        peak_coordinate
                        t_value
                    }}
                }}
            }}
        }}
        """
        kg_response = await client.post(
            f"{NEUROKG_URL}/graphql",
            json={"query": query},
            headers=headers
        )
        kg_data = kg_response.json()
        assert "data" in kg_data
    
    @pytest.mark.asyncio
    async def test_chat_driven_analysis(self, client):
        """Test chat-driven analysis workflow"""
        # 1. Start chat session
        chat_response = await client.post(
            f"{AGENT_URL}/chat/start",
            json={"user_id": "test_user"}
        )
        session_id = chat_response.json()["session_id"]
        
        # 2. Send analysis request
        message_response = await client.post(
            f"{AGENT_URL}/chat/{session_id}/message",
            json={
                "message": "Analyze motor cortex activation in dataset ds000114 using GLM"
            }
        )
        response = message_response.json()
        assert "plan" in response
        assert "tools" in response["plan"]
        
        # 3. Confirm execution
        confirm_response = await client.post(
            f"{AGENT_URL}/chat/{session_id}/confirm",
            json={"confirmed": True}
        )
        execution = confirm_response.json()
        assert "job_id" in execution
        
        # 4. Get results
        await asyncio.sleep(5)  # Wait for processing
        results_response = await client.get(
            f"{AGENT_URL}/chat/{session_id}/results"
        )
        results = results_response.json()
        assert "summary" in results
        assert "visualizations" in results
        assert "evidence" in results


@pytest.mark.asyncio
async def test_system_resilience():
    """Test overall system resilience and recovery"""
    async with httpx.AsyncClient() as client:
        # Test system health
        health_checks = [
            f"{ORCHESTRATOR_URL}/health",
            f"{NEUROKG_URL}/health",
            f"{AGENT_URL}/health",
            f"{GATEWAY_URL}/health"
        ]
        
        for endpoint in health_checks:
            response = await client.get(endpoint)
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"
        
        # Test graceful degradation
        # Even if one service is down, others should continue
        # This would be tested with actual service failures in integration environment


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
