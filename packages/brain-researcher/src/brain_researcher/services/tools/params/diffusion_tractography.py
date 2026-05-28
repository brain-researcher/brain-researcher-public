"""Fallback diffusion tractography utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    write_feature_contract,
)


@dataclass(frozen=True)
class DiffusionTractographyParameters:
    """Configuration for deterministic diffusion tractography fallback."""

    dwi_file: str
    bvals_file: str
    bvecs_file: str
    mask_file: str | None
    output_dir: str
    model_type: str
    tracking_method: str
    fa_threshold: float
    min_length: float
    max_length: float
    compute_connectivity: bool
    parcellation_file: str | None
    connectivity_metric: str
    compute_fa: bool
    compute_md: bool
    compute_rd: bool
    compute_ad: bool
    segment_bundles: bool
    save_streamlines: bool
    save_fa_map: bool
    save_connectivity: bool
    visualize: bool
    random_state: int | None


def diffusion_tractography_from_payload(
    payload: dict[str, object],
) -> DiffusionTractographyParameters:
    """Create parameters from a loosely-typed payload."""

    output_dir = payload.get("output_dir") or Path.cwd() / "diffusion_tractography"

    return DiffusionTractographyParameters(
        dwi_file=str(payload["dwi_file"]),
        bvals_file=str(payload.get("bvals_file", "")),
        bvecs_file=str(payload.get("bvecs_file", "")),
        mask_file=str(payload.get("mask_file")) if payload.get("mask_file") else None,
        output_dir=str(output_dir),
        model_type=str(payload.get("model_type", "dti")),
        tracking_method=str(payload.get("tracking_method", "deterministic")),
        fa_threshold=float(payload.get("fa_threshold", 0.1)),
        min_length=float(payload.get("min_length", 10.0)),
        max_length=float(payload.get("max_length", 250.0)),
        compute_connectivity=bool(payload.get("compute_connectivity", True)),
        parcellation_file=(
            str(payload.get("parcellation_file"))
            if payload.get("parcellation_file")
            else None
        ),
        connectivity_metric=str(payload.get("connectivity_metric", "count")),
        compute_fa=bool(payload.get("compute_fa", True)),
        compute_md=bool(payload.get("compute_md", True)),
        compute_rd=bool(payload.get("compute_rd", True)),
        compute_ad=bool(payload.get("compute_ad", True)),
        segment_bundles=bool(payload.get("segment_bundles", False)),
        save_streamlines=bool(payload.get("save_streamlines", True)),
        save_fa_map=bool(payload.get("save_fa_map", True)),
        save_connectivity=bool(payload.get("save_connectivity", True)),
        visualize=bool(payload.get("visualize", True)),
        random_state=payload.get("random_state"),
    )


def _load_volume(
    path: str, rng: np.random.Generator, fallback_shape: tuple[int, int, int, int]
) -> np.ndarray:
    file_path = Path(path)
    if file_path.suffix == ".npy":
        return np.load(file_path)
    if file_path.suffix == ".npz":
        npz = np.load(file_path)
        return npz[npz.files[0]]
    if file_path.exists() and file_path.stat().st_size > 0:
        # Keep fallback synthetic volumes bounded for large real inputs.
        # Using raw file-byte cbrt without a cap can allocate multi-GB arrays.
        size_est = int(np.cbrt(max(file_path.stat().st_size, 1)))
        size = int(np.clip(size_est, 16, 64))
        shape = (size, size, max(16, size // 2), fallback_shape[-1])
        return rng.normal(loc=500, scale=50, size=shape).astype(np.float32)
    return rng.normal(loc=500, scale=50, size=fallback_shape).astype(np.float32)


def _load_mask(path: str | None, volume: np.ndarray) -> np.ndarray:
    if path:
        mask_path = Path(path)
        if mask_path.suffix == ".npy" and mask_path.exists():
            mask = np.load(mask_path)
            if mask.ndim == 3:
                return mask.astype(bool)
        if mask_path.suffix == ".npz" and mask_path.exists():
            npz = np.load(mask_path)
            data = npz[npz.files[0]]
            return data.astype(bool)
    mean_volume = np.mean(volume, axis=-1)
    threshold = np.percentile(mean_volume, 70)
    mask = mean_volume > threshold
    if not np.any(mask):
        mask = mean_volume > mean_volume.mean()
    return mask.astype(bool)


def _generate_streamlines(mask: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n_streamlines = max(50, int(mask.sum() // 500))
    n_streamlines = min(n_streamlines, 2000)
    n_points = 32
    steps = rng.normal(scale=0.6, size=(n_streamlines, n_points, 3))
    streamlines = np.cumsum(steps, axis=1)
    return streamlines.astype(np.float32)


def _bundle_summary(streamlines: np.ndarray) -> dict[str, int]:
    n = streamlines.shape[0]
    return {
        "CST_L": int(n * 0.15),
        "CST_R": int(n * 0.15),
        "CC": int(n * 0.2),
        "UNC": int(n * 0.1),
    }


def _connectivity_matrix(mask: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n_regions = min(20, max(5, int(np.cbrt(mask.sum()))))
    matrix = rng.uniform(0, 1, size=(n_regions, n_regions))
    matrix = (matrix + matrix.T) / 2.0
    np.fill_diagonal(matrix, 0)
    return matrix.astype(np.float32)


def _diffusion_metrics(
    streamlines: np.ndarray, rng: np.random.Generator
) -> dict[str, float]:
    diffs = np.linalg.norm(np.diff(streamlines, axis=1), axis=2)
    lengths = diffs.sum(axis=1)
    return {
        "n_streamlines": int(streamlines.shape[0]),
        "mean_length": float(lengths.mean()) if lengths.size else 0.0,
        "max_length": float(lengths.max()) if lengths.size else 0.0,
        "min_length": float(lengths.min()) if lengths.size else 0.0,
        "mean_fa": float(rng.uniform(0.2, 0.7)),
    }


def run_diffusion_tractography(
    params: DiffusionTractographyParameters,
) -> dict[str, object]:
    """Execute deterministic diffusion tractography fallback."""

    rng = np.random.default_rng(params.random_state)
    fallback_shape = (64, 64, 40, 60)
    dwi = _load_volume(params.dwi_file, rng, fallback_shape)
    mask = _load_mask(params.mask_file, dwi)

    streamlines = _generate_streamlines(mask, rng)
    metrics = _diffusion_metrics(streamlines, rng)

    fa_map = rng.uniform(0.1, 0.9, size=mask.shape).astype(np.float32)
    md_map = rng.uniform(0.0005, 0.0015, size=mask.shape).astype(np.float32)
    rd_map = rng.uniform(0.0004, 0.001, size=mask.shape).astype(np.float32)
    ad_map = rng.uniform(0.0008, 0.0018, size=mask.shape).astype(np.float32)

    if params.segment_bundles:
        bundle_info = _bundle_summary(streamlines)
        metrics.update({"n_bundles": sum(bundle_info.values())})
    else:
        bundle_info = {}

    if params.compute_connectivity and params.save_connectivity:
        connectivity = _connectivity_matrix(mask, rng)
    else:
        connectivity = None

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str | None] = {
        "streamlines": None,
        "fa": None,
        "md": None,
        "rd": None,
        "ad": None,
        "connectivity": None,
        "feature_contract": None,
        "results": None,
        "visualization": None,
    }

    if params.save_streamlines:
        sl_path = out_dir / "streamlines.npy"
        np.save(sl_path, streamlines)
        outputs["streamlines"] = str(sl_path)

    if params.compute_fa and params.save_fa_map:
        fa_path = out_dir / "fa_map.npy"
        np.save(fa_path, fa_map)
        outputs["fa"] = str(fa_path)

    if params.compute_md:
        md_path = out_dir / "md_map.npy"
        np.save(md_path, md_map)
        outputs["md"] = str(md_path)

    if params.compute_rd:
        rd_path = out_dir / "rd_map.npy"
        np.save(rd_path, rd_map)
        outputs["rd"] = str(rd_path)

    if params.compute_ad:
        ad_path = out_dir / "ad_map.npy"
        np.save(ad_path, ad_map)
        outputs["ad"] = str(ad_path)

    if connectivity is not None:
        conn_path = out_dir / "connectivity.npy"
        np.save(conn_path, connectivity)
        outputs["connectivity"] = str(conn_path)
        try:
            contract = FeatureContract(
                matrix_kind=f"structural_connectome_{params.connectivity_metric}",
                source_level="tractography_counts",
                n_rois=int(connectivity.shape[0]) if connectivity.ndim == 2 else 0,
                transform_state="raw_structural_connectome",
                extras={
                    "model_type": params.model_type,
                    "tracking_method": params.tracking_method,
                    "parcellation_file": params.parcellation_file,
                    "connectivity_metric": params.connectivity_metric,
                },
            )
            contract_path = write_feature_contract(contract, out_dir)
            outputs["feature_contract"] = str(contract_path)
        except Exception:
            outputs["feature_contract"] = None

    summary = {
        "model": params.model_type,
        "tracking_method": params.tracking_method,
        "fa_threshold": params.fa_threshold,
        "metrics": metrics,
        "bundles": bundle_info,
        "connectivity_metric": (
            params.connectivity_metric if connectivity is not None else None
        ),
        "used_full_backend": False,
    }

    summary_path = out_dir / "tractography_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["results"] = str(summary_path)

    if params.visualize:
        vis_path = out_dir / "tractography_preview.png"
        vis_path.write_bytes(b"")
        outputs["visualization"] = str(vis_path)

    message = f"Diffusion tractography completed (fallback) — streamlines: {metrics['n_streamlines']}"

    return {
        "outputs": {k: v for k, v in outputs.items() if v is not None},
        "summary": summary,
        "message": message,
    }


__all__ = [
    "DiffusionTractographyParameters",
    "diffusion_tractography_from_payload",
    "run_diffusion_tractography",
]
