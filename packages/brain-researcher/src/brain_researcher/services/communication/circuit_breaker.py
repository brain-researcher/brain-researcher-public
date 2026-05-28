"""
Circuit Breaker Pattern Implementation.

Provides circuit breaker functionality to prevent cascade failures
in distributed systems by monitoring service calls and opening 
the circuit when failure thresholds are exceeded.
"""

import asyncio
import time
from typing import Optional, Callable, Any, Dict, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    
    CLOSED = "closed"        # Normal operation
    OPEN = "open"           # Circuit is open, failing fast
    HALF_OPEN = "half_open" # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 60.0
    half_open_max_calls: int = 3
    success_threshold: int = 2  # Successes needed to close from half-open
    timeout_seconds: float = 30.0
    exclude_exceptions: List[str] = None  # Exception types to ignore
    
    def __post_init__(self):
        if self.exclude_exceptions is None:
            self.exclude_exceptions = []


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""
    
    def __init__(self, message: str, circuit_name: str, last_failure: Optional[Exception] = None):
        super().__init__(message)
        self.circuit_name = circuit_name
        self.last_failure = last_failure


class CircuitBreakerMetrics:
    """Circuit breaker metrics and statistics."""
    
    def __init__(self):
        """Initialize metrics."""
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_call_time: Optional[datetime] = None
        self.last_failure_time: Optional[datetime] = None
        self.last_success_time: Optional[datetime] = None
        self.state_transitions: List[Dict[str, Any]] = []
        
    def record_call(self):
        """Record a call attempt."""
        self.total_calls += 1
        self.last_call_time = datetime.utcnow()
    
    def record_success(self):
        """Record a successful call."""
        self.successful_calls += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = datetime.utcnow()
    
    def record_failure(self):
        """Record a failed call."""
        self.failed_calls += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = datetime.utcnow()
    
    def record_state_change(self, from_state: CircuitState, to_state: CircuitState, reason: str = ""):
        """Record state transition."""
        self.state_transitions.append({
            "from": from_state.value,
            "to": to_state.value,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
            "total_calls": self.total_calls,
            "failure_rate": self.get_failure_rate()
        })
    
    def get_failure_rate(self) -> float:
        """Calculate failure rate."""
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls
    
    def get_success_rate(self) -> float:
        """Calculate success rate."""
        return 1.0 - self.get_failure_rate()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "failure_rate": self.get_failure_rate(),
            "success_rate": self.get_success_rate(),
            "last_call_time": self.last_call_time.isoformat() if self.last_call_time else None,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "recent_state_transitions": self.state_transitions[-10:]  # Last 10 transitions
        }


