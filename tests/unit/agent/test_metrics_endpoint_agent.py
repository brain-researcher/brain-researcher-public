import os

import pytest


@pytest.fixture(autouse=True)
def enable_metrics(monkeypatch):
    monkeypatch.setenv("BR_METRICS_ENABLED", "true")
    yield


def test_agent_metrics_includes_knowledge_cache(monkeypatch):
    """Ensure /metrics exposes knowledge cache Prometheus metrics."""

    # Lazy import after env is set
    from brain_researcher.services.agent.web_service import app, _get_agent_monitoring_for_metrics

    monitoring = _get_agent_monitoring_for_metrics()
    if monitoring is None:
        pytest.skip("Monitoring integration unavailable")

    # Seed cache metrics
    monitoring.metrics_collector.record_knowledge_cache_metrics(
        l1_hits=1,
        shared_hits=2,
        account_id="user123",
    )

    client = app.test_client()
    resp = client.get("/metrics")

    assert resp.status_code == 200
    payload = resp.data.decode()
    # At least cache metrics (hits) should be exposed
    assert "cache_hits_total" in payload


def test_agent_metrics_json_knowledge_snapshot(monkeypatch):
    """Ensure /metrics/knowledge JSON endpoint returns cache snapshot."""

    from brain_researcher.services.agent.web_service import app, _get_agent_monitoring_for_metrics

    monitoring = _get_agent_monitoring_for_metrics()
    if monitoring is None:
        pytest.skip("Monitoring integration unavailable")

    # Seed cache metrics to L1 only
    monitoring.metrics_collector.record_knowledge_cache_metrics(
        l1_hits=3,
        l1_misses=1,
        account_id="user999",
    )

    client = app.test_client()
    resp = client.get("/metrics/knowledge")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("status") == "ok"
    cache_metrics = data.get("cache_metrics", {})
    # Verify cache counters made it through
    assert cache_metrics.get("cache_hits_total") is not None
