from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain_researcher.services.tools.list_dataset_assets_tool import (
    ListDatasetAssetsArgs,
    ListDatasetAssetsTool,
)


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_dataset_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    bids_root = tmp_path / "ds000114"
    _write_text(
        bids_root / "dataset_description.json",
        json.dumps({"Name": "Test", "BIDSVersion": "1.9.0"}),
    )
    _write_text(
        bids_root / "participants.tsv",
        "participant_id\tgroup\nsub-01\tcontrol\n",
    )
    func_dir = bids_root / "sub-01" / "func"
    _write_text(func_dir / "sub-01_task-emotion_bold.nii.gz", "bold")
    _write_text(
        func_dir / "sub-01_task-emotion_events.tsv",
        "onset\tduration\ttrial_type\n0\t1\tgo\n",
    )

    fmriprep_root = tmp_path / "derivatives" / "fmriprep" / "ds000114"
    _write_text(
        fmriprep_root
        / "sub-01"
        / "func"
        / "sub-01_task-emotion_desc-confounds_timeseries.tsv",
        "trans_x\ttrans_y\n0.1\t0.0\n",
    )

    glm_root = tmp_path / "derivatives" / "glmfitlins" / "ds000114"
    _write_text(
        glm_root
        / "task-emotion"
        / "node-subjectLevel"
        / "sub-01"
        / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz",
        "statmap\n",
    )
    _write_text(
        glm_root / "task-emotion" / "dataset_description.json",
        json.dumps(
            {
                "PipelineDescription": {
                    "Version": "0.11.0",
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                }
            }
        ),
    )
    return bids_root, fmriprep_root, glm_root


