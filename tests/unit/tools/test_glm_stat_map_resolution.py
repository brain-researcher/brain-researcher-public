from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np
import yaml

from brain_researcher.services.tools.glm_stat_map_selector import (
    GLMStatMapQuery,
    clear_glm_stat_map_selector_cache,
    select_glm_stat_map_matches,
)
from brain_researcher.services.tools.neuroimage_asset_registry import (
    clear_neuroimage_asset_registry_cache,
)
from brain_researcher.services.tools.reference_asset_registry import (
    clear_reference_asset_registry_cache,
)
from brain_researcher.services.tools.resolve_dataset_asset_tool import (
    ResolveDatasetAssetTool,
)
from brain_researcher.services.tools.resolve_neuroimage_asset_tool import (
    ResolveNeuroimageAssetTool,
)
from brain_researcher.services.tools.resolve_reference_map_tool import (
    ResolveReferenceMapTool,
)


def _write_registry(tmp_path: Path, *, openneuro_root: Path | None = None) -> Path:
    families = []
    if openneuro_root is not None:
        families.append(
            {
                "family_id": "reference_maps_annotations",
                "entries": [
                    {
                        "asset_name": "local_openneuro_glmfitlins_stat_map_corpus",
                        "current_state": "already_usable",
                        "evidence_paths": [str(openneuro_root)],
                    }
                ],
            }
        )
    registry_path = tmp_path / "neuroimage_assets_backlog.yaml"
    registry_path.write_text(
        yaml.safe_dump({"version": "test", "families": families}),
        encoding="utf-8",
    )
    return registry_path


