import json
from pathlib import Path

from brain_researcher.services.agent.kg_resolution import (
    _path_from_mounts,
    collect_dataset_resources,
    find_existing_derivatives,
)


def _write_catalog(path: Path, row: dict):
    path.write_text(json.dumps(row) + "\n")


def _write_minimal_bids_fmri(root: Path, *, task: str = "emotion") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "Test", "BIDSVersion": "1.9.0"})
    )
    func_dir = root / "sub-01" / "func"
    func_dir.mkdir(parents=True, exist_ok=True)
    stem = f"sub-01_task-{task}_bold"
    (func_dir / f"{stem}.nii.gz").write_text("nifti-placeholder")
    (func_dir / f"{stem}.json").write_text(json.dumps({"RepetitionTime": 2.0}))


def _mock_openneuro_api(
    monkeypatch, dataset_id: str, snapshots: list[dict] | None = None
):
    class _Response:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "dataset": {
                        "id": dataset_id,
                        "snapshots": snapshots or [],
                    }
                }
            }

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: _Response())


def test_collect_dataset_resources(tmp_path, monkeypatch):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:openneuro:ds000114"
    simple_id = "ds000114"
    _mock_openneuro_api(
        monkeypatch,
        simple_id,
        snapshots=[{"id": "snap-1", "tag": "1.0.0", "created": "2025-01-01T00:00:00Z"}],
    )

    # Minimal catalog row complying with schema
    row = {
        "dataset_id": dataset_id,
        "name": "Motor task dataset",
        "short_name": "Motor",
        "alias": [simple_id],
        "description": "Test dataset",
        "modalities": ["MRI", "fMRI"],
        "acquisitions": ["BOLD"],
        "species": ["human"],
        "source_repo": "OpenNeuro",
        "source_repo_id": simple_id,
        "primary_url": f"https://openneuro.org/datasets/{simple_id}",
        "access_type": "public",
        "license": "CC0",
        "has_derivatives": True,
    }
    _write_catalog(catalog_path, row)

    bids_root = tmp_path / "bids_root"
    bids_root.mkdir()
    _write_minimal_bids_fmri(bids_root / simple_id, task="motor")
    mounts_path.write_text(
        f"""
local:
  bids: {bids_root}
"""
    )

    glm_path = tmp_path / "glm" / simple_id
    glm_path.mkdir(parents=True)
    manual_row = {
        "dataset_id": dataset_id,
        "source_repo_id": simple_id,
        "path_glmfitlins": str(glm_path),
    }
    manual_path.write_text(json.dumps(manual_row) + "\n")

    resources = collect_dataset_resources(
        simple_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
    )

    assert resources is not None
    assert resources.is_bids_available is True
    assert str(resources.bids_path).endswith(simple_id)
    assert "glmfitlins" in resources.derivatives
    assert resources.remote_urls["openneuro"].endswith(simple_id)
    assert "glmfitlins" in resources.available_derivatives


def test_collect_dataset_resources_can_skip_source_access(tmp_path, monkeypatch):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:openneuro:ds000114"
    simple_id = "ds000114"
    _write_catalog(
        catalog_path,
        {
            "dataset_id": dataset_id,
            "name": "Motor task dataset",
            "short_name": "Motor",
            "alias": [simple_id],
            "description": "Test dataset",
            "modalities": ["MRI", "fMRI"],
            "acquisitions": ["BOLD"],
            "species": ["human"],
            "source_repo": "OpenNeuro",
            "source_repo_id": simple_id,
            "primary_url": f"https://openneuro.org/datasets/{simple_id}",
            "access_type": "public",
            "license": "CC0",
        },
    )
    bids_root = tmp_path / "bids_root"
    bids_root.mkdir()
    _write_minimal_bids_fmri(bids_root / simple_id, task="motor")
    mounts_path.write_text(
        f"""
local:
  bids: {bids_root}
"""
    )
    manual_path.write_text("")

    def fail_requests(*args, **kwargs):
        raise AssertionError("source access should be skipped")

    monkeypatch.setattr("requests.post", fail_requests)

    resources = collect_dataset_resources(
        simple_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        run_bids_validation=False,
        enforce_semantic_gate=False,
        check_source_access=False,
    )

    assert resources is not None
    assert resources.source_access["bucket_check"]["state"] == "skipped"
    assert resources.semantic_match["matched"] is True
    assert resources.semantic_match["mode"] == "skipped"


