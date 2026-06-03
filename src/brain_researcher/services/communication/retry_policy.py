"""
Retry Policy Implementation.

Provides configurable retry mechanisms for handling transient failures
in distributed systems with various backoff strategies.
"""

import asyncio
import random
import time
from typing import Callable, Any, Optional, List, Type, Union
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BackoffStrategy(str, Enum):
    """Backoff strategy types."""

    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIBONACCI = "fibonacci"
    RANDOM = "random"
    EXPONENTIAL_JITTER = "exponential_jitter"


@dataclass
class RetryConfig:
    """Retry policy configuration."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    backoff_multiplier: float = 2.0
    jitter: bool = True
    jitter_max_seconds: float = 1.0
    retryable_exceptions: Optional[List[Type[Exception]]] = None
    non_retryable_exceptions: Optional[List[Type[Exception]]] = None
    timeout_seconds: Optional[float] = None

    def __post_init__(self):
        """Post-initialization validation."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be non-negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds")
        if self.backoff_multiplier <= 0:
            raise ValueError("backoff_multiplier must be positive")

        # Set default exception lists
        if self.retryable_exceptions is None:
            self.retryable_exceptions = [
                ConnectionError,
                TimeoutError,
                OSError,
                # Add more transient error types as needed
            ]

        if self.non_retryable_exceptions is None:
            self.non_retryable_exceptions = [
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                # Add more permanent error types as needed
            ]


class RetryAttempt:
    """Information about a retry attempt."""

    def __init__(
        self,
        attempt_number: int,
        delay_seconds: float,
        start_time: datetime,
        exception: Optional[Exception] = None
    ):
        """Initialize retry attempt.

        Args:
            attempt_number: Current attempt number (1-based)
            delay_seconds: Delay before this attempt
            start_time: Start time of the attempt
            exception: Exception from previous attempt
        """
        self.attempt_number = attempt_number
        self.delay_seconds = delay_seconds
        self.start_time = start_time
        self.exception = exception
        self.end_time: Optional[datetime] = None
        self.success: bool = False
        self.result: Any = None

    def complete(self, success: bool, result: Any = None, exception: Optional[Exception] = None):
        """Mark attempt as complete.

        Args:
            success: Whether the attempt was successful
            result: Result of the attempt if successful
            exception: Exception if failed
        """
        self.end_time = datetime.utcnow()
        self.success = success
        self.result = result
        if exception:
            self.exception = exception

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get attempt duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class RetryMetrics:
    """Metrics for retry policy execution."""

    def __init__(self):
        """Initialize retry metrics."""
        self.total_executions = 0
        self.successful_executions = 0
        self.failed_executions = 0
        self.total_attempts = 0
        self.total_retry_delay_seconds = 0.0
        self.execution_history: List[List[RetryAttempt]] = []
        self.last_execution_time: Optional[datetime] = None

    def record_execution(self, attempts: List[RetryAttempt]):
        """Record execution attempt history.

        Args:
            attempts: List of retry attempts for this execution
        """
        self.total_executions += 1
        self.total_attempts += len(attempts)
        self.last_execution_time = datetime.utcnow()

        # Check if execution was successful
        if attempts and attempts[-1].success:
            self.successful_executions += 1
        else:
            self.failed_executions += 1

        # Calculate total delay
        total_delay = sum(attempt.delay_seconds for attempt in attempts[1:])  # Skip first attempt
        self.total_retry_delay_seconds += total_delay

        # Store attempt history (keep last 100 executions)
        self.execution_history.append(attempts)
        if len(self.execution_history) > 100:
            self.execution_history.pop(0)

    def get_success_rate(self) -> float:
        """Get execution success rate."""
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions

    def get_average_attempts(self) -> float:
        """Get average number of attempts per execution."""
        if self.total_executions == 0:
            return 0.0
        return self.total_attempts / self.total_executions

    def get_average_delay(self) -> float:
        """Get average retry delay per execution."""
        if self.total_executions == 0:
            return 0.0
        return self.total_retry_delay_seconds / self.total_executions

    def to_dict(self) -> dict:
        """Convert metrics to dictionary."""
        return {
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "success_rate": self.get_success_rate(),
            "total_attempts": self.total_attempts,
            "average_attempts_per_execution": self.get_average_attempts(),
            "total_retry_delay_seconds": self.total_retry_delay_seconds,
            "average_delay_per_execution": self.get_average_delay(),
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None
        }


class BackoffCalculator(ABC):
    """Abstract base class for backoff calculators."""

    @abstractmethod
    def calculate_delay(self, attempt_number: int, base_delay: float, **kwargs) -> float:
        """Calculate delay for given attempt.

        Args:
            attempt_number: Current attempt number (1-based)
            base_delay: Base delay in seconds
            **kwargs: Additional parameters

        Returns:
            Delay in seconds
        """
        pass


