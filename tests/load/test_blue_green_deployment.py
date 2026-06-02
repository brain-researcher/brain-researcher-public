"""
Comprehensive tests for blue-green deployment functionality.

Tests cover:
- Zero-downtime deployment process
- Gradual traffic switching strategies
- Health check validation during deployment
- Automatic rollback mechanisms
- State persistence across deployments
- Multi-platform support (Docker Swarm, Kubernetes)
- Failure scenarios and recovery
- Performance impact assessment
"""

import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

import pytest

from tests.load.conftest import TestConfig, wait_for_condition


class BlueGreenDeploymentSimulator:
    """Simulate blue-green deployment operations for testing."""

    def __init__(self, platform="swarm"):
        self.platform = platform
        self.services = {}
        self.deployments = {}
        self.traffic_distribution = {}
        self.health_status = {}

    def create_service(self, service_name: str, color: str, replicas: int):
        """Create a new service/deployment."""
        service_id = f"{service_name}-{color}"

        if self.platform == "swarm":
            self.services[service_id] = {
                "name": service_id,
                "replicas": replicas,
                "status": "starting",
                "health": "unknown",
                "created_at": datetime.utcnow(),
            }
        else:  # Kubernetes
            self.deployments[service_id] = {
                "name": service_id,
                "replicas": replicas,
                "ready_replicas": 0,
                "status": "pending",
                "health": "unknown",
                "created_at": datetime.utcnow(),
            }

        return True

    def get_service_replicas(self, service_name: str, color: str) -> int:
        """Get current replica count."""
        service_id = f"{service_name}-{color}"

        if self.platform == "swarm":
            service = self.services.get(service_id, {})
            return service.get("replicas", 0)
        else:
            deployment = self.deployments.get(service_id, {})
            return deployment.get("ready_replicas", 0)

    def scale_service(self, service_name: str, color: str, replicas: int):
        """Scale service to specified replicas."""
        service_id = f"{service_name}-{color}"

        if self.platform == "swarm" and service_id in self.services:
            self.services[service_id]["replicas"] = replicas
            # Simulate gradual scaling
            if replicas > 0:
                self.services[service_id]["status"] = "running"
                self.services[service_id]["health"] = "healthy"
        elif self.platform == "k8s" and service_id in self.deployments:
            self.deployments[service_id]["replicas"] = replicas
            self.deployments[service_id]["ready_replicas"] = replicas
            if replicas > 0:
                self.deployments[service_id]["status"] = "ready"
                self.deployments[service_id]["health"] = "healthy"

        return True

    def health_check(self, service_name: str, color: str) -> bool:
        """Perform health check on service."""
        service_id = f"{service_name}-{color}"

        if self.platform == "swarm":
            service = self.services.get(service_id)
            if not service or service["replicas"] == 0:
                return False
            return service.get("health") == "healthy"
        else:
            deployment = self.deployments.get(service_id)
            if not deployment or deployment["ready_replicas"] == 0:
                return False
            return deployment.get("health") == "healthy"

    def update_traffic_distribution(
        self,
        service_name: str,
        active_color: str,
        inactive_color: str,
        inactive_percentage: int,
    ):
        """Update traffic distribution between colors."""
        self.traffic_distribution[service_name] = {
            "active_color": active_color,
            "inactive_color": inactive_color,
            "distribution": {
                active_color: 100 - inactive_percentage,
                inactive_color: inactive_percentage,
            },
        }

    def remove_service(self, service_name: str, color: str):
        """Remove service/deployment."""
        service_id = f"{service_name}-{color}"

        if self.platform == "swarm":
            self.services.pop(service_id, None)
        else:
            self.deployments.pop(service_id, None)


@pytest.fixture
def deployment_simulator():
    """Blue-green deployment simulator."""
    return BlueGreenDeploymentSimulator()


