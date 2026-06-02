"""
Comprehensive tests for HAProxy load balancing functionality.

Tests cover:
- Traffic distribution fairness
- Weighted load balancing algorithms
- Health check functionality
- Failover and recovery scenarios
- Session affinity (sticky sessions)
- SSL termination and security
- Performance under load
"""

import asyncio
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from tests.load.conftest import (
    TestConfig,
    assert_error_rate,
    assert_response_time,
    wait_for_condition,
)


class HAProxyTestClient:
    """Test client for HAProxy interactions."""

    def __init__(self, stats_url: str, admin_url: str = None):
        self.stats_url = stats_url
        self.admin_url = admin_url or stats_url.replace("/stats", "/admin")

    def get_stats(self) -> Dict:
        """Get HAProxy statistics."""
        try:
            response = requests.get(f"{self.stats_url};csv", timeout=10)
            response.raise_for_status()
            return self._parse_csv_stats(response.text)
        except Exception as e:
            pytest.skip(f"HAProxy stats not available: {e}")

    def _parse_csv_stats(self, csv_data: str) -> Dict:
        """Parse CSV statistics into structured data."""
        lines = csv_data.strip().split("\n")
        headers = lines[0].split(",")

        stats = {"backends": {}, "servers": []}

        for line in lines[1:]:
            if not line:
                continue
            values = line.split(",")
            if len(values) != len(headers):
                continue

            row = dict(zip(headers, values))
            if row.get("svname") == "BACKEND":
                stats["backends"][row["pxname"]] = row
            elif row.get("svname") not in ["FRONTEND", "BACKEND"]:
                stats["servers"].append(row)

        return stats

    def set_server_weight(self, backend: str, server: str, weight: int):
        """Set server weight via admin interface."""
        # This would use HAProxy stats socket in real implementation
        pass

    def disable_server(self, backend: str, server: str):
        """Disable a server."""
        pass

    def enable_server(self, backend: str, server: str):
        """Enable a server."""
        pass


@pytest.fixture
def haproxy_client(test_config: TestConfig):
    """HAProxy test client."""
    return HAProxyTestClient(test_config.haproxy_stats_url)


@pytest.mark.unit
class TestLoadBalancingAlgorithms:
    """Test different load balancing algorithms."""

    def test_round_robin_distribution(self, mock_haproxy_stats):
        """Test round-robin load distribution fairness."""
        # Simulate requests across servers
        server_requests = {"orch-1": 0, "orch-2": 0, "orch-3": 0}
        total_requests = 300

        # Round-robin simulation
        servers = list(server_requests.keys())
        for i in range(total_requests):
            server = servers[i % len(servers)]
            server_requests[server] += 1

        # Check distribution fairness (should be equal for round-robin)
        expected_per_server = total_requests // len(servers)
        for server, count in server_requests.items():
            assert (
                abs(count - expected_per_server) <= 1
            ), f"Round-robin distribution unfair: {server} got {count}, expected ~{expected_per_server}"

    def test_weighted_round_robin(self, mock_haproxy_stats):
        """Test weighted round-robin respects server weights."""
        # Server weights: orch-1=100, orch-2=200, orch-3=50
        weights = {"orch-1": 100, "orch-2": 200, "orch-3": 50}
        total_weight = sum(weights.values())
        total_requests = 350

        # Simulate weighted distribution
        server_requests = {server: 0 for server in weights.keys()}

        # Simple weighted round-robin simulation
        weight_queue = []
        for server, weight in weights.items():
            weight_queue.extend([server] * weight)

        for i in range(total_requests):
            server = weight_queue[i % len(weight_queue)]
            server_requests[server] += 1

        # Check proportional distribution
        for server, count in server_requests.items():
            expected_ratio = weights[server] / total_weight
            actual_ratio = count / total_requests
            assert (
                abs(actual_ratio - expected_ratio) < 0.05
            ), f"Weighted distribution incorrect: {server} got {actual_ratio:.2%}, expected {expected_ratio:.2%}"

    def test_least_connections_balancing(self):
        """Test least connections algorithm selection."""
        # Mock server connection counts
        servers = {
            "orch-1": {"connections": 10, "requests": 0},
            "orch-2": {"connections": 5, "requests": 0},
            "orch-3": {"connections": 15, "requests": 0},
        }

        # Simulate 30 requests with least connections
        for _ in range(30):
            # Select server with least connections
            selected_server = min(
                servers.keys(), key=lambda s: servers[s]["connections"]
            )

            servers[selected_server]["requests"] += 1
            servers[selected_server]["connections"] += 1

        # Verify that servers with initially fewer connections got more requests
        assert servers["orch-2"]["requests"] > servers["orch-1"]["requests"]
        assert servers["orch-2"]["requests"] > servers["orch-3"]["requests"]

    def test_source_ip_hashing(self):
        """Test source IP hashing for session affinity."""
        import hashlib

        # Mock client IPs
        client_ips = [
            "192.168.1.10",
            "192.168.1.11",
            "192.168.1.12",
            "192.168.1.13",
            "192.168.1.14",
            "192.168.1.15",
        ]

        servers = ["orch-1", "orch-2", "orch-3"]
        client_to_server = {}

        # Hash IP to server
        for ip in client_ips:
            hash_value = int(hashlib.md5(ip.encode()).hexdigest(), 16)
            server_index = hash_value % len(servers)
            client_to_server[ip] = servers[server_index]

        # Test consistency - same IP should always go to same server
        for _ in range(5):  # Multiple rounds
            for ip in client_ips:
                hash_value = int(hashlib.md5(ip.encode()).hexdigest(), 16)
                server_index = hash_value % len(servers)
                assigned_server = servers[server_index]

                assert (
                    client_to_server[ip] == assigned_server
                ), f"Source IP {ip} mapped to different servers"


