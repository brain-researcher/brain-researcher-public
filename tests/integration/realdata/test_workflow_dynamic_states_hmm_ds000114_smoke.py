"""Real-data smoke test for workflow_dynamic_states_hmm on ds000114.

This validates the end-to-end path:
  extract_timeseries -> workflow_dynamic_states_hmm (sliding_window/dynamic_connectivity)

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_dynamic_states_hmm_ds000114_smoke(tmp_path: Path):
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

    img = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    if not img.exists():
        pytest.skip(f"Missing required derivative: {img}")

    atlas = (
        PROJECT_ROOT
        / "data"
        / "neurokg"
        / "raw"
        / "nilearn_atlases"
        / "schaefer_2018"
        / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    if not atlas.exists():
        pytest.skip(f"Atlas not found: {atlas}")

    ts_dir = tmp_path / "timeseries"
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
    ts_file = Path(res_ts.data["outputs"]["timeseries"])
    assert ts_file.exists() and ts_file.stat().st_size > 0

    out_dir = tmp_path / "dynamic_states"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_dynamic_states_hmm",
        {
            "timeseries": str(ts_file),
            "window_length": 30,
            "step_size": 10,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    # Outputs are written directly into output_dir by dynamic_connectivity
    assert (out_dir / "dynamic_summary.json").exists()
    assert (out_dir / "dynamic_matrices.npy").exists()
    assert (out_dir / "state_assignments.npy").exists()

