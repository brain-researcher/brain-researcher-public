"""Real-data smoke test for rest-connectome workflow on ds000114 derivatives.

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


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_workflow_rest_connectome_e2e_ds000114_smoke(tmp_path: Path):
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
        pytest.skip(f"Required preproc BOLD missing: {img}")

    atlas_path = Path(
        os.environ.get(
            "BR_SCHAEFER100_ATLAS",
            PROJECT_ROOT
            / "data"
            / "br_kg"
            / "raw"
            / "nilearn_atlases"
            / "schaefer_2018"
            / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
        )
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas file not found: {atlas_path}")

    out_dir = tmp_path / "rest_connectome"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_rest_connectome_e2e",
        {
            "img": str(img),
            "atlas_name": "Schaefer2018_100",
            "atlas_path": str(atlas_path),
            "connectivity_kind": "correlation",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_rest_connectome_e2e"
    assert provenance.get("recipe_family") == "rest_connectome"
    assert provenance.get("primary_target") == "python"

    steps = workflow_data.get("steps") or {}
    atlas_outputs = (steps.get("atlas") or {}).get("data", {}).get("outputs", {})
    timeseries_outputs = (
        (steps.get("timeseries") or {}).get("data", {}).get("outputs", {})
    )
    connectivity_outputs = (
        (steps.get("connectivity") or {}).get("data", {}).get("outputs", {})
    )
    assert Path(atlas_outputs["atlas_path"]).exists()
    assert Path(atlas_outputs["labels_tsv"]).exists()
    assert Path(atlas_outputs["labels_json"]).exists()
    assert Path(timeseries_outputs["timeseries"]).exists()
    assert Path(timeseries_outputs["timeseries_csv"]).exists()
    assert Path(timeseries_outputs["summary"]).exists()

    matrix_file = out_dir / "connectivity_matrix.npy"
    assert matrix_file.exists() and matrix_file.stat().st_size > 0
    assert Path(connectivity_outputs["matrix"]) == matrix_file

    workflow_outputs = workflow_data.get("outputs") or {}
    assert Path(workflow_outputs["atlas_path"]).exists()
    assert Path(workflow_outputs["timeseries"]) == Path(
        timeseries_outputs["timeseries"]
    )
    assert Path(workflow_outputs["timeseries_csv"]) == Path(
        timeseries_outputs["timeseries_csv"]
    )
    assert Path(workflow_outputs["connectivity_matrix"]) == matrix_file
    assert workflow_data["summary"]["n_subjects"] == 1

    mat = np.load(matrix_file)
    assert mat.ndim == 3 and mat.shape[0] == 1, f"unexpected matrix shape: {mat.shape}"
    assert mat.shape[1] == mat.shape[2], f"matrix not square: {mat.shape}"
    assert np.isfinite(mat).all()
    assert np.allclose(mat, np.swapaxes(mat, 1, 2), atol=1e-5)
