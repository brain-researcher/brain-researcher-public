"""Real-data smoke test for workflow_task_glm_group on ds000114.

This validates the mature metadata contract for the composite GLM workflow:
subject-level first-level z-maps, second-level group z-map, summary artifacts,
and workflow provenance should all be produced coherently.

Marked as `realdata` so it is skipped by default in CI. Intended for local
validation on machines that have ds000114 inputs available.
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
@pytest.mark.timeout(600)
def test_workflow_task_glm_group_ds000114_smoke(tmp_path: Path):
    bids_root = Path(
        os.environ.get(
            "BR_DS000114_BIDS_ROOT",
            PROJECT_ROOT / "out" / "openneuro_local" / "ds000114" / "bids",
        )
    )
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

    if not bids_root.exists():
        pytest.skip(f"BIDS root not found: {bids_root}")
    if not fmriprep_root.exists():
        pytest.skip(f"fMRIPrep derivatives not found: {fmriprep_root}")

    img1 = (
        fmriprep_root
        / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    img2 = (
        fmriprep_root
        / "sub-02/ses-test/func/sub-02_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    ev1 = (
        bids_root / "sub-01/ses-test/func/sub-01_ses-test_task-linebisection_events.tsv"
    )
    ev2 = (
        bids_root / "sub-02/ses-test/func/sub-02_ses-test_task-linebisection_events.tsv"
    )

    for p in (img1, img2, ev1, ev2):
        if not p.exists():
            pytest.skip(f"Required ds000114 file missing: {p}")

    out_dir = tmp_path / "task_glm_group"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = execute_tool(
        "workflow_task_glm_group",
        {
            "bids_dir": str(bids_root),
            "fmriprep_dir": str(fmriprep_root),
            "task": "linebisection",
            "participant_label": ["01", "02"],
            "output_dir": str(out_dir),
        },
    )

    assert res.status == "success", res.error

    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_task_glm_group"
    assert provenance.get("recipe_family") == "task_glm_group"
    outputs = workflow_data.get("outputs") or {}
    assert outputs.get("route") in {"direct_inputs", "bids_fmriprep_derivatives"}
    assert len(outputs.get("first_level_dirs") or []) == 2
    assert len(outputs.get("selected_zmaps") or []) == 2
    assert outputs.get("resolved_inputs_manifest")
    assert Path(outputs["resolved_inputs_manifest"]).exists()
    assert Path(outputs["group_zmap"]) == (
        out_dir / "second_level" / "group_zmap.nii.gz"
    )

    steps = workflow_data.get("steps") or {}
    first_level_payload = (steps.get("first_level") or {}).get("data") or {}
    second_level_payload = (steps.get("second_level") or {}).get("data") or {}
    workflow_outputs = workflow_data.get("outputs") or {}

    first_level = out_dir / "first_level"
    sub01_summary = first_level / "sub-01" / "glm_first_level_summary.json"
    sub02_summary = first_level / "sub-02" / "glm_first_level_summary.json"
    assert sub01_summary.exists()
    assert sub02_summary.exists()

    second_level = out_dir / "second_level"
    group_zmap = second_level / "group_zmap.nii.gz"
    group_summary = second_level / "glm_second_level_summary.json"
    assert group_zmap.exists()
    assert group_summary.exists()

    selected = first_level_payload["outputs"]["selected_zmaps"]
    first_level_dirs = first_level_payload["outputs"]["first_level_dirs"]
    manifest = first_level_payload["outputs"]["resolved_inputs_manifest"]
    assert len(selected) == 2
    assert len(first_level_dirs) == 2
    assert Path(manifest).exists()
    assert Path(selected[0]).exists()
    assert Path(selected[1]).exists()
    assert Path(first_level_dirs[0]).exists()
    assert Path(first_level_dirs[1]).exists()
    assert Path(second_level_payload["outputs"]["zmap"]) == group_zmap
    assert Path(second_level_payload["outputs"]["summary"]) == group_summary
    assert workflow_outputs["route"] == "bids_fmriprep_derivatives"
    assert Path(workflow_outputs["resolved_inputs_manifest"]) == Path(manifest)
