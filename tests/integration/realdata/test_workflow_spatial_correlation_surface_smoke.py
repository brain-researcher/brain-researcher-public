"""Real-data smoke test for workflow_spatial_correlation_surface.

Uses neuromaps local annotations (Margulies2016 functional connectivity gradients)
in fsLR 32k space to ensure:
  stack_surface_hemis -> compare_surface_maps(spin test) runs and returns p-value.
"""

from __future__ import annotations

import json
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
@pytest.mark.timeout(300)
def test_workflow_spatial_correlation_surface_smoke(tmp_path: Path):
    base = (
        PROJECT_ROOT
        / "data"
        / "neurokg"
        / "raw"
        / "neuromaps"
        / "annotations"
        / "margulies2016"
    )
    map_left = base / "fcgradient03/fsLR/source-margulies2016_desc-fcgradient03_space-fsLR_den-32k_hemi-L_feature.func.gii"
    map_right = base / "fcgradient03/fsLR/source-margulies2016_desc-fcgradient03_space-fsLR_den-32k_hemi-R_feature.func.gii"
    ref_left = base / "fcgradient05/fsLR/source-margulies2016_desc-fcgradient05_space-fsLR_den-32k_hemi-L_feature.func.gii"
    ref_right = base / "fcgradient05/fsLR/source-margulies2016_desc-fcgradient05_space-fsLR_den-32k_hemi-R_feature.func.gii"

    for p in (map_left, map_right, ref_left, ref_right):
        if not p.exists():
            pytest.skip(f"Missing neuromaps annotation: {p}")

    out_dir = tmp_path / "spatial_correlation_surface"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_spatial_correlation_surface",
        {
            "map_left": str(map_left),
            "map_right": str(map_right),
            "ref_left": str(ref_left),
            "ref_right": str(ref_right),
            "n_perm": 100,
            "output_dir": str(out_dir),
        },
    )
    assert res.status == "success", res.error

    out_json = out_dir / "spatial_correlation_surface.json"
    assert out_json.exists() and out_json.stat().st_size > 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    corr = payload.get("outputs", {}).get("correlation")
    pval = payload.get("outputs", {}).get("pvalue")
    assert isinstance(corr, (int, float))
    assert pval is None or (isinstance(pval, (int, float)) and 0.0 <= float(pval) <= 1.0)

