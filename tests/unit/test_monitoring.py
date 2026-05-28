"""Unit tests for production monitoring system"""

import asyncio
import pytest
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from brain_researcher.services.agent.monitoring import (
    HealthMonitor,
    HealthStatus,
    ServiceType,
    AlertManager,
    Alert,
    AlertSeverity,
    MetricsCollector,
    MetricType,
    CircuitBreaker,
    CircuitOpenError
)
from brain_researcher.services.agent.monitoring_integration import (
    MonitoringIntegration,
    get_monitoring_integration
)
from brain_researcher.services.agent.monitoring.dashboard import MonitoringDashboard


class TestHealthMonitor:
    """Test health monitoring functionality."""
    
    @pytest.mark.asyncio
    async def test_health_check_registration(self):
        """Test registering health checks."""
        monitor = HealthMonitor()
        
        # Register a service
        monitor.register_service("test_service", ServiceType.CORE)
        
        assert "test_service" in monitor.services
        assert monitor.services["test_service"].service_type == ServiceType.CORE
    
    @pytest.mark.asyncio
    async def test_health_check_execution(self):
        """Test executing health checks."""
        monitor = HealthMonitor()
        
        # Register a custom check
        async def custom_check():
            from brain_researcher.services.agent.monitoring import HealthCheck
            return HealthCheck(
                name="custom",
                status=HealthStatus.HEALTHY,
                latency_ms=10,
                message="All good"
            )
        
        monitor.register_check("custom", custom_check)
        
        # Run checks
        checks = await monitor._run_health_checks()
        
        # Find our custom check
        custom_result = next((c for c in checks if c.name == "custom"), None)
        assert custom_result is not None
        assert custom_result.status == HealthStatus.HEALTHY
    
    @pytest.mark.asyncio
    async def test_system_metrics_collection(self):
        """Test system metrics collection."""
        monitor = HealthMonitor()
        
        metrics = await monitor._collect_system_metrics()
        
        assert metrics.cpu_percent >= 0
        assert metrics.memory_percent >= 0
        assert metrics.disk_percent >= 0
        assert metrics.network_connections >= 0
    
    def test_health_status_summary(self):
        """Test health status summary generation."""
        monitor = HealthMonitor()
        
        # Register services
        monitor.register_service("service1", ServiceType.CORE)
        monitor.register_service("service2", ServiceType.DATABASE)
        
        # Get status
        status = monitor.get_status()
        
        assert "status" in status
        assert "uptime_seconds" in status
        assert "services" in status
        assert "metrics" in status


class TestAlertManager:
    """Test alerting functionality."""
    
    @pytest.mark.asyncio
    async def test_alert_creation(self):
        """Test creating and sending alerts."""
        manager = AlertManager()
        
        alert = Alert(
            alert_id="test_alert",
            title="Test Alert",
            message="This is a test",
            severity=AlertSeverity.WARNING,
            source="test"
        )
        
        await manager.send_alert(alert)
        
        assert len(manager.alert_history) == 1
        assert manager.alert_history[0].alert_id == "test_alert"
    
    @pytest.mark.asyncio
    async def test_alert_suppression(self):
        """Test alert suppression logic."""
        manager = AlertManager(suppression_window=1, max_alerts_per_window=2)
        
        # Send same alert multiple times
        for i in range(5):
            alert = Alert(
                alert_id=f"test_{i}",
                title="Repeated Alert",
                message="Same issue",
                severity=AlertSeverity.WARNING,
                source="test"
            )
            await manager.send_alert(alert)
        
        # Only first 2 should be in history due to suppression
        assert len(manager.alert_history) == 2
    
    def test_alert_acknowledgment(self):
        """Test alert acknowledgment."""
        manager = AlertManager()
        
        alert = Alert(
            alert_id="test",
            title="Test",
            message="Test",
            severity=AlertSeverity.ERROR,
            source="test"
        )
        
        from brain_researcher.services.agent.monitoring.alerting import AlertState
        manager.active_alerts[alert.fingerprint] = AlertState(alert=alert)
        
        # Acknowledge
        manager.acknowledge_alert(alert.fingerprint)
        
        assert manager.active_alerts[alert.fingerprint].acknowledged
    
    def test_alert_severity_routing(self):
        """Test alert routing based on severity."""
        manager = AlertManager()
        
        from brain_researcher.services.agent.monitoring.alerting import AlertChannel
        
        # Test different severities
        info_channels = manager._get_channels_for_severity(AlertSeverity.INFO)
        assert AlertChannel.LOG in info_channels
        
        critical_channels = manager._get_channels_for_severity(AlertSeverity.CRITICAL)
        assert AlertChannel.LOG in critical_channels
        assert AlertChannel.PAGERDUTY in critical_channels