class CircuitBreaker:
    """Circuit breaker implementation."""
    
    def __init__(self, config: CircuitBreakerConfig, name: str = "default"):
        """Initialize circuit breaker.
        
        Args:
            config: Circuit breaker configuration
            name: Circuit breaker name for identification
        """
        self.config = config
        self.name = name
        self.state = CircuitState.CLOSED
        self.metrics = CircuitBreakerMetrics()
        self.last_failure_time = 0.0
        self.last_failure: Optional[Exception] = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()
        
        logger.info(f"Circuit breaker '{name}' initialized with config: {config}")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: When circuit is open
            Exception: Original exception from function
        """
        async with self._lock:
            # Check if circuit should be opened
            await self._update_state()
            
            # If circuit is open, fail fast
            if self.state == CircuitState.OPEN:
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is OPEN",
                    self.name,
                    self.last_failure
                )
            
            # If half-open, check if we've reached max calls
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN with max calls reached",
                        self.name,
                        self.last_failure
                    )
                self.half_open_calls += 1
        
        # Record call attempt
        self.metrics.record_call()
        
        try:
            # Execute function with timeout
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.config.timeout_seconds
                )
            else:
                result = func(*args, **kwargs)
            
            # Record success
            async with self._lock:
                await self._on_success()
            
            return result
            
        except Exception as e:
            # Check if exception should be excluded
            if self._should_exclude_exception(e):
                logger.debug(f"Excluding exception from circuit breaker: {type(e).__name__}")
                raise
            
            # Record failure
            async with self._lock:
                await self._on_failure(e)
            
            raise
    
    def is_open(self) -> bool:
        """Check if circuit breaker is open."""
        return self.state == CircuitState.OPEN
    
    def is_closed(self) -> bool:
        """Check if circuit breaker is closed."""
        return self.state == CircuitState.CLOSED
    
    def is_half_open(self) -> bool:
        """Check if circuit breaker is half-open."""
        return self.state == CircuitState.HALF_OPEN
    
    def get_state(self) -> CircuitState:
        """Get current circuit breaker state."""
        return self.state
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics."""
        metrics_dict = self.metrics.to_dict()
        metrics_dict.update({
            "name": self.name,
            "state": self.state.value,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout_seconds": self.config.recovery_timeout_seconds,
                "half_open_max_calls": self.config.half_open_max_calls,
                "success_threshold": self.config.success_threshold,
                "timeout_seconds": self.config.timeout_seconds
            }
        })
        return metrics_dict
    
    async def reset(self):
        """Reset circuit breaker to closed state."""
        async with self._lock:
            old_state = self.state
            self.state = CircuitState.CLOSED
            self.metrics.consecutive_failures = 0
            self.metrics.consecutive_successes = 0
            self.half_open_calls = 0
            self.last_failure = None
            self.last_failure_time = 0.0
            
            self.metrics.record_state_change(old_state, self.state, "Manual reset")
            logger.info(f"Circuit breaker '{self.name}' manually reset to CLOSED")
    
    async def force_open(self, reason: str = "Manual"):
        """Force circuit breaker to open state."""
        async with self._lock:
            old_state = self.state
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()
            
            self.metrics.record_state_change(old_state, self.state, f"Forced open: {reason}")
            logger.warning(f"Circuit breaker '{self.name}' forced to OPEN: {reason}")
    
    async def _update_state(self):
        """Update circuit breaker state based on current conditions."""
        now = time.time()
        
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if now - self.last_failure_time >= self.config.recovery_timeout_seconds:
                old_state = self.state
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                self.metrics.record_state_change(
                    old_state, 
                    self.state, 
                    f"Recovery timeout ({self.config.recovery_timeout_seconds}s) elapsed"
                )
                logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN")
    
    async def _on_success(self):
        """Handle successful call."""
        self.metrics.record_success()
        
        if self.state == CircuitState.HALF_OPEN:
            # Check if we have enough successes to close the circuit
            if self.metrics.consecutive_successes >= self.config.success_threshold:
                old_state = self.state
                self.state = CircuitState.CLOSED
                self.half_open_calls = 0
                self.metrics.record_state_change(
                    old_state, 
                    self.state, 
                    f"Success threshold ({self.config.success_threshold}) reached"
                )
                logger.info(f"Circuit breaker '{self.name}' transitioned to CLOSED")
    
    async def _on_failure(self, exception: Exception):
        """Handle failed call."""
        self.metrics.record_failure()
        self.last_failure = exception
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            # Check if we've reached the failure threshold
            if self.metrics.consecutive_failures >= self.config.failure_threshold:
                old_state = self.state
                self.state = CircuitState.OPEN
                self.metrics.record_state_change(
                    old_state, 
                    self.state, 
                    f"Failure threshold ({self.config.failure_threshold}) exceeded"
                )
                logger.warning(f"Circuit breaker '{self.name}' transitioned to OPEN due to failures")
        
        elif self.state == CircuitState.HALF_OPEN:
            # Any failure in half-open state reopens the circuit
            old_state = self.state
            self.state = CircuitState.OPEN
            self.half_open_calls = 0
            self.metrics.record_state_change(
                old_state, 
                self.state, 
                "Failure in HALF_OPEN state"
            )
            logger.warning(f"Circuit breaker '{self.name}' reopened due to failure in HALF_OPEN state")
    
    def _should_exclude_exception(self, exception: Exception) -> bool:
        """Check if exception should be excluded from circuit breaker logic."""
        exception_name = type(exception).__name__
        return exception_name in self.config.exclude_exceptions
    
    def record_success(self):
        """Manually record a success (for external use)."""
        asyncio.create_task(self._record_success_async())
    
    def record_failure(self):
        """Manually record a failure (for external use)."""
        asyncio.create_task(self._record_failure_async())
    
    async def _record_success_async(self):
        """Async wrapper for manual success recording."""
        async with self._lock:
            await self._on_success()
    
    async def _record_failure_async(self):
        """Async wrapper for manual failure recording."""
        async with self._lock:
            await self._on_failure(Exception("Manual failure"))


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""
    
    def __init__(self):
        """Initialize circuit breaker registry."""
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._default_config = CircuitBreakerConfig()
    
    def get_circuit_breaker(
        self, 
        name: str, 
        config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """Get or create circuit breaker.
        
        Args:
            name: Circuit breaker name
            config: Circuit breaker configuration
            
        Returns:
            Circuit breaker instance
        """
        if name not in self._circuit_breakers:
            cb_config = config or self._default_config
            self._circuit_breakers[name] = CircuitBreaker(cb_config, name)
        
        return self._circuit_breakers[name]
    
    def remove_circuit_breaker(self, name: str):
        """Remove circuit breaker from registry.
        
        Args:
            name: Circuit breaker name
        """
        if name in self._circuit_breakers:
            del self._circuit_breakers[name]
    
    def list_circuit_breakers(self) -> List[str]:
        """List all circuit breaker names.
        
        Returns:
            List of circuit breaker names
        """
        return list(self._circuit_breakers.keys())
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers.
        
        Returns:
            Dictionary of circuit breaker metrics
        """
        return {
            name: cb.get_metrics() 
            for name, cb in self._circuit_breakers.items()
        }
    
    async def reset_all(self):
        """Reset all circuit breakers."""
        for cb in self._circuit_breakers.values():
            await cb.reset()
    
    def set_default_config(self, config: CircuitBreakerConfig):
        """Set default configuration for new circuit breakers.
        
        Args:
            config: Default circuit breaker configuration
        """
        self._default_config = config


# Global circuit breaker registry instance
_global_registry = CircuitBreakerRegistry()


def get_circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
    """Get circuit breaker from global registry.
    
    Args:
        name: Circuit breaker name
        config: Optional configuration
        
    Returns:
        Circuit breaker instance
    """
    return _global_registry.get_circuit_breaker(name, config)


def circuit_breaker(
    name: Optional[str] = None,
    config: Optional[CircuitBreakerConfig] = None
):
    """Decorator for applying circuit breaker to functions.
    
    Args:
        name: Circuit breaker name (defaults to function name)
        config: Circuit breaker configuration
        
    Returns:
        Decorated function
    """
    def decorator(func):
        cb_name = name or func.__name__
        cb = get_circuit_breaker(cb_name, config)
        
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                return await cb.call(func, *args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                return asyncio.run(cb.call(func, *args, **kwargs))
            return sync_wrapper
    
    return decorator


# Export components
__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig", 
    "CircuitBreakerError",
    "CircuitBreakerMetrics",
    "CircuitBreakerRegistry",
    "CircuitState",
    "get_circuit_breaker",
    "circuit_breaker"
]