class FixedBackoff(BackoffCalculator):
    """Fixed delay backoff strategy."""

    def calculate_delay(self, attempt_number: int, base_delay: float, **kwargs) -> float:
        """Return fixed base delay."""
        return base_delay


class ExponentialBackoff(BackoffCalculator):
    """Exponential backoff strategy."""

    def calculate_delay(self, attempt_number: int, base_delay: float, **kwargs) -> float:
        """Calculate exponential delay."""
        multiplier = kwargs.get('backoff_multiplier', 2.0)
        max_delay = kwargs.get('max_delay_seconds', 60.0)

        delay = base_delay * (multiplier ** (attempt_number - 1))
        return min(delay, max_delay)


class LinearBackoff(BackoffCalculator):
    """Linear backoff strategy."""

    def calculate_delay(self, attempt_number: int, base_delay: float, **kwargs) -> float:
        """Calculate linear delay."""
        multiplier = kwargs.get('backoff_multiplier', 1.0)
        max_delay = kwargs.get('max_delay_seconds', 60.0)

        delay = base_delay + (multiplier * (attempt_number - 1))
        return min(delay, max_delay)


class FibonacciBackoff(BackoffCalculator):
    """Fibonacci sequence backoff strategy."""

    def __init__(self):
        """Initialize Fibonacci calculator."""
        self._fib_cache = {1: 1, 2: 1}

    def _fibonacci(self, n: int) -> int:
        """Calculate nth Fibonacci number."""
        if n in self._fib_cache:
            return self._fib_cache[n]

        self._fib_cache[n] = self._fibonacci(n - 1) + self._fibonacci(n - 2)
        return self._fib_cache[n]

    def calculate_delay(self, attempt_number: int, base_delay: float, **kwargs) -> float:
        """Calculate Fibonacci delay."""
        max_delay = kwargs.get('max_delay_seconds', 60.0)

        fib_multiplier = self._fibonacci(attempt_number)
        delay = base_delay * fib_multiplier
        return min(delay, max_delay)


class RandomBackoff(BackoffCalculator):
    """Random backoff strategy."""

    def calculate_delay(self, attempt_number: int, base_delay: float, **kwargs) -> float:
        """Calculate random delay."""
        max_delay = kwargs.get('max_delay_seconds', 60.0)

        # Random delay between base_delay and max_delay
        delay = random.uniform(base_delay, max_delay)
        return delay


class ExponentialJitterBackoff(BackoffCalculator):
    """Exponential backoff with jitter."""

    def calculate_delay(self, attempt_number: int, base_delay: float, **kwargs) -> float:
        """Calculate exponential delay with jitter."""
        multiplier = kwargs.get('backoff_multiplier', 2.0)
        max_delay = kwargs.get('max_delay_seconds', 60.0)
        jitter_max = kwargs.get('jitter_max_seconds', 1.0)

        # Calculate base exponential delay
        exponential_delay = base_delay * (multiplier ** (attempt_number - 1))
        exponential_delay = min(exponential_delay, max_delay)

        # Add jitter
        jitter = random.uniform(0, jitter_max)
        return exponential_delay + jitter


