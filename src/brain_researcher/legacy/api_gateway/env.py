"""
Environment-driven configuration helpers for the API gateway.

Centralizes the resolution of upstream service URLs so the gateway can
connect correctly in Docker, local dev, or custom deployments without
hard-coded localhost defaults.
"""

from __future__ import annotations

import os
from functools import lru_cache

try:  # pragma: no cover - optional dependency
    from brain_researcher.core.utils import ensure_env_loaded

    ensure_env_loaded()
except Exception:
    pass


@lru_cache(maxsize=None)
def _resolve_url(env_var: str, default: str) -> str:
    """Return a normalized URL for the given environment variable."""
    value = os.getenv(env_var, default).strip()
    return value[:-1] if value.endswith("/") else value


ORCHESTRATOR_URL = _resolve_url("ORCHESTRATOR_URL", "http://orchestrator:3001")
AGENT_URL = _resolve_url("AGENT_URL", "http://agent:8000")
BR_KG_URL = _resolve_url("BR_KG_URL", "http://br_kg:5000")
NICLIP_URL = _resolve_url("NICLIP_URL", "http://niclip:8001")
REDIS_URL = _resolve_url("REDIS_URL", "redis://redis:6379/0")


__all__ = [
    "ORCHESTRATOR_URL",
    "AGENT_URL",
    "BR_KG_URL",
    "NICLIP_URL",
    "REDIS_URL",
    "_resolve_url",
]
