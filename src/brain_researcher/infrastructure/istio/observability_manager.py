"""Minimal Istio observability helpers for tests/local usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import requests


@dataclass
class IstioObservabilityManager:
    """Manage Istio telemetry/access log configs."""

    namespace: str = "default"
    telemetry: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    access_logs: Dict[str, Any] = field(default_factory=dict)

    def configure_telemetry(self, name: str, config: Dict[str, Any]) -> bool:
        self.telemetry[name] = dict(config)
        return True

    def configure_access_logs(self, config: Dict[str, Any]) -> bool:
        self.access_logs = dict(config)
        return True

    def get_service_metrics(self, service_name: str) -> Dict[str, str]:
        try:
            response = requests.get("http://prometheus/api/v1/query", timeout=5)
            payload = response.json()
            results = payload.get("data", {}).get("result", [])
            metrics = {}
            for item in results:
                metric_name = item.get("metric", {}).get("__name__")
                value = item.get("value", [None, None])[1]
                if metric_name is not None and value is not None:
                    metrics[metric_name] = value
            return metrics
        except Exception:
            return {}
