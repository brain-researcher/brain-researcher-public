"""Shared helpers for Nilearn GLM and connectivity analyses."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from brain_researcher.core.analysis.connectivity_contracts import (
    build_feature_contract,
    safe_fisher_z,
    write_feature_contract,
)

try:  # Optional at import time; runtime validation happens in helpers
    from nilearn.connectome import ConnectivityMeasure
    from nilearn.glm.first_level import FirstLevelModel, make_first_level_design_matrix
    from nilearn.glm.second_level import SecondLevelModel
    from nilearn.image import load_img
    from nilearn.maskers import NiftiMasker, NiftiSpheresMasker
except Exception as _nilearn_exc:  # pragma: no cover - allows lightweight envs
    ConnectivityMeasure = None  # type: ignore
    FirstLevelModel = None  # type: ignore
    make_first_level_design_matrix = None  # type: ignore
    SecondLevelModel = None  # type: ignore
    NiftiMasker = None  # type: ignore
    NiftiSpheresMasker = None  # type: ignore
    load_img = None  # type: ignore
    _IMPORT_ERROR = _nilearn_exc
else:
    _IMPORT_ERROR = None


@dataclass(frozen=True)
class GLMFirstLevelParameters:
    img: str
    output_dir: str
    events: str | None = None
    t_r: float | None = None
    hrf_model: str = "spm"
    drift_model: str = "cosine"
    high_pass: float = 0.01
    mask_img: str | None = None
    smoothing_fwhm: float | None = None
    standardize: bool = True
    noise_model: str = "ar1"
    n_jobs: int = -1
    contrasts: dict[str, Sequence[float]] | None = None
    confounds: str | None = None
    fir_delays: tuple[int, ...] | None = None
    flobs_basis_file: str | None = None
    flobs_dt: float = 0.05


@dataclass(frozen=True)
class GLMSecondLevelParameters:
    contrast_maps: tuple[str, ...]
    output_dir: str
    design_matrix: str | dict[str, Sequence[float]] | None = None
    contrast: str | Sequence[float] | None = None
    mask_img: str | None = None
    smoothing_fwhm: float | None = None
    model_type: str = "ols"


@dataclass(frozen=True)
class ConnectivityMatrixParameters:
    timeseries: str | Sequence[Sequence[float]]
    kind: str = "correlation"
    vectorize: bool = False
    discard_diagonal: bool = False
    fisher_z: bool = True
    output_file: str | None = None


@dataclass(frozen=True)
class SeedBasedConnectivityParameters:
    img: str
    output_dir: str
    output_file: str | None = None
    seed_coords: tuple[float, float, float] | None = None
    seed_mask: str | None = None
    radius: float = 8.0
    mask_img: str | None = None
    smoothing_fwhm: float | None = None
    standardize: bool = True
    detrend: bool = True
    low_pass: float | None = None
    high_pass: float | None = None
    t_r: float | None = None
    confounds: str | None = None


def _ensure_path(path: str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return str(p)


def _normalize_hrf_model(value: str | None) -> str:
    raw = str(value or "spm").strip().lower()
    aliases = {
        "canonical": "spm",
        "spm": "spm",
        "derivs": "spm + derivative",
        "spm_time": "spm + derivative",
        "spm + derivative": "spm + derivative",
        "spm_time_dispersion": "spm + derivative + dispersion",
        "spm + derivative + dispersion": "spm + derivative + dispersion",
        "glover": "glover",
        "glover_time": "glover + derivative",
        "glover + derivative": "glover + derivative",
        "glover_time_dispersion": "glover + derivative + dispersion",
        "glover + derivative + dispersion": "glover + derivative + dispersion",
        "fir": "fir",
        "flobs": "flobs",
    }
    return aliases.get(raw, str(value or "spm"))


def _resolve_flobs_basis_file(path: str | None) -> str:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    fsl_dir = os.environ.get("FSLDIR")
    if fsl_dir:
        candidates.append(
            Path(fsl_dir) / "etc" / "default_flobs.flobs" / "hrfbasisfns.txt"
        )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        "FLOBS basis file not found. Provide flobs_basis_file or set FSLDIR."
    )


def _load_confounds_frame(
    path: str | None,
) -> tuple[pd.DataFrame | None, list[str]]:
    if not path:
        return None, []
    confounds_path = Path(_ensure_path(path))
    if confounds_path.suffix.lower() == ".tsv":
        df = pd.read_csv(confounds_path, sep="\t")
    elif confounds_path.suffix.lower() == ".csv":
        df = pd.read_csv(confounds_path)
    else:
        df = pd.read_csv(confounds_path, sep=None, engine="python")
    numeric_df = df.select_dtypes(include=[np.number]).replace(
        [np.inf, -np.inf], np.nan
    )
    if numeric_df.empty:
        return None, []
    numeric_df = numeric_df.fillna(0.0)
    return numeric_df, list(numeric_df.columns)


def _load_events_frame(path: str | None, n_scans: int, t_r: float) -> pd.DataFrame:
    if path:
        events_path = Path(_ensure_path(path))
        if events_path.suffix.lower() == ".tsv":
            events = pd.read_csv(events_path, sep="\t")
        elif events_path.suffix.lower() == ".csv":
            events = pd.read_csv(events_path)
        else:
            events = pd.read_csv(events_path, sep=None, engine="python")
    else:
        events = pd.DataFrame(
            {
                "onset": [0.0],
                "duration": [n_scans * t_r],
                "trial_type": ["stim"],
            }
        )

    required = {"onset", "duration", "trial_type"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Events file missing required columns: {sorted(missing)}")
    return events.loc[:, ["onset", "duration", "trial_type"]].copy()


def _build_default_contrasts(
    design_matrix: pd.DataFrame, *, aggregate_flobs: bool = False
) -> dict[str, np.ndarray]:
    contrasts: dict[str, np.ndarray] = {}
    if aggregate_flobs:
        prefixes = sorted(
            {
                col.rsplit("_flobs", 1)[0]
                for col in design_matrix.columns
                if "_flobs" in col
            }
        )
        for prefix in prefixes:
            vec = np.zeros(len(design_matrix.columns), dtype=float)
            for column in [
                c for c in design_matrix.columns if c.startswith(f"{prefix}_flobs")
            ]:
                vec[design_matrix.columns.get_loc(column)] = 1.0
            contrasts[prefix] = vec
        return contrasts

    columns = [
        c for c in design_matrix.columns if c.lower() not in {"constant", "intercept"}
    ]
    for col in columns:
        vec = np.zeros(len(design_matrix.columns), dtype=float)
        vec[design_matrix.columns.get_loc(col)] = 1.0
        contrasts[col] = vec
    return contrasts


def _build_flobs_design_matrix(
    frame_times: np.ndarray,
    events: pd.DataFrame,
    *,
    drift_model: str,
    high_pass: float,
    confounds: pd.DataFrame | None,
    confound_columns: list[str],
    flobs_basis_file: str | None,
    flobs_dt: float,
) -> tuple[pd.DataFrame, str]:
    if make_first_level_design_matrix is None:  # pragma: no cover
        raise RuntimeError("nilearn is required for FLOBS design matrix generation")

    basis_path = _resolve_flobs_basis_file(flobs_basis_file)
    basis = np.loadtxt(basis_path)
    if basis.ndim == 1:
        basis = basis[:, np.newaxis]
    if basis.ndim != 2 or basis.shape[1] == 0:
        raise ValueError("FLOBS basis file must contain at least one basis column")

    dt = float(flobs_dt)
    if dt <= 0:
        raise ValueError("flobs_dt must be positive")

    max_event_end = float((events["onset"] + events["duration"]).max())
    total_duration = max(frame_times[-1] + dt, max_event_end + basis.shape[0] * dt)
    highres_times = np.arange(0.0, total_duration + dt, dt)

    flobs_columns: dict[str, np.ndarray] = {}
    for condition in sorted(events["trial_type"].astype(str).unique()):
        reg = np.zeros(len(highres_times), dtype=float)
        subset = events[events["trial_type"].astype(str) == condition]
        for row in subset.itertuples(index=False):
            onset = float(row.onset)
            duration = max(float(row.duration), 0.0)
            start_idx = int(np.searchsorted(highres_times, onset, side="left"))
            end_time = onset + (duration if duration > 0 else dt)
            end_idx = int(np.searchsorted(highres_times, end_time, side="left"))
            reg[start_idx : max(start_idx + 1, end_idx)] += 1.0

        for basis_idx in range(basis.shape[1]):
            convolved = (
                np.convolve(reg, basis[:, basis_idx], mode="full")[: len(highres_times)]
                * dt
            )
            sampled = np.interp(frame_times, highres_times, convolved)
            flobs_columns[f"{condition}_flobs{basis_idx + 1}"] = sampled

    add_reg_names = list(flobs_columns.keys())
    add_regs = np.column_stack([flobs_columns[name] for name in add_reg_names])
    if confounds is not None and not confounds.empty:
        add_reg_names.extend(confound_columns)
        add_regs = np.column_stack([add_regs, confounds.to_numpy(dtype=float)])

    design_matrix = make_first_level_design_matrix(
        frame_times,
        events=None,
        hrf_model=None,
        drift_model=drift_model,
        high_pass=high_pass,
        add_regs=add_regs,
        add_reg_names=add_reg_names,
    )
    return design_matrix, basis_path


def glm_first_level_from_payload(payload: dict[str, Any]) -> GLMFirstLevelParameters:
    fir_delays = payload.get("fir_delays")
    return GLMFirstLevelParameters(
        img=str(payload["img"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "glm_first_level")),
        events=payload.get("events"),
        t_r=payload.get("t_r"),
        hrf_model=_normalize_hrf_model(payload.get("hrf_model", "spm")),
        drift_model=str(payload.get("drift_model", "cosine")),
        high_pass=float(payload.get("high_pass", 0.01)),
        mask_img=payload.get("mask_img"),
        smoothing_fwhm=payload.get("smoothing_fwhm"),
        standardize=bool(payload.get("standardize", True)),
        noise_model=str(payload.get("noise_model", "ar1")),
        n_jobs=int(payload.get("n_jobs", -1)),
        contrasts=payload.get("contrasts"),
        confounds=payload.get("confounds"),
        fir_delays=tuple(int(v) for v in fir_delays) if fir_delays else None,
        flobs_basis_file=payload.get("flobs_basis_file"),
        flobs_dt=float(payload.get("flobs_dt", 0.05)),
    )


def glm_second_level_from_payload(payload: dict[str, Any]) -> GLMSecondLevelParameters:
    contrast_maps = tuple(str(p) for p in payload.get("contrast_maps", []))
    return GLMSecondLevelParameters(
        contrast_maps=contrast_maps,
        output_dir=str(payload.get("output_dir", Path.cwd() / "glm_second_level")),
        design_matrix=payload.get("design_matrix"),
        contrast=payload.get("contrast"),
        mask_img=payload.get("mask_img"),
        smoothing_fwhm=payload.get("smoothing_fwhm"),
        model_type=str(payload.get("model_type", "ols")),
    )


def connectivity_matrix_from_payload(
    payload: dict[str, Any],
) -> ConnectivityMatrixParameters:
    return ConnectivityMatrixParameters(
        timeseries=payload["timeseries"],
        kind=str(payload.get("kind", "correlation")),
        vectorize=bool(payload.get("vectorize", False)),
        discard_diagonal=bool(payload.get("discard_diagonal", False)),
        fisher_z=bool(payload.get("fisher_z", True)),
        output_file=payload.get("output_file"),
    )


def seed_connectivity_from_payload(
    payload: dict[str, Any],
) -> SeedBasedConnectivityParameters:
    seed_coords = payload.get("seed_coords")
    return SeedBasedConnectivityParameters(
        img=str(payload["img"]),
        output_dir=str(payload.get("output_dir", Path.cwd() / "seed_based_fc")),
        output_file=payload.get("output_file"),
        seed_coords=tuple(seed_coords) if seed_coords else None,
        seed_mask=payload.get("seed_mask"),
        radius=float(payload.get("radius", 8.0)),
        mask_img=payload.get("mask_img"),
        smoothing_fwhm=payload.get("smoothing_fwhm"),
        standardize=bool(payload.get("standardize", True)),
        detrend=bool(payload.get("detrend", True)),
        low_pass=payload.get("low_pass"),
        high_pass=payload.get("high_pass"),
        t_r=payload.get("t_r"),
        confounds=payload.get("confounds"),
    )


def run_glm_first_level(params: GLMFirstLevelParameters) -> dict[str, Any]:
    _ensure_nilearn_available()
    img_path = _ensure_path(params.img)
    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_hrf_model = _normalize_hrf_model(params.hrf_model)

    img = load_img(img_path)
    t_r = params.t_r
    if t_r is None:
        zooms = img.header.get_zooms()
        if len(zooms) >= 4:
            t_r = float(zooms[3])
        else:
            t_r = 2.0

    n_scans = img.shape[3]
    events = _load_events_frame(params.events, n_scans, t_r)

    confounds, confound_columns = _load_confounds_frame(params.confounds)

    if resolved_hrf_model == "flobs":
        frame_times = np.arange(n_scans, dtype=float) * t_r
        design_matrix, used_flobs_basis = _build_flobs_design_matrix(
            frame_times,
            events,
            drift_model=params.drift_model,
            high_pass=params.high_pass,
            confounds=confounds,
            confound_columns=confound_columns,
            flobs_basis_file=params.flobs_basis_file,
            flobs_dt=params.flobs_dt,
        )
        model = FirstLevelModel(
            t_r=t_r,
            mask_img=params.mask_img,
            smoothing_fwhm=params.smoothing_fwhm,
            standardize=params.standardize,
            noise_model=params.noise_model,
            n_jobs=params.n_jobs,
        )
        model = model.fit(img_path, design_matrices=design_matrix)
    else:
        model = FirstLevelModel(
            t_r=t_r,
            hrf_model=resolved_hrf_model,
            fir_delays=list(params.fir_delays) if params.fir_delays else None,
            drift_model=params.drift_model,
            high_pass=params.high_pass,
            mask_img=params.mask_img,
            smoothing_fwhm=params.smoothing_fwhm,
            standardize=params.standardize,
            noise_model=params.noise_model,
            n_jobs=params.n_jobs,
        )
        model = model.fit(img_path, events, confounds=confounds)
        design_matrix = model.design_matrices_[0]
        used_flobs_basis = None

    contrasts = params.contrasts or {}
    if not contrasts:
        contrasts = _build_default_contrasts(
            design_matrix,
            aggregate_flobs=(resolved_hrf_model == "flobs"),
        )

    zmaps: list[str] = []
    for name, contrast in contrasts.items():
        if isinstance(contrast, list | tuple | np.ndarray):
            contrast_def = np.asarray(contrast, dtype=float)
        else:
            contrast_def = contrast
        z_map = model.compute_contrast(contrast_def, output_type="z_score")
        zmap_path = output_dir / f"{name}_zmap.nii.gz"
        z_map.to_filename(zmap_path)
        zmaps.append(str(zmap_path))

    summary = {
        "hrf_model": resolved_hrf_model,
        "requested_hrf_model": params.hrf_model,
        "noise_model": params.noise_model,
        "contrasts": list(contrasts.keys()),
        "design_columns": list(design_matrix.columns),
        "confounds_columns": confound_columns,
        "n_scans": int(design_matrix.shape[0]),
        "fir_delays": list(params.fir_delays) if params.fir_delays else None,
        "flobs_basis_file": used_flobs_basis,
        "used_nilearn_package": True,
    }

    summary_path = output_dir / "glm_first_level_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "summary": str(summary_path),
            "zmaps": zmaps,
        },
        "summary": summary,
        "message": "First-level GLM completed.",
    }


def run_glm_second_level(params: GLMSecondLevelParameters) -> dict[str, Any]:
    _ensure_nilearn_available()
    for path in params.contrast_maps:
        _ensure_path(path)
    if params.mask_img:
        _ensure_path(params.mask_img)

    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(params.design_matrix, str):
        dm_path = Path(_ensure_path(params.design_matrix))
        sep = "\t" if dm_path.suffix.lower() == ".tsv" else ","
        design_matrix = pd.read_csv(dm_path, sep=sep)
    elif isinstance(params.design_matrix, dict):
        design_matrix = pd.DataFrame(params.design_matrix)
    else:
        design_matrix = pd.DataFrame({"intercept": np.ones(len(params.contrast_maps))})

    try:
        model = SecondLevelModel(
            mask_img=params.mask_img,
            smoothing_fwhm=params.smoothing_fwhm,
            model_type=params.model_type,
        ).fit(list(params.contrast_maps), design_matrix=design_matrix)
    except TypeError:
        model = SecondLevelModel(
            mask_img=params.mask_img,
            smoothing_fwhm=params.smoothing_fwhm,
        ).fit(list(params.contrast_maps), design_matrix=design_matrix)

    contrast = params.contrast or "intercept"
    z_map = model.compute_contrast(contrast, output_type="z_score")
    zmap_path = output_dir / "group_zmap.nii.gz"
    z_map.to_filename(zmap_path)

    summary = {
        "model_type": params.model_type,
        "n_maps": len(params.contrast_maps),
        "design_columns": list(design_matrix.columns),
        "used_nilearn_package": True,
    }

    summary_path = output_dir / "glm_second_level_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "summary": str(summary_path),
            "zmap": str(zmap_path),
        },
        "summary": summary,
        "message": "Second-level GLM completed.",
    }


def _ensure_nilearn_available() -> None:
    if _IMPORT_ERROR is not None:
        raise RuntimeError(
            "nilearn is required for connectivity operations"
        ) from _IMPORT_ERROR


def _load_timeseries(timeseries: str | Sequence[Sequence[float]]) -> np.ndarray:
    if isinstance(timeseries, str):
        path = Path(_ensure_path(timeseries))
        suffix = path.suffix.lower()
        if suffix in {".npy", ".npz"}:
            data = np.load(path)
        elif suffix in {".csv", ".tsv", ".txt"}:
            delimiter = "," if suffix == ".csv" else "\t"
            data = np.loadtxt(path, delimiter=delimiter)
        else:
            data = np.load(path)
    else:
        data = np.asarray(timeseries)

    if data.ndim == 1:
        raise ValueError("Timeseries input must be at least 2D (time x roi)")
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    if data.ndim != 3:
        raise ValueError(
            f"Timeseries array must be 3D (subjects x time x roi), got {data.ndim}"
        )
    return data


def _zscore(arr: np.ndarray, axis: int) -> np.ndarray:
    mean = arr.mean(axis=axis, keepdims=True)
    std = arr.std(axis=axis, keepdims=True)
    std[std < 1e-6] = 1e-6
    return (arr - mean) / std


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


def run_connectivity_matrix(params: ConnectivityMatrixParameters) -> dict[str, Any]:
    _ensure_nilearn_available()
    timeseries = _load_timeseries(params.timeseries)
    n_subjects, n_tp, n_rois = timeseries.shape
    ts_list = [timeseries[idx] for idx in range(n_subjects)]

    measure = ConnectivityMeasure(
        kind=params.kind,
        vectorize=params.vectorize,
        discard_diagonal=params.discard_diagonal,
        standardize="zscore_sample",
    )
    matrix = measure.fit_transform(ts_list)
    fisher_z_diagnostics: dict[str, Any] | None = None
    if params.fisher_z:
        matrix, fisher_z_diagnostics = safe_fisher_z(
            matrix,
            f"connectivity_matrix(kind={params.kind})",
            return_diagnostics=True,
        )

    output_file = params.output_file or str(Path.cwd() / "connectivity_matrix.npy")
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    np.save(output_file, matrix)

    summary = {
        "kind": params.kind,
        "shape": list(matrix.shape),
        "n_subjects": int(n_subjects),
        "n_rois": int(n_rois),
        "used_nilearn_package": True,
        "fisher_z_applied": bool(params.fisher_z),
    }
    if fisher_z_diagnostics is not None:
        summary["fisher_z_diagnostics"] = fisher_z_diagnostics

    feature_contract_path: str | None = None
    try:
        contract_dir = Path(output_file).parent
        cov_estimator_obj = getattr(measure, "cov_estimator_", None) or getattr(
            measure, "cov_estimator", None
        )
        cov_estimator_name: str | None = None
        if cov_estimator_obj is not None:
            cov_estimator_name = type(cov_estimator_obj).__name__
        contract = build_feature_contract(
            matrix,
            matrix_kind=params.kind,
            source_level="roi_timeseries",
            n_rois=int(n_rois),
            n_timepoints=int(n_tp),
            effective_n_timepoints=int(n_tp),
            covariance_estimator=cov_estimator_name,
            fisher_z_diagnostics=fisher_z_diagnostics,
            extras={
                "n_subjects": int(n_subjects),
                "vectorize": bool(params.vectorize),
                "discard_diagonal": bool(params.discard_diagonal),
            },
        )
        feature_contract_path = str(write_feature_contract(contract, contract_dir))
    except Exception as exc:  # pragma: no cover - emitter must not break run
        summary["feature_contract_warning"] = (
            f"feature_contract sidecar emission failed: {exc!r}"
        )

    outputs: dict[str, str] = {
        "matrix": output_file,
        "connectivity_matrix": output_file,
    }
    if feature_contract_path is not None:
        outputs["feature_contract"] = feature_contract_path

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Connectivity matrix computed.",
    }


def run_seed_based_connectivity(
    params: SeedBasedConnectivityParameters,
) -> dict[str, Any]:
    _ensure_nilearn_available()
    img_path = _ensure_path(params.img)
    confounds = None
    if params.confounds:
        conf_path = Path(_ensure_path(params.confounds))
        sep = "\t" if conf_path.suffix.lower() == ".tsv" else ","
        confounds = _sample_standardize_columns(
            pd.read_csv(conf_path, sep=sep)
            .select_dtypes(include=[np.number])
            .fillna(0.0)
            .to_numpy()
        )

    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    brain_masker = NiftiMasker(
        mask_img=params.mask_img,
        smoothing_fwhm=params.smoothing_fwhm,
        standardize=_nilearn_standardize_arg(params.standardize),
        standardize_confounds=False,
        detrend=params.detrend,
        low_pass=params.low_pass,
        high_pass=params.high_pass,
        t_r=params.t_r,
    )
    brain_ts = brain_masker.fit_transform(img_path, confounds=confounds)

    if params.seed_mask:
        seed_masker = NiftiMasker(
            mask_img=_ensure_path(params.seed_mask),
            standardize=_nilearn_standardize_arg(params.standardize),
            standardize_confounds=False,
            detrend=params.detrend,
            low_pass=params.low_pass,
            high_pass=params.high_pass,
            t_r=params.t_r,
        )
        seed_ts = seed_masker.fit_transform(img_path, confounds=confounds)
    else:
        if not params.seed_coords:
            raise ValueError(
                "seed_coords or seed_mask is required for seed connectivity"
            )
        seed_masker = NiftiSpheresMasker(
            [params.seed_coords],
            radius=params.radius,
            standardize=_nilearn_standardize_arg(params.standardize),
            standardize_confounds=False,
            detrend=params.detrend,
            low_pass=params.low_pass,
            high_pass=params.high_pass,
            t_r=params.t_r,
        )
        seed_ts = seed_masker.fit_transform(img_path, confounds=confounds)

    seed_ts = seed_ts.mean(axis=1, keepdims=True)
    seed_ts = _zscore(seed_ts, axis=0)
    brain_ts = _zscore(brain_ts, axis=0)
    corr = (brain_ts * seed_ts).mean(axis=0)

    seed_map = brain_masker.inverse_transform(corr)
    map_path = (
        Path(params.output_file)
        if params.output_file
        else (output_dir / "seed_based_connectivity.nii.gz")
    )
    map_path.parent.mkdir(parents=True, exist_ok=True)
    seed_map.to_filename(map_path)

    summary = {
        "radius": params.radius,
        "seed": params.seed_coords or params.seed_mask,
        "n_voxels": int(corr.size),
        "used_nilearn_package": True,
    }

    return {
        "outputs": {
            "map": str(map_path),
        },
        "summary": summary,
        "message": "Seed-based connectivity completed.",
    }


__all__ = [
    "GLMFirstLevelParameters",
    "GLMSecondLevelParameters",
    "ConnectivityMatrixParameters",
    "SeedBasedConnectivityParameters",
    "glm_first_level_from_payload",
    "glm_second_level_from_payload",
    "connectivity_matrix_from_payload",
    "seed_connectivity_from_payload",
    "run_glm_first_level",
    "run_glm_second_level",
    "run_connectivity_matrix",
    "run_seed_based_connectivity",
]
