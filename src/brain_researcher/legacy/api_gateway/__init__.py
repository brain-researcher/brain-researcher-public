"""
Legacy standalone API gateway compatibility surface.

The default runtime topology is split services (web, agent, orchestrator,
br_kg, mcp). This package is the canonical Python owner for the older full
reverse-proxy gateway. No standalone reverse-proxy config or Docker image is
shipped in the public tree.

The legacy gateway provides a unified entry point for Brain Researcher
microservices with features including:

- HTTP reverse proxy with intelligent routing
- Service discovery and health monitoring
- JWT authentication and API key management
- Advanced rate limiting with multiple algorithms
- Request/response transformation and validation
- Load balancing with multiple strategies
- Circuit breaker pattern for resilience
- WebSocket proxy support
- Caching and compression
- Comprehensive metrics and monitoring
- CORS and security headers
- Real-time service health monitoring

Components:
- gateway: Main legacy gateway application and server
- service_registry: Service discovery and registration
- auth_middleware: Authentication and authorization
- rate_limiter: Rate limiting with multiple algorithms
- request_transformer: Request/response transformation
- health_monitor: Service health checking and monitoring
- load_balancer: Load balancing strategies
- job_submission: Job management endpoints (legacy)
- job_status: Job status tracking (legacy)

Usage (legacy full-gateway path only):
    from brain_researcher.legacy.api_gateway import create_gateway

    app = create_gateway("/path/to/local-gateway.yaml")

    # Run with uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
"""

from brain_researcher.services.shared.auth_middleware import (
    APIKeyManager,
    AuthConfig,
)
from brain_researcher.services.shared.auth_middleware import (
    RateLimiter as AuthRateLimiter,
)
from brain_researcher.services.shared.auth_middleware import (
    TokenManager,
    UserInfo,
    get_current_user,
    require_permissions,
    require_roles,
)

from .gateway import APIGateway, create_gateway
from .health_monitor import (
    HealthAlert,
    HealthCheckConfig,
    HealthCheckType,
    HealthMetrics,
    HealthMonitor,
)
from .load_balancer import (
    AffinityType,
    InstanceMetrics,
    LoadBalancer,
    LoadBalancerConfig,
    LoadBalancingStrategy,
)
from .rate_limiter import (
    RateLimitAlgorithm,
    RateLimiter,
    RateLimitExceeded,
    RateLimitInfo,
    RateLimitRule,
    RateLimitScope,
)
from .request_transformer import (
    RequestTransformationConfig,
    RequestTransformer,
    ResponseTransformationConfig,
    ResponseTransformer,
    TransformationAction,
    TransformationRule,
)
from .service_registry import (
    Service,
    ServiceHealth,
    ServiceInstance,
    ServiceRegistry,
    ServiceStatus,
)

API_GATEWAY_STATUS = "legacy_compatibility"
DEFAULT_GATEWAY_ENTRYPOINT = "brain_researcher.services.agent.asgi:app"

__version__ = "1.0.0"
__author__ = "Brain Researcher Team"
__description__ = "Legacy standalone API gateway compatibility surface"

__all__ = [
    "APIGateway",
    "create_gateway",
    "ServiceRegistry",
    "Service",
    "ServiceInstance",
    "ServiceHealth",
    "ServiceStatus",
    "get_current_user",
    "UserInfo",
    "require_roles",
    "require_permissions",
    "AuthConfig",
    "TokenManager",
    "APIKeyManager",
    "RateLimiter",
    "RateLimitRule",
    "RateLimitInfo",
    "RateLimitExceeded",
    "RateLimitAlgorithm",
    "RateLimitScope",
    "RequestTransformer",
    "ResponseTransformer",
    "RequestTransformationConfig",
    "ResponseTransformationConfig",
    "TransformationRule",
    "TransformationAction",
    "HealthMonitor",
    "HealthCheckConfig",
    "HealthCheckType",
    "HealthAlert",
    "HealthMetrics",
    "LoadBalancer",
    "LoadBalancerConfig",
    "LoadBalancingStrategy",
    "AffinityType",
    "InstanceMetrics",
    "__version__",
    "__author__",
    "__description__",
]


def get_version() -> str:
    """Get the legacy API gateway version."""

    return __version__


def get_info() -> dict:
    """Get legacy API gateway feature metadata."""

    return {
        "name": "Brain Researcher Legacy API Gateway",
        "version": __version__,
        "description": __description__,
        "author": __author__,
        "features": [
            "HTTP reverse proxy",
            "Service discovery",
            "JWT authentication",
            "API key management",
            "Advanced rate limiting",
            "Request/response transformation",
            "Load balancing",
            "Circuit breaker",
            "Health monitoring",
            "WebSocket proxy",
            "Caching and compression",
            "Metrics and monitoring",
            "CORS support",
            "Security headers",
        ],
        "supported_services": [
            "orchestrator (port 3001)",
            "agent (port 8000)",
            "br_kg (port 5000)",
            "niclip (port 8001)",
        ],
    }
