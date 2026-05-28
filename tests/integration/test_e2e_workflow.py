"""
End-to-end workflow integration tests.

Tests complete user journeys from landing page to results, including error scenarios
and fallback mechanisms for the Brain Researcher platform.
"""

import pytest
import asyncio
import httpx
import json
import time
import uuid
from typing import Dict, List, Any, Optional
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import websockets


# Test user scenarios
USER_SCENARIOS = {
    "beginner_researcher": {
        "profile": "PhD student, first time using neuroimaging analysis tools",
        "goals": ["learn GLM analysis", "understand results", "export findings"],
        "expected_path": ["landing", "demo_selection", "glm_demo", "results", "export"]
    },
    "experienced_researcher": {
        "profile": "Senior researcher, wants to explore connectivity analysis",
        "goals": ["run connectivity analysis", "compare with literature", "save workflow"],
        "expected_path": ["landing", "demo_selection", "connectivity_demo", "results", "share"]
    },
    "lab_manager": {
        "profile": "Lab manager evaluating the platform for team use",
        "goals": ["test multiple demos", "evaluate performance", "check reproducibility"],
        "expected_path": ["landing", "demo_gallery", "multiple_demos", "performance_review"]
    }
}


@pytest.fixture
async def e2e_client():
    """HTTP client configured for end-to-end testing."""
    timeout = httpx.Timeout(30.0, read=60.0)  # Longer timeout for full workflows
    async with httpx.AsyncClient(timeout=timeout) as client:
        yield client


@pytest.fixture
def mock_orchestrator_base_url():
    """Base URL for orchestrator service."""
    return "http://localhost:3001"


@pytest.fixture
def mock_web_ui_base_url():
    """Base URL for web UI."""
    return "http://localhost:3000"


