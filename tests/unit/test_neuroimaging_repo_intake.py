from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "configs" / "workflows" / "neuroimaging_repo_intake.yaml"
SCRIPT = ROOT / "scripts" / "check_neuroimaging_repo_intake.py"


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def test_neuroimaging_repo_intake_structure_and_decision() -> None:
    payload = _load_registry()

    assert payload["version"] == "1.0"
    assert payload["decision"]["preproc_qc_first"]["answer"] == "yes"

    family_ids = {family["family_id"] for family in payload["families"]}
    assert family_ids == {
        "preproc_qc_bids_apps",
        "structural_surface",
        "diffusion_reconstruction",
        "broader_frameworks",
    }


def test_neuroimaging_repo_intake_has_expected_key_entries() -> None:
    payload = _load_registry()
    all_entries = {
        entry["repo_slug"]: entry
        for family in payload["families"]
        for entry in family["entries"]
    }

    assert all_entries["nipreps/fmriprep"]["recommended_workflow"] == (
        "workflow_fmriprep_preprocessing"
    )
    assert all_entries["nipreps/mriqc"]["current_state"] == "present_not_standardized"
    assert all_entries["Washington-University/workbench"]["current_state"] == (
        "already_usable"
    )
    assert all_entries["FCP-INDI/C-PAC"]["current_state"] == (
        "missing_and_should_acquire"
    )


def test_check_neuroimaging_repo_intake_script_passes() -> None:
    cmd = [sys.executable, str(SCRIPT), "--registry", str(REGISTRY)]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    assert result["summary"]["valid_registry"] is True
    assert result["summary"]["family_count"] == 4
    assert result["summary"]["entry_count"] >= 10
    assert result["summary"]["already_usable_count"] >= 2
    assert result["summary"]["present_not_standardized_count"] >= 5
    assert result["summary"]["missing_and_should_acquire_count"] >= 2
    assert result["validation_errors"] == []
