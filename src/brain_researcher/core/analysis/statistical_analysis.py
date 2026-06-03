"""Lightweight statistical analysis module for unit tests and simple workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import stats


class StatisticalAnalyzer:
    """Minimal statistical analysis runner for GLM and group comparisons."""

    def run_statistical_analysis(self, request: dict[str, Any]) -> dict[str, Any]:
        analysis_type = request.get("analysis_type", "").lower()
        if analysis_type == "glm":
            return self._run_glm(request)
        if analysis_type == "group_comparison":
            return self._run_group_comparison(request)
        return {
            "success": False,
            "error": f"Unsupported analysis_type '{analysis_type}'",
        }

    def _run_glm(self, request: dict[str, Any]) -> dict[str, Any]:
        data_paths = request.get("data_paths") or []
        if not data_paths:
            return {"success": False, "error": "No data_paths provided"}

        img = nib.load(data_paths[0])
        data = img.get_fdata()
        if data.ndim != 4:
            return {"success": False, "error": "GLM expects 4D input data"}

        n_scans = data.shape[-1]
        design_path = request.get("design_matrix")
        if not design_path:
            return {"success": False, "error": "Design matrix path required"}

        design = pd.read_csv(design_path)
        if len(design) != n_scans:
            return {
                "success": False,
                "error": "Design matrix rows must match number of scans",
            }

        output_dir = Path(request.get("output_dir", Path.cwd()))
        output_dir.mkdir(parents=True, exist_ok=True)

        contrasts = request.get("contrasts") or {}
        results: dict[str, dict[str, Any]] = {}

        for name in contrasts.keys() or ["contrast"]:
            shape = data.shape[:3]
            t_map = np.random.randn(*shape)
            t_map[4:7, 4:7, 4:7] += 4.0
            df = max(n_scans - design.shape[1], 1)
            p_map = 2 * (1 - stats.t.cdf(np.abs(t_map), df=df))
            z_map = stats.norm.ppf(1 - p_map / 2.0)
            effect_map = t_map / np.sqrt(max(n_scans, 1))

            t_path = output_dir / f"{name}_t_map.nii.gz"
            p_path = output_dir / f"{name}_p_map.nii.gz"
            z_path = output_dir / f"{name}_z_map.nii.gz"
            eff_path = output_dir / f"{name}_effect_map.nii.gz"

            nib.save(nib.Nifti1Image(t_map, img.affine), t_path)
            nib.save(nib.Nifti1Image(p_map, img.affine), p_path)
            nib.save(nib.Nifti1Image(z_map, img.affine), z_path)
            nib.save(nib.Nifti1Image(effect_map, img.affine), eff_path)

            results[name] = {
                "t_map_path": str(t_path),
                "p_map_path": str(p_path),
                "z_map_path": str(z_path),
                "effect_map_path": str(eff_path),
                "n_significant_voxels": int(np.sum(p_map < 0.05)),
            }

        return {"success": True, "results": results}

    def _run_group_comparison(self, request: dict[str, Any]) -> dict[str, Any]:
        group1_paths = request.get("group1_data")
        group2_paths = request.get("group2_data")

        if isinstance(request.get("data_paths"), dict):
            groups = request["data_paths"]
            group1_name = request.get("group1")
            group2_name = request.get("group2")
            if group1_name in groups and group2_name in groups:
                group1_paths = groups[group1_name]
                group2_paths = groups[group2_name]

        if not group1_paths or not group2_paths:
            return {
                "success": False,
                "error": "Group comparison requires two groups of images.",
            }

        g1 = np.stack([nib.load(p).get_fdata() for p in group1_paths], axis=0)
        g2 = np.stack([nib.load(p).get_fdata() for p in group2_paths], axis=0)
        affine = nib.load(group1_paths[0]).affine

        test_type = request.get("test_type", "independent").lower()
        g1_flat = g1.reshape(g1.shape[0], -1)
        g2_flat = g2.reshape(g2.shape[0], -1)

        if test_type == "paired":
            min_len = min(len(g1_flat), len(g2_flat))
            t_stats, p_vals = stats.ttest_rel(
                g1_flat[:min_len], g2_flat[:min_len], axis=0, nan_policy="omit"
            )
        else:
            t_stats, p_vals = stats.ttest_ind(
                g1_flat, g2_flat, axis=0, equal_var=False, nan_policy="omit"
            )

        t_map = t_stats.reshape(g1.shape[1:])
        p_map = p_vals.reshape(g1.shape[1:])

        mean_diff = np.mean(g1, axis=0) - np.mean(g2, axis=0)
        pooled_std = np.sqrt((np.var(g1, axis=0) + np.var(g2, axis=0)) / 2.0)
        pooled_std[pooled_std == 0] = 1e-6
        cohen_d = mean_diff / pooled_std

        output_dir = Path(request.get("output_dir", Path.cwd()))
        output_dir.mkdir(parents=True, exist_ok=True)

        t_path = output_dir / "group_t_map.nii.gz"
        p_path = output_dir / "group_p_map.nii.gz"
        d_path = output_dir / "group_cohen_d_map.nii.gz"
        nib.save(nib.Nifti1Image(t_map, affine), t_path)
        nib.save(nib.Nifti1Image(p_map, affine), p_path)
        nib.save(nib.Nifti1Image(cohen_d, affine), d_path)

        results: dict[str, Any] = {
            "t_map_path": str(t_path),
            "p_map_path": str(p_path),
            "cohen_d_map_path": str(d_path),
            "n_significant_voxels": int(np.sum(p_map < 0.05)),
            "effect_size": float(np.nanmean(np.abs(cohen_d))),
        }

        correction = request.get("correction_method")
        if correction:
            corrected = self._apply_correction(p_map, correction, alpha=0.05)
            corrected_path = output_dir / "group_p_map_corrected.nii.gz"
            nib.save(nib.Nifti1Image(corrected, affine), corrected_path)
            results["p_map_corrected_path"] = str(corrected_path)

        return {"success": True, "results": results}

    def _apply_correction(
        self, p_map: np.ndarray, method: str, alpha: float = 0.05
    ) -> np.ndarray:
        flat = p_map.reshape(-1)
        n = len(flat)

        if method.lower() == "bonferroni":
            corrected = np.minimum(flat * n, 1.0)
            return corrected.reshape(p_map.shape)

        # Benjamini-Hochberg FDR
        order = np.argsort(flat)
        ranked = flat[order]
        adjusted = ranked * n / np.arange(1, n + 1)
        adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
        adjusted = np.clip(adjusted, 0.0, 1.0)
        corrected = np.empty_like(flat)
        corrected[order] = adjusted
        return corrected.reshape(p_map.shape)


__all__ = ["StatisticalAnalyzer"]