class TestCompleteUserJourneys:
    """Test complete user workflows from start to finish."""
    
    @pytest.mark.asyncio
    async def test_beginner_glm_workflow(self, e2e_client, mock_orchestrator_base_url):
        """Test complete workflow for beginner user doing GLM analysis."""
        base_url = mock_orchestrator_base_url
        user_session = f"session_{uuid.uuid4().hex[:8]}"
        
        # Step 1: Land on homepage
        response = await e2e_client.get(f"{base_url}/api/landing/status")
        if response.status_code != 200:
            pytest.skip("Orchestrator service not available for E2E test")
            
        status_data = response.json()
        assert "demos_available" in status_data
        assert status_data["demos_available"] > 0
        
        # Step 2: Get available demo scenarios
        response = await e2e_client.get(f"{base_url}/api/landing/examples")
        examples = response.json()
        
        # Find GLM demo
        glm_demo = None
        for example in examples:
            if "glm" in example["id"].lower() or "motor" in example["title"].lower():
                glm_demo = example
                break
                
        assert glm_demo is not None, "GLM demo not found in examples"
        
        # Step 3: Start GLM demo
        demo_request = {
            "demo_type": "glm",
            "user_email": "test@example.com",
            "parameters": {"user_session": user_session}
        }
        
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=demo_request
        )
        
        assert response.status_code == 200
        start_result = response.json()
        assert "demo_id" in start_result
        demo_id = start_result["demo_id"]
        
        # Step 4: Monitor progress
        max_wait_time = 120  # 2 minutes
        start_time = time.time()
        
        while (time.time() - start_time) < max_wait_time:
            response = await e2e_client.get(
                f"{base_url}/api/landing/demos/{demo_id}/progress"
            )
            
            if response.status_code == 200:
                progress = response.json()
                
                if progress["status"] == "completed":
                    break
                elif progress["status"] == "failed":
                    pytest.fail(f"Demo failed: {progress}")
                    
                # Check progress is reasonable
                assert 0 <= progress["progress"] <= 100
                assert "current_step" in progress
                
            await asyncio.sleep(2)
        else:
            pytest.fail("Demo did not complete within expected time")
            
        # Step 5: Get results
        response = await e2e_client.get(
            f"{base_url}/api/landing/demos/{demo_id}/result"
        )
        
        assert response.status_code == 200
        result = response.json()
        
        # Verify result structure
        assert result["demo_id"] == demo_id
        assert result["status"] == "completed"
        assert "outputs" in result
        assert "visualizations" in result
        assert "evidence_rail" in result
        
        # Step 6: Download outputs
        for file_type in ["pdf", "png"]:
            response = await e2e_client.get(
                f"{base_url}/api/landing/demos/{demo_id}/download/{file_type}"
            )
            # Should either download successfully or return meaningful error
            assert response.status_code in [200, 404, 501]
            
        # Step 7: Create share link
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/{demo_id}/share"
        )
        
        if response.status_code == 200:
            share_data = response.json()
            assert "share_url" in share_data
            assert share_data["share_url"].startswith("http")
            
    @pytest.mark.asyncio
    async def test_experienced_connectivity_workflow(self, e2e_client, mock_orchestrator_base_url):
        """Test workflow for experienced researcher doing connectivity analysis."""
        base_url = mock_orchestrator_base_url
        
        # Step 1: Skip landing, go directly to connectivity demo
        demo_request = {
            "demo_type": "connectivity",
            "parameters": {
                "skip_intro": True,
                "advanced_mode": True
            }
        }
        
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=demo_request
        )
        
        if response.status_code != 200:
            pytest.skip("Cannot start connectivity demo")
            
        start_result = response.json()
        demo_id = start_result["demo_id"]
        
        # Step 2: Stream progress via WebSocket (if available)
        try:
            ws_url = f"ws://localhost:3001/api/landing/demos/{demo_id}/stream"
            async with websockets.connect(ws_url, open_timeout=5) as websocket:
                
                progress_updates = []
                timeout_count = 0
                
                while timeout_count < 10:  # Max 10 cycles
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(), 
                            timeout=3.0
                        )
                        
                        if message.startswith("data: "):
                            progress_data = json.loads(message[6:])
                            progress_updates.append(progress_data)
                            
                            if progress_data.get("status") == "completed":
                                break
                                
                    except asyncio.TimeoutError:
                        timeout_count += 1
                        continue
                        
                assert len(progress_updates) > 0
                
        except (
            websockets.exceptions.InvalidURI,
            websockets.exceptions.InvalidStatus,
            websockets.exceptions.InvalidHandshake,
            ConnectionRefusedError,
        ):
            # Fall back to polling if WebSocket not available
            await self._poll_demo_completion(e2e_client, base_url, demo_id)
            
        # Step 3: Get detailed results
        response = await e2e_client.get(
            f"{base_url}/api/landing/demos/{demo_id}/result"
        )
        
        assert response.status_code == 200
        result = response.json()
        
        # Verify connectivity-specific outputs
        outputs = result["outputs"]
        connectivity_outputs = [
            o for o in outputs 
            if "correlation" in o["name"] or "network" in o["name"]
        ]
        assert len(connectivity_outputs) > 0
        
    @pytest.mark.asyncio
    async def test_lab_manager_evaluation_workflow(self, e2e_client, mock_orchestrator_base_url):
        """Test workflow for lab manager evaluating multiple demos."""
        base_url = mock_orchestrator_base_url
        
        # Step 1: Get all available demos
        response = await e2e_client.get(f"{base_url}/api/landing/examples")
        if response.status_code != 200:
            pytest.skip("Cannot get demo examples")
            
        examples = response.json()
        demo_types = [ex["demo_type"] for ex in examples[:3]]  # Test first 3
        
        # Step 2: Start multiple demos concurrently
        demo_tasks = []
        for demo_type in demo_types:
            request = {
                "demo_type": demo_type,
                "parameters": {"batch_evaluation": True}
            }
            
            task = asyncio.create_task(
                self._run_single_demo(e2e_client, base_url, request)
            )
            demo_tasks.append((demo_type, task))
            
        # Step 3: Wait for all demos to complete
        results = []
        for demo_type, task in demo_tasks:
            try:
                result = await task
                results.append({
                    "demo_type": demo_type,
                    "success": True,
                    "demo_id": result["demo_id"],
                    "duration": result.get("duration", 0)
                })
            except Exception as e:
                results.append({
                    "demo_type": demo_type,
                    "success": False,
                    "error": str(e)
                })
                
        # Step 4: Analyze performance
        successful_demos = [r for r in results if r["success"]]
        assert len(successful_demos) > 0, "No demos completed successfully"
        
        # Check performance metrics
        avg_duration = sum(r["duration"] for r in successful_demos) / len(successful_demos)
        assert avg_duration < 180, f"Average demo duration too high: {avg_duration}s"
        
    async def _poll_demo_completion(self, client, base_url, demo_id, max_wait=120):
        """Helper to poll demo completion."""
        start_time = time.time()
        
        while (time.time() - start_time) < max_wait:
            response = await client.get(
                f"{base_url}/api/landing/demos/{demo_id}/progress"
            )
            
            if response.status_code == 200:
                progress = response.json()
                if progress["status"] in ["completed", "failed"]:
                    return progress
                    
            await asyncio.sleep(2)
            
        raise TimeoutError(f"Demo {demo_id} did not complete in {max_wait}s")
        
    async def _run_single_demo(self, client, base_url, request):
        """Helper to run a single demo to completion."""
        # Start demo
        response = await client.post(
            f"{base_url}/api/landing/demos/start",
            json=request
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to start demo: {response.status_code}")
            
        start_result = response.json()
        demo_id = start_result["demo_id"]
        
        # Wait for completion
        await self._poll_demo_completion(client, base_url, demo_id)
        
        # Get results
        response = await client.get(
            f"{base_url}/api/landing/demos/{demo_id}/result"
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to get demo result: {response.status_code}")
            
        return response.json()


class TestErrorScenarios:
    """Test various error conditions and recovery mechanisms."""
    
    @pytest.mark.asyncio
    async def test_invalid_demo_type_error(self, e2e_client, mock_orchestrator_base_url):
        """Test error handling for invalid demo type."""
        base_url = mock_orchestrator_base_url
        
        invalid_request = {
            "demo_type": "nonexistent_demo",
            "parameters": {}
        }
        
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=invalid_request
        )
        
        # Should return meaningful error
        assert response.status_code in [400, 422]
        
        error_data = response.json()
        assert "error" in error_data or "detail" in error_data
        
    @pytest.mark.asyncio
    async def test_demo_timeout_handling(self, e2e_client, mock_orchestrator_base_url):
        """Test handling of demo timeouts."""
        base_url = mock_orchestrator_base_url
        
        # Start a demo that might timeout
        request = {
            "demo_type": "glm",
            "parameters": {"force_timeout": True}
        }
        
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=request
        )
        
        if response.status_code != 200:
            pytest.skip("Cannot test timeout scenario")
            
        demo_id = response.json()["demo_id"]
        
        # Check for timeout handling
        max_checks = 30  # 1 minute
        for _ in range(max_checks):
            response = await e2e_client.get(
                f"{base_url}/api/landing/demos/{demo_id}/progress"
            )
            
            if response.status_code == 200:
                progress = response.json()
                if progress["status"] == "timeout":
                    # Timeout was properly handled
                    assert "error" in progress or "timeout" in progress["status"]
                    return
                elif progress["status"] in ["completed", "failed"]:
                    return  # Demo completed normally
                    
            await asyncio.sleep(2)
            
    @pytest.mark.asyncio
    async def test_service_unavailable_fallback(self, e2e_client, mock_orchestrator_base_url):
        """Test fallback mechanisms when services are unavailable."""
        base_url = mock_orchestrator_base_url
        
        # Test with service health check
        response = await e2e_client.get(f"{base_url}/api/landing/status")
        
        if response.status_code != 200:
            pytest.skip("Orchestrator not available for fallback test")
            
        status = response.json()
        
        # If some services are unavailable, should be reflected in status
        if "service_status" in status:
            unavailable_services = [
                service for service, health in status["service_status"].items()
                if health != "healthy"
            ]
            
            # System should still function with some services down
            assert status["server_status"] in ["healthy", "degraded"]
            
    @pytest.mark.asyncio
    async def test_concurrent_user_limit(self, e2e_client, mock_orchestrator_base_url):
        """Test behavior when concurrent user limits are reached."""
        base_url = mock_orchestrator_base_url
        
        # Start multiple concurrent demos
        concurrent_requests = 10
        tasks = []
        
        for i in range(concurrent_requests):
            request = {
                "demo_type": "glm",
                "parameters": {"user_id": f"concurrent_user_{i}"}
            }
            
            task = asyncio.create_task(
                e2e_client.post(
                    f"{base_url}/api/landing/demos/start",
                    json=request
                )
            )
            tasks.append(task)
            
        # Wait for all requests
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Some should succeed, some might be rate limited
        success_count = 0
        rate_limited_count = 0
        
        for response in responses:
            if isinstance(response, Exception):
                continue
                
            if response.status_code == 200:
                success_count += 1
            elif response.status_code == 429:  # Rate limited
                rate_limited_count += 1
                
        # At least some requests should succeed
        assert success_count > 0
        
        # If rate limiting is implemented, should see 429 responses
        if rate_limited_count > 0:
            assert rate_limited_count < concurrent_requests  # Not all should be limited


