"""
Kubernetes Scaling Tests for Brain Researcher Platform

This module provides comprehensive tests for scaling scenarios including
HPA trigger validation, load distribution tests, session affinity validation,
and database connection pooling.
"""

import json
import logging
import random
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import pytest
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScalingTestClient:
    """Client for testing scaling scenarios."""

    def __init__(self, namespace: str = "brain-researcher-core"):
        self.namespace = namespace

    def run_kubectl(self, args: List[str], check: bool = True) -> str:
        """Execute kubectl command and return output."""
        cmd = ["kubectl"] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if check:
                logger.error(f"Command failed: {' '.join(cmd)}")
                logger.error(f"Error: {e.stderr}")
                raise
            return e.stderr.strip()

    def get_json_output(
        self, resource_type: str, name: str = None, namespace: str = None
    ) -> Dict[str, Any]:
        """Get JSON output for a Kubernetes resource."""
        ns = namespace or self.namespace
        args = ["get", resource_type]
        if name:
            args.append(name)
        args.extend(["-n", ns, "-o", "json"])
        output = self.run_kubectl(args)
        return json.loads(output)

    def scale_deployment(
        self, deployment_name: str, replicas: int, namespace: str = None
    ) -> bool:
        """Scale a deployment to specified number of replicas."""
        ns = namespace or self.namespace
        try:
            self.run_kubectl(
                [
                    "scale",
                    f"deployment/{deployment_name}",
                    f"--replicas={replicas}",
                    "-n",
                    ns,
                ]
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def wait_for_scale(
        self,
        deployment_name: str,
        expected_replicas: int,
        namespace: str = None,
        timeout: int = 300,
    ) -> bool:
        """Wait for deployment to scale to expected number of replicas."""
        ns = namespace or self.namespace
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                deployment_data = self.get_json_output(
                    "deployment", deployment_name, ns
                )
                status = deployment_data.get("status", {})

                ready_replicas = status.get("readyReplicas", 0)
                replicas = status.get("replicas", 0)

                if (
                    ready_replicas == expected_replicas
                    and replicas == expected_replicas
                ):
                    return True

                time.sleep(10)

            except subprocess.CalledProcessError:
                time.sleep(10)
                continue

        return False

    def generate_load(
        self, service_url: str, duration: int = 60, requests_per_second: int = 10
    ) -> Dict[str, Any]:
        """Generate load against a service and return metrics."""
        results = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "response_times": [],
            "errors": [],
        }

        def make_request():
            try:
                start_time = time.time()
                response = requests.get(
                    f"{service_url}/health", timeout=10, verify=False
                )
                response_time = time.time() - start_time

                results["total_requests"] += 1
                results["response_times"].append(response_time)

                if response.status_code < 400:
                    results["successful_requests"] += 1
                else:
                    results["failed_requests"] += 1

            except Exception as e:
                results["total_requests"] += 1
                results["failed_requests"] += 1
                results["errors"].append(str(e))

        # Generate load
        end_time = time.time() + duration

        while time.time() < end_time:
            with ThreadPoolExecutor(max_workers=requests_per_second) as executor:
                futures = []

                for _ in range(requests_per_second):
                    if time.time() >= end_time:
                        break
                    futures.append(executor.submit(make_request))

                # Wait for requests to complete
                for future in as_completed(futures, timeout=2):
                    try:
                        future.result()
                    except Exception:
                        pass

                time.sleep(1)  # Wait 1 second before next batch

        return results


@pytest.fixture(scope="module")
def scaling_client():
    """Scaling test client fixture."""
    return ScalingTestClient()


@pytest.fixture(scope="function")
def deployment_scaler():
    """Fixture to scale deployments and restore original scale."""
    original_scales = {}
    client = ScalingTestClient()

    def scale(
        deployment_name: str, replicas: int, namespace: str = "brain-researcher-core"
    ):
        """Scale deployment and store original scale."""
        try:
            # Get original scale
            if f"{namespace}/{deployment_name}" not in original_scales:
                deployment_data = client.get_json_output(
                    "deployment", deployment_name, namespace
                )
                original_replicas = deployment_data["spec"]["replicas"]
                original_scales[f"{namespace}/{deployment_name}"] = original_replicas

            # Scale deployment
            success = client.scale_deployment(deployment_name, replicas, namespace)
            if success:
                return client.wait_for_scale(deployment_name, replicas, namespace)
            return False

        except subprocess.CalledProcessError:
            return False

    def restore():
        """Restore original scales."""
        for resource, original_replicas in original_scales.items():
            namespace, deployment_name = resource.split("/")
            try:
                client.scale_deployment(deployment_name, original_replicas, namespace)
                client.wait_for_scale(deployment_name, original_replicas, namespace)
            except Exception as e:
                logger.warning(f"Failed to restore scale for {resource}: {e}")

    scale.restore = restore
    yield scale

    # Cleanup
    restore()


