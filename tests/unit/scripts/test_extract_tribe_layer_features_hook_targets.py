"""Pin TRIBE layer-feature extractor hook targets.

A silent rename of ``encoder.layers.{i}.1`` to anything else inside the TRIBE
checkpoint would make the extractor produce empty hidden-state matrices without
raising. These tests fail loudly when that contract drifts.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "autoresearch"
    / "discovery"
    / "extract_tribe_layer_features.py"
)


def _load_module():
    name = "extract_tribe_layer_features"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _build_synthetic_tribe_torch_model() -> torch.nn.Module:
    """Mirror the relevant TRIBE module layout: ``ModuleList`` blocks of
    ``[Residual, Attention/FeedForward, Residual]`` plus projectors and head."""

    class Block(torch.nn.Module):
        def __init__(self, dim: int = 8) -> None:
            super().__init__()
            self.layers = torch.nn.ModuleList(
                torch.nn.ModuleList(
                    [torch.nn.Identity(), torch.nn.Linear(dim, dim), torch.nn.Identity()]
                )
                for _ in range(4)
            )
            self.final_norm = torch.nn.LayerNorm(dim)

    class Model(torch.nn.Module):
        def __init__(self, dim: int = 8) -> None:
            super().__init__()
            self.encoder = Block(dim)
            self.projectors = torch.nn.ModuleDict(
                {
                    "audio": torch.nn.Linear(dim, dim),
                    "text": torch.nn.Linear(dim, dim),
                    "video": torch.nn.Linear(dim, dim),
                }
            )
            self.low_rank_head = torch.nn.Linear(dim, dim)
            self.predictor = torch.nn.Linear(dim, dim)

    return Model()


def test_default_feature_ids_pin_baseline_targets() -> None:
    mod = _load_module()
    expected = {
        "aggregate_features",
        "transformer_forward",
        "encoder.final_norm",
        "low_rank_head.input",
        "low_rank_head.output",
        "predictor.input",
    }
    assert expected.issubset(set(mod.DEFAULT_FEATURE_IDS))


def test_module_name_for_feature_handles_input_output_suffixes() -> None:
    mod = _load_module()
    assert mod._module_name_for_feature("low_rank_head.input") == ("low_rank_head", True)
    assert mod._module_name_for_feature("low_rank_head.output") == ("low_rank_head", False)
    assert mod._module_name_for_feature("encoder.layers.10.1") == ("encoder.layers.10.1", False)


def test_default_feature_ids_target_encoder_block_child_one_not_container() -> None:
    """Hooks must target ``encoder.layers.{i}.1`` (the callable submodule),
    never the bare ``encoder.layers.{i}`` ``ModuleList`` container which does
    not fire forward hooks."""
    mod = _load_module()
    torch_model = _build_synthetic_tribe_torch_model()
    feature_ids = mod._default_feature_ids(torch_model, include_predictor_output=False)

    assert "encoder.layers.0.1" in feature_ids
    assert "encoder.layers.3.1" in feature_ids
    assert "encoder.layers.0" not in feature_ids
    assert "projectors.audio" in feature_ids
    assert "projectors.text" in feature_ids
    assert "projectors.video" in feature_ids
    assert "predictor.output" not in feature_ids

    feature_ids_with_predictor = mod._default_feature_ids(
        torch_model, include_predictor_output=True
    )
    assert "predictor.output" in feature_ids_with_predictor


def test_hook_manager_installs_module_hooks_on_encoder_block_child_one() -> None:
    """End-to-end pin: installing hooks on the synthetic model and running a
    forward pass populates accumulators for ``encoder.layers.{i}.1`` and the
    baseline modules. If TRIBE renames these targets, this test fails."""
    mod = _load_module()
    torch_model = _build_synthetic_tribe_torch_model()
    feature_ids = [
        "encoder.layers.0.1",
        "encoder.layers.2.1",
        "encoder.final_norm",
        "low_rank_head.input",
        "low_rank_head.output",
        "projectors.audio",
    ]

    with mod.HookManager(torch_model, feature_ids) as hooks:
        x = torch.randn(2, 8)
        for idx in range(4):
            x = torch_model.encoder.layers[idx][1](x)
        x = torch_model.encoder.final_norm(x)
        _ = torch_model.projectors["audio"](x)
        _ = torch_model.low_rank_head(x)

    for fid in feature_ids:
        status = hooks.hook_status.get(fid, "")
        assert status.startswith("module_hook:"), f"{fid}: {status}"
        assert hooks.accumulators[fid].n_observations > 0, fid
        assert hooks.accumulators[fid].mean_vector() is not None, fid


def test_hook_manager_reports_missing_module_when_layer_path_drifts() -> None:
    """If a future TRIBE upgrade renames ``encoder.layers.{i}.1``, the
    extractor's status string should make that visible rather than silently
    skipping the layer."""
    mod = _load_module()
    torch_model = _build_synthetic_tribe_torch_model()

    with mod.HookManager(torch_model, ["encoder.layers.99.1"]) as hooks:
        pass

    assert hooks.hook_status["encoder.layers.99.1"].startswith("module_not_found:")
