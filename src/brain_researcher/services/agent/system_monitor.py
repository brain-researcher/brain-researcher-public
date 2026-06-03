"""
System Load Monitoring for Adaptive Execution Strategy (AGENT-021)

This module provides real-time system monitoring capabilities including CPU, memory,
I/O, and network metrics for dynamic execution strategy adaptation.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum

import psutil

logger = logging.getLogger(__name__)


class SystemHealth(str, Enum):
    """System health status levels."""

    HEALTHY = "healthy"
    MODERATE = "moderate"
    STRESSED = "stressed"
    CRITICAL = "critical"


@dataclass
class SystemMetrics:
    """System metrics snapshot."""

    timestamp: float
    cpu_usage: float  # Percentage
    memory_usage: float  # Percentage
    memory_available: float  # GB
    disk_io_read: float  # MB/s
    disk_io_write: float  # MB/s
    network_sent: float  # MB/s
    network_recv: float  # MB/s
    load_average: tuple[float, float, float]  # 1, 5, 15 minute averages
    active_processes: int
    queue_depth: int = 0  # Will be set by external systems
    gpu_usage: float | None = None  # Percentage, if available
    gpu_memory: float | None = None  # Percentage, if available


@dataclass
class PerformanceAnalysis:
    """Performance analysis results."""

    overall_health: SystemHealth
    bottlenecks: list[str]
    recommendations: list[str]
    trend_direction: str  # improving, stable, degrading
    predicted_capacity: float  # Percentage of capacity in next 5 minutes


class MetricsCollector:
    """Collects system metrics using psutil."""

    def __init__(self):
        """Initialize metrics collector."""
        self._last_net_stats = None
        self._last_disk_stats = None
        self._last_timestamp = None

        # Initialize baseline readings
        self._initialize_baseline()

    def _initialize_baseline(self):
        """Initialize baseline readings for delta calculations."""
        try:
            self._last_net_stats = psutil.net_io_counters()
            self._last_disk_stats = psutil.disk_io_counters()
            self._last_timestamp = time.time()
        except Exception as e:
            logger.warning(f"Failed to initialize baseline metrics: {e}")

    def collect_metrics(self) -> SystemMetrics:
        """Collect current system metrics."""
        current_time = time.time()

        try:
            # CPU metrics
            cpu_usage = psutil.cpu_percent(interval=None)

            # Memory metrics
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            memory_available = memory.available / (1024**3)  # Convert to GB

            # Load average (Unix-like systems)
            if hasattr(psutil, "getloadavg"):
                load_avg = psutil.getloadavg()
            else:
                # Windows fallback
                load_avg = (cpu_usage / 100.0, cpu_usage / 100.0, cpu_usage / 100.0)

            # Process count
            active_processes = len(psutil.pids())

            # I/O metrics (calculate rates)
            disk_io_read, disk_io_write = self._calculate_disk_io_rates(current_time)
            network_sent, network_recv = self._calculate_network_rates(current_time)

            # GPU metrics (if available)
            gpu_usage, gpu_memory = self._get_gpu_metrics()

            return SystemMetrics(
                timestamp=current_time,
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
                memory_available=memory_available,
                disk_io_read=disk_io_read,
                disk_io_write=disk_io_write,
                network_sent=network_sent,
                network_recv=network_recv,
                load_average=load_avg,
                active_processes=active_processes,
                gpu_usage=gpu_usage,
                gpu_memory=gpu_memory,
            )

        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
            # Return minimal metrics
            return SystemMetrics(
                timestamp=current_time,
                cpu_usage=0.0,
                memory_usage=0.0,
                memory_available=0.0,
                disk_io_read=0.0,
                disk_io_write=0.0,
                network_sent=0.0,
                network_recv=0.0,
                load_average=(0.0, 0.0, 0.0),
                active_processes=0,
            )

    def _calculate_disk_io_rates(self, current_time: float) -> tuple[float, float]:
        """Calculate disk I/O rates in MB/s."""
        try:
            current_disk = psutil.disk_io_counters()
            if (
                not current_disk
                or not self._last_disk_stats
                or not self._last_timestamp
            ):
                self._last_disk_stats = current_disk
                self._last_timestamp = current_time
                return 0.0, 0.0

            time_delta = current_time - self._last_timestamp
            if time_delta <= 0:
                return 0.0, 0.0

            read_delta = current_disk.read_bytes - self._last_disk_stats.read_bytes
            write_delta = current_disk.write_bytes - self._last_disk_stats.write_bytes

            read_rate = (read_delta / time_delta) / (1024**2)  # Convert to MB/s
            write_rate = (write_delta / time_delta) / (1024**2)

            self._last_disk_stats = current_disk
            return max(0.0, read_rate), max(0.0, write_rate)

        except Exception as e:
            logger.debug(f"Failed to calculate disk I/O rates: {e}")
            return 0.0, 0.0

    def _calculate_network_rates(self, current_time: float) -> tuple[float, float]:
        """Calculate network I/O rates in MB/s."""
        try:
            current_net = psutil.net_io_counters()
            if not current_net or not self._last_net_stats or not self._last_timestamp:
                self._last_net_stats = current_net
                self._last_timestamp = current_time
                return 0.0, 0.0

            time_delta = current_time - self._last_timestamp
            if time_delta <= 0:
                return 0.0, 0.0

            sent_delta = current_net.bytes_sent - self._last_net_stats.bytes_sent
            recv_delta = current_net.bytes_recv - self._last_net_stats.bytes_recv

            sent_rate = (sent_delta / time_delta) / (1024**2)  # Convert to MB/s
            recv_rate = (recv_delta / time_delta) / (1024**2)

            self._last_net_stats = current_net
            self._last_timestamp = current_time

            return max(0.0, sent_rate), max(0.0, recv_rate)

        except Exception as e:
            logger.debug(f"Failed to calculate network rates: {e}")
            return 0.0, 0.0

    def _get_gpu_metrics(self) -> tuple[float | None, float | None]:
        """Get GPU metrics if available."""
        try:
            # Try to import nvidia-ml-py for NVIDIA GPUs
            import pynvml

            pynvml.nvmlInit()

            device_count = pynvml.nvmlDeviceGetCount()
            if device_count == 0:
                return None, None

            # Use first GPU for now
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)

            # GPU utilization
            utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
            gpu_usage = utilization.gpu

            # GPU memory
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_memory = (mem_info.used / mem_info.total) * 100

            return float(gpu_usage), float(gpu_memory)

        except (ImportError, Exception):
            # GPU monitoring not available
            return None, None


class LoadTracker:
    """Tracks system load over time."""

    def __init__(self, history_size: int = 300):  # 5 minutes at 1s intervals
        """
        Initialize load tracker.

        Args:
            history_size: Number of historical metrics to keep
        """
        self.history_size = history_size
        self.metrics_history: deque = deque(maxlen=history_size)
        self._lock = asyncio.Lock()

    async def add_metrics(self, metrics: SystemMetrics):
        """Add metrics to history."""
        async with self._lock:
            self.metrics_history.append(metrics)

    def get_average_load(self, window_seconds: int = 60) -> SystemMetrics | None:
        """Get average load over specified window."""
        if not self.metrics_history:
            return None

        current_time = time.time()
        window_start = current_time - window_seconds

        # Filter metrics within window
        window_metrics = [
            m for m in self.metrics_history if m.timestamp >= window_start
        ]

        if not window_metrics:
            return None

        # Calculate averages
        avg_cpu = sum(m.cpu_usage for m in window_metrics) / len(window_metrics)
        avg_memory = sum(m.memory_usage for m in window_metrics) / len(window_metrics)
        avg_mem_avail = sum(m.memory_available for m in window_metrics) / len(
            window_metrics
        )
        avg_disk_read = sum(m.disk_io_read for m in window_metrics) / len(
            window_metrics
        )
        avg_disk_write = sum(m.disk_io_write for m in window_metrics) / len(
            window_metrics
        )
        avg_net_sent = sum(m.network_sent for m in window_metrics) / len(window_metrics)
        avg_net_recv = sum(m.network_recv for m in window_metrics) / len(window_metrics)
        avg_processes = sum(m.active_processes for m in window_metrics) / len(
            window_metrics
        )
        avg_queue = sum(m.queue_depth for m in window_metrics) / len(window_metrics)

        # GPU averages (if available)
        gpu_metrics = [m for m in window_metrics if m.gpu_usage is not None]
        avg_gpu = (
            sum(m.gpu_usage for m in gpu_metrics) / len(gpu_metrics)
            if gpu_metrics
            else None
        )
        avg_gpu_mem = (
            sum(m.gpu_memory for m in gpu_metrics) / len(gpu_metrics)
            if gpu_metrics
            else None
        )

        return SystemMetrics(
            timestamp=current_time,
            cpu_usage=avg_cpu,
            memory_usage=avg_memory,
            memory_available=avg_mem_avail,
            disk_io_read=avg_disk_read,
            disk_io_write=avg_disk_write,
            network_sent=avg_net_sent,
            network_recv=avg_net_recv,
            load_average=window_metrics[-1].load_average,  # Use latest
            active_processes=int(avg_processes),
            queue_depth=int(avg_queue),
            gpu_usage=avg_gpu,
            gpu_memory=avg_gpu_mem,
        )

    def get_trend(self, metric_name: str, window_seconds: int = 300) -> str:
        """Get trend direction for a specific metric."""
        if len(self.metrics_history) < 10:
            return "stable"

        current_time = time.time()
        window_start = current_time - window_seconds

        # Get recent metrics
        recent_metrics = [
            m for m in self.metrics_history if m.timestamp >= window_start
        ]

        if len(recent_metrics) < 5:
            return "stable"

        # Extract metric values
        values = []
        for m in recent_metrics:
            if hasattr(m, metric_name):
                values.append(getattr(m, metric_name))

        if len(values) < 5:
            return "stable"

        # Simple trend analysis
        first_half = values[: len(values) // 2]
        second_half = values[len(values) // 2 :]

        first_avg = sum(first_half) / len(first_half)
        second_avg = sum(second_half) / len(second_half)

        diff_percent = (
            ((second_avg - first_avg) / first_avg) * 100 if first_avg > 0 else 0
        )

        if diff_percent > 10:
            return "increasing"
        elif diff_percent < -10:
            return "decreasing"
        else:
            return "stable"


class PerformanceAnalyzer:
    """Analyzes system performance and provides recommendations."""

    def __init__(self):
        """Initialize performance analyzer."""
        self.thresholds = {
            "cpu_high": 80.0,
            "cpu_critical": 95.0,
            "memory_high": 85.0,
            "memory_critical": 95.0,
            "load_high": 2.0,
            "load_critical": 4.0,
            "disk_io_high": 100.0,  # MB/s
            "network_high": 100.0,  # MB/s
            "gpu_high": 90.0,
            "gpu_memory_high": 90.0,
        }

    def analyze_performance(
        self, current_metrics: SystemMetrics, load_tracker: LoadTracker
    ) -> PerformanceAnalysis:
        """Analyze current performance and provide recommendations."""

        bottlenecks = []
        recommendations = []
        health_score = 100.0

        # CPU analysis
        if current_metrics.cpu_usage > self.thresholds["cpu_critical"]:
            bottlenecks.append("CPU critically overloaded")
            recommendations.append("Reduce parallel task count immediately")
            health_score -= 30
        elif current_metrics.cpu_usage > self.thresholds["cpu_high"]:
            bottlenecks.append("High CPU usage")
            recommendations.append("Consider reducing CPU-intensive tasks")
            health_score -= 15

        # Memory analysis
        if current_metrics.memory_usage > self.thresholds["memory_critical"]:
            bottlenecks.append("Memory critically low")
            recommendations.append("Free memory or reduce memory-intensive tasks")
            health_score -= 35
        elif current_metrics.memory_usage > self.thresholds["memory_high"]:
            bottlenecks.append("High memory usage")
            recommendations.append("Monitor memory usage closely")
            health_score -= 20

        # Load average analysis
        if current_metrics.load_average[0] > self.thresholds["load_critical"]:
            bottlenecks.append("System load critical")
            recommendations.append("Reduce system load immediately")
            health_score -= 25
        elif current_metrics.load_average[0] > self.thresholds["load_high"]:
            bottlenecks.append("High system load")
            recommendations.append("Monitor system load")
            health_score -= 10

        # I/O analysis
        total_disk_io = current_metrics.disk_io_read + current_metrics.disk_io_write
        if total_disk_io > self.thresholds["disk_io_high"]:
            bottlenecks.append("High disk I/O")
            recommendations.append("Reduce disk-intensive operations")
            health_score -= 10

        # Network analysis
        total_network = current_metrics.network_sent + current_metrics.network_recv
        if total_network > self.thresholds["network_high"]:
            bottlenecks.append("High network usage")
            recommendations.append("Monitor network bandwidth")
            health_score -= 5

        # GPU analysis (if available)
        if current_metrics.gpu_usage is not None:
            if current_metrics.gpu_usage > self.thresholds["gpu_high"]:
                bottlenecks.append("High GPU usage")
                recommendations.append("Reduce GPU workload")
                health_score -= 15

        # Queue depth analysis
        if current_metrics.queue_depth > 20:
            bottlenecks.append("High task queue depth")
            recommendations.append("Process queue backlog")
            health_score -= 10

        # Determine overall health
        if health_score >= 80:
            overall_health = SystemHealth.HEALTHY
        elif health_score >= 60:
            overall_health = SystemHealth.MODERATE
        elif health_score >= 40:
            overall_health = SystemHealth.STRESSED
        else:
            overall_health = SystemHealth.CRITICAL

        # Get trend direction
        cpu_trend = load_tracker.get_trend("cpu_usage", 180)  # 3 minutes
        memory_trend = load_tracker.get_trend("memory_usage", 180)

        if cpu_trend == "increasing" or memory_trend == "increasing":
            trend_direction = "degrading"
        elif cpu_trend == "decreasing" and memory_trend == "decreasing":
            trend_direction = "improving"
        else:
            trend_direction = "stable"

        # Predict capacity
        predicted_capacity = self._predict_capacity(current_metrics, load_tracker)

        return PerformanceAnalysis(
            overall_health=overall_health,
            bottlenecks=bottlenecks,
            recommendations=recommendations,
            trend_direction=trend_direction,
            predicted_capacity=predicted_capacity,
        )

    def _predict_capacity(
        self, current_metrics: SystemMetrics, load_tracker: LoadTracker
    ) -> float:
        """Predict system capacity in next 5 minutes."""
        # Simple linear extrapolation based on trends
        cpu_trend = load_tracker.get_trend("cpu_usage", 300)
        memory_trend = load_tracker.get_trend("memory_usage", 300)

        # Current capacity (inverse of max utilization)
        current_cpu_capacity = max(0, 100 - current_metrics.cpu_usage)
        current_memory_capacity = max(0, 100 - current_metrics.memory_usage)
        current_capacity = min(current_cpu_capacity, current_memory_capacity)

        # Adjust based on trends
        if cpu_trend == "increasing" or memory_trend == "increasing":
            # Degrading trend, reduce predicted capacity
            predicted_capacity = current_capacity * 0.8
        elif cpu_trend == "decreasing" and memory_trend == "decreasing":
            # Improving trend, increase predicted capacity
            predicted_capacity = min(100, current_capacity * 1.2)
        else:
            # Stable trend
            predicted_capacity = current_capacity

        return max(0, min(100, predicted_capacity))


class SystemMonitor:
    """Main system monitoring class with real-time metrics collection."""

    def __init__(self, collection_interval: float = 1.0):
        """
        Initialize system monitor.

        Args:
            collection_interval: Seconds between metric collections
        """
        self.collection_interval = collection_interval
        self.metrics_collector = MetricsCollector()
        self.load_tracker = LoadTracker()
        self.performance_analyzer = PerformanceAnalyzer()

        self._monitoring = False
        self._monitor_task: asyncio.Task | None = None
        self._current_metrics: SystemMetrics | None = None
        self._queue_depth = 0

        logger.info(f"System monitor initialized with {collection_interval}s interval")

    async def start_monitoring(self):
        """Start continuous system monitoring."""
        if self._monitoring:
            logger.warning("System monitoring already started")
            return

        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("System monitoring started")

    async def stop_monitoring(self):
        """Stop system monitoring."""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("System monitoring stopped")

    async def _monitoring_loop(self):
        """Continuous monitoring loop."""
        try:
            while self._monitoring:
                # Collect metrics
                metrics = self.metrics_collector.collect_metrics()
                metrics.queue_depth = (
                    self._queue_depth
                )  # Update with external queue depth

                # Store current metrics
                self._current_metrics = metrics

                # Add to history
                await self.load_tracker.add_metrics(metrics)

                # Wait for next collection
                await asyncio.sleep(self.collection_interval)

        except asyncio.CancelledError:
            logger.info("Monitoring loop cancelled")
        except Exception as e:
            logger.error(f"Monitoring loop error: {e}")

    def get_system_metrics(self) -> SystemMetrics | None:
        """Get latest system metrics."""
        return self._current_metrics

    def update_queue_depth(self, depth: int):
        """Update task queue depth from external systems."""
        self._queue_depth = depth

    def get_performance_analysis(self) -> PerformanceAnalysis | None:
        """Get current performance analysis."""
        if not self._current_metrics:
            return None

        return self.performance_analyzer.analyze_performance(
            self._current_metrics, self.load_tracker
        )

    def get_average_metrics(self, window_seconds: int = 60) -> SystemMetrics | None:
        """Get average metrics over specified window."""
        return self.load_tracker.get_average_load(window_seconds)

    def get_health_status(self) -> SystemHealth:
        """Get current system health status."""
        analysis = self.get_performance_analysis()
        if analysis:
            return analysis.overall_health
        return SystemHealth.HEALTHY

    def is_overloaded(self) -> bool:
        """Check if system is currently overloaded."""
        analysis = self.get_performance_analysis()
        if analysis:
            return analysis.overall_health in [
                SystemHealth.STRESSED,
                SystemHealth.CRITICAL,
            ]
        return False

    def get_resource_utilization(self) -> dict[str, float]:
        """Get current resource utilization percentages."""
        if not self._current_metrics:
            return {}

        utilization = {
            "cpu": self._current_metrics.cpu_usage,
            "memory": self._current_metrics.memory_usage,
            "load_1min": self._current_metrics.load_average[0]
            * 25,  # Normalize to percentage
        }

        if self._current_metrics.gpu_usage is not None:
            utilization["gpu"] = self._current_metrics.gpu_usage
            utilization["gpu_memory"] = self._current_metrics.gpu_memory

        return utilization


# Factory function
def create_system_monitor(collection_interval: float = 1.0) -> SystemMonitor:
    """
    Create a system monitor instance.

    Args:
        collection_interval: Seconds between metric collections

    Returns:
        Configured SystemMonitor instance
    """
    return SystemMonitor(collection_interval)