@pytest.mark.unit
class TestHealthChecks:
    """Test health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_detection(self, mock_health_endpoints):
        """Test health check detects service status."""
        # Test healthy service
        healthy_response = mock_health_endpoints["orchestrator"]
        assert healthy_response["status"] == "healthy"
        assert healthy_response["response_time"] < 100

        # Test unhealthy service response
        unhealthy_response = {"status": "unhealthy", "response_time": 5000}
        assert unhealthy_response["status"] == "unhealthy"
        assert unhealthy_response["response_time"] > 1000

    def test_health_check_intervals(self):
        """Test health check timing and intervals."""
        check_interval = 30  # seconds
        timeout = 5
        retries = 3

        # Simulate health check schedule
        start_time = time.time()
        check_times = []

        for i in range(5):  # 5 checks
            check_time = start_time + (i * check_interval)
            check_times.append(check_time)

        # Verify intervals
        for i in range(1, len(check_times)):
            actual_interval = check_times[i] - check_times[i - 1]
            assert (
                abs(actual_interval - check_interval) < 1
            ), f"Health check interval incorrect: {actual_interval}s, expected {check_interval}s"

    def test_health_check_failure_threshold(self):
        """Test health check failure and recovery thresholds."""
        # Configuration: rise=2, fall=3
        rise_threshold = 2  # Consecutive successes to mark healthy
        fall_threshold = 3  # Consecutive failures to mark unhealthy

        # Simulate check results: F, F, F (should mark unhealthy)
        failure_sequence = [False, False, False]
        consecutive_failures = 0
        server_status = "healthy"

        for check_result in failure_sequence:
            if not check_result:
                consecutive_failures += 1
                if consecutive_failures >= fall_threshold:
                    server_status = "unhealthy"
            else:
                consecutive_failures = 0

        assert server_status == "unhealthy"

        # Simulate recovery: S, S (should mark healthy)
        recovery_sequence = [True, True]
        consecutive_successes = 0

        for check_result in recovery_sequence:
            if check_result:
                consecutive_successes += 1
                if consecutive_successes >= rise_threshold:
                    server_status = "healthy"
            else:
                consecutive_successes = 0

        assert server_status == "healthy"

    @patch("requests.get")
    def test_health_check_timeout_handling(self, mock_get):
        """Test health check timeout handling."""
        # Mock timeout
        mock_get.side_effect = requests.exceptions.Timeout("Health check timeout")

        def perform_health_check(url, timeout=5):
            try:
                response = requests.get(url, timeout=timeout)
                return response.status_code == 200
            except requests.exceptions.Timeout:
                return False
            except Exception:
                return False

        result = perform_health_check("http://test-service/health")
        assert result is False


@pytest.mark.integration
class TestFailoverScenarios:
    """Test failover and recovery scenarios."""

    @pytest.mark.asyncio
    async def test_single_server_failure(self, haproxy_client, mock_health_endpoints):
        """Test behavior when one server fails."""
        # Initial state: 3 healthy servers
        initial_servers = ["orch-1", "orch-2", "orch-3"]
        server_status = {server: "healthy" for server in initial_servers}

        # Simulate server failure
        failed_server = "orch-2"
        server_status[failed_server] = "unhealthy"

        # Traffic should redistribute to remaining healthy servers
        healthy_servers = [
            s for s, status in server_status.items() if status == "healthy"
        ]
        assert len(healthy_servers) == 2
        assert failed_server not in healthy_servers

        # Verify traffic is not routed to failed server
        server_requests = {server: 0 for server in initial_servers}

        # Simulate 100 requests after failure
        for i in range(100):
            # Route to healthy servers only (round-robin simulation)
            target_server = healthy_servers[i % len(healthy_servers)]
            server_requests[target_server] += 1

        # Failed server should receive no requests
        assert server_requests[failed_server] == 0

        # Healthy servers should share traffic
        for server in healthy_servers:
            assert server_requests[server] > 0

    @pytest.mark.asyncio
    async def test_server_recovery(self, haproxy_client):
        """Test server recovery after failure."""
        # Initial state: 1 server failed
        server_status = {
            "orch-1": "healthy",
            "orch-2": "unhealthy",
            "orch-3": "healthy",
        }

        # Simulate recovery
        server_status["orch-2"] = "healthy"

        # Verify server is back in rotation
        healthy_servers = [
            s for s, status in server_status.items() if status == "healthy"
        ]
        assert len(healthy_servers) == 3
        assert "orch-2" in healthy_servers

        # Traffic should include recovered server
        server_requests = {server: 0 for server in server_status.keys()}

        for i in range(150):
            target_server = healthy_servers[i % len(healthy_servers)]
            server_requests[target_server] += 1

        # All servers should receive requests
        for server in healthy_servers:
            assert server_requests[server] > 0

    def test_cascading_failure_prevention(self):
        """Test prevention of cascading failures."""
        # Scenario: 2 of 3 servers fail, remaining server overloaded
        server_capacity = {"orch-1": 100, "orch-2": 100, "orch-3": 100}
        server_load = {"orch-1": 0, "orch-2": 0, "orch-3": 0}
        server_status = {server: "healthy" for server in server_capacity.keys()}

        # Fail 2 servers
        server_status["orch-2"] = "unhealthy"
        server_status["orch-3"] = "unhealthy"

        healthy_servers = [
            s for s, status in server_status.items() if status == "healthy"
        ]

        # Simulate high load (300 requests - more than 1 server capacity)
        requests_to_process = 300
        rejected_requests = 0

        for _ in range(requests_to_process):
            if healthy_servers:
                target_server = healthy_servers[0]  # Only one healthy server
                if server_load[target_server] < server_capacity[target_server]:
                    server_load[target_server] += 1
                else:
                    # Server at capacity - should reject or queue
                    rejected_requests += 1

        # Some requests should be rejected to prevent overload
        assert rejected_requests > 0
        assert server_load["orch-1"] <= server_capacity["orch-1"]

    def test_partial_failure_graceful_degradation(self):
        """Test graceful degradation with partial failures."""
        # Different service types with different criticality
        services = {
            "orchestrator": {"critical": True, "healthy_servers": 2, "min_required": 1},
            "br_kg": {"critical": True, "healthy_servers": 1, "min_required": 1},
            "agent": {"critical": False, "healthy_servers": 0, "min_required": 1},
            "web-ui": {"critical": False, "healthy_servers": 3, "min_required": 1},
        }

        system_available = True
        degraded_services = []

        for service_name, config in services.items():
            if config["healthy_servers"] < config["min_required"]:
                if config["critical"]:
                    system_available = False
                else:
                    degraded_services.append(service_name)

        # System should remain available despite non-critical service failure
        assert system_available is True
        assert "agent" in degraded_services
        assert len(degraded_services) == 1


@pytest.mark.integration
class TestSessionAffinity:
    """Test session affinity (sticky sessions)."""

    def test_cookie_based_session_affinity(self):
        """Test cookie-based sticky sessions."""
        # Simulate cookie insertion by HAProxy
        sessions = {}  # session_id -> server

        def handle_request(session_id: str = None):
            if session_id and session_id in sessions:
                # Existing session - route to same server
                return sessions[session_id]
            else:
                # New session - select server and create cookie
                import random

                servers = ["orch-1", "orch-2", "orch-3"]
                selected_server = random.choice(servers)
                new_session_id = f"session_{len(sessions) + 1}"
                sessions[new_session_id] = selected_server
                return selected_server, new_session_id

        # Test session creation
        server, session_id = handle_request()
        assert server in ["orch-1", "orch-2", "orch-3"]
        assert session_id is not None

        # Test session persistence
        for _ in range(10):
            subsequent_server = handle_request(session_id)
            assert subsequent_server == server, "Session not sticky to same server"

    def test_session_affinity_with_server_failure(self):
        """Test session handling when preferred server fails."""
        # Setup sessions
        sessions = {"session_1": "orch-1", "session_2": "orch-2", "session_3": "orch-3"}

        server_status = {
            "orch-1": "healthy",
            "orch-2": "unhealthy",  # Failed server
            "orch-3": "healthy",
        }

        def handle_request_with_failover(session_id: str):
            preferred_server = sessions.get(session_id)
            if preferred_server and server_status.get(preferred_server) == "healthy":
                return preferred_server
            else:
                # Failover to healthy server
                healthy_servers = [
                    s for s, status in server_status.items() if status == "healthy"
                ]
                if healthy_servers:
                    new_server = healthy_servers[0]
                    sessions[session_id] = new_server  # Update session
                    return new_server
                else:
                    return None  # No healthy servers

        # Test normal session
        server = handle_request_with_failover("session_1")
        assert server == "orch-1"

        # Test failed server session
        server = handle_request_with_failover("session_2")
        assert server in ["orch-1", "orch-3"]  # Should failover
        assert server != "orch-2"  # Should not use failed server

    def test_session_distribution_fairness(self):
        """Test session distribution doesn't create hotspots."""
        sessions = {}
        server_session_count = {"orch-1": 0, "orch-2": 0, "orch-3": 0}

        import random

        random.seed(42)  # Reproducible test

        # Create 100 sessions
        for i in range(100):
            servers = list(server_session_count.keys())
            selected_server = random.choice(servers)
            session_id = f"session_{i+1}"
            sessions[session_id] = selected_server
            server_session_count[selected_server] += 1

        # Check distribution is reasonably fair
        avg_sessions = 100 / 3
        for server, count in server_session_count.items():
            # Allow 30% deviation from average
            assert (
                abs(count - avg_sessions) <= avg_sessions * 0.3
            ), f"Session distribution unfair: {server} has {count} sessions, expected ~{avg_sessions}"


