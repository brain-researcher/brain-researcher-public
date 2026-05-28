"""Real-data smoke test for workflow_test_retest_metrics on ds000114.

Builds per-run connectivity feature vectors for (sub-01, sub-02) across
ses-test/ses-retest, then runs the declarative reliability workflow.

Marked as `realdata` + `slow` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_test_retest_metrics_ds000114_smoke(tmp_path: Path):
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

    subjects = ["sub-01", "sub-02"]
    sessions = ["ses-test", "ses-retest"]

    features = []
    subj_ids = []
    sess_ids = []

    for sub in subjects:
        for ses in sessions:
            img = (
                fmriprep_root
                / f"{sub}/{ses}/func/{sub}_{ses}_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
            )
            if not img.exists():
                pytest.skip(f"Missing required preproc BOLD: {img}")

            tr = float(nib.load(str(img)).header.get_zooms()[3])

            ts_dir = tmp_path / "timeseries" / sub / ses
            ts_dir.mkdir(parents=True, exist_ok=True)
            res_ts = execute_tool(
                "extract_timeseries",
                {"img": str(img), "atlas": str(atlas_path), "tr": tr, "output_dir": str(ts_dir)},
            )
            assert res_ts.status == "success", res_ts.error
            ts_file = Path((res_ts.data or {}).get("outputs", {}).get("timeseries", ""))
            assert ts_file.exists() and ts_file.stat().st_size > 0

            conn_file = tmp_path / "connectivity" / f"{sub}_{ses}.npy"
            conn_file.parent.mkdir(parents=True, exist_ok=True)
            res_conn = execute_tool(
                "compute_connectivity",
                {"timeseries": str(ts_file), "kind": "correlation", "output_file": str(conn_file)},
            )
            assert res_conn.status == "success", res_conn.error
            mat = np.load(conn_file)
            if mat.ndim == 3 and mat.shape[0] == 1:
                mat = mat[0]
            iu = np.triu_indices(mat.shape[0], k=1)
            vec = mat[iu].astype("float32")
            features.append(vec)
            subj_ids.append(sub)
            sess_ids.append(ses)

    X = np.stack(features, axis=0)
    features_file = tmp_path / "features.npy"
    np.save(features_file, X)

    out_dir = tmp_path / "retest_metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_test_retest_metrics",
        {
            "features": str(features_file),
            "subject_ids": subj_ids,
            "session_ids": sess_ids,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    summary = out_dir / "reliability" / "test_retest_metrics.json"
    assert summary.exists() and summary.stat().st_size > 0

