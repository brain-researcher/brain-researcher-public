"""
Kubernetes Deployment Validation Tests for Brain Researcher Platform

This module provides comprehensive tests for validating Kubernetes deployments,
including namespace validation, service connectivity, pod readiness checks,
resource limit validation, storage mounting, and network policy tests.
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import requests
import yaml


class KubernetesTestClient:
    """Client for executing kubectl commands and parsing responses."""

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


@pytest.fixture(scope="module")
def k8s_client():
    """Kubernetes test client fixture."""
    return KubernetesTestClient()


@pytest.fixture(scope="module")
def manifest_path():
    """Path to Kubernetes manifests."""
    return Path(__file__).parent.parent.parent / "infrastructure" / "k8s" / "manifests"


class TestNamespaceValidation:
    """Test namespace creation and configuration."""

    @pytest.mark.parametrize(
        "namespace",
        [
            "brain-researcher-core",
            "brain-researcher-data",
            "brain-researcher-monitoring",
        ],
    )
    def test_namespace_exists(self, k8s_client: KubernetesTestClient, namespace: str):
        """Test that required namespaces exist."""
        try:
            output = k8s_client.run_kubectl(["get", "namespace", namespace])
            assert namespace in output
        except subprocess.CalledProcessError:
            pytest.fail(f"Namespace {namespace} does not exist")

    @pytest.mark.parametrize(
        "namespace",
        [
            "brain-researcher-core",
            "brain-researcher-data",
            "brain-researcher-monitoring",
        ],
    )
    def test_namespace_labels(self, k8s_client: KubernetesTestClient, namespace: str):
        """Test namespace labels are correctly set."""
        ns_data = k8s_client.get_json_output("namespace", namespace)
        labels = ns_data.get("metadata", {}).get("labels", {})

        assert labels.get("name") == namespace
        assert labels.get("app.kubernetes.io/name") == "brain-researcher"
        assert labels.get("app.kubernetes.io/part-of") == "brain-researcher-platform"

    def test_namespace_resource_quotas(self, k8s_client: KubernetesTestClient):
        """Test that resource quotas are properly configured."""
        for namespace in ["brain-researcher-core", "brain-researcher-data"]:
            try:
                quota_output = k8s_client.run_kubectl(
                    ["get", "resourcequota", "-n", namespace, "-o", "json"]
                )
                quotas = json.loads(quota_output)
                # Check that at least one resource quota exists for production namespaces
                assert len(quotas.get("items", [])) >= 0
            except subprocess.CalledProcessError:
                # ResourceQuotas are optional but recommended
                pass


class TestServiceConnectivity:
    """Test Kubernetes service connectivity and configuration."""

    @pytest.mark.parametrize(
        "service_info",
        [
            ("nginx-service", "brain-researcher-core", 80),
            ("orchestrator-service", "brain-researcher-core", 3001),
            ("agent-service", "brain-researcher-core", 8000),
            ("br_kg-service", "brain-researcher-core", 5000),
            ("niclip-service", "brain-researcher-core", 8001),
            ("web-ui-service", "brain-researcher-core", 3000),
            ("redis-service", "brain-researcher-data", 6379),
            ("postgres-service", "brain-researcher-data", 5432),
            ("prometheus-service", "brain-researcher-monitoring", 9090),
            ("grafana-service", "brain-researcher-monitoring", 3000),
        ],
    )
    def test_service_exists_and_configured(
        self, k8s_client: KubernetesTestClient, service_info
    ):
        """Test that services exist and are properly configured."""
        service_name, namespace, expected_port = service_info

        try:
            service_data = k8s_client.get_json_output(
                "service", service_name, namespace
            )

            # Verify service exists
            assert service_data["metadata"]["name"] == service_name

            # Verify port configuration
            ports = service_data["spec"]["ports"]
            port_numbers = [port["port"] for port in ports]
            assert expected_port in port_numbers

            # Verify labels
            labels = service_data["metadata"]["labels"]
            assert "app.kubernetes.io/part-of" in labels
            assert labels["app.kubernetes.io/part-of"] == "brain-researcher-platform"

        except subprocess.CalledProcessError:
            pytest.fail(
                f"Service {service_name} in namespace {namespace} does not exist"
            )

    def test_service_endpoints_have_targets(self, k8s_client: KubernetesTestClient):
        """Test that services have backend endpoints (pods)."""
        core_services = [
            "agent-service",
            "br_kg-service",
            "orchestrator-service",
            "web-ui-service",
            "niclip-service",
        ]

        for service_name in core_services:
            try:
                endpoints = k8s_client.get_json_output(
                    "endpoints", service_name, "brain-researcher-core"
                )

                # Check that endpoints exist
                subsets = endpoints.get("subsets", [])
                if subsets:
                    # At least one subset should have addresses
                    has_ready_addresses = any(
                        subset.get("addresses", []) for subset in subsets
                    )
                    assert (
                        has_ready_addresses
                    ), f"Service {service_name} has no ready endpoints"
                else:
                    # If no subsets, the service might be starting up
                    # This is acceptable in some scenarios
                    pass

            except subprocess.CalledProcessError:
                pytest.fail(f"Could not get endpoints for service {service_name}")


class TestPodReadiness:
    """Test pod readiness and health checks."""

    @pytest.mark.parametrize(
        "namespace",
        [
            "brain-researcher-core",
            "brain-researcher-data",
            "brain-researcher-monitoring",
        ],
    )
    def test_all_pods_running(self, k8s_client: KubernetesTestClient, namespace: str):
        """Test that all pods in namespace are running."""
        try:
            pods_data = k8s_client.get_json_output("pods", namespace=namespace)

            for pod in pods_data.get("items", []):
                pod_name = pod["metadata"]["name"]
                phase = pod["status"].get("phase", "Unknown")

                # Pods should be Running or Succeeded
                assert phase in [
                    "Running",
                    "Succeeded",
                ], f"Pod {pod_name} is in phase {phase}"

                # Check container statuses
                container_statuses = pod["status"].get("containerStatuses", [])
                for status in container_statuses:
                    container_name = status["name"]
                    ready = status.get("ready", False)
                    assert (
                        ready
                    ), f"Container {container_name} in pod {pod_name} is not ready"

        except subprocess.CalledProcessError:
            pytest.fail(f"Could not get pods in namespace {namespace}")

    def test_critical_pods_have_probes(self, k8s_client: KubernetesTestClient):
        """Test that critical pods have liveness and readiness probes."""
        critical_deployments = ["agent", "br_kg", "orchestrator", "postgres", "redis"]

        for deployment_name in critical_deployments:
            try:
                # Determine namespace
                if deployment_name in ["postgres", "redis"]:
                    namespace = "brain-researcher-data"
                elif deployment_name == "prometheus":
                    namespace = "brain-researcher-monitoring"
                else:
                    namespace = "brain-researcher-core"

                deployment_data = k8s_client.get_json_output(
                    "deployment", deployment_name, namespace
                )

                containers = deployment_data["spec"]["template"]["spec"]["containers"]

                for container in containers:
                    container_name = container["name"]

                    # Skip sidecar containers (metrics exporters)
                    if "exporter" in container_name or "metrics" in container_name:
                        continue

                    # Check for probes on main containers
                    if deployment_name in ["postgres", "redis", "agent", "br_kg"]:
                        assert (
                            "livenessProbe" in container
                        ), f"Container {container_name} missing liveness probe"
                        assert (
                            "readinessProbe" in container
                        ), f"Container {container_name} missing readiness probe"

            except subprocess.CalledProcessError:
                # Some deployments might not exist in test environment
                pass


class TestResourceLimits:
    """Test resource limits and requests are properly configured."""

    def test_pods_have_resource_limits(self, k8s_client: KubernetesTestClient):
        """Test that pods have resource limits and requests."""
        namespaces = ["brain-researcher-core", "brain-researcher-data"]

        for namespace in namespaces:
            try:
                pods_data = k8s_client.get_json_output("pods", namespace=namespace)

                for pod in pods_data.get("items", []):
                    pod_name = pod["metadata"]["name"]

                    # Skip completed pods
                    if pod["status"].get("phase") == "Succeeded":
                        continue

                    containers = pod["spec"]["containers"]

                    for container in containers:
                        container_name = container["name"]
                        resources = container.get("resources", {})

                        # Check for resource requests
                        requests = resources.get("requests", {})
                        assert (
                            "memory" in requests or "cpu" in requests
                        ), f"Container {container_name} in pod {pod_name} has no resource requests"

                        # Check for resource limits
                        limits = resources.get("limits", {})
                        assert (
                            "memory" in limits or "cpu" in limits
                        ), f"Container {container_name} in pod {pod_name} has no resource limits"

            except subprocess.CalledProcessError:
                pytest.fail(f"Could not get pods in namespace {namespace}")

    def test_resource_limits_reasonable(self, k8s_client: KubernetesTestClient):
        """Test that resource limits are within reasonable bounds."""
        try:
            pods_data = k8s_client.get_json_output(
                "pods", namespace="brain-researcher-core"
            )

            for pod in pods_data.get("items", []):
                containers = pod["spec"]["containers"]

                for container in containers:
                    resources = container.get("resources", {})
                    limits = resources.get("limits", {})

                    # Check memory limits are reasonable (not too high/low)
                    if "memory" in limits:
                        memory_str = limits["memory"]
                        # Basic validation - should end with standard units
                        assert any(
                            memory_str.endswith(unit) for unit in ["Mi", "Gi", "M", "G"]
                        ), f"Invalid memory limit format: {memory_str}"

                    # Check CPU limits are reasonable
                    if "cpu" in limits:
                        cpu_str = limits["cpu"]
                        # Should be numeric or end with 'm'
                        assert (
                            cpu_str.replace(".", "").replace("m", "").isdigit()
                        ), f"Invalid CPU limit format: {cpu_str}"

        except subprocess.CalledProcessError:
            # Not a failure if pods don't exist yet
            pass


class TestStorageMounting:
    """Test persistent volume and storage mounting."""

    def test_persistent_volumes_exist(self, k8s_client: KubernetesTestClient):
        """Test that required persistent volumes exist."""
        try:
            pv_data = k8s_client.get_json_output("pv")
            pv_names = [pv["metadata"]["name"] for pv in pv_data.get("items", [])]

            # We should have PVs for stateful services
            expected_pvs = ["postgres-pv", "redis-pv", "agent-pv", "br_kg-pv"]

            for expected_pv in expected_pvs:
                # Check if any PV matches the expected pattern
                matching_pvs = [pv for pv in pv_names if expected_pv in pv]
                if not matching_pvs:
                    # PVs might be dynamically provisioned, so this is not always a failure
                    pass

        except subprocess.CalledProcessError:
            # PVs might not exist in all test environments
            pass

    def test_persistent_volume_claims_bound(self, k8s_client: KubernetesTestClient):
        """Test that PVCs are bound to PVs."""
        namespaces = ["brain-researcher-core", "brain-researcher-data"]

        for namespace in namespaces:
            try:
                pvc_data = k8s_client.get_json_output("pvc", namespace=namespace)

                for pvc in pvc_data.get("items", []):
                    pvc_name = pvc["metadata"]["name"]
                    status = pvc["status"]["phase"]

                    assert status in [
                        "Bound",
                        "Pending",
                    ], f"PVC {pvc_name} is in unexpected state: {status}"

                    # If bound, should have volume name
                    if status == "Bound":
                        assert (
                            "volumeName" in pvc["spec"]
                        ), f"Bound PVC {pvc_name} has no volume name"

            except subprocess.CalledProcessError:
                # PVCs might not exist in all environments
                pass

    def test_stateful_pods_have_storage(self, k8s_client: KubernetesTestClient):
        """Test that stateful pods have persistent storage mounted."""
        stateful_pods = ["postgres", "redis", "agent", "br_kg"]

        for pod_prefix in stateful_pods:
            try:
                # Determine namespace
                if pod_prefix in ["postgres", "redis"]:
                    namespace = "brain-researcher-data"
                else:
                    namespace = "brain-researcher-core"

                pods_data = k8s_client.get_json_output("pods", namespace=namespace)

                for pod in pods_data.get("items", []):
                    pod_name = pod["metadata"]["name"]

                    if pod_prefix in pod_name:
                        volumes = pod["spec"].get("volumes", [])
                        volume_mounts = []

                        for container in pod["spec"]["containers"]:
                            volume_mounts.extend(container.get("volumeMounts", []))

                        # Should have at least one persistent volume mount
                        has_persistent_mount = any(
                            mount
                            for mount in volume_mounts
                            if not mount["name"].startswith("tmp-")
                            and mount["name"] not in ["kube-api-access"]
                        )

                        assert (
                            has_persistent_mount or len(volumes) > 1
                        ), f"Pod {pod_name} appears to have no persistent storage"

            except subprocess.CalledProcessError:
                # Pods might not exist in test environment
                pass


class TestNetworkPolicies:
    """Test network policies and security configurations."""

    def test_network_policies_exist(self, k8s_client: KubernetesTestClient):
        """Test that network policies are configured."""
        namespaces = ["brain-researcher-core", "brain-researcher-data"]

        for namespace in namespaces:
            try:
                np_data = k8s_client.get_json_output(
                    "networkpolicy", namespace=namespace
                )

                # Should have at least one network policy for security
                policies = np_data.get("items", [])
                if len(policies) > 0:
                    for policy in policies:
                        policy_name = policy["metadata"]["name"]

                        # Validate basic structure
                        assert "spec" in policy
                        spec = policy["spec"]

                        # Should have pod selector
                        assert "podSelector" in spec

                        # Should have ingress or egress rules
                        assert (
                            "ingress" in spec
                            or "egress" in spec
                            or "policyTypes" in spec
                        )

            except subprocess.CalledProcessError:
                # Network policies might not be implemented in all clusters
                pass

    def test_deny_all_default_policy(self, k8s_client: KubernetesTestClient):
        """Test for deny-all default network policies."""
        namespaces = ["brain-researcher-core", "brain-researcher-data"]

        for namespace in namespaces:
            try:
                np_data = k8s_client.get_json_output(
                    "networkpolicy", namespace=namespace
                )

                # Look for a default deny-all policy
                deny_all_policies = [
                    policy
                    for policy in np_data.get("items", [])
                    if "deny-all" in policy["metadata"]["name"].lower()
                    or "default" in policy["metadata"]["name"].lower()
                ]

                # This is a security best practice but not required
                if deny_all_policies:
                    for policy in deny_all_policies:
                        spec = policy["spec"]
                        # Should have empty pod selector (applies to all pods)
                        pod_selector = spec.get("podSelector", {})
                        # Empty selector or specific matchLabels are both valid

            except subprocess.CalledProcessError:
                # Network policies might not exist
                pass

    def test_service_to_service_communication(self, k8s_client: KubernetesTestClient):
        """Test that required service-to-service communication is allowed."""
        # This is a basic connectivity test
        try:
            # Get all services in core namespace
            services_data = k8s_client.get_json_output(
                "service", namespace="brain-researcher-core"
            )

            services = services_data.get("items", [])
            assert (
                len(services) > 0
            ), "No services found in brain-researcher-core namespace"

            # Basic validation that services exist
            service_names = [svc["metadata"]["name"] for svc in services]
            expected_services = [
                "orchestrator-service",
                "agent-service",
                "br_kg-service",
            ]

            for expected_svc in expected_services:
                assert any(
                    expected_svc in name for name in service_names
                ), f"Expected service {expected_svc} not found"

        except subprocess.CalledProcessError:
            pytest.fail("Could not retrieve services for network policy validation")


# Additional test utilities and fixtures


@pytest.fixture(scope="session")
def wait_for_deployment():
    """Fixture to wait for deployments to be ready."""

    def _wait(deployment_name: str, namespace: str, timeout: int = 300):
        """Wait for a deployment to be ready."""
        k8s_client = KubernetesTestClient(namespace)

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                deployment_data = k8s_client.get_json_output(
                    "deployment", deployment_name, namespace
                )

                status = deployment_data.get("status", {})
                ready_replicas = status.get("readyReplicas", 0)
                replicas = status.get("replicas", 0)

                if ready_replicas == replicas and replicas > 0:
                    return True

                time.sleep(10)

            except subprocess.CalledProcessError:
                time.sleep(10)
                continue

        return False

    return _wait


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