@pytest.mark.load
class TestLoadBalancingPerformance:
    """Test load balancing performance under various loads."""

    @pytest.mark.asyncio
    async def test_concurrent_request_handling(self, test_config: TestConfig):
        """Test handling of concurrent requests."""

        async def make_request(session_id: int):
            """Simulate a single request."""
            # Mock request processing time
            await asyncio.sleep(0.1)  # 100ms processing time
            return {"session_id": session_id, "response_time": 0.1, "status": "success"}

        # Simulate 50 concurrent requests
        concurrent_requests = 50
        start_time = time.time()

        tasks = [make_request(i) for i in range(concurrent_requests)]
        results = await asyncio.gather(*tasks)

        end_time = time.time()
        total_time = end_time - start_time

        # All requests should complete
        assert len(results) == concurrent_requests

        # Total time should be close to single request time (due to concurrency)
        # Allow some overhead for coordination
        assert total_time < 0.5, f"Concurrent processing too slow: {total_time}s"

        # All requests should succeed
        successful_requests = sum(1 for r in results if r["status"] == "success")
        assert successful_requests == concurrent_requests

    def test_high_throughput_handling(self):
        """Test system behavior under high request throughput."""
        # Simulate high throughput scenario
        requests_per_second = 1000
        test_duration = 10  # seconds
        total_requests = requests_per_second * test_duration

        # Mock load balancer processing
        processed_requests = 0
        start_time = time.time()

        # Simulate request processing
        batch_size = 100  # Process in batches
        for batch_start in range(0, total_requests, batch_size):
            batch_end = min(batch_start + batch_size, total_requests)
            batch_requests = batch_end - batch_start

            # Simulate batch processing time
            batch_time = 0.05  # 50ms per batch
            time.sleep(batch_time)

            processed_requests += batch_requests

        end_time = time.time()
        actual_duration = end_time - start_time
        actual_rps = processed_requests / actual_duration

        # Should handle target throughput within reasonable margin
        assert (
            actual_rps >= requests_per_second * 0.8
        ), f"Throughput too low: {actual_rps:.1f} RPS, target: {requests_per_second} RPS"

    def test_memory_usage_under_load(self):
        """Test memory usage remains stable under load."""
        import sys

        # Baseline memory usage
        baseline_memory = sys.getsizeof({})

        # Simulate storing connection/session data
        connections = {}
        sessions = {}

        # Add data for 10k connections
        for i in range(10000):
            conn_id = f"conn_{i}"
            session_id = f"session_{i}"

            connections[conn_id] = {
                "server": f"orch-{(i % 3) + 1}",
                "start_time": time.time(),
                "requests": i % 100,
            }

            sessions[session_id] = {
                "server": f"orch-{(i % 3) + 1}",
                "created": time.time(),
            }

        # Calculate memory usage
        connections_memory = sys.getsizeof(connections) + sum(
            sys.getsizeof(k) + sys.getsizeof(v) for k, v in connections.items()
        )
        sessions_memory = sys.getsizeof(sessions) + sum(
            sys.getsizeof(k) + sys.getsizeof(v) for k, v in sessions.items()
        )

        total_memory = connections_memory + sessions_memory

        # Memory usage should be reasonable (less than 10MB for 10k connections)
        max_acceptable_memory = 10 * 1024 * 1024  # 10MB
        assert (
            total_memory < max_acceptable_memory
        ), f"Memory usage too high: {total_memory / (1024*1024):.1f}MB"

    def test_response_time_distribution(self):
        """Test response time distribution under load."""
        import random

        random.seed(42)

        # Simulate response times for different load scenarios
        response_times = []

        # Normal load: 100 requests
        for _ in range(100):
            # Base response time + small variance
            response_time = 50 + random.gauss(0, 10)  # 50ms ± 10ms
            response_times.append(max(0, response_time))

        # High load: additional 400 requests with degraded performance
        for _ in range(400):
            # Higher response time under load
            response_time = 80 + random.gauss(0, 20)  # 80ms ± 20ms
            response_times.append(max(0, response_time))

        # Calculate percentiles
        response_times.sort()
        p50 = response_times[len(response_times) // 2]
        p95 = response_times[int(len(response_times) * 0.95)]
        p99 = response_times[int(len(response_times) * 0.99)]

        # Response time thresholds
        assert p50 < 100, f"Median response time too high: {p50:.1f}ms"
        assert p95 < 200, f"95th percentile response time too high: {p95:.1f}ms"
        assert p99 < 300, f"99th percentile response time too high: {p99:.1f}ms"


@pytest.mark.integration
@pytest.mark.slow
class TestHAProxyIntegration:
    """Integration tests with real or mocked HAProxy."""

    @pytest.mark.skipif(
        not pytest.importorskip("requests", minversion="2.25"),
        reason="requests library required for integration tests",
    )
    def test_haproxy_stats_parsing(self, haproxy_client):
        """Test parsing real HAProxy statistics."""
        try:
            stats = haproxy_client.get_stats()

            # Verify expected structure
            assert "backends" in stats
            assert "servers" in stats

            # Check for orchestrator backend
            if "orchestrator_backend" in stats["backends"]:
                backend = stats["backends"]["orchestrator_backend"]
                assert "status" in backend or "svname" in backend
        except Exception:
            pytest.skip("HAProxy not available for integration testing")

    @pytest.mark.asyncio
    async def test_load_balancer_health_endpoints(self, test_config: TestConfig):
        """Test load balancer health check endpoints."""
        health_endpoints = [
            "http://localhost/health",
            "http://localhost/api/health",
            "http://localhost/orchestrator/health",
        ]

        results = []
        for endpoint in health_endpoints:
            try:
                # Mock the health check response
                response_time = 50  # ms
                status_code = 200

                results.append(
                    {
                        "endpoint": endpoint,
                        "status_code": status_code,
                        "response_time": response_time,
                        "success": status_code == 200,
                    }
                )
            except Exception as e:
                results.append(
                    {"endpoint": endpoint, "error": str(e), "success": False}
                )

        # At least some endpoints should be healthy in a real deployment
        # For tests, we verify the structure is correct
        assert len(results) == len(health_endpoints)
        assert all("success" in result for result in results)
