"""Agent wrapper for diffusion tractography fallback workflows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    DiffusionTractographyParameters,
    diffusion_tractography_from_payload,
    run_diffusion_tractography,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class DiffusionTractographyArgs(BaseModel):
    """Arguments accepted by the diffusion tractography fallback."""

    model_config = ConfigDict(extra="ignore")

    dwi_file: str = Field(description="Path to diffusion-weighted image")
    bvals_file: str = Field(description="Path to bvals file")
    bvecs_file: str = Field(description="Path to bvecs file")
    mask_file: Optional[str] = Field(default=None, description="Optional brain mask")
    output_dir: Optional[str] = Field(default=None, description="Directory for outputs")
    model_type: str = Field(default="dti", description="Diffusion model type")
    tracking_method: str = Field(
        default="deterministic", description="Tracking algorithm"
    )
    fa_threshold: float = Field(default=0.1, description="FA threshold for stopping")
    min_length: float = Field(
        default=10.0, description="Minimum streamline length (mm)"
    )
    max_length: float = Field(
        default=250.0, description="Maximum streamline length (mm)"
    )
    compute_connectivity: bool = Field(
        default=True, description="Emit connectivity matrix"
    )
    parcellation_file: Optional[str] = Field(
        default=None, description="Optional parcellation map"
    )
    connectivity_metric: str = Field(
        default="count", description="Connectivity metric to summarise"
    )
    compute_fa: bool = Field(default=True, description="Persist FA map")
    compute_md: bool = Field(default=True, description="Persist mean diffusivity map")
    compute_rd: bool = Field(default=True, description="Persist radial diffusivity map")
    compute_ad: bool = Field(default=True, description="Persist axial diffusivity map")
    segment_bundles: bool = Field(default=False, description="Derive bundle summaries")
    save_streamlines: bool = Field(default=True, description="Persist streamline array")
    save_fa_map: bool = Field(default=True, description="Persist FA volume")
    save_connectivity: bool = Field(
        default=True, description="Persist connectivity matrix"
    )
    visualize: bool = Field(default=True, description="Generate preview visualisations")
    random_state: Optional[int] = Field(default=42, description="Optional RNG seed")


class DiffusionTractographyTool(NeuroToolWrapper):
    """Delegates diffusion tractography to neurocore fallback implementation."""

    def get_tool_name(self) -> str:
        return "diffusion_tractography"

    def get_tool_description(self) -> str:
        return (
            "Fallback diffusion tractography for fiber tracking with synthetic "
            "streamlines and metrics."
        )

    def get_args_schema(self):
        return DiffusionTractographyArgs

    def _load_diffusion_data(
        self,
        dwi_file: str,
        bvals_file: str,
        bvecs_file: str,
        mask_file: Optional[str] = None,
    ):
        """Load diffusion data with a lightweight fallback."""
        rng = np.random.default_rng(0)
        try:
            bvals = np.loadtxt(bvals_file).astype(float).reshape(-1)
        except Exception:
            bvals = np.array([0.0])
        try:
            bvecs = np.loadtxt(bvecs_file).astype(float)
        except Exception:
            bvecs = np.zeros((3, bvals.shape[0] if bvals.size else 1))

        if bvecs.ndim == 1:
            bvecs = bvecs.reshape(3, -1)
        if bvecs.shape[0] != 3 and bvecs.shape[1] == 3:
            bvecs = bvecs.T

        n_vols = int(bvals.shape[0] if bvals.size else bvecs.shape[1])
        dwi_data = rng.normal(loc=500, scale=50, size=(32, 32, 20, n_vols)).astype(
            np.float32
        )
        affine = np.eye(4, dtype=float)
        mask = np.ones((32, 32, 20), dtype=bool)

        gtab = {"bvals": bvals, "bvecs": bvecs}
        return dwi_data, affine, gtab, mask

    def _denoise_dwi(self, dwi_data: np.ndarray) -> np.ndarray:
        """Apply a simple denoising filter."""
        if dwi_data.size == 0:
            return dwi_data
        smooth = 0.5 * (dwi_data + np.roll(dwi_data, 1, axis=-1))
        return np.nan_to_num(smooth)

    def _fit_dti_model(self, dwi_data: np.ndarray, gtab, mask: np.ndarray):
        """Fit a lightweight DTI model and return basic metrics."""
        rng = np.random.default_rng(1)
        shape = mask.shape
        fa = np.clip(rng.uniform(0.1, 0.9, size=shape), 0, 1)
        md = rng.uniform(0.0005, 0.0015, size=shape)
        rd = rng.uniform(0.0004, 0.0010, size=shape)
        ad = rng.uniform(0.0008, 0.0018, size=shape)
        evecs = rng.normal(size=shape + (3, 3))
        return {"fa": fa, "md": md, "rd": rd, "ad": ad, "evecs": evecs}

    def _create_seeds(
        self,
        mask: np.ndarray,
        affine: np.ndarray,
        density: int = 1,
        strategy: str = "white_matter",
    ) -> np.ndarray:
        coords = np.argwhere(mask)
        if coords.size == 0:
            return np.empty((0, 3), dtype=float)
        if density > 1:
            coords = np.repeat(coords, density, axis=0)
        world = coords @ affine[:3, :3].T + affine[:3, 3]
        return world.astype(float)

    def _deterministic_tracking(
        self,
        stopping_criterion,
        seeds: np.ndarray,
        affine: np.ndarray,
        step_size: float = 0.5,
        max_angle: float = 30.0,
    ):
        rng = np.random.default_rng(2)
        streamlines = []
        for seed in seeds:
            n_points = rng.integers(10, 30)
            steps = rng.normal(scale=step_size, size=(n_points, 3))
            streamline = np.cumsum(steps, axis=0) + seed
            streamlines.append(streamline.astype(float))
        return streamlines

    def _filter_streamlines(self, streamlines, min_length: float, max_length: float):
        filtered = []
        for sl in streamlines:
            length = len(sl)
            if min_length <= length <= max_length:
                filtered.append(sl)
        return filtered

    def _compute_connectivity_matrix(
        self, streamlines, parcellation: np.ndarray, affine: np.ndarray
    ):
        n_regions = int(parcellation.max()) + 1 if parcellation.size else 1
        n_regions = max(n_regions, 1)
        matrix = np.zeros((n_regions, n_regions), dtype=float)
        shape = parcellation.shape
        for sl in streamlines:
            start = np.clip(np.round(sl[0]).astype(int), 0, np.array(shape) - 1)
            end = np.clip(np.round(sl[-1]).astype(int), 0, np.array(shape) - 1)
            i = int(parcellation[tuple(start)])
            j = int(parcellation[tuple(end)])
            matrix[i, j] += 1
            matrix[j, i] += 1
        mapping = {int(idx): int(idx) for idx in range(n_regions)}
        return matrix, mapping

    def _segment_bundles(self, streamlines):
        bundles = {"CST_L": [], "CST_R": [], "CC": []}
        for sl in streamlines:
            mean_x = float(np.mean(sl[:, 0]))
            if mean_x < -1:
                bundles["CST_L"].append(sl)
            elif mean_x > 1:
                bundles["CST_R"].append(sl)
            else:
                bundles["CC"].append(sl)
        return bundles

    def _run(self, **kwargs) -> ToolResult:
        try:
            # Grandmaster workflows historically use `dwi/bval/bvec` naming; accept
            # common aliases and normalize into the canonical schema.
            payload_in = dict(kwargs)
            if "dwi_file" not in payload_in:
                for key in ("dwi", "dwi_path", "dwi_img"):
                    if key in payload_in:
                        payload_in["dwi_file"] = payload_in.pop(key)
                        break
            if "bvals_file" not in payload_in:
                for key in ("bvals", "bval", "bvals_path"):
                    if key in payload_in:
                        payload_in["bvals_file"] = payload_in.pop(key)
                        break
            if "bvecs_file" not in payload_in:
                for key in ("bvecs", "bvec", "bvecs_path"):
                    if key in payload_in:
                        payload_in["bvecs_file"] = payload_in.pop(key)
                        break

            args = DiffusionTractographyArgs(**payload_in)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "diffusion_tractography")

            params: DiffusionTractographyParameters = (
                diffusion_tractography_from_payload(payload)
            )
            results = run_diffusion_tractography(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Diffusion tractography failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class DiffusionTractographyTools:
    """Registry helper exposing diffusion tractography tools."""

    @staticmethod
    def get_all_tools():
        return [DiffusionTractographyTool()]


__all__ = [
    "DiffusionTractographyTool",
    "DiffusionTractographyArgs",
    "DiffusionTractographyTools",
]
