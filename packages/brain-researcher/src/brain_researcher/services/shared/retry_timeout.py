"""Shared retry/timeout configuration for agent + orchestrator."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, Field


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


class RetryConfig(BaseModel):
    """Retry configuration for service calls (milliseconds)."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay_ms: int = Field(default=1000, ge=100)
    max_delay_ms: int = Field(default=30000, le=60000)
    exponential_base: float = Field(default=2.0, ge=1.0, le=3.0)
    jitter: bool = True


class TimeoutConfig(BaseModel):
    """Timeout configuration for various operations (milliseconds)."""

    default_timeout_ms: int = Field(default=30000)
    agent_timeout_ms: int = Field(default=60000)
    dataset_timeout_ms: int = Field(default=10000)
    file_upload_timeout_ms: int = Field(default=120000)
    websocket_ping_interval_ms: int = Field(default=30000)
    sse_keepalive_interval_ms: int = Field(default=30000)
    tool_execution_budget_ms: int = Field(default=90000)


@lru_cache(maxsize=1)
def load_retry_config() -> RetryConfig:
    """Load retry configuration from environment with sane defaults."""

    return RetryConfig(
        max_attempts=_get_int("BR_RETRY_MAX_ATTEMPTS", 3),
        initial_delay_ms=_get_int("BR_RETRY_INITIAL_DELAY_MS", 1000),
        max_delay_ms=_get_int("BR_RETRY_MAX_DELAY_MS", 30000),
        exponential_base=_get_float("BR_RETRY_EXPONENTIAL_BASE", 2.0),
        jitter=_get_bool("BR_RETRY_JITTER", True),
    )


@lru_cache(maxsize=1)
def load_timeout_config() -> TimeoutConfig:
    """Load timeout configuration from environment with sane defaults."""

    return TimeoutConfig(
        default_timeout_ms=_get_int("BR_TIMEOUT_DEFAULT_MS", 30000),
        agent_timeout_ms=_get_int("BR_TIMEOUT_AGENT_MS", 60000),
        dataset_timeout_ms=_get_int("BR_TIMEOUT_DATASET_MS", 10000),
        file_upload_timeout_ms=_get_int("BR_TIMEOUT_FILE_UPLOAD_MS", 120000),
        websocket_ping_interval_ms=_get_int("BR_TIMEOUT_WEBSOCKET_PING_MS", 30000),
        sse_keepalive_interval_ms=_get_int("BR_TIMEOUT_SSE_KEEPALIVE_MS", 30000),
        tool_execution_budget_ms=_get_int("BR_TIMEOUT_TOOL_BUDGET_MS", 90000),
    )


__all__ = ["RetryConfig", "TimeoutConfig", "load_retry_config", "load_timeout_config"]