class TestFallbackMechanisms:
    """Test fallback mechanisms and graceful degradation."""
    
    @pytest.mark.asyncio
    async def test_cached_demo_fallback(self, e2e_client, mock_orchestrator_base_url):
        """Test fallback to cached results when services are slow."""
        base_url = mock_orchestrator_base_url
        
        # Request a demo that should be cached
        request = {
            "demo_type": "glm",
            "parameters": {"prefer_cache": True}
        }
        
        start_time = time.time()
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=request
        )
        
        if response.status_code != 200:
            pytest.skip("Cannot test cache fallback")
            
        demo_id = response.json()["demo_id"]
        
        # Wait for completion
        await self._wait_for_completion(e2e_client, base_url, demo_id)
        
        # Check if cache was used (should be faster)
        total_time = time.time() - start_time
        
        # Cached results should return quickly
        if total_time < 10:  # Less than 10 seconds suggests cache was used
            response = await e2e_client.get(
                f"{base_url}/api/landing/demos/{demo_id}/result"
            )
            
            result = response.json()
            # Should indicate cache was used
            if "run_card" in result and "performance_metrics" in result["run_card"]:
                assert "cache" in str(result["run_card"]["performance_metrics"]).lower()
                
    @pytest.mark.asyncio
    async def test_graceful_feature_degradation(self, e2e_client, mock_orchestrator_base_url):
        """Test graceful degradation when optional features fail."""
        base_url = mock_orchestrator_base_url
        
        # Start demo with optional features that might fail
        request = {
            "demo_type": "connectivity",
            "parameters": {
                "enable_3d_visualization": True,
                "enable_interactive_plots": True,
                "generate_pdf_report": True
            }
        }
        
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=request
        )
        
        if response.status_code != 200:
            pytest.skip("Cannot test feature degradation")
            
        demo_id = response.json()["demo_id"]
        await self._wait_for_completion(e2e_client, base_url, demo_id)
        
        # Get results
        response = await e2e_client.get(
            f"{base_url}/api/landing/demos/{demo_id}/result"
        )
        
        result = response.json()
        
        # Demo should complete even if some visualizations failed
        assert result["status"] == "completed"
        
        # Check if any features were degraded
        if "warnings" in result:
            warnings = result["warnings"]
            degraded_features = [
                w for w in warnings 
                if "degraded" in w.lower() or "unavailable" in w.lower()
            ]
            
            # System should still provide core functionality
            assert len(result["outputs"]) > 0
            
    async def _wait_for_completion(self, client, base_url, demo_id, max_wait=120):
        """Helper to wait for demo completion."""
        start_time = time.time()
        
        while (time.time() - start_time) < max_wait:
            response = await client.get(
                f"{base_url}/api/landing/demos/{demo_id}/progress"
            )
            
            if response.status_code == 200:
                progress = response.json()
                if progress["status"] in ["completed", "failed", "timeout"]:
                    return progress
                    
            await asyncio.sleep(2)
            
        raise TimeoutError(f"Demo {demo_id} did not complete")


