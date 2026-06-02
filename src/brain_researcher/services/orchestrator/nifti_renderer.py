"""
NIfTI Renderer with Disk Caching - On-demand brain map visualization

Addresses Codex review concern: "Without on-demand rendering + caching,
first loads will timeout and repeated views waste CPU."

This module provides efficient NIfTI visualization with:
- On-demand rendering (only when requested)
- Disk caching (sub-50ms on cache hits)
- Multiple view modes (axial, sagittal, coronal)
- Configurable thresholds and slices
"""

import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from brain_researcher.config.paths import get_outputs_root, get_repo_root

logger = logging.getLogger(__name__)

# Cache directory structure:
# outputs/orchestrator/cache/rendered/<demo_id>/<artifact_id>/<view>-<slice>-<threshold>.png
RENDER_CACHE_ENV = "BR_ORCHESTRATOR_RENDER_CACHE_ROOT"
LEGACY_CACHE_ROOT = (
    get_repo_root()
    / "src"
    / "brain_researcher"
    / "services"
    / "orchestrator"
    / "cache"
    / "rendered"
)

ViewMode = Literal["axial", "sagittal", "coronal"]


@lru_cache(maxsize=1)
def get_cache_root() -> Path:
    """Resolve the render-cache root outside the source tree."""

    configured = os.getenv(RENDER_CACHE_ENV)
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = get_repo_root() / candidate
        return candidate.resolve(strict=False)
    return (get_outputs_root() / "orchestrator" / "cache" / "rendered").resolve(
        strict=False
    )


def clear_cache_root_cache() -> None:
    """Reset cached render-cache root resolution."""

    get_cache_root.cache_clear()


def get_cache_path(
    demo_id: str,
    artifact_id: str,
    view: ViewMode,
    slice_idx: Optional[int],
    threshold: float,
) -> Path:
    """
    Generate cache file path for a rendered NIfTI image

    Args:
        demo_id: Demo identifier
        artifact_id: Artifact identifier (relative path)
        view: View mode (axial/sagittal/coronal)
        slice_idx: Slice index (None for auto)
        threshold: Statistical threshold

    Returns:
        Path to cache file
    """
    # Create safe filename from artifact_id
    artifact_hash = hashlib.md5(artifact_id.encode()).hexdigest()[:8]

    # Build cache key
    slice_str = str(slice_idx) if slice_idx is not None else "auto"
    cache_key = f"{view}-{slice_str}-{threshold:.2f}.png"

    return get_cache_root() / demo_id / artifact_hash / cache_key


def render_nifti(
    nifti_path: Path,
    output_path: Path,
    view: ViewMode = "axial",
    slice_idx: Optional[int] = None,
    threshold: Optional[float] = 2.3,
    dpi: int = 120,
) -> Path:
    """
    Render NIfTI statistical map to PNG with caching

    Args:
        nifti_path: Path to NIfTI file (can be symlink)
        output_path: Path to save PNG
        view: View mode (axial/sagittal/coronal)
        slice_idx: Specific slice index (None for auto-selection)
        threshold: Statistical threshold for display
        dpi: Output resolution

    Returns:
        Path to rendered PNG file
    """
    # Check cache first
    if output_path.exists():
        logger.debug(f"Cache hit: {output_path}")
        return output_path

    logger.info(f"Rendering {nifti_path} -> {output_path}")

    # Create output directory
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Import nilearn here (lazy import to reduce startup time)
        import nibabel as nib
        from nilearn import plotting

        # Load NIfTI image (works with symlinks)
        img = nib.load(str(nifti_path))

        # Map view mode to nilearn display_mode
        display_mode_map = {"axial": "z", "sagittal": "x", "coronal": "y"}
        display_mode = display_mode_map[view]

        # Determine cut coordinates
        cut_coords = None
        if slice_idx is not None:
            # Convert slice index to mm coordinates
            vox_sizes = img.header.get_zooms()
            axis_map = {"x": 0, "y": 1, "z": 2}
            axis_idx = axis_map[display_mode]
            cut_coords = [slice_idx * vox_sizes[axis_idx]]

        # Render statistical map
        display = plotting.plot_stat_map(
            img,
            display_mode=display_mode,
            threshold=threshold,
            cut_coords=cut_coords,
            annotate=False,
            colorbar=True,
            cmap="cold_hot",
        )

        # Save to file
        display.savefig(str(output_path), dpi=dpi, bbox_inches="tight", pad_inches=0.1)
        display.close()

        logger.info(f"Rendered successfully: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Failed to render {nifti_path}: {e}")
        raise


