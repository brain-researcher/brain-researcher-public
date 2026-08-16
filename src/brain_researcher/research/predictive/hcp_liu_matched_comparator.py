"""Frozen Liu-style comparator on the nested-100 retrospective HCP split.

The primary procedure begins with the 76-term clean common-support cache, then
freezes a target-blind development-feature eligibility screen using Liu's
``max(abs(finite QCoD)) >= 0.01`` rule.  The resulting 74-term panel is
evaluated under four Liu-style model families and an explicit alpha grid.  It
reuses the authoritative nested100 244/82 partition, endpoint construction,
covariate policy, and metrics.  Term-0 ``cov_EmpiricalCovariance`` is retained
only as a secondary anchor, not as the primary comparison.

This is a matched, retrospective same-cohort comparator.  It is neither an
exact reproduction of the original Liu paper nor fresh held-out evidence.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Lasso, Ridge
from sklearn.metrics import r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from brain_researcher.research.predictive import hcp_nested100_replay as replay

TARGET_NAME = replay.TARGET_NAME
TERM0_INDEX = 0
TERM0_LABEL = "cov_EmpiricalCovariance"
COMMON_SUPPORT_TERM_INDICES = (
    0,
    1,
    3,
    4,
    5,
    8,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    29,
    31,
    32,
    33,
    34,
    35,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    54,
    55,
    56,
    57,
    58,
    60,
    61,
    62,
    63,
    74,
    75,
    76,
    77,
    78,
    79,
    80,
    81,
    83,
    84,
    116,
    117,
    118,
    119,
    120,
    121,
    132,
    133,
    134,
    137,
    138,
    141,
    142,
    143,
    145,
    218,
    219,
    220,
    221,
)
EXPECTED_DEGENERATE_COMMON_SUPPORT_TERM_INDICES = (141, 145)
MODEL_FAMILIES = ("kernelridgelinear", "kernelridgecosine", "ridge", "lasso")
ALPHA_GRID = (0.1, 1.0, 10.0, 100.0)
QCOD_BAND = (10.0, 90.0)


class LiuMatchedComparatorError(ValueError):
    """The frozen Liu-style comparator cannot be constructed or evaluated."""


def _qcod_values(matrix: np.ndarray) -> np.ndarray:
    q1, q3 = np.nanpercentile(matrix, [25.0, 75.0], axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return ((q3 - q1) / 2.0) / ((q1 + q3) / 2.0)


class _QCoDMiddleBand(BaseEstimator, TransformerMixin):
    """Fit the QCoD [10, 90] feature mask on a training matrix only."""

    def __init__(self, low_percentile: float = 10.0, high_percentile: float = 90.0):
        self.low_percentile = low_percentile
        self.high_percentile = high_percentile

    def fit(self, X: np.ndarray, y: object = None) -> _QCoDMiddleBand:
        del y
        matrix = _matrix(X, label="QCoD training matrix")
        qcod = _qcod_values(matrix)
        if not np.any(np.isfinite(qcod)):
            raise LiuMatchedComparatorError("QCoD screen has no finite feature statistics")
        finite_qcod = qcod[np.isfinite(qcod)]
        if float(np.max(np.abs(finite_qcod))) < 0.01:
            raise LiuMatchedComparatorError(
                "QCoD screen is degenerate under Liu's 0.01 eligibility rule"
            )
        low, high = np.percentile(
            finite_qcod, [self.low_percentile, self.high_percentile]
        )
        if not math.isfinite(float(low)) or not math.isfinite(float(high)):
            raise LiuMatchedComparatorError("QCoD percentile thresholds are non-finite")
        selected = np.flatnonzero(
            np.isfinite(qcod) & (qcod >= low) & (qcod <= high)
        ).astype(np.int64, copy=False)
        if selected.size == 0:
            raise LiuMatchedComparatorError("QCoD screen selected zero features")
        self.feature_indices_ = selected
        self.n_features_in_ = matrix.shape[1]
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if not hasattr(self, "feature_indices_") or not hasattr(self, "n_features_in_"):
            raise LiuMatchedComparatorError("QCoD screen must be fitted before transform")
        matrix = _matrix(X, label="QCoD evaluation matrix")
        if matrix.shape[1] != self.n_features_in_:
            raise LiuMatchedComparatorError("QCoD evaluation matrix has incompatible features")
        return matrix[:, self.feature_indices_]


def _matrix(value: object, *, label: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise LiuMatchedComparatorError(f"{label} must be a non-empty 2D matrix")
    if not np.all(np.isfinite(matrix)):
        raise LiuMatchedComparatorError(f"{label} must contain only finite values")
    return matrix


def _required_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LiuMatchedComparatorError(f"{label} must be an object")
    return value


def _required_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiuMatchedComparatorError(f"{label} must be an integer")
    return int(value)


def _required_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise LiuMatchedComparatorError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise LiuMatchedComparatorError(f"{label} must be finite")
    return normalized


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise LiuMatchedComparatorError(f"{label} must be non-empty text")
    return value


def _indices(value: object, *, label: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise LiuMatchedComparatorError(f"{label} must be a list")
    normalized = tuple(_required_int(item, label=label) for item in value)
    if not normalized or len(set(normalized)) != len(normalized):
        raise LiuMatchedComparatorError(f"{label} must contain unique indices")
    return normalized


def _reference_config(reference: Mapping[str, object]) -> replay.ReplayConfig:
    config = _required_mapping(reference.get("config"), label="nested100 config")
    alpha_values = config.get("alpha_grid")
    if not isinstance(alpha_values, list):
        raise LiuMatchedComparatorError("nested100 alpha grid must be a list")
    alpha_grid = tuple(
        _required_float(item, label="nested100 alpha grid value")
        for item in alpha_values
    )
    if alpha_grid != ALPHA_GRID:
        raise LiuMatchedComparatorError("nested100 alpha grid does not match frozen replay")
    replay_config = replay.ReplayConfig(
        seed=_required_int(config.get("seed"), label="nested100 seed"),
        test_fraction=_required_float(
            config.get("test_fraction"), label="nested100 test fraction"
        ),
        outer_folds=_required_int(
            config.get("outer_folds"), label="nested100 outer folds"
        ),
        inner_folds=_required_int(
            config.get("inner_folds"), label="nested100 inner folds"
        ),
        alpha_grid=alpha_grid,
        pca_policy=_required_text(
            config.get("pca_policy"), label="nested100 PCA policy"
        ),
        primary_target=_required_text(
            config.get("primary_target"), label="nested100 primary target"
        ),
        covariate_policy=_required_text(
            config.get("covariate_policy"), label="nested100 covariate policy"
        ),
    )
    if (
        replay_config.primary_target != TARGET_NAME
        or replay_config.pca_policy != replay.PCA_POLICY
        or replay_config.test_fraction != replay.TEST_FRACTION
        or replay_config.covariate_policy != replay.ReplayConfig().covariate_policy
    ):
        raise LiuMatchedComparatorError(
            "matched comparator requires the frozen nested100 endpoint and preprocessing"
        )
    if (
        replay_config.outer_folds != replay.OUTER_FOLDS
        or replay_config.inner_folds != replay.INNER_FOLDS
    ):
        raise LiuMatchedComparatorError("matched comparator requires nested100 5x3 CV")
    return replay_config


def _assert_reference_split(
    *,
    dataset: replay.HCPDataset,
    config: replay.ReplayConfig,
    reference: Mapping[str, object],
) -> replay.SplitPlan:
    split = _required_mapping(reference.get("split"), label="nested100 split")
    expected_development = _indices(
        split.get("development_indices"), label="nested100 development indices"
    )
    expected_repartition = _indices(
        split.get("retrospective_repartition_indices"),
        label="nested100 retrospective repartition indices",
    )
    if len(expected_development) != 244 or len(expected_repartition) != 82:
        raise LiuMatchedComparatorError(
            "matched comparator requires the frozen nested100 244/82 split"
        )
    plan = replay.build_split_plan(dataset, config)
    if tuple(plan.development_indices.tolist()) != expected_development:
        raise LiuMatchedComparatorError("development split differs from nested100 reference")
    if tuple(plan.repartition_indices.tolist()) != expected_repartition:
        raise LiuMatchedComparatorError("repartition split differs from nested100 reference")
    if int(split.get("development_subject_count", -1)) != len(expected_development):
        raise LiuMatchedComparatorError("nested100 development count is inconsistent")
    if int(split.get("retrospective_repartition_subject_count", -1)) != len(
        expected_repartition
    ):
        raise LiuMatchedComparatorError("nested100 repartition count is inconsistent")
    selector = _required_mapping(
        reference.get("frozen_100_selector"), label="nested100 selector"
    )
    outer = _required_mapping(
        selector.get("outer_selector_evaluation"), label="nested100 outer evaluation"
    )
    recorded_folds = outer.get("folds")
    if not isinstance(recorded_folds, list) or len(recorded_folds) != config.outer_folds:
        raise LiuMatchedComparatorError("nested100 outer folds are incomplete")
    for position, ((_, outer_test), recorded) in enumerate(
        zip(plan.outer_splits, recorded_folds, strict=True), start=1
    ):
        record = _required_mapping(recorded, label=f"nested100 outer fold {position}")
        expected = _indices(
            record.get("outer_test_indices"),
            label=f"nested100 outer fold {position} indices",
        )
        if tuple(outer_test.tolist()) != expected:
            raise LiuMatchedComparatorError(
                f"outer fold {position} differs from nested100 reference"
            )
    baseline = _required_mapping(
        reference.get("locked_term116_linear_family_baseline"),
        label="nested100 term116 baseline",
    )
    baseline_outer = _required_mapping(
        baseline.get("outer_selector_evaluation"),
        label="nested100 term116 outer evaluation",
    )
    baseline_folds = baseline_outer.get("folds")
    if not isinstance(baseline_folds, list) or len(baseline_folds) != config.outer_folds:
        raise LiuMatchedComparatorError("nested100 term116 outer folds are incomplete")
    for position, ((_, outer_test), recorded) in enumerate(
        zip(plan.outer_splits, baseline_folds, strict=True), start=1
    ):
        record = _required_mapping(
            recorded, label=f"nested100 term116 outer fold {position}"
        )
        if tuple(outer_test.tolist()) != _indices(
            record.get("outer_test_indices"),
            label=f"nested100 term116 outer fold {position} indices",
        ):
            raise LiuMatchedComparatorError(
                f"term116 outer fold {position} differs from nested100 reference"
            )
    return plan


def _split_summary(
    dataset: replay.HCPDataset, split_plan: replay.SplitPlan
) -> dict[str, object]:
    groups = np.asarray(dataset.family_ids, dtype=str)
    outer_test_indices = [outer_test for _, outer_test in split_plan.outer_splits]
    outer_union = set(np.concatenate(outer_test_indices).tolist())
    development = set(split_plan.development_indices.tolist())
    if outer_union != development:
        raise LiuMatchedComparatorError("outer evaluation folds do not cover development rows")
    if sum(len(indices) for indices in outer_test_indices) != len(outer_union):
        raise LiuMatchedComparatorError("outer evaluation folds overlap")
    development_family_count = int(len(set(groups[split_plan.development_indices])))
    repartition_family_count = int(len(set(groups[split_plan.repartition_indices])))
    if (development_family_count, repartition_family_count) != (243, 82):
        raise LiuMatchedComparatorError(
            "matched comparator requires nested100 family counts 243/82"
        )
    return {
        "development_family_count": development_family_count,
        "retrospective_repartition_family_count": repartition_family_count,
        "outer_test_sizes": [int(len(indices)) for indices in outer_test_indices],
        "outer_test_union_count": len(outer_union),
    }


def _require_common_support(dataset: replay.HCPDataset) -> tuple[int, ...]:
    missing = [
        term_index
        for term_index in COMMON_SUPPORT_TERM_INDICES
        if term_index not in dataset.term_records
    ]
    if missing:
        raise LiuMatchedComparatorError(
            f"common-support cache lacks frozen terms: {', '.join(map(str, missing))}"
        )
    return COMMON_SUPPORT_TERM_INDICES


def load_common_support_metric_catalog(source_bundle: Path) -> tuple[dict[str, object], ...]:
    """Load the exact 76-term source catalog used by the frozen comparator."""

    path = Path(source_bundle) / "public" / "metric_catalog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiuMatchedComparatorError("cannot read source metric catalog") from exc
    catalog = _required_mapping(payload, label="source metric catalog")
    terms = catalog.get("terms")
    if not isinstance(terms, list):
        raise LiuMatchedComparatorError("source metric catalog lacks terms")
    by_index: dict[int, dict[str, object]] = {}
    for raw in terms:
        row = _required_mapping(raw, label="source metric catalog term")
        index = _required_int(row.get("term_index"), label="source term index")
        by_index[index] = {
            "term_index": index,
            "metric_alias": _required_text(
                row.get("metric_alias"), label="source metric alias"
            ),
            "metric_family": _required_text(
                row.get("metric_family"), label="source metric family"
            ),
        }
    if tuple(sorted(by_index)) != COMMON_SUPPORT_TERM_INDICES:
        raise LiuMatchedComparatorError(
            "source metric catalog does not equal frozen 76-term common support"
        )
    return tuple(by_index[index] for index in COMMON_SUPPORT_TERM_INDICES)


def _common_support_term_metadata(
    *,
    dataset: replay.HCPDataset,
    metric_catalog: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    common_support = _require_common_support(dataset)
    catalog_by_index = {
        _required_int(row.get("term_index"), label="catalog term index"): row
        for row in metric_catalog
    }
    if tuple(sorted(catalog_by_index)) != common_support:
        raise LiuMatchedComparatorError("frozen term catalog differs from common support")
    metadata: list[dict[str, object]] = []
    for term_index in common_support:
        source_record = _required_mapping(
            dataset.term_records.get(term_index), label=f"source term {term_index}"
        )
        shape = source_record.get("shape")
        if not isinstance(shape, list) or tuple(shape) != (
            len(dataset.subject_ids),
            4950,
        ):
            raise LiuMatchedComparatorError(
                f"source term {term_index} must have shape "
                f"({len(dataset.subject_ids)}, 4950)"
            )
        catalog_row = catalog_by_index[term_index]
        metadata.append(
            {
                "term_index": term_index,
                "metric_alias": _required_text(
                    catalog_row.get("metric_alias"), label=f"term {term_index} alias"
                ),
                "metric_family": _required_text(
                    catalog_row.get("metric_family"), label=f"term {term_index} family"
                ),
                "cache_file": _required_text(
                    source_record.get("file"), label=f"term {term_index} cache file"
                ),
                "cache_dataset": _required_text(
                    source_record.get("dataset"), label=f"term {term_index} cache dataset"
                ),
                "shape": list(shape),
            }
        )
    return tuple(metadata)


def _development_term_eligibility(
    *,
    dataset: replay.HCPDataset,
    split_plan: replay.SplitPlan,
    cached_terms: Sequence[Mapping[str, object]],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Freeze Liu's non-degenerate-term rule from development features only.

    This step deliberately does not read endpoint values.  It prevents terms
    whose finite QCoD values are all below Liu's original ``0.01`` cutoff from
    entering the target-driven model/alpha search.  Fold-local QCoD screening
    still runs during CV for every eligible term.
    """

    development = split_plan.development_indices
    eligible: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for raw_metadata in cached_terms:
        metadata = dict(raw_metadata)
        term_index = _required_int(metadata.get("term_index"), label="term index")
        matrix = _matrix(
            replay._FeatureLoader(dataset).matrix(term_index),
            label=f"term-{term_index} eligibility matrix",
        )
        expected_shape = tuple(metadata.get("shape", ()))
        if matrix.shape != expected_shape:
            raise LiuMatchedComparatorError(
                f"term {term_index} matrix differs from its frozen source shape"
            )
        qcod = _qcod_values(matrix[development])
        finite = qcod[np.isfinite(qcod)]
        max_abs_finite_qcod = (
            float(np.max(np.abs(finite))) if finite.size else None
        )
        if max_abs_finite_qcod is None or max_abs_finite_qcod < 0.01:
            excluded.append(
                {
                    **metadata,
                    "development_max_abs_finite_qcod": max_abs_finite_qcod,
                    "reason": "max_abs_finite_development_qcod_below_0.01",
                }
            )
            continue
        eligible.append(
            {
                **metadata,
                "development_max_abs_finite_qcod": max_abs_finite_qcod,
            }
        )
    if not eligible:
        raise LiuMatchedComparatorError("development QCoD eligibility removed every term")
    eligible_indices = tuple(
        _required_int(item.get("term_index"), label="eligible term index")
        for item in eligible
    )
    if TERM0_INDEX not in eligible_indices:
        raise LiuMatchedComparatorError("term-0 anchor failed the frozen QCoD eligibility rule")
    if len(cached_terms) == 76:
        excluded_indices = tuple(
            _required_int(item.get("term_index"), label="excluded term index")
            for item in excluded
        )
        if excluded_indices != EXPECTED_DEGENERATE_COMMON_SUPPORT_TERM_INDICES:
            raise LiuMatchedComparatorError(
                "frozen common-support QCoD eligibility no longer excludes terms 141 and 145"
            )
        if len(eligible) != 74:
            raise LiuMatchedComparatorError(
                "frozen common-support QCoD eligibility must retain exactly 74 terms"
            )
    return tuple(eligible), tuple(excluded)


