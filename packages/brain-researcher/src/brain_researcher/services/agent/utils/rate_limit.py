from __future__ import annotations

import threading
import time
from collections import deque


class RateLimitExceeded(Exception):
    pass


class TokenBucketRateLimiter:
    """Thread-safe token bucket for RPS and RPM limits.

    Non-blocking acquire: raises RateLimitExceeded when limits are hit.
    """

    def __init__(self, rps: int = 30, rpm: int = 300) -> None:
        self.rps = max(1, int(rps))
        self.rpm = max(1, int(rpm))
        self._sec = deque(maxlen=self.rps)
        self._min = deque(maxlen=self.rpm)
        self._lock = threading.Lock()

    def try_acquire(self) -> None:
        now = time.time()
        with self._lock:
            # Clean old timestamps
            while self._sec and now - self._sec[0] > 1.0:
                self._sec.popleft()
            while self._min and now - self._min[0] > 60.0:
                self._min.popleft()

            if len(self._sec) >= self.rps or len(self._min) >= self.rpm:
                raise RateLimitExceeded("Local rate limit exceeded")

            self._sec.append(now)
            self._min.append(now)

