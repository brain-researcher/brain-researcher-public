"""
Rate Limiter for API Gateway.

Implements sophisticated rate limiting with multiple algorithms and strategies:
- Token bucket algorithm
- Fixed window counter
- Sliding window log
- Sliding window counter
- Distributed rate limiting with Redis

Features:
- Multiple rate limiting algorithms
- Per-user, per-API-key, and global rate limiting
- Burst handling with token bucket
- Rate limit exemptions and overrides
- Detailed rate limit headers
- Rate limit analytics and monitoring
"""

import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import redis
from pydantic import BaseModel, Field
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)


_SCRIPT_FAILURE_LOGGED: Set[str] = set()


def _log_script_failure(context: str, error: Exception) -> None:
    """Log Redis scripting failures only once per context to reduce noise."""
    if context not in _SCRIPT_FAILURE_LOGGED:
        logger.warning(
            "Redis scripting unavailable for %s; rate limiting fails open (%s)",
            context,
            error,
        )
        _SCRIPT_FAILURE_LOGGED.add(context)


class RateLimitAlgorithm(str, Enum):
    """Rate limiting algorithm types."""

    TOKEN_BUCKET = "token_bucket"
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW_LOG = "sliding_window_log"
    SLIDING_WINDOW_COUNTER = "sliding_window_counter"


class RateLimitScope(str, Enum):
    """Rate limiting scope levels."""

    GLOBAL = "global"
    PER_USER = "per_user"
    PER_API_KEY = "per_api_key"
    PER_IP = "per_ip"
    PER_SERVICE = "per_service"
    PER_ENDPOINT = "per_endpoint"


@dataclass
class RateLimitRule:
    """Rate limiting rule configuration."""

    name: str
    algorithm: RateLimitAlgorithm
    scope: RateLimitScope
    limit: int  # Number of requests
    window_seconds: int  # Time window
    burst_multiplier: float = 1.5  # For token bucket burst handling
    enabled: bool = True
    priority: int = 0  # Higher priority rules are checked first
    exemptions: List[str] = None  # Exempted users/keys/IPs

    def __post_init__(self):
        if self.exemptions is None:
            self.exemptions = []


class RateLimitInfo(BaseModel):
    """Rate limit information returned to clients."""

    limit: int = Field(..., description="Request limit")
    remaining: int = Field(..., description="Remaining requests")
    reset_time: int = Field(..., description="Reset time (Unix timestamp)")
    retry_after: Optional[int] = Field(None, description="Retry after seconds")
    window_seconds: int = Field(..., description="Time window in seconds")
    algorithm: str = Field(..., description="Rate limiting algorithm")


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        rate_limit_info: RateLimitInfo,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(message)
        self.rate_limit_info = rate_limit_info
        self.headers = headers or {}
        self.headers.update(
            {
                "X-RateLimit-Limit": str(rate_limit_info.limit),
                "X-RateLimit-Remaining": str(rate_limit_info.remaining),
                "X-RateLimit-Reset": str(rate_limit_info.reset_time),
                "X-RateLimit-Window": str(rate_limit_info.window_seconds),
                "X-RateLimit-Algorithm": rate_limit_info.algorithm,
            }
        )

        if rate_limit_info.retry_after:
            self.headers["Retry-After"] = str(rate_limit_info.retry_after)


def _fail_open_info(limit: int, window_seconds: int, algorithm: str) -> RateLimitInfo:
    """Construct a permissive rate info object when Redis scripts fail."""
    now = int(time.time())
    window = max(1, window_seconds)
    return RateLimitInfo(
        limit=limit,
        remaining=limit,
        reset_time=now + window,
        window_seconds=window,
        algorithm=algorithm,
    )