def test_collect_dataset_resources_prefers_exact_alias_over_fuzzy_name(
    tmp_path, monkeypatch
):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    primary_row = {
        "dataset_id": "ds:openneuro:ds900001",
        "name": "Natural Scenes Dataset",
        "short_name": "NSD",
        "alias": ["nsd"],
        "description": "Visual decoding dataset",
        "modalities": ["MRI", "fMRI"],
        "acquisitions": ["BOLD"],
        "species": ["human"],
        "source_repo": "OpenNeuro",
        "source_repo_id": "ds900001",
        "primary_url": "https://openneuro.org/datasets/ds900001",
        "access_type": "public",
        "license": "CC0",
    }
    fuzzy_row = {
        "dataset_id": "ds:openneuro:ds900002",
        "name": "NSD pilot task switching",
        "short_name": "Pilot",
        "alias": ["pilot-switch"],
        "description": "Contains NSD in name but is not the canonical dataset",
        "modalities": ["MRI", "fMRI"],
        "acquisitions": ["BOLD"],
        "species": ["human"],
        "source_repo": "OpenNeuro",
        "source_repo_id": "ds900002",
        "primary_url": "https://openneuro.org/datasets/ds900002",
        "access_type": "public",
        "license": "CC0",
    }
    catalog_path.write_text(
        json.dumps(primary_row) + "\n" + json.dumps(fuzzy_row) + "\n"
    )
    mounts_path.write_text("local: {}\n")
    manual_path.write_text("")

    _mock_openneuro_api(monkeypatch, "ds900001")

    resources = collect_dataset_resources(
        "nsd",
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        run_bids_validation=False,
    )

    assert resources is not None
    assert resources.resolved_dataset_id == "ds:openneuro:ds900001"
    assert resources.resolution_mode == "exact_alias"
    assert resources.resolver_warnings == []


def test_collect_dataset_resources_openneuro_mount_and_fmri_goal(tmp_path, monkeypatch):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:openneuro:ds004873"
    simple_id = "ds004873"
    _mock_openneuro_api(
        monkeypatch,
        simple_id,
        snapshots=[{"id": "snap-2", "tag": "1.2.0", "created": "2025-01-02T00:00:00Z"}],
    )

    _write_catalog(
        catalog_path,
        {
            "dataset_id": dataset_id,
            "name": "Calibrated BOLD study",
            "short_name": "Calibrated",
            "alias": [simple_id],
            "description": "BOLD and CMRO2 study",
            "modalities": ["MRI", "fMRI"],
            "acquisitions": ["BOLD", "ASL"],
            "species": ["human"],
            "source_repo": "OpenNeuro",
            "source_repo_id": simple_id,
            "primary_url": f"https://openneuro.org/datasets/{simple_id}",
            "access_type": "public",
            "license": "CC0",
        },
    )

    openneuro_root = tmp_path / "openneuro_mount"
    _write_minimal_bids_fmri(openneuro_root / simple_id)
    mounts_path.write_text(
        f"""
local:
  openneuro_local: {openneuro_root}
"""
    )
    manual_path.write_text("")

    resources = collect_dataset_resources(
        simple_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        analysis_goal="fmri-glm",
        run_bids_validation=False,
    )

    assert resources is not None
    assert resources.readiness["status"] == "ready"
    assert resources.required_files["all_required_passed"] is True
    assert any(
        t.get("stage") == "mount" and t.get("kind") == "raw" and t.get("hit")
        for t in resources.source_trace
    )


def test_collect_dataset_resources_semantic_gate_blocks_mismatch(tmp_path, monkeypatch):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:openneuro:ds999001"
    simple_id = "ds999001"
    _mock_openneuro_api(monkeypatch, simple_id)
    _write_catalog(
        catalog_path,
        {
            "dataset_id": dataset_id,
            "name": "Stroke lesion cohort",
            "short_name": "StrokeLesion",
            "alias": [simple_id],
            "description": "Stroke lesion maps with motor outcomes",
            "modalities": ["MRI"],
            "acquisitions": ["T1w"],
            "species": ["human"],
            "source_repo": "OpenNeuro",
            "source_repo_id": simple_id,
            "primary_url": f"https://openneuro.org/datasets/{simple_id}",
            "access_type": "public",
            "license": "CC0",
        },
    )

    openneuro_root = tmp_path / "openneuro_mount"
    ds_root = openneuro_root / simple_id
    ds_root.mkdir(parents=True, exist_ok=True)
    (ds_root / "dataset_description.json").write_text(
        json.dumps({"Name": "Stroke Lesion", "BIDSVersion": "1.9.0"})
    )
    anat_dir = ds_root / "sub-01" / "anat"
    anat_dir.mkdir(parents=True, exist_ok=True)
    (anat_dir / "sub-01_space-MNI152_label-lesion_roi.nii.gz").write_text("roi")

    mounts_path.write_text(
        f"""
local:
  openneuro_local: {openneuro_root}
"""
    )
    manual_path.write_text("")

    resources = collect_dataset_resources(
        simple_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        analysis_goal="lnm",
        semantic_intent="stroke depression lesion",
        run_bids_validation=False,
        enforce_semantic_gate=True,
    )

    assert resources is not None
    assert resources.semantic_match["matched"] is False
    assert resources.readiness["status"] == "blocked"
    assert "semantic" in resources.readiness["reason"]


