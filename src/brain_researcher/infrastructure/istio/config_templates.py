"""Istio configuration templates for common resources."""

from __future__ import annotations

from typing import Dict


class IstioConfigTemplates:
    """Generate basic Istio resource templates."""

    def get_virtual_service_template(self, name: str, host: str, namespace: str) -> Dict[str, object]:
        return {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "hosts": [host],
                "http": [
                    {
                        "route": [
                            {
                                "destination": {"host": host},
                                "weight": 100,
                            }
                        ]
                    }
                ],
            },
        }
