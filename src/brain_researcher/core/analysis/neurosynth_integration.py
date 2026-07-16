"""Neurosynth integration using nimare dataset."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_DATASET_PICKLE,
    DEFAULT_SOURCE_DIR,
    NeurosynthSourceError,
    verify_converted_dataset,
)

logger = logging.getLogger(__name__)

_DEFAULT_MNI_RESOLUTION_MM = 2
_MAP_SEMANTICS = "descriptive_coordinate_density"
_MAP_VALUE_SEMANTICS = "overlapping_coordinate_sphere_hit_count"
_STUDY_SELECTION_RULE = (
    "highest_positive_tfidf_weights_up_to_5_percent_of_dataset"
)


def _safe_slug(text: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text.strip()
    )
    cleaned = "_".join(filter(None, cleaned.split("_")))
    return cleaned or "term"


def _build_coordinate_density_map(
    coordinates: list[tuple[float, float, float]],
    *,
    radius_mm: float = 6.0,
    max_coordinates: int = 5000,
    threshold_count: float = 3.0,
):
    """Build a descriptive coordinate-density map from overlapping spheres.

    This intentionally avoids NiMARE kernel transformers (which can be
    memory-intensive). Voxel values are sphere hit counts in MNI152 space, not
    z-scores, effect estimates, probabilities, or corrected statistics.
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
            if (
                0 <= ii < data.shape[0]
                and 0 <= jj < data.shape[1]
                and 0 <= kk < data.shape[2]
            ):
                data[ii, jj, kk] += 1.0

    data[data < float(threshold_count)] = 0.0

    header = template.header.copy()
    header.set_data_dtype(np.float32)
    img = nib.Nifti1Image(data, affine, header)
    img.update_header()
    return img


def _get_dataset_path() -> str:
    """Get the explicit override or canonical Neurosynth dataset pickle path."""
    env_path = os.getenv("NEUROSYNTH_DATASET_PATH")
    if env_path:
        return str(Path(env_path).expanduser().resolve())
    return str(DEFAULT_DATASET_PICKLE)


def _source_dir_for_dataset() -> str:
    source_override = os.getenv("NEUROSYNTH_SOURCE_DIR")
    if os.getenv("NEUROSYNTH_DATASET_PATH") and not source_override:
        raise NeurosynthSourceError(
            "NEUROSYNTH_DATASET_PATH requires NEUROSYNTH_SOURCE_DIR so the "
            "dataset can be associated with a verified source manifest"
        )
    source_dir = source_override or str(DEFAULT_SOURCE_DIR)
    return source_dir


def _load_dataset():
    """Load the Neurosynth NiMARE dataset."""
    dataset_path = _get_dataset_path()
    verify_converted_dataset(dataset_path, _source_dir_for_dataset())

    try:
        from nimare import dataset as nimare_dataset
    except ImportError as exc:
        raise ImportError(
            "nimare is not installed. Please run: pip install nimare"
        ) from exc

    if not os.path.exists(dataset_path):
        raise FileNotFoundError(
            f"Neurosynth dataset not found at {dataset_path}\n"
            "Run python scripts/data/download_neurosynth_data.py and "
            "python scripts/data/convert_neurosynth.py. An explicit "
            "NEUROSYNTH_DATASET_PATH must be paired with NEUROSYNTH_SOURCE_DIR."
        )

    logger.info(f"Loading Neurosynth dataset from {dataset_path}")
    try:
        return nimare_dataset.Dataset.load(dataset_path)
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        raise