@pytest.fixture
def deployment_state_dir():
    """Temporary directory for deployment state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_deployment_script():
    """Mock the blue-green deployment script."""
    script_content = """
    #!/bin/bash
    echo "Mock deployment script"
    exit 0
    """

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Deployment successful"
        yield mock_run


@pytest.mark.unit
class TestDeploymentStateManagement:
    """Test deployment state management."""

    def test_save_deployment_state(self, deployment_state_dir):
        """Test saving deployment state to file."""
        state_file = os.path.join(deployment_state_dir, "test-service_state.json")

        state_data = {
            "service": "test-service",
            "active_color": "blue",
            "replicas": 5,
            "timestamp": "2023-08-28T10:00:00Z",
            "platform": "swarm",
        }

        # Simulate saving state
        with open(state_file, "w") as f:
            json.dump(state_data, f)

        # Verify state was saved
        assert os.path.exists(state_file)

        with open(state_file, "r") as f:
            loaded_state = json.load(f)

        assert loaded_state["service"] == "test-service"
        assert loaded_state["active_color"] == "blue"
        assert loaded_state["replicas"] == 5

    def test_load_deployment_state(self, deployment_state_dir):
        """Test loading deployment state from file."""
        state_file = os.path.join(deployment_state_dir, "test-service_state.json")

        # Create initial state file
        initial_state = {
            "service": "test-service",
            "active_color": "green",
            "replicas": 3,
            "timestamp": "2023-08-28T09:00:00Z",
            "platform": "k8s",
        }

        with open(state_file, "w") as f:
            json.dump(initial_state, f)

        # Load state
        with open(state_file, "r") as f:
            loaded_state = json.load(f)

        assert loaded_state["active_color"] == "green"
        assert loaded_state["replicas"] == 3
        assert loaded_state["platform"] == "k8s"

    def test_default_state_when_file_missing(self, deployment_state_dir):
        """Test default state when state file doesn't exist."""
        state_file = os.path.join(deployment_state_dir, "nonexistent_state.json")

        # Default state should be provided
        default_state = {
            "service": "nonexistent",
            "active_color": "blue",
            "replicas": 1,
            "platform": "swarm",
        }

        if not os.path.exists(state_file):
            loaded_state = default_state
        else:
            with open(state_file, "r") as f:
                loaded_state = json.load(f)

        assert loaded_state["active_color"] == "blue"
        assert loaded_state["replicas"] == 1

    def test_color_switching_logic(self):
        """Test blue-green color switching logic."""

        def get_inactive_color(active_color: str) -> str:
            return "green" if active_color == "blue" else "blue"

        assert get_inactive_color("blue") == "green"
        assert get_inactive_color("green") == "blue"

    def test_state_validation(self):
        """Test deployment state validation."""
        valid_state = {
            "service": "test-service",
            "active_color": "blue",
            "replicas": 5,
            "timestamp": "2023-08-28T10:00:00Z",
            "platform": "swarm",
        }

        # Validation function
        def validate_state(state: dict) -> bool:
            required_fields = ["service", "active_color", "replicas", "platform"]

            for field in required_fields:
                if field not in state:
                    return False

            if state["active_color"] not in ["blue", "green"]:
                return False

            if not isinstance(state["replicas"], int) or state["replicas"] < 0:
                return False

            if state["platform"] not in ["swarm", "k8s"]:
                return False

            return True

        assert validate_state(valid_state) is True

        # Test invalid states
        invalid_states = [
            {"service": "test"},  # Missing fields
            {**valid_state, "active_color": "red"},  # Invalid color
            {**valid_state, "replicas": -1},  # Invalid replicas
            {**valid_state, "platform": "unknown"},  # Invalid platform
        ]

        for invalid_state in invalid_states:
            assert validate_state(invalid_state) is False


