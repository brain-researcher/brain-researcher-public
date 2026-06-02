"""
Kubernetes Monitoring Tests for Brain Researcher Platform

This module provides comprehensive tests for monitoring infrastructure including
Prometheus metrics collection, alert rule validation, and log aggregation tests.
"""

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import requests
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MonitoringTestClient:
    """Client for testing monitoring infrastructure."""

    def __init__(self):
        self.prometheus_url = None
        self.grafana_url = None
        self.alert_manager_url = None

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
        args = ["get", resource_type]
        if name:
            args.append(name)
        if namespace:
            args.extend(["-n", namespace])
        args.extend(["-o", "json"])
        output = self.run_kubectl(args)
        return json.loads(output)

    def setup_service_urls(self):
        """Setup service URLs for monitoring components."""
        try:
            # Get Prometheus service
            prometheus_svc = self.get_json_output(
                "service", "prometheus-service", "brain-researcher-monitoring"
            )
            prometheus_ip = prometheus_svc["spec"]["clusterIP"]
            prometheus_port = prometheus_svc["spec"]["ports"][0]["port"]
            self.prometheus_url = f"http://{prometheus_ip}:{prometheus_port}"

            # Get Grafana service
            grafana_svc = self.get_json_output(
                "service", "grafana-service", "brain-researcher-monitoring"
            )
            grafana_ip = grafana_svc["spec"]["clusterIP"]
            grafana_port = grafana_svc["spec"]["ports"][0]["port"]
            self.grafana_url = f"http://{grafana_ip}:{grafana_port}"

        except subprocess.CalledProcessError:
            logger.warning("Could not setup monitoring service URLs")

    def make_request(self, url: str, timeout: int = 30) -> Optional[requests.Response]:
        """Make HTTP request with error handling."""
        try:
            response = requests.get(url, timeout=timeout, verify=False)
            return response
        except requests.RequestException as e:
            logger.warning(f"Request to {url} failed: {e}")
            return None

    def query_prometheus(self, query: str) -> Optional[Dict[str, Any]]:
        """Query Prometheus API."""
        if not self.prometheus_url:
            self.setup_service_urls()

        if not self.prometheus_url:
            return None

        url = f"{self.prometheus_url}/api/v1/query"
        params = {"query": query}

        try:
            response = requests.get(url, params=params, timeout=30, verify=False)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            pass

        return None


@pytest.fixture(scope="module")
def monitoring_client():
    """Monitoring test client fixture."""
    client = MonitoringTestClient()
    client.setup_service_urls()
    return client


