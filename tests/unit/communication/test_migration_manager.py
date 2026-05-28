"""
Unit tests for Istio migration manager functionality.

Tests the migration logic for transitioning services to Istio service mesh,
including canary deployments, rollback mechanisms, and compatibility checks.
"""

import pytest
import asyncio
import json
import time
from unittest.mock import Mock, patch, AsyncMock, MagicMock, call
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

# Test markers
pytestmark = [pytest.mark.unit, pytest.mark.migration]


class MockMigrationState:
    """Mock migration state for testing."""
    
    def __init__(self):
        self.services = {}
        self.rollout_status = {}
        self.health_checks = {}
        self.traffic_splits = {}
    
    def set_service_state(self, service_name: str, state: str):
        self.services[service_name] = state
    
    def get_service_state(self, service_name: str) -> str:
        return self.services.get(service_name, "unknown")


@pytest.fixture
def mock_migration_state():
    """Provide mock migration state."""
    return MockMigrationState()


@pytest.fixture
def mock_k8s_client():
    """Mock Kubernetes client for migration operations."""
    client = Mock()
    client.AppsV1Api = Mock()
    client.CoreV1Api = Mock()
    client.CustomObjectsApi = Mock()
    return client


@pytest.fixture
def mock_istio_client():
    """Mock Istio client for CRD operations."""
    client = Mock()
    client.create_virtual_service = Mock(return_value=True)
    client.create_destination_rule = Mock(return_value=True)
    client.delete_virtual_service = Mock(return_value=True)
    client.delete_destination_rule = Mock(return_value=True)
    return client


class TestMigrationPlanner:
    """Test migration planning functionality."""
    
    @pytest.fixture
    def migration_planner(self, mock_k8s_client):
        """Create a migration planner instance."""
        from brain_researcher.infrastructure.istio.migration_planner import MigrationPlanner
        
        with patch('kubernetes.client', return_value=mock_k8s_client):
            planner = MigrationPlanner(namespace="brain-researcher")
        
        return planner
    
    def test_analyze_service_dependencies(self, migration_planner):
        """Test service dependency analysis."""
        services = {
            "web-ui": {
                "dependencies": ["orchestrator", "auth-service"],
                "dependents": []
            },
            "orchestrator": {
                "dependencies": ["neurokg", "agent"],
                "dependents": ["web-ui"]
            },
            "neurokg": {
                "dependencies": ["neo4j", "redis"],
                "dependents": ["orchestrator", "agent"]
            },
            "agent": {
                "dependencies": ["neurokg"],
                "dependents": ["orchestrator"]
            }
        }
        
        migration_order = migration_planner.calculate_migration_order(services)
        
        # Leaf services (with external dependencies) should come first
        assert migration_order.index("neurokg") < migration_order.index("agent")
        assert migration_order.index("agent") < migration_order.index("orchestrator")
        assert migration_order.index("orchestrator") < migration_order.index("web-ui")
    
    def test_compatibility_check(self, migration_planner):
        """Test service compatibility checking."""
        service_specs = {
            "name": "neurokg-service",
            "version": "1.0.0",
            "protocols": ["HTTP", "gRPC"],
            "health_endpoint": "/health",
            "readiness_endpoint": "/ready",
            "metrics_endpoint": "/metrics"
        }
        
        compatibility = migration_planner.check_istio_compatibility(service_specs)
        
        assert compatibility["compatible"] is True
        assert "HTTP" in compatibility["supported_protocols"]
        assert compatibility["health_checks_available"] is True
    
    def test_resource_estimation(self, migration_planner):
        """Test resource estimation for Istio migration."""
        service_config = {
            "replicas": 3,
            "cpu_request": "100m",
            "memory_request": "128Mi",
            "cpu_limit": "500m",
            "memory_limit": "512Mi"
        }
        
        estimated_resources = migration_planner.estimate_migration_resources(service_config)
        
        # Should account for sidecar overhead
        assert estimated_resources["cpu_overhead"] > 0
        assert estimated_resources["memory_overhead"] > 0
        assert estimated_resources["total_cpu"] > service_config["cpu_limit"]
        assert estimated_resources["total_memory"] > service_config["memory_limit"]
    
    def test_migration_strategy_selection(self, migration_planner):
        """Test migration strategy selection."""
        service_profile = {
            "criticality": "high",
            "traffic_volume": "medium",
            "dependencies": 3,
            "external_traffic": True
        }
        
        strategy = migration_planner.select_migration_strategy(service_profile)
        
        # High criticality services should use blue-green or canary
        assert strategy in ["blue-green", "canary"]
    
    def test_rollback_plan_generation(self, migration_planner):
        """Test rollback plan generation."""
        migration_config = {
            "service": "neurokg-service",
            "strategy": "canary",
            "traffic_splits": [10, 50, 100],
            "validation_steps": ["health_check", "smoke_test", "load_test"]
        }
        
        rollback_plan = migration_planner.generate_rollback_plan(migration_config)
        
        assert "emergency_rollback" in rollback_plan
        assert "gradual_rollback" in rollback_plan
        assert rollback_plan["emergency_rollback"]["max_time"] <= 300  # 5 minutes


