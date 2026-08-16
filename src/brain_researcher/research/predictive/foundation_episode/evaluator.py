"""Fresh-fit grouped evaluator for the single-target foundation episode.

This module is deliberately independent of the historical benchmark runner's
``run_one_experiment`` and nested-CV replay paths.  It receives a frozen,
group-aware split plan, fits every candidate afresh, selects only from inner
train/validation rows, and evaluates the selected candidate on each held-out
outer fold exactly once.

The target contract is supplied by the authorized episode bundle. No feature
filtering is performed here.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Literal

import numpy as np
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, ParameterGrid

from brain_researcher.research.predictive.foundation_episode.contracts import (
    RECEIPT_COUNT,
)

CONTROLLER_AGGREGATE_SCHEMA_VERSION = "foundation_episode_controller_aggregate_v1"
# Public callers must inject the historical-compatible estimator runtime.
DEFAULT_ENGINE_PATH: Path | None = None
DEFAULT_ALPHA_GRID = (0.1, 1.0, 10.0, 100.0)
_ALLOWED_CONTROL_MODES = frozenset(
    {"observed", "family_block_shuffle", "synthetic_positive_control"}
)
_ALLOWED_SPLITTERS = frozenset({"GroupKFold", "SeededGroupKFold"})
_SEEDED_GROUP_ASSIGNMENT_ALGORITHM = (
    "foundation_mve24_seeded_balanced_group_assignment_v1"
)
_ROW_SHUFFLE_ALIASES = frozenset(
    {
        "row_shuffle",
        "row-wise",
        "row_wise",
        "row_wise_label_shuffle",
        "label_shuffle",
        "permutation",
    }
)
_ENGINE_LOAD_SEQUENCE = count()
_UINT32_MODULUS = 2**32


class FreshFitEvaluationError(ValueError):
    """A fail-closed fresh-fit evaluator contract violation."""


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    return value


def _seed_component(value: object) -> int:
    """Map the small, fixed evaluation labels into SeedSequence entropy."""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value % _UINT32_MODULUS
    text = str(value)
    return sum((index + 1) * ord(character) for index, character in enumerate(text)) % (
        _UINT32_MODULUS
    )


def _derive_seed(seed: int, *parts: object) -> int:
    entropy = [seed % _UINT32_MODULUS]
    entropy.extend(_seed_component(part) for part in parts)
    return int(np.random.SeedSequence(entropy).generate_state(1, dtype=np.uint32)[0])


def _require_seed(seed: object) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise FreshFitEvaluationError("seed must be an integer")
    return seed


def _require_term_index(term_index: object) -> int:
    if (
        isinstance(term_index, bool)
        or not isinstance(term_index, int)
        or term_index < 0
    ):
        raise FreshFitEvaluationError("term_index must be a non-negative integer")
    return term_index


def _as_index_tuple(value: object, label: str) -> tuple[int, ...]:
    array = np.asarray(value)
    if array.ndim != 1 or array.size == 0:
        raise FreshFitEvaluationError(
            f"{label} must be a non-empty one-dimensional vector"
        )
    if array.dtype.kind not in {"i", "u"}:
        raise FreshFitEvaluationError(f"{label} must contain integer row indices")
    indices = tuple(int(item) for item in array.tolist())
    if any(item < 0 for item in indices):
        raise FreshFitEvaluationError(f"{label} must contain non-negative row indices")
    if len(set(indices)) != len(indices):
        raise FreshFitEvaluationError(f"{label} must not contain duplicate row indices")
    return indices


def _as_fold_id(value: object, label: str) -> str:
    if isinstance(value, bool):
        raise FreshFitEvaluationError(f"{label} must be a non-empty identifier")
    normalized = str(value)
    if not normalized.strip() or normalized != normalized.strip():
        raise FreshFitEvaluationError(
            f"{label} must be a non-empty stripped identifier"
        )
    return normalized


def _freeze_value(value: object, label: str) -> object:
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            normalized_key = _as_fold_id(key, f"{label} key")
            frozen[normalized_key] = _freeze_value(item, f"{label}.{normalized_key}")
        return MappingProxyType(frozen)
    if isinstance(value, tuple | list):
        return tuple(
            _freeze_value(item, f"{label}[{index}]") for index, item in enumerate(value)
        )
    if isinstance(value, np.generic):
        return _freeze_value(value.item(), label)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    raise FreshFitEvaluationError(
        f"{label} contains unsupported receipt value {type(value).__name__}"
    )


def _freeze_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FreshFitEvaluationError(f"{label} must be a mapping")
    frozen = _freeze_value(value, label)
    assert isinstance(frozen, Mapping)
    return frozen


def _finite_or_none(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _normalize_groups(groups: object, n_rows: int) -> np.ndarray:
    raw = np.asarray(groups)
    if raw.ndim != 1 or len(raw) != n_rows:
        raise FreshFitEvaluationError(
            "groups must be a one-dimensional vector aligned to X"
        )
    normalized = np.asarray([str(item) for item in raw], dtype=str)
    if any(not item.strip() or item != item.strip() for item in normalized):
        raise FreshFitEvaluationError(
            "groups must contain non-empty stripped identifiers"
        )
    normalized.setflags(write=False)
    return normalized


def _normalize_inputs(
    X: object, y: object, groups: object
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    try:
        features = np.asarray(X, dtype=np.float64)
        target = np.asarray(y, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise FreshFitEvaluationError("X and y must be numeric") from exc
    if features.ndim != 2 or features.shape[0] == 0 or features.shape[1] == 0:
        raise FreshFitEvaluationError("X must be a non-empty two-dimensional matrix")
    if target.ndim != 1 or len(target) != len(features):
        raise FreshFitEvaluationError("y must be a one-dimensional vector aligned to X")
    if not np.all(np.isfinite(target)):
        raise FreshFitEvaluationError("y must contain only finite values")
    if np.any(np.isinf(features)):
        raise FreshFitEvaluationError("X must not contain infinity")
    copied_features = np.array(features, dtype=np.float64, copy=True)
    copied_target = np.array(target, dtype=np.float64, copy=True)
    copied_features.setflags(write=False)
    copied_target.setflags(write=False)
    return copied_features, copied_target, _normalize_groups(groups, len(features))


@dataclass(frozen=True, slots=True)
class FrozenGroupSplit:
    """One explicit grouped train/test partition expressed in global row IDs."""

    fold_id: str
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        fold_id = _as_fold_id(self.fold_id, "fold_id")
        train = _as_index_tuple(self.train_indices, "train_indices")
        test = _as_index_tuple(self.test_indices, "test_indices")
        if set(train) & set(test):
            raise FreshFitEvaluationError(
                f"split {fold_id!r} has overlapping train and test indices"
            )
        object.__setattr__(self, "fold_id", fold_id)
        object.__setattr__(self, "train_indices", train)
        object.__setattr__(self, "test_indices", test)

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "train_indices": list(self.train_indices),
            "test_indices": list(self.test_indices),
        }


@dataclass(frozen=True, slots=True)
class FrozenGroupSplitPlan:
    """A fixed outer/inner GroupKFold plan, independent of model fitting.

    ``from_groups`` is the canonical producer.  ``from_mapping`` exists for a
    previously materialized plan and validates the same grouped partition
    invariants when the evaluator receives the actual rows and groups.
    """

    outer_splits: tuple[FrozenGroupSplit, ...]
    inner_splits: Mapping[str, tuple[FrozenGroupSplit, ...]]
    evaluation_indices: tuple[int, ...] | None = None
    splitter: str = "GroupKFold"
    seed: int | None = None
    assignment_algorithm: str | None = None
    schema_version: str = "foundation_episode_frozen_group_split_plan_v1"

    def __post_init__(self) -> None:
        if self.splitter not in _ALLOWED_SPLITTERS:
            raise FreshFitEvaluationError(
                "FrozenGroupSplitPlan must declare GroupKFold or SeededGroupKFold"
            )
        if self.splitter == "SeededGroupKFold":
            if (
                isinstance(self.seed, bool)
                or not isinstance(self.seed, int)
                or self.seed < 0
            ):
                raise FreshFitEvaluationError(
                    "SeededGroupKFold requires a non-negative seed"
                )
            if self.assignment_algorithm != _SEEDED_GROUP_ASSIGNMENT_ALGORITHM:
                raise FreshFitEvaluationError(
                    "SeededGroupKFold requires the frozen balanced group assignment algorithm"
                )
        elif self.seed is not None or self.assignment_algorithm is not None:
            raise FreshFitEvaluationError(
                "GroupKFold plan must not carry seeded-assignment provenance"
            )
        outer = tuple(self.outer_splits)
        if len(outer) < 2 or not all(
            isinstance(item, FrozenGroupSplit) for item in outer
        ):
            raise FreshFitEvaluationError(
                "outer_splits must contain at least two FrozenGroupSplit values"
            )
        outer_ids = tuple(item.fold_id for item in outer)
        if len(set(outer_ids)) != len(outer_ids):
            raise FreshFitEvaluationError("outer fold identifiers must be unique")
        if not isinstance(self.inner_splits, Mapping):
            raise FreshFitEvaluationError(
                "inner_splits must be a mapping by outer fold ID"
            )
        normalized_inner: dict[str, tuple[FrozenGroupSplit, ...]] = {}
        for outer_id, inner in self.inner_splits.items():
            normalized_id = _as_fold_id(outer_id, "inner_splits key")
            folds = tuple(inner)
            if len(folds) < 2 or not all(
                isinstance(item, FrozenGroupSplit) for item in folds
            ):
                raise FreshFitEvaluationError(
                    f"inner_splits[{normalized_id!r}] must contain at least two "
                    "FrozenGroupSplit values"
                )
            inner_ids = tuple(item.fold_id for item in folds)
            if len(set(inner_ids)) != len(inner_ids):
                raise FreshFitEvaluationError(
                    f"inner_splits[{normalized_id!r}] fold identifiers must be unique"
                )
            normalized_inner[normalized_id] = folds
        if set(normalized_inner) != set(outer_ids):
            raise FreshFitEvaluationError(
                "inner_splits must provide exactly one inner plan for every outer fold"
            )
        evaluation_indices: tuple[int, ...] | None
        if self.evaluation_indices is None:
            evaluation_indices = None
        else:
            evaluation_indices = _as_index_tuple(
                self.evaluation_indices, "evaluation_indices"
            )
        object.__setattr__(self, "outer_splits", outer)
        object.__setattr__(self, "inner_splits", MappingProxyType(normalized_inner))
        object.__setattr__(self, "evaluation_indices", evaluation_indices)
        if self.splitter == "SeededGroupKFold" and (
            len(outer) != 5
            or any(len(folds) != 3 for folds in normalized_inner.values())
        ):
            raise FreshFitEvaluationError(
                "SeededGroupKFold requires exactly five outer and three inner folds"
            )

    @classmethod
    def from_groups(
        cls,
        groups: object,
        *,
        n_outer_splits: int = 5,
        n_inner_splits: int = 3,
    ) -> FrozenGroupSplitPlan:
        """Build the only plan producer: deterministic outer and inner GroupKFold."""

        raw_groups = np.asarray(groups)
        if raw_groups.ndim != 1 or raw_groups.size == 0:
            raise FreshFitEvaluationError(
                "groups must be a non-empty one-dimensional vector"
            )
        normalized_groups = _normalize_groups(raw_groups, len(raw_groups))
        if isinstance(n_outer_splits, bool) or not isinstance(n_outer_splits, int):
            raise FreshFitEvaluationError("n_outer_splits must be an integer")
        if isinstance(n_inner_splits, bool) or not isinstance(n_inner_splits, int):
            raise FreshFitEvaluationError("n_inner_splits must be an integer")
        n_groups = len(set(normalized_groups.tolist()))
        if not 2 <= n_outer_splits <= n_groups:
            raise FreshFitEvaluationError(
                "n_outer_splits must be between 2 and the number of distinct groups"
            )
        outer_splitter = GroupKFold(n_splits=n_outer_splits)
        rows = np.arange(len(normalized_groups), dtype=np.int64)
        outer_splits: list[FrozenGroupSplit] = []
        inner_splits: dict[str, tuple[FrozenGroupSplit, ...]] = {}
        for outer_index, (outer_train, outer_test) in enumerate(
            outer_splitter.split(rows, groups=normalized_groups)
        ):
            fold_id = f"outer_{outer_index}"
            train_global = rows[np.asarray(outer_train, dtype=np.int64)]
            test_global = rows[np.asarray(outer_test, dtype=np.int64)]
            train_groups = normalized_groups[train_global]
            n_inner_groups = len(set(train_groups.tolist()))
            if not 2 <= n_inner_splits <= n_inner_groups:
                raise FreshFitEvaluationError(
                    "n_inner_splits must be between 2 and the distinct groups in "
                    f"outer fold {fold_id}"
                )
            inner_splitter = GroupKFold(n_splits=n_inner_splits)
            inner_for_outer: list[FrozenGroupSplit] = []
            for inner_index, (inner_train, inner_test) in enumerate(
                inner_splitter.split(train_global, groups=train_groups)
            ):
                inner_for_outer.append(
                    FrozenGroupSplit(
                        fold_id=f"inner_{inner_index}",
                        train_indices=tuple(
                            int(item)
                            for item in train_global[
                                np.asarray(inner_train, dtype=np.int64)
                            ]
                        ),
                        test_indices=tuple(
                            int(item)
                            for item in train_global[
                                np.asarray(inner_test, dtype=np.int64)
                            ]
                        ),
                    )
                )
            outer_splits.append(
                FrozenGroupSplit(
                    fold_id=fold_id,
                    train_indices=tuple(int(item) for item in train_global),
                    test_indices=tuple(int(item) for item in test_global),
                )
            )
            inner_splits[fold_id] = tuple(inner_for_outer)
        return cls(outer_splits=tuple(outer_splits), inner_splits=inner_splits)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> FrozenGroupSplitPlan:
        """Coerce common JSON plan shapes without regenerating frozen split rows."""

        if not isinstance(value, Mapping):
            raise FreshFitEvaluationError(
                "split_plan must be a FrozenGroupSplitPlan or mapping"
            )
        splitter = value.get("splitter", value.get("splitter_name", "GroupKFold"))
        outer_raw = value.get(
            "outer_splits",
            value.get("outer_folds", value.get("folds", value.get("outer"))),
        )
        if isinstance(outer_raw, str) or not isinstance(outer_raw, Sequence):
            raise FreshFitEvaluationError(
                "split_plan must contain outer_splits as a sequence"
            )
        root_inner = value.get(
            "inner_splits", value.get("inner_by_outer", value.get("inner"))
        )
        evaluation_raw = value.get(
            "evaluation_indices",
            value.get(
                "evaluation_row_indices",
                value.get("discovery_row_indices", value.get("row_indices")),
            ),
        )
        outer_splits: list[FrozenGroupSplit] = []
        inner_splits: dict[str, tuple[FrozenGroupSplit, ...]] = {}
        for outer_index, raw_outer in enumerate(outer_raw):
            if not isinstance(raw_outer, Mapping):
                raise FreshFitEvaluationError("each outer split must be a mapping")
            fold_id = _as_fold_id(
                raw_outer.get("fold_id", raw_outer.get("fold", f"outer_{outer_index}")),
                "fold_id",
            )
            outer_splits.append(_split_from_mapping(raw_outer, fold_id))
            raw_inner = raw_outer.get("inner_splits", raw_outer.get("inner_folds"))
            if raw_inner is None:
                if isinstance(root_inner, Mapping):
                    raw_inner = root_inner.get(fold_id)
                    if raw_inner is None:
                        raw_inner = root_inner.get(raw_outer.get("fold_id"))
                elif isinstance(root_inner, Sequence) and not isinstance(
                    root_inner, str
                ):
                    if outer_index < len(root_inner):
                        raw_inner = root_inner[outer_index]
            if isinstance(raw_inner, Mapping):
                raw_inner = raw_inner.get("splits", raw_inner.get("folds"))
            if isinstance(raw_inner, str) or not isinstance(raw_inner, Sequence):
                raise FreshFitEvaluationError(
                    f"outer fold {fold_id!r} is missing its inner_splits sequence"
                )
            parsed_inner: list[FrozenGroupSplit] = []
            for inner_index, raw_split in enumerate(raw_inner):
                if not isinstance(raw_split, Mapping):
                    raise FreshFitEvaluationError("each inner split must be a mapping")
                inner_id = _as_fold_id(
                    raw_split.get(
                        "fold_id", raw_split.get("fold", f"inner_{inner_index}")
                    ),
                    "inner fold_id",
                )
                parsed_inner.append(_split_from_mapping(raw_split, inner_id))
            inner_splits[fold_id] = tuple(parsed_inner)
        seeded = str(splitter) == "SeededGroupKFold"
        seed = value.get("seed") if seeded else None
        assignment_algorithm = value.get("assignment_algorithm") if seeded else None
        return cls(
            outer_splits=tuple(outer_splits),
            inner_splits=inner_splits,
            evaluation_indices=(
                _as_index_tuple(evaluation_raw, "evaluation_row_indices")
                if evaluation_raw is not None
                else None
            ),
            splitter=str(splitter),
            seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else seed,
            assignment_algorithm=(
                assignment_algorithm
                if isinstance(assignment_algorithm, str)
                else assignment_algorithm
            ),
        )

    def validate(self, *, n_rows: int, groups: np.ndarray) -> None:
        """Fail closed unless the frozen rows form complete grouped CV partitions."""

        if self.splitter not in _ALLOWED_SPLITTERS:
            raise FreshFitEvaluationError("unknown grouped split plan type")
        if n_rows <= 0 or groups.shape != (n_rows,):
            raise FreshFitEvaluationError(
                "plan validation requires aligned non-empty groups"
            )
        all_rows = (
            set(range(n_rows))
            if self.evaluation_indices is None
            else set(self.evaluation_indices)
        )
        if not all_rows or any(row >= n_rows for row in all_rows):
            raise FreshFitEvaluationError(
                "evaluation_indices must be a non-empty subset of X row indices"
            )
        outer_test_counts = dict.fromkeys(all_rows, 0)
        for outer in self.outer_splits:
            train = set(outer.train_indices)
            test = set(outer.test_indices)
            _validate_split_rows(outer.fold_id, train, test, all_rows)
            _validate_group_disjointness(outer.fold_id, train, test, groups)
            for row in test:
                outer_test_counts[row] += 1
            inner = self.inner_splits[outer.fold_id]
            inner_test_counts = dict.fromkeys(train, 0)
            for inner_split in inner:
                inner_train = set(inner_split.train_indices)
                inner_test = set(inner_split.test_indices)
                _validate_split_rows(
                    f"{outer.fold_id}/{inner_split.fold_id}",
                    inner_train,
                    inner_test,
                    train,
                )
                _validate_group_disjointness(
                    f"{outer.fold_id}/{inner_split.fold_id}",
                    inner_train,
                    inner_test,
                    groups,
                )
                for row in inner_test:
                    inner_test_counts[row] += 1
            if any(count != 1 for count in inner_test_counts.values()):
                raise FreshFitEvaluationError(
                    f"inner splits for {outer.fold_id!r} must test every outer-train row "
                    "exactly once"
                )
        if any(count != 1 for count in outer_test_counts.values()):
            raise FreshFitEvaluationError(
                "outer splits must test every row exactly once"
            )
        if self.splitter == "GroupKFold":
            _validate_groupkfold_partitions(
                scope="outer",
                row_indices=np.asarray(sorted(all_rows), dtype=np.int64),
                groups=groups,
                splits=self.outer_splits,
            )
            for outer in self.outer_splits:
                _validate_groupkfold_partitions(
                    scope=f"inner plan for {outer.fold_id!r}",
                    row_indices=np.asarray(sorted(outer.train_indices), dtype=np.int64),
                    groups=groups,
                    splits=self.inner_splits[outer.fold_id],
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "splitter": self.splitter,
            "seed": self.seed,
            "assignment_algorithm": self.assignment_algorithm,
            "evaluation_indices": (
                list(self.evaluation_indices)
                if self.evaluation_indices is not None
                else None
            ),
            "outer_splits": [item.to_dict() for item in self.outer_splits],
            "inner_splits": {
                outer.fold_id: [
                    item.to_dict() for item in self.inner_splits[outer.fold_id]
                ]
                for outer in self.outer_splits
            },
        }


def _split_from_mapping(value: Mapping[str, object], fold_id: str) -> FrozenGroupSplit:
    train = value.get(
        "train_indices", value.get("train_row_indices", value.get("train"))
    )
    test = value.get(
        "test_indices",
        value.get(
            "test_row_indices",
            value.get(
                "validation_indices", value.get("val_indices", value.get("test"))
            ),
        ),
    )
    if train is None or test is None:
        raise FreshFitEvaluationError(
            f"split {fold_id!r} must provide train_indices and test_indices"
        )
    return FrozenGroupSplit(fold_id=fold_id, train_indices=train, test_indices=test)


def _validate_split_rows(
    split_id: str,
    train: set[int],
    test: set[int],
    expected_rows: set[int],
) -> None:
    if not train or not test or train & test or train | test != expected_rows:
        raise FreshFitEvaluationError(
            f"split {split_id!r} must partition its expected rows into non-empty "
            "train and test sets"
        )


def _validate_group_disjointness(
    split_id: str,
    train: set[int],
    test: set[int],
    groups: np.ndarray,
) -> None:
    train_groups = {str(groups[row]) for row in train}
    test_groups = {str(groups[row]) for row in test}
    overlap = sorted(train_groups & test_groups)
    if overlap:
        raise FreshFitEvaluationError(
            f"split {split_id!r} leaks group IDs across train and test: {overlap}"
        )


def _validate_groupkfold_partitions(
    *,
    scope: str,
    row_indices: np.ndarray,
    groups: np.ndarray,
    splits: Sequence[FrozenGroupSplit],
) -> None:
    """Prove that a declared GroupKFold plan is not merely group-disjoint."""

    try:
        generated = GroupKFold(n_splits=len(splits)).split(
            row_indices, groups=groups[row_indices]
        )
        expected_test_sets = {
            frozenset(int(row) for row in row_indices[np.asarray(test, dtype=np.int64)])
            for _, test in generated
        }
    except ValueError as exc:
        raise FreshFitEvaluationError(
            f"{scope} cannot be generated by GroupKFold: {exc}"
        ) from exc
    actual_test_sets = {frozenset(split.test_indices) for split in splits}
    if actual_test_sets != expected_test_sets:
        raise FreshFitEvaluationError(
            f"{scope} does not match deterministic GroupKFold partitions"
        )


def _coerce_split_plan(value: object) -> FrozenGroupSplitPlan:
    if isinstance(value, FrozenGroupSplitPlan):
        return value
    if isinstance(value, Mapping):
        return FrozenGroupSplitPlan.from_mapping(value)
    raise FreshFitEvaluationError(
        "split_plan must be a FrozenGroupSplitPlan or mapping"
    )


def signed_pearson_r(y_true: object, y_pred: object) -> float:
    """Return signed Pearson r, preserving anti-correlation instead of abs(r)."""

    truth = np.asarray(y_true, dtype=np.float64)
    prediction = np.asarray(y_pred, dtype=np.float64)
    if truth.ndim != 1 or prediction.ndim != 1 or len(truth) != len(prediction):
        raise FreshFitEvaluationError(
            "Pearson inputs must be aligned one-dimensional vectors"
        )
    if (
        len(truth) < 2
        or not np.all(np.isfinite(truth))
        or not np.all(np.isfinite(prediction))
    ):
        return float("nan")
    if np.isclose(np.std(truth), 0.0) or np.isclose(np.std(prediction), 0.0):
        return float("nan")
    return float(np.corrcoef(truth, prediction)[0, 1])


def calibration_slope(y_true: object, y_pred: object) -> float | None:
    """Return the held-out OLS slope for ``y_true = intercept + beta * y_pred``.

    This is a diagnostic only.  It is intentionally not a selection statistic:
    an unavailable or degenerate held-out prediction vector is represented as
    ``None`` rather than being coerced into a favorable numeric value.  A
    negative fitted beta is retained.
    """

    truth = np.asarray(y_true, dtype=np.float64)
    prediction = np.asarray(y_pred, dtype=np.float64)
    if truth.ndim != 1 or prediction.ndim != 1 or len(truth) != len(prediction):
        raise FreshFitEvaluationError(
            "calibration inputs must be aligned one-dimensional vectors"
        )
    if (
        len(truth) < 2
        or not np.all(np.isfinite(truth))
        or not np.all(np.isfinite(prediction))
    ):
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        centered_prediction = prediction - np.mean(prediction)
        centered_truth = truth - np.mean(truth)
        denominator = float(np.dot(centered_prediction, centered_prediction))
        numerator = float(np.dot(centered_prediction, centered_truth))
    if (
        not math.isfinite(denominator)
        or not math.isfinite(numerator)
        or denominator <= 0.0
    ):
        return None
    return _finite_or_none(numerator / denominator)


_signed_pearson_r = signed_pearson_r


def family_block_shuffle(y: object, groups: object, seed: int) -> np.ndarray:
    """Exchange whole label blocks only among families of the same size.

    The row order inside every family is preserved.  Thus this operation cannot
    silently become a row-wise label shuffle even when families are noncontiguous
    in the input array.
    """

    master_seed = _require_seed(seed)
    try:
        target = np.asarray(y, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise FreshFitEvaluationError(
            "y must be numeric for family block shuffle"
        ) from exc
    if target.ndim != 1 or target.size == 0 or not np.all(np.isfinite(target)):
        raise FreshFitEvaluationError(
            "y must be a non-empty finite vector for family block shuffle"
        )
    normalized_groups = _normalize_groups(groups, len(target))
    family_rows: dict[str, list[int]] = {}
    for row, group in enumerate(normalized_groups.tolist()):
        family_rows.setdefault(group, []).append(row)
    families_by_size: dict[int, list[str]] = {}
    for family, rows in family_rows.items():
        families_by_size.setdefault(len(rows), []).append(family)
    shuffled = np.array(target, copy=True)
    rng = np.random.default_rng(master_seed)
    for block_size in sorted(families_by_size):
        destination_families = families_by_size[block_size]
        source_positions = rng.permutation(len(destination_families))
        for destination_position, source_position in enumerate(source_positions):
            destination_rows = family_rows[destination_families[destination_position]]
            source_rows = family_rows[destination_families[int(source_position)]]
            if len(destination_rows) != len(source_rows):
                raise AssertionError("same-size family bucket invariant violated")
            shuffled[destination_rows] = target[source_rows]
    shuffled.setflags(write=False)
    return shuffled


@dataclass(frozen=True, slots=True)
class FoldReceipt:
    """Immutable-like audit record for one outer fold, including failures."""

    fold_id: str
    status: Literal["succeeded", "failed"]
    train_size: int
    test_size: int
    test_indices: tuple[int, ...]
    y_true: tuple[float, ...]
    y_pred: tuple[float, ...]
    metrics: Mapping[str, float | None]
    selection: Mapping[str, object]
    runtime_sec: float | None
    error: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed"}:
            raise FreshFitEvaluationError("fold receipt status is invalid")
        object.__setattr__(self, "fold_id", _as_fold_id(self.fold_id, "fold_id"))
        object.__setattr__(
            self, "test_indices", _as_index_tuple(self.test_indices, "test_indices")
        )
        if self.train_size <= 0 or self.test_size <= 0:
            raise FreshFitEvaluationError(
                "fold receipt train_size and test_size must be positive"
            )
        if self.test_size != len(self.test_indices):
            raise FreshFitEvaluationError(
                "fold receipt test_size must match test_indices"
            )
        truth = tuple(float(item) for item in self.y_true)
        prediction = tuple(float(item) for item in self.y_pred)
        if self.status == "succeeded" and (
            len(truth) != self.test_size or len(prediction) != self.test_size
        ):
            raise FreshFitEvaluationError(
                "successful fold receipt predictions must align to the held-out rows"
            )
        if self.status == "failed" and (truth or prediction):
            raise FreshFitEvaluationError(
                "failed fold receipts must not expose partial predictions"
            )
        object.__setattr__(self, "y_true", truth)
        object.__setattr__(self, "y_pred", prediction)
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics, "metrics"))
        object.__setattr__(
            self, "selection", _freeze_mapping(self.selection, "selection")
        )
        runtime = _finite_or_none(self.runtime_sec)
        if runtime is not None and runtime < 0.0:
            raise FreshFitEvaluationError("runtime_sec must be non-negative")
        object.__setattr__(self, "runtime_sec", runtime)
        if self.error is not None:
            object.__setattr__(self, "error", _freeze_mapping(self.error, "error"))

    def to_dict(self) -> dict[str, object]:
        selected_params = self.selection.get("selected_params", {})
        return {
            "fold_id": self.fold_id,
            "status": self.status,
            "train_size": self.train_size,
            "test_size": self.test_size,
            "test_indices": list(self.test_indices),
            "y_true": list(self.y_true),
            "y_pred": list(self.y_pred),
            "metrics": _jsonable(self.metrics),
            "selection": _jsonable(self.selection),
            "selected_params": _jsonable(selected_params),
            "best_params": _jsonable(selected_params),
            "runtime_sec": self.runtime_sec,
            "error": _jsonable(self.error) if self.error is not None else None,
        }


@dataclass(frozen=True, slots=True)
class EvaluationReceipt:
    """Private result envelope returned for both success and failure."""

    status: Literal["succeeded", "failed"]
    classifier_key: str
    term_index: int
    seed: int
    control_mode: str
    folds: tuple[FoldReceipt, ...]
    metrics: Mapping[str, float | None]
    runtime_sec: float | None
    error: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed"}:
            raise FreshFitEvaluationError("receipt status is invalid")
        object.__setattr__(
            self, "classifier_key", _as_fold_id(self.classifier_key, "classifier_key")
        )
        object.__setattr__(self, "term_index", _require_term_index(self.term_index))
        object.__setattr__(self, "seed", _require_seed(self.seed))
        object.__setattr__(
            self, "control_mode", _as_fold_id(self.control_mode, "control_mode")
        )
        folds = tuple(self.folds)
        if not all(isinstance(item, FoldReceipt) for item in folds):
            raise FreshFitEvaluationError("folds must contain FoldReceipt values")
        object.__setattr__(self, "folds", folds)
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics, "metrics"))
        runtime = _finite_or_none(self.runtime_sec)
        if runtime is not None and runtime < 0.0:
            raise FreshFitEvaluationError("runtime_sec must be non-negative")
        object.__setattr__(self, "runtime_sec", runtime)
        if self.error is not None:
            object.__setattr__(self, "error", _freeze_mapping(self.error, "error"))

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "classifier_key": self.classifier_key,
            "term_index": self.term_index,
            "seed": self.seed,
            "control_mode": self.control_mode,
            "folds": [item.to_dict() for item in self.folds],
            "metrics": _jsonable(self.metrics),
            "runtime_sec": self.runtime_sec,
            "error": _jsonable(self.error) if self.error is not None else None,
        }


def controller_aggregate(receipt: EvaluationReceipt, *, slot: int) -> dict[str, object]:
    """Return the only controller-safe view of a private row-level receipt.

    This projection intentionally omits fold IDs, row indices, targets,
    predictions, engine locations, free-form failure messages, and secondary
    diagnostics such as calibration slope.  It is safe to append to the
    MVE-100 controller's aggregate ledger, but it is not a substitute for the
    private audit receipt.
    """

    if not isinstance(receipt, EvaluationReceipt):
        raise FreshFitEvaluationError(
            "controller_aggregate requires an EvaluationReceipt"
        )
    if (
        isinstance(slot, bool)
        or not isinstance(slot, int)
        or not 1 <= slot <= RECEIPT_COUNT
    ):
        raise FreshFitEvaluationError(
            f"controller aggregate slot must be in 1..{RECEIPT_COUNT}"
        )
    completed = sum(fold.status == "succeeded" for fold in receipt.folds)
    failed = sum(fold.status == "failed" for fold in receipt.folds)
    return {
        "schema_version": CONTROLLER_AGGREGATE_SCHEMA_VERSION,
        "slot": slot,
        "status": receipt.status,
        "term_index": receipt.term_index,
        "classifier_key": receipt.classifier_key,
        "control_mode": receipt.control_mode,
        "candidate_label": (
            f"slot-{slot}:{receipt.classifier_key}:term-{receipt.term_index}"
        ),
        "metrics": {
            key: _jsonable(receipt.metrics.get(key))
            for key in (
                "primary_signed_pearson_r",
                "mean_fold_signed_pearson_r",
                "mean_fold_r2",
                "mean_fold_mae",
                "pooled_signed_pearson_r",
            )
        },
        "qc": {
            "outer_fold_count": len(receipt.folds),
            "completed_fold_count": completed,
            "failed_fold_count": failed,
            "all_outer_folds_succeeded": receipt.status == "succeeded" and failed == 0,
            "primary_metric_available": receipt.metrics.get("primary_signed_pearson_r")
            is not None,
        },
        "runtime_sec": receipt.runtime_sec,
        "failure_type": (
            receipt.error.get("type") if receipt.error is not None else None
        ),
    }


def _normalize_control_mode(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FreshFitEvaluationError(
            "control_mode must be a non-empty stripped string"
        )
    normalized = value.lower()
    if normalized in _ROW_SHUFFLE_ALIASES:
        raise FreshFitEvaluationError(
            "row-wise label shuffle is prohibited; use family_block_shuffle only"
        )
    if normalized not in _ALLOWED_CONTROL_MODES:
        raise FreshFitEvaluationError(
            "control_mode must be 'observed', 'family_block_shuffle', or "
            "'synthetic_positive_control'"
        )
    return normalized


def _load_engine(engine_path: str) -> ModuleType:
    """Load the requested engine without sibling-module cross-talk."""

    path = Path(engine_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"benchmark engine file does not exist: {path}")
    module_name = f"foundation_episode_benchmark_{next(_ENGINE_LOAD_SEQUENCE)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FreshFitEvaluationError(f"could not create an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    inserted_path = str(path.parent)
    sibling_names = ("_banghcp_common", "_banghcp_raw_target")
    previous_siblings = {name: sys.modules.get(name) for name in sibling_names}
    sys.path.insert(0, inserted_path)
    sys.modules[module_name] = module
    try:
        for name in sibling_names:
            sys.modules.pop(name, None)
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        for name in sibling_names:
            sys.modules.pop(name, None)
            previous = previous_siblings[name]
            if previous is not None:
                sys.modules[name] = previous
        try:
            sys.path.remove(inserted_path)
        except ValueError:
            pass
    return module


def _path_for_engine(engine_path: str | Path | None) -> Path:
    if engine_path is None:
        raise FreshFitEvaluationError(
            "engine_path is required; no governed data-root default is shipped"
        )
    if isinstance(engine_path, Path):
        return engine_path
    if (
        isinstance(engine_path, str)
        and engine_path.strip()
        and engine_path == engine_path.strip()
    ):
        return Path(engine_path)
    raise FreshFitEvaluationError("engine_path must be a filesystem path or None")


def _coerce_classifier_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FreshFitEvaluationError(
            "classifier_key must be a non-empty stripped string"
        )
    return value.lower()


def _make_failure_receipt(
    *,
    classifier_key: str,
    term_index: int,
    seed: int,
    control_mode: str,
    folds: Sequence[FoldReceipt],
    runtime_sec: float,
    exc: Exception,
) -> EvaluationReceipt:
    frozen_folds = tuple(folds)
    return EvaluationReceipt(
        status="failed",
        classifier_key=classifier_key or "invalid",
        term_index=term_index,
        seed=seed,
        control_mode=control_mode or "invalid",
        folds=frozen_folds,
        metrics={
            "primary_signed_pearson_r": None,
            "mean_fold_signed_pearson_r": None,
            "mean_fold_r2": None,
            "mean_fold_mae": None,
            "pooled_signed_pearson_r": None,
            "mean_fold_calibration_slope": None,
            "pooled_oof_calibration_slope": None,
        },
        runtime_sec=max(0.0, round(float(runtime_sec), 6)),
        error={"type": type(exc).__name__, "message": str(exc)},
    )


def _sklearn_fold(
    *,
    module: ModuleType,
    classifier_key: str,
    X: np.ndarray,
    y_fit: np.ndarray,
    outer: FrozenGroupSplit,
    inner_splits: Sequence[FrozenGroupSplit],
    seed: int,
) -> tuple[np.ndarray, Mapping[str, object]]:
    factory = getattr(module, "_build_estimator", None)
    if not callable(factory):
        raise FreshFitEvaluationError(
            "engine does not expose callable _build_estimator for sklearn classifiers"
        )
    outer_train = np.asarray(outer.train_indices, dtype=np.int64)
    estimator, param_grid = factory(
        classifier_key,
        DEFAULT_ALPHA_GRID,
        _derive_seed(seed, "outer", outer.fold_id, "candidate-grid"),
        n_train_samples=int(len(outer_train)),
        n_features=int(X.shape[1]),
    )
    estimator_overrides: dict[str, object] = {}
    if classifier_key == "mlp":
        try:
            estimator.set_params(mlpregressor__early_stopping=False)
        except (TypeError, ValueError) as exc:
            raise FreshFitEvaluationError(
                "MLP engine must expose mlpregressor__early_stopping for the "
                "group-safe override"
            ) from exc
        estimator_overrides["mlpregressor__early_stopping"] = False
    candidates = list(ParameterGrid(param_grid))
    if not candidates:
        candidates = [{}]
    candidate_results: list[dict[str, object]] = []
    selected_params: dict[str, object] | None = None
    selected_score = -math.inf
    for candidate_index, params in enumerate(candidates):
        inner_scores: list[float] = []
        candidate_error: str | None = None
        for inner in inner_splits:
            train = np.asarray(inner.train_indices, dtype=np.int64)
            validation = np.asarray(inner.test_indices, dtype=np.int64)
            try:
                fitted = clone(estimator)
                fitted.set_params(**params)
                fitted.fit(X[train], y_fit[train])
                prediction = np.asarray(
                    fitted.predict(X[validation]), dtype=np.float64
                ).reshape(-1)
                score = signed_pearson_r(y_fit[validation], prediction)
                if not math.isfinite(score):
                    raise FreshFitEvaluationError(
                        "inner signed Pearson r is non-finite"
                    )
                inner_scores.append(score)
            except (
                Exception
            ) as exc:  # candidate-local failure can still leave other candidates viable
                candidate_error = f"{type(exc).__name__}: {exc}"
                break
        mean_score = float(np.mean(inner_scores)) if candidate_error is None else None
        candidate_results.append(
            {
                "candidate_index": candidate_index,
                "params": dict(params),
                "inner_signed_pearson_r": tuple(inner_scores),
                "mean_inner_signed_pearson_r": mean_score,
                "error": candidate_error,
            }
        )
        if mean_score is not None and mean_score > selected_score:
            selected_score = mean_score
            selected_params = dict(params)
    if selected_params is None:
        raise FreshFitEvaluationError("all sklearn inner candidates failed")
    final_estimator, _ = factory(
        classifier_key,
        DEFAULT_ALPHA_GRID,
        _derive_seed(seed, "outer", outer.fold_id, "final-refit"),
        n_train_samples=int(len(outer_train)),
        n_features=int(X.shape[1]),
    )
    if classifier_key == "mlp":
        try:
            final_estimator.set_params(mlpregressor__early_stopping=False)
        except (TypeError, ValueError) as exc:
            raise FreshFitEvaluationError(
                "MLP engine must expose mlpregressor__early_stopping for the "
                "group-safe override"
            ) from exc
    final_estimator.set_params(**selected_params)
    final_estimator.fit(X[outer_train], y_fit[outer_train])
    outer_test = np.asarray(outer.test_indices, dtype=np.int64)
    prediction = np.asarray(
        final_estimator.predict(X[outer_test]), dtype=np.float64
    ).reshape(-1)
    if prediction.shape != (len(outer_test),) or not np.all(np.isfinite(prediction)):
        raise FreshFitEvaluationError(
            "final sklearn estimator returned invalid predictions"
        )
    return prediction, {
        "candidate_count": len(candidates),
        "selected_params": selected_params,
        "selected_inner_mean_signed_pearson_r": selected_score,
        "candidate_results": tuple(candidate_results),
        "estimator_overrides": estimator_overrides,
        "refit_protocol": "full_outer_training_after_inner_selection",
    }


def _cpm_fold(
    *,
    module: ModuleType,
    X: np.ndarray,
    y_fit: np.ndarray,
    outer: FrozenGroupSplit,
    inner_splits: Sequence[FrozenGroupSplit],
) -> tuple[np.ndarray, Mapping[str, object]]:
    """Select CPM's top-k only from the frozen group inner folds."""

    kernel = getattr(module, "_fit_cpm_fold", None)
    if not callable(kernel):
        raise FreshFitEvaluationError("engine does not expose callable _fit_cpm_fold")
    raw_grid = getattr(module, "DEFAULT_CPM_TOPK_GRID", (25, 100, 400))
    if isinstance(raw_grid, str) or not isinstance(raw_grid, Sequence):
        raise FreshFitEvaluationError("engine DEFAULT_CPM_TOPK_GRID must be a sequence")
    top_k_grid: list[int] = []
    for raw_top_k in raw_grid:
        if (
            isinstance(raw_top_k, bool)
            or not isinstance(raw_top_k, int)
            or raw_top_k <= 0
        ):
            raise FreshFitEvaluationError(
                "CPM top-k candidates must be positive integers"
            )
        top_k_grid.append(int(raw_top_k))
    if not top_k_grid:
        raise FreshFitEvaluationError("engine exposes no CPM top-k candidates")
    candidate_results: list[dict[str, object]] = []
    selected_top_k: int | None = None
    selected_score = -math.inf
    for candidate_index, top_k in enumerate(top_k_grid):
        inner_scores: list[float] = []
        candidate_error: str | None = None
        for inner in inner_splits:
            train = np.asarray(inner.train_indices, dtype=np.int64)
            validation = np.asarray(inner.test_indices, dtype=np.int64)
            try:
                _, prediction, _ = kernel(
                    X_train=X[train],
                    y_train=y_fit[train],
                    X_eval=X[validation],
                    top_k=top_k,
                )
                score = signed_pearson_r(
                    y_fit[validation],
                    np.asarray(prediction, dtype=np.float64).reshape(-1),
                )
                if not math.isfinite(score):
                    raise FreshFitEvaluationError(
                        "inner signed Pearson r is non-finite"
                    )
                inner_scores.append(score)
            except Exception as exc:  # preserve viable CPM candidates after one failure
                candidate_error = f"{type(exc).__name__}: {exc}"
                break
        mean_score = float(np.mean(inner_scores)) if candidate_error is None else None
        candidate_results.append(
            {
                "candidate_index": candidate_index,
                "params": {"top_k": top_k},
                "inner_signed_pearson_r": tuple(inner_scores),
                "mean_inner_signed_pearson_r": mean_score,
                "error": candidate_error,
            }
        )
        if mean_score is not None and mean_score > selected_score:
            selected_score = mean_score
            selected_top_k = top_k
    if selected_top_k is None:
        raise FreshFitEvaluationError("all CPM inner candidates failed")
    outer_train = np.asarray(outer.train_indices, dtype=np.int64)
    outer_test = np.asarray(outer.test_indices, dtype=np.int64)
    _, prediction, fit_metadata = kernel(
        X_train=X[outer_train],
        y_train=y_fit[outer_train],
        X_eval=X[outer_test],
        top_k=selected_top_k,
    )
    prediction_array = np.asarray(prediction, dtype=np.float64).reshape(-1)
    if prediction_array.shape != (len(outer_test),) or not np.all(
        np.isfinite(prediction_array)
    ):
        raise FreshFitEvaluationError(
            "final CPM estimator returned invalid predictions"
        )
    metadata = dict(fit_metadata) if isinstance(fit_metadata, Mapping) else {}
    return prediction_array, {
        "candidate_count": len(top_k_grid),
        "selected_params": {"top_k": selected_top_k, **metadata},
        "selected_inner_mean_signed_pearson_r": selected_score,
        "candidate_results": tuple(candidate_results),
        "refit_protocol": "full_outer_training_after_inner_selection",
    }