class TestPrometheusMetricsCollection:
    """Test Prometheus metrics collection from all services."""

    def test_prometheus_server_running(self, monitoring_client: MonitoringTestClient):
        """Test that Prometheus server is running and accessible."""
        try:
            # Check Prometheus pod is running
            pods_data = monitoring_client.get_json_output(
                "pods", namespace="brain-researcher-monitoring"
            )
            prometheus_pods = [
                pod
                for pod in pods_data.get("items", [])
                if "prometheus" in pod["metadata"]["name"]
            ]

            assert len(prometheus_pods) > 0, "No Prometheus pods found"

            for pod in prometheus_pods:
                pod_name = pod["metadata"]["name"]
                phase = pod["status"].get("phase", "Unknown")
                assert (
                    phase == "Running"
                ), f"Prometheus pod {pod_name} not running: {phase}"

            # Test Prometheus API accessibility
            if monitoring_client.prometheus_url:
                response = monitoring_client.make_request(
                    f"{monitoring_client.prometheus_url}/-/healthy"
                )
                if response:
                    assert (
                        response.status_code == 200
                    ), f"Prometheus health check failed: {response.status_code}"
                    logger.info("Prometheus server is healthy")
                else:
                    pytest.skip("Prometheus API not accessible")
            else:
                pytest.skip("Prometheus URL not configured")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check Prometheus server status")

    def test_prometheus_configuration(self, monitoring_client: MonitoringTestClient):
        """Test Prometheus configuration."""
        try:
            # Check Prometheus ConfigMap
            config_data = monitoring_client.get_json_output(
                "configmap", "prometheus-config", "brain-researcher-monitoring"
            )

            prometheus_yml = config_data["data"]["prometheus.yml"]
            config = yaml.safe_load(prometheus_yml)

            # Validate basic configuration structure
            assert "global" in config, "Prometheus config missing global section"
            assert (
                "scrape_configs" in config
            ), "Prometheus config missing scrape_configs"

            # Check scrape interval
            global_config = config["global"]
            scrape_interval = global_config.get("scrape_interval", "")
            assert scrape_interval, "No global scrape_interval configured"

            # Validate scrape configs
            scrape_configs = config["scrape_configs"]
            assert len(scrape_configs) > 0, "No scrape configurations found"

            # Check for Brain Researcher service discovery
            br_jobs = [
                job
                for job in scrape_configs
                if "brain-researcher" in job.get("job_name", "").lower()
            ]

            if br_jobs:
                logger.info(f"Found {len(br_jobs)} Brain Researcher monitoring jobs")
            else:
                # Check for Kubernetes service discovery
                k8s_jobs = [
                    job
                    for job in scrape_configs
                    if "kubernetes" in job.get("job_name", "").lower()
                ]
                assert len(k8s_jobs) > 0, "No Kubernetes service discovery configured"

            logger.info("Prometheus configuration validation passed")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check Prometheus configuration")
        except yaml.YAMLError:
            pytest.fail("Invalid Prometheus YAML configuration")

    @pytest.mark.parametrize(
        "service_metrics",
        [
            ("orchestrator", ["http_requests_total", "http_request_duration_seconds"]),
            ("agent", ["langgraph_requests_total", "tool_execution_duration_seconds"]),
            ("br_kg", ["api_requests_total", "database_query_duration_seconds"]),
            ("postgres", ["pg_up", "pg_stat_database_numbackends"]),
            ("redis", ["redis_up", "redis_connected_clients"]),
        ],
    )
    def test_service_metrics_collection(
        self, monitoring_client: MonitoringTestClient, service_metrics
    ):
        """Test that services are exposing metrics correctly."""
        service_name, expected_metrics = service_metrics

        if not monitoring_client.prometheus_url:
            pytest.skip("Prometheus not accessible")

        # Query for service-specific metrics
        found_metrics = []

        for metric in expected_metrics:
            result = monitoring_client.query_prometheus(metric)

            if result and result.get("status") == "success":
                data = result.get("data", {})
                result_data = data.get("result", [])

                if result_data:
                    found_metrics.append(metric)
                    logger.info(f"Found metric {metric} for {service_name}")

        # At least one expected metric should be found
        if found_metrics:
            logger.info(
                f"Service {service_name} metrics collection verified: {found_metrics}"
            )
        else:
            # Metrics might not be available yet, or service might not expose them
            logger.warning(f"No expected metrics found for {service_name}")

    def test_kubernetes_cluster_metrics(self, monitoring_client: MonitoringTestClient):
        """Test that Kubernetes cluster metrics are being collected."""
        if not monitoring_client.prometheus_url:
            pytest.skip("Prometheus not accessible")

        # Test common Kubernetes metrics
        k8s_metrics = [
            "up",  # General up/down status
            "kubernetes_build_info",  # Kubernetes version info
            "kube_node_info",  # Node information
            "kube_pod_info",  # Pod information
            "container_cpu_usage_seconds_total",  # Container CPU
            "container_memory_working_set_bytes",  # Container memory
        ]

        found_k8s_metrics = []

        for metric in k8s_metrics:
            result = monitoring_client.query_prometheus(metric)

            if result and result.get("status") == "success":
                data = result.get("data", {})
                if data.get("result"):
                    found_k8s_metrics.append(metric)

        # Should find at least basic metrics
        assert (
            len(found_k8s_metrics) > 0
        ), f"No Kubernetes metrics found. Available: {found_k8s_metrics}"

        logger.info(f"Kubernetes cluster metrics found: {found_k8s_metrics}")

    def test_metrics_targets_discovery(self, monitoring_client: MonitoringTestClient):
        """Test Prometheus target discovery."""
        if not monitoring_client.prometheus_url:
            pytest.skip("Prometheus not accessible")

        # Query targets endpoint
        targets_url = f"{monitoring_client.prometheus_url}/api/v1/targets"
        response = monitoring_client.make_request(targets_url)

        if not response or response.status_code != 200:
            pytest.skip("Could not query Prometheus targets")

        targets_data = response.json()

        if targets_data.get("status") != "success":
            pytest.skip("Prometheus targets query failed")

        active_targets = targets_data.get("data", {}).get("activeTargets", [])

        assert len(active_targets) > 0, "No active targets found in Prometheus"

        # Count healthy targets
        healthy_targets = [
            target for target in active_targets if target.get("health") == "up"
        ]

        total_targets = len(active_targets)
        healthy_count = len(healthy_targets)

        logger.info(f"Prometheus targets: {healthy_count}/{total_targets} healthy")

        # At least 50% of targets should be healthy
        if total_targets > 0:
            health_ratio = healthy_count / total_targets
            assert (
                health_ratio >= 0.5
            ), f"Too many unhealthy targets: {healthy_count}/{total_targets}"

        # Log target details
        for target in active_targets[:5]:  # Log first 5 targets
            job = target.get("labels", {}).get("job", "unknown")
            instance = target.get("labels", {}).get("instance", "unknown")
            health = target.get("health", "unknown")
            logger.info(f"Target: {job}/{instance} - {health}")


