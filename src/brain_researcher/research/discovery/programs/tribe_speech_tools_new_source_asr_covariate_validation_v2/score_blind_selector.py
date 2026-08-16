"""Exact score-blind minimax panel selector retained from the v2 program."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .contracts import (
    ACOUSTIC_FEATURES,
    CONDITIONS,
    ITEMS_PER_CONDITION_COLLECTION,
    MAX_ACOUSTIC_BALANCE_DIFFERENCE,
    MIN_POOL_ITEMS_PER_CONDITION_COLLECTION,
    SELECTED_ITEM_COUNT,
    SOURCE_COLLECTION_COUNT,
    CandidatePoolIntakeBindingV2,
    CandidatePoolItemBindingV2,
)

_OPTIMALITY_TOLERANCE = 1e-9
_BALANCE_TOLERANCE = 1e-8


class NewSourceMaterializationError(ValueError):
    """The score-blind candidate pool cannot be materialized."""


class NoFeasibleScoreBlindSelection(NewSourceMaterializationError):
    """No exact 48-row panel satisfies the frozen score-blind constraints."""


@dataclass(frozen=True, slots=True)
class AcousticBalanceResult:
    scope: str
    feature: str
    eligible_pool_size: int
    standardized_mean_difference: float


@dataclass(frozen=True, slots=True)
class ScoreBlindPanelSelection:
    selected_candidate_keys: tuple[str, ...]
    acoustic_balance: tuple[AcousticBalanceResult, ...]
    observed_max_absolute_standardized_mean_difference: float

    def to_contract_selection(self) -> dict[str, object]:
        return {
            "method_id": "score_blind_minimax_acoustic_balance_v1",
            "score_blind": True,
            "uses_tribe_features": False,
            "uses_frozen_axis_geometry": False,
            "uses_hypothesis_outcomes": False,
            "max_absolute_standardized_mean_difference": (
                MAX_ACOUSTIC_BALANCE_DIFFERENCE
            ),
            "selected_candidate_keys": list(self.selected_candidate_keys),
        }


def select_score_blind_panel(
    intake: CandidatePoolIntakeBindingV2,
) -> ScoreBlindPanelSelection:
    """Mechanically retained minimax-plus-lexicographic selection."""

    candidates, collection_keys = _validated_intake_candidates(intake)
    selected = _solve_deterministic_minimax(candidates, collection_keys)
    balance = _compute_acoustic_balance(
        selected=selected,
        candidates=candidates,
        collection_keys=collection_keys,
    )
    observed_max = max(abs(row.standardized_mean_difference) for row in balance)
    if observed_max > MAX_ACOUSTIC_BALANCE_DIFFERENCE + _BALANCE_TOLERANCE:
        raise NoFeasibleScoreBlindSelection(
            "selected panel exceeds the frozen acoustic balance threshold"
        )
    return ScoreBlindPanelSelection(
        selected_candidate_keys=tuple(candidate.candidate_key for candidate in selected),
        acoustic_balance=balance,
        observed_max_absolute_standardized_mean_difference=observed_max,
    )


def _validated_intake_candidates(
    intake: CandidatePoolIntakeBindingV2,
) -> tuple[tuple[CandidatePoolItemBindingV2, ...], tuple[str, ...]]:
    if not isinstance(intake, CandidatePoolIntakeBindingV2):
        raise NewSourceMaterializationError(
            "intake must be a validated CandidatePoolIntakeBindingV2"
        )
    collection_keys = tuple(sorted(intake.source_collection_keys))
    if len(collection_keys) != SOURCE_COLLECTION_COUNT or len(set(collection_keys)) != len(
        collection_keys
    ):
        raise NewSourceMaterializationError("intake must bind exactly four collections")
    candidates = tuple(sorted(intake.candidates, key=lambda item: item.candidate_key))
    if intake.candidate_pool_count != len(candidates):
        raise NewSourceMaterializationError("intake candidate count is inconsistent")
    counts = Counter((item.collection_key, item.condition) for item in candidates)
    for collection_key in collection_keys:
        for condition in CONDITIONS:
            if counts[(collection_key, condition)] < MIN_POOL_ITEMS_PER_CONDITION_COLLECTION:
                raise NewSourceMaterializationError(
                    "intake has fewer than 12 candidates in a required cell"
                )
            segment_counts = {
                item.whisperx_segment_count
                for item in candidates
                if item.collection_key == collection_key and item.condition == condition
            }
            if len(segment_counts) < 2:
                raise NoFeasibleScoreBlindSelection(
                    "pre-TRIBE segment count lacks within-cell variation"
                )
    return candidates, collection_keys


def _solver_constraints(
    candidates: Sequence[CandidatePoolItemBindingV2],
    collection_keys: Sequence[str],
):
    try:
        from scipy.optimize import LinearConstraint
    except ImportError as exc:  # pragma: no cover
        raise NewSourceMaterializationError(
            "score-blind selection requires scipy; install the analysis extras"
        ) from exc
    segment_keys = tuple(
        (collection_key, condition, segment_count)
        for collection_key in collection_keys
        for condition in CONDITIONS
        for segment_count in sorted(
            {
                candidate.whisperx_segment_count
                for candidate in candidates
                if candidate.collection_key == collection_key
                and candidate.condition == condition
            }
        )
    )
    n_candidates = len(candidates)
    segment_variable = {
        key: n_candidates + index for index, key in enumerate(segment_keys)
    }
    t_index = n_candidates + len(segment_keys)
    n_variables = t_index + 1
    rows: list[np.ndarray] = []
    lower: list[float] = []
    upper: list[float] = []
    for collection_key in collection_keys:
        for condition in CONDITIONS:
            cell_indices = [
                index
                for index, candidate in enumerate(candidates)
                if candidate.collection_key == collection_key
                and candidate.condition == condition
            ]
            count_row = np.zeros(n_variables, dtype=float)
            count_row[cell_indices] = 1.0
            rows.append(count_row)
            lower.append(float(ITEMS_PER_CONDITION_COLLECTION))
            upper.append(float(ITEMS_PER_CONDITION_COLLECTION))
            cell_segment_keys = [
                key
                for key in segment_keys
                if key[0] == collection_key and key[1] == condition
            ]
            for key in cell_segment_keys:
                value_indices = [
                    index
                    for index in cell_indices
                    if candidates[index].whisperx_segment_count == key[2]
                ]
                present_index = segment_variable[key]
                lower_link = np.zeros(n_variables, dtype=float)
                lower_link[value_indices] = 1.0
                lower_link[present_index] = -1.0
                rows.append(lower_link)
                lower.append(0.0)
                upper.append(np.inf)
                upper_link = np.zeros(n_variables, dtype=float)
                upper_link[value_indices] = 1.0
                upper_link[present_index] = -float(ITEMS_PER_CONDITION_COLLECTION)
                rows.append(upper_link)
                lower.append(-np.inf)
                upper.append(0.0)
            diversity_row = np.zeros(n_variables, dtype=float)
            for key in cell_segment_keys:
                diversity_row[segment_variable[key]] = 1.0
            rows.append(diversity_row)
            lower.append(2.0)
            upper.append(np.inf)
    parent_indices: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        parent_indices.setdefault(candidate.parent_key, []).append(index)
    for indices in parent_indices.values():
        if len(indices) < 2:
            continue
        parent_row = np.zeros(n_variables, dtype=float)
        parent_row[indices] = 1.0
        rows.append(parent_row)
        lower.append(-np.inf)
        upper.append(1.0)
    for scope in (*collection_keys, "pooled"):
        pool = [
            candidate
            for candidate in candidates
            if scope == "pooled" or candidate.collection_key == scope
        ]
        selected_count = (
            ITEMS_PER_CONDITION_COLLECTION
            if scope != "pooled"
            else ITEMS_PER_CONDITION_COLLECTION * len(collection_keys)
        )
        for feature in ACOUSTIC_FEATURES:
            values = np.asarray(
                [dict(candidate.acoustic_features)[feature] for candidate in pool],
                dtype=float,
            )
            mean = float(np.mean(values))
            scale = float(np.std(values, ddof=0))
            if scale == 0.0:
                scale = 1.0
            balance_row = np.zeros(n_variables, dtype=float)
            for index, candidate in enumerate(candidates):
                if scope != "pooled" and candidate.collection_key != scope:
                    continue
                sign = 1.0 if candidate.condition == "speech" else -1.0
                value = dict(candidate.acoustic_features)[feature]
                balance_row[index] = sign * (value - mean) / (selected_count * scale)
            balance_row[t_index] = -1.0
            rows.append(balance_row)
            lower.append(-np.inf)
            upper.append(0.0)
            inverse = -balance_row.copy()
            inverse[t_index] = -1.0
            rows.append(inverse)
            lower.append(-np.inf)
            upper.append(0.0)
    lower_bounds = np.zeros(n_variables, dtype=float)
    upper_bounds = np.ones(n_variables, dtype=float)
    upper_bounds[t_index] = MAX_ACOUSTIC_BALANCE_DIFFERENCE
    integrality = np.asarray([1] * (n_candidates + len(segment_keys)) + [0], dtype=int)
    return (
        LinearConstraint(np.vstack(rows), np.asarray(lower), np.asarray(upper)),
        lower_bounds,
        upper_bounds,
        integrality,
        t_index,
    )


def _run_milp(
    objective: np.ndarray,
    *,
    constraints: Sequence[object],
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    integrality: np.ndarray,
    forced: Mapping[int, int] | None = None,
):
    try:
        from scipy.optimize import Bounds, milp
    except ImportError as exc:  # pragma: no cover
        raise NewSourceMaterializationError(
            "score-blind selection requires scipy; install the analysis extras"
        ) from exc
    lower = lower_bounds.copy()
    upper = upper_bounds.copy()
    for index, value in (forced or {}).items():
        lower[index] = value
        upper[index] = value
    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=list(constraints),
        options={"disp": False},
    )
    if result.success and result.x is not None:
        return result
    if result.status == 2:
        raise NoFeasibleScoreBlindSelection(
            "no panel satisfies count, parent, ASR-diversity, and acoustic constraints"
        )
    raise NewSourceMaterializationError("score-blind selection solver did not complete")


def _solve_deterministic_minimax(
    candidates: Sequence[CandidatePoolItemBindingV2],
    collection_keys: Sequence[str],
) -> tuple[CandidatePoolItemBindingV2, ...]:
    try:
        from scipy.optimize import LinearConstraint
    except ImportError as exc:  # pragma: no cover
        raise NewSourceMaterializationError(
            "score-blind selection requires scipy; install the analysis extras"
        ) from exc
    candidates = tuple(sorted(candidates, key=lambda candidate: candidate.candidate_key))
    constraint, lower_bounds, upper_bounds, integrality, t_index = _solver_constraints(
        candidates, collection_keys
    )
    objective = np.zeros(len(lower_bounds), dtype=float)
    objective[t_index] = 1.0
    first = _run_milp(
        objective,
        constraints=(constraint,),
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        integrality=integrality,
    )
    optimum = float(first.x[t_index])
    optimum_row = np.zeros(len(lower_bounds), dtype=float)
    optimum_row[t_index] = 1.0
    constraints = (
        constraint,
        LinearConstraint(
            optimum_row,
            -np.inf,
            min(MAX_ACOUSTIC_BALANCE_DIFFERENCE, optimum + _OPTIMALITY_TOLERANCE),
        ),
    )
    forced: dict[int, int] = {}
    zero_objective = np.zeros(len(lower_bounds), dtype=float)
    for index in range(len(candidates)):
        proposed = {**forced, index: 1}
        try:
            _run_milp(
                zero_objective,
                constraints=constraints,
                lower_bounds=lower_bounds,
                upper_bounds=upper_bounds,
                integrality=integrality,
                forced=proposed,
            )
        except NoFeasibleScoreBlindSelection:
            forced[index] = 0
        else:
            forced[index] = 1
        if sum(forced.values()) == SELECTED_ITEM_COUNT:
            forced.update(dict.fromkeys(range(index + 1, len(candidates)), 0))
            break
    if len(forced) != len(candidates) or sum(forced.values()) != SELECTED_ITEM_COUNT:
        raise NoFeasibleScoreBlindSelection(
            "deterministic tie-break could not construct an exact 48-row panel"
        )
    return tuple(candidate for index, candidate in enumerate(candidates) if forced[index])


def _compute_acoustic_balance(
    *,
    selected: Sequence[CandidatePoolItemBindingV2],
    candidates: Sequence[CandidatePoolItemBindingV2],
    collection_keys: Sequence[str],
) -> tuple[AcousticBalanceResult, ...]:
    rows: list[AcousticBalanceResult] = []
    for scope in (*collection_keys, "pooled"):
        eligible_pool = [
            candidate
            for candidate in candidates
            if scope == "pooled" or candidate.collection_key == scope
        ]
        selected_pool = [
            candidate
            for candidate in selected
            if scope == "pooled" or candidate.collection_key == scope
        ]
        for feature in ACOUSTIC_FEATURES:
            eligible_values = np.asarray(
                [
                    dict(candidate.acoustic_features)[feature]
                    for candidate in eligible_pool
                ],
                dtype=float,
            )
            scale = float(np.std(eligible_values, ddof=0))
            if scale == 0.0:
                scale = 1.0
            speech = [
                dict(candidate.acoustic_features)[feature]
                for candidate in selected_pool
                if candidate.condition == "speech"
            ]
            tools = [
                dict(candidate.acoustic_features)[feature]
                for candidate in selected_pool
                if candidate.condition == "tools"
            ]
            smd = (float(np.mean(speech)) - float(np.mean(tools))) / scale
            rows.append(
                AcousticBalanceResult(
                    scope=scope,
                    feature=feature,
                    eligible_pool_size=len(eligible_pool),
                    standardized_mean_difference=smd,
                )
            )
    return tuple(rows)


__all__ = [
    "AcousticBalanceResult",
    "NewSourceMaterializationError",
    "NoFeasibleScoreBlindSelection",
    "ScoreBlindPanelSelection",
    "select_score_blind_panel",
]
