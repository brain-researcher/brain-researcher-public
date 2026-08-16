"""Frozen, selection-aware replay of the historical HCP 100-slot search.

The historical MVE-100 receipts cannot be used as an unbiased model ranking:
their controller saw aggregate outer-fold outcomes while proposing later slots.
This module instead freezes exactly 100 *templates* before model fitting and
evaluates the entire template-and-hyperparameter selector inside grouped nested
cross-validation.  The last 25 percent family-disjoint partition is a
retrospective reused-HCP repartition, not an unseen holdout, an independent
external replication, or evidence for scientific acceptance.

Only ``ICA_Cognition`` is the primary target.  Its supplied local endpoint is
a precomputed age/sex-residualized, rank-IG transformed component projection;
there is intentionally no performance-selected covariate target or PCA branch.
This therefore evaluates a retrospective matched endpoint, not a fold-local
covariate-adjustment estimand.
"""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType

import h5py
import numpy as np
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, ParameterGrid

from brain_researcher.research.predictive.foundation_episode.evaluator import (
    _load_engine as _load_engine_with_isolated_siblings,
)
from brain_researcher.research.predictive.foundation_episode.evaluator import (
    _predict_torch_model as _predict_torch_model,
)
from brain_researcher.research.predictive.foundation_episode.evaluator import (
    _torch_single_split as _torch_single_split,
)

TARGET_NAME = "ICA_Cognition"
ALPHA_GRID = (0.1, 1.0, 10.0, 100.0)
OUTER_FOLDS = 5
INNER_FOLDS = 3
TEST_FRACTION = 0.25
PCA_POLICY = "none"
SUPPORTED_SKLEARN = frozenset(
    {
        "ridge",
        "lasso",
        "kernelridgelinear",
        "kernelridgecosine",
        "elasticnet",
        "pls",
        "lightgbm",
        "xgboost",
        "mlp",
        "svr",
    }
)


class Nested100ReplayError(ValueError):
    """The frozen replay cannot be constructed or evaluated."""


@dataclass(frozen=True, slots=True)
class CandidateTemplate:
    """One frozen model--representation template, before inner tuning."""

    template_id: str
    source: str
    classifier_key: str
    term_index: int


@dataclass(frozen=True, slots=True)
class HCPDataset:
    """Rows/families/features plus either in-memory or lazy endpoint access."""

    subject_ids: tuple[str, ...]
    family_ids: tuple[str, ...]
    target: np.ndarray | None
    term_records: Mapping[int, Mapping[str, object]]
    term_cache_dir: Path
    engine_path: Path
    historical_v2_discovery_indices: tuple[int, ...] = ()
    target_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    """All data-independent choices for this retrospective internal replay."""

    seed: int = 20260809
    test_fraction: float = TEST_FRACTION
    outer_folds: int = OUTER_FOLDS
    inner_folds: int = INNER_FOLDS
    alpha_grid: tuple[float, ...] = ALPHA_GRID
    pca_policy: str = PCA_POLICY
    primary_target: str = TARGET_NAME
    covariate_policy: str = (
        "precomputed_age_sex_residualized_reconstructed_component_fixed"
    )


@dataclass(frozen=True, slots=True)
class SplitPlan:
    """The one retrospective reused-HCP partition and all development folds."""

    development_indices: np.ndarray
    repartition_indices: np.ndarray
    outer_splits: tuple[tuple[np.ndarray, np.ndarray], ...]
    final_inner_splits: tuple[tuple[np.ndarray, np.ndarray], ...]


def _as_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Nested100ReplayError(f"{label} must be an integer")
    return int(value)


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise Nested100ReplayError(f"{label} must be non-empty text")
    return value


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Nested100ReplayError(f"cannot read {label}") from exc
    if not isinstance(payload, dict):
        raise Nested100ReplayError(f"{label} must be a JSON object")
    return payload


def _proposal_from_receipt(receipt: Mapping[str, object]) -> tuple[str, int] | None:
    proposal = receipt.get("proposal")
    if not isinstance(proposal, Mapping):
        return None
    classifier = proposal.get("classifier_key")
    term = proposal.get("term_index")
    if (
        not isinstance(classifier, str)
        or isinstance(term, bool)
        or not isinstance(term, int)
    ):
        return None
    return classifier.lower(), int(term)