class TestCanaryDeployment:
    """Test canary deployment functionality."""
    
    @pytest.fixture
    def canary_deployer(self, mock_k8s_client, mock_istio_client):
        """Create a canary deployer instance."""
        from brain_researcher.infrastructure.istio.canary_deployer import CanaryDeployer
        
        with patch('kubernetes.client', return_value=mock_k8s_client):
            deployer = CanaryDeployer(
                namespace="brain-researcher",
                istio_client=mock_istio_client
            )
        
        return deployer
    
    def test_canary_deployment_initialization(self, canary_deployer):
        """Test canary deployment initialization."""
        canary_config = {
            "service_name": "neurokg-service",
            "canary_version": "v2",
            "stable_version": "v1",
            "traffic_splits": [10, 25, 50, 75, 100],
            "step_duration": "5m",
            "success_criteria": {
                "error_rate_threshold": 0.05,
                "latency_p99_threshold": 1000
            }
        }
        
        deployment_id = canary_deployer.initialize_canary(canary_config)
        
        assert deployment_id is not None
        assert len(deployment_id) > 0
        
        deployment_status = canary_deployer.get_deployment_status(deployment_id)
        assert deployment_status["phase"] == "initialized"
        assert deployment_status["current_traffic"] == 0
    
    def test_traffic_split_progression(self, canary_deployer):
        """Test traffic split progression during canary deployment."""
        deployment_id = "test-canary-001"
        
        # Initialize canary
        canary_config = {
            "service_name": "neurokg-service",
            "traffic_splits": [10, 50, 100]
        }
        canary_deployer.deployments[deployment_id] = {
            "config": canary_config,
            "current_step": 0,
            "phase": "initialized"
        }
        
        # Progress through traffic splits
        result = canary_deployer.advance_traffic_split(deployment_id)
        
        assert result is True
        status = canary_deployer.get_deployment_status(deployment_id)
        assert status["current_traffic"] == 10
        assert status["current_step"] == 1
    
    def test_canary_health_validation(self, canary_deployer):
        """Test canary version health validation."""
        deployment_id = "test-canary-002"
        
        # Mock health metrics
        with patch.object(canary_deployer, 'collect_canary_metrics') as mock_metrics:
            mock_metrics.return_value = {
                "error_rate": 0.02,  # Below threshold
                "latency_p99": 800,  # Below threshold
                "request_count": 1000,
                "success_rate": 0.98
            }
            
            health_status = canary_deployer.validate_canary_health(deployment_id)
            
            assert health_status["healthy"] is True
            assert health_status["error_rate"] < 0.05
            assert health_status["latency_p99"] < 1000
    
    def test_canary_failure_detection(self, canary_deployer):
        """Test canary failure detection and automatic rollback."""
        deployment_id = "test-canary-003"
        
        # Mock failing metrics
        with patch.object(canary_deployer, 'collect_canary_metrics') as mock_metrics:
            mock_metrics.return_value = {
                "error_rate": 0.15,  # Above threshold
                "latency_p99": 2000,  # Above threshold
                "request_count": 500
            }
            
            health_status = canary_deployer.validate_canary_health(deployment_id)
            
            assert health_status["healthy"] is False
            assert health_status["requires_rollback"] is True
    
    def test_automatic_rollback(self, canary_deployer):
        """Test automatic rollback on canary failure."""
        deployment_id = "test-canary-004"
        
        canary_deployer.deployments[deployment_id] = {
            "config": {
                "service_name": "neurokg-service",
                "stable_version": "v1",
                "canary_version": "v2"
            },
            "current_step": 2,
            "current_traffic": 50,
            "phase": "rolling_out"
        }
        
        rollback_result = canary_deployer.execute_rollback(deployment_id, reason="high_error_rate")
        
        assert rollback_result["success"] is True
        assert rollback_result["rollback_time"] < 300  # Should complete quickly
        
        status = canary_deployer.get_deployment_status(deployment_id)
        assert status["phase"] == "rolled_back"
        assert status["current_traffic"] == 0
    
    def test_canary_completion(self, canary_deployer):
        """Test successful canary deployment completion."""
        deployment_id = "test-canary-005"
        
        canary_deployer.deployments[deployment_id] = {
            "config": {
                "service_name": "neurokg-service",
                "traffic_splits": [10, 50, 100]
            },
            "current_step": 2,  # Last step
            "current_traffic": 50,
            "phase": "rolling_out"
        }
        
        # Mock successful metrics for final step
        with patch.object(canary_deployer, 'validate_canary_health') as mock_validation:
            mock_validation.return_value = {"healthy": True}
            
            # Complete final step
            result = canary_deployer.advance_traffic_split(deployment_id)
            
            assert result is True
            status = canary_deployer.get_deployment_status(deployment_id)
            assert status["current_traffic"] == 100
            assert status["phase"] == "completed"