def _torch_single_split(
    *,
    module: ModuleType,
    classifier_key: str,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_validation: np.ndarray,
    y_validation: np.ndarray,
    config: Mapping[str, object],
    seed: int,
) -> Mapping[str, object]:
    raw_edge_count = int(X_train.shape[1])
    kept_edge_indices = list(range(raw_edge_count))
    kwargs = {
        "X_train": X_train,
        "y_train": y_train,
        "X_val": X_validation,
        "y_val": y_validation,
        "raw_edge_count": raw_edge_count,
        "kept_edge_indices": kept_edge_indices,
        "config": dict(config),
        "seed": seed,
    }
    if classifier_key == "brainnetcnn":
        kernel = getattr(module, "_train_brainnet_single_split", None)
    else:
        kernel = getattr(module, "_train_torch_matrix_model_single_split", None)
        kwargs["classifier"] = classifier_key
    if not callable(kernel):
        raise FreshFitEvaluationError(
            "engine does not expose the required torch single-split training kernel"
        )
    result = kernel(**kwargs)
    if not isinstance(result, Mapping):
        raise FreshFitEvaluationError("torch single-split kernel must return a mapping")
    return result


def _predict_torch_model(
    *,
    module: ModuleType,
    classifier_key: str,
    result: Mapping[str, object],
    X_fit: np.ndarray,
    y_fit: np.ndarray,
    X_test: np.ndarray,
) -> np.ndarray:
    """Run a fitted single-split model on outer test X without passing outer y."""

    torch = getattr(module, "torch", None)
    vectorize = getattr(module, "_vectorized_upper_triangle_to_symmetric", None)
    if torch is None or not callable(vectorize) or "model" not in result:
        raise FreshFitEvaluationError("torch engine lacks prediction helpers")
    feature_mean = np.nanmean(X_fit, axis=0)
    feature_std = np.nanstd(X_fit, axis=0)
    feature_std[~np.isfinite(feature_std) | np.isclose(feature_std, 0.0)] = 1.0
    target_mean = float(np.nanmean(y_fit))
    target_std = float(np.nanstd(y_fit))
    if not math.isfinite(target_std) or np.isclose(target_std, 0.0):
        target_std = 1.0
    X_scaled = np.nan_to_num((X_test - feature_mean) / feature_std, nan=0.0)
    raw_edge_count = int(X_fit.shape[1])
    matrices = vectorize(
        X_scaled,
        raw_edge_count=raw_edge_count,
        kept_edge_indices=list(range(raw_edge_count)),
    )
    model = result["model"]
    try:
        device = next(model.parameters()).device
    except StopIteration as exc:
        raise FreshFitEvaluationError("torch model has no parameters") from exc
    model.eval()
    with torch.no_grad():
        if classifier_key == "brainnetcnn":
            inputs = torch.tensor(
                matrices[:, None, :, :], dtype=torch.float32, device=device
            )
            prediction_scaled = model(inputs).detach().cpu().numpy()
        else:
            normalized_operator = getattr(module, "_normalized_graph_operator", None)
            forward = getattr(module, "_torch_matrix_forward", None)
            if not callable(normalized_operator) or not callable(forward):
                raise FreshFitEvaluationError(
                    "torch engine lacks matrix prediction helpers"
                )
            adjacency_norm, adjacency_bias = normalized_operator(matrices)
            inputs = torch.tensor(matrices, dtype=torch.float32, device=device)
            normalized = torch.tensor(
                adjacency_norm, dtype=torch.float32, device=device
            )
            bias = torch.tensor(adjacency_bias, dtype=torch.float32, device=device)
            prediction_scaled = (
                forward(classifier_key, model, inputs, normalized, bias)
                .detach()
                .cpu()
                .numpy()
            )
    prediction = np.asarray(prediction_scaled, dtype=np.float64).reshape(-1)
    prediction = prediction * target_std + target_mean
    if prediction.shape != (len(X_test),) or not np.all(np.isfinite(prediction)):
        raise FreshFitEvaluationError(
            "torch model returned invalid outer-test predictions"
        )
    return prediction


