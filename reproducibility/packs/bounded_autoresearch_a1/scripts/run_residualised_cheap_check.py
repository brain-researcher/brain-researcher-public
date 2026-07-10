"""A1 sanity — re-run §5.1 cheap in-house check on the residualised target.

The residualised target is already orthogonal to {PMAT24, ListSort, ReadEng} at
the population level, so within-fold residualisation against the same three
columns should be a near-noise reduction. This script confirms that and reports
the new H1' (residualised Cognition) deconf number.

Approach mirrors `extended_covariate_gate/run_extended_covariate_gate.py` but:
- BEHAVIOR_CSV is the residualised CSV (ICA_Cognition column = residual).
- Predictor / fold manifest / TermLoader are reused verbatim from the frozen
  workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(
    0, str(HERE)
)  # run_prediction.py + predict.py live alongside this script

from predict import predict_fold  # type: ignore # noqa: E402
from run_prediction import (  # type: ignore # noqa: E402
    COMPONENT_ORDER,
    N_SUBJECTS,
    TERMS_DIR,
    TermLoader,
    _load_folds,
    _pearson_r,
)

# Like build_residualised_target.py, this sanity check needs staged HCP-YA
# behavior (Open Access) for the extended covariate set; point --hcp-csv /
# $A1_HCP_CSV at your local export. The default residualised target is the
# pack's shipped copy.
PACK_ROOT = HERE.parent
NUMERIC_COVS = [
    "Age_in_Yrs",
    "Handedness",
    "BMI",
    "PMAT24_A_CR",
    "ListSort_Unadj",
    "ReadEng_Unadj",
]


def load_extended_covariates(subjects):
    df = pd.read_csv(HCP_CSV).set_index("Subject")
    df_num = df.loc[[int(s) for s in subjects], NUMERIC_COVS].apply(
        pd.to_numeric, errors="coerce"
    )
    gender = (
        df.loc[[int(s) for s in subjects], "Gender"]
        .map({"F": 0.0, "M": 1.0})
        .astype(float)
    )
    acq_series = df.loc[[int(s) for s in subjects], "Acquisition"].astype(str)
    ref_acq = acq_series.value_counts().idxmax()
    levels = sorted(a for a in acq_series.unique() if a != ref_acq)
    acq_oh = pd.DataFrame(
        {f"acq_{a}": (acq_series == a).astype(float).values for a in levels},
        index=acq_series.index,
    )
    full = pd.concat([df_num, gender.rename("Gender"), acq_oh], axis=1)
    return full.to_numpy(dtype=np.float64), list(full.columns)


def _impute(C, train_rows):
    C = C.copy()
    for j in range(C.shape[1]):
        m = float(np.nanmean(C[train_rows, j]))
        if np.isnan(m):
            m = 0.0
        C[np.isnan(C[:, j]), j] = m
    return C


def _ols_beta(C, y):
    A = np.concatenate([np.ones((C.shape[0], 1)), C], axis=1)
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def _apply(beta, C):
    A = np.concatenate([np.ones((C.shape[0], 1)), C], axis=1)
    return A @ beta


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "§5.1 within-fold cheap check on the residualised target. Needs a "
            "SUBJECT-KEYED residualised CSV (from build_residualised_target.py) "
            "plus staged HCP-YA behavior for the extended covariate set — this is "
            "a deeper-provenance step, not required to reproduce the headline A1 "
            "recovery numbers (use run_prediction.py for those)."
        )
    )
    ap.add_argument(
        "--resid-csv",
        default=os.environ.get(
            "A1_RESID_CSV",
            str(
                PACK_ROOT
                / "artifacts"
                / "liu_component_behavior_residualised_cognition.csv"
            ),
        ),
        help="Subject-keyed residualised target CSV (must contain a Subject column).",
    )
    ap.add_argument(
        "--hcp-csv",
        default=os.environ.get("A1_HCP_CSV", ""),
        required=not os.environ.get("A1_HCP_CSV"),
        help="Staged HCP-YA subjects CSV ($A1_HCP_CSV).",
    )
    args = ap.parse_args()
    global RESID_CSV, HCP_CSV
    RESID_CSV = Path(args.resid_csv)
    HCP_CSV = Path(args.hcp_csv)

    t0 = time.time()
    loader = TermLoader(TERMS_DIR)
    beh = pd.read_csv(RESID_CSV)
    if "Subject" not in beh.columns:
        raise ValueError(
            "cheap check requires a SUBJECT-KEYED residualised CSV (with a Subject "
            "column); the pack's shipped artifacts/ copy is row-indexed. Rebuild it "
            "with build_residualised_target.py against your staged HCP data first."
        )
    if len(beh) != N_SUBJECTS:
        raise ValueError(
            f"residualised behavior CSV has {len(beh)} rows, expected {N_SUBJECTS}"
        )
    Y = beh[COMPONENT_ORDER].to_numpy(dtype=np.float64)
    subjects = beh["Subject"].to_numpy()
    C_raw, cov_cols = load_extended_covariates(subjects)

    folds = _load_folds()
    raw_r = [[] for _ in range(len(COMPONENT_ORDER))]
    dec_r = [[] for _ in range(len(COMPONENT_ORDER))]
    for fold_id, (tr, te) in enumerate(folds):
        C = _impute(C_raw, tr)
        Ctr, Cte = C[tr], C[te]
        y_pred = predict_fold(loader, tr, te, Y[tr], fold_id)
        y_pred = np.asarray(y_pred, dtype=np.float64)
        for k in range(len(COMPONENT_ORDER)):
            yt = Y[te, k]
            yp = y_pred[:, k]
            raw_r[k].append(_pearson_r(yt, yp))
            beta_y = _ols_beta(Ctr, Y[tr, k])
            yt_res = yt - _apply(beta_y, Cte)
            beta_p = _ols_beta(Cte, yp)
            yp_res = yp - _apply(beta_p, Cte)
            dec_r[k].append(_pearson_r(yt_res, yp_res))
        print(f"fold {fold_id} done", flush=True)

    per_component = []
    for k, name in enumerate(COMPONENT_ORDER):
        rm = float(np.nanmean(raw_r[k]))
        dm = float(np.nanmean(dec_r[k]))
        per_component.append(
            {
                "component": name,
                "raw_fold_mean_r": round(rm, 6),
                "deconf_fold_mean_r": round(dm, 6),
                "delta_deconf_minus_raw": round(dm - rm, 6),
                "fraction_retained": round(dm / rm, 6) if abs(rm) > 1e-9 else None,
                "per_fold_raw_r": [round(v, 6) for v in raw_r[k]],
                "per_fold_deconf_r": [round(v, 6) for v in dec_r[k]],
            }
        )

    out = {
        "schema_version": "liu_a1_residualised_cheap_check_v1",
        "target_csv": str(RESID_CSV),
        "description": (
            "A1 sanity check. Frozen Path B refit on the intelligence-"
            "residualised Cognition target, then within-fold residualisation "
            "against {Age, Gender, Handedness, BMI, Acquisition (one-hot), "
            "PMAT24, ListSort, ReadEng}. Expected: near-zero further loss on "
            "Cognition (target already orthogonal to PMAT24/ListSort/ReadEng "
            "at the population level)."
        ),
        "covariate_cols": cov_cols,
        "per_component": per_component,
        "aggregate_raw_mean_r": round(
            float(np.mean([c["raw_fold_mean_r"] for c in per_component])), 6
        ),
        "aggregate_deconf_mean_r": round(
            float(np.mean([c["deconf_fold_mean_r"] for c in per_component])), 6
        ),
        "wall_time_sec": round(time.time() - t0, 3),
    }
    out_path = HERE / "residualised_cheap_check.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(
        json.dumps(
            {
                "agg_raw": out["aggregate_raw_mean_r"],
                "agg_deconf": out["aggregate_deconf_mean_r"],
                "cog_raw": per_component[0]["raw_fold_mean_r"],
                "cog_deconf": per_component[0]["deconf_fold_mean_r"],
                "cog_retained": per_component[0]["fraction_retained"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
