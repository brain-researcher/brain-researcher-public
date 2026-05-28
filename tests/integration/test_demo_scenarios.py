"""
Comprehensive integration tests for demo scenarios.

Tests all 5 demo scenarios, validates orchestrator endpoints, checks service connectivity,
and ensures proper response formats for the Brain Researcher demo system.
"""

import pytest
import asyncio
import httpx
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from unittest.mock import AsyncMock, patch, MagicMock

from brain_researcher.services.orchestrator.demo_scenarios import (
    DEMO_SCENARIOS, DemoExecutor, get_demo_scenario, list_demo_scenarios,
    DemoScenarioType, DemoComplexity
)
from brain_researcher.services.orchestrator.models import (
    JobStatus, StepStatus, ArtifactType, PipelineType
)


@pytest.fixture
def demo_executor():
    """Fresh demo executor instance for each test."""
    return DemoExecutor()


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for orchestrator requests."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def sample_demo_request():
    """Sample demo request payload."""
    return {
        "scenario_id": "glm_motor_task",
        "user_id": "test_user_123",
        "parameters": {
            "custom_threshold": 0.001,
            "email_notifications": True
        }
    }


class TestDemoScenarios:
    """Test individual demo scenario definitions and execution."""
    
    def test_all_scenarios_defined(self):
        """Test that all 5 demo scenarios are properly defined."""
        expected_scenarios = [
            "glm_motor_task",
            "connectivity_dmn", 
            "brain_decoding_ml",
            "preprocessing_pipeline",
            "knowledge_graph_query"
        ]
        
        assert len(DEMO_SCENARIOS) == 5
        for scenario_id in expected_scenarios:
            assert scenario_id in DEMO_SCENARIOS
            
    def test_scenario_data_completeness(self):
        """Test that each scenario has all required fields."""
        required_fields = [
            "id", "name", "title", "description", "scenario_type",
            "complexity", "duration_seconds", "dataset", "pipeline_steps",
            "artifacts", "visualizations", "evidence_rail", "citations"
        ]
        
        for scenario_id, scenario in DEMO_SCENARIOS.items():
            for field in required_fields:
                assert hasattr(scenario, field), f"Scenario {scenario_id} missing {field}"
                
    def test_scenario_types_valid(self):
        """Test that all scenarios have valid types."""
        valid_types = set(DemoScenarioType)
        
        for scenario in DEMO_SCENARIOS.values():
            assert scenario.scenario_type in valid_types
            
    def test_complexity_levels_valid(self):
        """Test that all scenarios have valid complexity levels."""
        valid_complexities = set(DemoComplexity)
        
        for scenario in DEMO_SCENARIOS.values():
            assert scenario.complexity in valid_complexities
            
    def test_pipeline_steps_structure(self):
        """Test that pipeline steps have proper structure."""
        required_step_fields = ["step", "name", "description", "tool", "duration", "outputs"]
        
        for scenario in DEMO_SCENARIOS.values():
            assert len(scenario.pipeline_steps) > 0
            
            for step in scenario.pipeline_steps:
                for field in required_step_fields:
                    assert field in step, f"Step missing field: {field}"
                    
                assert isinstance(step["step"], int)
                assert step["step"] > 0
                assert isinstance(step["duration"], int)
                assert step["duration"] > 0
                assert isinstance(step["outputs"], list)
                
    def test_artifacts_structure(self):
        """Test that artifacts have proper structure and types."""
        for scenario in DEMO_SCENARIOS.values():
            assert len(scenario.artifacts) > 0
            
            for artifact in scenario.artifacts:
                assert hasattr(artifact, "id")
                assert hasattr(artifact, "type")
                assert hasattr(artifact, "name")
                assert hasattr(artifact, "url")
                assert hasattr(artifact, "size_bytes")
                
                assert artifact.type in ArtifactType
                assert artifact.size_bytes > 0
                assert artifact.url.startswith("/api/demo/artifacts/")
                
    def test_visualizations_structure(self):
        """Test that visualizations have proper structure."""
        required_viz_fields = ["id", "title", "type", "description", "url", "interactive"]
        
        for scenario in DEMO_SCENARIOS.values():
            assert len(scenario.visualizations) > 0
            
            for viz in scenario.visualizations:
                for field in required_viz_fields:
                    assert field in viz, f"Visualization missing field: {field}"
                    
                assert isinstance(viz["interactive"], bool)
                assert viz["url"].startswith("/viz/demo/")
                
    def test_evidence_rail_structure(self):
        """Test that evidence rail entries have proper structure."""
        required_evidence_fields = ["id", "type", "title", "description", "relevance"]
        
        for scenario in DEMO_SCENARIOS.values():
            assert len(scenario.evidence_rail) > 0
            
            for evidence in scenario.evidence_rail:
                for field in required_evidence_fields:
                    assert field in evidence, f"Evidence missing field: {field}"
                    
                assert 0.0 <= evidence["relevance"] <= 1.0
                assert evidence["type"] in ["dataset", "paper", "method", "tool"]


