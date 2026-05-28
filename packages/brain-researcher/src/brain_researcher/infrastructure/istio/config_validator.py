"""Istio configuration validation helpers."""

from __future__ import annotations

from typing import Any, Dict


class IstioConfigValidator:
    """Validate basic Istio resource schemas."""

    def validate_virtual_service(self, config: Dict[str, Any]) -> bool:
        if not isinstance(config, dict):
            return False
        spec = config.get("spec") or {}
        hosts = spec.get("hosts") or []
        http = spec.get("http") or []
        if not hosts or not isinstance(hosts, list):
            return False
        if not http or not isinstance(http, list):
            return False
        return True
