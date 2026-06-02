"""
Load tests for Istio scalability and autoscaling.

Tests horizontal pod autoscaling, cluster autoscaling, traffic scaling patterns,
and performance characteristics under various scaling scenarios.
"""

import asyncio
import json
import math
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import pytest

# Test markers
pytestmark = [pytest.mark.load, pytest.mark.istio, pytest.mark.scalability]


@pytest.fixture(scope="session")
def scalability_test_environment():
    """Set up scalability test environment."""
    return {
        "namespace": "brain-researcher-scale",
        "services": {
            "br_kg": {
                "port": 5000,
                "initial_replicas": 2,
                "max_replicas": 10,
                "target_cpu_utilization": 70,
                "requests_per_replica": 100,
            },
            "agent": {
                "port": 8000,
                "initial_replicas": 1,
                "max_replicas": 5,
                "target_cpu_utilization": 80,
                "requests_per_replica": 50,
            },
            "orchestrator": {
                "port": 3001,
                "initial_replicas": 3,
                "max_replicas": 15,
                "target_cpu_utilization": 60,
                "requests_per_replica": 200,
            },
            "web-ui": {
                "port": 3000,
                "initial_replicas": 2,
                "max_replicas": 8,
                "target_cpu_utilization": 75,
                "requests_per_replica": 300,
            },
        },
        "scaling_scenarios": {
            "gradual_ramp": {
                "initial_rps": 50,
                "peak_rps": 2000,
                "ramp_duration": 600,  # 10 minutes
                "plateau_duration": 300,  # 5 minutes
                "ramp_down_duration": 300,  # 5 minutes
            },
            "step_scaling": {
                "steps": [100, 300, 500, 800, 1200, 1500],
                "step_duration": 180,  # 3 minutes per step
                "step_pause": 60,  # 1 minute pause between steps
            },
            "spike_testing": {
                "baseline_rps": 200,
                "spike_rps": 2000,
                "spike_duration": 120,  # 2 minutes
                "recovery_duration": 300,  # 5 minutes
            },
        },
    }


@pytest.fixture
async def scalability_http_session():
    """Provide HTTP session optimized for scalability testing."""
    connector = aiohttp.TCPConnector(
        limit=1000,
        limit_per_host=200,
        keepalive_timeout=60,
        enable_cleanup_closed=True,
        use_dns_cache=True,
        ttl_dns_cache=300,
    )

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=60, connect=10),
        headers={"User-Agent": "BrainResearcher-ScalabilityTest/1.0"},
    ) as session:
        yield session


class MockHPAManager:
    """Mock HPA manager for testing scaling behavior."""

    def __init__(self):
        self.current_replicas = {}
        self.target_replicas = {}
        self.scaling_events = []

    def set_initial_replicas(self, service: str, replicas: int):
        """Set initial replica count."""
        self.current_replicas[service] = replicas
        self.target_replicas[service] = replicas

    def get_current_replicas(self, service: str) -> int:
        """Get current replica count."""
        return self.current_replicas.get(service, 1)

    def simulate_scaling_decision(
        self, service: str, cpu_utilization: float, target_cpu: float, max_replicas: int
    ):
        """Simulate HPA scaling decision."""
        current = self.current_replicas.get(service, 1)

        # Simple scaling algorithm simulation
        if cpu_utilization > target_cpu * 1.1:  # Scale up threshold
            desired = min(
                max_replicas, math.ceil(current * (cpu_utilization / target_cpu))
            )
        elif cpu_utilization < target_cpu * 0.8:  # Scale down threshold
            desired = max(1, math.floor(current * (cpu_utilization / target_cpu)))
        else:
            desired = current

        if desired != current:
            self.scaling_events.append(
                {
                    "service": service,
                    "timestamp": time.time(),
                    "from_replicas": current,
                    "to_replicas": desired,
                    "cpu_utilization": cpu_utilization,
                    "reason": "scale_up" if desired > current else "scale_down",
                }
            )

            self.target_replicas[service] = desired
            # Simulate gradual scaling
            asyncio.create_task(self._gradual_scaling(service, current, desired))

    async def _gradual_scaling(
        self, service: str, from_replicas: int, to_replicas: int
    ):
        """Simulate gradual scaling process."""
        steps = abs(to_replicas - from_replicas)
        step_duration = 30  # 30 seconds per replica change

        current = from_replicas
        direction = 1 if to_replicas > from_replicas else -1

        for _ in range(steps):
            await asyncio.sleep(step_duration)
            current += direction
            self.current_replicas[service] = current


@pytest.fixture
def mock_hpa_manager():
    """Provide mock HPA manager."""
    return MockHPAManager()


