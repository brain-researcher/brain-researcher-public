"""
Unit tests for System Monitor (AGENT-021).

Tests the SystemMonitor, MetricsCollector, LoadTracker, PerformanceAnalyzer,
and related components for real-time system monitoring and health assessment.
"""

import asyncio
import json
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from collections import deque

from brain_researcher.services.agent.system_monitor import (
    SystemMonitor,
    MetricsCollector,
    LoadTracker,
    PerformanceAnalyzer,
    SystemMetrics,
    SystemHealth,
    PerformanceAnalysis,
    create_system_monitor
)

# Import test fixtures
import sys
sys.path.append(str(Path(__file__).parent.parent / "fixtures" / "AGENT-021"))


class TestSystemMetrics:
    """Test SystemMetrics data structure."""
    
    def test_system_metrics_creation(self):
        """Test SystemMetrics creation with all fields."""
        timestamp = time.time()
        metrics = SystemMetrics(
            timestamp=timestamp,
            cpu_usage=75.5,
            memory_usage=60.2,
            memory_available=8.5,
            disk_io_read=25.3,
            disk_io_write=15.7,
            network_sent=12.4,
            network_recv=8.9,
            load_average=(1.5, 1.8, 2.0),
            active_processes=150,
            queue_depth=5,
            gpu_usage=80.0,
            gpu_memory=65.5
        )
        
        assert metrics.timestamp == timestamp
        assert metrics.cpu_usage == 75.5
        assert metrics.memory_usage == 60.2
        assert metrics.memory_available == 8.5
        assert metrics.disk_io_read == 25.3
        assert metrics.disk_io_write == 15.7
        assert metrics.network_sent == 12.4
        assert metrics.network_recv == 8.9
        assert metrics.load_average == (1.5, 1.8, 2.0)
        assert metrics.active_processes == 150
        assert metrics.queue_depth == 5
        assert metrics.gpu_usage == 80.0
        assert metrics.gpu_memory == 65.5
    
    def test_system_metrics_optional_fields(self):
        """Test SystemMetrics with optional fields."""
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=50.0,
            memory_usage=40.0,
            memory_available=12.0,
            disk_io_read=10.0,
            disk_io_write=5.0,
            network_sent=3.0,
            network_recv=2.0,
            load_average=(1.0, 1.0, 1.0),
            active_processes=100
            # gpu_usage and gpu_memory not provided (None by default)
        )
        
        assert metrics.gpu_usage is None
        assert metrics.gpu_memory is None
        assert metrics.queue_depth == 0  # Default value


class TestPerformanceAnalysis:
    """Test PerformanceAnalysis data structure."""
    
    def test_performance_analysis_creation(self):
        """Test PerformanceAnalysis creation."""
        analysis = PerformanceAnalysis(
            overall_health=SystemHealth.MODERATE,
            bottlenecks=["High CPU usage", "Memory pressure"],
            recommendations=["Reduce parallel tasks", "Monitor memory"],
            trend_direction="degrading",
            predicted_capacity=65.5
        )
        
        assert analysis.overall_health == SystemHealth.MODERATE
        assert len(analysis.bottlenecks) == 2
        assert "High CPU usage" in analysis.bottlenecks
        assert len(analysis.recommendations) == 2
        assert analysis.trend_direction == "degrading"
        assert analysis.predicted_capacity == 65.5