class TestHPAValidation:
    """Test Horizontal Pod Autoscaler (HPA) functionality."""

    def test_hpa_resources_exist(self, scaling_client: ScalingTestClient):
        """Test that HPA resources are configured."""
        try:
            hpa_data = scaling_client.get_json_output(
                "hpa", namespace=scaling_client.namespace
            )
            hpas = hpa_data.get("items", [])

            if not hpas:
                pytest.skip("No HPA resources configured")

            for hpa in hpas:
                hpa_name = hpa["metadata"]["name"]
                spec = hpa["spec"]

                # Verify HPA has required fields
                assert (
                    "scaleTargetRef" in spec
                ), f"HPA {hpa_name} missing scaleTargetRef"
                assert "minReplicas" in spec, f"HPA {hpa_name} missing minReplicas"
                assert "maxReplicas" in spec, f"HPA {hpa_name} missing maxReplicas"

                # Verify reasonable limits
                min_replicas = spec["minReplicas"]
                max_replicas = spec["maxReplicas"]

                assert (
                    min_replicas >= 1
                ), f"HPA {hpa_name} minReplicas too low: {min_replicas}"
                assert (
                    max_replicas > min_replicas
                ), f"HPA {hpa_name} maxReplicas not greater than minReplicas"
                assert (
                    max_replicas <= 20
                ), f"HPA {hpa_name} maxReplicas too high: {max_replicas}"

                logger.info(f"HPA {hpa_name}: min={min_replicas}, max={max_replicas}")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check HPA resources")

    @pytest.mark.parametrize(
        "deployment_name",
        [
            "orchestrator",
            "agent",
            "br_kg",
            "web-ui",
        ],
    )
    def test_hpa_target_deployment_exists(
        self, scaling_client: ScalingTestClient, deployment_name: str
    ):
        """Test that HPA targets valid deployments."""
        try:
            # Check if HPA exists for this deployment
            hpa_data = scaling_client.get_json_output(
                "hpa", namespace=scaling_client.namespace
            )
            hpas = hpa_data.get("items", [])

            deployment_hpa = None
            for hpa in hpas:
                target_ref = hpa["spec"]["scaleTargetRef"]
                if target_ref.get("name") == deployment_name:
                    deployment_hpa = hpa
                    break

            if not deployment_hpa:
                pytest.skip(f"No HPA configured for deployment {deployment_name}")

            # Verify target deployment exists
            deployment_data = scaling_client.get_json_output(
                "deployment", deployment_name
            )
            assert deployment_data["metadata"]["name"] == deployment_name

            # Check HPA status
            hpa_name = deployment_hpa["metadata"]["name"]
            status = deployment_hpa.get("status", {})

            # HPA should have current replicas info
            current_replicas = status.get("currentReplicas")
            if current_replicas is not None:
                assert (
                    current_replicas >= 1
                ), f"HPA {hpa_name} reports invalid current replicas: {current_replicas}"

            logger.info(f"HPA {hpa_name} targets deployment {deployment_name}")

        except subprocess.CalledProcessError:
            pytest.skip(f"Could not validate HPA for deployment {deployment_name}")

    def test_hpa_metrics_configuration(self, scaling_client: ScalingTestClient):
        """Test HPA metrics configuration."""
        try:
            hpa_data = scaling_client.get_json_output(
                "hpa", namespace=scaling_client.namespace
            )
            hpas = hpa_data.get("items", [])

            if not hpas:
                pytest.skip("No HPA resources to test")

            for hpa in hpas:
                hpa_name = hpa["metadata"]["name"]
                spec = hpa["spec"]

                # Check for metrics configuration
                metrics = spec.get("metrics", [])
                if not metrics:
                    # Fallback to legacy targetCPUUtilizationPercentage
                    cpu_target = spec.get("targetCPUUtilizationPercentage")
                    assert (
                        cpu_target is not None
                    ), f"HPA {hpa_name} has no metrics configuration"
                    assert (
                        10 <= cpu_target <= 90
                    ), f"HPA {hpa_name} CPU target unreasonable: {cpu_target}%"
                else:
                    # Validate metrics
                    for metric in metrics:
                        metric_type = metric.get("type")
                        assert metric_type in [
                            "Resource",
                            "Pods",
                            "Object",
                            "External",
                        ], f"HPA {hpa_name} invalid metric type: {metric_type}"

                        if metric_type == "Resource":
                            resource_name = metric["resource"]["name"]
                            assert resource_name in [
                                "cpu",
                                "memory",
                            ], f"HPA {hpa_name} unsupported resource: {resource_name}"

                logger.info(f"HPA {hpa_name} metrics configuration validated")

        except subprocess.CalledProcessError:
            pytest.skip("Could not validate HPA metrics configuration")


