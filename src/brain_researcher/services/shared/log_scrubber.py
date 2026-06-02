"""Lightweight secret scrubbing utilities for logs and error payloads."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

_PATTERNS: List[tuple[re.Pattern[str], str]] = [
    # Common key/value secrets
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*([^\s,;'\"\\]+)"
        ),
        r"\1=***REDACTED***",
    ),
    # Bearer tokens
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
        "Bearer ***REDACTED***",
    ),
    # JWTs
    (
        re.compile(r"eyJ[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+"),
        "***REDACTED***",
    ),
    # AWS access key ids
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "***REDACTED***",
    ),
]


def scrub_text(text: str) -> str:
    """Redact secret-like tokens from free-form text."""
    scrubbed = text
    for pattern, replacement in _PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def scrub_data(value: Any) -> Any:
    """Recursively scrub strings inside dict/list structures."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: scrub_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_data(v) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub_data(v) for v in value)
    return value


__all__ = ["scrub_text", "scrub_data"]
