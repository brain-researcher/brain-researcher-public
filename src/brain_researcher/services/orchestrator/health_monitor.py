"""
Real-time service health monitoring with automatic failover logic,
service status caching, and alert mechanisms.
"""

import asyncio
import json
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

import aiohttp
import psutil
from pydantic import BaseModel, Field

from .error_handler import ServiceType, error_registry
from .models import HealthResponse, ServiceHealth

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ServiceEndpoint:
    """Service endpoint configuration."""

    name: str
    url: str
    service_type: ServiceType
    health_check_path: str = "/health"
    timeout_seconds: int = 10
    expected_status_code: int = 200
    expected_response_keys: Optional[List[str]] = None
    custom_validator: Optional[Callable] = None
    priority: int = 1  # 1=critical, 2=important, 3=optional
    dependencies: List[str] = None  # Services this depends on

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.expected_response_keys is None:
            self.expected_response_keys = []


@dataclass
class HealthCheck:
    """Individual health check result."""

    service_name: str
    status: HealthStatus
    response_time_ms: float
    timestamp: datetime
    details: Dict[str, Any]
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class Alert:
    """Health monitoring alert."""

    id: str
    service_name: str
    severity: AlertSeverity
    title: str
    message: str
    timestamp: datetime
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class HealthMetrics(BaseModel):
    """Aggregated health metrics."""

    total_services: int = 0
    healthy_services: int = 0
    degraded_services: int = 0
    unhealthy_services: int = 0
    unavailable_services: int = 0
    overall_health_percentage: float = 0.0
    avg_response_time_ms: float = 0.0
    uptime_percentage_24h: float = 0.0
    last_incident_time: Optional[datetime] = None
    alerts_count: int = 0
    critical_alerts_count: int = 0


