"""Istio service mesh integration stubs for local/testing usage."""

from .service_registry import IstioServiceRegistry
from .traffic_manager import IstioTrafficManager
from .security_manager import IstioSecurityManager
from .observability_manager import IstioObservabilityManager
from .bridge import IstioBridge
from .config_validator import IstioConfigValidator
from .config_templates import IstioConfigTemplates
from .migration_planner import MigrationPlanner
from .canary_deployer import CanaryDeployer
from .blue_green_deployer import BlueGreenDeployer
from .migration_orchestrator import MigrationOrchestrator
from .migration_validator import MigrationValidator
from .strategy_selector import DeploymentStrategySelector
from .concurrent_migrator import ConcurrentMigrator
from .metrics_collector import MigrationMetricsCollector

__all__ = [
    "IstioServiceRegistry",
    "IstioTrafficManager",
    "IstioSecurityManager",
    "IstioObservabilityManager",
    "IstioBridge",
    "IstioConfigValidator",
    "IstioConfigTemplates",
    "MigrationPlanner",
    "CanaryDeployer",
    "BlueGreenDeployer",
    "MigrationOrchestrator",
    "MigrationValidator",
    "DeploymentStrategySelector",
    "ConcurrentMigrator",
    "MigrationMetricsCollector",
]