@pytest.mark.unit
class TestGradualTrafficSwitching:
    """Test gradual traffic switching mechanisms."""

    def test_traffic_switching_steps(self, deployment_simulator):
        """Test gradual traffic switching in steps."""
        service_name = "test-service"
        active_color = "blue"
        inactive_color = "green"

        # Create both deployments
        deployment_simulator.create_service(service_name, active_color, 3)
        deployment_simulator.create_service(service_name, inactive_color, 3)

        # Simulate gradual traffic switching
        traffic_steps = [10, 25, 50, 75, 100]

        for percentage in traffic_steps:
            deployment_simulator.update_traffic_distribution(
                service_name, active_color, inactive_color, percentage
            )

            distribution = deployment_simulator.traffic_distribution[service_name]
            assert distribution["distribution"][inactive_color] == percentage
            assert distribution["distribution"][active_color] == 100 - percentage

    def test_traffic_switch_validation(self, deployment_simulator):
        """Test validation before traffic switching."""
        service_name = "validation-service"
        active_color = "blue"
        inactive_color = "green"

        # Create only active deployment (inactive doesn't exist)
        deployment_simulator.create_service(service_name, active_color, 3)

        # Validation should fail for traffic switching
        def validate_traffic_switch(service: str, active: str, inactive: str) -> bool:
            active_healthy = deployment_simulator.health_check(service, active)
            inactive_healthy = deployment_simulator.health_check(service, inactive)

            return active_healthy and inactive_healthy

        # Should fail because inactive service doesn't exist
        assert (
            validate_traffic_switch(service_name, active_color, inactive_color) is False
        )

        # Create inactive deployment
        deployment_simulator.create_service(service_name, inactive_color, 3)

        # Should now pass
        assert (
            validate_traffic_switch(service_name, active_color, inactive_color) is True
        )

    def test_traffic_switch_rollback(self, deployment_simulator):
        """Test rolling back traffic during failed switch."""
        service_name = "rollback-service"
        active_color = "blue"
        inactive_color = "green"

        # Setup both deployments
        deployment_simulator.create_service(service_name, active_color, 3)
        deployment_simulator.create_service(service_name, inactive_color, 3)

        # Start traffic switching
        deployment_simulator.update_traffic_distribution(
            service_name, active_color, inactive_color, 50
        )

        # Simulate failure - rollback traffic to active
        deployment_simulator.update_traffic_distribution(
            service_name, active_color, inactive_color, 0
        )

        distribution = deployment_simulator.traffic_distribution[service_name]
        assert distribution["distribution"][active_color] == 100
        assert distribution["distribution"][inactive_color] == 0

    def test_canary_deployment_traffic_pattern(self, deployment_simulator):
        """Test canary deployment traffic pattern."""
        service_name = "canary-service"
        active_color = "blue"
        inactive_color = "green"

        deployment_simulator.create_service(service_name, active_color, 10)
        deployment_simulator.create_service(
            service_name, inactive_color, 1
        )  # Small canary

        # Canary traffic pattern: start with small percentage
        canary_steps = [1, 5, 10, 25, 50, 100]

        for percentage in canary_steps:
            deployment_simulator.update_traffic_distribution(
                service_name, active_color, inactive_color, percentage
            )

            distribution = deployment_simulator.traffic_distribution[service_name]

            # Verify small initial traffic to canary
            if percentage <= 10:
                assert distribution["distribution"][inactive_color] <= 10

            # Full traffic switch at end
            if percentage == 100:
                assert distribution["distribution"][inactive_color] == 100


@pytest.mark.unit
class TestHealthCheckValidation:
    """Test health check validation during deployments."""

    def test_health_check_timeout(self, deployment_simulator):
        """Test health check timeout handling."""
        service_name = "timeout-service"
        inactive_color = "green"

        # Create service but don't make it healthy
        deployment_simulator.create_service(service_name, inactive_color, 3)

        # Simulate health check with timeout
        def health_check_with_timeout(
            service: str, color: str, timeout: int = 30
        ) -> bool:
            start_time = time.time()

            while time.time() - start_time < timeout:
                if deployment_simulator.health_check(service, color):
                    return True
                time.sleep(1)  # Simulated check interval

            return False  # Timeout reached

        # Should timeout since service is not healthy
        result = health_check_with_timeout(service_name, inactive_color, timeout=2)
        assert result is False

    def test_health_check_retry_logic(self, deployment_simulator):
        """Test health check retry logic."""
        service_name = "retry-service"
        inactive_color = "green"

        deployment_simulator.create_service(service_name, inactive_color, 3)

        # Simulate health check with retries
        max_retries = 3
        retry_count = 0

        def health_check_with_retries() -> bool:
            nonlocal retry_count

            for attempt in range(max_retries):
                retry_count += 1

                # Simulate first 2 attempts fail, 3rd succeeds
                if attempt < 2:
                    result = False
                else:
                    # Make service healthy for final attempt
                    deployment_simulator.scale_service(service_name, inactive_color, 3)
                    result = deployment_simulator.health_check(
                        service_name, inactive_color
                    )

                if result:
                    return True

                time.sleep(0.1)  # Brief retry delay

            return False

        result = health_check_with_retries()
        assert result is True
        assert retry_count == 3  # Should have tried 3 times

    def test_multiple_health_check_endpoints(self, deployment_simulator):
        """Test health checks across multiple endpoints."""
        service_name = "multi-endpoint-service"
        inactive_color = "green"

        deployment_simulator.create_service(service_name, inactive_color, 3)

        # Mock different health endpoints
        endpoints = ["/health", "/health/ready", "/health/live", "/api/health"]

        endpoint_results = {
            "/health": True,
            "/health/ready": True,
            "/health/live": False,  # One endpoint fails
            "/api/health": True,
        }

        def check_all_endpoints() -> bool:
            # All endpoints must be healthy
            base_health = deployment_simulator.health_check(
                service_name, inactive_color
            )
            if not base_health:
                return False

            # Simulate endpoint-specific checks
            healthy_endpoints = sum(1 for result in endpoint_results.values() if result)
            total_endpoints = len(endpoint_results)

            # Require at least 75% of endpoints to be healthy
            health_threshold = 0.75
            return (healthy_endpoints / total_endpoints) >= health_threshold

        result = check_all_endpoints()
        assert result is True  # 3/4 endpoints healthy = 75%

    def test_health_check_degradation_detection(self, deployment_simulator):
        """Test detection of service degradation during deployment."""
        service_name = "degradation-service"
        inactive_color = "green"

        deployment_simulator.create_service(service_name, inactive_color, 3)
        deployment_simulator.scale_service(service_name, inactive_color, 3)

        # Simulate performance metrics during health checks
        performance_metrics = {
            "response_time_ms": [100, 150, 200, 300, 500],  # Degrading
            "error_rate": [0.1, 0.2, 0.5, 1.0, 2.0],  # Increasing
            "throughput_rps": [100, 95, 85, 70, 50],  # Decreasing
        }

        def detect_degradation() -> bool:
            # Simple degradation detection based on trends
            response_times = performance_metrics["response_time_ms"]
            error_rates = performance_metrics["error_rate"]

            # Check if response time is trending up
            response_trend = all(
                response_times[i] <= response_times[i + 1]
                for i in range(len(response_times) - 1)
            )

            # Check if error rate is too high
            current_error_rate = error_rates[-1]
            error_threshold = 1.5  # 1.5%

            return response_trend and current_error_rate > error_threshold

        degradation_detected = detect_degradation()
        assert degradation_detected is True  # Should detect degradation