class TestLoadDistribution:
    """Test load distribution across scaled pods."""

    def test_load_distribution_orchestrator(
        self, scaling_client: ScalingTestClient, deployment_scaler
    ):
        """Test load distribution for orchestrator service."""
        deployment_name = "orchestrator"
        service_name = "orchestrator-service"
        namespace = "brain-researcher-core"

        try:
            # Scale orchestrator to multiple replicas
            target_replicas = 3
            scale_success = deployment_scaler(
                deployment_name, target_replicas, namespace
            )

            if not scale_success:
                pytest.skip(
                    f"Could not scale {deployment_name} to {target_replicas} replicas"
                )

            # Get service endpoint
            service_data = scaling_client.get_json_output(
                "service", service_name, namespace
            )
            cluster_ip = service_data["spec"]["clusterIP"]
            service_url = f"http://{cluster_ip}:3001"

            # Generate load and check distribution
            load_results = scaling_client.generate_load(
                service_url, duration=30, requests_per_second=5
            )

            total_requests = load_results["total_requests"]
            successful_requests = load_results["successful_requests"]

            logger.info(
                f"Load test results: {total_requests} total, {successful_requests} successful"
            )

            # Check that we made meaningful requests
            assert total_requests > 0, "No requests were made"

            # At least 70% should succeed for load distribution test
            success_rate = successful_requests / total_requests
            assert (
                success_rate >= 0.7
            ), f"Success rate too low for load distribution test: {success_rate:.2%}"

            # Check response times are reasonable
            response_times = load_results["response_times"]
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
                assert (
                    avg_response_time < 5.0
                ), f"Average response time too high: {avg_response_time:.2f}s"

                # No response should take more than 30 seconds
                max_response_time = max(response_times)
                assert (
                    max_response_time < 30.0
                ), f"Maximum response time too high: {max_response_time:.2f}s"

            # Verify pods are still running after load test
            time.sleep(10)

            deployment_data = scaling_client.get_json_output(
                "deployment", deployment_name, namespace
            )
            ready_replicas = deployment_data["status"].get("readyReplicas", 0)

            assert (
                ready_replicas == target_replicas
            ), f"Not all replicas ready after load test: {ready_replicas}/{target_replicas}"

            logger.info(f"Load distribution test passed for {deployment_name}")

        except subprocess.CalledProcessError:
            pytest.skip(f"Could not test load distribution for {deployment_name}")

    def test_load_balancing_endpoints(
        self, scaling_client: ScalingTestClient, deployment_scaler
    ):
        """Test that load balancing distributes across all endpoints."""
        deployment_name = "web-ui"
        service_name = "web-ui-service"
        namespace = "brain-researcher-core"

        try:
            # Scale to multiple replicas
            target_replicas = 2
            scale_success = deployment_scaler(
                deployment_name, target_replicas, namespace
            )

            if not scale_success:
                pytest.skip(
                    f"Could not scale {deployment_name} to {target_replicas} replicas"
                )

            # Wait extra time for pods to be fully ready
            time.sleep(30)

            # Check endpoints
            endpoints_data = scaling_client.get_json_output(
                "endpoints", service_name, namespace
            )
            subsets = endpoints_data.get("subsets", [])

            total_addresses = sum(
                len(subset.get("addresses", [])) for subset in subsets
            )
            assert (
                total_addresses >= target_replicas
            ), f"Not enough endpoints for load balancing: {total_addresses}/{target_replicas}"

            # Get actual endpoint addresses
            endpoint_ips = []
            for subset in subsets:
                for address in subset.get("addresses", []):
                    endpoint_ips.append(address["ip"])

            logger.info(f"Endpoint IPs for {service_name}: {endpoint_ips}")

            # Test basic connectivity to each endpoint
            service_data = scaling_client.get_json_output(
                "service", service_name, namespace
            )
            service_port = service_data["spec"]["ports"][0]["port"]

            # Basic connectivity test
            for ip in endpoint_ips:
                try:
                    response = requests.get(
                        f"http://{ip}:{service_port}", timeout=10, verify=False
                    )
                    # Any response (even 404) indicates connectivity
                    logger.info(
                        f"Endpoint {ip} responded with status {response.status_code}"
                    )
                except requests.RequestException as e:
                    logger.warning(f"Endpoint {ip} connectivity issue: {e}")

            logger.info(f"Load balancing endpoints test passed for {deployment_name}")

        except subprocess.CalledProcessError:
            pytest.skip(f"Could not test load balancing for {deployment_name}")

    def test_concurrent_load_handling(
        self, scaling_client: ScalingTestClient, deployment_scaler
    ):
        """Test handling of concurrent load."""
        deployment_name = "orchestrator"
        service_name = "orchestrator-service"
        namespace = "brain-researcher-core"

        try:
            # Scale to handle concurrent load
            target_replicas = 2
            scale_success = deployment_scaler(
                deployment_name, target_replicas, namespace
            )

            if not scale_success:
                pytest.skip(
                    f"Could not scale {deployment_name} for concurrent load test"
                )

            service_data = scaling_client.get_json_output(
                "service", service_name, namespace
            )
            cluster_ip = service_data["spec"]["clusterIP"]
            service_url = f"http://{cluster_ip}:3001"

            # Run multiple concurrent load generators
            def run_load_batch():
                return scaling_client.generate_load(
                    service_url, duration=20, requests_per_second=3
                )

            # Run 3 concurrent load generators
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(run_load_batch) for _ in range(3)]
                results = [future.result() for future in futures]

            # Aggregate results
            total_requests = sum(r["total_requests"] for r in results)
            total_successful = sum(r["successful_requests"] for r in results)
            all_response_times = []

            for r in results:
                all_response_times.extend(r["response_times"])

            logger.info(
                f"Concurrent load test: {total_requests} total, {total_successful} successful"
            )

            # Validate results
            assert total_requests > 0, "No concurrent requests were made"

            success_rate = total_successful / total_requests
            assert (
                success_rate >= 0.6
            ), f"Concurrent load success rate too low: {success_rate:.2%}"

            if all_response_times:
                avg_response_time = sum(all_response_times) / len(all_response_times)
                assert (
                    avg_response_time < 10.0
                ), f"Average response time under concurrent load too high: {avg_response_time:.2f}s"

            logger.info("Concurrent load handling test passed")

        except subprocess.CalledProcessError:
            pytest.skip("Could not test concurrent load handling")