class TestPerformanceCharacteristics:
    """Test performance aspects of the complete workflow."""
    
    @pytest.mark.asyncio
    async def test_response_time_sla(self, e2e_client, mock_orchestrator_base_url):
        """Test that workflows meet response time SLAs."""
        base_url = mock_orchestrator_base_url
        
        # Test landing page load time
        start_time = time.time()
        response = await e2e_client.get(f"{base_url}/api/landing/status")
        landing_time = time.time() - start_time
        
        # Landing page should load quickly
        assert landing_time < 2.0, f"Landing page took {landing_time:.2f}s"
        
        # Test demo start time
        start_time = time.time()
        demo_request = {"demo_type": "glm", "parameters": {}}
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=demo_request
        )
        start_response_time = time.time() - start_time
        
        # Demo should start quickly
        if response.status_code == 200:
            assert start_response_time < 5.0, f"Demo start took {start_response_time:.2f}s"
            
    @pytest.mark.asyncio
    async def test_memory_usage_patterns(self, e2e_client, mock_orchestrator_base_url):
        """Test memory usage during workflows."""
        base_url = mock_orchestrator_base_url
        
        # Start a demo and monitor memory usage claims
        request = {"demo_type": "preprocessing", "parameters": {}}
        response = await e2e_client.post(
            f"{base_url}/api/landing/demos/start",
            json=request
        )
        
        if response.status_code != 200:
            pytest.skip("Cannot test memory patterns")
            
        demo_id = response.json()["demo_id"]
        
        # Check if memory metrics are reported during execution
        for _ in range(10):  # Check up to 10 times
            response = await e2e_client.get(
                f"{base_url}/api/landing/demos/{demo_id}/progress"
            )
            
            if response.status_code == 200:
                progress = response.json()
                
                # If memory metrics are reported, verify they're reasonable
                if "memory_usage_mb" in progress:
                    memory_usage = progress["memory_usage_mb"]
                    assert 0 < memory_usage < 8192, f"Unreasonable memory usage: {memory_usage}MB"
                    
                if progress["status"] in ["completed", "failed"]:
                    break
                    
            await asyncio.sleep(3)