def get_neurosynth_mapping(keyword: str, threshold: float = 3.0) -> dict[str, Any]:
    """Build a descriptive Neurosynth coordinate-density map for a term.

    This is not a NiMARE meta-analysis or an inferential statistical test. It
    selects the highest positive TF-IDF study weights (up to 5% of the dataset),
    rasterizes their reported coordinates as spheres, and stores the number of
    overlapping spheres in each voxel.

    Args:
        keyword: Term to search for (e.g., 'fear', 'memory', 'reward')
        threshold: Minimum coordinate-sphere overlap count retained in the map

    Returns:
        Dictionary with descriptive density maps, coordinates, and selected studies
    """
    try:
        # Load dataset
        dataset = _load_dataset()

        # Get vocabulary terms
        if not hasattr(dataset, "annotations") or dataset.annotations is None:
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

        # Select an exact, deterministic upper bound rather than a percentile
        # threshold that can accidentally include every zero-weight study.
        weights = np.asarray(weights, dtype=float)
        candidate_indices = np.flatnonzero(np.isfinite(weights) & (weights > 0))
        selection_limit = max(1, int(np.ceil(len(weights) * 0.05)))
        ranked_candidates = candidate_indices[
            np.argsort(-weights[candidate_indices], kind="stable")
        ]
        selected_indices = ranked_candidates[:selection_limit]
        selected_ids = np.asarray(dataset.ids)[selected_indices]
        selected_scores = weights[selected_indices]

        if len(selected_ids) == 0:
            return {
                "keyword": keyword,
                "term_used": term,
                "error": f"No studies have positive TF-IDF weights for '{term}'",
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
                    (
                        float(row[colset[0]]),
                        float(row[colset[1]]),
                        float(row[colset[2]]),
                    )
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
        img = _build_coordinate_density_map(
            coords,
            radius_mm=radius_mm,
            max_coordinates=max_coords,
            threshold_count=float(threshold),
        )

        coord_records: list[dict[str, float]] = [
            {"x": x, "y": y, "z": z} for x, y, z in coords[:max_coords]
        ]

        maps = [img]
        return {
            "keyword": keyword,
            "term_used": term,
            "coordinate_density_maps": maps,
            # Compatibility alias for existing internal consumers. The semantics
            # fields below are authoritative and explicitly non-inferential.
            "activation_maps": maps,
            "studies": selected_ids.tolist(),
            "coordinates": coord_records,
            "scores": selected_scores.tolist(),
            "n_studies": int(len(selected_ids)),
            "n_coords": int(min(len(coords), max_coords)),
            "threshold_count": float(threshold),
            "analysis_semantics": _MAP_SEMANTICS,
            "map_value_semantics": _MAP_VALUE_SEMANTICS,
            "inferential_statistics": False,
            "multiple_comparisons_correction": None,
            "study_selection": {
                "rule": _STUDY_SELECTION_RULE,
                "positive_weight_candidates": int(len(candidate_indices)),
                "dataset_studies": int(len(weights)),
                "selected_studies": int(len(selected_ids)),
                "maximum_fraction": 0.05,
                "maximum_studies": max_studies,
            },
            "compatibility_fields": {
                "activation_maps": "alias_of_coordinate_density_maps"
            },
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


def visualize_activation_maps(
    activation_maps: list,
    threshold: float = 3.0,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Visualize supplied maps without assigning inferential semantics."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        if float(threshold) < 0:
            raise ValueError("display threshold must be non-negative")
        resolved_output_dir = Path(
            output_dir or os.getenv("BR_KG_OUTPUT_DIR", "/tmp/br_kg")
        ).expanduser()
        resolved_output_dir.mkdir(parents=True, exist_ok=True)

        plots = []
        for i, img in enumerate(activation_maps):
            fig, ax = plt.subplots(figsize=(10, 8))
            data = img.get_fdata()
            display_data = np.array(data, dtype=float, copy=True)
            display_data[np.abs(display_data) < float(threshold)] = np.nan

            # Get middle slice
            mid_slice = display_data.shape[2] // 2
            ax.imshow(display_data[:, :, mid_slice].T, cmap="hot", origin="lower")
            ax.set_title(f"Neurosynth map values {i+1}")
            plt.colorbar(ax.images[0], ax=ax)

            plot_path = resolved_output_dir / f"neurosynth_map_{i+1}.png"
            plt.savefig(plot_path, dpi=150, bbox_inches="tight")
            plt.close(fig)

            plots.append(str(plot_path))

        return {
            "plots": plots,
            "n_plots": len(plots),
            "display_threshold": float(threshold),
            "threshold_semantics": "absolute_display_threshold_in_map_native_units",
            "inferential_statistics": False,
        }

    except Exception as e:
        logger.error(f"Visualization failed: {e}")
        return {"error": str(e)}


def calculate_relevance_scores(
    term: str, terms: list, scores: list
) -> dict[str, float]:
    """Calculate relevance scores for term matching."""
    import difflib

    relevance = {}
    for t, s in zip(terms, scores, strict=False):
        # Use SequenceMatcher for similarity
        similarity = difflib.SequenceMatcher(None, term.lower(), t.lower()).ratio()
        relevance[t] = similarity * s

    return dict(sorted(relevance.items(), key=lambda x: x[1], reverse=True))
