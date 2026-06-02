"""Real-data smoke test for workflow_neurosynth_roi_analysis.

Runs a lightweight Neurosynth (NiMARE) term query to build an activation map,
then summarizes it within a real MNI ROI mask and performs coordinate decoding.

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

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


@pytest.mark.realdata
@pytest.mark.timeout(900)
def test_workflow_neurosynth_roi_analysis_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dataset_path = (
        PROJECT_ROOT / "data" / "neurosynth_nimare" / "neurosynth_dataset_v7.pkl.gz"
    )
    if not dataset_path.exists():
        pytest.skip(f"Neurosynth dataset not found: {dataset_path}")

    atlas_path = (
        PROJECT_ROOT
        / "data"
        / "br_kg"
        / "raw"
        / "nilearn_atlases"
        / "schaefer_2018"
        / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    if not atlas_path.exists():
        pytest.skip(f"Atlas not found: {atlas_path}")

    # Reduce runtime/memory for a smoke test.
    monkeypatch.setenv("NEUROSYNTH_MAX_STUDIES", "100")
    monkeypatch.setenv("NEUROSYNTH_MAX_COORDINATES", "2000")
    monkeypatch.setenv("NEUROSYNTH_SPHERE_RADIUS_MM", "6")

    atlas_img = nib.load(str(atlas_path))
    atlas_data = np.asanyarray(atlas_img.dataobj)
    roi_mask = (atlas_data == 1).astype(np.uint8)
    roi_path = tmp_path / "roi_mask.nii.gz"
    nib.Nifti1Image(roi_mask, atlas_img.affine, atlas_img.header).to_filename(
        str(roi_path)
    )

    out_dir = tmp_path / "neurosynth_roi_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_neurosynth_roi_analysis",
        {
            "roi_mask": str(roi_path),
            "term": "memory",
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error
    assert res.data and "steps" in res.data

    steps = res.data["steps"]
    meta = steps.get("meta", {}).get("data", {})
    stat_map = meta.get("outputs", {}).get("stat_map")
    meta_json = meta.get("outputs", {}).get("meta_json")
    assert (
        isinstance(stat_map, str)
        and Path(stat_map).exists()
        and Path(stat_map).stat().st_size > 0
    )
    assert (
        isinstance(meta_json, str)
        and Path(meta_json).exists()
        and Path(meta_json).stat().st_size > 0
    )

    roi_tsv = out_dir / "roi" / "roi_values.tsv"
    assert roi_tsv.exists() and roi_tsv.stat().st_size > 0

    decode = steps.get("decode", {}).get("data", {})
    assert isinstance(decode, dict)
