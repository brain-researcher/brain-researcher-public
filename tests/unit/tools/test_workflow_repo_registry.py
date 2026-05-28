from __future__ import annotations

from pathlib import Path

import yaml

from brain_researcher.services.tools.workflow_repo_registry import (
    clear_workflow_repo_registry_cache,
    get_repo_candidate,
    get_repo_candidate_for_workflow,
    list_repo_candidates,
)


def _write_registry(tmp_path: Path) -> Path:
    registry_path = tmp_path / "neuroimaging_repo_intake.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "version": "test",
                "families": [
                    {
                        "family_id": "preproc_qc_bids_apps",
                        "title": "Preproc",
                        "entries": [
                            {
                                "repo_slug": "nipreps/fmriprep",
                                "repo_url": "https://github.com/nipreps/fmriprep",
                                "current_state": "present_not_standardized",
                                "domain": "fmri",
                                "packaging_mode": "container_workflow",
                                "interface_mode": "bids_app_cli",
                                "runtime_status": "ready_now",
                                "license_status": "permissive",
                                "priority": "P0",
                                "recommended_workflow": "workflow_fmriprep_preprocessing",
                                "why_it_matters": "important",
                                "next_action": "ship it",
                                "evidence_urls": ["https://github.com/nipreps/fmriprep"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry_path


def test_get_repo_candidate_and_workflow_lookup(monkeypatch, tmp_path):
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("BR_WORKFLOW_REPO_REGISTRY", str(registry_path))
    clear_workflow_repo_registry_cache()

    repo = get_repo_candidate("nipreps/fmriprep")
    assert repo is not None
    assert repo["family_id"] == "preproc_qc_bids_apps"

    workflow_repo = get_repo_candidate_for_workflow("workflow_fmriprep_preprocessing")
    assert workflow_repo is not None
    assert workflow_repo["repo_slug"] == "nipreps/fmriprep"

    clear_workflow_repo_registry_cache()


def test_list_repo_candidates_filters(monkeypatch, tmp_path):
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("BR_WORKFLOW_REPO_REGISTRY", str(registry_path))
    clear_workflow_repo_registry_cache()

    rows = list_repo_candidates(
        family_id="preproc_qc_bids_apps",
        packaging_mode="container_workflow",
        priority="P0",
    )
    assert len(rows) == 1
    assert rows[0]["repo_slug"] == "nipreps/fmriprep"

    clear_workflow_repo_registry_cache()
