"""Production Monitoring System for Brain Researcher Agent

Provides comprehensive health monitoring, metrics collection, alerting,
and operational dashboards for production readiness.
"""

from brain_researcher.services.agent.monitoring.alerting import (
    Alert,
    AlertChannel,
    AlertManager,
    AlertRule,
    AlertSeverity,
    AlertState,
    CircuitBreaker,
    CircuitOpenError,
)
from brain_researcher.services.agent.monitoring.dashboard import (
    AlertRequest,
    HealthResponse,
    MetricsQuery,
    MonitoringDashboard,
)
from brain_researcher.services.agent.monitoring.health_monitor import (
    HealthCheck,
    HealthMonitor,
    HealthStatus,
    ServiceHealth,
    ServiceType,
    SystemMetrics,
)
from brain_researcher.services.agent.monitoring.metrics_collector import (
    Metric,
    MetricPoint,
    MetricsCollector,
    MetricType,
)

__all__ = [
    # Health monitoring
    "HealthMonitor",
    "HealthStatus",
    "HealthCheck",
    "ServiceHealth",
    "ServiceType",
    "SystemMetrics",
    # Alerting
    "AlertManager",
    "Alert",
    "AlertSeverity",
    "AlertChannel",
    "AlertRule",
    "AlertState",
    "CircuitBreaker",
    "CircuitOpenError",
    # Metrics
    "MetricsCollector",
    "Metric",
    "MetricType",
    "MetricPoint",
    # Dashboard
    "MonitoringDashboard",
    "HealthResponse",
    "AlertRequest",
    "MetricsQuery",
]

# Version information
__version__ = "1.0.0"
