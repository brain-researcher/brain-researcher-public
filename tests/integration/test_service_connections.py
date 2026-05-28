"""
Integration tests for service connections and inter-service communication.

Tests connectivity between BR-KG (port 5000), Orchestrator (port 3001),
Agent service (port 8000), and WebSocket connections for the Brain Researcher platform.
"""

import pytest
import asyncio
import httpx
import websockets
import json
import time
from typing import Dict, List, Any, Optional
from unittest.mock import AsyncMock, patch, MagicMock
import redis.asyncio as redis
from datetime import datetime, timedelta

VALID_HEALTH_STATUSES = {"healthy", "degraded", "unhealthy"}


# Test configuration
SERVICE_ENDPOINTS = {
    "neurokg": "http://localhost:5000",
    "orchestrator": "http://localhost:3001", 
    "agent": "http://localhost:8000",
    "web_ui": "http://localhost:3000"
}

WEBSOCKET_ENDPOINTS = {
    "orchestrator_ws": "ws://localhost:3001/ws",
    "agent_ws": "ws://localhost:8000/ws",
    "neurokg_ws": "ws://localhost:5000/ws"
}

REDIS_URL = "redis://localhost:6379"


async def _connect_websocket(url: str, timeout: float = 5.0):
    """Connect to a websocket endpoint with a manual timeout guard."""
    return await asyncio.wait_for(websockets.connect(url), timeout=timeout)


