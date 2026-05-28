from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, TypeVar


T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout_sec: int = 60) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_timeout_sec = max(1, int(recovery_timeout_sec))
        self._failures = 0
        self._last_failure_ts = 0.0
        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.time()

    def _should_half_open(self) -> bool:
        return (self._now() - self._last_failure_ts) >= self.recovery_timeout_sec

    def call(self, func: Callable[[], T]) -> T:
        with self._lock:
            if self._state == CircuitState.OPEN and not self._should_half_open():
                raise RuntimeError("Circuit breaker is OPEN")
            if self._state == CircuitState.OPEN and self._should_half_open():
                self._state = CircuitState.HALF_OPEN

        try:
            result = func()
            with self._lock:
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.CLOSED
                self._failures = 0
            return result
        except Exception:
            with self._lock:
                self._failures += 1
                self._last_failure_ts = self._now()
                if self._failures >= self.failure_threshold:
                    self._state = CircuitState.OPEN
            raise

