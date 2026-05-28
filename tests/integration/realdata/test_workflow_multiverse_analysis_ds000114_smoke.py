"""Real-data smoke test for workflow_multiverse_analysis on ds000114.

Note: this workflow is currently a lightweight placeholder:
  standardize_confounds(strategy) -> derivatives_sanity_checker

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
@pytest.mark.timeout(300)
def test_workflow_multiverse_analysis_ds000114_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000114_BIDS_ROOT",
            "/app/data/openneuro/ds000114",
        )
    )
    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")

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

    confounds = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_desc-confounds_timeseries.tsv"
    )
    if not confounds.exists():
        pytest.skip(f"Confounds file not found: {confounds}")

    out_dir = tmp_path / "multiverse"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_multiverse_analysis",
        {
            "bids_dir": str(bids_root),
            "confounds": str(confounds),
            "preset": "motion",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    assert (out_dir / "confounds_variant.csv").exists()
    assert (out_dir / "multiverse_report.json").exists()