class TestMetricsCollector:
    """Test metrics collection functionality."""
    
    def test_metric_registration(self):
        """Test registering metrics."""
        collector = MetricsCollector()
        
        collector.register_metric(
            "test_metric",
            MetricType.COUNTER,
            "Test metric",
            "count"
        )
        
        assert "test_metric" in collector.metrics
        assert collector.metrics["test_metric"].metric_type == MetricType.COUNTER
    
    def test_counter_increment(self):
        """Test incrementing counter metrics."""
        collector = MetricsCollector()
        
        collector.register_metric(
            "test_counter",
            MetricType.COUNTER,
            "Test counter",
            "count"
        )
        
        # Increment
        collector.increment("test_counter", 1)
        collector.increment("test_counter", 2)
        
        latest = collector.metrics["test_counter"].get_latest()
        assert latest == 3

    def test_tool_execution_job_kind_labels(self):
        """Tool execution metrics include normalized job_kind labels."""
        collector = MetricsCollector()
        collector.record_tool_execution(
            tool_name="glm_analysis",
            duration_ms=120.0,
            success=True,
            job_kind="glm",
        )
        metric = collector.metrics["tool_executions_total"]
        point = metric.data_points[-1]
        assert point.labels["job_kind"] == "glm"
    
    def test_gauge_recording(self):
        """Test recording gauge metrics."""
        collector = MetricsCollector()
        
        collector.register_metric(
            "test_gauge",
            MetricType.GAUGE,
            "Test gauge",
            "value"
        )
        
        # Record values
        collector.record("test_gauge", 10.5)
        collector.record("test_gauge", 20.5)
        
        latest = collector.metrics["test_gauge"].get_latest()
        assert latest == 20.5
    
    def test_tool_metrics_recording(self):
        """Test recording tool execution metrics."""
        collector = MetricsCollector()

        # Record tool execution
        collector.record_tool_execution(
            tool_name="test_tool",
            duration_ms=100,
            success=True
        )
        
        # Check tool metrics were created
        assert "test_tool" in collector.tool_metrics
        
        tool_metrics = collector.get_tool_metrics("test_tool")
        assert tool_metrics["avg_duration"] == 100

    def test_cli_command_metrics(self):
        """CLI command metrics update counters and histograms."""
        collector = MetricsCollector()
        collector.record_cli_command(
            command="agent_act",
            duration_ms=250.0,
            status="success",
            job_kind="glm",
        )
        counter = collector.metrics["cli_commands_total"]
        histogram = collector.metrics["cli_command_duration_seconds"]
        assert counter.data_points[-1].labels["command"] == "agent_act"
        assert histogram.data_points[-1].value == pytest.approx(0.25)
    
    @pytest.mark.asyncio
    async def test_metrics_query(self):
        """Test querying historical metrics."""
        collector = MetricsCollector()
        
        # Add some data points
        collector.register_metric("test", MetricType.GAUGE, "Test", "unit")
        for i in range(10):
            collector.record("test", float(i))
            await asyncio.sleep(0.01)
        
        # Query metrics
        results = await collector.query(
            metric_names=["test"],
            start_time="-1m",
            resolution="1s"
        )
        
        assert "test" in results
        assert len(results["test"]) > 0


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def test_circuit_breaker_opens_on_failures(self):
        """Test circuit breaker opens after threshold failures."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=1)
        
        def failing_func():
            raise Exception("Test failure")
        
        # Fail multiple times
        for _ in range(3):
            with pytest.raises(Exception):
                breaker.call(failing_func)
        
        assert breaker.state == "open"
        
        # Next call should raise CircuitOpenError
        with pytest.raises(CircuitOpenError):
            breaker.call(failing_func)
    
    def test_circuit_breaker_closes_on_success(self):
        """Test circuit breaker closes on successful calls."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        def success_func():
            return "success"
        
        # Successful call
        result = breaker.call(success_func)
        assert result == "success"
        assert breaker.state == "closed"
    
    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after timeout."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            timeout=1,
            recovery_timeout=0.1
        )
        
        def failing_func():
            raise Exception("Fail")
        
        # Fail to open circuit
        with pytest.raises(Exception):
            breaker.call(failing_func)
        
        assert breaker.state == "open"
        
        # Wait for recovery timeout
        time.sleep(0.2)
        
        # Should attempt reset (half-open)
        def success_func():
            return "recovered"
        
        result = breaker.call(success_func)
        assert result == "recovered"
        assert breaker.state == "closed"


