"""Istio service mesh integration stubs for local/testing usage."""

from .blue_green_deployer import BlueGreenDeployer
from .bridge import IstioBridge
from .canary_deployer import CanaryDeployer
from .concurrent_migrator import ConcurrentMigrator
from .config_templates import IstioConfigTemplates
from .config_validator import IstioConfigValidator
from .metrics_collector import MigrationMetricsCollector
from .migration_orchestrator import MigrationOrchestrator
from .migration_planner import MigrationPlanner
from .migration_validator import MigrationValidator
from .observability_manager import IstioObservabilityManager
from .security_manager import IstioSecurityManager
from .service_registry import IstioServiceRegistry
from .strategy_selector import DeploymentStrategySelector
from .traffic_manager import IstioTrafficManager

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
