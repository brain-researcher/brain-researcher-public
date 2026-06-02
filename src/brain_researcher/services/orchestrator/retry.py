"""Core retry logic for P2.6 Shared Retry/Backoff Taxonomy.

This module provides the retry decision engine that:
- Classifies failures into categories
- Computes exponential backoff with jitter
- Determines if a job should be retried
"""

import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from brain_researcher.config.retry_settings import RetrySettings, get_retry_settings

logger = logging.getLogger(__name__)

# P2.6 Retry Metrics (structured logging for monitoring)
# These can be ingested by Prometheus, Datadog, or other monitoring systems


def _log_retry_metric(metric_name: str, category: str, value: float = 1.0, **labels):
    """
    Log structured retry metric for monitoring systems.

    Metrics can be scraped by Prometheus, Datadog, or similar systems.

    Args:
        metric_name: Metric name (e.g., 'retry_attempts_total')
        category: Error category
        value: Metric value (default 1.0 for counters)
        **labels: Additional labels
    """
    logger.info(
        f"METRIC: {metric_name}",
        extra={
            "metric_name": metric_name,
            "category": category,
            "value": value,
            **labels,
        },
    )


@dataclass
class RetryDecision:
    """Decision about whether and how to retry a failed job."""

    should_retry: bool
    reason: str
    category: str
    delay_seconds: int
    next_retry_at: Optional[datetime]
    attempt: int
    max_attempts: int
    metadata: dict

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "should_retry": self.should_retry,
            "reason": self.reason,
            "category": self.category,
            "delay_seconds": self.delay_seconds,
            "next_retry_at": (
                self.next_retry_at.isoformat() if self.next_retry_at else None
            ),
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "metadata": self.metadata,
        }


def classify_failure(
    exit_code: int, stderr: str, settings: Optional[RetrySettings] = None
) -> str:
    """Classify a failure into a retry category.

    Args:
        exit_code: Process exit code
        stderr: Standard error output (last N lines)
        settings: Retry settings (loads default if None)

    Returns:
        Category name: 'timeout', 'transient_io', 'internal', 'oom', 'user_error', 'unknown'

    Example:
        >>> category = classify_failure(exit_code=124, stderr="Command timed out")
        >>> assert category == "timeout"
    """
    if settings is None:
        settings = get_retry_settings()

    if not settings.taxonomy:
        # No taxonomy loaded, classify basic cases only
        if exit_code == 124:
            return "timeout"
        elif exit_code == 137:
            return "oom"
        else:
            return "unknown"

    return settings.taxonomy.classify_error(exit_code, stderr or "")


def compute_backoff(
    attempt: int,
    base_delay: int,
    max_delay: int,
    jitter_percent: int,
    seed: Optional[str] = None,
) -> int:
    """Compute exponential backoff delay with jitter.

    Formula: delay = min(base * 2^(attempt-1), max_delay) * (1 ± jitter)

    Args:
        attempt: Current attempt number (1-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap in seconds
        jitter_percent: Jitter percentage (0-100)
        seed: Optional seed for deterministic jitter (e.g., job_id)

    Returns:
        Delay in seconds with jitter applied

    Example:
        >>> # Attempt 1: base_delay * 1 ± 20%
        >>> delay = compute_backoff(attempt=1, base_delay=10, max_delay=300, jitter_percent=20)
        >>> assert 8 <= delay <= 12  # 10 ± 20%

        >>> # Attempt 3: base_delay * 4 ± 20%
        >>> delay = compute_backoff(attempt=3, base_delay=10, max_delay=300, jitter_percent=20)
        >>> assert 32 <= delay <= 48  # 40 ± 20%
    """
    if attempt < 1:
        attempt = 1

    # Exponential backoff: base * 2^(attempt-1)
    exponential_delay = base_delay * (2 ** (attempt - 1))

    # Cap at max_delay
    capped_delay = min(exponential_delay, max_delay)

    # Apply jitter: ±jitter_percent
    if jitter_percent > 0:
        # Use seed for deterministic randomness if provided
        if seed:
            # Hash seed to get deterministic random value
            hash_value = int(hashlib.md5(seed.encode()).hexdigest(), 16)
            rng = random.Random(hash_value + attempt)
        else:
            rng = random

        jitter_factor = 1.0 + (rng.uniform(-jitter_percent, jitter_percent) / 100.0)
        jittered_delay = int(capped_delay * jitter_factor)

        return max(1, jittered_delay)  # Ensure at least 1 second
    else:
        return capped_delay