def frozen_exact100_templates(
    *,
    v2_bundle: Path,
    recovery_bundle: Path,
) -> tuple[CandidateTemplate, ...]:
    """Recover slots 1--96 plus four fixed unique v1 pairs.

    Failed v2 controller transport slots deliberately remain templates.  Their
    proposals are recovered only from the bounded recovery receipts keyed by
    ``source_slot``; no historical performance value is imported.
    """

    v2_receipts = v2_bundle / "private" / "discovery_receipts"
    recovery_receipts = recovery_bundle / "private" / "recovery_receipts"
    recovered: dict[int, tuple[str, int]] = {}
    for path in sorted(recovery_receipts.glob("recovery_slot_*.json")):
        receipt = _read_json(path, label="recovery receipt")
        source_slot = receipt.get("source_slot")
        proposal = _proposal_from_receipt(receipt)
        if isinstance(source_slot, int) and proposal is not None:
            recovered[source_slot] = proposal

    templates: list[CandidateTemplate] = []
    for slot in range(1, 97):
        receipt = _read_json(
            v2_receipts / f"slot_{slot:02d}.json", label=f"v2 slot {slot}"
        )
        proposal = _proposal_from_receipt(receipt) or recovered.get(slot)
        if proposal is None:
            raise Nested100ReplayError(f"cannot recover proposal for v2 slot {slot}")
        classifier, term = proposal
        templates.append(
            CandidateTemplate(
                template_id=f"v2_slot_{slot:03d}",
                source="v2_slot_proposal",
                classifier_key=classifier,
                term_index=term,
            )
        )

    for classifier, term in (
        ("svr", 3),
        ("ridge", 17),
        ("xgboost", 3),
        ("kernelridgelinear", 3),
    ):
        templates.append(
            CandidateTemplate(
                template_id=f"v1_unique_{classifier}_{term}",
                source="v1_unique_fixed_addition",
                classifier_key=classifier,
                term_index=term,
            )
        )
    if len(templates) != 100 or len({item.template_id for item in templates}) != 100:
        raise AssertionError("exact100 template construction failed")
    return tuple(templates)


def _load_engine(engine_path: Path) -> ModuleType:
    """Use the evaluator's isolated loader for benchmark sibling imports."""

    try:
        return _load_engine_with_isolated_siblings(str(engine_path))
    except Exception as exc:
        raise Nested100ReplayError("cannot load benchmark engine") from exc


def load_hcp_dataset(source_bundle: Path) -> HCPDataset:
    """Load all source rows without importing the historical discovery split."""

    runtime = _read_json(
        source_bundle / "private" / "runtime_inputs.json", label="runtime inputs"
    )
    manifest = _read_json(source_bundle / "input_manifest.json", label="input manifest")
    target_path = Path(
        _text(runtime.get("target_table_path"), label="target table path")
    )
    exchangeability_path = Path(
        _text(
            runtime.get("exchangeability_manifest_path"), label="exchangeability path"
        )
    )
    term_cache_dir = Path(_text(runtime.get("term_cache_dir"), label="term cache path"))
    engine_path = Path(_text(runtime.get("kernel_source_path"), label="engine path"))
    exchangeability = _read_json(exchangeability_path, label="exchangeability manifest")
    raw_subjects = exchangeability.get("subjects")
    if not isinstance(raw_subjects, list):
        raise Nested100ReplayError("exchangeability manifest lacks subjects")
    subject_rows: list[tuple[str, str]] = []
    for row in raw_subjects:
        if not isinstance(row, Mapping):
            raise Nested100ReplayError("exchangeability subject row is malformed")
        subject_rows.append(
            (
                _text(row.get("subject_id"), label="subject ID"),
                _text(row.get("family_id"), label="family ID"),
            )
        )
    if len(subject_rows) != 326 or len({item[0] for item in subject_rows}) != 326:
        raise Nested100ReplayError("expected exactly 326 unique HCP subject rows")

    target_subjects: set[str] = set()
    try:
        with target_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or TARGET_NAME not in reader.fieldnames:
                raise Nested100ReplayError("target table lacks ICA_Cognition")
            for row in reader:
                subject = _text(row.get("Subject"), label="target subject")
                if subject in target_subjects:
                    raise Nested100ReplayError("target table has duplicate subject IDs")
                target_subjects.add(subject)
    except (OSError, csv.Error) as exc:
        raise Nested100ReplayError("cannot read HCP target table") from exc
    subject_ids = tuple(item[0] for item in subject_rows)
    if target_subjects != set(subject_ids):
        raise Nested100ReplayError("target and exchangeability subject IDs differ")

    term_cache = manifest.get("term_cache")
    if not isinstance(term_cache, Mapping) or not isinstance(
        term_cache.get("terms"), list
    ):
        raise Nested100ReplayError("input manifest lacks term cache records")
    records: dict[int, Mapping[str, object]] = {}
    for raw in term_cache["terms"]:
        if not isinstance(raw, Mapping):
            continue
        index = raw.get("term_index")
        if isinstance(index, int):
            records[index] = raw
    historical_split = _read_json(
        source_bundle / "private" / "split_plan.private.json",
        label="historical v2 split plan",
    )
    raw_historical_discovery = historical_split.get("discovery_row_indices")
    if not isinstance(raw_historical_discovery, list):
        raise Nested100ReplayError("historical v2 split plan lacks discovery rows")
    historical_discovery = tuple(
        _as_int(value, label="historical discovery row")
        for value in raw_historical_discovery
    )
    if len(historical_discovery) != 245 or any(
        index < 0 or index >= len(subject_ids) for index in historical_discovery
    ):
        raise Nested100ReplayError("historical v2 discovery rows are invalid")
    return HCPDataset(
        subject_ids=subject_ids,
        family_ids=tuple(item[1] for item in subject_rows),
        target=None,
        term_records=records,
        term_cache_dir=term_cache_dir,
        engine_path=engine_path,
        historical_v2_discovery_indices=historical_discovery,
        target_path=target_path,
    )