def _candidate_id(term_index: int, model_family: str, alpha: float) -> str:
    return f"liu_term{term_index:03d}_{model_family}_alpha_{alpha:g}"


def frozen_liu_candidates(
    term_indices: Sequence[int] = COMMON_SUPPORT_TERM_INDICES,
) -> tuple[dict[str, object], ...]:
    """Return a deterministic term × model × alpha candidate panel."""

    frozen_terms = tuple(term_indices)
    if not frozen_terms or len(set(frozen_terms)) != len(frozen_terms):
        raise LiuMatchedComparatorError("Liu candidate panel needs unique frozen terms")
    return tuple(
        {
            "candidate_id": _candidate_id(term_index, model_family, alpha),
            "term_index": term_index,
            "model_family": model_family,
            "alpha": alpha,
        }
        for term_index in frozen_terms
        for model_family in MODEL_FAMILIES
        for alpha in ALPHA_GRID
    )


def build_liu_preprocessor() -> Pipeline:
    """Build the fold-local QCoD and scaling sequence for finite matrices."""

    return Pipeline(
        steps=(
            ("qcod_10_90", _QCoDMiddleBand(*QCOD_BAND)),
            ("standard_scaler", StandardScaler()),
        )
    )


def build_liu_estimator(*, model_family: str, alpha: float) -> BaseEstimator:
    """Build one frozen Liu-style estimator after preprocessing is locked."""

    if model_family not in MODEL_FAMILIES:
        raise LiuMatchedComparatorError(f"unsupported Liu model family {model_family}")
    if alpha not in ALPHA_GRID:
        raise LiuMatchedComparatorError(f"unsupported Liu alpha {alpha}")
    if model_family == "kernelridgelinear":
        return KernelRidge(alpha=alpha, kernel="linear")
    if model_family == "kernelridgecosine":
        return KernelRidge(alpha=alpha, kernel="cosine")
    if model_family == "ridge":
        return Ridge(alpha=alpha, solver="auto")
    return Lasso(alpha=alpha, max_iter=10_000, selection="cyclic")


