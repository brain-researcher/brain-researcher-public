"""
Comprehensive tests for the Brain Researcher auto-scaling system.

Tests cover:
- CPU and memory-based scaling triggers
- Custom metrics scaling (queue depth, response time)
- ML-based predictive scaling
- Scaling decision logic and algorithms
- Cooldown periods and stability
- Multi-platform support (Docker Swarm, Kubernetes)
- Cost optimization features
- Performance under various load patterns
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pytest

from infrastructure.autoscaling.autoscaler import (
    AutoScaler,
    MetricSample,
    MetricsCollector,
    PlatformType,
    PredictiveScaler,
    ScalingAction,
    ScalingDecision,
    ServiceConfig,
)

# Import the autoscaler components (assuming they exist)
from tests.load.conftest import TestConfig


@pytest.fixture
def service_config():
    """Standard service configuration for testing."""
    return ServiceConfig(
        name="orchestrator",
        min_replicas=3,
        max_replicas=12,
        target_cpu_percent=65,
        target_memory_percent=70,
        scale_up_threshold=80,
        scale_down_threshold=30,
        cooldown_minutes=5,
        scale_up_increment=2,
        scale_down_increment=1,
        enable_predictive=True,
    )


@pytest.fixture
def sample_metrics():
    """Generate sample metrics for testing."""
    base_time = datetime.utcnow()

    samples = []
    for i in range(20):
        timestamp = base_time - timedelta(minutes=i * 2)
        sample = MetricSample(
            timestamp=timestamp,
            cpu_percent=50 + (i * 2),  # Increasing CPU
            memory_percent=40 + (i * 1.5),  # Increasing memory
            active_connections=10 + (i * 3),
            response_time_ms=100 + (i * 15),
            queue_depth=i * 2,
            custom_metrics={
                "queue_depth": i * 2,
                "avg_response_time_ms": 100 + (i * 15),
                "active_connections": 10 + (i * 3),
                "error_rate": i * 0.05,
            },
        )
        samples.append(sample)

    return list(reversed(samples))  # Chronological order


@pytest.mark.unit
class TestMetricsCollector:
    """Test the metrics collection functionality."""

    @pytest.fixture
    def metrics_collector(self, clean_redis):
        """Metrics collector with mocked dependencies."""
        collector = MetricsCollector(redis_url="redis://localhost:6379")
        collector.docker_client = Mock()
        collector.k8s_client = Mock()
        return collector

    @pytest.mark.asyncio
    async def test_system_metrics_collection(self, metrics_collector):
        """Test system-wide metrics collection."""
        with (
            patch("psutil.cpu_percent", return_value=75.5),
            patch("psutil.virtual_memory") as mock_memory,
            patch("psutil.disk_usage") as mock_disk,
            patch("psutil.net_io_counters") as mock_net,
            patch("os.getloadavg", return_value=[1.2, 1.5, 1.8]),
        ):

            mock_memory.return_value.percent = 68.2
            mock_disk.return_value.percent = 45.7
            mock_net.return_value._asdict.return_value = {
                "bytes_sent": 1024000,
                "bytes_recv": 2048000,
            }

            metrics = await metrics_collector.collect_system_metrics()

            assert metrics["cpu_percent"] == 75.5
            assert metrics["memory_percent"] == 68.2
            assert metrics["disk_usage"] == 45.7
            assert metrics["load_average"] == [1.2, 1.5, 1.8]
            assert "timestamp" in metrics
            assert "network_io" in metrics

    @pytest.mark.asyncio
    async def test_docker_service_metrics(self, metrics_collector):
        """Test Docker Swarm service metrics collection."""
        # Mock Docker service and container
        mock_service = Mock()
        mock_task = {
            "Status": {"State": "running", "ContainerStatus": {"ContainerID": "abc123"}}
        }
        mock_service.tasks.return_value = [mock_task]

        mock_container = Mock()
        mock_container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2000000},
                "system_cpu_usage": 4000000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1000000},
                "system_cpu_usage": 2000000,
            },
            "memory_stats": {"usage": 209715200, "limit": 536870912},  # 200MB  # 512MB
        }

        metrics_collector.docker_client.services.get.return_value = mock_service
        metrics_collector.docker_client.containers.get.return_value = mock_container

        samples = await metrics_collector.collect_service_metrics_docker("test-service")

        assert len(samples) == 1
        sample = samples[0]
        assert sample.cpu_percent == 50.0  # (2000000-1000000)/(4000000-2000000) * 100
        assert (
            sample.memory_percent == (200 * 1024 * 1024 / (512 * 1024 * 1024)) * 100
        )  # ~39.06%

    @pytest.mark.asyncio
    async def test_custom_metrics_collection(self, metrics_collector, clean_redis):
        """Test custom metrics collection from Redis."""
        # Setup test data in Redis
        redis_client = clean_redis
        if redis_client:
            # Set up queue depth
            redis_client.lpush("queue:test-service", *range(15))

            # Set up response times
            response_times = [100, 150, 120, 180, 200, 160, 140]
            redis_client.lpush("metrics:response_times:test-service", *response_times)

            # Set up connection count
            redis_client.set("metrics:connections:test-service", 25)

            # Set up error rate
            redis_client.set("metrics:errors:test-service", 2)

            metrics = await metrics_collector.collect_custom_metrics("test-service")

            assert metrics["queue_depth"] == 15.0
            assert "avg_response_time_ms" in metrics
            assert metrics["active_connections"] == 25.0
            assert metrics["error_rate"] == 2.0
        else:
            pytest.skip("Redis not available")

    def test_cpu_usage_parsing(self, metrics_collector):
        """Test CPU usage string parsing for Kubernetes."""
        test_cases = [
            ("100m", 100.0),
            ("1", 1000.0),
            ("500m", 500.0),
            ("1500m", 1500.0),
            ("2", 2000.0),
        ]

        for cpu_string, expected in test_cases:
            result = metrics_collector._parse_cpu_usage(cpu_string)
            assert (
                result == expected
            ), f"Failed to parse {cpu_string}: got {result}, expected {expected}"

    def test_memory_usage_parsing(self, metrics_collector):
        """Test memory usage string parsing for Kubernetes."""
        test_cases = [
            ("128Mi", 128 * 1024 * 1024),
            ("1Gi", 1024 * 1024 * 1024),
            ("512Ki", 512 * 1024),
            ("2Gi", 2 * 1024 * 1024 * 1024),
            ("256Mi", 256 * 1024 * 1024),
        ]

        for memory_string, expected in test_cases:
            result = metrics_collector._parse_memory_usage(memory_string)
            assert (
                result == expected
            ), f"Failed to parse {memory_string}: got {result}, expected {expected}"


@pytest.mark.unit
class TestPredictiveScaler:
    """Test ML-based predictive scaling functionality."""

    @pytest.fixture
    def predictive_scaler(self):
        """Predictive scaler instance."""
        return PredictiveScaler(history_window_hours=24)

    def test_feature_preparation(self, predictive_scaler, sample_metrics):
        """Test preparation of features for ML model."""
        features, targets = predictive_scaler.prepare_features(sample_metrics)

        assert features.shape[0] > 0, "No features generated"
        assert targets.shape[0] == features.shape[0], "Feature/target mismatch"

        # Each feature vector should have the right dimensions
        # 5 samples * 7 features per sample = 35 features
        expected_features = 5 * 7  # 5 previous samples, 7 features each
        assert features.shape[1] == expected_features

    def test_model_training(self, predictive_scaler, sample_metrics):
        """Test ML model training process."""
        success = predictive_scaler.train_model("test-service", sample_metrics)
        assert success is True

        # Model should be stored
        assert "test-service" in predictive_scaler.models
        assert "test-service" in predictive_scaler.scalers
        assert "test-service" in predictive_scaler.last_training

    def test_load_prediction(self, predictive_scaler, sample_metrics):
        """Test load prediction functionality."""
        # Train model first
        predictive_scaler.train_model("test-service", sample_metrics)

        # Make prediction using last 5 samples
        recent_metrics = sample_metrics[-5:]
        predicted_load = predictive_scaler.predict_load(
            "test-service", recent_metrics, prediction_horizon_minutes=15
        )

        assert predicted_load is not None
        assert 0 <= predicted_load <= 100, f"Invalid load prediction: {predicted_load}"

    def test_insufficient_data_handling(self, predictive_scaler):
        """Test handling of insufficient historical data."""
        # Too few samples
        sparse_metrics = [
            MetricSample(
                timestamp=datetime.utcnow(),
                cpu_percent=50,
                memory_percent=60,
                active_connections=10,
                response_time_ms=100,
                queue_depth=5,
            )
        ]

        success = predictive_scaler.train_model("test-service", sparse_metrics)
        assert success is False

        # Prediction should also fail
        predicted_load = predictive_scaler.predict_load("test-service", sparse_metrics)
        assert predicted_load is None

    def test_model_accuracy_tracking(self, predictive_scaler, sample_metrics):
        """Test model performance tracking."""
        success = predictive_scaler.train_model("test-service", sample_metrics)
        assert success is True

        # Model should exist
        model = predictive_scaler.models["test-service"]
        assert model is not None

        # Should have training timestamp
        last_training = predictive_scaler.last_training["test-service"]
        assert isinstance(last_training, datetime)
        assert last_training <= datetime.utcnow()


@pytest.mark.unit
class TestScalingDecisionLogic:
    """Test auto-scaling decision algorithms."""

    @pytest.fixture
    def autoscaler(self, service_config, clean_redis):
        """Auto-scaler instance with mocked clients."""
        scaler = AutoScaler(
            platform=PlatformType.DOCKER_SWARM, redis_url="redis://localhost:6379"
        )
        scaler.service_configs["test-service"] = service_config
        scaler.docker_client = Mock()
        scaler.k8s_client = Mock()
        return scaler

    def test_scale_up_decision(self, autoscaler, service_config):
        """Test scale-up decision logic."""
        # High CPU and memory usage
        high_load_samples = [
            MetricSample(
                timestamp=datetime.utcnow(),
                cpu_percent=85,  # Above scale_up_threshold (80)
                memory_percent=82,  # Above scale_up_threshold
                active_connections=50,
                response_time_ms=300,
                queue_depth=60,  # High queue depth
            )
        ]

        current_replicas = 3
        decision = autoscaler.analyze_scaling_decision(
            "test-service", high_load_samples, current_replicas
        )

        assert decision.action == ScalingAction.SCALE_UP
        assert decision.target_replicas > current_replicas
        assert decision.target_replicas <= service_config.max_replicas
        assert decision.confidence > 0.8

    def test_scale_down_decision(self, autoscaler, service_config):
        """Test scale-down decision logic."""
        # Low CPU and memory usage
        low_load_samples = [
            MetricSample(
                timestamp=datetime.utcnow(),
                cpu_percent=20,  # Below scale_down_threshold (30)
                memory_percent=25,  # Below scale_down_threshold
                active_connections=5,
                response_time_ms=80,
                queue_depth=2,  # Low queue depth
            )
        ]

        current_replicas = 8
        decision = autoscaler.analyze_scaling_decision(
            "test-service", low_load_samples, current_replicas
        )

        assert decision.action == ScalingAction.SCALE_DOWN
        assert decision.target_replicas < current_replicas
        assert decision.target_replicas >= service_config.min_replicas

    def test_maintain_decision(self, autoscaler, service_config):
        """Test decision to maintain current scale."""
        # Moderate load within normal range
        normal_load_samples = [
            MetricSample(
                timestamp=datetime.utcnow(),
                cpu_percent=65,  # At target CPU
                memory_percent=70,  # At target memory
                active_connections=20,
                response_time_ms=150,
                queue_depth=15,
            )
        ]

        current_replicas = 5
        decision = autoscaler.analyze_scaling_decision(
            "test-service", normal_load_samples, current_replicas
        )

        assert decision.action == ScalingAction.MAINTAIN
        assert decision.target_replicas == current_replicas

    def test_replica_limits_enforcement(self, autoscaler, service_config):
        """Test enforcement of min/max replica limits."""
        # Test max limit
        high_load_samples = [
            MetricSample(
                timestamp=datetime.utcnow(),
                cpu_percent=95,
                memory_percent=90,
                active_connections=100,
                response_time_ms=500,
                queue_depth=100,
            )
        ]

        current_replicas = service_config.max_replicas  # Already at max
        decision = autoscaler.analyze_scaling_decision(
            "test-service", high_load_samples, current_replicas
        )

        assert decision.target_replicas <= service_config.max_replicas

        # Test min limit
        low_load_samples = [
            MetricSample(
                timestamp=datetime.utcnow(),
                cpu_percent=5,
                memory_percent=10,
                active_connections=1,
                response_time_ms=50,
                queue_depth=0,
            )
        ]

        current_replicas = service_config.min_replicas  # Already at min
        decision = autoscaler.analyze_scaling_decision(
            "test-service", low_load_samples, current_replicas
        )

        assert decision.target_replicas >= service_config.min_replicas

    def test_predictive_scaling_influence(self, autoscaler, service_config):
        """Test how predictive scaling influences decisions."""
        # Mock predictive scaler with high predicted load
        autoscaler.predictive_scaler.predict_load = Mock(return_value=85.0)

        # Current load is moderate but prediction is high
        moderate_samples = [
            MetricSample(
                timestamp=datetime.utcnow(),
                cpu_percent=60,
                memory_percent=65,
                active_connections=25,
                response_time_ms=120,
                queue_depth=20,
            )
        ]

        # Add historical data for prediction
        autoscaler.metrics_history["test-service"] = moderate_samples * 10

        current_replicas = 3
        decision = autoscaler.analyze_scaling_decision(
            "test-service", moderate_samples, current_replicas
        )

        # Should scale up based on prediction
        assert decision.action == ScalingAction.SCALE_UP
        assert "Predicted:" in decision.reason
        assert decision.confidence >= 0.9  # Higher confidence with prediction


@pytest.mark.unit
class TestCooldownPeriods:
    """Test cooldown period functionality."""

    @pytest.fixture
    def autoscaler_with_history(self, clean_redis):
        """Auto-scaler with scaling history."""
        scaler = AutoScaler(
            platform=PlatformType.DOCKER_SWARM, redis_url="redis://localhost:6379"
        )
        scaler.docker_client = Mock()
        return scaler

    @pytest.mark.asyncio
    async def test_cooldown_prevents_scaling(
        self, autoscaler_with_history, service_config
    ):
        """Test that cooldown period prevents premature scaling."""
        # Record a recent scaling action
        recent_time = datetime.utcnow() - timedelta(minutes=2)  # 2 minutes ago
        autoscaler_with_history.last_scale_action["test-service"] = recent_time

        # Create a scaling decision
        decision = ScalingDecision(
            service_name="test-service",
            action=ScalingAction.SCALE_UP,
            current_replicas=3,
            target_replicas=5,
            confidence=0.9,
            reason="High load detected",
        )

        # Mock the platform-specific scaling method
        autoscaler_with_history.service_configs["test-service"] = service_config
        autoscaler_with_history._scale_docker_service = AsyncMock(return_value=True)

        # Try to execute scaling - should be blocked by cooldown
        result = await autoscaler_with_history.execute_scaling_decision(decision)

        assert result is False  # Scaling should be blocked
        autoscaler_with_history._scale_docker_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_allows_scaling_after_period(
        self, autoscaler_with_history, service_config
    ):
        """Test that scaling is allowed after cooldown period."""
        # Record an old scaling action (beyond cooldown)
        old_time = datetime.utcnow() - timedelta(minutes=10)  # 10 minutes ago
        autoscaler_with_history.last_scale_action["test-service"] = old_time

        decision = ScalingDecision(
            service_name="test-service",
            action=ScalingAction.SCALE_UP,
            current_replicas=3,
            target_replicas=5,
            confidence=0.9,
            reason="High load detected",
        )

        autoscaler_with_history.service_configs["test-service"] = service_config
        autoscaler_with_history._scale_docker_service = AsyncMock(return_value=True)

        # Scaling should be allowed
        result = await autoscaler_with_history.execute_scaling_decision(decision)

        assert result is True
        autoscaler_with_history._scale_docker_service.assert_called_once()

    def test_different_cooldown_periods(self):
        """Test different cooldown periods for different services."""
        configs = {
            "fast-service": ServiceConfig(name="fast-service", cooldown_minutes=2),
            "slow-service": ServiceConfig(name="slow-service", cooldown_minutes=10),
            "critical-service": ServiceConfig(
                name="critical-service", cooldown_minutes=15
            ),
        }

        current_time = datetime.utcnow()
        scaling_times = {
            "fast-service": current_time - timedelta(minutes=3),  # Should allow
            "slow-service": current_time - timedelta(minutes=5),  # Should block
            "critical-service": current_time - timedelta(minutes=10),  # Should block
        }

        for service, config in configs.items():
            last_scale_time = scaling_times[service]
            time_since_scaling = current_time - last_scale_time
            cooldown_period = timedelta(minutes=config.cooldown_minutes)

            should_allow = time_since_scaling >= cooldown_period

            if service == "fast-service":
                assert should_allow is True
            else:
                assert should_allow is False


@pytest.mark.integration
class TestMultiPlatformSupport:
    """Test support for different deployment platforms."""

    def test_docker_swarm_scaling(self, mock_docker_client):
        """Test Docker Swarm scaling operations."""
        autoscaler = AutoScaler(platform=PlatformType.DOCKER_SWARM)
        autoscaler.docker_client = mock_docker_client

        # Mock service scaling
        mock_service = Mock()
        mock_docker_client.services.get.return_value = mock_service

        decision = ScalingDecision(
            service_name="test-service",
            action=ScalingAction.SCALE_UP,
            current_replicas=3,
            target_replicas=5,
            confidence=0.8,
            reason="Test scaling",
        )

        # Test scaling execution
        with patch.object(autoscaler, "_scale_docker_service") as mock_scale:
            mock_scale.return_value = asyncio.coroutine(lambda: True)()

            result = asyncio.run(autoscaler.execute_scaling_decision(decision))
            assert result is True
            mock_scale.assert_called_once_with(decision)

    def test_kubernetes_scaling(self, mock_k8s_client):
        """Test Kubernetes scaling operations."""
        autoscaler = AutoScaler(platform=PlatformType.KUBERNETES)
        autoscaler.k8s_client = mock_k8s_client

        decision = ScalingDecision(
            service_name="test-service",
            action=ScalingAction.SCALE_DOWN,
            current_replicas=8,
            target_replicas=6,
            confidence=0.7,
            reason="Test scaling",
        )

        with patch.object(autoscaler, "_scale_k8s_deployment") as mock_scale:
            mock_scale.return_value = asyncio.coroutine(lambda: True)()

            result = asyncio.run(autoscaler.execute_scaling_decision(decision))
            assert result is True
            mock_scale.assert_called_once_with(decision, "default")

    def test_platform_specific_replica_counting(
        self, mock_docker_client, mock_k8s_client
    ):
        """Test platform-specific replica counting."""
        # Docker Swarm
        docker_scaler = AutoScaler(platform=PlatformType.DOCKER_SWARM)
        docker_scaler.docker_client = mock_docker_client

        mock_service = Mock()
        mock_service.tasks.return_value = [
            {"Status": {"State": "running"}},
            {"Status": {"State": "running"}},
            {"Status": {"State": "running"}},
        ]
        mock_docker_client.services.get.return_value = mock_service

        replicas = docker_scaler.get_current_replicas("test-service")
        assert replicas == 3

        # Kubernetes
        k8s_scaler = AutoScaler(platform=PlatformType.KUBERNETES)
        k8s_scaler.k8s_client = mock_k8s_client

        mock_deployment = Mock()
        mock_deployment.status.ready_replicas = 5
        mock_k8s_client.read_namespaced_deployment.return_value = mock_deployment

        replicas = k8s_scaler.get_current_replicas("test-service")
        assert replicas == 5


@pytest.mark.load
@pytest.mark.slow
class TestAutoScalingPerformance:
    """Test auto-scaling system performance."""

    @pytest.mark.asyncio
    async def test_scaling_decision_latency(self, sample_metrics):
        """Test scaling decision calculation speed."""
        autoscaler = AutoScaler()
        autoscaler.service_configs["test-service"] = ServiceConfig(name="test-service")

        # Measure decision calculation time
        start_time = time.time()

        for _ in range(100):  # 100 scaling decisions
            decision = autoscaler.analyze_scaling_decision(
                "test-service", sample_metrics[-5:], 3
            )
            assert decision is not None

        end_time = time.time()
        avg_decision_time = (end_time - start_time) / 100

        # Decision should be fast (< 50ms per decision)
        assert (
            avg_decision_time < 0.05
        ), f"Scaling decision too slow: {avg_decision_time*1000:.1f}ms"

    @pytest.mark.asyncio
    async def test_concurrent_service_scaling(self, clean_redis):
        """Test scaling multiple services concurrently."""
        autoscaler = AutoScaler(redis_url="redis://localhost:6379")
        autoscaler.docker_client = Mock()

        # Setup multiple services
        services = ["service-1", "service-2", "service-3", "service-4", "service-5"]
        for service in services:
            autoscaler.service_configs[service] = ServiceConfig(name=service)

        async def mock_collect_metrics(service_name):
            # Simulate metrics collection delay
            await asyncio.sleep(0.1)
            return [
                MetricSample(
                    timestamp=datetime.utcnow(),
                    cpu_percent=70 + hash(service_name) % 30,
                    memory_percent=60 + hash(service_name) % 25,
                    active_connections=10,
                    response_time_ms=100,
                    queue_depth=5,
                )
            ]

        autoscaler.collect_metrics_for_service = mock_collect_metrics
        autoscaler.get_current_replicas = Mock(return_value=3)

        # Mock scaling execution
        async def mock_execute_scaling(decision):
            await asyncio.sleep(0.05)  # Simulate scaling time
            return True

        autoscaler.execute_scaling_decision = mock_execute_scaling

        # Test concurrent scaling cycle
        start_time = time.time()
        await autoscaler.run_scaling_cycle()
        end_time = time.time()

        scaling_cycle_time = end_time - start_time

        # Should complete within reasonable time despite multiple services
        assert (
            scaling_cycle_time < 2.0
        ), f"Scaling cycle too slow: {scaling_cycle_time:.2f}s"

    def test_memory_usage_with_large_history(self, clean_redis):
        """Test memory usage with large metrics history."""
        autoscaler = AutoScaler(redis_url="redis://localhost:6379")

        # Generate large metrics history
        service_name = "memory-test-service"
        large_history = []

        base_time = datetime.utcnow()
        for i in range(10000):  # 10k samples
            sample = MetricSample(
                timestamp=base_time - timedelta(minutes=i),
                cpu_percent=50 + (i % 50),
                memory_percent=40 + (i % 40),
                active_connections=10 + (i % 100),
                response_time_ms=100 + (i % 200),
                queue_depth=i % 50,
            )
            large_history.append(sample)

        autoscaler.metrics_history[service_name] = large_history

        # Test memory cleanup (should keep only last 24 hours)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        # Simulate the cleanup that happens in run_scaling_cycle
        autoscaler.metrics_history[service_name] = [
            s
            for s in autoscaler.metrics_history[service_name]
            if s.timestamp > cutoff_time
        ]

        # Should have significantly fewer samples (24 hours * 60/2 = 720 samples max)
        remaining_samples = len(autoscaler.metrics_history[service_name])
        assert (
            remaining_samples <= 1440
        ), f"Too many samples retained: {remaining_samples}"
        assert remaining_samples > 0, "No samples retained"


@pytest.mark.unit
class TestCostOptimization:
    """Test cost optimization features."""

    def test_cost_aware_scaling_decisions(self):
        """Test scaling decisions consider cost implications."""
        # Mock cost model
        cost_per_replica_hour = {
            "orchestrator": 0.10,
            "br_kg": 0.08,
            "agent": 0.25,  # Expensive (LLM service)
            "web-ui": 0.05,
        }

        def calculate_scaling_cost(service: str, current: int, target: int):
            replica_change = target - current
            hourly_cost_change = replica_change * cost_per_replica_hour[service]
            return hourly_cost_change

        # Test expensive service scaling
        agent_cost = calculate_scaling_cost("agent", 2, 4)  # +2 replicas
        web_cost = calculate_scaling_cost("web-ui", 2, 4)  # +2 replicas

        assert agent_cost > web_cost
        assert agent_cost == 0.50  # $0.25 * 2 additional replicas
        assert web_cost == 0.10  # $0.05 * 2 additional replicas

    def test_spot_instance_scaling_preference(self):
        """Test preference for spot instances in scaling decisions."""
        # Mock instance types with costs
        instance_types = {
            "on-demand": {"cost_per_hour": 0.20, "availability": 1.0},
            "spot": {"cost_per_hour": 0.06, "availability": 0.85},
            "reserved": {"cost_per_hour": 0.12, "availability": 1.0},
        }

        def select_instance_type(required_availability: float = 0.9):
            suitable_types = [
                (name, config)
                for name, config in instance_types.items()
                if config["availability"] >= required_availability
            ]

            if not suitable_types:
                return None

            # Return cheapest suitable option
            return min(suitable_types, key=lambda x: x[1]["cost_per_hour"])

        # For normal scaling (availability requirement met by spot)
        selected = select_instance_type(0.8)
        assert selected[0] == "spot"

        # For critical scaling (high availability required)
        selected = select_instance_type(0.95)
        assert selected[0] in ["on-demand", "reserved"]

    def test_scaling_cost_budgets(self):
        """Test scaling within cost budgets."""
        monthly_budget = 1000  # $1000/month
        current_monthly_cost = 850  # $850/month
        available_budget = monthly_budget - current_monthly_cost  # $150

        # Calculate max additional replicas within budget
        service_hourly_cost = 0.10  # $0.10/hour per replica
        hours_in_month = 24 * 30  # 720 hours
        max_additional_cost_per_hour = available_budget / hours_in_month
        max_additional_replicas = int(
            max_additional_cost_per_hour / service_hourly_cost
        )

        assert max_additional_replicas == 2  # Can afford 2 more replicas

        # Verify scaling decision respects budget
        desired_replicas = 10
        current_replicas = 3
        requested_additional = desired_replicas - current_replicas  # 7 replicas

        actual_additional = min(requested_additional, max_additional_replicas)
        final_replicas = current_replicas + actual_additional

        assert final_replicas == 5  # 3 + 2, limited by budget
        assert final_replicas < desired_replicas  # Budget-constrained


@pytest.mark.integration
@pytest.mark.slow
class TestAutoScalerIntegration:
    """Integration tests for the complete auto-scaling system."""

    @pytest.mark.asyncio
    async def test_end_to_end_scaling_workflow(self, clean_redis):
        """Test complete scaling workflow from metrics to execution."""
        if not clean_redis:
            pytest.skip("Redis not available")

        autoscaler = AutoScaler(
            platform=PlatformType.DOCKER_SWARM, redis_url="redis://localhost:6379"
        )

        # Mock platform clients
        autoscaler.docker_client = Mock()
        mock_service = Mock()
        mock_service.tasks.return_value = [
            {"Status": {"State": "running"}},
            {"Status": {"State": "running"}},
            {"Status": {"State": "running"}},
        ]
        autoscaler.docker_client.services.get.return_value = mock_service

        # Setup service config
        service_config = ServiceConfig(
            name="integration-test-service",
            min_replicas=2,
            max_replicas=8,
            target_cpu_percent=70,
            cooldown_minutes=1,  # Short cooldown for testing
        )
        autoscaler.service_configs["integration-test-service"] = service_config

        # Setup high-load metrics in Redis
        redis_client = clean_redis
        redis_client.lpush("queue:integration-test-service", *range(50))  # High queue
        redis_client.lpush(
            "metrics:response_times:integration-test-service",
            *[300, 350, 400, 450, 500],
        )  # High response times
        redis_client.set(
            "metrics:connections:integration-test-service", 100
        )  # High connections

        # Mock metrics collection to return high load
        async def mock_collect_metrics(service_name):
            return [
                MetricSample(
                    timestamp=datetime.utcnow(),
                    cpu_percent=85,  # High CPU
                    memory_percent=80,  # High memory
                    active_connections=100,
                    response_time_ms=400,
                    queue_depth=50,
                )
            ]

        autoscaler.collect_metrics_for_service = mock_collect_metrics

        # Mock scaling execution
        scaling_executed = False
        original_replicas = 3

        async def mock_scale_service(decision):
            nonlocal scaling_executed, original_replicas
            if decision.action == ScalingAction.SCALE_UP:
                scaling_executed = True
                # Update mock to reflect new replica count
                new_tasks = [
                    {"Status": {"State": "running"}}
                    for _ in range(decision.target_replicas)
                ]
                mock_service.tasks.return_value = new_tasks
                return True
            return False

        autoscaler._scale_docker_service = mock_scale_service

        # Run scaling cycle
        await autoscaler.run_scaling_cycle()

        # Verify scaling was triggered
        assert scaling_executed is True

        # Verify new replica count
        new_replica_count = len(mock_service.tasks())
        assert new_replica_count > original_replicas
        assert new_replica_count <= service_config.max_replicas

    @pytest.mark.asyncio
    async def test_predictive_scaling_integration(self, clean_redis, sample_metrics):
        """Test integration of predictive scaling with decision engine."""
        if not clean_redis:
            pytest.skip("Redis not available")

        autoscaler = AutoScaler(redis_url="redis://localhost:6379")
        autoscaler.docker_client = Mock()

        # Setup service with predictive scaling enabled
        service_config = ServiceConfig(
            name="predictive-test-service",
            enable_predictive=True,
            min_replicas=2,
            max_replicas=10,
        )
        autoscaler.service_configs["predictive-test-service"] = service_config

        # Add historical data for training
        autoscaler.metrics_history["predictive-test-service"] = sample_metrics

        # Train predictive model
        training_success = autoscaler.predictive_scaler.train_model(
            "predictive-test-service", sample_metrics
        )
        assert training_success is True

        # Mock current moderate load but high predicted load
        async def mock_collect_metrics(service_name):
            return [
                MetricSample(
                    timestamp=datetime.utcnow(),
                    cpu_percent=60,  # Moderate current load
                    memory_percent=55,
                    active_connections=30,
                    response_time_ms=150,
                    queue_depth=20,
                )
            ]

        autoscaler.collect_metrics_for_service = mock_collect_metrics
        autoscaler.get_current_replicas = Mock(return_value=3)

        # Mock high prediction
        autoscaler.predictive_scaler.predict_load = Mock(return_value=85.0)

        scaling_decision = None

        async def capture_scaling_decision(decision):
            nonlocal scaling_decision
            scaling_decision = decision
            return True

        autoscaler.execute_scaling_decision = capture_scaling_decision

        # Run scaling cycle
        await autoscaler.run_scaling_cycle()

        # Verify predictive scaling triggered scale-up
        assert scaling_decision is not None
        assert scaling_decision.action == ScalingAction.SCALE_UP
        assert "Predicted:" in scaling_decision.reason
        assert scaling_decision.confidence >= 0.9  # High confidence with prediction