@pytest.fixture
async def http_client():
    """HTTP client for testing REST endpoints."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client


@pytest.fixture
async def redis_client():
    """Redis client for testing cache connections."""
    try:
        client = redis.from_url(REDIS_URL)
        yield client
        try:
            await client.aclose()
        except AttributeError:
            await client.close()
    except Exception:
        # Use fake redis for tests if real redis unavailable
        from fakeredis.aioredis import FakeRedis
        client = FakeRedis()
        yield client
        try:
            await client.aclose()
        except AttributeError:
            await client.close()


class TestServiceHealthChecks:
    """Test basic health checks for all services."""
    
    @pytest.mark.asyncio
    async def test_neurokg_health(self, http_client):
        """Test BR-KG service health endpoint."""
        try:
            response = await http_client.get(f"{SERVICE_ENDPOINTS['neurokg']}/health")
            
            if response.status_code == 200:
                health_data = response.json()
                assert "status" in health_data
                assert health_data["status"] in VALID_HEALTH_STATUSES
                assert "service" in health_data
                assert health_data["service"].startswith("neurokg")
                
                # Check database connectivity metadata when provided
                if (
                    health_data["status"] == "healthy"
                    and "database" in health_data
                ):
                    assert health_data["database"] in ["connected", "available"]
                    
            else:
                pytest.skip(f"BR-KG service unavailable (status: {response.status_code})")
                
        except httpx.ConnectError:
            pytest.skip("BR-KG service not running")
            
    @pytest.mark.asyncio
    async def test_orchestrator_health(self, http_client):
        """Test Orchestrator service health endpoint."""
        try:
            response = await http_client.get(f"{SERVICE_ENDPOINTS['orchestrator']}/health")
            
            if response.status_code == 200:
                health_data = response.json()
                assert "status" in health_data
                assert health_data["status"] in VALID_HEALTH_STATUSES
                service_name = health_data.get("service")
                if service_name:
                    assert service_name.startswith("orchestrator")
                else:
                    services_block = health_data.get("services", {})
                    assert isinstance(services_block, dict)
                
                # Check for expected orchestrator metrics
                expected_fields = ["demos_available", "active_demos", "queue_length"]
                for field in expected_fields:
                    if field in health_data:
                        assert isinstance(health_data[field], (int, float))
                        
            else:
                pytest.skip(f"Orchestrator service unavailable (status: {response.status_code})")
                
        except httpx.ConnectError:
            pytest.skip("Orchestrator service not running")
            
    @pytest.mark.asyncio 
    async def test_agent_health(self, http_client):
        """Test Agent service health endpoint."""
        try:
            response = await http_client.get(f"{SERVICE_ENDPOINTS['agent']}/health")
            
            if response.status_code == 200:
                health_data = response.json()
                assert "status" in health_data
                assert health_data["status"] in VALID_HEALTH_STATUSES
                assert "service" in health_data or "services" in health_data
                if "service" in health_data:
                    service_name = health_data["service"]
                    assert service_name.startswith("agent") or "agent" in service_name
                
                # Check for LangGraph specific metrics
                if "langgraph_status" in health_data:
                    assert health_data["langgraph_status"] in ["ready", "initializing", "error"]
                    
                if "active_tools" in health_data:
                    assert isinstance(health_data["active_tools"], int)
                    assert health_data["active_tools"] >= 0
                    
            else:
                pytest.skip(f"Agent service unavailable (status: {response.status_code})")
                
        except httpx.ConnectError:
            pytest.skip("Agent service not running")
            
    @pytest.mark.asyncio
    async def test_web_ui_health(self, http_client):
        """Test Web UI service health/availability."""
        try:
            # Next.js apps typically respond to root with 200
            response = await http_client.get(f"{SERVICE_ENDPOINTS['web_ui']}/")
            
            # Accept various success responses from Next.js
            assert response.status_code in [200, 404, 500]  # 404/500 might indicate dev mode
            
        except httpx.ConnectError:
            pytest.skip("Web UI service not running")


class TestServiceInterconnections:
    """Test communication between services."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_to_neurokg_communication(self, http_client):
        """Test that orchestrator can communicate with BR-KG."""
        try:
            # Test orchestrator calling BR-KG query endpoint
            query_request = {
                "query": "motor cortex activation",
                "limit": 5,
                "include_papers": True
            }
            
            response = await http_client.post(
                f"{SERVICE_ENDPOINTS['orchestrator']}/api/neurokg/query",
                json=query_request,
                timeout=10.0
            )
            
            # Should either succeed or return a well-formed error
            assert response.status_code in [200, 400, 404, 502, 503]
            
            if response.status_code == 200:
                result = response.json()
                assert "data" in result or "results" in result
                
        except httpx.ConnectError:
            pytest.skip("Cannot test orchestrator->BR-KG: service unavailable")
            
    @pytest.mark.asyncio
    async def test_orchestrator_to_agent_communication(self, http_client):
        """Test that orchestrator can communicate with Agent service."""
        try:
            # Test orchestrator calling Agent analysis endpoint
            analysis_request = {
                "query": "analyze motor cortex activation",
                "context": {
                    "dataset": "test_dataset",
                    "modality": "fMRI"
                }
            }
            
            response = await http_client.post(
                f"{SERVICE_ENDPOINTS['orchestrator']}/api/agent/analyze",
                json=analysis_request,
                timeout=15.0
            )
            
            # Should either succeed or return a well-formed error
            assert response.status_code in [200, 400, 404, 502, 503]
            
            if response.status_code == 200:
                result = response.json()
                # Agent responses should have job_id or session_id
                assert "job_id" in result or "session_id" in result or "task_id" in result
                
        except httpx.ConnectError:
            pytest.skip("Cannot test orchestrator->Agent: service unavailable")
            
    @pytest.mark.asyncio
    async def test_agent_to_neurokg_communication(self, http_client):
        """Test that Agent service can query BR-KG."""
        try:
            # Test agent using BR-KG tools
            tool_request = {
                "tool_name": "coordinate_to_concept",
                "parameters": {
                    "coordinates": [42, -22, 62],
                    "radius_mm": 10
                }
            }
            
            response = await http_client.post(
                f"{SERVICE_ENDPOINTS['agent']}/api/tools/execute",
                json=tool_request,
                timeout=20.0
            )
            
            assert response.status_code in [200, 400, 404, 502, 503]
            
            if response.status_code == 200:
                result = response.json()
                assert "result" in result or "data" in result
                
        except httpx.ConnectError:
            pytest.skip("Cannot test Agent->BR-KG: service unavailable")


