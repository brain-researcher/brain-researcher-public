"""Unit tests for the trusted full-pipeline label-permutation harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from brain_researcher.services.tools.full_pipeline_permutation_harness import (
    FullPipelinePermutationParameters,
    run_full_pipeline_permutation_null,
)

_invocations: list[dict[str, Any]] = []


def _train_mean_workflow(
    *,
    y_fit: np.ndarray,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    seed: int,
    workflow_config: dict[str, Any],
    output_dir: Path,
    is_observed: bool,
) -> np.ndarray:
    _invocations.append(
        {
            "is_observed": is_observed,
            "n_train": int(train_idx.size),
            "n_test": int(test_idx.size),
            "output_dir": str(output_dir),
        }
    )
    mean = float(np.mean(y_fit[train_idx]))
    return np.full(test_idx.size, mean, dtype=float)


def _echo_first_feature_workflow(
    *,
    y_fit: np.ndarray,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    seed: int,
    workflow_config: dict[str, Any],
    output_dir: Path,
    is_observed: bool,
) -> np.ndarray:
    # Ignores y_fit; "extracts a feature" deterministically from the indices.
    return test_idx.astype(float)


def _register_workflow(fn) -> str:
    name = f"_test_full_pipeline_wf_{fn.__name__}"
    module = ModuleType(name)
    setattr(module, "workflow", fn)
    sys.modules[name] = module
    return f"{name}:workflow"


def _write_inputs(
    tmp_path: Path, y: np.ndarray, folds: list[dict]
) -> tuple[Path, Path]:
    y_path = tmp_path / "y.npy"
    np.save(y_path, y)
    splits_path = tmp_path / "splits.json"
    splits_path.write_text(json.dumps({"folds": folds}), encoding="utf-8")
    return y_path, splits_path


@pytest.mark.unit
def test_harness_emits_trusted_full_pipeline_probe_shape(tmp_path: Path):
    _invocations.clear()
    y = np.arange(20, dtype=float)
    folds = [
        {"train": list(range(0, 10)), "test": list(range(10, 20))},
        {"train": list(range(10, 20)), "test": list(range(0, 10))},
    ]
    y_path, splits_path = _write_inputs(tmp_path, y, folds)

    params = FullPipelinePermutationParameters(
        workflow_callable_path=_register_workflow(_train_mean_workflow),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        workflow_config={"feature_pipeline": "demo"},
        n_permutations=5,
        seed=11,
        config_sha256="cfg-test",
    )

    result = run_full_pipeline_permutation_null(params)
    probe = result["probe"]

    assert probe["pipeline_scope"] == "full_pipeline"
    assert probe["generated_by"] == "br_full_pipeline_permutation_harness"
    assert probe["input_scope"] == "workflow_invocation"
    assert isinstance(probe["pipeline_invocation_sha256"], str)
    assert len(probe["pipeline_invocation_sha256"]) == 64
    assert probe["n_permutations"] == 5
    assert probe["config_sha256"] == "cfg-test"
    assert probe["split_manifest_sha256"]
    assert probe["verdict"] in {"null_indistinguishable", "signal_detected"}

    probe_path = Path(result["outputs"]["label_permutation_null"])
    assert probe_path == tmp_path / "review_probes" / "label_permutation_null.json"
    on_disk = json.loads(probe_path.read_text())
    assert on_disk["pipeline_invocation_sha256"] == probe["pipeline_invocation_sha256"]


@pytest.mark.unit
def test_harness_refits_workflow_per_fold_per_permutation(tmp_path: Path):
    _invocations.clear()
    y = np.arange(12, dtype=float)
    folds = [
        {"train": list(range(0, 6)), "test": list(range(6, 12))},
        {"train": list(range(6, 12)), "test": list(range(0, 6))},
    ]
    y_path, splits_path = _write_inputs(tmp_path, y, folds)

    params = FullPipelinePermutationParameters(
        workflow_callable_path=_register_workflow(_train_mean_workflow),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        n_permutations=4,
        seed=3,
    )

    run_full_pipeline_permutation_null(params)

    observed_calls = [call for call in _invocations if call["is_observed"]]
    perm_calls = [call for call in _invocations if not call["is_observed"]]
    assert len(observed_calls) == len(folds)
    assert len(perm_calls) == 4 * len(folds)
    # Per-permutation directories should be unique
    perm_dirs = {call["output_dir"] for call in perm_calls}
    assert len(perm_dirs) == 4 * len(folds)


@pytest.mark.unit
def test_harness_scores_against_original_y_under_permutation(tmp_path: Path):
    y = np.arange(20, dtype=float)
    folds = [
        {"train": list(range(0, 10)), "test": list(range(10, 20))},
        {"train": list(range(10, 20)), "test": list(range(0, 10))},
    ]
    y_path, splits_path = _write_inputs(tmp_path, y, folds)

    params = FullPipelinePermutationParameters(
        workflow_callable_path=_register_workflow(_echo_first_feature_workflow),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        n_permutations=6,
        seed=0,
    )

    probe = run_full_pipeline_permutation_null(params)["probe"]
    # Workflow ignores y_fit; predictions equal y[test_idx] in every pass.
    # Observed and null should both yield R^2 = 1.0.
    assert probe["observed_metric"] == pytest.approx(1.0)
    assert probe["null_mean"] == pytest.approx(1.0)


@pytest.mark.unit
def test_harness_invocation_hash_changes_with_workflow_config(tmp_path: Path):
    y = np.arange(10, dtype=float)
    folds = [{"train": list(range(0, 5)), "test": list(range(5, 10))}]
    y_path, splits_path = _write_inputs(tmp_path, y, folds)

    base = FullPipelinePermutationParameters(
        workflow_callable_path=_register_workflow(_train_mean_workflow),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path / "run_a"),
        workflow_config={"alpha": 1.0},
        n_permutations=2,
        seed=1,
    )
    alt = FullPipelinePermutationParameters(
        workflow_callable_path=_register_workflow(_train_mean_workflow),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path / "run_b"),
        workflow_config={"alpha": 2.0},
        n_permutations=2,
        seed=1,
    )

    sha_a = run_full_pipeline_permutation_null(base)["probe"][
        "pipeline_invocation_sha256"
    ]
    sha_b = run_full_pipeline_permutation_null(alt)["probe"][
        "pipeline_invocation_sha256"
    ]
    assert sha_a != sha_b


@pytest.mark.unit
def test_harness_probe_satisfies_native_trust_check(tmp_path: Path):
    """Probe written by the harness must be ranked as trusted full-pipeline
    by the native bundle_builder sidecar discovery so the review gate
    actually upgrades it."""

    from brain_researcher.services.review.bundle_builder import (
        _discover_review_sidecars,
        _is_trusted_full_pipeline_label_probe,
    )

    y = np.arange(10, dtype=float)
    folds = [{"train": list(range(0, 5)), "test": list(range(5, 10))}]
    y_path, splits_path = _write_inputs(tmp_path, y, folds)

    run_full_pipeline_permutation_null(
        FullPipelinePermutationParameters(
            workflow_callable_path=_register_workflow(_train_mean_workflow),
            y_path=str(y_path),
            split_manifest_path=str(splits_path),
            output_dir=str(tmp_path),
            n_permutations=2,
            seed=1,
        )
    )

    discovered = _discover_review_sidecars(tmp_path)
    probe = discovered["review_probes"]["label_permutation_null"]
    assert _is_trusted_full_pipeline_label_probe(probe)
