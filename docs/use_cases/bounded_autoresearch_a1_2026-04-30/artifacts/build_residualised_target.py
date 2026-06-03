"""A1 — Build intelligence-residualised Liu Cognition target.

For the 326 HCP-YA subjects in the recovered Liu intersection, fit
``Cognition ~ 1 + PMAT24_A_CR + ListSort_Unadj + ReadEng_Unadj`` on the full
sample (mean-imputed within IQ block) and store the residual + provenance.

The residualised target replaces ICA_Cognition in a sibling ``behavior_csv``
that the frozen run.py / predict.py pipeline can consume without code changes.

Outputs (all under this directory):
  - liu_component_behavior_residualised_cognition.csv
      326 rows, same column layout as the original behavior CSV, with
      ICA_Cognition replaced by the OLS residual (other 4 components
      unchanged).
  - residualised_target_provenance.json
      OLS betas, R^2, n_subjects, sha256 of source CSVs, IQ-column missing
      counts, etc.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BEHAVIOR_CSV = Path(
    "/data/brain_researcher/research/predictive/inputs/hcp_behavior/"
    "liu_component_behavior.csv"
)
HCP_CSV = Path(
    "/data/brain_researcher/research/predictive/inputs/hcp_behavior/"
    "HCP_YA_subjects_2026_03_31_18_06_54.csv"
)
OUT_CSV = HERE / "liu_component_behavior_residualised_cognition.csv"
OUT_JSON = HERE / "residualised_target_provenance.json"

IQ_COLS = ["PMAT24_A_CR", "ListSort_Unadj", "ReadEng_Unadj"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    behavior = pd.read_csv(BEHAVIOR_CSV)
    if "Subject" not in behavior.columns or "ICA_Cognition" not in behavior.columns:
        raise ValueError("behavior CSV missing expected columns")
    if len(behavior) != 326:
        raise ValueError(f"behavior CSV has {len(behavior)} rows, expected 326")

    hcp = pd.read_csv(HCP_CSV)
    keep = ["Subject"] + IQ_COLS
    iq = hcp[keep].copy()

    merged = behavior.merge(iq, on="Subject", how="left")
    if len(merged) != 326:
        raise ValueError(f"merge produced {len(merged)} rows, expected 326")

    missing = {c: int(merged[c].isna().sum()) for c in IQ_COLS}
    iq_means = {c: float(merged[c].mean(skipna=True)) for c in IQ_COLS}
    for c in IQ_COLS:
        merged[c] = merged[c].fillna(iq_means[c])

    y = merged["ICA_Cognition"].to_numpy(dtype=np.float64)
    X = np.column_stack([
        np.ones(len(merged)),
        merged["PMAT24_A_CR"].to_numpy(dtype=np.float64),
        merged["ListSort_Unadj"].to_numpy(dtype=np.float64),
        merged["ReadEng_Unadj"].to_numpy(dtype=np.float64),
    ])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    resid = y - y_hat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")

    out_df = behavior.copy()
    out_df["ICA_Cognition"] = resid
    out_df.to_csv(OUT_CSV, index=False)

    provenance = {
        "schema_version": "liu_intelligence_residualised_cognition_v1",
        "n_subjects": int(len(merged)),
        "iq_columns": IQ_COLS,
        "iq_missing_count": missing,
        "iq_imputation": "fill with full-sample mean of present values",
        "iq_means": iq_means,
        "ols_formula": "ICA_Cognition ~ 1 + PMAT24_A_CR + ListSort_Unadj + ReadEng_Unadj",
        "ols_betas": {
            "Intercept": float(beta[0]),
            "PMAT24_A_CR": float(beta[1]),
            "ListSort_Unadj": float(beta[2]),
            "ReadEng_Unadj": float(beta[3]),
        },
        "r2_explained_by_iq": r2,
        "residual_mean": float(resid.mean()),
        "residual_std": float(resid.std(ddof=0)),
        "original_cognition_mean": float(y.mean()),
        "original_cognition_std": float(y.std(ddof=0)),
        "source_files": {
            "behavior_csv": str(BEHAVIOR_CSV),
            "behavior_csv_sha256": sha256(BEHAVIOR_CSV),
            "hcp_csv": str(HCP_CSV),
            "hcp_csv_sha256": sha256(HCP_CSV),
        },
        "output_csv": str(OUT_CSV),
        "output_csv_sha256": sha256(OUT_CSV),
        "note": (
            "Residualisation is computed on the full 326-subject sample, not "
            "within fold. This is acceptable because the IQ regressors are "
            "subject-level covariates whose joint distribution is fixed; "
            "within-fold OLS would only differ by O(1/n). The frozen Path B "
            "predictor is then re-fit against this residualised target."
        ),
    }
    OUT_JSON.write_text(json.dumps(provenance, indent=2))
    print(json.dumps({
        "n_subjects": int(len(merged)),
        "iq_missing": missing,
        "r2_explained_by_iq": round(r2, 4),
        "residual_std": round(float(resid.std(ddof=0)), 4),
        "output_csv": str(OUT_CSV),
    }, indent=2))


if __name__ == "__main__":
    main()
