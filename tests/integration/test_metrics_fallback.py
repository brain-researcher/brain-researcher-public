from brain_researcher.services.agent import web_service
from brain_researcher.services.agent.monitoring.metrics_collector import MetricType


class EmptyMetrics:
    def export_prometheus(self) -> str:
        return ""


class EmptyMonitoring:
    def __init__(self):
        self._metrics = EmptyMetrics()


def test_metrics_fallback_to_local_collector(monkeypatch):
    monkeypatch.setattr(web_service, "_AGENT_METRICS_ENABLED", True)
    monkeypatch.setattr(
        web_service, "_get_monitoring_integration", lambda: EmptyMonitoring()
    )

    metric_name = "test_metrics_fallback"
    web_service._metrics.register_metric(
        metric_name,
        MetricType.GAUGE,
        "Fallback gauge",
        "units",
    )
    web_service._metrics.record(metric_name, 7)

    client = web_service.app.test_client()
    response = client.get("/metrics")
    body = response.get_data(as_text=True)

    try:
        assert response.status_code == 200
        assert f"{metric_name} 7" in body
    finally:
        web_service._metrics.metrics.pop(metric_name, None)
