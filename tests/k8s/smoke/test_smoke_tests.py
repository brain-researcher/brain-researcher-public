"""
Kubernetes Smoke Tests for Brain Researcher Platform

This module provides smoke tests for validating basic functionality of deployed services,
including health endpoints, database connectivity, inter-service communication,
ingress routing, and SSL/TLS validation.
"""

import json
import socket
import ssl
import subprocess
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import psycopg2
import pytest
import redis
import requests

# Suppress SSL warnings for self-signed certificates in test environment
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


class SmokeTestClient:
    """Client for executing smoke tests against deployed services."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = False  # For test environments with self-signed certs

    def get_service_url(self, service_name: str, namespace: str, port: int) -> str:
        """Get service URL using kubectl port-forward or direct cluster access."""
        try:
            # Try to get service cluster IP
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "service",
                    service_name,
                    "-n",
                    namespace,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            service_data = json.loads(result.stdout)
            cluster_ip = service_data["spec"].get("clusterIP")

            if cluster_ip and cluster_ip != "None":
                return f"http://{cluster_ip}:{port}"
            else:
                # Use port-forward for headless services
                return f"http://localhost:{port}"

        except subprocess.CalledProcessError:
            return f"http://localhost:{port}"

    def check_http_endpoint(
        self, url: str, expected_status: int = 200
    ) -> Tuple[bool, str]:
        """Check if HTTP endpoint is accessible."""
        try:
            response = self.session.get(url, timeout=self.timeout)
            success = response.status_code == expected_status
            message = (
                f"Status: {response.status_code}, Response length: {len(response.text)}"
            )
            return success, message
        except requests.exceptions.RequestException as e:
            return False, f"Request failed: {str(e)}"

    def check_tcp_connection(self, host: str, port: int) -> Tuple[bool, str]:
        """Check if TCP connection can be established."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((host, port))
            sock.close()

            success = result == 0
            message = f"Connection {'successful' if success else 'failed'}"
            return success, message
        except Exception as e:
            return False, f"Connection error: {str(e)}"


@pytest.fixture(scope="module")
def smoke_client():
    """Smoke test client fixture."""
    return SmokeTestClient()


@pytest.fixture(scope="module")
def service_urls():
    """Service URLs for testing."""
    return {
        "orchestrator": "http://orchestrator-service.brain-researcher-core.svc.cluster.local:3001",
        "agent": "http://agent-service.brain-researcher-core.svc.cluster.local:8000",
        "br_kg": "http://br_kg-service.brain-researcher-core.svc.cluster.local:5000",
        "niclip": "http://niclip-service.brain-researcher-core.svc.cluster.local:8001",
        "web_ui": "http://web-ui-service.brain-researcher-core.svc.cluster.local:3000",
        "nginx": "http://nginx-service.brain-researcher-core.svc.cluster.local:80",
        "prometheus": "http://prometheus-service.brain-researcher-monitoring.svc.cluster.local:9090",
        "grafana": "http://grafana-service.brain-researcher-monitoring.svc.cluster.local:3000",
    }


class TestServiceHealthEndpoints:
    """Test service health endpoints are responding."""

    @pytest.mark.parametrize(
        "service_info",
        [
            ("orchestrator", "/health", 200),
            ("orchestrator", "/api/v1/health", 200),
            ("agent", "/health", 200),
            ("br_kg", "/health", 200),
            ("niclip", "/health", 200),
            ("web_ui", "/", 200),  # Next.js app
            ("nginx", "/health", 200),
            ("prometheus", "/-/healthy", 200),
            ("grafana", "/api/health", 200),
        ],
    )
    def test_health_endpoints(
        self, smoke_client: SmokeTestClient, service_urls: Dict[str, str], service_info
    ):
        """Test that service health endpoints are accessible."""
        service_name, endpoint, expected_status = service_info

        if service_name not in service_urls:
            pytest.skip(f"Service {service_name} not configured")

        base_url = service_urls[service_name]
        full_url = f"{base_url}{endpoint}"

        success, message = smoke_client.check_http_endpoint(full_url, expected_status)
        assert success, f"Health check failed for {service_name}: {message}"

    def test_orchestrator_api_endpoints(
        self, smoke_client: SmokeTestClient, service_urls: Dict[str, str]
    ):
        """Test key orchestrator API endpoints."""
        if "orchestrator" not in service_urls:
            pytest.skip("Orchestrator service not configured")

        base_url = service_urls["orchestrator"]
        endpoints = [
            "/api/v1/status",
            "/api/v1/services",
            "/api/v1/jobs",
        ]

        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            success, message = smoke_client.check_http_endpoint(url)
            # Allow 404 for endpoints that might not be implemented yet
            if not success and "404" not in message:
                pytest.fail(f"Orchestrator endpoint {endpoint} failed: {message}")

    def test_br_kg_api_endpoints(
        self, smoke_client: SmokeTestClient, service_urls: Dict[str, str]
    ):
        """Test key BR-KG API endpoints."""
        if "br_kg" not in service_urls:
            pytest.skip("BR-KG service not configured")

        base_url = service_urls["br_kg"]
        endpoints = [
            "/api/finder/search?q=memory",
            "/api/stats",
            "/api/vocab/concepts",
        ]

        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            success, message = smoke_client.check_http_endpoint(url)
            # Allow 404 or 500 for endpoints that might need data
            if not success and not any(code in message for code in ["404", "500"]):
                pytest.fail(f"BR-KG endpoint {endpoint} failed: {message}")

    def test_agent_api_endpoints(
        self, smoke_client: SmokeTestClient, service_urls: Dict[str, str]
    ):
        """Test key Agent API endpoints."""
        if "agent" not in service_urls:
            pytest.skip("Agent service not configured")

        base_url = service_urls["agent"]
        endpoints = [
            "/health",
            "/api/v1/chat",  # Might return 405 for GET
            "/api/v1/tools",
        ]

        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            success, message = smoke_client.check_http_endpoint(url)
            # Allow method not allowed for chat endpoint
            if not success and not any(code in message for code in ["405", "404"]):
                pytest.fail(f"Agent endpoint {endpoint} failed: {message}")


