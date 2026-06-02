"""Replay, simulator, and raw-socket helpers for real-time two-photon pipelines."""

from __future__ import annotations

import base64
import json
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import shift as nd_shift

from .realtime_twophoton_schemas import FramePacket


@dataclass
class SyntheticReplayBundle:
    """Synthetic replay package used for simulator mode and tests."""

    frames: np.ndarray
    labels: np.ndarray
    timestamps_s: np.ndarray
    reference_template: np.ndarray
    roi_masks: np.ndarray
    neuropil_masks: np.ndarray
    latent_traces: np.ndarray


def _circular_mask(
    shape: tuple[int, int], center_y: int, center_x: int, radius: int
) -> np.ndarray:
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    return (yy - center_y) ** 2 + (xx - center_x) ** 2 <= radius**2


def generate_synthetic_replay_bundle(
    n_frames: int = 120,
    image_shape: tuple[int, int] = (64, 64),
    n_rois: int = 24,
    n_bins: int = 8,
    frame_rate_hz: float = 30.0,
    noise_std: float = 0.08,
    max_shift_px: float = 2.0,
    seed: int = 7,
) -> SyntheticReplayBundle:
    """Generate a synthetic calcium replay stream with place-bin labels."""

    rng = np.random.default_rng(seed)
    height, width = image_shape
    n_rois = max(n_rois, n_bins)
    roi_masks = np.zeros((n_rois, height, width), dtype=bool)
    neuropil_masks = np.zeros_like(roi_masks)
    union_mask = np.zeros((height, width), dtype=bool)
    centers: list[tuple[int, int]] = []

    for roi_idx in range(n_rois):
        for _ in range(100):
            cy = int(rng.integers(8, height - 8))
            cx = int(rng.integers(8, width - 8))
            radius = int(rng.integers(3, 5))
            mask = _circular_mask(image_shape, cy, cx, radius)
            if np.sum(union_mask & mask) < 6:
                roi_masks[roi_idx] = mask
                union_mask |= mask
                centers.append((cy, cx))
                break
        else:
            cy = int(rng.integers(8, height - 8))
            cx = int(rng.integers(8, width - 8))
            roi_masks[roi_idx] = _circular_mask(image_shape, cy, cx, 3)
            union_mask |= roi_masks[roi_idx]
            centers.append((cy, cx))

    for roi_idx, mask in enumerate(roi_masks):
        cy, cx = centers[roi_idx]
        outer = _circular_mask(image_shape, cy, cx, 6)
        neuropil = outer & ~mask
        neuropil_masks[roi_idx] = neuropil

    preferred_bins = np.arange(n_rois) % n_bins
    labels = np.arange(n_frames, dtype=int) % n_bins
    timestamps_s = np.arange(n_frames, dtype=float) / float(frame_rate_hz)
    latent_traces = np.zeros((n_frames, n_rois), dtype=np.float32)

    baseline_image = rng.normal(0.05, 0.01, size=image_shape).astype(np.float32)
    reference_template = baseline_image.copy()
    for mask in roi_masks:
        reference_template[mask] += 0.1

    frames = np.zeros((n_frames, height, width), dtype=np.float32)
    for frame_idx in range(n_frames):
        label = labels[frame_idx]
        frame = reference_template.copy()
        for roi_idx, mask in enumerate(roi_masks):
            distance = np.abs(preferred_bins[roi_idx] - label)
            distance = min(distance, n_bins - distance)
            gain = np.exp(-0.5 * (distance / 1.2) ** 2)
            activity = 0.4 + 1.4 * gain + rng.normal(0.0, 0.08)
            latent_traces[frame_idx, roi_idx] = max(activity, 0.01)
            frame[mask] += latent_traces[frame_idx, roi_idx]
            if np.any(neuropil_masks[roi_idx]):
                frame[neuropil_masks[roi_idx]] += (
                    latent_traces[frame_idx, roi_idx] * 0.12
                )

        frame += rng.normal(0.0, noise_std, size=image_shape)
        shift_y = float(rng.uniform(-max_shift_px, max_shift_px))
        shift_x = float(rng.uniform(-max_shift_px, max_shift_px))
        frames[frame_idx] = nd_shift(
            frame, shift=(shift_y, shift_x), order=1, mode="nearest"
        )

    return SyntheticReplayBundle(
        frames=frames,
        labels=labels,
        timestamps_s=timestamps_s,
        reference_template=reference_template.astype(np.float32),
        roi_masks=roi_masks,
        neuropil_masks=neuropil_masks,
        latent_traces=latent_traces,
    )


