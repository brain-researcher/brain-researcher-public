"""Unit tests for realtime two-photon controller backends."""

from __future__ import annotations

import json
import queue
import socket
import threading

import pytest
from websockets.sync.server import serve

from brain_researcher.services.tools.realtime_twophoton_controller import (
    UDPController,
    WebSocketController,
    build_controller,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_build_controller_requires_target_for_websocket():
    with pytest.raises(ValueError, match="controller_target"):
        build_controller(backend="websocket", target=None)


def test_udp_controller_emits_json_payload():
    port = _free_port()
    received: queue.Queue[bytes] = queue.Queue()

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", port))
    server.settimeout(2.0)

    def _listen() -> None:
        data, _addr = server.recvfrom(8192)
        received.put(data)

    listener = threading.Thread(target=_listen, daemon=True)
    listener.start()

    controller = UDPController(host="127.0.0.1", port=port)
    controller.emit({"state_value": 3, "confidence": 0.9})
    listener.join(timeout=2.0)
    controller.close()
    server.close()

    payload = json.loads(received.get_nowait().decode("utf-8"))
    assert payload["state_value"] == 3
    assert payload["confidence"] == 0.9


def test_websocket_controller_emits_json_payload():
    port = _free_port()
    received: queue.Queue[str] = queue.Queue()
    ready = threading.Event()
    server_holder: dict[str, object] = {}

    def _serve() -> None:
        def _handler(connection) -> None:
            received.put(connection.recv())

        with serve(_handler, "127.0.0.1", port) as server:
            server_holder["server"] = server
            ready.set()
            server.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)

    controller = WebSocketController(target=f"ws://127.0.0.1:{port}")
    controller.emit({"state_name": "coarse_place_bin", "state_value": 5})
    controller.close()
    server_holder["server"].shutdown()  # type: ignore[union-attr]
    thread.join(timeout=2.0)

    payload = json.loads(received.get_nowait())
    assert payload["state_name"] == "coarse_place_bin"
    assert payload["state_value"] == 5
