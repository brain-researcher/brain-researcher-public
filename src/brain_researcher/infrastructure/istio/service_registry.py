"""Minimal Istio service registry implementation for tests/local usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass
class IstioServiceRegistry:
    """Register and discover services in a lightweight, in-memory registry."""

    namespace: str = "default"
    services: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register_service(self, service_info: dict[str, Any]) -> bool:
        name = service_info.get("name")
        if not name:
            return False
        self.services[name] = dict(service_info)
        return True

    def discover_services(
        self, label_selector: str | None = None
    ) -> list[dict[str, Any]]:
        if not label_selector:
            return list(self.services.values())

        # Very small selector parser: "key=value"
        key, _, value = label_selector.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            return list(self.services.values())

        results = []
        for svc in self.services.values():
            labels = svc.get("labels", {}) or {}
            if labels.get(key) == value:
                results.append(svc)
        return results

    def check_service_health(self, service_name: str) -> dict[str, Any]:
        service = self.services.get(service_name)
        if not service:
            return {"status": "unknown", "healthy": False}

        health_path = service.get("health_check", "/health")
        port = service.get("port", 80)
        url = f"http://{service_name}:{port}{health_path}"

        try:
            response = requests.get(url, timeout=5)
            payload = {}
            try:
                payload = response.json()
            except Exception:
                payload = {}
            status = payload.get(
                "status", "healthy" if response.status_code == 200 else "unhealthy"
            )
            return {"status": status, "healthy": response.status_code == 200}
        except Exception:
            return {"status": "unreachable", "healthy": False}
