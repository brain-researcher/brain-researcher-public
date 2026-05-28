"""
JobStore Factory: Initialize JobStore based on configuration.

Supports:
- memory: In-memory dict (default, for development)
- sqlite: SQLite WAL mode (persistent, for production)
- dual: Dual-write to memory+SQLite (for validation)
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from brain_researcher.config.paths import get_data_root

from .job_store import JobStore
from .memory_job_store import MemoryJobStore

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _is_truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUE_VALUES


def _strict_sqlite_required(backend: str) -> bool:
    """Whether sqlite backend failures should hard-fail instead of falling back.

    Priority:
    1. BR_STRICT_SQLITE_BACKEND env var (explicit override)
    2. Production runtime detection via APP_ENV / ENV
    """
    if backend not in {"sqlite", "dual"}:
        return False

    strict_env = os.getenv("BR_STRICT_SQLITE_BACKEND")
    if strict_env is not None:
        return _is_truthy(strict_env)

    runtime_env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    return runtime_env in {"prod", "production"}


def get_job_store(
    backend: Optional[str] = None,
    db_path: Optional[str] = None,
    total_gpu_slots: int = 2
) -> JobStore:
    """
    Get JobStore implementation based on configuration.

    Args:
        backend: Backend type ('memory', 'sqlite', 'dual'). If None, reads from BR_QUEUE_BACKEND env var.
        db_path: SQLite database path. If None, reads from BR_QUEUE_DB env var.
        total_gpu_slots: Number of GPU slots available. Defaults to 2.

    Returns:
        JobStore implementation

    Raises:
        ValueError: If backend is unknown

    Environment Variables:
        BR_QUEUE_BACKEND: Queue backend type (default: 'memory')
        BR_QUEUE_DB_PATH: SQLite database path (preferred)
        BR_QUEUE_DB: SQLite database path (fallback, default: '<repo>/data/orchestrator/jobs.sqlite')
        BR_STRICT_SQLITE_BACKEND: Force hard-fail when sqlite backend cannot initialize.
        BR_TOTAL_GPU_SLOTS: Number of GPU slots (default: 2)

    Examples:
        # Development: in-memory
        export BR_QUEUE_BACKEND=memory
        job_store = get_job_store()

        # Production: persistent SQLite
        export BR_QUEUE_BACKEND=sqlite
        export BR_QUEUE_DB=/var/lib/brain-researcher/jobs.sqlite
        job_store = get_job_store()

        # Validation: dual-write
        export BR_QUEUE_BACKEND=dual
        job_store = get_job_store()
    """
    # Read from environment
    if backend is None:
        backend = os.getenv('BR_QUEUE_BACKEND', 'memory')

    if db_path is None:
        db_path = (
            os.getenv('BR_QUEUE_DB_PATH')
            or os.getenv('BR_QUEUE_DB')
            or str(get_data_root() / "orchestrator" / "jobs.sqlite")
        )

    # Read GPU slots from env
    total_gpu_slots = int(os.getenv('BR_TOTAL_GPU_SLOTS', str(total_gpu_slots)))

    backend = backend.lower()
    logger.info(f"Initializing JobStore with backend={backend}, gpu_slots={total_gpu_slots}")

    if backend == 'memory':
        return MemoryJobStore(total_gpu_slots=total_gpu_slots)

    elif backend == 'sqlite':
        # Import here to avoid circular dependency
        try:
            from .sqlite_job_store import SqliteJobStore
            # Note: SqliteJobStore requires async initialize() - caller must await it
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            busy_timeout = int(os.getenv('BR_SQLITE_BUSY_TIMEOUT_MS', '5000'))
            store = SqliteJobStore(
                db_path=db_path,
                total_gpu_slots=total_gpu_slots,
                busy_timeout_ms=busy_timeout
            )
            logger.warning("SqliteJobStore created but not initialized. Caller must await store.initialize()")
            return store
        except ImportError as e:
            msg = f"SqliteJobStore import failed: {e}."
            if _strict_sqlite_required(backend):
                logger.critical(
                    "%s Strict sqlite mode enabled; refusing fallback to MemoryJobStore.",
                    msg,
                )
                raise RuntimeError(
                    f"{msg} Strict sqlite mode is enabled; refusing fallback to MemoryJobStore."
                ) from e
            logger.error("%s Falling back to MemoryJobStore.", msg)
            return MemoryJobStore(total_gpu_slots=total_gpu_slots)

    elif backend == 'dual':
        # Dual-write for validation
        try:
            from .sqlite_job_store import SqliteJobStore, DualJobStore

            memory = MemoryJobStore(total_gpu_slots=total_gpu_slots)
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            busy_timeout = int(os.getenv('BR_SQLITE_BUSY_TIMEOUT_MS', '5000'))
            sqlite = SqliteJobStore(
                db_path=db_path,
                total_gpu_slots=total_gpu_slots,
                busy_timeout_ms=busy_timeout
            )
            logger.warning("DualJobStore created. Caller must await sqlite.initialize() before use.")
            return DualJobStore(primary=memory, secondary=sqlite)
        except ImportError as e:
            msg = f"DualJobStore import failed: {e}."
            if _strict_sqlite_required(backend):
                logger.critical(
                    "%s Strict sqlite mode enabled; refusing fallback to MemoryJobStore.",
                    msg,
                )
                raise RuntimeError(
                    f"{msg} Strict sqlite mode is enabled; refusing fallback to MemoryJobStore."
                ) from e
            logger.error("%s Falling back to MemoryJobStore.", msg)
            return MemoryJobStore(total_gpu_slots=total_gpu_slots)

    else:
        raise ValueError(f"Unknown JobStore backend: {backend}. Expected 'memory', 'sqlite', or 'dual'.")


# Global instance (singleton pattern)
_job_store_instance: Optional[JobStore] = None


def initialize_job_store(
    backend: Optional[str] = None,
    db_path: Optional[str] = None,
    total_gpu_slots: int = 2
) -> JobStore:
    """
    Initialize global JobStore instance.

    Should be called once at orchestrator startup.

    Args:
        backend: Backend type
        db_path: SQLite database path
        total_gpu_slots: Number of GPU slots

    Returns:
        Initialized JobStore instance
    """
    global _job_store_instance

    if _job_store_instance is not None:
        logger.warning("JobStore already initialized. Returning existing instance.")
        return _job_store_instance

    _job_store_instance = get_job_store(backend, db_path, total_gpu_slots)
    logger.info(f"JobStore initialized: {type(_job_store_instance).__name__}")

    return _job_store_instance


def get_initialized_job_store() -> JobStore:
    """
    Get the initialized JobStore instance.

    Returns:
        JobStore instance

    Raises:
        RuntimeError: If JobStore not initialized
    """
    global _job_store_instance

    if _job_store_instance is None:
        # Auto-initialize with defaults
        logger.warning("JobStore not explicitly initialized. Auto-initializing with defaults.")
        _job_store_instance = get_job_store()

    return _job_store_instance


def peek_initialized_job_store() -> Optional[JobStore]:
    """Return the global JobStore instance if set (no auto-initialize)."""
    return _job_store_instance


def set_initialized_job_store(job_store: JobStore) -> JobStore:
    """Set the global JobStore instance.

    This is primarily used by single-process compatibility deployments that
    co-host the agent and orchestrator in the same Python process. The
    orchestrator is responsible for constructing and (optionally) initializing
    the JobStore, then calling this setter so agent endpoints share the same
    instance.
    """
    global _job_store_instance
    _job_store_instance = job_store
    logger.info("JobStore instance set: %s", type(job_store).__name__)
    return _job_store_instance
