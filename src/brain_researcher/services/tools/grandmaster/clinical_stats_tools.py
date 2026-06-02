from __future__ import annotations

"""
Lightweight clinical / longitudinal utilities for Grandmaster.
These are intentionally minimal to avoid heavy deps but provide real functionality.
"""

from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.formula.api import mixedlm


def _load_table(table: str | Path) -> pd.DataFrame:
    path = Path(table).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in {".csv"}:
        return pd.read_csv(path)
    return pd.read_csv(path, sep="\t")


def analyze_clinical_correlation_tool(
    features_file: str,
    clinical_file: str,
    feature_cols: Iterable[str] | None = None,
    clinical_cols: Iterable[str] | None = None,
    covariates: Iterable[str] | None = None,
    output_file: str = "clinical_correlation.tsv",
):
    feats = _load_table(features_file)
    clin = _load_table(clinical_file)
    df = feats.merge(clin, on="participant_id", how="inner")
    fcols = list(feature_cols or [c for c in feats.columns if c != "participant_id"])
    ccols = list(clinical_cols or [c for c in clin.columns if c != "participant_id"])
    covs = list(covariates or [])

    rows = []
    for f in fcols:
        for c in ccols:
            cols = [f, c] + covs
            sub = df[["participant_id"] + cols].dropna()
            if sub.shape[0] < 4:
                continue
            X = sub[[f] + covs]
            X = sm.add_constant(X)
            y = sub[c]
            model = sm.OLS(y, X).fit()
            rows.append(
                {
                    "feature": f,
                    "clinical": c,
                    "beta": float(model.params.get(f, np.nan)),
                    "pvalue": float(model.pvalues.get(f, np.nan)),
                    "n": int(len(sub)),
                }
            )

    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, sep="\t", index=False)
    return {"status": "success", "outputs": {"table": str(out)}}


def analyze_longitudinal_lme_tool(
    features_file: str,
    subject_col: str = "participant_id",
    time_col: str = "session",
    dv_col: str = "score",
    covariates: Iterable[str] | None = None,
    output_file: str = "longitudinal_lme.tsv",
):
    df = _load_table(features_file).dropna()
    covs = list(covariates or [])
    formula = f"{dv_col} ~ 1 + {time_col}"
    if covs:
        formula += " + " + " + ".join(covs)
    model = mixedlm(formula, df, groups=df[subject_col])
    fit = model.fit()
    summary = fit.summary().as_text()
    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(str(out)).write_text(summary, encoding="utf-8")
    return {
        "status": "success",
        "outputs": {"summary_txt": str(out)},
        "params": fit.params.to_dict(),
    }


def compute_trajectory_similarity_tool(
    trajectories_file: str,
    id_col: str = "participant_id",
    time_col: str = "time",
    value_col: str = "value",
    output_file: str = "trajectory_similarity.tsv",
):
    df = _load_table(trajectories_file).dropna()
    groups = df.groupby(id_col)
    ids = list(groups.groups.keys())
    sims = []
    for i, id1 in enumerate(ids):
        t1 = groups.get_group(id1).sort_values(time_col)[value_col].to_numpy()
        for id2 in ids[i + 1 :]:
            t2 = groups.get_group(id2).sort_values(time_col)[value_col].to_numpy()
            n = min(len(t1), len(t2))
            if n < 2:
                continue
            v1, v2 = t1[:n], t2[:n]
            corr = float(np.corrcoef(v1, v2)[0, 1])
            sims.append({"id1": id1, "id2": id2, "pearson": corr, "n": n})
    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(sims).to_csv(out, sep="\t", index=False)
    return {"status": "success", "outputs": {"similarity_table": str(out)}}


def compare_to_normative_model_tool(
    subject_features: str,
    normative_mean: str,
    normative_std: str,
    output_file: str = "normative_deviation.tsv",
):
    sub = _load_table(subject_features)
    mean = _load_table(normative_mean)
    std = _load_table(normative_std)

    # Rename columns to avoid conflicts during merge
    # Assume all tables have a 'value' column (or 'stat' as alternative)
    if "value" in mean.columns:
        mean = mean.rename(columns={"value": "value_norm_mean"})
    elif "stat" in mean.columns:
        mean = mean.rename(columns={"stat": "value_norm_mean"})

    if "value" in std.columns:
        std = std.rename(columns={"value": "value_norm_std"})
    elif "stat" in std.columns:
        std = std.rename(columns={"stat": "value_norm_std"})

    df = sub.merge(mean, on="feature", how="inner")
    df = df.merge(std, on="feature", how="inner")

    # Compute z-score: (subject - mean) / std
    df["z"] = (df["value"] - df["value_norm_mean"]) / (df["value_norm_std"] + 1e-6)

    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, sep="\t", index=False)
    return {"status": "success", "outputs": {"deviation_table": str(out)}}


def normalize_with_lesion_tool(
    t1_img: str,
    lesion_mask: str,
    output_dir: str,
):
    """
    Minimal lesion-aware normalization: copies inputs and records manifest.
    (No heavy registration here; acts as a placeholder but functional bookkeeping.)
    """
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "t1_img": str(Path(t1_img).expanduser().resolve()),
        "lesion_mask": str(Path(lesion_mask).expanduser().resolve()),
        "note": "Normalization step should be replaced with ANTs lesion-aware reg in production.",
    }
    (out_dir / "lesion_normalization_manifest.json").write_text(
        pd.io.json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return {
        "status": "success",
        "outputs": {"manifest": str(out_dir / "lesion_normalization_manifest.json")},
    }


__all__ = [
    "analyze_clinical_correlation_tool",
    "analyze_longitudinal_lme_tool",
    "compute_trajectory_similarity_tool",
    "compare_to_normative_model_tool",
    "normalize_with_lesion_tool",
]
