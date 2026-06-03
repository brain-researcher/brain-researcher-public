"""Workflow Profiler

Provides performance profiling capabilities for DAG workflow execution
including timing analysis, memory usage tracking, and flamegraph generation.
"""

import asyncio
import json
import logging
import time
import sys
import gc
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
import statistics
import tracemalloc
from collections import defaultdict, deque
import os


logger = logging.getLogger(__name__)


class ProfilingType(str, Enum):
    """Types of profiling"""
    CPU = "cpu"
    MEMORY = "memory"
    IO = "io"
    NETWORK = "network"
    CUSTOM = "custom"


class ResourceType(str, Enum):
    """Types of resources to monitor"""
    CPU_PERCENT = "cpu_percent"
    MEMORY_RSS = "memory_rss"
    MEMORY_VMS = "memory_vms"
    MEMORY_PERCENT = "memory_percent"
    DISK_IO_READ = "disk_io_read"
    DISK_IO_WRITE = "disk_io_write"
    NETWORK_IO_SENT = "network_io_sent"
    NETWORK_IO_RECV = "network_io_recv"
    THREADS = "threads"
    FILE_DESCRIPTORS = "file_descriptors"


@dataclass
class ResourceSnapshot:
    """Snapshot of system resources at a point in time"""
    timestamp: datetime
    cpu_percent: float
    memory_rss: int  # Resident Set Size in bytes
    memory_vms: int  # Virtual Memory Size in bytes
    memory_percent: float
    disk_io_read: int  # Bytes read
    disk_io_write: int  # Bytes written
    network_io_sent: int  # Bytes sent
    network_io_recv: int  # Bytes received
    threads: int
    file_descriptors: int
    custom_metrics: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @staticmethod
    def capture() -> 'ResourceSnapshot':
        """Capture current system resource snapshot"""
        process = psutil.Process()

        # Get memory info
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()

        # Get CPU percent
        cpu_percent = process.cpu_percent()

        # Get I/O counters
        try:
            io_counters = process.io_counters()
            disk_read = io_counters.read_bytes
            disk_write = io_counters.write_bytes
        except (AttributeError, psutil.AccessDenied):
            disk_read = 0
            disk_write = 0

        # Get network I/O (system-wide)
        try:
            net_counters = psutil.net_io_counters()
            net_sent = net_counters.bytes_sent if net_counters else 0
            net_recv = net_counters.bytes_recv if net_counters else 0
        except (AttributeError, psutil.AccessDenied):
            net_sent = 0
            net_recv = 0

        # Get thread count
        try:
            threads = process.num_threads()
        except (AttributeError, psutil.AccessDenied):
            threads = 0

        # Get file descriptor count
        try:
            file_descriptors = process.num_fds() if hasattr(process, 'num_fds') else 0
        except (AttributeError, psutil.AccessDenied):
            file_descriptors = 0

        return ResourceSnapshot(
            timestamp=datetime.utcnow(),
            cpu_percent=cpu_percent,
            memory_rss=memory_info.rss,
            memory_vms=memory_info.vms,
            memory_percent=memory_percent,
            disk_io_read=disk_read,
            disk_io_write=disk_write,
            network_io_sent=net_sent,
            network_io_recv=net_recv,
            threads=threads,
            file_descriptors=file_descriptors
        )


