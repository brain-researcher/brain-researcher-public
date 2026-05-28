"""Real-data smoke test for workflow_ml_decoding_pipeline on ds000114.

Builds a compact feature matrix from real fMRIPrep preproc BOLD via:
  group_ica (CanICA timecourses) -> compute_connectivity -> vectorize edges
Then runs the declarative ML decoding workflow using dominant_hand labels.

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


def _labels_from_participants(participants_tsv: Path, subjects: list[str]) -> np.ndarray:
    df = pd.read_csv(participants_tsv, sep="\t")
    mapping = dict(zip(df["participant_id"].astype(str), df["dominant_hand"].astype(str)))
    labels = []
    for sub in subjects:
        hand = mapping.get(sub)
        if hand is None:
            raise RuntimeError(f"Subject {sub} not found in participants.tsv")
        labels.append(1 if hand.strip().lower() == "left" else 0)
    labels = np.asarray(labels, dtype="int64")
    if np.unique(labels).size != 2:
        raise RuntimeError(f"Need two classes, got labels={labels.tolist()}")
    return labels


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(1200)
def test_workflow_ml_decoding_pipeline_ds000114_smoke(tmp_path: Path):
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

    subjects = ["sub-01", "sub-02", "sub-03", "sub-06"]
    imgs = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Missing required preproc BOLD: {img}")
        imgs.append(str(img))

    y = _labels_from_participants(participants, subjects)

    ica_dir = tmp_path / "ica"
    ica_dir.mkdir(parents=True, exist_ok=True)
    res_ica = execute_tool(
        "group_ica",
        {"img": imgs, "n_components": 10, "output_dir": str(ica_dir)},
    )
    assert res_ica.status == "success", res_ica.error
    tc_file = Path((res_ica.data or {}).get("outputs", {}).get("timecourses_file", ""))
    assert tc_file.exists() and tc_file.stat().st_size > 0

    conn_file = tmp_path / "connectivity.npy"
    res_conn = execute_tool(
        "compute_connectivity",
        {"timeseries": str(tc_file), "kind": "correlation", "output_file": str(conn_file)},
    )
    assert res_conn.status == "success", res_conn.error
    mats = np.load(conn_file)
    assert mats.ndim == 3 and mats.shape[0] == len(subjects)
    n = mats.shape[1]
    assert mats.shape[2] == n

    iu = np.triu_indices(n, k=1)
    X = np.stack([mats[i][iu].astype("float32") for i in range(mats.shape[0])], axis=0)

    data_file = tmp_path / "X.npy"
    labels_file = tmp_path / "y.npy"
    groups_file = tmp_path / "groups.npy"
    np.save(data_file, X)
    np.save(labels_file, y)
    np.save(groups_file, np.arange(X.shape[0], dtype="int64"))

    out_dir = tmp_path / "ml_decoding"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_ml_decoding_pipeline",
        {
            "data_file": str(data_file),
            "labels_file": str(labels_file),
            "groups_file": str(groups_file),
            "cv_type": "kfold",
            "n_splits": 2,
            "task_type": "classification",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    assert (out_dir / "cv" / "cv_summary.json").exists()
    assert (out_dir / "decoder" / "mvpa_summary.json").exists()

