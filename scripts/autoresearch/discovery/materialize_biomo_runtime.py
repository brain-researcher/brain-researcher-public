#!/usr/bin/env python3
"""Standalone runtime materializer for IBC biological-motion TRIBE stimuli.

This avoids importing the full brain_researcher package on the discovery VM.
It writes a condition-resolved manifest with intact biological motion and
spatial/phase-scrambled controls.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw
from scipy.io import loadmat


@dataclass(frozen=True)
class ClipSpec:
    item_id: str
    condition: str
    scramble_kind: str
    azimuth_deg: int


CLIPS = (
    ClipSpec("intact_biological_motion_az090", "intact_biological_motion", "coherent", 90),
    ClipSpec("intact_biological_motion_az-090", "intact_biological_motion", "coherent", -90),
    ClipSpec("spatial_scrambled_motion_az090", "spatial_or_phase_scrambled_motion", "spatial", 90),
    ClipSpec("spatial_scrambled_motion_az-090", "spatial_or_phase_scrambled_motion", "spatial", -90),
    ClipSpec("phase_scrambled_motion_az090", "spatial_or_phase_scrambled_motion", "phase", 90),
    ClipSpec("phase_scrambled_motion_az-090", "spatial_or_phase_scrambled_motion", "phase", -90),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_walker_collection(raw: Any) -> list[np.ndarray]:
    if isinstance(raw, np.ndarray) and raw.dtype == object:
        arrays = [np.asarray(item, dtype=np.float32) for item in raw.flat]
    elif isinstance(raw, np.ndarray) and raw.ndim == 4:
        arrays = [np.asarray(raw[..., index], dtype=np.float32) for index in range(raw.shape[-1])]
    elif isinstance(raw, np.ndarray) and raw.ndim == 3:
        arrays = [np.asarray(raw, dtype=np.float32)]
    else:
        raise ValueError(f"Unsupported walkerdata structure: {type(raw)!r}")
    for item in arrays:
        if item.ndim != 3 or item.shape[2] != 3:
            raise ValueError(f"Expected walker shape (frames, markers, 3), got {item.shape!r}")
    return arrays


def load_walker_collection(path: Path) -> list[np.ndarray]:
    payload = loadmat(path, simplify_cells=True)
    return normalize_walker_collection(payload["walkerdata"])


def spatial_scramble(walker: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = np.array(walker, copy=True)
    means = out.mean(axis=0)
    center = means.reshape(-1, 3).mean(axis=0)
    new_means = (rng.random((out.shape[1], 3), dtype=np.float32) - 0.5) * np.array(
        (100.0, 400.0, 300.0),
        dtype=np.float32,
    ) + center
    new_means[:, 2] = means[:, 2]
    return out - means[np.newaxis, :, :] + new_means[np.newaxis, :, :]


def phase_scramble(walker: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = np.array(walker, copy=True)
    shifts = rng.integers(0, out.shape[0], size=out.shape[1])
    for marker_index, shift in enumerate(shifts):
        out[:, marker_index, :] = np.roll(out[:, marker_index, :], -int(shift), axis=0)
    return out


def project_walker(walker: np.ndarray, clip: ClipSpec, rng: np.random.Generator) -> np.ndarray:
    out = np.array(walker, dtype=np.float32, copy=True)
    out[:, :, 2] = -out[:, :, 2]
    out /= 10.0
    out *= 2.0
    if clip.scramble_kind == "spatial":
        out = spatial_scramble(out, rng)
    elif clip.scramble_kind == "phase":
        out = phase_scramble(out, rng)
    elif clip.scramble_kind != "coherent":
        raise ValueError(f"Unsupported scramble kind: {clip.scramble_kind}")
    out[:, :, 2] -= out[:, :, 2].mean()
    radians = np.deg2rad(float(clip.azimuth_deg))
    x_coords = out[:, :, 1] * np.cos(radians) + out[:, :, 0] * np.sin(radians)
    y_coords = -out[:, :, 2]
    return np.stack([x_coords, y_coords], axis=-1)


def loop_resample(projected: np.ndarray, fps: int, duration: float) -> np.ndarray:
    n_frames = max(1, int(round(duration * fps)))
    times = np.arange(n_frames, dtype=np.float32) / float(fps)
    source_indices = np.floor((times * 120.0) % projected.shape[0]).astype(np.int64)
    return projected[source_indices]


def render_frames(points_by_frame: np.ndarray, width: int, height: int, dot_radius: int) -> list[np.ndarray]:
    flat = points_by_frame.reshape(-1, 2)
    mins = flat.min(axis=0)
    maxs = flat.max(axis=0)
    center = (mins + maxs) / 2.0
    span = max(float(np.max(maxs - mins)), 1e-6)
    scale = 0.72 * float(min(width, height)) / span
    frames: list[np.ndarray] = []
    for points in points_by_frame:
        image = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for x_coord, y_coord in points:
            x_px = int(round((x_coord - center[0]) * scale + width / 2.0))
            y_px = int(round(height / 2.0 - (y_coord - center[1]) * scale))
            if 0 <= x_px < width and 0 <= y_px < height:
                draw.ellipse(
                    (x_px - dot_radius, y_px - dot_radius, x_px + dot_radius, y_px + dot_radius),
                    fill=(255, 255, 255),
                )
        frames.append(np.asarray(image, dtype=np.uint8))
    return frames


def write_video(frames: list[np.ndarray], path: Path, fps: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(
        str(path),
        format="FFMPEG",
        mode="I",
        fps=float(fps),
        codec="libx264",
        macro_block_size=None,
    ) as writer:
        for frame in frames:
            writer.append_data(frame)


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    walkers = load_walker_collection(args.walker_mat)
    if args.walker_indices:
        requested = str(args.walker_indices).strip().lower()
        if requested == "all":
            walker_indices = list(range(len(walkers)))
        else:
            walker_indices = [int(value.strip()) for value in requested.split(",") if value.strip()]
    else:
        walker_indices = [args.walker_index]
    for walker_index in walker_indices:
        if walker_index < 0 or walker_index >= len(walkers):
            raise ValueError(f"walker index {walker_index} out of range for {len(walkers)} walkers")

    items: list[dict[str, Any]] = []
    multi_walker = len(walker_indices) > 1
    for walker_index in walker_indices:
        walker = walkers[walker_index]
        for index, clip in enumerate(CLIPS):
            rng = np.random.default_rng(args.seed + 1000 * walker_index + index)
            frames = render_frames(
                loop_resample(project_walker(walker, clip, rng), args.fps, args.duration_seconds),
                args.frame_width,
                args.frame_height,
                args.dot_radius,
            )
            item_id = f"walker{walker_index:02d}_{clip.item_id}" if multi_walker else clip.item_id
            clip_dir = args.output_root / item_id
            video_path = (clip_dir / f"{item_id}.mp4").resolve()
            write_video(frames, video_path, args.fps)
            labels = {
                "run_type": "1" if clip.condition == "intact_biological_motion" else "2",
                "scramble_kind": clip.scramble_kind,
                "azimuth_deg": clip.azimuth_deg,
                "walker_index": walker_index,
            }
            item = {
                "item_id": item_id,
                "condition": clip.condition,
                "tribe_args": {"video_path": str(video_path)},
                "source": {"path": str(video_path), "walker_mat_path": str(args.walker_mat.resolve())},
                "labels": labels,
            }
            items.append(item)
            if not args.emit_legacy_biomo_types:
                continue
            legacy = "biomo_type1" if clip.condition == "intact_biological_motion" else "biomo_type2"
            items.append(
                {
                    **item,
                    "item_id": f"{item_id}_{legacy}",
                    "condition": legacy,
                    "labels": {**labels, "legacy_condition_alias": legacy},
                }
            )
    return {
        "schema_version": "tribe-biological-motion-manifest-v2",
        "prepared_at_utc": utc_now(),
        "generated_at_utc": utc_now(),
        "task_id": "ibc_biological_motion",
        "library_id": "tribe_ibc_paradigm_sweep_v1",
        "priority": "wave1",
        "task_family": "motion",
        "task_readiness": "ready_now",
        "family": "motion",
        "source_subdir": "BiologicalMotion",
        "preferred_tribe_input": "video_path",
        "materialized_root": str(args.output_root.resolve()),
        "source_walker_mat": str(args.walker_mat.resolve()),
        "source_walker_indices": walker_indices,
        "source_root": str(args.walker_mat.parent.parent.resolve()),
        "expected_rois": ["hMT_plus_V5", "posterior_superior_temporal_sulcus", "extrastriate_body_area"],
        "br_kg_tags": ["biological_motion", "motion_localizer", "social_perception"],
        "contrasts": [
            {
                "contrast_id": "biological_motion_type1_vs_type2",
                "positive_conditions": ["biomo_type1"],
                "negative_conditions": ["biomo_type2"],
            },
            {
                "contrast_id": "intact_motion_vs_scrambled_motion",
                "positive_conditions": ["intact_biological_motion"],
                "negative_conditions": ["spatial_or_phase_scrambled_motion"],
            },
        ],
        "item_count": len(items),
        "condition_counts": dict(Counter(str(item["condition"]) for item in items)),
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--walker-mat", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--walker-index", type=int, default=0)
    parser.add_argument("--walker-indices", default=None, help="Comma-separated walker indices or 'all'. Overrides --walker-index.")
    parser.add_argument("--duration-seconds", type=float, default=4.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--frame-width", type=int, default=512)
    parser.add_argument("--frame-height", type=int, default=512)
    parser.add_argument("--dot-radius", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--emit-legacy-biomo-types", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(args)
    args.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "manifest_path": str(args.manifest_path), "item_count": manifest["item_count"], "condition_counts": manifest["condition_counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
