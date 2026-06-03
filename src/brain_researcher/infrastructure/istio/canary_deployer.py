"""Canary deployment helper for Istio migrations (test/local stub)."""

from __future__ import annotations

import time
from typing import Any


class CanaryDeployer:
    """Manage canary deployments with simple in-memory state."""

    def __init__(self, namespace: str = "default", istio_client: Any | None = None):
        self.namespace = namespace
        self.istio_client = istio_client
        self.deployments: dict[str, dict[str, Any]] = {}

    def initialize_canary(self, config: dict[str, Any]) -> str:
        deployment_id = f"canary-{int(time.time() * 1000)}"
        self.deployments[deployment_id] = {
            "config": dict(config),
            "current_step": 0,
            "current_traffic": 0,
            "phase": "initialized",
            "started_at": time.time(),
        }
        return deployment_id

    def get_deployment_status(self, deployment_id: str) -> dict[str, Any]:
        deployment = self.deployments.get(deployment_id)
        if not deployment:
            return {"phase": "unknown", "current_traffic": 0, "current_step": 0}
        return {
            "phase": deployment.get("phase", "unknown"),
            "current_traffic": deployment.get("current_traffic", 0),
            "current_step": deployment.get("current_step", 0),
        }

    def collect_canary_metrics(self, deployment_id: str) -> dict[str, Any]:
        return {
            "error_rate": 0.0,
            "latency_p99": 100,
            "request_count": 100,
            "success_rate": 1.0,
        }

    def validate_canary_health(self, deployment_id: str) -> dict[str, Any]:
        deployment = self.deployments.get(deployment_id, {})
        config = deployment.get("config", {})
        criteria = config.get("success_criteria", {})
        error_threshold = criteria.get("error_rate_threshold", 0.05)
        latency_threshold = criteria.get("latency_p99_threshold", 1000)

        metrics = self.collect_canary_metrics(deployment_id)
        error_rate = metrics.get("error_rate", 0.0)
        latency = metrics.get("latency_p99", 0.0)

        healthy = error_rate <= error_threshold and latency <= latency_threshold
        return {
            "healthy": healthy,
            "requires_rollback": not healthy,
            "error_rate": error_rate,
            "latency_p99": latency,
        }

    def advance_traffic_split(self, deployment_id: str) -> bool:
        deployment = self.deployments.get(deployment_id)
        if not deployment:
            return False

        splits = deployment.get("config", {}).get("traffic_splits", [])
        current_step = deployment.get("current_step", 0)

        if current_step >= len(splits):
            deployment["phase"] = "completed"
            return True

        health = self.validate_canary_health(deployment_id)
        if not health.get("healthy", True):
            return False

        deployment["current_traffic"] = splits[current_step]
        deployment["current_step"] = current_step + 1
        deployment["phase"] = (
            "completed" if deployment["current_step"] >= len(splits) else "rolling_out"
        )
        return True

    def execute_rollback(self, deployment_id: str, reason: str = "") -> dict[str, Any]:
        deployment = self.deployments.get(deployment_id)
        if deployment:
            deployment["phase"] = "rolled_back"
            deployment["current_traffic"] = 0
            deployment["rollback_reason"] = reason
        return {"success": True, "rollback_time": 60}