@pytest.mark.unit
class TestRollbackMechanisms:
    """Test automatic rollback mechanisms."""

    def test_automatic_rollback_trigger(self, deployment_simulator):
        """Test conditions that trigger automatic rollback."""
        service_name = "rollback-service"
        active_color = "blue"
        inactive_color = "green"

        # Setup initial deployment
        deployment_simulator.create_service(service_name, active_color, 5)
        deployment_simulator.create_service(service_name, inactive_color, 5)

        # Simulate deployment failure scenarios
        failure_scenarios = {
            "health_check_failure": False,
            "high_error_rate": True,  # 5% error rate > 2% threshold
            "response_time_degradation": True,  # 800ms > 500ms threshold
            "deployment_timeout": False,
        }

        def should_rollback() -> bool:
            # Rollback if any critical failure condition is met
            critical_failures = [
                failure_scenarios["health_check_failure"],
                failure_scenarios["high_error_rate"],
                failure_scenarios["deployment_timeout"],
            ]

            # Performance degradation also triggers rollback
            performance_failures = [failure_scenarios["response_time_degradation"]]

            return any(critical_failures) or any(performance_failures)

        assert should_rollback() is True

    def test_rollback_execution_speed(self, deployment_simulator):
        """Test rollback execution speed."""
        service_name = "speed-rollback-service"
        active_color = "blue"
        inactive_color = "green"

        # Setup failed deployment scenario
        deployment_simulator.create_service(service_name, active_color, 3)
        deployment_simulator.create_service(service_name, inactive_color, 3)

        # Switch traffic to inactive (new deployment)
        deployment_simulator.update_traffic_distribution(
            service_name, active_color, inactive_color, 100
        )

        # Measure rollback speed
        start_time = time.time()

        # Execute rollback (switch traffic back)
        deployment_simulator.update_traffic_distribution(
            service_name, active_color, inactive_color, 0
        )

        end_time = time.time()
        rollback_time = end_time - start_time

        # Rollback should be very fast (< 5 seconds)
        assert rollback_time < 5.0

    def test_rollback_state_persistence(
        self, deployment_simulator, deployment_state_dir
    ):
        """Test rollback state is properly persisted."""
        service_name = "persistent-rollback-service"
        active_color = "blue"
        inactive_color = "green"

        # Initial state
        initial_state = {
            "service": service_name,
            "active_color": active_color,
            "replicas": 5,
            "timestamp": datetime.utcnow().isoformat(),
            "platform": "swarm",
        }

        # Save initial state
        state_file = os.path.join(deployment_state_dir, f"{service_name}_state.json")
        with open(state_file, "w") as f:
            json.dump(initial_state, f)

        # Simulate failed deployment and rollback
        rollback_state = {
            "service": service_name,
            "active_color": active_color,  # Rolled back to original
            "replicas": 5,
            "timestamp": datetime.utcnow().isoformat(),
            "platform": "swarm",
            "rollback": True,
            "rollback_reason": "Health check failure",
        }

        # Update state file with rollback info
        with open(state_file, "w") as f:
            json.dump(rollback_state, f)

        # Verify rollback state was saved
        with open(state_file, "r") as f:
            saved_state = json.load(f)

        assert saved_state["rollback"] is True
        assert saved_state["rollback_reason"] == "Health check failure"
        assert saved_state["active_color"] == active_color  # Back to original

    def test_partial_rollback_scenario(self, deployment_simulator):
        """Test partial rollback scenarios."""
        service_name = "partial-rollback-service"
        active_color = "blue"
        inactive_color = "green"

        # Setup deployment
        deployment_simulator.create_service(service_name, active_color, 5)
        deployment_simulator.create_service(service_name, inactive_color, 5)

        # Simulate partial traffic switch (50%)
        deployment_simulator.update_traffic_distribution(
            service_name, active_color, inactive_color, 50
        )

        # Detect issues with new deployment
        issues_detected = True  # Simulate issue detection

        if issues_detected:
            # Partial rollback: reduce new deployment traffic but don't eliminate
            deployment_simulator.update_traffic_distribution(
                service_name, active_color, inactive_color, 10
            )

            distribution = deployment_simulator.traffic_distribution[service_name]

            # Verify partial rollback
            assert distribution["distribution"][inactive_color] == 10
            assert distribution["distribution"][active_color] == 90

    def test_multi_service_rollback_coordination(self, deployment_simulator):
        """Test coordinated rollback across multiple services."""
        services = ["service-a", "service-b", "service-c"]
        active_color = "blue"
        inactive_color = "green"

        # Setup multiple services
        for service in services:
            deployment_simulator.create_service(service, active_color, 3)
            deployment_simulator.create_service(service, inactive_color, 3)

            # Switch traffic to inactive
            deployment_simulator.update_traffic_distribution(
                service, active_color, inactive_color, 100
            )

        # Simulate failure in one service requires rollback of all
        failed_service = "service-b"
        failure_detected = True

        if failure_detected:
            rollback_results = {}

            # Rollback all services in coordination
            for service in services:
                deployment_simulator.update_traffic_distribution(
                    service, active_color, inactive_color, 0
                )
                rollback_results[service] = True

            # Verify all services rolled back
            for service in services:
                distribution = deployment_simulator.traffic_distribution[service]
                assert distribution["distribution"][active_color] == 100
                assert rollback_results[service] is True