def _targets_for_indices(dataset: HCPDataset, indices: np.ndarray) -> np.ndarray:
    """Read numeric endpoint values only for the explicitly requested rows.

    The real source table is scanned for identity alignment, but values outside
    ``indices`` are intentionally never parsed as floats.  This permits the
    development phase to remain blind to the retrospective repartition values.
    """

    normalized = np.asarray(indices, dtype=np.int64)
    if normalized.ndim != 1 or len(normalized) == 0:
        raise Nested100ReplayError("target access indices must be a non-empty vector")
    if np.any(normalized < 0) or np.any(normalized >= len(dataset.subject_ids)):
        raise Nested100ReplayError("target access indices are out of range")
    if len(set(normalized.tolist())) != len(normalized):
        raise Nested100ReplayError("target access indices must be unique")
    if dataset.target is not None:
        target = np.asarray(dataset.target, dtype=np.float64)
        if target.shape != (len(dataset.subject_ids),) or not np.all(
            np.isfinite(target)
        ):
            raise Nested100ReplayError(
                "in-memory target does not align to subject rows"
            )
        return np.array(target[normalized], dtype=np.float64, copy=True)
    if dataset.target_path is None:
        raise Nested100ReplayError(
            "dataset has neither in-memory nor lazy target access"
        )
    wanted = {dataset.subject_ids[int(index)] for index in normalized}
    values: dict[str, float] = {}
    try:
        with dataset.target_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or TARGET_NAME not in reader.fieldnames:
                raise Nested100ReplayError("target table lacks ICA_Cognition")
            for row in reader:
                subject = _text(row.get("Subject"), label="target subject")
                if subject not in wanted:
                    continue
                value = float(row[TARGET_NAME])
                if not math.isfinite(value) or subject in values:
                    raise Nested100ReplayError("requested target values are invalid")
                values[subject] = value
    except (OSError, csv.Error, ValueError) as exc:
        raise Nested100ReplayError("cannot read requested HCP target values") from exc
    if set(values) != wanted:
        raise Nested100ReplayError("target table lacks one or more requested rows")
    return np.asarray(
        [values[dataset.subject_ids[int(index)]] for index in normalized],
        dtype=np.float64,
    )


class _FeatureLoader:
    def __init__(self, dataset: HCPDataset) -> None:
        self.dataset = dataset
        self._cache: dict[int, np.ndarray] = {}

    def matrix(self, term_index: int) -> np.ndarray:
        cached = self._cache.get(term_index)
        if cached is not None:
            return cached
        record = self.dataset.term_records.get(term_index)
        if not isinstance(record, Mapping):
            raise Nested100ReplayError(
                f"term {term_index} is absent from source term cache"
            )
        filename = _text(record.get("file"), label="term filename")
        dataset_name = _text(record.get("dataset"), label="term dataset")
        path = self.dataset.term_cache_dir / filename
        try:
            with h5py.File(path, "r") as handle:
                matrix = np.asarray(handle[dataset_name][:], dtype=np.float64)
        except (OSError, KeyError, ValueError) as exc:
            raise Nested100ReplayError(f"cannot load term {term_index}") from exc
        if matrix.shape[0] != len(self.dataset.subject_ids) or matrix.ndim != 2:
            raise Nested100ReplayError(f"term {term_index} does not align to HCP rows")
        self._cache[term_index] = matrix
        return matrix


def build_split_plan(dataset: HCPDataset, config: ReplayConfig) -> SplitPlan:
    """Freeze one group-disjoint retrospective repartition before fitting models."""

    groups = np.asarray(dataset.family_ids, dtype=str)
    indices = np.arange(len(dataset.subject_ids), dtype=np.int64)
    splitter = GroupShuffleSplit(
        n_splits=1, test_size=config.test_fraction, random_state=config.seed
    )
    development, repartition = next(splitter.split(indices, groups=groups))
    development = np.asarray(development, dtype=np.int64)
    repartition = np.asarray(repartition, dtype=np.int64)
    if set(groups[development]) & set(groups[repartition]):
        raise Nested100ReplayError(
            "family appears in both development and retrospective repartition"
        )

    outer_splits: list[tuple[np.ndarray, np.ndarray]] = []
    outer_group_kfold = GroupKFold(n_splits=config.outer_folds)
    for outer_train_local, outer_test_local in outer_group_kfold.split(
        development, groups=groups[development]
    ):
        outer_train = development[np.asarray(outer_train_local, dtype=np.int64)]
        outer_test = development[np.asarray(outer_test_local, dtype=np.int64)]
        outer_splits.append((outer_train, outer_test))
    final_inner_splits: list[tuple[np.ndarray, np.ndarray]] = []
    final_kfold = GroupKFold(n_splits=config.inner_folds)
    for train_local, validation_local in final_kfold.split(
        development, groups=groups[development]
    ):
        final_inner_splits.append(
            (
                development[np.asarray(train_local, dtype=np.int64)],
                development[np.asarray(validation_local, dtype=np.int64)],
            )
        )
    return SplitPlan(
        development_indices=development,
        repartition_indices=repartition,
        outer_splits=tuple(outer_splits),
        final_inner_splits=tuple(final_inner_splits),
    )


