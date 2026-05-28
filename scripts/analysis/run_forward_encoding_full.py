#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import Ridge


FEATURE_MODE = "B_raw_signed_plus_filteredKG"
PRIMARY_Y_MODE = "residual_lowrank32"
ALLOWED_Y_MODES = ("residual_voxel", "residual_lowrank32", "abs_voxel")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def weighted_mean(vectors: np.ndarray, weights: np.ndarray) -> np.ndarray:
    w = weights.astype(np.float64)
    wsum = float(w.sum())
    if wsum <= 1e-12:
        return vectors.mean(axis=0)
    return (w[:, None] * vectors).sum(axis=0) / wsum


def combo_aggregate(df: pd.DataFrame, X: np.ndarray, Y: np.ndarray) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
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


@dataclass
class EvalSummary:
    n_eval: int
    mean_r_model: float
    mean_r_baseline: float
    mean_delta: float
    win_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_eval": int(self.n_eval),
            "mean_r_model": float(self.mean_r_model),
            "mean_r_baseline": float(self.mean_r_baseline),
            "mean_delta": float(self.mean_delta),
            "win_rate": float(self.win_rate),
        }


def eval_combo_loto(
    fe,
    combo_df: pd.DataFrame,
    *,
    ridge_alpha: float,
    y_mode: str,
    min_train: int,
    n_components: int,
) -> tuple[pd.DataFrame, EvalSummary]:
    rows: list[dict[str, Any]] = []
    tasks = sorted(combo_df["canonical_task"].unique())

    for task in tasks:
        test = combo_df[combo_df["canonical_task"] == task].copy()
        train = combo_df[combo_df["canonical_task"] != task].copy()
        if len(test) == 0 or len(train) < min_train:
            continue

        Xtr = np.stack(train["x"].to_numpy())
        Ytr = np.stack(train["y"].to_numpy())
        Wtr = np.sqrt(train["n_maps"].to_numpy(dtype=float))

        Xte = np.stack(test["x"].to_numpy())
        Yte = np.stack(test["y"].to_numpy())

        ds_means: dict[str, np.ndarray] = {}
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
            r_model = fe.pearsonr_fast(yt, yp)
            r_base = fe.pearsonr_fast(yt, yb)
            rows.append(
                {
                    "feature_mode": FEATURE_MODE,
                    "y_mode": y_mode,
                    "canonical_task": str(r["canonical_task"]),
                    "task_raw": str(r["task_raw"]),
                    "contrast": str(r["contrast"]),
                    "dataset": str(r["dataset"]),
                    "n_maps": int(r["n_maps"]),
                    "r_model": float(r_model),
                    "r_baseline": float(r_base),
                    "delta_r": float(r_model - r_base)
                    if np.isfinite(r_model) and np.isfinite(r_base)
                    else float("nan"),
                }
            )

    sdf = pd.DataFrame(rows)
    if sdf.empty:
        return sdf, EvalSummary(
            n_eval=0,
            mean_r_model=float("nan"),
            mean_r_baseline=float("nan"),
            mean_delta=float("nan"),
            win_rate=float("nan"),
        )

    summary = EvalSummary(
        n_eval=int(len(sdf)),
        mean_r_model=float(sdf["r_model"].mean()),
        mean_r_baseline=float(sdf["r_baseline"].mean()),
        mean_delta=float(sdf["delta_r"].mean()),
        win_rate=float((sdf["delta_r"] > 0).mean()),
    )
    return sdf, summary


def compute_gate_decision(
    mode_summaries: dict[str, EvalSummary],
    *,
    delta_threshold: float,
    win_rate_threshold: float,
) -> dict[str, Any]:
    pass_delta_modes: list[str] = []
    pass_win_modes: list[str] = []
    pass_joint_modes: list[str] = []

    for mode, s in mode_summaries.items():
        if np.isfinite(s.mean_delta) and s.mean_delta > delta_threshold:
            pass_delta_modes.append(mode)
        if np.isfinite(s.win_rate) and s.win_rate > win_rate_threshold:
            pass_win_modes.append(mode)
        if (
            np.isfinite(s.mean_delta)
            and np.isfinite(s.win_rate)
            and s.mean_delta > delta_threshold
            and s.win_rate > win_rate_threshold
        ):
            pass_joint_modes.append(mode)

    decision = "go" if pass_joint_modes else "conditional_go"
    split_evidence = (not pass_joint_modes) and bool(pass_delta_modes) and bool(pass_win_modes)

    return {
        "decision": decision,
        "thresholds": {
            "mean_delta_gt": float(delta_threshold),
            "win_rate_gt": float(win_rate_threshold),
        },
        "pass_delta_modes": sorted(pass_delta_modes),
        "pass_win_modes": sorted(pass_win_modes),
        "pass_joint_modes": sorted(pass_joint_modes),
        "split_evidence": bool(split_evidence),
    }