def extract_peaks(
    nifti_path: Path,
    threshold: float = 2.3,
    min_distance: float = 8.0,
    max_peaks: int = 10,
) -> list[dict]:
    """Extract peak coordinates from a statistical map.

    This implementation avoids the heavy ``nilearn.reporting.get_clusters_table``
    helper which occasionally returns malformed cluster sizes ("" values) and can
    take tens of seconds on large maps. We instead compute local maxima directly
    using ``scipy.ndimage`` which is deterministic, fast, and gives us explicit
    control over tolerance handling.
    """

    try:
        import nibabel as nib
        import numpy as np
        from scipy import ndimage

        img = nib.load(str(nifti_path))
        data = img.get_fdata(dtype=float)

        if data is None:
            return []

        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

        # Support negative thresholds by flipping the sign of the data we
        # analyse so that we always search for maxima.
        search_data = data.copy()
        search_threshold = threshold
        invert = threshold < 0
        if invert:
            search_data = -search_data
            search_threshold = abs(threshold)

        mask = search_data >= search_threshold
        if not np.any(mask):
            return []

        # Identify local maxima within the threshold mask.
        # ``size=3`` corresponds to a 3x3x3 neighbourhood which is a reasonable
        # default for voxel data.
        local_max = ndimage.maximum_filter(search_data, size=3)
        peak_mask = mask & (search_data == local_max)
        peak_indices = np.column_stack(np.nonzero(peak_mask))

        if peak_indices.size == 0:
            return []

        # Sort peaks by intensity (descending) and enforce minimum distance in mm.
        peak_values = search_data[tuple(peak_indices.T)]
        order = np.argsort(peak_values)[::-1]

        # Pre-compute cluster labels for size estimation (volume in mm^3).
        labeled, _ = ndimage.label(mask)
        label_sizes = np.bincount(labeled.ravel())
        voxel_volume = float(abs(np.linalg.det(img.affine[:3, :3]))) or 1.0
        peaks: list[dict] = []
        selected_mm = []

        for idx in order:
            voxel_idx = peak_indices[idx]
            mm_coord = nib.affines.apply_affine(img.affine, voxel_idx)

            # Enforce minimum distance constraint (Euclidean, in mm).
            if selected_mm:
                dists = [np.linalg.norm(mm_coord - prev) for prev in selected_mm]
                if dists and min(dists) < min_distance:
                    continue

            label_val = labeled[tuple(voxel_idx)]
            if 0 < label_val < len(label_sizes):
                cluster_size_mm3 = label_sizes[label_val] * voxel_volume
            else:
                cluster_size_mm3 = voxel_volume
            cluster_size = int(round(cluster_size_mm3))

            raw_value = data[tuple(voxel_idx)]
            if invert:
                raw_value = -raw_value

            peaks.append(
                {
                    "x": float(mm_coord[0]),
                    "y": float(mm_coord[1]),
                    "z": float(mm_coord[2]),
                    "value": float(raw_value),
                    "cluster_size": int(cluster_size),
                }
            )
            selected_mm.append(mm_coord)

            if len(peaks) >= max_peaks:
                break

        return peaks

    except Exception as exc:
        logger.warning(f"Failed to extract peaks from {nifti_path}: {exc}")
        return []


def clear_cache(demo_id: Optional[str] = None):
    """
    Clear rendering cache

    Args:
        demo_id: If provided, only clear cache for this demo.
                 If None, clear entire cache.
    """
    if demo_id:
        cache_dir = get_cache_root() / demo_id
        if cache_dir.exists():
            import shutil

            shutil.rmtree(cache_dir)
            logger.info(f"Cleared cache for demo: {demo_id}")
    else:
        cache_root = get_cache_root()
        if cache_root.exists():
            import shutil

            shutil.rmtree(cache_root)
            logger.info("Cleared entire rendering cache")
