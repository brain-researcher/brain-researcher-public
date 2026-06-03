"""
Comprehensive error handling utilities with circuit breaker pattern,
retry logic, and graceful degradation strategies.
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any

from pydantic import BaseModel, Field

from .models import ErrorCode, ErrorContext, ErrorResponse

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class ServiceType(str, Enum):
    """Service types for different error handling strategies."""

    AGENT = "agent"
    BR_KG = "br_kg"
    DATABASE = "database"
    EXTERNAL_API = "external_api"
    FILE_SYSTEM = "file_system"
    CACHE = "cache"


class FailureType(str, Enum):
    """Types of failures for categorization."""

    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    RATE_LIMITED = "rate_limited"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    AUTHENTICATION_ERROR = "authentication_error"


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration."""

    failure_threshold: int = Field(default=5, ge=1)  # Failures to open circuit
    success_threshold: int = Field(default=3, ge=1)  # Successes to close circuit
    timeout_seconds: int = Field(default=60, ge=1)  # Time before half-open
    max_timeout_seconds: int = Field(default=600, ge=1)  # Max timeout
    backoff_multiplier: float = Field(default=1.5, ge=1.0)


class GracefulDegradationStrategy(BaseModel):
    """Strategy for graceful degradation."""

    fallback_enabled: bool = True
    use_cache: bool = True
    cache_ttl_seconds: int = Field(default=300, ge=0)
    simplified_response: bool = True
    disable_non_essential_features: bool = True
    user_notification_enabled: bool = True