@dataclass
class NodeProfile:
    """Performance profile for a single node"""
    node_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    cpu_time: float = 0.0  # CPU time in seconds
    wall_time: float = 0.0  # Wall clock time in seconds
    memory_peak: int = 0  # Peak memory usage in bytes
    memory_allocated: int = 0  # Total memory allocated in bytes
    io_operations: int = 0  # Number of I/O operations
    network_calls: int = 0  # Number of network calls
    child_profiles: Dict[str, 'NodeProfile'] = field(default_factory=dict)
    resource_snapshots: List[ResourceSnapshot] = field(default_factory=list)
    custom_metrics: Dict[str, Any] = field(default_factory=dict)

    def finish(self):
        """Mark profile as finished"""
        if self.end_time is None:
            self.end_time = datetime.utcnow()
            self.wall_time = (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['start_time'] = self.start_time.isoformat()
        if self.end_time:
            data['end_time'] = self.end_time.isoformat()
        data['resource_snapshots'] = [snap.to_dict() for snap in self.resource_snapshots]
        return data


@dataclass
class ProfilingSession:
    """A profiling session for an entire execution"""
    session_id: str
    dag_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    node_profiles: Dict[str, NodeProfile] = field(default_factory=dict)
    global_snapshots: List[ResourceSnapshot] = field(default_factory=list)
    profiling_overhead_ms: float = 0.0
    enabled_profiling_types: Set[ProfilingType] = field(default_factory=set)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['start_time'] = self.start_time.isoformat()
        if self.end_time:
            data['end_time'] = self.end_time.isoformat()
        data['node_profiles'] = {k: v.to_dict() for k, v in self.node_profiles.items()}
        data['global_snapshots'] = [snap.to_dict() for snap in self.global_snapshots]
        data['enabled_profiling_types'] = list(self.enabled_profiling_types)
        return data


@dataclass
class PerformanceAnalysis:
    """Analysis results of profiling data"""
    session_id: str
    analysis_time: datetime
    total_execution_time: float

    # Timing analysis
    slowest_nodes: List[Dict[str, Any]] = field(default_factory=list)
    fastest_nodes: List[Dict[str, Any]] = field(default_factory=list)
    timing_statistics: Dict[str, float] = field(default_factory=dict)

    # Memory analysis
    memory_peak: int = 0
    memory_growth_rate: float = 0.0  # bytes per second
    memory_hotspots: List[Dict[str, Any]] = field(default_factory=list)

    # Resource analysis
    cpu_utilization: Dict[str, float] = field(default_factory=dict)
    io_analysis: Dict[str, Any] = field(default_factory=dict)

    # Optimization recommendations
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['analysis_time'] = self.analysis_time.isoformat()
        return data


class MemoryTracker:
    """Tracks memory allocations during execution"""

    def __init__(self):
        self.tracking = False
        self.snapshots = []
        self.allocation_stats = defaultdict(int)

    def start_tracking(self):
        """Start memory tracking"""
        if not self.tracking:
            tracemalloc.start()
            self.tracking = True
            logger.info("Started memory tracking")

    def stop_tracking(self):
        """Stop memory tracking"""
        if self.tracking:
            tracemalloc.stop()
            self.tracking = False
            logger.info("Stopped memory tracking")

    def take_snapshot(self, label: str = None) -> Dict[str, Any]:
        """Take a memory snapshot"""
        if not self.tracking:
            return {}

        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')

        total_size = sum(stat.size for stat in top_stats)

        # Get top memory consumers
        top_consumers = []
        for i, stat in enumerate(top_stats[:10]):
            top_consumers.append({
                'rank': i + 1,
                'filename': stat.traceback.format()[-1] if stat.traceback else 'unknown',
                'size_bytes': stat.size,
                'size_mb': stat.size / 1024 / 1024,
                'count': stat.count
            })

        snapshot_data = {
            'label': label,
            'timestamp': datetime.utcnow().isoformat(),
            'total_size_bytes': total_size,
            'total_size_mb': total_size / 1024 / 1024,
            'top_consumers': top_consumers
        }

        self.snapshots.append(snapshot_data)
        return snapshot_data

    def compare_snapshots(self, snapshot1_idx: int, snapshot2_idx: int) -> Dict[str, Any]:
        """Compare two memory snapshots"""
        if (snapshot1_idx >= len(self.snapshots) or
            snapshot2_idx >= len(self.snapshots)):
            return {}

        snap1 = self.snapshots[snapshot1_idx]
        snap2 = self.snapshots[snapshot2_idx]

        size_diff = snap2['total_size_bytes'] - snap1['total_size_bytes']

        return {
            'snapshot1': snap1['label'],
            'snapshot2': snap2['label'],
            'size_difference_bytes': size_diff,
            'size_difference_mb': size_diff / 1024 / 1024,
            'growth_rate_mb_per_sec': size_diff / 1024 / 1024 / max(1,
                (datetime.fromisoformat(snap2['timestamp']) -
                 datetime.fromisoformat(snap1['timestamp'])).total_seconds())
        }


class ResourceMonitor:
    """Monitors system resources during execution"""

    def __init__(self, sampling_interval: float = 1.0):
        self.sampling_interval = sampling_interval
        self.monitoring = False
        self.monitor_thread = None
        self.snapshots = deque(maxlen=1000)  # Keep last 1000 snapshots

    def start_monitoring(self):
        """Start resource monitoring"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            logger.info("Started resource monitoring")

    def stop_monitoring(self):
        """Stop resource monitoring"""
        if self.monitoring:
            self.monitoring = False
            if self.monitor_thread:
                self.monitor_thread.join(timeout=2.0)
            logger.info("Stopped resource monitoring")

    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.monitoring:
            try:
                snapshot = ResourceSnapshot.capture()
                self.snapshots.append(snapshot)
                time.sleep(self.sampling_interval)
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
                time.sleep(1.0)

    def get_snapshots(self, limit: int = None) -> List[ResourceSnapshot]:
        """Get recent resource snapshots"""
        if limit:
            return list(self.snapshots)[-limit:]
        return list(self.snapshots)

    def get_resource_timeline(self, resource_type: ResourceType) -> List[Tuple[datetime, float]]:
        """Get timeline for a specific resource type"""
        timeline = []

        for snapshot in self.snapshots:
            if resource_type == ResourceType.CPU_PERCENT:
                value = snapshot.cpu_percent
            elif resource_type == ResourceType.MEMORY_RSS:
                value = snapshot.memory_rss
            elif resource_type == ResourceType.MEMORY_VMS:
                value = snapshot.memory_vms
            elif resource_type == ResourceType.MEMORY_PERCENT:
                value = snapshot.memory_percent
            elif resource_type == ResourceType.DISK_IO_READ:
                value = snapshot.disk_io_read
            elif resource_type == ResourceType.DISK_IO_WRITE:
                value = snapshot.disk_io_write
            elif resource_type == ResourceType.NETWORK_IO_SENT:
                value = snapshot.network_io_sent
            elif resource_type == ResourceType.NETWORK_IO_RECV:
                value = snapshot.network_io_recv
            elif resource_type == ResourceType.THREADS:
                value = snapshot.threads
            elif resource_type == ResourceType.FILE_DESCRIPTORS:
                value = snapshot.file_descriptors
            else:
                continue

            timeline.append((snapshot.timestamp, value))

        return timeline


class FlamegraphGenerator:
    """Generates flamegraph data for visualization"""

    def __init__(self):
        pass

    def generate_flamegraph_data(self, session: ProfilingSession) -> Dict[str, Any]:
        """Generate flamegraph data from profiling session"""
        # Build call stack structure
        root_node = {
            'name': 'root',
            'value': 0,
            'children': {}
        }

        # Process each node profile
        for node_id, profile in session.node_profiles.items():
            self._add_to_flamegraph(root_node, [node_id], profile.wall_time)

            # Add child profiles
            for child_id, child_profile in profile.child_profiles.items():
                self._add_to_flamegraph(root_node, [node_id, child_id], child_profile.wall_time)

        # Convert to flamegraph format
        return self._convert_to_flamegraph_format(root_node)

    def _add_to_flamegraph(self, root: Dict, path: List[str], value: float):
        """Add a path to the flamegraph structure"""
        current = root

        for node_name in path:
            if node_name not in current['children']:
                current['children'][node_name] = {
                    'name': node_name,
                    'value': 0,
                    'children': {}
                }
            current = current['children'][node_name]
            current['value'] += value

    def _convert_to_flamegraph_format(self, node: Dict) -> Dict[str, Any]:
        """Convert internal format to flamegraph format"""
        result = {
            'name': node['name'],
            'value': node['value']
        }

        if node['children']:
            result['children'] = [
                self._convert_to_flamegraph_format(child)
                for child in node['children'].values()
            ]

        return result


class WorkflowProfiler:
    """Main workflow profiler"""

    def __init__(self):
        self.active_sessions: Dict[str, ProfilingSession] = {}
        self.completed_sessions: Dict[str, ProfilingSession] = {}

        # Components
        self.memory_tracker = MemoryTracker()
        self.resource_monitor = ResourceMonitor()
        self.flamegraph_generator = FlamegraphGenerator()

        # Analysis cache
        self.analysis_cache: Dict[str, PerformanceAnalysis] = {}

        logger.info("Workflow profiler initialized")

    async def start_profiling_session(self,
                                    dag_id: str,
                                    profiling_types: Set[ProfilingType] = None) -> str:
        """Start a new profiling session"""
        session_id = f"profile_{dag_id}_{int(time.time())}"

        if profiling_types is None:
            profiling_types = {ProfilingType.CPU, ProfilingType.MEMORY}

        session = ProfilingSession(
            session_id=session_id,
            dag_id=dag_id,
            start_time=datetime.utcnow(),
            enabled_profiling_types=profiling_types
        )

        self.active_sessions[session_id] = session

        # Start appropriate monitoring
        if ProfilingType.MEMORY in profiling_types:
            self.memory_tracker.start_tracking()

        if ProfilingType.CPU in profiling_types or ProfilingType.IO in profiling_types:
            self.resource_monitor.start_monitoring()

        logger.info(f"Started profiling session {session_id} for DAG {dag_id}")
        return session_id

    async def end_profiling_session(self, session_id: str) -> bool:
        """End a profiling session"""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        session.end_time = datetime.utcnow()

        # Stop monitoring if no other active sessions need it
        if not any(ProfilingType.MEMORY in s.enabled_profiling_types
                  for s in self.active_sessions.values() if s.session_id != session_id):
            self.memory_tracker.stop_tracking()

        if not any(ProfilingType.CPU in s.enabled_profiling_types or
                  ProfilingType.IO in s.enabled_profiling_types
                  for s in self.active_sessions.values() if s.session_id != session_id):
            self.resource_monitor.stop_monitoring()

        # Move to completed sessions
        self.completed_sessions[session_id] = session
        del self.active_sessions[session_id]

        logger.info(f"Ended profiling session {session_id}")
        return True

    async def profile_node(self, session_id: str, node_id: str) -> Optional[str]:
        """Start profiling a specific node"""
        if session_id not in self.active_sessions:
            return None

        session = self.active_sessions[session_id]

        profile = NodeProfile(
            node_id=node_id,
            start_time=datetime.utcnow()
        )

        # Take initial snapshots
        if ProfilingType.MEMORY in session.enabled_profiling_types:
            self.memory_tracker.take_snapshot(f"node_{node_id}_start")

        session.node_profiles[node_id] = profile

        return node_id

    async def finish_node_profile(self, session_id: str, node_id: str) -> bool:
        """Finish profiling a specific node"""
        if (session_id not in self.active_sessions or
            node_id not in self.active_sessions[session_id].node_profiles):
            return False

        session = self.active_sessions[session_id]
        profile = session.node_profiles[node_id]

        profile.finish()

        # Take final snapshots
        if ProfilingType.MEMORY in session.enabled_profiling_types:
            self.memory_tracker.take_snapshot(f"node_{node_id}_end")

        # Get resource snapshots during node execution
        if ProfilingType.CPU in session.enabled_profiling_types:
            # Get snapshots from the time window of node execution
            snapshots = self.resource_monitor.get_snapshots()
            node_snapshots = [
                snap for snap in snapshots
                if profile.start_time <= snap.timestamp <= (profile.end_time or datetime.utcnow())
            ]
            profile.resource_snapshots = node_snapshots

        return True

    async def add_custom_metric(self,
                              session_id: str,
                              node_id: str,
                              metric_name: str,
                              metric_value: Any) -> bool:
        """Add a custom metric to node profile"""
        if (session_id not in self.active_sessions or
            node_id not in self.active_sessions[session_id].node_profiles):
            return False

        profile = self.active_sessions[session_id].node_profiles[node_id]
        profile.custom_metrics[metric_name] = metric_value

        return True

    async def get_profiling_session(self, session_id: str) -> Optional[ProfilingSession]:
        """Get profiling session data"""
        if session_id in self.active_sessions:
            return self.active_sessions[session_id]
        elif session_id in self.completed_sessions:
            return self.completed_sessions[session_id]
        return None

    async def analyze_performance(self, session_id: str) -> Optional[PerformanceAnalysis]:
        """Analyze performance data from profiling session"""

        # Check cache first
        if session_id in self.analysis_cache:
            return self.analysis_cache[session_id]

        session = await self.get_profiling_session(session_id)
        if not session:
            return None

        # Calculate total execution time
        if session.end_time:
            total_time = (session.end_time - session.start_time).total_seconds()
        else:
            total_time = (datetime.utcnow() - session.start_time).total_seconds()

        # Analyze node timings
        node_times = [(node_id, profile.wall_time)
                     for node_id, profile in session.node_profiles.items()
                     if profile.wall_time > 0]

        node_times.sort(key=lambda x: x[1], reverse=True)

        slowest_nodes = [
            {
                'node_id': node_id,
                'wall_time_seconds': wall_time,
                'percentage_of_total': (wall_time / total_time * 100) if total_time > 0 else 0
            }
            for node_id, wall_time in node_times[:5]
        ]

        fastest_nodes = [
            {
                'node_id': node_id,
                'wall_time_seconds': wall_time,
                'percentage_of_total': (wall_time / total_time * 100) if total_time > 0 else 0
            }
            for node_id, wall_time in node_times[-5:]
        ]

        # Timing statistics
        wall_times = [profile.wall_time for profile in session.node_profiles.values()
                     if profile.wall_time > 0]

        timing_stats = {}
        if wall_times:
            timing_stats = {
                'mean': statistics.mean(wall_times),
                'median': statistics.median(wall_times),
                'min': min(wall_times),
                'max': max(wall_times),
                'std_dev': statistics.stdev(wall_times) if len(wall_times) > 1 else 0.0
            }

        # Memory analysis
        memory_peak = 0
        memory_hotspots = []

        for node_id, profile in session.node_profiles.items():
            if profile.memory_peak > memory_peak:
                memory_peak = profile.memory_peak

            if profile.memory_peak > 0:
                memory_hotspots.append({
                    'node_id': node_id,
                    'memory_peak_bytes': profile.memory_peak,
                    'memory_peak_mb': profile.memory_peak / 1024 / 1024
                })

        memory_hotspots.sort(key=lambda x: x['memory_peak_bytes'], reverse=True)
        memory_hotspots = memory_hotspots[:5]

        # CPU utilization analysis
        cpu_utilization = {}
        for node_id, profile in session.node_profiles.items():
            if profile.resource_snapshots:
                cpu_values = [snap.cpu_percent for snap in profile.resource_snapshots]
                if cpu_values:
                    cpu_utilization[node_id] = {
                        'mean': statistics.mean(cpu_values),
                        'max': max(cpu_values),
                        'min': min(cpu_values)
                    }

        # Generate recommendations
        recommendations = []

        if slowest_nodes:
            slowest = slowest_nodes[0]
            if slowest['percentage_of_total'] > 50:
                recommendations.append(
                    f"Node '{slowest['node_id']}' takes {slowest['percentage_of_total']:.1f}% "
                    f"of execution time. Consider optimizing this node."
                )

        if memory_hotspots:
            hottest = memory_hotspots[0]
            if hottest['memory_peak_mb'] > 1000:  # > 1GB
                recommendations.append(
                    f"Node '{hottest['node_id']}' uses {hottest['memory_peak_mb']:.1f}MB "
                    f"of memory. Consider memory optimization."
                )

        if timing_stats and len(wall_times) > 1:
            if timing_stats['std_dev'] > timing_stats['mean']:
                recommendations.append(
                    "High variance in node execution times detected. "
                    "Consider load balancing or investigating inconsistent performance."
                )

        # Create analysis
        analysis = PerformanceAnalysis(
            session_id=session_id,
            analysis_time=datetime.utcnow(),
            total_execution_time=total_time,
            slowest_nodes=slowest_nodes,
            fastest_nodes=fastest_nodes,
            timing_statistics=timing_stats,
            memory_peak=memory_peak,
            memory_hotspots=memory_hotspots,
            cpu_utilization=cpu_utilization,
            recommendations=recommendations
        )

        # Cache analysis
        self.analysis_cache[session_id] = analysis

        return analysis

    async def generate_flamegraph(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Generate flamegraph data for session"""
        session = await self.get_profiling_session(session_id)
        if not session:
            return None

        return self.flamegraph_generator.generate_flamegraph_data(session)

    async def find_optimization_opportunities(self, session_id: str) -> List[Dict[str, Any]]:
        """Find optimization opportunities in profiling data"""
        analysis = await self.analyze_performance(session_id)
        if not analysis:
            return []

        opportunities = []

        # CPU optimization opportunities
        for node_id, cpu_stats in analysis.cpu_utilization.items():
            if cpu_stats['mean'] < 20:  # Low CPU usage
                opportunities.append({
                    'type': 'cpu_underutilization',
                    'node_id': node_id,
                    'description': f"Node '{node_id}' has low CPU utilization ({cpu_stats['mean']:.1f}%). "
                              f"Consider parallelizing or combining with other operations.",
                    'priority': 'medium'
                })
            elif cpu_stats['mean'] > 90:  # High CPU usage
                opportunities.append({
                    'type': 'cpu_bottleneck',
                    'node_id': node_id,
                    'description': f"Node '{node_id}' has high CPU utilization ({cpu_stats['mean']:.1f}%). "
                              f"Consider optimizing algorithms or scaling resources.",
                    'priority': 'high'
                })

        # Memory optimization opportunities
        for hotspot in analysis.memory_hotspots:
            if hotspot['memory_peak_mb'] > 500:  # > 500MB
                opportunities.append({
                    'type': 'memory_optimization',
                    'node_id': hotspot['node_id'],
                    'description': f"Node '{hotspot['node_id']}' uses {hotspot['memory_peak_mb']:.1f}MB "
                              f"of memory. Consider implementing memory pooling or streaming.",
                    'priority': 'high' if hotspot['memory_peak_mb'] > 1000 else 'medium'
                })

        # Parallelization opportunities
        if len(analysis.slowest_nodes) > 1:
            slow_nodes = [node['node_id'] for node in analysis.slowest_nodes[:3]]
            opportunities.append({
                'type': 'parallelization',
                'node_ids': slow_nodes,
                'description': f"Consider parallelizing nodes {slow_nodes} if they are independent.",
                'priority': 'medium'
            })

        return opportunities

    def get_profiler_statistics(self) -> Dict[str, Any]:
        """Get profiler statistics"""
        return {
            'active_sessions': len(self.active_sessions),
            'completed_sessions': len(self.completed_sessions),
            'total_sessions': len(self.active_sessions) + len(self.completed_sessions),
            'memory_tracking_active': self.memory_tracker.tracking,
            'resource_monitoring_active': self.resource_monitor.monitoring,
            'cached_analyses': len(self.analysis_cache),
            'memory_snapshots': len(self.memory_tracker.snapshots),
            'resource_snapshots': len(self.resource_monitor.snapshots)
        }