def _write_nifti(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = nib.Nifti1Image(np.zeros((2, 2, 2), dtype="float32"), affine=np.eye(4))
    nib.save(img, path)


def _write_openneuro_tree(tmp_path: Path) -> Path:
    root = tmp_path / "openneuro_glmfitlins" / "stat_maps"
    base = root / "ds000114" / "task-linebisection" / "node-subjectLevel" / "sub-01"
    _write_nifti(base / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz")
    _write_nifti(base / "sub-01_contrast-taskvbaseline_stat-t_statmap.nii.gz")
    (root / "ds000114" / "task-linebisection" / "dataset_description.json").write_text(
        json.dumps(
            {
                "BIDSVersion": "1.1.0",
                "License": "CC0",
                "PipelineDescription": {
                    "Version": "0.11.0",
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def _write_generic_derivative_tree(tmp_path: Path) -> Path:
    root = tmp_path / "derivatives" / "custom_glm" / "ds000200"
    stat_path = (
        root
        / "task-emotion"
        / "node-groupLevel"
        / "sub-01"
        / "sub-01_task-emotion_contrast-faces_stat-t_statmap.nii.gz"
    )
    _write_nifti(stat_path)
    (root / "task-emotion" / "dataset_description.json").write_text(
        json.dumps(
            {
                "PipelineDescription": {
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                }
            }
        ),
        encoding="utf-8",
    )
    return root


def _mock_dataset_context(monkeypatch, tmp_path: Path, glm_root: Path) -> None:
    from brain_researcher.services.tools import resolve_dataset_asset_tool as module

    bids_root = tmp_path / "ds000114"
    bids_root.mkdir(parents=True, exist_ok=True)
    (bids_root / "dataset_description.json").write_text(
        json.dumps({"Name": "Test", "BIDSVersion": "1.9.0"}), encoding="utf-8"
    )
    resources = SimpleNamespace(
        bids_path=str(bids_root),
        derivatives={"glmfitlins": str(glm_root)},
        remote_urls={"openneuro": "https://openneuro.org/datasets/ds000114"},
        size_bytes=123,
        is_bids_available=True,
        resolved_dataset_id="ds:openneuro:ds000114",
        resolution_mode="exact_simple_id",
        available_derivatives=["glmfitlins"],
        analysis_goal="fmri-glm",
        readiness={"status": "ready"},
        source_repo="OpenNeuro",
        dataset_name="Line Bisection",
        display_name="Line Bisection",
        dataset_metadata={"tasks": ["linebisection"], "modalities": ["fMRI"]},
    )
    monkeypatch.setattr(
        module.query_service, "dataset_resources", lambda *a, **k: resources
    )


def test_selector_prefers_registry_and_returns_all_matches(monkeypatch, tmp_path: Path):
    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()

    matches = select_glm_stat_map_matches(
        query=GLMStatMapQuery(
            dataset_ref="ds000114",
            task="linebisection",
            contrast="taskvbaseline",
            space="MNI152",
        ),
        derivative_roots={"glmfitlins": openneuro_root},
        include_registry=True,
    )

    assert len(matches) == 2
    assert matches[0]["source"] == "openneuro_registry"
    assert matches[0]["statistic"] == "z"
    assert matches[1]["statistic"] == "t"


def test_selector_falls_back_to_generic_derivative_scan(monkeypatch, tmp_path: Path):
    generic_root = _write_generic_derivative_tree(tmp_path)
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()

    matches = select_glm_stat_map_matches(
        query=GLMStatMapQuery(
            dataset_ref="ds000200",
            task="emotion",
            contrast="faces",
            statistic="t",
            space="MNI152",
        ),
        derivative_roots={"custom_glm": generic_root},
        include_registry=True,
    )

    assert len(matches) == 1
    assert matches[0]["source"] == "generic_derivative_scan"
    assert matches[0]["space"] == "MNI152NLin2009cAsym"
    assert matches[0]["space_inferred"] is True


def test_resolve_dataset_asset_stat_map_returns_all_matches(
    monkeypatch, tmp_path: Path
):
    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()
    _mock_dataset_context(monkeypatch, tmp_path, openneuro_root)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        kind="stat_map",
        derivative_kind="glmfitlins",
        task="linebisection",
        contrast="taskvbaseline",
        space="MNI152",
        output_dir=str(tmp_path / "outputs"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "stat_map"
    assert result.data["summary"]["n_matches"] == 2
    assert result.data["summary"]["returned_all_matches"] is True
    assert result.data["outputs"]["glm_stat_map"].endswith("_stat-z_statmap.nii.gz")
    assert len(result.data["outputs"]["resolved_files"]) == 2
    assert len(result.data["outputs"]["matches"]) == 2


def test_resolve_dataset_asset_stat_map_supports_asset_name_query_text(
    monkeypatch, tmp_path: Path
):
    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()
    _mock_dataset_context(monkeypatch, tmp_path, openneuro_root)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        kind="stat_map",
        derivative_kind="glmfitlins",
        asset_name="taskvbaseline",
        task="linebisection",
        space="MNI152",
        output_dir=str(tmp_path / "outputs"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "stat_map"
    assert result.data["outputs"]["glm_stat_map"].endswith("_stat-z_statmap.nii.gz")
    assert len(result.data["outputs"]["matches"]) == 2


def test_resolve_reference_map_supports_structured_glm_query(
    monkeypatch, tmp_path: Path
):
    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()

    tool = ResolveReferenceMapTool()
    result = tool._run(
        dataset_ref="ds000114",
        task="linebisection",
        contrast="taskvbaseline",
        statistic="z",
        space="MNI152",
        output_dir=str(tmp_path / "outputs"),
    )

    assert result.status == "success"
    assert result.data["outputs"]["reference_map"].endswith(
        "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    assert result.data["summary"]["contrast"] == "taskvbaseline"
    assert result.data["summary"]["dataset_id"] == "ds000114"
    assert result.data["summary"]["statistic"] == "z"
    assert result.data["summary"]["returned_all_matches"] is True


def test_resolve_reference_map_uses_fast_local_dataset_resources(
    monkeypatch, tmp_path: Path
):
    from brain_researcher.services.tools import resolve_reference_map_tool as module

    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()

    captured: dict[str, object] = {"calls": 0}
    resources = SimpleNamespace(
        bids_path=str(tmp_path / "ds000114"),
        derivatives={"glmfitlins": str(openneuro_root)},
        remote_urls={},
        size_bytes=1,
        is_bids_available=True,
        resolved_dataset_id="ds:openneuro:ds000114",
        resolution_mode="exact_simple_id",
        available_derivatives=["glmfitlins"],
        analysis_goal="fmri-glm",
        readiness={"status": "ready"},
    )

    def fake_dataset_resources(*args, **kwargs):
        captured["calls"] = int(captured["calls"]) + 1
        captured.update(kwargs)
        return resources

    monkeypatch.setattr(
        module.query_service, "dataset_resources", fake_dataset_resources
    )

    tool = ResolveReferenceMapTool()
    result = tool._run(
        dataset_ref="ds000114",
        task="linebisection",
        contrast="taskvbaseline",
        statistic="z",
        space="MNI152",
    )

    assert result.status == "success"
    assert captured["calls"] == 1
    assert captured["run_bids_validation"] is False
    assert captured["enforce_semantic_gate"] is False
    assert captured["check_source_access"] is False


def test_resolve_neuroimage_asset_auto_stat_map_prefers_dataset_asset(
    monkeypatch, tmp_path: Path
):
    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()
    _mock_dataset_context(monkeypatch, tmp_path, openneuro_root)

    tool = ResolveNeuroimageAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        name="taskvbaseline",
        task="linebisection",
        space="MNI152",
        output_dir=str(tmp_path / "outputs"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "stat_map"
    assert result.data["summary"]["resolver_tool"] == "resolve_dataset_asset"
    assert result.data["outputs"]["glm_stat_map"].endswith("_stat-z_statmap.nii.gz")


def test_resolve_neuroimage_asset_explicit_stat_map_without_dataset_ref_uses_reference_map(
    monkeypatch, tmp_path: Path
):
    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()

    tool = ResolveNeuroimageAssetTool()
    result = tool._run(
        kind="stat_map",
        contrast="taskvbaseline",
        task="linebisection",
        statistic="z",
        space="MNI152",
        output_dir=str(tmp_path / "outputs"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "stat_map"
    assert result.data["summary"]["resolver_tool"] == "resolve_reference_map"
    assert result.data["outputs"]["reference_map"].endswith(
        "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
