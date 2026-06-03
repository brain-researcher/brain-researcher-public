"""
Background tasks for the orchestrator service.

This module provides background maintenance tasks for job queue management,
including the SQLite sweeper for recovering stale jobs.
"""

import asyncio
import logging
import os
import time
from collections.abc import Mapping
from typing import Any

from .job_store import JobState, JobStore

logger = logging.getLogger(__name__)


async def sqlite_sweeper_loop(
    job_store: JobStore,
    interval_secs: int = 30,
    stop_event: asyncio.Event | None = None,
) -> None:
    """
    Background task to periodically recover stale jobs with expired leases.

    This sweeper runs only for SQLite and dual backends to requeue jobs that have
    expired leases (workers died, network issues, etc.). It's critical for ensuring
    jobs don't get stuck in CLAIMED or RUNNING state forever.

    Args:
        job_store: JobStore instance to perform recovery on
        interval_secs: How often to run recovery sweep (default: 30s)
        stop_event: Optional asyncio.Event to signal graceful shutdown

    Environment Variables:
        BR_QUEUE_SWEEP_INTERVAL_SECS: Override sweep interval (default: 30)

    Example:
        # In main_enhanced.py lifespan:
        stop_event = asyncio.Event()
        sweeper_task = asyncio.create_task(
            sqlite_sweeper_loop(job_store, interval_secs=30, stop_event=stop_event)
        )

        yield

        # Shutdown
        stop_event.set()
        await sweeper_task
    """
    logger.info(f"SQLite sweeper started with interval={interval_secs}s")

    # Track consecutive failures for exponential backoff
    consecutive_failures = 0
    max_failures_before_warning = 3

    try:
        while True:
            # Check for shutdown signal
            if stop_event and stop_event.is_set():
                logger.info("SQLite sweeper received shutdown signal")
                break

            try:
                # Run recovery sweep
                now_ts = int(time.time())
                stats = await job_store.recover_stale_jobs(now_ts=now_ts)

                # Log results if any jobs were recovered
                recovered = stats.get("recovered", stats.get("jobs_requeued", 0))
                gpus_freed = stats.get("gpus_freed", 0)

                if recovered > 0:
                    logger.warning(
                        f"SQLite sweeper recovered {recovered} stale jobs, freed {gpus_freed} GPU slots"
                    )
                else:
                    logger.debug("SQLite sweeper found no stale jobs (healthy)")

                # Update queue depth metrics (P5.11)
                try:
                    from .metrics import get_metrics_collector

                    metrics = get_metrics_collector()
                    queue_stats = await job_store.get_queue_stats()
                    state_counts = _render_state_counts(queue_stats)
                    if state_counts:
                        metrics.update_queue_depth(state_counts)
                except Exception as e:
                    logger.debug(f"Failed to update queue depth metrics: {e}")

                # Reset failure counter on success
                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1

                if consecutive_failures >= max_failures_before_warning:
                    logger.error(
                        f"SQLite sweeper failed {consecutive_failures} times in a row: {e}",
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        f"SQLite sweeper error (attempt {consecutive_failures}): {e}"
                    )

            # Sleep until next sweep (with periodic wake-ups to check stop_event)
            # Use shorter sleep intervals to allow responsive shutdown
            sleep_interval = min(interval_secs, 5)
            elapsed = 0

            while elapsed < interval_secs:
                if stop_event and stop_event.is_set():
                    break

                await asyncio.sleep(sleep_interval)
                elapsed += sleep_interval

    except asyncio.CancelledError:
        logger.info("SQLite sweeper cancelled")
        raise
    finally:
        logger.info("SQLite sweeper stopped")


def should_enable_sweeper(backend: str) -> bool:
    """
    Determine if the SQLite sweeper should be enabled for the given backend.

    Args:
        backend: Queue backend type ('memory', 'sqlite', 'dual')

    Returns:
        True if sweeper should run, False otherwise

    Examples:
        >>> should_enable_sweeper('memory')
        False
        >>> should_enable_sweeper('sqlite')
        True
        >>> should_enable_sweeper('dual')
        True
    """
    return backend.lower() in ("sqlite", "dual")


async def start_sqlite_sweeper(
    job_store: JobStore, backend: str, stop_event: asyncio.Event | None = None
) -> asyncio.Task | None:
    """
    Start the SQLite sweeper task if backend requires it.

    This is a convenience function for starting the sweeper conditionally based
    on the backend type. Returns None if sweeper not needed.

    Args:
        job_store: JobStore instance
        backend: Queue backend type
        stop_event: Optional event for shutdown signaling

    Returns:
        asyncio.Task if sweeper started, None otherwise

    Example:
        # In main_enhanced.py:
        sweeper_task = await start_sqlite_sweeper(
            job_store=job_store,
            backend=backend,
            stop_event=stop_event
        )
    """
    if not should_enable_sweeper(backend):
        logger.info(f"SQLite sweeper not needed for backend={backend}")
        return None

    # Get sweep interval from environment
    interval_secs = int(os.getenv("BR_QUEUE_SWEEP_INTERVAL_SECS", "30"))

    logger.info(
        f"Starting SQLite sweeper for backend={backend}, interval={interval_secs}s"
    )

    # Create and return task
    task = asyncio.create_task(
        sqlite_sweeper_loop(
            job_store=job_store, interval_secs=interval_secs, stop_event=stop_event
        )
    )

    return task


def _render_state_counts(queue_stats: Any) -> dict[str, int]:
    """
    Normalize per-state counts from heterogeneous JobStore stats payloads.

    SQLite returns {\"by_state\": {...}} while the in-memory store returns the counts
    inline along with GPU metadata. This helper extracts only the job state entries
    and ensures all JobState values exist so gauges can be zeroed when empty.
    """
    counts: dict[str, int] = {}
    source: Mapping[Any, Any] | None = None

    if isinstance(queue_stats, Mapping):
        by_state = queue_stats.get("by_state")
        if isinstance(by_state, Mapping):
            source = by_state
        else:
            source = queue_stats

    if source:
        ignored = {
            "gpu_total",
            "gpu_in_use",
            "gpu_available",
            "oldest_pending_age_sec",
            "active_workers",
            "total_jobs",
        }
        for key, value in source.items():
            if isinstance(key, str) and key in ignored:
                continue
            if not isinstance(value, int | float):
                continue
            state_name = key.value if isinstance(key, JobState) else str(key)
            counts[state_name] = int(value)

    for state in JobState:
        counts.setdefault(state.value, 0)

    return counts