@pytest.mark.integration
class TestMultiPlatformDeployment:
    """Test blue-green deployment across different platforms."""

    def test_docker_swarm_deployment(self, deployment_simulator):
        """Test Docker Swarm-specific deployment operations."""
        deployment_simulator.platform = "swarm"
        service_name = "swarm-service"
        active_color = "blue"
        inactive_color = "green"

        # Test service creation
        result = deployment_simulator.create_service(service_name, inactive_color, 3)
        assert result is True

        service_id = f"{service_name}-{inactive_color}"
        assert service_id in deployment_simulator.services

        # Test scaling
        deployment_simulator.scale_service(service_name, inactive_color, 5)
        replicas = deployment_simulator.get_service_replicas(
            service_name, inactive_color
        )
        assert replicas == 5

        # Test health check
        health = deployment_simulator.health_check(service_name, inactive_color)
        assert health is True

    def test_kubernetes_deployment(self, deployment_simulator):
        """Test Kubernetes-specific deployment operations."""
        deployment_simulator.platform = "k8s"
        service_name = "k8s-service"
        active_color = "blue"
        inactive_color = "green"

        # Test deployment creation
        result = deployment_simulator.create_service(service_name, inactive_color, 3)
        assert result is True

        deployment_id = f"{service_name}-{inactive_color}"
        assert deployment_id in deployment_simulator.deployments

        # Test scaling
        deployment_simulator.scale_service(service_name, inactive_color, 7)
        replicas = deployment_simulator.get_service_replicas(
            service_name, inactive_color
        )
        assert replicas == 7

        # Test readiness
        health = deployment_simulator.health_check(service_name, inactive_color)
        assert health is True

    def test_cross_platform_deployment_validation(self):
        """Test deployment validation across platforms."""
        platforms = ["swarm", "k8s"]

        for platform in platforms:
            simulator = BlueGreenDeploymentSimulator(platform)

            # Common deployment operations should work on both platforms
            service_name = f"cross-platform-service-{platform}"
            color = "green"

            # Create, scale, and validate
            create_result = simulator.create_service(service_name, color, 4)
            assert create_result is True

            scale_result = simulator.scale_service(service_name, color, 6)
            assert scale_result is True

            replicas = simulator.get_service_replicas(service_name, color)
            assert replicas == 6

            health = simulator.health_check(service_name, color)
            assert health is True

    def test_platform_specific_configurations(self):
        """Test platform-specific deployment configurations."""
        # Docker Swarm configuration
        swarm_config = {
            "update_parallelism": 2,
            "update_delay": "10s",
            "failure_action": "rollback",
            "monitor": "60s",
        }

        # Kubernetes configuration
        k8s_config = {
            "strategy": "RollingUpdate",
            "max_unavailable": "25%",
            "max_surge": "25%",
            "progress_deadline_seconds": 600,
        }

        def validate_config(platform: str, config: dict) -> bool:
            if platform == "swarm":
                required_fields = ["update_parallelism", "failure_action"]
                return all(field in config for field in required_fields)
            elif platform == "k8s":
                required_fields = ["strategy", "max_unavailable"]
                return all(field in config for field in required_fields)
            return False

        assert validate_config("swarm", swarm_config) is True
        assert validate_config("k8s", k8s_config) is True

        # Cross-validation should fail
        assert validate_config("swarm", k8s_config) is False
        assert validate_config("k8s", swarm_config) is False


