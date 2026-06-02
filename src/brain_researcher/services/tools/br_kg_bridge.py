"""Utility for calling the BR-KG API with retry logic."""

from __future__ import annotations

import time
from typing import Any

import requests


def post_with_retry(
    url: str, payload: dict[str, Any], retries: int = 3, backoff: float = 0.5
) -> dict[str, Any]:
    """Send POST request with retry on failure.

    Args:
        url: Endpoint URL.
        payload: JSON payload.
        retries: Number of retries on failure.
        backoff: Delay between retries in seconds (exponential).

    Returns:
        Result dictionary with ``status`` and either ``data`` or ``error``.
    """
    attempt = 0
    delay = backoff
    while True:
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}
        except Exception as e:  # pragma: no cover - network errors
            attempt += 1
            if attempt > retries:
                return {"status": "error", "error": str(e)}
            time.sleep(delay)
            delay *= 2
