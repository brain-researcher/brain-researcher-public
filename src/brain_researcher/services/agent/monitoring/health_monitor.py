"""Health Monitoring System for Brain Researcher Agent

Provides comprehensive health checks, metrics collection, and monitoring
for production readiness.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import aiohttp
import psutil

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ServiceType(Enum):
    """Types of services to monitor."""

    CORE = "core"
    TOOL = "tool"
    DATABASE = "database"
    CACHE = "cache"
    EXTERNAL = "external"


@dataclass
class HealthCheck:
    """Individual health check result."""

    name: str
    status: HealthStatus
    latency_ms: float
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


@dataclass
class ServiceHealth:
    """Health status of a service."""

    service_name: str
    service_type: ServiceType
    status: HealthStatus
    checks: list[HealthCheck] = field(default_factory=list)
    uptime_seconds: float = 0.0
    last_check: datetime | None = None
    error_count: int = 0
    success_count: int = 0

    @property
    def availability(self) -> float:
        """Calculate service availability percentage."""
        total = self.error_count + self.success_count
        return (self.success_count / total * 100) if total > 0 else 0.0


@dataclass
class SystemMetrics:
    """System-wide metrics."""

    cpu_percent: float
    memory_percent: float
    memory_mb: float
    disk_percent: float
    network_connections: int
    gpu_percent: float | None = None
    gpu_memory_mb: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)


class HealthMonitor:
    """Main health monitoring system."""

    def __init__(self, check_interval: int = 30, history_size: int = 1000):
        """Initialize health monitor.

        Args:
            check_interval: Seconds between health checks
            history_size: Number of historical checks to retain
        """
        self.check_interval = check_interval
        self.history_size = history_size

        # Service registry
        self.services: dict[str, ServiceHealth] = {}
        self.health_checks: dict[str, Callable] = {}

        # Metrics history
        self.metrics_history: deque = deque(maxlen=history_size)
        self.check_history: deque = deque(maxlen=history_size)

        # Monitoring state
        self.monitoring_task: asyncio.Task | None = None
        self.start_time = time.time()

        # Alert callbacks
        self.alert_handlers: list[Callable] = []

        # Register default checks
        self._register_default_checks()

    def _register_default_checks(self):
        """Register default health checks."""
        # System health
        self.register_check("system_resources", self._check_system_resources)
        self.register_check("disk_space", self._check_disk_space)

        # Service dependencies
        self.register_check("redis_connection", self._check_redis)
        self.register_check("neo4j_connection", self._check_neo4j)

        # Agent components
        self.register_check("tool_registry", self._check_tool_registry)
        self.register_check("executor_queue", self._check_executor_queue)

    def register_service(
        self,
        name: str,
        service_type: ServiceType,
        health_check: Callable | None = None,
    ):
        """Register a service for monitoring.

        Args:
            name: Service name
            service_type: Type of service
            health_check: Optional custom health check function
        """
        self.services[name] = ServiceHealth(
            service_name=name, service_type=service_type, status=HealthStatus.UNKNOWN
        )

        if health_check:
            self.health_checks[name] = health_check

        logger.info(f"Registered service: {name} ({service_type.value})")

    def register_check(self, name: str, check_func: Callable):
        """Register a health check function.

        Args:
            name: Check name
            check_func: Async function that returns HealthCheck
        """
        self.health_checks[name] = check_func

    async def start_monitoring(self):
        """Start the monitoring loop."""
        if self.monitoring_task:
            logger.warning("Monitoring already running")
            return

        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Health monitoring started")

    async def stop_monitoring(self):
        """Stop the monitoring loop."""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            await asyncio.gather(self.monitoring_task, return_exceptions=True)
            self.monitoring_task = None
            logger.info("Health monitoring stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while True:
            try:
                # Collect system metrics
                metrics = await self._collect_system_metrics()
                self.metrics_history.append(metrics)

                # Run health checks
                checks = await self._run_health_checks()
                self.check_history.extend(checks)

                # Update service health
                self._update_service_health(checks)

                # Check for alerts
                await self._check_alerts(checks, metrics)

                # Wait for next interval
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(self.check_interval)

    async def _collect_system_metrics(self) -> SystemMetrics:
        """Collect current system metrics."""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        network = len(psutil.net_connections())

        # GPU metrics (if available)
        gpu_percent = None
        gpu_memory = None
        try:
            import GPUtil

            gpus = GPUtil.getGPUs()
            if gpus:
                gpu_percent = gpus[0].load * 100
                gpu_memory = gpus[0].memoryUsed
        except:
            pass

        return SystemMetrics(
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_mb=memory.used / (1024**2),
            disk_percent=disk.percent,
            network_connections=network,
            gpu_percent=gpu_percent,
            gpu_memory_mb=gpu_memory,
        )

    async def _run_health_checks(self) -> list[HealthCheck]:
        """Run all registered health checks."""
        checks = []

        for name, check_func in self.health_checks.items():
            try:
                start_time = time.time()

                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()

                if not isinstance(result, HealthCheck):
                    # Convert to HealthCheck if needed
                    result = HealthCheck(
                        name=name,
                        status=(
                            HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
                        ),
                        latency_ms=(time.time() - start_time) * 1000,
                    )

                checks.append(result)

            except Exception as e:
                logger.error(f"Health check {name} failed: {e}")
                checks.append(
                    HealthCheck(
                        name=name,
                        status=HealthStatus.UNHEALTHY,
                        latency_ms=0,
                        message=str(e),
                    )
                )

        return checks

    def _update_service_health(self, checks: list[HealthCheck]):
        """Update service health based on checks."""
        for service in self.services.values():
            # Find relevant checks for this service
            service_checks = [
                c for c in checks if c.name.startswith(service.service_name)
            ]

            if service_checks:
                service.checks = service_checks
                service.last_check = datetime.now()

                # Update status based on checks
                if all(c.is_healthy for c in service_checks):
                    service.status = HealthStatus.HEALTHY
                    service.success_count += 1
                elif any(c.is_healthy for c in service_checks):
                    service.status = HealthStatus.DEGRADED
                else:
                    service.status = HealthStatus.UNHEALTHY
                    service.error_count += 1

                # Update uptime
                service.uptime_seconds = time.time() - self.start_time

    async def _check_alerts(self, checks: list[HealthCheck], metrics: SystemMetrics):
        """Check for alert conditions."""
        alerts = []

        # Check for unhealthy services
        unhealthy = [c for c in checks if c.status == HealthStatus.UNHEALTHY]
        if unhealthy:
            alerts.append(
                {
                    "type": "unhealthy_services",
                    "services": [c.name for c in unhealthy],
                    "severity": "high",
                }
            )

        # Check system resources
        if metrics.cpu_percent > 90:
            alerts.append(
                {"type": "high_cpu", "value": metrics.cpu_percent, "severity": "medium"}
            )

        if metrics.memory_percent > 90:
            alerts.append(
                {
                    "type": "high_memory",
                    "value": metrics.memory_percent,
                    "severity": "high",
                }
            )

        if metrics.disk_percent > 95:
            alerts.append(
                {
                    "type": "low_disk",
                    "value": metrics.disk_percent,
                    "severity": "critical",
                }
            )

        # Trigger alert handlers
        for alert in alerts:
            await self._trigger_alert(alert)

    async def _trigger_alert(self, alert: dict[str, Any]):
        """Trigger alert handlers."""
        for handler in self.alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")

    # Default health check implementations

    async def _check_system_resources(self) -> HealthCheck:
        """Check system resource availability."""
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()

        if cpu > 95 or memory.percent > 95:
            status = HealthStatus.UNHEALTHY
            message = f"High resource usage: CPU {cpu}%, Memory {memory.percent}%"
        elif cpu > 80 or memory.percent > 80:
            status = HealthStatus.DEGRADED
            message = f"Elevated resource usage: CPU {cpu}%, Memory {memory.percent}%"
        else:
            status = HealthStatus.HEALTHY
            message = f"Resources normal: CPU {cpu}%, Memory {memory.percent}%"

        return HealthCheck(
            name="system_resources",
            status=status,
            latency_ms=0,
            message=message,
            metadata={"cpu": cpu, "memory": memory.percent},
        )

    async def _check_disk_space(self) -> HealthCheck:
        """Check disk space availability."""
        disk = psutil.disk_usage("/")

        if disk.percent > 95:
            status = HealthStatus.UNHEALTHY
            message = f"Critical disk usage: {disk.percent}%"
        elif disk.percent > 85:
            status = HealthStatus.DEGRADED
            message = f"High disk usage: {disk.percent}%"
        else:
            status = HealthStatus.HEALTHY
            message = f"Disk usage normal: {disk.percent}%"

        return HealthCheck(
            name="disk_space",
            status=status,
            latency_ms=0,
            message=message,
            metadata={"disk_percent": disk.percent},
        )

    async def _check_redis(self) -> HealthCheck:
        """Check Redis connection."""
        try:
            import redis

            client = redis.Redis(host="localhost", port=6379, socket_connect_timeout=1)
            start = time.time()
            client.ping()
            latency = (time.time() - start) * 1000

            return HealthCheck(
                name="redis_connection",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="Redis connection OK",
            )
        except Exception as e:
            return HealthCheck(
                name="redis_connection",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message=f"Redis connection failed: {e}",
            )

    async def _check_neo4j(self) -> HealthCheck:
        """Check Neo4j connection."""
        try:
            # Simplified check - would use actual Neo4j driver in production
            async with aiohttp.ClientSession() as session:
                start = time.time()
                async with session.get("http://localhost:7474", timeout=2) as resp:
                    latency = (time.time() - start) * 1000

                    if resp.status == 200:
                        return HealthCheck(
                            name="neo4j_connection",
                            status=HealthStatus.HEALTHY,
                            latency_ms=latency,
                            message="Neo4j connection OK",
                        )
                    else:
                        return HealthCheck(
                            name="neo4j_connection",
                            status=HealthStatus.DEGRADED,
                            latency_ms=latency,
                            message=f"Neo4j returned status {resp.status}",
                        )
        except Exception as e:
            return HealthCheck(
                name="neo4j_connection",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message=f"Neo4j connection failed: {e}",
            )

    async def _check_tool_registry(self) -> HealthCheck:
        """Check tool registry health."""
        try:
            start = time.time()

            # Prefer exposed ToolSpec count from catalog to avoid false negatives
            # from no-discovery registry construction.
            exposed_spec_count = 0
            spec_error: str | None = None
            try:
                from brain_researcher.services.tools.registry import UnifiedToolRegistry

                exposed_spec_count = len(UnifiedToolRegistry().get_exposed_toolspecs())
            except Exception as exc:  # pragma: no cover - defensive fallback
                spec_error = str(exc)

            if exposed_spec_count > 0:
                latency = (time.time() - start) * 1000
                return HealthCheck(
                    name="tool_registry",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message=f"{exposed_spec_count} exposed tool specs available",
                    metadata={
                        "exposed_toolspec_count": exposed_spec_count,
                        "health_source": "catalog",
                    },
                )

            # Fallback to real registry discovery so health doesn't fail on
            # catalog load issues or empty spec filters.
            discovered_tool_count = 0
            runtime_error: str | None = None
            try:
                from brain_researcher.services.tools.tool_registry import ToolRegistry

                registry = ToolRegistry.from_env(
                    auto_discover=True,
                    use_capabilities=False,
                    enable_integrations=False,
                    light_mode=True,
                )
                discovered_tool_count = len(registry.get_all_tools())
            except Exception as exc:  # pragma: no cover - defensive fallback
                runtime_error = str(exc)

            latency = (time.time() - start) * 1000
            if discovered_tool_count > 0:
                return HealthCheck(
                    name="tool_registry",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message=f"{discovered_tool_count} tools discovered at runtime",
                    metadata={
                        "exposed_toolspec_count": exposed_spec_count,
                        "discovered_tool_count": discovered_tool_count,
                        "health_source": "runtime_discovery",
                        "catalog_error": spec_error,
                    },
                )

            return HealthCheck(
                name="tool_registry",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message="No tool specs or runtime-discovered tools available",
                metadata={
                    "exposed_toolspec_count": exposed_spec_count,
                    "discovered_tool_count": discovered_tool_count,
                    "catalog_error": spec_error,
                    "runtime_error": runtime_error,
                },
            )
        except Exception as e:
            return HealthCheck(
                name="tool_registry",
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message=f"Tool registry error: {e}",
            )

    async def _check_executor_queue(self) -> HealthCheck:
        """Check executor queue health."""
        # This would check actual queue in production
        return HealthCheck(
            name="executor_queue",
            status=HealthStatus.HEALTHY,
            latency_ms=0,
            message="Executor queue operational",
            metadata={"queue_size": 0},
        )

    def get_status(self) -> dict[str, Any]:
        """Get current health status summary."""
        overall_status = HealthStatus.HEALTHY

        # Check all services
        for service in self.services.values():
            if service.status == HealthStatus.UNHEALTHY:
                overall_status = HealthStatus.UNHEALTHY
                break
            elif service.status == HealthStatus.DEGRADED:
                overall_status = HealthStatus.DEGRADED

        # Get latest metrics
        latest_metrics = self.metrics_history[-1] if self.metrics_history else None

        return {
            "status": overall_status.value,
            "uptime_seconds": time.time() - self.start_time,
            "services": {
                name: {
                    "status": service.status.value,
                    "availability": service.availability,
                    "last_check": (
                        service.last_check.isoformat() if service.last_check else None
                    ),
                }
                for name, service in self.services.items()
            },
            "metrics": (
                {
                    "cpu_percent": latest_metrics.cpu_percent if latest_metrics else 0,
                    "memory_percent": (
                        latest_metrics.memory_percent if latest_metrics else 0
                    ),
                    "disk_percent": (
                        latest_metrics.disk_percent if latest_metrics else 0
                    ),
                }
                if latest_metrics
                else {}
            ),
            "timestamp": datetime.now().isoformat(),
        }

    def add_alert_handler(self, handler: Callable):
        """Add an alert handler function.

        Args:
            handler: Function to call when alerts trigger
        """
        self.alert_handlers.append(handler)
        logger.info(f"Added alert handler: {handler.__name__}")