def _torch_fold(
    *,
    module: ModuleType,
    classifier_key: str,
    X: np.ndarray,
    y_fit: np.ndarray,
    outer: FrozenGroupSplit,
    inner_splits: Sequence[FrozenGroupSplit],
    seed: int,
) -> tuple[np.ndarray, Mapping[str, object]]:
    candidates_fn = getattr(module, "_torch_matrix_model_candidates", None)
    if not callable(candidates_fn):
        raise FreshFitEvaluationError(
            "engine does not expose torch candidate configurations"
        )
    candidates = list(candidates_fn(classifier_key))
    if not candidates:
        raise FreshFitEvaluationError(
            "torch classifier has no candidate configurations"
        )
    candidate_results: list[dict[str, object]] = []
    selected_config: dict[str, object] | None = None
    selected_score = -math.inf
    for candidate_index, config in enumerate(candidates):
        inner_scores: list[float] = []
        candidate_error: str | None = None
        for inner in inner_splits:
            train = np.asarray(inner.train_indices, dtype=np.int64)
            validation = np.asarray(inner.test_indices, dtype=np.int64)
            try:
                result = _torch_single_split(
                    module=module,
                    classifier_key=classifier_key,
                    X_train=X[train],
                    y_train=y_fit[train],
                    X_validation=X[validation],
                    y_validation=y_fit[validation],
                    config=config,
                    seed=_derive_seed(
                        seed,
                        "outer",
                        outer.fold_id,
                        "candidate",
                        candidate_index,
                        "inner",
                        inner.fold_id,
                    ),
                )
                prediction = np.asarray(
                    result["val_predictions"], dtype=np.float64
                ).reshape(-1)
                score = signed_pearson_r(y_fit[validation], prediction)
                if not math.isfinite(score):
                    raise FreshFitEvaluationError(
                        "inner signed Pearson r is non-finite"
                    )
                inner_scores.append(score)
            except (
                Exception
            ) as exc:  # a candidate can fail without corrupting selection
                candidate_error = f"{type(exc).__name__}: {exc}"
                break
        mean_score = float(np.mean(inner_scores)) if candidate_error is None else None
        candidate_results.append(
            {
                "candidate_index": candidate_index,
                "params": dict(config),
                "inner_signed_pearson_r": tuple(inner_scores),
                "mean_inner_signed_pearson_r": mean_score,
                "error": candidate_error,
            }
        )
        if mean_score is not None and mean_score > selected_score:
            selected_score = mean_score
            selected_config = dict(config)
    if selected_config is None:
        raise FreshFitEvaluationError("all torch inner candidates failed")
    # Final refit must use every outer-training row.  The external kernels
    # require validation labels for their checkpoint policy, so we self-monitor
    # against the same outer-training rows rather than leaking outer-test labels
    # or systematically discarding an inner-train subset for torch families.
    outer_train = np.asarray(outer.train_indices, dtype=np.int64)
    final_result = _torch_single_split(
        module=module,
        classifier_key=classifier_key,
        X_train=X[outer_train],
        y_train=y_fit[outer_train],
        X_validation=X[outer_train],
        y_validation=y_fit[outer_train],
        config=selected_config,
        seed=_derive_seed(seed, "outer", outer.fold_id, "final-refit"),
    )
    prediction = _predict_torch_model(
        module=module,
        classifier_key=classifier_key,
        result=final_result,
        X_fit=X[outer_train],
        y_fit=y_fit[outer_train],
        X_test=X[np.asarray(outer.test_indices, dtype=np.int64)],
    )
    return prediction, {
        "candidate_count": len(candidates),
        "selected_params": selected_config,
        "selected_inner_mean_signed_pearson_r": selected_score,
        "candidate_results": tuple(candidate_results),
        "refit_protocol": "full_outer_training_self_monitored_no_outer_test_labels",
        "refit_monitoring_rows": "outer_train",
    }