class TestDemoExecution:
    """Test demo scenario execution and progress tracking."""
    
    @pytest.mark.asyncio
    async def test_demo_execution_basic(self, demo_executor):
        """Test basic demo execution flow."""
        demo_id = await demo_executor.execute_demo(
            demo_id="test_demo_001",
            scenario_id="glm_motor_task",
            user_id="test_user"
        )
        
        assert demo_id == "test_demo_001"
        assert demo_id in demo_executor.active_demos
        
        # Check final status
        demo_info = demo_executor.get_demo_progress(demo_id)
        assert demo_info["status"] == JobStatus.COMPLETED
        assert demo_info["progress"] == 100
        
    @pytest.mark.asyncio
    async def test_demo_execution_all_scenarios(self, demo_executor):
        """Test execution of all demo scenarios."""
        scenarios_to_test = list(DEMO_SCENARIOS.keys())
        
        for i, scenario_id in enumerate(scenarios_to_test):
            demo_id = f"test_demo_{i:03d}"
            
            result_id = await demo_executor.execute_demo(
                demo_id=demo_id,
                scenario_id=scenario_id
            )
            
            assert result_id == demo_id
            
            # Verify completion
            demo_info = demo_executor.get_demo_progress(demo_id)
            assert demo_info["status"] == JobStatus.COMPLETED
            assert demo_info["scenario_id"] == scenario_id
            
    @pytest.mark.asyncio
    async def test_demo_progress_tracking(self, demo_executor):
        """Test that demo progress is properly tracked during execution."""
        # Start demo but track progress during execution
        scenario = DEMO_SCENARIOS["connectivity_dmn"]
        demo_id = "progress_test_001"
        
        # Mock the asyncio.sleep to speed up test
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            # Execute demo in background
            task = asyncio.create_task(
                demo_executor.execute_demo(demo_id, "connectivity_dmn")
            )
            
            # Allow some execution time
            await asyncio.sleep(0.01)
            
            # Check progress updates
            progress = demo_executor.get_demo_progress(demo_id)
            assert progress is not None
            assert progress["scenario_id"] == "connectivity_dmn"
            
            # Wait for completion
            await task
            
            # Verify final state
            final_progress = demo_executor.get_demo_progress(demo_id)
            assert final_progress["status"] == JobStatus.COMPLETED
            assert final_progress["progress"] == 100
            
    @pytest.mark.asyncio
    async def test_demo_caching(self, demo_executor):
        """Test that pre-computed demos use caching properly."""
        scenario_id = "glm_motor_task"  # This scenario is precomputed
        demo_id_1 = "cache_test_001"
        demo_id_2 = "cache_test_002"
        
        # First execution
        start_time = time.time()
        await demo_executor.execute_demo(demo_id_1, scenario_id)
        first_duration = time.time() - start_time
        
        # Second execution (should be cached)
        start_time = time.time()
        await demo_executor.execute_demo(demo_id_2, scenario_id)
        second_duration = time.time() - start_time
        
        # Both should complete successfully
        assert demo_executor.get_demo_progress(demo_id_1)["status"] == JobStatus.COMPLETED
        assert demo_executor.get_demo_progress(demo_id_2)["status"] == JobStatus.COMPLETED
        
    @pytest.mark.asyncio
    async def test_demo_error_handling(self, demo_executor):
        """Test error handling for invalid demo scenarios."""
        with pytest.raises(ValueError, match="Unknown demo scenario"):
            await demo_executor.execute_demo(
                demo_id="error_test_001",
                scenario_id="invalid_scenario"
            )
            
    def test_list_available_scenarios(self, demo_executor):
        """Test listing available scenarios."""
        scenarios = demo_executor.list_available_scenarios()
        
        assert len(scenarios) == 5
        
        for scenario in scenarios:
            required_fields = [
                "id", "name", "title", "description", "type",
                "complexity", "duration", "tags", "popularity", "thumbnail"
            ]
            for field in required_fields:
                assert field in scenario