def test_collect_dataset_resources_source_access_openneuro_verified(
    tmp_path, monkeypatch
):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:openneuro:ds001111"
    simple_id = "ds001111"
    _mock_openneuro_api(
        monkeypatch,
        simple_id,
        snapshots=[
            {"id": "snap-1", "tag": "1.0.0", "created": "2025-01-01T00:00:00Z"},
            {"id": "snap-2", "tag": "1.1.0", "created": "2025-02-01T00:00:00Z"},
        ],
    )

    _write_catalog(
        catalog_path,
        {
            "dataset_id": dataset_id,
            "name": "Versioned dataset",
            "short_name": "Versioned",
            "alias": [simple_id],
            "description": "OpenNeuro dataset with snapshots",
            "modalities": ["MRI", "fMRI"],
            "acquisitions": ["BOLD"],
            "species": ["human"],
            "source_repo": "OpenNeuro",
            "source_repo_id": simple_id,
            "primary_url": f"https://openneuro.org/datasets/{simple_id}",
            "access_type": "public",
            "license": "CC0",
        },
    )
    (tmp_path / "bids" / simple_id).mkdir(parents=True)
    mounts_path.write_text(
        f"""
local:
  openneuro_local: {tmp_path / "bids"}
"""
    )
    manual_path.write_text("")

    resources = collect_dataset_resources(
        simple_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        dataset_version="latest",
        run_bids_validation=False,
    )

    assert resources is not None
    assert resources.source_access["provider"] == "openneuro"
    assert resources.source_access["bucket_check"]["state"] == "verified_present"
    assert resources.source_access["version_check"]["mode"] == "verified"
    assert resources.source_access["version_check"]["resolved"] == "1.1.0"
    assert len(resources.source_access["available_versions"]) == 2


def test_collect_dataset_resources_public_s3_mount_exposes_mount_status(tmp_path):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:manual:nsd"
    _write_catalog(
        catalog_path,
        {
            "dataset_id": dataset_id,
            "name": "NSD (Natural Scenes Dataset)",
            "short_name": "NSD",
            "alias": ["nsd"],
            "description": "Dense natural scene responses",
            "modalities": ["fMRI"],
            "acquisitions": ["BOLD"],
            "species": ["human"],
            "source_repo": "project / AWS",
            "source_repo_id": dataset_id,
            "primary_url": "https://naturalscenesdataset.org",
            "access_type": "public",
            "license": "CC-BY",
        },
    )

    public_root = tmp_path / "public_s3_mount"
    nsd_root = public_root / "natural-scenes-dataset"
    (nsd_root / "nsddata_timeseries").mkdir(parents=True, exist_ok=True)
    mounts_path.write_text(
        f"""
local:
  public_s3_root: {public_root}
"""
    )
    manual_path.write_text("")

    resources = collect_dataset_resources(
        "nsd",
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        run_bids_validation=False,
        check_source_access=False,
    )

    assert resources is not None
    assert resources.local_path == nsd_root
    assert resources.bids_path is None
    assert resources.is_bids_available is False
    assert resources.readiness["status"] == "partial"
    assert "does not expose a BIDS root" in resources.readiness["note"]
    assert any(
        "does not expose a BIDS root" in note for note in resources.readiness["notes"]
    )
    assert resources.required_files["skipped"] is True
    assert "skipping BIDS-specific required-file checks" in resources.required_files[
        "note"
    ]
    assert resources.mount_status["mounted"] is True
    assert resources.mount_status["mount_kind"] == "public_s3"
    assert resources.mount_status["matched_alias"] == "natural-scenes-dataset"
    assert resources.mount_status["local_path"] == str(nsd_root)
    assert any(
        t.get("kind") == "public_s3" and t.get("hit") for t in resources.source_trace
    )


