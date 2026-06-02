"""Agent Error Handling and Logging Integration.

This module provides enhanced error handling and logging capabilities
that integrate with the new infrastructure components.
"""

import asyncio
import json
import logging
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from brain_researcher.services.agent.error_handling import (
    AgentError,
    ErrorCategory,
    ErrorHandler,
    ErrorSeverity,
)

logger = logging.getLogger(__name__)


class IntegrationType(Enum):
    """Types of integrations that can generate errors."""

    SUBSCRIPTION = "subscription"
    STREAMING = "streaming"
    DEDUPLICATION = "deduplication"
    PLUGIN = "plugin"
    CORE_AGENT = "core_agent"
    TOOL_EXECUTION = "tool_execution"


@dataclass
class IntegrationError:
    """Extended error information for integrations."""

    error_id: str
    integration_type: IntegrationType
    component: str
    error_type: str
    message: str
    details: Dict[str, Any]
    stack_trace: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    resolution_suggestions: List[str] = field(default_factory=list)


class IntegrationLogger:
    """Enhanced logger for integration components."""

    def __init__(
        self,
        component_name: str,
        integration_type: IntegrationType,
        redis_client=None,
        notification_manager=None,
    ):
        """Initialize integration logger.

        Args:
            component_name: Name of the component
            integration_type: Type of integration
            redis_client: Optional Redis client for log storage
            notification_manager: Optional notification manager for error alerts
        """
        self.component_name = component_name
        self.integration_type = integration_type
        self.redis = redis_client
        self.notification_manager = notification_manager

        # Create component-specific logger
        self.logger = logging.getLogger(
            f"agent.{integration_type.value}.{component_name}"
        )

        # Error tracking
        self.error_count = 0
        self.recent_errors: List[IntegrationError] = []
        self.max_recent_errors = 100

        # Performance tracking
        self.performance_metrics = {
            "operations_count": 0,
            "average_duration": 0.0,
            "error_rate": 0.0,
        }

    async def log_error(
        self,
        error: Exception,
        details: Dict[str, Any] = None,
        thread_id: str = None,
        user_id: str = None,
    ):
        """Log an error with enhanced context.

        Args:
            error: Exception that occurred
            details: Additional error details
            thread_id: Optional thread ID
            user_id: Optional user ID
        """
        error_id = str(uuid.uuid4())

        # Create integration error
        integration_error = IntegrationError(
            error_id=error_id,
            integration_type=self.integration_type,
            component=self.component_name,
            error_type=type(error).__name__,
            message=str(error),
            details=details or {},
            stack_trace=traceback.format_exc(),
            thread_id=thread_id,
            user_id=user_id,
            resolution_suggestions=self._generate_resolution_suggestions(error),
        )

        # Log to standard logger
        self.logger.error(
            f"[{error_id}] {self.component_name} error: {error}",
            extra={
                "error_id": error_id,
                "integration_type": self.integration_type.value,
                "component": self.component_name,
                "thread_id": thread_id,
                "user_id": user_id,
                "details": details,
            },
        )

        # Store error
        self._store_error(integration_error)

        # Notify if severe
        if self._is_severe_error(error):
            await self._notify_error(integration_error)

        # Update metrics
        self.error_count += 1
        self._update_error_rate()

    def _generate_resolution_suggestions(self, error: Exception) -> List[str]:
        """Generate resolution suggestions based on error type."""
        suggestions = []

        error_type = type(error).__name__

        if "Connection" in error_type:
            suggestions.extend(
                [
                    "Check network connectivity",
                    "Verify service endpoints are accessible",
                    "Check authentication credentials",
                ]
            )
        elif "Timeout" in error_type:
            suggestions.extend(
                [
                    "Increase timeout values",
                    "Check system performance",
                    "Verify service is not overloaded",
                ]
            )
        elif "Permission" in error_type or "Auth" in error_type:
            suggestions.extend(
                [
                    "Verify user permissions",
                    "Check API keys and tokens",
                    "Ensure proper role assignments",
                ]
            )
        elif "Validation" in error_type or "Invalid" in error_type:
            suggestions.extend(
                [
                    "Check input data format",
                    "Verify required fields are present",
                    "Review data validation rules",
                ]
            )
        else:
            suggestions.append("Check logs for more detailed error information")

        return suggestions

    def _is_severe_error(self, error: Exception) -> bool:
        """Determine if error is severe enough for immediate notification."""
        severe_types = [
            "SecurityError",
            "PermissionError",
            "SystemError",
            "MemoryError",
            "DatabaseError",
        ]

        return any(severe_type in type(error).__name__ for severe_type in severe_types)

    def _store_error(self, error: IntegrationError):
        """Store error in memory and Redis."""
        # Add to recent errors
        self.recent_errors.append(error)
        if len(self.recent_errors) > self.max_recent_errors:
            self.recent_errors.pop(0)

        # Store in Redis if available
        if self.redis:
            asyncio.create_task(self._store_error_in_redis(error))

    async def _store_error_in_redis(self, error: IntegrationError):
        """Store error in Redis."""
        try:
            key = f"agent:errors:{error.integration_type.value}:{error.error_id}"
            error_data = {
                "error_id": error.error_id,
                "integration_type": error.integration_type.value,
                "component": error.component,
                "error_type": error.error_type,
                "message": error.message,
                "details": error.details,
                "timestamp": error.timestamp.isoformat(),
                "thread_id": error.thread_id,
                "user_id": error.user_id,
                "resolution_suggestions": error.resolution_suggestions,
            }

            await self.redis.setex(key, 86400, json.dumps(error_data))  # 24 hour TTL

            # Add to error index
            index_key = f"agent:error_index:{error.integration_type.value}"
            await self.redis.lpush(index_key, error.error_id)
            await self.redis.ltrim(index_key, 0, 999)  # Keep only 1000 recent errors

        except Exception as e:
            self.logger.error(f"Failed to store error in Redis: {e}")

    async def _notify_error(self, error: IntegrationError):
        """Send error notification."""
        if self.notification_manager and error.thread_id:
            try:
                await self.notification_manager.notify_error(
                    error.thread_id,
                    error.error_id,
                    f"{error.component} error: {error.message}",
                    {
                        "integration_type": error.integration_type.value,
                        "error_type": error.error_type,
                        "resolution_suggestions": error.resolution_suggestions,
                    },
                )
            except Exception as e:
                self.logger.error(f"Failed to send error notification: {e}")

    def _update_error_rate(self):
        """Update error rate metrics."""
        if self.performance_metrics["operations_count"] > 0:
            self.performance_metrics["error_rate"] = (
                self.error_count / self.performance_metrics["operations_count"]
            )

    @contextmanager
    def log_operation(self, operation_name: str, details: Dict[str, Any] = None):
        """Context manager for logging operations with timing.

        Args:
            operation_name: Name of the operation
            details: Additional operation details
        """
        start_time = datetime.now()
        operation_id = str(uuid.uuid4())

        self.logger.debug(
            f"[{operation_id}] Starting {operation_name}",
            extra={
                "operation_id": operation_id,
                "operation": operation_name,
                "details": details,
                "integration_type": self.integration_type.value,
                "component": self.component_name,
            },
        )

        try:
            yield operation_id

            # Success
            duration = (datetime.now() - start_time).total_seconds()

            self.logger.debug(
                f"[{operation_id}] Completed {operation_name} in {duration:.3f}s",
                extra={
                    "operation_id": operation_id,
                    "operation": operation_name,
                    "duration": duration,
                    "status": "success",
                },
            )

            # Update metrics
            self._update_performance_metrics(duration)

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()

            self.logger.error(
                f"[{operation_id}] Failed {operation_name} after {duration:.3f}s: {e}",
                extra={
                    "operation_id": operation_id,
                    "operation": operation_name,
                    "duration": duration,
                    "status": "error",
                    "error": str(e),
                },
            )

            # Log the error
            asyncio.create_task(
                self.log_error(
                    e,
                    {
                        "operation": operation_name,
                        "operation_id": operation_id,
                        "duration": duration,
                    },
                )
            )

            raise

    def _update_performance_metrics(self, duration: float):
        """Update performance metrics."""
        count = self.performance_metrics["operations_count"]
        avg = self.performance_metrics["average_duration"]

        # Update moving average
        self.performance_metrics["operations_count"] = count + 1
        self.performance_metrics["average_duration"] = (avg * count + duration) / (
            count + 1
        )

        # Update error rate
        self._update_error_rate()

    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary for this component."""
        error_types = {}
        for error in self.recent_errors:
            error_types[error.error_type] = error_types.get(error.error_type, 0) + 1

        return {
            "component": self.component_name,
            "integration_type": self.integration_type.value,
            "total_errors": self.error_count,
            "recent_errors": len(self.recent_errors),
            "error_types": error_types,
            "error_rate": self.performance_metrics["error_rate"],
            "average_operation_duration": self.performance_metrics["average_duration"],
        }


class IntegrationErrorManager:
    """Manages errors across all integration components."""

    def __init__(self, redis_client=None, notification_manager=None):
        """Initialize error manager.

        Args:
            redis_client: Optional Redis client
            notification_manager: Optional notification manager
        """
        self.redis = redis_client
        self.notification_manager = notification_manager

        # Component loggers
        self.loggers: Dict[str, IntegrationLogger] = {}

        # Global error handler
        self.error_handler = ErrorHandler()

    def get_logger(
        self, component_name: str, integration_type: IntegrationType
    ) -> IntegrationLogger:
        """Get or create logger for a component.

        Args:
            component_name: Component name
            integration_type: Integration type

        Returns:
            Integration logger
        """
        key = f"{integration_type.value}.{component_name}"

        if key not in self.loggers:
            self.loggers[key] = IntegrationLogger(
                component_name, integration_type, self.redis, self.notification_manager
            )

        return self.loggers[key]

    async def get_errors(
        self, integration_type: Optional[IntegrationType] = None, limit: int = 50
    ) -> List[IntegrationError]:
        """Get recent errors.

        Args:
            integration_type: Optional integration type filter
            limit: Maximum errors to return

        Returns:
            List of recent errors
        """
        if not self.redis:
            # Return from memory
            all_errors = []
            for logger in self.loggers.values():
                if not integration_type or logger.integration_type == integration_type:
                    all_errors.extend(logger.recent_errors)

            all_errors.sort(key=lambda e: e.timestamp, reverse=True)
            return all_errors[:limit]

        # Get from Redis
        errors = []

        try:
            if integration_type:
                index_key = f"agent:error_index:{integration_type.value}"
                error_ids = await self.redis.lrange(index_key, 0, limit - 1)
            else:
                # Get from all integration types
                error_ids = []
                for int_type in IntegrationType:
                    index_key = f"agent:error_index:{int_type.value}"
                    ids = await self.redis.lrange(
                        index_key, 0, limit // len(IntegrationType)
                    )
                    error_ids.extend(ids)

            # Fetch error details
            for error_id in error_ids[:limit]:
                if integration_type:
                    key = f"agent:errors:{integration_type.value}:{error_id}"
                else:
                    # Try all integration types
                    key = None
                    for int_type in IntegrationType:
                        test_key = f"agent:errors:{int_type.value}:{error_id}"
                        if await self.redis.exists(test_key):
                            key = test_key
                            break

                if key:
                    error_data = await self.redis.get(key)
                    if error_data:
                        try:
                            data = json.loads(error_data)
                            error = IntegrationError(
                                error_id=data["error_id"],
                                integration_type=IntegrationType(
                                    data["integration_type"]
                                ),
                                component=data["component"],
                                error_type=data["error_type"],
                                message=data["message"],
                                details=data["details"],
                                timestamp=datetime.fromisoformat(data["timestamp"]),
                                thread_id=data.get("thread_id"),
                                user_id=data.get("user_id"),
                                resolution_suggestions=data.get(
                                    "resolution_suggestions", []
                                ),
                            )
                            errors.append(error)
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            logger.error(f"Error retrieving errors from Redis: {e}")

        return errors

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get comprehensive error statistics."""
        stats = {
            "by_integration": {},
            "by_component": {},
            "total_errors": 0,
            "total_components": len(self.loggers),
        }

        for key, component_logger in self.loggers.items():
            summary = component_logger.get_error_summary()

            # By integration type
            int_type = summary["integration_type"]
            if int_type not in stats["by_integration"]:
                stats["by_integration"][int_type] = {
                    "total_errors": 0,
                    "components": 0,
                    "error_rate": 0.0,
                }

            stats["by_integration"][int_type]["total_errors"] += summary["total_errors"]
            stats["by_integration"][int_type]["components"] += 1
            stats["by_integration"][int_type]["error_rate"] += summary["error_rate"]

            # By component
            stats["by_component"][key] = summary

            # Total
            stats["total_errors"] += summary["total_errors"]

        # Average error rates
        for int_type in stats["by_integration"]:
            int_stats = stats["by_integration"][int_type]
            if int_stats["components"] > 0:
                int_stats["error_rate"] /= int_stats["components"]

        return stats


