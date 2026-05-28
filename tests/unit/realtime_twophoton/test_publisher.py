"""Unit tests for realtime two-photon raw-socket publishing helpers."""

from __future__ import annotations

import json
import queue
import socket
import threading

import numpy as np
import pytest

from brain_researcher.services.tools.realtime_twophoton_publisher import (
    RawSocketPublisher,
    RawSocketPublisherConfig,
    publish_replay_bundle_to_raw_socket,
)
from brain_researcher.services.tools.realtime_twophoton_runtime import (
    build_simulated_bundle,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_raw_socket_publisher_emits_start_frame_end_messages():
    port = _free_port()
    received: queue.Queue[list[dict[str, object]]] = queue.Queue()
    ready = threading.Event()

    def _server() -> None:
        listener = socket.create_server(("127.0.0.1", port), backlog=1)
        listener.settimeout(2.0)
        ready.set()
        conn, _addr = listener.accept()
        with listener, conn:
            reader = conn.makefile("r", encoding="utf-8")
            records = [json.loads(line) for line in reader if line.strip()]
            received.put(records)

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)

    frames = np.arange(18, dtype=np.float32).reshape(2, 3, 3)
    timestamps = np.asarray([0.1, 0.2], dtype=np.float32)
    publisher = RawSocketPublisher(
        RawSocketPublisherConfig(host="127.0.0.1", port=port)
    )
    publisher.publish_frames(frames, timestamps_s=timestamps)
    publisher.close()
    thread.join(timeout=2.0)

    records = received.get_nowait()
    assert [record["type"] for record in records] == [
        "stream_start",
        "frame",
        "frame",
        "stream_end",
    ]
    assert records[1]["frame_id"] == 0
    assert records[1]["shape"] == [3, 3]
    assert records[1]["dtype"] == "float32"
    assert records[2]["timestamp_s"] == pytest.approx(0.2)


def test_publish_replay_bundle_to_raw_socket_sends_all_frames():
    port = _free_port()
    bundle = build_simulated_bundle(
        n_frames=6,
        frame_shape=(24, 24),
        n_rois=8,
        n_state_bins=8,
        noise=0.02,
        frame_rate_hz=20.0,
    )
    received: queue.Queue[int] = queue.Queue()
    ready = threading.Event()

    def _server() -> None:
        listener = socket.create_server(("127.0.0.1", port), backlog=1)
        listener.settimeout(2.0)
        ready.set()
        conn, _addr = listener.accept()
        with listener, conn:
            reader = conn.makefile("r", encoding="utf-8")
            count = 0
            for line in reader:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if payload.get("type") == "frame":
                    count += 1
            received.put(count)

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)

    sent = publish_replay_bundle_to_raw_socket(
        bundle,
        host="127.0.0.1",
        port=port,
    )
    thread.join(timeout=2.0)

    assert sent == 6
    assert received.get_nowait() == 6