def build_liu_pipeline(*, model_family: str, alpha: float) -> Pipeline:
    """Build the full pipeline, primarily for direct unit-level inspection."""

    preprocessor = build_liu_preprocessor()
    return Pipeline(
        steps=(
            *preprocessor.steps,
            ("model", build_liu_estimator(model_family=model_family, alpha=alpha)),
        )
    )


def _fit_preprocessor(
    X_train: np.ndarray, X_evaluation: np.ndarray
) -> tuple[np.ndarray, np.ndarray, int]:
    preprocessor = build_liu_preprocessor()
    train = np.asarray(preprocessor.fit_transform(X_train), dtype=np.float64)
    evaluation = np.asarray(preprocessor.transform(X_evaluation), dtype=np.float64)
    if not np.all(np.isfinite(train)) or not np.all(np.isfinite(evaluation)):
        raise LiuMatchedComparatorError("fold-local preprocessing returned non-finite values")
    selector = preprocessor.named_steps["qcod_10_90"]
    assert isinstance(selector, _QCoDMiddleBand)
    return train, evaluation, int(len(selector.feature_indices_))


def _pearson(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_true) == 0.0 or np.std(y_pred) == 0.0:
        return float("nan")
    return float(np.corrcoef(y_true, y_pred)[0, 1])


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | None]:
    return replay._metrics(y_true, y_pred)