class RetryStrategy(BaseModel):
    """Enhanced retry strategy configuration."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay_ms: int = Field(default=1000, ge=100)
    max_delay_ms: int = Field(default=30000, le=60000)
    exponential_base: float = Field(default=2.0, ge=1.0, le=3.0)
    jitter_enabled: bool = True
    jitter_max_ms: int = Field(default=500, ge=0)
    backoff_strategy: str = Field(default="exponential")  # exponential, linear, fixed


class ErrorMetrics(BaseModel):
    """Error metrics for monitoring."""

    total_requests: int = 0
    failed_requests: int = 0
    success_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    last_error_time: datetime | None = None
    error_types: dict[str, int] = Field(default_factory=dict)
    circuit_state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0


class ServiceErrorHandler:
    """Main error handler with circuit breaker and retry logic."""

    def __init__(
        self,
        service_name: str,
        service_type: ServiceType,
        circuit_config: CircuitBreakerConfig | None = None,
        retry_strategy: RetryStrategy | None = None,
        degradation_strategy: GracefulDegradationStrategy | None = None,
    ):
        self.service_name = service_name
        self.service_type = service_type
        self.circuit_config = circuit_config or CircuitBreakerConfig()
        self.retry_strategy = retry_strategy or RetryStrategy()
        self.degradation_strategy = (
            degradation_strategy or GracefulDegradationStrategy()
        )

        self.metrics = ErrorMetrics()
        self.circuit_opened_at: datetime | None = None
        self.cache: dict[str, Any] = {}
        self.cache_timestamps: dict[str, datetime] = {}

        logger.info(f"Initialized error handler for {service_name} ({service_type})")

    async def execute_with_circuit_breaker(
        self,
        operation: Callable,
        *args,
        operation_id: str | None = None,
        context: dict[str, Any] | None = None,
        **kwargs,
    ) -> Any:
        """Execute operation with circuit breaker protection."""
        operation_id = operation_id or f"{self.service_name}_{int(time.time())}"
        context = context or {}

        # Check circuit state
        if self.metrics.circuit_state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.metrics.circuit_state = CircuitState.HALF_OPEN
                logger.info(f"Circuit breaker half-open for {self.service_name}")
            else:
                return await self._handle_circuit_open(operation_id, context)

        start_time = time.time()

        try:
            # Execute with retry logic
            result = await self._execute_with_retry(
                operation, *args, operation_id=operation_id, context=context, **kwargs
            )

            # Record success
            await self._record_success(time.time() - start_time)
            return result

        except Exception as e:
            # Record failure
            await self._record_failure(
                e, time.time() - start_time, operation_id, context
            )
            raise

    async def _execute_with_retry(
        self,
        operation: Callable,
        *args,
        operation_id: str,
        context: dict[str, Any],
        **kwargs,
    ) -> Any:
        """Execute operation with retry logic."""
        last_exception = None

        for attempt in range(self.retry_strategy.max_attempts):
            try:
                if asyncio.iscoroutinefunction(operation):
                    return await operation(*args, **kwargs)
                else:
                    return operation(*args, **kwargs)

            except Exception as e:
                last_exception = e
                failure_type = self._classify_failure(e)

                # Don't retry certain error types
                if failure_type in [
                    FailureType.VALIDATION_ERROR,
                    FailureType.AUTHENTICATION_ERROR,
                ]:
                    logger.warning(
                        f"Non-retryable error in {operation_id}: {failure_type}"
                    )
                    raise

                if attempt < self.retry_strategy.max_attempts - 1:
                    delay_ms = self._calculate_delay(attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {operation_id}: {str(e)}"
                        f". Retrying in {delay_ms}ms"
                    )
                    await asyncio.sleep(delay_ms / 1000.0)
                else:
                    logger.error(
                        f"All {self.retry_strategy.max_attempts} attempts failed for {operation_id}"
                    )

        raise last_exception

    def _calculate_delay(self, attempt: int) -> int:
        """Calculate delay for retry attempt."""
        if self.retry_strategy.backoff_strategy == "exponential":
            base_delay = self.retry_strategy.initial_delay_ms * (
                self.retry_strategy.exponential_base**attempt
            )
        elif self.retry_strategy.backoff_strategy == "linear":
            base_delay = self.retry_strategy.initial_delay_ms * (attempt + 1)
        else:  # fixed
            base_delay = self.retry_strategy.initial_delay_ms

        # Apply jitter if enabled
        if self.retry_strategy.jitter_enabled:
            jitter = random.randint(0, self.retry_strategy.jitter_max_ms)
            base_delay += jitter

        return min(int(base_delay), self.retry_strategy.max_delay_ms)

    def _classify_failure(self, exception: Exception) -> FailureType:
        """Classify failure type for appropriate handling."""
        error_message = str(exception).lower()
        exception_type = type(exception).__name__.lower()

        if "timeout" in error_message or "timeout" in exception_type:
            return FailureType.TIMEOUT
        elif "connection" in error_message or "connection" in exception_type:
            return FailureType.CONNECTION_ERROR
        elif "unavailable" in error_message or "503" in error_message:
            return FailureType.SERVICE_UNAVAILABLE
        elif "rate limit" in error_message or "429" in error_message:
            return FailureType.RATE_LIMITED
        elif "validation" in error_message or "400" in error_message:
            return FailureType.VALIDATION_ERROR
        elif "unauthorized" in error_message or "401" in error_message:
            return FailureType.AUTHENTICATION_ERROR
        elif "resource" in error_message and "exhaust" in error_message:
            return FailureType.RESOURCE_EXHAUSTED
        else:
            return FailureType.INTERNAL_ERROR

    async def _record_success(self, response_time_ms: float):
        """Record successful operation."""
        self.metrics.total_requests += 1
        self.metrics.consecutive_successes += 1
        self.metrics.consecutive_failures = 0

        # Update average response time
        if self.metrics.total_requests == 1:
            self.metrics.avg_response_time_ms = response_time_ms * 1000
        else:
            # Exponential moving average
            alpha = 0.1
            self.metrics.avg_response_time_ms = (
                alpha * (response_time_ms * 1000)
                + (1 - alpha) * self.metrics.avg_response_time_ms
            )

        self.metrics.success_rate = (
            self.metrics.total_requests - self.metrics.failed_requests
        ) / self.metrics.total_requests

        # Close circuit if enough successes in half-open state
        if (
            self.metrics.circuit_state == CircuitState.HALF_OPEN
            and self.metrics.consecutive_successes
            >= self.circuit_config.success_threshold
        ):
            self.metrics.circuit_state = CircuitState.CLOSED
            self.circuit_opened_at = None
            logger.info(f"Circuit breaker closed for {self.service_name}")

    async def _record_failure(
        self,
        exception: Exception,
        response_time_ms: float,
        operation_id: str,
        context: dict[str, Any],
    ):
        """Record failed operation."""
        self.metrics.total_requests += 1
        self.metrics.failed_requests += 1
        self.metrics.consecutive_failures += 1
        self.metrics.consecutive_successes = 0
        self.metrics.last_error_time = datetime.utcnow()

        failure_type = self._classify_failure(exception)
        self.metrics.error_types[failure_type.value] = (
            self.metrics.error_types.get(failure_type.value, 0) + 1
        )

        self.metrics.success_rate = (
            self.metrics.total_requests - self.metrics.failed_requests
        ) / self.metrics.total_requests

        # Open circuit if threshold reached
        if (
            self.metrics.circuit_state == CircuitState.CLOSED
            and self.metrics.consecutive_failures
            >= self.circuit_config.failure_threshold
        ):
            self.metrics.circuit_state = CircuitState.OPEN
            self.circuit_opened_at = datetime.utcnow()
            logger.error(f"Circuit breaker opened for {self.service_name}")

        # Log error details
        logger.error(
            f"Operation failed: {operation_id}, "
            f"Service: {self.service_name}, "
            f"Error: {str(exception)}, "
            f"Type: {failure_type.value}, "
            f"Context: {context}"
        )

    def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should attempt reset."""
        if self.circuit_opened_at is None:
            return False

        elapsed = (datetime.utcnow() - self.circuit_opened_at).total_seconds()
        timeout = self.circuit_config.timeout_seconds * (
            self.circuit_config.backoff_multiplier
            ** min(
                self.metrics.consecutive_failures
                // self.circuit_config.failure_threshold,
                5,
            )
        )
        timeout = min(timeout, self.circuit_config.max_timeout_seconds)

        return elapsed >= timeout

    async def _handle_circuit_open(
        self, operation_id: str, context: dict[str, Any]
    ) -> Any:
        """Handle circuit breaker open state."""
        logger.warning(
            f"Circuit breaker open for {self.service_name}, operation: {operation_id}"
        )

        # Try graceful degradation
        if self.degradation_strategy.fallback_enabled:
            return await self._apply_graceful_degradation(operation_id, context)

        # Raise service unavailable error
        raise ServiceUnavailableError(
            f"Service {self.service_name} is currently unavailable",
            service_name=self.service_name,
            circuit_state=self.metrics.circuit_state,
            estimated_recovery_time=self._estimate_recovery_time(),
        )

    async def _apply_graceful_degradation(
        self, operation_id: str, context: dict[str, Any]
    ) -> Any:
        """Apply graceful degradation strategies."""
        degraded_response = {
            "status": "degraded",
            "service": self.service_name,
            "operation_id": operation_id,
            "message": "Service temporarily unavailable, using fallback response",
            "data": None,
        }

        # Try cache fallback
        if self.degradation_strategy.use_cache:
            cached_result = self._get_cached_response(operation_id, context)
            if cached_result is not None:
                degraded_response["data"] = cached_result
                degraded_response["message"] = (
                    "Using cached response due to service unavailability"
                )
                return degraded_response

        # Return simplified response
        if self.degradation_strategy.simplified_response:
            degraded_response["data"] = self._generate_simplified_response(context)
            return degraded_response

        # If no fallback available, raise error
        raise ServiceUnavailableError(
            f"Service {self.service_name} is unavailable and no fallback available"
        )

    def _get_cached_response(
        self, operation_id: str, context: dict[str, Any]
    ) -> Any | None:
        """Get cached response if available and valid."""
        cache_key = self._generate_cache_key(operation_id, context)

        if cache_key in self.cache:
            timestamp = self.cache_timestamps.get(cache_key)
            if (
                timestamp
                and (datetime.utcnow() - timestamp).total_seconds()
                <= self.degradation_strategy.cache_ttl_seconds
            ):
                logger.info(f"Using cached response for {operation_id}")
                return self.cache[cache_key]
            else:
                # Remove expired cache
                self.cache.pop(cache_key, None)
                self.cache_timestamps.pop(cache_key, None)

        return None

    def _generate_cache_key(self, operation_id: str, context: dict[str, Any]) -> str:
        """Generate cache key for operation."""
        import hashlib
        import json

        key_data = {
            "service": self.service_name,
            "operation": operation_id,
            "context": context,
        }

        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _generate_simplified_response(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate simplified response for graceful degradation."""
        return {
            "simplified": True,
            "message": f"Simplified response from {self.service_name}",
            "context": context,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _estimate_recovery_time(self) -> int:
        """Estimate recovery time in seconds."""
        if self.circuit_opened_at is None:
            return 0

        base_timeout = self.circuit_config.timeout_seconds
        failure_multiplier = (
            self.metrics.consecutive_failures // self.circuit_config.failure_threshold
        )

        return int(
            base_timeout
            * (self.circuit_config.backoff_multiplier ** min(failure_multiplier, 5))
        )

    def cache_response(self, operation_id: str, context: dict[str, Any], response: Any):
        """Cache successful response."""
        if self.degradation_strategy.use_cache:
            cache_key = self._generate_cache_key(operation_id, context)
            self.cache[cache_key] = response
            self.cache_timestamps[cache_key] = datetime.utcnow()

            # Clean up old cache entries
            self._cleanup_cache()

    def _cleanup_cache(self):
        """Clean up expired cache entries."""
        current_time = datetime.utcnow()
        expired_keys = []

        for key, timestamp in self.cache_timestamps.items():
            if (
                current_time - timestamp
            ).total_seconds() > self.degradation_strategy.cache_ttl_seconds:
                expired_keys.append(key)

        for key in expired_keys:
            self.cache.pop(key, None)
            self.cache_timestamps.pop(key, None)

    def get_metrics(self) -> ErrorMetrics:
        """Get current error metrics."""
        return self.metrics

    def reset_circuit(self):
        """Manually reset circuit breaker."""
        self.metrics.circuit_state = CircuitState.CLOSED
        self.metrics.consecutive_failures = 0
        self.circuit_opened_at = None
        logger.info(f"Circuit breaker manually reset for {self.service_name}")


class ServiceUnavailableError(Exception):
    """Service unavailable error with additional context."""

    def __init__(
        self,
        message: str,
        service_name: str | None = None,
        circuit_state: CircuitState | None = None,
        estimated_recovery_time: int | None = None,
    ):
        super().__init__(message)
        self.service_name = service_name
        self.circuit_state = circuit_state
        self.estimated_recovery_time = estimated_recovery_time


class ErrorMessageFormatter:
    """Formats user-friendly error messages."""

    @staticmethod
    def format_error_for_user(
        error_code: ErrorCode,
        original_error: str,
        context: dict[str, Any] | None = None,
        suggestions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Format error message for user consumption."""

        user_messages = {
            ErrorCode.SERVICE_UNAVAILABLE: {
                "title": "Service Temporarily Unavailable",
                "message": "The analysis service is currently unavailable. Please try again in a few minutes.",
                "icon": "🔧",
                "severity": "warning",
            },
            ErrorCode.SERVICE_TIMEOUT: {
                "title": "Request Timeout",
                "message": "Your request is taking longer than expected. You can try again or contact support if the issue persists.",
                "icon": "⏱️",
                "severity": "warning",
            },
            ErrorCode.VALIDATION_ERROR: {
                "title": "Invalid Input",
                "message": "Please check your input parameters and try again.",
                "icon": "❌",
                "severity": "error",
            },
            ErrorCode.RATE_LIMITED: {
                "title": "Rate Limit Exceeded",
                "message": "You've made too many requests recently. Please wait a moment before trying again.",
                "icon": "🚦",
                "severity": "warning",
            },
            ErrorCode.NOT_FOUND: {
                "title": "Resource Not Found",
                "message": "The requested resource could not be found. Please check your request and try again.",
                "icon": "🔍",
                "severity": "error",
            },
        }

        default_message = {
            "title": "Unexpected Error",
            "message": "An unexpected error occurred. Our team has been notified.",
            "icon": "⚠️",
            "severity": "error",
        }

        formatted = user_messages.get(error_code, default_message).copy()

        # Add suggestions if provided
        if suggestions:
            formatted["suggestions"] = suggestions
        elif error_code == ErrorCode.SERVICE_UNAVAILABLE:
            formatted["suggestions"] = [
                "Try again in a few minutes",
                "Check system status page",
                "Use demo mode if available",
            ]
        elif error_code == ErrorCode.VALIDATION_ERROR:
            formatted["suggestions"] = [
                "Check parameter ranges in documentation",
                "Verify required fields are filled",
                "Use example values for testing",
            ]

        # Add context information
        if context:
            formatted["context"] = context

        formatted["technical_details"] = original_error
        formatted["timestamp"] = datetime.utcnow().isoformat()

        return formatted


class ErrorHandlerRegistry:
    """Registry for managing service error handlers."""

    def __init__(self):
        self._handlers: dict[str, ServiceErrorHandler] = {}
        self._global_config: dict[str, Any] = {}

    def register_handler(
        self,
        service_name: str,
        service_type: ServiceType,
        circuit_config: CircuitBreakerConfig | None = None,
        retry_strategy: RetryStrategy | None = None,
        degradation_strategy: GracefulDegradationStrategy | None = None,
    ) -> ServiceErrorHandler:
        """Register error handler for service."""

        handler = ServiceErrorHandler(
            service_name=service_name,
            service_type=service_type,
            circuit_config=circuit_config,
            retry_strategy=retry_strategy,
            degradation_strategy=degradation_strategy,
        )

        self._handlers[service_name] = handler
        logger.info(f"Registered error handler for service: {service_name}")

        return handler

    def get_handler(self, service_name: str) -> ServiceErrorHandler | None:
        """Get error handler for service."""
        return self._handlers.get(service_name)

    def get_all_metrics(self) -> dict[str, ErrorMetrics]:
        """Get metrics from all registered handlers."""
        return {name: handler.get_metrics() for name, handler in self._handlers.items()}

    def reset_all_circuits(self):
        """Reset all circuit breakers."""
        for handler in self._handlers.values():
            handler.reset_circuit()
        logger.info("All circuit breakers have been reset")


# Global error handler registry
error_registry = ErrorHandlerRegistry()


# Decorator for automatic error handling
def with_error_handling(
    service_name: str,
    service_type: ServiceType,
    operation_id: str | None = None,
    context: dict[str, Any] | None = None,
):
    """Decorator to automatically apply error handling to functions."""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            handler = error_registry.get_handler(service_name)
            if not handler:
                # Register default handler if not exists
                handler = error_registry.register_handler(service_name, service_type)

            op_id = operation_id or f"{func.__name__}_{int(time.time())}"
            op_context = context or {}

            return await handler.execute_with_circuit_breaker(
                func, *args, operation_id=op_id, context=op_context, **kwargs
            )

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            async def async_func(*args, **kwargs):
                return func(*args, **kwargs)

            handler = error_registry.get_handler(service_name)
            if not handler:
                handler = error_registry.register_handler(service_name, service_type)

            op_id = operation_id or f"{func.__name__}_{int(time.time())}"
            op_context = context or {}

            return asyncio.run(
                handler.execute_with_circuit_breaker(
                    async_func, *args, operation_id=op_id, context=op_context, **kwargs
                )
            )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# Context manager for error handling
@asynccontextmanager
async def error_handling_context(
    service_name: str,
    service_type: ServiceType,
    operation_id: str | None = None,
    context: dict[str, Any] | None = None,
):
    """Context manager for error handling operations."""
    handler = error_registry.get_handler(service_name)
    if not handler:
        handler = error_registry.register_handler(service_name, service_type)

    op_id = operation_id or f"context_{int(time.time())}"
    op_context = context or {}

    start_time = time.time()

    try:
        yield handler
        # Record success
        await handler._record_success(time.time() - start_time)

    except Exception as e:
        # Record failure
        await handler._record_failure(e, time.time() - start_time, op_id, op_context)
        raise


def create_error_response(
    error_code: ErrorCode,
    message: str,
    details: dict | None = None,
    context: ErrorContext | None = None,
    suggestions: list[str] | None = None,
) -> ErrorResponse:
    """Helper function to create standardized error responses."""
    formatted_error = ErrorMessageFormatter.format_error_for_user(
        error_code=error_code,
        original_error=message,
        context=context.model_dump() if context else None,
        suggestions=suggestions,
    )

    return ErrorResponse.create(
        code=error_code,
        message=formatted_error["message"],
        details=details or formatted_error,
    )