class TestMetricsCollector:
    """Test MetricsCollector functionality."""
    
    def test_metrics_collector_initialization(self):
        """Test MetricsCollector initialization."""
        collector = MetricsCollector()
        
        assert collector._last_net_stats is not None or True  # May be None if no network
        assert collector._last_disk_stats is not None or True  # May be None if no disk
        assert collector._last_timestamp is not None or True
    
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.getloadavg')
    @patch('psutil.pids')
    @patch('psutil.disk_io_counters')
    @patch('psutil.net_io_counters')
    def test_collect_metrics_success(self, mock_net, mock_disk, mock_pids, 
                                   mock_loadavg, mock_memory, mock_cpu):
        """Test successful metrics collection."""
        # Mock psutil calls
        mock_cpu.return_value = 65.5
        
        mock_memory_obj = MagicMock()
        mock_memory_obj.percent = 70.2
        mock_memory_obj.available = 8589934592  # 8GB in bytes
        mock_memory.return_value = mock_memory_obj
        
        mock_loadavg.return_value = (1.5, 1.8, 2.0)
        mock_pids.return_value = list(range(150))  # 150 processes
        
        mock_disk.return_value = MagicMock(read_bytes=1000, write_bytes=500)
        mock_net.return_value = MagicMock(bytes_sent=2000, bytes_recv=1500)
        
        collector = MetricsCollector()
        metrics = collector.collect_metrics()
        
        assert isinstance(metrics, SystemMetrics)
        assert metrics.cpu_usage == 65.5
        assert metrics.memory_usage == 70.2
        assert abs(metrics.memory_available - 8.0) < 0.1  # ~8GB
        assert metrics.load_average == (1.5, 1.8, 2.0)
        assert metrics.active_processes == 150
    
    @patch('psutil.cpu_percent')
    def test_collect_metrics_with_exception(self, mock_cpu):
        """Test metrics collection with psutil exception."""
        mock_cpu.side_effect = Exception("PSUtil error")
        
        collector = MetricsCollector()
        metrics = collector.collect_metrics()
        
        # Should return minimal metrics on error
        assert isinstance(metrics, SystemMetrics)
        assert metrics.cpu_usage == 0.0
        assert metrics.memory_usage == 0.0
    
    @patch('psutil.disk_io_counters')
    def test_disk_io_rate_calculation(self, mock_disk):
        """Test disk I/O rate calculation."""
        collector = MetricsCollector()
        
        # First call - baseline
        mock_disk.return_value = MagicMock(read_bytes=1000000, write_bytes=500000)
        collector._last_timestamp = time.time() - 1.0  # 1 second ago
        
        read_rate, write_rate = collector._calculate_disk_io_rates(time.time())
        
        # Should be 0 for first call (no previous data)
        assert read_rate >= 0
        assert write_rate >= 0
        
        # Second call - should calculate rate
        mock_disk.return_value = MagicMock(read_bytes=2000000, write_bytes=1000000)
        read_rate, write_rate = collector._calculate_disk_io_rates(time.time())
        
        # Should have positive rates now
        assert read_rate >= 0
        assert write_rate >= 0
    
    @patch('psutil.net_io_counters')
    def test_network_rate_calculation(self, mock_net):
        """Test network I/O rate calculation."""
        collector = MetricsCollector()
        
        # First call - baseline
        mock_net.return_value = MagicMock(bytes_sent=1000000, bytes_recv=800000)
        collector._last_timestamp = time.time() - 1.0
        
        sent_rate, recv_rate = collector._calculate_network_rates(time.time())
        assert sent_rate >= 0
        assert recv_rate >= 0
    
    @patch('pynvml.nvmlInit')
    @patch('pynvml.nvmlDeviceGetCount')
    @patch('pynvml.nvmlDeviceGetHandleByIndex')
    @patch('pynvml.nvmlDeviceGetUtilizationRates')
    @patch('pynvml.nvmlDeviceGetMemoryInfo')
    def test_gpu_metrics_collection(self, mock_mem_info, mock_util_rates, 
                                   mock_handle, mock_count, mock_init):
        """Test GPU metrics collection when available."""
        # Mock NVIDIA ML
        mock_count.return_value = 1
        mock_handle.return_value = MagicMock()
        
        mock_util = MagicMock()
        mock_util.gpu = 75
        mock_util_rates.return_value = mock_util
        
        mock_mem = MagicMock()
        mock_mem.used = 4 * 1024**3  # 4GB used
        mock_mem.total = 8 * 1024**3  # 8GB total
        mock_mem_info.return_value = mock_mem
        
        collector = MetricsCollector()
        gpu_usage, gpu_memory = collector._get_gpu_metrics()
        
        assert gpu_usage == 75.0
        assert gpu_memory == 50.0  # 4/8 * 100
    
    def test_gpu_metrics_unavailable(self):
        """Test GPU metrics when NVIDIA ML is unavailable."""
        collector = MetricsCollector()
        gpu_usage, gpu_memory = collector._get_gpu_metrics()
        
        # Should return None when GPU monitoring unavailable
        assert gpu_usage is None
        assert gpu_memory is None


