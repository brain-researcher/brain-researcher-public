"""Real-data smoke test for naturalistic ISC workflow on ds000114.

Marked as `realdata` so it is skipped by default in CI. Intended for local
validation on machines that have ds000114 fMRIPrep derivatives available.
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
@pytest.mark.timeout(600)
def test_workflow_naturalistic_isc_ds000114_smoke(tmp_path: Path):
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
                / "br_kg"
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
    ts_files: list[str] = []
    for sub in subjects:
        img = (
            fmriprep_root
            / f"{sub}/ses-test/func/{sub}_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        )
        if not img.exists():
            pytest.skip(f"Required preproc BOLD missing: {img}")

        out_dir = tmp_path / f"ts_{sub}"
        out_dir.mkdir(parents=True, exist_ok=True)
        res_ts = execute_tool(
            "extract_timeseries",
            {"img": str(img), "atlas": str(atlas_path), "output_dir": str(out_dir)},
        )
        assert res_ts.status == "success", res_ts.error
        ts_files.append(res_ts.data["outputs"]["timeseries"])

    # Hyperalignment expects a list of 2D (time x roi) arrays stored on disk.
    out_dir = tmp_path / "isc"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_naturalistic_isc",
        {
            "data_files": ts_files,
            "method": "procrustes",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error
    results = out_dir / "isc" / "hyperalignment_results.json"
    assert results.exists() and results.stat().st_size > 0
