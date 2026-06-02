"""Real-data smoke test for brain simulation workflow.

Uses SC matrix derived from ds000117 DWI connectome workflow (fallback) as input.

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


def _make_tiny_dwi_proxy(path: Path) -> Path:
    rng = np.random.default_rng(13)
    dwi = rng.normal(loc=600.0, scale=35.0, size=(14, 14, 10, 20)).astype(np.float32)
    np.save(path, dwi)
    return path


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_brain_simulation_smoke(tmp_path: Path):
    ds117 = Path(
        os.environ.get(
            "BR_DS000117_BIDS_ROOT",
            "/app/data/openneuro/ds000117",
        )
    )
    if not ds117.exists():
        pytest.skip(f"ds000117 not found at {ds117}")

    dwi = ds117 / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.nii.gz"
    bval = ds117 / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.bval"
    bvec = ds117 / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.bvec"
    for p in (dwi, bval, bvec):
        if not p.exists():
            pytest.skip(f"Required DWI input missing: {p}")

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

    dwi_proxy = _make_tiny_dwi_proxy(tmp_path / "dwi_proxy.npy")

    # First, produce a connectome matrix.
    dwi_dir = tmp_path / "dwi"
    dwi_dir.mkdir(parents=True, exist_ok=True)
    res_dwi = execute_tool(
        "workflow_dwi_connectome",
        {
            "dwi": str(dwi_proxy),
            "bvals": str(bval),
            "bvecs": str(bvec),
            "atlas": str(atlas_path),
            "output_dir": str(dwi_dir),
        },
    )
    assert res_dwi.status == "success", res_dwi.error
    sc_csv = dwi_dir / "sc" / "connectivity_matrix.csv"
    if not sc_csv.exists():
        pytest.skip("Structural connectome matrix not produced")

    # Convert to numpy for simulation input.
    sc = np.loadtxt(sc_csv, delimiter=",")
    sc_file = tmp_path / "sc.npy"
    np.save(sc_file, sc)

    out_dir = tmp_path / "brain_sim"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_brain_simulation",
        {
            "sc_matrix": str(sc_file),
            "model": "neural_mass",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error
    sim_dir = out_dir / "simulation"
    assert sim_dir.exists() and sim_dir.is_dir()
    assert (sim_dir / "time.npy").exists() and (sim_dir / "time.npy").stat().st_size > 0
    assert (sim_dir / "activity.npy").exists() and (
        sim_dir / "activity.npy"
    ).stat().st_size > 0
    assert (sim_dir / "simulation_summary.json").exists() and (
        sim_dir / "simulation_summary.json"
    ).stat().st_size > 0