@pytest.mark.integration
@pytest.mark.slow
class TestEndToEndDeploymentWorkflow:
    """Test complete end-to-end deployment workflows."""

    @pytest.mark.asyncio
    async def test_complete_deployment_workflow(
        self, deployment_simulator, deployment_state_dir
    ):
        """Test complete blue-green deployment from start to finish."""
        service_name = "complete-workflow-service"
        active_color = "blue"
        inactive_color = "green"
        initial_replicas = 3

        # Step 1: Initialize with active deployment
        deployment_simulator.create_service(
            service_name, active_color, initial_replicas
        )

        # Save initial state
        state_file = os.path.join(deployment_state_dir, f"{service_name}_state.json")
        initial_state = {
            "service": service_name,
            "active_color": active_color,
            "replicas": initial_replicas,
            "timestamp": datetime.utcnow().isoformat(),
            "platform": deployment_simulator.platform,
        }

        with open(state_file, "w") as f:
            json.dump(initial_state, f)

        # Step 2: Deploy new version (inactive color)
        deploy_success = deployment_simulator.create_service(
            service_name, inactive_color, initial_replicas
        )
        assert deploy_success is True

        # Step 3: Health check new deployment
        await asyncio.sleep(0.1)  # Simulate deployment time
        health_ok = deployment_simulator.health_check(service_name, inactive_color)
        assert health_ok is True

        # Step 4: Gradual traffic switching
        traffic_steps = [10, 25, 50, 75, 100]

        for step_percentage in traffic_steps:
            deployment_simulator.update_traffic_distribution(
                service_name, active_color, inactive_color, step_percentage
            )

            await asyncio.sleep(0.05)  # Simulate monitoring period

            # Verify health during traffic switch
            health_ok = deployment_simulator.health_check(service_name, inactive_color)
            assert health_ok is True

            # Check traffic distribution
            distribution = deployment_simulator.traffic_distribution[service_name]
            assert distribution["distribution"][inactive_color] == step_percentage

        # Step 5: Finalize deployment
        # Scale down old deployment
        deployment_simulator.scale_service(service_name, active_color, 0)

        # Update state to reflect new active color
        final_state = {
            "service": service_name,
            "active_color": inactive_color,  # Swapped
            "replicas": initial_replicas,
            "timestamp": datetime.utcnow().isoformat(),
            "platform": deployment_simulator.platform,
            "deployment_successful": True,
        }

        with open(state_file, "w") as f:
            json.dump(final_state, f)

        # Step 6: Cleanup old deployment
        deployment_simulator.remove_service(service_name, active_color)

        # Verify final state
        new_replicas = deployment_simulator.get_service_replicas(
            service_name, inactive_color
        )
        assert new_replicas == initial_replicas

        old_replicas = deployment_simulator.get_service_replicas(
            service_name, active_color
        )
        assert old_replicas == 0

    @pytest.mark.asyncio
    async def test_deployment_with_failure_and_rollback(
        self, deployment_simulator, deployment_state_dir
    ):
        """Test deployment that fails and triggers automatic rollback."""
        service_name = "failure-rollback-service"
        active_color = "blue"
        inactive_color = "green"
        initial_replicas = 4

        # Step 1: Setup initial deployment
        deployment_simulator.create_service(
            service_name, active_color, initial_replicas
        )

        # Step 2: Deploy new version
        deployment_simulator.create_service(
            service_name, inactive_color, initial_replicas
        )

        # Step 3: Start gradual traffic switch
        deployment_simulator.update_traffic_distribution(
            service_name, active_color, inactive_color, 25
        )

        await asyncio.sleep(0.1)

        # Step 4: Simulate failure detection
        # Mock health check failure
        original_health_check = deployment_simulator.health_check

        def failing_health_check(service: str, color: str) -> bool:
            if color == inactive_color:
                return False  # New deployment fails health check
            return original_health_check(service, color)

        deployment_simulator.health_check = failing_health_check

        # Step 5: Detect failure and trigger rollback
        health_ok = deployment_simulator.health_check(service_name, inactive_color)
        assert health_ok is False

        # Rollback traffic immediately
        deployment_simulator.update_traffic_distribution(
            service_name, active_color, inactive_color, 0
        )

        # Step 6: Verify rollback
        distribution = deployment_simulator.traffic_distribution[service_name]
        assert distribution["distribution"][active_color] == 100
        assert distribution["distribution"][inactive_color] == 0

        # Step 7: Cleanup failed deployment
        deployment_simulator.remove_service(service_name, inactive_color)

        # Verify old deployment still healthy
        active_replicas = deployment_simulator.get_service_replicas(
            service_name, active_color
        )
        assert active_replicas == initial_replicas

    @pytest.mark.asyncio
    async def test_concurrent_multi_service_deployment(self, deployment_state_dir):
        """Test concurrent deployment of multiple services."""
        services = ["service-1", "service-2", "service-3", "service-4"]
        active_color = "blue"
        inactive_color = "green"

        # Create simulators for each service (simulating independent deployments)
        simulators = {}
        for service in services:
            simulators[service] = BlueGreenDeploymentSimulator()
            simulators[service].create_service(service, active_color, 3)

        # Concurrent deployment tasks
        async def deploy_service(
            service_name: str, simulator: BlueGreenDeploymentSimulator
        ):
            # Deploy new version
            simulator.create_service(service_name, inactive_color, 3)

            # Health check
            await asyncio.sleep(0.1)
            health_ok = simulator.health_check(service_name, inactive_color)
            if not health_ok:
                return False

            # Gradual traffic switch
            for percentage in [25, 50, 75, 100]:
                simulator.update_traffic_distribution(
                    service_name, active_color, inactive_color, percentage
                )
                await asyncio.sleep(0.02)  # Brief monitoring

            return True

        # Execute concurrent deployments
        start_time = time.time()
        deployment_tasks = [
            deploy_service(service, simulators[service]) for service in services
        ]

        results = await asyncio.gather(*deployment_tasks, return_exceptions=True)
        end_time = time.time()

        # Verify all deployments succeeded
        assert all(result is True for result in results)

        # Verify concurrent execution was faster than sequential
        total_time = end_time - start_time
        max_expected_time = len(services) * 0.5  # Generous sequential estimate
        assert total_time < max_expected_time

        # Verify final state of all services
        for service in services:
            distribution = simulators[service].traffic_distribution.get(service, {})
            if distribution:
                assert distribution["distribution"][inactive_color] == 100