class TestBlueGreenDeployment:
    """Test blue-green deployment functionality."""
    
    @pytest.fixture
    def blue_green_deployer(self, mock_k8s_client, mock_istio_client):
        """Create a blue-green deployer instance."""
        from brain_researcher.infrastructure.istio.blue_green_deployer import BlueGreenDeployer
        
        with patch('kubernetes.client', return_value=mock_k8s_client):
            deployer = BlueGreenDeployer(
                namespace="brain-researcher",
                istio_client=mock_istio_client
            )
        
        return deployer
    
    def test_green_environment_setup(self, blue_green_deployer):
        """Test green environment setup."""
        deployment_config = {
            "service_name": "neurokg-service",
            "blue_version": "v1",
            "green_version": "v2",
            "replicas": 3,
            "resources": {
                "cpu": "500m",
                "memory": "1Gi"
            }
        }
        
        deployment_id = blue_green_deployer.setup_green_environment(deployment_config)
        
        assert deployment_id is not None
        
        deployment_status = blue_green_deployer.get_deployment_status(deployment_id)
        assert deployment_status["green_ready"] is True
        assert deployment_status["traffic_on_green"] is False
    
    def test_traffic_switch(self, blue_green_deployer):
        """Test traffic switching from blue to green."""
        deployment_id = "bg-deploy-001"
        
        blue_green_deployer.deployments[deployment_id] = {
            "config": {
                "service_name": "neurokg-service",
                "blue_version": "v1",
                "green_version": "v2"
            },
            "green_ready": True,
            "traffic_on_green": False
        }
        
        switch_result = blue_green_deployer.switch_traffic_to_green(deployment_id)
        
        assert switch_result["success"] is True
        assert switch_result["switch_time"] < 60  # Should be fast
        
        status = blue_green_deployer.get_deployment_status(deployment_id)
        assert status["traffic_on_green"] is True
    
    def test_blue_green_rollback(self, blue_green_deployer):
        """Test blue-green rollback."""
        deployment_id = "bg-deploy-002"
        
        blue_green_deployer.deployments[deployment_id] = {
            "config": {"service_name": "neurokg-service"},
            "green_ready": True,
            "traffic_on_green": True,
            "blue_preserved": True
        }
        
        rollback_result = blue_green_deployer.rollback_to_blue(deployment_id)
        
        assert rollback_result["success"] is True
        
        status = blue_green_deployer.get_deployment_status(deployment_id)
        assert status["traffic_on_green"] is False
    
    def test_cleanup_old_version(self, blue_green_deployer):
        """Test cleanup of old version after successful deployment."""
        deployment_id = "bg-deploy-003"
        
        blue_green_deployer.deployments[deployment_id] = {
            "config": {"service_name": "neurokg-service"},
            "traffic_on_green": True,
            "deployment_successful": True,
            "grace_period_expired": True
        }
        
        cleanup_result = blue_green_deployer.cleanup_old_version(deployment_id)
        
        assert cleanup_result["success"] is True
        assert cleanup_result["resources_released"] > 0


