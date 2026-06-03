"""
Service coordination with health check aggregation, service discovery,
failover handling, and circuit breaker pattern implementation.
"""

import asyncio
import logging
import random
import statistics
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field

from .env import AGENT_URL, BR_KG_URL, WEB_UI_URL
from .models import HealthResponse, ServiceHealth

logger = logging.getLogger(__name__)


# ============================================================================
# Models and Enums
# ============================================================================


class ServiceStatus(str, Enum):
    """Service status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit is open, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class ServiceType(str, Enum):
    """Types of services in the system."""

    AGENT = "agent"
    BR_KG = "br_kg"
    WEB_UI = "web_ui"
    ORCHESTRATOR = "orchestrator"
    EXTERNAL_API = "external_api"
    DATABASE = "database"
    CACHE = "cache"


class FailoverStrategy(str, Enum):
    """Failover strategies."""

    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LEAST_CONNECTIONS = "least_connections"
    FASTEST_RESPONSE = "fastest_response"
    RANDOM = "random"


class ServiceEndpoint(BaseModel):
    """Service endpoint configuration."""

    id: str
    name: str
    service_type: ServiceType
    url: str
    weight: int = 1
    priority: int = 1  # 1=primary, 2=secondary, etc.
    health_check_path: str = "/health"
    timeout_seconds: int = 10
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration."""

    failure_threshold: int = 5  # Failures needed to open circuit
    success_threshold: int = 3  # Successes needed to close circuit
    timeout_seconds: int = 60  # How long circuit stays open
    slow_call_threshold_ms: int = 5000  # Calls slower than this count as failures
    minimum_throughput: int = 10  # Minimum calls before circuit can open


class LoadBalancingConfig(BaseModel):
    """Load balancing configuration."""

    strategy: FailoverStrategy = FailoverStrategy.ROUND_ROBIN
    health_check_interval_seconds: int = 30
    max_retries_per_request: int = 3
    connection_timeout_seconds: int = 5
    request_timeout_seconds: int = 30


# ============================================================================
# Circuit Breaker Implementation
# ============================================================================


class CircuitBreaker:
    """Circuit breaker for service calls with failure detection."""

    def __init__(self, service_id: str, config: CircuitBreakerConfig):
        self.service_id = service_id
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: datetime | None = None
        self.last_state_change = datetime.utcnow()

        # Call history for minimum throughput calculation
        self.call_history: deque = deque(maxlen=100)
        self.recent_calls_window = timedelta(minutes=1)

        logger.info(f"Circuit breaker created for service {service_id}")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function call through circuit breaker."""
        # Check if circuit is open
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = datetime.utcnow()
                logger.info(f"Circuit breaker for {self.service_id} moved to HALF_OPEN")
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN for {self.service_id}"
                )

        start_time = time.time()

        try:
            # Execute the function call
            result = (
                await func(*args, **kwargs)
                if asyncio.iscoroutinefunction(func)
                else func(*args, **kwargs)
            )

            # Record successful call
            call_duration_ms = (time.time() - start_time) * 1000
            self._record_success(call_duration_ms)

            return result

        except Exception as e:
            # Record failed call
            call_duration_ms = (time.time() - start_time) * 1000
            self._record_failure(call_duration_ms)
            raise e

    def _record_success(self, call_duration_ms: float):
        """Record a successful call."""
        call_time = datetime.utcnow()
        self.call_history.append(
            {"time": call_time, "success": True, "duration_ms": call_duration_ms}
        )

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self._close_circuit()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on successful call
            self.failure_count = max(0, self.failure_count - 1)

    def _record_failure(self, call_duration_ms: float):
        """Record a failed call."""
        call_time = datetime.utcnow()
        self.call_history.append(
            {"time": call_time, "success": False, "duration_ms": call_duration_ms}
        )

        # Count slow calls as failures
        is_slow_call = call_duration_ms > self.config.slow_call_threshold_ms

        self.failure_count += 1
        self.last_failure_time = call_time

        # Check if we should open the circuit
        if self._should_open_circuit():
            self._open_circuit()

        logger.warning(
            f"Call failed for {self.service_id} (failure count: {self.failure_count}, slow: {is_slow_call})"
        )

    def _should_open_circuit(self) -> bool:
        """Check if circuit should be opened."""
        if self.state == CircuitState.OPEN:
            return False

        # Need minimum throughput to open circuit
        recent_calls = self._get_recent_calls()
        if len(recent_calls) < self.config.minimum_throughput:
            return False

        # Check failure threshold
        return self.failure_count >= self.config.failure_threshold

    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset from OPEN to HALF_OPEN."""
        if self.state != CircuitState.OPEN or not self.last_failure_time:
            return False

        timeout_passed = (
            datetime.utcnow() - self.last_failure_time
        ).total_seconds() >= self.config.timeout_seconds

        return timeout_passed

    def _open_circuit(self):
        """Open the circuit breaker."""
        self.state = CircuitState.OPEN
        self.success_count = 0
        self.last_state_change = datetime.utcnow()

        logger.warning(
            f"Circuit breaker OPENED for {self.service_id} (failures: {self.failure_count})"
        )

    def _close_circuit(self):
        """Close the circuit breaker."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = datetime.utcnow()

        logger.info(f"Circuit breaker CLOSED for {self.service_id}")

    def _get_recent_calls(self) -> list[dict[str, Any]]:
        """Get calls within the recent time window."""
        cutoff_time = datetime.utcnow() - self.recent_calls_window
        return [call for call in self.call_history if call["time"] > cutoff_time]

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        recent_calls = self._get_recent_calls()
        success_calls = [call for call in recent_calls if call["success"]]

        return {
            "service_id": self.service_id,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": (
                self.last_failure_time.isoformat() if self.last_failure_time else None
            ),
            "last_state_change": self.last_state_change.isoformat(),
            "recent_calls": len(recent_calls),
            "recent_success_rate": (
                len(success_calls) / len(recent_calls) if recent_calls else 0
            ),
            "avg_response_time_ms": (
                statistics.mean([call["duration_ms"] for call in recent_calls])
                if recent_calls
                else 0
            ),
        }


class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is open."""

    pass


