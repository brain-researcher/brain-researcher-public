"""Real-data smoke test for PPI workflow on ds000114.

Marked as `realdata` so it is skipped by default in CI. Intended for local
validation on machines that have the OpenNeuro ds000114 dataset available.
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
def test_workflow_ppi_analysis_ds000114_smoke(tmp_path: Path):
    bids_root = Path(os.environ.get("BR_DS000114_BIDS_ROOT", "/app/data/openneuro/ds000114"))
    if not bids_root.exists():
        pytest.skip(f"ds000114 not found at {bids_root}")

    img_test = bids_root / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_bold.nii.gz"
    img_retest = bids_root / "sub-01/ses-retest/func/sub-01_ses-retest_task-linebisection_bold.nii.gz"
    ev_test = bids_root / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_events.tsv"
    ev_retest = bids_root / "sub-01/ses-retest/func/sub-01_ses-retest_task-linebisection_events.tsv"

    for p in (img_test, img_retest, ev_test, ev_retest):
        if not p.exists():
            pytest.skip(f"Required ds000114 file missing: {p}")

    tr = float(nib.load(str(img_test)).header.get_zooms()[3])

    mn0, mx0 = _bbox_world(img_test)
    mn1, mx1 = _bbox_world(img_retest)
    mn = np.maximum(mn0, mn1)
    mx = np.minimum(mx0, mx1)
    seed_coords = ((mn + mx) / 2.0).tolist()

    out_dir = tmp_path / "ppi_workflow"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_ppi_analysis",
        {
            "img": [str(img_test), str(img_retest)],
            "events": [str(ev_test), str(ev_retest)],
            "seed_coords": seed_coords,
            "t_r": tr,
            "output_dir": str(out_dir),
        },
    )

    assert res.status == "success", res.error

    ppi_dir = out_dir / "ppi"
    assert (ppi_dir / "ppi_zmap_00.nii.gz").exists()
    assert (ppi_dir / "ppi_zmap_01.nii.gz").exists()

    group_dir = out_dir / "group"
    assert (group_dir / "group_zmap.nii.gz").exists()

