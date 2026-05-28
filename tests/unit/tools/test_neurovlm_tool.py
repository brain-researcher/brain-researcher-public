from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np

from brain_researcher.services.tools.grandmaster_tools import DecodeBrainMapTool
from brain_researcher.services.tools.neurovlm_tool import NeuroVLMBuildRDMTool
from brain_researcher.services.tools.runner import execute_tool
from brain_researcher.services.tools.tool_base import ToolResult


def _write_stat_map(path: Path) -> Path:
    data = np.zeros((3, 3, 3), dtype=np.float32)
    data[1, 2, 1] = 5.0
    nib.Nifti1Image(data, np.eye(4)).to_filename(str(path))
    return path


def test_neurovlm_build_rdm_passthrough(tmp_path: Path):
    matrix = np.array(
        [[0.0, 0.1, 0.2], [0.1, 0.0, 0.3], [0.2, 0.3, 0.0]], dtype=np.float32
    )
    src = tmp_path / "input_rdm.npy"
    dst = tmp_path / "copied_rdm.npy"
    np.save(src, matrix)

    result = NeuroVLMBuildRDMTool()._run(input_rdm=str(src), output_file=str(dst))

    assert result.status == "success", result.error
    assert dst.exists()
    assert np.allclose(np.load(dst), matrix)
    assert result.data["summary"]["source"] == "input_rdm"


def test_neurovlm_build_rdm_from_texts(tmp_path: Path, monkeypatch):
    def _fake_embeddings(texts, *, head, datasets, device):
        assert texts == ["left hand", "right hand", "bilateral"]
        assert head == "infonce"
        assert datasets is None
        assert device is None
        return np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)

    monkeypatch.setattr(
        "brain_researcher.services.tools.neurovlm_tool._prepare_text_brain_embeddings",
        _fake_embeddings,
    )

    out_file = tmp_path / "model_rdm.npy"
    result = NeuroVLMBuildRDMTool()._run(
        texts=["left hand", "right hand", "bilateral"],
        output_file=str(out_file),
    )

    assert result.status == "success", result.error
    rdm = np.load(out_file)
    assert rdm.shape == (3, 3)
    assert np.allclose(rdm, rdm.T)
    assert np.allclose(np.diag(rdm), 0.0)

    labels_path = Path(result.data["outputs"]["labels_json"])
    assert labels_path.exists()
    assert json.loads(labels_path.read_text(encoding="utf-8")) == [
        "left hand",
        "right hand",
        "bilateral",
    ]


def test_decode_brain_map_uses_neurovlm_first(tmp_path: Path, monkeypatch):
    stat_map = _write_stat_map(tmp_path / "stat_map.nii.gz")
    expected = ToolResult(
        status="success",
        data={"decoder": "neurovlm", "top_matches": [{"concept": "working memory"}]},
    )

    def _fake_decode(**kwargs):
        assert kwargs["stat_map"] == str(stat_map)
        assert kwargs["top_k"] == 4
        assert np.allclose(kwargs["peak_coordinate"], [1.0, 2.0, 1.0])
        return expected

    monkeypatch.setattr(
        "brain_researcher.services.tools.neurovlm_tool.decode_brain_map_with_neurovlm",
        _fake_decode,
    )

    result = DecodeBrainMapTool()._run(stat_map=str(stat_map), top_k=4)

    assert result.status == "success"
    assert result.data == expected.data


def test_decode_brain_map_falls_back_to_coordinate_decode(tmp_path: Path, monkeypatch):
    stat_map = _write_stat_map(tmp_path / "stat_map.nii.gz")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "brain_researcher.services.tools.neurovlm_tool.decode_brain_map_with_neurovlm",
        lambda **_: ToolResult(status="error", error="NeuroVLM unavailable"),
    )

    def _fake_call_wrapper(wrapper, params):
        captured["tool_name"] = wrapper.get_tool_name()
        captured["params"] = params
        return ToolResult(
            status="success",
            data={"coordinate_mappings": [{"coordinate": params["coordinates"][0]}]},
        )

    monkeypatch.setattr(
        "brain_researcher.services.tools.grandmaster_tools._call_wrapper",
        _fake_call_wrapper,
    )

    result = DecodeBrainMapTool()._run(stat_map=str(stat_map), top_k=3)

    assert result.status == "success", result.error
    assert captured["tool_name"] == "coordinate_to_concept"
    params = captured["params"]
    assert params["top_k"] == 3
    assert np.allclose(params["coordinates"][0], [1.0, 2.0, 1.0])
    assert result.data["fallbacks"][0]["tool"] == "neurovlm"


def test_workflow_rsa_model_brain_builds_model_rdm_from_texts(
    tmp_path: Path, monkeypatch
):
    def _fake_embeddings(texts, *, head, datasets, device):
        assert texts == ["condition A", "condition B", "condition C"]
        assert head == "infonce"
        return np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)

    monkeypatch.setattr(
        "brain_researcher.services.tools.neurovlm_tool._prepare_text_brain_embeddings",
        _fake_embeddings,
    )

    brain_rdm = np.asarray(
        [[0.0, 0.2, 0.4], [0.2, 0.0, 0.3], [0.4, 0.3, 0.0]], dtype=np.float32
    )
    brain_rdm_file = tmp_path / "brain_rdm.npy"
    np.save(brain_rdm_file, brain_rdm)

    out_dir = tmp_path / "rsa"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = execute_tool(
        "workflow_rsa_model_brain",
        {
            "brain_rdm": str(brain_rdm_file),
            "model_texts": ["condition A", "condition B", "condition C"],
            "output_dir": str(out_dir),
        },
    )

    assert result.status == "success", result.error

    model_rdm_file = out_dir / "model_rdm.npy"
    rsa_csv = out_dir / "rsa.csv"
    assert model_rdm_file.exists()
    assert rsa_csv.exists()

    model_rdm = np.load(model_rdm_file)
    assert model_rdm.shape == (3, 3)
    assert np.allclose(model_rdm, model_rdm.T)
    assert np.allclose(np.diag(model_rdm), 0.0)
