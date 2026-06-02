"""Real-data smoke test for workflow_visual_decoding on ds000114.

Builds a small features matrix from Schaefer-100 connectivity edges and uses
dominant_hand from participants.tsv as labels.

Marked as `realdata` + `slow` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from brain_researcher.services.tools.runner import execute_tool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _upper_tri(mat: np.ndarray) -> np.ndarray:
    if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
        raise ValueError("connectivity matrix must be square")
    iu = np.triu_indices(mat.shape[0], k=1)
    return mat[iu]


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_workflow_visual_decoding_ds000114_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000114_BIDS_ROOT",
            "/app/data/openneuro/ds000114",
        )
    )
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

    participants = bids_root / "participants.tsv"
    if not participants.exists():
        pytest.skip(f"participants.tsv not found: {participants}")
    part_df = pd.read_csv(participants, sep="\t")
    if (
        "participant_id" not in part_df.columns
        or "dominant_hand" not in part_df.columns
    ):
        pytest.skip("participants.tsv missing participant_id/dominant_hand columns")

    label_map = {"left": 0, "right": 1}
    part_df["label"] = part_df["dominant_hand"].astype(str).str.lower().map(label_map)
    part_df = part_df.dropna(subset=["label"]).copy()

    # Keep runtime reasonable: small subject subset
    subjects = ["sub-01", "sub-02", "sub-03", "sub-04"]
    part_df = part_df[part_df["participant_id"].isin(subjects)]
    if part_df.shape[0] < 4:
        pytest.skip("Not enough labeled subjects for visual decoding smoke test")

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

    atlas = (
        PROJECT_ROOT
        / "data"
        / "br_kg"
        / "raw"
        / "nilearn_atlases"
        / "schaefer_2018"
        / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    if not atlas.exists():
        pytest.skip(f"Atlas not found: {atlas}")

    feats = []
    labels = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Missing required derivative: {img}")

        ts_dir = tmp_path / "timeseries" / sub
        ts_dir.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {
                "img": str(img),
                "atlas": str(atlas),
                "output_dir": str(ts_dir),
            },
        )
        assert res_ts.status == "success", res_ts.error
        ts_file = res_ts.data["outputs"]["timeseries"]

        conn_file = tmp_path / "conn" / f"{sub}.npy"
        conn_file.parent.mkdir(parents=True, exist_ok=True)
        res_conn = execute_tool(
            "compute_connectivity",
            {
                "timeseries": ts_file,
                "kind": "correlation",
                "output_file": str(conn_file),
            },
        )
        assert res_conn.status == "success", res_conn.error
        mat = np.load(res_conn.data["outputs"]["matrix"])
        if mat.ndim == 3 and mat.shape[0] == 1:
            mat = mat[0]
        feats.append(_upper_tri(mat))

        row = part_df[part_df["participant_id"] == sub].iloc[0]
        labels.append(int(row["label"]))

    X = np.stack(feats)
    y = np.asarray(labels, dtype=int)
    features_file = tmp_path / "features.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(features_file, X)
    np.save(labels_file, y)

    out_dir = tmp_path / "visual_decoding"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_visual_decoding",
        {
            "features": str(features_file),
            "labels": str(labels_file),
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    pred = out_dir / "visual_decode" / "pred.npy"
    weights = out_dir / "visual_decode" / "weights.npy"
    assert pred.exists() and pred.stat().st_size > 0
    assert weights.exists() and weights.stat().st_size > 0