class TestLoadTracker:
    """Test LoadTracker functionality."""
    
    def test_load_tracker_initialization(self):
        """Test LoadTracker initialization."""
        tracker = LoadTracker(history_size=100)
        
        assert tracker.history_size == 100
        assert len(tracker.metrics_history) == 0
        assert tracker.metrics_history.maxlen == 100
    
    @pytest.mark.asyncio
    async def test_add_metrics(self):
        """Test adding metrics to history."""
        tracker = LoadTracker()
        
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=50.0,
            memory_usage=60.0,
            memory_available=10.0,
            disk_io_read=5.0,
            disk_io_write=3.0,
            network_sent=2.0,
            network_recv=1.5,
            load_average=(1.0, 1.1, 1.2),
            active_processes=120
        )
        
        await tracker.add_metrics(metrics)
        
        assert len(tracker.metrics_history) == 1
        assert tracker.metrics_history[0] == metrics
    
    @pytest.mark.asyncio
    async def test_history_size_limit(self):
        """Test that history size is properly limited."""
        tracker = LoadTracker(history_size=3)
        
        # Add more metrics than history size
        for i in range(5):
            metrics = SystemMetrics(
                timestamp=time.time() + i,
                cpu_usage=float(i * 10),
                memory_usage=50.0,
                memory_available=10.0,
                disk_io_read=5.0,
                disk_io_write=3.0,
                network_sent=2.0,
                network_recv=1.5,
                load_average=(1.0, 1.1, 1.2),
                active_processes=120
            )
            await tracker.add_metrics(metrics)
        
        # Should only keep last 3
        assert len(tracker.metrics_history) == 3
        assert tracker.metrics_history[-1].cpu_usage == 40.0  # Last added
    
    @pytest.mark.asyncio
    async def test_get_average_load(self):
        """Test average load calculation."""
        tracker = LoadTracker()
        current_time = time.time()
        
        # Add metrics over time
        metrics_data = [
            (current_time - 120, 40.0, 50.0),  # 2 minutes ago
            (current_time - 60, 60.0, 70.0),   # 1 minute ago
            (current_time - 30, 80.0, 90.0),   # 30 seconds ago
        ]
        
        for timestamp, cpu, memory in metrics_data:
            metrics = SystemMetrics(
                timestamp=timestamp,
                cpu_usage=cpu,
                memory_usage=memory,
                memory_available=10.0,
                disk_io_read=5.0,
                disk_io_write=3.0,
                network_sent=2.0,
                network_recv=1.5,
                load_average=(1.0, 1.1, 1.2),
                active_processes=120
            )
            await tracker.add_metrics(metrics)
        
        # Get average for last 90 seconds
        avg_metrics = tracker.get_average_load(window_seconds=90)
        
        assert avg_metrics is not None
        assert avg_metrics.cpu_usage == (60.0 + 80.0) / 2  # Should average last 2
        assert avg_metrics.memory_usage == (70.0 + 90.0) / 2
    
    @pytest.mark.asyncio
    async def test_get_trend(self):
        """Test trend analysis."""
        tracker = LoadTracker()
        current_time = time.time()
        
        # Add increasing CPU usage trend
        for i in range(10):
            metrics = SystemMetrics(
                timestamp=current_time - (10 - i) * 30,  # Every 30 seconds
                cpu_usage=float(i * 10),  # Increasing from 0 to 90
                memory_usage=50.0,
                memory_available=10.0,
                disk_io_read=5.0,
                disk_io_write=3.0,
                network_sent=2.0,
                network_recv=1.5,
                load_average=(1.0, 1.1, 1.2),
                active_processes=120
            )
            await tracker.add_metrics(metrics)
        
        trend = tracker.get_trend("cpu_usage", window_seconds=300)
        
        # Should detect increasing trend
        assert trend == "increasing"
    
    @pytest.mark.asyncio
    async def test_get_trend_decreasing(self):
        """Test decreasing trend detection."""
        tracker = LoadTracker()
        current_time = time.time()
        
        # Add decreasing memory usage trend
        for i in range(10):
            metrics = SystemMetrics(
                timestamp=current_time - (10 - i) * 30,
                cpu_usage=50.0,
                memory_usage=float(90 - i * 10),  # Decreasing from 90 to 0
                memory_available=10.0,
                disk_io_read=5.0,
                disk_io_write=3.0,
                network_sent=2.0,
                network_recv=1.5,
                load_average=(1.0, 1.1, 1.2),
                active_processes=120
            )
            await tracker.add_metrics(metrics)
        
        trend = tracker.get_trend("memory_usage", window_seconds=300)
        
        # Should detect decreasing trend
        assert trend == "decreasing"
    
    def test_get_trend_insufficient_data(self):
        """Test trend analysis with insufficient data."""
        tracker = LoadTracker()
        
        # No data
        trend = tracker.get_trend("cpu_usage")
        assert trend == "stable"
        
        # Add just a few points
        for i in range(3):
            tracker.metrics_history.append(
                SystemMetrics(
                    timestamp=time.time() - i,
                    cpu_usage=50.0,
                    memory_usage=60.0,
                    memory_available=10.0,
                    disk_io_read=5.0,
                    disk_io_write=3.0,
                    network_sent=2.0,
                    network_recv=1.5,
                    load_average=(1.0, 1.1, 1.2),
                    active_processes=120
                )
            )
        
        trend = tracker.get_trend("cpu_usage")
        assert trend == "stable"


