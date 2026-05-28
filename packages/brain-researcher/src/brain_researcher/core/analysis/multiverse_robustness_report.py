"""Multiverse robustness reporting utilities.

This module provides lightweight, deterministic summaries for "multiverse"
analyses: how stable an effect is across analytic variations, which choices
drive variability, and actionable "stable vs caution" statements.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def load_fitlins_multiverse_manifest(manifest_json: str | Path) -> pd.DataFrame:
    """Load FitLins multiverse manifest.json into a flat table.

    Expected schema (current BR):
    {"dataset_id": str, "task": str, "variants": [ {model_id, variant_id, ...} ]}
    """
    path = Path(manifest_json)
    payload = json.loads(path.read_text())
    variants = payload.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    rows: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        row: dict[str, Any] = {
            "model_id": variant.get("model_id"),
            "variant_id": variant.get("variant_id"),
            "hrf": variant.get("hrf"),
            "confounds": variant.get("confounds"),
            "high_pass": variant.get("high_pass"),
        }
        families = variant.get("confounds_families")
        if isinstance(families, dict):
            for key, val in families.items():
                row[str(key)] = bool(val)
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["model_id"] = df["model_id"].astype(str)
    if "variant_id" in df.columns:
        df["variant_id"] = df["variant_id"].astype(str)
    return df


def load_multiverse_summary_csv(summary_csv: str | Path) -> pd.DataFrame:
    """Load the Yeo17 multiverse summary CSV produced by ingest scripts."""
    df = pd.read_csv(summary_csv)
    for col in ("model_id", "variant_id", "contrast", "metric", "region_id"):
        if col in df.columns:
            df[col] = df[col].astype(str)
    for col in ("value", "pct_active", "z_thr", "n_vox"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _sorted_unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for val in values:
        if pd.isna(val):
            continue
        key = json.dumps(val, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(val)
    try:
        return sorted(out)
    except Exception:
        return out


def _eta_squared(y: np.ndarray, groups: np.ndarray) -> float:
    y = y.astype(float)
    mask = ~np.isnan(y)
    y = y[mask]
    groups = groups[mask]
    if y.size < 2:
        return 0.0

    mean_total = float(np.mean(y))
    ss_total = float(np.sum((y - mean_total) ** 2))
    if ss_total <= 0:
        return 0.0

    ss_between = 0.0
    for level in np.unique(groups):
        idx = groups == level
        if not np.any(idx):
            continue
        y_level = y[idx]
        ss_between += float(y_level.size) * float((np.mean(y_level) - mean_total) ** 2)
    return float(ss_between / ss_total)


def compute_axis_sensitivity(
    pipeline_df: pd.DataFrame,
    *,
    effect_col: str,
    axes: Iterable[str],
) -> dict[str, float]:
    """Compute per-axis variance attribution (η²) for a pipeline table."""
    if pipeline_df.empty or effect_col not in pipeline_df.columns:
        return {}
    y = pipeline_df[effect_col].to_numpy(dtype=float)
    scores: dict[str, float] = {}
    for axis in axes:
        if axis not in pipeline_df.columns:
            continue
        groups = pipeline_df[axis].astype(str).to_numpy()
        if len(pd.unique(groups)) < 2:
            continue
        scores[axis] = _eta_squared(y, groups)
    return scores


def compute_pairwise_pattern_correlations(
    summary_df: pd.DataFrame,
    *,
    contrast: str,
    metric: str,
    regions: Iterable[str] | None = None,
) -> dict[str, float | None]:
    """Compute pairwise pipeline correlations over region patterns (best effort)."""
    df = summary_df.copy()
    df = df[(df["contrast"] == contrast) & (df["metric"] == metric)]
    if regions is not None:
        regions_set = {str(r) for r in regions}
        df = df[df["region_id"].astype(str).isin(regions_set)]
    if df.empty:
        return {"pairwise_corr_mean": None, "pairwise_corr_min": None}

    pivot = (
        df.groupby(["model_id", "variant_id", "region_id"], as_index=False)["value"]
        .mean()
        .pivot_table(
            index=["model_id", "variant_id"],
            columns="region_id",
            values="value",
            aggfunc="mean",
        )
    )
    if pivot.shape[0] < 2:
        return {"pairwise_corr_mean": None, "pairwise_corr_min": None}

    mat = pivot.to_numpy(dtype=float)
    keep = ~np.all(np.isnan(mat), axis=0)
    mat = mat[:, keep]
    if mat.shape[1] < 2:
        return {"pairwise_corr_mean": None, "pairwise_corr_min": None}

    col_means = np.nanmean(mat, axis=0)
    inds = np.where(np.isnan(mat))
    if inds[0].size:
        mat[inds] = col_means[inds[1]]

    corr = np.corrcoef(mat)
    iu = np.triu_indices_from(corr, k=1)
    vals = corr[iu]
    if vals.size == 0:
        return {"pairwise_corr_mean": None, "pairwise_corr_min": None}
    return {
        "pairwise_corr_mean": float(np.mean(vals)),
        "pairwise_corr_min": float(np.min(vals)),
    }


def _analysis_space_from_variants(
    variants_df: pd.DataFrame,
    *,
    fixed_thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if variants_df.empty:
        return {
            "n_pipelines": 0,
            "axes": {},
            "n_factorial": 0,
            "fixed": dict(fixed_thresholds or {}),
        }

    axes: dict[str, dict[str, Any]] = {}
    for axis in variants_df.columns:
        if axis in {"model_id", "variant_id"}:
            continue
        levels = _sorted_unique(variants_df[axis].dropna().tolist())
        if not levels:
            continue
        axes[axis] = {
            "levels": levels,
            "n_levels": len(levels),
        }

    n_factorial = 1
    for meta in axes.values():
        n = int(meta.get("n_levels", 0))
        if n > 1:
            n_factorial *= n
    return {
        "n_pipelines": int(
            variants_df[["model_id", "variant_id"]].drop_duplicates().shape[0]
        ),
        "axes": axes,
        "n_factorial": int(n_factorial),
        "fixed": dict(fixed_thresholds or {}),
    }


def _pick_default_contrast(summary_df: pd.DataFrame) -> str | None:
    if summary_df.empty or "contrast" not in summary_df.columns:
        return None
    counts = summary_df["contrast"].value_counts(dropna=True)
    if counts.empty:
        return None
    return str(counts.index[0])


def _pick_default_region(
    summary_df: pd.DataFrame,
    *,
    contrast: str,
    metric: str,
) -> str | None:
    df = summary_df[
        (summary_df["contrast"] == contrast) & (summary_df["metric"] == metric)
    ]
    if df.empty:
        return None
    agg = (
        df.groupby(["region_id", "model_id", "variant_id"], as_index=False)["value"]
        .mean()
        .groupby("region_id", as_index=False)["value"]
        .mean()
    )
    if agg.empty:
        return None
    agg["abs"] = agg["value"].abs()
    best = agg.sort_values("abs", ascending=False).iloc[0]
    return str(best["region_id"])


def _format_axis_label(axis: str) -> str:
    mapping = {
        "hrf": "HRF",
        "confounds": "Motion/confounds",
        "high_pass": "High-pass",
        "confounds_global_signal": "GSR",
        "confounds_aroma": "ICA-AROMA",
        "confounds_scrub_motion_outliers": "FD scrub",
        "confounds_motion_24": "24MP",
        "confounds_motion_6": "6MP",
    }
    return mapping.get(axis, axis)


def build_multiverse_robustness_report(
    summary_df: pd.DataFrame,
    *,
    variants_df: pd.DataFrame | None = None,
    claim: str | None = None,
    contrast: str | None = None,
    metric: str = "mean_z",
    region_id: str | None = None,
    active_threshold: float = 0.0,
) -> dict[str, Any]:
    """Compute a robustness report payload (no plotting)."""
    if contrast is None:
        contrast = _pick_default_contrast(summary_df)
    if contrast is None:
        raise ValueError("No contrasts found in summary table.")

    if region_id is None:
        region_id = _pick_default_region(summary_df, contrast=contrast, metric=metric)
    if region_id is None:
        raise ValueError("No regions found for requested contrast/metric.")

    df = summary_df.copy()
    df = df[
        (df["contrast"] == contrast)
        & (df["metric"] == metric)
        & (df["region_id"] == region_id)
    ]
    if df.empty:
        raise ValueError("No rows found for requested (contrast, metric, region_id).")

    pipeline_effect = (
        df.groupby(["model_id", "variant_id"], as_index=False)
        .agg(
            effect_value=("value", "mean"),
            pct_active=("pct_active", "mean"),
            z_thr=("z_thr", "max"),
            n_obs=("value", "count"),
        )
        .sort_values(["model_id", "variant_id"])
    )
    pipeline_effect["active"] = pipeline_effect["pct_active"].fillna(0.0) > float(
        active_threshold
    )

    pipeline_joined = pipeline_effect.copy()
    if variants_df is not None and not variants_df.empty:
        vdf = variants_df.copy()
        for col in ("model_id", "variant_id"):
            if col in vdf.columns:
                vdf[col] = vdf[col].astype(str)
        pipeline_joined = pipeline_joined.merge(
            vdf,
            how="left",
            on=["model_id", "variant_id"],
            suffixes=("", "_meta"),
        )

    y = pipeline_joined["effect_value"].to_numpy(dtype=float)
    pos = float(np.mean(y > 0)) if y.size else 0.0
    neg = float(np.mean(y < 0)) if y.size else 0.0
    sign_consistency = float(max(pos, neg))
    active_frac = float(np.mean(pipeline_joined["active"])) if y.size else 0.0

    fixed_thresholds: dict[str, Any] = {}
    z_thr_vals = _sorted_unique(df["z_thr"].dropna().tolist())
    if z_thr_vals:
        fixed_thresholds["z_thr"] = (
            z_thr_vals[0] if len(z_thr_vals) == 1 else z_thr_vals
        )

    analysis_space = (
        _analysis_space_from_variants(variants_df, fixed_thresholds=fixed_thresholds)
        if variants_df is not None
        else {
            "n_pipelines": int(pipeline_effect.shape[0]),
            "axes": {},
            "n_factorial": None,
            "fixed": fixed_thresholds,
        }
    )

    axis_candidates = [
        "hrf",
        "confounds",
        "high_pass",
        "confounds_global_signal",
        "confounds_aroma",
        "confounds_scrub_motion_outliers",
    ]
    sensitivity = compute_axis_sensitivity(
        pipeline_joined,
        effect_col="effect_value",
        axes=[a for a in axis_candidates if a in pipeline_joined.columns],
    )
    sens_sum = float(sum(sensitivity.values()))
    sensitivity_norm = (
        {k: (v / sens_sum if sens_sum > 0 else 0.0) for k, v in sensitivity.items()}
        if sensitivity
        else {}
    )

    corr_stats = compute_pairwise_pattern_correlations(
        summary_df,
        contrast=contrast,
        metric=metric,
    )

    stable_lines: list[str] = []
    caution_lines: list[str] = []

    n_pipes = int(pipeline_joined.shape[0])
    effect_mean = float(np.nanmean(y)) if y.size else float("nan")
    effect_std = float(np.nanstd(y)) if y.size else float("nan")
    rel_std = (
        float(effect_std / abs(effect_mean))
        if effect_mean and not math.isnan(effect_mean)
        else None
    )

    if n_pipes < 2:
        caution_lines.append(
            "Only one pipeline variant available; robustness cannot be assessed."
        )
    else:
        if sign_consistency >= 0.9:
            stable_lines.append(
                f"Effect direction is consistent in {sign_consistency:.0%} of pipelines."
            )
        elif sign_consistency >= 0.75:
            caution_lines.append(
                f"Effect direction flips in ~{(1 - sign_consistency):.0%} of pipelines."
            )
        else:
            caution_lines.append("Effect direction is unstable across pipelines.")

        if active_frac >= 0.8:
            stable_lines.append(
                f"Supra-threshold activity is present in {active_frac:.0%} of pipelines."
            )
        else:
            caution_lines.append(
                f"Supra-threshold activity is present in only {active_frac:.0%} of pipelines."
            )

        if rel_std is not None and rel_std <= 0.5:
            stable_lines.append(
                "Effect magnitude variability is modest across pipelines."
            )
        elif rel_std is not None and rel_std > 0.5:
            caution_lines.append(
                "Effect magnitude varies substantially across pipelines."
            )

        pc_mean = corr_stats.get("pairwise_corr_mean")
        if isinstance(pc_mean, float) and pc_mean >= 0.6:
            stable_lines.append("Regional pattern similarity is high across pipelines.")
        elif isinstance(pc_mean, float) and pc_mean < 0.4:
            caution_lines.append("Regional pattern similarity is low across pipelines.")

    if sensitivity_norm:
        top_axis = max(sensitivity_norm.items(), key=lambda kv: kv[1])[0]
        top_share = float(sensitivity_norm[top_axis])
        if top_share >= 0.35:
            caution_lines.append(
                f"Result is sensitive to {_format_axis_label(top_axis)} choices."
            )
        if (
            "confounds_global_signal" in sensitivity_norm
            and sensitivity_norm["confounds_global_signal"] >= 0.15
        ):
            caution_lines.append("Recommendation: report results with and without GSR.")

    return {
        "input": {
            "claim": claim,
            "contrast": contrast,
            "metric": metric,
            "region_id": region_id,
        },
        "analysis_space": analysis_space,
        "effect_distribution": {
            "n_pipelines": int(n_pipes),
            "pipelines": pipeline_joined.to_dict(orient="records"),
        },
        "sensitivity": {
            "eta2": sensitivity,
            "eta2_norm": sensitivity_norm,
            "axis_labels": {k: _format_axis_label(k) for k in sensitivity},
        },
        "stability": {
            "effect_mean": effect_mean,
            "effect_std": effect_std,
            "sign_consistency": sign_consistency,
            "active_frac": active_frac,
            **corr_stats,
            "stable": stable_lines,
            "caution": caution_lines,
        },
    }