def should_retry(
    exit_code: int,
    stderr: str,
    attempt: int,
    job_id: Optional[str] = None,
    settings: Optional[RetrySettings] = None,
) -> RetryDecision:
    """Determine if a failed job should be retried and compute backoff.

    This is the main entry point for retry logic. It:
    1. Classifies the failure into a category
    2. Checks if category is retryable
    3. Checks if attempts remaining
    4. Computes backoff delay with jitter
    5. Returns structured decision

    Args:
        exit_code: Process exit code
        stderr: Standard error output
        attempt: Current attempt number (1-indexed)
        job_id: Optional job ID for deterministic jitter
        settings: Retry settings (loads default if None)

    Returns:
        RetryDecision with should_retry, delay, and metadata

    Example:
        >>> decision = should_retry(
        ...     exit_code=124,
        ...     stderr="timeout",
        ...     attempt=1,
        ...     job_id="job_abc123"
        ... )
        >>> assert decision.should_retry is True
        >>> assert decision.category == "timeout"
        >>> assert decision.delay_seconds > 0
    """
    if settings is None:
        settings = get_retry_settings()

    # Gate blocks are deterministic policy failures; never retry.
    stderr = stderr or ""
    stderr_l = stderr.lower()
    if "preflight blocked" in stderr_l or "postcheck blocked" in stderr_l:
        return RetryDecision(
            should_retry=False,
            reason="Gate blocked (non-retryable)",
            category="user_error",
            delay_seconds=0,
            next_retry_at=None,
            attempt=attempt,
            max_attempts=settings.max_attempts,
            metadata={
                "exit_code": exit_code,
                "stderr_snippet": stderr[:200],
            },
        )

    # Classify the failure
    category = classify_failure(exit_code, stderr, settings)

    # Get category-specific settings
    category_settings = settings.get_category_settings(category)
    max_attempts = category_settings["max_attempts"]
    base_delay = category_settings["base_delay"]
    max_delay = category_settings["max_delay"]

    # Check if retryable
    is_retryable = settings.is_retryable(category)

    # Build metadata
    metadata = {
        "exit_code": exit_code,
        "stderr_snippet": stderr[:200] if stderr else "",
        "category_settings": category_settings,
    }

    # Determine if we should retry
    if not settings.enabled:
        return RetryDecision(
            should_retry=False,
            reason="Retry system disabled (BR_RETRY_ENABLED=false)",
            category=category,
            delay_seconds=0,
            next_retry_at=None,
            attempt=attempt,
            max_attempts=max_attempts,
            metadata=metadata,
        )

    if not is_retryable:
        return RetryDecision(
            should_retry=False,
            reason=f"Category '{category}' is not retryable",
            category=category,
            delay_seconds=0,
            next_retry_at=None,
            attempt=attempt,
            max_attempts=max_attempts,
            metadata=metadata,
        )

    if attempt >= max_attempts:
        # P2.6 Metrics: Log retry exhaustion
        _log_retry_metric(
            "retry_exhausted_total",
            category=category,
            final_attempt=attempt,
            max_attempts=max_attempts,
        )
        return RetryDecision(
            should_retry=False,
            reason=f"Max attempts reached ({attempt}/{max_attempts})",
            category=category,
            delay_seconds=0,
            next_retry_at=None,
            attempt=attempt,
            max_attempts=max_attempts,
            metadata=metadata,
        )

    # Compute backoff delay
    delay_seconds = compute_backoff(
        attempt=attempt,
        base_delay=base_delay,
        max_delay=max_delay,
        jitter_percent=settings.jitter_percent,
        seed=job_id,
    )

    next_retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)

    # P2.6 Metrics: Log retry attempt and backoff delay
    _log_retry_metric(
        "retry_attempts_total",
        category=category,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    _log_retry_metric(
        "retry_backoff_seconds",
        category=category,
        value=float(delay_seconds),
        attempt=attempt,
    )

    return RetryDecision(
        should_retry=True,
        reason=f"Retrying {category} error (attempt {attempt}/{max_attempts})",
        category=category,
        delay_seconds=delay_seconds,
        next_retry_at=next_retry_at,
        attempt=attempt,
        max_attempts=max_attempts,
        metadata=metadata,
    )


def format_retry_summary(decision: RetryDecision) -> str:
    """Format a human-readable summary of a retry decision.

    Args:
        decision: RetryDecision to format

    Returns:
        Formatted string suitable for logging

    Example:
        >>> decision = should_retry(exit_code=124, stderr="timeout", attempt=2)
        >>> summary = format_retry_summary(decision)
        >>> print(summary)
        Retry timeout error: attempt 2/5, waiting 60s until 2025-11-05T23:30:00
    """
    if not decision.should_retry:
        return f"Not retrying: {decision.reason}"

    retry_time = (
        decision.next_retry_at.strftime("%Y-%m-%dT%H:%M:%S")
        if decision.next_retry_at
        else "unknown"
    )

    return (
        f"Retry {decision.category} error: "
        f"attempt {decision.attempt}/{decision.max_attempts}, "
        f"waiting {decision.delay_seconds}s until {retry_time}"
    )
