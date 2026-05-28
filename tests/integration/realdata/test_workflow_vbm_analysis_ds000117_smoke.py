"""Real-data smoke test for VBM analysis workflow using ds000117 T1w.

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
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_vbm_analysis_ds000117_smoke(tmp_path: Path):
    bids_root = Path(os.environ.get("BR_DS000117_BIDS_ROOT", "/app/data/openneuro/ds000117"))
    if not bids_root.exists():
        pytest.skip(f"ds000117 not found at {bids_root}")

    t1w = bids_root / "sub-01/ses-mri/anat/sub-01_ses-mri_acq-mprage_T1w.nii.gz"
    if not t1w.exists():
        pytest.skip(f"T1w missing: {t1w}")

    # Build a minimal gm_maps list by running the segmenter twice (same file).
    seg1 = tmp_path / "seg1"
    seg2 = tmp_path / "seg2"
    seg1.mkdir(parents=True, exist_ok=True)
    seg2.mkdir(parents=True, exist_ok=True)
    res1 = execute_tool("unified_segmenter", {"t1w": str(t1w), "output_dir": str(seg1)})
    res2 = execute_tool("unified_segmenter", {"t1w": str(t1w), "output_dir": str(seg2)})
    assert res1.status == "success", res1.error
    assert res2.status == "success", res2.error
    gm_maps = [
        res1.data["outputs"]["gm_prob_map"],
        res2.data["outputs"]["gm_prob_map"],
    ]

    out_dir = tmp_path / "vbm"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_vbm_analysis",
        {"t1w": str(t1w), "gm_maps": gm_maps, "output_dir": str(out_dir)},
    )
    assert res.status == "success", res.error
    group_map = out_dir / "stats" / "group_zmap.nii.gz"
    assert group_map.exists() and group_map.stat().st_size > 0

