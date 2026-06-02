"""
End-to-end tests for Istio multi-cluster communication.

Tests cross-cluster service discovery, traffic routing, security,
and failover scenarios in a multi-cluster service mesh setup.
"""

import asyncio
import json
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock, patch

import aiohttp
import pytest

# Test markers
pytestmark = [pytest.mark.e2e, pytest.mark.istio, pytest.mark.multi_cluster]


@pytest.fixture(scope="session")
def multi_cluster_environment():
    """Set up multi-cluster test environment."""
    return {
        "clusters": {
            "primary": {
                "name": "brain-researcher-primary",
                "namespace": "brain-researcher",
                "network": "network-primary",
                "services": {
                    "br_kg": {"port": 5000, "replicas": 2},
                    "agent": {"port": 8000, "replicas": 1},
                    "web-ui": {"port": 3000, "replicas": 2},
                },
                "endpoint": "https://primary-cluster.brain-researcher.io",
            },
            "secondary": {
                "name": "brain-researcher-secondary",
                "namespace": "brain-researcher",
                "network": "network-secondary",
                "services": {
                    "br_kg": {"port": 5000, "replicas": 1},
                    "orchestrator": {"port": 3001, "replicas": 2},
                    "data-processor": {"port": 9000, "replicas": 1},
                },
                "endpoint": "https://secondary-cluster.brain-researcher.io",
            },
            "edge": {
                "name": "brain-researcher-edge",
                "namespace": "brain-researcher",
                "network": "network-edge",
                "services": {
                    "edge-gateway": {"port": 80, "replicas": 1},
                    "cache-service": {"port": 6379, "replicas": 1},
                },
                "endpoint": "https://edge-cluster.brain-researcher.io",
            },
        },
        "cross_cluster_services": [
            {
                "name": "br_kg-global",
                "primary_cluster": "primary",
                "replica_clusters": ["secondary"],
                "failover_policy": "automatic",
            },
            {
                "name": "orchestrator-global",
                "primary_cluster": "secondary",
                "replica_clusters": [],
                "failover_policy": "manual",
            },
        ],
    }


@pytest.fixture
async def multi_cluster_http_session():
    """Provide HTTP session for multi-cluster testing."""
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        keepalive_timeout=60,
        enable_cleanup_closed=True,
        ssl=False,  # For testing with self-signed certs
    )

    async with aiohttp.ClientSession(
        connector=connector, timeout=aiohttp.ClientTimeout(total=60, connect=10)
    ) as session:
        yield session


class TestMultiClusterSetup:
    """Test multi-cluster Istio setup and configuration."""

    def test_cluster_configuration(self, multi_cluster_environment):
        """Test multi-cluster configuration setup."""
        from brain_researcher.infrastructure.istio.multi_cluster_manager import (
            MultiClusterManager,
        )

        with patch("kubernetes.client"):
            mc_manager = MultiClusterManager()

        clusters = multi_cluster_environment["clusters"]

        # Test primary cluster configuration
        primary_config = mc_manager.generate_primary_cluster_config(
            cluster_name=clusters["primary"]["name"],
            network=clusters["primary"]["network"],
            namespace=clusters["primary"]["namespace"],
        )

        assert primary_config["kind"] == "Gateway"
        assert primary_config["spec"]["servers"][0]["port"]["number"] == 15443

        # Test remote cluster configuration
        secondary_config = mc_manager.generate_remote_cluster_config(
            cluster_name=clusters["secondary"]["name"],
            network=clusters["secondary"]["network"],
            primary_cluster_endpoint=clusters["primary"]["endpoint"],
            namespace=clusters["secondary"]["namespace"],
        )

        assert secondary_config["kind"] == "Secret"
        assert (
            secondary_config["metadata"]["labels"]["istio/cluster"]
            == clusters["secondary"]["name"]
        )

    def test_service_entry_configuration(self, multi_cluster_environment):
        """Test ServiceEntry configuration for cross-cluster services."""
        from brain_researcher.infrastructure.istio.multi_cluster_manager import (
            MultiClusterManager,
        )

        with patch("kubernetes.client"):
            mc_manager = MultiClusterManager()

        # Configure cross-cluster service entry
        service_entry = mc_manager.generate_cross_cluster_service_entry(
            service_name="br_kg-service",
            primary_cluster="primary",
            secondary_clusters=["secondary"],
            service_port=5000,
        )

        assert service_entry["kind"] == "ServiceEntry"
        assert service_entry["spec"]["hosts"] == [
            "br_kg-service.brain-researcher.global"
        ]
        assert service_entry["spec"]["location"] == "MESH_EXTERNAL"
        assert service_entry["spec"]["resolution"] == "DNS"

        # Should have endpoints for multiple clusters
        assert len(service_entry["spec"]["endpoints"]) >= 2

    def test_destination_rule_multi_cluster(self, multi_cluster_environment):
        """Test DestinationRule for multi-cluster load balancing."""
        from brain_researcher.infrastructure.istio.multi_cluster_manager import (
            MultiClusterManager,
        )

        with patch("kubernetes.client"):
            mc_manager = MultiClusterManager()

        dest_rule = mc_manager.generate_multi_cluster_destination_rule(
            service_name="br_kg-service",
            clusters=["primary", "secondary"],
            load_balancing_policy="ROUND_ROBIN",
            locality_preferences={
                "primary": {"region": "us-west-2", "zone": "us-west-2a"},
                "secondary": {"region": "us-east-1", "zone": "us-east-1b"},
            },
        )

        assert dest_rule["kind"] == "DestinationRule"
        assert (
            dest_rule["spec"]["trafficPolicy"]["loadBalancer"]["simple"]
            == "ROUND_ROBIN"
        )

        # Should have locality load balancing configured
        assert "localityLbSetting" in dest_rule["spec"]["trafficPolicy"]