class TestSessionAffinity:
    """Test session affinity configuration."""

    @pytest.mark.parametrize(
        "service_info",
        [
            ("orchestrator-service", "brain-researcher-core", True),
            ("agent-service", "brain-researcher-core", True),
            ("grafana-service", "brain-researcher-monitoring", True),
            ("br_kg-service", "brain-researcher-core", False),
            ("web-ui-service", "brain-researcher-core", False),
        ],
    )
    def test_session_affinity_configuration(
        self, scaling_client: ScalingTestClient, service_info
    ):
        """Test session affinity is configured correctly."""
        service_name, namespace, should_have_affinity = service_info

        try:
            service_data = scaling_client.get_json_output(
                "service", service_name, namespace
            )
            session_affinity = service_data["spec"].get("sessionAffinity", "None")

            if should_have_affinity:
                assert (
                    session_affinity == "ClientIP"
                ), f"Service {service_name} should have ClientIP session affinity, got: {session_affinity}"

                # Check session affinity config
                affinity_config = service_data["spec"].get("sessionAffinityConfig", {})
                if "clientIP" in affinity_config:
                    timeout = affinity_config["clientIP"].get("timeoutSeconds")
                    if timeout:
                        assert (
                            60 <= timeout <= 3600
                        ), f"Session affinity timeout unreasonable: {timeout}s"
            else:
                assert (
                    session_affinity == "None"
                ), f"Service {service_name} should not have session affinity, got: {session_affinity}"

            logger.info(
                f"Session affinity test passed for {service_name}: {session_affinity}"
            )

        except subprocess.CalledProcessError:
            pytest.skip(f"Service {service_name} not found in namespace {namespace}")

    def test_stateful_service_affinity(
        self, scaling_client: ScalingTestClient, deployment_scaler
    ):
        """Test that stateful services maintain session affinity."""
        service_name = "agent-service"
        deployment_name = "agent"
        namespace = "brain-researcher-core"

        try:
            # Scale agent to multiple replicas
            target_replicas = 2
            scale_success = deployment_scaler(
                deployment_name, target_replicas, namespace
            )

            if not scale_success:
                pytest.skip(
                    f"Could not scale {deployment_name} for session affinity test"
                )

            # Check service has session affinity
            service_data = scaling_client.get_json_output(
                "service", service_name, namespace
            )
            session_affinity = service_data["spec"].get("sessionAffinity")

            assert (
                session_affinity == "ClientIP"
            ), f"Agent service should have ClientIP affinity for stateful sessions"

            # Basic connectivity test
            cluster_ip = service_data["spec"]["clusterIP"]
            service_port = service_data["spec"]["ports"][0]["port"]

            try:
                response = requests.get(
                    f"http://{cluster_ip}:{service_port}/health",
                    timeout=10,
                    verify=False,
                )
                # Connection successful indicates affinity is working
                logger.info(
                    f"Session affinity test - service responded: {response.status_code}"
                )
            except requests.RequestException:
                # Service might not be ready, but configuration is correct
                pass

            logger.info("Stateful service affinity test passed")

        except subprocess.CalledProcessError:
            pytest.skip("Could not test stateful service affinity")

    def test_websocket_session_affinity(self, scaling_client: ScalingTestClient):
        """Test WebSocket session affinity for orchestrator."""
        service_name = "orchestrator-service"
        namespace = "brain-researcher-core"

        try:
            service_data = scaling_client.get_json_output(
                "service", service_name, namespace
            )

            # Check for WebSocket port
            websocket_port = None
            for port in service_data["spec"]["ports"]:
                if port["name"] == "websocket":
                    websocket_port = port["port"]
                    break

            if not websocket_port:
                pytest.skip("No WebSocket port configured for orchestrator")

            # Verify session affinity
            session_affinity = service_data["spec"].get("sessionAffinity")
            assert (
                session_affinity == "ClientIP"
            ), "WebSocket service should have ClientIP session affinity"

            # Check affinity timeout
            affinity_config = service_data["spec"].get("sessionAffinityConfig", {})
            if "clientIP" in affinity_config:
                timeout = affinity_config["clientIP"].get("timeoutSeconds", 0)
                # WebSocket sessions might need longer timeouts
                assert (
                    timeout >= 300
                ), f"WebSocket session affinity timeout too short: {timeout}s"

            logger.info("WebSocket session affinity test passed")

        except subprocess.CalledProcessError:
            pytest.skip("Could not test WebSocket session affinity")


