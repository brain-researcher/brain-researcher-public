"""Minimal Istio security policy helpers for tests/local usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class IstioSecurityManager:
    """Manage Istio security resources in-memory."""

    namespace: str = "default"
    authorization_policies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    peer_authentications: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    request_authentications: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def create_authorization_policy(self, name: str, config: Dict[str, Any]) -> bool:
        self.authorization_policies[name] = dict(config)
        return True

    def enable_mtls(self, namespace: str, config: Dict[str, Any]) -> bool:
        self.peer_authentications[namespace] = dict(config)
        return True

    def configure_jwt_validation(self, name: str, config: Dict[str, Any]) -> bool:
        self.request_authentications[name] = dict(config)
        return True