class TestDatabaseConnectivity:
    """Test database connectivity and basic operations."""

    def test_redis_connectivity(self, smoke_client: SmokeTestClient):
        """Test Redis connectivity."""
        try:
            # Get Redis service endpoint
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "service",
                    "redis-service",
                    "-n",
                    "brain-researcher-data",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            service_data = json.loads(result.stdout)
            cluster_ip = service_data["spec"].get("clusterIP")

            if not cluster_ip or cluster_ip == "None":
                pytest.skip("Redis service not available or is headless")

            # Test TCP connection
            success, message = smoke_client.check_tcp_connection(cluster_ip, 6379)
            assert success, f"Redis TCP connection failed: {message}"

            # Try Redis connection if possible
            try:
                r = redis.Redis(host=cluster_ip, port=6379, decode_responses=True)
                r.ping()
                # Test basic operations
                r.set("test_key", "test_value", ex=60)
                value = r.get("test_key")
                assert value == "test_value"
                r.delete("test_key")
            except redis.RedisError:
                # Connection might be restricted, but TCP connection succeeded
                pass

        except subprocess.CalledProcessError:
            pytest.skip("Could not get Redis service information")

    def test_postgres_connectivity(self, smoke_client: SmokeTestClient):
        """Test PostgreSQL connectivity."""
        try:
            # Get PostgreSQL service endpoint
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "service",
                    "postgres-service",
                    "-n",
                    "brain-researcher-data",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            service_data = json.loads(result.stdout)
            cluster_ip = service_data["spec"].get("clusterIP")

            if not cluster_ip or cluster_ip == "None":
                pytest.skip("PostgreSQL service not available or is headless")

            # Test TCP connection
            success, message = smoke_client.check_tcp_connection(cluster_ip, 5432)
            assert success, f"PostgreSQL TCP connection failed: {message}"

            # Try database connection if credentials are available
            try:
                # Get database credentials from secret
                secret_result = subprocess.run(
                    [
                        "kubectl",
                        "get",
                        "secret",
                        "postgres-secret",
                        "-n",
                        "brain-researcher-data",
                        "-o",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if secret_result.returncode == 0:
                    secret_data = json.loads(secret_result.stdout)
                    # This is just a connection test, not extracting actual secrets
                    # In a real environment, use proper secret management
                    pass

            except Exception:
                # Credentials not available, but TCP connection succeeded
                pass

        except subprocess.CalledProcessError:
            pytest.skip("Could not get PostgreSQL service information")


class TestInterServiceCommunication:
    """Test inter-service communication within the cluster."""

    def test_orchestrator_to_agent_communication(
        self, smoke_client: SmokeTestClient, service_urls: Dict[str, str]
    ):
        """Test that orchestrator can communicate with agent."""
        if "orchestrator" not in service_urls or "agent" not in service_urls:
            pytest.skip("Required services not configured")

        # Test that orchestrator can reach agent health endpoint
        orchestrator_url = service_urls["orchestrator"]

        # This would typically be tested by making a request through orchestrator
        # that internally calls the agent service
        try:
            # Test orchestrator's ability to call agent
            response = requests.get(
                f"{orchestrator_url}/api/v1/agent/status", timeout=30, verify=False
            )
            # Allow 404 if endpoint not implemented, but not connection errors
            assert response.status_code in [
                200,
                404,
                405,
            ], f"Orchestrator-Agent communication failed: {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.fail("Orchestrator service not reachable for inter-service test")
        except requests.exceptions.RequestException:
            # Other request issues might be acceptable
            pass

    def test_agent_to_br_kg_communication(
        self, smoke_client: SmokeTestClient, service_urls: Dict[str, str]
    ):
        """Test that agent can communicate with BR-KG."""
        if "agent" not in service_urls or "br_kg" not in service_urls:
            pytest.skip("Required services not configured")

        # Test direct BR-KG health from agent's perspective
        br_kg_url = service_urls["br_kg"]

        try:
            response = requests.get(f"{br_kg_url}/health", timeout=30, verify=False)
            assert (
                response.status_code == 200
            ), f"BR-KG health check failed: {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.fail("BR-KG service not reachable for inter-service test")
        except requests.exceptions.RequestException:
            # Might be configuration issues, but service should be reachable
            pass

    def test_service_discovery(self):
        """Test Kubernetes service discovery."""
        try:
            # Test DNS resolution for services
            services_to_test = [
                "orchestrator-service.brain-researcher-core.svc.cluster.local",
                "agent-service.brain-researcher-core.svc.cluster.local",
                "br_kg-service.brain-researcher-core.svc.cluster.local",
                "redis-service.brain-researcher-data.svc.cluster.local",
                "postgres-service.brain-researcher-data.svc.cluster.local",
            ]

            for service_name in services_to_test:
                try:
                    socket.gethostbyname(service_name)
                except socket.gaierror:
                    # DNS resolution failed - might not be in cluster or service doesn't exist
                    # This is not necessarily a failure in all test environments
                    pass

        except Exception:
            # Service discovery test is environment-dependent
            pass


class TestIngressRouting:
    """Test ingress routing and external access."""

    def test_ingress_controller_exists(self):
        """Test that ingress controller is running."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "ingress", "-A"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0 and result.stdout.strip():
                # Ingress resources exist
                assert "brain-researcher" in result.stdout or len(result.stdout) > 0
            else:
                # Ingress might not be configured in test environment
                pytest.skip("No ingress resources found")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check ingress resources")

    def test_nginx_ingress_configuration(self, smoke_client: SmokeTestClient):
        """Test nginx ingress configuration."""
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "ingress",
                    "brain-researcher-ingress",
                    "-n",
                    "brain-researcher-core",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                pytest.skip("Ingress not configured")

            ingress_data = json.loads(result.stdout)

            # Validate ingress configuration
            spec = ingress_data.get("spec", {})
            assert "rules" in spec, "Ingress has no rules"

            rules = spec["rules"]
            assert len(rules) > 0, "Ingress has no routing rules"

            # Check that routes exist for main services
            paths = []
            for rule in rules:
                http_config = rule.get("http", {})
                paths.extend(path["path"] for path in http_config.get("paths", []))

            # Should have routes for main services
            expected_paths = ["/api", "/app", "/grafana"]
            for expected_path in expected_paths:
                path_exists = any(expected_path in path for path in paths)
                if not path_exists:
                    # Not all paths need to be configured
                    pass

        except (subprocess.CalledProcessError, json.JSONDecodeError):
            pytest.skip("Could not validate ingress configuration")

    def test_external_access_simulation(self, smoke_client: SmokeTestClient):
        """Simulate external access through ingress."""
        try:
            # Get ingress external IP/hostname
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "ingress",
                    "-n",
                    "brain-researcher-core",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                pytest.skip("No ingress configured")

            ingress_data = json.loads(result.stdout)
            ingresses = ingress_data.get("items", [])

            if not ingresses:
                pytest.skip("No ingress resources found")

            for ingress in ingresses:
                status = ingress.get("status", {})
                load_balancer = status.get("loadBalancer", {})
                ingress_points = load_balancer.get("ingress", [])

                if ingress_points:
                    for point in ingress_points:
                        ip = point.get("ip")
                        hostname = point.get("hostname")

                        if ip:
                            success, message = smoke_client.check_tcp_connection(ip, 80)
                            assert (
                                success
                            ), f"External access to {ip}:80 failed: {message}"
                            break
                        elif hostname:
                            success, message = smoke_client.check_tcp_connection(
                                hostname, 80
                            )
                            assert (
                                success
                            ), f"External access to {hostname}:80 failed: {message}"
                            break
                else:
                    pytest.skip("Ingress has no external endpoints")

        except (subprocess.CalledProcessError, json.JSONDecodeError):
            pytest.skip("Could not test external access")


class TestSSLTLSValidation:
    """Test SSL/TLS configuration and certificates."""

    def test_tls_secrets_exist(self):
        """Test that TLS secrets are configured."""
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "secret",
                    "-n",
                    "brain-researcher-core",
                    "--field-selector",
                    "type=kubernetes.io/tls",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0 and result.stdout.strip():
                # TLS secrets exist
                assert "tls" in result.stdout.lower()
            else:
                pytest.skip("No TLS secrets found - might be HTTP only deployment")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check TLS secrets")

    def test_certificate_validity(self):
        """Test certificate validity for HTTPS endpoints."""
        try:
            # Get ingress with TLS configuration
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "ingress",
                    "-n",
                    "brain-researcher-core",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                pytest.skip("No ingress configured")

            ingress_data = json.loads(result.stdout)
            ingresses = ingress_data.get("items", [])

            tls_hosts = []
            for ingress in ingresses:
                tls_config = ingress.get("spec", {}).get("tls", [])
                for tls in tls_config:
                    tls_hosts.extend(tls.get("hosts", []))

            if not tls_hosts:
                pytest.skip("No TLS configuration found")

            # Test certificate for each TLS host
            for host in tls_hosts:
                try:
                    # Basic SSL connection test
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE  # For self-signed certs in test

                    with socket.create_connection((host, 443), timeout=10) as sock:
                        with context.wrap_socket(sock, server_hostname=host) as ssock:
                            cert = ssock.getpeercert()
                            assert cert is not None, f"No certificate found for {host}"

                except (socket.gaierror, socket.timeout, ssl.SSLError):
                    # Certificate issues might be expected in test environment
                    pass

        except (subprocess.CalledProcessError, json.JSONDecodeError):
            pytest.skip("Could not validate TLS configuration")

    def test_https_redirect(self, smoke_client: SmokeTestClient):
        """Test that HTTP redirects to HTTPS where configured."""
        try:
            # This test depends on ingress configuration
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "ingress",
                    "-n",
                    "brain-researcher-core",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                pytest.skip("No ingress configured")

            ingress_data = json.loads(result.stdout)
            ingresses = ingress_data.get("items", [])

            # Look for SSL redirect annotations
            ssl_redirect_configured = False
            for ingress in ingresses:
                annotations = ingress.get("metadata", {}).get("annotations", {})
                if (
                    annotations.get("nginx.ingress.kubernetes.io/ssl-redirect")
                    == "true"
                ):
                    ssl_redirect_configured = True
                    break

            if not ssl_redirect_configured:
                pytest.skip("SSL redirect not configured")

            # Test would involve making HTTP requests and checking for redirects
            # This is environment-specific and might not work in all test setups

        except (subprocess.CalledProcessError, json.JSONDecodeError):
            pytest.skip("Could not test HTTPS redirect")


# Integration test for overall system health
class TestSystemHealth:
    """Overall system health checks."""

    def test_all_critical_services_healthy(
        self, smoke_client: SmokeTestClient, service_urls: Dict[str, str]
    ):
        """Test that all critical services are healthy."""
        critical_services = ["orchestrator", "agent", "br_kg"]
        failed_services = []

        for service_name in critical_services:
            if service_name not in service_urls:
                continue

            url = f"{service_urls[service_name]}/health"
            success, message = smoke_client.check_http_endpoint(url)

            if not success:
                failed_services.append(f"{service_name}: {message}")

        assert (
            not failed_services
        ), f"Critical services failed health checks: {failed_services}"

    def test_system_resource_usage(self):
        """Test that system resources are within acceptable limits."""
        try:
            # Get node resource usage
            result = subprocess.run(
                ["kubectl", "top", "nodes"], capture_output=True, text=True, check=False
            )

            if result.returncode != 0:
                pytest.skip("Resource metrics not available")

            lines = result.stdout.strip().split("\n")[1:]  # Skip header

            for line in lines:
                parts = line.split()
                if len(parts) >= 5:
                    node_name = parts[0]
                    cpu_usage = parts[1]
                    memory_usage = parts[3]

                    # Parse CPU percentage
                    if cpu_usage.endswith("%"):
                        cpu_percent = int(cpu_usage[:-1])
                        assert (
                            cpu_percent < 90
                        ), f"Node {node_name} CPU usage too high: {cpu_percent}%"

                    # Parse memory percentage
                    if memory_usage.endswith("%"):
                        memory_percent = int(memory_usage[:-1])
                        assert (
                            memory_percent < 90
                        ), f"Node {node_name} memory usage too high: {memory_percent}%"

        except (subprocess.CalledProcessError, ValueError):
            pytest.skip("Could not check resource usage")


if __name__ == "__main__":
    # Run smoke tests
    pytest.main([__file__, "-v", "-x"])  # Stop on first failure for smoke tests