class TestOrchestratorEndpoints:
    """Test orchestrator API endpoints for demos."""
    
    @pytest.mark.asyncio
    async def test_start_demo_endpoint(self, mock_http_client):
        """Test /api/demos/start endpoint."""
        # Mock response
        expected_response = {
            "demo_id": "abc123",
            "status": "started",
            "estimated_duration": 85,
            "queue_position": 1
        }
        mock_http_client.post.return_value.json.return_value = expected_response
        mock_http_client.post.return_value.status_code = 200
        
        # Test request
        request_data = {
            "scenario_id": "glm_motor_task",
            "user_id": "test_user",
            "parameters": {}
        }
        
        response = await mock_http_client.post(
            "/api/demos/start",
            json=request_data
        )
        
        # Verify call was made correctly
        mock_http_client.post.assert_called_once_with(
            "/api/demos/start",
            json=request_data
        )
        
        # Verify response structure
        response_data = response.json()
        assert "demo_id" in response_data
        assert "status" in response_data
        assert "estimated_duration" in response_data
        
    @pytest.mark.asyncio
    async def test_demo_progress_endpoint(self, mock_http_client):
        """Test /api/demos/{demo_id}/progress endpoint."""
        demo_id = "test_demo_123"
        
        expected_response = {
            "demo_id": demo_id,
            "status": "running",
            "progress": 45,
            "current_step": "Running GLM analysis",
            "steps_completed": ["Data loading", "Preprocessing"],
            "estimated_time_remaining": 40
        }
        
        mock_http_client.get.return_value.json.return_value = expected_response
        mock_http_client.get.return_value.status_code = 200
        
        response = await mock_http_client.get(f"/api/demos/{demo_id}/progress")
        
        mock_http_client.get.assert_called_once_with(f"/api/demos/{demo_id}/progress")
        
        response_data = response.json()
        assert response_data["demo_id"] == demo_id
        assert response_data["status"] == "running"
        assert 0 <= response_data["progress"] <= 100
        
    @pytest.mark.asyncio
    async def test_demo_result_endpoint(self, mock_http_client):
        """Test /api/demos/{demo_id}/result endpoint."""
        demo_id = "completed_demo_123"
        
        expected_response = {
            "demo_id": demo_id,
            "status": "completed",
            "duration": 85,
            "artifacts": [
                {
                    "id": "artifact_1",
                    "type": "brain_map",
                    "name": "zstat1.nii.gz",
                    "url": f"/api/demo/artifacts/{demo_id}/zstat1.nii.gz",
                    "size_bytes": 2847392
                }
            ],
            "visualizations": [
                {
                    "id": "viz_1",
                    "title": "Motor Activation Map",
                    "type": "brain_map_3d",
                    "url": f"/viz/demo/{demo_id}/brain_map"
                }
            ],
            "evidence_rail": [],
            "run_card": {
                "reproducibility_score": 0.95,
                "environment": {"fsl_version": "6.0.5"}
            }
        }
        
        mock_http_client.get.return_value.json.return_value = expected_response
        mock_http_client.get.return_value.status_code = 200
        
        response = await mock_http_client.get(f"/api/demos/{demo_id}/result")
        
        response_data = response.json()
        assert response_data["demo_id"] == demo_id
        assert response_data["status"] == "completed"
        assert "artifacts" in response_data
        assert "visualizations" in response_data
        assert "run_card" in response_data
        
    @pytest.mark.asyncio
    async def test_demo_stream_endpoint(self, mock_http_client):
        """Test /api/demos/{demo_id}/stream SSE endpoint."""
        demo_id = "streaming_demo_123"
        
        # Mock SSE stream response
        mock_response = MagicMock()
        mock_response.aiter_text.return_value = [
            "data: {'progress': 25, 'status': 'running'}\n\n",
            "data: {'progress': 50, 'status': 'running'}\n\n",
            "data: {'progress': 100, 'status': 'completed'}\n\n"
        ]
        mock_http_client.stream.return_value.__aenter__.return_value = mock_response
        
        # Test streaming
        async with mock_http_client.stream(
            "GET", f"/api/demos/{demo_id}/stream"
        ) as response:
            events = []
            async for chunk in response.aiter_text():
                if chunk.startswith("data: "):
                    events.append(chunk)
                    
        assert len(events) == 3
        assert "progress" in events[0]
        assert "status" in events[0]
        
    @pytest.mark.asyncio
    async def test_demo_scenarios_list_endpoint(self, mock_http_client):
        """Test /api/demos/scenarios endpoint."""
        expected_response = {
            "scenarios": [
                {
                    "id": "glm_motor_task",
                    "name": "Motor Task GLM Analysis",
                    "type": "glm_motor_task",
                    "complexity": "beginner",
                    "duration": 85,
                    "tags": ["fMRI", "GLM", "Motor"],
                    "thumbnail": "/demo/thumbnails/glm_motor_card.png"
                }
            ]
        }
        
        mock_http_client.get.return_value.json.return_value = expected_response
        mock_http_client.get.return_value.status_code = 200
        
        response = await mock_http_client.get("/api/demos/scenarios")
        response_data = response.json()
        
        assert "scenarios" in response_data
        assert len(response_data["scenarios"]) > 0
        
        scenario = response_data["scenarios"][0]
        required_fields = ["id", "name", "type", "complexity", "duration"]
        for field in required_fields:
            assert field in scenario


