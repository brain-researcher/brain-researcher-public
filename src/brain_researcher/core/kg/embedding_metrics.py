"""
Monitoring and metrics system for the embedding index.

Tracks performance, usage, and health metrics.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    """Metrics for a single query."""

    timestamp: float
    query_text: str
    latency_ms: float
    num_results: int
    shard_count: int
    error: str | None = None


@dataclass
class IndexMetrics:
    """Metrics for the index state."""

    total_embeddings: int = 0
    total_shards: int = 0
    memory_usage_mb: float = 0.0
    last_refresh: float | None = None
    refresh_count: int = 0


class EmbeddingMetricsCollector:
    """Collects and manages metrics for the embedding index."""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.query_history: list[QueryMetrics] = []
        self.index_metrics = IndexMetrics()
        self.lock = threading.Lock()

        # Aggregated metrics
        self.total_queries = 0
        self.total_errors = 0
        self.start_time = time.time()

        # Performance buckets for histogram
        self.latency_buckets = [10, 50, 100, 250, 500, 1000, 2500, 5000]  # ms
        self.latency_histogram = {bucket: 0 for bucket in self.latency_buckets}
        self.latency_histogram[float("inf")] = 0  # For queries > 5000ms

    def record_query(
        self,
        query_text: str,
        latency_ms: float,
        num_results: int,
        shard_count: int,
        error: str | None = None,
    ) -> None:
        """Record metrics for a query."""
        with self.lock:
            # Create query metrics
            metrics = QueryMetrics(
                timestamp=time.time(),
                query_text=query_text[:100],  # Truncate long queries
                latency_ms=latency_ms,
                num_results=num_results,
                shard_count=shard_count,
                error=error,
            )

            # Add to history
            self.query_history.append(metrics)
            if len(self.query_history) > self.max_history:
                self.query_history.pop(0)

            # Update counters
            self.total_queries += 1
            if error:
                self.total_errors += 1

            # Update histogram
            for bucket in self.latency_buckets:
                if latency_ms <= bucket:
                    self.latency_histogram[bucket] += 1
                    break
            else:
                self.latency_histogram[float("inf")] += 1

    def update_index_metrics(
        self, total_embeddings: int, total_shards: int, memory_usage_mb: float
    ) -> None:
        """Update index state metrics."""
        with self.lock:
            self.index_metrics.total_embeddings = total_embeddings
            self.index_metrics.total_shards = total_shards
            self.index_metrics.memory_usage_mb = memory_usage_mb

    def record_refresh(self) -> None:
        """Record that a refresh occurred."""
        with self.lock:
            self.index_metrics.last_refresh = time.time()
            self.index_metrics.refresh_count += 1

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all metrics."""
        with self.lock:
            uptime_seconds = time.time() - self.start_time

            # Calculate query statistics
            recent_queries = self.query_history[-100:]  # Last 100 queries
            if recent_queries:
                latencies = [q.latency_ms for q in recent_queries if q.error is None]
                avg_latency = sum(latencies) / len(latencies) if latencies else 0
                p95_latency = (
                    sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
                )
                p99_latency = (
                    sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
                )
            else:
                avg_latency = p95_latency = p99_latency = 0

            # Calculate error rate
            error_rate = (
                self.total_errors / self.total_queries if self.total_queries > 0 else 0
            )

            # Calculate QPS
            qps = self.total_queries / uptime_seconds if uptime_seconds > 0 else 0

            return {
                "uptime_seconds": uptime_seconds,
                "total_queries": self.total_queries,
                "total_errors": self.total_errors,
                "error_rate": error_rate,
                "queries_per_second": qps,
                "latency_ms": {
                    "avg": avg_latency,
                    "p95": p95_latency,
                    "p99": p99_latency,
                },
                "latency_histogram": dict(self.latency_histogram),
                "index": {
                    "total_embeddings": self.index_metrics.total_embeddings,
                    "total_shards": self.index_metrics.total_shards,
                    "memory_usage_mb": self.index_metrics.memory_usage_mb,
                    "last_refresh": self.index_metrics.last_refresh,
                    "refresh_count": self.index_metrics.refresh_count,
                },
                "recent_errors": [
                    {"timestamp": q.timestamp, "query": q.query_text, "error": q.error}
                    for q in recent_queries
                    if q.error
                ][
                    -10:
                ],  # Last 10 errors
            }

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        summary = self.get_summary()

        lines = [
            "# HELP embedding_queries_total Total number of queries",
            "# TYPE embedding_queries_total counter",
            f"embedding_queries_total {summary['total_queries']}",
            "",
            "# HELP embedding_errors_total Total number of errors",
            "# TYPE embedding_errors_total counter",
            f"embedding_errors_total {summary['total_errors']}",
            "",
            "# HELP embedding_latency_ms Query latency in milliseconds",
            "# TYPE embedding_latency_ms histogram",
        ]

        # Add histogram buckets
        total_count = 0
        for bucket in self.latency_buckets:
            count = self.latency_histogram[bucket]
            total_count += count
            lines.append(f'embedding_latency_ms_bucket{{le="{bucket}"}} {total_count}')

        lines.extend(
            [
                f'embedding_latency_ms_bucket{{le="+Inf"}} {self.total_queries}',
                f"embedding_latency_ms_sum {sum(q.latency_ms for q in self.query_history)}",
                f"embedding_latency_ms_count {self.total_queries}",
                "",
                "# HELP embedding_index_size Total number of embeddings in index",
                "# TYPE embedding_index_size gauge",
                f"embedding_index_size {summary['index']['total_embeddings']}",
                "",
                "# HELP embedding_index_shards Number of index shards",
                "# TYPE embedding_index_shards gauge",
                f"embedding_index_shards {summary['index']['total_shards']}",
                "",
                "# HELP embedding_memory_usage_mb Memory usage in MB",
                "# TYPE embedding_memory_usage_mb gauge",
                f"embedding_memory_usage_mb {summary['index']['memory_usage_mb']}",
            ]
        )

        return "\n".join(lines)

    def save_to_file(self, filepath: str) -> None:
        """Save metrics summary to JSON file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self.get_summary(), f, indent=2, default=str)


class QueryTimer:
    """Context manager for timing queries."""

    def __init__(
        self,
        metrics_collector: EmbeddingMetricsCollector,
        query_text: str,
        shard_count: int,
    ):
        self.metrics_collector = metrics_collector
        self.query_text = query_text
        self.shard_count = shard_count
        self.start_time = None
        self.error = None
        self.num_results = 0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (time.time() - self.start_time) * 1000

        if exc_type is not None:
            self.error = str(exc_val)

        self.metrics_collector.record_query(
            query_text=self.query_text,
            latency_ms=latency_ms,
            num_results=self.num_results,
            shard_count=self.shard_count,
            error=self.error,
        )

        # Log slow queries
        if latency_ms > 1000 and self.error is None:
            logger.warning(
                f"Slow query ({latency_ms:.0f}ms): {self.query_text[:50]}..."
            )

    def set_results(self, num_results: int):
        """Set the number of results found."""
        self.num_results = num_results


# Global metrics collector
_metrics_collector: EmbeddingMetricsCollector | None = None


def get_metrics_collector() -> EmbeddingMetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = EmbeddingMetricsCollector()
    return _metrics_collector


# Example usage
if __name__ == "__main__":
    collector = get_metrics_collector()

    # Simulate some queries
    import random

    for i in range(20):
        query = f"test query {i}"
        latency = random.uniform(10, 200)
        num_results = random.randint(0, 10)
        shard_count = 3
        error = "timeout" if i % 10 == 0 else None

        collector.record_query(query, latency, num_results, shard_count, error)

    # Update index metrics
    collector.update_index_metrics(
        total_embeddings=50000, total_shards=5, memory_usage_mb=1024.5
    )

    # Print summary
    print("Metrics Summary:")
    print(json.dumps(collector.get_summary(), indent=2, default=str))

    # Save metrics
    collector.save_to_file("knowledge/metrics/embedding_metrics.json")

    # Print Prometheus format
    print("\nPrometheus Format:")
    print(collector.get_prometheus_metrics())
