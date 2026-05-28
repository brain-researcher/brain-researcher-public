"""Production Monitoring System for Brain Researcher Agent

Provides comprehensive health monitoring, metrics collection, alerting,
and operational dashboards for production readiness.
"""

from brain_researcher.services.agent.monitoring.health_monitor import (
    HealthMonitor,
    HealthStatus,
    HealthCheck,
    ServiceHealth,
    ServiceType,
    SystemMetrics
)

from brain_researcher.services.agent.monitoring.alerting import (
    AlertManager,
    Alert,
    AlertSeverity,
    AlertChannel,
    AlertRule,
    AlertState,
    CircuitBreaker,
    CircuitOpenError
)

from brain_researcher.services.agent.monitoring.metrics_collector import (
    MetricsCollector,
    Metric,
    MetricType,
    MetricPoint
)

from brain_researcher.services.agent.monitoring.dashboard import (
    MonitoringDashboard,
    HealthResponse,
    AlertRequest,
    MetricsQuery
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
    "MetricsQuery"
]

# Version information
__version__ = "1.0.0"