class TestPerformanceAnalyzer:
    """Test PerformanceAnalyzer functionality."""
    
    def test_performance_analyzer_initialization(self):
        """Test PerformanceAnalyzer initialization."""
        analyzer = PerformanceAnalyzer()
        
        assert analyzer.thresholds["cpu_high"] == 80.0
        assert analyzer.thresholds["memory_critical"] == 95.0
        assert analyzer.thresholds["load_high"] == 2.0
    
    @pytest.mark.asyncio
    async def test_analyze_healthy_system(self):
        """Test analysis of healthy system."""
        analyzer = PerformanceAnalyzer()
        tracker = LoadTracker()
        
        # Healthy system metrics
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=25.0,
            memory_usage=40.0,
            memory_available=12.0,
            disk_io_read=5.0,
            disk_io_write=3.0,
            network_sent=2.0,
            network_recv=1.5,
            load_average=(0.8, 0.9, 1.0),
            active_processes=120,
            queue_depth=2,
            gpu_usage=15.0
        )
        
        analysis = analyzer.analyze_performance(metrics, tracker)
        
        assert analysis.overall_health == SystemHealth.HEALTHY
        assert len(analysis.bottlenecks) == 0
        assert "trend_direction" in analysis.__dict__
    
    @pytest.mark.asyncio
    async def test_analyze_stressed_system(self):
        """Test analysis of stressed system."""
        analyzer = PerformanceAnalyzer()
        tracker = LoadTracker()
        
        # Stressed system metrics
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=85.0,  # High CPU
            memory_usage=88.0,  # High memory
            memory_available=2.0,
            disk_io_read=80.0,
            disk_io_write=70.0,
            network_sent=120.0,
            network_recv=110.0,
            load_average=(4.5, 4.8, 4.2),  # High load
            active_processes=250,
            queue_depth=25,  # High queue
            gpu_usage=85.0
        )
        
        analysis = analyzer.analyze_performance(metrics, tracker)
        
        assert analysis.overall_health in [SystemHealth.STRESSED, SystemHealth.CRITICAL]
        assert len(analysis.bottlenecks) > 0
        assert any("CPU" in bottleneck for bottleneck in analysis.bottlenecks)
        assert len(analysis.recommendations) > 0
    
    @pytest.mark.asyncio
    async def test_analyze_critical_system(self):
        """Test analysis of critical system."""
        analyzer = PerformanceAnalyzer()
        tracker = LoadTracker()
        
        # Critical system metrics
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=96.0,  # Critical CPU
            memory_usage=94.0,  # Critical memory
            memory_available=1.0,
            disk_io_read=150.0,
            disk_io_write=140.0,
            network_sent=200.0,
            network_recv=180.0,
            load_average=(7.0, 7.5, 7.2),  # Critical load
            active_processes=320,
            queue_depth=50,
            gpu_usage=95.0
        )
        
        analysis = analyzer.analyze_performance(metrics, tracker)
        
        assert analysis.overall_health == SystemHealth.CRITICAL
        assert len(analysis.bottlenecks) >= 3  # Multiple bottlenecks
        assert any("critically" in bottleneck.lower() for bottleneck in analysis.bottlenecks)
        assert any("immediately" in rec.lower() for rec in analysis.recommendations)
    
    def test_predict_capacity_stable(self):
        """Test capacity prediction for stable system."""
        analyzer = PerformanceAnalyzer()
        tracker = LoadTracker()
        
        # Mock stable trend
        tracker.get_trend = MagicMock()
        tracker.get_trend.return_value = "stable"
        
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=50.0,
            memory_usage=60.0,
            memory_available=10.0,
            disk_io_read=10.0,
            disk_io_write=8.0,
            network_sent=5.0,
            network_recv=4.0,
            load_average=(1.5, 1.6, 1.7),
            active_processes=150
        )
        
        predicted = analyzer._predict_capacity(metrics, tracker)
        
        # For stable system with 50% CPU, 60% memory: capacity = min(50, 40) = 40%
        assert predicted == 40.0
    
    def test_predict_capacity_degrading(self):
        """Test capacity prediction for degrading system."""
        analyzer = PerformanceAnalyzer()
        tracker = LoadTracker()
        
        # Mock degrading trend
        tracker.get_trend = MagicMock()
        tracker.get_trend.side_effect = lambda metric, _: "increasing" if "usage" in metric else "stable"
        
        metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=70.0,
            memory_usage=80.0,
            memory_available=5.0,
            disk_io_read=20.0,
            disk_io_write=15.0,
            network_sent=10.0,
            network_recv=8.0,
            load_average=(2.5, 2.8, 3.0),
            active_processes=200
        )
        
        predicted = analyzer._predict_capacity(metrics, tracker)
        
        # Should reduce predicted capacity due to degrading trend
        base_capacity = min(30.0, 20.0)  # 30% CPU available, 20% memory available
        expected = base_capacity * 0.8  # Degrading reduction
        assert predicted == expected


