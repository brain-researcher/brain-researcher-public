"""Real-data smoke test for workflow_surface_projection_analysis on ds000114.

This validates the end-to-end path:
  seed_based_fc (3D NIfTI) -> map_volume_to_surface -> parcellate_cifti -> stack

Marked as `realdata` so it is skipped by default in CI.
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
def test_workflow_surface_projection_analysis_ds000114_smoke(tmp_path: Path):
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

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_map = seed_dir / "seed_based_fc.nii.gz"
    res_seed = execute_tool(
        "seed_based_fc",
        {
            "img": str(img),
            "seed_coords": seed_coords,
            "t_r": tr,
            "confounds": str(confounds),
            "mask_img": str(mask),
            "output_file": str(seed_map),
        },
    )
    assert res_seed.status == "success", res_seed.error
    assert seed_map.exists() and seed_map.stat().st_size > 0

    out_dir = tmp_path / "surface_projection"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_surface_projection_analysis",
        {
            "volume": str(seed_map),
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    # Surface projections
    surf_l = out_dir / "surface_L.func.gii"
    surf_r = out_dir / "surface_R.func.gii"
    stacked = out_dir / "surface.func.gii"
    for p in (surf_l, surf_r, stacked):
        assert p.exists() and p.stat().st_size > 0
        img_obj = nib.load(str(p))
        assert isinstance(img_obj, nib.gifti.GiftiImage)
        assert len(img_obj.darrays) >= 1

    # Parcellated maps
    parc_l = out_dir / "parcellation_L.func.gii"
    parc_r = out_dir / "parcellation_R.func.gii"
    parc_stacked = out_dir / "parcellation.func.gii"
    for p in (parc_l, parc_r, parc_stacked):
        assert p.exists() and p.stat().st_size > 0
        img_obj = nib.load(str(p))
        assert isinstance(img_obj, nib.gifti.GiftiImage)
        assert len(img_obj.darrays) >= 1

