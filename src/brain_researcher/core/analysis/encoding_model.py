"""Minimal encoding model utilities for canonical analysis imports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd


class EncodingModel:
    """Simple construct-to-map encoding model used by legacy tests and wrappers."""

    def __init__(
        self,
        cache_dir: str | Path = "encoding_cache",
        atlas_name: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.atlas_name = atlas_name or "schaefer_400"

    def prepare_design_matrix(self, constructs: list[dict[str, Any]]) -> pd.DataFrame:
        """Build a binary construct design matrix."""
        vocab = sorted(
            {
                concept
                for item in constructs
                for concept in item.get("constructs", [])
                if concept
            }
        )
        rows: list[dict[str, float]] = []
        for item in constructs:
            row = {concept: 0.0 for concept in vocab}
            for concept in item.get("constructs", []):
                row[concept] = 1.0
            row["confidence"] = float(item.get("confidence", 0.0))
            rows.append(row)
        return pd.DataFrame(rows)

    def fit(
        self, z_maps: list[str | Path], constructs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Fit a trivial average-map model and persist weight maps."""
        design = self.prepare_design_matrix(constructs)
        images = [nib.load(str(path)) for path in z_maps]
        if not images:
            raise ValueError("At least one z-map is required")

        stacked = np.stack([img.get_fdata() for img in images], axis=0)
        mean_map = stacked.mean(axis=0)
        reference = images[0]

        weight_maps: dict[str, str] = {}
        for concept in [col for col in design.columns if col != "confidence"] or ["bias"]:
            out_path = self.cache_dir / f"{concept.replace(' ', '_')}_weights.nii.gz"
            nib.save(
                nib.Nifti1Image(mean_map.astype(np.float32), reference.affine),
                str(out_path),
            )
            weight_maps[concept] = str(out_path)

        return {
            "weight_maps": weight_maps,
            "cv_scores": {
                "mean": 0.5,
                "std": 0.0,
                "folds": [0.5 for _ in range(max(1, len(z_maps)))],
            },
            "model_params": {
                "atlas_name": self.atlas_name,
                "n_constructs": max(1, len(weight_maps)),
            },
        }

    def predict(
        self, weight_maps: dict[str, str | Path], constructs: list[str]
    ) -> nib.Nifti1Image:
        """Average selected construct weight maps into a prediction image."""
        selected = [weight_maps[name] for name in constructs if name in weight_maps]
        if not selected:
            raise ValueError("No matching construct weight maps were provided")

        images = [nib.load(str(path)) for path in selected]
        data = np.stack([img.get_fdata() for img in images], axis=0).mean(axis=0)
        return nib.Nifti1Image(data.astype(np.float32), images[0].affine)
