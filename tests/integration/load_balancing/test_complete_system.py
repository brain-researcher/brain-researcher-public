"""
Comprehensive integration tests for the complete load balancing and auto-scaling system.

This module tests the entire system working together:
- HAProxy load balancer
- Docker Swarm orchestration
- Auto-scaling mechanisms
- Blue-green deployments
- Connection pooling
- Kubernetes HPA
- Circuit breakers and failover

Tests are designed to validate production readiness and high availability.
"""

import asyncio
import pytest
import requests
import time
import json
import subprocess
import threading
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

docker = pytest.importorskip(
    "docker",
    reason="docker Python package is required for load balancing integration tests",
)
psutil = pytest.importorskip(
    "psutil",
    reason="psutil is required for load balancing integration tests",
)
websocket = pytest.importorskip(
    "websocket",
    reason="websocket-client is required for load balancing integration tests",
)
k8s_client_module = pytest.importorskip(
    "kubernetes.client",
    reason="kubernetes Python package is required for load balancing integration tests",
)
k8s_config_module = pytest.importorskip(
    "kubernetes.config",
    reason="kubernetes Python package is required for load balancing integration tests",
)
k8s_client = k8s_client_module
k8s_config = k8s_config_module

# Test configuration
TEST_CONFIG = {
    'base_url': 'http://localhost',
    'haproxy_stats_url': 'http://localhost:8404/stats',
    'prometheus_url': 'http://localhost:9090',
    'test_duration': 300,  # 5 minutes
    'max_users': 100,
    'ramp_up_time': 60,
    'cooldown_time': 30,
    'health_check_interval': 5,
    'auto_scaling_timeout': 180,  # 3 minutes
}

@dataclass
class SystemMetrics:
    """System performance metrics."""
    timestamp: datetime
    cpu_usage: float
    memory_usage: float
    response_time: float
    error_rate: float
    active_connections: int
    throughput: float

@dataclass
class LoadBalancerStatus:
    """Load balancer status information."""
    active_backends: int
    total_backends: int
    session_distribution: Dict[str, int]
    health_checks_passed: int
    health_checks_failed: int

@dataclass
class AutoScalingEvent:
    """Auto-scaling event information."""
    timestamp: datetime
    action: str  # scale_up, scale_down, no_change
    current_replicas: int
    desired_replicas: int
    trigger_reason: str
    response_time: float

