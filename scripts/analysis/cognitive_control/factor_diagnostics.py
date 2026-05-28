#!/usr/bin/env python3
"""Run exploratory factor diagnostics for harmonized cognitive-control data.

This script is the next-step diagnostic companion to the DMCC harmonization and
small CFA entrypoints. It is intended to answer a practical measurement
question: do the current task scores show a usable positive manifold before we
spend effort interpreting CFA results?

The first supported model is the reduced DMCC task set:
- dmcc_stroop_v
- dmcc_axcpt_v
- dmcc_taskswitch_v
- dmcc_sternberg_v
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.decomposition import FactorAnalysis, PCA
from statsmodels.multivariate.factor import Factor


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_CSV = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "harmonized_behavior"
    / "dmcc_behavior_only"
    / "behavior_harmonized.csv"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "factor_diagnostics"
    / "dmcc_behavior_only"
)

MODEL_SPECS: dict[str, dict[str, Any]] = {
    "dmcc_unity": {
        "columns": [
            "dmcc_stroop_v",
            "dmcc_axcpt_v",
            "dmcc_taskswitch_v",
            "dmcc_sternberg_v",
        ],
        "factor_names": ["f1"],
    }
}


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean_scalar(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_scalar(item) for item in value]
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _clean_scalar(value.item())
        return [_clean_scalar(item) for item in value.tolist()]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _cronbach_alpha(data: pd.DataFrame) -> float:
    k = data.shape[1]
    item_var_sum = float(data.var(axis=0, ddof=1).sum())
    total_var = float(data.sum(axis=1).var(ddof=1))
    if k < 2 or total_var == 0.0:
        return float("nan")
    return float((k / (k - 1.0)) * (1.0 - (item_var_sum / total_var)))


def _item_total_frame(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for column in data.columns:
        other_columns = [col for col in data.columns if col != column]
        other_mean = data[other_columns].mean(axis=1)
        rows.append(
            {
                "variable": column,
                "item_total_r": float(data[column].corr(other_mean)),
                "mean": float(data[column].mean()),
                "sd": float(data[column].std(ddof=1)),
                "min": float(data[column].min()),
                "max": float(data[column].max()),
            }
        )
    return pd.DataFrame.from_records(rows)


def _descriptive_frame(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for column in data.columns:
        rows.append(
            {
                "variable": column,
                "n": int(data[column].notna().sum()),
                "mean": float(data[column].mean()),
                "sd": float(data[column].std(ddof=1)),
                "min": float(data[column].min()),
                "q25": float(data[column].quantile(0.25)),
                "median": float(data[column].median()),
                "q75": float(data[column].quantile(0.75)),
                "max": float(data[column].max()),
            }
        )
    return pd.DataFrame.from_records(rows)


def _sklearn_fa_loadings(data: pd.DataFrame, n_factors: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    model = FactorAnalysis(n_components=n_factors, random_state=0)
    scores = model.fit_transform(data.to_numpy())
    loadings = pd.DataFrame(
        model.components_.T,
        index=data.columns,
        columns=[f"factor_{idx + 1}" for idx in range(n_factors)],
    )
    loadings.index.name = "variable"
    score_frame = pd.DataFrame(
        scores,
        index=data.index,
        columns=[f"factor_{idx + 1}" for idx in range(n_factors)],
    )
    return loadings.reset_index(), score_frame


def _statsmodels_factor(
    data: pd.DataFrame,
    n_factors: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    model = Factor(data, n_factor=n_factors, method="ml")
    result = model.fit()

    loadings = pd.DataFrame(
        result.loadings,
        index=data.columns,
        columns=[f"factor_{idx + 1}" for idx in range(n_factors)],
    )
    loadings.index.name = "variable"
    loadings["communality"] = result.communality
    loadings["uniqueness"] = result.uniqueness

    scores = result.factor_scoring(method="regression")
    score_frame = pd.DataFrame(
        scores,
        index=data.index,
        columns=[f"factor_{idx + 1}" for idx in range(n_factors)],
    )

    summary = {
        "n_factors": n_factors,
        "n_obs": int(result.nobs),
        "df": int(result.df),
        "fa_method": str(result.fa_method),
        "rotation_method": _clean_scalar(result.rotation_method),
        "mle_retvals": {
            str(key): _clean_scalar(value)
            for key, value in getattr(result, "mle_retvals", {}).items()
        },
    }
    return summary, loadings.reset_index(), score_frame


def _pca_outputs(data: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    n_components = min(data.shape[0], data.shape[1])
    model = PCA(n_components=n_components, random_state=0)
    scores = model.fit_transform(data.to_numpy())

    pca_summary = {
        "n_components": int(n_components),
        "explained_variance_ratio": [float(value) for value in model.explained_variance_ratio_],
        "explained_variance": [float(value) for value in model.explained_variance_],
        "singular_values": [float(value) for value in model.singular_values_],
    }

    loadings = pd.DataFrame(
        model.components_.T,
        index=data.columns,
        columns=[f"pc_{idx + 1}" for idx in range(n_components)],
    )
    loadings.index.name = "variable"

    score_frame = pd.DataFrame(
        scores,
        index=data.index,
        columns=[f"pc_{idx + 1}" for idx in range(n_components)],
    )
    return pca_summary, loadings.reset_index(), score_frame


def _write_csv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return str(path)


def _write_json(payload: dict[str, Any], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run exploratory factor diagnostics on harmonized cognitive-control scores."
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help="Path to the harmonized behavioral CSV.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for diagnostic outputs.",
    )
    parser.add_argument(
        "--model-name",
        choices=sorted(MODEL_SPECS),
        default="dmcc_unity",
        help="Named variable set to analyze.",
    )
    parser.add_argument(
        "--n-factors",
        type=int,
        default=1,
        help="Number of exploratory factors to estimate.",
    )
    args = parser.parse_args()

    input_csv = args.input_csv.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    if args.n_factors < 1:
        raise ValueError("--n-factors must be at least 1.")

    spec = MODEL_SPECS[args.model_name]
    columns = list(spec["columns"])
    raw_df = pd.read_csv(input_csv)
    data = raw_df[columns].dropna().copy()
    if data.empty:
        raise RuntimeError("No complete cases remain for the requested columns.")

    sample_summary = {
        "model_name": args.model_name,
        "input_csv": str(input_csv),
        "n_rows_input": int(len(raw_df)),
        "n_rows_complete_cases": int(len(data)),
        "columns": columns,
        "n_factors": int(args.n_factors),
        "cronbach_alpha": _clean_scalar(_cronbach_alpha(data)),
        "average_interitem_correlation": _clean_scalar(
            data.corr().where(~np.eye(len(columns), dtype=bool)).stack().mean()
        ),
    }

    descriptive = _descriptive_frame(data)
    correlations = data.corr().reset_index().rename(columns={"index": "variable"})
    item_total = _item_total_frame(data)

    pca_summary, pca_loadings, pca_scores = _pca_outputs(data)
    sklearn_loadings, sklearn_scores = _sklearn_fa_loadings(data, n_factors=args.n_factors)
    statsmodels_summary, statsmodels_loadings, statsmodels_scores = _statsmodels_factor(
        data, n_factors=args.n_factors
    )

    outputs = {
        "sample_summary_json": _write_json(
            sample_summary, output_root / "sample_summary.json"
        ),
        "pca_summary_json": _write_json(pca_summary, output_root / "pca_summary.json"),
        "statsmodels_factor_summary_json": _write_json(
            statsmodels_summary, output_root / "statsmodels_factor_summary.json"
        ),
        "descriptive_stats_csv": _write_csv(
            descriptive, output_root / "descriptive_stats.csv"
        ),
        "correlation_matrix_csv": _write_csv(
            correlations, output_root / "correlation_matrix.csv"
        ),
        "item_total_statistics_csv": _write_csv(
            item_total, output_root / "item_total_statistics.csv"
        ),
        "pca_loadings_csv": _write_csv(pca_loadings, output_root / "pca_loadings.csv"),
        "pca_scores_csv": _write_csv(
            pca_scores.reset_index(drop=True), output_root / "pca_scores.csv"
        ),
        "sklearn_fa_loadings_csv": _write_csv(
            sklearn_loadings, output_root / "sklearn_fa_loadings.csv"
        ),
        "sklearn_fa_scores_csv": _write_csv(
            sklearn_scores.reset_index(drop=True), output_root / "sklearn_fa_scores.csv"
        ),
        "statsmodels_factor_loadings_csv": _write_csv(
            statsmodels_loadings, output_root / "statsmodels_factor_loadings.csv"
        ),
        "statsmodels_factor_scores_csv": _write_csv(
            statsmodels_scores.reset_index(drop=True),
            output_root / "statsmodels_factor_scores.csv",
        ),
    }

    manifest = {
        "model_name": args.model_name,
        "input_csv": str(input_csv),
        "output_root": str(output_root),
        "n_factors": int(args.n_factors),
        "outputs": outputs,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
