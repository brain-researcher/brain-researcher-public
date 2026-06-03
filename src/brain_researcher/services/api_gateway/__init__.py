"""Legacy standalone API gateway compatibility surface.

The canonical Python owner now lives under `brain_researcher.legacy.api_gateway`.
This package preserves the historical `brain_researcher.services.api_gateway`
import path as a compatibility-only shim.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

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


def _load_legacy_api_gateway():
    return import_module("brain_researcher.legacy.api_gateway")


def __getattr__(name: str) -> Any:
    if name in {"API_GATEWAY_STATUS", "DEFAULT_GATEWAY_ENTRYPOINT", "__version__", "__author__", "__description__", "get_version", "get_info"}:
        return globals()[name]
    return getattr(_load_legacy_api_gateway(), name)


def get_version() -> str:
    """Get the legacy API gateway version."""

    return __version__


def get_info() -> dict:
    """Get legacy API gateway feature metadata."""

    legacy_info = _load_legacy_api_gateway().get_info()
    return {
        **legacy_info,
        "name": "Brain Researcher Legacy API Gateway",
    }
