"""
Rate limiting implementation for BR-KG API.
Implements KG-010: Rate Limiting with token bucket algorithm.
"""

import time
import json
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import logging
from functools import wraps
from flask import request, jsonify, Response

logger = logging.getLogger(__name__)


class RateLimitType(Enum):
    """Types of rate limiting."""
    GLOBAL = "global"  # Global rate limit for all users
    PER_USER = "per_user"  # Per authenticated user
    PER_IP = "per_ip"  # Per IP address
    PER_KEY = "per_key"  # Per API key


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10  # Allow burst of requests
    enable_global: bool = True
    enable_per_user: bool = True
    enable_per_ip: bool = True
    redis_prefix: str = "br_kg:ratelimit"
    ttl_seconds: int = 3600  # 1 hour TTL for Redis keys


@dataclass
class RateLimitStatus:
    """Status of rate limit for a client."""
    allowed: bool
    limit: int
    remaining: int
    reset_time: int  # Unix timestamp
    retry_after: Optional[int] = None  # Seconds to wait if rate limited


class TokenBucket:
    """Token bucket algorithm implementation."""

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        initial_tokens: Optional[int] = None
    ):
        """
        Initialize token bucket.

        Args:
            capacity: Maximum number of tokens
            refill_rate: Tokens added per second
            initial_tokens: Initial token count (defaults to capacity)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = initial_tokens if initial_tokens is not None else capacity
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if not enough tokens
        """
        self._refill()

        if self.tokens >= tokens:
            self.tokens = max(0, self.tokens - tokens)  # Ensure tokens doesn't go negative
            return True
        return False

    def _refill(self):
        """Refill bucket based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

        # Round tokens to avoid floating point precision issues
        if abs(self.tokens - round(self.tokens)) < 0.001:
            self.tokens = round(self.tokens)

    def get_wait_time(self, tokens: int = 1) -> float:
        """
        Get time to wait for tokens to be available.

        Args:
            tokens: Number of tokens needed

        Returns:
            Seconds to wait (0 if tokens available now)
        """
        self._refill()

        if self.tokens >= tokens:
            return 0.0

        tokens_needed = tokens - self.tokens
        return tokens_needed / self.refill_rate

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "capacity": self.capacity,
            "refill_rate": self.refill_rate,
            "tokens": self.tokens,
            "last_refill": self.last_refill
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenBucket":
        """Create from dictionary."""
        bucket = cls(
            capacity=data["capacity"],
            refill_rate=data["refill_rate"],
            initial_tokens=data["tokens"]
        )
        bucket.last_refill = data["last_refill"]
        return bucket


class RateLimiter:
    """Rate limiter with Redis backend."""

    def __init__(
        self,
        config: Optional[RateLimitConfig] = None,
        redis_client=None
    ):
        """
        Initialize rate limiter.

        Args:
            config: Rate limit configuration
            redis_client: Redis client (optional, uses fakeredis if None)
        """
        self.config = config or RateLimitConfig()
        self.redis = redis_client

        if self.redis is None:
            try:
                import redis
                import os
                redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
                self.redis = redis.from_url(redis_url)
                # Test connection
                self.redis.ping()
                logger.info(f"Connected to Redis at {redis_url}")
            except Exception as e:
                logger.warning(f"Redis not available, using in-memory rate limiting: {e}")
                import fakeredis
                self.redis = fakeredis.FakeRedis()

        # In-memory fallback for non-Redis environments
        self.memory_buckets: Dict[str, TokenBucket] = {}

    def _get_client_id(
        self,
        request_obj=None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> str:
        """
        Get client identifier for rate limiting.

        Args:
            request_obj: Flask request object
            user_id: User ID if authenticated
            api_key: API key if provided

        Returns:
            Client identifier string
        """
        if user_id:
            return f"user:{user_id}"
        elif api_key:
            # Hash API key for privacy
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            return f"key:{key_hash}"
        elif request_obj:
            # Use IP address as fallback
            ip = request_obj.environ.get('HTTP_X_FORWARDED_FOR', request_obj.remote_addr)
            return f"ip:{ip}"
        else:
            return "anonymous"

    def _get_redis_key(self, client_id: str, limit_type: str) -> str:
        """Get Redis key for client and limit type."""
        return f"{self.config.redis_prefix}:{limit_type}:{client_id}"

    def _get_bucket(
        self,
        client_id: str,
        limit_type: str = "minute"
    ) -> TokenBucket:
        """
        Get or create token bucket for client.

        Args:
            client_id: Client identifier
            limit_type: Type of limit (minute/hour)

        Returns:
            Token bucket for client
        """
        redis_key = self._get_redis_key(client_id, limit_type)

        # Try to get from Redis
        try:
            data = self.redis.get(redis_key)
            if data:
                bucket_dict = json.loads(data)
                return TokenBucket.from_dict(bucket_dict)
        except Exception as e:
            logger.warning(f"Error reading from Redis: {e}")

        # Create new bucket based on limit type
        if limit_type == "minute":
            capacity = self.config.requests_per_minute
            refill_rate = self.config.requests_per_minute / 60.0
        else:  # hour
            capacity = self.config.requests_per_hour
            refill_rate = self.config.requests_per_hour / 3600.0

        # Add burst allowance
        capacity = min(capacity + self.config.burst_size, capacity * 1.5)

        return TokenBucket(capacity=capacity, refill_rate=refill_rate)

    def _save_bucket(
        self,
        client_id: str,
        bucket: TokenBucket,
        limit_type: str = "minute"
    ):
        """Save token bucket to Redis."""
        redis_key = self._get_redis_key(client_id, limit_type)

        try:
            self.redis.setex(
                redis_key,
                self.config.ttl_seconds,
                json.dumps(bucket.to_dict())
            )
        except Exception as e:
            logger.warning(f"Error saving to Redis: {e}")
            # Fall back to in-memory
            self.memory_buckets[redis_key] = bucket

    def check_limit(
        self,
        request_obj=None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        tokens: int = 1
    ) -> RateLimitStatus:
        """
        Check if request is within rate limit.

        Args:
            request_obj: Flask request object
            user_id: User ID if authenticated
            api_key: API key if provided
            tokens: Number of tokens to consume

        Returns:
            RateLimitStatus with result
        """
        client_id = self._get_client_id(request_obj, user_id, api_key)

        # Check minute limit
        minute_bucket = self._get_bucket(client_id, "minute")
        minute_allowed = minute_bucket.consume(tokens)

        if not minute_allowed:
            wait_time = minute_bucket.get_wait_time(tokens)
            return RateLimitStatus(
                allowed=False,
                limit=self.config.requests_per_minute,
                remaining=int(minute_bucket.tokens),
                reset_time=int(time.time() + wait_time),
                retry_after=max(1, int(wait_time))  # Ensure at least 1 second retry
            )

        # Check hour limit
        hour_bucket = self._get_bucket(client_id, "hour")
        hour_allowed = hour_bucket.consume(tokens)

        if not hour_allowed:
            # Restore minute tokens since hour limit failed
            minute_bucket.tokens += tokens
            self._save_bucket(client_id, minute_bucket, "minute")

            wait_time = int(hour_bucket.get_wait_time(tokens))
            return RateLimitStatus(
                allowed=False,
                limit=self.config.requests_per_hour,
                remaining=int(hour_bucket.tokens),
                reset_time=int(time.time() + wait_time),
                retry_after=wait_time
            )

        # Save updated buckets
        self._save_bucket(client_id, minute_bucket, "minute")
        self._save_bucket(client_id, hour_bucket, "hour")

        # Return success with minute limit info (more restrictive)
        return RateLimitStatus(
            allowed=True,
            limit=self.config.requests_per_minute,
            remaining=int(minute_bucket.tokens),
            reset_time=int(time.time() + 60)
        )

    def reset_limit(
        self,
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Reset rate limit for a client.

        Args:
            client_id: Direct client ID
            user_id: User ID to reset
            api_key: API key to reset
        """
        if not client_id:
            client_id = self._get_client_id(None, user_id, api_key)

        # Delete Redis keys
        for limit_type in ["minute", "hour"]:
            redis_key = self._get_redis_key(client_id, limit_type)
            try:
                self.redis.delete(redis_key)
            except Exception as e:
                logger.warning(f"Error deleting from Redis: {e}")

            # Also clear from memory
            if redis_key in self.memory_buckets:
                del self.memory_buckets[redis_key]

    def get_status(
        self,
        request_obj=None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get current rate limit status without consuming tokens.

        Args:
            request_obj: Flask request object
            user_id: User ID if authenticated
            api_key: API key if provided

        Returns:
            Status dictionary
        """
        client_id = self._get_client_id(request_obj, user_id, api_key)

        minute_bucket = self._get_bucket(client_id, "minute")
        hour_bucket = self._get_bucket(client_id, "hour")

        # Refill to get current state
        minute_bucket._refill()
        hour_bucket._refill()

        return {
            "client_id": client_id,
            "limits": {
                "per_minute": {
                    "limit": self.config.requests_per_minute,
                    "remaining": int(minute_bucket.tokens),
                    "reset_time": int(time.time() + 60)
                },
                "per_hour": {
                    "limit": self.config.requests_per_hour,
                    "remaining": int(hour_bucket.tokens),
                    "reset_time": int(time.time() + 3600)
                }
            }
        }


# Flask decorator for rate limiting
def rate_limit(
    requests_per_minute: Optional[int] = None,
    requests_per_hour: Optional[int] = None,
    get_user_id=None,
    get_api_key=None
):
    """
    Decorator for rate limiting Flask routes.

    Args:
        requests_per_minute: Override default requests per minute
        requests_per_hour: Override default requests per hour
        get_user_id: Function to extract user ID from request
        get_api_key: Function to extract API key from request

    Returns:
        Decorated function
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get or create rate limiter
            if not hasattr(decorated_function, '_rate_limiter'):
                config = RateLimitConfig()
                if requests_per_minute:
                    config.requests_per_minute = requests_per_minute
                if requests_per_hour:
                    config.requests_per_hour = requests_per_hour
                decorated_function._rate_limiter = RateLimiter(config)

            limiter = decorated_function._rate_limiter

            # Extract user ID and API key if functions provided
            user_id = get_user_id() if get_user_id else None
            api_key = get_api_key() if get_api_key else None

            # Check rate limit
            status = limiter.check_limit(
                request_obj=request,
                user_id=user_id,
                api_key=api_key
            )

            # Add rate limit headers
            def add_headers(response):
                response.headers['X-RateLimit-Limit'] = str(status.limit)
                response.headers['X-RateLimit-Remaining'] = str(status.remaining)
                response.headers['X-RateLimit-Reset'] = str(status.reset_time)

                if not status.allowed:
                    response.headers['Retry-After'] = str(status.retry_after)

                return response

            # Return 429 if rate limited
            if not status.allowed:
                response = jsonify({
                    "error": "Rate limit exceeded",
                    "retry_after": status.retry_after,
                    "reset_time": status.reset_time
                })
                response.status_code = 429
                return add_headers(response)

            # Call original function
            result = f(*args, **kwargs)

            # Add headers to response
            if isinstance(result, tuple):
                # Handle (data, status_code) return
                response = jsonify(result[0]) if not isinstance(result[0], Response) else result[0]
                response.status_code = result[1] if len(result) > 1 else 200
                return add_headers(response)
            elif isinstance(result, Response):
                return add_headers(result)
            else:
                response = jsonify(result)
                return add_headers(response)

        return decorated_function
    return decorator


# Middleware for global rate limiting
class RateLimitMiddleware:
    """Flask middleware for global rate limiting."""

    def __init__(self, app=None, config: Optional[RateLimitConfig] = None):
        """
        Initialize middleware.

        Args:
            app: Flask application
            config: Rate limit configuration
        """
        self.app = app
        self.config = config or RateLimitConfig()
        self.limiter = RateLimiter(self.config)

        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize Flask application."""
        app.before_request(self.before_request)
        app.after_request(self.after_request)

    def before_request(self):
        """Check rate limit before request."""
        # Skip rate limiting for static files and health checks
        if request.path.startswith('/static') or request.path == '/health':
            return

        # Extract user ID and API key from headers or auth
        user_id = None
        api_key = request.headers.get('X-API-Key')

        # Check for JWT token (placeholder for KG-009)
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            # TODO: Decode JWT and extract user_id
            pass

        # Check rate limit
        status = self.limiter.check_limit(
            request_obj=request,
            user_id=user_id,
            api_key=api_key
        )

        # Store status for after_request
        request.rate_limit_status = status

        # Return 429 if rate limited
        if not status.allowed:
            response = jsonify({
                "error": "Rate limit exceeded",
                "retry_after": status.retry_after,
                "reset_time": status.reset_time
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(status.retry_after)
            return response

    def after_request(self, response):
        """Add rate limit headers after request."""
        if hasattr(request, 'rate_limit_status'):
            status = request.rate_limit_status
            response.headers['X-RateLimit-Limit'] = str(status.limit)
            response.headers['X-RateLimit-Remaining'] = str(status.remaining)
            response.headers['X-RateLimit-Reset'] = str(status.reset_time)

        return response


# API endpoints for rate limit management
def create_rate_limit_endpoints(app):
    """Add rate limit management endpoints to Flask app."""

    # Check if endpoints already registered
    if 'get_rate_limit_status' in app.view_functions:
        return  # Already registered, skip

    @app.route("/api/rate-limit/status", methods=["GET"])
    def get_rate_limit_status():
        """Get current rate limit status."""
        # Get limiter from app context
        limiter = getattr(app, '_rate_limiter', None)
        if not limiter:
            limiter = RateLimiter()
            app._rate_limiter = limiter

        # Get status
        api_key = request.headers.get('X-API-Key')
        status = limiter.get_status(
            request_obj=request,
            api_key=api_key
        )

        return jsonify(status)

    @app.route("/api/rate-limit/reset", methods=["POST"])
    @rate_limit(requests_per_minute=5)  # Limit reset requests
    def reset_rate_limit():
        """Reset rate limit (admin only)."""
        # TODO: Check admin authorization (KG-009)

        data = request.get_json()
        client_id = data.get("client_id")

        if not client_id:
            return jsonify({"error": "client_id required"}), 400

        # Get limiter
        limiter = getattr(app, '_rate_limiter', None)
        if not limiter:
            limiter = RateLimiter()
            app._rate_limiter = limiter

        # Reset limit
        limiter.reset_limit(client_id=client_id)

        return jsonify({"message": f"Rate limit reset for {client_id}"})