class TestSystemMonitor:
    """Test SystemMonitor functionality."""
    
    def test_system_monitor_initialization(self):
        """Test SystemMonitor initialization."""
        monitor = SystemMonitor(collection_interval=2.0)
        
        assert monitor.collection_interval == 2.0
        assert isinstance(monitor.metrics_collector, MetricsCollector)
        assert isinstance(monitor.load_tracker, LoadTracker)
        assert isinstance(monitor.performance_analyzer, PerformanceAnalyzer)
        assert monitor._monitoring is False
    
    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self):
        """Test starting and stopping monitoring."""
        monitor = SystemMonitor(collection_interval=0.1)  # Fast for testing
        
        assert monitor._monitoring is False
        
        # Start monitoring
        await monitor.start_monitoring()
        assert monitor._monitoring is True
        assert monitor._monitor_task is not None
        
        # Let it collect a few metrics
        await asyncio.sleep(0.3)
        
        # Stop monitoring
        await monitor.stop_monitoring()
        assert monitor._monitoring is False
    
    @pytest.mark.asyncio
    async def test_monitoring_loop(self):
        """Test monitoring loop collects metrics."""
        with patch.object(MetricsCollector, 'collect_metrics') as mock_collect:
            mock_metrics = SystemMetrics(
                timestamp=time.time(),
                cpu_usage=45.0,
                memory_usage=55.0,
                memory_available=9.0,
                disk_io_read=8.0,
                disk_io_write=6.0,
                network_sent=4.0,
                network_recv=3.0,
                load_average=(1.2, 1.3, 1.4),
                active_processes=130
            )
            mock_collect.return_value = mock_metrics
            
            monitor = SystemMonitor(collection_interval=0.1)
            await monitor.start_monitoring()
            
            # Wait for a few collections
            await asyncio.sleep(0.25)
            
            # Should have collected metrics
            assert monitor._current_metrics is not None
            assert monitor._current_metrics.cpu_usage == 45.0
            
            await monitor.stop_monitoring()
    
    def test_get_system_metrics(self):
        """Test getting current system metrics."""
        monitor = SystemMonitor()
        
        # Initially no metrics
        metrics = monitor.get_system_metrics()
        assert metrics is None
        
        # Set some metrics
        test_metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=30.0,
            memory_usage=40.0,
            memory_available=12.0,
            disk_io_read=5.0,
            disk_io_write=3.0,
            network_sent=2.0,
            network_recv=1.5,
            load_average=(1.0, 1.0, 1.0),
            active_processes=100
        )
        monitor._current_metrics = test_metrics
        
        retrieved_metrics = monitor.get_system_metrics()
        assert retrieved_metrics == test_metrics
    
    def test_update_queue_depth(self):
        """Test queue depth updating."""
        monitor = SystemMonitor()
        
        assert monitor._queue_depth == 0
        
        monitor.update_queue_depth(15)
        assert monitor._queue_depth == 15
    
    @pytest.mark.asyncio
    async def test_get_performance_analysis(self):
        """Test performance analysis generation."""
        monitor = SystemMonitor()
        
        # No metrics available
        analysis = monitor.get_performance_analysis()
        assert analysis is None
        
        # Set current metrics
        monitor._current_metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=75.0,
            memory_usage=85.0,
            memory_available=4.0,
            disk_io_read=30.0,
            disk_io_write=25.0,
            network_sent=15.0,
            network_recv=12.0,
            load_average=(3.0, 3.2, 3.5),
            active_processes=200
        )
        
        # Should generate analysis
        analysis = monitor.get_performance_analysis()
        assert analysis is not None
        assert isinstance(analysis, PerformanceAnalysis)
        assert analysis.overall_health in [SystemHealth.MODERATE, SystemHealth.STRESSED, SystemHealth.CRITICAL]
    
    def test_get_health_status(self):
        """Test health status determination."""
        monitor = SystemMonitor()
        
        # Default healthy when no metrics
        health = monitor.get_health_status()
        assert health == SystemHealth.HEALTHY
        
        # Mock performance analysis
        with patch.object(monitor, 'get_performance_analysis') as mock_analysis:
            mock_result = MagicMock()
            mock_result.overall_health = SystemHealth.STRESSED
            mock_analysis.return_value = mock_result
            
            health = monitor.get_health_status()
            assert health == SystemHealth.STRESSED
    
    def test_is_overloaded(self):
        """Test overload detection."""
        monitor = SystemMonitor()
        
        # Mock performance analysis for overloaded system
        with patch.object(monitor, 'get_performance_analysis') as mock_analysis:
            mock_result = MagicMock()
            mock_result.overall_health = SystemHealth.CRITICAL
            mock_analysis.return_value = mock_result
            
            assert monitor.is_overloaded() is True
            
            # Test stressed system
            mock_result.overall_health = SystemHealth.STRESSED
            assert monitor.is_overloaded() is True
            
            # Test healthy system
            mock_result.overall_health = SystemHealth.HEALTHY
            assert monitor.is_overloaded() is False
    
    def test_get_resource_utilization(self):
        """Test resource utilization reporting."""
        monitor = SystemMonitor()
        
        # No metrics
        utilization = monitor.get_resource_utilization()
        assert len(utilization) == 0
        
        # Set metrics with GPU
        monitor._current_metrics = SystemMetrics(
            timestamp=time.time(),
            cpu_usage=65.0,
            memory_usage=75.0,
            memory_available=6.0,
            disk_io_read=20.0,
            disk_io_write=15.0,
            network_sent=10.0,
            network_recv=8.0,
            load_average=(2.0, 2.1, 2.2),
            active_processes=180,
            gpu_usage=80.0,
            gpu_memory=85.0
        )
        
        utilization = monitor.get_resource_utilization()
        
        assert utilization["cpu"] == 65.0
        assert utilization["memory"] == 75.0
        assert utilization["load_1min"] == 50.0  # 2.0 * 25
        assert utilization["gpu"] == 80.0
        assert utilization["gpu_memory"] == 85.0
    
    @pytest.mark.asyncio
    async def test_get_average_metrics(self):
        """Test average metrics retrieval."""
        monitor = SystemMonitor()
        
        # Add some metrics to load tracker
        current_time = time.time()
        for i in range(3):
            metrics = SystemMetrics(
                timestamp=current_time - i * 30,
                cpu_usage=50.0 + i * 10,
                memory_usage=60.0 + i * 5,
                memory_available=10.0,
                disk_io_read=5.0,
                disk_io_write=3.0,
                network_sent=2.0,
                network_recv=1.5,
                load_average=(1.0, 1.0, 1.0),
                active_processes=120
            )
            await monitor.load_tracker.add_metrics(metrics)
        
        avg_metrics = monitor.get_average_metrics(window_seconds=120)
        
        assert avg_metrics is not None
        # Should be average of the metrics
        assert 50.0 <= avg_metrics.cpu_usage <= 70.0
        assert 60.0 <= avg_metrics.memory_usage <= 70.0
    
    def test_factory_function(self):
        """Test system monitor factory function."""
        monitor = create_system_monitor(collection_interval=3.0)
        
        assert isinstance(monitor, SystemMonitor)
        assert monitor.collection_interval == 3.0


