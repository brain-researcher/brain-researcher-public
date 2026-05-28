"""Real-data smoke test for workflow_rsa_model_brain on ds000114.

Derives a small connectivity-feature representation for several subjects and
builds a brain RDM from between-subject similarity. A simple model RDM is built
from dominant_hand labels. Then runs the declarative RSA workflow.

Marked as `realdata` + `slow` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _upper_triangle_features(mat: np.ndarray, n_keep: int = 200) -> np.ndarray:
    if mat.ndim == 3 and mat.shape[0] == 1:
        mat = mat[0]
    iu = np.triu_indices(mat.shape[0], k=1)
    vec = mat[iu].astype("float32")
    if vec.size < n_keep:
        raise RuntimeError(f"Connectivity vector too small: {vec.size} < {n_keep}")
    return vec[:n_keep]


def _labels_from_participants(participants_tsv: Path, subjects: list[str]) -> np.ndarray:
    df = pd.read_csv(participants_tsv, sep="\t")
    mapping = dict(zip(df["participant_id"].astype(str), df["dominant_hand"].astype(str)))
    labels = []
    for sub in subjects:
        hand = mapping.get(sub)
        if hand is None:
            raise RuntimeError(f"Subject {sub} not found in participants.tsv")
        labels.append(1 if hand.strip().lower() == "left" else 0)
    return np.asarray(labels, dtype="int64")


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_rsa_model_brain_ds000114_smoke(tmp_path: Path):
    openneuro_root = Path(
        os.environ.get(
            "BR_DS000114_OPENNEURO_ROOT",
            "/app/data/openneuro/ds000114",
        )
    )
    participants = openneuro_root / "participants.tsv"
    if not participants.exists():
        pytest.skip(f"participants.tsv not found: {participants}")

    fmriprep_root = Path(
        os.environ.get(
            "BR_DS000114_FMRIPREP_ROOT",
            PROJECT_ROOT
            / "outputs"
            / "_a4_ds000114_linebisection"
            / "derivatives_local"
            / "ds000114-fmriprep",
        )
    )
    if not fmriprep_root.exists():
        pytest.skip(f"fMRIPrep derivatives not found: {fmriprep_root}")

    atlas_path = Path(
        os.environ.get(
            "BR_SCHAEFER100_ATLAS",
            PROJECT_ROOT
            / "data"
            / "neurokg"
            / "raw"
            / "nilearn_atlases"
            / "schaefer_2018"
            / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
        )
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas file not found: {atlas_path}")

    subjects = ["sub-01", "sub-02", "sub-03", "sub-06"]
    y = _labels_from_participants(participants, subjects)

    feats = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Missing required preproc BOLD: {img}")

        tr = float(nib.load(str(img)).header.get_zooms()[3])

        ts_dir = tmp_path / "timeseries" / sub
        ts_dir.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {"img": str(img), "atlas": str(atlas_path), "tr": tr, "output_dir": str(ts_dir)},
        )
        assert res_ts.status == "success", res_ts.error
        ts_file = Path((res_ts.data or {}).get("outputs", {}).get("timeseries", ""))
        assert ts_file.exists() and ts_file.stat().st_size > 0

        conn_file = tmp_path / "connectivity" / f"{sub}.npy"
        conn_file.parent.mkdir(parents=True, exist_ok=True)
        res_conn = execute_tool(
            "compute_connectivity",
            {"timeseries": str(ts_file), "kind": "correlation", "output_file": str(conn_file)},
        )
        assert res_conn.status == "success", res_conn.error
        mat = np.load(conn_file)
        feats.append(_upper_triangle_features(mat, n_keep=200))

    X = np.stack(feats, axis=0)

    # Brain RDM: 1 - Pearson correlation between subject feature vectors.
    corr = np.corrcoef(X)
    brain_rdm = 1.0 - corr
    np.fill_diagonal(brain_rdm, 0.0)

    # Model RDM: absolute label differences (0 if same, 1 if different).
    model_rdm = np.abs(y[:, None] - y[None, :]).astype("float32")

    brain_rdm_file = tmp_path / "brain_rdm.npy"
    model_rdm_file = tmp_path / "model_rdm.npy"
    np.save(brain_rdm_file, brain_rdm.astype("float32"))
    np.save(model_rdm_file, model_rdm)

    out_dir = tmp_path / "rsa"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_rsa_model_brain",
        {"brain_rdm": str(brain_rdm_file), "model_rdm": str(model_rdm_file), "output_dir": str(out_dir)},
    )
    assert res.status == "success", res.error

    rsa_csv = out_dir / "rsa.csv"
    assert rsa_csv.exists() and rsa_csv.stat().st_size > 0
    out_df = pd.read_csv(rsa_csv)
    assert "correlation" in out_df.columns