class TestMigrationOrchestrator:
    """Test migration orchestrator functionality."""
    
    @pytest.fixture
    def migration_orchestrator(self, mock_k8s_client, mock_istio_client, mock_migration_state):
        """Create a migration orchestrator instance."""
        from brain_researcher.infrastructure.istio.migration_orchestrator import MigrationOrchestrator
        
        with patch('kubernetes.client', return_value=mock_k8s_client):
            orchestrator = MigrationOrchestrator(
                namespace="brain-researcher",
                istio_client=mock_istio_client
            )
            orchestrator.state = mock_migration_state
        
        return orchestrator
    
    def test_full_migration_workflow(self, migration_orchestrator):
        """Test complete migration workflow orchestration."""
        migration_plan = {
            "services": ["neurokg", "agent", "orchestrator", "web-ui"],
            "strategy": "phased",
            "validation_steps": ["health_check", "integration_test"],
            "rollback_policy": "auto_on_failure"
        }
        
        migration_id = migration_orchestrator.start_migration(migration_plan)
        
        assert migration_id is not None
        
        status = migration_orchestrator.get_migration_status(migration_id)
        assert status["phase"] == "started"
        assert status["services_migrated"] == 0
    
    def test_service_migration_ordering(self, migration_orchestrator):
        """Test service migration ordering based on dependencies."""
        migration_id = "migration-001"
        
        services = {
            "web-ui": {"dependencies": ["orchestrator"]},
            "orchestrator": {"dependencies": ["neurokg", "agent"]},
            "agent": {"dependencies": ["neurokg"]},
            "neurokg": {"dependencies": []}
        }
        
        migration_orchestrator.migrations[migration_id] = {
            "services": services,
            "current_service": None,
            "completed_services": []
        }
        
        next_service = migration_orchestrator.get_next_service_to_migrate(migration_id)
        
        # Should start with neurokg (no dependencies)
        assert next_service == "neurokg"
    
    def test_migration_validation(self, migration_orchestrator):
        """Test migration validation at each step."""
        migration_id = "migration-002"
        service_name = "neurokg"
        
        with patch.object(migration_orchestrator, 'run_validation_tests') as mock_validation:
            mock_validation.return_value = {
                "health_check": {"passed": True, "duration": 5.2},
                "integration_test": {"passed": True, "duration": 12.8},
                "smoke_test": {"passed": True, "duration": 8.1}
            }
            
            validation_result = migration_orchestrator.validate_service_migration(
                migration_id, service_name
            )
            
            assert validation_result["success"] is True
            assert all(test["passed"] for test in validation_result["tests"].values())
    
    def test_migration_failure_handling(self, migration_orchestrator):
        """Test migration failure handling and rollback."""
        migration_id = "migration-003"
        
        migration_orchestrator.migrations[migration_id] = {
            "services": ["neurokg", "agent"],
            "completed_services": ["neurokg"],
            "current_service": "agent",
            "rollback_policy": "auto_on_failure"
        }
        
        # Simulate migration failure
        with patch.object(migration_orchestrator, 'migrate_service') as mock_migrate:
            mock_migrate.return_value = {"success": False, "error": "Deployment failed"}
            
            result = migration_orchestrator.handle_migration_failure(migration_id, "agent")
            
            assert result["action"] == "rollback_initiated"
            assert result["rollback_scope"] == "full_migration"
    
    def test_migration_pause_resume(self, migration_orchestrator):
        """Test migration pause and resume functionality."""
        migration_id = "migration-004"
        
        migration_orchestrator.migrations[migration_id] = {
            "status": "in_progress",
            "current_service": "agent"
        }
        
        # Pause migration
        pause_result = migration_orchestrator.pause_migration(migration_id)
        assert pause_result["success"] is True
        
        status = migration_orchestrator.get_migration_status(migration_id)
        assert status["status"] == "paused"
        
        # Resume migration
        resume_result = migration_orchestrator.resume_migration(migration_id)
        assert resume_result["success"] is True
        
        status = migration_orchestrator.get_migration_status(migration_id)
        assert status["status"] == "in_progress"
    
    def test_migration_progress_tracking(self, migration_orchestrator):
        """Test migration progress tracking."""
        migration_id = "migration-005"
        
        migration_orchestrator.migrations[migration_id] = {
            "services": ["neurokg", "agent", "orchestrator", "web-ui"],
            "completed_services": ["neurokg", "agent"],
            "current_service": "orchestrator",
            "start_time": datetime.now() - timedelta(minutes=30)
        }
        
        progress = migration_orchestrator.get_migration_progress(migration_id)
        
        assert progress["completion_percentage"] == 50.0  # 2/4 services
        assert progress["current_phase"] == "orchestrator"
        assert progress["estimated_time_remaining"] > 0