class TokenBucket:
    """Token bucket rate limiter implementation."""

    def __init__(
        self, redis_client: redis.Redis, key: str, capacity: int, refill_rate: float
    ):
        """Initialize token bucket.

        Args:
            redis_client: Redis client
            key: Bucket key
            capacity: Maximum tokens
            refill_rate: Tokens per second
        """
        self.redis = redis_client
        self.key = key
        self.capacity = capacity
        self.refill_rate = refill_rate

    async def consume(self, tokens: int = 1) -> Tuple[bool, RateLimitInfo]:
        """Consume tokens from bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            Tuple of (allowed, rate_limit_info)
        """
        now = time.time()

        # Lua script for atomic token bucket operations
        lua_script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local tokens_requested = tonumber(ARGV[3])
        local now = tonumber(ARGV[4])

        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1]) or capacity
        local last_refill = tonumber(bucket[2]) or now

        -- Calculate tokens to add based on time elapsed
        local time_passed = math.max(0, now - last_refill)
        local tokens_to_add = time_passed * refill_rate
        tokens = math.min(capacity, tokens + tokens_to_add)

        -- Check if we can consume the requested tokens
        local allowed = tokens >= tokens_requested
        local remaining_tokens = tokens

        if allowed then
            remaining_tokens = tokens - tokens_requested
        end

        -- Update bucket state
        redis.call('HMSET', key, 'tokens', remaining_tokens, 'last_refill', now)
        redis.call('EXPIRE', key, 3600)  -- 1 hour expiry

        return {allowed and 1 or 0, remaining_tokens}
        """

        try:
            result = self.redis.eval(
                lua_script, 1, self.key, self.capacity, self.refill_rate, tokens, now
            )

            allowed = bool(result[0])
            remaining_tokens = int(result[1])

            # Calculate reset time (when bucket will be full)
            if remaining_tokens < self.capacity:
                tokens_needed = self.capacity - remaining_tokens
                reset_time = int(now + (tokens_needed / self.refill_rate))
            else:
                reset_time = int(now)

            rate_info = RateLimitInfo(
                limit=self.capacity,
                remaining=remaining_tokens,
                reset_time=reset_time,
                window_seconds=int(self.capacity / self.refill_rate),
                algorithm="token_bucket",
            )

            if not allowed:
                rate_info.retry_after = max(1, int(tokens / self.refill_rate))

            return allowed, rate_info

        except ResponseError as exc:
            _log_script_failure(f"token_bucket:{self.key}", exc)
            window = int(self.capacity / self.refill_rate) if self.refill_rate else 3600
            return True, _fail_open_info(self.capacity, window or 3600, "token_bucket")
        except Exception as e:
            logger.error(f"Token bucket error for {self.key}: {e}")
            window = int(self.capacity / self.refill_rate) if self.refill_rate else 3600
            return True, _fail_open_info(self.capacity, window or 3600, "token_bucket")


class SlidingWindowCounter:
    """Sliding window counter rate limiter."""

    def __init__(
        self, redis_client: redis.Redis, key: str, limit: int, window_seconds: int
    ):
        """Initialize sliding window counter.

        Args:
            redis_client: Redis client
            key: Counter key
            limit: Request limit
            window_seconds: Time window
        """
        self.redis = redis_client
        self.key = key
        self.limit = limit
        self.window_seconds = window_seconds

    async def check_limit(self) -> Tuple[bool, RateLimitInfo]:
        """Check if request is within rate limit.

        Returns:
            Tuple of (allowed, rate_limit_info)
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Lua script for atomic sliding window operations
        lua_script = """
        local key = KEYS[1]
        local window_start = tonumber(ARGV[1])
        local now = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])

        -- Remove expired entries
        redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

        -- Count current requests
        local current_count = redis.call('ZCARD', key)

        local allowed = current_count < limit
        local remaining = math.max(0, limit - current_count)

        if allowed then
            -- Add current request
            redis.call('ZADD', key, now, now .. ':' .. math.random())
            remaining = remaining - 1
        end

        -- Set expiry
        redis.call('EXPIRE', key, math.ceil(ARGV[4]))

        return {allowed and 1 or 0, current_count, remaining}
        """

        try:
            result = self.redis.eval(
                lua_script,
                1,
                self.key,
                window_start,
                now,
                self.limit,
                self.window_seconds,
            )

            allowed = bool(result[0])
            current_count = int(result[1])
            remaining = int(result[2])

            # Calculate reset time
            reset_time = int(now + self.window_seconds)

            rate_info = RateLimitInfo(
                limit=self.limit,
                remaining=remaining,
                reset_time=reset_time,
                window_seconds=self.window_seconds,
                algorithm="sliding_window_counter",
            )

            if not allowed:
                # Estimate retry time based on oldest request
                oldest_requests = self.redis.zrange(self.key, 0, 0, withscores=True)
                if oldest_requests:
                    oldest_time = oldest_requests[0][1]
                    rate_info.retry_after = max(
                        1, int(oldest_time + self.window_seconds - now)
                    )

            return allowed, rate_info

        except ResponseError as exc:
            _log_script_failure(f"sliding_window:{self.key}", exc)
            return True, _fail_open_info(
                self.limit, self.window_seconds, "sliding_window_counter"
            )
        except Exception as e:
            logger.error(f"Sliding window counter error for {self.key}: {e}")
            return True, _fail_open_info(
                self.limit, self.window_seconds, "sliding_window_counter"
            )