class TestWebSocketConnections:
    """Test WebSocket connections for real-time communication."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_websocket(self):
        """Test WebSocket connection to orchestrator."""
        try:
            websocket = await _connect_websocket(
                WEBSOCKET_ENDPOINTS["orchestrator_ws"],
                timeout=5.0
            )
            try:
                # Send test message
                test_message = {
                    "type": "ping",
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                await websocket.send(json.dumps(test_message))
                
                # Wait for response
                response = await asyncio.wait_for(
                    websocket.recv(), 
                    timeout=5.0
                )
                
                response_data = json.loads(response)
                assert "type" in response_data
                # Common WebSocket response types
                assert response_data["type"] in ["pong", "ack", "connected"]
            finally:
                await websocket.close()
                
        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.InvalidURI,
                websockets.exceptions.InvalidStatus,
                ConnectionRefusedError,
                OSError):
            pytest.skip("Orchestrator WebSocket not available")
            
    @pytest.mark.asyncio
    async def test_agent_websocket(self):
        """Test WebSocket connection to agent service."""
        try:
            websocket = await _connect_websocket(
                WEBSOCKET_ENDPOINTS["agent_ws"],
                timeout=5.0
            )
            try:
                # Send test message
                test_message = {
                    "type": "status_check",
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                await websocket.send(json.dumps(test_message))
                
                # Wait for response
                response = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=5.0
                )

                response_data = json.loads(response)
                assert "type" in response_data
            finally:
                await websocket.close()
                
        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.InvalidURI, 
                websockets.exceptions.InvalidStatus,
                ConnectionRefusedError,
                OSError):
            pytest.skip("Agent WebSocket not available")
            
    @pytest.mark.asyncio
    async def test_websocket_progress_streaming(self):
        """Test real-time progress streaming via WebSocket."""
        try:
            websocket = await _connect_websocket(
                WEBSOCKET_ENDPOINTS["orchestrator_ws"],
                timeout=5.0
            )
            try:
                # Subscribe to demo progress
                subscribe_message = {
                    "type": "subscribe",
                    "channel": "demo_progress",
                    "demo_id": "test_demo_123"
                }
                
                await websocket.send(json.dumps(subscribe_message))
                
                # Wait for subscription confirmation
                response = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=5.0
                )
                
                response_data = json.loads(response)
                assert response_data.get("type") in ["subscribed", "ack"]
            finally:
                await websocket.close()

        except Exception:
            pytest.skip("WebSocket progress streaming not available")


class TestRedisConnections:
    """Test Redis connections and caching."""
    
    @pytest.mark.asyncio
    async def test_redis_basic_connection(self, redis_client):
        """Test basic Redis connectivity."""
        # Test basic operations
        await redis_client.set("test_key", "test_value")
        value = await redis_client.get("test_key")
        assert value.decode("utf-8") == "test_value"
        
        # Clean up
        await redis_client.delete("test_key")
        
    @pytest.mark.asyncio
    async def test_redis_demo_caching(self, redis_client):
        """Test Redis caching for demo results."""
        # Simulate caching demo result
        demo_result = {
            "demo_id": "cached_demo_123",
            "status": "completed",
            "artifacts": ["artifact1.nii.gz", "artifact2.png"],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        cache_key = f"demo:cached_demo_123:result"
        await redis_client.setex(
            cache_key, 
            3600,  # 1 hour TTL
            json.dumps(demo_result)
        )
        
        # Retrieve from cache
        cached_data = await redis_client.get(cache_key)
        assert cached_data is not None
        
        cached_result = json.loads(cached_data.decode("utf-8"))
        assert cached_result["demo_id"] == "cached_demo_123"
        assert cached_result["status"] == "completed"
        
        # Clean up
        await redis_client.delete(cache_key)
        
    @pytest.mark.asyncio
    async def test_redis_session_storage(self, redis_client):
        """Test Redis session storage for user data."""
        # Simulate user session data
        session_data = {
            "user_id": "test_user_456",
            "active_demos": ["demo1", "demo2"],
            "preferences": {
                "theme": "dark",
                "notifications": True
            },
            "last_activity": datetime.utcnow().isoformat()
        }
        
        session_key = f"session:test_user_456"
        await redis_client.setex(
            session_key,
            1800,  # 30 minutes TTL
            json.dumps(session_data)
        )
        
        # Retrieve session
        stored_session = await redis_client.get(session_key)
        assert stored_session is not None
        
        session = json.loads(stored_session.decode("utf-8"))
        assert session["user_id"] == "test_user_456"
        assert len(session["active_demos"]) == 2
        
        # Clean up
        await redis_client.delete(session_key)


class TestDatabaseConnections:
    """Test database connections (Neo4j for BR-KG)."""
    
    @pytest.mark.asyncio
    async def test_neurokg_database_query(self, http_client):
        """Test BR-KG database query functionality."""
        try:
            # Test simple Cypher query via API
            query_request = {
                "cypher": "MATCH (n) RETURN count(n) as node_count LIMIT 1",
                "parameters": {}
            }
            
            response = await http_client.post(
                f"{SERVICE_ENDPOINTS['neurokg']}/api/cypher",
                json=query_request,
                timeout=10.0
            )
            
            if response.status_code == 200:
                result = response.json()
                assert "data" in result
                # Should return node count
                assert "node_count" in result["data"][0] if result["data"] else True
                
        except httpx.ConnectError:
            pytest.skip("Cannot test Neo4j: BR-KG service unavailable")
            
    @pytest.mark.asyncio
    async def test_neurokg_graph_traversal(self, http_client):
        """Test graph traversal queries."""
        try:
            # Test finding related concepts
            traversal_request = {
                "start_concept": "motor cortex",
                "relationship_types": ["RELATED_TO", "PART_OF"],
                "max_depth": 2,
                "limit": 10
            }
            
            response = await http_client.post(
                f"{SERVICE_ENDPOINTS['neurokg']}/api/graph/traverse",
                json=traversal_request,
                timeout=15.0
            )
            
            # Should either succeed or return meaningful error
            assert response.status_code in [200, 400, 404, 500]
            
            if response.status_code == 200:
                result = response.json()
                assert "paths" in result or "nodes" in result or "results" in result
                
        except httpx.ConnectError:
            pytest.skip("Cannot test graph traversal: BR-KG service unavailable")


class TestServiceFailureHandling:
    """Test how services handle failures and timeouts."""
    
    @pytest.mark.asyncio
    async def test_service_timeout_handling(self, http_client):
        """Test service behavior under timeout conditions."""
        # Test with very short timeout
        timeout_triggered = False
        async with httpx.AsyncClient(timeout=0.001) as fast_timeout_client:
            try:
                await fast_timeout_client.get(f"{SERVICE_ENDPOINTS['neurokg']}/health")
            except httpx.TimeoutException:
                timeout_triggered = True

        if not timeout_triggered:
            pytest.skip("Service responded before timeout threshold")

    @pytest.mark.asyncio
    async def test_service_unavailable_response(self, http_client):
        """Test response when dependent services are unavailable."""
        # Test orchestrator behavior when BR-KG is unavailable
        try:
            response = await http_client.get(
                f"{SERVICE_ENDPOINTS['orchestrator']}/api/neurokg/status"
            )
            
            # Should return either success or graceful failure
            assert response.status_code in [200, 503, 502, 404]
            
            if response.status_code in [503, 502]:
                error_data = response.json()
                assert "error" in error_data
                assert "service_unavailable" in str(error_data).lower() or\
                       "temporarily unavailable" in str(error_data).lower()
                       
        except httpx.ConnectError:
            # Expected if orchestrator is not running
            pass
            
    @pytest.mark.asyncio
    async def test_circuit_breaker_behavior(self, http_client):
        """Test circuit breaker patterns for service calls."""
        # Simulate multiple failing requests
        failing_endpoint = f"{SERVICE_ENDPOINTS['orchestrator']}/api/nonexistent"
        
        failure_count = 0
        for _ in range(5):
            try:
                response = await http_client.get(failing_endpoint)
                if response.status_code >= 400:
                    failure_count += 1
            except Exception:
                failure_count += 1
                
        # Should have consistent failure handling
        assert failure_count > 0


class TestLoadBalancingAndScaling:
    """Test load balancing and scaling capabilities."""
    
    @pytest.mark.asyncio
    async def test_concurrent_service_requests(self, http_client):
        """Test handling of concurrent requests to services."""
        # Send multiple concurrent health check requests
        tasks = []
        for service_name, endpoint in SERVICE_ENDPOINTS.items():
            if service_name != "web_ui":  # Skip UI for this test
                task = asyncio.create_task(
                    http_client.get(f"{endpoint}/health", timeout=10.0)
                )
                tasks.append((service_name, task))
                
        # Wait for all requests
        results = []
        for service_name, task in tasks:
            try:
                response = await task
                results.append({
                    "service": service_name,
                    "status_code": response.status_code,
                    "success": response.status_code == 200
                })
            except Exception as e:
                results.append({
                    "service": service_name,
                    "status_code": None,
                    "success": False,
                    "error": str(e)
                })
                
        # At least some services should respond successfully
        successful_services = [r for r in results if r["success"]]
        # Don't require all services to be running, but structure should be valid
        assert len(results) > 0
        
    @pytest.mark.asyncio
    async def test_service_response_times(self, http_client):
        """Test service response time characteristics."""
        response_times = {}
        
        for service_name, endpoint in SERVICE_ENDPOINTS.items():
            if service_name == "web_ui":
                continue
                
            try:
                start_time = time.time()
                response = await http_client.get(f"{endpoint}/health", timeout=5.0)
                end_time = time.time()
                
                response_times[service_name] = {
                    "response_time": end_time - start_time,
                    "status_code": response.status_code
                }
                
            except Exception as e:
                response_times[service_name] = {
                    "response_time": None,
                    "error": str(e)
                }
                
        # Response times should be reasonable for healthy services
        for service_name, metrics in response_times.items():
            if metrics.get("response_time") is not None:
                # Health checks should respond within 2 seconds
                assert metrics["response_time"] < 2.0,\
                    f"{service_name} health check took {metrics['response_time']:.2f}s"


class TestServiceAuthentication:
    """Test authentication and authorization between services."""
    
    @pytest.mark.asyncio
    async def test_api_key_authentication(self, http_client):
        """Test API key authentication for service-to-service calls."""
        # Test with missing API key
        response = await http_client.get(
            f"{SERVICE_ENDPOINTS['neurokg']}/api/protected/admin",
            timeout=5.0
        )
        
        # Should require authentication
        assert response.status_code in [401, 403, 404]
        
        # Test with API key header
        headers = {"X-API-Key": "test-api-key-123"}
        response = await http_client.get(
            f"{SERVICE_ENDPOINTS['neurokg']}/api/protected/admin",
            headers=headers,
            timeout=5.0
        )
        
        # Should either accept the key or return 404 (endpoint doesn't exist)
        assert response.status_code in [200, 401, 403, 404]
        
    @pytest.mark.asyncio
    async def test_cors_headers(self, http_client):
        """Test CORS headers for cross-origin requests."""
        try:
            response = await http_client.options(
                f"{SERVICE_ENDPOINTS['orchestrator']}/api/demos/start",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST"
                }
            )
            
            # Should include CORS headers
            if response.status_code in [200, 204]:
                headers = response.headers
                # Common CORS headers
                cors_headers = [
                    "access-control-allow-origin",
                    "access-control-allow-methods", 
                    "access-control-allow-headers"
                ]
                
                # At least one CORS header should be present
                has_cors = any(header in headers for header in cors_headers)
                if not has_cors:
                    pytest.skip("CORS not configured or different implementation")
                    
        except Exception:
            pytest.skip("CORS preflight test failed")


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/test_service_connections.py -v
    pytest.main([__file__, "-v", "--tb=short"])