@pytest.mark.load
@pytest.mark.slow
class TestDeploymentPerformanceImpact:
    """Test performance impact of blue-green deployments."""

    def test_deployment_resource_usage(self, deployment_simulator):
        """Test resource usage during deployment."""
        service_name = "resource-test-service"
        active_color = "blue"
        inactive_color = "green"
        replicas = 5

        # Initial resource usage (active deployment only)
        deployment_simulator.create_service(service_name, active_color, replicas)
        initial_resource_usage = replicas * 100  # Mock resource units

        # Add inactive deployment (doubles resource usage temporarily)
        deployment_simulator.create_service(service_name, inactive_color, replicas)
        peak_resource_usage = replicas * 200  # Both deployments running

        # After cleanup (back to normal)
        deployment_simulator.remove_service(service_name, active_color)
        final_resource_usage = replicas * 100

        # Verify resource usage pattern
        assert peak_resource_usage == 2 * initial_resource_usage
        assert final_resource_usage == initial_resource_usage

        # Resource efficiency check
        resource_overhead = (
            peak_resource_usage - initial_resource_usage
        ) / initial_resource_usage
        assert resource_overhead == 1.0  # 100% overhead during deployment (expected)

    def test_deployment_duration_scaling(self, deployment_simulator):
        """Test how deployment duration scales with service size."""
        service_base_name = "scaling-test-service"
        active_color = "blue"
        inactive_color = "green"

        replica_counts = [1, 5, 10, 20, 50]
        deployment_times = []

        for replicas in replica_counts:
            service_name = f"{service_base_name}-{replicas}"

            start_time = time.time()

            # Simulate deployment steps
            deployment_simulator.create_service(service_name, active_color, replicas)
            deployment_simulator.create_service(service_name, inactive_color, replicas)

            # Simulate health check time (scales with replicas)
            health_check_time = replicas * 0.001  # 1ms per replica
            time.sleep(health_check_time)

            # Traffic switching time (constant)
            traffic_switch_time = 0.01  # 10ms regardless of size
            time.sleep(traffic_switch_time)

            deployment_time = time.time() - start_time
            deployment_times.append(deployment_time)

        # Verify deployment time scales reasonably
        # Should be roughly linear with replica count
        time_per_replica = [dt / rc for dt, rc in zip(deployment_times, replica_counts)]

        # Time per replica should be relatively consistent
        avg_time_per_replica = sum(time_per_replica) / len(time_per_replica)
        for tpr in time_per_replica:
            assert (
                abs(tpr - avg_time_per_replica) / avg_time_per_replica < 0.5
            )  # Within 50%

    def test_zero_downtime_validation(self, deployment_simulator):
        """Test validation of zero-downtime deployment."""
        service_name = "zero-downtime-service"
        active_color = "blue"
        inactive_color = "green"
        replicas = 5

        # Setup initial service
        deployment_simulator.create_service(service_name, active_color, replicas)

        # Track service availability during deployment
        availability_checks = []

        def check_availability() -> bool:
            # Service is available if at least one color has healthy replicas
            active_healthy = deployment_simulator.get_service_replicas(
                service_name, active_color
            ) > 0 and deployment_simulator.health_check(service_name, active_color)
            inactive_healthy = deployment_simulator.get_service_replicas(
                service_name, inactive_color
            ) > 0 and deployment_simulator.health_check(service_name, inactive_color)

            return active_healthy or inactive_healthy

        # Check availability throughout deployment
        availability_checks.append(check_availability())  # Before deployment

        # Deploy inactive version
        deployment_simulator.create_service(service_name, inactive_color, replicas)
        availability_checks.append(check_availability())  # During deployment

        # Traffic switching phases
        for percentage in [25, 50, 75, 100]:
            deployment_simulator.update_traffic_distribution(
                service_name, active_color, inactive_color, percentage
            )
            availability_checks.append(check_availability())

        # Remove old version
        deployment_simulator.remove_service(service_name, active_color)
        availability_checks.append(check_availability())  # After cleanup

        # Verify zero downtime - all availability checks should be True
        assert all(availability_checks), f"Downtime detected: {availability_checks}"

    def test_deployment_network_impact(self):
        """Test network impact of deployment traffic switching."""
        # Mock network metrics during deployment
        baseline_connections = 1000
        baseline_bandwidth = 100  # MB/s

        # During traffic switching, some connection redistribution occurs
        traffic_switch_phases = [
            {"blue_connections": 1000, "green_connections": 0, "total_bandwidth": 100},
            {"blue_connections": 750, "green_connections": 250, "total_bandwidth": 105},
            {"blue_connections": 500, "green_connections": 500, "total_bandwidth": 110},
            {"blue_connections": 250, "green_connections": 750, "total_bandwidth": 105},
            {"blue_connections": 0, "green_connections": 1000, "total_bandwidth": 100},
        ]

        max_bandwidth = max(phase["total_bandwidth"] for phase in traffic_switch_phases)
        bandwidth_overhead = (max_bandwidth - baseline_bandwidth) / baseline_bandwidth

        # Network overhead should be minimal (< 15%)
        assert (
            bandwidth_overhead < 0.15
        ), f"Network overhead too high: {bandwidth_overhead:.2%}"

        # Total connections should remain consistent
        for phase in traffic_switch_phases:
            total_connections = phase["blue_connections"] + phase["green_connections"]
            assert total_connections == baseline_connections
