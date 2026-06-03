"""
Environment-driven service endpoint configuration for the orchestrator.

Centralizes resolution of upstream service URLs so that every endpoint
module shares the same environment-aware defaults. This avoids hard-coded
localhost references when running inside Docker or other deployment targets.
"""

from __future__ import annotations

import os
from functools import cache

try:  # pragma: no cover - optional dependency
    from brain_researcher.core.utils import ensure_env_loaded

    ensure_env_loaded()
except Exception:
    pass


@cache
def _resolve_url(env_var: str, default: str) -> str:
    """Return a normalized service URL for the given environment variable."""
    value = os.getenv(env_var, default).strip()
    # Remove trailing slash to avoid accidental `//` when composing paths.
    return value[:-1] if value.endswith("/") else value


def _resolve_candidates(*env_vars: str, default: str) -> str:
    """Resolve the first populated service URL from an explicit env list."""

    for env_var in env_vars:
        value = os.getenv(env_var)
        if value and value.strip():
            return _resolve_url(env_var, value)
    return default[:-1] if default.endswith("/") else default


ORCHESTRATOR_URL = _resolve_candidates(
    "BR_ORCHESTRATOR_URL",
    "ORCHESTRATOR_URL",
    "ORCHESTRATOR_BASE_URL",
    "ORCHESTRATOR_API_URL",
    default="http://localhost:3001",
)
AGENT_URL = _resolve_candidates(
    "BR_AGENT_URL",
    "AGENT_URL",
    default="http://localhost:8000",
)
BR_KG_URL = _resolve_candidates(
    "BR_KG_URL",
    "BR_KG_URL",
    default="http://localhost:5000",
)
NICLIP_URL = _resolve_candidates(
    "BR_NICLIP_URL",
    "NICLIP_URL",
    default="http://localhost:8001",
)
WEB_UI_URL = _resolve_candidates(
    "BR_WEB_UI_URL",
    "WEB_UI_URL",
    default="http://localhost:3000",
)


@cache
def get_metrics_enabled() -> bool:
    """Check if Prometheus metrics are enabled."""
    return os.getenv("BR_METRICS_ENABLED", "true").lower() in {"1", "true", "yes"}


__all__ = [
    "AGENT_URL",
    "ORCHESTRATOR_URL",
    "BR_KG_URL",
    "NICLIP_URL",
    "WEB_UI_URL",
    "_resolve_url",
    "_resolve_candidates",
    "get_metrics_enabled",
]