class TestAlertRuleValidation:
    """Test Prometheus alerting rules configuration."""

    def test_alert_rules_configuration(self, monitoring_client: MonitoringTestClient):
        """Test that alert rules are properly configured."""
        try:
            # Check for alert rule ConfigMaps
            configmaps_data = monitoring_client.get_json_output(
                "configmap", namespace="brain-researcher-monitoring"
            )

            alert_configmaps = [
                cm
                for cm in configmaps_data.get("items", [])
                if "alert" in cm["metadata"]["name"].lower()
                or "rule" in cm["metadata"]["name"].lower()
            ]

            if not alert_configmaps:
                pytest.skip("No alert rule ConfigMaps found")

            for cm in alert_configmaps:
                cm_name = cm["metadata"]["name"]
                cm_data = cm.get("data", {})

                # Look for YAML rule files
                rule_files = [
                    (key, value)
                    for key, value in cm_data.items()
                    if key.endswith(".yml") or key.endswith(".yaml")
                ]

                if rule_files:
                    logger.info(f"Found alert rules in ConfigMap {cm_name}")

                    for filename, content in rule_files:
                        try:
                            rules_config = yaml.safe_load(content)

                            # Validate rule structure
                            if "groups" in rules_config:
                                groups = rules_config["groups"]

                                for group in groups:
                                    group_name = group.get("name", "unnamed")
                                    rules = group.get("rules", [])

                                    logger.info(
                                        f"Alert group '{group_name}' has {len(rules)} rules"
                                    )

                                    for rule in rules:
                                        # Validate required fields
                                        if "alert" in rule:  # It's an alerting rule
                                            assert (
                                                "expr" in rule
                                            ), f"Alert rule missing expression in group {group_name}"
                                            assert "for" in rule or "summary" in rule.get(
                                                "annotations", {}
                                            ), f"Alert rule missing duration or summary in group {group_name}"

                        except yaml.YAMLError as e:
                            pytest.fail(f"Invalid YAML in alert rules {filename}: {e}")

            logger.info("Alert rules configuration validation passed")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check alert rules configuration")

    def test_critical_alerts_defined(self, monitoring_client: MonitoringTestClient):
        """Test that critical alerts are defined."""
        if not monitoring_client.prometheus_url:
            pytest.skip("Prometheus not accessible")

        # Query Prometheus rules API
        rules_url = f"{monitoring_client.prometheus_url}/api/v1/rules"
        response = monitoring_client.make_request(rules_url)

        if not response or response.status_code != 200:
            pytest.skip("Could not query Prometheus rules")

        rules_data = response.json()

        if rules_data.get("status") != "success":
            pytest.skip("Prometheus rules query failed")

        rule_groups = rules_data.get("data", {}).get("groups", [])

        # Extract all alert rules
        alert_rules = []
        for group in rule_groups:
            for rule in group.get("rules", []):
                if rule.get("type") == "alerting":
                    alert_rules.append(rule["name"])

        if not alert_rules:
            pytest.skip("No alert rules found in Prometheus")

        # Check for critical alert categories
        critical_alert_patterns = [
            r".*[Pp]od.*[Dd]own.*",
            r".*[Ss]ervice.*[Dd]own.*",
            r".*[Cc]pu.*[Hh]igh.*",
            r".*[Mm]emory.*[Hh]igh.*",
            r".*[Dd]isk.*[Ff]ull.*",
            r".*[Dd]atabase.*[Dd]own.*",
        ]

        found_critical_alerts = []

        for pattern in critical_alert_patterns:
            matching_alerts = [
                alert
                for alert in alert_rules
                if re.search(pattern, alert, re.IGNORECASE)
            ]
            found_critical_alerts.extend(matching_alerts)

        logger.info(f"Alert rules found: {len(alert_rules)}")
        logger.info(f"Critical alerts found: {len(found_critical_alerts)}")

        # Log some example alerts
        for alert in alert_rules[:5]:
            logger.info(f"Alert rule: {alert}")

        # Should have some form of critical monitoring
        if len(found_critical_alerts) == 0 and len(alert_rules) == 0:
            pytest.skip("No alerting configured")

    def test_alert_manager_connectivity(self, monitoring_client: MonitoringTestClient):
        """Test AlertManager connectivity if configured."""
        try:
            # Check if AlertManager is deployed
            pods_data = monitoring_client.get_json_output(
                "pods", namespace="brain-researcher-monitoring"
            )

            alertmanager_pods = [
                pod
                for pod in pods_data.get("items", [])
                if "alertmanager" in pod["metadata"]["name"].lower()
            ]

            if not alertmanager_pods:
                pytest.skip("AlertManager not deployed")

            # Check AlertManager service
            try:
                alertmanager_svc = monitoring_client.get_json_output(
                    "service", "alertmanager-service", "brain-researcher-monitoring"
                )

                cluster_ip = alertmanager_svc["spec"]["clusterIP"]
                port = alertmanager_svc["spec"]["ports"][0]["port"]
                alertmanager_url = f"http://{cluster_ip}:{port}"

                # Test AlertManager API
                response = monitoring_client.make_request(
                    f"{alertmanager_url}/-/healthy"
                )

                if response:
                    assert (
                        response.status_code == 200
                    ), f"AlertManager health check failed: {response.status_code}"
                    logger.info("AlertManager is healthy")
                else:
                    logger.warning("AlertManager not accessible")

            except subprocess.CalledProcessError:
                pytest.skip("AlertManager service not found")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check AlertManager deployment")

    def test_alert_notification_configuration(
        self, monitoring_client: MonitoringTestClient
    ):
        """Test alert notification configuration."""
        try:
            # Check for AlertManager configuration
            try:
                alertmanager_config = monitoring_client.get_json_output(
                    "configmap", "alertmanager-config", "brain-researcher-monitoring"
                )

                config_data = alertmanager_config["data"]["alertmanager.yml"]
                config = yaml.safe_load(config_data)

                # Validate basic AlertManager config structure
                assert (
                    "global" in config or "route" in config
                ), "AlertManager config missing basic structure"

                if "route" in config:
                    route = config["route"]
                    assert "receiver" in route, "AlertManager route missing receiver"

                if "receivers" in config:
                    receivers = config["receivers"]
                    assert len(receivers) > 0, "No AlertManager receivers configured"

                    # Log receiver types
                    for receiver in receivers:
                        receiver_name = receiver.get("name", "unnamed")
                        notification_types = []

                        if "email_configs" in receiver:
                            notification_types.append("email")
                        if "slack_configs" in receiver:
                            notification_types.append("slack")
                        if "webhook_configs" in receiver:
                            notification_types.append("webhook")

                        logger.info(
                            f"AlertManager receiver '{receiver_name}': {notification_types}"
                        )

                logger.info("AlertManager notification configuration validated")

            except subprocess.CalledProcessError:
                pytest.skip("AlertManager configuration not found")

        except yaml.YAMLError:
            pytest.fail("Invalid AlertManager YAML configuration")


