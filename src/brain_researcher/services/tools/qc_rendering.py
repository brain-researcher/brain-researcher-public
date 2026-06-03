"""Utilities for deterministic QC image rendering."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib
import nibabel as nib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _load_volume(path: str | Path) -> np.ndarray:
    path = Path(path)
    if path.suffix == ".npy":
        return np.asarray(np.load(path))
    if path.suffix == ".npz":
        npz = np.load(path)
        return np.asarray(npz[npz.files[0]])
    return np.asarray(nib.load(str(path)).get_fdata())


def _safe_slice_indices(mask_1d: np.ndarray, count: int = 3) -> list[int]:
    active = np.where(mask_1d > 0)[0]
    if active.size == 0:
        return []
    quantiles = np.linspace(0.2, 0.8, num=count)
    return sorted(
        {
            int(np.clip(np.quantile(active, q), active.min(), active.max()))
            for q in quantiles
        }
    )


def _normalize_image(data: np.ndarray) -> np.ndarray:
    finite = np.asarray(data, dtype=np.float32)
    finite = np.nan_to_num(finite, nan=0.0, posinf=0.0, neginf=0.0)
    positive = finite[finite > 0]
    if positive.size == 0:
        vmax = float(np.max(finite)) if finite.size else 1.0
        vmin = float(np.min(finite)) if finite.size else 0.0
    else:
        vmin = float(np.percentile(positive, 2))
        vmax = float(np.percentile(positive, 98))
    if vmax <= vmin:
        vmax = vmin + 1.0
    clipped = np.clip(finite, vmin, vmax)
    return (clipped - vmin) / (vmax - vmin)


def _extract_plane(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    if axis == 0:
        return np.rot90(volume[index, :, :])
    if axis == 1:
        return np.rot90(volume[:, index, :])
    return np.rot90(volume[:, :, index])


def _select_slice_indices(volume: np.ndarray, axis: int, count: int = 3) -> list[int]:
    mask = np.any(np.asarray(volume) != 0, axis=tuple(i for i in range(3) if i != axis))
    indices = _safe_slice_indices(mask, count=count)
    if indices:
        return indices
    return [int(volume.shape[axis] // 2)]


def _match_shapes(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    target_shape = tuple(min(a, b) for a, b in zip(left.shape[:3], right.shape[:3], strict=False))
    slices = tuple(slice(0, size) for size in target_shape)
    return np.asarray(left[slices]), np.asarray(right[slices])


def _checkerboard_slice(reference_slice: np.ndarray, moving_slice: np.ndarray, tiles: int = 8) -> np.ndarray:
    height, width = reference_slice.shape
    tile_h = max(1, height // tiles)
    tile_w = max(1, width // tiles)
    yy, xx = np.indices((height, width))
    mask = ((yy // tile_h) + (xx // tile_w)) % 2 == 0
    return np.where(mask, reference_slice, moving_slice)


def render_mask_overlay_png(
    anatomical_path: str | Path,
    mask_path: str | Path,
    output_png: str | Path,
    *,
    title: str | None = None,
) -> str:
    """Render a simple tri-planar mask-overlay montage for semantic QC."""

    anatomical = _load_volume(anatomical_path)
    mask = _load_volume(mask_path)
    anatomical = _normalize_image(np.asarray(anatomical))
    mask = (np.asarray(mask) > 0).astype(np.uint8)

    planes: Sequence[tuple[str, int]] = (
        ("sagittal", 0),
        ("coronal", 1),
        ("axial", 2),
    )
    slices: list[tuple[str, int, int]] = []
    for plane_name, axis in planes:
        indices = _safe_slice_indices(np.any(mask > 0, axis=tuple(i for i in range(3) if i != axis)))
        if not indices:
            indices = [mask.shape[axis] // 2]
        for idx in indices:
            slices.append((plane_name, axis, idx))

    fig, axes = plt.subplots(3, 3, figsize=(9, 9))
    fig.patch.set_facecolor("white")
    if title:
        fig.suptitle(title, fontsize=12)

    for ax, (plane_name, axis, idx) in zip(axes.flat, slices, strict=False):
        base_slice = _extract_plane(anatomical, axis, idx)
        mask_slice = _extract_plane(mask, axis, idx)
        ax.imshow(base_slice, cmap="gray", interpolation="nearest")
        if np.any(mask_slice):
            ax.contour(mask_slice, levels=[0.5], colors=["#ff3b30"], linewidths=1.2)
        ax.set_title(f"{plane_name} {idx}", fontsize=9)
        ax.axis("off")

    for ax in axes.flat[len(slices) :]:
        ax.axis("off")

    output_path = Path(output_png)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def render_registration_checkerboard_png(
    reference_path: str | Path,
    registered_path: str | Path,
    output_png: str | Path,
    *,
    title: str | None = None,
) -> str:
    """Render a tri-planar checkerboard for registration QC."""

    reference, registered = _match_shapes(
        _load_volume(reference_path),
        _load_volume(registered_path),
    )
    reference = _normalize_image(reference)
    registered = _normalize_image(registered)

    planes: Sequence[tuple[str, int]] = (
        ("sagittal", 0),
        ("coronal", 1),
        ("axial", 2),
    )
    slices: list[tuple[str, int, int]] = []
    support = np.maximum(reference, registered)
    for plane_name, axis in planes:
        for idx in _select_slice_indices(support, axis):
            slices.append((plane_name, axis, idx))

    fig, axes = plt.subplots(3, 3, figsize=(9, 9))
    fig.patch.set_facecolor("white")
    if title:
        fig.suptitle(title, fontsize=12)

    for ax, (plane_name, axis, idx) in zip(axes.flat, slices, strict=False):
        ref_slice = _extract_plane(reference, axis, idx)
        reg_slice = _extract_plane(registered, axis, idx)
        ax.imshow(
            _checkerboard_slice(ref_slice, reg_slice),
            cmap="gray",
            interpolation="nearest",
        )
        ax.set_title(f"{plane_name} {idx}", fontsize=9)
        ax.axis("off")

    for ax in axes.flat[len(slices) :]:
        ax.axis("off")

    output_path = Path(output_png)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def render_label_overlay_png(
    anatomical_path: str | Path,
    labels_path: str | Path,
    output_png: str | Path,
    *,
    title: str | None = None,
) -> str:
    """Render a tri-planar label overlay for segmentation QC."""

    anatomical, labels = _match_shapes(
        _load_volume(anatomical_path),
        _load_volume(labels_path),
    )
    anatomical = _normalize_image(anatomical)
    labels = np.asarray(labels)

    planes: Sequence[tuple[str, int]] = (
        ("sagittal", 0),
        ("coronal", 1),
        ("axial", 2),
    )
    slices: list[tuple[str, int, int]] = []
    support = (labels > 0).astype(np.uint8)
    for plane_name, axis in planes:
        for idx in _select_slice_indices(support, axis):
            slices.append((plane_name, axis, idx))

    fig, axes = plt.subplots(3, 3, figsize=(9, 9))
    fig.patch.set_facecolor("white")
    if title:
        fig.suptitle(title, fontsize=12)

    for ax, (plane_name, axis, idx) in zip(axes.flat, slices, strict=False):
        base_slice = _extract_plane(anatomical, axis, idx)
        label_slice = _extract_plane(labels, axis, idx)
        alpha = np.where(label_slice > 0, 0.35, 0.0)
        ax.imshow(base_slice, cmap="gray", interpolation="nearest")
        ax.imshow(
            label_slice,
            cmap="tab20",
            interpolation="nearest",
            alpha=alpha,
            vmin=0,
            vmax=max(1, int(np.max(labels))),
        )
        ax.set_title(f"{plane_name} {idx}", fontsize=9)
        ax.axis("off")

    for ax in axes.flat[len(slices) :]:
        ax.axis("off")

    output_path = Path(output_png)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


__all__ = [
    "render_label_overlay_png",
    "render_mask_overlay_png",
    "render_registration_checkerboard_png",
]
