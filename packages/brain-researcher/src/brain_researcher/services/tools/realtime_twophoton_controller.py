"""Controller backends for realtime two-photon replay."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ControllerEvent:
    """A controller emission or gated decision."""

    emitted: bool
    payload: dict
    backend: str
    reason: str | None = None


class Controller(Protocol):
    """Protocol for command emitters."""

    def emit(self, payload: dict) -> ControllerEvent:
        """Emit or no-op for a command payload."""

    def close(self) -> None:
        """Close any backend resources."""


class NullController:
    """Controller that never touches the network."""

    backend = "none"

    def emit(self, payload: dict) -> ControllerEvent:
        return ControllerEvent(emitted=False, payload=payload, backend=self.backend)

    def close(self) -> None:
        return None


class UDPController:
    """Simple JSON-over-UDP controller."""

    backend = "udp"

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = int(port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def emit(self, payload: dict) -> ControllerEvent:
        self.socket.sendto(json.dumps(payload).encode("utf-8"), (self.host, self.port))
        return ControllerEvent(emitted=True, payload=payload, backend=self.backend)

    def close(self) -> None:
        self.socket.close()


class WebSocketController:
    """Simple JSON-over-WebSocket controller."""

    backend = "websocket"

    def __init__(self, target: str):
        if not target:
            raise ValueError("controller_target is required when controller_backend='websocket'")
        try:
            from websockets.sync.client import connect
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "websockets is required for controller_backend='websocket'. "
                "Install the optical_realtime extra."
            ) from exc

        self.target = target
        self._connect = connect
        try:
            self.connection = self._connect(target, open_timeout=2.0)
        except Exception as exc:
            raise ConnectionError(f"Unable to connect to websocket controller target {target!r}: {exc}") from exc

    def emit(self, payload: dict[str, Any]) -> ControllerEvent:
        try:
            self.connection.send(json.dumps(payload))
        except Exception as exc:
            raise ConnectionError(
                f"Failed to emit websocket control payload to {self.target!r}: {exc}"
            ) from exc
        return ControllerEvent(emitted=True, payload=payload, backend=self.backend)

    def close(self) -> None:
        self.connection.close()


def build_controller(
    backend: str,
    host: str | None = None,
    port: int | None = None,
    target: str | None = None,
) -> Controller:
    """Build a controller backend."""

    normalized = backend.lower()
    if normalized == "none":
        return NullController()
    if normalized == "udp":
        if host is None or port is None:
            raise ValueError("controller_host and controller_port are required for UDP control")
        return UDPController(host=host, port=port)
    if normalized == "websocket":
        return WebSocketController(target=target or "")
    raise ValueError(f"Unsupported controller backend: {backend}")