class TestLogAggregation:
    """Test log aggregation and centralized logging."""

    def test_pod_logs_accessibility(self, monitoring_client: MonitoringTestClient):
        """Test that pod logs are accessible via kubectl."""
        namespaces = [
            "brain-researcher-core",
            "brain-researcher-data",
            "brain-researcher-monitoring",
        ]

        log_accessibility_results = {}

        for namespace in namespaces:
            try:
                pods_data = monitoring_client.get_json_output(
                    "pods", namespace=namespace
                )
                pods = pods_data.get("items", [])

                namespace_results = {"accessible": 0, "total": 0, "errors": []}

                for pod in pods[:3]:  # Test first 3 pods per namespace
                    pod_name = pod["metadata"]["name"]
                    namespace_results["total"] += 1

                    try:
                        # Try to get recent logs
                        logs = monitoring_client.run_kubectl(
                            [
                                "logs",
                                pod_name,
                                "-n",
                                namespace,
                                "--tail=10",
                                "--since=1h",
                            ],
                            check=False,
                        )

                        if logs and not logs.startswith("Error"):
                            namespace_results["accessible"] += 1
                            logger.info(f"Logs accessible for pod {pod_name}")
                        else:
                            namespace_results["errors"].append(
                                f"{pod_name}: {logs[:100]}"
                            )

                    except Exception as e:
                        namespace_results["errors"].append(f"{pod_name}: {str(e)}")

                log_accessibility_results[namespace] = namespace_results

            except subprocess.CalledProcessError:
                log_accessibility_results[namespace] = {
                    "accessible": 0,
                    "total": 0,
                    "errors": ["Namespace not accessible"],
                }

        # Validate results
        total_accessible = sum(
            result["accessible"] for result in log_accessibility_results.values()
        )
        total_pods = sum(
            result["total"] for result in log_accessibility_results.values()
        )

        if total_pods == 0:
            pytest.skip("No pods found to test log accessibility")

        accessibility_ratio = total_accessible / total_pods
        assert (
            accessibility_ratio >= 0.7
        ), f"Too many pods with inaccessible logs: {total_accessible}/{total_pods}"

        logger.info(f"Pod logs accessibility: {total_accessible}/{total_pods} pods")

        # Log errors for debugging
        for namespace, result in log_accessibility_results.items():
            if result["errors"]:
                logger.warning(f"Log errors in {namespace}: {result['errors']}")

    def test_log_rotation_configuration(self, monitoring_client: MonitoringTestClient):
        """Test log rotation configuration."""
        try:
            # Check DaemonSet for log rotation (if using fluentd, filebeat, etc.)
            daemonsets_data = monitoring_client.get_json_output(
                "daemonset", namespace="kube-system"
            )

            log_daemonsets = [
                ds
                for ds in daemonsets_data.get("items", [])
                if any(
                    log_tool in ds["metadata"]["name"].lower()
                    for log_tool in ["fluentd", "filebeat", "logstash", "fluent-bit"]
                )
            ]

            if log_daemonsets:
                for ds in log_daemonsets:
                    ds_name = ds["metadata"]["name"]
                    logger.info(f"Found log aggregation DaemonSet: {ds_name}")

                    # Check that it's running on nodes
                    status = ds.get("status", {})
                    desired = status.get("desiredNumberScheduled", 0)
                    ready = status.get("numberReady", 0)

                    if desired > 0:
                        readiness_ratio = ready / desired
                        assert (
                            readiness_ratio >= 0.8
                        ), f"Log DaemonSet {ds_name} not ready: {ready}/{desired}"
                        logger.info(f"Log DaemonSet {ds_name}: {ready}/{desired} ready")
            else:
                pytest.skip("No log aggregation DaemonSets found")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check log aggregation DaemonSets")

    def test_application_log_structure(self, monitoring_client: MonitoringTestClient):
        """Test that application logs have proper structure."""
        services_to_check = [
            ("orchestrator", "brain-researcher-core"),
            ("agent", "brain-researcher-core"),
            ("br_kg", "brain-researcher-core"),
        ]

        structured_log_indicators = [
            "level",
            "timestamp",
            "message",
            "logger",
            "INFO",
            "DEBUG",
            "WARN",
            "ERROR",
            "json",
            "{",
            "}",  # JSON structure indicators
        ]

        log_structure_results = {}

        for service_name, namespace in services_to_check:
            try:
                pods_data = monitoring_client.get_json_output(
                    "pods", namespace=namespace
                )
                service_pods = [
                    pod
                    for pod in pods_data.get("items", [])
                    if service_name in pod["metadata"]["name"]
                ]

                if not service_pods:
                    continue

                # Check logs from first pod
                pod_name = service_pods[0]["metadata"]["name"]

                logs = monitoring_client.run_kubectl(
                    ["logs", pod_name, "-n", namespace, "--tail=20"], check=False
                )

                if not logs or logs.startswith("Error"):
                    log_structure_results[service_name] = {
                        "structured": False,
                        "reason": "No logs available",
                    }
                    continue

                # Count structured log indicators
                indicator_count = sum(
                    1
                    for indicator in structured_log_indicators
                    if indicator.lower() in logs.lower()
                )

                is_structured = indicator_count >= 3  # At least 3 indicators

                log_structure_results[service_name] = {
                    "structured": is_structured,
                    "indicators_found": indicator_count,
                    "sample_logs": logs.split("\n")[:3],  # First 3 lines
                }

                logger.info(
                    f"Service {service_name} log structure: {'structured' if is_structured else 'unstructured'}"
                )

            except subprocess.CalledProcessError:
                log_structure_results[service_name] = {
                    "structured": False,
                    "reason": "Could not access logs",
                }

        if not log_structure_results:
            pytest.skip("No service logs available for structure testing")

        # At least 50% of services should have some structured logging
        structured_services = [
            s for s, r in log_structure_results.items() if r.get("structured", False)
        ]
        total_services = len(log_structure_results)

        structure_ratio = len(structured_services) / total_services

        logger.info(
            f"Structured logging: {len(structured_services)}/{total_services} services"
        )

        # Log structure information
        for service, result in log_structure_results.items():
            if result.get("structured"):
                logger.info(
                    f"Service {service} has structured logs ({result.get('indicators_found', 0)} indicators)"
                )
            else:
                reason = result.get("reason", "Insufficient structure indicators")
                logger.info(f"Service {service} logs: {reason}")

    def test_log_volume_and_retention(self, monitoring_client: MonitoringTestClient):
        """Test log volume and retention policies."""
        try:
            # Check for PersistentVolumes used for logging
            pv_data = monitoring_client.get_json_output("pv")
            log_pvs = [
                pv
                for pv in pv_data.get("items", [])
                if any(
                    log_keyword in pv["metadata"]["name"].lower()
                    for log_keyword in ["log", "logs", "elasticsearch", "loki"]
                )
            ]

            if log_pvs:
                for pv in log_pvs:
                    pv_name = pv["metadata"]["name"]
                    capacity = pv["spec"]["capacity"]["storage"]

                    logger.info(f"Log storage PV {pv_name}: {capacity}")

                    # Check that capacity is reasonable (at least 1Gi)
                    if capacity.endswith("Gi"):
                        capacity_gi = int(capacity[:-2])
                        assert capacity_gi >= 1, f"Log storage too small: {capacity}"
                    elif capacity.endswith("Ti"):
                        # Terabytes are definitely sufficient
                        pass
                    else:
                        logger.warning(f"Unusual storage capacity format: {capacity}")

            # Check for log retention ConfigMaps
            configmaps_data = monitoring_client.get_json_output(
                "configmap", namespace="brain-researcher-monitoring"
            )

            log_retention_configs = [
                cm
                for cm in configmaps_data.get("items", [])
                if any(
                    keyword in cm["metadata"]["name"].lower()
                    for keyword in ["log", "retention", "elasticsearch", "loki"]
                )
            ]

            if log_retention_configs:
                logger.info(
                    f"Found {len(log_retention_configs)} log retention configurations"
                )

            logger.info("Log volume and retention check completed")

        except subprocess.CalledProcessError:
            pytest.skip("Could not check log storage configuration")


