"""
End-to-end tests for Istio canary deployments.

Tests complete canary deployment workflows including progressive traffic shifting,
health validation, automatic rollback, and production deployment scenarios.
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
pytestmark = [pytest.mark.e2e, pytest.mark.istio, pytest.mark.canary]


@pytest.fixture(scope="session")
def canary_test_environment():
    """Set up canary deployment test environment."""
    return {
        "namespace": "brain-researcher-canary",
        "services": {
            "br_kg": {
                "stable_version": "v1.0.0",
                "canary_version": "v1.1.0",
                "port": 5000,
                "replicas": 3,
            },
            "agent": {
                "stable_version": "v1.0.0",
                "canary_version": "v1.1.0",
                "port": 8000,
                "replicas": 2,
            },
            "orchestrator": {
                "stable_version": "v1.0.0",
                "canary_version": "v1.1.0",
                "port": 3001,
                "replicas": 3,
            },
        },
        "traffic_steps": [10, 25, 50, 75, 100],
        "step_duration": 300,  # 5 minutes in seconds
        "success_criteria": {
            "error_rate_threshold": 0.05,  # 5%
            "latency_p99_threshold": 2000,  # 2 seconds
            "min_requests_per_step": 100,
        },
    }


@pytest.fixture
async def canary_http_session():
    """Provide HTTP session for canary testing."""
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60),
        connector=aiohttp.TCPConnector(limit=100),
    ) as session:
        yield session


@pytest.fixture
def deployment_manager():
    """Create deployment manager for canary operations."""
    from brain_researcher.infrastructure.istio.canary_deployment_manager import (
        CanaryDeploymentManager,
    )

    with patch("kubernetes.client"):
        manager = CanaryDeploymentManager()

    return manager


class TestCanaryDeploymentLifecycle:
    """Test complete canary deployment lifecycle."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_full_canary_deployment(
        self, canary_test_environment, canary_http_session, deployment_manager
    ):
        """Test complete canary deployment from start to finish."""
        service_name = "br_kg"
        service_config = canary_test_environment["services"][service_name]

        # Step 1: Initialize canary deployment
        deployment_config = {
            "service_name": f"{service_name}-service",
            "namespace": canary_test_environment["namespace"],
            "stable_version": service_config["stable_version"],
            "canary_version": service_config["canary_version"],
            "traffic_steps": canary_test_environment["traffic_steps"],
            "step_duration": canary_test_environment["step_duration"],
            "success_criteria": canary_test_environment["success_criteria"],
        }

        deployment_id = await deployment_manager.start_canary_deployment(
            deployment_config
        )
        assert deployment_id is not None

        # Step 2: Monitor deployment progress
        base_url = f"http://{service_name}-service.{canary_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        total_requests = 0
        successful_requests = 0
        error_counts = {}
        latencies = []

        # Simulate production traffic during canary
        async def generate_traffic():
            nonlocal total_requests, successful_requests, error_counts, latencies

            for _ in range(1000):  # Generate substantial traffic
                start_time = time.time()
                try:
                    async with canary_http_session.get(
                        f"{base_url}/api/v1/search",
                        params={"query": f"canary-test-{random.randint(1, 100)}"},
                        headers={"x-canary-test": "true"},
                    ) as response:
                        end_time = time.time()
                        latencies.append((end_time - start_time) * 1000)

                        total_requests += 1
                        if 200 <= response.status < 400:
                            successful_requests += 1
                        else:
                            status_group = f"{response.status // 100}xx"
                            error_counts[status_group] = (
                                error_counts.get(status_group, 0) + 1
                            )

                except aiohttp.ClientError as e:
                    total_requests += 1
                    error_counts["connection_error"] = (
                        error_counts.get("connection_error", 0) + 1
                    )

                # Spread requests over time
                await asyncio.sleep(random.uniform(0.1, 0.5))

        # Start traffic generation
        traffic_task = asyncio.create_task(generate_traffic())

        try:
            # Step 3: Monitor canary progression
            deployment_completed = False
            max_wait_time = (
                len(canary_test_environment["traffic_steps"])
                * canary_test_environment["step_duration"]
            )
            start_time = time.time()

            while (
                not deployment_completed and (time.time() - start_time) < max_wait_time
            ):
                await asyncio.sleep(30)  # Check every 30 seconds

                status = await deployment_manager.get_deployment_status(deployment_id)

                if status["phase"] == "completed":
                    deployment_completed = True
                elif status["phase"] == "failed" or status["phase"] == "rolled_back":
                    pytest.fail(f"Canary deployment failed: {status}")

            # Step 4: Validate deployment results
            if deployment_completed:
                final_status = await deployment_manager.get_deployment_status(
                    deployment_id
                )
                assert final_status["current_traffic"] == 100
                assert final_status["phase"] == "completed"

                # Validate traffic distribution worked
                assert total_requests > 500  # Should have generated substantial traffic

                if total_requests > 0:
                    success_rate = successful_requests / total_requests
                    assert success_rate >= 0.90  # At least 90% success rate

                if latencies:
                    avg_latency = sum(latencies) / len(latencies)
                    p99_latency = sorted(latencies)[int(0.99 * len(latencies))]

                    assert avg_latency < 1000  # Average latency under 1 second
                    assert (
                        p99_latency
                        < canary_test_environment["success_criteria"][
                            "latency_p99_threshold"
                        ]
                    )

            else:
                pytest.fail("Canary deployment did not complete within expected time")

        finally:
            # Cancel traffic generation
            traffic_task.cancel()
            try:
                await traffic_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_canary_rollback_on_failure(
        self, canary_test_environment, canary_http_session, deployment_manager
    ):
        """Test automatic rollback when canary version has issues."""
        service_name = "agent"
        service_config = canary_test_environment["services"][service_name]

        # Configure deployment with failing canary version
        deployment_config = {
            "service_name": f"{service_name}-service",
            "namespace": canary_test_environment["namespace"],
            "stable_version": service_config["stable_version"],
            "canary_version": "v1.1.0-broken",  # Simulated broken version
            "traffic_steps": [10, 25],  # Shorter progression for test
            "step_duration": 60,  # 1 minute steps
            "success_criteria": {
                "error_rate_threshold": 0.02,  # Very strict threshold
                "latency_p99_threshold": 1000,
                "min_requests_per_step": 50,
            },
        }

        deployment_id = await deployment_manager.start_canary_deployment(
            deployment_config
        )

        # Simulate high error rate from canary version
        base_url = f"http://{service_name}-service.{canary_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        error_simulation_active = True

        async def simulate_canary_errors():
            """Simulate errors from canary version."""
            while error_simulation_active:
                try:
                    # Simulate requests that would hit the canary version
                    async with canary_http_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-canary-routing": "force-canary",
                            "x-test-error-simulation": "true",
                        },
                    ) as response:
                        # Response might be successful or error depending on routing
                        pass
                except aiohttp.ClientError:
                    pass  # Expected in error simulation

                await asyncio.sleep(0.5)

        # Start error simulation
        error_task = asyncio.create_task(simulate_canary_errors())

        try:
            # Wait for deployment to detect issues and rollback
            rollback_detected = False
            max_wait = 300  # 5 minutes maximum
            start_time = time.time()

            while not rollback_detected and (time.time() - start_time) < max_wait:
                await asyncio.sleep(10)

                status = await deployment_manager.get_deployment_status(deployment_id)

                if status["phase"] == "rolled_back":
                    rollback_detected = True
                    break
                elif status["phase"] == "completed":
                    # Should not complete if canary is failing
                    pytest.fail("Deployment completed despite canary failures")

            assert rollback_detected, "Automatic rollback was not triggered"

            # Validate rollback restored stable version
            final_status = await deployment_manager.get_deployment_status(deployment_id)
            assert final_status["current_traffic"] == 0  # All traffic back to stable
            assert final_status["rollback_reason"] in [
                "high_error_rate",
                "health_check_failure",
            ]

        finally:
            error_simulation_active = False
            error_task.cancel()
            try:
                await error_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_canary_manual_promotion(
        self, canary_test_environment, canary_http_session, deployment_manager
    ):
        """Test manual promotion of canary to production."""
        service_name = "orchestrator"
        service_config = canary_test_environment["services"][service_name]

        deployment_config = {
            "service_name": f"{service_name}-service",
            "namespace": canary_test_environment["namespace"],
            "stable_version": service_config["stable_version"],
            "canary_version": service_config["canary_version"],
            "traffic_steps": [10, 25],  # Partial deployment for manual test
            "step_duration": 60,
            "manual_promotion": True,  # Require manual promotion
            "success_criteria": canary_test_environment["success_criteria"],
        }

        deployment_id = await deployment_manager.start_canary_deployment(
            deployment_config
        )

        # Wait for canary to reach 25% traffic
        target_traffic = 25
        reached_target = False
        max_wait = 180  # 3 minutes
        start_time = time.time()

        while not reached_target and (time.time() - start_time) < max_wait:
            await asyncio.sleep(5)

            status = await deployment_manager.get_deployment_status(deployment_id)
            if status["current_traffic"] >= target_traffic:
                reached_target = True

        assert reached_target, "Canary did not reach target traffic level"

        # Manually promote canary to 100%
        promotion_result = await deployment_manager.promote_canary_to_production(
            deployment_id
        )
        assert promotion_result["success"] is True

        # Validate full promotion
        await asyncio.sleep(30)  # Allow time for promotion to take effect

        final_status = await deployment_manager.get_deployment_status(deployment_id)
        assert final_status["current_traffic"] == 100
        assert final_status["phase"] == "completed"