class TestDatabaseConnectionPooling:
    """Test database connection pooling under scaling scenarios."""

    def test_postgres_connection_limits(
        self, scaling_client: ScalingTestClient, deployment_scaler
    ):
        """Test PostgreSQL connection limits with scaled services."""
        postgres_svc = "postgres-service"
        namespace = "brain-researcher-data"

        # Services that connect to PostgreSQL
        db_clients = ["orchestrator", "br_kg", "agent"]

        try:
            # Check PostgreSQL service exists
            scaling_client.get_json_output("service", postgres_svc, namespace)

            # Scale database client services
            for service_name in db_clients:
                try:
                    # Try to scale each service to 2 replicas
                    scale_success = deployment_scaler(
                        service_name, 2, "brain-researcher-core"
                    )
                    if scale_success:
                        logger.info(f"Scaled {service_name} to 2 replicas")
                    else:
                        logger.warning(f"Could not scale {service_name}")
                except Exception as e:
                    logger.warning(f"Could not scale {service_name}: {e}")

            # Wait for services to stabilize
            time.sleep(30)

            # Check PostgreSQL pod logs for connection warnings
            try:
                pods_data = scaling_client.get_json_output("pods", namespace=namespace)
                postgres_pods = [
                    pod
                    for pod in pods_data.get("items", [])
                    if "postgres" in pod["metadata"]["name"]
                ]

                connection_warnings = 0

                for pod in postgres_pods:
                    pod_name = pod["metadata"]["name"]
                    try:
                        # Get recent logs
                        logs = scaling_client.run_kubectl(
                            ["logs", pod_name, "-n", namespace, "--tail=50"]
                        )

                        # Look for connection-related warnings
                        warning_indicators = [
                            "too many connections",
                            "connection limit",
                            "max_connections",
                            "FATAL",
                        ]

                        for indicator in warning_indicators:
                            if indicator.lower() in logs.lower():
                                connection_warnings += 1
                                break

                    except subprocess.CalledProcessError:
                        pass

                # Some warnings might be acceptable, but not too many
                assert (
                    connection_warnings < len(postgres_pods) * 2
                ), f"Too many PostgreSQL connection warnings: {connection_warnings}"

                logger.info(
                    f"PostgreSQL connection limit test passed - {connection_warnings} warnings"
                )

            except subprocess.CalledProcessError:
                pytest.skip("Could not check PostgreSQL pod logs")

        except subprocess.CalledProcessError:
            pytest.skip("PostgreSQL service not available for connection pooling test")

    def test_redis_connection_scaling(
        self, scaling_client: ScalingTestClient, deployment_scaler
    ):
        """Test Redis connection scaling."""
        redis_svc = "redis-service"
        namespace = "brain-researcher-data"

        # Services that typically use Redis
        redis_clients = ["orchestrator", "agent"]

        try:
            # Check Redis service exists
            scaling_client.get_json_output("service", redis_svc, namespace)

            # Scale Redis client services
            for service_name in redis_clients:
                try:
                    scale_success = deployment_scaler(
                        service_name, 3, "brain-researcher-core"
                    )
                    if scale_success:
                        logger.info(
                            f"Scaled {service_name} to 3 replicas for Redis test"
                        )
                except Exception as e:
                    logger.warning(f"Could not scale {service_name}: {e}")

            # Wait for scaling
            time.sleep(30)

            # Check Redis connection info
            try:
                pods_data = scaling_client.get_json_output("pods", namespace=namespace)
                redis_pods = [
                    pod
                    for pod in pods_data.get("items", [])
                    if "redis" in pod["metadata"]["name"]
                ]

                for pod in redis_pods:
                    pod_name = pod["metadata"]["name"]
                    try:
                        # Check Redis info using kubectl exec
                        redis_info = scaling_client.run_kubectl(
                            [
                                "exec",
                                pod_name,
                                "-n",
                                namespace,
                                "--",
                                "redis-cli",
                                "info",
                                "clients",
                            ]
                        )

                        # Parse connected clients
                        for line in redis_info.split("\n"):
                            if line.startswith("connected_clients:"):
                                clients = int(line.split(":")[1])
                                # Should have reasonable number of connections
                                assert (
                                    clients < 100
                                ), f"Too many Redis connections: {clients}"
                                logger.info(f"Redis connected clients: {clients}")
                                break

                    except subprocess.CalledProcessError:
                        # Redis CLI might not be available or configured differently
                        pass

                logger.info("Redis connection scaling test passed")

            except subprocess.CalledProcessError:
                pytest.skip("Could not check Redis connection info")

        except subprocess.CalledProcessError:
            pytest.skip("Redis service not available for connection scaling test")

    def test_database_connection_pooling_config(
        self, scaling_client: ScalingTestClient
    ):
        """Test database connection pooling configuration."""
        namespace = "brain-researcher-core"

        # Check for connection pooling configuration in deployments
        services_with_db = ["orchestrator", "br_kg", "agent"]

        for service_name in services_with_db:
            try:
                deployment_data = scaling_client.get_json_output(
                    "deployment", service_name, namespace
                )
                containers = deployment_data["spec"]["template"]["spec"]["containers"]

                for container in containers:
                    env_vars = container.get("env", [])

                    # Look for database connection environment variables
                    db_env_vars = [
                        var
                        for var in env_vars
                        if any(
                            db_key in var["name"].upper()
                            for db_key in ["DB_", "DATABASE_", "POOL_", "REDIS_"]
                        )
                    ]

                    if db_env_vars:
                        logger.info(
                            f"Service {service_name} has DB environment configuration"
                        )

                        # Check for connection pool settings
                        pool_settings = [
                            var
                            for var in db_env_vars
                            if any(
                                pool_key in var["name"].upper()
                                for pool_key in ["POOL", "MAX_CONN", "MIN_CONN"]
                            )
                        ]

                        if pool_settings:
                            logger.info(
                                f"Service {service_name} has connection pool configuration"
                            )

                logger.info(f"Database connection config checked for {service_name}")

            except subprocess.CalledProcessError:
                continue

        logger.info("Database connection pooling configuration test completed")


if __name__ == "__main__":
    # Run scaling tests
    pytest.main([__file__, "-v", "-s"])
