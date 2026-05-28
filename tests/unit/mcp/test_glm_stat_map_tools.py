from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np
import yaml

from brain_researcher.services.tools.glm_stat_map_selector import (
    clear_glm_stat_map_selector_cache,
)
from brain_researcher.services.tools.neuroimage_asset_registry import (
    clear_neuroimage_asset_registry_cache,
)
from brain_researcher.services.tools.reference_asset_registry import (
    clear_reference_asset_registry_cache,
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


def _mock_dataset_context(monkeypatch, tmp_path: Path, glm_root: Path) -> None:
    from brain_researcher.services.tools import (
        resolve_dataset_asset_tool as dataset_module,
    )
    from brain_researcher.services.tools import (
        resolve_reference_map_tool as reference_module,
    )

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
        dataset_module.query_service, "dataset_resources", lambda *a, **k: resources
    )
    monkeypatch.setattr(
        reference_module.query_service, "dataset_resources", lambda *a, **k: resources
    )


def test_tool_execute_resolve_dataset_asset_supports_stat_map(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()
    _mock_dataset_context(monkeypatch, tmp_path, openneuro_root)
    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"resolve_dataset_asset"})
    monkeypatch.setattr(srv, "AGENT_MULTIAGENT_ENABLED", False)
    monkeypatch.setattr(srv, "AGENT_CRITIC_TOOL_GATE", False)
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda tool_id: srv._get_registry().get_toolspec_by_name(tool_id),
    )

    resp = srv.tool_execute(
        "resolve_dataset_asset",
        params={
            "dataset_ref": "ds000114",
            "kind": "stat_map",
            "derivative_kind": "glmfitlins",
            "task": "linebisection",
            "contrast": "taskvbaseline",
            "space": "MNI152",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "stat_map"
    assert result["data"]["summary"]["n_matches"] == 2
    assert len(result["data"]["outputs"]["matches"]) == 2
    assert result["data"]["outputs"]["glm_stat_map"].endswith("_stat-z_statmap.nii.gz")


def test_tool_execute_resolve_reference_map_supports_structured_glm_query(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()
    _mock_dataset_context(monkeypatch, tmp_path, openneuro_root)
    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"resolve_reference_map"})
    monkeypatch.setattr(srv, "AGENT_MULTIAGENT_ENABLED", False)
    monkeypatch.setattr(srv, "AGENT_CRITIC_TOOL_GATE", False)
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda tool_id: srv._get_registry().get_toolspec_by_name(tool_id),
    )

    resp = srv.tool_execute(
        "resolve_reference_map",
        params={
            "dataset_ref": "ds000114",
            "task": "linebisection",
            "contrast": "taskvbaseline",
            "statistic": "z",
            "space": "MNI152",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["dataset_id"] == "ds000114"
    assert result["data"]["summary"]["contrast"] == "taskvbaseline"
    assert result["data"]["summary"]["statistic"] == "z"
    assert result["data"]["summary"]["n_matches"] == 1
    assert result["data"]["outputs"]["reference_map"].endswith(
        "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )


def test_tool_execute_resolve_neuroimage_asset_supports_auto_stat_map(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    openneuro_root = _write_openneuro_tree(tmp_path)
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    clear_glm_stat_map_selector_cache()
    _mock_dataset_context(monkeypatch, tmp_path, openneuro_root)
    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"resolve_neuroimage_asset"})
    monkeypatch.setattr(srv, "AGENT_MULTIAGENT_ENABLED", False)
    monkeypatch.setattr(srv, "AGENT_CRITIC_TOOL_GATE", False)
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda tool_id: srv._get_registry().get_toolspec_by_name(tool_id),
    )

    resp = srv.tool_execute(
        "resolve_neuroimage_asset",
        params={
            "dataset_ref": "ds000114",
            "name": "taskvbaseline",
            "task": "linebisection",
            "space": "MNI152",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "stat_map"
    assert result["data"]["summary"]["resolver_tool"] == "resolve_dataset_asset"
    assert result["data"]["outputs"]["glm_stat_map"].endswith("_stat-z_statmap.nii.gz")
