"""
Health Monitor for API Gateway.

Monitors the health and availability of all registered services with:

Features:
- Configurable health check intervals
- Multiple health check types (HTTP, TCP, custom)
- Health check retries and timeouts
- Circuit breaker integration
- Health metrics collection
- Service dependency mapping
- Health check alerts and notifications
- Graceful degradation strategies
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

import httpx
from httpx import AsyncClient, ConnectTimeout, ReadTimeout
from pydantic import BaseModel, Field

from .service_registry import (
    Service,
    ServiceHealth,
    ServiceInstance,
    ServiceRegistry,
    ServiceStatus,
)

logger = logging.getLogger(__name__)


class HealthCheckType(str, Enum):
    """Types of health checks."""

    HTTP = "http"
    TCP = "tcp"
    CUSTOM = "custom"


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class HealthCheckConfig:
    """Health check configuration."""

    type: HealthCheckType = HealthCheckType.HTTP
    path: str = "/health"
    method: str = "GET"
    timeout_seconds: int = 5
    interval_seconds: int = 30
    retries: int = 3
    retry_delay_seconds: int = 5
    expected_status_codes: List[int] = None
    expected_response_contains: Optional[str] = None
    custom_headers: Dict[str, str] = None

    def __post_init__(self):
        if self.expected_status_codes is None:
            self.expected_status_codes = [200, 204]
        if self.custom_headers is None:
            self.custom_headers = {}


class ServiceDependency(BaseModel):
    """Service dependency relationship."""

    service_name: str = Field(..., description="Dependent service name")
    dependency_name: str = Field(..., description="Dependency service name")
    dependency_type: str = Field(
        "required", description="Dependency type (required/optional)"
    )
    health_threshold: float = Field(0.8, description="Minimum health threshold")


class HealthAlert(BaseModel):
    """Health monitoring alert."""

    alert_id: str = Field(..., description="Alert identifier")
    service_name: str = Field(..., description="Service name")
    instance_id: Optional[str] = Field(None, description="Instance ID")
    severity: AlertSeverity = Field(..., description="Alert severity")
    message: str = Field(..., description="Alert message")
    timestamp: datetime = Field(..., description="Alert timestamp")
    resolved: bool = Field(False, description="Alert resolved status")
    resolved_at: Optional[datetime] = Field(None, description="Resolution timestamp")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class HealthMetrics(BaseModel):
    """Health monitoring metrics."""

    service_name: str = Field(..., description="Service name")
    total_checks: int = Field(0, description="Total health checks performed")
    successful_checks: int = Field(0, description="Successful health checks")
    failed_checks: int = Field(0, description="Failed health checks")
    average_response_time_ms: float = Field(0.0, description="Average response time")
    uptime_percentage: float = Field(100.0, description="Uptime percentage")
    last_check_time: Optional[datetime] = Field(
        None, description="Last check timestamp"
    )
    consecutive_failures: int = Field(0, description="Consecutive failures")
    consecutive_successes: int = Field(0, description="Consecutive successes")


class HealthMonitor:
    """Health monitoring service."""

    def __init__(
        self,
        service_registry: ServiceRegistry,
        default_check_config: Optional[HealthCheckConfig] = None,
    ):
        """Initialize health monitor.

        Args:
            service_registry: Service registry instance
            default_check_config: Default health check configuration
        """
        self.service_registry = service_registry
        self.default_config = default_check_config or HealthCheckConfig()

        # Service-specific configurations
        self.service_configs: Dict[str, HealthCheckConfig] = {}

        # Health metrics storage
        self.metrics: Dict[str, HealthMetrics] = {}

        # Service dependencies
        self.dependencies: Dict[str, List[ServiceDependency]] = {}

        # Alert handlers
        self.alert_handlers: List[Callable[[HealthAlert], None]] = []

        # Active alerts
        self.active_alerts: Dict[str, HealthAlert] = {}

        # HTTP client for health checks
        self.http_client = AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )

        # Background task control
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def set_service_config(self, service_name: str, config: HealthCheckConfig):
        """Set health check configuration for a specific service.

        Args:
            service_name: Service name
            config: Health check configuration
        """
        self.service_configs[service_name] = config

    def add_dependency(self, dependency: ServiceDependency):
        """Add service dependency relationship.

        Args:
            dependency: Service dependency
        """
        if dependency.service_name not in self.dependencies:
            self.dependencies[dependency.service_name] = []

        self.dependencies[dependency.service_name].append(dependency)

    def add_alert_handler(self, handler: Callable[[HealthAlert], None]):
        """Add alert handler callback.

        Args:
            handler: Alert handler function
        """
        self.alert_handlers.append(handler)

    async def start_monitoring(self):
        """Start health monitoring background tasks."""
        if self._running:
            return

        self._running = True

        # Start monitoring task
        self._tasks.append(asyncio.create_task(self._monitoring_loop()))

        # Start metrics collection task
        self._tasks.append(asyncio.create_task(self._metrics_collection_loop()))

        logger.info("Health monitoring started")

    async def stop_monitoring(self):
        """Stop health monitoring."""
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

        # Close HTTP client
        await self.http_client.aclose()

        logger.info("Health monitoring stopped")

    async def check_service_health(self, service: Service) -> Dict[str, ServiceHealth]:
        """Check health of all instances of a service.

        Args:
            service: Service to check

        Returns:
            Dictionary of instance_id -> ServiceHealth
        """
        if not service.instances:
            return {}

        # Get service-specific config or use default
        config = self.service_configs.get(service.name, self.default_config)

        # Check all instances concurrently
        tasks = []
        for instance in service.instances:
            task = asyncio.create_task(
                self._check_instance_health(instance, config, service.health_check_path)
            )
            tasks.append((instance.instance_id, task))

        # Wait for all checks to complete
        results = {}
        for instance_id, task in tasks:
            try:
                health = await task
                results[instance_id] = health
            except Exception as e:
                logger.error(
                    f"Health check failed for {service.name}/{instance_id}: {e}"
                )
                results[instance_id] = ServiceHealth(
                    status=ServiceStatus.UNHEALTHY,
                    last_check=datetime.utcnow(),
                    error_message=str(e),
                    consecutive_failures=1,
                )

        return results

    async def check_all_services(self):
        """Check health of all registered services."""
        services = await self.service_registry.get_all_services()

        for service_name, service in services.items():
            try:
                # Check service health
                health_results = await self.check_service_health(service)

                # Update service registry with health information
                for instance_id, health in health_results.items():
                    await self.service_registry.update_instance_health(
                        service_name, instance_id, health
                    )

                    # Update metrics
                    await self._update_metrics(service_name, health)

                    # Check for alerts
                    await self._check_alerts(service_name, instance_id, health)

            except Exception as e:
                logger.error(f"Error checking service {service_name}: {e}")

    async def get_service_metrics(self, service_name: str) -> Optional[HealthMetrics]:
        """Get health metrics for a service.

        Args:
            service_name: Service name

        Returns:
            Health metrics or None if not found
        """
        return self.metrics.get(service_name)

    async def get_all_metrics(self) -> Dict[str, HealthMetrics]:
        """Get health metrics for all services.

        Returns:
            Dictionary of service_name -> HealthMetrics
        """
        return self.metrics.copy()

    async def get_service_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary for all services.

        Returns:
            Health summary dictionary
        """
        services = await self.service_registry.get_all_services()

        summary = {
            "total_services": len(services),
            "healthy_services": 0,
            "unhealthy_services": 0,
            "unknown_services": 0,
            "total_instances": 0,
            "healthy_instances": 0,
            "unhealthy_instances": 0,
            "average_response_time_ms": 0.0,
            "overall_uptime_percentage": 0.0,
            "active_alerts": len(self.active_alerts),
        }

        total_response_time = 0.0
        total_uptime = 0.0
        services_with_metrics = 0

        for service_name, service in services.items():
            summary["total_instances"] += len(service.instances)

            # Count healthy/unhealthy instances
            for instance in service.instances:
                if instance.health.status == ServiceStatus.HEALTHY:
                    summary["healthy_instances"] += 1
                elif instance.health.status == ServiceStatus.UNHEALTHY:
                    summary["unhealthy_instances"] += 1

            # Determine service health (majority rule)
            healthy_instances = sum(
                1
                for inst in service.instances
                if inst.health.status == ServiceStatus.HEALTHY
            )

            if healthy_instances > len(service.instances) / 2:
                summary["healthy_services"] += 1
            elif healthy_instances == 0:
                summary["unhealthy_services"] += 1
            else:
                summary["unknown_services"] += 1

            # Include metrics if available
            metrics = self.metrics.get(service_name)
            if metrics:
                total_response_time += metrics.average_response_time_ms
                total_uptime += metrics.uptime_percentage
                services_with_metrics += 1

        # Calculate averages
        if services_with_metrics > 0:
            summary["average_response_time_ms"] = (
                total_response_time / services_with_metrics
            )
            summary["overall_uptime_percentage"] = total_uptime / services_with_metrics

        return summary

    async def _check_instance_health(
        self,
        instance: ServiceInstance,
        config: HealthCheckConfig,
        health_check_path: str,
    ) -> ServiceHealth:
        """Check health of a single service instance.

        Args:
            instance: Service instance
            config: Health check configuration
            health_check_path: Health check endpoint path

        Returns:
            Service health information
        """
        start_time = time.time()

        try:
            if config.type == HealthCheckType.HTTP:
                health = await self._http_health_check(
                    instance, config, health_check_path
                )
            elif config.type == HealthCheckType.TCP:
                health = await self._tcp_health_check(instance, config)
            elif config.type == HealthCheckType.CUSTOM:
                health = await self._custom_health_check(instance, config)
            else:
                raise ValueError(f"Unsupported health check type: {config.type}")

            # Calculate response time
            response_time = (time.time() - start_time) * 1000
            health.response_time_ms = response_time
            health.last_check = datetime.utcnow()

            return health

        except Exception as e:
            return ServiceHealth(
                status=ServiceStatus.UNHEALTHY,
                last_check=datetime.utcnow(),
                response_time_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
                consecutive_failures=1,
            )

    async def _http_health_check(
        self,
        instance: ServiceInstance,
        config: HealthCheckConfig,
        health_check_path: str,
    ) -> ServiceHealth:
        """Perform HTTP health check.

        Args:
            instance: Service instance
            config: Health check configuration
            health_check_path: Health check endpoint path

        Returns:
            Service health information
        """
        url = f"{instance.url.rstrip('/')}/{health_check_path.lstrip('/')}"
        headers = config.custom_headers.copy()

        for attempt in range(config.retries):
            try:
                response = await self.http_client.request(
                    config.method, url, headers=headers, timeout=config.timeout_seconds
                )

                # Check status code
                if response.status_code not in config.expected_status_codes:
                    if attempt < config.retries - 1:
                        await asyncio.sleep(config.retry_delay_seconds)
                        continue
                    else:
                        return ServiceHealth(
                            status=ServiceStatus.UNHEALTHY,
                            last_check=datetime.utcnow(),
                            error_message=f"Unexpected status code: {response.status_code}",
                            consecutive_failures=1,
                        )

                # Check response content if specified
                if config.expected_response_contains:
                    response_text = response.text
                    if config.expected_response_contains not in response_text:
                        if attempt < config.retries - 1:
                            await asyncio.sleep(config.retry_delay_seconds)
                            continue
                        else:
                            return ServiceHealth(
                                status=ServiceStatus.UNHEALTHY,
                                last_check=datetime.utcnow(),
                                error_message="Response content check failed",
                                consecutive_failures=1,
                            )

                # Health check passed
                return ServiceHealth(
                    status=ServiceStatus.HEALTHY,
                    last_check=datetime.utcnow(),
                    consecutive_successes=1,
                )

            except (ConnectTimeout, ReadTimeout) as e:
                if attempt < config.retries - 1:
                    await asyncio.sleep(config.retry_delay_seconds)
                    continue
                else:
                    return ServiceHealth(
                        status=ServiceStatus.UNHEALTHY,
                        last_check=datetime.utcnow(),
                        error_message=f"Timeout: {str(e)}",
                        consecutive_failures=1,
                    )

            except Exception as e:
                if attempt < config.retries - 1:
                    await asyncio.sleep(config.retry_delay_seconds)
                    continue
                else:
                    return ServiceHealth(
                        status=ServiceStatus.UNHEALTHY,
                        last_check=datetime.utcnow(),
                        error_message=str(e),
                        consecutive_failures=1,
                    )

        # Should not reach here
        return ServiceHealth(
            status=ServiceStatus.UNHEALTHY,
            last_check=datetime.utcnow(),
            error_message="All retries failed",
            consecutive_failures=1,
        )

    async def _tcp_health_check(
        self, instance: ServiceInstance, config: HealthCheckConfig
    ) -> ServiceHealth:
        """Perform TCP health check.

        Args:
            instance: Service instance
            config: Health check configuration

        Returns:
            Service health information
        """
        # Extract host and port from URL
        from urllib.parse import urlparse

        parsed = urlparse(instance.url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        try:
            # Attempt TCP connection
            future = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(
                future, timeout=config.timeout_seconds
            )

            # Close connection
            writer.close()
            await writer.wait_closed()

            return ServiceHealth(
                status=ServiceStatus.HEALTHY,
                last_check=datetime.utcnow(),
                consecutive_successes=1,
            )

        except Exception as e:
            return ServiceHealth(
                status=ServiceStatus.UNHEALTHY,
                last_check=datetime.utcnow(),
                error_message=str(e),
                consecutive_failures=1,
            )

    async def _custom_health_check(
        self, instance: ServiceInstance, config: HealthCheckConfig
    ) -> ServiceHealth:
        """Perform custom health check.

        Args:
            instance: Service instance
            config: Health check configuration

        Returns:
            Service health information
        """
        # Placeholder for custom health check logic
        # This would be implemented based on specific requirements
        return ServiceHealth(
            status=ServiceStatus.UNKNOWN,
            last_check=datetime.utcnow(),
            error_message="Custom health check not implemented",
        )

    async def _update_metrics(self, service_name: str, health: ServiceHealth):
        """Update health metrics for a service.

        Args:
            service_name: Service name
            health: Health information
        """
        if service_name not in self.metrics:
            self.metrics[service_name] = HealthMetrics(service_name=service_name)

        metrics = self.metrics[service_name]
        metrics.total_checks += 1
        metrics.last_check_time = health.last_check

        if health.status == ServiceStatus.HEALTHY:
            metrics.successful_checks += 1
            metrics.consecutive_successes += 1
            metrics.consecutive_failures = 0
        else:
            metrics.failed_checks += 1
            metrics.consecutive_failures += 1
            metrics.consecutive_successes = 0

        # Update average response time
        if health.response_time_ms is not None:
            total_response_time = (
                metrics.average_response_time_ms * (metrics.total_checks - 1)
                + health.response_time_ms
            )
            metrics.average_response_time_ms = (
                total_response_time / metrics.total_checks
            )

        # Update uptime percentage
        metrics.uptime_percentage = (
            metrics.successful_checks / metrics.total_checks * 100
            if metrics.total_checks > 0
            else 100.0
        )

    async def _check_alerts(
        self, service_name: str, instance_id: str, health: ServiceHealth
    ):
        """Check if alerts should be generated based on health status.

        Args:
            service_name: Service name
            instance_id: Instance ID
            health: Health information
        """
        alert_key = f"{service_name}:{instance_id}"

        # Check for new unhealthy status
        if (
            health.status == ServiceStatus.UNHEALTHY
            and health.consecutive_failures >= 3
        ):
            if alert_key not in self.active_alerts:
                alert = HealthAlert(
                    alert_id=f"health_{service_name}_{instance_id}_{int(time.time())}",
                    service_name=service_name,
                    instance_id=instance_id,
                    severity=AlertSeverity.ERROR,
                    message=f"Service {service_name} instance {instance_id} is unhealthy: {health.error_message}",
                    timestamp=datetime.utcnow(),
                    metadata={
                        "consecutive_failures": health.consecutive_failures,
                        "response_time_ms": health.response_time_ms,
                    },
                )

                self.active_alerts[alert_key] = alert
                await self._emit_alert(alert)

        # Check for recovery
        elif (
            health.status == ServiceStatus.HEALTHY and health.consecutive_successes >= 2
        ):
            if alert_key in self.active_alerts:
                alert = self.active_alerts[alert_key]
                alert.resolved = True
                alert.resolved_at = datetime.utcnow()

                recovery_alert = HealthAlert(
                    alert_id=f"recovery_{service_name}_{instance_id}_{int(time.time())}",
                    service_name=service_name,
                    instance_id=instance_id,
                    severity=AlertSeverity.INFO,
                    message=f"Service {service_name} instance {instance_id} has recovered",
                    timestamp=datetime.utcnow(),
                    metadata={
                        "consecutive_successes": health.consecutive_successes,
                        "downtime_duration": str(datetime.utcnow() - alert.timestamp),
                    },
                )

                del self.active_alerts[alert_key]
                await self._emit_alert(recovery_alert)

    async def _emit_alert(self, alert: HealthAlert):
        """Emit alert to all registered handlers.

        Args:
            alert: Alert to emit
        """
        logger.info(f"Health alert: {alert.message}")

        for handler in self.alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Error in alert handler: {e}")

    async def _monitoring_loop(self):
        """Background monitoring loop."""
        while self._running:
            try:
                await self.check_all_services()
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    async def _metrics_collection_loop(self):
        """Background metrics collection loop."""
        while self._running:
            try:
                # Clean up old metrics data
                # This could be extended to persist metrics to a time-series database
                await asyncio.sleep(300)  # Collect every 5 minutes
            except Exception as e:
                logger.error(f"Error in metrics collection loop: {e}")
                await asyncio.sleep(300)


# Export components
__all__ = [
    "HealthMonitor",
    "HealthCheckConfig",
    "HealthCheckType",
    "ServiceDependency",
    "HealthAlert",
    "HealthMetrics",
    "AlertSeverity",
]
