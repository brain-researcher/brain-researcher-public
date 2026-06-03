"""Shared JWT authentication and API key middleware."""

import os
import json
import hashlib
import secrets
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta
from enum import Enum
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from fastapi import HTTPException, Security, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from pydantic import BaseModel, Field, validator
import redis
from passlib.context import CryptContext
from functools import wraps
import time


class AuthType(str, Enum):
    """Authentication types."""

    JWT = "jwt"
    API_KEY = "api_key"
    BOTH = "both"


class UserRole(str, Enum):
    """User roles."""

    ADMIN = "admin"
    USER = "user"
    SERVICE = "service"
    GUEST = "guest"


class TokenType(str, Enum):
    """Token types."""

    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"


class UserInfo(BaseModel):
    """User information model."""

    user_id: str = Field(..., description="User identifier")
    username: str = Field(..., description="Username")
    email: Optional[str] = Field(None, description="Email address")
    roles: List[UserRole] = Field(default_factory=list, description="User roles")
    permissions: List[str] = Field(default_factory=list, description="User permissions")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=datetime.now, description="Account creation time")
    last_login: Optional[datetime] = Field(None, description="Last login time")
    is_active: bool = Field(True, description="Account active status")


class TokenPayload(BaseModel):
    """JWT token payload model."""

    sub: str = Field(..., description="Subject (user ID)")
    exp: datetime = Field(..., description="Expiration time")
    iat: datetime = Field(default_factory=datetime.now, description="Issued at")
    type: TokenType = Field(..., description="Token type")
    roles: List[str] = Field(default_factory=list, description="User roles")
    permissions: List[str] = Field(default_factory=list, description="Permissions")
    jti: Optional[str] = Field(None, description="JWT ID for revocation")