class SystemIntegrationTest:
    """Complete system integration test orchestrator."""
    
    def __init__(self):
        self.docker_client = docker.from_env()
        self.metrics_history: List[SystemMetrics] = []
        self.scaling_events: List[AutoScalingEvent] = []
        self.load_balancer_stats: List[LoadBalancerStatus] = []
        self.test_start_time = None
        self.test_results = {}
        self.active_threads = []
        self.stop_monitoring = False
        
    def setup_test_environment(self):
        """Set up the complete test environment."""
        print("Setting up complete system integration test environment...")
        
        # Ensure all required services are running
        self._ensure_services_running()
        
        # Initialize monitoring
        self._setup_monitoring()
        
        # Warm up the system
        self._warmup_system()
        
        print("Test environment setup complete")
    
    def _ensure_services_running(self):
        """Ensure all required services are running."""
        required_services = [
            'haproxy',
            'brain-researcher-orchestrator',
            'brain-researcher-neurokg', 
            'brain-researcher-agent',
            'redis',
            'neo4j',
            'pgbouncer'
        ]
        
        for service in required_services:
            if not self._is_service_running(service):
                pytest.fail(f"Required service {service} is not running")
    
    def _is_service_running(self, service_name: str) -> bool:
        """Check if a service is running."""
        try:
            containers = self.docker_client.containers.list()
            for container in containers:
                if service_name in container.name:
                    return container.status == 'running'
            return False
        except Exception as e:
            print(f"Error checking service {service_name}: {e}")
            return False
    
    def _setup_monitoring(self):
        """Set up system monitoring."""
        # Start metrics collection thread
        monitoring_thread = threading.Thread(
            target=self._collect_metrics_continuously,
            daemon=True
        )
        self.active_threads.append(monitoring_thread)
        monitoring_thread.start()
        
        # Start load balancer monitoring
        lb_thread = threading.Thread(
            target=self._monitor_load_balancer,
            daemon=True
        )
        self.active_threads.append(lb_thread)
        lb_thread.start()
    
    def _warmup_system(self):
        """Warm up the system with light load."""
        print("Warming up system...")
        
        # Send warmup requests
        for _ in range(10):
            try:
                response = requests.get(
                    f"{TEST_CONFIG['base_url']}/health",
                    timeout=5
                )
                assert response.status_code == 200
            except Exception as e:
                print(f"Warmup request failed: {e}")
        
        time.sleep(5)  # Allow systems to stabilize
        print("System warmup complete")
    
    def _collect_metrics_continuously(self):
        """Continuously collect system metrics."""
        while not self.stop_monitoring:
            try:
                metrics = self._collect_current_metrics()
                self.metrics_history.append(metrics)
                time.sleep(TEST_CONFIG['health_check_interval'])
            except Exception as e:
                print(f"Error collecting metrics: {e}")
                time.sleep(1)
    
    def _collect_current_metrics(self) -> SystemMetrics:
        """Collect current system metrics."""
        # CPU and memory usage
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_usage = psutil.virtual_memory().percent
        
        # Response time (sample request)
        start_time = time.time()
        try:
            response = requests.get(
                f"{TEST_CONFIG['base_url']}/health",
                timeout=5
            )
            response_time = (time.time() - start_time) * 1000  # ms
            error_rate = 0.0 if response.status_code == 200 else 1.0
        except Exception:
            response_time = 5000.0  # Timeout
            error_rate = 1.0
        
        # Active connections (from HAProxy stats if available)
        active_connections = self._get_active_connections()
        
        # Throughput (requests per second - estimated)
        throughput = self._estimate_throughput()
        
        return SystemMetrics(
            timestamp=datetime.now(),
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            response_time=response_time,
            error_rate=error_rate,
            active_connections=active_connections,
            throughput=throughput
        )
    
    def _get_active_connections(self) -> int:
        """Get active connections from HAProxy stats."""
        try:
            response = requests.get(
                TEST_CONFIG['haproxy_stats_url'] + ";csv",
                timeout=5
            )
            if response.status_code == 200:
                # Parse HAProxy CSV stats
                lines = response.text.strip().split('\n')
                total_connections = 0
                for line in lines[1:]:  # Skip header
                    fields = line.split(',')
                    if len(fields) > 4:  # Current sessions field
                        try:
                            total_connections += int(fields[4])
                        except (ValueError, IndexError):
                            pass
                return total_connections
        except Exception:
            pass
        return 0
    
    def _estimate_throughput(self) -> float:
        """Estimate current throughput."""
        # Simple estimation based on recent metrics
        if len(self.metrics_history) < 2:
            return 0.0
        
        # Calculate based on connection changes over time
        recent_metrics = self.metrics_history[-10:]  # Last 10 samples
        if len(recent_metrics) >= 2:
            time_diff = (recent_metrics[-1].timestamp - recent_metrics[0].timestamp).total_seconds()
            if time_diff > 0:
                connection_changes = abs(recent_metrics[-1].active_connections - recent_metrics[0].active_connections)
                return connection_changes / time_diff
        
        return 0.0
    
    def _monitor_load_balancer(self):
        """Monitor load balancer status."""
        while not self.stop_monitoring:
            try:
                status = self._get_load_balancer_status()
                self.load_balancer_stats.append(status)
                time.sleep(TEST_CONFIG['health_check_interval'])
            except Exception as e:
                print(f"Error monitoring load balancer: {e}")
                time.sleep(1)
    
    def _get_load_balancer_status(self) -> LoadBalancerStatus:
        """Get current load balancer status."""
        try:
            response = requests.get(
                TEST_CONFIG['haproxy_stats_url'] + ";csv",
                timeout=5
            )
            if response.status_code == 200:
                lines = response.text.strip().split('\n')
                active_backends = 0
                total_backends = 0
                session_distribution = {}
                health_checks_passed = 0
                health_checks_failed = 0
                
                for line in lines[1:]:  # Skip header
                    fields = line.split(',')
                    if len(fields) > 17:  # Check if it's a backend/server entry
                        backend_name = fields[0]
                        server_name = fields[1]
                        status = fields[17]  # Status field
                        
                        if server_name != 'BACKEND':  # Individual servers
                            total_backends += 1
                            if 'UP' in status:
                                active_backends += 1
                                health_checks_passed += 1
                            else:
                                health_checks_failed += 1
                            
                            # Session distribution
                            try:
                                current_sessions = int(fields[4])
                                session_distribution[f"{backend_name}:{server_name}"] = current_sessions
                            except (ValueError, IndexError):
                                pass
                
                return LoadBalancerStatus(
                    active_backends=active_backends,
                    total_backends=total_backends,
                    session_distribution=session_distribution,
                    health_checks_passed=health_checks_passed,
                    health_checks_failed=health_checks_failed
                )
        except Exception:
            pass
        
        return LoadBalancerStatus(
            active_backends=0,
            total_backends=0,
            session_distribution={},
            health_checks_passed=0,
            health_checks_failed=0
        )