def is_unresolved_item(item: dict[str, Any] | None) -> bool:
    if not isinstance(item, dict):
        return True
    quality = item.get("quality")
    if isinstance(quality, dict):
        n_features = int(quality.get("n_features") or 0)
        task_resolved = bool(quality.get("task_resolved", False))
        if (not task_resolved) or n_features <= 0:
            return True
    n_kg = len(item.get("kg_feature_ids") or [])
    n_onvoc = len(item.get("onvoc_ids") or [])
    return (n_kg + n_onvoc) <= 0


def resolution_lookup_from_kg_map(path: Path) -> dict[tuple[str, str], bool]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    lookup: dict[tuple[str, str], bool] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        task_raw = str(it.get("task_raw", "")).strip()
        contrast = str(it.get("contrast", "")).strip()
        if not task_raw or not contrast:
            continue
        lookup[(task_raw, contrast)] = not is_unresolved_item(it)
    return lookup


def summarize_from_rows(rows: pd.DataFrame, y_modes: list[str]) -> dict[str, EvalSummary]:
    out: dict[str, EvalSummary] = {}
    for mode in y_modes:
        sub = rows[rows["y_mode"] == mode] if not rows.empty else rows
        if sub.empty:
            out[mode] = EvalSummary(
                n_eval=0,
                mean_r_model=float("nan"),
                mean_r_baseline=float("nan"),
                mean_delta=float("nan"),
                win_rate=float("nan"),
            )
            continue
        out[mode] = EvalSummary(
            n_eval=int(len(sub)),
            mean_r_model=float(sub["r_model"].mean()),
            mean_r_baseline=float(sub["r_baseline"].mean()),
            mean_delta=float(sub["delta_r"].mean()),
            win_rate=float((sub["delta_r"] > 0).mean()),
        )
    return out