class TestDataIntegrity:
    """Test data integrity throughout the workflow."""
    
    @pytest.mark.asyncio
    async def test_demo_result_consistency(self, e2e_client, mock_orchestrator_base_url):
        """Test that demo results are consistent across runs."""
        base_url = mock_orchestrator_base_url
        
        # Run the same demo twice
        demo_request = {
            "demo_type": "glm",
            "parameters": {"seed": 42}  # Use deterministic seed
        }
        
        results = []
        for run in range(2):
            response = await e2e_client.post(
                f"{base_url}/api/landing/demos/start",
                json=demo_request
            )
            
            if response.status_code != 200:
                pytest.skip(f"Cannot start demo for run {run + 1}")
                
            demo_id = response.json()["demo_id"]
            await self._wait_for_completion(e2e_client, base_url, demo_id)
            
            # Get result
            response = await e2e_client.get(
                f"{base_url}/api/landing/demos/{demo_id}/result"
            )
            
            results.append(response.json())
            
        # Compare results
        result1, result2 = results
        
        # Core outputs should be consistent
        assert len(result1["outputs"]) == len(result2["outputs"])
        
        # Check artifact consistency
        artifacts1 = {a["name"]: a["size_bytes"] for a in result1.get("artifacts", [])}
        artifacts2 = {a["name"]: a["size_bytes"] for a in result2.get("artifacts", [])}
        
        # Artifact sizes should be identical for deterministic demos
        for name, size1 in artifacts1.items():
            if name in artifacts2:
                size2 = artifacts2[name]
                # Allow small variations for metadata
                assert abs(size1 - size2) < 1000, f"Artifact {name} size inconsistent: {size1} vs {size2}"
                
    async def _wait_for_completion(self, client, base_url, demo_id):
        """Helper method to wait for demo completion."""
        max_wait = 120
        start_time = time.time()
        
        while (time.time() - start_time) < max_wait:
            response = await client.get(
                f"{base_url}/api/landing/demos/{demo_id}/progress"
            )
            
            if response.status_code == 200:
                progress = response.json()
                if progress["status"] in ["completed", "failed"]:
                    return
                    
            await asyncio.sleep(2)
            
        raise TimeoutError("Demo did not complete")


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/test_e2e_workflow.py -v
    pytest.main([__file__, "-v", "--tb=short", "-x"])