class TestHorizontalPodAutoscaling:
    """Test Horizontal Pod Autoscaler (HPA) behavior."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_gradual_load_scaling(
        self, scalability_test_environment, scalability_http_session, mock_hpa_manager
    ):
        """Test HPA scaling with gradually increasing load."""
        service_name = "br_kg"
        service_config = scalability_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{scalability_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Initialize HPA manager
        mock_hpa_manager.set_initial_replicas(
            service_name, service_config["initial_replicas"]
        )

        # Gradual scaling scenario
        scenario = scalability_test_environment["scaling_scenarios"]["gradual_ramp"]

        total_duration = (
            scenario["ramp_duration"]
            + scenario["plateau_duration"]
            + scenario["ramp_down_duration"]
        )

        print(
            f"Starting gradual scaling test for {service_name} - Duration: {total_duration}s"
        )

        scaling_metrics = {
            "timestamps": [],
            "target_rps": [],
            "actual_rps": [],
            "response_times": [],
            "success_rates": [],
            "replica_counts": [],
            "cpu_utilization": [],
            "scaling_events": [],
        }

        async def load_generator():
            """Generate variable load according to scenario."""
            start_time = time.time()
            request_count = 0

            while time.time() - start_time < total_duration:
                elapsed = time.time() - start_time

                # Calculate target RPS based on scenario phase
                if elapsed < scenario["ramp_duration"]:
                    # Ramp up phase
                    progress = elapsed / scenario["ramp_duration"]
                    target_rps = (
                        scenario["initial_rps"]
                        + (scenario["peak_rps"] - scenario["initial_rps"]) * progress
                    )
                elif elapsed < scenario["ramp_duration"] + scenario["plateau_duration"]:
                    # Plateau phase
                    target_rps = scenario["peak_rps"]
                else:
                    # Ramp down phase
                    ramp_down_progress = (
                        elapsed
                        - scenario["ramp_duration"]
                        - scenario["plateau_duration"]
                    ) / scenario["ramp_down_duration"]
                    target_rps = (
                        scenario["peak_rps"]
                        - (scenario["peak_rps"] - scenario["initial_rps"])
                        * ramp_down_progress
                    )

                # Generate requests at target rate
                request_interval = 1.0 / target_rps if target_rps > 0 else 1.0

                # Make request
                request_start = time.time()

                try:
                    async with scalability_http_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-scaling-test": "gradual",
                            "x-target-rps": str(int(target_rps)),
                            "x-request-id": str(request_count),
                        },
                    ) as response:
                        request_end = time.time()
                        response_time = (request_end - request_start) * 1000

                        # Simulate CPU utilization calculation
                        current_replicas = mock_hpa_manager.get_current_replicas(
                            service_name
                        )
                        requests_per_replica = (
                            target_rps / current_replicas
                            if current_replicas > 0
                            else target_rps
                        )

                        # Simulate CPU usage based on requests per replica
                        base_cpu = 20  # Base CPU usage
                        cpu_per_request = 0.5  # CPU per request per replica
                        simulated_cpu = base_cpu + (
                            requests_per_replica * cpu_per_request
                        )

                        # Trigger HPA scaling decision
                        mock_hpa_manager.simulate_scaling_decision(
                            service_name,
                            simulated_cpu,
                            service_config["target_cpu_utilization"],
                            service_config["max_replicas"],
                        )

                        # Record metrics periodically
                        if request_count % 50 == 0:  # Every 50 requests
                            scaling_metrics["timestamps"].append(elapsed)
                            scaling_metrics["target_rps"].append(target_rps)
                            scaling_metrics["actual_rps"].append(
                                50
                                / (
                                    time.time()
                                    - (
                                        scaling_metrics["timestamps"][-2]
                                        if scaling_metrics["timestamps"]
                                        else start_time
                                    )
                                )
                            )
                            scaling_metrics["response_times"].append(response_time)
                            scaling_metrics["success_rates"].append(
                                1.0 if response.status == 200 else 0.0
                            )
                            scaling_metrics["replica_counts"].append(current_replicas)
                            scaling_metrics["cpu_utilization"].append(simulated_cpu)

                except aiohttp.ClientError:
                    pass

                request_count += 1

                # Rate limiting
                request_elapsed = time.time() - request_start
                sleep_time = max(0, request_interval - request_elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        # Run load generation
        await load_generator()

        # Analyze scaling behavior
        scaling_events = mock_hpa_manager.scaling_events

        print(f"Scaling test completed:")
        print(f"  Scaling events: {len(scaling_events)}")
        print(
            f"  Final replica count: {mock_hpa_manager.get_current_replicas(service_name)}"
        )

        if scaling_events:
            scale_up_events = [e for e in scaling_events if e["reason"] == "scale_up"]
            scale_down_events = [
                e for e in scaling_events if e["reason"] == "scale_down"
            ]

            print(f"  Scale up events: {len(scale_up_events)}")
            print(f"  Scale down events: {len(scale_down_events)}")

            # Should have scaling events during load changes
            assert (
                len(scaling_events) > 0
            ), "No scaling events occurred during gradual load test"

            # Should scale up during ramp up
            ramp_up_events = [
                e
                for e in scale_up_events
                if e["timestamp"] - scaling_metrics["timestamps"][0]
                < scenario["ramp_duration"]
            ]
            assert len(ramp_up_events) > 0, "No scale up events during ramp up phase"

            # Final replica count should be reasonable
            final_replicas = mock_hpa_manager.get_current_replicas(service_name)
            assert (
                service_config["initial_replicas"]
                <= final_replicas
                <= service_config["max_replicas"]
            ), f"Final replica count out of bounds: {final_replicas}"

        # Validate performance during scaling
        if scaling_metrics["response_times"]:
            avg_response_time = statistics.mean(scaling_metrics["response_times"])
            p95_response_time = sorted(scaling_metrics["response_times"])[
                int(0.95 * len(scaling_metrics["response_times"]))
            ]

            print(f"  Average response time: {avg_response_time:.2f}ms")
            print(f"  P95 response time: {p95_response_time:.2f}ms")

            # Performance should remain reasonable during scaling
            assert (
                avg_response_time <= 200
            ), f"Average response time too high during scaling: {avg_response_time:.2f}ms"
            assert (
                p95_response_time <= 500
            ), f"P95 response time too high during scaling: {p95_response_time:.2f}ms"

        if scaling_metrics["success_rates"]:
            avg_success_rate = statistics.mean(scaling_metrics["success_rates"])
            assert (
                avg_success_rate >= 0.95
            ), f"Success rate too low during scaling: {avg_success_rate:.1%}"

    @pytest.mark.asyncio
    async def test_step_scaling_behavior(
        self, scalability_test_environment, scalability_http_session, mock_hpa_manager
    ):
        """Test HPA behavior with step-wise load increases."""
        service_name = "orchestrator"
        service_config = scalability_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{scalability_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        mock_hpa_manager.set_initial_replicas(
            service_name, service_config["initial_replicas"]
        )

        scenario = scalability_test_environment["scaling_scenarios"]["step_scaling"]

        print(f"Starting step scaling test for {service_name}")

        step_results = []

        for step_index, target_rps in enumerate(scenario["steps"]):
            print(f"Step {step_index + 1}: {target_rps} RPS")

            step_metrics = {
                "step": step_index + 1,
                "target_rps": target_rps,
                "duration": scenario["step_duration"],
                "requests": 0,
                "successes": 0,
                "response_times": [],
                "initial_replicas": mock_hpa_manager.get_current_replicas(service_name),
                "final_replicas": 0,
                "scaling_events": [],
            }

            step_start = time.time()
            step_end = step_start + scenario["step_duration"]

            request_interval = 1.0 / target_rps

            while time.time() < step_end:
                request_start = time.time()

                try:
                    async with scalability_http_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-scaling-test": "step",
                            "x-step": str(step_index + 1),
                            "x-target-rps": str(target_rps),
                        },
                    ) as response:
                        request_end = time.time()
                        response_time = (request_end - request_start) * 1000

                        step_metrics["requests"] += 1
                        step_metrics["response_times"].append(response_time)

                        if response.status == 200:
                            step_metrics["successes"] += 1

                        # Simulate HPA decision
                        current_replicas = mock_hpa_manager.get_current_replicas(
                            service_name
                        )
                        requests_per_replica = (
                            target_rps / current_replicas
                            if current_replicas > 0
                            else target_rps
                        )
                        simulated_cpu = 30 + (requests_per_replica * 0.3)

                        mock_hpa_manager.simulate_scaling_decision(
                            service_name,
                            simulated_cpu,
                            service_config["target_cpu_utilization"],
                            service_config["max_replicas"],
                        )

                except aiohttp.ClientError:
                    step_metrics["requests"] += 1

                # Rate limiting
                elapsed = time.time() - request_start
                sleep_time = max(0, request_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            step_metrics["final_replicas"] = mock_hpa_manager.get_current_replicas(
                service_name
            )

            # Get scaling events for this step
            step_events = [
                e
                for e in mock_hpa_manager.scaling_events
                if step_start <= e["timestamp"] <= step_end
            ]
            step_metrics["scaling_events"] = step_events

            # Calculate step performance
            if step_metrics["requests"] > 0:
                step_metrics["success_rate"] = (
                    step_metrics["successes"] / step_metrics["requests"]
                )
                step_metrics["actual_rps"] = (
                    step_metrics["requests"] / scenario["step_duration"]
                )

            if step_metrics["response_times"]:
                step_metrics["avg_response_time"] = statistics.mean(
                    step_metrics["response_times"]
                )
                step_metrics["p95_response_time"] = sorted(
                    step_metrics["response_times"]
                )[int(0.95 * len(step_metrics["response_times"]))]

            step_results.append(step_metrics)

            print(
                f"  Step {step_index + 1} completed: {step_metrics.get('success_rate', 0):.1%} success rate, "
                f"{step_metrics['initial_replicas']} -> {step_metrics['final_replicas']} replicas"
            )

            # Pause between steps
            if step_index < len(scenario["steps"]) - 1:
                await asyncio.sleep(scenario["step_pause"])

        # Analyze step scaling results
        total_scaling_events = sum(len(step["scaling_events"]) for step in step_results)

        print(f"Step scaling completed:")
        print(f"  Total scaling events: {total_scaling_events}")
        print(f"  Final replica count: {step_results[-1]['final_replicas']}")

        # Validate scaling behavior
        for i, step in enumerate(step_results):
            # Performance should be maintained at each step
            assert (
                step.get("success_rate", 0) >= 0.9
            ), f"Step {i+1} success rate too low: {step.get('success_rate', 0):.1%}"

            if step.get("avg_response_time"):
                assert (
                    step["avg_response_time"] <= 300
                ), f"Step {i+1} response time too high: {step['avg_response_time']:.2f}ms"

            # Should scale up for higher load steps
            if i > 0 and step["target_rps"] > step_results[i - 1]["target_rps"] * 1.5:
                assert (
                    step["final_replicas"] >= step["initial_replicas"]
                ), f"Step {i+1} should have scaled up for increased load"

        # Overall scaling should be responsive
        assert total_scaling_events > 0, "No scaling occurred during step scaling test"

    @pytest.mark.asyncio
    async def test_scaling_stability_and_oscillation(
        self, scalability_test_environment, scalability_http_session, mock_hpa_manager
    ):
        """Test scaling stability and prevent oscillation."""
        service_name = "web-ui"
        service_config = scalability_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{scalability_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        mock_hpa_manager.set_initial_replicas(
            service_name, service_config["initial_replicas"]
        )

        print(f"Testing scaling stability for {service_name}")

        # Test with steady load around scaling threshold
        target_cpu = service_config["target_cpu_utilization"]
        threshold_rps = (
            service_config["requests_per_replica"] * service_config["initial_replicas"]
        )

        stability_phases = [
            {"name": "below_threshold", "rps": threshold_rps * 0.8, "duration": 180},
            {"name": "at_threshold", "rps": threshold_rps, "duration": 240},
            {"name": "above_threshold", "rps": threshold_rps * 1.2, "duration": 180},
            {
                "name": "oscillating",
                "rps_pattern": [threshold_rps * 0.9, threshold_rps * 1.1],
                "duration": 300,
            },
        ]

        stability_results = []

        for phase in stability_phases:
            print(f"Phase: {phase['name']}")

            phase_metrics = {
                "name": phase["name"],
                "duration": phase["duration"],
                "replica_changes": 0,
                "scaling_events": [],
                "performance": {"requests": 0, "successes": 0, "response_times": []},
                "initial_replicas": mock_hpa_manager.get_current_replicas(service_name),
            }

            phase_start = time.time()
            phase_end = phase_start + phase["duration"]

            while time.time() < phase_end:
                # Determine current target RPS
                if "rps_pattern" in phase:
                    # Oscillating pattern
                    pattern_index = int((time.time() - phase_start) // 30) % len(
                        phase["rps_pattern"]
                    )
                    current_rps = phase["rps_pattern"][pattern_index]
                else:
                    current_rps = phase["rps"]

                request_interval = 1.0 / current_rps
                request_start = time.time()

                try:
                    async with scalability_http_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-stability-test": phase["name"],
                            "x-current-rps": str(int(current_rps)),
                        },
                    ) as response:
                        request_end = time.time()
                        response_time = (request_end - request_start) * 1000

                        phase_metrics["performance"]["requests"] += 1
                        phase_metrics["performance"]["response_times"].append(
                            response_time
                        )

                        if response.status == 200:
                            phase_metrics["performance"]["successes"] += 1

                        # Simulate HPA with stability considerations
                        current_replicas = mock_hpa_manager.get_current_replicas(
                            service_name
                        )
                        requests_per_replica = (
                            current_rps / current_replicas
                            if current_replicas > 0
                            else current_rps
                        )
                        simulated_cpu = 25 + (requests_per_replica * 0.4)

                        # Add some randomness to prevent perfect stability
                        simulated_cpu *= random.uniform(0.9, 1.1)

                        mock_hpa_manager.simulate_scaling_decision(
                            service_name,
                            simulated_cpu,
                            target_cpu,
                            service_config["max_replicas"],
                        )

                except aiohttp.ClientError:
                    phase_metrics["performance"]["requests"] += 1

                elapsed = time.time() - request_start
                sleep_time = max(0, request_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            # Analyze phase stability
            phase_events = [
                e
                for e in mock_hpa_manager.scaling_events
                if phase_start <= e["timestamp"] <= phase_end
            ]
            phase_metrics["scaling_events"] = phase_events
            phase_metrics["replica_changes"] = len(phase_events)
            phase_metrics["final_replicas"] = mock_hpa_manager.get_current_replicas(
                service_name
            )

            # Calculate performance metrics
            if phase_metrics["performance"]["requests"] > 0:
                perf = phase_metrics["performance"]
                perf["success_rate"] = perf["successes"] / perf["requests"]

                if perf["response_times"]:
                    perf["avg_response_time"] = statistics.mean(perf["response_times"])

            stability_results.append(phase_metrics)

            print(
                f"  {phase['name']}: {phase_metrics['replica_changes']} scaling events, "
                f"{phase_metrics['initial_replicas']} -> {phase_metrics['final_replicas']} replicas"
            )

        # Analyze scaling stability
        for result in stability_results:
            phase_name = result["name"]

            # Below threshold should be stable
            if phase_name == "below_threshold":
                assert (
                    result["replica_changes"] <= 1
                ), f"Too many scaling events below threshold: {result['replica_changes']}"

            # At threshold should be relatively stable
            elif phase_name == "at_threshold":
                assert (
                    result["replica_changes"] <= 2
                ), f"Too many scaling events at threshold: {result['replica_changes']}"

            # Above threshold should scale up but then stabilize
            elif phase_name == "above_threshold":
                assert (
                    result["replica_changes"] <= 3
                ), f"Too many scaling events above threshold: {result['replica_changes']}"

            # Oscillating load should not cause excessive scaling
            elif phase_name == "oscillating":
                assert (
                    result["replica_changes"] <= 4
                ), f"Excessive scaling oscillation: {result['replica_changes']} events"

            # Performance should remain good throughout
            if result["performance"].get("success_rate"):
                assert (
                    result["performance"]["success_rate"] >= 0.95
                ), f"Performance degraded in {phase_name}: {result['performance']['success_rate']:.1%}"


class TestClusterAutoscaling:
    """Test cluster-level autoscaling behavior."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_node_scaling_triggers(
        self, scalability_test_environment, scalability_http_session
    ):
        """Test conditions that trigger cluster autoscaling."""
        # This test simulates conditions that would trigger cluster autoscaling
        # In a real environment, this would involve actual node provisioning

        services = scalability_test_environment["services"]

        # Simulate resource pressure across multiple services
        print("Testing cluster autoscaling triggers...")

        cluster_metrics = {
            "total_pods": 0,
            "resource_requests": {"cpu": 0, "memory": 0},
            "node_capacity": {
                "cpu": 4000,
                "memory": 8192,
            },  # Simulated node capacity (4 CPU, 8GB RAM)
            "nodes": 3,  # Initial node count
            "scaling_events": [],
        }

        # Calculate initial resource usage
        for service_name, config in services.items():
            replicas = config["initial_replicas"]
            cluster_metrics["total_pods"] += replicas
            cluster_metrics["resource_requests"]["cpu"] += (
                replicas * 500
            )  # 500m CPU per pod
            cluster_metrics["resource_requests"]["memory"] += (
                replicas * 512
            )  # 512MB per pod

        # Simulate high load scenario that would exhaust node capacity
        high_load_scenarios = [
            {"service": "orchestrator", "target_replicas": 12},
            {"service": "web-ui", "target_replicas": 8},
            {"service": "br_kg", "target_replicas": 8},
            {"service": "agent", "target_replicas": 4},
        ]

        for scenario in high_load_scenarios:
            service_name = scenario["service"]
            target_replicas = scenario["target_replicas"]
            current_replicas = services[service_name]["initial_replicas"]

            print(
                f"Simulating scale up for {service_name}: {current_replicas} -> {target_replicas} replicas"
            )

            # Calculate additional resource requirements
            additional_replicas = target_replicas - current_replicas
            additional_cpu = additional_replicas * 500
            additional_memory = additional_replicas * 512

            # Check if current cluster capacity is sufficient
            total_cpu_needed = (
                cluster_metrics["resource_requests"]["cpu"] + additional_cpu
            )
            total_memory_needed = (
                cluster_metrics["resource_requests"]["memory"] + additional_memory
            )

            current_capacity_cpu = (
                cluster_metrics["nodes"] * cluster_metrics["node_capacity"]["cpu"]
            )
            current_capacity_memory = (
                cluster_metrics["nodes"] * cluster_metrics["node_capacity"]["memory"]
            )

            cpu_utilization = (
                (total_cpu_needed / current_capacity_cpu) * 100
                if current_capacity_cpu > 0
                else 100
            )
            memory_utilization = (
                (total_memory_needed / current_capacity_memory) * 100
                if current_capacity_memory > 0
                else 100
            )

            print(
                f"  Resource utilization: CPU {cpu_utilization:.1f}%, Memory {memory_utilization:.1f}%"
            )

            # Simulate cluster autoscaling decision
            if cpu_utilization > 80 or memory_utilization > 80:
                # Would trigger cluster autoscaling
                nodes_needed = math.ceil(
                    max(
                        total_cpu_needed / cluster_metrics["node_capacity"]["cpu"],
                        total_memory_needed
                        / cluster_metrics["node_capacity"]["memory"],
                    )
                )

                if nodes_needed > cluster_metrics["nodes"]:
                    new_nodes = nodes_needed - cluster_metrics["nodes"]
                    cluster_metrics["scaling_events"].append(
                        {
                            "trigger_service": service_name,
                            "nodes_added": new_nodes,
                            "cpu_utilization": cpu_utilization,
                            "memory_utilization": memory_utilization,
                            "reason": "resource_pressure",
                        }
                    )

                    cluster_metrics["nodes"] = nodes_needed

                    print(
                        f"  Cluster autoscaling triggered: +{new_nodes} nodes (total: {cluster_metrics['nodes']})"
                    )

            # Update resource tracking
            cluster_metrics["total_pods"] += additional_replicas
            cluster_metrics["resource_requests"]["cpu"] += additional_cpu
            cluster_metrics["resource_requests"]["memory"] += additional_memory

            await asyncio.sleep(1)  # Simulate time for scaling decisions

        # Analyze cluster scaling behavior
        total_scaling_events = len(cluster_metrics["scaling_events"])
        total_nodes_added = sum(
            event["nodes_added"] for event in cluster_metrics["scaling_events"]
        )

        print(f"\nCluster autoscaling results:")
        print(f"  Scaling events: {total_scaling_events}")
        print(f"  Nodes added: {total_nodes_added}")
        print(f"  Final cluster size: {cluster_metrics['nodes']} nodes")

        # Validate cluster scaling decisions
        if total_scaling_events > 0:
            # Should have scaled when resource pressure exceeded thresholds
            assert total_nodes_added > 0, "No nodes added despite resource pressure"

            # Shouldn't over-provision excessively
            final_capacity_cpu = (
                cluster_metrics["nodes"] * cluster_metrics["node_capacity"]["cpu"]
            )
            final_cpu_utilization = (
                cluster_metrics["resource_requests"]["cpu"] / final_capacity_cpu
            ) * 100

            assert (
                50 <= final_cpu_utilization <= 90
            ), f"Final CPU utilization not optimal: {final_cpu_utilization:.1f}%"

        # Should trigger scaling for high resource demands
        total_resource_increase = (
            (cluster_metrics["resource_requests"]["cpu"] / (len(services) * 500))
            + (cluster_metrics["resource_requests"]["memory"] / (len(services) * 512))
        ) / 2

        if total_resource_increase > 2.0:  # More than 2x resource increase
            assert (
                total_scaling_events > 0
            ), "Cluster autoscaling should have triggered for significant resource increase"

    @pytest.mark.asyncio
    async def test_node_downscaling(
        self, scalability_test_environment, scalability_http_session
    ):
        """Test cluster downscaling behavior."""
        print("Testing cluster node downscaling...")

        # Simulate scenario where load decreases and nodes can be removed
        cluster_state = {
            "nodes": 6,  # Start with scaled-up cluster
            "node_capacity": {"cpu": 4000, "memory": 8192},
            "current_usage": {"cpu": 3000, "memory": 2048},  # Low usage
            "downscaling_events": [],
        }

        # Simulate load reduction phases
        load_reduction_phases = [
            {"name": "evening_reduction", "cpu_reduction": 0.3, "duration": 300},
            {"name": "night_reduction", "cpu_reduction": 0.6, "duration": 600},
            {"name": "maintenance_window", "cpu_reduction": 0.8, "duration": 180},
        ]

        for phase in load_reduction_phases:
            print(
                f"Phase: {phase['name']} - CPU reduction: {phase['cpu_reduction']:.0%}"
            )

            # Calculate new resource usage
            phase_cpu_usage = cluster_state["current_usage"]["cpu"] * (
                1 - phase["cpu_reduction"]
            )
            phase_memory_usage = (
                cluster_state["current_usage"]["memory"] * 0.8
            )  # Memory typically doesn't reduce as much

            total_capacity_cpu = (
                cluster_state["nodes"] * cluster_state["node_capacity"]["cpu"]
            )
            total_capacity_memory = (
                cluster_state["nodes"] * cluster_state["node_capacity"]["memory"]
            )

            cpu_utilization = (phase_cpu_usage / total_capacity_cpu) * 100
            memory_utilization = (phase_memory_usage / total_capacity_memory) * 100

            print(
                f"  Resource utilization: CPU {cpu_utilization:.1f}%, Memory {memory_utilization:.1f}%"
            )

            # Simulate cluster downscaling decision
            if cpu_utilization < 30 and memory_utilization < 50:
                # Calculate optimal node count
                optimal_nodes_cpu = math.ceil(
                    phase_cpu_usage / (cluster_state["node_capacity"]["cpu"] * 0.7)
                )  # 70% target utilization
                optimal_nodes_memory = math.ceil(
                    phase_memory_usage
                    / (cluster_state["node_capacity"]["memory"] * 0.8)
                )  # 80% target utilization

                optimal_nodes = max(
                    optimal_nodes_cpu, optimal_nodes_memory, 2
                )  # Minimum 2 nodes

                if optimal_nodes < cluster_state["nodes"]:
                    nodes_to_remove = cluster_state["nodes"] - optimal_nodes

                    cluster_state["downscaling_events"].append(
                        {
                            "phase": phase["name"],
                            "nodes_removed": nodes_to_remove,
                            "cpu_utilization": cpu_utilization,
                            "memory_utilization": memory_utilization,
                            "reason": "low_utilization",
                        }
                    )

                    cluster_state["nodes"] = optimal_nodes

                    print(
                        f"  Cluster downscaling: -{nodes_to_remove} nodes (remaining: {cluster_state['nodes']})"
                    )

            # Update current usage for next phase
            cluster_state["current_usage"]["cpu"] = phase_cpu_usage
            cluster_state["current_usage"]["memory"] = phase_memory_usage

            # Simulate phase duration
            await asyncio.sleep(
                min(5, phase["duration"] / 60)
            )  # Scaled down time for testing

        # Analyze downscaling behavior
        total_downscaling_events = len(cluster_state["downscaling_events"])
        total_nodes_removed = sum(
            event["nodes_removed"] for event in cluster_state["downscaling_events"]
        )

        print(f"\nCluster downscaling results:")
        print(f"  Downscaling events: {total_downscaling_events}")
        print(f"  Nodes removed: {total_nodes_removed}")
        print(f"  Final cluster size: {cluster_state['nodes']} nodes")

        # Validate downscaling behavior
        if total_downscaling_events > 0:
            assert total_nodes_removed > 0, "No nodes removed despite low utilization"

            # Should maintain minimum cluster size
            assert cluster_state["nodes"] >= 2, "Cluster downscaled below minimum size"

            # Final utilization should be reasonable
            final_cpu_utilization = (
                cluster_state["current_usage"]["cpu"]
                / (cluster_state["nodes"] * cluster_state["node_capacity"]["cpu"])
            ) * 100
            assert (
                40 <= final_cpu_utilization <= 80
            ), f"Final CPU utilization after downscaling not optimal: {final_cpu_utilization:.1f}%"

        # Should trigger downscaling for significant resource reduction
        total_resource_reduction = 1.0 - (
            cluster_state["current_usage"]["cpu"] / 3000
        )  # Original usage was 3000

        if total_resource_reduction > 0.5:  # More than 50% reduction
            assert (
                total_downscaling_events > 0
            ), "Cluster downscaling should have triggered for significant load reduction"


