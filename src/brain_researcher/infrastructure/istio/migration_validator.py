"""Validation helpers for Istio migrations (test/local stub)."""

from __future__ import annotations

from typing import Any, Dict, List


class MigrationValidator:
    """Validate Istio readiness and compatibility."""

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace

    def run_pre_migration_checks(self, service_config: Dict[str, Any]) -> Dict[str, Any]:
        checks = {
            "resource_validation": {"passed": True},
            "port_validation": {"passed": True},
            "image_validation": {"passed": True},
        }
        return {"passed": all(c["passed"] for c in checks.values()), "checks": checks}

    def check_istio_components(self) -> Dict[str, Dict[str, Any]]:
        return {
            "pilot": {"ready": True, "version": "1.18.0"},
            "proxy": {"ready": True, "version": "1.18.0"},
            "citadel": {"ready": True, "version": "1.18.0"},
        }

    def validate_istio_readiness(self) -> Dict[str, Any]:
        components = self.check_istio_components()
        ready = all(component.get("ready") for component in components.values())
        return {"ready": ready, "components": components}

    def validate_mesh_compatibility(self, service_spec: Dict[str, Any]) -> Dict[str, Any]:
        protocols = service_spec.get("protocols", [])
        protocol_support = {protocol: True for protocol in protocols}
        return {
            "compatible": True,
            "protocol_support": protocol_support,
            "observability_ready": bool(service_spec.get("observability_ready", True)),
        }

    def validate_network_policies(self, network_policies: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"compatible": True, "migration_required": True}
