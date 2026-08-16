"""Group-safe private/public split plans for the MVE-100 discovery boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.model_selection import GroupKFold

from brain_researcher.research.predictive.foundation_episode.contracts import (
    FoundationEpisodeError,
)

PRIVATE_SPLIT_SCHEMA = "br.foundation_episode.private_split_plan.v1"
PUBLIC_SPLIT_SCHEMA = "br.foundation_episode.public_split_plan.v1"
SEEDED_GROUP_ASSIGNMENT_ALGORITHM = (
    "foundation_mve24_seeded_balanced_group_assignment_v1"
)


def _require_texts(values: Sequence[object], *, label: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise FoundationEpisodeError(f"{label}[{index}] must be non-empty text")
        normalized.append(value)
    if not normalized:
        raise FoundationEpisodeError(f"{label} must not be empty")
    return tuple(normalized)


def _validate_group_disjointness(
    groups: np.ndarray,
    train: np.ndarray,
    test: np.ndarray,
    *,
    label: str,
) -> None:
    if set(groups[train]) & set(groups[test]):
        raise FoundationEpisodeError(
            f"{label} leaks Family_ID groups across train/test"
        )


def _family_test_sets(
    *,
    row_indices: np.ndarray,
    all_groups: np.ndarray,
    rng: np.random.Generator,
    n_splits: int,
) -> list[np.ndarray]:
    """Assign complete families to balanced test folds using one seeded generator."""

    group_to_rows: dict[str, list[int]] = {}
    for row in row_indices.tolist():
        group_to_rows.setdefault(str(all_groups[row]), []).append(int(row))
    if len(group_to_rows) < n_splits:
        raise FoundationEpisodeError(
            f"replication needs at least {n_splits} families for grouped folds"
        )

    groups = np.asarray(sorted(group_to_rows), dtype=object)
    rng.shuffle(groups)
    ordered_groups = sorted(
        groups.tolist(), key=lambda group: -len(group_to_rows[group])
    )
    assigned: list[list[str]] = [[] for _ in range(n_splits)]
    loads = [0 for _ in range(n_splits)]
    for group in ordered_groups:
        fold = min(range(n_splits), key=lambda candidate: (loads[candidate], candidate))
        assigned[fold].append(group)
        loads[fold] += len(group_to_rows[group])
    return [
        np.asarray(
            sorted(row for group in assigned[fold] for row in group_to_rows[group]),
            dtype=np.int64,
        )
        for fold in range(n_splits)
    ]


def _replication_plan(
    *, discovery_indices: np.ndarray, all_groups: np.ndarray, seed: int
) -> dict[str, object]:
    """Materialize the alternative family-safe 5x3 plan on discovery subjects."""

    rng = np.random.default_rng(seed)
    outer_test_sets = _family_test_sets(
        row_indices=discovery_indices,
        all_groups=all_groups,
        rng=rng,
        n_splits=5,
    )
    universe = {int(row) for row in discovery_indices.tolist()}
    outer_folds: list[dict[str, object]] = []
    for outer_index, test_indices in enumerate(outer_test_sets, start=1):
        train_indices = np.asarray(
            sorted(universe - set(test_indices.tolist())), dtype=np.int64
        )
        _validate_group_disjointness(
            all_groups,
            train_indices,
            test_indices,
            label=f"replication outer {outer_index}",
        )
        inner_test_sets = _family_test_sets(
            row_indices=train_indices,
            all_groups=all_groups,
            rng=rng,
            n_splits=3,
        )
        train_universe = {int(row) for row in train_indices.tolist()}
        inner_folds: list[dict[str, object]] = []
        for inner_index, inner_test in enumerate(inner_test_sets, start=1):
            inner_train = np.asarray(
                sorted(train_universe - set(inner_test.tolist())), dtype=np.int64
            )
            _validate_group_disjointness(
                all_groups,
                inner_train,
                inner_test,
                label=f"replication outer {outer_index} inner {inner_index}",
            )
            inner_folds.append(
                {
                    "fold_id": f"inner_{inner_index}",
                    "train_row_indices": inner_train.tolist(),
                    "test_row_indices": inner_test.tolist(),
                }
            )
        outer_folds.append(
            {
                "fold_id": f"outer_{outer_index}",
                "train_row_indices": train_indices.tolist(),
                "test_row_indices": test_indices.tolist(),
                "inner_folds": inner_folds,
            }
        )
    return {
        "schema_version": "foundation_episode_group_split_plan_v1",
        "splitter": "SeededGroupKFold",
        "seed": seed,
        "assignment_algorithm": SEEDED_GROUP_ASSIGNMENT_ALGORITHM,
        "evaluation_row_indices": discovery_indices.tolist(),
        "outer_folds": outer_folds,
    }


@dataclass(frozen=True, slots=True)
class SplitPlans:
    """Private split selectors plus an identity-free public count summary."""

    private_plan: dict[str, object]
    public_plan: dict[str, object]


def build_group_safe_split_plans(
    *,
    subject_ids: Sequence[object],
    family_ids: Sequence[object],
    seed: int,
) -> SplitPlans:
    """Build a deterministic 75/25 family split and a seed-plus-one replication plan."""

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise FoundationEpisodeError("seed must be a non-negative integer")
    subjects = _require_texts(subject_ids, label="subject_ids")
    families = _require_texts(family_ids, label="family_ids")
    if len(subjects) != len(families):
        raise FoundationEpisodeError(
            "subject_ids and family_ids must have equal length"
        )
    if len(set(subjects)) != len(subjects):
        raise FoundationEpisodeError("subject_ids must be unique")

    family_groups = np.asarray(sorted(set(families)), dtype=object)
    if len(family_groups) < 7:
        raise FoundationEpisodeError(
            "at least seven Family_ID groups are required for 5x3 grouped CV"
        )
    discovery_group_count = int(np.floor(0.75 * len(family_groups) + 0.5))
    if discovery_group_count < 5 or discovery_group_count >= len(family_groups):
        raise FoundationEpisodeError(
            "75/25 discovery / holdout family split is invalid"
        )

    rng = np.random.default_rng(seed)
    rng.shuffle(family_groups)
    discovery_groups = set(family_groups[:discovery_group_count].tolist())
    holdout_groups = set(family_groups[discovery_group_count:].tolist())
    all_groups = np.asarray(families, dtype=str)
    discovery_indices = np.flatnonzero(
        np.asarray([group in discovery_groups for group in families], dtype=bool)
    ).astype(np.int64)
    holdout_indices = np.flatnonzero(
        np.asarray([group in holdout_groups for group in families], dtype=bool)
    ).astype(np.int64)
    if not len(discovery_indices) or not len(holdout_indices):
        raise FoundationEpisodeError("family split produced an empty partition")
    _validate_group_disjointness(
        all_groups, discovery_indices, holdout_indices, label="discovery/holdout"
    )

    discovery_local_groups = all_groups[discovery_indices]
    outer = GroupKFold(n_splits=5)
    outer_folds: list[dict[str, object]] = []
    public_outer_folds: list[dict[str, object]] = []
    placeholder = np.zeros(len(discovery_indices), dtype=np.uint8)
    for fold_index, (train_local, test_local) in enumerate(
        outer.split(placeholder, groups=discovery_local_groups), start=1
    ):
        train_indices = discovery_indices[np.asarray(train_local, dtype=np.int64)]
        test_indices = discovery_indices[np.asarray(test_local, dtype=np.int64)]
        _validate_group_disjointness(
            all_groups, train_indices, test_indices, label=f"outer fold {fold_index}"
        )
        train_groups = all_groups[train_indices]
        inner = GroupKFold(n_splits=3)
        inner_folds: list[dict[str, object]] = []
        public_inner_folds: list[dict[str, object]] = []
        inner_placeholder = np.zeros(len(train_indices), dtype=np.uint8)
        for inner_index, (inner_train_local, inner_test_local) in enumerate(
            inner.split(inner_placeholder, groups=train_groups), start=1
        ):
            inner_train = train_indices[np.asarray(inner_train_local, dtype=np.int64)]
            inner_test = train_indices[np.asarray(inner_test_local, dtype=np.int64)]
            _validate_group_disjointness(
                all_groups,
                inner_train,
                inner_test,
                label=f"outer {fold_index} inner {inner_index}",
            )
            inner_folds.append(
                {
                    "fold": inner_index,
                    "train_row_indices": inner_train.tolist(),
                    "test_row_indices": inner_test.tolist(),
                }
            )
            public_inner_folds.append(
                {
                    "train_row_count": int(len(inner_train)),
                    "test_row_count": int(len(inner_test)),
                    "train_family_count": int(len(set(all_groups[inner_train]))),
                    "test_family_count": int(len(set(all_groups[inner_test]))),
                }
            )
        outer_folds.append(
            {
                "fold": fold_index,
                "train_row_indices": train_indices.tolist(),
                "test_row_indices": test_indices.tolist(),
                "inner_folds": inner_folds,
            }
        )
        public_outer_folds.append(
            {
                "train_row_count": int(len(train_indices)),
                "test_row_count": int(len(test_indices)),
                "train_family_count": int(len(set(all_groups[train_indices]))),
                "test_family_count": int(len(set(all_groups[test_indices]))),
                "inner_folds": public_inner_folds,
            }
        )

    replication_seed = seed + 1
    replication = _replication_plan(
        discovery_indices=discovery_indices,
        all_groups=all_groups,
        seed=replication_seed,
    )
    private_plan: dict[str, object] = {
        "schema_version": PRIVATE_SPLIT_SCHEMA,
        "seed": seed,
        "group_column": "Family_ID",
        "subject_rows": [
            {"row_index": index, "subject_id": subject, "family_id": family}
            for index, (subject, family) in enumerate(
                zip(subjects, families, strict=True)
            )
        ],
        "discovery_row_indices": discovery_indices.tolist(),
        "sealed_holdout_row_indices": holdout_indices.tolist(),
        "outer_folds": outer_folds,
        "replication_seed": replication_seed,
        "replication_split_plan": replication,
    }
    public_plan: dict[str, object] = {
        "schema_version": PUBLIC_SPLIT_SCHEMA,
        "discovery_group_count": int(len(discovery_groups)),
        "sealed_holdout_group_count": int(len(holdout_groups)),
        "discovery_row_count": int(len(discovery_indices)),
        "sealed_holdout_row_count": int(len(holdout_indices)),
        "outer_folds": public_outer_folds,
        "replication_split": {
            "outer_fold_count": int(len(replication["outer_folds"])),
            "inner_fold_count": 3,
            "evaluation_row_count": int(len(discovery_indices)),
        },
    }
    return SplitPlans(private_plan=private_plan, public_plan=public_plan)


__all__ = [
    "PRIVATE_SPLIT_SCHEMA",
    "PUBLIC_SPLIT_SCHEMA",
    "SplitPlans",
    "build_group_safe_split_plans",
]
