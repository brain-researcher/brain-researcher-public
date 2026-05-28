"""Targeted tests for recently wired grandmaster tools/workflows.

Covers:
- compare_surface_maps (neuromaps spin test, small n_perm)
- workflow_connectivity_gradients (single-subject matrix)
- workflow_seed_based_connectivity
- workflow_group_ica
- group_ica (CanICA lightweight implementation)

Notes:
- Uses existing neuromaps gradient files shipped in repo to avoid downloads.
- Sets TMPDIR to a writable project subdir to dodge /tmp permission issues.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
OUT_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(OUT_ROOT))


@pytest.mark.skipif(
    not (
        PROJECT_ROOT / "data/neurokg/raw/neuromaps/annotations/margulies2016"
    ).exists(),
    reason="neuromaps reference data not present",
)
def test_compare_surface_maps_spin():
    neuromaps = pytest.importorskip("neuromaps")
    """Spin-test comparison on fsLR32k gradients with small permutations."""
    base = PROJECT_ROOT / "data/neurokg/raw/neuromaps/annotations/margulies2016"
    g3_l = (
        base
        / "fcgradient03/fsLR/source-margulies2016_desc-fcgradient03_space-fsLR_den-32k_hemi-L_feature.func.gii"
    )
    g3_r = (
        base
        / "fcgradient03/fsLR/source-margulies2016_desc-fcgradient03_space-fsLR_den-32k_hemi-R_feature.func.gii"
    )
    g5_l = (
        base
        / "fcgradient05/fsLR/source-margulies2016_desc-fcgradient05_space-fsLR_den-32k_hemi-L_feature.func.gii"
    )
    g5_r = (
        base
        / "fcgradient05/fsLR/source-margulies2016_desc-fcgradient05_space-fsLR_den-32k_hemi-R_feature.func.gii"
    )

    for p in (g3_l, g3_r, g5_l, g5_r):
        assert p.exists(), f"Missing neuromaps file: {p}"

    out_dir = OUT_ROOT / "spin_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_spatial_correlation_surface",
        {
            "map_left": str(g3_l),
            "map_right": str(g3_r),
            "ref_left": str(g5_l),
            "ref_right": str(g5_r),
            "n_perm": 10,
            "output_dir": str(out_dir),
        },
    )

    assert res.status == "success", res.error
    outputs = res.data.get("outputs") or {}
    assert outputs.get("outputs"), "Missing outputs section"
    corr = outputs["outputs"]["correlation"]
    pval = outputs["outputs"]["pvalue"]
    assert isinstance(corr, float)
    assert pval is None or isinstance(pval, float)


def _make_synthetic_bold(path: Path):
    rng = np.random.default_rng(0)
    data = rng.standard_normal((8, 8, 8, 20)).astype(np.float32)  # x, y, z, time
    data += 5.0  # shift to ensure mask is non-empty for epi strategy
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)
    nib.save(img, path)
    return path


def test_group_ica_canica_outputs_timecourses(tmp_path: Path):
    """Ensure lightweight CanICA path writes components and non-empty timecourses."""
    bold = _make_synthetic_bold(tmp_path / "bold.nii.gz")
    # create an explicit brain mask to bypass epi mask auto-empty issue
    mask_path = tmp_path / "mask.nii.gz"
    nib.save(nib.Nifti1Image(np.ones((8, 8, 8), dtype=np.uint8), np.eye(4)), mask_path)
    out_dir = tmp_path / "ica"
    res = execute_tool(
        "group_ica",
        {
            "img": str(bold),
            "n_components": 3,
            "output_dir": str(out_dir),
            "mask": str(mask_path),
        },
    )
    assert res.status == "success", res.error
    outs = res.data["outputs"]
    tc = Path(outs["timecourses"])
    comps = Path(outs["components_file"])
    assert tc.exists() and tc.stat().st_size > 0
    assert comps.exists() and comps.stat().st_size > 0
    arr = np.load(tc)
    # CanICA.transform returns a list of (time x components) arrays per subject.
    # We persist as (subjects x time x components) when shapes match.
    assert arr.size > 0
    assert arr.ndim in (2, 3)
    if arr.ndim == 2:
        assert arr.shape[0] > 0 and arr.shape[1] > 0
    else:
        assert arr.shape[0] > 0 and arr.shape[1] > 0 and arr.shape[2] > 0


def test_workflow_connectivity_gradients_single_subject(tmp_path: Path):
    """Single-subject timeseries should run end-to-end."""
    ts = np.random.randn(1, 20, 6)  # subjects, timepoints, rois
    ts_file = tmp_path / "ts.npy"
    np.save(ts_file, ts)
    out_dir = tmp_path / "grad"
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
    conn = Path(steps["connectivity"]["data"]["outputs"]["matrix"])
    grad_outputs = steps["gradients"]["data"]["outputs"]
    metrics = Path(grad_outputs["metrics"])
    communities = Path(grad_outputs["communities"])
    processed_graph = Path(grad_outputs["processed_graph"])
    visualization = Path(grad_outputs["visualization"])
    assert conn.exists()
    assert metrics.exists()
    assert communities.exists()
    assert processed_graph.exists()
    assert visualization.exists()
    with metrics.open() as f:
        json.load(f)
    with communities.open() as f:
        json.load(f)

    workflow_outputs = workflow_data.get("outputs") or {}
    assert Path(workflow_outputs["connectivity_matrix"]) == conn
    assert Path(workflow_outputs["graph_metrics"]) == metrics
    assert Path(workflow_outputs["communities"]) == communities
    assert Path(workflow_outputs["thresholded_connectivity"]) == processed_graph
    assert Path(workflow_outputs["visualization"]) == visualization
    assert Path(workflow_outputs["graph_summary"]).exists()


@pytest.mark.skipif(
    not (
        PROJECT_ROOT
        / "data/neurokg/raw/neuromaps/atlases/fsLR/tpl-fsLR_den-32k_hemi-L_midthickness.surf.gii"
    ).exists(),
    reason="neuromaps fsLR 32k surface files not present",
)
def test_workflow_surface_projection_analysis_smoke(tmp_path: Path):
    """Project a volume to fsLR32k surface and parcellate, ensuring outputs exist."""
    nilearn = pytest.importorskip("nilearn")
    out_dir = tmp_path / "surface_projection"
    out_dir.mkdir(parents=True, exist_ok=True)

    vol = nilearn.datasets.load_mni152_template()
    vol_file = tmp_path / "mni152_template.nii.gz"
    vol.to_filename(vol_file)

    res = execute_tool(
        "workflow_surface_projection_analysis",
        {"volume": str(vol_file), "output_dir": str(out_dir)},
    )
    assert res.status == "success", res.error

    surface = out_dir / "surface.func.gii"
    parc = out_dir / "parcellation.func.gii"
    assert surface.exists() and surface.stat().st_size > 0
    assert parc.exists() and parc.stat().st_size > 0


def test_workflow_seed_based_connectivity_smoke(tmp_path: Path):
    """Run seed-based FC on a small real BIDS fixture image."""
    bold = (
        PROJECT_ROOT
        / "tests/fixtures/golden_data/bids_dataset/sub-01/ses-01/func/sub-01_ses-01_task-rest_bold.nii.gz"
    )
    assert bold.exists(), f"Missing fixture BOLD: {bold}"

    out_dir = tmp_path / "seed_fc"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Use the center voxel coordinate in world space for a stable in-mask seed.
    # The fixture affine is 2mm with origin -10mm, so voxel (5,5,5) maps to (0,0,0).
    res = execute_tool(
        "workflow_seed_based_connectivity",
        {
            "img": str(bold),
            "seed_coords": [0.0, 0.0, 0.0],
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
    assert Path(workflow_outputs["map"]) == out_map
    summary = (workflow_data.get("steps") or {}).get("seed_fc", {}).get("data", {}).get(
        "summary"
    ) or {}
    assert summary.get("used_nilearn_package") is True
    assert len(summary.get("seed") or []) == 3


def test_workflow_group_ica_smoke(tmp_path: Path):
    """Workflow-level group ICA should emit ICA, connectivity, and NBS artifacts."""
    bold = (
        PROJECT_ROOT
        / "tests/fixtures/golden_data/bids_dataset/sub-01/ses-01/func/sub-01_ses-01_task-rest_bold.nii.gz"
    )
    assert bold.exists(), f"Missing fixture BOLD: {bold}"

    out_dir = tmp_path / "group_ica_workflow"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_group_ica",
        {
            "img": [str(bold), str(bold)],
            "n_components": 3,
            "labels": [0, 1],
            "threshold": 1.0,
            "n_permutations": 5,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_group_ica"
    assert provenance.get("stage") == "connectivity"

    steps = workflow_data.get("steps") or {}
    ica_outputs = (steps.get("ica") or {}).get("data", {}).get("outputs", {})
    conn_outputs = (steps.get("conn") or {}).get("data", {}).get("outputs", {})
    stats_payload = (steps.get("stats") or {}).get("data") or {}

    components = Path(ica_outputs["components_file"])
    timecourses = Path(ica_outputs["timecourses"])
    connectivity = Path(conn_outputs["matrix"])
    tmap = Path(stats_payload["tmap_file"])
    supra_mask = Path(stats_payload["supra_mask_file"])
    components_json = Path(stats_payload["components_file"])
    assert components.exists() and components.stat().st_size > 0
    assert timecourses.exists() and timecourses.stat().st_size > 0
    assert connectivity.exists() and connectivity.stat().st_size > 0
    assert tmap.exists() and tmap.stat().st_size > 0
    assert supra_mask.exists() and supra_mask.stat().st_size > 0
    assert components_json.exists() and components_json.stat().st_size > 0

    workflow_outputs = workflow_data.get("outputs") or {}
    assert Path(workflow_outputs["components_file"]) == components
    assert Path(workflow_outputs["timecourses_file"]) == timecourses
    assert Path(workflow_outputs["connectivity_matrix"]) == connectivity
    assert Path(workflow_outputs["nbs_tmap"]) == tmap
    assert Path(workflow_outputs["nbs_supra_mask"]) == supra_mask
    assert Path(workflow_outputs["nbs_components"]) == components_json


def test_workflow_dynamic_states_hmm_smoke(tmp_path: Path):
    """Run dynamic states workflow on a real fixture BOLD via group_ica timecourses."""
    bold = (
        PROJECT_ROOT
        / "tests/fixtures/golden_data/bids_dataset/sub-01/ses-01/func/sub-01_ses-01_task-rest_bold.nii.gz"
    )
    assert bold.exists(), f"Missing fixture BOLD: {bold}"

    # Derive timeseries from BOLD using the existing group_ica tool (CanICA).
    ica_dir = tmp_path / "ica"
    ica_dir.mkdir(parents=True, exist_ok=True)

    mask_path = tmp_path / "mask.nii.gz"
    try:
        from nilearn.masking import compute_epi_mask  # type: ignore

        compute_epi_mask(str(bold)).to_filename(mask_path)
    except Exception:
        img = nib.load(str(bold))
        mask_data = np.ones(img.shape[:3], dtype=np.uint8)
        nib.save(nib.Nifti1Image(mask_data, img.affine), mask_path)

    ica_res = execute_tool(
        "group_ica",
        {
            "img": str(bold),
            "n_components": 3,
            "output_dir": str(ica_dir),
            "mask": str(mask_path),
        },
    )
    assert ica_res.status == "success", ica_res.error
    timecourses = Path(ica_res.data["outputs"]["timecourses_file"])
    assert timecourses.exists() and timecourses.stat().st_size > 0

    out_dir = tmp_path / "dynamic_states"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_dynamic_states_hmm",
        {
            "timeseries": str(timecourses),
            "window_length": 10,
            "step_size": 5,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    matrices = out_dir / "dynamic_matrices.npy"
    states = out_dir / "state_assignments.npy"
    summary = out_dir / "dynamic_summary.json"
    metrics = out_dir / "dynamic_metrics.json"
    for p in (matrices, states, summary, metrics):
        assert p.exists() and p.stat().st_size > 0
