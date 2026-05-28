"""Real-data smoke test for gene enrichment workflow.

Uses a seed-based FC map derived from ds000114 fMRIPrep BOLD as the input map.

Marked as `realdata` so it is skipped by default in CI.
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
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_workflow_gene_enrichment_ds000114_smoke(tmp_path: Path):
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

    tr = float(nib.load(str(img)).header.get_zooms()[3])

    seed_out = tmp_path / "seed_fc"
    seed_out.mkdir(parents=True, exist_ok=True)
    seed_map = seed_out / "seed_fc.nii.gz"
    res_seed = execute_tool(
        "seed_based_fc",
        {
            "img": str(img),
            "seed_coords": [0.0, 0.0, 0.0],
            "t_r": tr,
            "output_file": str(seed_map),
        },
    )
    assert res_seed.status == "success", res_seed.error
    assert seed_map.exists() and seed_map.stat().st_size > 0

    out_dir = tmp_path / "gene_enrichment"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_gene_enrichment",
        {"map_file": str(seed_map), "output_dir": str(out_dir)},
    )
    assert res.status == "success", res.error
    assert (out_dir / "gene_enrichment.csv").exists()

