"""Planning helpers for Istio migration workflows (test/local stub)."""

from __future__ import annotations

from typing import Any, Dict, List


def _parse_cpu(value: str) -> int:
    if value.endswith("m"):
        return int(value[:-1])
    try:
        return int(float(value) * 1000)
    except ValueError:
        return 0


def _parse_memory(value: str) -> int:
    if value.endswith("Gi"):
        return int(float(value[:-2]) * 1024)
    if value.endswith("Mi"):
        return int(float(value[:-2]))
    try:
        return int(value)
    except ValueError:
        return 0


def _format_cpu(milli: int) -> str:
    return f"{max(int(milli), 0)}m"


def _format_memory(mi: int) -> str:
    return f"{max(int(mi), 0)}Mi"


class MigrationPlanner:
    """Lightweight migration planner for Istio service mesh adoption."""

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace

    def calculate_migration_order(self, services: Dict[str, Dict[str, Any]]) -> List[str]:
        """Return a dependency-aware migration order."""
        remaining = {name: set(meta.get("dependencies", [])) for name, meta in services.items()}
        order: List[str] = []
        available = sorted(
            [name for name, deps in remaining.items() if not deps or not (deps & remaining.keys())]
        )

        while available:
            current = available.pop(0)
            order.append(current)
            remaining.pop(current, None)
            for name, deps in list(remaining.items()):
                deps.discard(current)
            available = sorted(
                [name for name, deps in remaining.items() if not deps or not (deps & remaining.keys())]
            )

        # Append any remaining services (cycles or missing data) in stable order
        if remaining:
            order.extend(sorted(remaining.keys()))

        return order

    def check_istio_compatibility(self, service_specs: Dict[str, Any]) -> Dict[str, Any]:
        protocols = service_specs.get("protocols", [])
        supported = [p for p in protocols if "HTTP" in p or "gRPC" in p or "http" in p]
        health_checks = bool(service_specs.get("health_endpoint") or service_specs.get("readiness_endpoint"))
        return {
            "compatible": True,
            "supported_protocols": supported or protocols,
            "health_checks_available": health_checks,
        }

    def estimate_migration_resources(self, service_config: Dict[str, Any]) -> Dict[str, Any]:
        cpu_limit = _parse_cpu(str(service_config.get("cpu_limit", "0m")))
        mem_limit = _parse_memory(str(service_config.get("memory_limit", "0Mi")))

        cpu_overhead = max(int(cpu_limit * 0.2), 1)
        mem_overhead = max(int(mem_limit * 0.2), 1)

        total_cpu = cpu_limit + cpu_overhead
        total_mem = mem_limit + mem_overhead

        return {
            "cpu_overhead": cpu_overhead,
            "memory_overhead": mem_overhead,
            "total_cpu": _format_cpu(total_cpu),
            "total_memory": _format_memory(total_mem),
        }

    def select_migration_strategy(self, service_profile: Dict[str, Any]) -> str:
        criticality = service_profile.get("criticality", "medium")
        traffic = service_profile.get("traffic_volume", "medium")
        external = bool(service_profile.get("external_traffic"))
        if criticality == "high":
            return "blue-green" if external or traffic == "high" else "canary"
        if traffic == "high":
            return "canary"
        return "rolling"

    def generate_rollback_plan(self, migration_config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "emergency_rollback": {
                "max_time": 300,
                "strategy": "immediate",
                "traffic_shift": "all_to_stable",
            },
            "gradual_rollback": {
                "steps": migration_config.get("traffic_splits", [100, 50, 0]),
                "validation_steps": migration_config.get("validation_steps", []),
            },
        }

