"""
Load tests for Istio service mesh performance.

Tests service mesh overhead, latency impact, throughput characteristics,
and performance under various load conditions.
"""

import asyncio
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import pytest

# Test markers
pytestmark = [pytest.mark.load, pytest.mark.istio, pytest.mark.performance]


@pytest.fixture(scope="session")
def load_test_environment():
    """Set up load test environment."""
    return {
        "namespace": "brain-researcher-load",
        "services": {
            "br_kg": {
                "port": 5000,
                "replicas": 3,
                "endpoints": ["/health", "/api/v1/search", "/api/v1/status"],
                "expected_rps": 500,
            },
            "agent": {
                "port": 8000,
                "replicas": 2,
                "endpoints": ["/health", "/api/v1/process", "/api/v1/status"],
                "expected_rps": 200,
            },
            "orchestrator": {
                "port": 3001,
                "replicas": 3,
                "endpoints": ["/health", "/api/v1/analytics", "/api/v1/dashboard"],
                "expected_rps": 1000,
            },
            "web-ui": {
                "port": 3000,
                "replicas": 2,
                "endpoints": ["/health", "/api/status", "/api/config"],
                "expected_rps": 2000,
            },
        },
        "load_scenarios": {
            "light": {"concurrent_users": 50, "duration": 120},
            "moderate": {"concurrent_users": 100, "duration": 300},
            "heavy": {"concurrent_users": 200, "duration": 600},
            "burst": {"concurrent_users": 500, "duration": 60},
        },
    }


@pytest.fixture
async def load_test_session():
    """Provide HTTP session optimized for load testing."""
    connector = aiohttp.TCPConnector(
        limit=500,
        limit_per_host=100,
        keepalive_timeout=60,
        enable_cleanup_closed=True,
        use_dns_cache=True,
        ttl_dns_cache=300,
    )

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=30, connect=5),
        headers={"User-Agent": "BrainResearcher-LoadTest/1.0"},
    ) as session:
        yield session