class TestMigrationValidator:
    """Test migration validation functionality."""
    
    @pytest.fixture
    def migration_validator(self):
        """Create a migration validator instance."""
        from brain_researcher.infrastructure.istio.migration_validator import MigrationValidator
        
        return MigrationValidator(namespace="brain-researcher")
    
    def test_pre_migration_checks(self, migration_validator):
        """Test pre-migration validation checks."""
        service_config = {
            "name": "neurokg-service",
            "image": "neurokg:v2",
            "ports": [{"containerPort": 5001}],
            "env": [{"name": "DB_HOST", "value": "neo4j"}],
            "resources": {
                "requests": {"cpu": "100m", "memory": "256Mi"},
                "limits": {"cpu": "500m", "memory": "1Gi"}
            }
        }
        
        validation_result = migration_validator.run_pre_migration_checks(service_config)
        
        assert validation_result["passed"] is True
        assert "resource_validation" in validation_result["checks"]
        assert "port_validation" in validation_result["checks"]
        assert "image_validation" in validation_result["checks"]
    
    def test_istio_readiness_check(self, migration_validator):
        """Test Istio readiness validation."""
        with patch.object(migration_validator, 'check_istio_components') as mock_check:
            mock_check.return_value = {
                "pilot": {"ready": True, "version": "1.18.0"},
                "proxy": {"ready": True, "version": "1.18.0"},
                "citadel": {"ready": True, "version": "1.18.0"}
            }
            
            readiness = migration_validator.validate_istio_readiness()
            
            assert readiness["ready"] is True
            assert all(component["ready"] for component in readiness["components"].values())
    
    def test_service_mesh_compatibility(self, migration_validator):
        """Test service mesh compatibility validation."""
        service_spec = {
            "protocols": ["HTTP/1.1", "HTTP/2", "gRPC"],
            "health_endpoints": {
                "liveness": "/health",
                "readiness": "/ready"
            },
            "metrics_endpoint": "/metrics",
            "observability_ready": True
        }
        
        compatibility = migration_validator.validate_mesh_compatibility(service_spec)
        
        assert compatibility["compatible"] is True
        assert compatibility["protocol_support"]["HTTP/1.1"] is True
        assert compatibility["protocol_support"]["gRPC"] is True
        assert compatibility["observability_ready"] is True
    
    def test_network_policy_validation(self, migration_validator):
        """Test network policy validation for Istio migration."""
        network_policies = [
            {
                "name": "allow-ingress",
                "spec": {
                    "podSelector": {"matchLabels": {"app": "neurokg"}},
                    "ingress": [{
                        "from": [{"podSelector": {"matchLabels": {"app": "orchestrator"}}}]
                    }]
                }
            }
        ]
        
        validation = migration_validator.validate_network_policies(network_policies)
        
        assert validation["compatible"] is True
        assert validation["migration_required"] is True  # Will need Istio AuthorizationPolicy


