"""Real-data smoke test for TMS targeting workflow.

Uses ds000114-derived FC connectivity matrix as input.

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
@pytest.mark.timeout(600)
def test_workflow_tms_targeting_ds000114_smoke(tmp_path: Path):
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

    img = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    if not img.exists():
        pytest.skip(f"Required preproc BOLD missing: {img}")

    ts_dir = tmp_path / "ts"
    ts_dir.mkdir(parents=True, exist_ok=True)
    res_ts = execute_tool(
        "extract_timeseries",
        {"img": str(img), "atlas": str(atlas_path), "output_dir": str(ts_dir)},
    )
    assert res_ts.status == "success", res_ts.error
    ts = np.load(res_ts.data["outputs"]["timeseries"])
    ts_file = tmp_path / "ts.npy"
    np.save(ts_file, ts[np.newaxis, ...])

    conn_file = tmp_path / "fc.npy"
    res_conn = execute_tool(
        "connectivity_matrix",
        {
            "timeseries": str(ts_file),
            "kind": "correlation",
            "output_file": str(conn_file),
        },
    )
    assert res_conn.status == "success", res_conn.error
    assert conn_file.exists() and conn_file.stat().st_size > 0

    out_dir = tmp_path / "tms"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_tms_targeting",
        {"connectivity_matrix": str(conn_file), "output_dir": str(out_dir)},
    )
    assert res.status == "success", res.error
    assert (out_dir / "tms_target.json").exists()
