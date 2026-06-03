"""
Prometheus metrics collector for Brain Researcher orchestrator.

Exposes core metrics for job lifecycle, cache performance, and queue monitoring.
MVP implementation with 5 essential metrics to support operational observability.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Orchestrator Prometheus metrics collector (MVP).

    Collects and exposes 5 core metrics:
    1. Job enqueue counter
    2. Job completion counter
    3. Job duration histogram
    4. Cache operations counter
    5. Queue depth gauge

    When disabled (BR_METRICS_ENABLED=false), all methods become no-ops.
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize metrics collector.

        Args:
            enabled: If False, collector becomes no-op (no metrics collected)
        """
        self.enabled = enabled
        self.prom_jobs_enqueued = None
        self.prom_jobs_completed = None
        self.prom_jobs_duration = None
        self.prom_cache_ops = None
        self.prom_queue_depth = None

        if enabled:
            self._init_prometheus_metrics()

    def _init_prometheus_metrics(self):
        """Initialize Prometheus metric objects."""
        try:
            from prometheus_client import REGISTRY, Counter, Gauge, Histogram

            # Metric 1: Job enqueue counter
            self.prom_jobs_enqueued = Counter(
                "brain_researcher_orchestrator_jobs_enqueued_total",
                "Total number of jobs submitted to orchestrator",
                ["kind"],  # kind = tool, dag, pipeline, etc.
            )

            # Metric 2: Job completion counter
            self.prom_jobs_completed = Counter(
                "brain_researcher_orchestrator_jobs_completed_total",
                "Total number of jobs completed by final state",
                ["kind", "state"],  # state = succeeded, failed, cancelled, timeout
            )

            # Metric 3: Job duration histogram
            # Buckets from 1s to 1 hour to capture typical job durations
            self.prom_jobs_duration = Histogram(
                "brain_researcher_orchestrator_jobs_duration_seconds",
                "Job execution duration in seconds",
                ["kind", "state"],
                buckets=[1, 5, 10, 30, 60, 300, 600, 1800, 3600],
            )

            # Metric 4: Cache operations counter
            self.prom_cache_ops = Counter(
                "brain_researcher_orchestrator_cache_operations_total",
                "Cache operations (hits/misses)",
                [
                    "operation",
                    "result",
                ],  # operation=lookup/store, result=hit/miss/error
            )

            # Metric 5: Queue depth gauge
            self.prom_queue_depth = Gauge(
                "brain_researcher_orchestrator_queue_depth",
                "Current number of jobs in queue by state",
                ["state"],  # state = pending, running, claimed, etc.
            )

            logger.info("Prometheus metrics initialized for orchestrator")

        except ImportError as e:
            logger.warning(f"Failed to initialize Prometheus metrics: {e}")
            logger.warning("Install prometheus-client: pip install prometheus-client")
            self.enabled = False

    # Public API Methods

    def record_job_enqueued(self, kind: str):
        """
        Record a job submission.

        Args:
            kind: Job type (e.g., 'tool', 'dag', 'pipeline')
        """
        if self.enabled and self.prom_jobs_enqueued:
            self.prom_jobs_enqueued.labels(kind=kind).inc()

    def record_job_completed(self, kind: str, state: str, duration: float):
        """
        Record a job completion with final state and duration.

        Args:
            kind: Job type (e.g., 'tool', 'dag', 'pipeline')
            state: Final state (e.g., 'succeeded', 'failed', 'cancelled')
            duration: Job duration in seconds
        """
        if self.enabled and self.prom_jobs_completed and self.prom_jobs_duration:
            self.prom_jobs_completed.labels(kind=kind, state=state).inc()
            self.prom_jobs_duration.labels(kind=kind, state=state).observe(duration)

    def record_cache_operation(self, operation: str, result: str):
        """
        Record a cache operation (hit/miss).

        Args:
            operation: Operation type (e.g., 'lookup', 'store')
            result: Operation result (e.g., 'hit', 'miss', 'error')
        """
        if self.enabled and self.prom_cache_ops:
            self.prom_cache_ops.labels(operation=operation, result=result).inc()

    def update_queue_depth(self, state_counts: dict[str, int]):
        """
        Update queue depth gauges from job store stats.

        Args:
            state_counts: Dictionary mapping job states to counts
                         e.g., {"pending": 10, "running": 5, "succeeded": 100}
        """
        if self.enabled and self.prom_queue_depth:
            for state, count in state_counts.items():
                self.prom_queue_depth.labels(state=state).set(count)

    def get_router(self) -> APIRouter:
        """
        Return FastAPI router with /metrics endpoint.

        Returns:
            APIRouter with Prometheus metrics endpoint
        """
        router = APIRouter()

        @router.get("/metrics", response_class=PlainTextResponse)
        async def prometheus_metrics():
            """
            Prometheus metrics endpoint.

            Returns metrics in Prometheus text format for scraping.
            """
            if not self.enabled:
                raise HTTPException(
                    status_code=404,
                    detail="Metrics disabled (set BR_METRICS_ENABLED=true to enable)",
                )

            try:
                from prometheus_client import REGISTRY, generate_latest

                return generate_latest(REGISTRY)
            except ImportError:
                raise HTTPException(
                    status_code=500, detail="prometheus-client not installed"
                )

        return router


# Global instance (initialized in main_enhanced.py)
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """
    Get the global metrics collector instance.

    Returns:
        MetricsCollector instance

    Raises:
        RuntimeError: If collector not initialized
    """
    if _metrics_collector is None:
        raise RuntimeError(
            "MetricsCollector not initialized. Call init_metrics() first."
        )
    return _metrics_collector


def init_metrics(enabled: bool = True) -> MetricsCollector:
    """
    Initialize global metrics collector.

    Args:
        enabled: If False, collector becomes no-op

    Returns:
        Initialized MetricsCollector instance
    """
    global _metrics_collector
    _metrics_collector = MetricsCollector(enabled=enabled)
    return _metrics_collector
