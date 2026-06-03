"""Shared helpers for Nilearn preprocessing workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import datasets
from nilearn.maskers import NiftiLabelsMasker, NiftiMasker

from brain_researcher.services.tools.atlas_utils import (
    allow_network_atlas_fetch,
    atlas_reference_hints,
    default_atlas_output_root,
    derive_local_atlas_labels,
    existing_search_roots,
    fetch_templateflow_schaefer_atlas,
    find_local_aal_atlas,
    find_local_harvard_oxford_atlas,
    find_local_schaefer_atlas,
    find_local_yeo_atlas,
    is_path_like_atlas,
    normalize_harvard_oxford_variant,
    parse_schaefer_n_rois,
    parse_schaefer_yeo_networks,
    parse_yeo_networks,
    schaefer_output_root,
)


@dataclass(frozen=True)
class NiftiMaskerParameters:
    img: str
    output_file: str | None = None
    mask_img: str | None = None
    mask_strategy: str = "epi"
    standardize: bool = True
    detrend: bool = True
    smoothing_fwhm: float | None = None
    low_pass: float | None = None
    high_pass: float | None = None
    t_r: float | None = None
    confounds: str | None = None
    confound_strategy: tuple[str, ...] = ("motion", "wm_csf")


@dataclass(frozen=True)
class ROIExtractionParameters:
    img: str
    atlas: str
    output_dir: str
    n_parcels: int | None = None
    extract_type: str = "mean"
    confounds: str | None = None
    standardize: bool = True
    detrend: bool = True
    low_pass: float | None = None
    high_pass: float | None = None
    t_r: float | None = None
    output_file: str | None = None
    labels_file: str | None = None


def _ensure_file(path: str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return str(p)


def _nilearn_standardize_arg(enabled: bool) -> str | bool:
    return "zscore_sample" if enabled else False


def _sample_standardize_columns(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array[:, np.newaxis]
    mean = array.mean(axis=0, keepdims=True)
    std = array.std(axis=0, ddof=1, keepdims=True)
    std[~np.isfinite(std) | (std < 1e-6)] = 1.0
    return (array - mean) / std


def _load_confounds(
    path: str | None, strategy: tuple[str, ...]
) -> tuple[np.ndarray | None, list[str]]:
    if not path:
        return None, []
    confounds_path = Path(_ensure_file(path))
    if confounds_path.suffix.lower() in {".tsv", ".csv"}:
        sep = "\t" if confounds_path.suffix.lower() == ".tsv" else ","
        df = pd.read_csv(confounds_path, sep=sep)
    elif confounds_path.suffix.lower() in {".npy", ".npz"}:
        data = np.load(confounds_path)
        if isinstance(data, np.lib.npyio.NpzFile):
            data = data[data.files[0]]
        return _sample_standardize_columns(np.asarray(data)), []
    else:
        df = pd.read_csv(confounds_path, sep=None, engine="python")

    df = df.select_dtypes(include=[np.number])
    if df.empty:
        return None, []

    if strategy:
        patterns = [s.lower() for s in strategy]
        cols = [c for c in df.columns if any(p in c.lower() for p in patterns)]
        if not cols:
            cols = list(df.columns)
    else:
        cols = list(df.columns)

    confounds = _sample_standardize_columns(df[cols].fillna(0.0).to_numpy())
    return confounds, cols


def _resolve_atlas(
    atlas: str,
    n_parcels: int | None,
    reference_img: str | None = None,
) -> tuple[str, list[str] | None]:
    atlas_path = Path(atlas)
    if atlas_path.exists():
        return str(atlas_path), None
    if is_path_like_atlas(atlas):
        raise FileNotFoundError(f"Atlas path not found: {atlas}")

    atlas_key = atlas.lower()
    if atlas_key in {"aal", "aal3"}:
        output_root = default_atlas_output_root() / "aal"
        search_roots = existing_search_roots(None, output_root)
        local_atlas = find_local_aal_atlas(roots=search_roots)
        if local_atlas is not None:
            return str(local_atlas), derive_local_atlas_labels(
                local_atlas,
                atlas_name=atlas,
                family="aal",
            )
        if not allow_network_atlas_fetch():
            raise FileNotFoundError(
                "AAL atlas not found locally. "
                "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to /app/data/atlases."
            )
        data = datasets.fetch_atlas_aal(data_dir=str(output_root), verbose=0)
        return data.maps, list(data.labels)
    if "harvard" in atlas_key:
        variant = normalize_harvard_oxford_variant(atlas)
        output_root = default_atlas_output_root() / "harvard_oxford"
        search_roots = existing_search_roots(None, output_root)
        local_atlas = find_local_harvard_oxford_atlas(
            variant=variant,
            roots=search_roots,
        )
        if local_atlas is not None:
            return str(local_atlas), derive_local_atlas_labels(
                local_atlas,
                atlas_name=atlas,
                family="harvard_oxford",
            )
        if not allow_network_atlas_fetch():
            raise FileNotFoundError(
                f"Harvard-Oxford atlas not found locally for {atlas}. "
                "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to /app/data/atlases."
            )
        data = datasets.fetch_atlas_harvard_oxford(
            atlas_name=variant,
            data_dir=str(output_root),
        )
        return data.maps, list(data.labels)
    if "schaefer" in atlas_key:
        n_rois = n_parcels or parse_schaefer_n_rois(atlas)
        n_networks = parse_schaefer_yeo_networks(atlas)
        output_root = schaefer_output_root(default_atlas_output_root())
        search_roots = existing_search_roots(None, output_root)
        reference_space, reference_resolution = atlas_reference_hints(reference_img)
        local_atlas = find_local_schaefer_atlas(
            n_rois=n_rois,
            roots=search_roots,
            yeo_networks=n_networks,
            space=reference_space,
            resolution=reference_resolution,
            include_legacy=False,
        )
        if local_atlas is not None:
            return str(local_atlas), derive_local_atlas_labels(
                local_atlas,
                atlas_name=atlas,
                family="schaefer_2018",
            )
        if allow_network_atlas_fetch():
            templateflow_atlas = fetch_templateflow_schaefer_atlas(
                n_rois=n_rois,
                yeo_networks=n_networks,
                space=reference_space,
                resolution=reference_resolution,
            )
            if templateflow_atlas is not None:
                return str(templateflow_atlas), derive_local_atlas_labels(
                    templateflow_atlas,
                    atlas_name=atlas,
                    family="schaefer_2018",
                )
        legacy_atlas = find_local_schaefer_atlas(
            n_rois=n_rois,
            roots=search_roots,
            yeo_networks=n_networks,
            space=reference_space,
            resolution=reference_resolution,
        )
        if legacy_atlas is not None:
            return str(legacy_atlas), derive_local_atlas_labels(
                legacy_atlas,
                atlas_name=atlas,
                family="schaefer_2018",
            )
        if not allow_network_atlas_fetch():
            raise FileNotFoundError(
                f"Schaefer atlas not found locally for {atlas}. "
                "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to /app/data/atlases."
            )
        output_root.mkdir(parents=True, exist_ok=True)
        data = datasets.fetch_atlas_schaefer_2018(
            n_rois=n_rois,
            yeo_networks=n_networks,
            resolution_mm=2,
            data_dir=str(output_root),
            verbose=0,
        )
        return data.maps, list(data.labels)
    if "yeo" in atlas_key:
        n_networks = parse_yeo_networks(atlas)
        output_root = default_atlas_output_root() / "yeo_2011"
        search_roots = existing_search_roots(None, output_root)
        local_atlas = find_local_yeo_atlas(n_networks=n_networks, roots=search_roots)
        if local_atlas is not None:
            return str(local_atlas), derive_local_atlas_labels(
                local_atlas,
                atlas_name=atlas,
                family="yeo_2011",
            )
        if not allow_network_atlas_fetch():
            raise FileNotFoundError(
                f"Yeo atlas not found locally for {atlas}. "
                "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to /app/data/atlases."
            )
        data = datasets.fetch_atlas_yeo_2011(
            n_networks=n_networks,
            thickness="thick",
            data_dir=str(output_root),
        )
        return data.maps, list(data.labels)

    raise FileNotFoundError(f"Atlas not found or unsupported: {atlas}")


def nifti_masker_from_payload(payload: dict[str, Any]) -> NiftiMaskerParameters:
    confound_strategy = payload.get("confound_strategy", ["motion", "wm_csf"])
    return NiftiMaskerParameters(
        img=str(payload["img"]),
        output_file=payload.get("output_file"),
        mask_img=payload.get("mask_img"),
        mask_strategy=str(payload.get("mask_strategy", "epi")),
        standardize=bool(payload.get("standardize", True)),
        detrend=bool(payload.get("detrend", True)),
        smoothing_fwhm=payload.get("smoothing_fwhm"),
        low_pass=payload.get("low_pass"),
        high_pass=payload.get("high_pass"),
        t_r=payload.get("t_r"),
        confounds=payload.get("confounds"),
        confound_strategy=tuple(confound_strategy),
    )


def roi_extraction_from_payload(payload: dict[str, Any]) -> ROIExtractionParameters:
    return ROIExtractionParameters(
        img=str(payload["img"]),
        atlas=str(payload["atlas"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "roi_output")),
        n_parcels=payload.get("n_parcels"),
        extract_type=str(payload.get("extract_type", "mean")),
        confounds=payload.get("confounds"),
        standardize=bool(payload.get("standardize", True)),
        detrend=bool(payload.get("detrend", True)),
        low_pass=payload.get("low_pass"),
        high_pass=payload.get("high_pass"),
        t_r=payload.get("t_r"),
        output_file=payload.get("output_file"),
        labels_file=payload.get("labels_file"),
    )


def run_nifti_masker(params: NiftiMaskerParameters) -> dict[str, Any]:
    img_path = _ensure_file(params.img)
    confounds, confound_cols = _load_confounds(
        params.confounds, params.confound_strategy
    )

    output_dir = (
        Path(params.output_file).parent if params.output_file else Path(img_path).parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = params.output_file or str(output_dir / "nifti_masker_timeseries.npy")

    mask_img = None
    mask_strategy = params.mask_strategy
    if params.mask_img and params.mask_img.lower() != "compute":
        mask_img = _ensure_file(params.mask_img)
        mask_strategy = None

    masker = NiftiMasker(
        mask_img=mask_img,
        mask_strategy=mask_strategy,
        standardize=_nilearn_standardize_arg(params.standardize),
        standardize_confounds=False,
        detrend=params.detrend,
        smoothing_fwhm=params.smoothing_fwhm,
        low_pass=params.low_pass,
        high_pass=params.high_pass,
        t_r=params.t_r,
    )
    signals = masker.fit_transform(img_path, confounds=confounds)
    np.save(output_file, signals)

    mask_path = output_dir / "nifti_masker_mask.nii.gz"
    if masker.mask_img_ is not None:
        nib.save(masker.mask_img_, mask_path)

    summary = {
        "mask_strategy": params.mask_strategy,
        "confound_strategy": list(params.confound_strategy),
        "confounds_used": confound_cols,
        "standardize": params.standardize,
        "detrend": params.detrend,
        "n_timepoints": int(signals.shape[0]),
        "n_features": int(signals.shape[1]),
        "used_nilearn_package": True,
    }

    return {
        "outputs": {
            "signals": output_file,
            "timeseries": output_file,
            "mask": str(mask_path) if mask_path.exists() else None,
        },
        "summary": summary,
        "message": "NiftiMasker completed.",
    }


def run_roi_extraction(params: ROIExtractionParameters) -> dict[str, Any]:
    img_path = _ensure_file(params.img)
    confounds, confound_cols = _load_confounds(params.confounds, ())
    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    atlas_path, labels = _resolve_atlas(
        params.atlas,
        params.n_parcels,
        reference_img=img_path,
    )
    labels_img = atlas_path

    masker = NiftiLabelsMasker(
        labels_img=labels_img,
        standardize=_nilearn_standardize_arg(params.standardize),
        standardize_confounds=False,
        detrend=params.detrend,
        low_pass=params.low_pass,
        high_pass=params.high_pass,
        t_r=params.t_r,
        strategy=params.extract_type,
        keep_masked_labels=False,
    )
    signals = masker.fit_transform(img_path, confounds=confounds)

    output_file = params.output_file or str(output_dir / "roi_timeseries.npy")
    np.save(output_file, signals)

    labels_path = None
    if params.labels_file and labels:
        labels_path = Path(params.labels_file)
        labels_path.parent.mkdir(parents=True, exist_ok=True)
        labels_path.write_text("\n".join(labels), encoding="utf-8")

    summary = {
        "atlas": params.atlas,
        "n_parcels": params.n_parcels or (len(labels) if labels else signals.shape[1]),
        "extract_type": params.extract_type,
        "confounds_used": confound_cols,
        "used_nilearn_package": True,
    }

    return {
        "outputs": {
            "signals": output_file,
            "timeseries": output_file,
            "labels": str(labels_path) if labels_path else None,
        },
        "summary": summary,
        "message": "ROI extraction completed.",
    }


__all__ = [
    "NiftiMaskerParameters",
    "ROIExtractionParameters",
    "nifti_masker_from_payload",
    "roi_extraction_from_payload",
    "run_nifti_masker",
    "run_roi_extraction",
]
