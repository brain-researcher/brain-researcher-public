"""Real-data smoke test for FitLins multiverse (yeo17) workflow.

Marked as `realdata` + `slow` so it is skipped by default. Intended for local
validation on machines that have ds000114 inputs available.
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
@pytest.mark.timeout(900)
def test_workflow_fitlins_multiverse_yeo17_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_FITLINS_BIDS_ROOT",
            PROJECT_ROOT / "out" / "openneuro_local" / "ds000114" / "bids",
        )
    )
    fmriprep_root = Path(
        os.environ.get(
            "BR_FITLINS_FMRIPREP_ROOT",
            PROJECT_ROOT
            / "outputs"
            / "_a4_ds000114_linebisection"
            / "derivatives_local"
            / "ds000114-fmriprep",
        )
    )

    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")
    if not fmriprep_root.exists():
        pytest.skip(f"fMRIPrep derivatives not found: {fmriprep_root}")

    # Current workflow defaults to participant-label 01,02
    for sub in ("sub-01", "sub-02"):
        if not (bids_root / sub).exists():
            pytest.skip(f"Missing required subject in BIDS root: {sub}")
        if not (fmriprep_root / sub).exists():
            pytest.skip(f"Missing required subject in fMRIPrep derivatives: {sub}")

    out_dir = tmp_path / "fitlins_multiverse"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_fitlins_multiverse_yeo17",
        {
            "bids_dir": str(bids_root),
            "fmriprep_dir": str(fmriprep_root),
            "output_dir": str(out_dir),
        },
    )

    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_fitlins_multiverse_yeo17"
    assert provenance.get("recipe_family") == "fitlins_multiverse"

    outputs = workflow_data.get("outputs") or {}
    manifest = Path(
        outputs.get("run_manifest")
        or out_dir / "fitlins_multiverse" / "run_manifest.json"
    )
    assert manifest.exists() and manifest.stat().st_size > 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    variants = payload.get("variants") or []
    assert variants, "No multiverse variants found in run_manifest.json"
    assert all(v.get("status") == "success" for v in variants)
    assert Path(outputs["analysis_bundle_json"]).exists()
    assert Path(outputs["observation_json"]).exists()
    assert Path(outputs["execution_manifest_json"]).exists()
    assert Path(outputs["provenance_json"]).exists()
    assert Path(outputs["source_summary_json"]).exists()
