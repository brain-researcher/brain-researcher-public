#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


ROOT = Path("/app/brain_researcher")
FE_DIR = ROOT / "outputs/forward_encoding_full_v2_schaefer900"
OUT_DIR = ROOT / "outputs/gallant_paper"
FEV2_SCRIPT = ROOT / "scripts/analysis/run_forward_encoding_v2.py"
FULL_SCRIPT = ROOT / "scripts/analysis/run_forward_encoding_full.py"
KG_FEATURE_MAP = ROOT / "outputs/forward_encoding_v2/kg_feature_map.refreshed.json"
STATMAP_ROOT = ROOT / "data/openneuro_glmfitlins/stat_maps"

TABLE_S3 = OUT_DIR / "table_s3_resolution_balance.csv"
TABLE_S4 = OUT_DIR / "table_s4_kg_incremental_ablation.csv"
TABLE_S5 = OUT_DIR / "table_s5_adjusted_association.csv"
METHODS_MD = OUT_DIR / "methodology_s3_s4_s5.md"

MODE_ORDER = ["abs_voxel", "residual_voxel", "residual_lowrank32"]
X_MODE_ORDER = ["anchor_signed_only", "anchor_signed_plus_kg", "kg_only"]


def _require_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Required input not found: {path}")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    # Dataclasses and other runtime introspection expect module to exist in sys.modules.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _combo_resolution(sample_df: pd.DataFrame) -> pd.DataFrame:
    combo_df = (
        sample_df[
            ["dataset", "canonical_task", "task_raw", "contrast", "resolved_status"]
        ]
        .drop_duplicates(subset=["dataset", "task_raw", "contrast"])
        .copy()
    )
    combo_df["resolution_bucket"] = np.where(
        combo_df["resolved_status"], "resolved", "unresolved"
    )
    return combo_df


def make_table_s3(sample_df: pd.DataFrame, manifest_df: pd.DataFrame) -> pd.DataFrame:
    combo_df = _combo_resolution(sample_df)
    map_counts = (
        manifest_df.groupby(["dataset", "task_raw", "contrast"], as_index=False)
        .size()
        .rename(columns={"size": "n_maps"})
    )
    combo_df = combo_df.merge(
        map_counts, on=["dataset", "task_raw", "contrast"], how="left"
    )
    combo_df["n_maps"] = combo_df["n_maps"].fillna(0).astype(int)

    blocks: list[pd.DataFrame] = []
    dimensions = [
        ("overall", None),
        ("dataset", "dataset"),
        ("canonical_task", "canonical_task"),
    ]
    for dimension, col in dimensions:
        block = combo_df.copy()
        block["dimension"] = dimension
        if col is None:
            block["dimension_value"] = "all"
        else:
            block["dimension_value"] = block[col].astype(str)
        summary_obs = (
            block.groupby(
                ["dimension", "dimension_value", "resolution_bucket"], as_index=False
            )
            .agg(n_combos=("contrast", "size"), n_maps=("n_maps", "sum"))
            .copy()
        )
        keys = block[["dimension", "dimension_value"]].drop_duplicates().copy()
        buckets = pd.DataFrame({"resolution_bucket": ["resolved", "unresolved"]})
        summary = keys.merge(buckets, how="cross").merge(
            summary_obs,
            on=["dimension", "dimension_value", "resolution_bucket"],
            how="left",
        )
        summary["n_combos"] = summary["n_combos"].fillna(0).astype(int)
        summary["n_maps"] = summary["n_maps"].fillna(0).astype(int)
        combo_totals = summary.groupby(["dimension", "dimension_value"])[
            "n_combos"
        ].transform("sum")
        map_totals = summary.groupby(["dimension", "dimension_value"])["n_maps"].transform(
            "sum"
        )
        summary["pct_combos_within_dimension"] = summary["n_combos"] / combo_totals
        summary["pct_maps_within_dimension"] = summary["n_maps"] / map_totals
        summary["mean_maps_per_combo"] = np.where(
            summary["n_combos"] > 0, summary["n_maps"] / summary["n_combos"], 0.0
        )
        blocks.append(summary)

    out = pd.concat(blocks, ignore_index=True)
    out["resolution_bucket"] = pd.Categorical(
        out["resolution_bucket"], ["resolved", "unresolved"], ordered=True
    )
    out["dimension"] = pd.Categorical(
        out["dimension"], ["overall", "dataset", "canonical_task"], ordered=True
    )
    out = out.sort_values(
        ["dimension", "dimension_value", "resolution_bucket"]
    ).reset_index(drop=True)
    return out