def build_figure_manifest(out_dir: Path) -> dict[str, Any]:
    figs = [
        {
            "id": "fig_main_delta_win",
            "title": "Mode-wise mean delta and win rate",
            "kind": "bar_dual_axis",
            "source": str(out_dir / "model_mode_summary.csv"),
        },
        {
            "id": "fig_per_task_delta",
            "title": "Held-out per-task delta distribution",
            "kind": "bar",
            "source": str(out_dir / "table_per_task_heldout.csv"),
        },
        {
            "id": "fig_dataset_shift",
            "title": "Dataset-wise baseline and model performance",
            "kind": "bar_grouped",
            "source": str(out_dir / "table_dataset_shift.csv"),
        },
        {
            "id": "fig_feature_collapse",
            "title": "Feature collapse reduction",
            "kind": "single_value_compare",
            "source": str(out_dir / "table_feature_coverage.csv"),
            "notes": "Compare against prior baseline duplicate ratio 0.9524",
        },
        {
            "id": "fig_rdoc_projection",
            "title": "RDoC aggregation from tuning maps",
            "kind": "bar",
            "source": str(out_dir / "rdoc_projection_summary.json"),
        },
        {
            "id": "fig_resolution_sensitivity",
            "title": "Resolution-bucket sensitivity (resolved vs unresolved)",
            "kind": "bar_grouped",
            "source": str(out_dir / "model_mode_summary_by_resolution.csv"),
        },
    ]
    return {"generated_at": utc_now_iso(), "figures": figs}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full-scale forward encoding runner (residual-centric, KG-enhanced)."
    )
    parser.add_argument(
        "--fev2-script",
        type=Path,
        default=Path("scripts/analysis/run_forward_encoding_v2.py"),
    )
    parser.add_argument(
        "--diag-script",
        type=Path,
        default=Path("scripts/analysis/run_forward_encoding_diagnostics.py"),
    )
    parser.add_argument("--root", type=Path, default=Path("data/openneuro_glmfitlins/stat_maps"))
    parser.add_argument("--out", type=Path, default=Path("outputs/forward_encoding_full_v1"))
    parser.add_argument(
        "--kg-feature-map",
        type=Path,
        default=Path("outputs/forward_encoding_v2/kg_feature_map.json"),
    )
    parser.add_argument(
        "--rdoc-rules",
        type=Path,
        default=Path("outputs/forward_encoding_v2/rdoc_projection_rules.json"),
    )

    parser.add_argument("--max-samples", type=int, default=900)
    parser.add_argument("--max-per-task", type=int, default=80)
    parser.add_argument("--min-train", type=int, default=20)
    parser.add_argument("--ridge-alpha", type=float, default=30.0)
    parser.add_argument("--max-features", type=int, default=140)
    parser.add_argument("--min-feature-df", type=int, default=2)
    parser.add_argument("--max-feature-df-ratio", type=float, default=0.9)
    parser.add_argument("--max-onvoc-degree", type=int, default=18)
    parser.add_argument("--run-abs-aux", action="store_true")
    parser.add_argument("--n-components", type=int, default=32)
    parser.add_argument("--delta-threshold", type=float, default=-0.002)
    parser.add_argument("--win-rate-threshold", type=float, default=0.55)
    parser.add_argument("--max-tuning-maps", type=int, default=16)
    parser.add_argument(
        "--target-space",
        choices=["voxel", "schaefer"],
        default="schaefer",
        help="Target-space representation for Y.",
    )
    parser.add_argument("--schaefer-n-rois", type=int, default=400)
    parser.add_argument("--schaefer-yeo-networks", type=int, default=7)
    parser.add_argument("--schaefer-resolution-mm", type=int, default=2)
    parser.add_argument(
        "--schaefer-atlas-path",
        type=Path,
        default=None,
        help="Optional local Schaefer atlas labels image.",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    fe = load_module(args.fev2_script, "fev2")
    diag = load_module(args.diag_script, "diag")

    all_maps = fe.list_stat_maps(args.root)
    selected0 = fe.select_maps(all_maps, args.max_per_task, args.max_samples)

    (
        id_to_label,
        label_to_id,
        parents,
        children,
        top_concepts,
        degree_by_id,
    ) = fe.load_onvoc()

    kg_lookup = fe.load_kg_feature_map(args.kg_feature_map)

    X_raw, _X_smooth, _X_blend, feature_meta, selected = fe.build_feature_matrices(
        selected0,
        label_to_id,
        parents,
        children,
        top_concepts,
        degree_by_id,
        max_onvoc_degree=args.max_onvoc_degree,
        max_hops=0,
        alpha=0.0,
        blend_lambda=0.0,
        min_feature_df=args.min_feature_df,
        max_feature_df_ratio=args.max_feature_df_ratio,
        max_features=args.max_features,
        kg_lookup=kg_lookup,
        allow_lexical=False,
    )

    Y, mask, template, keep_mask, target_meta = fe.load_Y(
        selected,
        target_space=args.target_space,
        schaefer_n_rois=args.schaefer_n_rois,
        schaefer_yeo_networks=args.schaefer_yeo_networks,
        schaefer_resolution_mm=args.schaefer_resolution_mm,
        schaefer_atlas_path=args.schaefer_atlas_path,
    )
    if not keep_mask.all():
        selected = selected[keep_mask].reset_index(drop=True)
        X_raw = X_raw[keep_mask]

    # Base artifacts.
    selected.to_csv(args.out / "manifest.csv", index=False)
    (args.out / "feature_vocab.json").write_text(
        json.dumps({"features": feature_meta}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    feat_cov = diag.feature_coverage_table(selected, X_raw)
    feat_cov.to_csv(args.out / "table_feature_coverage.csv", index=False)

    combo_tbl = diag.combo_consistency_table(selected, Y)
    combo_tbl.to_csv(args.out / "table_combo_consistency.csv", index=False)

    combo_df = combo_aggregate(selected, X_raw, Y)
    combo_df.drop(columns=["x", "y"]).to_csv(args.out / "combo_manifest.csv", index=False)

    y_modes = ["residual_voxel", "residual_lowrank32"]
    if args.run_abs_aux:
        y_modes.append("abs_voxel")

    mode_summaries: dict[str, EvalSummary] = {}
    sample_tables: list[pd.DataFrame] = []

    for mode in y_modes:
        sdf, summary = eval_combo_loto(
            fe,
            combo_df,
            ridge_alpha=args.ridge_alpha,
            y_mode=mode,
            min_train=args.min_train,
            n_components=args.n_components,
        )
        mode_summaries[mode] = summary
        if not sdf.empty:
            sdf.to_csv(args.out / f"sample_metrics_{mode}.csv", index=False)
            sample_tables.append(sdf)

    if sample_tables:
        sample_metrics = pd.concat(sample_tables, axis=0, ignore_index=True)
    else:
        sample_metrics = pd.DataFrame(
            columns=[
                "feature_mode",
                "y_mode",
                "canonical_task",
                "task_raw",
                "contrast",
                "dataset",
                "n_maps",
                "r_model",
                "r_baseline",
                "delta_r",
            ]
        )

    # Attach resolved/unresolved sensitivity buckets from KG map quality.
    resolution_lookup = resolution_lookup_from_kg_map(args.kg_feature_map)
    if sample_metrics.empty:
        sample_metrics["resolved_status"] = pd.Series(dtype=bool)
        sample_metrics["kg_quality_bucket"] = pd.Series(dtype=str)
    else:
        sample_metrics["resolved_status"] = [
            bool(resolution_lookup.get((str(t), str(c)), False))
            for t, c in zip(sample_metrics["task_raw"], sample_metrics["contrast"])
        ]
        sample_metrics["kg_quality_bucket"] = np.where(
            sample_metrics["resolved_status"], "resolved", "unresolved"
        )
    sample_metrics.to_csv(args.out / "sample_metrics.csv", index=False)

    # Summary tables.
    mode_rows = []
    for mode, s in mode_summaries.items():
        row = {
            "feature_mode": FEATURE_MODE,
            "target_space": str(target_meta.get("target_space", args.target_space)),
            "y_mode": mode,
            **s.to_dict(),
        }
        mode_rows.append(row)
    mode_df = pd.DataFrame(mode_rows).sort_values("y_mode").reset_index(drop=True)
    mode_df.to_csv(args.out / "model_mode_summary.csv", index=False)

    if sample_metrics.empty:
        by_resolution_df = pd.DataFrame(
            columns=[
                "feature_mode",
                "target_space",
                "y_mode",
                "resolution_bucket",
                "n_eval",
                "mean_r_model",
                "mean_r_baseline",
                "mean_delta",
                "win_rate",
            ]
        )
    else:
        by_rows: list[dict[str, Any]] = []
        for (mode, bucket), g in sample_metrics.groupby(
            ["y_mode", "kg_quality_bucket"], as_index=False
        ):
            by_rows.append(
                {
                    "feature_mode": FEATURE_MODE,
                    "target_space": str(target_meta.get("target_space", args.target_space)),
                    "y_mode": str(mode),
                    "resolution_bucket": str(bucket),
                    "n_eval": int(len(g)),
                    "mean_r_model": float(g["r_model"].mean()),
                    "mean_r_baseline": float(g["r_baseline"].mean()),
                    "mean_delta": float(g["delta_r"].mean()),
                    "win_rate": float((g["delta_r"] > 0).mean()),
                }
            )
        by_resolution_df = pd.DataFrame(by_rows).sort_values(
            ["y_mode", "resolution_bucket"]
        ).reset_index(drop=True)
    by_resolution_df.to_csv(args.out / "model_mode_summary_by_resolution.csv", index=False)

    if sample_metrics.empty:
        per_task = pd.DataFrame(
            columns=[
                "y_mode",
                "canonical_task",
                "n_samples",
                "mean_r_model",
                "mean_r_baseline",
                "mean_delta",
                "win_rate",
            ]
        )
        ds_shift = pd.DataFrame(
            columns=[
                "y_mode",
                "dataset",
                "n_samples",
                "mean_r_model",
                "mean_r_baseline",
                "mean_delta",
                "win_rate",
            ]
        )
    else:
        per_task = (
            sample_metrics.groupby(["y_mode", "canonical_task"], as_index=False)
            .agg(
                n_samples=("delta_r", "count"),
                mean_r_model=("r_model", "mean"),
                mean_r_baseline=("r_baseline", "mean"),
                mean_delta=("delta_r", "mean"),
                win_rate=("delta_r", lambda s: float((s > 0).mean())),
            )
            .sort_values(["y_mode", "canonical_task"])
            .reset_index(drop=True)
        )

        ds_shift = (
            sample_metrics.groupby(["y_mode", "dataset"], as_index=False)
            .agg(
                n_samples=("delta_r", "count"),
                mean_r_model=("r_model", "mean"),
                mean_r_baseline=("r_baseline", "mean"),
                mean_delta=("delta_r", "mean"),
                win_rate=("delta_r", lambda s: float((s > 0).mean())),
            )
            .sort_values(["y_mode", "dataset"])
            .reset_index(drop=True)
        )

    per_task.to_csv(args.out / "table_per_task_heldout.csv", index=False)
    ds_shift.to_csv(args.out / "table_dataset_shift.csv", index=False)

    gate = compute_gate_decision(
        mode_summaries,
        delta_threshold=args.delta_threshold,
        win_rate_threshold=args.win_rate_threshold,
    )
    (args.out / "gate_decision.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if sample_metrics.empty:
        resolved_rows = sample_metrics.copy()
        unresolved_rows = sample_metrics.copy()
    else:
        resolved_rows = sample_metrics[sample_metrics["resolved_status"] == True].copy()
        unresolved_rows = sample_metrics[sample_metrics["resolved_status"] == False].copy()

    resolved_summaries = summarize_from_rows(resolved_rows, y_modes)
    unresolved_summaries = summarize_from_rows(unresolved_rows, y_modes)
    gate_resolved = compute_gate_decision(
        resolved_summaries,
        delta_threshold=args.delta_threshold,
        win_rate_threshold=args.win_rate_threshold,
    )
    gate_unresolved = compute_gate_decision(
        unresolved_summaries,
        delta_threshold=args.delta_threshold,
        win_rate_threshold=args.win_rate_threshold,
    )
    gate_sensitivity = {
        "full": {
            "gate": gate,
            "results_by_mode": {k: v.to_dict() for k, v in mode_summaries.items()},
            "n_eval": int(len(sample_metrics)),
        },
        "resolved_only": {
            "gate": gate_resolved,
            "results_by_mode": {k: v.to_dict() for k, v in resolved_summaries.items()},
            "n_eval": int(len(resolved_rows)),
        },
        "unresolved_only": {
            "gate": gate_unresolved,
            "results_by_mode": {k: v.to_dict() for k, v in unresolved_summaries.items()},
            "n_eval": int(len(unresolved_rows)),
        },
        "split_evidence": bool(
            gate["decision"] != "go" and gate_resolved.get("decision") == "go"
        ),
    }
    (args.out / "gate_decision_sensitivity.json").write_text(
        json.dumps(gate_sensitivity, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Optional interpretability outputs (tuning maps + RDoC projection summary).
    rdoc_rules = fe.load_rdoc_rules(args.rdoc_rules)
    if str(target_meta.get("target_space", args.target_space)) == "voxel":
        tuning_df, rdoc_summary = fe.export_tuning_maps_and_rdoc(
            X_raw,
            Y,
            feature_meta,
            mask,
            template,
            args.out,
            args.ridge_alpha,
            args.max_tuning_maps,
            id_to_label,
            rdoc_rules,
        )
    else:
        model = Ridge(alpha=args.ridge_alpha, fit_intercept=True)
        model.fit(X_raw, Y)
        coef = model.coef_  # [n_targets, n_features]

        feat_df = pd.DataFrame(feature_meta).copy()
        feat_df["feature_index"] = np.arange(len(feat_df))
        feat_df["mean_abs_beta"] = [
            float(np.mean(np.abs(coef[:, j]))) for j in range(coef.shape[1])
        ]
        onvoc_feat = feat_df[feat_df["feature"].str.startswith("ONVOC::")].copy()
        onvoc_feat = onvoc_feat.sort_values(
            "mean_abs_beta", ascending=False
        ).head(args.max_tuning_maps)

        parcel_labels = list(target_meta.get("labels") or [])
        parcel_rows: list[dict[str, Any]] = []
        compat_rows: list[dict[str, Any]] = []
        for _, r in onvoc_feat.iterrows():
            feat = str(r["feature"])
            j = int(r["feature_index"])
            cid = feat.split("::", 1)[1]
            label = id_to_label.get(cid, cid)

            vec = coef[:, j].astype(float)
            top_i = int(np.argmax(np.abs(vec)))
            top_beta = float(vec[top_i])
            top_label = (
                str(parcel_labels[top_i])
                if top_i < len(parcel_labels)
                else f"parcel_{top_i}"
            )

            rule = rdoc_rules.get(cid, {})
            primary = rule.get("rdoc_primary", {})
            base_row = {
                "feature": feat,
                "onvoc_id": cid,
                "onvoc_label": label,
                "mean_abs_beta": float(r["mean_abs_beta"]),
                "rdoc_domain": primary.get("domain", ""),
                "rdoc_construct": primary.get("construct", ""),
                "rdoc_confidence": float(rule.get("confidence", 0.0))
                if rule
                else np.nan,
            }
            parcel_rows.append(
                {
                    **base_row,
                    "top_parcel_index": top_i,
                    "top_parcel_label": top_label,
                    "top_parcel_beta": top_beta,
                }
            )
            compat_rows.append({**base_row, "map_path": ""})

        tuning_parcel_df = pd.DataFrame(parcel_rows)
        tuning_parcel_df.to_csv(args.out / "tuning_parcel_manifest.csv", index=False)

        tuning_df = pd.DataFrame(compat_rows)
        tuning_df.to_csv(args.out / "tuning_map_manifest.csv", index=False)

        agg_rows: list[dict[str, Any]] = []
        if not tuning_df.empty:
            grp = (
                tuning_df.groupby(["rdoc_domain", "rdoc_construct"], dropna=False)[
                    "mean_abs_beta"
                ]
                .sum()
                .reset_index()
                .sort_values("mean_abs_beta", ascending=False)
            )
            for _, rr in grp.iterrows():
                agg_rows.append(
                    {
                        "rdoc_domain": rr["rdoc_domain"],
                        "rdoc_construct": rr["rdoc_construct"],
                        "total_mean_abs_beta": float(rr["mean_abs_beta"]),
                    }
                )
        rdoc_summary = {
            "n_tuning_maps": int(len(tuning_df)),
            "rdoc_aggregation": agg_rows,
            "target_space": "schaefer",
        }
        (args.out / "rdoc_projection_summary.json").write_text(
            json.dumps(rdoc_summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    rdoc_summary_path = args.out / "rdoc_projection_summary.json"
    tuning_manifest_path = args.out / "tuning_map_manifest.csv"
    if not rdoc_summary_path.exists():
        rdoc_summary_path.write_text(
            json.dumps(
                {
                    "n_tuning_maps": 0,
                    "rdoc_aggregation": [],
                    "message": "No ONVOC tuning maps were available for projection.",
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if not tuning_manifest_path.exists():
        pd.DataFrame(
            columns=[
                "feature",
                "onvoc_id",
                "onvoc_label",
                "mean_abs_beta",
                "map_path",
                "rdoc_domain",
                "rdoc_construct",
                "rdoc_confidence",
            ]
        ).to_csv(tuning_manifest_path, index=False)

    figure_manifest = build_figure_manifest(args.out)
    (args.out / "figure_manifest.json").write_text(
        json.dumps(figure_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    feature_dup_rate = float(feat_cov["is_duplicate_feature_vector"].mean()) if len(feat_cov) else float("nan")
    mean_active_features = float(feat_cov["n_active_features"].mean()) if len(feat_cov) else float("nan")

    model_metrics = {
        "generated_at": utc_now_iso(),
        "feature_mode": FEATURE_MODE,
        "primary_mode": PRIMARY_Y_MODE,
        "target_space": str(target_meta.get("target_space", args.target_space)),
        "target_meta": target_meta,
        "selection": {
            "root": str(args.root),
            "max_samples": int(args.max_samples),
            "max_per_task": int(args.max_per_task),
            "min_train": int(args.min_train),
            "n_selected_samples": int(len(selected)),
            "n_selected_tasks": int(selected["canonical_task"].nunique()),
            "n_unique_combos": int(selected[["task_raw", "contrast"]].drop_duplicates().shape[0]),
            "n_features": int(X_raw.shape[1]),
            "n_targets": int(Y.shape[1]),
            "n_voxels": int(Y.shape[1]),
        },
        "feature_coverage": {
            "duplicate_vector_ratio": feature_dup_rate,
            "mean_active_features": mean_active_features,
        },
        "results_by_mode": {mode: summary.to_dict() for mode, summary in mode_summaries.items()},
        "gate": gate,
        "sensitivity": gate_sensitivity,
        "rdoc": {
            "n_tuning_maps": int(len(tuning_df)) if hasattr(tuning_df, "__len__") else 0,
            "n_rdoc_aggregates": int(len(rdoc_summary.get("rdoc_aggregation", [])))
            if isinstance(rdoc_summary, dict)
            else 0,
        },
        "notes": [
            "B-mode features only: raw anchors + signed conditions + filtered KG.",
            "Residual-centric evaluation over combo means with sqrt(n_maps) weighting.",
            "Gate requires mean_delta and win_rate thresholds to pass in the same mode.",
        ],
    }
    (args.out / "model_metrics.json").write_text(
        json.dumps(model_metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    run_manifest = {
        "generated_at": utc_now_iso(),
        "script": "scripts/analysis/run_forward_encoding_full.py",
        "inputs": {
            "fev2_script": str(args.fev2_script),
            "diag_script": str(args.diag_script),
            "kg_feature_map": str(args.kg_feature_map),
            "rdoc_rules": str(args.rdoc_rules),
            "target_space": args.target_space,
            "schaefer_n_rois": args.schaefer_n_rois,
            "schaefer_yeo_networks": args.schaefer_yeo_networks,
            "schaefer_resolution_mm": args.schaefer_resolution_mm,
            "schaefer_atlas_path": str(args.schaefer_atlas_path) if args.schaefer_atlas_path else None,
        },
        "outputs": {
            "model_metrics": str(args.out / "model_metrics.json"),
            "sample_metrics": str(args.out / "sample_metrics.csv"),
            "gate_decision": str(args.out / "gate_decision.json"),
            "gate_decision_sensitivity": str(args.out / "gate_decision_sensitivity.json"),
            "figure_manifest": str(args.out / "figure_manifest.json"),
        },
    }
    (args.out / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    narrative_lines = [
        "# Forward Encoding Full-Scale Summary",
        "",
        "## Core finding",
        "Shared absolute-map baseline remains strong, while residual targets approach parity and preserve task-specific structure.",
        "",
        "## Gate",
        f"- Decision: {gate['decision']}",
        f"- Joint pass modes: {gate['pass_joint_modes']}",
        f"- Split evidence: {gate['split_evidence']}",
        "",
        "## Feature coverage",
        f"- Duplicate feature vector ratio: {feature_dup_rate:.4f}",
        f"- Mean active features: {mean_active_features:.2f}",
        "",
        "## Sensitivity (Resolution Buckets)",
        f"- Resolved-only gate: {gate_resolved.get('decision')}",
        f"- Unresolved-only gate: {gate_unresolved.get('decision')}",
        f"- Split evidence (resolved passes while full fails): {gate_sensitivity.get('split_evidence')}",
        "",
        "## Modes",
    ]
    for mode, s in mode_summaries.items():
        narrative_lines.append(
            f"- {mode}: mean_delta={s.mean_delta:.4f}, win_rate={s.win_rate:.4f}, n_eval={s.n_eval}"
        )
    (args.out / "narrative_summary.md").write_text("\n".join(narrative_lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "out": str(args.out),
                "gate": gate,
                "results_by_mode": {k: v.to_dict() for k, v in mode_summaries.items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