def _mean_metric(
    metrics: Sequence[Mapping[str, float | None]], key: str
) -> float | None:
    return replay._mean_metric(metrics, key)


def _score_term_candidates_on_inner(
    *,
    candidates: Sequence[Mapping[str, object]],
    X: np.ndarray,
    y: np.ndarray,
    inner_splits: Sequence[tuple[np.ndarray, np.ndarray]],
) -> list[dict[str, object]]:
    """Score a term's candidates, reusing preprocessing within each inner fold."""

    if not candidates:
        raise LiuMatchedComparatorError("inner selection received no candidates")
    rows = [
        {
            "status": "selected",
            "candidate_id": candidate["candidate_id"],
            "term_index": candidate["term_index"],
            "model_family": candidate["model_family"],
            "alpha": candidate["alpha"],
            "fold_default_r2": [],
            "fold_signed_pearson_r": [],
            "fold_selected_feature_count": [],
        }
        for candidate in candidates
    ]
    for train, validation in inner_splits:
        try:
            train_x, validation_x, selected_features = _fit_preprocessor(
                X[train], X[validation]
            )
            for candidate, row in zip(candidates, rows, strict=True):
                estimator = build_liu_estimator(
                    model_family=_required_text(
                        candidate.get("model_family"), label="model family"
                    ),
                    alpha=_required_float(candidate.get("alpha"), label="candidate alpha"),
                )
                estimator.fit(train_x, y[train])
                prediction = np.asarray(estimator.predict(validation_x), dtype=np.float64)
                if prediction.shape != (len(validation),) or not np.all(
                    np.isfinite(prediction)
                ):
                    raise LiuMatchedComparatorError("inner estimator returned invalid predictions")
                row["fold_default_r2"].append(float(r2_score(y[validation], prediction)))
                pearson_r = _pearson(y[validation], prediction)
                row["fold_signed_pearson_r"].append(
                    pearson_r if math.isfinite(pearson_r) else None
                )
                row["fold_selected_feature_count"].append(selected_features)
        except Exception as exc:
            return [
                {
                    "status": "failed",
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
                for candidate in candidates
            ]
    for row in rows:
        fold_r2 = [float(value) for value in row["fold_default_r2"]]
        if not all(math.isfinite(value) for value in fold_r2):
            return [
                {
                    "status": "failed",
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": "non-finite inner default R2",
                }
                for candidate in candidates
            ]
        row["mean_inner_default_r2"] = float(np.mean(fold_r2))
        finite_r = [
            float(value)
            for value in row["fold_signed_pearson_r"]
            if value is not None
        ]
        row["mean_inner_signed_pearson_r"] = (
            float(np.mean(finite_r)) if finite_r else None
        )
    return rows


def _select_inner_candidate(
    *,
    candidate_rows: Sequence[Mapping[str, object]],
    expected_count: int,
    stage: str,
) -> Mapping[str, object]:
    selected = [row for row in candidate_rows if row.get("status") == "selected"]
    if len(selected) != expected_count:
        failed = [str(row.get("candidate_id")) for row in candidate_rows if row.get("status") != "selected"]
        raise LiuMatchedComparatorError(
            f"{stage} did not select every frozen Liu candidate: {', '.join(failed)}"
        )
    return min(
        selected,
        key=lambda row: (-float(row["mean_inner_default_r2"]), str(row["candidate_id"])),
    )


def _predict_with_candidate(
    *,
    candidate: Mapping[str, object],
    X: np.ndarray,
    y: np.ndarray,
    train_indices: np.ndarray,
    prediction_indices: np.ndarray,
) -> tuple[np.ndarray, int]:
    train_x, evaluation_x, selected_features = _fit_preprocessor(
        X[train_indices], X[prediction_indices]
    )
    estimator = build_liu_estimator(
        model_family=_required_text(candidate.get("model_family"), label="model family"),
        alpha=_required_float(candidate.get("alpha"), label="candidate alpha"),
    )
    estimator.fit(train_x, y[train_indices])
    prediction = np.asarray(estimator.predict(evaluation_x), dtype=np.float64)
    if prediction.shape != (len(prediction_indices),) or not np.all(np.isfinite(prediction)):
        raise LiuMatchedComparatorError("selected Liu estimator returned invalid predictions")
    return prediction, selected_features


def _run_procedure(
    *,
    dataset: replay.HCPDataset,
    split_plan: replay.SplitPlan,
    development_target: np.ndarray,
    term_indices: Sequence[int],
    procedure_label: str,
) -> dict[str, object]:
    candidates = frozen_liu_candidates(term_indices)
    loader = replay._FeatureLoader(dataset)
    matrices = {
        term_index: _matrix(loader.matrix(term_index), label=f"term-{term_index} matrix")
        for term_index in term_indices
    }
    if any(matrix.shape[0] != len(dataset.subject_ids) for matrix in matrices.values()):
        raise LiuMatchedComparatorError("common-support matrix does not align to subject rows")
    y = np.asarray(development_target, dtype=np.float64)
    groups = np.asarray(dataset.family_ids, dtype=str)
    candidates_by_term = {
        term_index: tuple(
            candidate for candidate in candidates if candidate["term_index"] == term_index
        )
        for term_index in term_indices
    }
    outer_records: list[dict[str, object]] = []
    outer_predictions: list[tuple[np.ndarray, np.ndarray]] = []
    for outer_fold, (outer_train, outer_test) in enumerate(split_plan.outer_splits, start=1):
        inner_splits = replay._inner_group_splits(
            outer_train, groups, len(split_plan.final_inner_splits)
        )
        inner_rows = [
            row
            for term_index in term_indices
            for row in _score_term_candidates_on_inner(
                candidates=candidates_by_term[term_index],
                X=matrices[term_index],
                y=y,
                inner_splits=inner_splits,
            )
        ]
        winner = _select_inner_candidate(
            candidate_rows=inner_rows,
            expected_count=len(candidates),
            stage=f"{procedure_label} outer fold {outer_fold}",
        )
        term_index = _required_int(winner.get("term_index"), label="selected term")
        prediction, selected_features = _predict_with_candidate(
            candidate=winner,
            X=matrices[term_index],
            y=y,
            train_indices=outer_train,
            prediction_indices=outer_test,
        )
        outer_predictions.append((outer_test, prediction))
        outer_records.append(
            {
                "outer_fold": outer_fold,
                "status": "succeeded",
                "selected_candidate_id": winner["candidate_id"],
                "selected_term_index": term_index,
                "selected_model_family": winner["model_family"],
                "selected_alpha": winner["alpha"],
                "selected_outer_feature_count": selected_features,
                "inner_candidate_success_count": len(candidates),
                "inner_candidates": inner_rows,
                "outer_metrics": _metrics(y[outer_test], prediction),
                "outer_test_indices": outer_test.tolist(),
                "outer_y_true": y[outer_test].tolist(),
                "outer_y_pred": prediction.tolist(),
            }
        )
    fold_metrics = [
        _metrics(y[indices], prediction) for indices, prediction in outer_predictions
    ]
    ordered_indices = np.concatenate([indices for indices, _ in outer_predictions])
    ordered_predictions = np.concatenate(
        [prediction for _, prediction in outer_predictions]
    )
    final_rows = [
        row
        for term_index in term_indices
        for row in _score_term_candidates_on_inner(
            candidates=candidates_by_term[term_index],
            X=matrices[term_index],
            y=y,
            inner_splits=split_plan.final_inner_splits,
        )
    ]
    final_winner = _select_inner_candidate(
        candidate_rows=final_rows,
        expected_count=len(candidates),
        stage=f"{procedure_label} final development selection",
    )
    final_term = _required_int(final_winner.get("term_index"), label="final selected term")
    repartition_prediction, selected_features = _predict_with_candidate(
        candidate=final_winner,
        X=matrices[final_term],
        y=y,
        train_indices=split_plan.development_indices,
        prediction_indices=split_plan.repartition_indices,
    )
    pooled_metrics = replay._metrics(y[ordered_indices], ordered_predictions)
    return {
        "procedure_label": procedure_label,
        "term_indices": list(term_indices),
        "candidate_count": len(candidates),
        "candidates": [dict(candidate) for candidate in candidates],
        "outer_evaluation": {
            "metrics": {
                "mean_fold_signed_pearson_r": _mean_metric(
                    fold_metrics, "signed_pearson_r"
                ),
                "mean_fold_r2": _mean_metric(fold_metrics, "r2"),
                "mean_fold_mae": _mean_metric(fold_metrics, "mae"),
                "mean_fold_calibration_slope": _mean_metric(
                    fold_metrics, "calibration_slope"
                ),
                "pooled_oof_signed_pearson_r": pooled_metrics["signed_pearson_r"],
                "pooled_oof_r2": pooled_metrics["r2"],
                "pooled_oof_mae": pooled_metrics["mae"],
                "pooled_oof_calibration_slope": pooled_metrics[
                    "calibration_slope"
                ],
            },
            "folds": outer_records,
        },
        "final_development_selection": {
            "selected_candidate_id": final_winner["candidate_id"],
            "selected_term_index": final_term,
            "selected_model_family": final_winner["model_family"],
            "selected_alpha": final_winner["alpha"],
            "selected_repartition_feature_count": selected_features,
            "inner_candidate_success_count": len(candidates),
            "all_inner_candidate_rows": final_rows,
        },
        "locked_retrospective_repartition_prediction": {
            "subject_indices": split_plan.repartition_indices.tolist(),
            "y_pred": repartition_prediction.tolist(),
        },
    }


def prepare_frozen_liu_matched_contract(
    *,
    dataset: replay.HCPDataset,
    nested100_reference: Mapping[str, object],
    metric_catalog: Sequence[Mapping[str, object]],
    nested100_reference_path: Path | None = None,
) -> dict[str, object]:
    """Freeze the exact comparator before any endpoint value is read."""

    if _required_text(
        nested100_reference.get("schema_version"), label="nested100 schema version"
    ) != "br.hcp_nested100_replay.v1":
        raise LiuMatchedComparatorError("unexpected nested100 reference schema")
    config = _reference_config(nested100_reference)
    split_plan = _assert_reference_split(
        dataset=dataset, config=config, reference=nested100_reference
    )
    split_summary = _split_summary(dataset, split_plan)
    cached_terms = _common_support_term_metadata(
        dataset=dataset, metric_catalog=metric_catalog
    )
    effective_terms, excluded_terms = _development_term_eligibility(
        dataset=dataset,
        split_plan=split_plan,
        cached_terms=cached_terms,
    )
    effective_term_indices = tuple(
        _required_int(row.get("term_index"), label="effective term index")
        for row in effective_terms
    )
    common_candidates = frozen_liu_candidates(effective_term_indices)
    term0_candidates = frozen_liu_candidates((TERM0_INDEX,))
    return {
        "schema_version": "br.hcp_liu_matched_comparator_contract.v4",
        "source_nested100_result": (
            str(nested100_reference_path) if nested100_reference_path is not None else None
        ),
        "endpoint": {
            "target": config.primary_target,
            "covariate_policy": config.covariate_policy,
            "target_construction": "precomputed_age_sex_residualized_rank_IG_component_projection_not_fold_local",
        },
        "split": {
            "seed": config.seed,
            "development_indices": split_plan.development_indices.tolist(),
            "retrospective_repartition_indices": split_plan.repartition_indices.tolist(),
            "development_subject_count": len(split_plan.development_indices),
            "retrospective_repartition_subject_count": len(split_plan.repartition_indices),
            "outer_folds": config.outer_folds,
            "inner_folds": config.inner_folds,
            "family_grouped": True,
            "reference_outer_test_indices": [
                outer_test.tolist() for _, outer_test in split_plan.outer_splits
            ],
            **split_summary,
        },
        "preprocessing": {
            "qcod_percentiles": list(QCOD_BAND),
            "qcod_fit_scope": "each_inner_or_outer_training_partition_only",
            "input_finiteness": "all_76_cached_matrices_must_be_finite_no_imputation",
            "scaling": "StandardScaler_fit_on_training_partition_only",
            "pca_policy": "none",
            "reuse_scope": "one_preprocessor_fit_per_term_per_split_shared_by_16_model_alpha_candidates",
        },
        "primary_common_support_procedure": {
            "cached_terms": list(cached_terms),
            "cached_term_count": len(cached_terms),
            "term_eligibility": {
                "fit_scope": "development_feature_matrices_only_before_target_access",
                "rule": "include_if_max_abs_finite_development_qcod_at_least_0.01",
                "excluded_terms": list(excluded_terms),
            },
            "terms": list(effective_terms),
            "term_count": len(effective_terms),
            "model_families": list(MODEL_FAMILIES),
            "alpha_grid": list(ALPHA_GRID),
            "candidate_count": len(common_candidates),
            "term_model_pipeline_count": len(effective_term_indices)
            * len(MODEL_FAMILIES),
            "selection_objective": "GridSearchCV_estimator_default_R2",
            "selection_rule": "mean_inner_default_R2_then_candidate_id_ascending",
        },
        "secondary_term0_anchor": {
            "term_index": TERM0_INDEX,
            "term_label": TERM0_LABEL,
            "model_families": list(MODEL_FAMILIES),
            "alpha_grid": list(ALPHA_GRID),
            "candidate_count": len(term0_candidates),
            "selection_objective": "GridSearchCV_estimator_default_R2",
            "selection_rule": "mean_inner_default_R2_then_candidate_id_ascending",
        },
        "metrics": {
            "outer": [
                "mean_fold_signed_pearson_r",
                "pooled_oof_signed_pearson_r",
                "mean_fold_r2",
                "pooled_oof_r2",
                "mean_fold_mae",
                "pooled_oof_mae",
                "mean_fold_calibration_slope",
                "pooled_oof_calibration_slope",
                "per_fold",
            ],
            "retrospective_repartition": [
                "signed_pearson_r",
                "r2",
                "mae",
                "calibration_slope",
            ],
        },
        "claim_boundary": {
            "comparator_kind": "matched_Liu_style_common_support_comparator_not_direct_original_paper_reproduction",
            "retrospective_reused_hcp_repartition_status": "repartition_of_previously_reused_HCP_rows_not_unseen_holdout",
            "retrospective_repartition_is_unbiased": False,
            "same_cohort_comparison_only": True,
            "external_replication": False,
            "scientific_acceptance": False,
            "liu_superiority_claim": False,
            "candidate_budget_comparison": (
                f"Liu_common_support_{len(effective_term_indices) * len(MODEL_FAMILIES)}_"
                f"term_model_pipelines_{len(common_candidates)}_alpha_configurations_"
                "vs_nested100_100_candidate_templates"
            ),
            "test_adaptation": False,
        },
        "test_adaptation": "forbidden",
    }


def _assert_frozen_contract(
    *,
    frozen_contract: Mapping[str, object],
    dataset: replay.HCPDataset,
    nested100_reference: Mapping[str, object],
    metric_catalog: Sequence[Mapping[str, object]],
    nested100_reference_path: Path | None,
) -> tuple[replay.ReplayConfig, replay.SplitPlan, tuple[int, ...]]:
    expected = prepare_frozen_liu_matched_contract(
        dataset=dataset,
        nested100_reference=nested100_reference,
        metric_catalog=metric_catalog,
        nested100_reference_path=nested100_reference_path,
    )
    if dict(frozen_contract) != expected:
        raise LiuMatchedComparatorError(
            "frozen contract differs from the exact current nested100/source inputs"
        )
    config = _reference_config(nested100_reference)
    split_plan = _assert_reference_split(
        dataset=dataset, config=config, reference=nested100_reference
    )
    primary = _required_mapping(
        expected.get("primary_common_support_procedure"),
        label="frozen primary Liu procedure",
    )
    raw_terms = primary.get("terms")
    if not isinstance(raw_terms, list):
        raise LiuMatchedComparatorError("frozen primary Liu terms must be a list")
    term_indices = tuple(
        _required_int(
            _required_mapping(row, label="frozen primary Liu term").get("term_index"),
            label="frozen primary Liu term index",
        )
        for row in raw_terms
    )
    if not term_indices or len(set(term_indices)) != len(term_indices):
        raise LiuMatchedComparatorError("frozen primary Liu terms must be unique")
    return config, split_plan, term_indices


def _delta(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _matched_comparison(
    *,
    label: str,
    common_procedure: Mapping[str, object],
    reference_procedure: Mapping[str, object],
) -> dict[str, object]:
    common_outer = _required_mapping(
        common_procedure.get("outer_evaluation"), label="common comparator outer evaluation"
    )
    reference_outer = _required_mapping(
        reference_procedure.get("outer_selector_evaluation"),
        label=f"{label} outer evaluation",
    )
    common_folds = common_outer.get("folds")
    reference_folds = reference_outer.get("folds")
    if not isinstance(common_folds, list) or not isinstance(reference_folds, list):
        raise LiuMatchedComparatorError(f"{label} lacks comparable outer folds")
    if len(common_folds) != len(reference_folds):
        raise LiuMatchedComparatorError(f"{label} outer fold count differs")
    fold_delta_r: list[float | None] = []
    for position, (common_raw, reference_raw) in enumerate(
        zip(common_folds, reference_folds, strict=True), start=1
    ):
        common_fold = _required_mapping(common_raw, label="common comparator outer fold")
        reference_fold = _required_mapping(reference_raw, label=f"{label} outer fold")
        if common_fold.get("outer_test_indices") != reference_fold.get(
            "outer_test_indices"
        ):
            raise LiuMatchedComparatorError(
                f"{label} outer fold {position} indices do not match the comparator"
            )
        common_metrics = _required_mapping(
            common_fold.get("outer_metrics"), label="common comparator fold metrics"
        )
        reference_metrics = _required_mapping(
            reference_fold.get("outer_metrics"), label=f"{label} fold metrics"
        )
        fold_delta_r.append(
            _delta(
                common_metrics.get("signed_pearson_r"),
                reference_metrics.get("signed_pearson_r"),
            )
        )
    common_metrics = _required_mapping(
        common_outer.get("metrics"), label="common comparator outer metrics"
    )
    reference_metrics = _required_mapping(
        reference_outer.get("metrics"), label=f"{label} outer metrics"
    )
    outer_keys = (
        "mean_fold_signed_pearson_r",
        "pooled_oof_signed_pearson_r",
        "mean_fold_r2",
        "pooled_oof_r2",
        "mean_fold_mae",
        "pooled_oof_mae",
        "mean_fold_calibration_slope",
        "pooled_oof_calibration_slope",
    )
    common_repartition = _required_mapping(
        common_procedure.get("retrospective_reused_hcp_repartition"),
        label="common comparator repartition",
    )
    reference_repartition = _required_mapping(
        reference_procedure.get("retrospective_reused_hcp_repartition"),
        label=f"{label} repartition",
    )
    if common_repartition.get("subject_indices") != reference_repartition.get(
        "subject_indices"
    ):
        raise LiuMatchedComparatorError(f"{label} repartition indices do not match")
    common_repartition_metrics = _required_mapping(
        common_repartition.get("metrics"), label="common comparator repartition metrics"
    )
    reference_repartition_metrics = _required_mapping(
        reference_repartition.get("metrics"), label=f"{label} repartition metrics"
    )
    return {
        "comparison_label": f"common_support_minus_{label}",
        "interpretation": "direct_same_split_metric_delta_only_no_p_value_or_selection_adjusted_inference",
        "outer_summary_delta": {
            key: _delta(common_metrics.get(key), reference_metrics.get(key))
            for key in outer_keys
        },
        "outer_fold_signed_pearson_r_delta": fold_delta_r,
        "retrospective_repartition_delta": {
            key: _delta(
                common_repartition_metrics.get(key), reference_repartition_metrics.get(key)
            )
            for key in ("signed_pearson_r", "r2", "mae", "calibration_slope")
        },
    }


def _assert_reference_target_alignment(
    *,
    reference: Mapping[str, object],
    split_plan: replay.SplitPlan,
    development_target: np.ndarray,
    repartition_target: np.ndarray,
) -> None:
    """Assert persisted nested100 outcomes still refer to the current endpoint."""

    for procedure_key, label in (
        ("frozen_100_selector", "nested100 selector"),
        (
            "locked_term116_linear_family_baseline",
            "nested100 term116 baseline",
        ),
    ):
        procedure = _required_mapping(reference.get(procedure_key), label=label)
        outer = _required_mapping(
            procedure.get("outer_selector_evaluation"), label=f"{label} outer evaluation"
        )
        records = outer.get("folds")
        if not isinstance(records, list) or len(records) != len(split_plan.outer_splits):
            raise LiuMatchedComparatorError(f"{label} has incomplete outer outcomes")
        for position, ((_, indices), raw_record) in enumerate(
            zip(split_plan.outer_splits, records, strict=True), start=1
        ):
            record = _required_mapping(raw_record, label=f"{label} outer fold {position}")
            if tuple(indices.tolist()) != _indices(
                record.get("outer_test_indices"),
                label=f"{label} outer fold {position} indices",
            ):
                raise LiuMatchedComparatorError(
                    f"{label} outer fold {position} indices no longer match the split"
                )
            observed = np.asarray(record.get("outer_y_true"), dtype=np.float64)
            expected = development_target[indices]
            if observed.shape != expected.shape or not np.array_equal(observed, expected):
                raise LiuMatchedComparatorError(
                    f"{label} outer fold {position} y_true differs from current target"
                )
        repartition = _required_mapping(
            procedure.get("retrospective_reused_hcp_repartition"),
            label=f"{label} repartition",
        )
        if tuple(split_plan.repartition_indices.tolist()) != _indices(
            repartition.get("subject_indices"), label=f"{label} repartition indices"
        ):
            raise LiuMatchedComparatorError(
                f"{label} repartition indices no longer match the split"
            )
        observed = np.asarray(repartition.get("y_true"), dtype=np.float64)
        if observed.shape != repartition_target.shape or not np.array_equal(
            observed, repartition_target
        ):
            raise LiuMatchedComparatorError(
                f"{label} repartition y_true differs from current target"
            )


def run_frozen_liu_matched_comparator(
    *,
    dataset: replay.HCPDataset,
    nested100_reference: Mapping[str, object],
    metric_catalog: Sequence[Mapping[str, object]],
    frozen_contract: Mapping[str, object],
    nested100_reference_path: Path | None = None,
) -> dict[str, object]:
    """Run only a separately prepared and still-matching frozen contract."""

    _, split_plan, primary_term_indices = _assert_frozen_contract(
        frozen_contract=frozen_contract,
        dataset=dataset,
        nested100_reference=nested100_reference,
        metric_catalog=metric_catalog,
        nested100_reference_path=nested100_reference_path,
    )
    development_target = np.full(len(dataset.subject_ids), np.nan, dtype=np.float64)
    development_target[split_plan.development_indices] = replay._targets_for_indices(
        dataset, split_plan.development_indices
    )
    common_procedure = _run_procedure(
        dataset=dataset,
        split_plan=split_plan,
        development_target=development_target,
        term_indices=primary_term_indices,
        procedure_label="frozen_development_eligible_common_support_Liu_style_comparator",
    )
    term0_anchor = _run_procedure(
        dataset=dataset,
        split_plan=split_plan,
        development_target=development_target,
        term_indices=(TERM0_INDEX,),
        procedure_label="secondary_term0_EmpiricalCovariance_anchor",
    )
    # Both model selections and every retrospective prediction are now locked
    # using development labels only.  Read the 82 reused labels once to score.
    repartition_y = replay._targets_for_indices(dataset, split_plan.repartition_indices)
    _assert_reference_target_alignment(
        reference=nested100_reference,
        split_plan=split_plan,
        development_target=development_target,
        repartition_target=repartition_y,
    )
    for procedure in (common_procedure, term0_anchor):
        locked = procedure.pop("locked_retrospective_repartition_prediction")
        assert isinstance(locked, Mapping)
        prediction = np.asarray(locked["y_pred"], dtype=np.float64)
        procedure["retrospective_reused_hcp_repartition"] = {
            "subject_indices": list(locked["subject_indices"]),
            "y_true": repartition_y.tolist(),
            "y_pred": prediction.tolist(),
            "metrics": _metrics(repartition_y, prediction),
        }
    selector = _required_mapping(
        nested100_reference.get("frozen_100_selector"), label="nested100 selector"
    )
    baseline = _required_mapping(
        nested100_reference.get("locked_term116_linear_family_baseline"),
        label="nested100 term116 baseline",
    )
    return {
        "schema_version": "br.hcp_liu_matched_comparator.v4",
        "analysis_label": "frozen_development_eligible_common_support_Liu_style_matched_HCP_retrospective_repartition",
        "claim_boundary": dict(
            _required_mapping(frozen_contract.get("claim_boundary"), label="claim boundary")
        ),
        "frozen_contract": dict(frozen_contract),
        "execution_validation": {
            **_split_summary(dataset, split_plan),
            "outer_and_repartition_indices_asserted_against_nested100": True,
            "repartition_y_true_loaded_from_current_target_table": True,
            "nested100_y_true_matches_current_target": True,
            "all_common_support_matrices_required_finite": True,
        },
        "matched_liu_common_support": common_procedure,
        "term0_secondary_anchor": term0_anchor,
        "matched_comparisons": {
            "vs_nested100_selector": _matched_comparison(
                label="nested100_selector",
                common_procedure=common_procedure,
                reference_procedure=selector,
            ),
            "vs_locked_term116_linear_family_baseline": _matched_comparison(
                label="locked_term116_linear_family_baseline",
                common_procedure=common_procedure,
                reference_procedure=baseline,
            ),
        },
    }


def read_nested100_reference(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiuMatchedComparatorError("cannot read nested100 reference result") from exc
    if not isinstance(payload, dict):
        raise LiuMatchedComparatorError("nested100 reference must be an object")
    return payload


def read_frozen_liu_matched_contract(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiuMatchedComparatorError("cannot read frozen Liu comparator contract") from exc
    if not isinstance(payload, dict):
        raise LiuMatchedComparatorError("frozen Liu comparator contract must be an object")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_frozen_liu_matched_contract(
    output_dir: Path, contract: Mapping[str, object]
) -> Path:
    """Create the new output directory exclusively and persist its contract."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    contract_path = destination / "frozen_contract.json"
    _write_json(contract_path, contract)
    return contract_path


def write_liu_matched_comparator_result(
    output_dir: Path, result: Mapping[str, object]
) -> Path:
    """Persist one result only under the already prepared contract directory."""

    destination = Path(output_dir)
    contract_path = destination / "frozen_contract.json"
    if not destination.is_dir() or not contract_path.is_file():
        raise LiuMatchedComparatorError("result requires a prepared frozen contract directory")
    contract = _required_mapping(result.get("frozen_contract"), label="result contract")
    if read_frozen_liu_matched_contract(contract_path) != dict(contract):
        raise LiuMatchedComparatorError("result contract differs from prepared contract")
    result_path = destination / "liu_matched_comparator_result.json"
    if result_path.exists():
        raise LiuMatchedComparatorError("comparator result already exists")
    _write_json(result_path, result)
    return result_path


__all__ = [
    "ALPHA_GRID",
    "COMMON_SUPPORT_TERM_INDICES",
    "EXPECTED_DEGENERATE_COMMON_SUPPORT_TERM_INDICES",
    "MODEL_FAMILIES",
    "QCOD_BAND",
    "TERM0_INDEX",
    "LiuMatchedComparatorError",
    "build_liu_estimator",
    "build_liu_pipeline",
    "build_liu_preprocessor",
    "frozen_liu_candidates",
    "load_common_support_metric_catalog",
    "prepare_frozen_liu_matched_contract",
    "read_frozen_liu_matched_contract",
    "read_nested100_reference",
    "run_frozen_liu_matched_comparator",
    "write_frozen_liu_matched_contract",
    "write_liu_matched_comparator_result",
]
