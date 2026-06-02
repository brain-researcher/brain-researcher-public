"""
Service Mesh Configuration and Management.

Provides service mesh capabilities including service proxy, traffic routing,
security policies, and observability for Brain Researcher services.
"""

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import httpx
import redis.asyncio as redis
from fastapi import Request, Response

from brain_researcher.services.shared.trace_headers import (
    get_trace_id,
    set_trace_headers,
)

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .retry_policy import RetryConfig, RetryPolicy

logger = logging.getLogger(__name__)


class TrafficPolicy(str, Enum):
    """Traffic routing policies."""

    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    CANARY = "canary"
    BLUE_GREEN = "blue_green"
    STICKY_SESSION = "sticky_session"


class SecurityPolicy(str, Enum):
    """Security policies for service mesh."""

    MUTUAL_TLS = "mtls"
    JWT_VALIDATION = "jwt"
    RBAC = "rbac"
    RATE_LIMITING = "rate_limit"


@dataclass
class ServiceEndpoint:
    """Service endpoint configuration."""

    name: str
    url: str
    version: str = "v1"
    weight: int = 100
    health_check_path: str = "/health"
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class TrafficRoute:
    """Traffic routing rule."""

    name: str
    source_service: Optional[str] = None
    destination_service: str = ""
    path_patterns: List[str] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    policy: TrafficPolicy = TrafficPolicy.ROUND_ROBIN
    endpoints: List[ServiceEndpoint] = field(default_factory=list)
    timeout_seconds: float = 30.0
    retries: int = 3
    circuit_breaker: Optional[CircuitBreakerConfig] = None


@dataclass
class SecurityRule:
    """Security rule for service mesh."""

    name: str
    policy: SecurityPolicy
    source_services: List[str] = field(default_factory=list)
    destination_services: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class MeshConfig:
    """Service mesh configuration."""

    cluster_name: str = "brain_researcher"
    enable_mtls: bool = False
    enable_tracing: bool = True
    enable_metrics: bool = True
    default_timeout_seconds: float = 30.0
    default_retries: int = 3
    health_check_interval_seconds: int = 30
    traffic_routes: List[TrafficRoute] = field(default_factory=list)
    security_rules: List[SecurityRule] = field(default_factory=list)
    redis_url: str = "redis://localhost:6379/1"


