"""Real-data smoke test for SC-FC coupling workflow.

SC is derived from ds000117 DWI (tractography fallback), and FC is derived from
ds000114 fMRIPrep BOLD ROI timeseries.

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


def _resolve_repo_path(path: Path) -> Path:
    if path.exists():
        return path
    try:
        alt = PROJECT_ROOT.parent.parent / path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path
    return alt if alt.exists() else path


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(1200)
def test_workflow_sc_fc_coupling_smoke(tmp_path: Path):
    ds117 = Path(os.environ.get("BR_DS000117_BIDS_ROOT", "/app/data/openneuro/ds000117"))
    if not ds117.exists():
        pytest.skip(f"ds000117 not found at {ds117}")

    dwi = ds117 / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.nii.gz"
    bval = ds117 / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.bval"
    bvec = ds117 / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.bvec"
    for p in (dwi, bval, bvec):
        if not p.exists():
            pytest.skip(f"Required DWI input missing: {p}")

    # Build a small FC timeseries tensor from ds000114 fMRIPrep.
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
            _resolve_repo_path(
                PROJECT_ROOT
                / "data"
                / "neurokg"
                / "raw"
                / "nilearn_atlases"
                / "schaefer_2018"
                / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
            ),
        )
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas file not found: {atlas_path}")

    subjects = ("sub-01", "sub-02")
    ts_list = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Required preproc BOLD missing: {img}")
        out_ts = tmp_path / f"ts_{sub}"
        out_ts.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {"img": str(img), "atlas": str(atlas_path), "output_dir": str(out_ts)},
        )
        assert res_ts.status == "success", res_ts.error
        ts_list.append(np.load(res_ts.data["outputs"]["timeseries"]))

    min_tp = min(ts.shape[0] for ts in ts_list)
    ts_stack = np.stack([ts[:min_tp] for ts in ts_list], axis=0)
    ts_file = tmp_path / "timeseries.npy"
    np.save(ts_file, ts_stack)

    # Run tractography to obtain a tractogram path.
    tracts_dir = tmp_path / "tracts"
    tracts_dir.mkdir(parents=True, exist_ok=True)
    res_tracts = execute_tool(
        "run_tractography",
        {"dwi": str(dwi), "bvals": str(bval), "bvecs": str(bvec), "output_dir": str(tracts_dir)},
    )
    assert res_tracts.status == "success", res_tracts.error
    tractogram = res_tracts.data["outputs"]["streamlines"]

    out_dir = tmp_path / "sc_fc"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_sc_fc_coupling",
        {
            "tractogram": tractogram,
            "atlas": str(atlas_path),
            "timeseries": str(ts_file),
            "connectivity_kind": "correlation",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    assert (out_dir / "sc.npy").exists() or (out_dir / "sc" / "connectivity_matrix.csv").exists()
    assert (out_dir / "fc.npy").exists()