def load_replay_bundle(input_file: str | Path) -> dict[str, np.ndarray]:
    """Load a replay bundle from a `.npz` file."""

    path = Path(input_file)
    if not path.exists():
        raise FileNotFoundError(f"Replay file not found: {path}")

    with np.load(path, allow_pickle=True) as bundle:
        data = {key: bundle[key] for key in bundle.files}
    if "frames" not in data:
        raise ValueError("Replay bundle must contain 'frames'")
    return data


def save_replay_bundle(bundle: dict[str, np.ndarray], output_file: str | Path) -> Path:
    """Persist a replay bundle as a compressed `.npz`."""

    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **bundle)
    return path


def iter_bundle_frame_packets(
    bundle: dict[str, Any],
    frame_rate_hz: float,
) -> Iterator[FramePacket]:
    """Yield frame packets from an in-memory replay bundle."""

    frames = np.asarray(bundle["frames"], dtype=np.float32)
    timestamps = np.asarray(
        bundle.get(
            "timestamps_s",
            np.arange(len(frames), dtype=np.float32) / float(frame_rate_hz),
        ),
        dtype=np.float32,
    )
    for frame_idx, frame in enumerate(frames):
        timestamp_s = (
            float(timestamps[frame_idx])
            if frame_idx < len(timestamps)
            else float(frame_idx) / float(frame_rate_hz)
        )
        yield FramePacket(
            frame_id=frame_idx,
            timestamp_s=timestamp_s,
            image=np.asarray(frame, dtype=np.float32),
        )


def _decode_raw_socket_frame(
    payload: dict[str, Any],
    *,
    default_frame_id: int,
    default_timestamp_s: float,
) -> FramePacket:
    frame_id = int(payload.get("frame_id", default_frame_id))
    timestamp_s = float(payload.get("timestamp_s", default_timestamp_s))

    if "image" in payload:
        image = np.asarray(payload["image"], dtype=np.float32)
    elif "image_b64" in payload:
        if "shape" not in payload:
            raise ValueError(
                "raw_socket frame payload with 'image_b64' must include 'shape'"
            )
        shape = tuple(int(value) for value in payload["shape"])
        dtype = np.dtype(str(payload.get("dtype", "float32")))
        raw = base64.b64decode(payload["image_b64"])
        image = np.frombuffer(raw, dtype=dtype).reshape(shape).astype(np.float32)
    else:
        raise ValueError("raw_socket frame payload must include 'image' or 'image_b64'")

    if image.ndim != 2:
        raise ValueError(f"Expected 2D frame image, got shape {image.shape}")

    return FramePacket(frame_id=frame_id, timestamp_s=timestamp_s, image=image)


def iter_raw_socket_frame_packets(
    *,
    host: str,
    port: int,
    timeout_s: float,
    frame_rate_hz: float,
    max_frames: int | None = None,
) -> Iterator[FramePacket]:
    """Yield frame packets from a simple NDJSON-over-TCP stream.

    The runtime acts as a TCP listener. Each line must be a JSON object describing
    a frame packet, for example:

    `{"frame_id": 0, "timestamp_s": 0.0, "image": [[...], [...]]}`

    or the more compact base64 form:

    `{"frame_id": 0, "timestamp_s": 0.0, "shape": [64, 64], "dtype": "float32", "image_b64": "..."}`
    """

    listener = socket.create_server((host, int(port)), backlog=1)
    listener.settimeout(float(timeout_s))
    try:
        try:
            connection, _address = listener.accept()
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out waiting for raw_socket publisher on {(host, int(port))}"
            ) from exc
    finally:
        listener.close()

    with connection:
        connection.settimeout(float(timeout_s))
        reader = connection.makefile("r", encoding="utf-8")
        try:
            next_frame_id = 0
            while max_frames is None or next_frame_id < int(max_frames):
                try:
                    line = reader.readline()
                except OSError as exc:
                    raise TimeoutError(
                        f"Timed out waiting for raw_socket frame on {(host, int(port))}"
                    ) from exc
                if not line:
                    break
                payload = json.loads(line)
                packet_type = payload.get("type")
                if packet_type in {"stream_start", "start"}:
                    continue
                if packet_type in {"stream_end", "end"}:
                    break
                if packet_type not in {None, "frame"}:
                    continue

                packet = _decode_raw_socket_frame(
                    payload,
                    default_frame_id=next_frame_id,
                    default_timestamp_s=float(next_frame_id) / float(frame_rate_hz),
                )
                yield packet
                next_frame_id += 1
        finally:
            reader.close()