class APIKey(BaseModel):
    """API key model."""

    key_id: str = Field(..., description="Key identifier")
    key_hash: str = Field(..., description="Hashed key value")
    name: str = Field(..., description="Key name")
    user_id: str = Field(..., description="Owner user ID")
    roles: List[UserRole] = Field(default_factory=list, description="Associated roles")
    permissions: List[str] = Field(default_factory=list, description="Key permissions")
    rate_limit: int = Field(1000, description="Requests per hour")
    expires_at: Optional[datetime] = Field(None, description="Expiration time")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation time")
    last_used: Optional[datetime] = Field(None, description="Last usage time")
    is_active: bool = Field(True, description="Key active status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class AuthConfig:
    """Authentication configuration."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
        api_key_header_name: str = "X-API-Key",
        enable_rate_limiting: bool = True,
        redis_url: Optional[str] = None
    ):
        """Initialize auth configuration.

        Args:
            secret_key: JWT secret key
            algorithm: JWT algorithm
            access_token_expire_minutes: Access token expiration
            refresh_token_expire_days: Refresh token expiration
            api_key_header_name: API key header name
            enable_rate_limiting: Enable rate limiting
            redis_url: Redis URL for token storage
        """
        # JWT_SECRET_KEY is REQUIRED - fail fast if not set to avoid silent validation failures
        self.secret_key = secret_key or os.environ.get("JWT_SECRET_KEY")
        if not self.secret_key:
            raise RuntimeError(
                "JWT_SECRET_KEY environment variable is required. "
                "Set it to the same value as orchestrator to ensure token validation works."
            )
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days
        self.api_key_header_name = api_key_header_name
        self.enable_rate_limiting = enable_rate_limiting

        # Initialize Redis
        self.redis_client = self._init_redis(redis_url)

        # Password context
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def _init_redis(self, redis_url: Optional[str]) -> redis.Redis:
        """Initialize Redis client."""
        try:
            url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = redis.from_url(url, decode_responses=False)
            client.ping()
            return client
        except:
            # Fallback to fakeredis
            try:
                import fakeredis
                return fakeredis.FakeRedis(decode_responses=False)
            except ImportError:
                return None


class TokenManager:
    """JWT token management."""

    def __init__(self, config: AuthConfig):
        """Initialize token manager.

        Args:
            config: Authentication configuration
        """
        self.config = config

    def create_access_token(
        self,
        user_id: str,
        roles: List[UserRole] = None,
        permissions: List[str] = None,
        additional_claims: Dict[str, Any] = None
    ) -> str:
        """Create access token.

        Args:
            user_id: User identifier
            roles: User roles
            permissions: User permissions
            additional_claims: Additional JWT claims

        Returns:
            JWT access token
        """
        expires_at = datetime.utcnow() + timedelta(minutes=self.config.access_token_expire_minutes)

        payload = TokenPayload(
            sub=user_id,
            exp=expires_at,
            type=TokenType.ACCESS,
            roles=[r.value for r in (roles or [])],
            permissions=permissions or [],
            jti=secrets.token_urlsafe(16)
        )

        token_dict = payload.dict()
        if additional_claims:
            token_dict.update(additional_claims)

        token = jwt.encode(token_dict, self.config.secret_key, algorithm=self.config.algorithm)

        # Store token metadata in Redis
        if self.config.redis_client:
            token_key = f"token:{payload.jti}"
            self.config.redis_client.setex(
                token_key,
                self.config.access_token_expire_minutes * 60,
                json.dumps({"user_id": user_id, "type": "access"})
            )

        return token

    def create_refresh_token(self, user_id: str) -> str:
        """Create refresh token.

        Args:
            user_id: User identifier

        Returns:
            JWT refresh token
        """
        expires_at = datetime.utcnow() + timedelta(days=self.config.refresh_token_expire_days)

        payload = TokenPayload(
            sub=user_id,
            exp=expires_at,
            type=TokenType.REFRESH,
            jti=secrets.token_urlsafe(16)
        )

        token = jwt.encode(payload.dict(), self.config.secret_key, algorithm=self.config.algorithm)

        # Store refresh token
        if self.config.redis_client:
            token_key = f"refresh:{payload.jti}"
            self.config.redis_client.setex(
                token_key,
                self.config.refresh_token_expire_days * 86400,
                json.dumps({"user_id": user_id, "type": "refresh"})
            )

        return token

    def verify_token(self, token: str, token_type: TokenType = TokenType.ACCESS) -> TokenPayload:
        """Verify JWT token.

        Args:
            token: JWT token
            token_type: Expected token type

        Returns:
            Token payload

        Raises:
            HTTPException: If token is invalid
        """
        try:
            payload = jwt.decode(token, self.config.secret_key, algorithms=[self.config.algorithm])
            token_payload = TokenPayload(**payload)

            # Verify token type
            if token_payload.type != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token type. Expected {token_type.value}"
                )

            # Check if token is revoked
            if self.config.redis_client and token_payload.jti:
                revoked_key = f"revoked:{token_payload.jti}"
                if self.config.redis_client.exists(revoked_key):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked"
                    )

            return token_payload

        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}"
            )

    def revoke_token(self, jti: str, expiry_seconds: int = 86400):
        """Revoke a token.

        Args:
            jti: JWT ID
            expiry_seconds: Revocation expiry
        """
        if self.config.redis_client:
            revoked_key = f"revoked:{jti}"
            self.config.redis_client.setex(revoked_key, expiry_seconds, "1")


class APIKeyManager:
    """API key management."""

    def __init__(self, config: AuthConfig):
        """Initialize API key manager.

        Args:
            config: Authentication configuration
        """
        self.config = config

    def generate_api_key(
        self,
        user_id: str,
        name: str,
        roles: List[UserRole] = None,
        permissions: List[str] = None,
        expires_in_days: Optional[int] = None
    ) -> tuple[str, APIKey]:
        """Generate new API key.

        Args:
            user_id: User identifier
            name: Key name
            roles: Associated roles
            permissions: Key permissions
            expires_in_days: Expiration in days

        Returns:
            Tuple of (raw_key, api_key_model)
        """
        # Generate key
        raw_key = f"br_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = secrets.token_urlsafe(16)

        # Create API key model
        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            user_id=user_id,
            roles=roles or [],
            permissions=permissions or [],
            expires_at=datetime.now() + timedelta(days=expires_in_days) if expires_in_days else None
        )

        # Store in Redis
        if self.config.redis_client:
            key_data = json.dumps(api_key.dict(), default=str)
            self.config.redis_client.hset("api_keys", key_hash, key_data)

        return raw_key, api_key

    def verify_api_key(self, api_key: str) -> APIKey:
        """Verify API key.

        Args:
            api_key: Raw API key

        Returns:
            API key model

        Raises:
            HTTPException: If key is invalid
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        if not self.config.redis_client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key verification unavailable"
            )

        # Get key from Redis
        key_data = self.config.redis_client.hget("api_keys", key_hash)

        if not key_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key"
            )

        # Parse key data
        try:
            data = json.loads(key_data)
            api_key_model = APIKey(**data)
        except:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key format"
            )

        # Check if key is active
        if not api_key_model.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key is inactive"
            )

        # Check expiration
        if api_key_model.expires_at and datetime.now() > api_key_model.expires_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired"
            )

        # Update last used
        api_key_model.last_used = datetime.now()
        self.config.redis_client.hset(
            "api_keys",
            key_hash,
            json.dumps(api_key_model.dict(), default=str)
        )

        return api_key_model

    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke API key.

        Args:
            key_id: Key identifier

        Returns:
            True if revoked
        """
        if not self.config.redis_client:
            return False

        # Find and deactivate key
        for key_hash in self.config.redis_client.hkeys("api_keys"):
            key_data = self.config.redis_client.hget("api_keys", key_hash)
            if key_data:
                data = json.loads(key_data)
                if data.get("key_id") == key_id:
                    data["is_active"] = False
                    self.config.redis_client.hset(
                        "api_keys",
                        key_hash,
                        json.dumps(data, default=str)
                    )
                    return True

        return False


class RateLimiter:
    """Rate limiting implementation."""

    def __init__(self, config: AuthConfig):
        """Initialize rate limiter.

        Args:
            config: Authentication configuration
        """
        self.config = config
        self.enabled = config.enable_rate_limiting and config.redis_client is not None

    def check_rate_limit(
        self,
        identifier: str,
        limit: int = 100,
        window_seconds: int = 3600
    ) -> tuple[bool, Dict[str, int]]:
        """Check rate limit.

        Args:
            identifier: User or API key identifier
            limit: Request limit
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed, rate_info)
        """
        if not self.enabled:
            return True, {"limit": limit, "remaining": limit, "reset": 0}

        now = int(time.time())
        window_start = now - window_seconds
        key = f"rate_limit:{identifier}"

        # Clean old entries
        self.config.redis_client.zremrangebyscore(key, 0, window_start)

        # Count requests in window
        request_count = self.config.redis_client.zcard(key)

        if request_count >= limit:
            # Rate limit exceeded
            reset_time = int(self.config.redis_client.zrange(key, 0, 0, withscores=True)[0][1]) + window_seconds

            return False, {
                "limit": limit,
                "remaining": 0,
                "reset": reset_time
            }

        # Add current request
        self.config.redis_client.zadd(key, {str(now): now})
        self.config.redis_client.expire(key, window_seconds)

        return True, {
            "limit": limit,
            "remaining": limit - request_count - 1,
            "reset": now + window_seconds
        }


# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Global auth config
_auth_config = AuthConfig()
_token_manager = TokenManager(_auth_config)
_api_key_manager = APIKeyManager(_auth_config)
_rate_limiter = RateLimiter(_auth_config)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header)
) -> UserInfo:
    """Get current authenticated user.

    Args:
        credentials: Bearer token credentials
        api_key: API key from header

    Returns:
        User information

    Raises:
        HTTPException: If authentication fails
    """
    # Try JWT token first
    if credentials and credentials.credentials:
        try:
            payload = _token_manager.verify_token(credentials.credentials)

            # Check rate limit
            allowed, rate_info = _rate_limiter.check_rate_limit(
                f"user:{payload.sub}",
                limit=1000
            )

            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(rate_info["limit"]),
                        "X-RateLimit-Remaining": str(rate_info["remaining"]),
                        "X-RateLimit-Reset": str(rate_info["reset"])
                    }
                )

            return UserInfo(
                user_id=payload.sub,
                username=payload.sub,
                roles=[UserRole(r) for r in payload.roles],
                permissions=payload.permissions
            )
        except HTTPException:
            raise
        except Exception as e:
            pass  # Try API key next

    # Try API key
    if api_key:
        try:
            api_key_model = _api_key_manager.verify_api_key(api_key)

            # Check rate limit
            allowed, rate_info = _rate_limiter.check_rate_limit(
                f"api_key:{api_key_model.key_id}",
                limit=api_key_model.rate_limit
            )

            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(rate_info["limit"]),
                        "X-RateLimit-Remaining": str(rate_info["remaining"]),
                        "X-RateLimit-Reset": str(rate_info["reset"])
                    }
                )

            return UserInfo(
                user_id=api_key_model.user_id,
                username=f"api_key_{api_key_model.name}",
                roles=api_key_model.roles,
                permissions=api_key_model.permissions,
                metadata={"api_key_id": api_key_model.key_id}
            )
        except HTTPException:
            raise
        except Exception as e:
            pass

    # No valid authentication
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"}
    )


def require_roles(*required_roles: UserRole):
    """Decorator to require specific roles.

    Args:
        *required_roles: Required user roles

    Returns:
        Dependency function
    """
    async def role_checker(current_user: UserInfo = Depends(get_current_user)) -> UserInfo:
        if not any(role in current_user.roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {[r.value for r in required_roles]}"
            )
        return current_user

    return role_checker


def require_permissions(*required_permissions: str):
    """Decorator to require specific permissions.

    Args:
        *required_permissions: Required permissions

    Returns:
        Dependency function
    """
    async def permission_checker(current_user: UserInfo = Depends(get_current_user)) -> UserInfo:
        if not all(perm in current_user.permissions for perm in required_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {list(required_permissions)}"
            )
        return current_user

    return permission_checker


# Export components
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
    "require_permissions"
]