class ServiceHealthMonitor:
    """Main service health monitoring system."""

    def __init__(
        self,
        check_interval_seconds: int = 30,
        alert_cooldown_seconds: int = 300,
        health_history_hours: int = 24,
        max_concurrent_checks: int = 10,
    ):
        self.check_interval_seconds = check_interval_seconds
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self.health_history_hours = health_history_hours
        self.max_concurrent_checks = max_concurrent_checks

        self.endpoints: Dict[str, ServiceEndpoint] = {}
        self.health_cache: Dict[str, HealthCheck] = {}
        self.health_history: Dict[str, List[HealthCheck]] = {}
        self.alerts: Dict[str, Alert] = {}
        self.alert_handlers: List[Callable] = []

        self.monitoring_active = False
        self.monitoring_task: Optional[asyncio.Task] = None
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent_checks)

        # System resource monitoring
        self.system_metrics: Dict[str, Any] = {}
        self.resource_thresholds = {
            "cpu_percent": 80,
            "memory_percent": 85,
            "disk_percent": 90,
        }

        logger.info("Health monitor initialized")

    def register_service(self, endpoint: ServiceEndpoint):
        """Register a service endpoint for monitoring."""
        self.endpoints[endpoint.name] = endpoint
        self.health_history[endpoint.name] = []

        logger.info(f"Registered service for monitoring: {endpoint.name}")

    def register_services(self, endpoints: List[ServiceEndpoint]):
        """Register multiple service endpoints."""
        for endpoint in endpoints:
            self.register_service(endpoint)

    def add_alert_handler(self, handler: Callable[[Alert], None]):
        """Add alert handler callback."""
        self.alert_handlers.append(handler)

    async def start_monitoring(self):
        """Start continuous health monitoring."""
        if self.monitoring_active:
            logger.warning("Health monitoring already active")
            return

        self.monitoring_active = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())

        logger.info("Health monitoring started")

    async def stop_monitoring(self):
        """Stop health monitoring."""
        self.monitoring_active = False

        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("Health monitoring stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring_active:
            try:
                start_time = time.time()

                # Run health checks
                await self._run_all_health_checks()

                # Update system metrics
                self._update_system_metrics()

                # Process alerts
                await self._process_health_alerts()

                # Clean up old data
                self._cleanup_old_data()

                # Calculate next check interval
                elapsed = time.time() - start_time
                sleep_time = max(0, self.check_interval_seconds - elapsed)

                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                await asyncio.sleep(self.check_interval_seconds)

    async def _run_all_health_checks(self):
        """Run health checks for all registered services."""
        if not self.endpoints:
            return

        # Create semaphore to limit concurrent checks
        semaphore = asyncio.Semaphore(self.max_concurrent_checks)

        # Run all checks concurrently
        tasks = [
            self._run_health_check_with_semaphore(endpoint, semaphore)
            for endpoint in self.endpoints.values()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(results):
            endpoint = list(self.endpoints.values())[i]

            if isinstance(result, Exception):
                logger.error(f"Health check failed for {endpoint.name}: {str(result)}")
                result = HealthCheck(
                    service_name=endpoint.name,
                    status=HealthStatus.UNAVAILABLE,
                    response_time_ms=float("inf"),
                    timestamp=datetime.utcnow(),
                    details={"error": str(result)},
                    error_message=str(result),
                )

            # Update cache and history
            self.health_cache[endpoint.name] = result
            self.health_history[endpoint.name].append(result)

    async def _run_health_check_with_semaphore(
        self, endpoint: ServiceEndpoint, semaphore: asyncio.Semaphore
    ) -> HealthCheck:
        """Run health check with concurrency control."""
        async with semaphore:
            return await self._run_health_check(endpoint)

    async def _run_health_check(self, endpoint: ServiceEndpoint) -> HealthCheck:
        """Run health check for a single service."""
        start_time = time.time()

        try:
            health_url = f"{endpoint.url.rstrip('/')}{endpoint.health_check_path}"

            timeout = aiohttp.ClientTimeout(total=endpoint.timeout_seconds)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(health_url) as response:
                    response_time_ms = (time.time() - start_time) * 1000
                    response_data = await response.json()

                    # Validate response
                    status = self._validate_health_response(
                        endpoint, response, response_data, response_time_ms
                    )

                    return HealthCheck(
                        service_name=endpoint.name,
                        status=status,
                        response_time_ms=response_time_ms,
                        timestamp=datetime.utcnow(),
                        details=response_data,
                        metadata={"status_code": response.status, "url": health_url},
                    )

        except asyncio.TimeoutError:
            response_time_ms = endpoint.timeout_seconds * 1000
            return HealthCheck(
                service_name=endpoint.name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=response_time_ms,
                timestamp=datetime.utcnow(),
                details={"error": "timeout"},
                error_message=f"Health check timeout after {endpoint.timeout_seconds}s",
            )

        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            return HealthCheck(
                service_name=endpoint.name,
                status=HealthStatus.UNAVAILABLE,
                response_time_ms=response_time_ms,
                timestamp=datetime.utcnow(),
                details={"error": str(e)},
                error_message=str(e),
            )

    def _validate_health_response(
        self,
        endpoint: ServiceEndpoint,
        response: aiohttp.ClientResponse,
        response_data: Dict[str, Any],
        response_time_ms: float,
    ) -> HealthStatus:
        """Validate health check response and determine status."""

        # Check status code
        if response.status != endpoint.expected_status_code:
            return HealthStatus.UNHEALTHY

        # Check expected response keys
        for key in endpoint.expected_response_keys:
            if key not in response_data:
                return HealthStatus.DEGRADED

        # Check response time
        if response_time_ms > 5000:  # 5 second threshold
            return HealthStatus.DEGRADED

        # Custom validation
        if endpoint.custom_validator:
            try:
                if not endpoint.custom_validator(response_data):
                    return HealthStatus.DEGRADED
            except Exception as e:
                logger.warning(f"Custom validator failed for {endpoint.name}: {str(e)}")
                return HealthStatus.DEGRADED

        # Check service-specific health indicators
        if "status" in response_data:
            reported_status = response_data["status"].lower()
            if reported_status in ["unhealthy", "error", "failed"]:
                return HealthStatus.UNHEALTHY
            elif reported_status in ["degraded", "warning", "limited"]:
                return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    def _update_system_metrics(self):
        """Update system resource metrics."""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            self.system_metrics = {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "disk_percent": disk.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_free_gb": disk.free / (1024**3),
                "load_average": (
                    psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else 0
                ),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to update system metrics: {str(e)}")

    async def _process_health_alerts(self):
        """Process health status changes and generate alerts."""
        current_time = datetime.utcnow()

        for service_name, current_check in self.health_cache.items():
            endpoint = self.endpoints[service_name]

            # Get previous status
            history = self.health_history.get(service_name, [])
            previous_status = (
                history[-2].status if len(history) >= 2 else HealthStatus.HEALTHY
            )

            # Check for status changes
            if current_check.status != previous_status:
                await self._generate_status_change_alert(
                    endpoint, previous_status, current_check, current_time
                )

            # Check for performance alerts
            if current_check.status == HealthStatus.HEALTHY:
                await self._check_performance_alerts(
                    endpoint, current_check, current_time
                )

            # Check system resource alerts
            await self._check_system_resource_alerts(current_time)

    async def _generate_status_change_alert(
        self,
        endpoint: ServiceEndpoint,
        previous_status: HealthStatus,
        current_check: HealthCheck,
        current_time: datetime,
    ):
        """Generate alert for service status change."""

        # Determine alert severity
        severity_map = {
            (HealthStatus.HEALTHY, HealthStatus.DEGRADED): AlertSeverity.WARNING,
            (HealthStatus.HEALTHY, HealthStatus.UNHEALTHY): AlertSeverity.ERROR,
            (HealthStatus.HEALTHY, HealthStatus.UNAVAILABLE): AlertSeverity.CRITICAL,
            (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY): AlertSeverity.ERROR,
            (HealthStatus.DEGRADED, HealthStatus.UNAVAILABLE): AlertSeverity.CRITICAL,
            (HealthStatus.UNHEALTHY, HealthStatus.UNAVAILABLE): AlertSeverity.CRITICAL,
        }

        # Recovery alerts (lower severity)
        recovery_map = {
            (HealthStatus.UNAVAILABLE, HealthStatus.HEALTHY): AlertSeverity.INFO,
            (HealthStatus.UNHEALTHY, HealthStatus.HEALTHY): AlertSeverity.INFO,
            (HealthStatus.DEGRADED, HealthStatus.HEALTHY): AlertSeverity.INFO,
            (HealthStatus.UNAVAILABLE, HealthStatus.DEGRADED): AlertSeverity.WARNING,
            (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED): AlertSeverity.WARNING,
        }

        transition = (previous_status, current_check.status)
        severity = severity_map.get(transition) or recovery_map.get(transition)

        if not severity:
            return  # No alert needed

        alert_id = f"{endpoint.name}_{current_time.timestamp()}"

        # Create alert message
        if current_check.status in [HealthStatus.UNHEALTHY, HealthStatus.UNAVAILABLE]:
            title = f"Service {endpoint.name} is {current_check.status.value}"
            message = f"Service status changed from {previous_status.value} to {current_check.status.value}"
            if current_check.error_message:
                message += f". Error: {current_check.error_message}"
        else:
            title = f"Service {endpoint.name} recovered"
            message = f"Service status improved from {previous_status.value} to {current_check.status.value}"

        alert = Alert(
            id=alert_id,
            service_name=endpoint.name,
            severity=severity,
            title=title,
            message=message,
            timestamp=current_time,
            metadata={
                "previous_status": previous_status.value,
                "current_status": current_check.status.value,
                "response_time_ms": current_check.response_time_ms,
                "endpoint_priority": endpoint.priority,
                "service_type": endpoint.service_type.value,
            },
        )

        await self._emit_alert(alert)

    async def _check_performance_alerts(
        self,
        endpoint: ServiceEndpoint,
        current_check: HealthCheck,
        current_time: datetime,
    ):
        """Check for performance-related alerts."""

        # High response time alert
        if current_check.response_time_ms > 10000:  # 10 seconds
            alert_id = f"{endpoint.name}_slow_response_{current_time.timestamp()}"

            # Check if we already alerted recently
            recent_alerts = [
                alert
                for alert in self.alerts.values()
                if (
                    alert.service_name == endpoint.name
                    and "slow_response" in alert.id
                    and not alert.resolved
                    and (current_time - alert.timestamp).total_seconds()
                    < self.alert_cooldown_seconds
                )
            ]

            if not recent_alerts:
                alert = Alert(
                    id=alert_id,
                    service_name=endpoint.name,
                    severity=AlertSeverity.WARNING,
                    title=f"Slow response from {endpoint.name}",
                    message=f"Response time is {current_check.response_time_ms:.0f}ms (threshold: 10000ms)",
                    timestamp=current_time,
                    metadata={
                        "response_time_ms": current_check.response_time_ms,
                        "threshold_ms": 10000,
                    },
                )

                await self._emit_alert(alert)

    async def _check_system_resource_alerts(self, current_time: datetime):
        """Check for system resource alerts."""

        for resource, threshold in self.resource_thresholds.items():
            current_value = self.system_metrics.get(resource, 0)

            if current_value > threshold:
                alert_id = f"system_{resource}_{current_time.timestamp()}"

                # Check cooldown
                recent_alerts = [
                    alert
                    for alert in self.alerts.values()
                    if (
                        alert.service_name == "system"
                        and resource in alert.id
                        and not alert.resolved
                        and (current_time - alert.timestamp).total_seconds()
                        < self.alert_cooldown_seconds
                    )
                ]

                if not recent_alerts:
                    severity = (
                        AlertSeverity.CRITICAL
                        if current_value > threshold * 1.1
                        else AlertSeverity.ERROR
                    )

                    alert = Alert(
                        id=alert_id,
                        service_name="system",
                        severity=severity,
                        title=f"High {resource.replace('_', ' ')}",
                        message=f"System {resource.replace('_', ' ')} is {current_value:.1f}% (threshold: {threshold}%)",
                        timestamp=current_time,
                        metadata={
                            "resource": resource,
                            "current_value": current_value,
                            "threshold": threshold,
                        },
                    )

                    await self._emit_alert(alert)

    async def _emit_alert(self, alert: Alert):
        """Emit alert to all registered handlers."""
        self.alerts[alert.id] = alert

        logger.warning(f"Health alert: {alert.title} - {alert.message}")

        # Call alert handlers
        for handler in self.alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {str(e)}")

    def _cleanup_old_data(self):
        """Clean up old health check data and resolved alerts."""
        cutoff_time = datetime.utcnow() - timedelta(hours=self.health_history_hours)

        # Clean up health history
        for service_name in self.health_history:
            self.health_history[service_name] = [
                check
                for check in self.health_history[service_name]
                if check.timestamp > cutoff_time
            ]

        # Clean up resolved alerts older than 24 hours
        alert_cutoff = datetime.utcnow() - timedelta(hours=24)
        expired_alerts = [
            alert_id
            for alert_id, alert in self.alerts.items()
            if alert.resolved and alert.resolved_at and alert.resolved_at < alert_cutoff
        ]

        for alert_id in expired_alerts:
            del self.alerts[alert_id]

    async def get_service_health(self, service_name: str) -> Optional[HealthCheck]:
        """Get current health status for specific service."""
        return self.health_cache.get(service_name)

    async def get_all_service_health(self) -> Dict[str, HealthCheck]:
        """Get current health status for all services."""
        return self.health_cache.copy()

    async def get_health_summary(self) -> HealthResponse:
        """Get overall system health summary."""
        if not self.health_cache:
            return HealthResponse(
                status=HealthStatus.HEALTHY.value,
                services={},
                timestamp=datetime.utcnow(),
            )

        # Convert to ServiceHealth format
        services = {}
        status_counts = {status: 0 for status in HealthStatus}

        for service_name, check in self.health_cache.items():
            status_counts[check.status] += 1

            services[service_name] = ServiceHealth(
                name=service_name,
                status=check.status.value,
                latency_ms=(
                    int(check.response_time_ms)
                    if check.response_time_ms != float("inf")
                    else None
                ),
                last_check=check.timestamp,
                error=check.error_message,
            )

        # Determine overall status
        total_services = len(self.health_cache)
        if status_counts[HealthStatus.UNAVAILABLE] > total_services * 0.5:
            overall_status = HealthStatus.UNHEALTHY.value
        elif (
            status_counts[HealthStatus.UNHEALTHY] > 0
            or status_counts[HealthStatus.UNAVAILABLE] > 0
        ):
            overall_status = HealthStatus.DEGRADED.value
        elif status_counts[HealthStatus.DEGRADED] > total_services * 0.3:
            overall_status = HealthStatus.DEGRADED.value
        else:
            overall_status = HealthStatus.HEALTHY.value

        return HealthResponse(
            status=overall_status,
            services=services,
            timestamp=datetime.utcnow(),
            uptime_seconds=self._calculate_uptime_seconds(),
        )

    def _calculate_uptime_seconds(self) -> int:
        """Calculate system uptime in seconds."""
        try:
            return int(time.time() - psutil.boot_time())
        except:
            return 0

    async def get_health_metrics(self) -> HealthMetrics:
        """Get aggregated health metrics."""
        if not self.health_cache:
            return HealthMetrics()

        total_services = len(self.health_cache)
        status_counts = {status: 0 for status in HealthStatus}
        total_response_time = 0
        valid_response_times = 0

        for check in self.health_cache.values():
            status_counts[check.status] += 1

            if check.response_time_ms != float("inf"):
                total_response_time += check.response_time_ms
                valid_response_times += 1

        avg_response_time = (
            total_response_time / valid_response_times
            if valid_response_times > 0
            else 0
        )

        health_percentage = (
            status_counts[HealthStatus.HEALTHY] * 100
            + status_counts[HealthStatus.DEGRADED] * 50
        ) / total_services

        # Calculate 24h uptime
        uptime_24h = self._calculate_uptime_percentage_24h()

        # Get alert counts
        active_alerts = [alert for alert in self.alerts.values() if not alert.resolved]
        critical_alerts = [
            alert for alert in active_alerts if alert.severity == AlertSeverity.CRITICAL
        ]

        return HealthMetrics(
            total_services=total_services,
            healthy_services=status_counts[HealthStatus.HEALTHY],
            degraded_services=status_counts[HealthStatus.DEGRADED],
            unhealthy_services=status_counts[HealthStatus.UNHEALTHY],
            unavailable_services=status_counts[HealthStatus.UNAVAILABLE],
            overall_health_percentage=health_percentage,
            avg_response_time_ms=avg_response_time,
            uptime_percentage_24h=uptime_24h,
            alerts_count=len(active_alerts),
            critical_alerts_count=len(critical_alerts),
        )

    def _calculate_uptime_percentage_24h(self) -> float:
        """Calculate uptime percentage for last 24 hours."""
        cutoff = datetime.utcnow() - timedelta(hours=24)

        total_checks = 0
        successful_checks = 0

        for service_history in self.health_history.values():
            for check in service_history:
                if check.timestamp > cutoff:
                    total_checks += 1
                    if check.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]:
                        successful_checks += 1

        if total_checks == 0:
            return 100.0

        return (successful_checks / total_checks) * 100

    async def resolve_alert(self, alert_id: str):
        """Mark alert as resolved."""
        if alert_id in self.alerts:
            self.alerts[alert_id].resolved = True
            self.alerts[alert_id].resolved_at = datetime.utcnow()
            logger.info(f"Alert resolved: {alert_id}")

    async def force_health_check(
        self, service_name: Optional[str] = None
    ) -> Dict[str, HealthCheck]:
        """Force immediate health check for service(s)."""
        if service_name:
            if service_name in self.endpoints:
                endpoint = self.endpoints[service_name]
                result = await self._run_health_check(endpoint)
                self.health_cache[service_name] = result
                self.health_history[service_name].append(result)
                return {service_name: result}
            else:
                raise ValueError(f"Service {service_name} not registered")
        else:
            await self._run_all_health_checks()
            return self.health_cache.copy()


# Global health monitor instance
health_monitor = ServiceHealthMonitor()


# Default service configurations
def get_default_service_endpoints() -> List[ServiceEndpoint]:
    """Get default service endpoint configurations."""
    return [
        ServiceEndpoint(
            name="agent",
            url="http://localhost:8000",
            service_type=ServiceType.AGENT,
            priority=1,
            expected_response_keys=["status", "uptime"],
        ),
        ServiceEndpoint(
            name="br_kg",
            url="http://localhost:5000",
            service_type=ServiceType.BR_KG,
            priority=1,
            expected_response_keys=["status", "database"],
        ),
        ServiceEndpoint(
            name="web_ui",
            url="http://localhost:3000",
            service_type=ServiceType.EXTERNAL_API,
            priority=2,
            health_check_path="/api/health",
        ),
    ]


# Alert handlers
async def log_alert_handler(alert: Alert):
    """Default alert handler that logs alerts."""
    level_map = {
        AlertSeverity.INFO: logging.INFO,
        AlertSeverity.WARNING: logging.WARNING,
        AlertSeverity.ERROR: logging.ERROR,
        AlertSeverity.CRITICAL: logging.CRITICAL,
    }

    level = level_map.get(alert.severity, logging.WARNING)
    logger.log(level, f"[{alert.severity.upper()}] {alert.title}: {alert.message}")


def console_alert_handler(alert: Alert):
    """Alert handler that prints to console."""
    timestamp = alert.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {alert.severity.upper()}: {alert.title}")
    print(f"  Service: {alert.service_name}")
    print(f"  Message: {alert.message}")
    if alert.metadata:
        print(f"  Metadata: {alert.metadata}")
    print("-" * 50)


# Convenience functions
async def initialize_health_monitoring(
    endpoints: Optional[List[ServiceEndpoint]] = None,
    custom_alert_handlers: Optional[List[Callable]] = None,
):
    """Initialize and start health monitoring."""

    # Register default endpoints if none provided
    if not endpoints:
        endpoints = get_default_service_endpoints()

    health_monitor.register_services(endpoints)

    # Add default alert handlers
    health_monitor.add_alert_handler(log_alert_handler)

    # Add custom alert handlers
    if custom_alert_handlers:
        for handler in custom_alert_handlers:
            health_monitor.add_alert_handler(handler)

    # Start monitoring
    await health_monitor.start_monitoring()

    logger.info("Health monitoring initialized and started")


async def get_system_health_status() -> Dict[str, Any]:
    """Get comprehensive system health status."""
    health_summary = await health_monitor.get_health_summary()
    health_metrics = await health_monitor.get_health_metrics()

    return {
        "summary": health_summary.model_dump(),
        "metrics": health_metrics.model_dump(),
        "system_resources": health_monitor.system_metrics,
        "active_alerts": [
            asdict(alert)
            for alert in health_monitor.alerts.values()
            if not alert.resolved
        ],
    }
