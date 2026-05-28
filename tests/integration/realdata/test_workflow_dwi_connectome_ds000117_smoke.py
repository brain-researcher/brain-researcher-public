"""Real-data smoke test for workflow_dwi_connectome on ds000117.

Uses ds000117 raw DWI gradients plus a standard atlas to validate the mature
composite-workflow metadata contract. The current runtime still uses a tiny DWI
proxy for tractography compute while preserving real bvals/bvecs and atlas
inputs.

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
    rng = np.random.default_rng(11)
    dwi = rng.normal(loc=600.0, scale=30.0, size=(14, 14, 10, 20)).astype(np.float32)
    np.save(path, dwi)
    return path


@pytest.mark.realdata
@pytest.mark.slow
@pytest.mark.timeout(900)
def test_workflow_dwi_connectome_ds000117_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000117_BIDS_ROOT",
            "/app/data/openneuro/ds000117",
        )
    )
    if not bids_root.exists():
        pytest.skip(f"ds000117 not found at {bids_root}")

    dwi = bids_root / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.nii.gz"
    bval = bids_root / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.bval"
    bvec = bids_root / "sub-01/ses-mri/dwi/sub-01_ses-mri_dwi.bvec"
    for p in (dwi, bval, bvec):
        if not p.exists():
            pytest.skip(f"Required DWI input missing: {p}")

    atlas_path = Path(
        os.environ.get(
            "BR_SCHAEFER100_ATLAS",
            _resolve_repo_path(
                PROJECT_ROOT
                / "data"
                / "neurokg"
                / "raw"
                / "nilearn_atlases"
                / "schaefer_2018"
                / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
            ),
        )
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas file not found: {atlas_path}")

    qsirecon_root = Path(
        os.environ.get(
            "BR_DS000117_QSIRECON_ROOT",
            bids_root / "derivatives" / "qsirecon",
        )
    )

    out_dir = tmp_path / "dwi_connectome"
    out_dir.mkdir(parents=True, exist_ok=True)
    params = {
        "atlas": str(atlas_path),
        "output_dir": str(out_dir),
    }
    if qsirecon_root.exists():
        params["qsirecon_dir"] = str(qsirecon_root)
    else:
        dwi_proxy = _make_tiny_dwi_proxy(tmp_path / "dwi_proxy.npy")
        params.update(
            {
                "dwi": str(dwi_proxy),
                "bvals": str(bval),
                "bvecs": str(bvec),
            }
        )

    res = execute_tool("workflow_dwi_connectome", params)
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_dwi_connectome"
    assert provenance.get("recipe_family") == "dwi_connectome"

    workflow_outputs = workflow_data.get("outputs") or {}
    steps = workflow_data.get("steps") or {}
    sc_dir = out_dir / "sc"
    conn_csv = sc_dir / "connectivity_matrix.csv"
    conn_npy = sc_dir / "connectivity_matrix.npy"
    graph_metrics = sc_dir / "graph_metrics.json"
    manifest = sc_dir / "connectome_manifest.json"
    assert conn_csv.exists() and conn_csv.stat().st_size > 0
    assert conn_npy.exists() and conn_npy.stat().st_size > 0
    assert graph_metrics.exists() and graph_metrics.stat().st_size > 0
    assert manifest.exists() and manifest.stat().st_size > 0

    if qsirecon_root.exists():
        summary = workflow_outputs.get("summary") or {}
        final_outputs = workflow_outputs.get("outputs") or {}
        assert summary.get("used_derivatives") is True
        assert final_outputs.get("qsirecon_dir") == str(qsirecon_root)
        assert Path(final_outputs["connectivity_matrix"]) == conn_csv
        assert Path(final_outputs["connectivity_matrix_npy"]) == conn_npy
        assert Path(final_outputs["graph_metrics"]) == graph_metrics
        assert Path(final_outputs["manifest"]) == manifest
    else:
        tracts_payload = (steps.get("tracts") or {}).get("data") or {}
        sc_payload = (steps.get("sc") or {}).get("data") or {}

        streamlines = Path(tracts_payload["outputs"]["streamlines"])
        tractography_summary = Path(tracts_payload["outputs"]["results"])
        tractography_provenance = Path(tracts_payload["outputs"]["provenance_json"])
        assert streamlines.exists() and streamlines.stat().st_size > 0
        assert tractography_summary.exists() and tractography_summary.stat().st_size > 0
        assert (
            tractography_provenance.exists()
            and tractography_provenance.stat().st_size > 0
        )

        assert Path(sc_payload["outputs"]["connectivity_matrix"]) == conn_csv
        assert Path(sc_payload["outputs"]["connectivity_matrix_npy"]) == conn_npy
        assert Path(sc_payload["outputs"]["graph_metrics"]) == graph_metrics
        assert Path(sc_payload["outputs"]["manifest"]) == manifest