class TestServiceMeshOverhead:
    """Test Istio service mesh overhead on performance."""

    @pytest.mark.asyncio
    async def test_latency_overhead_comparison(
        self, load_test_environment, load_test_session
    ):
        """Compare latency with and without service mesh."""
        service_name = "br_kg"
        service_config = load_test_environment["services"][service_name]

        # Test configurations
        test_configs = [
            {
                "name": "with_istio",
                "url": f"http://{service_name}-service.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}",
                "headers": {"x-istio-enabled": "true"},
            },
            {
                "name": "bypass_istio",
                "url": f"http://{service_name}-service-direct.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}",
                "headers": {"x-istio-bypass": "true"},
            },
        ]

        results = {}

        for config in test_configs:
            print(f"Testing latency for {config['name']}...")

            latencies = []

            # Warm up
            for _ in range(10):
                try:
                    async with load_test_session.get(
                        f"{config['url']}/health", headers=config["headers"]
                    ) as response:
                        pass
                except aiohttp.ClientError:
                    pass

            # Actual measurements
            for i in range(200):
                start_time = time.time()

                try:
                    async with load_test_session.get(
                        f"{config['url']}/health",
                        headers={
                            **config["headers"],
                            "x-request-id": f"{config['name']}-{i}",
                        },
                    ) as response:
                        end_time = time.time()

                        if response.status == 200:
                            latency = (end_time - start_time) * 1000  # Convert to ms
                            latencies.append(latency)

                except aiohttp.ClientError:
                    pass

                # Small delay to avoid overwhelming the service
                await asyncio.sleep(0.01)

            if latencies:
                results[config["name"]] = {
                    "count": len(latencies),
                    "mean": statistics.mean(latencies),
                    "median": statistics.median(latencies),
                    "p95": sorted(latencies)[int(0.95 * len(latencies))],
                    "p99": sorted(latencies)[int(0.99 * len(latencies))],
                    "min": min(latencies),
                    "max": max(latencies),
                    "stddev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
                }

        # Analyze overhead
        if "with_istio" in results and "bypass_istio" in results:
            istio_mean = results["with_istio"]["mean"]
            direct_mean = results["bypass_istio"]["mean"]

            overhead_ms = istio_mean - direct_mean
            overhead_percent = (
                (overhead_ms / direct_mean) * 100 if direct_mean > 0 else 0
            )

            print(f"Latency comparison:")
            print(f"  Direct: {direct_mean:.2f}ms")
            print(f"  With Istio: {istio_mean:.2f}ms")
            print(f"  Overhead: {overhead_ms:.2f}ms ({overhead_percent:.1f}%)")

            # Validate acceptable overhead
            assert (
                overhead_percent <= 50
            ), f"Istio overhead too high: {overhead_percent:.1f}%"
            assert (
                overhead_ms <= 10
            ), f"Istio absolute overhead too high: {overhead_ms:.2f}ms"

            # P95 and P99 should also be reasonable
            istio_p95 = results["with_istio"]["p95"]
            direct_p95 = results["bypass_istio"]["p95"]
            p95_overhead = (
                ((istio_p95 - direct_p95) / direct_p95) * 100 if direct_p95 > 0 else 0
            )

            assert (
                p95_overhead <= 100
            ), f"P95 latency overhead too high: {p95_overhead:.1f}%"

        elif "with_istio" in results:
            # Only Istio results available, validate absolute performance
            istio_mean = results["with_istio"]["mean"]
            assert istio_mean <= 50, f"Istio latency too high: {istio_mean:.2f}ms"

    @pytest.mark.asyncio
    async def test_throughput_overhead(self, load_test_environment, load_test_session):
        """Test throughput impact of service mesh."""
        service_name = "orchestrator"
        service_config = load_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Test different concurrency levels
        concurrency_levels = [10, 25, 50, 100]

        throughput_results = {}

        for concurrency in concurrency_levels:
            print(f"Testing throughput with {concurrency} concurrent connections...")

            async def concurrent_requests():
                """Make concurrent requests."""
                request_results = []

                async def single_request(request_id: int):
                    start_time = time.time()

                    try:
                        async with load_test_session.get(
                            f"{base_url}/health",
                            headers={
                                "x-throughput-test": "true",
                                "x-concurrency": str(concurrency),
                            },
                        ) as response:
                            end_time = time.time()

                            return {
                                "success": response.status == 200,
                                "latency": (end_time - start_time) * 1000,
                                "request_id": request_id,
                            }

                    except aiohttp.ClientError:
                        return {
                            "success": False,
                            "latency": (time.time() - start_time) * 1000,
                            "request_id": request_id,
                        }

                # Execute concurrent requests
                tasks = [single_request(i) for i in range(concurrency)]
                return await asyncio.gather(*tasks, return_exceptions=True)

            # Measure throughput over multiple rounds
            total_requests = 0
            successful_requests = 0
            total_time = 0
            all_latencies = []

            test_rounds = 10

            for round_num in range(test_rounds):
                round_start = time.time()

                results = await concurrent_requests()

                round_end = time.time()
                round_time = round_end - round_start

                total_time += round_time

                valid_results = [r for r in results if isinstance(r, dict)]
                successful_round_requests = sum(
                    1 for r in valid_results if r.get("success")
                )

                total_requests += len(valid_results)
                successful_requests += successful_round_requests

                # Collect latencies
                round_latencies = [
                    r["latency"] for r in valid_results if r.get("success")
                ]
                all_latencies.extend(round_latencies)

                # Brief pause between rounds
                await asyncio.sleep(0.5)

            # Calculate throughput metrics
            if total_time > 0:
                requests_per_second = total_requests / total_time
                successful_rps = successful_requests / total_time
                success_rate = (
                    successful_requests / total_requests if total_requests > 0 else 0
                )

                avg_latency = statistics.mean(all_latencies) if all_latencies else 0
                p95_latency = (
                    sorted(all_latencies)[int(0.95 * len(all_latencies))]
                    if all_latencies
                    else 0
                )

                throughput_results[concurrency] = {
                    "total_requests": total_requests,
                    "successful_requests": successful_requests,
                    "total_time": total_time,
                    "requests_per_second": requests_per_second,
                    "successful_rps": successful_rps,
                    "success_rate": success_rate,
                    "avg_latency": avg_latency,
                    "p95_latency": p95_latency,
                }

                print(
                    f"  Concurrency {concurrency}: {successful_rps:.1f} RPS, {success_rate:.1%} success rate"
                )

        # Analyze throughput scalability
        if throughput_results:
            # Check that throughput increases with concurrency (up to a point)
            sorted_results = sorted(throughput_results.items())

            for i in range(1, len(sorted_results)):
                prev_concurrency, prev_result = sorted_results[i - 1]
                curr_concurrency, curr_result = sorted_results[i]

                # Throughput should generally increase with concurrency
                # (allowing for some variance at higher concurrency levels)
                if prev_concurrency <= 50 and curr_concurrency <= 100:
                    throughput_ratio = (
                        curr_result["successful_rps"] / prev_result["successful_rps"]
                    )

                    # Should see some improvement in throughput
                    assert (
                        throughput_ratio >= 0.8
                    ), f"Throughput degraded significantly from {prev_concurrency} to {curr_concurrency}: {throughput_ratio:.2f}x"

            # Validate absolute performance
            max_rps = max(
                result["successful_rps"] for result in throughput_results.values()
            )
            assert max_rps >= 50, f"Maximum throughput too low: {max_rps:.1f} RPS"

    @pytest.mark.asyncio
    async def test_memory_cpu_overhead(self, load_test_environment, load_test_session):
        """Test memory and CPU overhead of Istio sidecars."""
        # This test would typically require integration with monitoring systems
        # For now, we'll test the observable performance characteristics

        service_name = "agent"
        service_config = load_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Test resource usage under sustained load
        print("Testing resource usage under sustained load...")

        load_duration = 180  # 3 minutes
        target_rps = 50
        request_interval = 1.0 / target_rps

        resource_metrics = {
            "requests_sent": 0,
            "responses_received": 0,
            "errors": 0,
            "latencies": [],
            "start_time": time.time(),
        }

        async def sustained_load():
            """Generate sustained load."""
            end_time = time.time() + load_duration
            request_count = 0

            while time.time() < end_time:
                start_request = time.time()

                try:
                    async with load_test_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-resource-test": "true",
                            "x-request-num": str(request_count),
                        },
                    ) as response:
                        end_request = time.time()

                        resource_metrics["requests_sent"] += 1

                        if response.status == 200:
                            resource_metrics["responses_received"] += 1
                            resource_metrics["latencies"].append(
                                (end_request - start_request) * 1000
                            )
                        else:
                            resource_metrics["errors"] += 1

                except aiohttp.ClientError:
                    resource_metrics["requests_sent"] += 1
                    resource_metrics["errors"] += 1

                request_count += 1

                # Maintain target RPS
                elapsed = time.time() - start_request
                sleep_time = max(0, request_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        # Run sustained load test
        await sustained_load()

        # Analyze resource efficiency
        total_time = time.time() - resource_metrics["start_time"]

        if resource_metrics["requests_sent"] > 0:
            success_rate = (
                resource_metrics["responses_received"]
                / resource_metrics["requests_sent"]
            )
            actual_rps = resource_metrics["requests_sent"] / total_time

            print(f"Resource usage test results:")
            print(f"  Duration: {total_time:.1f}s")
            print(f"  Requests sent: {resource_metrics['requests_sent']}")
            print(f"  Success rate: {success_rate:.1%}")
            print(f"  Actual RPS: {actual_rps:.1f}")

            if resource_metrics["latencies"]:
                avg_latency = statistics.mean(resource_metrics["latencies"])
                p95_latency = sorted(resource_metrics["latencies"])[
                    int(0.95 * len(resource_metrics["latencies"]))
                ]

                print(f"  Average latency: {avg_latency:.2f}ms")
                print(f"  P95 latency: {p95_latency:.2f}ms")

                # Validate sustained performance
                assert (
                    success_rate >= 0.95
                ), f"Success rate degraded under sustained load: {success_rate:.1%}"
                assert (
                    avg_latency <= 100
                ), f"Average latency too high under load: {avg_latency:.2f}ms"
                assert (
                    p95_latency <= 200
                ), f"P95 latency too high under load: {p95_latency:.2f}ms"

            # Should maintain target RPS within reasonable variance
            rps_variance = abs(actual_rps - target_rps) / target_rps
            assert rps_variance <= 0.1, f"RPS variance too high: {rps_variance:.1%}"


class TestHighLoadScenarios:
    """Test service mesh under high load conditions."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_burst_traffic_handling(
        self, load_test_environment, load_test_session
    ):
        """Test handling of sudden traffic bursts."""
        service_name = "web-ui"
        service_config = load_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Burst test configuration
        burst_sizes = [100, 250, 500, 1000]

        burst_results = {}

        for burst_size in burst_sizes:
            print(f"Testing burst of {burst_size} requests...")

            async def burst_request(request_id: int):
                """Individual request in burst."""
                start_time = time.time()

                try:
                    async with load_test_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-burst-test": "true",
                            "x-burst-size": str(burst_size),
                            "x-request-id": str(request_id),
                        },
                    ) as response:
                        end_time = time.time()

                        return {
                            "success": response.status == 200,
                            "status_code": response.status,
                            "latency": (end_time - start_time) * 1000,
                            "request_id": request_id,
                            "rate_limited": response.status == 429,
                            "server_error": response.status >= 500,
                        }

                except asyncio.TimeoutError:
                    return {
                        "success": False,
                        "timeout": True,
                        "latency": (time.time() - start_time) * 1000,
                        "request_id": request_id,
                    }

                except aiohttp.ClientError as e:
                    return {
                        "success": False,
                        "connection_error": True,
                        "error": str(e),
                        "latency": (time.time() - start_time) * 1000,
                        "request_id": request_id,
                    }

            # Execute burst
            burst_start = time.time()
            tasks = [burst_request(i) for i in range(burst_size)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            burst_duration = time.time() - burst_start

            # Analyze burst results
            valid_results = [r for r in results if isinstance(r, dict)]
            successful_requests = [r for r in valid_results if r.get("success")]
            failed_requests = [r for r in valid_results if not r.get("success")]

            rate_limited_requests = [r for r in valid_results if r.get("rate_limited")]
            timeout_requests = [r for r in valid_results if r.get("timeout")]
            server_error_requests = [r for r in valid_results if r.get("server_error")]

            success_rate = (
                len(successful_requests) / len(valid_results) if valid_results else 0
            )

            successful_latencies = [r["latency"] for r in successful_requests]
            avg_latency = (
                statistics.mean(successful_latencies) if successful_latencies else 0
            )
            p95_latency = (
                sorted(successful_latencies)[int(0.95 * len(successful_latencies))]
                if successful_latencies
                else 0
            )

            actual_rps = (
                len(valid_results) / burst_duration if burst_duration > 0 else 0
            )

            burst_results[burst_size] = {
                "total_requests": len(valid_results),
                "successful_requests": len(successful_requests),
                "failed_requests": len(failed_requests),
                "success_rate": success_rate,
                "rate_limited_requests": len(rate_limited_requests),
                "timeout_requests": len(timeout_requests),
                "server_error_requests": len(server_error_requests),
                "avg_latency": avg_latency,
                "p95_latency": p95_latency,
                "burst_duration": burst_duration,
                "actual_rps": actual_rps,
            }

            print(
                f"  Burst {burst_size}: {success_rate:.1%} success rate, {avg_latency:.0f}ms avg latency"
            )

            # Wait between bursts to allow recovery
            await asyncio.sleep(10)

        # Analyze burst handling capability
        for burst_size, result in burst_results.items():
            # Should maintain reasonable performance even under burst
            if burst_size <= 250:
                # Smaller bursts should have high success rates
                assert (
                    result["success_rate"] >= 0.8
                ), f"Burst {burst_size} success rate too low: {result['success_rate']:.1%}"
            else:
                # Larger bursts might have lower success rates but should handle gracefully
                assert (
                    result["success_rate"] >= 0.5
                ), f"Large burst {burst_size} handled too poorly: {result['success_rate']:.1%}"

            # Should not have excessive server errors (rate limiting is acceptable)
            server_error_rate = (
                result["server_error_requests"] / result["total_requests"]
            )
            assert (
                server_error_rate <= 0.1
            ), f"Too many server errors in burst {burst_size}: {server_error_rate:.1%}"

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_sustained_high_load(self, load_test_environment, load_test_session):
        """Test performance under sustained high load."""
        service_name = "orchestrator"
        service_config = load_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Sustained load configuration
        target_rps = 200
        test_duration = 600  # 10 minutes
        concurrent_workers = 50

        print(
            f"Starting sustained load test: {target_rps} RPS for {test_duration}s with {concurrent_workers} workers"
        )

        # Shared metrics
        metrics = {
            "requests_sent": 0,
            "successful_responses": 0,
            "failed_responses": 0,
            "latencies": [],
            "status_codes": {},
            "errors": [],
            "start_time": time.time(),
        }

        async def worker(worker_id: int):
            """Individual worker generating load."""
            worker_requests = 0
            worker_end_time = metrics["start_time"] + test_duration

            # Calculate inter-request delay for this worker
            requests_per_worker = target_rps / concurrent_workers
            request_interval = (
                1.0 / requests_per_worker if requests_per_worker > 0 else 1.0
            )

            while time.time() < worker_end_time:
                request_start = time.time()

                try:
                    # Vary endpoints to simulate realistic traffic
                    endpoint = random.choice(
                        ["/health", "/api/v1/analytics", "/api/v1/dashboard"]
                    )

                    async with load_test_session.get(
                        f"{base_url}{endpoint}",
                        headers={
                            "x-sustained-load": "true",
                            "x-worker-id": str(worker_id),
                            "x-request-num": str(worker_requests),
                        },
                    ) as response:
                        request_end = time.time()
                        latency = (request_end - request_start) * 1000

                        # Update shared metrics (in production, use proper synchronization)
                        metrics["requests_sent"] += 1

                        if response.status == 200:
                            metrics["successful_responses"] += 1
                        else:
                            metrics["failed_responses"] += 1

                        metrics["latencies"].append(latency)

                        status_key = str(response.status)
                        metrics["status_codes"][status_key] = (
                            metrics["status_codes"].get(status_key, 0) + 1
                        )

                except aiohttp.ClientError as e:
                    metrics["requests_sent"] += 1
                    metrics["failed_responses"] += 1
                    metrics["errors"].append(str(e))

                worker_requests += 1

                # Rate limiting
                elapsed = time.time() - request_start
                sleep_time = max(0, request_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        # Start all workers
        start_time = time.time()
        worker_tasks = [worker(i) for i in range(concurrent_workers)]

        # Monitor progress periodically
        monitoring_task = asyncio.create_task(
            self._monitor_sustained_load_progress(metrics, test_duration)
        )

        # Wait for all workers to complete
        await asyncio.gather(*worker_tasks)

        # Stop monitoring
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass

        # Analyze sustained load results
        total_time = time.time() - start_time

        if metrics["requests_sent"] > 0:
            success_rate = metrics["successful_responses"] / metrics["requests_sent"]
            actual_rps = metrics["requests_sent"] / total_time
            successful_rps = metrics["successful_responses"] / total_time

            print(f"\nSustained load test completed:")
            print(f"  Duration: {total_time:.1f}s")
            print(f"  Total requests: {metrics['requests_sent']}")
            print(f"  Success rate: {success_rate:.1%}")
            print(f"  Target RPS: {target_rps}")
            print(f"  Actual RPS: {actual_rps:.1f}")
            print(f"  Successful RPS: {successful_rps:.1f}")

            if metrics["latencies"]:
                avg_latency = statistics.mean(metrics["latencies"])
                median_latency = statistics.median(metrics["latencies"])
                p95_latency = sorted(metrics["latencies"])[
                    int(0.95 * len(metrics["latencies"]))
                ]
                p99_latency = sorted(metrics["latencies"])[
                    int(0.99 * len(metrics["latencies"]))
                ]

                print(f"  Average latency: {avg_latency:.2f}ms")
                print(f"  Median latency: {median_latency:.2f}ms")
                print(f"  P95 latency: {p95_latency:.2f}ms")
                print(f"  P99 latency: {p99_latency:.2f}ms")

                # Validate sustained performance
                assert (
                    success_rate >= 0.9
                ), f"Success rate too low under sustained load: {success_rate:.1%}"
                assert (
                    avg_latency <= 200
                ), f"Average latency too high: {avg_latency:.2f}ms"
                assert p95_latency <= 500, f"P95 latency too high: {p95_latency:.2f}ms"
                assert p99_latency <= 1000, f"P99 latency too high: {p99_latency:.2f}ms"

            # RPS should be close to target (allowing for some variance)
            rps_variance = abs(successful_rps - target_rps) / target_rps
            assert (
                rps_variance <= 0.2
            ), f"RPS variance too high: {rps_variance:.1%} (target: {target_rps}, actual: {successful_rps:.1f})"

    async def _monitor_sustained_load_progress(
        self, metrics: Dict, total_duration: int
    ):
        """Monitor sustained load test progress."""
        start_time = metrics["start_time"]

        while True:
            await asyncio.sleep(30)  # Report every 30 seconds

            elapsed = time.time() - start_time
            progress = (elapsed / total_duration) * 100

            if metrics["requests_sent"] > 0:
                current_rps = metrics["requests_sent"] / elapsed
                success_rate = (
                    metrics["successful_responses"] / metrics["requests_sent"]
                )

                print(
                    f"Progress: {progress:.1f}% - RPS: {current_rps:.1f}, Success: {success_rate:.1%}"
                )

            if elapsed >= total_duration:
                break


class TestConcurrentServiceMesh:
    """Test concurrent access patterns in service mesh."""

    @pytest.mark.asyncio
    async def test_cross_service_concurrent_load(
        self, load_test_environment, load_test_session
    ):
        """Test concurrent load across multiple services."""
        services = load_test_environment["services"]

        # Test configuration
        concurrent_users_per_service = 20
        test_duration = 120  # 2 minutes

        print(f"Testing concurrent load across {len(services)} services...")

        service_metrics = {}

        async def service_load_generator(service_name: str, service_config: Dict):
            """Generate load for a specific service."""
            base_url = f"http://{service_name}-service.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

            service_results = {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "latencies": [],
                "start_time": time.time(),
            }

            async def user_session(user_id: int):
                """Simulate user session for this service."""
                session_end_time = service_results["start_time"] + test_duration
                session_requests = 0

                while time.time() < session_end_time:
                    # Choose random endpoint
                    endpoint = random.choice(
                        service_config.get("endpoints", ["/health"])
                    )

                    request_start = time.time()

                    try:
                        async with load_test_session.get(
                            f"{base_url}{endpoint}",
                            headers={
                                "x-cross-service-load": "true",
                                "x-service": service_name,
                                "x-user-id": str(user_id),
                                "x-session-request": str(session_requests),
                            },
                        ) as response:
                            request_end = time.time()
                            latency = (request_end - request_start) * 1000

                            service_results["requests"] += 1
                            service_results["latencies"].append(latency)

                            if response.status == 200:
                                service_results["successes"] += 1
                            else:
                                service_results["failures"] += 1

                    except aiohttp.ClientError:
                        service_results["requests"] += 1
                        service_results["failures"] += 1

                    session_requests += 1

                    # Variable delay between requests
                    await asyncio.sleep(random.uniform(0.1, 2.0))

            # Start concurrent user sessions for this service
            user_tasks = [user_session(i) for i in range(concurrent_users_per_service)]
            await asyncio.gather(*user_tasks)

            # Calculate service metrics
            total_time = time.time() - service_results["start_time"]

            if service_results["requests"] > 0:
                service_results["success_rate"] = (
                    service_results["successes"] / service_results["requests"]
                )
                service_results["rps"] = service_results["requests"] / total_time
                service_results["successful_rps"] = (
                    service_results["successes"] / total_time
                )

            if service_results["latencies"]:
                service_results["avg_latency"] = statistics.mean(
                    service_results["latencies"]
                )
                service_results["p95_latency"] = sorted(service_results["latencies"])[
                    int(0.95 * len(service_results["latencies"]))
                ]

            service_metrics[service_name] = service_results

        # Start load generators for all services concurrently
        service_tasks = [
            service_load_generator(name, config) for name, config in services.items()
        ]

        await asyncio.gather(*service_tasks)

        # Analyze cross-service performance
        print("\nCross-service load test results:")

        total_requests = sum(
            metrics["requests"] for metrics in service_metrics.values()
        )
        total_successes = sum(
            metrics["successes"] for metrics in service_metrics.values()
        )
        overall_success_rate = (
            total_successes / total_requests if total_requests > 0 else 0
        )

        print(
            f"Overall: {total_requests} requests, {overall_success_rate:.1%} success rate"
        )

        for service_name, metrics in service_metrics.items():
            print(
                f"  {service_name}: {metrics['rps']:.1f} RPS, {metrics['success_rate']:.1%} success, {metrics.get('avg_latency', 0):.0f}ms avg"
            )

            # Validate individual service performance
            assert (
                metrics["success_rate"] >= 0.8
            ), f"Service {service_name} success rate too low: {metrics['success_rate']:.1%}"

            if metrics.get("avg_latency"):
                assert (
                    metrics["avg_latency"] <= 500
                ), f"Service {service_name} average latency too high: {metrics['avg_latency']:.0f}ms"

        # Validate overall system performance under concurrent load
        assert (
            overall_success_rate >= 0.85
        ), f"Overall success rate too low under cross-service load: {overall_success_rate:.1%}"

    @pytest.mark.asyncio
    async def test_service_mesh_connection_pooling(
        self, load_test_environment, load_test_session
    ):
        """Test connection pooling efficiency in service mesh."""
        service_name = "br_kg"
        service_config = load_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{load_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Test different connection patterns
        connection_patterns = [
            {
                "name": "sequential_requests",
                "concurrent_connections": 1,
                "requests_per_connection": 100,
                "connection_reuse": True,
            },
            {
                "name": "parallel_connections",
                "concurrent_connections": 20,
                "requests_per_connection": 5,
                "connection_reuse": True,
            },
            {
                "name": "new_connections",
                "concurrent_connections": 10,
                "requests_per_connection": 10,
                "connection_reuse": False,
            },
        ]

        pattern_results = {}

        for pattern in connection_patterns:
            print(f"Testing connection pattern: {pattern['name']}")

            async def connection_worker(connection_id: int):
                """Worker representing a connection."""
                connection_results = {
                    "requests": 0,
                    "successes": 0,
                    "latencies": [],
                    "connection_errors": 0,
                }

                async def run_with_session(
                    session: aiohttp.ClientSession,
                ) -> Dict[str, Any]:
                    for request_num in range(pattern["requests_per_connection"]):
                        request_start = time.time()

                        try:
                            async with session.get(
                                f"{base_url}/health",
                                headers={
                                    "x-connection-pattern": pattern["name"],
                                    "x-connection-id": str(connection_id),
                                    "x-request-num": str(request_num),
                                    "connection": (
                                        "keep-alive"
                                        if pattern["connection_reuse"]
                                        else "close"
                                    ),
                                },
                            ) as response:
                                request_end = time.time()
                                latency = (request_end - request_start) * 1000

                                connection_results["requests"] += 1
                                connection_results["latencies"].append(latency)

                                if response.status == 200:
                                    connection_results["successes"] += 1

                        except aiohttp.ClientError:
                            connection_results["requests"] += 1
                            connection_results["connection_errors"] += 1

                        # Small delay between requests on same connection
                        await asyncio.sleep(0.01)

                    return connection_results

                if pattern["connection_reuse"]:
                    return await run_with_session(load_test_session)

                async with aiohttp.ClientSession() as connection_session:
                    return await run_with_session(connection_session)

            # Execute connection pattern
            pattern_start = time.time()

            connection_tasks = [
                connection_worker(i) for i in range(pattern["concurrent_connections"])
            ]

            connection_results = await asyncio.gather(*connection_tasks)

            pattern_duration = time.time() - pattern_start

            # Aggregate results
            total_requests = sum(r["requests"] for r in connection_results)
            total_successes = sum(r["successes"] for r in connection_results)
            total_connection_errors = sum(
                r["connection_errors"] for r in connection_results
            )
            all_latencies = []

            for r in connection_results:
                all_latencies.extend(r["latencies"])

            pattern_metrics = {
                "total_requests": total_requests,
                "total_successes": total_successes,
                "success_rate": (
                    total_successes / total_requests if total_requests > 0 else 0
                ),
                "connection_errors": total_connection_errors,
                "duration": pattern_duration,
                "rps": total_requests / pattern_duration if pattern_duration > 0 else 0,
            }

            if all_latencies:
                pattern_metrics["avg_latency"] = statistics.mean(all_latencies)
                pattern_metrics["p95_latency"] = sorted(all_latencies)[
                    int(0.95 * len(all_latencies))
                ]

            pattern_results[pattern["name"]] = pattern_metrics

            print(
                f"  {pattern['name']}: {pattern_metrics['rps']:.1f} RPS, {pattern_metrics['success_rate']:.1%} success"
            )

        # Analyze connection pooling efficiency
        if (
            "sequential_requests" in pattern_results
            and "parallel_connections" in pattern_results
        ):
            sequential_rps = pattern_results["sequential_requests"]["rps"]
            parallel_rps = pattern_results["parallel_connections"]["rps"]

            # Parallel connections should provide higher throughput
            throughput_improvement = (
                parallel_rps / sequential_rps if sequential_rps > 0 else 1
            )

            print(
                f"Connection pooling throughput improvement: {throughput_improvement:.1f}x"
            )

            # Should see significant improvement with parallel connections
            assert (
                throughput_improvement >= 2.0
            ), f"Insufficient throughput improvement with connection pooling: {throughput_improvement:.1f}x"

        # Validate connection reuse efficiency
        if (
            "parallel_connections" in pattern_results
            and "new_connections" in pattern_results
        ):
            reuse_latency = pattern_results["parallel_connections"].get(
                "avg_latency", 0
            )
            new_conn_latency = pattern_results["new_connections"].get("avg_latency", 0)

            if reuse_latency > 0 and new_conn_latency > 0:
                latency_improvement = (
                    new_conn_latency - reuse_latency
                ) / new_conn_latency

                print(
                    f"Connection reuse latency improvement: {latency_improvement:.1%}"
                )

                # Connection reuse should reduce latency
                assert (
                    latency_improvement >= 0
                ), "Connection reuse should not increase latency"
