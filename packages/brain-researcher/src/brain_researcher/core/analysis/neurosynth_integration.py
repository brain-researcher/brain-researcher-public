"""Neurosynth integration using nimare dataset."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_MNI_RESOLUTION_MM = 2


def _safe_slug(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text.strip())
    cleaned = "_".join(filter(None, cleaned.split("_")))
    return cleaned or "term"


def _build_activation_map_from_coordinates(
    coordinates: list[tuple[float, float, float]],
    *,
    radius_mm: float = 6.0,
    max_coordinates: int = 5000,
    threshold_count: float = 3.0,
):
    """Build a lightweight activation map by rasterizing coordinate spheres.

    This intentionally avoids NiMARE kernel transformers (which can be
    memory-intensive) while still producing a real, coordinate-derived map in
    MNI152 space.
    """
    import nibabel as nib
    from nibabel.affines import apply_affine
    from nilearn.datasets import load_mni152_template

    template = load_mni152_template(resolution=_DEFAULT_MNI_RESOLUTION_MM)
    affine = template.affine
    inv_affine = np.linalg.inv(affine)

    data = np.zeros(template.shape, dtype=np.float32)

    voxel_size = float(abs(affine[0, 0])) or float(_DEFAULT_MNI_RESOLUTION_MM)
    radius_vox = int(np.ceil(float(radius_mm) / voxel_size))
    grid = np.mgrid[
        -radius_vox : radius_vox + 1,
        -radius_vox : radius_vox + 1,
        -radius_vox : radius_vox + 1,
    ].reshape(3, -1)
    offsets = grid.T.astype(int)
    dist2_mm = (offsets.astype(float) * voxel_size) ** 2
    offsets = offsets[dist2_mm.sum(axis=1) <= float(radius_mm) ** 2]

    for x, y, z in coordinates[: int(max_coordinates)]:
        ijk = np.round(apply_affine(inv_affine, [x, y, z])).astype(int)
        for dx, dy, dz in offsets:
            ii = int(ijk[0] + dx)
            jj = int(ijk[1] + dy)
            kk = int(ijk[2] + dz)
            if 0 <= ii < data.shape[0] and 0 <= jj < data.shape[1] and 0 <= kk < data.shape[2]:
                data[ii, jj, kk] += 1.0

    data[data < float(threshold_count)] = 0.0

    header = template.header.copy()
    header.set_data_dtype(np.float32)
    img = nib.Nifti1Image(data, affine, header)
    img.update_header()
    return img


def _get_dataset_path() -> str:
    """Get the Neurosynth dataset path."""
    env_path = os.getenv("NEUROSYNTH_DATASET_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Prefer the repository-level data directory, but keep legacy src/data
    # probing for compatibility with older layouts.
    module_path = Path(__file__).resolve()
    candidate_base_dirs = [
        module_path.parents[4] / "data" / "neurosynth_nimare",  # <repo>/data/...
        module_path.parents[3] / "data" / "neurosynth_nimare",  # <repo>/src/data/...
    ]

    for base_dir in candidate_base_dirs:
        pkl_gz_path = base_dir / "neurosynth_dataset_v7.pkl.gz"
        pkl_path = base_dir / "neurosynth_dataset_v7.pkl"
        if pkl_gz_path.exists():
            return str(pkl_gz_path)
        if pkl_path.exists():
            return str(pkl_path)

    # Keep deterministic error messaging anchored to the preferred location.
    return str(candidate_base_dirs[0] / "neurosynth_dataset_v7.pkl.gz")


def _load_dataset():
    """Load the Neurosynth NiMARE dataset."""
    try:
        from nimare import dataset as nimare_dataset
    except ImportError:
        raise ImportError("nimare is not installed. Please run: pip install nimare")

    dataset_path = _get_dataset_path()

    if not os.path.exists(dataset_path):
        raise FileNotFoundError(
            f"Neurosynth dataset not found at {dataset_path}\n"
            f"Please download the dataset or set NEUROSYNTH_DATASET_PATH environment variable"
        )

    logger.info(f"Loading Neurosynth dataset from {dataset_path}")
    try:
        return nimare_dataset.Dataset.load(dataset_path)
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        raise


def get_neurosynth_mapping(keyword: str, threshold: float = 3.0) -> dict[str, Any]:
    """
    Perform Neurosynth meta-analysis for a given keyword.

    Args:
        keyword: Term to search for (e.g., 'fear', 'memory', 'reward')
        threshold: Z-score threshold for significant activation

    Returns:
        Dictionary with activation maps, coordinates, studies
    """
    try:
        # Load dataset
        dataset = _load_dataset()

        # Get vocabulary terms
        if not hasattr(dataset, 'annotations') or dataset.annotations is None:
            return {
                "keyword": keyword,
                "error": "Dataset has no annotations",
                "activation_maps": [],
                "studies": [],
                "coordinates": [],
                "scores": [],
            }

        # Search for term in vocabulary
        vocab = dataset.annotations.columns.tolist()

        # Find matching term (case-insensitive)
        matching_terms = [v for v in vocab if keyword.lower() in v.lower()]

        if not matching_terms:
            # Try fuzzy match
            import difflib
            close_matches = difflib.get_close_matches(keyword, vocab, n=1, cutoff=0.6)
            if close_matches:
                matching_terms = close_matches
            else:
                return {
                    "keyword": keyword,
                    "error": f"Term '{keyword}' not found in vocabulary. Closest matches not found.",
                    "activation_maps": [],
                    "studies": [],
                    "coordinates": [],
                    "scores": [],
                }

        # Use first matching term
        term = matching_terms[0]
        logger.info(f"Using term '{term}' for keyword '{keyword}'")

        # Get weights for this term
        weights = dataset.annotations[term].values

        # Lightweight meta-analysis: select top studies and rasterize coordinates.
        threshold_idx = float(np.percentile(np.abs(weights), 95))  # Top 5%
        selected_mask = weights >= threshold_idx
        selected_ids = dataset.ids[selected_mask]
        selected_scores = weights[selected_mask]

        if len(selected_ids) == 0:
            return {
                "keyword": keyword,
                "term_used": term,
                "error": f"No studies found with significant weights for '{term}'",
                "activation_maps": [],
                "studies": [],
                "coordinates": [],
                "scores": [],
            }

        max_studies = int(os.getenv("NEUROSYNTH_MAX_STUDIES", "500"))
        if len(selected_ids) > max_studies:
            order = np.argsort(selected_scores)[::-1][:max_studies]
            selected_ids = selected_ids[order]
            selected_scores = selected_scores[order]

        dataset_filtered = dataset.slice(selected_ids)
        coordinates_df = getattr(dataset_filtered, "coordinates", None)
        if coordinates_df is None or len(coordinates_df) == 0:
            return {
                "keyword": keyword,
                "term_used": term,
                "activation_maps": [],
                "studies": selected_ids.tolist(),
                "coordinates": [],
                "scores": selected_scores.tolist(),
                "n_studies": int(len(selected_ids)),
                "n_coords": 0,
                "error": "No coordinates available for selected studies",
            }

        coords: list[tuple[float, float, float]] = []
        for colset in (("x", "y", "z"), ("X", "Y", "Z")):
            if all(c in coordinates_df.columns for c in colset):
                coords = [
                    (float(row[colset[0]]), float(row[colset[1]]), float(row[colset[2]]))
                    for _, row in coordinates_df[list(colset)].dropna().iterrows()
                ]
                break

        if not coords:
            return {
                "keyword": keyword,
                "term_used": term,
                "activation_maps": [],
                "studies": selected_ids.tolist(),
                "coordinates": [],
                "scores": selected_scores.tolist(),
                "n_studies": int(len(selected_ids)),
                "n_coords": 0,
                "error": "Coordinates table missing x/y/z columns",
            }

        max_coords = int(os.getenv("NEUROSYNTH_MAX_COORDINATES", "5000"))
        radius_mm = float(os.getenv("NEUROSYNTH_SPHERE_RADIUS_MM", "6"))
        img = _build_activation_map_from_coordinates(
            coords,
            radius_mm=radius_mm,
            max_coordinates=max_coords,
            threshold_count=float(threshold),
        )

        coord_records: list[dict[str, float]] = [
            {"x": x, "y": y, "z": z} for x, y, z in coords[:max_coords]
        ]

        return {
            "keyword": keyword,
            "term_used": term,
            "activation_maps": [img],
            "studies": selected_ids.tolist(),
            "coordinates": coord_records,
            "scores": selected_scores.tolist(),
            "n_studies": int(len(selected_ids)),
            "n_coords": int(min(len(coords), max_coords)),
            "threshold_count": float(threshold),
        }

    except FileNotFoundError as e:
        return {
            "keyword": keyword,
            "error": str(e),
            "activation_maps": [],
            "studies": [],
            "coordinates": [],
            "scores": [],
        }
    except ImportError as e:
        return {
            "keyword": keyword,
            "error": str(e),
            "activation_maps": [],
            "studies": [],
            "coordinates": [],
            "scores": [],
        }
    except Exception as e:
        logger.error(f"Unexpected error in get_neurosynth_mapping: {e}")
        return {
            "keyword": keyword,
            "error": f"Unexpected error: {e}",
            "activation_maps": [],
            "studies": [],
            "coordinates": [],
            "scores": [],
        }


def visualize_activation_maps(activation_maps: list, threshold: float = 3.0) -> dict[str, Any]:
    """Create visualization of activation maps."""
    import nibabel as nib
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        output_dir = os.getenv("NEUROKG_OUTPUT_DIR", "/tmp/neurokg")
        os.makedirs(output_dir, exist_ok=True)

        plots = []
        for i, img in enumerate(activation_maps):
            fig, ax = plt.subplots(figsize=(10, 8))
            data = img.get_fdata()

            # Get middle slice
            mid_slice = data.shape[2] // 2
            ax.imshow(data[:, :, mid_slice].T, cmap='hot', origin='lower')
            ax.set_title(f"Activation Map {i+1}")
            plt.colorbar(ax.images[0], ax=ax)

            plot_path = os.path.join(output_dir, f"activation_map_{i+1}.png")
            plt.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

            plots.append(plot_path)

        return {"plots": plots, "n_plots": len(plots)}

    except Exception as e:
        logger.error(f"Visualization failed: {e}")
        return {"error": str(e)}


def calculate_relevance_scores(term: str, terms: list, scores: list) -> dict[str, float]:
    """Calculate relevance scores for term matching."""
    import difflib

    relevance = {}
    for t, s in zip(terms, scores):
        # Use SequenceMatcher for similarity
        similarity = difflib.SequenceMatcher(None, term.lower(), t.lower()).ratio()
        relevance[t] = similarity * s

    return dict(sorted(relevance.items(), key=lambda x: x[1], reverse=True))
