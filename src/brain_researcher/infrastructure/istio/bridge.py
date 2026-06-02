"""Minimal Istio bridge implementation for tests/local usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import aiohttp


@dataclass
class IstioBridge:
    """Bridge for service-to-service calls and basic config storage."""

    namespace: str = "default"
    services: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    circuit_breakers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    retry_policies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timeouts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    health_checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    config: Any = None

    def register_service(self, name: str, info: Dict[str, Any]) -> bool:
        self.services[name] = dict(info)
        return True

    async def call_service(
        self,
        service_name: str,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"http://{service_name}{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=data) as resp:
                return await resp.json()

    def configure_circuit_breaker(
        self, service_name: str, config: Dict[str, Any]
    ) -> bool:
        self.circuit_breakers[service_name] = dict(config)
        return True

    def configure_retry_policy(self, service_name: str, config: Dict[str, Any]) -> bool:
        self.retry_policies[service_name] = dict(config)
        return True

    def configure_timeout(self, service_name: str, config: Dict[str, Any]) -> bool:
        self.timeouts[service_name] = dict(config)
        return True

    def configure_health_checks(
        self, service_name: str, config: Dict[str, Any]
    ) -> bool:
        self.health_checks[service_name] = dict(config)
        return True