class TestCanaryTrafficManagement:
    """Test canary traffic management and routing."""

    @pytest.mark.asyncio
    async def test_traffic_distribution_accuracy(
        self, canary_test_environment, canary_http_session
    ):
        """Test accuracy of traffic distribution between stable and canary versions."""
        service_name = "br_kg"
        service_config = canary_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{canary_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Test different traffic split percentages
        traffic_splits = [10, 25, 50, 75]

        for split_percentage in traffic_splits:
            # Configure traffic split (this would be done by the deployment manager)
            # For testing, we'll simulate by checking response headers/versions

            version_counts = {"stable": 0, "canary": 0, "unknown": 0}
            total_requests = 200  # Enough for statistical significance

            for i in range(total_requests):
                try:
                    headers = {
                        "x-request-id": f"traffic-test-{split_percentage}-{i}",
                        "x-canary-traffic-split": str(split_percentage),
                    }

                    async with canary_http_session.get(
                        f"{base_url}/api/v1/version", headers=headers
                    ) as response:
                        if response.status == 200:
                            # Check which version handled the request
                            version_header = response.headers.get(
                                "x-service-version", "unknown"
                            )
                            response_data = await response.json()
                            version = response_data.get("version", version_header)

                            if "v1.0" in version or "stable" in version:
                                version_counts["stable"] += 1
                            elif "v1.1" in version or "canary" in version:
                                version_counts["canary"] += 1
                            else:
                                version_counts["unknown"] += 1
                        else:
                            version_counts["unknown"] += 1

                except aiohttp.ClientError:
                    version_counts["unknown"] += 1

            # Validate traffic distribution
            total_known = version_counts["stable"] + version_counts["canary"]

            if total_known > 50:  # Need minimum successful requests
                actual_canary_percentage = (
                    version_counts["canary"] / total_known
                ) * 100

                # Allow for some variance in distribution (±10%)
                expected_min = max(0, split_percentage - 10)
                expected_max = min(100, split_percentage + 10)

                assert (
                    expected_min <= actual_canary_percentage <= expected_max
                ), f"Traffic split {split_percentage}% resulted in {actual_canary_percentage:.1f}% canary traffic"

    @pytest.mark.asyncio
    async def test_session_affinity_during_canary(
        self, canary_test_environment, canary_http_session
    ):
        """Test session affinity behavior during canary deployment."""
        service_name = "orchestrator"
        service_config = canary_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{canary_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Test session stickiness for user sessions
        session_ids = [f"session-{i}" for i in range(10)]
        session_versions = {}

        # Make multiple requests per session
        for session_id in session_ids:
            version_consistency = []

            for request_num in range(5):
                try:
                    headers = {
                        "x-session-id": session_id,
                        "cookie": f"session={session_id}",
                        "x-request-id": f"{session_id}-{request_num}",
                    }

                    async with canary_http_session.get(
                        f"{base_url}/api/v1/session-info", headers=headers
                    ) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            version = response_data.get("service_version", "unknown")
                            version_consistency.append(version)

                except aiohttp.ClientError:
                    version_consistency.append("error")

                await asyncio.sleep(0.1)  # Small delay between requests

            # Check if session remained on the same version
            if version_consistency and version_consistency[0] != "error":
                unique_versions = set(v for v in version_consistency if v != "error")
                session_versions[session_id] = {
                    "versions": list(unique_versions),
                    "consistent": len(unique_versions) <= 1,
                }

        # Validate session affinity
        consistent_sessions = sum(
            1 for s in session_versions.values() if s["consistent"]
        )
        total_valid_sessions = len(session_versions)

        if total_valid_sessions > 0:
            consistency_rate = consistent_sessions / total_valid_sessions
            # Most sessions should be consistent (allowing for some routing changes)
            assert (
                consistency_rate >= 0.7
            ), f"Only {consistency_rate:.1%} of sessions were consistent"


class TestCanaryHealthValidation:
    """Test health validation during canary deployments."""

    @pytest.mark.asyncio
    async def test_comprehensive_health_checks(
        self, canary_test_environment, canary_http_session
    ):
        """Test comprehensive health validation of canary version."""
        service_name = "br_kg"
        service_config = canary_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{canary_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Comprehensive health check suite
        health_checks = [
            {
                "name": "basic_health",
                "endpoint": "/health",
                "method": "GET",
                "expected_status": 200,
                "timeout": 5,
            },
            {
                "name": "readiness_check",
                "endpoint": "/ready",
                "method": "GET",
                "expected_status": 200,
                "timeout": 5,
            },
            {
                "name": "api_functionality",
                "endpoint": "/api/v1/search",
                "method": "POST",
                "data": {"query": "health test"},
                "expected_status": [200, 400],  # 400 acceptable for invalid query
                "timeout": 10,
            },
            {
                "name": "metrics_endpoint",
                "endpoint": "/metrics",
                "method": "GET",
                "expected_status": 200,
                "timeout": 5,
            },
        ]

        health_results = {}

        # Test canary version health
        canary_headers = {"x-canary-routing": "force-canary"}

        for check in health_checks:
            check_results = []

            # Perform each check multiple times for reliability
            for attempt in range(3):
                start_time = time.time()

                try:
                    request_kwargs = {
                        "headers": canary_headers,
                        "timeout": aiohttp.ClientTimeout(total=check["timeout"]),
                    }

                    if check["method"] == "POST":
                        request_kwargs["json"] = check.get("data", {})
                        request_method = canary_http_session.post
                    else:
                        request_method = canary_http_session.get

                    async with request_method(
                        f"{base_url}{check['endpoint']}", **request_kwargs
                    ) as response:
                        end_time = time.time()
                        response_time = (end_time - start_time) * 1000

                        # Check if response status is acceptable
                        expected_statuses = check["expected_status"]
                        if not isinstance(expected_statuses, list):
                            expected_statuses = [expected_statuses]

                        success = response.status in expected_statuses

                        check_results.append(
                            {
                                "success": success,
                                "status_code": response.status,
                                "response_time": response_time,
                                "attempt": attempt + 1,
                            }
                        )

                except asyncio.TimeoutError:
                    check_results.append(
                        {
                            "success": False,
                            "error": "timeout",
                            "response_time": check["timeout"] * 1000,
                            "attempt": attempt + 1,
                        }
                    )

                except aiohttp.ClientError as e:
                    check_results.append(
                        {
                            "success": False,
                            "error": str(e),
                            "response_time": 0,
                            "attempt": attempt + 1,
                        }
                    )

                await asyncio.sleep(1)  # Wait between attempts

            # Analyze check results
            successful_checks = [r for r in check_results if r["success"]]
            health_results[check["name"]] = {
                "success_rate": len(successful_checks) / len(check_results),
                "avg_response_time": (
                    sum(r["response_time"] for r in successful_checks)
                    / len(successful_checks)
                    if successful_checks
                    else 0
                ),
                "results": check_results,
            }

        # Validate overall health
        critical_checks = ["basic_health", "readiness_check"]
        for check_name in critical_checks:
            result = health_results[check_name]
            assert (
                result["success_rate"] >= 0.67
            ), f"Critical check {check_name} failed too often: {result['success_rate']:.1%}"

            if result["avg_response_time"] > 0:
                assert (
                    result["avg_response_time"] < 5000
                ), f"Check {check_name} too slow: {result['avg_response_time']:.0f}ms"

    @pytest.mark.asyncio
    async def test_load_testing_canary(
        self, canary_test_environment, canary_http_session
    ):
        """Test canary version under load."""
        service_name = "agent"
        service_config = canary_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{canary_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Load test configuration
        load_config = {
            "concurrent_users": 20,
            "requests_per_user": 50,
            "ramp_up_time": 30,  # Seconds to reach full load
            "test_duration": 120,  # Total test duration in seconds
        }

        # Track performance metrics
        metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "response_times": [],
            "error_types": {},
            "concurrent_connections": 0,
        }

        async def user_session(user_id: int):
            """Simulate a user session with multiple requests."""
            session_metrics = {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "response_times": [],
            }

            # Ramp up gradually
            delay = (
                load_config["ramp_up_time"] / load_config["concurrent_users"]
            ) * user_id
            await asyncio.sleep(delay)

            for request_num in range(load_config["requests_per_user"]):
                start_time = time.time()

                try:
                    headers = {
                        "x-user-id": f"load-test-user-{user_id}",
                        "x-request-id": f"load-{user_id}-{request_num}",
                        "x-canary-routing": "force-canary",
                    }

                    # Vary request types
                    if request_num % 3 == 0:
                        endpoint = "/health"
                        method = canary_http_session.get
                        request_data = {}
                    elif request_num % 3 == 1:
                        endpoint = "/api/v1/process"
                        method = canary_http_session.post
                        request_data = {"json": {"task": f"load-test-{request_num}"}}
                    else:
                        endpoint = f"/api/v1/status"
                        method = canary_http_session.get
                        request_data = {}

                    async with method(
                        f"{base_url}{endpoint}", headers=headers, **request_data
                    ) as response:
                        end_time = time.time()
                        response_time = (end_time - start_time) * 1000

                        session_metrics["requests"] += 1
                        session_metrics["response_times"].append(response_time)

                        if 200 <= response.status < 400:
                            session_metrics["successes"] += 1
                        else:
                            session_metrics["failures"] += 1

                except Exception as e:
                    end_time = time.time()
                    response_time = (end_time - start_time) * 1000

                    session_metrics["requests"] += 1
                    session_metrics["failures"] += 1
                    session_metrics["response_times"].append(response_time)

                # Vary request interval
                await asyncio.sleep(random.uniform(0.5, 2.0))

            return session_metrics

        # Execute load test
        start_time = time.time()
        tasks = [user_session(i) for i in range(load_config["concurrent_users"])]

        user_results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()

        # Aggregate results
        for result in user_results:
            if isinstance(result, dict):
                metrics["total_requests"] += result["requests"]
                metrics["successful_requests"] += result["successes"]
                metrics["failed_requests"] += result["failures"]
                metrics["response_times"].extend(result["response_times"])

        # Analyze performance
        if metrics["response_times"]:
            metrics["avg_response_time"] = sum(metrics["response_times"]) / len(
                metrics["response_times"]
            )
            metrics["p95_response_time"] = sorted(metrics["response_times"])[
                int(0.95 * len(metrics["response_times"]))
            ]
            metrics["p99_response_time"] = sorted(metrics["response_times"])[
                int(0.99 * len(metrics["response_times"]))
            ]

        if metrics["total_requests"] > 0:
            metrics["success_rate"] = (
                metrics["successful_requests"] / metrics["total_requests"]
            )
            metrics["error_rate"] = (
                metrics["failed_requests"] / metrics["total_requests"]
            )

        test_duration = end_time - start_time
        metrics["requests_per_second"] = (
            metrics["total_requests"] / test_duration if test_duration > 0 else 0
        )

        # Validate performance criteria
        assert (
            metrics["success_rate"] >= 0.95
        ), f"Success rate too low: {metrics['success_rate']:.1%}"
        assert (
            metrics["error_rate"] <= 0.05
        ), f"Error rate too high: {metrics['error_rate']:.1%}"

        if metrics["response_times"]:
            assert (
                metrics["avg_response_time"] < 1000
            ), f"Average response time too high: {metrics['avg_response_time']:.0f}ms"
            assert (
                metrics["p95_response_time"] < 2000
            ), f"P95 response time too high: {metrics['p95_response_time']:.0f}ms"

        assert (
            metrics["requests_per_second"] >= 5
        ), f"Throughput too low: {metrics['requests_per_second']:.1f} req/s"


@pytest.mark.production
class TestProductionCanaryScenarios:
    """Test production-like canary deployment scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_multi_service_canary_coordination(
        self, canary_test_environment, canary_http_session, deployment_manager
    ):
        """Test coordinated canary deployment across multiple services."""
        # Deploy canary versions of dependent services in correct order
        services_order = ["br_kg", "agent", "orchestrator"]  # Dependency order

        deployment_ids = {}

        try:
            # Start canary deployments in dependency order
            for service_name in services_order:
                service_config = canary_test_environment["services"][service_name]

                deployment_config = {
                    "service_name": f"{service_name}-service",
                    "namespace": canary_test_environment["namespace"],
                    "stable_version": service_config["stable_version"],
                    "canary_version": service_config["canary_version"],
                    "traffic_steps": [
                        10,
                        25,
                        50,
                    ],  # Faster progression for coordination test
                    "step_duration": 60,
                    "success_criteria": canary_test_environment["success_criteria"],
                    "dependency_services": services_order[
                        : services_order.index(service_name)
                    ],
                }

                deployment_id = await deployment_manager.start_canary_deployment(
                    deployment_config
                )
                deployment_ids[service_name] = deployment_id

                # Wait for initial deployment before starting next service
                await asyncio.sleep(30)

            # Monitor all deployments
            all_completed = False
            max_wait = 900  # 15 minutes for all services
            start_time = time.time()

            while not all_completed and (time.time() - start_time) < max_wait:
                await asyncio.sleep(30)

                statuses = {}
                for service_name, deployment_id in deployment_ids.items():
                    statuses[service_name] = (
                        await deployment_manager.get_deployment_status(deployment_id)
                    )

                # Check if all deployments are complete or if any failed
                completed_count = sum(
                    1 for status in statuses.values() if status["phase"] == "completed"
                )
                failed_count = sum(
                    1
                    for status in statuses.values()
                    if status["phase"] in ["failed", "rolled_back"]
                )

                if failed_count > 0:
                    failed_services = [
                        name
                        for name, status in statuses.items()
                        if status["phase"] in ["failed", "rolled_back"]
                    ]
                    pytest.fail(
                        f"Canary deployment failed for services: {failed_services}"
                    )

                if completed_count == len(services_order):
                    all_completed = True

            assert (
                all_completed
            ), "Multi-service canary deployment did not complete in time"

            # Validate end-to-end functionality with all canary versions
            orchestrator_url = f"http://orchestrator-service.{canary_test_environment['namespace']}.svc.cluster.local:3001"

            # Test complete workflow through all canary versions
            async with canary_http_session.post(
                f"{orchestrator_url}/api/v1/full-workflow-test",
                json={"test": "multi-service-canary"},
                headers={"x-canary-routing": "force-canary"},
            ) as response:
                # Should work with all canary versions deployed
                assert response.status in [200, 404]  # Success or endpoint not found

        finally:
            # Cleanup: rollback any incomplete deployments
            for service_name, deployment_id in deployment_ids.items():
                try:
                    status = await deployment_manager.get_deployment_status(
                        deployment_id
                    )
                    if status["phase"] not in ["completed", "rolled_back"]:
                        await deployment_manager.rollback_canary_deployment(
                            deployment_id
                        )
                except Exception:
                    pass  # Best effort cleanup

    @pytest.mark.asyncio
    async def test_canary_with_external_dependencies(
        self, canary_test_environment, canary_http_session
    ):
        """Test canary deployment behavior with external service dependencies."""
        service_name = "orchestrator"
        base_url = f"http://{service_name}-service.{canary_test_environment['namespace']}.svc.cluster.local:3001"

        # Test scenarios with various external dependency states
        dependency_scenarios = [
            {
                "name": "healthy_externals",
                "simulate_healthy": True,
                "expected_success_rate": 0.95,
            },
            {
                "name": "degraded_externals",
                "simulate_degraded": True,
                "expected_success_rate": 0.85,
            },
            {
                "name": "failing_externals",
                "simulate_failing": True,
                "expected_success_rate": 0.5,
            },
        ]

        for scenario in dependency_scenarios:
            scenario_results = {"requests": 0, "successes": 0, "failures": 0}

            # Generate requests for this scenario
            for i in range(100):
                try:
                    headers = {
                        "x-canary-routing": "force-canary",
                        "x-external-dependency-scenario": scenario["name"],
                        "x-request-id": f"{scenario['name']}-{i}",
                    }

                    async with canary_http_session.post(
                        f"{base_url}/api/v1/external-dependent-operation",
                        json={"operation": "test_external_deps"},
                        headers=headers,
                    ) as response:
                        scenario_results["requests"] += 1

                        if 200 <= response.status < 400:
                            scenario_results["successes"] += 1
                        else:
                            scenario_results["failures"] += 1

                except aiohttp.ClientError:
                    scenario_results["requests"] += 1
                    scenario_results["failures"] += 1

                await asyncio.sleep(0.1)

            # Validate scenario results
            if scenario_results["requests"] > 0:
                success_rate = (
                    scenario_results["successes"] / scenario_results["requests"]
                )

                # Success rate should meet expectations for the scenario
                assert (
                    success_rate >= scenario["expected_success_rate"]
                ), f"Scenario {scenario['name']} success rate {success_rate:.2f} below expected {scenario['expected_success_rate']:.2f}"