def _select_x_mode(
    X_all: np.ndarray, feature_meta: list[dict], x_mode: str
) -> np.ndarray:
    names = [str(d.get("feature", "")) for d in feature_meta]

    def is_kg_feature(name: str) -> bool:
        return name.startswith("KG_TASK::") or name.startswith("KG_NODE::") or name.startswith(
            "ONVOC::"
        )

    if x_mode == "anchor_signed_plus_kg":
        keep = np.ones(len(names), dtype=bool)
    elif x_mode == "anchor_signed_only":
        keep = np.array([not is_kg_feature(n) for n in names], dtype=bool)
    elif x_mode == "kg_only":
        keep = np.array([is_kg_feature(n) for n in names], dtype=bool)
    else:
        raise ValueError(f"Unknown x_mode={x_mode}")

    if keep.sum() == 0:
        return np.zeros((X_all.shape[0], 1), dtype=float)
    return X_all[:, keep]


def _summary_from_sample(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {
            "n_eval": 0,
            "mean_delta": float("nan"),
            "win_rate": float("nan"),
            "mean_r_model": float("nan"),
            "mean_r_baseline": float("nan"),
        }
    return {
        "n_eval": int(len(df)),
        "mean_delta": float(df["delta_r"].mean()),
        "win_rate": float((df["delta_r"] > 0).mean()),
        "mean_r_model": float(df["r_model"].mean()),
        "mean_r_baseline": float(df["r_baseline"].mean()),
    }


def make_table_s4() -> pd.DataFrame:
    fe = _load_module(FEV2_SCRIPT, "fev2_mod")
    full = _load_module(FULL_SCRIPT, "full_mod")

    all_maps = fe.list_stat_maps(STATMAP_ROOT)
    selected0 = fe.select_maps(all_maps, max_per_task=80, max_samples=900)
    (
        _id_to_label,
        label_to_id,
        parents,
        children,
        top_concepts,
        degree_by_id,
    ) = fe.load_onvoc()
    kg_lookup = fe.load_kg_feature_map(KG_FEATURE_MAP)
    X_raw, _X_smooth, _X_blend, feature_meta, selected = fe.build_feature_matrices(
        selected0,
        label_to_id,
        parents,
        children,
        top_concepts,
        degree_by_id,
        max_onvoc_degree=18,
        max_hops=0,
        alpha=0.0,
        blend_lambda=0.0,
        min_feature_df=2,
        max_feature_df_ratio=0.9,
        max_features=140,
        kg_lookup=kg_lookup,
        allow_lexical=False,
    )
    Y, _mask, _template, keep_mask, _target_meta = fe.load_Y(
        selected,
        target_space="schaefer",
        schaefer_n_rois=400,
        schaefer_yeo_networks=7,
        schaefer_resolution_mm=2,
        schaefer_atlas_path=None,
    )
    if not keep_mask.all():
        selected = selected[keep_mask].reset_index(drop=True)
        X_raw = X_raw[keep_mask]

    resolution_lookup = full.resolution_lookup_from_kg_map(KG_FEATURE_MAP)

    rows: list[dict] = []
    for x_mode in X_MODE_ORDER:
        X_mode = _select_x_mode(X_raw, feature_meta, x_mode)
        combo_df = full.combo_aggregate(selected, X_mode, Y)
        for y_mode in MODE_ORDER:
            sample_df, summary = full.eval_combo_loto(
                fe,
                combo_df,
                ridge_alpha=30.0,
                y_mode=y_mode,
                min_train=20,
                n_components=32,
            )
            if sample_df.empty:
                continue
            sample_df = sample_df.copy()
            sample_df["resolved_status"] = [
                bool(resolution_lookup.get((str(t), str(c)), False))
                for t, c in zip(sample_df["task_raw"], sample_df["contrast"])
            ]
            full_s = summary.to_dict()
            res_s = _summary_from_sample(sample_df[sample_df["resolved_status"]])
            unr_s = _summary_from_sample(sample_df[~sample_df["resolved_status"]])
            for cohort, ss in [
                ("full", full_s),
                ("resolved", res_s),
                ("unresolved", unr_s),
            ]:
                rows.append(
                    {
                        "x_mode": x_mode,
                        "y_mode": y_mode,
                        "cohort": cohort,
                        "n_eval": int(ss["n_eval"]),
                        "mean_delta": float(ss["mean_delta"]),
                        "win_rate": float(ss["win_rate"]),
                        "mean_r_model": float(ss["mean_r_model"]),
                        "mean_r_baseline": float(ss["mean_r_baseline"]),
                        "passes_default_gate": bool(
                            np.isfinite(ss["mean_delta"])
                            and np.isfinite(ss["win_rate"])
                            and ss["mean_delta"] > -0.002
                            and ss["win_rate"] > 0.55
                        ),
                    }
                )

    out = pd.DataFrame(rows)
    out["x_mode"] = pd.Categorical(out["x_mode"], X_MODE_ORDER, ordered=True)
    out["y_mode"] = pd.Categorical(out["y_mode"], MODE_ORDER, ordered=True)
    out["cohort"] = pd.Categorical(
        out["cohort"], ["full", "resolved", "unresolved"], ordered=True
    )
    out = out.sort_values(["x_mode", "cohort", "y_mode"]).reset_index(drop=True)

    # Incremental deltas vs anchor_signed_only within each cohort/y_mode.
    base = (
        out[out["x_mode"] == "anchor_signed_only"][
            ["cohort", "y_mode", "mean_delta", "win_rate", "mean_r_model", "mean_r_baseline"]
        ]
        .rename(
            columns={
                "mean_delta": "mean_delta_anchor_signed_only",
                "win_rate": "win_rate_anchor_signed_only",
                "mean_r_model": "mean_r_model_anchor_signed_only",
                "mean_r_baseline": "mean_r_baseline_anchor_signed_only",
            }
        )
        .copy()
    )
    out = out.merge(base, on=["cohort", "y_mode"], how="left", validate="many_to_one")
    out["delta_vs_anchor_signed_only"] = (
        out["mean_delta"] - out["mean_delta_anchor_signed_only"]
    )
    out["win_rate_vs_anchor_signed_only"] = (
        out["win_rate"] - out["win_rate_anchor_signed_only"]
    )
    out["mean_r_model_vs_anchor_signed_only"] = (
        out["mean_r_model"] - out["mean_r_model_anchor_signed_only"]
    )
    out["mean_r_baseline_vs_anchor_signed_only"] = (
        out["mean_r_baseline"] - out["mean_r_baseline_anchor_signed_only"]
    )
    return out[
        [
            "x_mode",
            "cohort",
            "y_mode",
            "n_eval",
            "mean_delta",
            "win_rate",
            "mean_r_model",
            "mean_r_baseline",
            "passes_default_gate",
            "delta_vs_anchor_signed_only",
            "win_rate_vs_anchor_signed_only",
            "mean_r_model_vs_anchor_signed_only",
            "mean_r_baseline_vs_anchor_signed_only",
        ]
    ]


def _model_row(
    *,
    table_id: str,
    outcome: str,
    contrast: str,
    estimate: float,
    se: float,
    p_value: float,
    ci_low: float,
    ci_high: float,
    n_obs: int,
    n_combos: int,
) -> dict[str, object]:
    return {
        "table_id": table_id,
        "outcome": outcome,
        "contrast": contrast,
        "estimate": float(estimate),
        "std_error": float(se),
        "ci_low_95": float(ci_low),
        "ci_high_95": float(ci_high),
        "p_value": float(p_value),
        "n_obs": int(n_obs),
        "n_combos": int(n_combos),
    }


def make_table_s5(sample_df: pd.DataFrame) -> pd.DataFrame:
    df = sample_df.copy()
    df["resolved"] = df["resolved_status"].astype(int)
    df["delta_positive"] = (df["delta_r"] > 0).astype(int)
    df["combo_id"] = (
        df["dataset"].astype(str)
        + "|"
        + df["task_raw"].astype(str)
        + "|"
        + df["contrast"].astype(str)
    )
    n_obs = len(df)
    n_combos = df["combo_id"].nunique()

    # Mode- and composition-adjusted pooled association.
    base_formula = "C(y_mode) + resolved + np.log1p(n_maps) + C(dataset) + C(canonical_task)"
    m_delta = smf.ols(f"delta_r ~ {base_formula}", data=df).fit(
        cov_type="cluster", cov_kwds={"groups": df["combo_id"]}
    )
    m_win = smf.ols(f"delta_positive ~ {base_formula}", data=df).fit(
        cov_type="cluster", cov_kwds={"groups": df["combo_id"]}
    )

    rows: list[dict[str, object]] = []
    ci_delta = m_delta.conf_int().loc["resolved"].to_numpy(dtype=float)
    rows.append(
        _model_row(
            table_id="pooled_adjusted",
            outcome="delta_r",
            contrast="resolved_vs_unresolved",
            estimate=m_delta.params["resolved"],
            se=m_delta.bse["resolved"],
            p_value=m_delta.pvalues["resolved"],
            ci_low=ci_delta[0],
            ci_high=ci_delta[1],
            n_obs=n_obs,
            n_combos=n_combos,
        )
    )
    ci_win = m_win.conf_int().loc["resolved"].to_numpy(dtype=float)
    rows.append(
        _model_row(
            table_id="pooled_adjusted",
            outcome="delta_positive",
            contrast="resolved_vs_unresolved",
            estimate=m_win.params["resolved"],
            se=m_win.bse["resolved"],
            p_value=m_win.pvalues["resolved"],
            ci_low=ci_win[0],
            ci_high=ci_win[1],
            n_obs=n_obs,
            n_combos=n_combos,
        )
    )

    # Mode-specific resolved effects from interaction models.
    m_delta_int = smf.ols(
        f"delta_r ~ C(y_mode) * resolved + np.log1p(n_maps) + C(dataset) + C(canonical_task)",
        data=df,
    ).fit(
        cov_type="cluster", cov_kwds={"groups": df["combo_id"]}
    )
    m_win_int = smf.ols(
        f"delta_positive ~ C(y_mode) * resolved + np.log1p(n_maps) + C(dataset) + C(canonical_task)",
        data=df,
    ).fit(
        cov_type="cluster", cov_kwds={"groups": df["combo_id"]}
    )
    tests = {
        "abs_voxel": "resolved = 0",
        "residual_voxel": "resolved + C(y_mode)[T.residual_voxel]:resolved = 0",
        "residual_lowrank32": "resolved + C(y_mode)[T.residual_lowrank32]:resolved = 0",
    }
    for mode in MODE_ORDER:
        t_delta = m_delta_int.t_test(tests[mode])
        ci = t_delta.conf_int(alpha=0.05).squeeze()
        rows.append(
            _model_row(
                table_id="mode_specific_interaction",
                outcome="delta_r",
                contrast=f"resolved_vs_unresolved@{mode}",
                estimate=float(t_delta.effect.squeeze()),
                se=float(t_delta.sd.squeeze()),
                p_value=float(t_delta.pvalue.squeeze()),
                ci_low=float(ci[0]),
                ci_high=float(ci[1]),
                n_obs=n_obs,
                n_combos=n_combos,
            )
        )

        t_win = m_win_int.t_test(tests[mode])
        ciw = t_win.conf_int(alpha=0.05).squeeze()
        rows.append(
            _model_row(
                table_id="mode_specific_interaction",
                outcome="delta_positive",
                contrast=f"resolved_vs_unresolved@{mode}",
                estimate=float(t_win.effect.squeeze()),
                se=float(t_win.sd.squeeze()),
                p_value=float(t_win.pvalue.squeeze()),
                ci_low=float(ciw[0]),
                ci_high=float(ciw[1]),
                n_obs=n_obs,
                n_combos=n_combos,
            )
        )

    out = pd.DataFrame(rows).sort_values(
        ["table_id", "outcome", "contrast"]
    ).reset_index(drop=True)
    return out


def write_methods_markdown() -> None:
    lines = [
        "# Supplementary Table Methods (S3-S5)",
        "",
        "S3 and S5 were computed directly from existing artifacts under",
        "`outputs/forward_encoding_full_v2_schaefer900`.",
        "S4 was recomputed by deterministic rerun of combo-level evaluation",
        "with fixed benchmark settings and frozen KG snapshot (no online MCP retrieval).",
        "",
        "## S3: Resolution Balance",
        "- Source files: `sample_metrics.csv`, `manifest.csv`.",
        "- Unit of resolution labeling: unique combo `(dataset, task_raw, contrast)`.",
        "- Reported counts include combo totals and map totals for resolved vs unresolved strata.",
        "- Stratification levels: overall, dataset, canonical task.",
        "",
        "## S4: KG Incremental Ablation",
        "- Source files: `run_forward_encoding_v2.py`, `run_forward_encoding_full.py`,",
        "  `kg_feature_map.refreshed.json`, and `data/openneuro_glmfitlins/stat_maps`.",
        "- X-mode ablations:",
        "  - `anchor_signed_only`: remove all `KG_*`/`ONVOC::*` channels.",
        "  - `anchor_signed_plus_kg`: full hybrid feature space (default).",
        "  - `kg_only`: retain only `KG_*`/`ONVOC::*` channels.",
        "- Y-modes: `abs_voxel`, `residual_voxel`, `residual_lowrank32`.",
        "- Cohorts: full, resolved, unresolved (from frozen resolution lookup).",
        "- `passes_default_gate` uses thresholds `mean_delta > -0.002` and `win_rate > 0.55`.",
        "",
        "## S5: Adjusted Association",
        "- Source file: `sample_metrics.csv`.",
        "- Outcome definitions:",
        "  - `delta_r`: model-minus-baseline correlation at combo level.",
        "  - `delta_positive`: indicator of `delta_r > 0`.",
        "- Models use cluster-robust linear regression with combo-level clustering",
        "  (`combo_id = dataset|task_raw|contrast`).",
        "- Pooled adjusted model: outcome ~ `C(y_mode) + resolved + log1p(n_maps)`",
        "  + dataset/task fixed effects.",
        "- Mode-specific associations use interaction models:",
        "  outcome ~ `C(y_mode) * resolved + log1p(n_maps) + dataset/task fixed effects`,",
        "  then linear contrasts per mode.",
        "",
        "Generated by `scripts/analysis/generate_gallant_supplement_tables_s345.py`.",
    ]
    METHODS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    _require_exists(FE_DIR / "sample_metrics.csv")
    _require_exists(FE_DIR / "manifest.csv")
    _require_exists(FEV2_SCRIPT)
    _require_exists(FULL_SCRIPT)
    _require_exists(KG_FEATURE_MAP)
    _require_exists(STATMAP_ROOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sample_df = pd.read_csv(FE_DIR / "sample_metrics.csv")
    manifest_df = pd.read_csv(FE_DIR / "manifest.csv")

    s3 = make_table_s3(sample_df=sample_df, manifest_df=manifest_df)
    s4 = make_table_s4()
    s5 = make_table_s5(sample_df=sample_df)

    s3.to_csv(TABLE_S3, index=False)
    s4.to_csv(TABLE_S4, index=False)
    s5.to_csv(TABLE_S5, index=False)
    write_methods_markdown()

    print(f"Wrote {TABLE_S3}")
    print(f"Wrote {TABLE_S4}")
    print(f"Wrote {TABLE_S5}")
    print(f"Wrote {METHODS_MD}")


if __name__ == "__main__":
    main()