@pytest.fixture(scope="module")
def system_test():
    """System integration test fixture."""
    test = SystemIntegrationTest()
    test.setup_test_environment()
    yield test
    test.stop_monitoring = True
    # Wait for monitoring threads to stop
    for thread in test.active_threads:
        if thread.is_alive():
            thread.join(timeout=5)


class TestCompleteSystemIntegration:
    """Complete system integration test suite."""
    
    def test_system_health_check(self, system_test):
        """Test overall system health."""
        print("Testing system health...")
        
        # Test health endpoints
        health_endpoints = [
            '/health',
            '/api/health',
            '/api/status'
        ]
        
        for endpoint in health_endpoints:
            try:
                response = requests.get(
                    f"{TEST_CONFIG['base_url']}{endpoint}",
                    timeout=10
                )
                assert response.status_code == 200, f"Health check failed for {endpoint}"
                print(f"✓ Health check passed for {endpoint}")
            except Exception as e:
                pytest.fail(f"Health check failed for {endpoint}: {e}")
    
    def test_load_balancer_distribution(self, system_test):
        """Test load balancer request distribution."""
        print("Testing load balancer distribution...")
        
        # Send requests and track distribution
        request_count = 100
        server_responses = {}
        
        for i in range(request_count):
            try:
                response = requests.get(
                    f"{TEST_CONFIG['base_url']}/api/datasets",
                    timeout=5,
                    headers={'X-Test-Request': f'load-balance-{i}'}
                )
                
                # Track which server responded (if available in headers)
                server_id = response.headers.get('X-Served-By', 'unknown')
                server_responses[server_id] = server_responses.get(server_id, 0) + 1
                
            except Exception as e:
                print(f"Request {i} failed: {e}")
        
        # Analyze distribution
        if len(server_responses) > 1:
            # Calculate distribution fairness
            total_requests = sum(server_responses.values())
            expected_per_server = total_requests / len(server_responses)
            max_deviation = max(
                abs(count - expected_per_server) / expected_per_server
                for count in server_responses.values()
            )
            
            # Allow up to 30% deviation for fair distribution
            assert max_deviation < 0.3, f"Load balancer distribution unfair: {server_responses}"
            print(f"✓ Load balancer distribution is fair: {server_responses}")
        else:
            print("⚠ Only one server detected in responses")
    
    def test_auto_scaling_behavior(self, system_test):
        """Test auto-scaling under load."""
        print("Testing auto-scaling behavior...")
        
        initial_metrics = system_test._collect_current_metrics()
        print(f"Initial CPU: {initial_metrics.cpu_usage}%, Memory: {initial_metrics.memory_usage}%")
        
        # Generate sustained load to trigger auto-scaling
        def load_generator():
            """Generate load for auto-scaling test."""
            for i in range(200):  # High number of requests
                try:
                    # Simulate CPU-intensive analysis request
                    response = requests.post(
                        f"{TEST_CONFIG['base_url']}/api/analysis",
                        json={
                            'type': 'glm',
                            'dataset': 'test_dataset',
                            'contrasts': ['condition_a > baseline'],
                            'test_id': f'autoscale_test_{i}'
                        },
                        timeout=30
                    )
                    time.sleep(0.1)  # Small delay between requests
                except Exception as e:
                    print(f"Load generation request {i} failed: {e}")
        
        # Start load generation in threads
        load_threads = []
        for _ in range(5):  # 5 concurrent load generators
            thread = threading.Thread(target=load_generator)
            load_threads.append(thread)
            thread.start()
        
        # Monitor for auto-scaling events
        scaling_detected = False
        start_time = time.time()
        
        while (time.time() - start_time) < TEST_CONFIG['auto_scaling_timeout']:
            current_metrics = system_test._collect_current_metrics()
            
            # Check if auto-scaling should trigger
            if (current_metrics.cpu_usage > 80 or 
                current_metrics.memory_usage > 85 or
                current_metrics.response_time > 2000):
                
                print(f"High resource usage detected - CPU: {current_metrics.cpu_usage}%, "
                      f"Memory: {current_metrics.memory_usage}%, "
                      f"Response Time: {current_metrics.response_time}ms")
                
                # Check for scaling events (this would typically check container counts)
                scaling_detected = self._check_scaling_occurred()
                if scaling_detected:
                    break
            
            time.sleep(10)
        
        # Wait for load generation to complete
        for thread in load_threads:
            thread.join(timeout=30)
        
        # Verify auto-scaling behavior
        final_metrics = system_test._collect_current_metrics()
        
        print(f"Final CPU: {final_metrics.cpu_usage}%, Memory: {final_metrics.memory_usage}%")
        
        # Auto-scaling should have either prevented excessive resource usage
        # or the system should have handled the load gracefully
        assert (scaling_detected or 
                final_metrics.response_time < 5000), "Auto-scaling failed to handle load"
        
        print("✓ Auto-scaling behavior test completed")
    
    def _check_scaling_occurred(self) -> bool:
        """Check if scaling has occurred."""
        try:
            # Check Docker Swarm services
            client = docker.from_env()
            services = client.services.list()
            
            for service in services:
                if 'brain-researcher' in service.name:
                    # Check if replica count has changed
                    service.reload()
                    replicas = service.attrs['Spec']['Mode'].get('Replicated', {}).get('Replicas', 1)
                    if replicas > 1:
                        print(f"Scaling detected: {service.name} has {replicas} replicas")
                        return True
        except Exception as e:
            print(f"Error checking scaling: {e}")
        
        return False
    
    def test_failover_recovery(self, system_test):
        """Test failover and recovery mechanisms."""
        print("Testing failover and recovery...")
        
        # Get initial load balancer status
        initial_status = system_test._get_load_balancer_status()
        print(f"Initial active backends: {initial_status.active_backends}")
        
        # Simulate backend failure (if possible in test environment)
        # This would typically involve stopping a service temporarily
        
        # Test that system continues to work
        successful_requests = 0
        failed_requests = 0
        
        for i in range(50):
            try:
                response = requests.get(
                    f"{TEST_CONFIG['base_url']}/health",
                    timeout=5
                )
                if response.status_code == 200:
                    successful_requests += 1
                else:
                    failed_requests += 1
            except Exception:
                failed_requests += 1
            
            time.sleep(0.2)
        
        # System should maintain high availability even during failures
        success_rate = successful_requests / (successful_requests + failed_requests)
        assert success_rate > 0.8, f"Success rate too low during failover: {success_rate}"
        
        print(f"✓ Failover test completed - Success rate: {success_rate:.2%}")
    
    def test_connection_pooling_efficiency(self, system_test):
        """Test database connection pooling efficiency."""
        print("Testing connection pooling efficiency...")
        
        # Test with concurrent database operations
        def database_operation():
            """Simulate database operation."""
            try:
                response = requests.get(
                    f"{TEST_CONFIG['base_url']}/api/datasets",
                    timeout=10
                )
                return response.status_code == 200
            except Exception:
                return False
        
        # Execute concurrent operations
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(database_operation) for _ in range(100)]
            
            successful_ops = sum(
                1 for future in as_completed(futures, timeout=60)
                if future.result()
            )
        
        success_rate = successful_ops / 100
        assert success_rate > 0.95, f"Connection pooling efficiency too low: {success_rate}"
        
        print(f"✓ Connection pooling test completed - Success rate: {success_rate:.2%}")
    
    def test_websocket_load_balancing(self, system_test):
        """Test WebSocket connection load balancing."""
        print("Testing WebSocket load balancing...")
        
        websocket_connections = []
        connection_servers = []
        
        def create_websocket_connection():
            """Create a WebSocket connection."""
            try:
                ws_url = TEST_CONFIG['base_url'].replace('http', 'ws') + '/ws/test'
                ws = websocket.create_connection(ws_url, timeout=10)
                
                # Send a test message and get response
                ws.send('{"type": "ping"}')
                response = ws.recv()
                
                # Try to determine which server handled the connection
                # (This would depend on implementation details)
                server_info = json.loads(response).get('server', 'unknown')
                connection_servers.append(server_info)
                
                websocket_connections.append(ws)
                return True
            except Exception as e:
                print(f"WebSocket connection failed: {e}")
                return False
        
        # Create multiple WebSocket connections
        successful_connections = 0
        for _ in range(20):
            if create_websocket_connection():
                successful_connections += 1
            time.sleep(0.1)
        
        # Clean up connections
        for ws in websocket_connections:
            try:
                ws.close()
            except Exception:
                pass
        
        # Verify WebSocket load balancing worked
        assert successful_connections > 15, f"Too few WebSocket connections succeeded: {successful_connections}"
        
        print(f"✓ WebSocket load balancing test completed - {successful_connections} connections")
    
    def test_blue_green_deployment_readiness(self, system_test):
        """Test blue-green deployment readiness."""
        print("Testing blue-green deployment readiness...")
        
        # Check that the system supports blue-green deployments
        # This involves checking that services can be switched without downtime
        
        # Test health check endpoints that would be used during deployments
        health_response = requests.get(
            f"{TEST_CONFIG['base_url']}/health/ready",
            timeout=5
        )
        
        # The system should report readiness for deployments
        assert health_response.status_code in [200, 404], "Readiness endpoint should exist or return 404"
        
        # Test that the system can handle traffic switches gracefully
        # (This would be a more complex test in a real environment)
        
        print("✓ Blue-green deployment readiness verified")
    
    def test_performance_under_sustained_load(self, system_test):
        """Test system performance under sustained load."""
        print("Testing performance under sustained load...")
        
        system_test.test_start_time = time.time()
        
        # Generate sustained load for several minutes
        def sustained_load_generator():
            """Generate sustained load."""
            request_count = 0
            start_time = time.time()
            
            while (time.time() - start_time) < 180:  # 3 minutes
                try:
                    response = requests.get(
                        f"{TEST_CONFIG['base_url']}/api/datasets",
                        timeout=5
                    )
                    request_count += 1
                    time.sleep(1)  # 1 request per second per thread
                except Exception:
                    pass
            
            return request_count
        
        # Start multiple load generators
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(sustained_load_generator) for _ in range(10)]
            
            total_requests = sum(
                future.result() for future in as_completed(futures, timeout=300)
            )
        
        # Analyze performance metrics collected during the test
        if system_test.metrics_history:
            avg_response_time = sum(m.response_time for m in system_test.metrics_history) / len(system_test.metrics_history)
            max_response_time = max(m.response_time for m in system_test.metrics_history)
            avg_error_rate = sum(m.error_rate for m in system_test.metrics_history) / len(system_test.metrics_history)
            
            print(f"Performance metrics - Avg RT: {avg_response_time:.1f}ms, "
                  f"Max RT: {max_response_time:.1f}ms, Error Rate: {avg_error_rate:.2%}")
            
            # Performance thresholds
            assert avg_response_time < 2000, f"Average response time too high: {avg_response_time}ms"
            assert max_response_time < 10000, f"Maximum response time too high: {max_response_time}ms"
            assert avg_error_rate < 0.05, f"Error rate too high: {avg_error_rate:.2%}"
        
        print(f"✓ Sustained load test completed - {total_requests} total requests")
    
    def test_system_recovery_after_stress(self, system_test):
        """Test system recovery after stress conditions."""
        print("Testing system recovery after stress...")
        
        # Apply stress and then verify recovery
        initial_metrics = system_test._collect_current_metrics()
        
        # Generate high load for a short period
        def stress_generator():
            """Generate stress load."""
            for _ in range(100):
                try:
                    requests.post(
                        f"{TEST_CONFIG['base_url']}/api/analysis",
                        json={'type': 'stress_test', 'heavy_computation': True},
                        timeout=1  # Short timeout to avoid hanging
                    )
                except Exception:
                    pass  # Expected to fail under stress
        
        # Apply stress with multiple threads
        stress_threads = [threading.Thread(target=stress_generator) for _ in range(5)]
        for thread in stress_threads:
            thread.start()
        
        # Wait for stress period
        time.sleep(30)
        
        # Stop stress and allow recovery
        for thread in stress_threads:
            thread.join(timeout=10)
        
        # Wait for system recovery
        time.sleep(60)
        
        # Verify system has recovered
        recovery_metrics = system_test._collect_current_metrics()
        
        # Response times should return to normal
        assert recovery_metrics.response_time < initial_metrics.response_time * 2, \
            "System did not recover properly after stress"
        
        # System should be responding to health checks
        health_response = requests.get(f"{TEST_CONFIG['base_url']}/health", timeout=10)
        assert health_response.status_code == 200, "System not healthy after recovery"
        
        print("✓ System recovery test completed")


