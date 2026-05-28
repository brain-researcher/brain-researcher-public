"""
Consumer contract tests: Orchestrator -> Agent Service.

These tests define the contract expectations that the Orchestrator has
when communicating with the Agent service.
"""

import pytest
import asyncio
from pathlib import Path

import pytest
try:
    from pact import Consumer, Provider
except ImportError:
    pytest.skip("pact Consumer/Provider not available (pact-python v3?)", allow_module_level=True)

from ..pact_config import pact_config, get_service_config
from ..pact_helpers.pact_client import PactClient, PactMatchers
from ..pact_helpers.mock_data import MockDataGenerator


class TestOrchestratorToAgentContract:
    """Contract tests from Orchestrator consumer perspective to Agent provider."""
    
    @pytest.fixture
    def pact_client(self):
        """Create Pact client for Orchestrator -> Agent contract."""
        orchestrator_config = get_service_config("orchestrator")
        agent_config = get_service_config("agent")
        return PactClient(orchestrator_config, agent_config)
    
    @pytest.mark.asyncio
    async def test_agent_health_check_contract(self, pact_client):
        """Test agent health check endpoint contract."""
        async with pact_client as pact:
            (pact
             .given("agent service is running")
             .upon_receiving("a request for agent health status")
             .with_request(
                 method="GET",
                 path="/health"
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
                     "version": "1.0.0"
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", "/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "queue_length" in data
            assert "active_jobs" in data
            assert "available_tools" in data
            assert "timestamp" in data
    
    @pytest.mark.asyncio
    async def test_execute_query_contract(self, pact_client):
        """Test query execution endpoint contract."""
        async with pact_client as pact:
            query_request = {
                "query": "Run GLM analysis on motor task data",
                "context": {
                    "dataset_id": "motor-task-001",
                    "user_id": "user_test123"
                },
                "parameters": {
                    "pipeline": "glm",
                    "smoothing": 6,
                    "threshold": 0.001
                },
                "thread_id": "thread_test123",
                "job_id": "job_test123"
            }
            
            (pact
             .given("agent can execute queries")
             .upon_receiving("a query execution request")
             .with_request(
                 method="POST",
                 path="/execute",
                 headers={"Content-Type": "application/json"},
                 body=query_request
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "execution_id": PactMatchers.uuid(),
                     "status": "accepted",
                     "estimated_duration": 120,
                     "steps": [
                         {
                             "id": "step_preprocess",
                             "name": "Data Preprocessing",
                             "tool": "fmriprep",
                             "estimated_duration": 60
                         },
                         {
                             "id": "step_glm",
                             "name": "GLM Analysis",
                             "tool": "fsl_glm", 
                             "estimated_duration": 60
                         }
                     ],
                     "stream_url": f"/executions/{PactMatchers.uuid().example}/stream"
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/execute",
                headers={"Content-Type": "application/json"},
                json_data=query_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "execution_id" in data
            assert data["status"] == "accepted"
            assert "estimated_duration" in data
            assert "steps" in data
            assert isinstance(data["steps"], list)
    
    @pytest.mark.asyncio
    async def test_get_execution_status_contract(self, pact_client):
        """Test execution status retrieval contract."""
        execution_id = "12345678-1234-1234-1234-123456789012"
        
        async with pact_client as pact:
            (pact
             .given("an execution is running")
             .upon_receiving("a request for execution status")
             .with_request(
                 method="GET",
                 path=f"/executions/{execution_id}"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "execution_id": execution_id,
                     "status": "running",
                     "progress": {
                         "current_step": 1,
                         "total_steps": 2,
                         "percentage": 50.0,
                         "estimated_remaining_seconds": 60
                     },
                     "current_step": {
                         "id": "step_glm",
                         "name": "GLM Analysis",
                         "status": "running",
                         "progress": 0.75
                     },
                     "completed_steps": [
                         {
                             "id": "step_preprocess", 
                             "name": "Data Preprocessing",
                             "status": "completed",
                             "duration_seconds": 45,
                             "artifacts": [
                                 {
                                     "id": "artifact_preprocessed",
                                     "type": "file",
                                     "name": "preprocessed_data.nii.gz",
                                     "url": "/api/artifacts/artifact_preprocessed"
                                 }
                             ]
                         }
                     ],
                     "artifacts": [],
                     "timing": {
                         "start_time": PactMatchers.iso_datetime(),
                         "estimated_end_time": PactMatchers.iso_datetime()
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", f"/executions/{execution_id}")
            
            assert response.status_code == 200
            data = response.json()
            assert data["execution_id"] == execution_id
            assert "status" in data
            assert "progress" in data
            assert "current_step" in data
            assert "completed_steps" in data
    
    @pytest.mark.asyncio
    async def test_cancel_execution_contract(self, pact_client):
        """Test execution cancellation contract."""
        execution_id = "12345678-1234-1234-1234-123456789012"
        
        async with pact_client as pact:
            (pact
             .given("an execution is running")
             .upon_receiving("a request to cancel execution")
             .with_request(
                 method="POST",
                 path=f"/executions/{execution_id}/cancel"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "execution_id": execution_id,
                     "status": "cancelled",
                     "message": "Execution cancelled successfully",
                     "cancelled_at": PactMatchers.iso_datetime()
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("POST", f"/executions/{execution_id}/cancel")
            
            assert response.status_code == 200
            data = response.json()
            assert data["execution_id"] == execution_id
            assert data["status"] == "cancelled"
    
    @pytest.mark.asyncio
    async def test_get_available_tools_contract(self, pact_client):
        """Test available tools listing contract."""
        async with pact_client as pact:
            (pact
             .given("agent has tools available")
             .upon_receiving("a request for available tools")
             .with_request(
                 method="GET",
                 path="/tools",
                 query={"category": "neuroimaging"}
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "tools": [
                         {
                             "id": "fsl_glm",
                             "name": "FSL GLM Analysis",
                             "category": "neuroimaging",
                             "description": "General Linear Model analysis using FSL",
                             "version": "6.0.5",
                             "parameters": [
                                 {
                                     "name": "smoothing",
                                     "type": "float",
                                     "default": 6.0,
                                     "required": False,
                                     "description": "FWHM smoothing kernel size"
                                 },
                                 {
                                     "name": "threshold",
                                     "type": "float",
                                     "default": 0.001,
                                     "required": False,
                                     "description": "Statistical threshold"
                                 }
                             ],
                             "required_inputs": ["fmri_data", "design_matrix"],
                             "outputs": ["statistical_map", "design_matrix_image"],
                             "estimated_runtime": "2-5 minutes"
                         },
                         {
                             "id": "fmriprep",
                             "name": "fMRIPrep Preprocessing",
                             "category": "neuroimaging",
                             "description": "Robust preprocessing pipeline",
                             "version": "21.0.1",
                             "parameters": [
                                 {
                                     "name": "skull_strip",
                                     "type": "boolean",
                                     "default": True,
                                     "required": False
                                 }
                             ],
                             "required_inputs": ["raw_fmri_data"],
                             "outputs": ["preprocessed_data", "confounds"],
                             "estimated_runtime": "30-60 minutes"
                         }
                     ],
                     "categories": ["neuroimaging", "statistics", "visualization"],
                     "total_count": 2
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "GET", "/tools",
                params={"category": "neuroimaging"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "tools" in data
            assert "categories" in data
            assert "total_count" in data
            assert isinstance(data["tools"], list)
            assert len(data["tools"]) == 2
    
    @pytest.mark.asyncio
    async def test_agent_busy_contract(self, pact_client):
        """Test agent busy response contract."""
        async with pact_client as pact:
            query_request = {
                "query": "Run analysis",
                "context": {},
                "parameters": {}
            }
            
            (pact
             .given("agent is busy with other jobs")
             .upon_receiving("a query when agent is busy")
             .with_request(
                 method="POST",
                 path="/execute",
                 headers={"Content-Type": "application/json"},
                 body=query_request
             )
             .will_respond_with(
                 status=503,
                 headers={"Content-Type": "application/json"},
                 body={
                     "error": {
                         "code": "SERVICE_UNAVAILABLE",
                         "message": "Agent is currently busy processing other requests",
                         "details": {
                             "queue_length": 5,
                             "estimated_wait_time": 300
                         },
                         "retry_after": 60,
                         "timestamp": PactMatchers.iso_datetime()
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/execute",
                headers={"Content-Type": "application/json"},
                json_data=query_request
            )
            
            assert response.status_code == 503
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "retry_after" in data["error"]
    
    @pytest.mark.asyncio
    async def test_execution_not_found_contract(self, pact_client):
        """Test execution not found error contract."""
        execution_id = "nonexistent-execution"
        
        async with pact_client as pact:
            (pact
             .given("no executions exist")
             .upon_receiving("a request for non-existent execution")
             .with_request(
                 method="GET",
                 path=f"/executions/{execution_id}"
             )
             .will_respond_with(
                 status=404,
                 headers={"Content-Type": "application/json"},
                 body={
                     "error": {
                         "code": "NOT_FOUND",
                         "message": f"Execution {execution_id} not found",
                         "timestamp": PactMatchers.iso_datetime()
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", f"/executions/{execution_id}")
            
            assert response.status_code == 404
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "NOT_FOUND"
    
    @pytest.mark.asyncio
    async def test_get_agent_metrics_contract(self, pact_client):
        """Test agent metrics endpoint contract."""
        async with pact_client as pact:
            (pact
             .given("agent has metrics available")
             .upon_receiving("a request for agent metrics")
             .with_request(
                 method="GET",
                 path="/metrics"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "metrics": {
                         "executions_total": 150,
                         "executions_successful": 142,
                         "executions_failed": 8,
                         "average_execution_time_seconds": 85.5,
                         "queue_length": 2,
                         "active_executions": 3,
                         "tools_used": {
                             "fsl_glm": 45,
                             "fmriprep": 32,
                             "nilearn_decoding": 28
                         },
                         "error_rates": {
                             "timeout": 0.02,
                             "tool_error": 0.03,
                             "validation_error": 0.01
                         }
                     },
                     "timestamp": PactMatchers.iso_datetime(),
                     "collection_period": "last_24h"
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", "/metrics")
            
            assert response.status_code == 200
            data = response.json()
            assert "metrics" in data
            metrics = data["metrics"]
            assert "executions_total" in metrics
            assert "executions_successful" in metrics
            assert "average_execution_time_seconds" in metrics
            assert "tools_used" in metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])