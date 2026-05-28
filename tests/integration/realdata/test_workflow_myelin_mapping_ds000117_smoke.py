"""Real-data smoke test for myelin mapping workflow using ds000117 FLASH/T1w.

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
def test_workflow_myelin_mapping_ds000117_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000117_BIDS_ROOT",
            "/app/data/openneuro/ds000117",
        )
    )
    if not bids_root.exists():
        pytest.skip(f"ds000117 not found at {bids_root}")

    t1w = bids_root / "sub-01/ses-mri/anat/sub-01_ses-mri_acq-mprage_T1w.nii.gz"
    if not t1w.exists():
        pytest.skip(f"T1w missing: {t1w}")

    out_dir = tmp_path / "myelin"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_myelin_mapping",
        {"t1w": str(t1w), "output_dir": str(out_dir)},
    )
    assert res.status == "success", res.error
    assert (out_dir / "myelin_map.nii.gz").exists() and (
        out_dir / "myelin_map.nii.gz"
    ).stat().st_size > 0
