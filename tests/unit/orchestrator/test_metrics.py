"""
Unit tests for metrics module (P5.11).

Tests MetricsCollector class including:
- Initialization with enabled/disabled state
- Metric recording methods
- Router generation with /metrics endpoint
- No-op behavior when disabled
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from brain_researcher.services.orchestrator.metrics import MetricsCollector, init_metrics, get_metrics_collector


@pytest.fixture(autouse=True)
def clear_prometheus_registry():
    """Clear Prometheus registry between tests to avoid duplicate metric errors."""
    try:
        from prometheus_client import REGISTRY
        # Clear all collectors
        collectors = list(REGISTRY._collector_to_names.keys())
        for collector in collectors:
            try:
                REGISTRY.unregister(collector)
            except Exception:
                pass
    except ImportError:
        pass
    yield


class TestMetricsCollector:
    """Test MetricsCollector class."""

    def test_init_enabled(self):
        """Test initialization with metrics enabled."""
        with patch('prometheus_client.Counter') as mock_counter, \
             patch('prometheus_client.Histogram') as mock_histogram, \
             patch('prometheus_client.Gauge') as mock_gauge:

            collector = MetricsCollector(enabled=True)

            assert collector.enabled is True
            # Should have initialized all 5 metrics
            assert mock_counter.call_count == 3  # jobs_enqueued, jobs_completed, cache_ops
            assert mock_histogram.call_count == 1  # jobs_duration
            assert mock_gauge.call_count == 1  # queue_depth

    def test_init_disabled(self):
        """Test initialization with metrics disabled."""
        collector = MetricsCollector(enabled=False)

        assert collector.enabled is False
        assert collector.prom_jobs_enqueued is None
        assert collector.prom_jobs_completed is None
        assert collector.prom_jobs_duration is None
        assert collector.prom_cache_ops is None
        assert collector.prom_queue_depth is None

    def test_init_missing_prometheus_client(self):
        """Test graceful degradation when prometheus-client not installed."""
        with patch('prometheus_client.Counter', side_effect=ImportError("No module named 'prometheus_client'")):
            collector = MetricsCollector(enabled=True)

            # Should disable metrics on ImportError
            assert collector.enabled is False

    def test_record_job_enqueued_enabled(self):
        """Test recording job enqueue when enabled."""
        with patch('prometheus_client.Counter') as mock_counter_cls:
            mock_counter = Mock()
            mock_counter_cls.return_value = mock_counter

            collector = MetricsCollector(enabled=True)
            collector.prom_jobs_enqueued = mock_counter

            # Record enqueue
            collector.record_job_enqueued(kind="tool")

            mock_counter.labels.assert_called_once_with(kind="tool")
            mock_counter.labels.return_value.inc.assert_called_once()

    def test_record_job_enqueued_disabled(self):
        """Test recording job enqueue when disabled (no-op)."""
        collector = MetricsCollector(enabled=False)

        # Should not raise error
        collector.record_job_enqueued(kind="tool")

    def test_record_job_completed_enabled(self):
        """Test recording job completion when enabled."""
        with patch('prometheus_client.Counter') as mock_counter_cls, \
             patch('prometheus_client.Histogram') as mock_histogram_cls:

            mock_counter = Mock()
            mock_histogram = Mock()
            mock_counter_cls.return_value = mock_counter
            mock_histogram_cls.return_value = mock_histogram

            collector = MetricsCollector(enabled=True)
            collector.prom_jobs_completed = mock_counter
            collector.prom_jobs_duration = mock_histogram

            # Record completion
            collector.record_job_completed(kind="tool", state="succeeded", duration=45.5)

            # Should increment counter
            mock_counter.labels.assert_called_once_with(kind="tool", state="succeeded")
            mock_counter.labels.return_value.inc.assert_called_once()

            # Should observe duration
            mock_histogram.labels.assert_called_once_with(kind="tool", state="succeeded")
            mock_histogram.labels.return_value.observe.assert_called_once_with(45.5)

    def test_record_job_completed_disabled(self):
        """Test recording job completion when disabled (no-op)."""
        collector = MetricsCollector(enabled=False)

        # Should not raise error
        collector.record_job_completed(kind="tool", state="succeeded", duration=45.5)

    def test_record_cache_operation_enabled(self):
        """Test recording cache operation when enabled."""
        with patch('prometheus_client.Counter') as mock_counter_cls:
            mock_counter = Mock()
            mock_counter_cls.return_value = mock_counter

            collector = MetricsCollector(enabled=True)
            collector.prom_cache_ops = mock_counter

            # Record hit
            collector.record_cache_operation(operation="lookup", result="hit")

            mock_counter.labels.assert_called_with(operation="lookup", result="hit")
            mock_counter.labels.return_value.inc.assert_called()

    def test_record_cache_operation_disabled(self):
        """Test recording cache operation when disabled (no-op)."""
        collector = MetricsCollector(enabled=False)

        # Should not raise error
        collector.record_cache_operation(operation="lookup", result="hit")

    def test_update_queue_depth_enabled(self):
        """Test updating queue depth when enabled."""
        with patch('prometheus_client.Gauge') as mock_gauge_cls:
            mock_gauge = Mock()
            mock_gauge_cls.return_value = mock_gauge

            collector = MetricsCollector(enabled=True)
            collector.prom_queue_depth = mock_gauge

            # Update queue depth
            state_counts = {
                "pending": 10,
                "running": 5,
                "succeeded": 100,
                "failed": 3
            }
            collector.update_queue_depth(state_counts)

            # Should set gauge for each state
            assert mock_gauge.labels.call_count == 4
            mock_gauge.labels.assert_any_call(state="pending")
            mock_gauge.labels.assert_any_call(state="running")
            mock_gauge.labels.assert_any_call(state="succeeded")
            mock_gauge.labels.assert_any_call(state="failed")

    def test_update_queue_depth_disabled(self):
        """Test updating queue depth when disabled (no-op)."""
        collector = MetricsCollector(enabled=False)

        # Should not raise error
        collector.update_queue_depth({"pending": 10, "running": 5})

    def test_get_router_enabled(self):
        """Test router generation when enabled."""
        with patch('prometheus_client.Counter'), \
             patch('prometheus_client.Histogram'), \
             patch('prometheus_client.Gauge'):

            collector = MetricsCollector(enabled=True)
            router = collector.get_router()

            # Should return APIRouter
            assert router is not None
            # Should have /metrics endpoint
            routes = [route.path for route in router.routes]
            assert "/metrics" in routes

    def test_get_router_disabled(self):
        """Test router generation when disabled."""
        collector = MetricsCollector(enabled=False)
        router = collector.get_router()

        # Should still return router (endpoint will return 404)
        assert router is not None


class TestMetricsGlobalFunctions:
    """Test global metrics functions."""

    def test_init_metrics(self):
        """Test global metrics initialization."""
        with patch('brain_researcher.services.orchestrator.metrics.MetricsCollector') as mock_collector_cls:
            mock_collector = Mock()
            mock_collector_cls.return_value = mock_collector

            result = init_metrics(enabled=True)

            mock_collector_cls.assert_called_once_with(enabled=True)
            assert result == mock_collector

    def test_get_metrics_collector_success(self):
        """Test getting metrics collector after initialization."""
        # Initialize first
        with patch('prometheus_client.Counter'), \
             patch('prometheus_client.Histogram'), \
             patch('prometheus_client.Gauge'):

            init_metrics(enabled=True)
            collector = get_metrics_collector()

            assert collector is not None
            assert isinstance(collector, MetricsCollector)

    def test_get_metrics_collector_not_initialized(self):
        """Test getting metrics collector before initialization raises error."""
        # Reset global state
        import brain_researcher.services.orchestrator.metrics as metrics_module
        metrics_module._metrics_collector = None

        with pytest.raises(RuntimeError, match="MetricsCollector not initialized"):
            get_metrics_collector()


class TestMetricsEndpoint:
    """Test /metrics endpoint behavior."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint_enabled(self):
        """Test /metrics endpoint returns Prometheus format when enabled."""
        with patch('prometheus_client.Counter'), \
             patch('prometheus_client.Histogram'), \
             patch('prometheus_client.Gauge'), \
             patch('prometheus_client.generate_latest') as mock_generate:

            mock_generate.return_value = b"# HELP metric_name\n# TYPE metric_name counter\nmetric_name 42\n"

            collector = MetricsCollector(enabled=True)
            router = collector.get_router()

            # Find the /metrics endpoint
            metrics_endpoint = None
            for route in router.routes:
                if route.path == "/metrics":
                    metrics_endpoint = route.endpoint
                    break

            assert metrics_endpoint is not None

            # Call endpoint
            response = await metrics_endpoint()

            # Should return Prometheus text format
            assert b"metric_name" in response
            mock_generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_endpoint_disabled(self):
        """Test /metrics endpoint returns 404 when disabled."""
        from fastapi import HTTPException

        collector = MetricsCollector(enabled=False)
        router = collector.get_router()

        # Find the /metrics endpoint
        metrics_endpoint = None
        for route in router.routes:
            if route.path == "/metrics":
                metrics_endpoint = route.endpoint
                break

        assert metrics_endpoint is not None

        # Call endpoint should raise 404
        with pytest.raises(HTTPException) as exc_info:
            await metrics_endpoint()

        assert exc_info.value.status_code == 404
        assert "disabled" in exc_info.value.detail.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
