"""Minimal Istio traffic management helpers for tests/local usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class _IstioConfigStore:
    virtual_services: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    destination_rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class IstioTrafficManager:
    """Manage Istio traffic resources in-memory (VirtualService/DestinationRule)."""

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace
        self.config = _IstioConfigStore()

    def create_virtual_service(self, name: str, config: Dict[str, Any]) -> bool:
        self.config.virtual_services[name] = dict(config)
        return True

    def create_destination_rule(self, name: str, config: Dict[str, Any]) -> bool:
        self.config.destination_rules[name] = dict(config)
        return True

    def configure_traffic_split(self, name: str, config: Dict[str, Any]) -> bool:
        # Traffic splitting is expressed via a VirtualService definition.
        self.config.virtual_services[name] = dict(config)
        return True
