"""Trusted full-pipeline label-permutation-null harness.

The deterministic scientific-review gate only treats a label-permutation-null
probe as ``pipeline_scope=full_pipeline`` evidence when it is emitted by a
trusted generator with workflow-invocation provenance. The plain
``permutation_testing_tool`` shuffles labels and refits an estimator against a
fixed feature matrix, so it can never satisfy that bar.

This harness fills that gap: it accepts an importable workflow callable that
encapsulates the full pipeline (raw inputs → feature extraction → fit-able
preprocessing → estimator → predictions), re-runs the callable per permutation
per fold under shuffled labels, scores predictions against the **original**
test labels, and writes ``review_probes/label_permutation_null.json`` with the
trusted ``generated_by`` / ``input_scope`` / ``pipeline_invocation_sha256``
fields the gate looks for.

Workflow callable contract::

    def workflow_fn(
        *,
        y_fit: np.ndarray,            # full y vector for the fit phase
                                       # (shuffled on permutation passes)
        train_idx: np.ndarray,        # row indices for this fold's train set
        test_idx: np.ndarray,         # row indices for this fold's test set
        seed: int,                    # per-call seed for any RNG inside the workflow
        workflow_config: dict[str, Any],
        output_dir: Path,             # per-invocation workspace
        is_observed: bool,            # True only for the observed pass
    ) -> np.ndarray                   # predictions for ``test_idx``
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from brain_researcher.services.tools.params.permutation_testing import (
    _compute_metric,
    _import_callable,
    _load_numeric_array,
    _load_split_manifest,
    _sha256_file,
    _shuffle_within_groups,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_GENERATOR_NAME = "br_full_pipeline_permutation_harness"
_INPUT_SCOPE = "workflow_invocation"


@dataclass(frozen=True)
class FullPipelinePermutationParameters:
    """Configuration for a full-pipeline label-permutation-null harness run."""

    workflow_callable_path: str
    y_path: str
    split_manifest_path: str
    output_dir: str
    workflow_config: dict[str, Any] = field(default_factory=dict)
    cv_scope: str = "nested_outer_cv"
    exchangeability_unit: str = "row"
    metric: str = "r2"
    n_permutations: int = 1000
    seed: int = 0
    config_sha256: str | None = None
    groups_path: str | None = None
    null_indistinguishable_threshold: float = 0.05


def full_pipeline_permutation_from_payload(
    payload: dict[str, Any],
) -> FullPipelinePermutationParameters:
    return FullPipelinePermutationParameters(
        workflow_callable_path=str(payload["workflow_callable_path"]),
        y_path=str(payload["y_path"]),
        split_manifest_path=str(payload["split_manifest_path"]),
        output_dir=str(payload["output_dir"]),
        workflow_config=dict(payload.get("workflow_config") or {}),
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
    )


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _pipeline_invocation_sha256(
    workflow_callable_path: str,
    workflow_callable: Callable[..., Any],
    workflow_config: dict[str, Any],
    split_manifest_sha256: str,
) -> str:
    """Bind the probe to the exact workflow callable + config + splits.

    A reviewer can replay this hash to verify that the probe was emitted for
    the same pipeline source, configuration, and CV layout as the headline
    result. Source hashing is best-effort — we fall back to the callable path
    alone when the source isn't available on disk (e.g. dynamically defined
    test fixtures).
    """

    digest = hashlib.sha256()
    digest.update(workflow_callable_path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(split_manifest_sha256.encode("utf-8"))
    digest.update(b"\0")
    digest.update(_canonical_json(workflow_config).encode("utf-8"))
    digest.update(b"\0")
    try:
        source_file = inspect.getsourcefile(workflow_callable)
        if source_file:
            source_path = Path(source_file)
            if source_path.exists():
                digest.update(source_path.read_bytes())
    except (TypeError, OSError):
        pass
    return digest.hexdigest()


def _run_workflow(
    workflow_callable: Callable[..., Any],
    *,
    y_fit: np.ndarray,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    seed: int,
    workflow_config: dict[str, Any],
    output_dir: Path,
    is_observed: bool,
) -> np.ndarray:
    predictions = workflow_callable(
        y_fit=y_fit,
        train_idx=train_idx,
        test_idx=test_idx,
        seed=seed,
        workflow_config=workflow_config,
        output_dir=output_dir,
        is_observed=is_observed,
    )
    return np.asarray(predictions, dtype=float).ravel()


def _score_workflow_pass(
    workflow_callable: Callable[..., Any],
    *,
    y_fit: np.ndarray,
    y_score: np.ndarray,
    folds: list[dict[str, Any]],
    metric: str,
    seed: int,
    workflow_config: dict[str, Any],
    base_output_dir: Path,
    is_observed: bool,
) -> float:
    fold_scores: list[float] = []
    for fold_idx, fold in enumerate(folds):
        train_idx = np.asarray(fold["train"], dtype=int)
        test_idx = np.asarray(fold["test"], dtype=int)
        if train_idx.size == 0 or test_idx.size == 0:
            continue
        fold_out = base_output_dir / f"fold-{fold_idx:02d}"
        fold_out.mkdir(parents=True, exist_ok=True)
        y_pred = _run_workflow(
            workflow_callable,
            y_fit=y_fit,
            train_idx=train_idx,
            test_idx=test_idx,
            seed=seed,
            workflow_config=workflow_config,
            output_dir=fold_out,
            is_observed=is_observed,
        )
        if y_pred.size != test_idx.size:
            raise ValueError(
                f"Workflow callable returned {y_pred.size} predictions for fold "
                f"{fold_idx} but the test set has {test_idx.size} rows."
            )
        fold_scores.append(_compute_metric(metric, y_score[test_idx], y_pred))
    if not fold_scores:
        return float("nan")
    return float(np.mean(fold_scores))


def run_full_pipeline_permutation_null(
    params: FullPipelinePermutationParameters,
) -> dict[str, Any]:
    """Re-run the full workflow per permutation and emit a trusted probe.

    Wall-time scales with ``n_permutations * cv_folds`` and the cost of the
    workflow itself (which usually includes feature extraction). Keep the
    permutation count modest unless the workflow is cheap or you have spare
    compute; 1000 is the registry default for confirmatory claims.
    """

    workflow_callable = _import_callable(params.workflow_callable_path)

    y = _load_numeric_array(params.y_path).ravel()
    groups = (
        _load_numeric_array(params.groups_path).ravel() if params.groups_path else None
    )

    manifest_path = Path(params.split_manifest_path)
    folds = _load_split_manifest(manifest_path)
    split_manifest_sha = _sha256_file(manifest_path)

    output_dir = Path(params.output_dir)
    probes_dir = output_dir / "review_probes"
    probes_dir.mkdir(parents=True, exist_ok=True)
    observed_dir = output_dir / "observed"
    observed_dir.mkdir(parents=True, exist_ok=True)
    permutations_dir = output_dir / "permutations"
    permutations_dir.mkdir(parents=True, exist_ok=True)

    pipeline_invocation_sha = _pipeline_invocation_sha256(
        params.workflow_callable_path,
        workflow_callable,
        params.workflow_config,
        split_manifest_sha,
    )

    n_permutations = max(1, int(params.n_permutations))
    rng = np.random.default_rng(params.seed)

    observed_metric = _score_workflow_pass(
        workflow_callable,
        y_fit=y,
        y_score=y,
        folds=folds,
        metric=params.metric,
        seed=params.seed,
        workflow_config=params.workflow_config,
        base_output_dir=observed_dir,
        is_observed=True,
    )

    null_values: list[float] = []
    for perm_idx in range(n_permutations):
        y_perm = _shuffle_within_groups(y, groups, rng)
        perm_seed = int(rng.integers(0, np.iinfo(np.int64).max - 1))
        perm_dir = permutations_dir / f"perm-{perm_idx:04d}"
        score = _score_workflow_pass(
            workflow_callable,
            y_fit=y_perm,
            y_score=y,
            folds=folds,
            metric=params.metric,
            seed=perm_seed,
            workflow_config=params.workflow_config,
            base_output_dir=perm_dir,
            is_observed=False,
        )
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

    probe = {
        "status": "ok",
        "n_permutations": int(n_permutations),
        "seed": int(params.seed),
        "pipeline_scope": "full_pipeline",
        "generated_by": _GENERATOR_NAME,
        "input_scope": _INPUT_SCOPE,
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
        "pipeline_invocation_sha256": pipeline_invocation_sha,
        "workflow_callable_path": params.workflow_callable_path,
        "verdict": verdict,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }

    probe_path = probes_dir / "label_permutation_null.json"
    probe_path.write_text(json.dumps(probe, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "outputs": {"label_permutation_null": str(probe_path)},
        "probe": probe,
        "message": "Full-pipeline label-permutation-null harness completed.",
    }


class FullPipelinePermutationHarnessTool(NeuroToolWrapper):
    """Agent-visible entry point for the trusted full-pipeline harness."""

    def get_tool_name(self) -> str:
        return "full_pipeline_permutation_harness"

    def get_tool_description(self) -> str:
        return (
            "Run a trusted full-pipeline label-permutation-null probe by "
            "re-executing an importable workflow callable per permutation. "
            "Emits a review-recognised probe with workflow_invocation "
            "provenance for confirmatory predictive claims."
        )

    def _run(self, **kwargs) -> ToolResult:
        try:
            params = full_pipeline_permutation_from_payload(kwargs)
            result = run_full_pipeline_permutation_null(params)
            return ToolResult(status="success", data=result)
        except Exception as exc:  # pragma: no cover - defensive surface
            return ToolResult(status="error", error=str(exc), data={})


__all__ = [
    "FullPipelinePermutationParameters",
    "full_pipeline_permutation_from_payload",
    "run_full_pipeline_permutation_null",
    "FullPipelinePermutationHarnessTool",
]
