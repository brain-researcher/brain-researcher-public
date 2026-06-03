"""
Resource Monitoring System for Brain Researcher Agent.

Tracks actual resource usage and provides metrics.
"""

import logging
import psutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ResourceSnapshot:
    """Point-in-time resource usage snapshot."""

    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    disk_io_read_mb: float
    disk_io_write_mb: float
    network_sent_mb: float
    network_recv_mb: float
    active_threads: int

    @classmethod
    def capture(cls) -> "ResourceSnapshot":
        """Capture current system resource usage."""
        memory = psutil.virtual_memory()
        disk_io = psutil.disk_io_counters()
        net_io = psutil.net_io_counters()

        return cls(
            timestamp=datetime.now(),
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_percent=memory.percent,
            memory_mb=memory.used / (1024 * 1024),
            disk_io_read_mb=disk_io.read_bytes / (1024 * 1024) if disk_io else 0,
            disk_io_write_mb=disk_io.write_bytes / (1024 * 1024) if disk_io else 0,
            network_sent_mb=net_io.bytes_sent / (1024 * 1024) if net_io else 0,
            network_recv_mb=net_io.bytes_recv / (1024 * 1024) if net_io else 0,
            active_threads=threading.active_count(),
        )


@dataclass
class ResourceMetrics:
    """Aggregated resource usage metrics."""

    tool_name: str
    execution_id: str
    start_time: datetime
    end_time: Optional[datetime] = None

    # Peak usage
    peak_cpu_percent: float = 0.0
    peak_memory_mb: float = 0.0

    # Average usage
    avg_cpu_percent: float = 0.0
    avg_memory_mb: float = 0.0

    # Total I/O
    total_disk_read_mb: float = 0.0
    total_disk_write_mb: float = 0.0
    total_network_sent_mb: float = 0.0
    total_network_recv_mb: float = 0.0

    # Snapshots for detailed analysis
    snapshots: List[ResourceSnapshot] = field(default_factory=list)

    @property
    def duration(self) -> Optional[timedelta]:
        """Get execution duration."""
        if self.end_time:
            return self.end_time - self.start_time
        return datetime.now() - self.start_time

    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        duration = self.duration
        return duration.total_seconds() if duration else 0.0

    def add_snapshot(self, snapshot: ResourceSnapshot):
        """Add a resource snapshot and update metrics."""
        self.snapshots.append(snapshot)

        # Update peak values
        if snapshot.cpu_percent > self.peak_cpu_percent:
            self.peak_cpu_percent = snapshot.cpu_percent
        if snapshot.memory_mb > self.peak_memory_mb:
            self.peak_memory_mb = snapshot.memory_mb

        # Update averages
        if self.snapshots:
            self.avg_cpu_percent = sum(s.cpu_percent for s in self.snapshots) / len(self.snapshots)
            self.avg_memory_mb = sum(s.memory_mb for s in self.snapshots) / len(self.snapshots)

        # Update I/O totals (using deltas from first snapshot)
        if len(self.snapshots) > 1:
            first = self.snapshots[0]
            self.total_disk_read_mb = snapshot.disk_io_read_mb - first.disk_io_read_mb
            self.total_disk_write_mb = snapshot.disk_io_write_mb - first.disk_io_write_mb
            self.total_network_sent_mb = snapshot.network_sent_mb - first.network_sent_mb
            self.total_network_recv_mb = snapshot.network_recv_mb - first.network_recv_mb

    def finalize(self):
        """Mark metrics as complete."""
        self.end_time = datetime.now()

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            "tool_name": self.tool_name,
            "execution_id": self.execution_id,
            "duration_seconds": self.duration_seconds,
            "peak_cpu_percent": round(self.peak_cpu_percent, 2),
            "peak_memory_mb": round(self.peak_memory_mb, 2),
            "avg_cpu_percent": round(self.avg_cpu_percent, 2),
            "avg_memory_mb": round(self.avg_memory_mb, 2),
            "total_disk_read_mb": round(self.total_disk_read_mb, 2),
            "total_disk_write_mb": round(self.total_disk_write_mb, 2),
            "total_network_mb": round(self.total_network_sent_mb + self.total_network_recv_mb, 2),
            "snapshot_count": len(self.snapshots),
        }