@pytest.mark.parametrize("deployment_strategy", ["canary", "blue-green", "rolling"])
def test_deployment_strategy_selection(deployment_strategy):
    """Test different deployment strategies."""
    from brain_researcher.infrastructure.istio.strategy_selector import DeploymentStrategySelector
    
    selector = DeploymentStrategySelector()
    
    service_profile = {
        "criticality": "high" if deployment_strategy != "rolling" else "medium",
        "traffic_volume": "high",
        "rollback_tolerance": "low"
    }
    
    selected_strategy = selector.select_strategy(service_profile, preferred=deployment_strategy)
    
    if deployment_strategy == "rolling" and service_profile["criticality"] == "high":
        # Should override rolling with safer strategy for high criticality
        assert selected_strategy in ["canary", "blue-green"]
    else:
        assert selected_strategy == deployment_strategy


@pytest.mark.asyncio
async def test_concurrent_migrations():
    """Test concurrent migration handling."""
    from brain_researcher.infrastructure.istio.concurrent_migrator import ConcurrentMigrator
    
    migrator = ConcurrentMigrator(max_concurrent=2)
    
    # Create multiple migration tasks
    migration_tasks = []
    for i in range(5):
        task = migrator.create_migration_task(f"service-{i}", {"strategy": "canary"})
        migration_tasks.append(task)
    
    # Execute migrations with concurrency limit
    results = await migrator.execute_migrations(migration_tasks)
    
    assert len(results) == 5
    assert all(result["completed"] for result in results)
    
    # Verify concurrency limit was respected
    assert migrator.max_concurrent_reached_count >= 1


class TestMigrationMetrics:
    """Test migration metrics collection."""
    
    @pytest.fixture
    def metrics_collector(self):
        """Create a metrics collector instance."""
        from brain_researcher.infrastructure.istio.metrics_collector import MigrationMetricsCollector
        
        return MigrationMetricsCollector()
    
    def test_migration_duration_tracking(self, metrics_collector):
        """Test migration duration tracking."""
        migration_id = "migration-metrics-001"
        
        metrics_collector.start_migration_timer(migration_id)
        
        # Simulate some migration work
        time.sleep(0.1)
        
        duration = metrics_collector.end_migration_timer(migration_id)
        
        assert duration > 0.1
        assert duration < 1.0  # Should be reasonable for test
    
    def test_error_rate_calculation(self, metrics_collector):
        """Test error rate calculation during migration."""
        migration_id = "migration-metrics-002"
        
        # Record some successes and failures
        for _ in range(8):
            metrics_collector.record_operation_result(migration_id, success=True)
        
        for _ in range(2):
            metrics_collector.record_operation_result(migration_id, success=False)
        
        error_rate = metrics_collector.calculate_error_rate(migration_id)
        
        assert error_rate == 0.2  # 2/10 = 20%
    
    def test_rollback_metrics(self, metrics_collector):
        """Test rollback metrics collection."""
        rollback_event = {
            "migration_id": "migration-003",
            "service": "neurokg",
            "reason": "high_error_rate",
            "rollback_duration": 45.2,
            "rollback_strategy": "immediate"
        }
        
        metrics_collector.record_rollback_event(rollback_event)
        
        rollback_stats = metrics_collector.get_rollback_statistics()
        
        assert rollback_stats["total_rollbacks"] == 1
        assert "high_error_rate" in rollback_stats["rollback_reasons"]
        assert rollback_stats["average_rollback_time"] == 45.2