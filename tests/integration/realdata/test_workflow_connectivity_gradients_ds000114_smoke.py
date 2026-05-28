"""Real-data smoke test for workflow_connectivity_gradients on ds000114.

The current BR contract is connectivity + graph-topology fallback outputs,
including metrics, communities, a processed graph, and a visualization.
Marked as `realdata` so it is skipped by default.
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
@pytest.mark.timeout(600)
def test_workflow_connectivity_gradients_ds000114_smoke(tmp_path: Path):
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
            / "neurokg"
            / "raw"
            / "nilearn_atlases"
            / "schaefer_2018"
            / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
        )
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas file not found: {atlas_path}")

    tr = float(nib.load(str(img)).header.get_zooms()[3])

    ts_dir = tmp_path / "timeseries"
    ts_dir.mkdir(parents=True, exist_ok=True)
    res_ts = execute_tool(
        "extract_timeseries",
        {
            "img": str(img),
            "atlas": str(atlas_path),
            "tr": tr,
            "output_dir": str(ts_dir),
        },
    )
    assert res_ts.status == "success", res_ts.error
    ts_file = Path((res_ts.data or {}).get("outputs", {}).get("timeseries", ""))
    assert ts_file.exists() and ts_file.stat().st_size > 0

    out_dir = tmp_path / "connectivity_gradients"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_connectivity_gradients",
        {
            "timeseries": str(ts_file),
            "connectivity_kind": "correlation",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_connectivity_gradients"
    assert provenance.get("stage") == "connectivity"

    steps = workflow_data.get("steps") or {}
    connectivity_outputs = (
        (steps.get("connectivity") or {}).get("data", {}).get("outputs", {})
    )
    gradient_outputs = (steps.get("gradients") or {}).get("data", {}).get("outputs", {})

    conn = out_dir / "connectivity.npy"
    assert conn.exists() and conn.stat().st_size > 0
    assert Path(connectivity_outputs["matrix"]) == conn

    metrics = out_dir / "gradients" / "graph_metrics.json"
    communities = out_dir / "gradients" / "communities.json"
    processed_graph = out_dir / "gradients" / "thresholded_connectivity.npy"
    visualization = out_dir / "gradients" / "graph_theory_plot.png"
    assert metrics.exists() and metrics.stat().st_size > 0
    assert communities.exists() and communities.stat().st_size > 0
    assert processed_graph.exists() and processed_graph.stat().st_size > 0
    assert visualization.exists()

    assert Path(gradient_outputs["metrics"]) == metrics
    assert Path(gradient_outputs["communities"]) == communities
    assert Path(gradient_outputs["processed_graph"]) == processed_graph
    assert Path(gradient_outputs["visualization"]) == visualization

    workflow_outputs = workflow_data.get("outputs") or {}
    assert Path(workflow_outputs["connectivity_matrix"]) == conn
    assert Path(workflow_outputs["graph_metrics"]) == metrics
    assert Path(workflow_outputs["communities"]) == communities
    assert Path(workflow_outputs["thresholded_connectivity"]) == processed_graph
    assert Path(workflow_outputs["visualization"]) == visualization
    assert Path(workflow_outputs["graph_summary"]).exists()
