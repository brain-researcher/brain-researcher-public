"""Microscope-side publisher/client for realtime two-photon raw_socket streams."""

from __future__ import annotations

import base64
import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .realtime_twophoton_acquisition import load_replay_bundle


@dataclass(frozen=True)
class RawSocketPublisherConfig:
    """Connection settings for the raw-socket publisher."""

    host: str = "127.0.0.1"
    port: int = 7788
    connect_timeout_s: float = 5.0
    write_timeout_s: float = 5.0
    connect_retry_interval_s: float = 0.05
    send_start_event: bool = True
    send_end_event: bool = True


class RawSocketPublisher:
    """Small TCP client that emits the realtime two-photon NDJSON protocol."""

    def __init__(self, config: RawSocketPublisherConfig):
        self.config = config
        self._socket: socket.socket | None = None
        self._writer = None
        self._started = False

    @property
    def is_connected(self) -> bool:
        return self._socket is not None and self._writer is not None

    def connect(self) -> None:
        if self.is_connected:
            return

        deadline = time.monotonic() + float(self.config.connect_timeout_s)
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection(
                    (self.config.host, int(self.config.port)),
                    timeout=min(1.0, float(self.config.write_timeout_s)),
                )
                sock.settimeout(float(self.config.write_timeout_s))
                writer = sock.makefile("w", encoding="utf-8")
                self._socket = sock
                self._writer = writer
                return
            except OSError as exc:
                last_error = exc
                time.sleep(float(self.config.connect_retry_interval_s))

        raise ConnectionError(
            f"Unable to connect raw_socket publisher to "
            f"{self.config.host}:{int(self.config.port)}: {last_error}"
        )

    def send_json(self, payload: dict[str, Any]) -> None:
        self.connect()
        assert self._writer is not None
        self._writer.write(json.dumps(payload) + "\n")
        self._writer.flush()

    def send_start(self, metadata: dict[str, Any] | None = None) -> None:
        if self._started:
            return
        payload: dict[str, Any] = {"type": "stream_start"}
        if metadata:
            payload.update(metadata)
        self.send_json(payload)
        self._started = True

    def send_frame(
        self,
        frame: np.ndarray,
        *,
        frame_id: int,
        timestamp_s: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        image = np.asarray(frame)
        if image.ndim != 2:
            raise ValueError(f"Expected 2D frame image, got shape {image.shape}")

        if self.config.send_start_event and not self._started:
            self.send_start()

        wire_image = np.asarray(image, dtype=np.float32)
        payload: dict[str, Any] = {
            "type": "frame",
            "frame_id": int(frame_id),
            "shape": list(wire_image.shape),
            "dtype": str(wire_image.dtype),
            "image_b64": base64.b64encode(wire_image.tobytes()).decode("ascii"),
        }
        if timestamp_s is not None:
            payload["timestamp_s"] = float(timestamp_s)
        if metadata:
            payload.update(metadata)
        self.send_json(payload)

    def send_end(self, metadata: dict[str, Any] | None = None) -> None:
        if not self.is_connected:
            return
        payload: dict[str, Any] = {"type": "stream_end"}
        if metadata:
            payload.update(metadata)
        self.send_json(payload)

    def publish_frames(
        self,
        frames: np.ndarray,
        *,
        timestamps_s: np.ndarray | None = None,
        start_metadata: dict[str, Any] | None = None,
        frame_metadata: dict[str, Any] | None = None,
    ) -> int:
        stack = np.asarray(frames)
        if stack.ndim != 3:
            raise ValueError(
                f"Expected frames with shape [n_frames, height, width], got {stack.shape}"
            )
        if timestamps_s is not None and len(timestamps_s) != len(stack):
            raise ValueError("timestamps_s length must match number of frames")

        if self.config.send_start_event:
            self.send_start(metadata=start_metadata)

        for frame_idx, frame in enumerate(stack):
            timestamp = (
                float(timestamps_s[frame_idx]) if timestamps_s is not None else None
            )
            self.send_frame(
                frame,
                frame_id=frame_idx,
                timestamp_s=timestamp,
                metadata=frame_metadata,
            )

        if self.config.send_end_event:
            self.send_end()
        return int(len(stack))

    def close(self) -> None:
        writer = self._writer
        sock = self._socket
        self._writer = None
        self._socket = None
        self._started = False
        if writer is not None:
            writer.close()
        if sock is not None:
            sock.close()

    def __enter__(self) -> RawSocketPublisher:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self.close()


def publish_frames_to_raw_socket(
    frames: np.ndarray,
    *,
    host: str,
    port: int,
    timestamps_s: np.ndarray | None = None,
    connect_timeout_s: float = 5.0,
    write_timeout_s: float = 5.0,
    connect_retry_interval_s: float = 0.05,
) -> int:
    """Convenience helper to publish a stack of frames in one call."""

    publisher = RawSocketPublisher(
        RawSocketPublisherConfig(
            host=host,
            port=port,
            connect_timeout_s=connect_timeout_s,
            write_timeout_s=write_timeout_s,
            connect_retry_interval_s=connect_retry_interval_s,
        )
    )
    try:
        return publisher.publish_frames(frames, timestamps_s=timestamps_s)
    finally:
        publisher.close()


def publish_replay_bundle_to_raw_socket(
    replay_source: str | Path | dict[str, Any],
    *,
    host: str,
    port: int,
    frames_key: str = "frames",
    timestamps_key: str = "timestamps_s",
    connect_timeout_s: float = 5.0,
    write_timeout_s: float = 5.0,
    connect_retry_interval_s: float = 0.05,
) -> int:
    """Publish frames from an existing replay bundle to a raw_socket runtime."""

    if isinstance(replay_source, str | Path):
        bundle = load_replay_bundle(replay_source)
    else:
        bundle = replay_source
    if frames_key not in bundle:
        raise ValueError(f"Replay bundle is missing frames key: {frames_key}")
    frames = np.asarray(bundle[frames_key], dtype=np.float32)
    timestamps = (
        np.asarray(bundle[timestamps_key], dtype=np.float32)
        if timestamps_key in bundle
        else None
    )
    return publish_frames_to_raw_socket(
        frames,
        host=host,
        port=port,
        timestamps_s=timestamps,
        connect_timeout_s=connect_timeout_s,
        write_timeout_s=write_timeout_s,
        connect_retry_interval_s=connect_retry_interval_s,
    )