def _pearson(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_true) == 0.0 or np.std(y_pred) == 0.0:
        return float("nan")
    return float(np.corrcoef(y_true, y_pred)[0, 1])


def _calibration_slope(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denominator = float(np.dot(y_pred - y_pred.mean(), y_pred - y_pred.mean()))
    if denominator == 0.0:
        return float("nan")
    return float(np.dot(y_pred - y_pred.mean(), y_true - y_true.mean()) / denominator)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | None]:
    values = {
        "signed_pearson_r": _pearson(y_true, y_pred),
        "r2": float(r2_score(y_true, y_pred)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "calibration_slope": _calibration_slope(y_true, y_pred),
    }
    return {
        key: (value if math.isfinite(value) else None) for key, value in values.items()
    }


def _inner_group_splits(
    outer_train: np.ndarray, groups: np.ndarray, n_splits: int
) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    kfold = GroupKFold(n_splits=n_splits)
    result: list[tuple[np.ndarray, np.ndarray]] = []
    for train_local, validation_local in kfold.split(
        outer_train, groups=groups[outer_train]
    ):
        result.append(
            (
                outer_train[np.asarray(train_local, dtype=np.int64)],
                outer_train[np.asarray(validation_local, dtype=np.int64)],
            )
        )
    return tuple(result)


def _sklearn_parameter_grid(
    module: ModuleType,
    classifier_key: str,
    *,
    alpha_grid: Sequence[float],
    seed: int,
    n_train: int,
    n_features: int,
) -> tuple[object, list[dict[str, object]]]:
    factory = getattr(module, "_build_estimator", None)
    if not callable(factory):
        raise Nested100ReplayError("benchmark engine does not expose _build_estimator")
    estimator, raw_grid = factory(
        classifier_key,
        tuple(alpha_grid),
        seed,
        n_train_samples=n_train,
        n_features=n_features,
    )
    return estimator, list(ParameterGrid(raw_grid)) or [{}]


def _cpm_predict(
    module: ModuleType,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_eval: np.ndarray,
    top_k: int,
) -> np.ndarray:
    kernel = getattr(module, "_fit_cpm_fold", None)
    if not callable(kernel):
        raise Nested100ReplayError("benchmark engine does not expose CPM kernel")
    _, prediction, _ = kernel(
        X_train=X_train, y_train=y_train, X_eval=X_eval, top_k=top_k
    )
    return np.asarray(prediction, dtype=np.float64).reshape(-1)


def _score_template_on_inner(
    *,
    module: ModuleType,
    template: CandidateTemplate,
    X: np.ndarray,
    y: np.ndarray,
    inner_splits: Sequence[tuple[np.ndarray, np.ndarray]],
    seed: int,
    alpha_grid: Sequence[float] = ALPHA_GRID,
) -> dict[str, object]:
    """Select candidate hyperparameters using only development inner labels."""

    classifier = template.classifier_key
    try:
        if classifier == "cpm":
            parameter_rows = [
                {"top_k": int(value)}
                for value in getattr(module, "DEFAULT_CPM_TOPK_GRID", (25, 100, 400))
            ]
            kind = "cpm"
        elif classifier in SUPPORTED_SKLEARN:
            estimator, parameter_rows = _sklearn_parameter_grid(
                module,
                classifier,
                alpha_grid=alpha_grid,
                seed=seed,
                n_train=sum(len(train) for train, _ in inner_splits)
                // len(inner_splits),
                n_features=X.shape[1],
            )
            kind = "sklearn"
        elif classifier in frozenset(getattr(module, "MATRIX_ONLY_CLASSIFIERS", ())):
            candidates_fn = getattr(module, "_torch_matrix_model_candidates", None)
            if not callable(candidates_fn):
                raise Nested100ReplayError(
                    "benchmark engine lacks torch candidate factory"
                )
            parameter_rows = [dict(item) for item in candidates_fn(classifier)]
            if not parameter_rows:
                raise Nested100ReplayError(
                    "torch classifier has no inner configurations"
                )
            kind = "torch"
        else:
            return {
                "status": "unavailable",
                "template_id": template.template_id,
                "reason": f"{classifier} has no standard sklearn/CPM selector in this replay",
            }
        best: dict[str, object] | None = None
        all_rows: list[dict[str, object]] = []
        for params in parameter_rows:
            fold_scores: list[float] = []
            failed: str | None = None
            for inner_index, (train, validation) in enumerate(inner_splits, start=1):
                try:
                    if kind == "cpm":
                        pred = _cpm_predict(
                            module,
                            X[train],
                            y[train],
                            X[validation],
                            int(params["top_k"]),
                        )
                    elif kind == "torch":
                        fitted = _torch_single_split(
                            module=module,
                            classifier_key=classifier,
                            X_train=X[train],
                            y_train=y[train],
                            X_validation=X[validation],
                            y_validation=y[validation],
                            config=params,
                            seed=seed + inner_index,
                        )
                        pred = np.asarray(
                            fitted["val_predictions"], dtype=np.float64
                        ).reshape(-1)
                    else:
                        fitted = clone(estimator)
                        fitted.set_params(**params)
                        fitted.fit(X[train], y[train])
                        pred = np.asarray(
                            fitted.predict(X[validation]), dtype=np.float64
                        ).reshape(-1)
                    score = _pearson(y[validation], pred)
                    if not math.isfinite(score):
                        raise Nested100ReplayError("inner Pearson r is non-finite")
                    fold_scores.append(score)
                except (
                    Exception
                ) as exc:  # template failure must not stop other templates
                    failed = f"{type(exc).__name__}: {exc}"
                    break
            mean_score = float(np.mean(fold_scores)) if failed is None else None
            row = {
                "params": dict(params),
                "fold_signed_pearson_r": fold_scores,
                "mean_signed_pearson_r": mean_score,
                "error": failed,
            }
            all_rows.append(row)
            if mean_score is not None and (
                best is None or mean_score > float(best["mean_signed_pearson_r"])
            ):
                best = row
        if best is None:
            return {
                "status": "failed",
                "template_id": template.template_id,
                "reason": "all inner parameter fits failed",
                "parameter_rows": all_rows,
            }
        return {
            "status": "selected",
            "template_id": template.template_id,
            "classifier_key": classifier,
            "term_index": template.term_index,
            "selected_params": best["params"],
            "mean_signed_pearson_r": best["mean_signed_pearson_r"],
            "parameter_rows": all_rows,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "template_id": template.template_id,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def _fit_selected_and_predict(
    *,
    module: ModuleType,
    template: CandidateTemplate,
    params: Mapping[str, object],
    X: np.ndarray,
    y_train: np.ndarray,
    train_indices: np.ndarray,
    evaluation_indices: np.ndarray,
    seed: int,
    alpha_grid: Sequence[float] = ALPHA_GRID,
) -> np.ndarray:
    """Fit only the already selected template on training labels and predict X."""

    if template.classifier_key == "cpm":
        return _cpm_predict(
            module,
            X[train_indices],
            y_train,
            X[evaluation_indices],
            int(params["top_k"]),
        )
    if template.classifier_key in frozenset(
        getattr(module, "MATRIX_ONLY_CLASSIFIERS", ())
    ):
        # The historical torch kernels require validation labels to decide their
        # own checkpoint.  Reuse outer-training rows for that self-monitoring
        # pass rather than pass any held-out outer/internal-test label.
        fitted = _torch_single_split(
            module=module,
            classifier_key=template.classifier_key,
            X_train=X[train_indices],
            y_train=y_train,
            X_validation=X[train_indices],
            y_validation=y_train,
            config=params,
            seed=seed,
        )
        return _predict_torch_model(
            module=module,
            classifier_key=template.classifier_key,
            result=fitted,
            X_fit=X[train_indices],
            y_fit=y_train,
            X_test=X[evaluation_indices],
        )
    if template.classifier_key not in SUPPORTED_SKLEARN:
        raise Nested100ReplayError(
            f"unavailable selected classifier {template.classifier_key}"
        )
    estimator, _ = _sklearn_parameter_grid(
        module,
        template.classifier_key,
        alpha_grid=alpha_grid,
        seed=seed,
        n_train=len(train_indices),
        n_features=X.shape[1],
    )
    fitted = clone(estimator)
    fitted.set_params(**params)
    fitted.fit(X[train_indices], y_train)
    prediction = np.asarray(
        fitted.predict(X[evaluation_indices]), dtype=np.float64
    ).reshape(-1)
    if prediction.shape != (len(evaluation_indices),) or not np.all(
        np.isfinite(prediction)
    ):
        raise Nested100ReplayError("selected estimator returned invalid predictions")
    return prediction


def _winner(rows: Sequence[Mapping[str, object]]) -> Mapping[str, object] | None:
    selected = [row for row in rows if row.get("status") == "selected"]
    if not selected:
        return None
    return max(
        selected,
        key=lambda row: (float(row["mean_signed_pearson_r"]), str(row["template_id"])),
    )


def _require_complete_inner_selection(
    *,
    rows: Sequence[Mapping[str, object]],
    templates: Sequence[CandidateTemplate],
    stage: str,
) -> int:
    """Fail before any repartition label is read if one template did not fit."""

    statuses = {
        row.get("template_id"): row.get("status")
        for row in rows
        if isinstance(row.get("template_id"), str)
    }
    incomplete = [
        template.template_id
        for template in templates
        if statuses.get(template.template_id) != "selected"
    ]
    if incomplete:
        raise Nested100ReplayError(
            f"{stage} did not select every frozen template: {', '.join(incomplete)}"
        )
    return len(templates)


def _template_lookup(
    templates: Sequence[CandidateTemplate],
) -> dict[str, CandidateTemplate]:
    return {template.template_id: template for template in templates}


def locked_term116_linear_family_baseline_templates() -> tuple[CandidateTemplate, ...]:
    """Predeclared fixed term-116 model family, not a Liu comparator."""

    return tuple(
        CandidateTemplate(
            template_id=f"locked_term116_linear_family_baseline_{classifier}",
            source="locked_term116_linear_family_baseline",
            classifier_key=classifier,
            term_index=116,
        )
        for classifier in (
            "kernelridgelinear",
            "kernelridgecosine",
            "ridge",
            "lasso",
        )
    )


def _mean_metric(
    fold_metrics: Sequence[Mapping[str, float | None]], key: str
) -> float | None:
    values = [float(item[key]) for item in fold_metrics if item.get(key) is not None]
    return float(np.mean(values)) if values else None


def _run_selector_procedure(
    *,
    procedure_label: str,
    dataset: HCPDataset,
    development_target: np.ndarray,
    templates: Sequence[CandidateTemplate],
    config: ReplayConfig,
    split_plan: SplitPlan,
    module: ModuleType,
    loader: _FeatureLoader,
) -> dict[str, object]:
    """Evaluate one predeclared inner-selected procedure on a shared split."""

    template_by_id = _template_lookup(templates)
    groups = np.asarray(dataset.family_ids, dtype=str)
    y = np.asarray(development_target, dtype=np.float64)
    if y.shape != (len(dataset.subject_ids),):
        raise Nested100ReplayError("development target does not align to HCP rows")
    if not np.all(np.isfinite(y[split_plan.development_indices])):
        raise Nested100ReplayError("development target values are not finite")
    outer_records: list[dict[str, object]] = []
    selector_predictions: list[tuple[np.ndarray, np.ndarray]] = []

    for outer_index, (outer_train, outer_test) in enumerate(
        split_plan.outer_splits, start=1
    ):
        inner_splits = _inner_group_splits(outer_train, groups, config.inner_folds)
        inner_rows: list[dict[str, object]] = []
        for template_index, template in enumerate(templates, start=1):
            X = loader.matrix(template.term_index)
            inner_rows.append(
                _score_template_on_inner(
                    module=module,
                    template=template,
                    X=X,
                    y=y,
                    inner_splits=inner_splits,
                    seed=config.seed + outer_index * 10_000 + template_index,
                    alpha_grid=config.alpha_grid,
                )
            )
        successful_inner_count = _require_complete_inner_selection(
            rows=inner_rows,
            templates=templates,
            stage=f"{procedure_label} outer fold {outer_index}",
        )
        winner = _winner(inner_rows)
        assert winner is not None
        chosen = template_by_id[str(winner["template_id"])]
        prediction = _fit_selected_and_predict(
            module=module,
            template=chosen,
            params=winner["selected_params"],
            X=loader.matrix(chosen.term_index),
            y_train=y[outer_train],
            train_indices=outer_train,
            evaluation_indices=outer_test,
            seed=config.seed + outer_index,
            alpha_grid=config.alpha_grid,
        )
        selector_predictions.append((outer_test, prediction))
        outer_records.append(
            {
                "outer_fold": outer_index,
                "status": "succeeded",
                "selected_template_id": chosen.template_id,
                "selected_classifier_key": chosen.classifier_key,
                "selected_term_index": chosen.term_index,
                "selected_params": winner["selected_params"],
                "inner_candidate_success_count": successful_inner_count,
                "inner_candidates": inner_rows,
                "outer_metrics": _metrics(y[outer_test], prediction),
                "outer_test_indices": outer_test.tolist(),
                "outer_y_true": y[outer_test].tolist(),
                "outer_y_pred": prediction.tolist(),
            }
        )

    if len(selector_predictions) != config.outer_folds:
        raise Nested100ReplayError(
            f"{procedure_label} has incomplete outer selector folds"
        )
    ordered_outer_indices = np.concatenate(
        [indices for indices, _ in selector_predictions]
    )
    ordered_outer_predictions = np.concatenate(
        [prediction for _, prediction in selector_predictions]
    )
    fold_metrics = [
        _metrics(y[indices], prediction) for indices, prediction in selector_predictions
    ]
    selector_metrics = {
        "mean_fold_signed_pearson_r": _mean_metric(fold_metrics, "signed_pearson_r"),
        "mean_fold_r2": _mean_metric(fold_metrics, "r2"),
        "mean_fold_mae": _mean_metric(fold_metrics, "mae"),
        "mean_fold_calibration_slope": _mean_metric(fold_metrics, "calibration_slope"),
        "pooled_oof_signed_pearson_r": _pearson(
            y[ordered_outer_indices], ordered_outer_predictions
        ),
        "pooled_oof_r2": float(
            r2_score(y[ordered_outer_indices], ordered_outer_predictions)
        ),
        "pooled_oof_mae": float(
            mean_absolute_error(y[ordered_outer_indices], ordered_outer_predictions)
        ),
        "pooled_oof_calibration_slope": _calibration_slope(
            y[ordered_outer_indices], ordered_outer_predictions
        ),
    }

    final_rows: list[dict[str, object]] = []
    for template_index, template in enumerate(templates, start=1):
        final_rows.append(
            _score_template_on_inner(
                module=module,
                template=template,
                X=loader.matrix(template.term_index),
                y=y,
                inner_splits=split_plan.final_inner_splits,
                seed=config.seed + 1_000_000 + template_index,
                alpha_grid=config.alpha_grid,
            )
        )
    final_successful_inner_count = _require_complete_inner_selection(
        rows=final_rows,
        templates=templates,
        stage=f"{procedure_label} final development selection",
    )
    final_winner = _winner(final_rows)
    assert final_winner is not None
    final_template = template_by_id[str(final_winner["template_id"])]
    # This is the sole retrospective-repartition prediction step for this
    # predeclared procedure.  Do not index repartition y here: the top-level
    # caller locks both procedures before the one same-run scoring step.
    repartition_prediction = _fit_selected_and_predict(
        module=module,
        template=final_template,
        params=final_winner["selected_params"],
        X=loader.matrix(final_template.term_index),
        y_train=y[split_plan.development_indices],
        train_indices=split_plan.development_indices,
        evaluation_indices=split_plan.repartition_indices,
        seed=config.seed + 2_000_000,
        alpha_grid=config.alpha_grid,
    )
    winner_counts: dict[str, int] = {}
    for record in outer_records:
        template_id = record.get("selected_template_id")
        if isinstance(template_id, str):
            winner_counts[template_id] = winner_counts.get(template_id, 0) + 1
    return {
        "procedure_label": procedure_label,
        "template_count": len(templates),
        "templates": [asdict(item) for item in templates],
        "outer_selector_evaluation": {
            "metrics": selector_metrics,
            "winner_frequency": winner_counts,
            "folds": outer_records,
        },
        "final_development_selection": {
            "selected_template_id": final_template.template_id,
            "selected_classifier_key": final_template.classifier_key,
            "selected_term_index": final_template.term_index,
            "selected_params": final_winner["selected_params"],
            "inner_candidate_success_count": final_successful_inner_count,
            "all_inner_candidate_rows": final_rows,
        },
        "locked_retrospective_repartition_prediction": {
            "subject_indices": split_plan.repartition_indices.tolist(),
            "y_pred": repartition_prediction.tolist(),
        },
    }


def run_frozen_nested100_replay(
    *,
    dataset: HCPDataset,
    templates: Sequence[CandidateTemplate],
    config: ReplayConfig = ReplayConfig(),
) -> dict[str, object]:
    """Evaluate two frozen procedures, then score one retrospective repartition."""

    if len(templates) != 100 or len({item.template_id for item in templates}) != 100:
        raise Nested100ReplayError(
            "replay requires exactly 100 uniquely identified templates"
        )
    if config.primary_target != TARGET_NAME or config.pca_policy != PCA_POLICY:
        raise Nested100ReplayError(
            "this replay freezes ICA_Cognition and PCA policy none"
        )
    split_plan = build_split_plan(dataset, config)
    module = _load_engine(dataset.engine_path)
    loader = _FeatureLoader(dataset)
    groups = np.asarray(dataset.family_ids, dtype=str)
    # The development target vector is the only endpoint data available while
    # either selector is fitted.  It deliberately contains no numeric values
    # for the retrospective partition, whose labels are accessed exactly once
    # below after both frozen procedures have locked their final models.
    development_target = np.full(len(dataset.subject_ids), np.nan, dtype=np.float64)
    development_target[split_plan.development_indices] = _targets_for_indices(
        dataset, split_plan.development_indices
    )
    selector = _run_selector_procedure(
        procedure_label="frozen_100_candidate_selector",
        dataset=dataset,
        development_target=development_target,
        templates=templates,
        config=config,
        split_plan=split_plan,
        module=module,
        loader=loader,
    )
    baseline = _run_selector_procedure(
        procedure_label="locked_term116_linear_family_baseline",
        dataset=dataset,
        development_target=development_target,
        templates=locked_term116_linear_family_baseline_templates(),
        config=config,
        split_plan=split_plan,
        module=module,
        loader=loader,
    )
    # Both procedures and all parameters are now locked using development data
    # only.  This is one retrospective same-run repartition scoring event, not
    # an unbiased unseen-test disclosure.
    repartition_y = _targets_for_indices(dataset, split_plan.repartition_indices)
    for procedure in (selector, baseline):
        locked = procedure.pop("locked_retrospective_repartition_prediction")
        assert isinstance(locked, Mapping)
        prediction = np.asarray(locked["y_pred"], dtype=np.float64)
        procedure["retrospective_reused_hcp_repartition"] = {
            "subject_indices": list(locked["subject_indices"]),
            "y_true": repartition_y.tolist(),
            "y_pred": prediction.tolist(),
            "metrics": _metrics(repartition_y, prediction),
        }
    selector_folds = selector["outer_selector_evaluation"]["folds"]
    baseline_folds = baseline["outer_selector_evaluation"]["folds"]
    paired_outer_delta_r = [
        float(left["outer_metrics"]["signed_pearson_r"])
        - float(right["outer_metrics"]["signed_pearson_r"])
        for left, right in zip(selector_folds, baseline_folds, strict=True)
    ]
    selector_repartition = selector["retrospective_reused_hcp_repartition"]["metrics"]
    baseline_repartition = baseline["retrospective_reused_hcp_repartition"]["metrics"]
    selector_outer_metrics = selector["outer_selector_evaluation"]["metrics"]
    baseline_outer_metrics = baseline["outer_selector_evaluation"]["metrics"]
    historical_v2_discovery = set(dataset.historical_v2_discovery_indices)
    historical_development_overlap = len(
        set(split_plan.development_indices.tolist()) & historical_v2_discovery
    )
    historical_repartition_overlap = len(
        set(split_plan.repartition_indices.tolist()) & historical_v2_discovery
    )
    historical_outer_evaluation_overlap = [
        {
            "outer_fold": outer_fold,
            "historical_v2_discovery_rows": len(
                set(outer_test.tolist()) & historical_v2_discovery
            ),
        }
        for outer_fold, (_, outer_test) in enumerate(split_plan.outer_splits, start=1)
    ]

    def delta(left: object, right: object) -> float | None:
        if left is None or right is None:
            return None
        return float(left) - float(right)

    return {
        "schema_version": "br.hcp_nested100_replay.v1",
        "analysis_label": "frozen_100_candidate_selector_selection_aware_HCP_retrospective_repartition",
        "claim_boundary": {
            "retrospective_reused_hcp_repartition_status": "repartition_of_previously_reused_HCP_rows_not_unseen_holdout",
            "retrospective_repartition_is_unbiased": False,
            "historical_candidate_panel_outcome_informed": True,
            "outer_nested_cv_unbiased_for_historical_search": False,
            "selection_adjusted_within_replay_only": True,
            "external_replication": False,
            "scientific_acceptance": False,
            "liu_comparator": "not_a_Liu_comparator",
            "liu_superiority_claim": False,
            "target_construction": "precomputed_age_sex_residualized_rank_IG_component_projection_not_fold_local",
        },
        "config": asdict(config),
        "split": {
            "development_indices": split_plan.development_indices.tolist(),
            "retrospective_repartition_indices": split_plan.repartition_indices.tolist(),
            "development_subject_count": int(len(split_plan.development_indices)),
            "retrospective_repartition_subject_count": int(
                len(split_plan.repartition_indices)
            ),
            "outer_fold_count": len(split_plan.outer_splits),
            "historical_v2_discovery_rows_in_development": historical_development_overlap,
            "historical_v2_discovery_rows_in_repartition": historical_repartition_overlap,
            "historical_v2_discovery_rows_in_outer_evaluation_folds": historical_outer_evaluation_overlap,
            "development_family_count": int(
                len(set(groups[split_plan.development_indices]))
            ),
            "retrospective_repartition_family_count": int(
                len(set(groups[split_plan.repartition_indices]))
            ),
        },
        "frozen_100_selector": selector,
        "locked_term116_linear_family_baseline": baseline,
        "retrospective_partition_once": {
            "subject_indices": split_plan.repartition_indices.tolist(),
            "atomic_predeclared_procedures": [
                "frozen_100_candidate_selector",
                "locked_term116_linear_family_baseline",
            ],
            "status": "retrospective_reused_HCP_repartition_not_unseen_holdout",
            "frozen_100_selector": selector["retrospective_reused_hcp_repartition"],
            "locked_term116_linear_family_baseline": baseline[
                "retrospective_reused_hcp_repartition"
            ],
            "paired_delta_signed_pearson_r": {
                "outer_fold_values": paired_outer_delta_r,
                "mean_outer_delta": float(np.mean(paired_outer_delta_r)),
                "pooled_oof_delta": delta(
                    selector_outer_metrics["pooled_oof_signed_pearson_r"],
                    baseline_outer_metrics["pooled_oof_signed_pearson_r"],
                ),
                "retrospective_repartition": {
                    "signed_pearson_r": delta(
                        selector_repartition["signed_pearson_r"],
                        baseline_repartition["signed_pearson_r"],
                    ),
                    "r2": delta(selector_repartition["r2"], baseline_repartition["r2"]),
                    "mae": delta(
                        selector_repartition["mae"], baseline_repartition["mae"]
                    ),
                    "calibration_slope": delta(
                        selector_repartition["calibration_slope"],
                        baseline_repartition["calibration_slope"],
                    ),
                },
            },
        },
    }


def write_replay_result(output_dir: Path, result: Mapping[str, object]) -> Path:
    """Persist a new result directory without altering historical episodes."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    result_path = output_dir / "nested100_result.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".nested100_result.", dir=output_dir
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        temporary.replace(result_path)
    finally:
        temporary.unlink(missing_ok=True)
    return result_path


__all__ = [
    "CandidateTemplate",
    "HCPDataset",
    "Nested100ReplayError",
    "ReplayConfig",
    "build_split_plan",
    "frozen_exact100_templates",
    "locked_term116_linear_family_baseline_templates",
    "load_hcp_dataset",
    "run_frozen_nested100_replay",
    "write_replay_result",
]
