#!/usr/bin/env python3
"""
Manifest validation tests that can run without a Kubernetes cluster.
These tests validate the structure and correctness of the K8s manifests.
"""

import os
from pathlib import Path

import pytest
import yaml


class TestManifestValidation:
    """Test Kubernetes manifests are valid and follow best practices."""

    @pytest.fixture
    def manifest_dir(self):
        """Get the manifests directory."""
        base_dir = Path(__file__).parent.parent.parent
        return base_dir / "infrastructure" / "k8s" / "manifests"

    @pytest.fixture
    def helm_dir(self):
        """Get the Helm chart directory."""
        base_dir = Path(__file__).parent.parent.parent
        return base_dir / "infrastructure" / "k8s" / "helm" / "brain-researcher"

    def load_yaml_file(self, filepath):
        """Load and parse a YAML file."""
        with open(filepath, "r") as f:
            # Support multi-document YAML files
            docs = list(yaml.safe_load_all(f))
            return docs if len(docs) > 1 else docs[0] if docs else None

    def test_manifests_exist(self, manifest_dir):
        """Test that all expected manifest files exist."""
        expected_files = [
            "00-namespaces.yaml",
            "01-configmaps.yaml",
            "02-secrets.yaml",
            "03-services.yaml",
            "04-storage.yaml",
            "05-statefulsets.yaml",
            "06-deployments.yaml",
            "07-hpa.yaml",
            "08-ingress.yaml",
            "09-network-policies.yaml",
        ]

        for filename in expected_files:
            filepath = manifest_dir / filename
            assert filepath.exists(), f"Missing manifest: {filename}"
            print(f"✓ Found manifest: {filename}")

    def test_namespace_configuration(self, manifest_dir):
        """Test namespace manifests are properly configured."""
        namespace_file = manifest_dir / "00-namespaces.yaml"
        if not namespace_file.exists():
            pytest.skip("Namespace file not found")

        namespaces = self.load_yaml_file(namespace_file)
        if not isinstance(namespaces, list):
            namespaces = [namespaces]

        expected_namespaces = [
            "brain-researcher-core",
            "brain-researcher-data",
            "brain-researcher-monitoring",
        ]

        found_namespaces = []
        for ns in namespaces:
            if ns and ns.get("kind") == "Namespace":
                name = ns["metadata"]["name"]
                found_namespaces.append(name)

                # Check for required labels
                assert "labels" in ns["metadata"], f"Namespace {name} missing labels"
                assert (
                    "app" in ns["metadata"]["labels"]
                ), f"Namespace {name} missing app label"
                print(f"✓ Namespace {name} properly configured")

        for expected_ns in expected_namespaces:
            assert expected_ns in found_namespaces, f"Missing namespace: {expected_ns}"

    def test_service_definitions(self, manifest_dir):
        """Test service manifests are properly configured."""
        service_file = manifest_dir / "03-services.yaml"
        if not service_file.exists():
            pytest.skip("Service file not found")

        services = self.load_yaml_file(service_file)
        if not isinstance(services, list):
            services = [services]

        required_services = [
            "orchestrator",
            "br_kg",
            "agent",
            "web-ui",
        ]

        found_services = []
        for svc in services:
            if svc and svc.get("kind") == "Service":
                name = svc["metadata"]["name"]
                found_services.append(name)

                # Validate service structure
                assert "spec" in svc, f"Service {name} missing spec"
                assert "ports" in svc["spec"], f"Service {name} missing ports"
                assert "selector" in svc["spec"], f"Service {name} missing selector"
                print(f"✓ Service {name} validated")

        for required_svc in required_services:
            assert any(
                required_svc in s for s in found_services
            ), f"Missing required service: {required_svc}"

    def test_deployment_resources(self, manifest_dir):
        """Test deployments have proper resource limits."""
        deployment_file = manifest_dir / "06-deployments.yaml"
        if not deployment_file.exists():
            pytest.skip("Deployment file not found")

        deployments = self.load_yaml_file(deployment_file)
        if not isinstance(deployments, list):
            deployments = [deployments]

        for deploy in deployments:
            if deploy and deploy.get("kind") == "Deployment":
                name = deploy["metadata"]["name"]
                containers = deploy["spec"]["template"]["spec"]["containers"]

                for container in containers:
                    # Check resource limits exist
                    assert (
                        "resources" in container
                    ), f"Container in {name} missing resources"
                    assert (
                        "limits" in container["resources"]
                    ), f"Container in {name} missing resource limits"
                    assert (
                        "requests" in container["resources"]
                    ), f"Container in {name} missing resource requests"

                    # Check probes
                    assert (
                        "livenessProbe" in container
                    ), f"Container in {name} missing liveness probe"
                    assert (
                        "readinessProbe" in container
                    ), f"Container in {name} missing readiness probe"

                    print(f"✓ Deployment {name} resources validated")

    def test_statefulset_configuration(self, manifest_dir):
        """Test StatefulSets are properly configured."""
        statefulset_file = manifest_dir / "05-statefulsets.yaml"
        if not statefulset_file.exists():
            pytest.skip("StatefulSet file not found")

        statefulsets = self.load_yaml_file(statefulset_file)
        if not isinstance(statefulsets, list):
            statefulsets = [statefulsets]

        for sts in statefulsets:
            if sts and sts.get("kind") == "StatefulSet":
                name = sts["metadata"]["name"]

                # Check for required StatefulSet fields
                assert (
                    "serviceName" in sts["spec"]
                ), f"StatefulSet {name} missing serviceName"
                assert (
                    "volumeClaimTemplates" in sts["spec"]
                ), f"StatefulSet {name} missing volumeClaimTemplates"
                assert (
                    "updateStrategy" in sts["spec"]
                ), f"StatefulSet {name} missing updateStrategy"

                print(f"✓ StatefulSet {name} validated")

    def test_agent_statefulset_allowlist_includes_rest_connectome_workflow_ids(
        self, manifest_dir
    ):
        """Agent StatefulSet must allowlist rest-connectome workflow runtime IDs."""
        statefulset_file = manifest_dir / "05-statefulsets.yaml"
        if not statefulset_file.exists():
            pytest.skip("StatefulSet file not found")

        statefulsets = self.load_yaml_file(statefulset_file)
        if not isinstance(statefulsets, list):
            statefulsets = [statefulsets]

        required = {
            "workflow_rest_connectome_e2e",
            "fetch_atlas",
            "extract_timeseries",
            "compute_connectivity",
        }
        found_agent = False
        for sts in statefulsets:
            if not sts or sts.get("kind") != "StatefulSet":
                continue
            if sts.get("metadata", {}).get("name") != "agent":
                continue
            found_agent = True
            containers = (
                (sts.get("spec") or {})
                .get("template", {})
                .get("spec", {})
                .get("containers", [])
            )
            assert containers, "Agent StatefulSet has no containers"
            env = containers[0].get("env") or []
            allow_raw = ""
            for item in env:
                if (
                    isinstance(item, dict)
                    and item.get("name") == "AGENT_TOOL_ALLOWLIST"
                ):
                    allow_raw = str(item.get("value") or "")
                    break
            assert allow_raw, "Agent StatefulSet missing AGENT_TOOL_ALLOWLIST value"
            allowset = {
                chunk.strip() for chunk in allow_raw.split(",") if chunk.strip()
            }
            missing = sorted(required - allowset)
            assert not missing, f"Agent StatefulSet missing allowlist IDs: {missing}"

        assert found_agent, "Agent StatefulSet not found in 05-statefulsets.yaml"

    def test_ingress_configuration(self, manifest_dir):
        """Test Ingress configuration."""
        ingress_file = manifest_dir / "08-ingress.yaml"
        if not ingress_file.exists():
            pytest.skip("Ingress file not found")

        ingresses = self.load_yaml_file(ingress_file)
        if not isinstance(ingresses, list):
            ingresses = [ingresses]

        for ing in ingresses:
            if ing and ing.get("kind") == "Ingress":
                name = ing["metadata"]["name"]

                # Check for TLS configuration
                assert "tls" in ing["spec"], f"Ingress {name} missing TLS config"

                # Check for rules
                assert "rules" in ing["spec"], f"Ingress {name} missing rules"

                # Check annotations for cert-manager
                annotations = ing["metadata"].get("annotations", {})
                assert (
                    "cert-manager.io/cluster-issuer" in annotations
                ), f"Ingress {name} missing cert-manager annotation"

                print(f"✓ Ingress {name} validated")

    def test_network_policies(self, manifest_dir):
        """Test NetworkPolicy configuration."""
        netpol_file = manifest_dir / "09-network-policies.yaml"
        if not netpol_file.exists():
            pytest.skip("NetworkPolicy file not found")

        policies = self.load_yaml_file(netpol_file)
        if not isinstance(policies, list):
            policies = [policies]

        # Check for deny-all policy
        deny_all_found = False
        for policy in policies:
            if policy and policy.get("kind") == "NetworkPolicy":
                name = policy["metadata"]["name"]
                if "deny-all" in name or "default-deny" in name:
                    deny_all_found = True

                # Validate policy structure
                assert "spec" in policy, f"NetworkPolicy {name} missing spec"
                assert (
                    "policyTypes" in policy["spec"]
                ), f"NetworkPolicy {name} missing policyTypes"

                print(f"✓ NetworkPolicy {name} validated")

        assert deny_all_found, "Default deny-all NetworkPolicy not found"

    def test_helm_chart_structure(self, helm_dir):
        """Test Helm chart structure and files."""
        required_files = [
            "Chart.yaml",
            "values.yaml",
            "templates/_helpers.tpl",
            "templates/NOTES.txt",
        ]

        for filename in required_files:
            filepath = helm_dir / filename
            assert filepath.exists(), f"Missing Helm file: {filename}"
            print(f"✓ Found Helm file: {filename}")

        # Validate Chart.yaml
        chart_file = helm_dir / "Chart.yaml"
        chart = self.load_yaml_file(chart_file)
        assert chart["name"] == "brain-researcher", "Invalid chart name"
        assert "version" in chart, "Missing chart version"
        assert "appVersion" in chart, "Missing app version"
        print("✓ Helm chart metadata validated")

        # Validate values.yaml structure
        values_file = helm_dir / "values.yaml"
        values = self.load_yaml_file(values_file)

        required_sections = ["global", "orchestrator", "br_kg", "agent", "webUi"]

        for section in required_sections:
            assert section in values, f"Missing section in values.yaml: {section}"
            print(f"✓ Helm values section '{section}' found")

    def test_security_contexts(self, manifest_dir):
        """Test that security contexts are properly configured."""
        deployment_file = manifest_dir / "06-deployments.yaml"
        if not deployment_file.exists():
            pytest.skip("Deployment file not found")

        deployments = self.load_yaml_file(deployment_file)
        if not isinstance(deployments, list):
            deployments = [deployments]

        security_issues = []
        for deploy in deployments:
            if deploy and deploy.get("kind") == "Deployment":
                name = deploy["metadata"]["name"]
                pod_spec = deploy["spec"]["template"]["spec"]

                # Check pod-level security context
                if "securityContext" not in pod_spec:
                    security_issues.append(f"{name}: Missing pod security context")
                else:
                    sec_ctx = pod_spec["securityContext"]
                    if not sec_ctx.get("runAsNonRoot", False):
                        security_issues.append(f"{name}: Not running as non-root")

                # Check container-level security
                for container in pod_spec["containers"]:
                    if "securityContext" in container:
                        if container["securityContext"].get("privileged", False):
                            security_issues.append(
                                f"{name}: Container running privileged"
                            )

        if security_issues:
            print("Security issues found:")
            for issue in security_issues:
                print(f"  ⚠️  {issue}")
        else:
            print("✓ All deployments have proper security contexts")

    def test_hpa_configuration(self, manifest_dir):
        """Test HorizontalPodAutoscaler configuration."""
        hpa_file = manifest_dir / "07-hpa.yaml"
        if not hpa_file.exists():
            pytest.skip("HPA file not found")

        hpas = self.load_yaml_file(hpa_file)
        if not isinstance(hpas, list):
            hpas = [hpas]

        for hpa in hpas:
            if hpa and hpa.get("kind") == "HorizontalPodAutoscaler":
                name = hpa["metadata"]["name"]
                spec = hpa["spec"]

                # Validate HPA settings
                assert "minReplicas" in spec, f"HPA {name} missing minReplicas"
                assert "maxReplicas" in spec, f"HPA {name} missing maxReplicas"
                assert (
                    spec["minReplicas"] < spec["maxReplicas"]
                ), f"HPA {name} minReplicas >= maxReplicas"
                assert "metrics" in spec, f"HPA {name} missing metrics"

                print(
                    f"✓ HPA {name} validated (min:{spec['minReplicas']}, max:{spec['maxReplicas']})"
                )


def run_manifest_tests():
    """Run manifest validation tests."""
    print("\n" + "=" * 60)
    print("Running Kubernetes Manifest Validation Tests")
    print("=" * 60)

    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    run_manifest_tests()
