#!/usr/bin/env python3
"""Compare alternative task-scoring grids for DMCC cognitive-control data.

This script consumes the harmonized DMCC task-level summary table and evaluates
many combinations of task-level scoring rules using exploratory measurement
diagnostics rather than CFA. The main question is pragmatic: which combination
of AX-CPT, Stroop, task-switching, and Sternberg scores produces the strongest
positive manifold?
"""

from __future__ import annotations

import argparse
import itertools
import json
import warnings
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
    / "task_level_summary.csv"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "score_grid"
    / "dmcc_behavior_only"
)

ID_COLUMNS = ["dataset", "participant_id", "session_id"]
TASK_ORDER = ["Axcpt", "Stroop", "Cuedts", "Stern"]
TASK_VARIABLE_NAMES = {
    "Axcpt": "axcpt",
    "Stroop": "stroop",
    "Cuedts": "taskswitch",
    "Stern": "sternberg",
}

TASK_SCORE_CANDIDATES: dict[str, dict[str, dict[str, Any]]] = {
    "Axcpt": {
        "dprime_context": {
            "column": "axcpt_dprime_context",
            "transform": "identity",
            "description": "AX hit vs BX false-alarm d-prime; higher is better.",
        },
        "ay_minus_bx_error": {
            "column": "axcpt_ay_minus_bx_error",
            "transform": "identity",
            "description": "AY error minus BX error; higher suggests more proactive control.",
        },
        "bx_by_ie": {
            "column": "raw_score_ie_cost",
            "transform": "identity",
            "description": "Negative BX-vs-BY inverse-efficiency cost; higher is better.",
        },
    },
    "Stroop": {
        "ie": {
            "column": "raw_score_ie_cost",
            "transform": "identity",
            "description": "Negative incongruent-vs-congruent inverse-efficiency cost.",
        },
        "rt": {
            "column": "control_rt_cost_s",
            "transform": "negate",
            "description": "Negative incongruent-vs-congruent RT cost.",
        },
        "accuracy": {
            "column": "control_accuracy_cost",
            "transform": "identity",
            "description": "Congruent minus incongruent accuracy; higher is better.",
        },
    },
    "Cuedts": {
        "ie": {
            "column": "raw_score_ie_cost",
            "transform": "identity",
            "description": "Negative switch-vs-repeat inverse-efficiency cost.",
        },
        "rt": {
            "column": "control_rt_cost_s",
            "transform": "negate",
            "description": "Negative switch-vs-repeat RT cost.",
        },
        "accuracy": {
            "column": "control_accuracy_cost",
            "transform": "identity",
            "description": "Repeat minus switch accuracy; higher is better.",
        },
    },
    "Stern": {
        "ie": {
            "column": "raw_score_ie_cost",
            "transform": "identity",
            "description": "Negative recent-negative-vs-novel-negative inverse-efficiency cost.",
        },
        "rt": {
            "column": "control_rt_cost_s",
            "transform": "negate",
            "description": "Negative recent-negative-vs-novel-negative RT cost.",
        },
        "accuracy": {
            "column": "control_accuracy_cost",
            "transform": "identity",
            "description": "Novel-negative minus recent-negative accuracy; higher is better.",
        },
    },
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


def _zscore_series(series: pd.Series) -> pd.Series:
    non_null = series.dropna()
    if len(non_null) < 2:
        return pd.Series(np.nan, index=series.index, dtype=float)
    std = float(non_null.std(ddof=0))
    if std == 0.0:
        return pd.Series(np.nan, index=series.index, dtype=float)
    mean = float(non_null.mean())
    return (series - mean) / std


def _cronbach_alpha(data: pd.DataFrame) -> float:
    k = data.shape[1]
    item_var_sum = float(data.var(axis=0, ddof=1).sum())
    total_var = float(data.sum(axis=1).var(ddof=1))
    if k < 2 or total_var == 0.0:
        return float("nan")
    return float((k / (k - 1.0)) * (1.0 - (item_var_sum / total_var)))


def _candidate_series(task_df: pd.DataFrame, task: str, candidate_name: str) -> pd.Series:
    candidate = TASK_SCORE_CANDIDATES[task][candidate_name]
    series = pd.to_numeric(task_df[candidate["column"]], errors="coerce")
    if candidate["transform"] == "negate":
        series = -series
    elif candidate["transform"] != "identity":
        raise ValueError(f"Unsupported transform: {candidate['transform']}")
    return series


def _orient_loadings(loadings: np.ndarray) -> np.ndarray:
    oriented = loadings.astype(float).copy()
    if np.nansum(oriented) < 0:
        oriented *= -1.0
    return oriented


def _build_wide_scores(
    task_level: pd.DataFrame,
    combo: dict[str, str],
) -> pd.DataFrame:
    wide: pd.DataFrame | None = None
    for task in TASK_ORDER:
        sub = task_level.loc[task_level["task"] == task, ID_COLUMNS].copy()
        raw_series = _candidate_series(
            task_level.loc[task_level["task"] == task], task, combo[task]
        )
        variable = TASK_VARIABLE_NAMES[task]
        sub[f"{variable}_raw"] = raw_series.to_numpy()
        if wide is None:
            wide = sub
        else:
            wide = wide.merge(sub, on=ID_COLUMNS, how="inner")

    if wide is None:
        raise RuntimeError("Failed to build wide score table.")

    raw_columns = [f"{TASK_VARIABLE_NAMES[task]}_raw" for task in TASK_ORDER]
    wide = wide.dropna(subset=raw_columns).copy()
    for column in raw_columns:
        z_column = column.replace("_raw", "_z")
        wide[z_column] = _zscore_series(wide[column])
    z_columns = [f"{TASK_VARIABLE_NAMES[task]}_z" for task in TASK_ORDER]
    return wide.dropna(subset=z_columns).copy()


def _pairwise_summary(data: pd.DataFrame) -> tuple[float, float]:
    corr = data.corr()
    mask = ~np.eye(len(corr), dtype=bool)
    values = corr.where(mask).stack()
    return float(values.mean()), float(values.min())


def _item_total_rows(data: pd.DataFrame, combo_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in data.columns:
        other_columns = [col for col in data.columns if col != column]
        other_mean = data[other_columns].mean(axis=1)
        rows.append(
            {
                "combo_id": combo_id,
                "variable": column,
                "item_total_r": float(data[column].corr(other_mean)),
            }
        )
    return rows


def _compute_combo_metrics(
    wide_scores: pd.DataFrame,
    combo_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    z_columns = [column for column in wide_scores.columns if column.endswith("_z")]
    data = wide_scores[z_columns].copy()

    avg_interitem_r, min_pairwise_r = _pairwise_summary(data)
    alpha = _cronbach_alpha(data)
    pca = PCA(n_components=min(data.shape[0], data.shape[1]), random_state=0)
    pca.fit(data.to_numpy())

    sklearn_fa = FactorAnalysis(n_components=1, random_state=0)
    sklearn_fa.fit(data.to_numpy())
    sklearn_loadings = _orient_loadings(sklearn_fa.components_.T[:, 0])

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        stats_factor = Factor(data, n_factor=1, method="ml").fit()
    stats_loadings = _orient_loadings(stats_factor.loadings[:, 0])
    stats_success = bool(getattr(stats_factor, "mle_retvals", {}).get("success", False))
    warning_messages = sorted({str(w.message) for w in caught_warnings})

    item_total_rows = _item_total_rows(data, combo_id)
    item_total_values = [row["item_total_r"] for row in item_total_rows]

    loading_rows: list[dict[str, Any]] = []
    for variable, value in zip(data.columns, sklearn_loadings):
        loading_rows.append(
            {
                "combo_id": combo_id,
                "method": "sklearn_fa",
                "variable": variable,
                "loading": float(value),
                "communality": None,
                "uniqueness": None,
            }
        )
    for idx, variable in enumerate(data.columns):
        loading_rows.append(
            {
                "combo_id": combo_id,
                "method": "statsmodels_ml",
                "variable": variable,
                "loading": float(stats_loadings[idx]),
                "communality": float(stats_factor.communality[idx]),
                "uniqueness": float(stats_factor.uniqueness[idx]),
            }
        )

    metrics = {
        "combo_id": combo_id,
        "n_complete_cases": int(len(data)),
        "cronbach_alpha": float(alpha),
        "avg_interitem_r": float(avg_interitem_r),
        "min_pairwise_r": float(min_pairwise_r),
        "pca_pc1_variance_ratio": float(pca.explained_variance_ratio_[0]),
        "item_total_r_mean": float(np.mean(item_total_values)),
        "item_total_r_min": float(np.min(item_total_values)),
        "sklearn_loading_mean": float(np.mean(sklearn_loadings)),
        "sklearn_loading_min": float(np.min(sklearn_loadings)),
        "sklearn_negative_loading_count": int(np.sum(sklearn_loadings < 0)),
        "statsmodels_loading_mean": float(np.mean(stats_loadings)),
        "statsmodels_loading_min": float(np.min(stats_loadings)),
        "statsmodels_negative_loading_count": int(np.sum(stats_loadings < 0)),
        "statsmodels_mle_success": stats_success,
        "statsmodels_warning_count": int(len(warning_messages)),
        "statsmodels_warnings_json": json.dumps(warning_messages),
    }
    return metrics, item_total_rows, loading_rows


def _rank_results(results: pd.DataFrame) -> pd.DataFrame:
    positive_metrics = [
        "cronbach_alpha",
        "avg_interitem_r",
        "min_pairwise_r",
        "pca_pc1_variance_ratio",
        "item_total_r_mean",
        "item_total_r_min",
        "statsmodels_loading_mean",
        "statsmodels_loading_min",
    ]
    negative_metrics = ["statsmodels_negative_loading_count"]

    ranked = results.copy()
    rank_columns: list[str] = []
    for column in positive_metrics:
        rank_col = f"rank_{column}"
        ranked[rank_col] = ranked[column].rank(method="min", ascending=False)
        rank_columns.append(rank_col)
    for column in negative_metrics:
        rank_col = f"rank_{column}"
        ranked[rank_col] = ranked[column].rank(method="min", ascending=True)
        rank_columns.append(rank_col)
    ranked["rank_statsmodels_mle_success"] = ranked["statsmodels_mle_success"].astype(int).rank(
        method="min", ascending=False
    )
    rank_columns.append("rank_statsmodels_mle_success")
    ranked["rank_statsmodels_warning_count"] = ranked["statsmodels_warning_count"].rank(
        method="min", ascending=True
    )
    rank_columns.append("rank_statsmodels_warning_count")
    ranked["composite_rank"] = ranked[rank_columns].sum(axis=1)
    return ranked.sort_values(
        by=[
            "composite_rank",
            "cronbach_alpha",
            "avg_interitem_r",
            "pca_pc1_variance_ratio",
        ],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


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
        description="Compare alternative DMCC score grids using exploratory diagnostics."
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help="Path to the DMCC task-level summary CSV.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for score-grid outputs.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="How many top combinations to write to the top-ranked CSV.",
    )
    args = parser.parse_args()

    input_csv = args.input_csv.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1.")

    task_level = pd.read_csv(input_csv)
    task_level = task_level.loc[task_level["task"].isin(TASK_ORDER)].copy()

    candidate_choices = {
        task: list(TASK_SCORE_CANDIDATES[task].keys()) for task in TASK_ORDER
    }

    result_rows: list[dict[str, Any]] = []
    item_total_rows: list[dict[str, Any]] = []
    loading_rows: list[dict[str, Any]] = []
    best_combo_scores: pd.DataFrame | None = None

    product_iter = itertools.product(*(candidate_choices[task] for task in TASK_ORDER))
    for choice_tuple in product_iter:
        combo = {task: choice for task, choice in zip(TASK_ORDER, choice_tuple)}
        combo_id = "|".join(f"{task}={combo[task]}" for task in TASK_ORDER)
        wide_scores = _build_wide_scores(task_level, combo)

        metrics, combo_item_totals, combo_loadings = _compute_combo_metrics(
            wide_scores, combo_id
        )
        for task in TASK_ORDER:
            metrics[f"{task.lower()}_score_choice"] = combo[task]
        result_rows.append(metrics)
        item_total_rows.extend(combo_item_totals)
        loading_rows.extend(combo_loadings)

        if best_combo_scores is None:
            best_combo_scores = wide_scores.copy()
            best_combo_scores["combo_id"] = combo_id

    results = pd.DataFrame.from_records(result_rows)
    ranked = _rank_results(results)
    top_ranked = ranked.head(args.top_k).copy()

    best_combo_id = str(ranked.iloc[0]["combo_id"])
    best_combo_choices = {
        task: str(ranked.iloc[0][f"{task.lower()}_score_choice"]) for task in TASK_ORDER
    }
    best_combo_scores = _build_wide_scores(task_level, best_combo_choices)
    best_combo_scores["combo_id"] = best_combo_id

    candidate_dictionary = {
        task: {
            name: {
                "source_column": spec["column"],
                "transform": spec["transform"],
                "description": spec["description"],
            }
            for name, spec in TASK_SCORE_CANDIDATES[task].items()
        }
        for task in TASK_ORDER
    }

    outputs = {
        "score_grid_results_csv": _write_csv(
            ranked, output_root / "score_grid_results.csv"
        ),
        "top_ranked_combinations_csv": _write_csv(
            top_ranked, output_root / "top_ranked_combinations.csv"
        ),
        "score_grid_item_totals_csv": _write_csv(
            pd.DataFrame.from_records(item_total_rows),
            output_root / "score_grid_item_totals.csv",
        ),
        "score_grid_loadings_csv": _write_csv(
            pd.DataFrame.from_records(loading_rows),
            output_root / "score_grid_loadings.csv",
        ),
        "best_combo_scores_csv": _write_csv(
            best_combo_scores, output_root / "best_combo_scores.csv"
        ),
        "candidate_dictionary_json": _write_json(
            candidate_dictionary, output_root / "candidate_dictionary.json"
        ),
    }

    summary = {
        "input_csv": str(input_csv),
        "n_combinations": int(len(ranked)),
        "top_k": int(args.top_k),
        "best_combo_id": best_combo_id,
        "best_combo_choices": best_combo_choices,
        "best_combo_metrics": {
            key: _clean_scalar(value)
            for key, value in ranked.iloc[0].to_dict().items()
            if not str(key).startswith("rank_")
        },
    }
    outputs["summary_json"] = _write_json(summary, output_root / "summary.json")

    manifest = {
        "input_csv": str(input_csv),
        "output_root": str(output_root),
        "n_combinations": int(len(ranked)),
        "outputs": outputs,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
