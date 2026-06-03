"""Shared helpers for Statsmodels GLM analysis."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests

try:  # Optional for p-value computation
    from scipy import stats as scipy_stats
except Exception:  # pragma: no cover - scipy may be missing in minimal envs
    scipy_stats = None


@dataclass(frozen=True)
class StatsmodelsGLMParameters:
    data_file: str
    design_matrix: str
    output_dir: str
    dependent_var: str | None = None
    mask_file: str | None = None
    formula: str | None = None
    family: str = "gaussian"
    link_function: str | None = None
    contrasts: dict[str, Sequence[float]] | None = None
    contrast_names: Sequence[str] | None = None
    alpha: float = 0.05
    correction_method: str = "fdr"
    fit_intercept: bool = True
    standardize: bool = False
    robust_covariance: bool = False
    regularization: str | None = None
    regularization_strength: float | None = None
    save_residuals: bool = True
    save_fitted: bool = True
    save_stats_maps: bool = True
    voxel_wise: bool = False
    smoothing_fwhm: float | None = None
    compute_diagnostics: bool = True
    plot_diagnostics: bool = True


def statsmodels_glm_from_payload(payload: dict[str, any]) -> StatsmodelsGLMParameters:
    return StatsmodelsGLMParameters(
        data_file=str(payload["data_file"]),
        design_matrix=str(payload["design_matrix"]),
        output_dir=str(payload["output_dir"]),
        dependent_var=payload.get("dependent_var"),
        mask_file=payload.get("mask_file"),
        formula=payload.get("formula"),
        family=str(payload.get("family", "gaussian")),
        link_function=payload.get("link_function"),
        contrasts=payload.get("contrasts"),
        contrast_names=payload.get("contrast_names"),
        alpha=float(payload.get("alpha", 0.05)),
        correction_method=str(payload.get("correction_method", "fdr")),
        fit_intercept=bool(payload.get("fit_intercept", True)),
        standardize=bool(payload.get("standardize", False)),
        robust_covariance=bool(payload.get("robust_covariance", False)),
        regularization=payload.get("regularization"),
        regularization_strength=payload.get("regularization_strength"),
        save_residuals=bool(payload.get("save_residuals", True)),
        save_fitted=bool(payload.get("save_fitted", True)),
        save_stats_maps=bool(payload.get("save_stats_maps", True)),
        voxel_wise=bool(payload.get("voxel_wise", False)),
        smoothing_fwhm=payload.get("smoothing_fwhm"),
        compute_diagnostics=bool(payload.get("compute_diagnostics", True)),
        plot_diagnostics=bool(payload.get("plot_diagnostics", True)),
    )


def _is_nifti(path: Path) -> bool:
    suffixes = [s.lower() for s in path.suffixes]
    return suffixes[-2:] == [".nii", ".gz"] or suffixes[-1:] == [".nii"]


def _load_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        sep = "\t" if suffix == ".tsv" else ","
        return pd.read_csv(path, sep=sep)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".npy", ".npz"}:
        data = np.load(path)
        if isinstance(data, np.lib.npyio.NpzFile):
            data = data[data.files[0]]
        arr = np.asarray(data)
        if arr.ndim == 1:
            arr = arr[:, None]
        columns = [f"x{i}" for i in range(arr.shape[1])]
        return pd.DataFrame(arr, columns=columns)
    return pd.read_csv(path, sep=None, engine="python")


def _numeric_df(df: pd.DataFrame) -> pd.DataFrame:
    numeric = df.select_dtypes(include=[np.number])
    if numeric.empty:
        raise ValueError("Design matrix has no numeric columns.")
    return numeric


def _resolve_family(name: str, link_name: str | None) -> sm.families.Family:
    name = name.lower()
    family_map = {
        "gaussian": sm.families.Gaussian,
        "poisson": sm.families.Poisson,
        "binomial": sm.families.Binomial,
        "gamma": sm.families.Gamma,
        "inverse_gaussian": sm.families.InverseGaussian,
        "negative_binomial": sm.families.NegativeBinomial,
    }
    family_cls = family_map.get(name, sm.families.Gaussian)
    if not link_name:
        return family_cls()
    link_name = link_name.lower()
    link_map = {
        "identity": sm.families.links.identity,
        "log": sm.families.links.log,
        "logit": sm.families.links.logit,
        "probit": sm.families.links.probit,
        "cloglog": sm.families.links.cloglog,
        "inverse": sm.families.links.inverse_power,
    }
    link_cls = link_map.get(link_name)
    return family_cls(link=link_cls()) if link_cls else family_cls()


def _standardize_design(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col.lower() in {"const", "intercept"}:
            continue
        std = df[col].std()
        if std == 0 or np.isnan(std):
            continue
        df[col] = (df[col] - df[col].mean()) / std
    return df


def _default_contrasts(
    columns: list[str], contrast_names: Sequence[str] | None
) -> dict[str, np.ndarray]:
    names = (
        list(contrast_names)
        if contrast_names
        else [c for c in columns if c.lower() not in {"const", "intercept"}]
    )
    contrasts: dict[str, np.ndarray] = {}
    for name in names:
        if name not in columns:
            continue
        vec = np.zeros(len(columns))
        vec[columns.index(name)] = 1.0
        contrasts[name] = vec
    return contrasts


def _apply_correction(pvals: np.ndarray, method: str) -> tuple[np.ndarray, np.ndarray]:
    method = method.lower()
    method_map = {
        "fdr": "fdr_bh",
        "fdr_bh": "fdr_bh",
        "bonferroni": "bonferroni",
        "holm": "holm",
    }
    adj_method = method_map.get(method, "fdr_bh")
    reject, pvals_corr, _, _ = multipletests(pvals, method=adj_method)
    return pvals_corr, reject


def _t_to_z(tvals: np.ndarray, df: float) -> np.ndarray:
    if scipy_stats is None:
        return tvals
    pvals = 2 * scipy_stats.t.sf(np.abs(tvals), df)
    zvals = scipy_stats.norm.isf(pvals / 2)
    zvals[np.isnan(zvals)] = 0.0
    return zvals


def run_statsmodels_glm(params: StatsmodelsGLMParameters) -> dict[str, any]:
    data_path = Path(params.data_file)
    design_path = Path(params.design_matrix)
    if params.mask_file:
        Path(params.mask_file)

    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    is_nifti = _is_nifti(data_path)
    voxel_wise = params.voxel_wise or is_nifti

    outputs: dict[str, str | None | list[str]] = {
        "summary": str(output_dir / "glm_summary.json"),
        "residuals": None,
        "fitted": None,
        "stat_map": None,
        "stat_maps": [],
    }

    if voxel_wise:
        if not is_nifti:
            raise ValueError("voxel_wise=True requires a NIfTI data_file")

        img = nib.load(str(data_path))
        data = np.asarray(img.get_fdata())
        if data.ndim != 4:
            raise ValueError("Voxel-wise GLM expects a 4D NIfTI file")
        n_time = data.shape[3]

        if params.mask_file:
            mask_data = np.asarray(nib.load(params.mask_file).get_fdata()) > 0
        else:
            mask_data = np.abs(data).mean(axis=3) > 0
        mask_flat = mask_data.reshape(-1)
        y = data.reshape(-1, n_time).T
        y = y[:, mask_flat]

        design_df = _numeric_df(_load_table(design_path))
        if len(design_df) != n_time:
            raise ValueError("Design matrix rows must match number of timepoints")

        if params.fit_intercept and "const" not in design_df.columns:
            design_df = sm.add_constant(design_df, has_constant="add")
        if params.standardize:
            design_df = _standardize_design(design_df)

        x = design_df.to_numpy()
        xtx_inv = np.linalg.pinv(x.T @ x)
        betas = xtx_inv @ x.T @ y
        fitted = x @ betas
        resid = y - fitted
        df_resid = max(n_time - x.shape[1], 1)
        sigma2 = (resid**2).sum(axis=0) / df_resid

        contrast_defs = params.contrasts or _default_contrasts(
            list(design_df.columns), params.contrast_names
        )
        stat_maps: list[str] = []
        for name, contrast in contrast_defs.items():
            c = np.asarray(contrast, dtype=float)
            if c.ndim != 1 or c.size != x.shape[1]:
                raise ValueError(
                    f"Contrast {name} has wrong length (expected {x.shape[1]})"
                )
            denom = np.sqrt(np.maximum(sigma2 * (c @ xtx_inv @ c), 1e-12))
            tvals = (c @ betas) / denom
            zvals = _t_to_z(tvals, df_resid)
            vol = np.zeros(mask_flat.shape[0], dtype=float)
            vol[mask_flat] = zvals
            vol = vol.reshape(mask_data.shape)
            zmap = nib.Nifti1Image(vol, img.affine, img.header)
            zmap_path = output_dir / f"{name}_zmap.nii.gz"
            zmap.to_filename(zmap_path)
            stat_maps.append(str(zmap_path))

        if params.save_stats_maps:
            outputs["stat_maps"] = stat_maps
            outputs["stat_map"] = stat_maps[0] if stat_maps else None

        if params.save_residuals:
            residuals_path = output_dir / "residuals.npy"
            np.save(residuals_path, resid)
            outputs["residuals"] = str(residuals_path)

        if params.save_fitted:
            fitted_path = output_dir / "fitted.npy"
            np.save(fitted_path, fitted)
            outputs["fitted"] = str(fitted_path)

        summary = {
            "family": params.family,
            "voxel_wise": True,
            "n_timepoints": int(n_time),
            "n_voxels": int(mask_flat.sum()),
            "design_columns": list(design_df.columns),
            "contrasts": list(contrast_defs.keys()),
            "used_statsmodels": False,
            "used_manual_ols": True,
        }
    else:
        data_df = _load_table(data_path)
        design_df = _numeric_df(_load_table(design_path))

        if params.formula:
            combined = data_df.copy()
            for col in design_df.columns:
                if col not in combined.columns:
                    combined[col] = design_df[col].values
            family = _resolve_family(params.family, params.link_function)
            model = smf.glm(formula=params.formula, data=combined, family=family)
            results = model.fit()
            y = model.endog
            exog = pd.DataFrame(model.exog, columns=model.exog_names)
        else:
            if params.dependent_var and params.dependent_var in data_df.columns:
                y_series = data_df[params.dependent_var]
            elif "y" in data_df.columns:
                y_series = data_df["y"]
            else:
                y_series = data_df.iloc[:, 0]

            if y_series.name in design_df.columns:
                design_df = design_df.drop(columns=[y_series.name])
            if params.fit_intercept and "const" not in design_df.columns:
                design_df = sm.add_constant(design_df, has_constant="add")
            if params.standardize:
                design_df = _standardize_design(design_df)

            if len(design_df) != len(y_series):
                raise ValueError("Design matrix rows must match data rows")

            family = _resolve_family(params.family, params.link_function)
            model = sm.GLM(y_series, design_df, family=family)
            if params.regularization:
                strength = params.regularization_strength or 0.1
                l1_wt = 1.0 if params.regularization.lower() == "l1" else 0.0
                if params.regularization.lower() == "elasticnet":
                    l1_wt = 0.5
                results = model.fit_regularized(alpha=strength, L1_wt=l1_wt)
            else:
                if params.robust_covariance:
                    results = model.fit(cov_type="HC3")
                else:
                    results = model.fit()

            y = y_series.to_numpy()
            exog = design_df

        resid = np.asarray(results.resid_response)
        fitted = np.asarray(results.fittedvalues)

        if params.save_residuals:
            residuals_path = output_dir / "residuals.npy"
            np.save(residuals_path, resid)
            outputs["residuals"] = str(residuals_path)

        if params.save_fitted:
            fitted_path = output_dir / "fitted.npy"
            np.save(fitted_path, fitted)
            outputs["fitted"] = str(fitted_path)

        contrast_defs = params.contrasts or _default_contrasts(
            list(exog.columns), params.contrast_names
        )
        contrast_results = []
        for name, contrast in contrast_defs.items():
            try:
                test = results.t_test(contrast)
                contrast_results.append(
                    {
                        "name": name,
                        "tvalue": float(np.squeeze(test.tvalue)),
                        "pvalue": float(np.squeeze(test.pvalue)),
                    }
                )
            except Exception:
                continue

        if contrast_results and params.correction_method:
            pvals = np.array([c["pvalue"] for c in contrast_results], dtype=float)
            pvals_corr, reject = _apply_correction(pvals, params.correction_method)
            for idx, corr in enumerate(pvals_corr):
                contrast_results[idx]["pvalue_corrected"] = float(corr)
                contrast_results[idx]["reject_null"] = bool(reject[idx])

        params_values = results.params
        pvalues_values = getattr(results, "pvalues", None)
        if hasattr(params_values, "to_dict"):
            params_dict = {k: float(v) for k, v in params_values.to_dict().items()}
        else:
            params_dict = {
                col: float(val)
                for col, val in zip(
                    exog.columns, np.asarray(params_values), strict=False
                )
            }
        if pvalues_values is None:
            pvalues_dict = {}
        elif hasattr(pvalues_values, "to_dict"):
            pvalues_dict = {k: float(v) for k, v in pvalues_values.to_dict().items()}
        else:
            pvalues_dict = {
                col: float(val)
                for col, val in zip(
                    exog.columns, np.asarray(pvalues_values), strict=False
                )
            }

        summary = {
            "family": params.family,
            "voxel_wise": False,
            "n_obs": int(len(y)),
            "design_columns": list(exog.columns),
            "params": params_dict,
            "pvalues": pvalues_dict,
            "aic": float(results.aic) if hasattr(results, "aic") else None,
            "bic": float(results.bic) if hasattr(results, "bic") else None,
            "contrasts": contrast_results,
            "used_statsmodels": True,
            "used_manual_ols": False,
        }

    summary_path = Path(outputs["summary"])
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Statsmodels GLM completed.",
    }


__all__ = [
    "StatsmodelsGLMParameters",
    "statsmodels_glm_from_payload",
    "run_statsmodels_glm",
]