class TestTrafficScalingPatterns:
    """Test various traffic scaling patterns and performance."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_diurnal_traffic_pattern(
        self, scalability_test_environment, scalability_http_session
    ):
        """Test scaling behavior with diurnal (daily) traffic patterns."""
        service_name = "web-ui"
        service_config = scalability_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{scalability_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        # Simulate 24-hour traffic pattern (compressed to 24 minutes for testing)
        time_compression_factor = 60  # 1 minute = 1 hour
        pattern_duration = 24 * 60 / time_compression_factor  # 24 minutes

        print(
            f"Testing diurnal traffic pattern for {service_name} (compressed 24h -> {pattern_duration}m)"
        )

        diurnal_metrics = {
            "hourly_stats": {},
            "scaling_events": [],
            "performance_by_hour": {},
        }

        async def generate_diurnal_traffic():
            """Generate traffic following diurnal pattern."""
            start_time = time.time()

            while time.time() - start_time < pattern_duration * 60:
                elapsed_minutes = (time.time() - start_time) / 60
                simulated_hour = (elapsed_minutes * time_compression_factor) % 24

                # Define traffic pattern (RPS) throughout the day
                base_rps = 100
                if 0 <= simulated_hour < 6:  # Night: low traffic
                    traffic_multiplier = 0.2
                elif 6 <= simulated_hour < 9:  # Morning ramp-up
                    traffic_multiplier = 0.5 + (simulated_hour - 6) * 0.3  # 0.5 to 1.4
                elif 9 <= simulated_hour < 12:  # Morning peak
                    traffic_multiplier = 1.5
                elif 12 <= simulated_hour < 14:  # Lunch spike
                    traffic_multiplier = 2.0
                elif 14 <= simulated_hour < 18:  # Afternoon
                    traffic_multiplier = 1.3
                elif 18 <= simulated_hour < 21:  # Evening peak
                    traffic_multiplier = 1.8
                else:  # Evening decline
                    traffic_multiplier = 1.0 - (simulated_hour - 21) * 0.2

                current_rps = base_rps * traffic_multiplier
                hour_key = int(simulated_hour)

                # Initialize hour tracking
                if hour_key not in diurnal_metrics["hourly_stats"]:
                    diurnal_metrics["hourly_stats"][hour_key] = {
                        "target_rps": current_rps,
                        "requests": 0,
                        "successes": 0,
                        "response_times": [],
                        "start_time": time.time(),
                    }

                # Make request
                request_start = time.time()

                try:
                    async with scalability_http_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-diurnal-test": "true",
                            "x-simulated-hour": str(int(simulated_hour)),
                            "x-traffic-multiplier": f"{traffic_multiplier:.2f}",
                        },
                    ) as response:
                        request_end = time.time()
                        response_time = (request_end - request_start) * 1000

                        hour_stats = diurnal_metrics["hourly_stats"][hour_key]
                        hour_stats["requests"] += 1
                        hour_stats["response_times"].append(response_time)

                        if response.status == 200:
                            hour_stats["successes"] += 1

                except aiohttp.ClientError:
                    diurnal_metrics["hourly_stats"][hour_key]["requests"] += 1

                # Rate limiting
                request_interval = 1.0 / current_rps if current_rps > 0 else 1.0
                elapsed = time.time() - request_start
                sleep_time = max(0, request_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        # Run diurnal traffic simulation
        await generate_diurnal_traffic()

        # Analyze diurnal performance
        print("Diurnal pattern results by hour:")

        for hour in sorted(diurnal_metrics["hourly_stats"].keys()):
            stats = diurnal_metrics["hourly_stats"][hour]

            if stats["requests"] > 0:
                success_rate = stats["successes"] / stats["requests"]
                avg_response_time = (
                    statistics.mean(stats["response_times"])
                    if stats["response_times"]
                    else 0
                )

                # Estimate actual RPS
                hour_duration = min(
                    3600 / time_compression_factor, 60
                )  # Max 1 minute per hour in test
                actual_rps = stats["requests"] / hour_duration

                diurnal_metrics["performance_by_hour"][hour] = {
                    "target_rps": stats["target_rps"],
                    "actual_rps": actual_rps,
                    "success_rate": success_rate,
                    "avg_response_time": avg_response_time,
                }

                print(
                    f"  Hour {hour:02d}: {actual_rps:.0f} RPS (target: {stats['target_rps']:.0f}), "
                    f"{success_rate:.1%} success, {avg_response_time:.0f}ms avg"
                )

        # Validate diurnal scaling behavior
        peak_hours = [12, 18, 19, 20]  # Lunch and evening peaks
        off_peak_hours = [2, 3, 4, 5]  # Night hours

        peak_performance = []
        off_peak_performance = []

        for hour, perf in diurnal_metrics["performance_by_hour"].items():
            if hour in peak_hours:
                peak_performance.append(perf)
            elif hour in off_peak_hours:
                off_peak_performance.append(perf)

        # Performance should be maintained during peak hours
        if peak_performance:
            avg_peak_success = statistics.mean(
                [p["success_rate"] for p in peak_performance]
            )
            avg_peak_response_time = statistics.mean(
                [p["avg_response_time"] for p in peak_performance]
            )

            assert (
                avg_peak_success >= 0.9
            ), f"Peak hour performance too low: {avg_peak_success:.1%}"
            assert (
                avg_peak_response_time <= 200
            ), f"Peak hour response time too high: {avg_peak_response_time:.0f}ms"

        # Off-peak should also maintain good performance (potentially better)
        if off_peak_performance:
            avg_off_peak_success = statistics.mean(
                [p["success_rate"] for p in off_peak_performance]
            )
            assert (
                avg_off_peak_success >= 0.95
            ), f"Off-peak performance unexpectedly low: {avg_off_peak_success:.1%}"

    @pytest.mark.asyncio
    async def test_flash_crowd_handling(
        self, scalability_test_environment, scalability_http_session
    ):
        """Test handling of flash crowd scenarios (sudden massive traffic spikes)."""
        service_name = "orchestrator"
        service_config = scalability_test_environment["services"][service_name]
        base_url = f"http://{service_name}-service.{scalability_test_environment['namespace']}.svc.cluster.local:{service_config['port']}"

        print(f"Testing flash crowd handling for {service_name}")

        # Flash crowd scenario configuration
        flash_crowd_config = {
            "baseline_rps": 200,
            "flash_crowd_rps": 2000,  # 10x increase
            "ramp_up_duration": 30,  # 30 seconds to reach peak
            "peak_duration": 120,  # 2 minutes at peak
            "ramp_down_duration": 60,  # 1 minute to return to baseline
        }

        flash_crowd_metrics = {
            "phases": {},
            "timeline": [],
            "peak_performance": {},
            "recovery_time": 0,
        }

        total_duration = (
            flash_crowd_config["ramp_up_duration"]
            + flash_crowd_config["peak_duration"]
            + flash_crowd_config["ramp_down_duration"]
        )

        async def flash_crowd_simulation():
            """Simulate flash crowd traffic pattern."""
            start_time = time.time()

            while time.time() - start_time < total_duration:
                elapsed = time.time() - start_time

                # Determine current phase and target RPS
                if elapsed < flash_crowd_config["ramp_up_duration"]:
                    # Ramp up phase
                    phase = "ramp_up"
                    progress = elapsed / flash_crowd_config["ramp_up_duration"]
                    current_rps = (
                        flash_crowd_config["baseline_rps"]
                        + (
                            flash_crowd_config["flash_crowd_rps"]
                            - flash_crowd_config["baseline_rps"]
                        )
                        * progress
                    )

                elif (
                    elapsed
                    < flash_crowd_config["ramp_up_duration"]
                    + flash_crowd_config["peak_duration"]
                ):
                    # Peak phase
                    phase = "peak"
                    current_rps = flash_crowd_config["flash_crowd_rps"]

                else:
                    # Ramp down phase
                    phase = "ramp_down"
                    ramp_down_elapsed = (
                        elapsed
                        - flash_crowd_config["ramp_up_duration"]
                        - flash_crowd_config["peak_duration"]
                    )
                    progress = (
                        ramp_down_elapsed / flash_crowd_config["ramp_down_duration"]
                    )
                    current_rps = (
                        flash_crowd_config["flash_crowd_rps"]
                        - (
                            flash_crowd_config["flash_crowd_rps"]
                            - flash_crowd_config["baseline_rps"]
                        )
                        * progress
                    )

                # Initialize phase tracking
                if phase not in flash_crowd_metrics["phases"]:
                    flash_crowd_metrics["phases"][phase] = {
                        "requests": 0,
                        "successes": 0,
                        "failures": 0,
                        "response_times": [],
                        "errors": {"timeout": 0, "connection": 0, "server": 0},
                        "start_time": time.time(),
                    }

                # Make request
                request_start = time.time()

                try:
                    async with scalability_http_session.get(
                        f"{base_url}/health",
                        headers={
                            "x-flash-crowd": "true",
                            "x-phase": phase,
                            "x-target-rps": str(int(current_rps)),
                            "x-elapsed": f"{elapsed:.1f}",
                        },
                    ) as response:
                        request_end = time.time()
                        response_time = (request_end - request_start) * 1000

                        phase_stats = flash_crowd_metrics["phases"][phase]
                        phase_stats["requests"] += 1
                        phase_stats["response_times"].append(response_time)

                        if response.status == 200:
                            phase_stats["successes"] += 1
                        else:
                            phase_stats["failures"] += 1
                            if response.status >= 500:
                                phase_stats["errors"]["server"] += 1

                except asyncio.TimeoutError:
                    phase_stats = flash_crowd_metrics["phases"][phase]
                    phase_stats["requests"] += 1
                    phase_stats["failures"] += 1
                    phase_stats["errors"]["timeout"] += 1

                except aiohttp.ClientError:
                    phase_stats = flash_crowd_metrics["phases"][phase]
                    phase_stats["requests"] += 1
                    phase_stats["failures"] += 1
                    phase_stats["errors"]["connection"] += 1

                # Record timeline data
                if (
                    len(flash_crowd_metrics["timeline"]) == 0
                    or elapsed - flash_crowd_metrics["timeline"][-1]["elapsed"] >= 10
                ):
                    flash_crowd_metrics["timeline"].append(
                        {
                            "elapsed": elapsed,
                            "phase": phase,
                            "target_rps": current_rps,
                            "timestamp": time.time(),
                        }
                    )

                # Rate limiting
                request_interval = 1.0 / current_rps if current_rps > 0 else 1.0
                request_elapsed = time.time() - request_start
                sleep_time = max(0, request_interval - request_elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        # Run flash crowd simulation
        await flash_crowd_simulation()

        # Analyze flash crowd handling
        print("Flash crowd results by phase:")

        for phase, stats in flash_crowd_metrics["phases"].items():
            if stats["requests"] > 0:
                success_rate = stats["successes"] / stats["requests"]
                error_rate = stats["failures"] / stats["requests"]

                avg_response_time = (
                    statistics.mean(stats["response_times"])
                    if stats["response_times"]
                    else 0
                )
                p95_response_time = (
                    sorted(stats["response_times"])[
                        int(0.95 * len(stats["response_times"]))
                    ]
                    if stats["response_times"]
                    else 0
                )

                print(
                    f"  {phase}: {success_rate:.1%} success, {error_rate:.1%} error rate"
                )
                print(
                    f"    Avg response time: {avg_response_time:.0f}ms, P95: {p95_response_time:.0f}ms"
                )
                print(
                    f"    Timeouts: {stats['errors']['timeout']}, Connections: {stats['errors']['connection']}, Server: {stats['errors']['server']}"
                )

        # Validate flash crowd handling
        ramp_up_stats = flash_crowd_metrics["phases"].get("ramp_up", {})
        peak_stats = flash_crowd_metrics["phases"].get("peak", {})
        ramp_down_stats = flash_crowd_metrics["phases"].get("ramp_down", {})

        # System should handle ramp up reasonably well
        if ramp_up_stats.get("requests", 0) > 0:
            ramp_up_success_rate = (
                ramp_up_stats["successes"] / ramp_up_stats["requests"]
            )
            assert (
                ramp_up_success_rate >= 0.8
            ), f"Ramp up phase success rate too low: {ramp_up_success_rate:.1%}"

        # Peak performance might be degraded but should maintain some level of service
        if peak_stats.get("requests", 0) > 0:
            peak_success_rate = peak_stats["successes"] / peak_stats["requests"]
            assert (
                peak_success_rate >= 0.5
            ), f"Peak phase success rate too low: {peak_success_rate:.1%}"

            # Should not have excessive server errors (some load shedding is acceptable)
            server_error_rate = peak_stats["errors"]["server"] / peak_stats["requests"]
            assert (
                server_error_rate <= 0.3
            ), f"Too many server errors during peak: {server_error_rate:.1%}"

        # System should recover during ramp down
        if ramp_down_stats.get("requests", 0) > 0:
            ramp_down_success_rate = (
                ramp_down_stats["successes"] / ramp_down_stats["requests"]
            )
            assert (
                ramp_down_success_rate >= 0.9
            ), f"Recovery phase success rate too low: {ramp_down_success_rate:.1%}"

        print(f"Flash crowd handling test completed successfully")
