"""Real-data smoke test for seed-based connectivity workflow on ds000114.

Marked as `realdata` so it is skipped by default in CI. Uses fMRIPrep MNI-space
preprocessed BOLD + confounds + brain mask from the repo-local derivatives.
"""

from __future__ import annotations

import itertools
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


def _bbox_world(path: Path) -> tuple[np.ndarray, np.ndarray]:
    img = nib.load(str(path))
    nx, ny, nz = img.shape[:3]
    corners = []
    for i, j, k in itertools.product([0, nx - 1], [0, ny - 1], [0, nz - 1]):
        corners.append(img.affine.dot([i, j, k, 1.0])[:3])
    corners = np.asarray(corners)
    return corners.min(axis=0), corners.max(axis=0)


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_seed_based_connectivity_ds000114_smoke(tmp_path: Path):
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
    confounds = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_desc-confounds_timeseries.tsv"
    )
    mask = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-brain_mask.nii.gz"
    )

    for p in (img, confounds, mask):
        if not p.exists():
            pytest.skip(f"Missing required derivative: {p}")

    tr = float(nib.load(str(img)).header.get_zooms()[3])

    mn, mx = _bbox_world(img)
    seed_coords = ((mn + mx) / 2.0).tolist()

    out_dir = tmp_path / "seed_based_connectivity"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_seed_based_connectivity",
        {
            "img": str(img),
            "seed_coords": seed_coords,
            "t_r": tr,
            "confounds": str(confounds),
            "mask_img": str(mask),
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_seed_based_connectivity"
    assert provenance.get("recipe_family") == "seed_based_connectivity"
    assert provenance.get("primary_target") == "python"

    out_map = out_dir / "seed_based_fc.nii.gz"
    assert out_map.exists() and out_map.stat().st_size > 0

    workflow_outputs = workflow_data.get("outputs") or {}
    step_outputs = (
        (workflow_data.get("steps") or {})
        .get("seed_fc", {})
        .get("data", {})
        .get("outputs", {})
    )
    assert Path(step_outputs["map"]) == out_map
    assert Path(workflow_outputs["map"]) == out_map
    summary = (workflow_data.get("steps") or {}).get("seed_fc", {}).get("data", {}).get(
        "summary"
    ) or {}
    assert summary.get("used_nilearn_package") is True
    assert len(summary.get("seed") or []) == 3

    out_img = nib.load(str(out_map))
    assert out_img.shape == nib.load(str(img)).shape[:3]
    data = np.asanyarray(out_img.dataobj)
    assert np.isfinite(data).all()
