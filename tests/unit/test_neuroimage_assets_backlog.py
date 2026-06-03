from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "configs" / "br-kg" / "neuroimage_assets_backlog.yaml"
SCRIPT = ROOT / "scripts" / "validation" / "check_neuroimage_assets_backlog.py"


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def test_neuroimage_assets_backlog_structure_and_decision() -> None:
    payload = _load_registry()

    assert payload["version"] == "1.0"
    assert payload["decision"]["standardized_templates"]["answer"] == "partial_yes"
    assert "unified template registry" in payload["decision"]["standardized_templates"]["summary"]

    families = payload["families"]
    family_ids = {family["family_id"] for family in families}
    assert family_ids == {
        "dataset_metadata_bids",
        "templates_spaces_transforms",
        "atlases_parcellations",
        "reference_maps_annotations",
        "derivatives_qc_design",
        "semantic_provenance_glue",
    }


def test_neuroimage_assets_backlog_state_coverage_and_key_entries() -> None:
    payload = _load_registry()
    by_family = {family["family_id"]: family for family in payload["families"]}

    for family_id, family in by_family.items():
        states = {entry["current_state"] for entry in family["entries"]}
        assert states == {
            "already_usable",
            "present_not_standardized",
            "missing_and_should_acquire",
        }, family_id

    template_entries = {
        entry["asset_name"]: entry
        for entry in by_family["templates_spaces_transforms"]["entries"]
    }
    assert (
        template_entries["generic_template_resolver"]["resolver_status"]
        == "partially_real"
    )
    assert (
        template_entries["unified_template_registry_and_alias_layer"]["current_state"]
        == "missing_and_should_acquire"
    )

    atlas_entries = {
        entry["asset_name"]: entry
        for entry in by_family["atlases_parcellations"]["entries"]
    }
    assert (
        atlas_entries["generic_parcellation_fetch_runtime"]["resolver_status"]
        == "partially_real"
    )

    dataset_entries = {
        entry["asset_name"]: entry
        for entry in by_family["dataset_metadata_bids"]["entries"]
    }
    assert dataset_entries["canonical_dataset_catalog"]["current_state"] == "already_usable"
    assert dataset_entries["bids_path_resolution"]["resolver_status"] == "real"


def test_check_neuroimage_assets_backlog_script_passes() -> None:
    cmd = [sys.executable, str(SCRIPT), "--registry", str(REGISTRY)]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    assert result["summary"]["valid_registry"] is True
    assert result["summary"]["family_count"] == 6
    assert result["summary"]["entry_count"] >= 20
    assert result["summary"]["already_usable_count"] >= 6
    assert result["summary"]["present_not_standardized_count"] >= 6
    assert result["summary"]["missing_and_should_acquire_count"] >= 6
    assert result["validation_errors"] == []
