#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import Ridge


def load_fev2_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("fev2", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pearsonr_fast(a: np.ndarray, b: np.ndarray) -> float:
    aa = a.astype(np.float64, copy=False)
    bb = b.astype(np.float64, copy=False)
    aa = aa - aa.mean()
    bb = bb - bb.mean()
    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na <= 1e-12 or nb <= 1e-12:
        return float("nan")
    return float(np.dot(aa, bb) / (na * nb))


def combo_consistency_table(df: pd.DataFrame, Y: np.ndarray) -> pd.DataFrame:
    rows = []
    for (task_raw, contrast), g in df.groupby(["task_raw", "contrast"], sort=True):
        idx = g.index.to_numpy()
        Yg = Y[idx]
        n = len(idx)

        within_mean_r = np.nan
        within_median_r = np.nan
        combo_mean_vs_single_r = np.nan
        if n >= 2:
            X = Yg.astype(np.float64)
            X = X - X.mean(axis=1, keepdims=True)
            norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
            Xn = X / norms
            C = Xn @ Xn.T
            tri = C[np.triu_indices(n, 1)]
            within_mean_r = float(np.nanmean(tri))
            within_median_r = float(np.nanmedian(tri))

            mu = Yg.mean(axis=0)
            rs = [pearsonr_fast(y, mu) for y in Yg]
            combo_mean_vs_single_r = float(np.nanmean(rs))

        rows.append(
            {
                "task_raw": task_raw,
                "contrast": contrast,
                "n_maps": int(n),
                "within_combo_mean_r": within_mean_r,
                "within_combo_median_r": within_median_r,
                "combo_mean_vs_single_r": combo_mean_vs_single_r,
                "voxel_var_mean": float(np.var(Yg, axis=0).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["task_raw", "contrast"]).reset_index(drop=True)


def evaluate_residual_loto(df: pd.DataFrame, X: np.ndarray, Y: np.ndarray, ridge_alpha: float, min_train: int) -> pd.DataFrame:
    rows = []
    groups = sorted(df["canonical_task"].unique())

    for task in groups:
        test_idx = np.where(df["canonical_task"].values == task)[0]
        train_idx = np.where(df["canonical_task"].values != task)[0]
        if len(test_idx) == 0 or len(train_idx) < min_train:
            continue

        Xtr, Xte = X[train_idx], X[test_idx]
        Ytr, Yte = Y[train_idx], Y[test_idx]

        mu_global = Ytr.mean(axis=0, keepdims=True)
        Ytr_res = Ytr - mu_global

        reg = Ridge(alpha=ridge_alpha, fit_intercept=True)
        reg.fit(Xtr, Ytr_res)
        Ypred = mu_global + reg.predict(Xte)

        train_df = df.iloc[train_idx].copy()
        train_df["_rel"] = np.arange(len(train_df))
        ds_means = {}
        for ds, g in train_df.groupby("dataset"):
            ds_means[ds] = Ytr[g["_rel"].to_numpy()].mean(axis=0)

        for li, si in enumerate(test_idx):
            y_true = Yte[li]
            y_pred = Ypred[li]
            mu = mu_global[0]
            y_true_res = y_true - mu
            y_pred_res = y_pred - mu

            ds = str(df.iloc[si]["dataset"])
            mu_ds = ds_means.get(ds, mu)

            rows.append(
                {
                    "sample_index": int(si),
                    "dataset": ds,
                    "task_raw": str(df.iloc[si]["task_raw"]),
                    "canonical_task": str(df.iloc[si]["canonical_task"]),
                    "contrast": str(df.iloc[si]["contrast"]),
                    "r_abs": pearsonr_fast(y_true, y_pred),
                    "r_res": pearsonr_fast(y_true_res, y_pred_res),
                    "r_baseline_global": pearsonr_fast(y_true, mu),
                    "r_baseline_dataset": pearsonr_fast(y_true, mu_ds),
                }
            )

    out = pd.DataFrame(rows)
    out["delta_abs_vs_global"] = out["r_abs"] - out["r_baseline_global"]
    out["delta_res_vs_global"] = out["r_res"] - out["r_baseline_global"]
    out["delta_abs_vs_dataset"] = out["r_abs"] - out["r_baseline_dataset"]
    return out


def evaluate_lowrank_loto(
    df: pd.DataFrame,
    X: np.ndarray,
    Y: np.ndarray,
    ridge_alpha: float,
    min_train: int,
    components_list: list[int],
) -> pd.DataFrame:
    rows = []
    groups = sorted(df["canonical_task"].unique())

    for ncomp in components_list:
        sample_rows = []
        for task in groups:
            test_idx = np.where(df["canonical_task"].values == task)[0]
            train_idx = np.where(df["canonical_task"].values != task)[0]
            if len(test_idx) == 0 or len(train_idx) < min_train:
                continue

            Xtr, Xte = X[train_idx], X[test_idx]
            Ytr, Yte = Y[train_idx], Y[test_idx]

            mu = Ytr.mean(axis=0, keepdims=True)
            Ytr_res = Ytr - mu

            nc = int(min(ncomp, max(2, Ytr_res.shape[0] - 1), Ytr_res.shape[1] - 1))
            if nc < 2:
                continue

            pca = TruncatedSVD(n_components=nc, random_state=42)
            Ztr = pca.fit_transform(Ytr_res)

            reg = Ridge(alpha=ridge_alpha, fit_intercept=True)
            reg.fit(Xtr, Ztr)

            Zpred = reg.predict(Xte)
            Ypred = mu + Zpred @ pca.components_

            for li, si in enumerate(test_idx):
                y_true = Yte[li]
                y_pred = Ypred[li]
                sample_rows.append(
                    {
                        "n_components": nc,
                        "sample_index": int(si),
                        "canonical_task": str(df.iloc[si]["canonical_task"]),
                        "r_abs": pearsonr_fast(y_true, y_pred),
                        "r_res": pearsonr_fast(y_true - mu[0], y_pred - mu[0]),
                        "r_baseline": pearsonr_fast(y_true, mu[0]),
                    }
                )

        sdf = pd.DataFrame(sample_rows)
        if sdf.empty:
            continue
        rows.append(
            {
                "n_components": int(sdf["n_components"].iloc[0]),
                "n_samples": int(len(sdf)),
                "mean_r_abs": float(sdf["r_abs"].mean()),
                "mean_r_res": float(sdf["r_res"].mean()),
                "mean_r_baseline": float(sdf["r_baseline"].mean()),
                "delta_abs": float((sdf["r_abs"] - sdf["r_baseline"]).mean()),
                "delta_res": float((sdf["r_res"] - sdf["r_baseline"]).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("n_components").reset_index(drop=True)


def feature_coverage_table(df: pd.DataFrame, X: np.ndarray) -> pd.DataFrame:
    active = (X > 0).astype(np.uint8)
    df = df.copy()
    df["n_active_features"] = active.sum(axis=1)

    combo_rows = []
    combo_vec_hash = {}
    for (task_raw, contrast), g in df.groupby(["task_raw", "contrast"], sort=True):
        idx = g.index.to_numpy()
        vec = (active[idx].mean(axis=0) > 0).astype(np.uint8)
        h = hashlib.md5(np.packbits(vec).tobytes()).hexdigest()
        combo_vec_hash[(task_raw, contrast)] = h

        src = g["feature_source"].mode()
        src_val = str(src.iloc[0]) if not src.empty else "unknown"

        combo_rows.append(
            {
                "task_raw": task_raw,
                "contrast": contrast,
                "n_maps": int(len(idx)),
                "n_active_features": int(vec.sum()),
                "source": src_val,
                "feature_vector_hash": h,
            }
        )

    cdf = pd.DataFrame(combo_rows)
    dup = cdf.groupby("feature_vector_hash").size().rename("n_combos_with_same_vector").reset_index()
    cdf = cdf.merge(dup, on="feature_vector_hash", how="left")
    cdf["is_duplicate_feature_vector"] = cdf["n_combos_with_same_vector"] > 1
    return cdf.sort_values(["task_raw", "contrast"]).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward encoding diagnostics (residual/noise-ceiling/low-rank).")
    ap.add_argument("--fev2-script", type=Path, default=Path("scripts/analysis/run_forward_encoding_v2.py"))
    ap.add_argument("--root", type=Path, default=Path("data/openneuro_glmfitlins/stat_maps"))
    ap.add_argument("--out", type=Path, default=Path("outputs/forward_encoding_debug"))
    ap.add_argument("--max-samples", type=int, default=400)
    ap.add_argument("--max-per-task", type=int, default=30)
    ap.add_argument("--min-train", type=int, default=20)
    ap.add_argument("--ridge-alpha", type=float, default=30.0)
    ap.add_argument("--max-hops", type=int, default=3)
    ap.add_argument("--alpha", type=float, default=0.65)
    ap.add_argument("--blend-lambda", type=float, default=0.4)
    ap.add_argument("--min-feature-df", type=int, default=2)
    ap.add_argument("--max-feature-df-ratio", type=float, default=0.85)
    ap.add_argument("--max-features", type=int, default=120)
    ap.add_argument("--max-onvoc-degree", type=int, default=18)
    ap.add_argument("--allow-lexical-fallback", action="store_true")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    fe = load_fev2_module(args.fev2_script)

    all_maps = fe.list_stat_maps(args.root)
    selected = fe.select_maps(all_maps, args.max_per_task, args.max_samples)

    (
        _id2label,
        label2id,
        parents_by_child,
        children_by_parent,
        top_concepts,
        degree_by_id,
    ) = fe.load_onvoc()

    X_raw, X_smooth, X_blend, feature_meta, selected = fe.build_feature_matrices(
        selected,
        label2id,
        parents_by_child,
        children_by_parent,
        top_concepts,
        degree_by_id,
        max_onvoc_degree=args.max_onvoc_degree,
        max_hops=args.max_hops,
        alpha=args.alpha,
        blend_lambda=args.blend_lambda,
        min_feature_df=args.min_feature_df,
        max_feature_df_ratio=args.max_feature_df_ratio,
        max_features=args.max_features,
        kg_lookup={},
        allow_lexical=args.allow_lexical_fallback,
    )

    Y, _mask, _template, keep_mask = fe.load_resampled_Y(selected)
    if not keep_mask.all():
        selected = selected[keep_mask].reset_index(drop=True)
        X_raw = X_raw[keep_mask]
        X_smooth = X_smooth[keep_mask]
        X_blend = X_blend[keep_mask]

    selected.to_csv(args.out / "manifest_debug.csv", index=False)
    (args.out / "feature_vocab_debug.json").write_text(json.dumps({"features": feature_meta}, indent=2))

    combo_tbl = combo_consistency_table(selected, Y)
    combo_tbl.to_csv(args.out / "table_combo_consistency.csv", index=False)

    resid_rows = evaluate_residual_loto(selected, X_blend, Y, args.ridge_alpha, args.min_train)
    resid_rows.to_csv(args.out / "table_residual_loto_samples.csv", index=False)

    per_task = (
        resid_rows.groupby("canonical_task", as_index=False)
        .agg(
            n_samples=("sample_index", "count"),
            r_model_abs=("r_abs", "mean"),
            r_model_res=("r_res", "mean"),
            r_baseline_global=("r_baseline_global", "mean"),
            r_baseline_dataset=("r_baseline_dataset", "mean"),
            delta_abs_vs_global=("delta_abs_vs_global", "mean"),
            delta_res_vs_global=("delta_res_vs_global", "mean"),
            delta_abs_vs_dataset=("delta_abs_vs_dataset", "mean"),
        )
        .sort_values("canonical_task")
        .reset_index(drop=True)
    )
    per_task.to_csv(args.out / "table_per_task_heldout.csv", index=False)

    ds_shift = (
        resid_rows.groupby("dataset", as_index=False)
        .agg(
            n_samples=("sample_index", "count"),
            global_baseline_r=("r_baseline_global", "mean"),
            dataset_baseline_r=("r_baseline_dataset", "mean"),
            model_r_abs=("r_abs", "mean"),
            model_r_res=("r_res", "mean"),
        )
        .sort_values("dataset")
        .reset_index(drop=True)
    )
    ds_shift.to_csv(args.out / "table_dataset_shift.csv", index=False)

    feat_cov = feature_coverage_table(selected, X_blend)
    feat_cov.to_csv(args.out / "table_feature_coverage.csv", index=False)

    lowrank_tbl = evaluate_lowrank_loto(
        selected,
        X_blend,
        Y,
        ridge_alpha=args.ridge_alpha,
        min_train=args.min_train,
        components_list=[32, 64, 128],
    )
    lowrank_tbl.to_csv(args.out / "table_lowrank_loto.csv", index=False)

    summary = {
        "n_selected_samples": int(len(selected)),
        "n_selected_tasks": int(selected["canonical_task"].nunique()),
        "n_unique_combos": int(selected[["task_raw", "contrast"]].drop_duplicates().shape[0]),
        "n_features": int(X_blend.shape[1]),
        "allow_lexical_fallback": bool(args.allow_lexical_fallback),
        "residual_overall": {
            "mean_r_abs": float(resid_rows["r_abs"].mean()),
            "mean_r_res": float(resid_rows["r_res"].mean()),
            "mean_r_baseline_global": float(resid_rows["r_baseline_global"].mean()),
            "mean_r_baseline_dataset": float(resid_rows["r_baseline_dataset"].mean()),
            "mean_delta_abs_vs_global": float(resid_rows["delta_abs_vs_global"].mean()),
            "mean_delta_res_vs_global": float(resid_rows["delta_res_vs_global"].mean()),
        },
        "combo_consistency": {
            "median_within_combo_mean_r": float(combo_tbl["within_combo_mean_r"].median(skipna=True)),
            "mean_within_combo_mean_r": float(combo_tbl["within_combo_mean_r"].mean(skipna=True)),
            "median_n_maps": float(combo_tbl["n_maps"].median()),
        },
        "feature_coverage": {
            "mean_active_features": float(feat_cov["n_active_features"].mean()),
            "duplicate_vector_rate": float(feat_cov["is_duplicate_feature_vector"].mean()),
        },
    }
    (args.out / "diagnostic_summary.json").write_text(json.dumps(summary, indent=2))

    print(json.dumps({"ok": True, "out": str(args.out), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