def _metric_mapping(
    y_true: np.ndarray, y_pred: np.ndarray
) -> Mapping[str, float | None]:
    return {
        "signed_pearson_r": _finite_or_none(signed_pearson_r(y_true, y_pred)),
        "r2": _finite_or_none(float(r2_score(y_true, y_pred))),
        "mae": _finite_or_none(float(mean_absolute_error(y_true, y_pred))),
        "calibration_slope": calibration_slope(y_true, y_pred),
    }


def _aggregate_metrics(folds: Sequence[FoldReceipt]) -> Mapping[str, float | None]:
    successful = [item for item in folds if item.status == "succeeded"]
    if not successful:
        return {
            "primary_signed_pearson_r": None,
            "mean_fold_signed_pearson_r": None,
            "mean_fold_r2": None,
            "mean_fold_mae": None,
            "pooled_signed_pearson_r": None,
            "mean_fold_calibration_slope": None,
            "pooled_oof_calibration_slope": None,
        }
    per_fold_r = [item.metrics.get("signed_pearson_r") for item in successful]
    per_fold_r2 = [item.metrics.get("r2") for item in successful]
    per_fold_mae = [item.metrics.get("mae") for item in successful]
    per_fold_calibration_slope = [
        item.metrics.get("calibration_slope") for item in successful
    ]
    if any(value is None for value in per_fold_r + per_fold_r2 + per_fold_mae):
        raise FreshFitEvaluationError("successful folds must have finite metrics")
    pooled_truth = np.asarray(
        [value for item in successful for value in item.y_true], dtype=np.float64
    )
    pooled_prediction = np.asarray(
        [value for item in successful for value in item.y_pred], dtype=np.float64
    )
    mean_fold_r = float(np.mean(np.asarray(per_fold_r, dtype=np.float64)))
    return {
        "primary_signed_pearson_r": mean_fold_r,
        "mean_fold_signed_pearson_r": mean_fold_r,
        "mean_fold_r2": float(np.mean(np.asarray(per_fold_r2, dtype=np.float64))),
        "mean_fold_mae": float(np.mean(np.asarray(per_fold_mae, dtype=np.float64))),
        "pooled_signed_pearson_r": _finite_or_none(
            signed_pearson_r(pooled_truth, pooled_prediction)
        ),
        "mean_fold_calibration_slope": (
            None
            if any(value is None for value in per_fold_calibration_slope)
            else float(
                np.mean(np.asarray(per_fold_calibration_slope, dtype=np.float64))
            )
        ),
        "pooled_oof_calibration_slope": calibration_slope(
            pooled_truth, pooled_prediction
        ),
    }