def test_collect_dataset_resources_missing_goal_files_returns_partial(
    tmp_path, monkeypatch
):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:openneuro:ds004873"
    simple_id = "ds004873"
    _mock_openneuro_api(monkeypatch, simple_id)

    _write_catalog(
        catalog_path,
        {
            "dataset_id": dataset_id,
            "name": "Incomplete BOLD study",
            "short_name": "IncompleteBold",
            "alias": [simple_id],
            "description": "Dataset with only metadata present",
            "modalities": ["MRI", "fMRI"],
            "acquisitions": ["BOLD"],
            "species": ["human"],
            "source_repo": "OpenNeuro",
            "source_repo_id": simple_id,
            "primary_url": f"https://openneuro.org/datasets/{simple_id}",
            "access_type": "public",
            "license": "CC0",
        },
    )

    openneuro_root = tmp_path / "openneuro_mount"
    ds_root = openneuro_root / simple_id
    ds_root.mkdir(parents=True, exist_ok=True)
    (ds_root / "dataset_description.json").write_text(
        json.dumps({"Name": "Incomplete", "BIDSVersion": "1.9.0"})
    )
    mounts_path.write_text(
        f"""
local:
  openneuro_local: {openneuro_root}
"""
    )
    manual_path.write_text("")

    resources = collect_dataset_resources(
        simple_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        analysis_goal="fmri-glm",
        run_bids_validation=False,
    )

    assert resources is not None
    assert resources.is_bids_available is True
    assert resources.readiness["status"] == "partial"
    assert any(
        "Analysis goal 'fmri-glm' is not fully satisfied" in note
        for note in resources.readiness["notes"]
    )


def test_collect_dataset_resources_bids_validator_errors_return_note(
    tmp_path, monkeypatch
):
    catalog_path = tmp_path / "catalog.jsonl"
    mounts_path = tmp_path / "mounts.yaml"
    manual_path = tmp_path / "catalog_manual.jsonl"

    dataset_id = "ds:openneuro:ds001111"
    simple_id = "ds001111"
    _mock_openneuro_api(monkeypatch, simple_id)
    _write_catalog(
        catalog_path,
        {
            "dataset_id": dataset_id,
            "name": "Validator warning dataset",
            "short_name": "ValidatorSet",
            "alias": [simple_id],
            "description": "OpenNeuro dataset for validator handling",
            "modalities": ["MRI", "fMRI"],
            "acquisitions": ["BOLD"],
            "species": ["human"],
            "source_repo": "OpenNeuro",
            "source_repo_id": simple_id,
            "primary_url": f"https://openneuro.org/datasets/{simple_id}",
            "access_type": "public",
            "license": "CC0",
        },
    )

    openneuro_root = tmp_path / "openneuro_mount"
    _write_minimal_bids_fmri(openneuro_root / simple_id, task="emotion")
    mounts_path.write_text(
        f"""
local:
  openneuro_local: {openneuro_root}
"""
    )
    manual_path.write_text("")

    monkeypatch.setattr(
        "brain_researcher.services.agent.kg_resolution._run_bids_validator",
        lambda bids_path: {
            "ran": True,
            "errors": 2,
            "warnings": 0,
            "error_codes": [1, 2],
            "warning_codes": [],
        },
    )

    resources = collect_dataset_resources(
        simple_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_path,
        analysis_goal="fmri-glm",
        run_bids_validation=True,
    )

    assert resources is not None
    assert resources.readiness["status"] == "partial"
    assert any(
        "BIDS validator reported errors" in note
        for note in resources.readiness["notes"]
    )


def test_find_existing_derivatives_accepts_canonical_id(tmp_path):
    manual_path = tmp_path / "catalog_manual.jsonl"
    deriv = tmp_path / "derivatives" / "fmriprep" / "ds000114"
    deriv.mkdir(parents=True)
    manual_path.write_text(
        json.dumps(
            {
                "source_repo_id": "ds000114",
                "path_fmriprep": str(deriv),
            }
        )
        + "\n"
    )

    hits = find_existing_derivatives(
        "ds:openneuro:ds000114",
        manual_catalog=manual_path,
    )

    assert len(hits) == 1
    assert hits[0].kind == "fmriprep"
    assert str(hits[0].path) == str(deriv)


def test_path_from_mounts_matches_case_insensitive_aliases():
    mounts = {
        "oak_mount": {
            "datasets": {
                "HCP_YA": "/mnt/oak/HCP_YA",
            }
        }
    }

    assert _path_from_mounts("hcp_ya", mounts) == Path("/mnt/oak/HCP_YA")
    assert _path_from_mounts("ds:manual:hcp_ya", mounts) == Path("/mnt/oak/HCP_YA")
