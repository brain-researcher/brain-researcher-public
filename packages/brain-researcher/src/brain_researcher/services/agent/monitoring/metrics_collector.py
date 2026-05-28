"""Metrics Collection System for Brain Researcher Agent

Collects, aggregates, and stores performance metrics for monitoring.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json
import numpy as np

from brain_researcher.services.telemetry.job_kind import JobKind

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics to collect."""

    COUNTER = "counter"  # Monotonically increasing
    GAUGE = "gauge"  # Point-in-time value
    HISTOGRAM = "histogram"  # Distribution of values
    SUMMARY = "summary"  # Statistical summary


@dataclass
class MetricPoint:
    """Single metric data point."""

    timestamp: float
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class Metric:
    """Metric definition and storage."""

    name: str
    metric_type: MetricType
    description: str
    unit: str = ""
    labels: List[str] = field(default_factory=list)
    data_points: deque = field(default_factory=lambda: deque(maxlen=10000))

    def add_point(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Add a data point to the metric."""
        point = MetricPoint(timestamp=time.time(), value=value, labels=labels or {})
        self.data_points.append(point)

    def get_latest(self) -> Optional[float]:
        """Get the latest value."""
        if self.data_points:
            return self.data_points[-1].value
        return None

    def get_aggregated(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        aggregation: str = "avg",
    ) -> Optional[float]:
        """Get aggregated value over time range."""
        # Filter points by time range
        points = self.data_points
        if start_time:
            points = [p for p in points if p.timestamp >= start_time]
        if end_time:
            points = [p for p in points if p.timestamp <= end_time]

        if not points:
            return None

        values = [p.value for p in points]

        if aggregation == "avg":
            return np.mean(values)
        elif aggregation == "sum":
            return np.sum(values)
        elif aggregation == "min":
            return np.min(values)
        elif aggregation == "max":
            return np.max(values)
        elif aggregation == "p50":
            return np.percentile(values, 50)
        elif aggregation == "p95":
            return np.percentile(values, 95)
        elif aggregation == "p99":
            return np.percentile(values, 99)
        else:
            return np.mean(values)


class MetricsCollector:
    """Collects and manages system metrics."""

    def __init__(self, collection_interval: int = 10, retention_hours: int = 24):
        """Initialize metrics collector.

        Args:
            collection_interval: Seconds between collection
            retention_hours: Hours to retain metrics
        """
        self.collection_interval = collection_interval
        self.retention_seconds = retention_hours * 3600

        # Metric storage
        self.metrics: Dict[str, Metric] = {}

        # Tool-specific metrics
        self.tool_metrics: Dict[str, Dict[str, Metric]] = defaultdict(dict)

        # Collection task
        self.collection_task: Optional[asyncio.Task] = None

        # Register default metrics
        self._register_default_metrics()

    def _register_default_metrics(self):
        """Register default system metrics."""
        # System metrics
        self.register_metric(
            "system_cpu_usage", MetricType.GAUGE, "CPU usage percentage", "%"
        )
        self.register_metric(
            "system_memory_usage", MetricType.GAUGE, "Memory usage in MB", "MB"
        )
        self.register_metric(
            "system_disk_usage", MetricType.GAUGE, "Disk usage percentage", "%"
        )

        # Agent metrics
        self.register_metric(
            "agent_requests_total",
            MetricType.COUNTER,
            "Total number of requests",
            "requests",
        )
        self.register_metric(
            "agent_request_duration",
            MetricType.HISTOGRAM,
            "Request duration in milliseconds",
            "ms",
        )
        self.register_metric(
            "agent_errors_total", MetricType.COUNTER, "Total number of errors", "errors"
        )
        self.register_metric(
            "planner_requests_total",
            MetricType.COUNTER,
            "Total planner requests received",
            "requests",
        )
        self.register_metric(
            "planner_errors_total",
            MetricType.COUNTER,
            "Planner failures (validation, planning, catalog load)",
            "errors",
        )
        self.register_metric(
            "planner_request_duration_ms",
            MetricType.HISTOGRAM,
            "Planner request duration in milliseconds",
            "ms",
        )
        self.register_metric(
            "catalog_load_failures_total",
            MetricType.COUNTER,
            "Total catalog loader failures (fall back to legacy)",
            "failures",
        )
        self.register_metric(
            "plan_memory_failure_writes_total",
            MetricType.COUNTER,
            "PlanMemory failure records successfully written",
            "writes",
        )
        self.register_metric(
            "plan_memory_failure_write_errors_total",
            MetricType.COUNTER,
            "PlanMemory failure record write errors",
            "errors",
        )
        self.register_metric(
            "kg_failure_writes_total",
            MetricType.COUNTER,
            "KG failure records successfully written",
            "writes",
        )
        self.register_metric(
            "kg_failure_write_errors_total",
            MetricType.COUNTER,
            "KG failure record write errors",
            "errors",
        )
        self.register_metric(
            "kg_failure_write_lag_ms",
            MetricType.GAUGE,
            "KG failure write lag in milliseconds",
            "ms",
        )
        self.register_metric(
            "kg_failure_dedupe_hits_total",
            MetricType.COUNTER,
            "KG failure record dedupe hits",
            "hits",
        )
        self.register_metric(
            "kg_failure_dedupe_hit_rate",
            MetricType.GAUGE,
            "Fraction of failure writes deduped",
            "ratio",
        )
        self.register_metric(
            "planner_constraint_filter_rate",
            MetricType.GAUGE,
            "Fraction of catalog candidates filtered by constraints",
            "ratio",
        )
        self.register_metric(
            "kg_evidence_writes_total",
            MetricType.COUNTER,
            "KG evidence records successfully written",
            "writes",
        )
        self.register_metric(
            "kg_evidence_write_errors_total",
            MetricType.COUNTER,
            "KG evidence record write errors",
            "errors",
        )
        self.register_metric(
            "kg_evidence_write_lag_ms",
            MetricType.GAUGE,
            "KG evidence write lag in milliseconds",
            "ms",
        )
        self.register_metric(
            "kg_evidence_coverage_total",
            MetricType.GAUGE,
            "Fraction of candidates with evidence priors",
            "ratio",
        )
        self.register_metric(
            "kg_writeback_success_total",
            MetricType.COUNTER,
            "KG writeback operations succeeded",
            "operations",
            labels=["type"],
        )
        self.register_metric(
            "kg_writeback_fail_total",
            MetricType.COUNTER,
            "KG writeback operations failed",
            "operations",
            labels=["type"],
        )
        self.register_metric(
            "kg_writeback_timeout_total",
            MetricType.COUNTER,
            "KG writeback operations that timed out",
            "operations",
            labels=["type"],
        )

        # Tool metrics
        self.register_metric(
            "tool_executions_total",
            MetricType.COUNTER,
            "Total tool executions",
            "executions",
            labels=["tool_name", "status", "job_kind"],
        )
        self.register_metric(
            "tool_execution_duration",
            MetricType.HISTOGRAM,
            "Tool execution duration",
            "ms",
            labels=["tool_name", "job_kind"],
        )
        self.register_metric(
            "tool_routing_candidate_count",
            MetricType.GAUGE,
            "Number of candidates considered during tool routing",
            "count",
            labels=["surface"],
        )
        self.register_metric(
            "tool_routing_selected_rank",
            MetricType.GAUGE,
            "Rank of the selected tool in the candidate list",
            "rank",
            labels=["surface"],
        )
        self.register_metric(
            "tool_routing_selected_in_topk_total",
            MetricType.COUNTER,
            "Selected tool was within top-k candidates",
            "hits",
            labels=["surface", "k"],
        )
        self.register_metric(
            "tool_routing_latency_ms",
            MetricType.HISTOGRAM,
            "Tool routing latency by stage",
            "ms",
            labels=["surface", "stage"],
        )
        self.register_metric(
            "tool_routing_family_expand_success_total",
            MetricType.COUNTER,
            "Family tool expansion outcomes during routing",
            "events",
            labels=["surface", "result"],
        )

        # Cache metrics
        self.register_metric(
            "cache_hits_total", MetricType.COUNTER, "Total cache hits", "hits"
        )
        self.register_metric(
            "cache_misses_total", MetricType.COUNTER, "Total cache misses", "misses"
        )
        self.register_metric(
            "cache_size_bytes", MetricType.GAUGE, "Cache size in bytes", "bytes"
        )

        # CLI metrics
        self.register_metric(
            "cli_commands_total",
            MetricType.COUNTER,
            "CLI command executions",
            "commands",
            labels=["command", "status", "job_kind"],
        )
        self.register_metric(
            "cli_command_duration_seconds",
            MetricType.HISTOGRAM,
            "CLI command duration in seconds",
            "seconds",
            labels=["command", "job_kind"],
        )

        # LLM cost and usage metrics
        self.register_metric(
            "llm_requests_total",
            MetricType.COUNTER,
            "Total LLM requests",
            "requests",
            labels=["provider", "model", "bill_to", "route", "transport"],
        )
        self.register_metric(
            "llm_tokens_total",
            MetricType.COUNTER,
            "Total LLM tokens consumed",
            "tokens",
            labels=["provider", "model", "bill_to", "type"],
        )
        self.register_metric(
            "llm_cost_usd_total",
            MetricType.COUNTER,
            "Total LLM cost in USD",
            "usd",
            labels=["provider", "model", "bill_to"],
        )
        self.register_metric(
            "llm_request_duration_ms",
            MetricType.HISTOGRAM,
            "LLM request duration in milliseconds",
            "ms",
            labels=["provider", "model", "route"],
        )
        self.register_metric(
            "llm_fallback_total",
            MetricType.COUNTER,
            "Total LLM fallback events",
            "fallbacks",
            labels=["from_provider", "reason"],
        )

    def register_metric(
        self,
        name: str,
        metric_type: MetricType,
        description: str,
        unit: str = "",
        labels: Optional[List[str]] = None,
    ):
        """Register a new metric.

        Args:
            name: Metric name
            metric_type: Type of metric
            description: Metric description
            unit: Unit of measurement
            labels: Label names for this metric
        """
        self.metrics[name] = Metric(
            name=name,
            metric_type=metric_type,
            description=description,
            unit=unit,
            labels=labels or [],
        )
        logger.debug(f"Registered metric: {name}")

    def record(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a metric value.

        Args:
            name: Metric name
            value: Metric value
            labels: Optional labels
        """
        if name in self.metrics:
            self.metrics[name].add_point(value, labels)
        else:
            logger.warning(f"Unknown metric: {name}")

    def increment(
        self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None
    ):
        """Increment a counter metric.

        Args:
            name: Metric name
            value: Increment value
            labels: Optional labels
        """
        if name in self.metrics:
            metric = self.metrics[name]
            if metric.metric_type == MetricType.COUNTER:
                current = metric.get_latest() or 0
                metric.add_point(current + value, labels)
            else:
                logger.warning(f"Metric {name} is not a counter")
        else:
            logger.warning(f"Unknown metric: {name}")

    def record_tool_execution(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
        error: Optional[str] = None,
        job_kind: Optional[str] = None,
    ):
        """Record tool execution metrics.

        Args:
            tool_name: Name of the tool
            duration_ms: Execution duration in milliseconds
            success: Whether execution was successful
            error: Error message if failed
            job_kind: Stable job kind label for dashboards
        """
        job_kind_value = job_kind or JobKind.OTHER.value

        # Record execution count
        self.increment(
            "tool_executions_total",
            labels={
                "tool_name": tool_name,
                "status": "success" if success else "error",
                "job_kind": job_kind_value,
            },
        )

        # Record duration
        self.record(
            "tool_execution_duration",
            duration_ms,
            labels={"tool_name": tool_name, "job_kind": job_kind_value},
        )

        # Tool-specific metrics
        if tool_name not in self.tool_metrics:
            self._register_tool_metrics(tool_name)

        tool_metrics = self.tool_metrics[tool_name]
        tool_metrics["executions"].add_point(1.0)
        tool_metrics["duration"].add_point(duration_ms)

        if not success:
            tool_metrics["errors"].add_point(1.0)
            self.increment("agent_errors_total")

    def record_cli_command(
        self,
        command: str,
        duration_ms: float,
        status: str,
        job_kind: Optional[str] = None,
    ) -> None:
        """Record CLI command metrics exposed through Prometheus."""
        job_kind_value = job_kind or JobKind.OTHER.value
        self.increment(
            "cli_commands_total",
            labels={
                "command": command,
                "status": status,
                "job_kind": job_kind_value,
            },
        )
        self.record(
            "cli_command_duration_seconds",
            duration_ms / 1000.0,
            labels={"command": command, "job_kind": job_kind_value},
        )

    def record_llm_invocation(
        self,
        provider: str,
        model: str,
        route: str = "primary",
        transport: str = "sdk",
        bill_to: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        estimated_cost: Optional[float] = None,
        latency_ms: Optional[int] = None,
        fallback_reason: Optional[str] = None,
    ) -> None:
        """
        Record LLM invocation metrics.

        Args:
            provider: LLM provider (e.g., google, openai)
            model: Model name (e.g., gemini-3.1-flash-lite-preview, gpt-4o)
            route: "primary" or "fallback"
            transport: "cli" or "sdk"
            bill_to: Billing target (local_oauth, byok, managed)
            usage: Token usage dict (prompt_tokens, completion_tokens, total_tokens)
            estimated_cost: Estimated cost in USD
            latency_ms: Request latency in milliseconds
            fallback_reason: Reason for fallback (if route=fallback)
        """
        bill_to_val = bill_to or "unknown"

        # Increment request counter
        self.increment(
            "llm_requests_total",
            labels={
                "provider": provider,
                "model": model,
                "bill_to": bill_to_val,
                "route": route,
                "transport": transport,
            },
        )

        # Record tokens if available
        if usage:
            prompt_tokens = usage.get("prompt_tokens", 0) or 0
            completion_tokens = usage.get("completion_tokens", 0) or 0

            if prompt_tokens > 0:
                self.increment(
                    "llm_tokens_total",
                    value=float(prompt_tokens),
                    labels={
                        "provider": provider,
                        "model": model,
                        "bill_to": bill_to_val,
                        "type": "prompt",
                    },
                )

            if completion_tokens > 0:
                self.increment(
                    "llm_tokens_total",
                    value=float(completion_tokens),
                    labels={
                        "provider": provider,
                        "model": model,
                        "bill_to": bill_to_val,
                        "type": "completion",
                    },
                )

        # Record cost if available
        if estimated_cost is not None and estimated_cost > 0:
            self.increment(
                "llm_cost_usd_total",
                value=estimated_cost,
                labels={
                    "provider": provider,
                    "model": model,
                    "bill_to": bill_to_val,
                },
            )

        # Record latency
        if latency_ms is not None:
            self.record(
                "llm_request_duration_ms",
                float(latency_ms),
                labels={
                    "provider": provider,
                    "model": model,
                    "route": route,
                },
            )

        # Record fallback event
        if route == "fallback" and fallback_reason:
            self.increment(
                "llm_fallback_total",
                labels={
                    "from_provider": provider,
                    "reason": fallback_reason,
                },
            )

    def record_tool_routing(
        self,
        *,
        surface: str,
        candidate_count: Optional[int] = None,
        selected_rank: Optional[int] = None,
        candidate_generation_latency_ms: Optional[float] = None,
        selection_latency_ms: Optional[float] = None,
        routing_latency_ms: Optional[float] = None,
        family_expand_success: Optional[bool] = None,
        top_k_hits: Optional[Dict[int, bool]] = None,
    ) -> None:
        """Record shared routing telemetry for chat and planner surfaces."""

        labels = {"surface": surface or "unknown"}

        if candidate_count is not None:
            self.record(
                "tool_routing_candidate_count",
                float(candidate_count),
                labels=labels,
            )
        if selected_rank is not None:
            self.record(
                "tool_routing_selected_rank",
                float(selected_rank),
                labels=labels,
            )
        if candidate_generation_latency_ms is not None:
            self.record(
                "tool_routing_latency_ms",
                float(candidate_generation_latency_ms),
                labels={**labels, "stage": "candidate_generation"},
            )
        if selection_latency_ms is not None:
            self.record(
                "tool_routing_latency_ms",
                float(selection_latency_ms),
                labels={**labels, "stage": "selection"},
            )
        if routing_latency_ms is not None:
            self.record(
                "tool_routing_latency_ms",
                float(routing_latency_ms),
                labels={**labels, "stage": "total"},
            )
        if top_k_hits:
            for k, hit in top_k_hits.items():
                if not hit:
                    continue
                self.increment(
                    "tool_routing_selected_in_topk_total",
                    labels={**labels, "k": str(k)},
                )
        if family_expand_success is not None:
            self.increment(
                "tool_routing_family_expand_success_total",
                labels={
                    **labels,
                    "result": "success" if family_expand_success else "failure",
                },
            )

    def _register_tool_metrics(self, tool_name: str):
        """Register metrics for a specific tool.

        Args:
            tool_name: Name of the tool
        """
        self.tool_metrics[tool_name] = {
            "executions": Metric(
                name=f"{tool_name}_executions",
                metric_type=MetricType.COUNTER,
                description=f"Executions of {tool_name}",
                unit="executions",
            ),
            "duration": Metric(
                name=f"{tool_name}_duration",
                metric_type=MetricType.HISTOGRAM,
                description=f"Duration of {tool_name}",
                unit="ms",
            ),
            "errors": Metric(
                name=f"{tool_name}_errors",
                metric_type=MetricType.COUNTER,
                description=f"Errors in {tool_name}",
                unit="errors",
            ),
        }

    async def start_collection(self):
        """Start metrics collection loop."""
        if self.collection_task:
            logger.warning("Collection already running")
            return

        self.collection_task = asyncio.create_task(self._collection_loop())
        logger.info("Metrics collection started")

    async def stop_collection(self):
        """Stop metrics collection loop."""
        if self.collection_task:
            self.collection_task.cancel()
            await asyncio.gather(self.collection_task, return_exceptions=True)
            self.collection_task = None
            logger.info("Metrics collection stopped")

    async def _collection_loop(self):
        """Main collection loop."""
        while True:
            try:
                # Collect system metrics
                await self._collect_system_metrics()

                # Clean old metrics
                self._clean_old_metrics()

                # Wait for next interval
                await asyncio.sleep(self.collection_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Collection loop error: {e}")
                await asyncio.sleep(self.collection_interval)

    async def _collect_system_metrics(self):
        """Collect system-level metrics."""
        try:
            import psutil

            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            self.record("system_cpu_usage", cpu_percent)

            # Memory usage
            memory = psutil.virtual_memory()
            memory_mb = memory.used / (1024**2)
            self.record("system_memory_usage", memory_mb)

            # Disk usage
            disk = psutil.disk_usage("/")
            self.record("system_disk_usage", disk.percent)

        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")

    def _clean_old_metrics(self):
        """Remove old metric points beyond retention period."""
        cutoff_time = time.time() - self.retention_seconds

        for metric in self.metrics.values():
            # Remove old points
            while metric.data_points and metric.data_points[0].timestamp < cutoff_time:
                metric.data_points.popleft()

        # Clean tool metrics
        for tool_metrics in self.tool_metrics.values():
            for metric in tool_metrics.values():
                while (
                    metric.data_points and metric.data_points[0].timestamp < cutoff_time
                ):
                    metric.data_points.popleft()

    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current metric values.

        Returns:
            Dictionary of current metric values
        """
        current = {}

        for name, metric in self.metrics.items():
            latest = metric.get_latest()
            if latest is not None:
                current[name] = {
                    "value": latest,
                    "type": metric.metric_type.value,
                    "unit": metric.unit,
                }

        return current

    def get_tool_metrics(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Get tool-specific metrics.

        Args:
            tool_name: Specific tool name or None for all

        Returns:
            Tool metrics dictionary
        """
        if tool_name:
            if tool_name not in self.tool_metrics:
                return {}

            metrics = self.tool_metrics[tool_name]
            return {
                "executions": metrics["executions"].get_latest() or 0,
                "avg_duration": metrics["duration"].get_aggregated(aggregation="avg")
                or 0,
                "p95_duration": metrics["duration"].get_aggregated(aggregation="p95")
                or 0,
                "errors": metrics["errors"].get_latest() or 0,
            }
        else:
            # Return metrics for all tools
            all_metrics = {}
            for name, metrics in self.tool_metrics.items():
                all_metrics[name] = {
                    "executions": metrics["executions"].get_latest() or 0,
                    "avg_duration": metrics["duration"].get_aggregated(
                        aggregation="avg"
                    )
                    or 0,
                    "errors": metrics["errors"].get_latest() or 0,
                }
            return all_metrics

    async def query(
        self,
        metric_names: List[str],
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        resolution: str = "1m",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Query historical metrics.

        Args:
            metric_names: List of metric names to query
            start_time: Start time (ISO format or relative)
            end_time: End time (ISO format or relative)
            resolution: Data resolution (1m, 5m, 15m, 1h)

        Returns:
            Dictionary of metric time series
        """
        # Parse time range
        start_ts = self._parse_time(start_time) if start_time else time.time() - 3600
        end_ts = self._parse_time(end_time) if end_time else time.time()

        # Parse resolution to seconds
        resolution_seconds = self._parse_resolution(resolution)

        results = {}

        for metric_name in metric_names:
            if metric_name not in self.metrics:
                continue

            metric = self.metrics[metric_name]

            # Get points in time range
            points = [
                p for p in metric.data_points if start_ts <= p.timestamp <= end_ts
            ]

            # Aggregate by resolution
            time_series = []
            current_bucket = start_ts

            while current_bucket < end_ts:
                bucket_end = current_bucket + resolution_seconds
                bucket_points = [
                    p.value
                    for p in points
                    if current_bucket <= p.timestamp < bucket_end
                ]

                if bucket_points:
                    time_series.append(
                        {"timestamp": current_bucket, "value": np.mean(bucket_points)}
                    )

                current_bucket = bucket_end

            results[metric_name] = time_series

        return results

    def _parse_time(self, time_str: str) -> float:
        """Parse time string to timestamp.

        Args:
            time_str: Time string (ISO or relative like '-1h')

        Returns:
            Unix timestamp
        """
        if time_str.startswith("-"):
            # Relative time
            amount = int(time_str[1:-1])
            unit = time_str[-1]

            if unit == "s":
                return time.time() - amount
            elif unit == "m":
                return time.time() - (amount * 60)
            elif unit == "h":
                return time.time() - (amount * 3600)
            elif unit == "d":
                return time.time() - (amount * 86400)
        else:
            # ISO format
            dt = datetime.fromisoformat(time_str)
            return dt.timestamp()

        return time.time()

    def _parse_resolution(self, resolution: str) -> int:
        """Parse resolution string to seconds.

        Args:
            resolution: Resolution string (1m, 5m, 15m, 1h)

        Returns:
            Seconds
        """
        amount = int(resolution[:-1])
        unit = resolution[-1]

        if unit == "s":
            return amount
        elif unit == "m":
            return amount * 60
        elif unit == "h":
            return amount * 3600

        return 60  # Default to 1 minute

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted metrics
        """
        lines = []

        for name, metric in self.metrics.items():
            # Add HELP and TYPE comments
            lines.append(f"# HELP {name} {metric.description}")
            lines.append(f"# TYPE {name} {metric.metric_type.value}")

            # Add metric value
            latest = metric.get_latest()
            if latest is not None:
                if metric.labels:
                    # Emit last value per label set (Prometheus expects labeled samples).
                    label_latest: Dict[Tuple[Tuple[str, str], ...], float] = {}
                    for point in metric.data_points:
                        if not point.labels:
                            continue
                        label_key = tuple(sorted(point.labels.items()))
                        label_latest[label_key] = point.value
                    for label_key, value in label_latest.items():
                        label_str = ",".join(f'{k}="{v}"' for k, v in label_key)
                        lines.append(f"{name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{name} {latest}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Knowledge cache helpers (used by EvidenceAggregator exports)
    # ------------------------------------------------------------------

    def record_knowledge_cache_metrics(
        self,
        l1_hits: int = 0,
        l1_misses: int = 0,
        shared_hits: int = 0,
        shared_sets: int = 0,
        account_id: str = "unknown",
    ) -> None:
        labels_l1 = {"layer": "l1", "account_id": account_id}
        labels_shared = {"layer": "shared", "account_id": account_id}

        if l1_hits:
            self.increment("cache_hits_total", l1_hits, labels=labels_l1)
        if shared_hits:
            self.increment("cache_hits_total", shared_hits, labels=labels_shared)
        if l1_misses:
            self.increment("cache_misses_total", l1_misses, labels=labels_l1)
        if shared_sets:
            # Use hits counter to record sets; keeping separate metric is not necessary for export
            self.increment("cache_hits_total", 0, labels=labels_shared)


_shared_metrics_collector: Optional[MetricsCollector] = None


def get_default_metrics_collector() -> MetricsCollector:
    """Return a process-wide shared metrics collector."""

    global _shared_metrics_collector
    if _shared_metrics_collector is None:
        _shared_metrics_collector = MetricsCollector()
    return _shared_metrics_collector


def record(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    get_default_metrics_collector().record(name, value, labels)


def increment(
    name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None
) -> None:
    get_default_metrics_collector().increment(name, value, labels)


def record_tool_routing(**kwargs: Any) -> None:
    get_default_metrics_collector().record_tool_routing(**kwargs)
