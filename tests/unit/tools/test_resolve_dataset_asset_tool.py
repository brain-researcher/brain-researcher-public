from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from brain_researcher.services.tools.resolve_dataset_asset_tool import (
    ResolveDatasetAssetTool,
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
    glm_root.mkdir(parents=True, exist_ok=True)
    return bids_root, fmriprep_root, glm_root


def _mock_resource_context(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    from brain_researcher.services.tools import resolve_dataset_asset_tool as module

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


def test_resolve_dataset_asset_uses_fast_local_resource_mode(monkeypatch, tmp_path):
    from brain_researcher.services.tools import resolve_dataset_asset_tool as module

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

    tool = ResolveDatasetAssetTool()
    result = tool._run(dataset_ref="ds000114")

    assert result.status == "success"
    assert captured["calls"] == 1
    assert captured["run_bids_validation"] is False
    assert captured["enforce_semantic_gate"] is False
    assert captured["check_source_access"] is False


def test_resolve_dataset_asset_auto_summary(monkeypatch, tmp_path):
    bids_root, _fmriprep_root, _glm_root = _mock_resource_context(monkeypatch, tmp_path)

    tool = ResolveDatasetAssetTool()
    result = tool._run(dataset_ref="ds000114")

    assert result.status == "success"
    assert result.data["outputs"]["bids_root"] == str(bids_root)
    assert result.data["outputs"]["dataset_description"].endswith(
        "dataset_description.json"
    )
    assert result.data["outputs"]["participants_tsv"].endswith("participants.tsv")
    assert result.data["summary"]["resolved_kind"] == "dataset"
    assert result.data["summary"]["resolved_dataset_id"] == "ds:openneuro:ds000114"


def test_resolve_dataset_asset_auto_bids_file(monkeypatch, tmp_path):
    _mock_resource_context(monkeypatch, tmp_path)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        subject_id="01",
        datatype="func",
        suffix="bold",
        output_dir=str(tmp_path / "out"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "bids"
    assert Path(result.data["outputs"]["resolved_file"]).parent == tmp_path / "out"
    assert result.data["outputs"]["resolved_file"].endswith("_bold.nii.gz")


def test_resolve_dataset_asset_auto_events(monkeypatch, tmp_path):
    _mock_resource_context(monkeypatch, tmp_path)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        asset_name="events",
        subject_id="01",
        task="emotion",
        output_dir=str(tmp_path / "out"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "events"
    assert result.data["outputs"]["events_file"].endswith("_events.tsv")
    assert Path(result.data["outputs"]["events_file"]).parent == tmp_path / "out"


def test_resolve_dataset_asset_auto_confounds(monkeypatch, tmp_path):
    _mock_resource_context(monkeypatch, tmp_path)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        asset_name="confounds",
        subject_id="01",
        task="emotion",
        output_dir=str(tmp_path / "out"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "confounds"
    assert result.data["outputs"]["confounds_file"].endswith(
        "_desc-confounds_timeseries.tsv"
    )
    assert result.data["outputs"]["derivative_root"].endswith("/fmriprep/ds000114")


def test_resolve_dataset_asset_explicit_derivative_root(monkeypatch, tmp_path):
    _bids_root, _fmriprep_root, glm_root = _mock_resource_context(monkeypatch, tmp_path)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        kind="derivative",
        derivative_kind="glmfitlins",
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "derivative"
    assert result.data["outputs"]["derivative_root"] == str(glm_root)


def test_resolve_dataset_asset_returns_stable_provenance_fields(monkeypatch, tmp_path):
    _mock_resource_context(monkeypatch, tmp_path)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        asset_name="confounds",
        subject_id="01",
        task="emotion",
    )

    assert result.status == "success"
    resolved_asset = result.data["resolved_asset"]
    assert resolved_asset["kind"] == "confounds"
    assert resolved_asset["canonical_id"]
    assert resolved_asset["source"] == "fmriprep_local_scan"
    assert resolved_asset["relative_path"].endswith(
        "sub-01_task-emotion_desc-confounds_timeseries.tsv"
    )
    assert "matches" in result.data["outputs"]
    assert (
        result.data["outputs"]["matches"][0]["canonical_id"]
        == resolved_asset["canonical_id"]
    )


def test_resolve_dataset_asset_download_missing_fetches_bids_subset(
    monkeypatch, tmp_path
):
    from brain_researcher.services.tools import resolve_dataset_asset_tool as module

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

    captured: dict[str, object] = {}

    def fake_download(dataset_id, out_dir, include, **kwargs):
        captured["dataset_id"] = dataset_id
        captured["include"] = list(include)
        root = Path(out_dir)
        _write_text(
            root / "dataset_description.json",
            json.dumps({"Name": "Downloaded", "BIDSVersion": "1.9.0"}),
        )
        _write_text(
            root / "participants.tsv",
            "participant_id\tgroup\nsub-01\tcontrol\n",
        )
        _write_text(
            root / "sub-01" / "func" / "sub-01_task-emotion_bold.nii.gz",
            "bold",
        )
        return str(root)

    monkeypatch.setattr(module, "download_openneuro_subset", fake_download)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        subject_id="01",
        datatype="func",
        suffix="bold",
        task="emotion",
        download_missing=True,
        download_root=str(tmp_path / "cache"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "bids"
    assert result.data["summary"]["download_missing_used"] is True
    assert result.data["outputs"]["resolved_file"].endswith("_bold.nii.gz")
    assert captured["dataset_id"] == "ds000114"
    assert any("sub-01" in str(pattern) for pattern in captured["include"])


def test_resolve_dataset_asset_download_missing_fetches_confounds_subset(
    monkeypatch, tmp_path
):
    from brain_researcher.services.tools import resolve_dataset_asset_tool as module

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

    monkeypatch.setattr(module, "download_openneuro_subset", fake_download)

    tool = ResolveDatasetAssetTool()
    result = tool._run(
        dataset_ref="ds000114",
        kind="confounds",
        asset_name="confounds",
        derivative_kind="fmriprep",
        subject_id="01",
        task="emotion",
        datatype="func",
        download_missing=True,
        download_root=str(tmp_path / "cache"),
    )

    assert result.status == "success"
    assert result.data["summary"]["resolved_kind"] == "confounds"
    assert result.data["summary"]["download_missing_used"] is True
    assert result.data["outputs"]["confounds_file"].endswith(
        "_desc-confounds_timeseries.tsv"
    )
    assert result.data["outputs"]["derivative_root"].endswith("/derivatives/fmriprep")