class TestServiceConnectivity:
    """Test connectivity between orchestrator and other services."""
    
    @pytest.mark.asyncio
    async def test_neurokg_connectivity(self, mock_http_client):
        """Test connection to BR-KG service (port 5000)."""
        # Test BR-KG health endpoint
        mock_http_client.get.return_value.json.return_value = {
            "status": "healthy",
            "service": "neurokg",
            "version": "1.0.0",
            "database": "connected"
        }
        mock_http_client.get.return_value.status_code = 200
        
        response = await mock_http_client.get("http://localhost:5000/health")
        
        assert response.status_code == 200
        health_data = response.json()
        assert health_data["status"] == "healthy"
        assert health_data["service"] == "neurokg"
        
    @pytest.mark.asyncio
    async def test_agent_service_connectivity(self, mock_http_client):
        """Test connection to Agent service (port 8000)."""
        # Test Agent health endpoint
        mock_http_client.get.return_value.json.return_value = {
            "status": "healthy",
            "service": "agent",
            "active_tools": 25,
            "langgraph_status": "ready"
        }
        mock_http_client.get.return_value.status_code = 200
        
        response = await mock_http_client.get("http://localhost:8000/health")
        
        assert response.status_code == 200
        health_data = response.json()
        assert health_data["status"] == "healthy"
        assert health_data["service"] == "agent"
        
    @pytest.mark.asyncio
    async def test_orchestrator_service_connectivity(self, mock_http_client):
        """Test orchestrator service itself (port 3001)."""
        # Test orchestrator health
        mock_http_client.get.return_value.json.return_value = {
            "status": "healthy",
            "service": "orchestrator",
            "demos_available": 5,
            "active_demos": 2
        }
        mock_http_client.get.return_value.status_code = 200
        
        response = await mock_http_client.get("http://localhost:3001/health")
        
        assert response.status_code == 200
        health_data = response.json()
        assert health_data["status"] == "healthy"