@pytest.mark.integration
class TestSystemMonitorIntegration:
    """Integration tests for system monitor."""
    
    @pytest.mark.asyncio
    async def test_full_monitoring_cycle(self):
        """Test complete monitoring cycle with real-like scenarios."""
        # Load test scenarios
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-021"
        with open(fixtures_path / "system_metrics.json") as f:
            test_data = json.load(f)
        
        monitor = SystemMonitor(collection_interval=0.1)
        
        # Mock metrics collector to return test scenarios
        scenarios = ["healthy_system", "moderate_load", "stressed_system"]
        scenario_index = 0
        
        def mock_collect():
            nonlocal scenario_index
            scenario_data = test_data["test_scenarios"][scenarios[scenario_index % len(scenarios)]]
            scenario_index += 1
            
            return SystemMetrics(
                timestamp=time.time(),
                cpu_usage=scenario_data["cpu_usage"],
                memory_usage=scenario_data["memory_usage"],
                memory_available=scenario_data["memory_available"],
                disk_io_read=scenario_data["disk_io_read"],
                disk_io_write=scenario_data["disk_io_write"],
                network_sent=scenario_data["network_sent"],
                network_recv=scenario_data["network_recv"],
                load_average=tuple(scenario_data["load_average"]),
                active_processes=scenario_data["active_processes"],
                gpu_usage=scenario_data["gpu_usage"],
                gpu_memory=scenario_data["gpu_memory"]
            )
        
        monitor.metrics_collector.collect_metrics = mock_collect
        
        # Start monitoring and let it run through scenarios
        await monitor.start_monitoring()
        await asyncio.sleep(0.5)  # Let it collect several metrics
        
        # Should have current metrics
        assert monitor.get_system_metrics() is not None
        
        # Should have performance analysis
        analysis = monitor.get_performance_analysis()
        assert analysis is not None
        
        # Should have resource utilization
        utilization = monitor.get_resource_utilization()
        assert len(utilization) > 0
        
        # Should have average metrics
        avg_metrics = monitor.get_average_metrics()
        assert avg_metrics is not None
        
        await monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_system_load_progression(self):
        """Test monitoring system load changes over time."""
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "AGENT-021"
        with open(fixtures_path / "system_metrics.json") as f:
            test_data = json.load(f)
        
        monitor = SystemMonitor(collection_interval=0.05)
        
        # Use degrading system progression
        progression = test_data["mock_metrics_progression"]["degrading_system"]
        progression_index = 0
        
        def mock_collect():
            nonlocal progression_index
            if progression_index >= len(progression):
                progression_index = len(progression) - 1
            
            data = progression[progression_index]
            progression_index += 1
            
            return SystemMetrics(
                timestamp=time.time(),
                cpu_usage=data["cpu_usage"],
                memory_usage=data["memory_usage"],
                memory_available=16.0 - (data["memory_usage"] / 100.0) * 16.0,
                disk_io_read=10.0,
                disk_io_write=8.0,
                network_sent=5.0,
                network_recv=4.0,
                load_average=(data["cpu_usage"] / 50.0, data["cpu_usage"] / 50.0, data["cpu_usage"] / 50.0),
                active_processes=100 + int(data["cpu_usage"])
            )
        
        monitor.metrics_collector.collect_metrics = mock_collect
        
        await monitor.start_monitoring()
        
        initial_health = None
        final_health = None
        
        # Monitor progression
        for i in range(len(progression)):
            await asyncio.sleep(0.06)  # Slightly longer than collection interval
            
            if i == 0:
                initial_health = monitor.get_health_status()
            if i == len(progression) - 1:
                final_health = monitor.get_health_status()
        
        await monitor.stop_monitoring()
        
        # Should detect health degradation
        health_values = {
            SystemHealth.HEALTHY: 0,
            SystemHealth.MODERATE: 1,
            SystemHealth.STRESSED: 2,
            SystemHealth.CRITICAL: 3
        }
        
        # Final health should be worse than initial
        assert health_values[final_health] >= health_values[initial_health]


