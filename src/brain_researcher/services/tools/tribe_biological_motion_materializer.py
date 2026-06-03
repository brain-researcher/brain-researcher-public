"""Materialize condition-resolved biological-motion TRIBE stimuli from walkerdata.mat."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import loadmat

from brain_researcher.services.tools.tribe_stimulus_library import (
    DEFAULT_TRIBE_STIMULUS_LIBRARY,
    resolve_task_config,
)

WALKER_LABELS = {
    0: "BMLwalker",
    1: "ModifiedWalker",
    2: "IdealCuttingWalker",
}


@dataclass(frozen=True)
class ClipSpec:
    item_id: str
    condition: str
    scramble_kind: str
    azimuth_deg: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_walker_collection(raw: Any) -> list[np.ndarray]:
    if isinstance(raw, np.ndarray) and raw.dtype == object:
        arrays = [np.asarray(item, dtype=np.float32) for item in raw.flat]
    elif isinstance(raw, np.ndarray) and raw.ndim == 4:
        arrays = [
            np.asarray(raw[..., index], dtype=np.float32)
            for index in range(raw.shape[-1])
        ]
    elif isinstance(raw, np.ndarray) and raw.ndim == 3:
        arrays = [np.asarray(raw, dtype=np.float32)]
    elif isinstance(raw, list | tuple):
        arrays = [np.asarray(item, dtype=np.float32) for item in raw]
    else:
        raise ValueError(f"Unsupported walkerdata structure: {type(raw)!r}")

    normalized: list[np.ndarray] = []
    for item in arrays:
        if item.ndim != 3 or item.shape[2] != 3:
            raise ValueError(
                f"Each walker must have shape (frames, markers, 3); got {item.shape!r}"
            )
        normalized.append(item)
    if not normalized:
        raise ValueError("walkerdata did not contain any walkers")
    return normalized


def load_walker_collection(walker_mat_path: Path) -> list[np.ndarray]:
    payload = loadmat(walker_mat_path, simplify_cells=True)
    if "walkerdata" not in payload:
        raise KeyError(f"walkerdata variable not found in {walker_mat_path}")
    return _normalize_walker_collection(payload["walkerdata"])


def _spatial_scramble_md(
    walker: np.ndarray,
    *,
    area: tuple[float, float, float] = (100.0, 400.0, 300.0),
    retain_vertical: bool = True,
    rng: np.random.Generator,
) -> np.ndarray:
    out = np.array(walker, copy=True)
    mean_positions = out.mean(axis=0)
    center = mean_positions.reshape(-1, 3).mean(axis=0)
    new_mean_positions = (
        rng.random((out.shape[1], 3), dtype=np.float32) - 0.5
    ) * np.array(
        area,
        dtype=np.float32,
    ) + center
    if retain_vertical:
        new_mean_positions[:, 2] = mean_positions[:, 2]
    return out - mean_positions[np.newaxis, :, :] + new_mean_positions[np.newaxis, :, :]


def _phase_scramble_md(walker: np.ndarray, *, rng: np.random.Generator) -> np.ndarray:
    out = np.array(walker, copy=True)
    n_frames = out.shape[0]
    shifts = rng.integers(0, n_frames, size=out.shape[1])
    for marker_index, shift in enumerate(shifts):
        out[:, marker_index, :] = np.roll(out[:, marker_index, :], -int(shift), axis=0)
    return out


def _project_walker_to_2d(
    walker: np.ndarray,
    *,
    azimuth_deg: int,
    scramble_kind: str,
    rng: np.random.Generator,
) -> np.ndarray:
    out = np.array(walker, dtype=np.float32, copy=True)
    out[:, :, 2] = -out[:, :, 2]
    out /= 10.0
    out *= 2.0

    if scramble_kind == "spatial":
        out = _spatial_scramble_md(out, rng=rng)
    elif scramble_kind == "phase":
        out = _phase_scramble_md(out, rng=rng)
    elif scramble_kind != "coherent":
        raise ValueError(f"Unsupported scramble kind: {scramble_kind}")

    out[:, :, 2] -= out[:, :, 2].mean()
    radians = np.deg2rad(float(azimuth_deg))
    x_coords = out[:, :, 1] * np.cos(radians) + out[:, :, 0] * np.sin(radians)
    y_coords = -out[:, :, 2]
    return np.stack([x_coords, y_coords], axis=-1)


def _loop_and_resample(
    projected: np.ndarray,
    *,
    source_fps: float,
    output_fps: int,
    duration_seconds: float,
) -> np.ndarray:
    n_output_frames = max(1, int(round(duration_seconds * output_fps)))
    times = np.arange(n_output_frames, dtype=np.float32) / float(output_fps)
    source_indices = np.floor((times * source_fps) % projected.shape[0]).astype(
        np.int64
    )
    return projected[source_indices]


def _render_frames(
    points_by_frame: np.ndarray,
    *,
    frame_width: int,
    frame_height: int,
    dot_radius: int,
) -> list[np.ndarray]:
    from PIL import Image, ImageDraw

    flat = points_by_frame.reshape(-1, 2)
    mins = flat.min(axis=0)
    maxs = flat.max(axis=0)
    center = (mins + maxs) / 2.0
    span = float(np.max(maxs - mins))
    span = max(span, 1e-6)
    scale = 0.72 * float(min(frame_width, frame_height)) / span

    rendered: list[np.ndarray] = []
    for frame_points in points_by_frame:
        image = Image.new("RGB", (frame_width, frame_height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for x_coord, y_coord in frame_points:
            x_px = int(round((x_coord - center[0]) * scale + (frame_width / 2.0)))
            y_px = int(round((frame_height / 2.0) - (y_coord - center[1]) * scale))
            if 0 <= x_px < frame_width and 0 <= y_px < frame_height:
                draw.ellipse(
                    (
                        x_px - dot_radius,
                        y_px - dot_radius,
                        x_px + dot_radius,
                        y_px + dot_radius,
                    ),
                    fill=(255, 255, 255),
                )
        rendered.append(np.asarray(image, dtype=np.uint8))
    return rendered


def _write_clip_frames_and_video(
    *,
    frames: list[np.ndarray],
    clip_dir: Path,
    item_id: str,
    fps: int,
) -> tuple[Path, Path]:
    import imageio.v2 as imageio

    frame_dir = clip_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for stale_frame in frame_dir.glob("*.png"):
        stale_frame.unlink()
    for index, frame in enumerate(frames):
        frame_path = frame_dir / f"{item_id}_{index:04d}.png"
        imageio.imwrite(frame_path, frame)

    video_path = clip_dir / f"{item_id}.mp4"
    with imageio.get_writer(
        str(video_path),
        format="FFMPEG",
        mode="I",
        fps=float(fps),
        codec="libx264",
        macro_block_size=None,
    ) as writer:
        for frame in frames:
            writer.append_data(frame)
    return frame_dir, video_path


def _default_clip_specs() -> tuple[ClipSpec, ...]:
    return (
        ClipSpec(
            item_id="intact_biological_motion_az090",
            condition="intact_biological_motion",
            scramble_kind="coherent",
            azimuth_deg=90,
        ),
        ClipSpec(
            item_id="intact_biological_motion_az-090",
            condition="intact_biological_motion",
            scramble_kind="coherent",
            azimuth_deg=-90,
        ),
        ClipSpec(
            item_id="spatial_scrambled_motion_az090",
            condition="spatial_or_phase_scrambled_motion",
            scramble_kind="spatial",
            azimuth_deg=90,
        ),
        ClipSpec(
            item_id="spatial_scrambled_motion_az-090",
            condition="spatial_or_phase_scrambled_motion",
            scramble_kind="spatial",
            azimuth_deg=-90,
        ),
        ClipSpec(
            item_id="phase_scrambled_motion_az090",
            condition="spatial_or_phase_scrambled_motion",
            scramble_kind="phase",
            azimuth_deg=90,
        ),
        ClipSpec(
            item_id="phase_scrambled_motion_az-090",
            condition="spatial_or_phase_scrambled_motion",
            scramble_kind="phase",
            azimuth_deg=-90,
        ),
    )


def _legacy_condition_for(condition: str) -> str:
    return "biomo_type1" if condition == "intact_biological_motion" else "biomo_type2"


def materialize_biological_motion(
    *,
    stimulus_library: Path,
    walker_mat_path: Path,
    output_root: Path,
    manifest_path: Path,
    walker_index: int,
    duration_seconds: float,
    fps: int,
    frame_width: int,
    frame_height: int,
    dot_radius: int,
    seed: int,
    emit_legacy_biomo_types: bool,
) -> dict[str, Any]:
    task = resolve_task_config("ibc_biological_motion", stimulus_library)
    walkers = load_walker_collection(walker_mat_path)
    if walker_index < 0 or walker_index >= len(walkers):
        raise IndexError(
            f"walker_index {walker_index} is out of range for {len(walkers)} walkers"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    walker = walkers[walker_index]
    items: list[dict[str, Any]] = []
    for index, clip_spec in enumerate(_default_clip_specs()):
        rng = np.random.default_rng(seed + index)
        projected = _project_walker_to_2d(
            walker,
            azimuth_deg=clip_spec.azimuth_deg,
            scramble_kind=clip_spec.scramble_kind,
            rng=rng,
        )
        points_by_frame = _loop_and_resample(
            projected,
            source_fps=120.0,
            output_fps=fps,
            duration_seconds=duration_seconds,
        )
        frames = _render_frames(
            points_by_frame,
            frame_width=frame_width,
            frame_height=frame_height,
            dot_radius=dot_radius,
        )
        clip_dir = output_root / clip_spec.item_id
        frame_dir, video_path = _write_clip_frames_and_video(
            frames=frames,
            clip_dir=clip_dir,
            item_id=clip_spec.item_id,
            fps=fps,
        )
        resolved_video_path = str(video_path.resolve())
        resolved_frame_dir = str(frame_dir.resolve())
        base_labels = {
            "run_type": (
                "1" if clip_spec.condition == "intact_biological_motion" else "2"
            ),
            "scramble_kind": clip_spec.scramble_kind,
            "azimuth_deg": clip_spec.azimuth_deg,
            "walker_index": walker_index,
            "walker_label": WALKER_LABELS.get(walker_index, f"walker_{walker_index}"),
        }
        item = {
            "item_id": clip_spec.item_id,
            "condition": clip_spec.condition,
            "tribe_args": {"video_path": resolved_video_path},
            "source": {
                "path": resolved_video_path,
                "frame_dir": resolved_frame_dir,
                "walker_mat_path": str(walker_mat_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
            },
            "labels": dict(base_labels),
            "task_id": task.task_id,
            "video_path": resolved_video_path,
            "frame_dir": resolved_frame_dir,
            "manifest_path": str(manifest_path.resolve()),
            "fps": fps,
            "duration_seconds": duration_seconds,
            "n_frames": len(frames),
            "frame_width": frame_width,
            "frame_height": frame_height,
            "dot_radius": dot_radius,
            "scramble_kind": clip_spec.scramble_kind,
            "azimuth_deg": clip_spec.azimuth_deg,
            "walker_index": walker_index,
            "walker_label": WALKER_LABELS.get(walker_index, f"walker_{walker_index}"),
            "source_walker_mat": str(walker_mat_path.resolve()),
        }
        items.append(item)
        if emit_legacy_biomo_types:
            legacy_condition = _legacy_condition_for(clip_spec.condition)
            items.append(
                {
                    **item,
                    "item_id": f"{clip_spec.item_id}_{legacy_condition}",
                    "condition": legacy_condition,
                    "labels": {
                        **base_labels,
                        "legacy_condition_alias": legacy_condition,
                    },
                }
            )

    condition_counts = dict(Counter(str(item["condition"]) for item in items))
    manifest = {
        "schema_version": "tribe-biological-motion-manifest-v2",
        "prepared_at_utc": _utc_now_iso(),
        "generated_at_utc": _utc_now_iso(),
        "task_id": task.task_id,
        "library_id": task.library_id,
        "priority": task.priority,
        "task_family": task.family,
        "task_readiness": task.readiness,
        "family": task.family,
        "source_subdir": task.source_subdir,
        "preferred_tribe_input": task.preferred_tribe_input,
        "materialized_root": str(output_root.resolve()),
        "source_walker_mat": str(walker_mat_path.resolve()),
        "source_root": str(task.source_root.resolve()),
        "expected_rois": list(task.expected_rois),
        "br_kg_tags": list(task.br_kg_tags),
        "contrasts": list(task.contrasts),
        "item_count": len(items),
        "condition_counts": condition_counts,
        "items": items,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    rows_path = output_root / "stimuli.jsonl"
    with rows_path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")

    summary_path = output_root / "materialization_summary.json"
    summary_payload = {
        "manifest_path": str(manifest_path.resolve()),
        "stimuli_jsonl_path": str(rows_path.resolve()),
        "items_total": len(items),
        "conditions": sorted({item["condition"] for item in items}),
        "walker_index": walker_index,
        "walker_label": WALKER_LABELS.get(walker_index, f"walker_{walker_index}"),
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    return summary_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stimulus-library",
        type=Path,
        default=DEFAULT_TRIBE_STIMULUS_LIBRARY,
        help="Path to configs/experiments/tribe_ibc_stimulus_library.yaml",
    )
    parser.add_argument(
        "--walker-mat",
        type=Path,
        default=None,
        help="Explicit path to protocol/walkerdata.mat. Defaults to the path implied by the stimulus library.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Override the materialized_root from the stimulus library task config.",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=None,
        help="Override the manifest_path from the stimulus library task config.",
    )
    parser.add_argument("--walker-index", type=int, default=0)
    parser.add_argument("--duration-seconds", type=float, default=4.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--frame-width", type=int, default=512)
    parser.add_argument("--frame-height", type=int, default=512)
    parser.add_argument("--dot-radius", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--emit-legacy-biomo-types",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Emit alias rows for biomo_type1 and biomo_type2 so the stock "
            "legacy biological-motion contrast remains materialized."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    task = resolve_task_config(
        "ibc_biological_motion",
        args.stimulus_library.expanduser().resolve(),
    )
    walker_mat_path = (
        args.walker_mat.expanduser().resolve()
        if args.walker_mat is not None
        else (task.source_root / "protocol" / "walkerdata.mat").resolve()
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root is not None
        else task.materialized_root
    )
    manifest_path = (
        args.manifest_path.expanduser().resolve()
        if args.manifest_path is not None
        else task.manifest_path
    )
    try:
        summary = materialize_biological_motion(
            stimulus_library=args.stimulus_library.expanduser().resolve(),
            walker_mat_path=walker_mat_path,
            output_root=output_root,
            manifest_path=manifest_path,
            walker_index=args.walker_index,
            duration_seconds=args.duration_seconds,
            fps=args.fps,
            frame_width=args.frame_width,
            frame_height=args.frame_height,
            dot_radius=args.dot_radius,
            seed=args.seed,
            emit_legacy_biomo_types=args.emit_legacy_biomo_types,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps({"status": "ok", **summary}, indent=2))
    return 0


__all__ = [
    "ClipSpec",
    "build_parser",
    "load_walker_collection",
    "main",
    "materialize_biological_motion",
]