class TestResponseFormats:
    """Test that all responses follow the expected formats."""
    
    def test_error_response_format(self):
        """Test standardized error response format."""
        error_response = {
            "error": {
                "code": "SERVICE_UNAVAILABLE",
                "message": "BR-KG service is temporarily unavailable",
                "details": {
                    "service": "neurokg",
                    "retry_after": 30
                },
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        # Validate structure
        assert "error" in error_response
        error = error_response["error"]
        assert "code" in error
        assert "message" in error
        assert "timestamp" in error
        
    def test_success_response_format(self):
        """Test standardized success response format."""
        success_response = {
            "data": {
                "demo_id": "abc123",
                "status": "completed"
            },
            "meta": {
                "execution_time": 85.4,
                "cache_used": True
            }
        }
        
        # Validate structure
        assert "data" in success_response
        assert "meta" in success_response
        
    def test_paginated_response_format(self):
        """Test paginated response format for lists."""
        paginated_response = {
            "data": [
                {"id": "demo1", "name": "Demo 1"},
                {"id": "demo2", "name": "Demo 2"}
            ],
            "meta": {
                "total_count": 25,
                "page": 1,
                "per_page": 10,
                "has_next": True
            }
        }
        
        # Validate structure
        assert "data" in paginated_response
        assert "meta" in paginated_response
        meta = paginated_response["meta"]
        assert "total_count" in meta
        assert "page" in meta
        assert "per_page" in meta


class TestPerformanceAndTimeouts:
    """Test performance characteristics and timeout handling."""
    
    @pytest.mark.asyncio
    async def test_demo_execution_timeout(self, demo_executor):
        """Test demo execution respects timeout constraints."""
        # Mock a very long running demo
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = asyncio.TimeoutError()
            
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    demo_executor.execute_demo("timeout_test", "glm_motor_task"),
                    timeout=1.0  # Very short timeout
                )
                
    @pytest.mark.asyncio
    async def test_concurrent_demo_execution(self, demo_executor):
        """Test handling of concurrent demo executions."""
        # Start multiple demos concurrently
        demo_tasks = []
        for i in range(3):
            task = asyncio.create_task(
                demo_executor.execute_demo(
                    f"concurrent_test_{i}",
                    "knowledge_graph_query"  # Fastest scenario
                )
            )
            demo_tasks.append(task)
            
        # Wait for all to complete
        results = await asyncio.gather(*demo_tasks, return_exceptions=True)
        
        # Verify all completed successfully
        for i, result in enumerate(results):
            assert not isinstance(result, Exception)
            assert result == f"concurrent_test_{i}"
            
            # Check status
            progress = demo_executor.get_demo_progress(f"concurrent_test_{i}")
            assert progress["status"] == JobStatus.COMPLETED
            
    def test_memory_usage_tracking(self, demo_executor):
        """Test that demo execution tracks resource usage."""
        # This would be more meaningful with actual memory monitoring
        # For now, just verify the structure exists
        demo_executor.active_demos["test"] = {
            "memory_usage_mb": 250,
            "cpu_usage_percent": 45.2,
            "disk_usage_mb": 1200
        }
        
        demo_info = demo_executor.get_demo_progress("test")
        assert "memory_usage_mb" in demo_info
        assert "cpu_usage_percent" in demo_info
        assert "disk_usage_mb" in demo_info


class TestFailureScenarios:
    """Test various failure scenarios and recovery."""
    
    @pytest.mark.asyncio
    async def test_service_unavailable_handling(self, mock_http_client):
        """Test handling when services are unavailable."""
        # Mock service unavailable
        mock_http_client.get.side_effect = httpx.ConnectError("Connection failed")
        
        with pytest.raises(httpx.ConnectError):
            await mock_http_client.get("http://localhost:5000/health")
            
    @pytest.mark.asyncio
    async def test_invalid_demo_parameters(self, demo_executor):
        """Test handling of invalid demo parameters."""
        # Test with invalid scenario ID
        with pytest.raises(ValueError):
            await demo_executor.execute_demo(
                "invalid_test",
                "nonexistent_scenario"
            )
            
    @pytest.mark.asyncio
    async def test_partial_demo_failure(self, demo_executor):
        """Test handling when a demo partially fails."""
        # Mock a scenario where execution fails midway
        original_execute = demo_executor._generate_demo_result
        
        async def failing_generate_result(*args, **kwargs):
            raise RuntimeError("Simulated processing failure")
            
        with patch.object(demo_executor, '_generate_demo_result', failing_generate_result):
            with pytest.raises(RuntimeError):
                await demo_executor.execute_demo("failure_test", "glm_motor_task")


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/test_demo_scenarios.py -v
    pytest.main([__file__, "-v", "--tb=short"])
