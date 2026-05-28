from brain_researcher.services.agent.monitoring.metrics_collector import (
    MetricType,
    MetricsCollector,
)


def test_export_prometheus_labeled_metrics_without_unlabeled_samples():
    collector = MetricsCollector()
    metric_name = "test_labeled_metric"
    collector.register_metric(
        metric_name,
        MetricType.GAUGE,
        "Test labeled metric",
        labels=["label"],
    )
    collector.record(metric_name, 1, labels={"label": "a"})
    collector.record(metric_name, 2, labels={"label": "b"})

    payload = collector.export_prometheus()
    lines = [
        line for line in payload.splitlines() if line.startswith(metric_name)
    ]

    assert lines, "Expected labeled metric samples in Prometheus export"
    assert all("{" in line and "}" in line for line in lines)
    assert any('label="a"' in line for line in lines)
    assert any('label="b"' in line for line in lines)
