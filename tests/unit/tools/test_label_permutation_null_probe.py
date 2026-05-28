"""Unit tests for the label-permutation-null probe emitter."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from brain_researcher.services.tools.params.permutation_testing import (
    LabelPermutationNullParameters,
    run_label_permutation_null,
)
from brain_researcher.services.tools.permutation_testing_tool import (
    PermutationTestingTool,
)


class _MeanEstimator:
    """Tiny estimator that predicts the train mean for every test row."""

    def fit(self, X, y):
        self._mean = float(np.mean(y))
        return self

    def predict(self, X):
        return np.full(len(X), self._mean, dtype=float)


class _LinearLeakageEstimator:
    """Deterministic estimator that fits exactly on the train fold."""

    def fit(self, X, y):
        X = np.asarray(X)
        y = np.asarray(y)
        denom = float(np.sum(X[:, 0] ** 2))
        self._slope = float(np.sum(X[:, 0] * y) / denom) if denom else 0.0
        return self

    def predict(self, X):
        X = np.asarray(X)
        return X[:, 0] * self._slope


class _FeatureEchoEstimator:
    """Estimator that predicts the first feature after being refit."""

    fit_calls = 0

    def fit(self, X, y):
        type(self).fit_calls += 1
        return self

    def predict(self, X):
        X = np.asarray(X)
        return X[:, 0]


def _factory_path(estimator_cls) -> str:
    module = ModuleType(f"_probe_module_{estimator_cls.__name__}")
    module.factory = estimator_cls
    sys.modules[module.__name__] = module
    return f"{module.__name__}:factory"


def _write_arrays(
    tmp_path: Path,
    X: np.ndarray,
    y: np.ndarray,
    folds: list[dict],
) -> tuple[Path, Path, Path]:
    x_path = tmp_path / "X.npy"
    y_path = tmp_path / "y.npy"
    splits_path = tmp_path / "splits.json"
    np.save(x_path, X)
    np.save(y_path, y)
    splits_path.write_text(json.dumps({"folds": folds}), encoding="utf-8")
    return x_path, y_path, splits_path


@pytest.mark.unit
def test_run_label_permutation_null_emits_registry_shaped_probe(tmp_path: Path):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(40, 3))
    y = rng.normal(size=40)
    folds = [
        {"train": list(range(0, 20)), "test": list(range(20, 40))},
        {"train": list(range(20, 40)), "test": list(range(0, 20))},
    ]
    x_path, y_path, splits_path = _write_arrays(tmp_path, X, y, folds)

    params = LabelPermutationNullParameters(
        estimator_factory_path=_factory_path(_MeanEstimator),
        X_path=str(x_path),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        cv_scope="nested_outer_cv",
        exchangeability_unit="row",
        metric="r2",
        n_permutations=25,
        seed=42,
        config_sha256="cfg-test",
    )

    result = run_label_permutation_null(params)
    probe = result["probe"]

    required_fields = {
        "status",
        "n_permutations",
        "seed",
        "pipeline_scope",
        "generated_by",
        "input_scope",
        "cv_scope",
        "exchangeability_unit",
        "metric",
        "observed_metric",
        "null_mean",
        "null_p95",
        "null_max",
        "empirical_p",
        "split_manifest_sha256",
        "config_sha256",
        "verdict",
    }
    assert required_fields.issubset(probe.keys()), required_fields - probe.keys()
    assert probe["pipeline_scope"] == "feature_matrix_only"
    assert probe["generated_by"] == "permutation_testing_tool"
    assert probe["input_scope"] == "feature_matrix"
    assert probe["n_permutations"] == 25
    assert probe["config_sha256"] == "cfg-test"
    assert probe["split_manifest_sha256"]
    assert probe["verdict"] in {"null_indistinguishable", "signal_detected"}

    probe_path = Path(result["outputs"]["label_permutation_null"])
    assert probe_path.exists()
    assert probe_path.parent.name == "review_probes"
    on_disk = json.loads(probe_path.read_text())
    assert on_disk["pipeline_scope"] == "feature_matrix_only"


@pytest.mark.unit
def test_run_label_permutation_null_detects_signal(tmp_path: Path):
    rng = np.random.default_rng(1)
    X = rng.normal(size=(60, 1))
    y = X[:, 0] * 3.0 + rng.normal(scale=0.05, size=60)
    folds = [
        {"train": list(range(0, 30)), "test": list(range(30, 60))},
        {"train": list(range(30, 60)), "test": list(range(0, 30))},
    ]
    x_path, y_path, splits_path = _write_arrays(tmp_path, X, y, folds)

    params = LabelPermutationNullParameters(
        estimator_factory_path=_factory_path(_LinearLeakageEstimator),
        X_path=str(x_path),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        metric="r2",
        n_permutations=40,
        seed=7,
    )

    result = run_label_permutation_null(params)
    probe = result["probe"]
    assert probe["verdict"] == "signal_detected"
    assert probe["empirical_p"] <= 0.05
    assert probe["observed_metric"] > probe["null_p95"]


@pytest.mark.unit
def test_label_permutation_null_scores_permutations_against_original_y_test(
    tmp_path: Path,
):
    X = np.arange(20, dtype=float).reshape(-1, 1)
    y = X[:, 0].copy()
    folds = [
        {"train": list(range(0, 10)), "test": list(range(10, 20))},
        {"train": list(range(10, 20)), "test": list(range(0, 10))},
    ]
    x_path, y_path, splits_path = _write_arrays(tmp_path, X, y, folds)
    _FeatureEchoEstimator.fit_calls = 0

    params = LabelPermutationNullParameters(
        estimator_factory_path=_factory_path(_FeatureEchoEstimator),
        X_path=str(x_path),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        metric="r2",
        n_permutations=8,
        seed=123,
    )

    result = run_label_permutation_null(params)
    probe = result["probe"]

    assert probe["observed_metric"] == pytest.approx(1.0)
    assert probe["null_mean"] == pytest.approx(1.0)
    assert probe["null_p95"] == pytest.approx(1.0)
    assert _FeatureEchoEstimator.fit_calls == (1 + 8) * len(folds)


@pytest.mark.unit
def test_untrusted_full_pipeline_request_is_downgraded(tmp_path: Path):
    X = np.arange(12, dtype=float).reshape(-1, 1)
    y = np.arange(12, dtype=float)
    folds = [{"train": list(range(0, 6)), "test": list(range(6, 12))}]
    x_path, y_path, splits_path = _write_arrays(tmp_path, X, y, folds)

    params = LabelPermutationNullParameters(
        estimator_factory_path=_factory_path(_MeanEstimator),
        X_path=str(x_path),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        metric="r2",
        n_permutations=2,
        seed=11,
        pipeline_scope="full_pipeline",
    )

    probe = run_label_permutation_null(params)["probe"]

    assert probe["pipeline_scope"] == "feature_matrix_only"
    assert probe["requested_pipeline_scope"] == "full_pipeline"
    assert probe["generated_by"] == "permutation_testing_tool"
    assert probe["pipeline_invocation_sha256"] is None


@pytest.mark.unit
def test_trusted_harness_metadata_preserves_full_pipeline_scope(tmp_path: Path):
    X = np.arange(12, dtype=float).reshape(-1, 1)
    y = np.arange(12, dtype=float)
    folds = [{"train": list(range(0, 6)), "test": list(range(6, 12))}]
    x_path, y_path, splits_path = _write_arrays(tmp_path, X, y, folds)

    params = LabelPermutationNullParameters(
        estimator_factory_path=_factory_path(_MeanEstimator),
        X_path=str(x_path),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        metric="r2",
        n_permutations=2,
        seed=12,
        pipeline_scope="full_pipeline",
        generated_by="br_full_pipeline_permutation_harness",
        input_scope="workflow_invocation",
        pipeline_invocation_sha256="workflow-digest",
    )

    probe = run_label_permutation_null(params)["probe"]

    assert probe["pipeline_scope"] == "full_pipeline"
    assert probe["generated_by"] == "br_full_pipeline_permutation_harness"
    assert probe["input_scope"] == "workflow_invocation"
    assert probe["pipeline_invocation_sha256"] == "workflow-digest"
    assert "requested_pipeline_scope" not in probe


@pytest.mark.unit
def test_permutation_testing_tool_runs_label_permutation_null_probe(tmp_path: Path):
    rng = np.random.default_rng(2)
    X = rng.normal(size=(24, 2))
    y = rng.normal(size=24)
    folds = [
        {"train": list(range(0, 12)), "test": list(range(12, 24))},
        {"train": list(range(12, 24)), "test": list(range(0, 12))},
    ]
    x_path, y_path, splits_path = _write_arrays(tmp_path, X, y, folds)

    result = PermutationTestingTool().run(
        probe="label_permutation_null",
        estimator_factory_path=_factory_path(_MeanEstimator),
        X_path=str(x_path),
        y_path=str(y_path),
        split_manifest_path=str(splits_path),
        output_dir=str(tmp_path),
        n_permutations=5,
        seed=9,
    )

    assert result["status"] == "success"
    probe_path = Path(result["data"]["outputs"]["label_permutation_null"])
    assert probe_path == tmp_path / "review_probes" / "label_permutation_null.json"
    assert json.loads(probe_path.read_text())["pipeline_scope"] == "feature_matrix_only"
