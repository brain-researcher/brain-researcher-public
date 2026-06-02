"""Fallback-friendly permutation testing helpers."""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


def _as_tuple(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(str(v) for v in values)


@dataclass(frozen=True)
class PermutationTestParameters:
    """Lightweight configuration for permutation testing."""

    data_file: str | None = None
    group1_files: tuple[str, ...] = ()
    group2_files: tuple[str, ...] = ()
    test_type: str = "ttest_1samp"
    n_permutations: int = 1000
    alpha: float = 0.05
    tail: int = 0
    correction_method: str = "none"
    cluster_threshold: float | None = None
    tfce_e: float = 0.5
    tfce_h: float = 2.0
    mask_file: str | None = None
    design_matrix: Any | None = None
    contrast: Any | None = None
    output_dir: str = str(Path.cwd() / "permutation_test")
    save_stats: bool = True
    save_clusters: bool = True
    save_null: bool = False
    seed: int | None = None
    n_jobs: int = 1
    verbose: bool = True


def permutation_test_from_payload(payload: dict[str, Any]) -> PermutationTestParameters:
    """Create parameters from a JSON-serialisable payload."""

    return PermutationTestParameters(
        data_file=payload.get("data_file"),
        group1_files=_as_tuple(payload.get("group1_files")),
        group2_files=_as_tuple(payload.get("group2_files")),
        test_type=str(payload.get("test_type", "ttest_1samp")),
        n_permutations=int(payload.get("n_permutations", 1000)),
        alpha=float(payload.get("alpha", 0.05)),
        tail=int(payload.get("tail", 0)),
        correction_method=str(payload.get("correction_method", "none")),
        cluster_threshold=payload.get("cluster_threshold"),
        tfce_e=float(payload.get("tfce_e", 0.5)),
        tfce_h=float(payload.get("tfce_h", 2.0)),
        mask_file=payload.get("mask_file"),
        design_matrix=payload.get("design_matrix"),
        contrast=payload.get("contrast"),
        output_dir=(
            str(payload["output_dir"])
            if payload.get("output_dir")
            else str(Path.cwd() / "permutation_test")
        ),
        save_stats=bool(payload.get("save_stats", True)),
        save_clusters=bool(payload.get("save_clusters", True)),
        save_null=bool(payload.get("save_null", False)),
        seed=payload.get("seed"),
        n_jobs=int(payload.get("n_jobs", 1)),
        verbose=bool(payload.get("verbose", True)),
    )


def _load_numeric_array(path: str) -> np.ndarray:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(path)

    if file_path.suffix in {".npy", ".npz"}:
        data = np.load(file_path)  # type: ignore[assignment]
        if isinstance(data, np.lib.npyio.NpzFile):
            first_key = data.files[0]
            return np.asarray(data[first_key])
        return np.asarray(data)

    try:
        return np.loadtxt(file_path)
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise ValueError(f"Unable to load numeric data from {path}") from exc


def _reshape(vector: np.ndarray, feature_shape: tuple[int, ...]) -> np.ndarray:
    if feature_shape:
        return vector.reshape(feature_shape)
    if vector.size == 1:
        return vector.reshape(())
    return vector.reshape((vector.size,))


def _p_values(observed: np.ndarray, null_dist: np.ndarray, tail: int) -> np.ndarray:
    if tail == 0:
        greater = np.abs(null_dist) >= np.abs(observed)
    elif tail > 0:
        greater = null_dist >= observed
    else:
        greater = null_dist <= observed

    counts = greater.sum(axis=0, dtype=float)
    return (counts + 1.0) / (null_dist.shape[0] + 1.0)


def _apply_correction(p_values: np.ndarray, method: str) -> np.ndarray:
    method = method.lower()
    flat = p_values.ravel()
    n_tests = max(len(flat), 1)

    if method in {"none", "", "uncorrected"}:
        return p_values

    if method in {"fwe_bonferroni", "bonferroni"}:
        corrected = np.minimum(flat * n_tests, 1.0)
        return corrected.reshape(p_values.shape)

    # Default to Benjamini-Hochberg FDR
    order = np.argsort(flat)
    ranks = np.arange(1, n_tests + 1)
    adjusted = np.empty_like(flat, dtype=float)
    adjusted[order] = flat[order] * n_tests / ranks
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    return np.clip(adjusted.reshape(p_values.shape), 0.0, 1.0)


def _summarise_distribution(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
    }


def run_permutation_test(params: PermutationTestParameters) -> dict[str, Any]:
    """Execute a lightweight permutation test with analytic fallbacks."""

    output_dir = Path(params.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(params.seed)
    n_perm = max(100, min(params.n_permutations, 2048))

    if params.data_file:
        data = _load_numeric_array(params.data_file)
        if data.ndim == 1:
            data = data[:, np.newaxis]
        data_flat = data.reshape(data.shape[0], -1)
        feature_shape = tuple(data.shape[1:]) if data.ndim > 1 else (1,)

        observed = data_flat.mean(axis=0)
        std = data_flat.std(axis=0, ddof=1)
        std[std == 0] = 1e-6
        null = rng.normal(
            loc=0.0,
            scale=std / np.sqrt(data_flat.shape[0]),
            size=(n_perm, observed.size),
        )
        n_subjects = data_flat.shape[0]

    elif params.group1_files and params.group2_files:
        group1 = np.stack([_load_numeric_array(p) for p in params.group1_files])
        group2 = np.stack([_load_numeric_array(p) for p in params.group2_files])

        group1_flat = group1.reshape(group1.shape[0], -1)
        group2_flat = group2.reshape(group2.shape[0], -1)
        feature_shape = tuple(group1.shape[1:]) if group1.ndim > 1 else (1,)

        observed = group1_flat.mean(axis=0) - group2_flat.mean(axis=0)
        pooled_var = group1_flat.var(axis=0, ddof=1) / max(
            group1_flat.shape[0], 1
        ) + group2_flat.var(axis=0, ddof=1) / max(group2_flat.shape[0], 1)
        pooled_std = np.sqrt(np.clip(pooled_var, 1e-6, None))
        null = rng.normal(loc=0.0, scale=pooled_std, size=(n_perm, observed.size))
        n_subjects = group1_flat.shape[0] + group2_flat.shape[0]

    else:
        raise ValueError(
            "Permutation testing requires 'data_file' or both 'group1_files' and 'group2_files'."
        )

    observed_map = _reshape(observed, feature_shape)
    p_values = _reshape(_p_values(observed, null, params.tail), feature_shape)
    corrected_p = _apply_correction(p_values, params.correction_method)
    significant = (corrected_p <= params.alpha).astype(np.uint8)

    outputs: dict[str, str | None] = {
        "summary": None,
        "observed": None,
        "p_values": None,
        "corrected_p_values": None,
        "significance_mask": None,
        "null_distribution": None,
        "clusters": None,
    }

    observed_path = output_dir / "permutation_observed.npy"
    if params.save_stats:
        np.save(observed_path, observed_map)
        outputs["observed"] = str(observed_path)

    p_values_path = output_dir / "permutation_pvalues.npy"
    np.save(p_values_path, p_values)
    outputs["p_values"] = str(p_values_path)

    corrected_path = output_dir / "permutation_corrected_pvalues.npy"
    np.save(corrected_path, corrected_p)
    outputs["corrected_p_values"] = str(corrected_path)

    mask_path = output_dir / "permutation_significant_mask.npy"
    np.save(mask_path, significant)
    outputs["significance_mask"] = str(mask_path)

    if params.save_null:
        null_path = output_dir / "permutation_null_distribution.npy"
        np.save(null_path, null)
        outputs["null_distribution"] = str(null_path)

    if params.save_clusters:
        clusters_path = output_dir / "permutation_clusters.json"
        clusters_path.write_text(json.dumps({"placeholder": True}), encoding="utf-8")
        outputs["clusters"] = str(clusters_path)

    summary = {
        "test_type": params.test_type,
        "n_subjects": int(n_subjects),
        "n_features": int(observed.size),
        "n_permutations": int(n_perm),
        "alpha": float(params.alpha),
        "tail": int(params.tail),
        "correction_method": params.correction_method,
        "observed_stats": _summarise_distribution(observed),
        "p_value_stats": _summarise_distribution(p_values),
        "significant_voxels": int(np.count_nonzero(significant)),
        "used_full_backend": False,
    }

    summary_path = output_dir / "permutation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["summary"] = str(summary_path)

    return {
        "outputs": outputs,
        "summary": summary,
        "message": "Permutation testing completed (fallback).",
    }


@dataclass(frozen=True)
class LabelPermutationNullParameters:
    """Configuration for a label-permutation-null probe.

    This implementation consumes a precomputed feature matrix and refits the
    estimator factory per permutation. It is model/feature-matrix scoped unless
    a trusted outer harness supplies workflow-invocation provenance.
    """

    estimator_factory_path: str
    X_path: str
    y_path: str
    split_manifest_path: str
    output_dir: str
    cv_scope: str = "nested_outer_cv"
    exchangeability_unit: str = "row"
    metric: str = "r2"
    n_permutations: int = 1000
    seed: int = 0
    config_sha256: str | None = None
    groups_path: str | None = None
    null_indistinguishable_threshold: float = 0.05
    pipeline_scope: str = "feature_matrix_only"
    generated_by: str = "permutation_testing_tool"
    input_scope: str = "feature_matrix"
    pipeline_invocation_sha256: str | None = None


_FULL_PIPELINE_SCOPE_VALUES = frozenset(
    {
        "full_pipeline",
        "whole_pipeline",
        "end_to_end",
        "entire_pipeline",
        "pipeline",
    }
)
_TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS = frozenset(
    {
        "br_full_pipeline_permutation_harness",
        "br.workflow.full_pipeline_permutation_harness",
    }
)
_TRUSTED_FULL_PIPELINE_INPUT_SCOPES = frozenset(
    {
        "raw_inputs",
        "workflow_invocation",
        "full_pipeline",
    }
)
_FEATURE_MATRIX_SCOPE_VALUES = frozenset(
    {
        "feature_matrix",
        "feature_matrix_only",
        "model",
        "model_only",
        "estimator",
        "estimator_only",
    }
)


def label_permutation_null_from_payload(
    payload: dict[str, Any],
) -> LabelPermutationNullParameters:
    """Create probe parameters from a JSON-serialisable payload."""

    return LabelPermutationNullParameters(
        estimator_factory_path=str(payload["estimator_factory_path"]),
        X_path=str(payload["X_path"]),
        y_path=str(payload["y_path"]),
        split_manifest_path=str(payload["split_manifest_path"]),
        output_dir=str(payload["output_dir"]),
        cv_scope=str(payload.get("cv_scope", "nested_outer_cv")),
        exchangeability_unit=str(payload.get("exchangeability_unit", "row")),
        metric=str(payload.get("metric", "r2")),
        n_permutations=int(payload.get("n_permutations", 1000)),
        seed=int(payload.get("seed", 0)),
        config_sha256=payload.get("config_sha256"),
        groups_path=payload.get("groups_path"),
        null_indistinguishable_threshold=float(
            payload.get("null_indistinguishable_threshold", 0.05)
        ),
        pipeline_scope=str(payload.get("pipeline_scope", "feature_matrix_only")),
        generated_by=str(payload.get("generated_by", "permutation_testing_tool")),
        input_scope=str(payload.get("input_scope", "feature_matrix")),
        pipeline_invocation_sha256=payload.get("pipeline_invocation_sha256"),
    )


def _import_callable(path: str) -> Callable[[], Any]:
    module_name, _, attr = path.rpartition(":")
    if not module_name:
        module_name, _, attr = path.rpartition(".")
    if not module_name or not attr:
        raise ValueError(
            f"estimator_factory_path must be 'module.path:callable' or 'module.path.callable', got {path!r}"
        )
    module = importlib.import_module(module_name)
    factory = getattr(module, attr)
    if not callable(factory):
        raise TypeError(f"{path} is not callable")
    return factory


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_split_manifest(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "folds" in raw:
        folds = raw["folds"]
    else:
        folds = raw
    if not isinstance(folds, list):
        raise ValueError(
            f"Split manifest at {path} must be a list of folds or {{'folds': [...]}}"
        )
    parsed: list[dict[str, Any]] = []
    for fold in folds:
        if not isinstance(fold, dict):
            continue
        train = fold.get("train") or fold.get("train_idx") or fold.get("train_indices")
        test = fold.get("test") or fold.get("test_idx") or fold.get("test_indices")
        if train is None or test is None:
            continue
        parsed.append(
            {
                "train": np.asarray(train, dtype=int),
                "test": np.asarray(test, dtype=int),
            }
        )
    if not parsed:
        raise ValueError(f"No usable folds found in split manifest {path}")
    return parsed


def _compute_metric(metric: str, y_true: np.ndarray, y_pred: np.ndarray) -> float:
    metric = metric.lower()
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if metric in {"r2", "r_squared"}:
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        mean = float(np.mean(y_true))
        ss_tot = float(np.sum((y_true - mean) ** 2))
        if ss_tot == 0.0:
            return 0.0
        return 1.0 - ss_res / ss_tot
    if metric in {"accuracy", "acc"}:
        return float(np.mean(y_true == y_pred))
    if metric in {"neg_mse", "neg_mean_squared_error"}:
        return -float(np.mean((y_true - y_pred) ** 2))
    if metric in {"pearson_r", "pearson"}:
        if y_true.size < 2:
            return 0.0
        coeff = np.corrcoef(y_true, y_pred)
        return float(coeff[0, 1]) if np.isfinite(coeff[0, 1]) else 0.0
    raise ValueError(f"Unsupported metric: {metric}")


def _shuffle_within_groups(
    y: np.ndarray,
    groups: np.ndarray | None,
    rng: np.random.Generator,
) -> np.ndarray:
    if groups is None or groups.size == 0:
        permuted = y.copy()
        rng.shuffle(permuted)
        return permuted
    permuted = y.copy()
    for unique in np.unique(groups):
        idx = np.where(groups == unique)[0]
        if idx.size <= 1:
            continue
        shuffled = idx.copy()
        rng.shuffle(shuffled)
        permuted[idx] = y[shuffled]
    return permuted


def _evaluate_pipeline(
    factory: Callable[[], Any],
    X: np.ndarray,
    y_fit: np.ndarray,
    y_score: np.ndarray,
    folds: Sequence[dict[str, Any]],
    metric: str,
) -> float:
    fold_scores: list[float] = []
    for fold in folds:
        train_idx = fold["train"]
        test_idx = fold["test"]
        if train_idx.size == 0 or test_idx.size == 0:
            continue
        estimator = factory()
        estimator.fit(X[train_idx], y_fit[train_idx])
        y_pred = estimator.predict(X[test_idx])
        fold_scores.append(_compute_metric(metric, y_score[test_idx], y_pred))
    if not fold_scores:
        return float("nan")
    return float(np.mean(fold_scores))


def _normalise_token(value: Any) -> str:
    return str(value or "").strip().lower()


def _effective_pipeline_scope(params: LabelPermutationNullParameters) -> str:
    requested_scope = _normalise_token(params.pipeline_scope)
    if requested_scope in _FULL_PIPELINE_SCOPE_VALUES:
        generated_by = _normalise_token(params.generated_by)
        input_scope = _normalise_token(params.input_scope)
        if (
            generated_by in _TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS
            and input_scope in _TRUSTED_FULL_PIPELINE_INPUT_SCOPES
            and bool(str(params.pipeline_invocation_sha256 or "").strip())
        ):
            return "full_pipeline"
        return "feature_matrix_only"
    if requested_scope in _FEATURE_MATRIX_SCOPE_VALUES:
        return "feature_matrix_only"
    return "feature_matrix_only"


def run_label_permutation_null(
    params: LabelPermutationNullParameters,
) -> dict[str, Any]:
    """Execute a label-permutation-null probe.

    Refits the estimator factory per permutation and writes
    ``review_probes/label_permutation_null.json`` in the registry-mandated
    shape so deterministic scientific-review checks can find the probe. The
    emitted ``pipeline_scope`` is only ``full_pipeline`` for trusted harness
    outputs with workflow-invocation provenance.
    """

    output_dir = Path(params.output_dir)
    probes_dir = output_dir / "review_probes"
    probes_dir.mkdir(parents=True, exist_ok=True)

    factory = _import_callable(params.estimator_factory_path)

    X = _load_numeric_array(params.X_path)
    y = _load_numeric_array(params.y_path).ravel()
    groups = (
        _load_numeric_array(params.groups_path).ravel() if params.groups_path else None
    )

    manifest_path = Path(params.split_manifest_path)
    folds = _load_split_manifest(manifest_path)
    split_manifest_sha = _sha256_file(manifest_path)

    n_permutations = max(1, int(params.n_permutations))
    rng = np.random.default_rng(params.seed)

    observed_metric = _evaluate_pipeline(factory, X, y, y, folds, params.metric)

    null_values: list[float] = []
    for _ in range(n_permutations):
        y_perm = _shuffle_within_groups(y, groups, rng)
        score = _evaluate_pipeline(factory, X, y_perm, y, folds, params.metric)
        null_values.append(score)

    null_array = np.asarray(null_values, dtype=float)
    finite = null_array[np.isfinite(null_array)]
    if finite.size == 0:
        null_mean = float("nan")
        null_p95 = float("nan")
        null_max = float("nan")
        empirical_p = 1.0
    else:
        null_mean = float(np.mean(finite))
        null_p95 = float(np.percentile(finite, 95))
        null_max = float(np.max(finite))
        n_ge = int(np.sum(finite >= observed_metric))
        empirical_p = (n_ge + 1) / (finite.size + 1)

    verdict = (
        "signal_detected"
        if empirical_p <= params.null_indistinguishable_threshold
        else "null_indistinguishable"
    )
    pipeline_scope = _effective_pipeline_scope(params)
    requested_pipeline_scope = _normalise_token(params.pipeline_scope)

    probe = {
        "status": "ok",
        "n_permutations": int(n_permutations),
        "seed": int(params.seed),
        "pipeline_scope": pipeline_scope,
        "generated_by": params.generated_by,
        "input_scope": params.input_scope,
        "cv_scope": params.cv_scope,
        "exchangeability_unit": params.exchangeability_unit,
        "metric": params.metric,
        "observed_metric": float(observed_metric),
        "null_mean": null_mean,
        "null_p95": null_p95,
        "null_max": null_max,
        "empirical_p": float(empirical_p),
        "split_manifest_sha256": split_manifest_sha,
        "config_sha256": params.config_sha256,
        "pipeline_invocation_sha256": params.pipeline_invocation_sha256,
        "verdict": verdict,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    if requested_pipeline_scope and requested_pipeline_scope != pipeline_scope:
        probe["requested_pipeline_scope"] = requested_pipeline_scope

    probe_path = probes_dir / "label_permutation_null.json"
    probe_path.write_text(json.dumps(probe, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "outputs": {"label_permutation_null": str(probe_path)},
        "probe": probe,
        "message": "Label-permutation-null probe completed.",
    }


__all__ = [
    "PermutationTestParameters",
    "permutation_test_from_payload",
    "run_permutation_test",
    "LabelPermutationNullParameters",
    "label_permutation_null_from_payload",
    "run_label_permutation_null",
]
