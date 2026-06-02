"""Compatibility shim for legacy API gateway auth imports."""

from brain_researcher.services.shared.auth_middleware import (
    APIKey,
    APIKeyManager,
    AuthConfig,
    AuthType,
    RateLimiter,
    TokenManager,
    TokenPayload,
    TokenType,
    UserInfo,
    UserRole,
    get_current_user,
    require_permissions,
    require_roles,
)

__all__ = [
    "AuthType",
    "UserRole",
    "TokenType",
    "UserInfo",
    "TokenPayload",
    "APIKey",
    "AuthConfig",
    "TokenManager",
    "APIKeyManager",
    "RateLimiter",
    "get_current_user",
    "require_roles",
    "require_permissions",
]