class TestMonitoringIntegration:
    """Test monitoring integration with services."""
    
    @pytest.mark.asyncio
    async def test_tool_execution_monitoring(self):
        """Test monitoring decorator for tool execution."""
        integration = MonitoringIntegration()
        
        @integration.monitor_tool_execution("test_tool")
        async def mock_tool():
            await asyncio.sleep(0.01)
            return "result"
        
        # Execute tool
        result = await mock_tool()
        assert result == "result"
        
        # Check metrics were recorded
        tool_metrics = integration.metrics_collector.get_tool_metrics("test_tool")
        assert tool_metrics is not None
    
    @pytest.mark.asyncio
    async def test_cache_operation_monitoring(self):
        """Test monitoring decorator for cache operations."""
        integration = MonitoringIntegration()
        
        @integration.monitor_cache_operation("get")
        async def mock_cache_get():
            return "cached_value"
        
        # Execute cache operation
        result = await mock_cache_get()
        assert result == "cached_value"
        
        # Check cache hit was recorded
        metrics = integration.metrics_collector.get_current_metrics()
        assert "cache_hits_total" in metrics
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Test circuit breaker integration with services."""
        integration = MonitoringIntegration()
        
        # Get circuit breaker for tool executor
        breaker = integration.circuit_breakers["tool_executor"]
        
        # Simulate failures
        for _ in range(5):
            breaker._on_failure()
        
        assert breaker.state == "open"
        
        @integration.monitor_tool_execution("critical_tool")
        async def failing_tool():
            return "should not execute"
        
        # Should raise due to open circuit
        with pytest.raises(Exception, match="Circuit breaker open"):
            await failing_tool()
    
    def test_singleton_pattern(self):
        """Test monitoring integration singleton."""
        integration1 = get_monitoring_integration()
        integration2 = get_monitoring_integration()

        assert integration1 is integration2


class TestMonitoringDashboardApi:
    """Test HTTP ingestion endpoints."""

    def test_cli_metric_ingest_endpoint(self):
        dashboard = MonitoringDashboard()
        client = TestClient(dashboard.app)
        response = client.post(
            "/metrics/cli",
            json={
                "command": "agent_act",
                "duration_ms": 100.0,
                "status": "success",
                "job_kind": "glm",
            },
        )
        assert response.status_code == 200
        counter = dashboard.metrics_collector.metrics["cli_commands_total"]
        assert counter.data_points[-1].labels["command"] == "agent_act"