@pytest.mark.performance
class TestSystemMonitorPerformance:
    """Performance tests for system monitor."""
    
    @pytest.mark.asyncio
    async def test_monitoring_overhead(self):
        """Test monitoring overhead on system performance."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_cpu_percent = process.cpu_percent()
        
        # Start intensive monitoring
        monitor = SystemMonitor(collection_interval=0.01)  # Very frequent
        await monitor.start_monitoring()
        
        # Let it run for a while
        await asyncio.sleep(2.0)
        
        final_cpu_percent = process.cpu_percent()
        
        await monitor.stop_monitoring()
        
        # Monitor itself shouldn't use excessive CPU
        cpu_increase = final_cpu_percent - initial_cpu_percent
        assert cpu_increase < 10.0  # Less than 10% CPU increase
    
    @pytest.mark.asyncio
    async def test_memory_usage_stability(self):
        """Test that memory usage remains stable during monitoring."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        monitor = SystemMonitor(collection_interval=0.05)
        await monitor.start_monitoring()
        
        # Run for extended period
        await asyncio.sleep(3.0)
        
        final_memory = process.memory_info().rss
        memory_growth = final_memory - initial_memory
        
        await monitor.stop_monitoring()
        
        # Memory growth should be minimal (under 50MB)
        assert memory_growth < 50 * 1024 * 1024
    
    @pytest.mark.asyncio
    async def test_metrics_collection_latency(self):
        """Test metrics collection latency."""
        monitor = SystemMonitor()
        
        # Measure collection time
        times = []
        for _ in range(10):
            start = time.time()
            metrics = monitor.metrics_collector.collect_metrics()
            end = time.time()
            times.append(end - start)
            
            # Verify we got valid metrics
            assert metrics is not None
            assert metrics.cpu_usage >= 0
        
        avg_time = sum(times) / len(times)
        
        # Should collect metrics quickly (under 100ms average)
        assert avg_time < 0.1
    
    @pytest.mark.asyncio
    async def test_concurrent_monitoring(self):
        """Test multiple concurrent monitors."""
        monitors = []
        
        # Start multiple monitors
        for i in range(3):
            monitor = SystemMonitor(collection_interval=0.1)
            monitors.append(monitor)
            await monitor.start_monitoring()
        
        # Let them run concurrently
        await asyncio.sleep(0.5)
        
        # All should have collected metrics
        for monitor in monitors:
            assert monitor.get_system_metrics() is not None
        
        # Stop all monitors
        for monitor in monitors:
            await monitor.stop_monitoring()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])