class RetryPolicy:
    """Main retry policy implementation."""

    def __init__(self, config: RetryConfig, name: str = "default"):
        """Initialize retry policy.

        Args:
            config: Retry policy configuration
            name: Policy name for identification
        """
        self.config = config
        self.name = name
        self.metrics = RetryMetrics()

        # Initialize backoff calculator
        self._backoff_calculator = self._create_backoff_calculator()

        logger.debug(f"Retry policy '{name}' initialized with config: {config}")

    def _create_backoff_calculator(self) -> BackoffCalculator:
        """Create appropriate backoff calculator."""
        strategy_map = {
            BackoffStrategy.FIXED: FixedBackoff,
            BackoffStrategy.EXPONENTIAL: ExponentialBackoff,
            BackoffStrategy.LINEAR: LinearBackoff,
            BackoffStrategy.FIBONACCI: FibonacciBackoff,
            BackoffStrategy.RANDOM: RandomBackoff,
            BackoffStrategy.EXPONENTIAL_JITTER: ExponentialJitterBackoff
        }

        calculator_class = strategy_map.get(self.config.backoff_strategy)
        if not calculator_class:
            logger.warning(f"Unknown backoff strategy: {self.config.backoff_strategy}, using exponential")
            calculator_class = ExponentialBackoff

        return calculator_class()

    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with retry policy.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            Exception: Last exception if all retries failed
        """
        attempts: List[RetryAttempt] = []
        last_exception = None

        for attempt_num in range(1, self.config.max_attempts + 1):
            # Calculate delay for this attempt (0 for first attempt)
            if attempt_num == 1:
                delay = 0.0
            else:
                delay = self._calculate_delay(attempt_num)
                if delay > 0:
                    await asyncio.sleep(delay)

            # Create attempt record
            attempt = RetryAttempt(
                attempt_number=attempt_num,
                delay_seconds=delay,
                start_time=datetime.utcnow(),
                exception=last_exception
            )
            attempts.append(attempt)

            try:
                # Execute function with timeout if configured
                if self.config.timeout_seconds:
                    if asyncio.iscoroutinefunction(func):
                        result = await asyncio.wait_for(
                            func(*args, **kwargs),
                            timeout=self.config.timeout_seconds
                        )
                    else:
                        # For sync functions, run in executor with timeout
                        result = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(None, func, *args, **kwargs),
                            timeout=self.config.timeout_seconds
                        )
                else:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)

                # Success!
                attempt.complete(True, result)
                self.metrics.record_execution(attempts)

                logger.debug(f"Retry policy '{self.name}' succeeded on attempt {attempt_num}")
                return result

            except Exception as e:
                last_exception = e
                attempt.complete(False, exception=e)

                # Check if exception is retryable
                if not self._is_retryable(e):
                    logger.debug(f"Non-retryable exception in retry policy '{self.name}': {type(e).__name__}")
                    self.metrics.record_execution(attempts)
                    raise

                # Log retry attempt
                if attempt_num < self.config.max_attempts:
                    next_delay = self._calculate_delay(attempt_num + 1)
                    logger.debug(
                        f"Retry policy '{self.name}' attempt {attempt_num} failed: {type(e).__name__}. "
                        f"Retrying in {next_delay:.2f}s"
                    )
                else:
                    logger.warning(
                        f"Retry policy '{self.name}' exhausted all {self.config.max_attempts} attempts"
                    )

        # All retries failed
        self.metrics.record_execution(attempts)
        raise last_exception

    def _calculate_delay(self, attempt_number: int) -> float:
        """Calculate delay for given attempt number."""
        base_delay = self._backoff_calculator.calculate_delay(
            attempt_number,
            self.config.base_delay_seconds,
            backoff_multiplier=self.config.backoff_multiplier,
            max_delay_seconds=self.config.max_delay_seconds,
            jitter_max_seconds=self.config.jitter_max_seconds
        )

        # Apply jitter if enabled (for non-jitter strategies)
        if (self.config.jitter and
            self.config.backoff_strategy != BackoffStrategy.EXPONENTIAL_JITTER and
            self.config.backoff_strategy != BackoffStrategy.RANDOM):
            jitter = random.uniform(0, self.config.jitter_max_seconds)
            base_delay += jitter

        return min(base_delay, self.config.max_delay_seconds)

    def _is_retryable(self, exception: Exception) -> bool:
        """Check if exception is retryable."""
        exception_type = type(exception)

        # Check non-retryable exceptions first
        if any(isinstance(exception, exc_type) for exc_type in self.config.non_retryable_exceptions):
            return False

        # Check retryable exceptions
        if any(isinstance(exception, exc_type) for exc_type in self.config.retryable_exceptions):
            return True

        # Default to not retryable
        return False

    def get_metrics(self) -> dict:
        """Get retry policy metrics."""
        metrics_dict = self.metrics.to_dict()
        metrics_dict.update({
            "name": self.name,
            "config": {
                "max_attempts": self.config.max_attempts,
                "base_delay_seconds": self.config.base_delay_seconds,
                "max_delay_seconds": self.config.max_delay_seconds,
                "backoff_strategy": self.config.backoff_strategy.value,
                "backoff_multiplier": self.config.backoff_multiplier,
                "jitter": self.config.jitter,
                "timeout_seconds": self.config.timeout_seconds
            }
        })
        return metrics_dict


def retry(
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL,
    **config_kwargs
):
    """Decorator for applying retry policy to functions.

    Args:
        max_attempts: Maximum number of attempts
        base_delay_seconds: Base delay between attempts
        backoff_strategy: Backoff strategy to use
        **config_kwargs: Additional configuration parameters

    Returns:
        Decorated function
    """
    def decorator(func):
        config = RetryConfig(
            max_attempts=max_attempts,
            base_delay_seconds=base_delay_seconds,
            backoff_strategy=backoff_strategy,
            **config_kwargs
        )

        retry_policy = RetryPolicy(config, func.__name__)

        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                return await retry_policy.execute(func, *args, **kwargs)
            return async_wrapper
        else:
            async def sync_wrapper(*args, **kwargs):
                return await retry_policy.execute(func, *args, **kwargs)
            return sync_wrapper

    return decorator


# Export components
__all__ = [
    "RetryPolicy",
    "RetryConfig",
    "BackoffStrategy",
    "RetryAttempt",
    "RetryMetrics",
    "BackoffCalculator",
    "retry"
]