class ResourceMonitor:
    """Monitors and tracks resource usage for tool executions."""

    def __init__(
        self,
        sampling_interval: float = 1.0,
        history_size: int = 1000,
        enable_monitoring: bool = True,
    ):
        """
        Initialize resource monitor.

        Args:
            sampling_interval: Seconds between resource samples
            history_size: Number of historical metrics to keep
            enable_monitoring: Enable active monitoring
        """
        self.sampling_interval = sampling_interval
        self.history_size = history_size
        self.enable_monitoring = enable_monitoring

        # Active monitoring
        self.active_metrics: Dict[str, ResourceMetrics] = {}

        # Historical metrics
        self.history: Deque[ResourceMetrics] = deque(maxlen=history_size)

        # System baseline (measured at startup)
        self.baseline = ResourceSnapshot.capture() if enable_monitoring else None

        # Monitoring thread
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        if enable_monitoring:
            self.start_monitoring()

        logger.info(
            f"ResourceMonitor initialized (sampling: {sampling_interval}s, "
            f"monitoring: {'enabled' if enable_monitoring else 'disabled'})"
        )

    def start_tracking(self, tool_name: str, execution_id: str) -> ResourceMetrics:
        """
        Start tracking resources for a tool execution.

        Args:
            tool_name: Name of the tool
            execution_id: Unique execution ID

        Returns:
            ResourceMetrics object for this execution
        """
        with self._lock:
            if execution_id in self.active_metrics:
                logger.warning(f"Already tracking execution {execution_id}")
                return self.active_metrics[execution_id]

            metrics = ResourceMetrics(
                tool_name=tool_name,
                execution_id=execution_id,
                start_time=datetime.now(),
            )

            # Capture initial snapshot
            if self.enable_monitoring:
                metrics.add_snapshot(ResourceSnapshot.capture())

            self.active_metrics[execution_id] = metrics

            logger.debug(f"Started tracking resources for {tool_name} (exec: {execution_id[:8]})")
            return metrics

    def stop_tracking(self, execution_id: str) -> Optional[ResourceMetrics]:
        """
        Stop tracking resources for an execution.

        Args:
            execution_id: Execution ID to stop tracking

        Returns:
            Final ResourceMetrics or None if not found
        """
        with self._lock:
            metrics = self.active_metrics.pop(execution_id, None)

            if metrics:
                metrics.finalize()
                self.history.append(metrics)

                logger.debug(
                    f"Stopped tracking {metrics.tool_name} (exec: {execution_id[:8]}): "
                    f"Peak CPU: {metrics.peak_cpu_percent:.1f}%, "
                    f"Peak Memory: {metrics.peak_memory_mb:.1f}MB, "
                    f"Duration: {metrics.duration_seconds:.1f}s"
                )

                return metrics
            else:
                logger.warning(f"No active tracking for execution {execution_id}")
                return None

    def get_current_usage(self) -> Dict[str, float]:
        """Get current system resource usage."""
        if not self.enable_monitoring:
            return {"cpu_percent": 0, "memory_mb": 0}

        snapshot = ResourceSnapshot.capture()

        # Calculate relative to baseline if available
        if self.baseline:
            cpu_delta = max(0, snapshot.cpu_percent - self.baseline.cpu_percent)
            memory_delta = max(0, snapshot.memory_mb - self.baseline.memory_mb)
        else:
            cpu_delta = snapshot.cpu_percent
            memory_delta = snapshot.memory_mb

        return {
            "cpu_percent": cpu_delta,
            "memory_mb": memory_delta,
            "memory_percent": snapshot.memory_percent,
            "active_threads": snapshot.active_threads,
        }

    def get_tool_statistics(self, tool_name: Optional[str] = None) -> Dict:
        """
        Get aggregated statistics for tool(s).

        Args:
            tool_name: Specific tool name or None for all tools

        Returns:
            Statistics dictionary
        """
        with self._lock:
            # Filter metrics by tool if specified
            if tool_name:
                metrics_list = [m for m in self.history if m.tool_name == tool_name]
            else:
                metrics_list = list(self.history)

            if not metrics_list:
                return {"error": "No metrics available"}

            # Aggregate statistics
            stats = {
                "count": len(metrics_list),
                "total_duration_seconds": sum(m.duration_seconds for m in metrics_list),
                "avg_duration_seconds": sum(m.duration_seconds for m in metrics_list) / len(metrics_list),
                "avg_cpu_percent": sum(m.avg_cpu_percent for m in metrics_list) / len(metrics_list),
                "avg_memory_mb": sum(m.avg_memory_mb for m in metrics_list) / len(metrics_list),
                "peak_cpu_percent": max(m.peak_cpu_percent for m in metrics_list),
                "peak_memory_mb": max(m.peak_memory_mb for m in metrics_list),
                "total_disk_io_mb": sum(m.total_disk_read_mb + m.total_disk_write_mb for m in metrics_list),
            }

            # Group by tool if not filtered
            if not tool_name:
                by_tool = {}
                for m in metrics_list:
                    if m.tool_name not in by_tool:
                        by_tool[m.tool_name] = []
                    by_tool[m.tool_name].append(m)

                stats["by_tool"] = {
                    tool: {
                        "count": len(tool_metrics),
                        "avg_duration": sum(m.duration_seconds for m in tool_metrics) / len(tool_metrics),
                        "avg_cpu": sum(m.avg_cpu_percent for m in tool_metrics) / len(tool_metrics),
                        "avg_memory": sum(m.avg_memory_mb for m in tool_metrics) / len(tool_metrics),
                    }
                    for tool, tool_metrics in by_tool.items()
                }

            return stats

    def start_monitoring(self):
        """Start the monitoring thread."""
        if self._monitoring:
            logger.warning("Monitoring already started")
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Resource monitoring started")

    def stop_monitoring(self):
        """Stop the monitoring thread."""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Resource monitoring stopped")

    def _monitor_loop(self):
        """Background monitoring loop."""
        while self._monitoring:
            try:
                # Capture snapshot for all active executions
                with self._lock:
                    if self.active_metrics:
                        snapshot = ResourceSnapshot.capture()
                        for metrics in self.active_metrics.values():
                            metrics.add_snapshot(snapshot)

                # Sleep until next sample
                time.sleep(self.sampling_interval)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")

    def get_recommendations(self) -> List[str]:
        """Get resource optimization recommendations based on history."""
        if not self.history:
            return ["No execution history available for recommendations"]

        recommendations = []
        stats = self.get_tool_statistics()

        # Check for high CPU usage
        if stats.get("avg_cpu_percent", 0) > 70:
            recommendations.append(
                f"High average CPU usage ({stats['avg_cpu_percent']:.1f}%). "
                "Consider increasing CPU allocation or optimizing tools."
            )

        # Check for high memory usage
        if stats.get("peak_memory_mb", 0) > 6000:  # 6GB
            recommendations.append(
                f"High peak memory usage ({stats['peak_memory_mb']:.0f}MB). "
                "Consider increasing memory limits or using streaming processing."
            )

        # Check for long-running tools
        if stats.get("avg_duration_seconds", 0) > 300:  # 5 minutes
            recommendations.append(
                f"Long average execution time ({stats['avg_duration_seconds']:.0f}s). "
                "Consider implementing progress tracking or breaking into smaller tasks."
            )

        # Tool-specific recommendations
        if "by_tool" in stats:
            for tool, tool_stats in stats["by_tool"].items():
                if tool_stats["avg_cpu"] > 80:
                    recommendations.append(
                        f"Tool '{tool}' has high CPU usage ({tool_stats['avg_cpu']:.1f}%). "
                        "Consider optimizing or limiting concurrent executions."
                    )

        return recommendations if recommendations else ["System resources are well-utilized"]

    def export_metrics(self) -> List[Dict]:
        """Export all historical metrics as list of dictionaries."""
        with self._lock:
            return [m.to_dict() for m in self.history]