"""Real-data smoke test for workflow_local_activity_analysis on ds000114.

Validates that we can compute voxelwise local activity maps end-to-end:
  compute_alff (writes alff + falff) + compute_reho (AFNI 3dReHo)
"""

from __future__ import annotations

import os
from pathlib import Path

import nibabel as nib
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_local_activity_analysis_ds000114_smoke(tmp_path: Path):
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
    mask = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-brain_mask.nii.gz"
    )
    for p in (img, mask):
        if not p.exists():
            pytest.skip(f"Missing required derivative: {p}")

    out_dir = tmp_path / "local_activity"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_local_activity_analysis",
        {
            "img": str(img),
            "mask": str(mask),
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    alff = out_dir / "alff.nii.gz"
    falff = out_dir / "falff.nii.gz"
    reho = out_dir / "reho.nii.gz"
    for p in (alff, falff, reho):
        assert p.exists() and p.stat().st_size > 0

    # Basic sanity checks on output geometry
    img_ref = nib.load(str(mask))
    for p in (alff, falff, reho):
        out_img = nib.load(str(p))
        assert out_img.shape[:3] == img_ref.shape[:3]

