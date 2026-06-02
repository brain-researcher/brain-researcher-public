"""State store factory for durable UI state.

This is intentionally separate from JobStore. It persists *UI/control-plane*
state that should survive restarts (threads/messages, notifications, share
tokens), while JobStore remains the source of truth for execution jobs.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from brain_researcher.config.paths import get_data_root

from .sqlite_state_store import SqliteStateStore

logger = logging.getLogger(__name__)

_STATE_STORE: Optional[SqliteStateStore] = None
_STATE_STORE_LOCK = asyncio.Lock()


def state_store_enforced() -> bool:
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    if env in {"prod", "production"}:
        return True
    enforce = os.getenv("BR_STATE_STORE_ENFORCE")
    if enforce is None:
        return False
    return enforce.strip().lower() in {"1", "true", "yes", "y", "on"}


def state_store_enabled() -> bool:
    if os.getenv("BR_STATE_DB"):
        return True
    enabled = os.getenv("BR_STATE_STORE_ENABLED")
    if enabled is None:
        return state_store_enforced()
    return enabled.strip().lower() in {"1", "true", "yes", "y", "on"}


def resolve_state_db_path() -> str:
    # Prefer explicit state DB. Fall back to job DB if configured.
    return (
        os.getenv("BR_STATE_DB")
        or os.getenv("BR_QUEUE_DB_PATH")
        or os.getenv("BR_QUEUE_DB")
        or str(get_data_root() / "orchestrator" / "state.sqlite")
    )


async def get_state_store() -> Optional[SqliteStateStore]:
    """Return the singleton state store instance (initialized) when enabled."""
    if not state_store_enabled():
        return None

    global _STATE_STORE
    if _STATE_STORE is not None:
        return _STATE_STORE

    async with _STATE_STORE_LOCK:
        if _STATE_STORE is not None:
            return _STATE_STORE

        db_path = resolve_state_db_path()
        busy_timeout_ms = int(os.getenv("BR_SQLITE_BUSY_TIMEOUT_MS", "5000"))
        store = SqliteStateStore(db_path=db_path, busy_timeout_ms=busy_timeout_ms)
        await store.initialize()
        _STATE_STORE = store
        logger.info("State store enabled (db_path=%s)", db_path)
        return _STATE_STORE
