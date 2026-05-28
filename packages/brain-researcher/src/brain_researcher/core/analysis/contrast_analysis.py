"""Minimal contrast analysis utilities for canonical analysis imports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from scipy import ndimage


class ContrastAnalyzer:
    """Analyze z-maps and emit simple reports and visualization assets."""

    def __init__(self, output_dir: str | Path = "reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_significant_clusters(
        self,
        z_map_path: str | Path,
        threshold: float = 3.0,
        min_size: int = 10,
    ) -> list[dict[str, Any]]:
        """Return connected suprathreshold clusters from a z-map."""
        img = nib.load(str(z_map_path))
        data = np.asarray(img.get_fdata())
        mask = np.abs(data) >= float(threshold)
        if not np.any(mask):
            return []

        structure = np.ones((3, 3, 3), dtype=int)
        labeled, n_labels = ndimage.label(mask, structure=structure)
        clusters: list[dict[str, Any]] = []

        for label_idx in range(1, n_labels + 1):
            cluster_mask = labeled == label_idx
            size = int(cluster_mask.sum())
            if size < int(min_size):
                continue

            cluster_values = data[cluster_mask]
            flat_cluster = np.argwhere(cluster_mask)
            peak_offset = int(np.argmax(np.abs(cluster_values)))
            peak_coords = flat_cluster[peak_offset].tolist()
            center = ndimage.center_of_mass(cluster_mask.astype(float))

            clusters.append(
                {
                    "index": len(clusters) + 1,
                    "size": size,
                    "peak_value": float(cluster_values[peak_offset]),
                    "peak_coords": [int(v) for v in peak_coords],
                    "center_of_mass": [float(v) for v in center],
                }
            )

        return sorted(clusters, key=lambda item: abs(item["peak_value"]), reverse=True)

    def _render_plot(
        self, data: np.ndarray, contrast_name: str, stem: str, slices: tuple[int, int]
    ) -> str:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        axes[0].imshow(data[:, :, slices[0]].T, cmap="hot", origin="lower")
        axes[0].set_title(f"{contrast_name} axial")
        axes[1].imshow(data[:, slices[1], :].T, cmap="hot", origin="lower")
        axes[1].set_title(f"{contrast_name} coronal")
        for ax in axes:
            ax.set_axis_off()

        path = self.output_dir / f"{contrast_name}_{stem}.png"
        fig.tight_layout()
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    def analyze_contrast(
        self,
        z_map: str | Path,
        contrast_name: str,
        task_description: str | None = None,
        constructs: list[dict[str, Any]] | None = None,
        threshold: float = 3.0,
        min_size: int = 5,
    ) -> dict[str, Any]:
        """Analyze a single contrast and save a lightweight report."""
        img = nib.load(str(z_map))
        data = np.asarray(img.get_fdata())
        clusters = self._get_significant_clusters(
            z_map, threshold=threshold, min_size=min_size
        )

        construct_count = sum(len(item.get("constructs", [])) for item in constructs or [])
        utility_score = float(
            min(
                1.0,
                0.25
                + 0.1 * construct_count
                + 0.05 * len(clusters)
                + (0.05 if task_description else 0.0),
            )
        )

        mid_z = data.shape[2] // 2
        mid_y = data.shape[1] // 2
        glass_path = self._render_plot(data, contrast_name, "glass", (mid_z, mid_y))
        slices_path = self._render_plot(data, contrast_name, "slices", (mid_z, mid_y))

        report = {
            "contrast_name": contrast_name,
            "task_description": task_description,
            "utility_score": utility_score,
            "clusters": clusters,
            "plots": {
                "glass": glass_path,
                "slices": slices_path,
            },
        }
        report_path = self.output_dir / f"{contrast_name}_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    def analyze_dataset(self, dataset_path: str | Path) -> dict[str, dict[str, Any]]:
        """Analyze every contrast directory under a dataset root."""
        dataset_root = Path(dataset_path)
        results: dict[str, dict[str, Any]] = {}
        for contrast_dir in sorted(path for path in dataset_root.iterdir() if path.is_dir()):
            z_map = contrast_dir / "z_map.nii.gz"
            if not z_map.exists():
                continue

            metadata_path = contrast_dir / "metadata.json"
            metadata: dict[str, Any] = {}
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            contrast_name = metadata.get("contrast_name") or contrast_dir.name
            results[contrast_dir.name] = self.analyze_contrast(
                z_map=z_map,
                contrast_name=contrast_name,
                task_description=metadata.get("task_description"),
                constructs=metadata.get("constructs"),
            )

        summary_path = self.output_dir / "analysis_summary.json"
        summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        return results