def _mock_context(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    from brain_researcher.services.tools import list_dataset_assets_tool as module

    bids_root, fmriprep_root, glm_root = _write_dataset_tree(tmp_path)
    resources = SimpleNamespace(
        bids_path=str(bids_root),
        derivatives={
            "fmriprep": str(fmriprep_root),
            "glmfitlins": str(glm_root),
        },
        remote_urls={"openneuro": "https://openneuro.org/datasets/ds000114"},
        size_bytes=123,
        is_bids_available=True,
        resolved_dataset_id="ds:openneuro:ds000114",
        resolution_mode="exact_simple_id",
        available_derivatives=["fmriprep", "glmfitlins"],
        analysis_goal="fmri-glm",
        readiness={"status": "ready"},
        source_repo="OpenNeuro",
        dataset_name="Emotion dataset",
        display_name="Emotion dataset",
        dataset_metadata={"tasks": ["emotion"], "modalities": ["fMRI"]},
    )
    monkeypatch.setattr(
        module.query_service, "dataset_resources", lambda *a, **k: resources
    )
    return bids_root, fmriprep_root, glm_root


def test_list_dataset_assets_uses_fast_local_resource_mode(monkeypatch, tmp_path):
    from brain_researcher.services.tools import list_dataset_assets_tool as module

    bids_root, _fmriprep_root, _glm_root = _write_dataset_tree(tmp_path)
    captured: dict[str, object] = {"calls": 0}
    resources = SimpleNamespace(
        bids_path=str(bids_root),
        derivatives={},
        remote_urls={},
        size_bytes=1,
        is_bids_available=True,
        resolved_dataset_id="ds:openneuro:ds000114",
        resolution_mode="exact_simple_id",
        available_derivatives=[],
        analysis_goal="generic",
        readiness={"status": "ready"},
        source_repo="OpenNeuro",
        dataset_name="Emotion dataset",
        display_name="Emotion dataset",
        dataset_metadata={"tasks": ["emotion"], "modalities": ["fMRI"]},
    )

    def fake_dataset_resources(*args, **kwargs):
        captured["calls"] = int(captured["calls"]) + 1
        captured.update(kwargs)
        return resources

    monkeypatch.setattr(
        module.query_service, "dataset_resources", fake_dataset_resources
    )

    tool = ListDatasetAssetsTool()
    result = tool._run(dataset_ref="ds000114")

    assert result.status == "success"
    assert captured["calls"] == 1
    assert captured["run_bids_validation"] is False
    assert captured["enforce_semantic_gate"] is False
    assert captured["check_source_access"] is False


def test_list_dataset_assets_returns_dataset_and_derivative_inventory(
    monkeypatch, tmp_path
):
    bids_root, _fmriprep_root, _glm_root = _mock_context(monkeypatch, tmp_path)

    tool = ListDatasetAssetsTool()
    result = tool._run(dataset_ref="ds000114")

    assert result.status == "success"
    assets = result.data["outputs"]["assets"]
    assert any(asset["kind"] == "dataset" for asset in assets)
    assert any(asset["kind"] == "derivative" for asset in assets)
    assert any(asset["source_path"] == str(bids_root) for asset in assets)
    assert all("canonical_id" in asset for asset in assets)
    assert all("manifest_fields" in asset for asset in assets)
    assert result.data["summary"]["browse_kind"] == "all"
    assert result.data["summary"]["needs_filters"] is False


def test_list_dataset_assets_schema_includes_legacy_aliases():
    schema = ListDatasetAssetsArgs.model_json_schema()

    assert schema["additionalProperties"] is False
    assert "asset_type" in schema["properties"]
    assert "scope" in schema["properties"]
    assert "query" in schema["properties"]
    assert "derivative_type" in schema["properties"]
    assert "subject" in schema["properties"]
    assert "session" in schema["properties"]
    assert "download_missing" in schema["properties"]
    assert "download_root" in schema["properties"]

    tool = ListDatasetAssetsTool()
    assert tool.TIMEOUT_S == 300


def test_list_dataset_assets_run_accepts_legacy_aliases(monkeypatch, tmp_path):
    _mock_context(monkeypatch, tmp_path)

    tool = ListDatasetAssetsTool()
    result = tool._run(
        dataset_ref="ds000114",
        asset_type="derivatives",
        derivative_type="fmriprep",
    )

    assert result.status == "success"
    assert result.data["summary"]["browse_kind"] == "derivative"
    assert result.data["summary"]["count"] == 1
    assert result.data["summary"]["filters"]["derivative_kind"] == "fmriprep"


def test_list_dataset_assets_run_accepts_scope_query_and_bids_aliases(
    monkeypatch, tmp_path
):
    _mock_context(monkeypatch, tmp_path)

    tool = ListDatasetAssetsTool()
    result = tool._run(
        dataset_ref="ds000114",
        scope="derivatives",
        query="fmriprep",
        subject="01",
        session="ses-func01",
    )

    assert result.status == "success"
    assert result.data["summary"]["browse_kind"] == "derivative"
    assert result.data["summary"]["query"] == "fmriprep"
    assert result.data["summary"]["filters"]["subject_id"] == "sub-01"
    assert result.data["summary"]["filters"]["session_id"] == "ses-func01"
    assert result.data["summary"]["count"] == 1
    assert result.data["outputs"]["assets"][0]["derivative_kind"] == "fmriprep"


def test_list_dataset_assets_run_rejects_conflicting_scope_aliases(
    monkeypatch, tmp_path
):
    _mock_context(monkeypatch, tmp_path)

    tool = ListDatasetAssetsTool()
    result = tool._run(
        dataset_ref="ds000114",
        kind="dataset",
        scope="derivatives",
    )

    assert result.status == "error"
    assert "Conflicting kind" in result.error


def test_list_dataset_assets_rejects_unknown_params():
    with pytest.raises(Exception) as excinfo:
        ListDatasetAssetsArgs(dataset_ref="ds000114", unexpected_filter="oops")

    assert "unexpected_filter" in str(excinfo.value)


def test_list_dataset_assets_stat_map_requires_filters(monkeypatch, tmp_path):
    _mock_context(monkeypatch, tmp_path)

    tool = ListDatasetAssetsTool()
    result = tool._run(dataset_ref="ds000114", kind="stat_map")

    assert result.status == "success"
    assert result.data["outputs"]["assets"] == []
    assert result.data["summary"]["needs_filters"] is True
    assert (
        "contrast/task/node/subject_id/statistic/space"
        in result.data["summary"]["suggested_filters"]
    )


def test_list_dataset_assets_returns_targeted_events_confounds_and_stat_maps(
    monkeypatch, tmp_path
):
    _mock_context(monkeypatch, tmp_path)

    tool = ListDatasetAssetsTool()
    result = tool._run(
        dataset_ref="ds000114",
        subject_id="01",
        task="emotion",
        contrast="taskvbaseline",
        statistic="z",
        include_metadata=True,
    )

    assert result.status == "success"
    assets = result.data["outputs"]["assets"]
    assert any(asset["kind"] == "events" for asset in assets)
    assert any(asset["kind"] == "confounds" for asset in assets)
    stat_map = next(asset for asset in assets if asset["kind"] == "stat_map")
    assert stat_map["contrast"] == "taskvbaseline"
    assert stat_map["statistic"] == "z"
    assert stat_map["level"] == "subject"
    assert stat_map["relative_path"].endswith(
        "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    assert "metadata" in stat_map


def test_list_dataset_assets_download_missing_fetches_confounds_subset(
    monkeypatch, tmp_path
):
    from brain_researcher.services.tools import (
        list_dataset_assets_tool as module,
    )
    from brain_researcher.services.tools import (
        resolve_dataset_asset_tool as resolve_module,
    )

    resources = SimpleNamespace(
        bids_path=None,
        derivatives={},
        remote_urls={"openneuro": "https://openneuro.org/datasets/ds000114"},
        size_bytes=123,
        is_bids_available=False,
        resolved_dataset_id="ds:openneuro:ds000114",
        resolution_mode="exact_simple_id",
        available_derivatives=[],
        analysis_goal="generic",
        readiness={"status": "partial"},
        source_repo="OpenNeuro",
        dataset_name="Emotion dataset",
        display_name="Emotion dataset",
        dataset_metadata={"tasks": ["emotion"], "modalities": ["fMRI"]},
    )
    monkeypatch.setattr(
        module.query_service, "dataset_resources", lambda *a, **k: resources
    )

    def fake_download(dataset_id, out_dir, include, **kwargs):
        root = Path(out_dir)
        _write_text(
            root / "derivatives" / "fmriprep" / "dataset_description.json",
            json.dumps({"Name": "fMRIPrep"}),
        )
        _write_text(
            root
            / "derivatives"
            / "fmriprep"
            / "sub-01"
            / "func"
            / "sub-01_task-emotion_desc-confounds_timeseries.tsv",
            "trans_x\ttrans_y\n0.1\t0.0\n",
        )
        return str(root)

    monkeypatch.setattr(resolve_module, "download_openneuro_subset", fake_download)

    tool = ListDatasetAssetsTool()
    result = tool._run(
        dataset_ref="ds000114",
        kind="confounds",
        subject_id="01",
        task="emotion",
        datatype="func",
        download_missing=True,
        download_root=str(tmp_path / "cache"),
    )

    assert result.status == "success"
    assets = result.data["outputs"]["assets"]
    assert len(assets) == 1
    assert assets[0]["kind"] == "confounds"
    assert assets[0]["relative_path"].endswith(
        "sub-01_task-emotion_desc-confounds_timeseries.tsv"
    )
    assert result.data["summary"]["download_missing_used"] is True
    assert result.data["downloads"]