class FixedWindowCounter:
    """Fixed window counter rate limiter."""

    def __init__(
        self, redis_client: redis.Redis, key: str, limit: int, window_seconds: int
    ):
        """Initialize fixed window counter.

        Args:
            redis_client: Redis client
            key: Counter key
            limit: Request limit
            window_seconds: Time window
        """
        self.redis = redis_client
        self.key = key
        self.limit = limit
        self.window_seconds = window_seconds

    async def check_limit(self) -> Tuple[bool, RateLimitInfo]:
        """Check if request is within rate limit.

        Returns:
            Tuple of (allowed, rate_limit_info)
        """
        now = time.time()
        window_key = f"{self.key}:{int(now // self.window_seconds)}"

        try:
            # Atomic increment
            pipeline = self.redis.pipeline()
            pipeline.incr(window_key)
            pipeline.expire(window_key, self.window_seconds)
            results = pipeline.execute()

            current_count = results[0]
            allowed = current_count <= self.limit
            remaining = max(0, self.limit - current_count)

            # Calculate reset time (start of next window)
            current_window = int(now // self.window_seconds)
            reset_time = (current_window + 1) * self.window_seconds

            rate_info = RateLimitInfo(
                limit=self.limit,
                remaining=remaining,
                reset_time=int(reset_time),
                window_seconds=self.window_seconds,
                algorithm="fixed_window",
            )

            if not allowed:
                rate_info.retry_after = max(1, int(reset_time - now))

            return allowed, rate_info

        except Exception as e:
            logger.error(f"Fixed window counter error for {window_key}: {e}")
            # Fail open
            return True, RateLimitInfo(
                limit=self.limit,
                remaining=self.limit,
                reset_time=int(now + self.window_seconds),
                window_seconds=self.window_seconds,
                algorithm="fixed_window",
            )


class RateLimiter:
    """Main rate limiter class."""

    def __init__(
        self,
        redis_client: redis.Redis,
        default_rules: Optional[List[RateLimitRule]] = None,
    ):
        """Initialize rate limiter.

        Args:
            redis_client: Redis client
            default_rules: Default rate limiting rules
        """
        self.redis = redis_client
        self.rules = default_rules or self._get_default_rules()

        # Sort rules by priority (higher priority first)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def _get_default_rules(self) -> List[RateLimitRule]:
        """Get default rate limiting rules."""
        return [
            # Global rate limiting
            RateLimitRule(
                name="global_burst",
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
                scope=RateLimitScope.GLOBAL,
                limit=10000,  # 10k requests
                window_seconds=3600,  # per hour
                priority=1,
            ),
            # Per-user limits
            RateLimitRule(
                name="user_standard",
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW_COUNTER,
                scope=RateLimitScope.PER_USER,
                limit=1000,  # 1k requests
                window_seconds=3600,  # per hour
                priority=2,
            ),
            # Per-API-key limits
            RateLimitRule(
                name="api_key_standard",
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
                scope=RateLimitScope.PER_API_KEY,
                limit=5000,  # 5k requests
                window_seconds=3600,  # per hour
                burst_multiplier=2.0,
                priority=2,
            ),
            # Per-IP limits (DDoS protection)
            RateLimitRule(
                name="ip_protection",
                algorithm=RateLimitAlgorithm.FIXED_WINDOW,
                scope=RateLimitScope.PER_IP,
                limit=100,  # 100 requests
                window_seconds=60,  # per minute
                priority=3,
            ),
            # Per-service limits
            RateLimitRule(
                name="service_protection",
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW_COUNTER,
                scope=RateLimitScope.PER_SERVICE,
                limit=10000,  # 10k requests
                window_seconds=3600,  # per hour
                priority=2,
            ),
        ]

    async def check_rate_limit(
        self,
        identifier: str,
        scope: RateLimitScope = RateLimitScope.PER_USER,
        service: Optional[str] = None,
        endpoint: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> RateLimitInfo:
        """Check rate limit for a request.

        Args:
            identifier: User ID, API key, or other identifier
            scope: Rate limiting scope
            service: Service name (for per-service limits)
            endpoint: Endpoint path (for per-endpoint limits)
            ip_address: Client IP address

        Returns:
            Rate limit information

        Raises:
            RateLimitExceeded: If rate limit is exceeded
        """
        # Find applicable rules for this request
        applicable_rules = self._find_applicable_rules(scope, service, endpoint)

        for rule in applicable_rules:
            if not rule.enabled:
                continue

            # Check exemptions
            if identifier in rule.exemptions:
                continue

            # Generate rate limit key
            key = self._generate_key(rule, identifier, service, endpoint, ip_address)

            # Apply rate limiting based on algorithm
            allowed, rate_info = await self._apply_rate_limit(rule, key)

            # If rate limit exceeded, raise exception
            if not allowed:
                logger.warning(
                    f"Rate limit exceeded for {identifier} on rule {rule.name}: "
                    f"{rate_info.remaining}/{rate_info.limit}"
                )

                raise RateLimitExceeded(
                    f"Rate limit exceeded: {rule.limit} requests per {rule.window_seconds} seconds",
                    rate_info,
                )

        # If we get here, all rate limits passed
        # Return the most restrictive rate limit info
        if applicable_rules:
            most_restrictive_rule = min(
                applicable_rules, key=lambda r: r.limit / r.window_seconds
            )
            key = self._generate_key(
                most_restrictive_rule, identifier, service, endpoint, ip_address
            )
            _, rate_info = await self._apply_rate_limit(
                most_restrictive_rule, key, consume=False
            )
            return rate_info

        # No applicable rules, return permissive rate info
        return RateLimitInfo(
            limit=float("inf"),
            remaining=float("inf"),
            reset_time=int(time.time() + 3600),
            window_seconds=3600,
            algorithm="none",
        )

    def _find_applicable_rules(
        self,
        scope: RateLimitScope,
        service: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> List[RateLimitRule]:
        """Find rules applicable to the current request."""
        applicable_rules = []

        for rule in self.rules:
            # Check scope match
            if rule.scope == scope:
                applicable_rules.append(rule)
            elif rule.scope == RateLimitScope.GLOBAL:
                applicable_rules.append(rule)
            elif rule.scope == RateLimitScope.PER_SERVICE and service:
                applicable_rules.append(rule)
            elif rule.scope == RateLimitScope.PER_ENDPOINT and endpoint:
                applicable_rules.append(rule)

        return applicable_rules

    def _generate_key(
        self,
        rule: RateLimitRule,
        identifier: str,
        service: Optional[str] = None,
        endpoint: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> str:
        """Generate Redis key for rate limiting."""
        key_parts = ["ratelimit", rule.name]

        if rule.scope == RateLimitScope.GLOBAL:
            key_parts.append("global")
        elif rule.scope == RateLimitScope.PER_USER:
            key_parts.extend(["user", identifier])
        elif rule.scope == RateLimitScope.PER_API_KEY:
            key_parts.extend(["apikey", identifier])
        elif rule.scope == RateLimitScope.PER_IP:
            key_parts.extend(["ip", ip_address or identifier])
        elif rule.scope == RateLimitScope.PER_SERVICE:
            key_parts.extend(["service", service or "unknown"])
        elif rule.scope == RateLimitScope.PER_ENDPOINT:
            key_parts.extend(["endpoint", endpoint or "unknown"])

        return ":".join(str(part) for part in key_parts)

    async def _apply_rate_limit(
        self, rule: RateLimitRule, key: str, consume: bool = True
    ) -> Tuple[bool, RateLimitInfo]:
        """Apply rate limiting based on algorithm."""

        if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            # Token bucket with burst capability
            capacity = int(rule.limit * rule.burst_multiplier)
            refill_rate = rule.limit / rule.window_seconds

            bucket = TokenBucket(self.redis, key, capacity, refill_rate)
            return await bucket.consume(1 if consume else 0)

        elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW_COUNTER:
            counter = SlidingWindowCounter(
                self.redis, key, rule.limit, rule.window_seconds
            )
            return await counter.check_limit()

        elif rule.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
            counter = FixedWindowCounter(
                self.redis, key, rule.limit, rule.window_seconds
            )
            return await counter.check_limit()

        else:
            # Fallback to sliding window
            counter = SlidingWindowCounter(
                self.redis, key, rule.limit, rule.window_seconds
            )
            return await counter.check_limit()

    def add_rule(self, rule: RateLimitRule):
        """Add a new rate limiting rule."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a rate limiting rule."""
        for i, rule in enumerate(self.rules):
            if rule.name == rule_name:
                del self.rules[i]
                return True
        return False

    def get_rule(self, rule_name: str) -> Optional[RateLimitRule]:
        """Get a rate limiting rule by name."""
        for rule in self.rules:
            if rule.name == rule_name:
                return rule
        return None

    async def get_rate_limit_stats(
        self, identifier: str, scope: RateLimitScope
    ) -> Dict[str, Any]:
        """Get rate limiting statistics for an identifier."""
        stats = {}

        applicable_rules = self._find_applicable_rules(scope)

        for rule in applicable_rules:
            key = self._generate_key(rule, identifier)

            if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                bucket_info = self.redis.hmget(key, "tokens", "last_refill")
                if bucket_info[0]:
                    stats[rule.name] = {
                        "algorithm": rule.algorithm.value,
                        "tokens": float(bucket_info[0]),
                        "capacity": int(rule.limit * rule.burst_multiplier),
                        "last_refill": (
                            float(bucket_info[1]) if bucket_info[1] else None
                        ),
                    }

            elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW_COUNTER:
                count = self.redis.zcard(key)
                stats[rule.name] = {
                    "algorithm": rule.algorithm.value,
                    "current_count": count,
                    "limit": rule.limit,
                    "window_seconds": rule.window_seconds,
                }

            elif rule.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
                current_window = int(time.time() // rule.window_seconds)
                window_key = f"{key}:{current_window}"
                count = self.redis.get(window_key)
                stats[rule.name] = {
                    "algorithm": rule.algorithm.value,
                    "current_count": int(count) if count else 0,
                    "limit": rule.limit,
                    "window_seconds": rule.window_seconds,
                }

        return stats


# Export components
__all__ = [
    "RateLimiter",
    "RateLimitRule",
    "RateLimitInfo",
    "RateLimitExceeded",
    "RateLimitAlgorithm",
    "RateLimitScope",
    "TokenBucket",
    "SlidingWindowCounter",
    "FixedWindowCounter",
]