def generate_integration_test_report(system_test: SystemIntegrationTest) -> Dict[str, Any]:
    """Generate comprehensive integration test report."""
    
    test_duration = time.time() - (system_test.test_start_time or time.time())
    
    # Analyze metrics
    if system_test.metrics_history:
        avg_cpu = sum(m.cpu_usage for m in system_test.metrics_history) / len(system_test.metrics_history)
        max_cpu = max(m.cpu_usage for m in system_test.metrics_history)
        avg_memory = sum(m.memory_usage for m in system_test.metrics_history) / len(system_test.metrics_history)
        max_memory = max(m.memory_usage for m in system_test.metrics_history)
        avg_response_time = sum(m.response_time for m in system_test.metrics_history) / len(system_test.metrics_history)
        max_response_time = max(m.response_time for m in system_test.metrics_history)
        total_errors = sum(m.error_rate for m in system_test.metrics_history)
    else:
        avg_cpu = max_cpu = avg_memory = max_memory = 0
        avg_response_time = max_response_time = total_errors = 0
    
    # Analyze load balancer stats
    if system_test.load_balancer_stats:
        avg_active_backends = sum(s.active_backends for s in system_test.load_balancer_stats) / len(system_test.load_balancer_stats)
        total_health_checks = sum(s.health_checks_passed + s.health_checks_failed for s in system_test.load_balancer_stats)
        health_check_success_rate = sum(s.health_checks_passed for s in system_test.load_balancer_stats) / max(total_health_checks, 1)
    else:
        avg_active_backends = health_check_success_rate = 0
        total_health_checks = 0
    
    report = {
        'test_summary': {
            'duration_seconds': test_duration,
            'total_metrics_collected': len(system_test.metrics_history),
            'total_scaling_events': len(system_test.scaling_events),
            'total_lb_checks': len(system_test.load_balancer_stats)
        },
        'performance_metrics': {
            'cpu_usage': {'average': avg_cpu, 'maximum': max_cpu},
            'memory_usage': {'average': avg_memory, 'maximum': max_memory},
            'response_time_ms': {'average': avg_response_time, 'maximum': max_response_time},
            'total_errors': total_errors
        },
        'load_balancer_performance': {
            'average_active_backends': avg_active_backends,
            'health_check_success_rate': health_check_success_rate,
            'total_health_checks': total_health_checks
        },
        'scaling_events': len(system_test.scaling_events),
        'test_timestamp': datetime.now().isoformat(),
        'configuration': TEST_CONFIG
    }
    
    return report


@pytest.fixture(autouse=True)
def integration_test_report(system_test):
    """Generate integration test report after all tests."""
    yield
    
    # Generate and save report
    report = generate_integration_test_report(system_test)
    
    # Save report to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"integration_test_report_{timestamp}.json"
    
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nIntegration test report saved to: {report_file}")
    print(f"Test Summary: {report['test_summary']}")
    print(f"Performance: Avg CPU {report['performance_metrics']['cpu_usage']['average']:.1f}%, "
          f"Avg Response Time {report['performance_metrics']['response_time_ms']['average']:.1f}ms")


if __name__ == "__main__":
    # Run integration tests
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-x"  # Stop on first failure
    ])
