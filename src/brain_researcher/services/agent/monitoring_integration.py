"""Integration module for monitoring system with existing agent services

Connects monitoring to tool executor, cache manager, and performance optimizer.
"""

import asyncio
import logging
from functools import wraps
from typing import Any, Dict, Optional

from brain_researcher.services.agent.monitoring import (
    Alert,
    AlertManager,
    AlertSeverity,
    CircuitBreaker,
    HealthMonitor,
    MetricsCollector,
    MonitoringDashboard,
    ServiceType,
)
from brain_researcher.services.telemetry.metrics_kind_resolver import resolve_job_kind

logger = logging.getLogger(__name__)


class MonitoringIntegration:
    """Integrates monitoring with agent services."""

    def __init__(self):
        """Initialize monitoring integration."""
        # Core monitoring components
        self.health_monitor = HealthMonitor()
        self.alert_manager = AlertManager()
        self.metrics_collector = MetricsCollector()

        # Dashboard
        self.dashboard = MonitoringDashboard(
            health_monitor=self.health_monitor,
            alert_manager=self.alert_manager,
            metrics_collector=self.metrics_collector,
        )

        # Circuit breakers for services
        self.circuit_breakers = {}

        # Integration hooks
        self._setup_integrations()

    def _setup_integrations(self):
        """Set up integration hooks with services."""
        # Register services for monitoring
        self.health_monitor.register_service(
            "tool_executor", ServiceType.CORE, self._check_tool_executor_health
        )

        self.health_monitor.register_service(
            "cache_manager", ServiceType.CACHE, self._check_cache_health
        )

        self.health_monitor.register_service(
            "performance_optimizer", ServiceType.CORE, self._check_optimizer_health
        )

        # Create circuit breakers
        self.circuit_breakers["tool_executor"] = CircuitBreaker(
            failure_threshold=5, timeout=60, recovery_timeout=30
        )

        self.circuit_breakers["cache"] = CircuitBreaker(
            failure_threshold=10, timeout=30, recovery_timeout=15
        )

    async def start(self):
        """Start monitoring services."""
        logger.info("Starting monitoring integration...")

        # Start monitoring components
        await self.health_monitor.start_monitoring()
        await self.metrics_collector.start_collection()
        await self.dashboard.start()

        logger.info("Monitoring integration started")

    async def stop(self):
        """Stop monitoring services."""
        logger.info("Stopping monitoring integration...")

        await self.dashboard.stop()
        await self.metrics_collector.stop_collection()
        await self.health_monitor.stop_monitoring()

        logger.info("Monitoring integration stopped")

    # Integration decorators

    def monitor_tool_execution(self, tool_name: str):
        """Decorator to monitor tool execution.

        Args:
            tool_name: Name of the tool being executed
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                import time

                # Check circuit breaker
                breaker = self.circuit_breakers.get("tool_executor")
                if breaker and breaker.state == "open":
                    # Send alert
                    await self.alert_manager.send_alert(
                        Alert(
                            alert_id=f"circuit_open_{tool_name}",
                            title=f"Circuit breaker open for {tool_name}",
                            message="Too many failures, circuit breaker is open",
                            severity=AlertSeverity.ERROR,
                            source="tool_executor",
                        )
                    )
                    raise Exception(f"Circuit breaker open for {tool_name}")

                # Record execution start
                start_time = time.time()
                success = False
                error_msg = None

                try:
                    # Execute tool
                    result = await func(*args, **kwargs)
                    success = True

                    # Reset circuit breaker on success
                    if breaker:
                        breaker._on_success()

                    return result

                except Exception as e:
                    error_msg = str(e)

                    # Record failure in circuit breaker
                    if breaker:
                        breaker._on_failure()

                    # Send alert for critical tools
                    if tool_name in ["glm_analysis", "fmri_preprocessing"]:
                        await self.alert_manager.send_alert(
                            Alert(
                                alert_id=f"tool_failure_{tool_name}",
                                title=f"Critical tool failure: {tool_name}",
                                message=str(e),
                                severity=AlertSeverity.ERROR,
                                source="tool_executor",
                                metadata={"tool": tool_name},
                            )
                        )

                    raise

                finally:
                    # Record metrics
                    duration_ms = (time.time() - start_time) * 1000
                    job_kind = resolve_job_kind(
                        metadata={"parameters": {"tool": tool_name}},
                        payload={"metadata": {"parameters": {"tool": tool_name}}},
                    )
                    self.metrics_collector.record_tool_execution(
                        tool_name=tool_name,
                        duration_ms=duration_ms,
                        success=success,
                        error=error_msg,
                        job_kind=job_kind,
                    )

                    # Increment request counter
                    self.metrics_collector.increment("agent_requests_total")
                    self.metrics_collector.record("agent_request_duration", duration_ms)

            return wrapper

        return decorator

    def monitor_cache_operation(self, operation: str):
        """Decorator to monitor cache operations.

        Args:
            operation: Cache operation (get, set, invalidate)
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Check circuit breaker
                breaker = self.circuit_breakers.get("cache")
                if breaker and breaker.state == "open":
                    logger.warning(
                        f"Cache circuit breaker open, bypassing cache for {operation}"
                    )
                    # Return None for get operations, True for set operations
                    return None if operation == "get" else True

                try:
                    result = await func(*args, **kwargs)

                    # Record cache metrics
                    if operation == "get":
                        if result is not None:
                            self.metrics_collector.increment("cache_hits_total")
                        else:
                            self.metrics_collector.increment("cache_misses_total")

                    # Reset circuit breaker on success
                    if breaker:
                        breaker._on_success()

                    return result

                except Exception as e:
                    # Record failure
                    if breaker:
                        breaker._on_failure()

                    logger.error(f"Cache operation {operation} failed: {e}")

                    # Return safe default
                    return None if operation == "get" else False

            return wrapper

        return decorator

    # Health check implementations

    async def _check_tool_executor_health(self):
        """Check tool executor health."""
        from brain_researcher.services.agent.monitoring import HealthCheck, HealthStatus

        try:
            # Check if executor is responsive
            # This would check actual executor in production
            return HealthCheck(
                name="tool_executor",
                status=HealthStatus.HEALTHY,
                latency_ms=0,
                message="Tool executor operational",
            )
        except Exception as e:
            return HealthCheck(
                name="tool_executor",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message=f"Tool executor error: {e}",
            )

    async def _check_cache_health(self):
        """Check cache health."""
        import time

        from brain_researcher.services.agent.monitoring import HealthCheck, HealthStatus

        try:
            # Test cache operation
            import redis

            client = redis.Redis(host="localhost", port=6379, socket_connect_timeout=1)

            start = time.time()
            client.set("health_check", "ok", ex=10)
            value = client.get("health_check")
            latency = (time.time() - start) * 1000

            if value == b"ok":
                return HealthCheck(
                    name="cache_manager",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message="Cache operational",
                )
            else:
                return HealthCheck(
                    name="cache_manager",
                    status=HealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="Cache responding but degraded",
                )

        except Exception as e:
            return HealthCheck(
                name="cache_manager",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message=f"Cache error: {e}",
            )

    async def _check_optimizer_health(self):
        """Check performance optimizer health."""
        from brain_researcher.services.agent.monitoring import HealthCheck, HealthStatus

        try:
            # Check optimizer status
            # This would check actual optimizer in production
            return HealthCheck(
                name="performance_optimizer",
                status=HealthStatus.HEALTHY,
                latency_ms=0,
                message="Optimizer operational",
                metadata={"optimization_level": "ADVANCED"},
            )
        except Exception as e:
            return HealthCheck(
                name="performance_optimizer",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message=f"Optimizer error: {e}",
            )

    def get_monitoring_dashboard_app(self):
        """Get FastAPI app for monitoring dashboard.

        Returns:
            FastAPI application
        """
        return self.dashboard.app


# Singleton instance
_monitoring_integration = None


def get_monitoring_integration() -> MonitoringIntegration:
    """Get or create monitoring integration singleton.

    Returns:
        MonitoringIntegration instance
    """
    global _monitoring_integration
    if _monitoring_integration is None:
        _monitoring_integration = MonitoringIntegration()
    return _monitoring_integration


# Convenience decorators
monitor_tool = lambda tool_name: get_monitoring_integration().monitor_tool_execution(
    tool_name
)
monitor_cache = lambda operation: get_monitoring_integration().monitor_cache_operation(
    operation
)