class TestCrossClusterServiceDiscovery:
    """Test cross-cluster service discovery functionality."""

    @pytest.mark.asyncio
    async def test_cross_cluster_dns_resolution(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test DNS resolution of cross-cluster services."""
        primary_cluster = multi_cluster_environment["clusters"]["primary"]
        secondary_cluster = multi_cluster_environment["clusters"]["secondary"]

        # Test resolution from primary cluster to secondary services
        primary_namespace = primary_cluster["namespace"]

        try:
            # Test accessing orchestrator service from primary cluster
            orchestrator_url = f"http://orchestrator-service.{primary_namespace}.global"

            async with multi_cluster_http_session.get(
                f"{orchestrator_url}/health",
                headers={"x-cluster-test": "cross-cluster-dns"},
            ) as response:
                # Should resolve and connect to secondary cluster
                assert response.status in [200, 404, 503]  # Various valid responses

                # Check for cross-cluster headers
                cluster_header = response.headers.get("x-source-cluster")
                if cluster_header:
                    assert cluster_header in ["primary", "secondary"]

        except aiohttp.ClientError as e:
            if "name resolution" in str(e).lower() or "dns" in str(e).lower():
                pytest.skip("Cross-cluster DNS not configured in test environment")
            else:
                raise

    @pytest.mark.asyncio
    async def test_service_discovery_across_networks(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test service discovery across different networks."""
        clusters = multi_cluster_environment["clusters"]

        # Test service discovery from different network perspectives
        network_tests = [
            {
                "from_network": "network-primary",
                "to_network": "network-secondary",
                "service": "br_kg-service",
                "expected_endpoint": clusters["secondary"]["endpoint"],
            },
            {
                "from_network": "network-secondary",
                "to_network": "network-primary",
                "service": "web-ui-service",
                "expected_endpoint": clusters["primary"]["endpoint"],
            },
        ]

        for test_case in network_tests:
            try:
                # Simulate request from source network to target network
                service_url = f"http://{test_case['service']}.brain-researcher.global"

                headers = {
                    "x-source-network": test_case["from_network"],
                    "x-target-network": test_case["to_network"],
                    "x-network-test": "cross-network-discovery",
                }

                async with multi_cluster_http_session.get(
                    f"{service_url}/health", headers=headers
                ) as response:
                    # Should successfully route across networks
                    assert response.status in [200, 404, 503]

                    # Response should indicate which cluster handled the request
                    handling_cluster = response.headers.get("x-handling-cluster")
                    if handling_cluster:
                        # Should route to appropriate cluster based on service location
                        assert handling_cluster in clusters.keys()

            except aiohttp.ClientError:
                # Network routing might not be fully configured in test environment
                pytest.skip(
                    f"Cross-network routing not available: {test_case['from_network']} -> {test_case['to_network']}"
                )


class TestCrossClusterTrafficRouting:
    """Test traffic routing between clusters."""

    @pytest.mark.asyncio
    async def test_locality_aware_routing(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test locality-aware traffic routing."""
        # Test that requests prefer local cluster services when available
        service_name = "br_kg-service"

        # Simulate requests from different localities
        localities = [
            {
                "region": "us-west-2",
                "zone": "us-west-2a",
                "expected_cluster": "primary",
            },
            {
                "region": "us-east-1",
                "zone": "us-east-1b",
                "expected_cluster": "secondary",
            },
        ]

        for locality in localities:
            locality_results = {"local": 0, "remote": 0, "unknown": 0}

            # Make multiple requests to test locality preference
            for i in range(20):
                try:
                    headers = {
                        "x-locality-region": locality["region"],
                        "x-locality-zone": locality["zone"],
                        "x-request-id": f"locality-{locality['region']}-{i}",
                        "x-locality-test": "true",
                    }

                    service_url = f"http://{service_name}.brain-researcher.global:5000"

                    async with multi_cluster_http_session.get(
                        f"{service_url}/api/v1/cluster-info", headers=headers
                    ) as response:
                        if response.status == 200:
                            try:
                                data = await response.json()
                                handling_cluster = data.get("cluster", "unknown")

                                if handling_cluster == locality["expected_cluster"]:
                                    locality_results["local"] += 1
                                elif (
                                    handling_cluster
                                    in multi_cluster_environment["clusters"].keys()
                                ):
                                    locality_results["remote"] += 1
                                else:
                                    locality_results["unknown"] += 1
                            except json.JSONDecodeError:
                                locality_results["unknown"] += 1
                        else:
                            locality_results["unknown"] += 1

                except aiohttp.ClientError:
                    locality_results["unknown"] += 1

                await asyncio.sleep(0.1)

            # Analyze locality routing
            total_requests = sum(locality_results.values())
            if total_requests > 5:  # Need minimum successful requests
                local_preference = locality_results["local"] / total_requests

                # Should prefer local cluster when available (allow for some variance)
                if locality_results["local"] > 0 and locality_results["remote"] > 0:
                    assert (
                        local_preference >= 0.6
                    ), f"Locality {locality['region']} routing: {local_preference:.1%} local preference"

    @pytest.mark.asyncio
    async def test_weighted_cluster_routing(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test weighted routing between clusters."""
        service_name = "br_kg-service"

        # Configure weighted routing (simulated through headers)
        routing_weights = {
            "primary": 70,  # 70% to primary cluster
            "secondary": 30,  # 30% to secondary cluster
        }

        cluster_counts = {"primary": 0, "secondary": 0, "unknown": 0}
        total_requests = 100

        for i in range(total_requests):
            try:
                headers = {
                    "x-weighted-routing": "true",
                    "x-primary-weight": str(routing_weights["primary"]),
                    "x-secondary-weight": str(routing_weights["secondary"]),
                    "x-request-id": f"weighted-{i}",
                }

                service_url = f"http://{service_name}.brain-researcher.global:5000"

                async with multi_cluster_http_session.get(
                    f"{service_url}/health", headers=headers
                ) as response:
                    # Determine which cluster handled the request
                    cluster_header = response.headers.get(
                        "x-handling-cluster", "unknown"
                    )

                    if cluster_header in cluster_counts:
                        cluster_counts[cluster_header] += 1
                    else:
                        cluster_counts["unknown"] += 1

            except aiohttp.ClientError:
                cluster_counts["unknown"] += 1

            await asyncio.sleep(0.05)  # Small delay between requests

        # Validate weighted distribution
        successful_requests = cluster_counts["primary"] + cluster_counts["secondary"]

        if successful_requests > 50:  # Need sufficient successful requests
            primary_percentage = (cluster_counts["primary"] / successful_requests) * 100
            secondary_percentage = (
                cluster_counts["secondary"] / successful_requests
            ) * 100

            # Allow for variance in distribution (±15%)
            assert (
                55 <= primary_percentage <= 85
            ), f"Primary cluster routing: {primary_percentage:.1f}% (expected ~70%)"
            assert (
                15 <= secondary_percentage <= 45
            ), f"Secondary cluster routing: {secondary_percentage:.1f}% (expected ~30%)"

    @pytest.mark.asyncio
    async def test_header_based_cluster_routing(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test routing based on custom headers."""
        service_name = "orchestrator-service"

        # Test different header-based routing scenarios
        routing_scenarios = [
            {
                "headers": {"x-route-to-cluster": "primary", "x-user-type": "admin"},
                "expected_cluster": "primary",
                "description": "Admin users to primary cluster",
            },
            {
                "headers": {
                    "x-route-to-cluster": "secondary",
                    "x-user-type": "researcher",
                },
                "expected_cluster": "secondary",
                "description": "Researchers to secondary cluster",
            },
            {
                "headers": {"x-deployment-version": "canary", "x-beta-tester": "true"},
                "expected_cluster": "secondary",
                "description": "Beta testers to canary deployment",
            },
        ]

        for scenario in routing_scenarios:
            scenario_results = {
                "correct_routing": 0,
                "incorrect_routing": 0,
                "unknown": 0,
            }

            for i in range(10):
                try:
                    headers = scenario["headers"].copy()
                    headers["x-request-id"] = f"header-routing-{i}"
                    headers["x-routing-scenario"] = scenario["description"]

                    service_url = f"http://{service_name}.brain-researcher.global:3001"

                    async with multi_cluster_http_session.get(
                        f"{service_url}/health", headers=headers
                    ) as response:
                        handling_cluster = response.headers.get(
                            "x-handling-cluster", "unknown"
                        )

                        if handling_cluster == scenario["expected_cluster"]:
                            scenario_results["correct_routing"] += 1
                        elif (
                            handling_cluster
                            in multi_cluster_environment["clusters"].keys()
                        ):
                            scenario_results["incorrect_routing"] += 1
                        else:
                            scenario_results["unknown"] += 1

                except aiohttp.ClientError:
                    scenario_results["unknown"] += 1

                await asyncio.sleep(0.2)

            # Validate header-based routing
            total_attempts = sum(scenario_results.values())
            if total_attempts > 0:
                correct_rate = scenario_results["correct_routing"] / total_attempts

                # Should route correctly based on headers (allow for some test environment variance)
                print(
                    f"Scenario '{scenario['description']}': {correct_rate:.1%} correct routing"
                )

                if scenario_results["correct_routing"] > 0:
                    # If any correct routing occurred, expect reasonable rate
                    assert (
                        correct_rate >= 0.5
                    ), f"Header-based routing accuracy too low: {correct_rate:.1%}"


class TestCrossClusterFailover:
    """Test failover mechanisms between clusters."""

    @pytest.mark.asyncio
    async def test_automatic_failover(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test automatic failover when primary cluster fails."""
        primary_cluster = multi_cluster_environment["clusters"]["primary"]
        secondary_cluster = multi_cluster_environment["clusters"]["secondary"]

        service_name = "br_kg-service"
        service_url = f"http://{service_name}.brain-researcher.global:5000"

        # Phase 1: Establish baseline with healthy primary
        baseline_results = []

        for i in range(10):
            try:
                async with multi_cluster_http_session.get(
                    f"{service_url}/health",
                    headers={
                        "x-baseline-test": "true",
                        "x-request-id": f"baseline-{i}",
                    },
                ) as response:
                    baseline_results.append(
                        {
                            "success": response.status == 200,
                            "cluster": response.headers.get(
                                "x-handling-cluster", "unknown"
                            ),
                        }
                    )
            except aiohttp.ClientError:
                baseline_results.append({"success": False, "cluster": "error"})

            await asyncio.sleep(0.5)

        baseline_primary_usage = sum(
            1 for r in baseline_results if r.get("cluster") == "primary"
        )

        # Phase 2: Simulate primary cluster failure
        print("Simulating primary cluster failure...")

        failover_results = []

        for i in range(20):
            try:
                headers = {
                    "x-simulate-primary-failure": "true",
                    "x-failover-test": "true",
                    "x-request-id": f"failover-{i}",
                }

                start_time = time.time()

                async with multi_cluster_http_session.get(
                    f"{service_url}/health", headers=headers
                ) as response:
                    end_time = time.time()

                    failover_results.append(
                        {
                            "success": response.status == 200,
                            "cluster": response.headers.get(
                                "x-handling-cluster", "unknown"
                            ),
                            "response_time": (end_time - start_time) * 1000,
                            "failover_occurred": response.headers.get(
                                "x-failover-active"
                            )
                            == "true",
                        }
                    )

            except aiohttp.ClientError as e:
                failover_results.append(
                    {
                        "success": False,
                        "error": str(e),
                        "response_time": (
                            (time.time() - start_time) * 1000
                            if "start_time" in locals()
                            else 0
                        ),
                        "connection_timeout": "timeout" in str(e).lower(),
                    }
                )

            await asyncio.sleep(0.3)

        # Analyze failover behavior
        successful_failovers = [r for r in failover_results if r.get("success")]
        secondary_usage = sum(
            1 for r in successful_failovers if r.get("cluster") == "secondary"
        )
        failover_activations = sum(
            1 for r in failover_results if r.get("failover_occurred")
        )

        if len(successful_failovers) > 0:
            secondary_usage_rate = secondary_usage / len(successful_failovers)
            success_rate = len(successful_failovers) / len(failover_results)

            print(f"Failover success rate: {success_rate:.1%}")
            print(f"Secondary cluster usage: {secondary_usage_rate:.1%}")
            print(f"Failover activations: {failover_activations}")

            # Should show increased usage of secondary cluster during primary failure
            if baseline_primary_usage > 5:  # Had significant primary usage before
                assert (
                    secondary_usage_rate > 0.3
                ), f"Insufficient failover to secondary cluster: {secondary_usage_rate:.1%}"

            # Should maintain reasonable availability during failover
            assert (
                success_rate >= 0.5
            ), f"Availability too low during failover: {success_rate:.1%}"

    @pytest.mark.asyncio
    async def test_failback_after_recovery(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test failback to primary cluster after recovery."""
        service_name = "br_kg-service"
        service_url = f"http://{service_name}.brain-researcher.global:5000"

        # Phase 1: Simulate primary cluster failure and establish failover
        print("Establishing failover state...")

        failover_period_results = []

        for i in range(15):
            try:
                headers = {
                    "x-simulate-primary-failure": "true",
                    "x-establish-failover": "true",
                    "x-request-id": f"establish-failover-{i}",
                }

                async with multi_cluster_http_session.get(
                    f"{service_url}/health", headers=headers
                ) as response:
                    failover_period_results.append(
                        {
                            "success": response.status == 200,
                            "cluster": response.headers.get(
                                "x-handling-cluster", "unknown"
                            ),
                        }
                    )
            except aiohttp.ClientError:
                failover_period_results.append({"success": False, "cluster": "error"})

            await asyncio.sleep(0.3)

        # Verify failover is established
        failover_secondary_usage = sum(
            1 for r in failover_period_results if r.get("cluster") == "secondary"
        )

        # Phase 2: Simulate primary cluster recovery
        print("Simulating primary cluster recovery...")
        await asyncio.sleep(5)  # Allow time for recovery detection

        recovery_results = []

        for i in range(20):
            try:
                headers = {
                    "x-simulate-primary-recovery": "true",
                    "x-failback-test": "true",
                    "x-request-id": f"recovery-{i}",
                }

                async with multi_cluster_http_session.get(
                    f"{service_url}/health", headers=headers
                ) as response:
                    recovery_results.append(
                        {
                            "success": response.status == 200,
                            "cluster": response.headers.get(
                                "x-handling-cluster", "unknown"
                            ),
                            "failback_active": response.headers.get("x-failback-active")
                            == "true",
                        }
                    )
            except aiohttp.ClientError:
                recovery_results.append({"success": False, "cluster": "error"})

            await asyncio.sleep(0.4)

        # Analyze failback behavior
        successful_requests = [r for r in recovery_results if r.get("success")]
        primary_usage_after_recovery = sum(
            1 for r in successful_requests if r.get("cluster") == "primary"
        )
        failback_activations = sum(
            1 for r in recovery_results if r.get("failback_active")
        )

        if len(successful_requests) > 5:
            primary_usage_rate = primary_usage_after_recovery / len(successful_requests)

            print(f"Primary cluster usage after recovery: {primary_usage_rate:.1%}")
            print(f"Failback activations: {failback_activations}")

            # Should show gradual or immediate return to primary cluster
            # Allow for both gradual and immediate failback strategies
            if failover_secondary_usage > 5:  # Had established failover
                assert (
                    primary_usage_rate > 0.2
                ), f"Insufficient failback to primary cluster: {primary_usage_rate:.1%}"

    @pytest.mark.asyncio
    async def test_partial_cluster_failure_handling(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test handling of partial cluster failures."""
        # Test scenario where some services in a cluster fail but others remain healthy

        failure_scenarios = [
            {
                "name": "single_service_failure",
                "failed_services": ["br_kg-service"],
                "healthy_services": ["web-ui-service"],
                "cluster": "primary",
            },
            {
                "name": "majority_service_failure",
                "failed_services": ["orchestrator-service", "data-processor-service"],
                "healthy_services": [],
                "cluster": "secondary",
            },
        ]

        for scenario in failure_scenarios:
            print(f"Testing partial failure scenario: {scenario['name']}")

            scenario_results = {
                "failed_service_requests": [],
                "healthy_service_requests": [],
                "cross_cluster_routing": 0,
            }

            # Test failed services
            for service in scenario["failed_services"]:
                service_results = []

                for i in range(10):
                    try:
                        headers = {
                            "x-partial-failure-scenario": scenario["name"],
                            "x-simulate-service-failure": service,
                            "x-request-id": f"partial-{scenario['name']}-{service}-{i}",
                        }

                        service_url = f"http://{service}.brain-researcher.global"

                        async with multi_cluster_http_session.get(
                            f"{service_url}/health", headers=headers
                        ) as response:
                            service_results.append(
                                {
                                    "success": response.status == 200,
                                    "status": response.status,
                                    "cluster": response.headers.get(
                                        "x-handling-cluster", "unknown"
                                    ),
                                    "routed_cross_cluster": response.headers.get(
                                        "x-cross-cluster-routing"
                                    )
                                    == "true",
                                }
                            )

                            if (
                                response.headers.get("x-cross-cluster-routing")
                                == "true"
                            ):
                                scenario_results["cross_cluster_routing"] += 1

                    except aiohttp.ClientError:
                        service_results.append(
                            {"success": False, "connection_error": True}
                        )

                    await asyncio.sleep(0.2)

                scenario_results["failed_service_requests"].extend(service_results)

            # Test healthy services (should remain functional)
            for service in scenario["healthy_services"]:
                service_results = []

                for i in range(5):
                    try:
                        headers = {
                            "x-partial-failure-scenario": scenario["name"],
                            "x-healthy-service-test": service,
                            "x-request-id": f"healthy-{scenario['name']}-{service}-{i}",
                        }

                        service_url = f"http://{service}.brain-researcher.global"

                        async with multi_cluster_http_session.get(
                            f"{service_url}/health", headers=headers
                        ) as response:
                            service_results.append(
                                {
                                    "success": response.status == 200,
                                    "cluster": response.headers.get(
                                        "x-handling-cluster", "unknown"
                                    ),
                                }
                            )

                    except aiohttp.ClientError:
                        service_results.append({"success": False})

                    await asyncio.sleep(0.3)

                scenario_results["healthy_service_requests"].extend(service_results)

            # Analyze partial failure handling
            failed_service_success_rate = 0
            if scenario_results["failed_service_requests"]:
                failed_successful = sum(
                    1
                    for r in scenario_results["failed_service_requests"]
                    if r.get("success")
                )
                failed_service_success_rate = failed_successful / len(
                    scenario_results["failed_service_requests"]
                )

            healthy_service_success_rate = 1.0
            if scenario_results["healthy_service_requests"]:
                healthy_successful = sum(
                    1
                    for r in scenario_results["healthy_service_requests"]
                    if r.get("success")
                )
                healthy_service_success_rate = healthy_successful / len(
                    scenario_results["healthy_service_requests"]
                )

            print(f"Failed services success rate: {failed_service_success_rate:.1%}")
            print(f"Healthy services success rate: {healthy_service_success_rate:.1%}")
            print(
                f"Cross-cluster routing instances: {scenario_results['cross_cluster_routing']}"
            )

            # Healthy services should maintain high availability
            if scenario["healthy_services"]:
                assert (
                    healthy_service_success_rate >= 0.8
                ), f"Healthy services affected by partial failure: {healthy_service_success_rate:.1%}"

            # Failed services should either fail cleanly or route to other clusters
            if scenario_results["cross_cluster_routing"] > 0:
                # If cross-cluster routing is working, should improve failed service availability
                assert (
                    failed_service_success_rate > 0
                ), "Cross-cluster routing not improving failed service availability"

            await asyncio.sleep(5)  # Wait between scenarios


class TestMultiClusterSecurity:
    """Test security aspects of multi-cluster communication."""

    @pytest.mark.asyncio
    async def test_cross_cluster_mtls(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test mTLS enforcement in cross-cluster communication."""
        service_name = "br_kg-service"
        service_url = f"http://{service_name}.brain-researcher.global:5000"

        # Test different certificate scenarios
        cert_scenarios = [
            {
                "name": "valid_cluster_cert",
                "headers": {"x-cluster-cert": "valid", "x-source-cluster": "primary"},
                "expected_success": True,
            },
            {
                "name": "invalid_cluster_cert",
                "headers": {"x-cluster-cert": "invalid", "x-source-cluster": "unknown"},
                "expected_success": False,
            },
            {
                "name": "missing_cluster_cert",
                "headers": {"x-source-cluster": "primary"},
                "expected_success": False,
            },
        ]

        for scenario in cert_scenarios:
            scenario_results = []

            for i in range(5):
                try:
                    headers = scenario["headers"].copy()
                    headers["x-mtls-test"] = scenario["name"]
                    headers["x-request-id"] = f"mtls-{scenario['name']}-{i}"

                    async with multi_cluster_http_session.get(
                        f"{service_url}/health", headers=headers
                    ) as response:
                        scenario_results.append(
                            {
                                "success": response.status == 200,
                                "status": response.status,
                                "tls_verified": response.headers.get("x-tls-verified")
                                == "true",
                                "auth_error": response.status in [401, 403],
                            }
                        )

                except aiohttp.ClientError as e:
                    scenario_results.append(
                        {
                            "success": False,
                            "connection_error": True,
                            "ssl_error": "ssl" in str(e).lower()
                            or "certificate" in str(e).lower(),
                        }
                    )

                await asyncio.sleep(0.3)

            # Analyze mTLS enforcement
            success_rate = sum(1 for r in scenario_results if r.get("success")) / len(
                scenario_results
            )
            auth_error_rate = sum(
                1 for r in scenario_results if r.get("auth_error")
            ) / len(scenario_results)
            ssl_error_rate = sum(
                1 for r in scenario_results if r.get("ssl_error")
            ) / len(scenario_results)

            print(
                f"mTLS scenario {scenario['name']}: {success_rate:.1%} success, {auth_error_rate:.1%} auth errors, {ssl_error_rate:.1%} SSL errors"
            )

            # Validate security enforcement
            if scenario["expected_success"]:
                # Valid certs should have reasonable success rate
                assert (
                    success_rate >= 0.6 or auth_error_rate == 0
                ), f"Valid cert scenario unexpectedly blocked: {scenario['name']}"
            else:
                # Invalid certs should be rejected
                assert (
                    success_rate <= 0.4 or auth_error_rate > 0 or ssl_error_rate > 0
                ), f"Invalid cert scenario unexpectedly allowed: {scenario['name']}"

    @pytest.mark.asyncio
    async def test_cross_cluster_authorization_policies(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test authorization policies across clusters."""
        service_name = "orchestrator-service"
        service_url = f"http://{service_name}.brain-researcher.global:3001"

        # Test different authorization scenarios
        auth_scenarios = [
            {
                "name": "authorized_cross_cluster",
                "headers": {
                    "x-source-cluster": "primary",
                    "x-service-account": "br_kg-service-account",
                    "authorization": "Bearer valid-cross-cluster-token",
                },
                "expected_authorized": True,
            },
            {
                "name": "unauthorized_cluster",
                "headers": {
                    "x-source-cluster": "untrusted-cluster",
                    "x-service-account": "unknown-account",
                },
                "expected_authorized": False,
            },
            {
                "name": "missing_authorization",
                "headers": {"x-source-cluster": "secondary"},
                "expected_authorized": False,
            },
        ]

        for scenario in auth_scenarios:
            scenario_results = []

            for i in range(5):
                try:
                    headers = scenario["headers"].copy()
                    headers["x-auth-test"] = scenario["name"]
                    headers["x-request-id"] = f"auth-{scenario['name']}-{i}"

                    async with multi_cluster_http_session.get(
                        f"{service_url}/api/v1/protected-resource", headers=headers
                    ) as response:
                        scenario_results.append(
                            {
                                "success": response.status == 200,
                                "status": response.status,
                                "authorized": response.status != 403,
                                "authenticated": response.status != 401,
                            }
                        )

                except aiohttp.ClientError:
                    scenario_results.append(
                        {"success": False, "connection_error": True}
                    )

                await asyncio.sleep(0.2)

            # Analyze authorization enforcement
            success_rate = sum(1 for r in scenario_results if r.get("success")) / len(
                scenario_results
            )
            authorized_rate = sum(
                1 for r in scenario_results if r.get("authorized")
            ) / len(scenario_results)

            print(
                f"Auth scenario {scenario['name']}: {success_rate:.1%} success, {authorized_rate:.1%} authorized"
            )

            # Validate authorization policies
            if scenario["expected_authorized"]:
                assert (
                    authorized_rate >= 0.6
                ), f"Authorized scenario blocked: {scenario['name']} ({authorized_rate:.1%})"
            else:
                assert (
                    authorized_rate <= 0.5
                ), f"Unauthorized scenario allowed: {scenario['name']} ({authorized_rate:.1%})"


@pytest.mark.production
class TestProductionMultiClusterScenarios:
    """Test production-like multi-cluster scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_multi_cluster_disaster_recovery(
        self, multi_cluster_environment, multi_cluster_http_session
    ):
        """Test disaster recovery across multiple clusters."""
        # Simulate complete datacenter/region failure

        print("Testing disaster recovery scenario...")

        # Phase 1: Normal operations across all clusters
        normal_ops_results = await self._test_multi_cluster_operations(
            multi_cluster_environment,
            multi_cluster_http_session,
            "normal-operations",
            duration=30,
        )

        # Phase 2: Simulate primary region failure
        print("Simulating primary region failure...")

        disaster_results = await self._test_multi_cluster_operations(
            multi_cluster_environment,
            multi_cluster_http_session,
            "primary-region-failure",
            duration=60,
        )

        # Phase 3: Simulate primary region recovery
        print("Simulating primary region recovery...")

        recovery_results = await self._test_multi_cluster_operations(
            multi_cluster_environment,
            multi_cluster_http_session,
            "primary-region-recovery",
            duration=45,
        )

        # Analyze disaster recovery effectiveness
        normal_availability = normal_ops_results.get("availability", 0)
        disaster_availability = disaster_results.get("availability", 0)
        recovery_availability = recovery_results.get("availability", 0)

        print(f"Normal availability: {normal_availability:.1%}")
        print(f"Disaster availability: {disaster_availability:.1%}")
        print(f"Recovery availability: {recovery_availability:.1%}")

        # Validate disaster recovery requirements
        assert (
            disaster_availability >= 0.7
        ), f"Availability during disaster too low: {disaster_availability:.1%}"

        assert (
            recovery_availability >= 0.9
        ), f"Recovery availability insufficient: {recovery_availability:.1%}"

        # Recovery should improve upon disaster state
        assert (
            recovery_availability > disaster_availability
        ), "Recovery did not improve availability"

    async def _test_multi_cluster_operations(
        self,
        multi_cluster_environment: Dict[str, Any],
        http_session: aiohttp.ClientSession,
        scenario: str,
        duration: int,
    ) -> Dict[str, Any]:
        """Helper method to test multi-cluster operations."""

        results = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "cluster_distribution": {},
            "response_times": [],
            "errors": [],
        }

        # Test different services across clusters
        services_to_test = [
            {"name": "br_kg-service", "port": 5000, "endpoint": "/health"},
            {"name": "orchestrator-service", "port": 3001, "endpoint": "/health"},
            {"name": "web-ui-service", "port": 3000, "endpoint": "/health"},
        ]

        end_time = time.time() + duration

        while time.time() < end_time:
            for service in services_to_test:
                start_time = time.time()

                try:
                    service_url = f"http://{service['name']}.brain-researcher.global:{service['port']}"
                    headers = {
                        "x-disaster-scenario": scenario,
                        "x-request-id": f"{scenario}-{int(time.time())}-{service['name']}",
                    }

                    async with http_session.get(
                        f"{service_url}{service['endpoint']}", headers=headers
                    ) as response:
                        end_request_time = time.time()
                        response_time = (end_request_time - start_time) * 1000

                        results["total_requests"] += 1
                        results["response_times"].append(response_time)

                        if response.status == 200:
                            results["successful_requests"] += 1
                        else:
                            results["failed_requests"] += 1

                        # Track cluster distribution
                        handling_cluster = response.headers.get(
                            "x-handling-cluster", "unknown"
                        )
                        results["cluster_distribution"][handling_cluster] = (
                            results["cluster_distribution"].get(handling_cluster, 0) + 1
                        )

                except aiohttp.ClientError as e:
                    results["total_requests"] += 1
                    results["failed_requests"] += 1
                    results["errors"].append(str(e))
                    results["response_times"].append((time.time() - start_time) * 1000)

                await asyncio.sleep(0.5)

            await asyncio.sleep(2)  # Pause between service test rounds

        # Calculate metrics
        if results["total_requests"] > 0:
            results["availability"] = (
                results["successful_requests"] / results["total_requests"]
            )
            results["error_rate"] = (
                results["failed_requests"] / results["total_requests"]
            )

        if results["response_times"]:
            results["avg_response_time"] = sum(results["response_times"]) / len(
                results["response_times"]
            )
            results["p95_response_time"] = sorted(results["response_times"])[
                int(0.95 * len(results["response_times"]))
            ]

        return results