def evaluate_fresh_fit(
    X: object,
    y: object,
    groups: object,
    split_plan: FrozenGroupSplitPlan | Mapping[str, object],
    classifier_key: str,
    seed: int,
    engine_path: str | Path | None = None,
    control_mode: str = "observed",
    *,
    term_index: int = 0,
) -> EvaluationReceipt:
    """Fit one episode candidate against a frozen grouped nested-CV plan.

    The function deliberately returns a receipt for *all* expected failures.
    Invalid plans, unavailable estimator engines, disallowed row shuffles, and
    per-fold model errors therefore remain auditable without a separate error
    channel.  It does not perform null inference or claim validation.
    """

    started_at = time.perf_counter()
    normalized_classifier = (
        classifier_key.lower()
        if isinstance(classifier_key, str)
        and classifier_key.strip()
        and classifier_key == classifier_key.strip()
        else "invalid"
    )
    normalized_seed = (
        seed if isinstance(seed, int) and not isinstance(seed, bool) else 0
    )
    normalized_term_index = (
        term_index
        if isinstance(term_index, int)
        and not isinstance(term_index, bool)
        and term_index >= 0
        else 0
    )
    normalized_control = (
        control_mode.lower()
        if isinstance(control_mode, str)
        and control_mode.strip()
        and control_mode == control_mode.strip()
        else "invalid"
    )
    normalized_engine_path: Path | None = None
    features: np.ndarray | None = None
    target: np.ndarray | None = None
    normalized_groups: np.ndarray | None = None
    plan: FrozenGroupSplitPlan | None = None
    folds: list[FoldReceipt] = []
    try:
        normalized_classifier = _coerce_classifier_key(classifier_key)
        normalized_seed = _require_seed(seed)
        normalized_term_index = _require_term_index(term_index)
        normalized_control = _normalize_control_mode(control_mode)
        normalized_engine_path = _path_for_engine(engine_path)
        features, target, normalized_groups = _normalize_inputs(X, y, groups)
        plan = _coerce_split_plan(split_plan)
        plan.validate(n_rows=len(features), groups=normalized_groups)
        y_fit = (
            family_block_shuffle(target, normalized_groups, normalized_seed)
            if normalized_control == "family_block_shuffle"
            else target
        )
        module = _load_engine(str(normalized_engine_path))
        torch_classifiers = frozenset(getattr(module, "MATRIX_ONLY_CLASSIFIERS", ()))
        for outer in plan.outer_splits:
            fold_started_at = time.perf_counter()
            outer_test = np.asarray(outer.test_indices, dtype=np.int64)
            try:
                if normalized_classifier == "cpm":
                    prediction, selection = _cpm_fold(
                        module=module,
                        X=features,
                        y_fit=y_fit,
                        outer=outer,
                        inner_splits=plan.inner_splits[outer.fold_id],
                    )
                elif normalized_classifier in torch_classifiers:
                    prediction, selection = _torch_fold(
                        module=module,
                        classifier_key=normalized_classifier,
                        X=features,
                        y_fit=y_fit,
                        outer=outer,
                        inner_splits=plan.inner_splits[outer.fold_id],
                        seed=normalized_seed,
                    )
                else:
                    prediction, selection = _sklearn_fold(
                        module=module,
                        classifier_key=normalized_classifier,
                        X=features,
                        y_fit=y_fit,
                        outer=outer,
                        inner_splits=plan.inner_splits[outer.fold_id],
                        seed=normalized_seed,
                    )
                # A family-block control is one global relabelling of the
                # target vector.  Its held-out score must use the same frozen
                # relabelling as its training folds, rather than silently
                # comparing shuffled fits to the observed labels.
                metrics = _metric_mapping(y_fit[outer_test], prediction)
                if metrics["signed_pearson_r"] is None:
                    raise FreshFitEvaluationError(
                        "outer signed Pearson r is non-finite"
                    )
                folds.append(
                    FoldReceipt(
                        fold_id=outer.fold_id,
                        status="succeeded",
                        train_size=len(outer.train_indices),
                        test_size=len(outer.test_indices),
                        test_indices=outer.test_indices,
                        y_true=tuple(float(item) for item in y_fit[outer_test]),
                        y_pred=tuple(float(item) for item in prediction),
                        metrics=metrics,
                        selection=selection,
                        runtime_sec=time.perf_counter() - fold_started_at,
                    )
                )
            except Exception as exc:
                folds.append(
                    FoldReceipt(
                        fold_id=outer.fold_id,
                        status="failed",
                        train_size=len(outer.train_indices),
                        test_size=len(outer.test_indices),
                        test_indices=outer.test_indices,
                        y_true=(),
                        y_pred=(),
                        metrics={
                            "signed_pearson_r": None,
                            "r2": None,
                            "mae": None,
                            "calibration_slope": None,
                        },
                        selection={"candidate_count": 0, "selected_params": {}},
                        runtime_sec=time.perf_counter() - fold_started_at,
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                )
                raise
        metrics = _aggregate_metrics(folds)
        return EvaluationReceipt(
            status="succeeded",
            classifier_key=normalized_classifier,
            term_index=normalized_term_index,
            seed=normalized_seed,
            control_mode=normalized_control,
            folds=tuple(folds),
            metrics=metrics,
            runtime_sec=max(0.0, round(time.perf_counter() - started_at, 6)),
        )
    except Exception as exc:
        return _make_failure_receipt(
            classifier_key=normalized_classifier,
            term_index=normalized_term_index,
            seed=normalized_seed,
            control_mode=normalized_control,
            folds=folds,
            runtime_sec=time.perf_counter() - started_at,
            exc=exc,
        )


__all__ = [
    "DEFAULT_ENGINE_PATH",
    "calibration_slope",
    "EvaluationReceipt",
    "FoldReceipt",
    "FreshFitEvaluationError",
    "FrozenGroupSplit",
    "FrozenGroupSplitPlan",
    "controller_aggregate",
    "evaluate_fresh_fit",
    "family_block_shuffle",
    "signed_pearson_r",
]
