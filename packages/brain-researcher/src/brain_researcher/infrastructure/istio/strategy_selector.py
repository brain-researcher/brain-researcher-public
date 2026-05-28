"""Deployment strategy selection helpers (test/local stub)."""

from __future__ import annotations

from typing import Any, Dict, Optional


class DeploymentStrategySelector:
    """Select the safest deployment strategy for a service."""

    def select_strategy(self, service_profile: Dict[str, Any], preferred: Optional[str] = None) -> str:
        criticality = service_profile.get("criticality", "medium")

        if preferred:
            if preferred == "rolling" and criticality == "high":
                return "canary"
            return preferred

        if criticality == "high":
            return "blue-green"
        return "rolling"