# Integration helper functions
def setup_integration_logging(
    redis_client=None, notification_manager=None
) -> IntegrationErrorManager:
    """Set up integration logging and error management.

    Args:
        redis_client: Optional Redis client
        notification_manager: Optional notification manager

    Returns:
        Integration error manager
    """
    return IntegrationErrorManager(redis_client, notification_manager)


def get_integration_logger(
    component_name: str,
    integration_type: IntegrationType,
    error_manager: Optional[IntegrationErrorManager] = None,
) -> IntegrationLogger:
    """Get a logger for an integration component.

    Args:
        component_name: Name of the component
        integration_type: Type of integration
        error_manager: Optional error manager (will create if not provided)

    Returns:
        Integration logger
    """
    if not error_manager:
        error_manager = IntegrationErrorManager()

    return error_manager.get_logger(component_name, integration_type)


# Decorator for automatic error logging
def log_integration_errors(
    integration_type: IntegrationType, component_name: str = None
):
    """Decorator to automatically log errors in integration functions.

    Args:
        integration_type: Type of integration
        component_name: Optional component name (uses function name if not provided)
    """

    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            error_manager = IntegrationErrorManager()
            comp_name = component_name or func.__name__
            logger = error_manager.get_logger(comp_name, integration_type)

            with logger.log_operation(
                func.__name__, {"args": len(args), "kwargs": list(kwargs.keys())}
            ):
                return await func(*args, **kwargs)

        def sync_wrapper(*args, **kwargs):
            error_manager = IntegrationErrorManager()
            comp_name = component_name or func.__name__
            logger = error_manager.get_logger(comp_name, integration_type)

            with logger.log_operation(
                func.__name__, {"args": len(args), "kwargs": list(kwargs.keys())}
            ):
                return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
