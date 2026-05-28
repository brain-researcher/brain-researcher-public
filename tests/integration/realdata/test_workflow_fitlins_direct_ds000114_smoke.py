"""Real-data smoke test for FitLins direct workflow on ds000114.

Marked as `realdata` + `slow` so it is skipped by default. Intended for local
validation on machines that have ds000114 inputs and FitLins runtime available.
"""

from __future__ import annotations

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
@pytest.mark.timeout(1800)
def test_workflow_fitlins_direct_ds000114_smoke(tmp_path: Path):
    try:
        import fitlins  # noqa: F401
    except Exception:
        pytest.skip("FitLins python package not available in environment")

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

    model = Path(
        os.environ.get(
            "BR_FITLINS_MODEL",
            "/app/brain_researcher/data/openneuro_glmfitlins/"
            "statsmodel_specs/ds000114/ds000114-linebisection_specs.json",
        )
    )
    if not model.exists():
        pytest.skip(f"FitLins model spec not found: {model}")

    # Use a short path to avoid AF_UNIX path length limits in Nipype/FitLins.
    out_dir = (
        Path(
            os.environ.get(
                "BR_FITLINS_TEST_OUTDIR",
                str(TMP_ROOT / "fitlins_direct_smoke"),
            )
        )
        .expanduser()
        .resolve()
    )
    if out_dir.exists():
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_fitlins_direct",
        {
            "bids_dir": str(bids_root),
            "fmriprep_dir": str(fmriprep_root),
            "task": "linebisection",
            "participant_label": ["01", "02"],
            "model": str(model),
            "container_type": "wrapper",
            "container_image": "",
            "output_dir": str(out_dir),
            # FitLins is heavyweight and can be brittle across environments.
            # For smoke tests, validate command construction + input wiring.
            "dry_run": True,
        },
    )
    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_fitlins_direct"
    assert provenance.get("recipe_family") == "fitlins_direct"

    outputs = workflow_data.get("outputs", {})
    assert outputs.get("dry_run") is True
    assert outputs.get("preview_only") is True
    assert outputs.get("fitlins_dir", "").endswith("/fitlins")
    cmd = (
        outputs.get("command")
        or outputs.get("command_host")
        or outputs.get("command_container")
    )
    assert cmd, outputs
    assert out_dir.exists() and out_dir.is_dir()
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    assert "--model" in cmd_str