# ============================================================================
# Service Discovery and Registry
# ============================================================================


class ServiceRegistry:
    """Service discovery and registry with health monitoring."""

    def __init__(self):
        self.services: dict[str, list[ServiceEndpoint]] = defaultdict(list)
        self.service_health: dict[str, ServiceHealth] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.load_balancing_state: dict[str, dict[str, Any]] = defaultdict(dict)

        # Health monitoring
        self.health_check_task: asyncio.Task | None = None
        self.health_check_interval = 30  # seconds

        logger.info("Service registry initialized")

    def register_service(self, endpoint: ServiceEndpoint):
        """Register a service endpoint."""
        service_name = endpoint.service_type.value

        # Remove any existing endpoint with same ID
        self.services[service_name] = [
            ep for ep in self.services[service_name] if ep.id != endpoint.id
        ]

        # Add new endpoint
        self.services[service_name].append(endpoint)

        # Initialize circuit breaker
        circuit_config = CircuitBreakerConfig()
        self.circuit_breakers[endpoint.id] = CircuitBreaker(endpoint.id, circuit_config)

        # Initialize load balancing state
        self.load_balancing_state[service_name]["current_index"] = 0
        self.load_balancing_state[service_name]["connection_counts"] = defaultdict(int)

        logger.info(f"Registered service endpoint: {endpoint.name} ({endpoint.id})")

    def unregister_service(self, endpoint_id: str):
        """Unregister a service endpoint."""
        for service_name, endpoints in self.services.items():
            self.services[service_name] = [
                ep for ep in endpoints if ep.id != endpoint_id
            ]

        # Clean up circuit breaker
        if endpoint_id in self.circuit_breakers:
            del self.circuit_breakers[endpoint_id]

        logger.info(f"Unregistered service endpoint: {endpoint_id}")

    def discover_service(
        self,
        service_type: ServiceType,
        strategy: FailoverStrategy = FailoverStrategy.ROUND_ROBIN,
        tags: list[str] | None = None,
    ) -> ServiceEndpoint | None:
        """Discover an available service endpoint."""
        service_name = service_type.value
        endpoints = self.services.get(service_name, [])

        if not endpoints:
            logger.warning(f"No endpoints found for service {service_name}")
            return None

        # Filter by tags if provided
        if tags:
            endpoints = [ep for ep in endpoints if any(tag in ep.tags for tag in tags)]

        # Filter out unhealthy endpoints
        healthy_endpoints = []
        for endpoint in endpoints:
            health = self.service_health.get(endpoint.id)
            circuit_breaker = self.circuit_breakers.get(endpoint.id)

            # Skip if circuit breaker is open
            if circuit_breaker and circuit_breaker.state == CircuitState.OPEN:
                continue

            # Skip if marked as unhealthy
            if health and health.status in ["unhealthy", "unavailable"]:
                continue

            healthy_endpoints.append(endpoint)

        if not healthy_endpoints:
            logger.warning(f"No healthy endpoints found for service {service_name}")
            # Return a random endpoint as fallback
            return random.choice(endpoints) if endpoints else None

        # Apply load balancing strategy
        return self._apply_load_balancing_strategy(
            service_name, healthy_endpoints, strategy
        )

    def _apply_load_balancing_strategy(
        self,
        service_name: str,
        endpoints: list[ServiceEndpoint],
        strategy: FailoverStrategy,
    ) -> ServiceEndpoint:
        """Apply load balancing strategy to select endpoint."""

        if strategy == FailoverStrategy.ROUND_ROBIN:
            state = self.load_balancing_state[service_name]
            index = state.get("current_index", 0)
            selected = endpoints[index % len(endpoints)]
            state["current_index"] = (index + 1) % len(endpoints)
            return selected

        elif strategy == FailoverStrategy.WEIGHTED:
            total_weight = sum(ep.weight for ep in endpoints)
            if total_weight == 0:
                return random.choice(endpoints)

            rand_weight = random.randint(1, total_weight)
            current_weight = 0

            for endpoint in endpoints:
                current_weight += endpoint.weight
                if rand_weight <= current_weight:
                    return endpoint

            return endpoints[-1]  # Fallback

        elif strategy == FailoverStrategy.LEAST_CONNECTIONS:
            connection_counts = self.load_balancing_state[service_name].get(
                "connection_counts", {}
            )
            return min(endpoints, key=lambda ep: connection_counts.get(ep.id, 0))

        elif strategy == FailoverStrategy.FASTEST_RESPONSE:
            # Use circuit breaker stats to find fastest endpoint
            fastest_endpoint = None
            fastest_time = float("inf")

            for endpoint in endpoints:
                circuit_breaker = self.circuit_breakers.get(endpoint.id)
                if circuit_breaker:
                    stats = circuit_breaker.get_stats()
                    avg_time = stats.get("avg_response_time_ms", float("inf"))
                    if avg_time < fastest_time:
                        fastest_time = avg_time
                        fastest_endpoint = endpoint

            return fastest_endpoint or random.choice(endpoints)

        else:  # RANDOM
            return random.choice(endpoints)

    async def start_health_monitoring(self):
        """Start periodic health checks for all registered services."""
        if self.health_check_task:
            return

        self.health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("Service health monitoring started")

    async def stop_health_monitoring(self):
        """Stop health monitoring."""
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
            self.health_check_task = None

        logger.info("Service health monitoring stopped")

    async def _health_check_loop(self):
        """Background task to perform health checks."""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)

                # Collect all endpoints
                all_endpoints = []
                for endpoints in self.services.values():
                    all_endpoints.extend(endpoints)

                # Perform health checks concurrently
                tasks = [
                    self._check_endpoint_health(endpoint) for endpoint in all_endpoints
                ]

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                logger.error(f"Health check loop error: {str(e)}")

    async def _check_endpoint_health(self, endpoint: ServiceEndpoint):
        """Perform health check for a single endpoint."""
        try:
            circuit_breaker = self.circuit_breakers[endpoint.id]

            async def health_check():
                timeout = httpx.Timeout(endpoint.timeout_seconds)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(
                        f"{endpoint.url.rstrip('/')}{endpoint.health_check_path}",
                        follow_redirects=True,
                    )
                    response.raise_for_status()
                    return response.json()

            # Use circuit breaker for health check
            await circuit_breaker.call(health_check)

            # Update service health
            self.service_health[endpoint.id] = ServiceHealth(
                name=endpoint.name,
                status="healthy",
                latency_ms=int(
                    circuit_breaker.get_stats().get("avg_response_time_ms", 0)
                ),
                last_check=datetime.utcnow(),
            )

        except CircuitBreakerOpenError:
            # Circuit breaker is open, mark as unavailable
            self.service_health[endpoint.id] = ServiceHealth(
                name=endpoint.name,
                status="unavailable",
                last_check=datetime.utcnow(),
                error="Circuit breaker is open",
            )

        except Exception as e:
            # Health check failed
            self.service_health[endpoint.id] = ServiceHealth(
                name=endpoint.name,
                status="unhealthy",
                last_check=datetime.utcnow(),
                error=str(e),
            )

    def get_service_health(
        self, service_type: ServiceType | None = None
    ) -> dict[str, ServiceHealth]:
        """Get health status for all services or specific service type."""
        if service_type:
            service_name = service_type.value
            endpoints = self.services.get(service_name, [])
            return {
                endpoint.id: self.service_health.get(
                    endpoint.id,
                    ServiceHealth(
                        name=endpoint.name,
                        status="unknown",
                        last_check=datetime.utcnow(),
                    ),
                )
                for endpoint in endpoints
            }
        else:
            return self.service_health.copy()

    def get_circuit_breaker_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all circuit breakers."""
        return {
            endpoint_id: circuit_breaker.get_stats()
            for endpoint_id, circuit_breaker in self.circuit_breakers.items()
        }


# ============================================================================
# Service Coordinator
# ============================================================================


class ServiceCoordinator:
    """Main service coordination class with failover and circuit breaker integration."""

    def __init__(self, load_balancing_config: LoadBalancingConfig | None = None):
        self.config = load_balancing_config or LoadBalancingConfig()
        self.registry = ServiceRegistry()
        self.request_stats: dict[str, list[dict[str, Any]]] = defaultdict(list)

        # Failover handlers
        self.failover_handlers: dict[ServiceType, list[Callable]] = defaultdict(list)

        logger.info("Service coordinator initialized")

    async def start(self):
        """Start the service coordinator."""
        await self.registry.start_health_monitoring()

        # Register default services
        await self._register_default_services()

        logger.info("Service coordinator started")

    async def stop(self):
        """Stop the service coordinator."""
        await self.registry.stop_health_monitoring()
        logger.info("Service coordinator stopped")

    async def _register_default_services(self):
        """Register default Brain Researcher services."""
        web_ui_url = WEB_UI_URL

        default_services = [
            ServiceEndpoint(
                id="agent_primary",
                name="Agent Service Primary",
                service_type=ServiceType.AGENT,
                url=AGENT_URL,
                weight=10,
                priority=1,
                tags=["primary", "llm", "agent"],
            ),
            ServiceEndpoint(
                id="br_kg_primary",
                name="BR-KG Service Primary",
                service_type=ServiceType.BR_KG,
                url=BR_KG_URL,
                weight=10,
                priority=1,
                tags=["primary", "knowledge-graph", "database"],
            ),
            ServiceEndpoint(
                id="web_ui_primary",
                name="Web UI Primary",
                service_type=ServiceType.WEB_UI,
                url=web_ui_url,
                weight=10,
                priority=1,
                tags=["primary", "frontend", "ui"],
            ),
        ]

        for service in default_services:
            self.registry.register_service(service)

    async def make_request(
        self, service_type: ServiceType, method: str, path: str, **kwargs
    ) -> Any:
        """Make a request to a service with failover and circuit breaker protection."""

        for attempt in range(self.config.max_retries_per_request):
            endpoint = self.registry.discover_service(
                service_type, self.config.strategy
            )

            if not endpoint:
                raise ServiceUnavailableError(
                    f"No available endpoints for {service_type.value}"
                )

            try:
                # Track connection count for load balancing
                connection_counts = self.registry.load_balancing_state[
                    service_type.value
                ].get("connection_counts", {})
                connection_counts[endpoint.id] = (
                    connection_counts.get(endpoint.id, 0) + 1
                )

                circuit_breaker = self.registry.circuit_breakers[endpoint.id]

                async def make_http_request():
                    timeout = httpx.Timeout(
                        timeout=self.config.request_timeout_seconds,
                        connect=self.config.connection_timeout_seconds,
                        read=self.config.request_timeout_seconds,
                        write=self.config.request_timeout_seconds,
                        pool=self.config.connection_timeout_seconds,
                    )

                    async with httpx.AsyncClient(timeout=timeout) as client:
                        url = f"{endpoint.url.rstrip('/')}{path}"
                        response = await client.request(method, url, **kwargs)
                        response.raise_for_status()
                        return response

                # Make request through circuit breaker
                start_time = time.time()
                response = await circuit_breaker.call(make_http_request)
                duration_ms = (time.time() - start_time) * 1000

                # Record successful request
                self._record_request_stats(endpoint.id, True, duration_ms)

                # Update connection count
                connection_counts[endpoint.id] -= 1

                return response

            except CircuitBreakerOpenError:
                logger.warning(
                    f"Circuit breaker open for {endpoint.id}, trying next endpoint"
                )
                continue

            except Exception as e:
                logger.error(f"Request failed to {endpoint.id}: {str(e)}")

                # Record failed request
                self._record_request_stats(endpoint.id, False, 0)

                # Update connection count
                connection_counts = self.registry.load_balancing_state[
                    service_type.value
                ].get("connection_counts", {})
                connection_counts[endpoint.id] = max(
                    0, connection_counts.get(endpoint.id, 1) - 1
                )

                # Notify failover handlers
                await self._notify_failover_handlers(service_type, endpoint, e)

                # If this was the last attempt, re-raise the exception
                if attempt == self.config.max_retries_per_request - 1:
                    raise

        raise ServiceUnavailableError(f"All attempts failed for {service_type.value}")

    def _record_request_stats(
        self, endpoint_id: str, success: bool, duration_ms: float
    ):
        """Record request statistics."""
        self.request_stats[endpoint_id].append(
            {
                "timestamp": datetime.utcnow(),
                "success": success,
                "duration_ms": duration_ms,
            }
        )

        # Keep only recent stats (last hour)
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        self.request_stats[endpoint_id] = [
            stat
            for stat in self.request_stats[endpoint_id]
            if stat["timestamp"] > cutoff_time
        ]

    async def _notify_failover_handlers(
        self,
        service_type: ServiceType,
        failed_endpoint: ServiceEndpoint,
        error: Exception,
    ):
        """Notify registered failover handlers."""
        for handler in self.failover_handlers[service_type]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(service_type, failed_endpoint, error)
                else:
                    handler(service_type, failed_endpoint, error)
            except Exception as e:
                logger.error(f"Failover handler error: {str(e)}")

    def register_failover_handler(self, service_type: ServiceType, handler: Callable):
        """Register a failover event handler."""
        self.failover_handlers[service_type].append(handler)
        logger.info(f"Registered failover handler for {service_type.value}")

    def get_aggregated_health(self) -> HealthResponse:
        """Get aggregated health status for all services."""
        all_health = self.registry.get_service_health()

        # Determine overall system status
        if not all_health:
            overall_status = "healthy"
        else:
            unhealthy_count = len(
                [
                    h
                    for h in all_health.values()
                    if h.status in ["unhealthy", "unavailable"]
                ]
            )
            degraded_count = len(
                [h for h in all_health.values() if h.status == "degraded"]
            )
            total_count = len(all_health)

            if unhealthy_count > total_count * 0.5:
                overall_status = "unhealthy"
            elif unhealthy_count > 0 or degraded_count > total_count * 0.3:
                overall_status = "degraded"
            else:
                overall_status = "healthy"

        return HealthResponse(
            status=overall_status, services=all_health, timestamp=datetime.utcnow()
        )

    def get_service_stats(self) -> dict[str, Any]:
        """Get comprehensive service statistics."""
        circuit_stats = self.registry.get_circuit_breaker_stats()

        # Calculate request statistics
        request_summary = {}
        for endpoint_id, stats in self.request_stats.items():
            if stats:
                success_count = len([s for s in stats if s["success"]])
                total_count = len(stats)
                avg_duration = statistics.mean(
                    [s["duration_ms"] for s in stats if s["success"]]
                )

                request_summary[endpoint_id] = {
                    "total_requests": total_count,
                    "success_rate": success_count / total_count * 100,
                    "avg_response_time_ms": avg_duration,
                }

        return {
            "circuit_breakers": circuit_stats,
            "request_stats": request_summary,
            "registered_services": {
                service_type: len(endpoints)
                for service_type, endpoints in self.registry.services.items()
            },
            "load_balancing_strategy": self.config.strategy.value,
        }


class ServiceUnavailableError(Exception):
    """Exception raised when no services are available."""

    pass


# Global service coordinator instance
service_coordinator = ServiceCoordinator()
