"""Client-side metrics helpers for CLI commands."""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

_DEFAULT_MONITORING_URL = os.getenv("BR_MONITORING_API", "http://localhost:8100")


def _build_endpoint(path: str) -> str:
    base = _DEFAULT_MONITORING_URL.rstrip("/")
    return f"{base}{path}"


def record_cli_command_metric(
    command: str,
    *,
    duration_ms: float,
    status: str,
    job_kind: str,
    timeout: float = 1.0,
) -> None:
    """Best-effort POST of CLI metrics to the monitoring service."""
    payload = {
        "command": command,
        "duration_ms": duration_ms,
        "status": status,
        "job_kind": job_kind,
    }
    url = _build_endpoint("/metrics/cli")
    try:
        httpx.post(url, json=payload, timeout=timeout)
    except Exception:
        # Non-blocking: metrics ingestion should never break CLI
        return
