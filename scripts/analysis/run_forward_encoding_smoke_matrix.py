#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import Ridge


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def weighted_mean(vectors: np.ndarray, weights: np.ndarray) -> np.ndarray:
    w = weights.astype(np.float64)
    wsum = float(w.sum())
    if wsum <= 1e-12:
        return vectors.mean(axis=0)
    return (w[:, None] * vectors).sum(axis=0) / wsum


def combo_aggregate(df: pd.DataFrame, X: np.ndarray, Y: np.ndarray) -> pd.DataFrame:
    rows = []
    for (canonical_task, task_raw, contrast), g in df.groupby(
        ["canonical_task", "task_raw", "contrast"], sort=True
    ):
        idx = g.index.to_numpy()
        ds_mode = g["dataset"].mode()
        dataset = str(ds_mode.iloc[0]) if not ds_mode.empty else ""
        rows.append(
            {
                "canonical_task": str(canonical_task),
                "task_raw": str(task_raw),
                "contrast": str(contrast),
                "dataset": dataset,
                "n_maps": int(len(idx)),
                "x": X[idx].mean(axis=0),
                "y": Y[idx].mean(axis=0),
            }
        )
    return pd.DataFrame(rows)


def eval_combo_loto(
    fe,
    combo_df: pd.DataFrame,
    ridge_alpha: float,
    y_mode: str,
    n_components: int = 32,
) -> tuple[pd.DataFrame, dict]:
    rows = []
    tasks = sorted(combo_df["canonical_task"].unique())

    for task in tasks:
        test = combo_df[combo_df["canonical_task"] == task].copy()
        train = combo_df[combo_df["canonical_task"] != task].copy()
        if len(test) == 0 or len(train) < 10:
            continue

        Xtr = np.stack(train["x"].to_numpy())
        Ytr = np.stack(train["y"].to_numpy())
        Wtr = np.sqrt(train["n_maps"].to_numpy(dtype=float))

        Xte = np.stack(test["x"].to_numpy())
        Yte = np.stack(test["y"].to_numpy())

        ds_means = {}
        for ds, g in train.groupby("dataset"):
            yg = np.stack(g["y"].to_numpy())
            wg = np.sqrt(g["n_maps"].to_numpy(dtype=float))
            ds_means[str(ds)] = weighted_mean(yg, wg)

        global_mu = weighted_mean(Ytr, Wtr)

        if y_mode == "abs_voxel":
            model = Ridge(alpha=ridge_alpha, fit_intercept=True)
            model.fit(Xtr, Ytr, sample_weight=Wtr)
            Yhat = model.predict(Xte)
            baselines = np.repeat(global_mu[None, :], len(test), axis=0)
        elif y_mode == "residual_voxel":
            Ytr_res = np.empty_like(Ytr)
            for i, (_, r) in enumerate(train.iterrows()):
                Ytr_res[i] = Ytr[i] - ds_means.get(str(r["dataset"]), global_mu)

            model = Ridge(alpha=ridge_alpha, fit_intercept=True)
            model.fit(Xtr, Ytr_res, sample_weight=Wtr)
            Yhat_res = model.predict(Xte)

            Yhat = np.empty_like(Yhat_res)
            baselines = np.empty_like(Yhat_res)
            for i, (_, r) in enumerate(test.iterrows()):
                base = ds_means.get(str(r["dataset"]), global_mu)
                Yhat[i] = base + Yhat_res[i]
                baselines[i] = base
        elif y_mode == "residual_lowrank32":
            Ytr_res = np.empty_like(Ytr)
            for i, (_, r) in enumerate(train.iterrows()):
                Ytr_res[i] = Ytr[i] - ds_means.get(str(r["dataset"]), global_mu)

            nc = int(min(n_components, max(2, Ytr_res.shape[0] - 1), Ytr_res.shape[1] - 1))
            pca = TruncatedSVD(n_components=nc, random_state=42)
            Ztr = pca.fit_transform(Ytr_res)

            model = Ridge(alpha=ridge_alpha, fit_intercept=True)
            model.fit(Xtr, Ztr, sample_weight=Wtr)
            Zhat = model.predict(Xte)
            Yhat_res = Zhat @ pca.components_

            Yhat = np.empty_like(Yhat_res)
            baselines = np.empty_like(Yhat_res)
            for i, (_, r) in enumerate(test.iterrows()):
                base = ds_means.get(str(r["dataset"]), global_mu)
                Yhat[i] = base + Yhat_res[i]
                baselines[i] = base
        else:
            raise ValueError(f"Unknown y_mode={y_mode}")

        for i, (_, r) in enumerate(test.iterrows()):
            yt = Yte[i]
            yp = Yhat[i]
            yb = baselines[i]
            rows.append(
                {
                    "canonical_task": str(r["canonical_task"]),
                    "task_raw": str(r["task_raw"]),
                    "contrast": str(r["contrast"]),
                    "dataset": str(r["dataset"]),
                    "n_maps": int(r["n_maps"]),
                    "r_model": fe.pearsonr_fast(yt, yp),
                    "r_baseline": fe.pearsonr_fast(yt, yb),
                }
            )

    sdf = pd.DataFrame(rows)
    if sdf.empty:
        return sdf, {
            "n_eval": 0,
            "mean_r_model": float("nan"),
            "mean_r_baseline": float("nan"),
            "mean_delta": float("nan"),
            "win_rate": float("nan"),
        }

    sdf["delta_r"] = sdf["r_model"] - sdf["r_baseline"]
    summary = {
        "n_eval": int(len(sdf)),
        "mean_r_model": float(sdf["r_model"].mean()),
        "mean_r_baseline": float(sdf["r_baseline"].mean()),
        "mean_delta": float(sdf["delta_r"].mean()),
        "win_rate": float((sdf["delta_r"] > 0).mean()),
    }
    return sdf, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Run 3x3 smoke matrix for feature/Y diagnostics.")
    ap.add_argument("--fev2-script", type=Path, default=Path("scripts/analysis/run_forward_encoding_v2.py"))
    ap.add_argument("--diag-script", type=Path, default=Path("scripts/analysis/run_forward_encoding_diagnostics.py"))
    ap.add_argument("--out", type=Path, default=Path("outputs/forward_encoding_debug_matrix"))
    ap.add_argument("--root", type=Path, default=Path("data/openneuro_glmfitlins/stat_maps"))
    ap.add_argument("--kg-feature-map", type=Path, default=Path("outputs/forward_encoding_v2/kg_feature_map.json"))
    ap.add_argument("--max-samples", type=int, default=400)
    ap.add_argument("--max-per-task", type=int, default=30)
    ap.add_argument("--ridge-alpha", type=float, default=30.0)
    ap.add_argument("--max-features", type=int, default=140)
    ap.add_argument("--min-feature-df", type=int, default=2)
    ap.add_argument("--max-feature-df-ratio", type=float, default=0.9)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    fe = load_module(args.fev2_script, "fev2")
    diag = load_module(args.diag_script, "diag")

    # Shared dataset load once.
    all_maps = fe.list_stat_maps(args.root)
    selected0 = fe.select_maps(all_maps, args.max_per_task, args.max_samples)

    (
        _id2label,
        label2id,
        parents,
        children,
        top_concepts,
        degree_by_id,
    ) = fe.load_onvoc()

    kg_lookup = fe.load_kg_feature_map(args.kg_feature_map)

    # Build Y once on reference selected set.
    Y0, mask, template, keep_mask = fe.load_resampled_Y(selected0)
    selected_ref = selected0[keep_mask].reset_index(drop=True)
    Y = Y0

    feature_modes = [
        {
            "feature_mode": "A_raw_signed",
            "kg": {},
            "allow_lexical": False,
            "max_hops": 0,
            "alpha": 0.0,
            "blend_lambda": 0.0,
            "matrix": "raw",
        },
        {
            "feature_mode": "B_raw_signed_plus_filteredKG",
            "kg": kg_lookup,
            "allow_lexical": False,
            "max_hops": 0,
            "alpha": 0.0,
            "blend_lambda": 0.0,
            "matrix": "raw",
        },
        {
            "feature_mode": "C_B_plus_light_smoothing",
            "kg": kg_lookup,
            "allow_lexical": False,
            "max_hops": 1,
            "alpha": 0.6,
            "blend_lambda": 0.2,
            "matrix": "blend",
        },
    ]
    y_modes = ["abs_voxel", "residual_voxel", "residual_lowrank32"]

    all_rows = []
    coverage_rows = []

    for fm in feature_modes:
        X_raw, X_smooth, X_blend, feature_meta, selected_mode = fe.build_feature_matrices(
            selected0,
            label2id,
            parents,
            children,
            top_concepts,
            degree_by_id,
            max_onvoc_degree=18,
            max_hops=fm["max_hops"],
            alpha=fm["alpha"],
            blend_lambda=fm["blend_lambda"],
            min_feature_df=args.min_feature_df,
            max_feature_df_ratio=args.max_feature_df_ratio,
            max_features=args.max_features,
            kg_lookup=fm["kg"],
            allow_lexical=fm["allow_lexical"],
        )

        selected_mode = selected_mode[keep_mask].reset_index(drop=True)
        X_raw = X_raw[keep_mask]
        X_smooth = X_smooth[keep_mask]
        X_blend = X_blend[keep_mask]

        X = X_raw if fm["matrix"] == "raw" else X_blend

        cov = diag.feature_coverage_table(selected_mode, X)
        dup_ratio = float(cov["is_duplicate_feature_vector"].mean()) if len(cov) else float("nan")
        cov.to_csv(args.out / f"feature_coverage_{fm['feature_mode']}.csv", index=False)

        source_counts = {
            str(k): int(v)
            for k, v in pd.Series(selected_mode["feature_source"]).value_counts().items()
        }
        coverage_rows.append(
            {
                "feature_mode": fm["feature_mode"],
                "n_features": int(X.shape[1]),
                "n_samples": int(len(selected_mode)),
                "duplicate_vector_ratio": dup_ratio,
                "feature_source_counts": json.dumps(source_counts, ensure_ascii=False),
            }
        )

        combo_df = combo_aggregate(selected_mode, X, Y)
        combo_df.to_pickle(args.out / f"combo_cache_{fm['feature_mode']}.pkl")

        for ym in y_modes:
            sdf, summ = eval_combo_loto(
                fe,
                combo_df,
                ridge_alpha=args.ridge_alpha,
                y_mode=ym,
                n_components=32,
            )
            if not sdf.empty:
                sdf.to_csv(args.out / f"samples_{fm['feature_mode']}__{ym}.csv", index=False)

            row = {
                "feature_mode": fm["feature_mode"],
                "y_mode": ym,
                "n_eval": summ["n_eval"],
                "mean_r_model": summ["mean_r_model"],
                "mean_r_baseline": summ["mean_r_baseline"],
                "mean_delta": summ["mean_delta"],
                "win_rate": summ["win_rate"],
                "duplicate_vector_ratio": dup_ratio,
                "n_features": int(X.shape[1]),
            }
            all_rows.append(row)

    cov_df = pd.DataFrame(coverage_rows).sort_values("feature_mode").reset_index(drop=True)
    cov_df.to_csv(args.out / "matrix_feature_coverage_summary.csv", index=False)

    res_df = pd.DataFrame(all_rows).sort_values(["feature_mode", "y_mode"]).reset_index(drop=True)
    res_df.to_csv(args.out / "matrix_results.csv", index=False)

    best_idx = res_df["mean_delta"].astype(float).idxmax()
    best = res_df.loc[best_idx].to_dict() if len(res_df) else {}
    best = {
        str(k): (
            int(v)
            if isinstance(v, np.integer)
            else float(v)
            if isinstance(v, np.floating)
            else v
        )
        for k, v in best.items()
    }

    by_feature_mode = (
        {
            str(k): float(v)
            for k, v in res_df.groupby("feature_mode")["mean_delta"].mean().items()
        }
        if len(res_df)
        else {}
    )
    by_y_mode = (
        {str(k): float(v) for k, v in res_df.groupby("y_mode")["mean_delta"].mean().items()}
        if len(res_df)
        else {}
    )

    summary = {
        "n_rows": int(len(res_df)),
        "best": best,
        "by_feature_mode": by_feature_mode,
        "by_y_mode": by_y_mode,
    }
    (args.out / "matrix_summary.json").write_text(json.dumps(summary, indent=2))

    print(json.dumps({"ok": True, "out": str(args.out), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