class ServiceProxy:
    """Service proxy for handling inter-service communication."""

    def __init__(self, config: MeshConfig, service_name: str):
        """Initialize service proxy.

        Args:
            config: Mesh configuration
            service_name: Name of the service this proxy represents
        """
        self.config = config
        self.service_name = service_name
        self.http_client = httpx.AsyncClient(timeout=config.default_timeout_seconds)
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.retry_policies: Dict[str, RetryPolicy] = {}
        self.request_metrics: Dict[str, Dict[str, Any]] = {}

    async def proxy_request(
        self, target_service: str, request: Request, body: bytes
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Proxy request to target service through service mesh.

        Args:
            target_service: Target service name
            request: Incoming request
            body: Request body

        Returns:
            Tuple of (status_code, headers, response_body)
        """
        try:
            # Find routing rule
            route = self._find_route(target_service, request)
            if not route:
                return 503, {}, b"Service not available"

            # Apply security policies
            if not await self._check_security(route, request):
                return 403, {}, b"Access denied"

            # Select endpoint
            endpoint = await self._select_endpoint(route, request)
            if not endpoint:
                return 503, {}, b"No healthy endpoints"

            # Get circuit breaker
            circuit_breaker = await self._get_circuit_breaker(target_service, endpoint)

            # Check if circuit is open
            if circuit_breaker.is_open():
                return 503, {}, b"Circuit breaker open"

            # Make request with retry policy
            retry_policy = await self._get_retry_policy(target_service)

            start_time = time.time()
            status_code, headers, response_body = await retry_policy.execute(
                self._make_request, endpoint, request, body
            )
            duration = time.time() - start_time

            # Record metrics
            await self._record_metrics(target_service, endpoint, status_code, duration)

            # Update circuit breaker
            if 200 <= status_code < 500:
                circuit_breaker.record_success()
            else:
                circuit_breaker.record_failure()

            return status_code, headers, response_body

        except Exception as e:
            logger.error(f"Proxy request error: {e}")
            return 500, {}, b"Internal proxy error"

    async def _make_request(
        self, endpoint: ServiceEndpoint, request: Request, body: bytes
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Make HTTP request to service endpoint."""
        # Build target URL
        target_url = f"{endpoint.url.rstrip('/')}{request.url.path}"

        # Prepare headers
        headers = dict(request.headers)

        # Add mesh headers
        headers["X-Mesh-Source"] = self.service_name
        headers["X-Mesh-Request-ID"] = str(uuid.uuid4())
        headers["X-Mesh-Timestamp"] = datetime.utcnow().isoformat()

        # Add tracing headers if enabled
        if self.config.enable_tracing:
            trace_id = get_trace_id(headers) or str(uuid.uuid4())
            set_trace_headers(headers, trace_id)
            headers["X-Span-ID"] = str(uuid.uuid4())

        # Make request
        response = await self.http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )

        return response.status_code, dict(response.headers), response.content

    def _find_route(
        self, target_service: str, request: Request
    ) -> Optional[TrafficRoute]:
        """Find matching traffic route."""
        for route in self.config.traffic_routes:
            if route.destination_service != target_service:
                continue

            # Check source service if specified
            if route.source_service and route.source_service != self.service_name:
                continue

            # Check path patterns
            if route.path_patterns:
                path_matches = any(
                    self._path_matches(request.url.path, pattern)
                    for pattern in route.path_patterns
                )
                if not path_matches:
                    continue

            # Check header conditions
            if route.headers:
                header_matches = all(
                    request.headers.get(key) == value
                    for key, value in route.headers.items()
                )
                if not header_matches:
                    continue

            return route

        return None

    def _path_matches(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern."""
        import re

        regex_pattern = pattern.replace("*", ".*").replace("?", ".")
        return bool(re.match(f"^{regex_pattern}$", path))

    async def _check_security(self, route: TrafficRoute, request: Request) -> bool:
        """Check security policies."""
        for rule in self.config.security_rules:
            if not rule.enabled:
                continue

            # Check if rule applies
            if rule.source_services and self.service_name not in rule.source_services:
                continue

            if (
                rule.destination_services
                and route.destination_service not in rule.destination_services
            ):
                continue

            # Apply security policy
            if not await self._apply_security_policy(rule, request):
                return False

        return True

    async def _apply_security_policy(
        self, rule: SecurityRule, request: Request
    ) -> bool:
        """Apply specific security policy."""
        if rule.policy == SecurityPolicy.JWT_VALIDATION:
            return await self._validate_jwt(request, rule.config)

        elif rule.policy == SecurityPolicy.RBAC:
            return await self._check_rbac(request, rule.config)

        elif rule.policy == SecurityPolicy.RATE_LIMITING:
            return await self._check_rate_limit(request, rule.config)

        # Default allow for other policies
        return True

    async def _validate_jwt(self, request: Request, config: Dict[str, Any]) -> bool:
        """Validate JWT token."""
        try:
            import jwt

            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return False

            token = auth_header[7:]
            secret = config.get("secret", "default_secret")
            algorithm = config.get("algorithm", "HS256")

            decoded = jwt.decode(token, secret, algorithms=[algorithm])

            # Store user info in request context
            request.state.user = decoded
            return True

        except Exception as e:
            logger.warning(f"JWT validation failed: {e}")
            return False

    async def _check_rbac(self, request: Request, config: Dict[str, Any]) -> bool:
        """Check role-based access control."""
        user = getattr(request.state, "user", {})
        required_roles = config.get("required_roles", [])
        user_roles = user.get("roles", [])

        return any(role in user_roles for role in required_roles)

    async def _check_rate_limit(self, request: Request, config: Dict[str, Any]) -> bool:
        """Check rate limiting."""
        # Simplified rate limiting - would use Redis in production
        limit = config.get("requests_per_minute", 60)
        user_id = getattr(request.state, "user", {}).get("user_id", "anonymous")

        # For now, always allow
        return True

    async def _select_endpoint(
        self, route: TrafficRoute, request: Request
    ) -> Optional[ServiceEndpoint]:
        """Select service endpoint based on routing policy."""
        if not route.endpoints:
            return None

        if route.policy == TrafficPolicy.ROUND_ROBIN:
            return await self._round_robin_select(route.endpoints)

        elif route.policy == TrafficPolicy.WEIGHTED:
            return await self._weighted_select(route.endpoints)

        elif route.policy == TrafficPolicy.CANARY:
            return await self._canary_select(route.endpoints, request)

        elif route.policy == TrafficPolicy.BLUE_GREEN:
            return await self._blue_green_select(route.endpoints)

        elif route.policy == TrafficPolicy.STICKY_SESSION:
            return await self._sticky_session_select(route.endpoints, request)

        # Default to first endpoint
        return route.endpoints[0]

    async def _round_robin_select(
        self, endpoints: List[ServiceEndpoint]
    ) -> ServiceEndpoint:
        """Round robin endpoint selection."""
        # Simple implementation - would use Redis counter in production
        import random

        return random.choice(endpoints)

    async def _weighted_select(
        self, endpoints: List[ServiceEndpoint]
    ) -> ServiceEndpoint:
        """Weighted endpoint selection."""
        import random

        total_weight = sum(ep.weight for ep in endpoints)
        if total_weight == 0:
            return random.choice(endpoints)

        r = random.randint(1, total_weight)
        current_weight = 0

        for endpoint in endpoints:
            current_weight += endpoint.weight
            if r <= current_weight:
                return endpoint

        return endpoints[-1]

    async def _canary_select(
        self, endpoints: List[ServiceEndpoint], request: Request
    ) -> ServiceEndpoint:
        """Canary deployment selection."""
        # Look for canary version
        canary_endpoints = [ep for ep in endpoints if "canary" in ep.version.lower()]
        stable_endpoints = [
            ep for ep in endpoints if "canary" not in ep.version.lower()
        ]

        # Route small percentage to canary
        canary_percentage = 10  # 10% traffic to canary

        import random

        if canary_endpoints and random.randint(1, 100) <= canary_percentage:
            return random.choice(canary_endpoints)

        return random.choice(stable_endpoints) if stable_endpoints else endpoints[0]

    async def _blue_green_select(
        self, endpoints: List[ServiceEndpoint]
    ) -> ServiceEndpoint:
        """Blue-green deployment selection."""
        # Look for "green" version, fallback to "blue"
        green_endpoints = [ep for ep in endpoints if ep.version.lower() == "green"]
        if green_endpoints:
            return green_endpoints[0]

        blue_endpoints = [ep for ep in endpoints if ep.version.lower() == "blue"]
        if blue_endpoints:
            return blue_endpoints[0]

        return endpoints[0]

    async def _sticky_session_select(
        self, endpoints: List[ServiceEndpoint], request: Request
    ) -> ServiceEndpoint:
        """Sticky session selection."""
        session_id = request.headers.get("X-Session-ID") or request.cookies.get(
            "session_id"
        )

        if session_id:
            # Hash session ID to endpoint
            import hashlib

            hash_value = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
            endpoint_index = hash_value % len(endpoints)
            return endpoints[endpoint_index]

        return endpoints[0]

    async def _get_circuit_breaker(
        self, service: str, endpoint: ServiceEndpoint
    ) -> CircuitBreaker:
        """Get or create circuit breaker for service endpoint."""
        key = f"{service}:{endpoint.name}"

        if key not in self.circuit_breakers:
            config = CircuitBreakerConfig(
                failure_threshold=5, recovery_timeout_seconds=60, half_open_max_calls=3
            )
            self.circuit_breakers[key] = CircuitBreaker(config)

        return self.circuit_breakers[key]

    async def _get_retry_policy(self, service: str) -> RetryPolicy:
        """Get or create retry policy for service."""
        if service not in self.retry_policies:
            config = RetryConfig(
                max_attempts=self.config.default_retries,
                base_delay_seconds=1.0,
                max_delay_seconds=30.0,
                backoff_multiplier=2.0,
            )
            self.retry_policies[service] = RetryPolicy(config)

        return self.retry_policies[service]

    async def _record_metrics(
        self, service: str, endpoint: ServiceEndpoint, status_code: int, duration: float
    ):
        """Record request metrics."""
        if not self.config.enable_metrics:
            return

        key = f"{service}:{endpoint.name}"

        if key not in self.request_metrics:
            self.request_metrics[key] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_duration": 0.0,
                "avg_duration": 0.0,
                "last_request": None,
            }

        metrics = self.request_metrics[key]
        metrics["total_requests"] += 1
        metrics["total_duration"] += duration
        metrics["avg_duration"] = metrics["total_duration"] / metrics["total_requests"]
        metrics["last_request"] = datetime.utcnow().isoformat()

        if 200 <= status_code < 400:
            metrics["successful_requests"] += 1
        else:
            metrics["failed_requests"] += 1

    async def get_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get service proxy metrics."""
        return self.request_metrics.copy()

    async def close(self):
        """Close proxy and cleanup resources."""
        await self.http_client.aclose()


class ServiceMesh:
    """Main service mesh coordinator."""

    def __init__(self, config: MeshConfig):
        """Initialize service mesh.

        Args:
            config: Mesh configuration
        """
        self.config = config
        self.proxies: Dict[str, ServiceProxy] = {}
        self.redis_client = None
        self.running = False
        self._health_check_task = None

    async def start(self):
        """Start service mesh."""
        try:
            # Connect to Redis for distributed coordination
            self.redis_client = redis.from_url(self.config.redis_url)

            # Start health checking
            self._health_check_task = asyncio.create_task(self._health_check_loop())

            self.running = True
            logger.info("Service mesh started")

        except Exception as e:
            logger.error(f"Failed to start service mesh: {e}")
            raise

    async def stop(self):
        """Stop service mesh."""
        self.running = False

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Close all proxies
        for proxy in self.proxies.values():
            await proxy.close()

        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()

        logger.info("Service mesh stopped")

    def register_service(self, service_name: str) -> ServiceProxy:
        """Register service with mesh.

        Args:
            service_name: Name of the service

        Returns:
            Service proxy instance
        """
        if service_name not in self.proxies:
            self.proxies[service_name] = ServiceProxy(self.config, service_name)

        return self.proxies[service_name]

    def unregister_service(self, service_name: str):
        """Unregister service from mesh.

        Args:
            service_name: Name of the service
        """
        if service_name in self.proxies:
            asyncio.create_task(self.proxies[service_name].close())
            del self.proxies[service_name]

    async def get_mesh_status(self) -> Dict[str, Any]:
        """Get service mesh status."""
        status = {
            "cluster_name": self.config.cluster_name,
            "running": self.running,
            "services": list(self.proxies.keys()),
            "routes": len(self.config.traffic_routes),
            "security_rules": len(self.config.security_rules),
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Add service metrics
        service_metrics = {}
        for service_name, proxy in self.proxies.items():
            service_metrics[service_name] = await proxy.get_metrics()

        status["service_metrics"] = service_metrics

        return status

    async def _health_check_loop(self):
        """Background health checking loop."""
        while self.running:
            try:
                await self._check_service_health()
                await asyncio.sleep(self.config.health_check_interval_seconds)

            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(60)

    async def _check_service_health(self):
        """Check health of all service endpoints."""
        for route in self.config.traffic_routes:
            for endpoint in route.endpoints:
                try:
                    health_url = (
                        f"{endpoint.url.rstrip('/')}{endpoint.health_check_path}"
                    )

                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(health_url)

                        if response.status_code == 200:
                            # Endpoint is healthy
                            pass
                        else:
                            logger.warning(
                                f"Endpoint {endpoint.name} unhealthy: {response.status_code}"
                            )

                except Exception as e:
                    logger.warning(f"Health check failed for {endpoint.name}: {e}")


# Export components
__all__ = [
    "ServiceMesh",
    "ServiceProxy",
    "MeshConfig",
    "TrafficRoute",
    "ServiceEndpoint",
    "SecurityRule",
    "TrafficPolicy",
    "SecurityPolicy",
]
