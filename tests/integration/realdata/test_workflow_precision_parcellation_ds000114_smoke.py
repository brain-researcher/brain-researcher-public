"""Real-data smoke test for workflow_precision_parcellation on ds000114.

This validates:
  extract_timeseries -> workflow_precision_parcellation (individual_parcellation)

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from brain_researcher.services.tools.runner import execute_tool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


@pytest.mark.realdata
@pytest.mark.timeout(300)
def test_workflow_precision_parcellation_ds000114_smoke(tmp_path: Path):
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
        pytest.skip(f"Missing required derivative: {img}")

    atlas = (
        PROJECT_ROOT
        / "data"
        / "br_kg"
        / "raw"
        / "nilearn_atlases"
        / "schaefer_2018"
        / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    if not atlas.exists():
        pytest.skip(f"Atlas not found: {atlas}")

    ts_dir = tmp_path / "timeseries"
    ts_dir.mkdir(parents=True, exist_ok=True)
    res_ts = execute_tool(
        "extract_timeseries",
        {
            "img": str(img),
            "atlas": str(atlas),
            "output_dir": str(ts_dir),
        },
    )
    assert res_ts.status == "success", res_ts.error
    ts_file = Path(res_ts.data["outputs"]["timeseries"])
    assert ts_file.exists() and ts_file.stat().st_size > 0

    out_dir = tmp_path / "precision_parcellation"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_precision_parcellation",
        {
            "timeseries": str(ts_file),
            "n_components": 10,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    workflow_outputs = res.data["outputs"]["outputs"]
    out_npz = out_dir / "parcellation.npz"
    labels_path = out_dir / "parcellation_labels.npy"
    stability_path = out_dir / "parcellation_stability_report.json"
    provenance_path = out_dir / "parcellation_provenance.json"

    assert out_npz.exists() and out_npz.stat().st_size > 0
    assert labels_path.exists() and labels_path.stat().st_size > 0
    assert stability_path.exists() and stability_path.stat().st_size > 0
    assert provenance_path.exists() and provenance_path.stat().st_size > 0

    assert Path(workflow_outputs["npz"]) == out_npz
    assert Path(workflow_outputs["labels"]) == labels_path
    assert Path(workflow_outputs["stability_report"]) == stability_path
    assert Path(workflow_outputs["provenance"]) == provenance_path

    payload = np.load(out_npz)
    assert "time_factors" in payload and "spatial_components" in payload

    labels = np.load(labels_path)
    assert labels.ndim == 1
    assert labels.shape[0] == payload["spatial_components"].shape[1]

    stability = json.loads(stability_path.read_text(encoding="utf-8"))
    assert "mean_pairwise_ari" in stability
    assert "best_seed" in stability

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["tool"] == "individual_parcellation_tool"
    assert provenance["reference_context"]["reference_asset_ids"] == [
        "nilearn.atlas.schaefer2018.400.17networks",
        "nilearn.atlas.yeo2011.17networks.volume",
    ]
    assert provenance["reference_context"]["atlas_family"] == (
        "precision_parcellation_reference"
    )
