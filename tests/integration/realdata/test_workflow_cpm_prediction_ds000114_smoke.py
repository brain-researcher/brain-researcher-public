"""Real-data smoke test for workflow_cpm_prediction on ds000114.

Current workflow implementation runs:
  timeseries -> connectivity -> ml_cross_validation
It does *not* yet implement the full CPM edge-selection/regression steps, but
this test ensures the workflow is runnable end-to-end on real OpenNeuro data.

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


def _labels_from_participants(participants_tsv: Path, subjects: list[str]) -> np.ndarray:
    df = pd.read_csv(participants_tsv, sep="\t")
    mapping = dict(zip(df["participant_id"].astype(str), df["dominant_hand"].astype(str)))
    y = []
    for sub in subjects:
        hand = mapping.get(sub)
        if hand is None:
            raise RuntimeError(f"Subject {sub} not found in participants.tsv")
        y.append(1 if hand.strip().lower() == "left" else 0)
    y = np.asarray(y, dtype="int64")
    if np.unique(y).size != 2:
        raise RuntimeError(f"Need two classes, got labels={y.tolist()}")
    return y


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_cpm_prediction_ds000114_smoke(tmp_path: Path):
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
    imgs = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Missing required preproc BOLD: {img}")
        imgs.append(img)

    y = _labels_from_participants(participants, subjects)
    labels_file = tmp_path / "labels.npy"
    np.save(labels_file, y)

    tr = float(nib.load(str(imgs[0])).header.get_zooms()[3])

    ts_list = []
    for sub, img in zip(subjects, imgs):
        sub_dir = tmp_path / "timeseries" / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {"img": str(img), "atlas": str(atlas_path), "tr": tr, "output_dir": str(sub_dir)},
        )
        assert res_ts.status == "success", res_ts.error
        ts_file = Path((res_ts.data or {}).get("outputs", {}).get("timeseries", ""))
        assert ts_file.exists() and ts_file.stat().st_size > 0
        ts_list.append(np.load(ts_file))

    ts = np.stack(ts_list, axis=0).astype("float32")
    ts_file = tmp_path / "timeseries_group.npy"
    np.save(ts_file, ts)

    out_dir = tmp_path / "cpm_prediction"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_cpm_prediction",
        {
            "timeseries": str(ts_file),
            "labels": str(labels_file),
            "connectivity_kind": "correlation",
            "cv_type": "kfold",
            "n_splits": 2,
            "task_type": "classification",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    assert (out_dir / "connectivity.npy").exists()
    assert (out_dir / "cv" / "cv_summary.json").exists()

