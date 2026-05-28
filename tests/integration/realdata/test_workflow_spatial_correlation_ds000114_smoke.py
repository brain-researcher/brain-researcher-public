"""Real-data smoke test for workflow_spatial_correlation (volumetric).

Builds a seed-based functional connectivity map from real ds000114 fMRIPrep
derivatives, then correlates it with a local neuromaps MNI152 annotation via
query_neuromaps + compare_surface_maps (volumetric path, no null permutations).

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import json
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
def test_workflow_spatial_correlation_ds000114_smoke(tmp_path: Path):
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
    confounds = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_desc-confounds_timeseries.tsv"
    )
    mask = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-brain_mask.nii.gz"
    )
    for p in (img, confounds, mask):
        if not p.exists():
            pytest.skip(f"Missing required derivative: {p}")

    tr = float(nib.load(str(img)).header.get_zooms()[3])

    seed_dir = tmp_path / "seed_based_connectivity"
    seed_dir.mkdir(parents=True, exist_ok=True)
    res_seed = execute_tool(
        "workflow_seed_based_connectivity",
        {
            "img": str(img),
            "seed_coords": [0.0, -52.0, 18.0],
            "t_r": tr,
            "confounds": str(confounds),
            "mask_img": str(mask),
            "output_dir": str(seed_dir),
        },
    )
    assert res_seed.status == "success", res_seed.error
    map_file = seed_dir / "seed_based_fc.nii.gz"
    assert map_file.exists() and map_file.stat().st_size > 0

    out_dir = tmp_path / "spatial_correlation"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_spatial_correlation",
        {
            "map_file": str(map_file),
            # Local MNI152 neuromaps annotation shipped with the repo cache.
            "reference_term": "cogpc1",
            "n_perm": 0,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    out_json = out_dir / "spatial_correlation.json"
    assert out_json.exists() and out_json.stat().st_size > 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    corr = payload.get("outputs", {}).get("correlation")
    assert isinstance(corr, (int, float))

