"""
Integration tests for /metrics endpoint (P5.11).

Tests the actual HTTP endpoint in the FastAPI application including:
- Endpoint accessibility and response format
- Metric value correctness after operations
- Disabled mode behavior
"""

import importlib
import os
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient


def _clear_prometheus_registry():
    from prometheus_client import REGISTRY

    collectors = list(getattr(REGISTRY, "_collector_to_names", {}).keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass
        except AttributeError:
            # Some collectors do not expose required interface
            continue


def _reload_orchestrator_app(metrics_enabled: bool):
    """Reload orchestrator modules with the desired metrics flag."""
    flag = "true" if metrics_enabled else "false"
    with patch.dict(os.environ, {"BR_METRICS_ENABLED": flag}, clear=False):
        from brain_researcher.services.orchestrator import env as env_module
        from brain_researcher.services.orchestrator import metrics as metrics_module
        from brain_researcher.services.telemetry import metrics_kind_resolver
        import brain_researcher.services.orchestrator.main_enhanced as main_module

        env_module.get_metrics_enabled.cache_clear()
        metrics_kind_resolver.reset_job_kind_cache()
        _clear_prometheus_registry()
        importlib.reload(env_module)
        importlib.reload(metrics_module)
        app_module = importlib.reload(main_module)
        return app_module.app


def _fresh_metrics():
    """Return a freshly initialized MetricsCollector with a clean registry."""
    _clear_prometheus_registry()
    from brain_researcher.services.orchestrator.metrics import init_metrics

    return init_metrics(enabled=True)


@pytest.fixture(autouse=True)
def reset_prometheus_registry():
    """Ensure Prometheus registry is clean between tests."""
    _clear_prometheus_registry()
    yield
    _clear_prometheus_registry()


@pytest.fixture
def metrics_enabled_app():
    """Create test app with metrics enabled."""
    yield _reload_orchestrator_app(metrics_enabled=True)


@pytest.fixture
def metrics_disabled_app():
    """Create test app with metrics disabled."""
    yield _reload_orchestrator_app(metrics_enabled=False)


class TestMetricsEndpoint:
    """Test /metrics HTTP endpoint."""

    def test_metrics_endpoint_exists(self, metrics_enabled_app):
        """Test /metrics endpoint is registered."""
        client = TestClient(metrics_enabled_app)
        response = client.get("/metrics")

        # Should return 200 (or possibly 500 if prometheus-client not installed)
        assert response.status_code in (200, 500)

    def test_metrics_endpoint_prometheus_format(self, metrics_enabled_app):
        """Test /metrics returns Prometheus text format."""
        with patch('prometheus_client.Counter'), \
             patch('prometheus_client.Histogram'), \
             patch('prometheus_client.Gauge'), \
             patch('prometheus_client.generate_latest') as mock_generate:

            # Mock Prometheus output
            mock_generate.return_value = b"""# HELP brain_researcher_orchestrator_jobs_enqueued_total Total number of jobs submitted
# TYPE brain_researcher_orchestrator_jobs_enqueued_total counter
brain_researcher_orchestrator_jobs_enqueued_total{kind="tool"} 5.0
# HELP brain_researcher_orchestrator_jobs_completed_total Total number of jobs completed
# TYPE brain_researcher_orchestrator_jobs_completed_total counter
brain_researcher_orchestrator_jobs_completed_total{kind="tool",state="succeeded"} 3.0
"""

            client = TestClient(metrics_enabled_app)
            response = client.get("/metrics")

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/plain; charset=utf-8"
            assert b"brain_researcher_orchestrator" in response.content
            assert b"jobs_enqueued_total" in response.content

    def test_metrics_endpoint_disabled(self, metrics_disabled_app):
        """Test /metrics returns 404 when disabled."""
        client = TestClient(metrics_disabled_app)
        response = client.get("/metrics")

        assert response.status_code == 404
        detail = response.json().get("detail", "").lower()
        assert detail in {"not found", "metrics disabled (set br_metrics_enabled=true to enable)"}


class TestMetricsIntegration:
    """Test metrics are updated correctly during operations."""

    @pytest.mark.asyncio
    async def test_job_enqueue_metric(self, metrics_enabled_app):
        """Test job enqueue metric is recorded."""
        with patch('prometheus_client.Counter') as mock_counter_cls:
            mock_counter = Mock()
            mock_counter_cls.return_value = mock_counter

            metrics = _fresh_metrics()
            metrics.prom_jobs_enqueued = mock_counter

            # Enqueue a job
            metrics.record_job_enqueued(kind="tool")

            # Verify metric was called
            mock_counter.labels.assert_called_with(kind="tool")
            mock_counter.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_job_completion_metric(self, metrics_enabled_app):
        """Test job completion metric is recorded."""
        with patch('prometheus_client.Counter') as mock_counter_cls, \
             patch('prometheus_client.Histogram') as mock_histogram_cls:

            mock_counter = Mock()
            mock_histogram = Mock()
            mock_counter_cls.return_value = mock_counter
            mock_histogram_cls.return_value = mock_histogram

            metrics = _fresh_metrics()
            metrics.prom_jobs_completed = mock_counter
            metrics.prom_jobs_duration = mock_histogram

            # Complete a job
            metrics.record_job_completed(kind="tool", state="succeeded", duration=30.5)

            # Verify counter incremented
            mock_counter.labels.assert_called_with(kind="tool", state="succeeded")
            mock_counter.labels.return_value.inc.assert_called_once()

            # Verify histogram observed
            mock_histogram.labels.assert_called_with(kind="tool", state="succeeded")
            mock_histogram.labels.return_value.observe.assert_called_with(30.5)

    @pytest.mark.asyncio
    async def test_cache_hit_metric(self, metrics_enabled_app):
        """Test cache hit metric is recorded."""
        with patch('prometheus_client.Counter') as mock_counter_cls:
            mock_counter = Mock()
            mock_counter_cls.return_value = mock_counter

            metrics = _fresh_metrics()
            metrics.prom_cache_ops = mock_counter

            # Record cache hit
            metrics.record_cache_operation(operation="lookup", result="hit")

            # Verify metric was called
            mock_counter.labels.assert_called_with(operation="lookup", result="hit")
            mock_counter.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_metric(self, metrics_enabled_app):
        """Test cache miss metric is recorded."""
        with patch('prometheus_client.Counter') as mock_counter_cls:
            mock_counter = Mock()
            mock_counter_cls.return_value = mock_counter

            metrics = _fresh_metrics()
            metrics.prom_cache_ops = mock_counter

            # Record cache miss
            metrics.record_cache_operation(operation="lookup", result="miss")

            # Verify metric was called
            mock_counter.labels.assert_called_with(operation="lookup", result="miss")
            mock_counter.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_queue_depth_metric(self, metrics_enabled_app):
        """Test queue depth metric is updated."""
        with patch('prometheus_client.Gauge') as mock_gauge_cls:
            mock_gauge = Mock()
            mock_gauge_cls.return_value = mock_gauge

            metrics = _fresh_metrics()
            metrics.prom_queue_depth = mock_gauge

            # Update queue depth
            state_counts = {
                "pending": 5,
                "running": 2,
                "succeeded": 10
            }
            metrics.update_queue_depth(state_counts)

            # Verify gauge was set for each state
            assert mock_gauge.labels.call_count == 3
            mock_gauge.labels.assert_any_call(state="pending")
            mock_gauge.labels.assert_any_call(state="running")
            mock_gauge.labels.assert_any_call(state="succeeded")


class TestMetricsHistogramBuckets:
    """Test histogram bucket configuration."""

    def test_duration_histogram_buckets(self):
        """Test job duration histogram has appropriate buckets."""
        with patch('prometheus_client.Histogram') as mock_histogram:
            from brain_researcher.services.orchestrator.metrics import MetricsCollector

            collector = MetricsCollector(enabled=True)

            # Find the jobs_duration histogram call
            histogram_calls = [call for call in mock_histogram.call_args_list
                             if 'jobs_duration_seconds' in str(call)]

            assert len(histogram_calls) == 1

            # Check buckets argument
            call_args, call_kwargs = histogram_calls[0]
            buckets = call_kwargs.get('buckets', [])

            # Should have buckets from 1s to 1hr
            assert 1 in buckets  # 1 second
            assert 60 in buckets  # 1 minute
            assert 300 in buckets  # 5 minutes
            assert 3600 in buckets  # 1 hour


class TestMetricsLabels:
    """Test metric label consistency."""

    def test_job_metrics_kind_label(self):
        """Test job metrics use 'kind' label."""
        with patch('prometheus_client.Counter') as mock_counter:
            from brain_researcher.services.orchestrator.metrics import MetricsCollector

            collector = MetricsCollector(enabled=True)

            # Find jobs_enqueued counter call
            enqueued_calls = [call for call in mock_counter.call_args_list
                            if 'jobs_enqueued_total' in str(call)]

            assert len(enqueued_calls) == 1

            # Check labels argument
            call_args, call_kwargs = enqueued_calls[0]
            # Labels is the 3rd positional argument
            assert 'kind' in call_args[2] or (len(call_args) > 2 and 'kind' in call_args[2])

    def test_cache_metrics_labels(self):
        """Test cache metrics use 'operation' and 'result' labels."""
        with patch('prometheus_client.Counter') as mock_counter:
            from brain_researcher.services.orchestrator.metrics import MetricsCollector

            collector = MetricsCollector(enabled=True)

            # Find cache_operations counter call
            cache_calls = [call for call in mock_counter.call_args_list
                          if 'cache_operations_total' in str(call)]

            assert len(cache_calls) == 1

            # Check labels argument
            call_args, call_kwargs = cache_calls[0]
            labels = call_args[2] if len(call_args) > 2 else []

            assert 'operation' in labels
            assert 'result' in labels


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