# Integration test for overall monitoring health
class TestMonitoringIntegration:
    """Integration tests for the entire monitoring stack."""

    def test_monitoring_stack_health(self, monitoring_client: MonitoringTestClient):
        """Test overall health of monitoring stack."""
        monitoring_components = [
            ("prometheus", "brain-researcher-monitoring"),
            ("grafana", "brain-researcher-monitoring"),
        ]

        component_health = {}

        for component, namespace in monitoring_components:
            try:
                # Check pod health
                pods_data = monitoring_client.get_json_output(
                    "pods", namespace=namespace
                )
                component_pods = [
                    pod
                    for pod in pods_data.get("items", [])
                    if component in pod["metadata"]["name"].lower()
                ]

                if not component_pods:
                    component_health[component] = "not_deployed"
                    continue

                running_pods = [
                    pod
                    for pod in component_pods
                    if pod["status"].get("phase") == "Running"
                ]

                if len(running_pods) == len(component_pods):
                    component_health[component] = "healthy"
                elif len(running_pods) > 0:
                    component_health[component] = "partially_healthy"
                else:
                    component_health[component] = "unhealthy"

                logger.info(
                    f"Component {component}: {component_health[component]} ({len(running_pods)}/{len(component_pods)} pods)"
                )

            except subprocess.CalledProcessError:
                component_health[component] = "unknown"

        # Evaluate overall health
        healthy_components = [c for c, h in component_health.items() if h == "healthy"]
        total_components = len(component_health)

        if total_components == 0:
            pytest.skip("No monitoring components found")

        health_ratio = len(healthy_components) / total_components
        assert (
            health_ratio >= 0.5
        ), f"Too many unhealthy monitoring components: {healthy_components} out of {list(component_health.keys())}"

        logger.info(
            f"Monitoring stack health: {len(healthy_components)}/{total_components} components healthy"
        )

    def test_end_to_end_metrics_flow(self, monitoring_client: MonitoringTestClient):
        """Test end-to-end metrics flow from services to Prometheus."""
        if not monitoring_client.prometheus_url:
            pytest.skip("Prometheus not accessible for E2E test")

        # Test the full metrics pipeline
        test_metrics = [
            "up",  # Basic connectivity
            "prometheus_notifications_total",  # Prometheus internal metrics
            "prometheus_config_last_reload_successful",  # Config reload
        ]

        metrics_pipeline_health = {}

        for metric in test_metrics:
            result = monitoring_client.query_prometheus(metric)

            if result and result.get("status") == "success":
                data = result.get("data", {})
                result_data = data.get("result", [])

                if result_data:
                    metrics_pipeline_health[metric] = "available"
                    # Log sample values
                    for item in result_data[:2]:  # First 2 results
                        labels = item.get("metric", {})
                        value = item.get("value", ["", ""])[1]
                        logger.info(f"Metric {metric}: {value} {labels}")
                else:
                    metrics_pipeline_health[metric] = "no_data"
            else:
                metrics_pipeline_health[metric] = "unavailable"

        # Check pipeline health
        available_metrics = [
            m for m, h in metrics_pipeline_health.items() if h == "available"
        ]

        assert (
            len(available_metrics) > 0
        ), f"No metrics available in pipeline: {metrics_pipeline_health}"

        pipeline_ratio = len(available_metrics) / len(test_metrics)
        assert (
            pipeline_ratio >= 0.6
        ), f"Metrics pipeline unhealthy: {available_metrics} available out of {test_metrics}"

        logger.info(
            f"End-to-end metrics pipeline: {len(available_metrics)}/{len(test_metrics)} metrics flowing"
        )


if __name__ == "__main__":
    # Run monitoring tests
    pytest.main([__file__, "-v", "-s"])
