"""Estimate ROI-level HRFs from FIR fits and refit with the learned kernel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .nilearn_analysis import (
    NiftiMasker,
    _build_flobs_design_matrix,
    _ensure_nilearn_available,
    _load_confounds_frame,
    _load_events_frame,
    _normalize_hrf_model,
    load_img,
    make_first_level_design_matrix,
)


@dataclass(frozen=True)
class HRFEstimateAndRefitParameters:
    """Configuration for ROI/global HRF estimation and refitting."""

    img: str
    events: str | None
    output_dir: str
    t_r: float | None = None
    roi_mask: str | None = None
    mask_img: str | None = None
    confounds: str | None = None
    fir_delays: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
    drift_model: str = "cosine"
    high_pass: float = 0.01
    smoothing_fwhm: float | None = None
    standardize: bool = True
    comparison_hrf_model: str | None = "canonical"
    flobs_basis_file: str | None = None
    flobs_dt: float = 0.05


def hrf_estimate_and_refit_from_payload(
    payload: dict[str, object],
) -> HRFEstimateAndRefitParameters:
    """Create typed parameters from the tool payload."""

    output_dir = payload.get("output_dir") or Path.cwd() / "hrf_estimate_and_refit"
    fir_delays = payload.get("fir_delays") or [0, 1, 2, 3, 4, 5]
    comparison_hrf_model = payload.get("comparison_hrf_model", "canonical")
    return HRFEstimateAndRefitParameters(
        img=str(payload["img"]),
        events=str(payload["events"]) if payload.get("events") else None,
        output_dir=str(output_dir),
        t_r=float(payload["t_r"]) if payload.get("t_r") is not None else None,
        roi_mask=str(payload["roi_mask"]) if payload.get("roi_mask") else None,
        mask_img=str(payload["mask_img"]) if payload.get("mask_img") else None,
        confounds=str(payload["confounds"]) if payload.get("confounds") else None,
        fir_delays=tuple(int(v) for v in fir_delays),
        drift_model=str(payload.get("drift_model", "cosine")),
        high_pass=float(payload.get("high_pass", 0.01)),
        smoothing_fwhm=(
            float(payload["smoothing_fwhm"])
            if payload.get("smoothing_fwhm") is not None
            else None
        ),
        standardize=bool(payload.get("standardize", True)),
        comparison_hrf_model=(
            str(comparison_hrf_model) if comparison_hrf_model is not None else None
        ),
        flobs_basis_file=(
            str(payload["flobs_basis_file"])
            if payload.get("flobs_basis_file")
            else None
        ),
        flobs_dt=float(payload.get("flobs_dt", 0.05)),
    )


def _build_standard_design(
    frame_times: np.ndarray,
    events: pd.DataFrame,
    *,
    hrf_model: str,
    fir_delays: tuple[int, ...] | None,
    drift_model: str,
    high_pass: float,
    confounds: pd.DataFrame | None,
    confound_columns: list[str],
) -> pd.DataFrame:
    if make_first_level_design_matrix is None:  # pragma: no cover
        raise RuntimeError("nilearn is required for HRF design matrix generation")

    add_regs = confounds.to_numpy(dtype=float) if confounds is not None else None
    add_reg_names = confound_columns if confounds is not None else None
    return make_first_level_design_matrix(
        frame_times,
        events=events,
        hrf_model=hrf_model,
        fir_delays=list(fir_delays) if fir_delays else None,
        drift_model=drift_model,
        high_pass=high_pass,
        add_regs=add_regs,
        add_reg_names=add_reg_names,
    )


def _fit_ols(
    design_matrix: pd.DataFrame, signal: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    x = np.asarray(design_matrix.to_numpy(dtype=float), dtype=float)
    y = np.asarray(signal, dtype=float).reshape(-1)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return beta, fitted, r2


def _extract_condition_kernels(
    fir_design: pd.DataFrame,
    betas: np.ndarray,
    fir_delays: tuple[int, ...],
    conditions: list[str],
) -> tuple[list[dict[str, object]], dict[str, np.ndarray]]:
    rows: list[dict[str, object]] = []
    kernels: dict[str, np.ndarray] = {}
    for condition in conditions:
        raw_kernel = np.asarray(
            [
                betas[fir_design.columns.get_loc(f"{condition}_delay_{delay}")]
                for delay in fir_delays
            ],
            dtype=float,
        )
        scale = float(np.max(np.abs(raw_kernel))) if raw_kernel.size else 0.0
        normalized = (
            raw_kernel / scale if np.isfinite(scale) and scale >= 1e-8 else raw_kernel
        )
        kernels[condition] = normalized
        for delay, raw_value, norm_value in zip(
            fir_delays, raw_kernel, normalized, strict=True
        ):
            rows.append(
                {
                    "condition": condition,
                    "delay_index": int(delay),
                    "delay_s": float(delay),
                    "beta": float(raw_value),
                    "normalized_hrf": float(norm_value),
                }
            )
    return rows, kernels


def _build_custom_refit_design(
    frame_times: np.ndarray,
    events: pd.DataFrame,
    *,
    kernels: dict[str, np.ndarray],
    drift_model: str,
    high_pass: float,
    confounds: pd.DataFrame | None,
    confound_columns: list[str],
    t_r: float,
) -> pd.DataFrame:
    if make_first_level_design_matrix is None:  # pragma: no cover
        raise RuntimeError("nilearn is required for HRF design matrix generation")

    n_scans = len(frame_times)
    regressors: dict[str, np.ndarray] = {}
    for condition, kernel in kernels.items():
        reg = np.zeros(n_scans, dtype=float)
        subset = events[events["trial_type"].astype(str) == condition]
        for row in subset.itertuples(index=False):
            onset_idx = int(np.searchsorted(frame_times, float(row.onset), side="left"))
            duration_s = max(float(row.duration), 0.0)
            duration_scans = max(int(round(duration_s / t_r)), 1)
            reg[onset_idx : min(n_scans, onset_idx + duration_scans)] += 1.0
        regressors[f"{condition}_custom_hrf"] = np.convolve(reg, kernel, mode="full")[
            :n_scans
        ]

    add_reg_names = list(regressors.keys())
    add_regs = np.column_stack([regressors[name] for name in add_reg_names])
    if confounds is not None and not confounds.empty:
        add_reg_names.extend(confound_columns)
        add_regs = np.column_stack([add_regs, confounds.to_numpy(dtype=float)])

    return make_first_level_design_matrix(
        frame_times,
        events=None,
        hrf_model=None,
        drift_model=drift_model,
        high_pass=high_pass,
        add_regs=add_regs,
        add_reg_names=add_reg_names,
    )


def run_hrf_estimate_and_refit(
    params: HRFEstimateAndRefitParameters,
) -> dict[str, object]:
    """Estimate an ROI-level HRF with FIR and compare canonical vs refit models."""

    _ensure_nilearn_available()
    img_path = str(Path(params.img).resolve())
    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    img = load_img(img_path)
    t_r = params.t_r
    if t_r is None:
        zooms = img.header.get_zooms()
        t_r = float(zooms[3]) if len(zooms) >= 4 else 2.0

    n_scans = img.shape[3]
    frame_times = np.arange(n_scans, dtype=float) * t_r
    events = _load_events_frame(params.events, n_scans, t_r)
    confounds, confound_columns = _load_confounds_frame(params.confounds)

    masker = NiftiMasker(
        mask_img=params.roi_mask or params.mask_img,
        smoothing_fwhm=params.smoothing_fwhm,
        standardize="zscore_sample" if params.standardize else False,
    )
    roi_signal = masker.fit_transform(img_path).mean(axis=1)

    fir_design = _build_standard_design(
        frame_times,
        events,
        hrf_model="fir",
        fir_delays=params.fir_delays,
        drift_model=params.drift_model,
        high_pass=params.high_pass,
        confounds=confounds,
        confound_columns=confound_columns,
    )
    fir_betas, _, fir_r2 = _fit_ols(fir_design, roi_signal)
    conditions = sorted(events["trial_type"].astype(str).unique())
    hrf_rows, kernels = _extract_condition_kernels(
        fir_design,
        fir_betas,
        params.fir_delays,
        conditions,
    )

    canonical_design = _build_standard_design(
        frame_times,
        events,
        hrf_model="spm",
        fir_delays=None,
        drift_model=params.drift_model,
        high_pass=params.high_pass,
        confounds=confounds,
        confound_columns=confound_columns,
    )
    _, canonical_fit, canonical_r2 = _fit_ols(canonical_design, roi_signal)

    custom_design = _build_custom_refit_design(
        frame_times,
        events,
        kernels=kernels,
        drift_model=params.drift_model,
        high_pass=params.high_pass,
        confounds=confounds,
        confound_columns=confound_columns,
        t_r=t_r,
    )
    _, custom_fit, custom_r2 = _fit_ols(custom_design, roi_signal)

    comparison_summary: dict[str, object] | None = None
    comparison_fit = np.full_like(roi_signal, np.nan, dtype=float)
    if params.comparison_hrf_model:
        comparison_model = _normalize_hrf_model(params.comparison_hrf_model)
        if comparison_model == "flobs":
            comparison_design, basis_path = _build_flobs_design_matrix(
                frame_times,
                events,
                drift_model=params.drift_model,
                high_pass=params.high_pass,
                confounds=confounds,
                confound_columns=confound_columns,
                flobs_basis_file=params.flobs_basis_file,
                flobs_dt=params.flobs_dt,
            )
            used_basis = basis_path
        else:
            comparison_design = _build_standard_design(
                frame_times,
                events,
                hrf_model=comparison_model,
                fir_delays=params.fir_delays if comparison_model == "fir" else None,
                drift_model=params.drift_model,
                high_pass=params.high_pass,
                confounds=confounds,
                confound_columns=confound_columns,
            )
            used_basis = None
        _, comparison_fit, comparison_r2 = _fit_ols(comparison_design, roi_signal)
        comparison_summary = {
            "hrf_model": comparison_model,
            "r2": comparison_r2,
            "design_columns": list(comparison_design.columns),
            "flobs_basis_file": used_basis,
        }
        comparison_design.to_csv(
            output_dir / "comparison_design_matrix.tsv",
            sep="\t",
            index=False,
        )

    hrf_df = pd.DataFrame(hrf_rows)
    hrf_df["delay_s"] = hrf_df["delay_index"].astype(float) * t_r
    predictions_df = pd.DataFrame(
        {
            "time_s": frame_times,
            "roi_signal": roi_signal,
            "canonical_fit": canonical_fit,
            "custom_fit": custom_fit,
        }
    )
    if params.comparison_hrf_model:
        predictions_df["comparison_fit"] = comparison_fit

    outputs = {
        "estimated_hrf_tsv": str(output_dir / "estimated_hrf.tsv"),
        "predictions_tsv": str(output_dir / "hrf_refit_predictions.tsv"),
        "summary_json": str(output_dir / "hrf_refit_summary.json"),
        "fir_design_tsv": str(output_dir / "fir_design_matrix.tsv"),
        "canonical_design_tsv": str(output_dir / "canonical_design_matrix.tsv"),
        "custom_design_tsv": str(output_dir / "custom_design_matrix.tsv"),
    }

    hrf_df.to_csv(outputs["estimated_hrf_tsv"], sep="\t", index=False)
    predictions_df.to_csv(outputs["predictions_tsv"], sep="\t", index=False)
    fir_design.to_csv(outputs["fir_design_tsv"], sep="\t", index=False)
    canonical_design.to_csv(outputs["canonical_design_tsv"], sep="\t", index=False)
    custom_design.to_csv(outputs["custom_design_tsv"], sep="\t", index=False)

    summary = {
        "n_scans": int(n_scans),
        "t_r": float(t_r),
        "conditions": conditions,
        "fir_delays": list(params.fir_delays),
        "fir_estimation_r2": float(fir_r2),
        "canonical_refit_r2": float(canonical_r2),
        "custom_refit_r2": float(custom_r2),
        "comparison": comparison_summary,
        "confounds_columns": confound_columns,
    }
    Path(outputs["summary_json"]).write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    return {
        "outputs": outputs,
        "summary": summary,
        "message": (
            "Estimated ROI-level FIR HRFs and compared canonical versus refit models."
        ),
    }


__all__ = [
    "HRFEstimateAndRefitParameters",
    "hrf_estimate_and_refit_from_payload",
    "run_hrf_estimate_and_refit",
]
