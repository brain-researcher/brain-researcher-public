"""Exact geometry and permutation evaluator for the public TRIBE v2 design.

This is a mechanical publicization of the private D/S/C/AUC, H1/H2/H3/H5,
balanced-label permutation, within-cell permutation, and Holm calculations.
Only the input identities and runtime boundary are parameterized.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations, permutations
from typing import Any

import numpy as np

from .contracts import (
    CONDITIONS,
    EARLY_LAYERS,
    FEATURE_DIMENSION,
    FROZEN_HYPOTHESIS_FAMILIES,
    INFERENCE_ALPHA,
    ITEMS_PER_CONDITION_COLLECTION,
    LATE_LAYERS,
    LOCKED_LAYERS,
    PROGRAM_ID,
    SOURCE_COLLECTION_COUNT,
    FrozenReferenceBindingV2,
    SourceFeasibilityBindingV2,
    SourceFeasibilityContractError,
    is_validator_issued_binding,
    validate_inference_config,
)

EVALUATION_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.new_source_evaluation.v2"
)
REFERENCE_TOTAL_ROWS = 48
REFERENCE_ROWS_PER_TARGET_CONDITION = 8
_BALANCED_MASKS = np.zeros((924, 12), dtype=bool)
for _mask_index, _selection in enumerate(combinations(range(12), 6)):
    _BALANCED_MASKS[_mask_index, list(_selection)] = True
_SIX_PERMUTATIONS = np.asarray(tuple(permutations(range(6))), dtype=int)


class FrozenHypothesisEvaluationError(ValueError):
    """The supplied public arrays cannot support the frozen v2 evaluation."""


def _invalid_result(*, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "evaluation_status": "invalid",
        "outcome": "invalid",
        "invalid_reason": {"code": code, "message": message},
        "inference_unit": (
            "item_label_permutations_conditional_on_fixed_four_source_panel"
        ),
        "source_population_inference": False,
        "three_of_four_source_gate_role": "stability_only_not_source_level_p_value",
        "authority_granted": False,
        "launch_authorized": False,
        "gpu_authorized": False,
        "tribe_inference_authorized": False,
        "manuscript_update_authorized": False,
        "registration_authorized": False,
        "execution_authorized": False,
        "confirmation_authorized": False,
    }


def _require_matrix(
    value: Any, *, label: str, expected_rows: int, expected_dimension: int | None
) -> np.ndarray:
    matrix = np.asarray(value, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != expected_rows:
        raise FrozenHypothesisEvaluationError(
            f"{label} must be a finite two-dimensional matrix with {expected_rows} rows"
        )
    if expected_dimension is not None and matrix.shape[1] != expected_dimension:
        raise FrozenHypothesisEvaluationError(
            f"{label} does not match the corresponding reference feature dimension"
        )
    if matrix.shape[1] == 0 or not np.all(np.isfinite(matrix)):
        raise FrozenHypothesisEvaluationError(f"{label} must be finite and non-empty")
    return matrix


def _midranks(values: np.ndarray) -> np.ndarray:
    """Return one-based average ranks, retaining ties as midranks."""

    order = np.argsort(values, kind="mergesort")
    ranked = np.empty(values.shape[0], dtype=float)
    sorted_values = values[order]
    start = 0
    while start < values.shape[0]:
        end = start + 1
        while end < values.shape[0] and sorted_values[end] == sorted_values[start]:
            end += 1
        ranked[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranked


def _pearson(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.shape != right.shape or left.ndim != 1 or left.size < 2:
        return None
    centered_left = left - float(left.mean())
    centered_right = right - float(right.mean())
    denominator = float(np.linalg.norm(centered_left) * np.linalg.norm(centered_right))
    if not np.isfinite(denominator) or denominator <= 0.0:
        return None
    value = float(np.dot(centered_left, centered_right) / denominator)
    return value if np.isfinite(value) else None


def _roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    labels = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    if labels.shape != scores.shape or labels.ndim != 1:
        raise FrozenHypothesisEvaluationError("ROC AUC inputs must have equal shape")
    n_positive = int(labels.sum())
    n_negative = int(labels.shape[0] - n_positive)
    if n_positive == 0 or n_negative == 0:
        raise FrozenHypothesisEvaluationError("ROC AUC requires both conditions")
    ranks = _midranks(scores)
    return float(
        (ranks[labels].sum() - n_positive * (n_positive + 1) / 2.0)
        / (n_positive * n_negative)
    )


def _rows(value: Any, *, label: str) -> list[Mapping[str, Any]]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise FrozenHypothesisEvaluationError(f"{label} rows must be a list")
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise FrozenHypothesisEvaluationError(f"{label}[{index}] must be an object")
        rows.append(row)
    return rows


def _row_string(row: Mapping[str, Any], field: str, *, label: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FrozenHypothesisEvaluationError(f"{label}.{field} must be non-empty text")
    return value.strip()


def _validate_inference_binding(
    *,
    feasibility_binding: SourceFeasibilityBindingV2 | None,
    reference_binding: FrozenReferenceBindingV2 | None,
    reference_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
) -> SourceFeasibilityBindingV2:
    if not is_validator_issued_binding(feasibility_binding):
        raise FrozenHypothesisEvaluationError(
            "inferential evaluation requires a validator-issued feasibility binding"
        )
    assert isinstance(feasibility_binding, SourceFeasibilityBindingV2)
    if reference_binding is not feasibility_binding.frozen_reference:
        raise FrozenHypothesisEvaluationError(
            "inferential evaluation must use the feasibility-bound reference"
        )
    bound_reference_rows = tuple(
        (row.row_key, row.condition)
        for row in feasibility_binding.frozen_reference.item_rows
    )
    supplied_reference_rows = tuple(
        (
            _row_string(row, "row_key", label=f"reference[{index}]"),
            _row_string(row, "condition", label=f"reference[{index}]"),
        )
        for index, row in enumerate(reference_rows)
    )
    if supplied_reference_rows != bound_reference_rows:
        raise FrozenHypothesisEvaluationError(
            "reference rows do not match the feasibility-bound reference"
        )
    bound_evaluation_rows = tuple(
        (
            row.row_key,
            row.collection_key,
            row.condition,
            row.whisperx_segment_count,
        )
        for row in feasibility_binding.evaluation_item_rows
    )
    supplied_evaluation_rows = tuple(
        (
            _row_string(row, "row_key", label=f"evaluation[{index}]"),
            _row_string(row, "collection_key", label=f"evaluation[{index}]"),
            _row_string(row, "condition", label=f"evaluation[{index}]"),
            row.get("whisperx_segment_count"),
        )
        for index, row in enumerate(evaluation_rows)
    )
    if supplied_evaluation_rows != bound_evaluation_rows:
        raise FrozenHypothesisEvaluationError(
            "evaluation rows do not match the selected-panel binding"
        )
    return feasibility_binding


def _reference_geometry(
    reference_matrices: Mapping[str, np.ndarray],
    reference_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if len(reference_rows) != REFERENCE_TOTAL_ROWS:
        raise FrozenHypothesisEvaluationError(
            "frozen reference must contain 48 rows"
        )
    conditions = [
        _row_string(row, "condition", label=f"reference[{index}]")
        for index, row in enumerate(reference_rows)
    ]
    speech_indices = [
        index for index, condition in enumerate(conditions) if condition == "speech"
    ]
    tool_indices = [
        index for index, condition in enumerate(conditions) if condition == "tools"
    ]
    if (
        len(speech_indices) != REFERENCE_ROWS_PER_TARGET_CONDITION
        or len(tool_indices) != REFERENCE_ROWS_PER_TARGET_CONDITION
    ):
        raise FrozenHypothesisEvaluationError(
            "frozen reference must contain exactly eight speech and eight tools rows"
        )
    geometry: dict[str, dict[str, Any]] = {}
    for layer_id, matrix in reference_matrices.items():
        speech = matrix[speech_indices]
        tools = matrix[tool_indices]
        speech_centroid = speech.mean(axis=0)
        tools_centroid = tools.mean(axis=0)
        axis = speech_centroid - tools_centroid
        residuals = np.concatenate((speech - speech_centroid, tools - tools_centroid))
        dispersion = float(np.sqrt(np.mean(np.sum(residuals**2, axis=1))))
        axis_norm = float(np.linalg.norm(axis))
        if dispersion <= 0.0 or not np.isfinite(dispersion):
            raise FrozenHypothesisEvaluationError(
                f"reference dispersion must be positive for {layer_id}"
            )
        if axis_norm <= 0.0 or not np.isfinite(axis_norm):
            raise FrozenHypothesisEvaluationError(
                f"reference speech-tools axis must be non-zero for {layer_id}"
            )
        geometry[layer_id] = {
            "axis": axis,
            "axis_norm": axis_norm,
            "dispersion": dispersion,
        }
    return geometry


def _family_mean(
    records: Mapping[str, Mapping[str, float]], layer_ids: Sequence[str], field: str
) -> float:
    return float(np.mean([records[layer_id][field] for layer_id in layer_ids]))


def _pairwise_profile(
    matrix: np.ndarray, item_index: int, cell_indices: Sequence[int]
) -> np.ndarray:
    peers = [index for index in cell_indices if index != item_index]
    return np.linalg.norm(matrix[peers] - matrix[item_index], axis=1)


def _item_family_concordance(
    matrices: Mapping[str, np.ndarray],
    *,
    item_index: int,
    cell_indices: Sequence[int],
    layer_ids: Sequence[str],
) -> float | None:
    profiles = [
        _pairwise_profile(matrices[layer_id], item_index, cell_indices)
        for layer_id in layer_ids
    ]
    values = [
        _pearson(profiles[left], profiles[right])
        for left, right in combinations(range(len(profiles)), 2)
    ]
    if any(value is None for value in values):
        return None
    return float(np.mean(np.asarray(values, dtype=float)))


def _leave_self_out_mean(
    matrix: np.ndarray, indices: Sequence[int], dispersion: float
) -> float:
    values: list[float] = []
    for item_index in indices:
        peers = [index for index in indices if index != item_index]
        centroid = matrix[peers].mean(axis=0)
        values.append(float(np.linalg.norm(matrix[item_index] - centroid) / dispersion))
    return float(np.mean(values))


def _observed_source_result(
    *,
    source_id: str,
    speech_indices: Sequence[int],
    tool_indices: Sequence[int],
    evaluation: Mapping[str, np.ndarray],
    geometry: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    all_indices = list(speech_indices) + list(tool_indices)
    layer_records: dict[str, dict[str, float]] = {}
    residuals: dict[str, dict[str, list[float]]] = {
        "early": {"speech": [], "tools": []},
        "late": {"speech": [], "tools": []},
    }
    for layer_id in LOCKED_LAYERS:
        matrix = evaluation[layer_id]
        speech = matrix[list(speech_indices)]
        tools = matrix[list(tool_indices)]
        axis = np.asarray(geometry[layer_id]["axis"], dtype=float)
        axis_norm = float(geometry[layer_id]["axis_norm"])
        dispersion = float(geometry[layer_id]["dispersion"])
        delta = speech.mean(axis=0) - tools.mean(axis=0)
        delta_norm = float(np.linalg.norm(delta))
        dot = float(np.dot(axis, delta))
        layer_records[layer_id] = {
            "S": float(delta_norm / dispersion),
            "C": float(dot / (axis_norm * delta_norm)) if delta_norm > 0.0 else 0.0,
            "G": float(dot / (axis_norm * dispersion)),
            "frozen_reference_auc": _roc_auc(
                np.asarray([True] * len(speech_indices) + [False] * len(tool_indices)),
                matrix[all_indices] @ axis,
            ),
        }
        family = "early" if layer_id in EARLY_LAYERS else "late"
        residuals[family]["speech"].append(
            _leave_self_out_mean(matrix, speech_indices, dispersion)
        )
        residuals[family]["tools"].append(
            _leave_self_out_mean(matrix, tool_indices, dispersion)
        )
    families = {
        family: {
            field: _family_mean(layer_records, layer_ids, field)
            for field in ("S", "C", "G", "frozen_reference_auc")
        }
        for family, layer_ids in (("early", EARLY_LAYERS), ("late", LATE_LAYERS))
    }
    residual_means = {
        family: {
            condition: float(np.mean(values))
            for condition, values in residuals[family].items()
        }
        for family in ("early", "late")
    }
    h5_value = float(
        (residual_means["late"]["tools"] - residual_means["early"]["tools"])
        - (residual_means["late"]["speech"] - residual_means["early"]["speech"])
    )
    return {
        "collection_key": source_id,
        "layers": [
            {"layer_id": layer_id, **layer_records[layer_id]}
            for layer_id in LOCKED_LAYERS
        ],
        "families": families,
        "delta_s": float(families["late"]["S"] - families["early"]["S"]),
        "delta_auc": float(
            families["late"]["frozen_reference_auc"]
            - families["early"]["frozen_reference_auc"]
        ),
        "leave_self_out_residual_difference_in_differences": h5_value,
    }


def _mean_lso_from_gram(
    gram: np.ndarray, mask: np.ndarray, dispersion: float
) -> np.ndarray:
    float_mask = mask.astype(float)
    group_dot_each_item = float_mask @ gram
    group_squared_norm = np.sum(group_dot_each_item * float_mask, axis=1)
    squared = (
        36.0 * np.diag(gram)[None, :]
        - 12.0 * group_dot_each_item
        + group_squared_norm[:, None]
    ) / 25.0
    residual = np.sqrt(np.maximum(squared, 0.0))
    return np.sum(residual * float_mask, axis=1) / 6.0 / dispersion


def _balanced_source_statistics(
    *,
    source_indices: Sequence[int],
    evaluation: Mapping[str, np.ndarray],
    geometry: Mapping[str, Mapping[str, Any]],
) -> dict[str, np.ndarray]:
    """Precompute all 924 balanced-label outcomes from Gram matrices."""

    mask = _BALANCED_MASKS
    contrast = mask.astype(float) * 2.0 - 1.0
    families: dict[str, dict[str, list[np.ndarray]]] = {
        "early": {"S": [], "C": [], "AUC": [], "speech_lso": [], "tools_lso": []},
        "late": {"S": [], "C": [], "AUC": [], "speech_lso": [], "tools_lso": []},
    }
    for layer_id in LOCKED_LAYERS:
        data = evaluation[layer_id][list(source_indices)]
        gram = data @ data.T
        ref = geometry[layer_id]
        dispersion = float(ref["dispersion"])
        axis_norm = float(ref["axis_norm"])
        scores = data @ np.asarray(ref["axis"], dtype=float)
        delta_squared_norm = np.einsum("bi,ij,bj->b", contrast, gram, contrast) / 36.0
        delta_norm = np.sqrt(np.maximum(delta_squared_norm, 0.0))
        dot = contrast @ scores / 6.0
        family = "early" if layer_id in EARLY_LAYERS else "late"
        families[family]["S"].append(delta_norm / dispersion)
        families[family]["C"].append(
            np.divide(
                dot,
                axis_norm * delta_norm,
                out=np.zeros_like(dot),
                where=delta_norm > 0.0,
            )
        )
        score_ranks = _midranks(scores)
        families[family]["AUC"].append((mask @ score_ranks - 21.0) / 36.0)
        families[family]["speech_lso"].append(
            _mean_lso_from_gram(gram, mask, dispersion)
        )
        families[family]["tools_lso"].append(
            _mean_lso_from_gram(gram, ~mask, dispersion)
        )
    means = {
        family: {
            field: np.mean(np.stack(values, axis=0), axis=0)
            for field, values in records.items()
        }
        for family, records in families.items()
    }
    return {
        "delta_s": means["late"]["S"] - means["early"]["S"],
        "delta_auc": means["late"]["AUC"] - means["early"]["AUC"],
        "h5": (
            (means["late"]["tools_lso"] - means["early"]["tools_lso"])
            - (means["late"]["speech_lso"] - means["early"]["speech_lso"])
        ),
    }


def _monte_carlo_p_value(
    observed: float, null_values: np.ndarray, *, lower_tail: bool
) -> float:
    if lower_tail:
        extreme = int(np.count_nonzero(null_values <= observed))
    else:
        extreme = int(np.count_nonzero(null_values >= observed))
    return float((1 + extreme) / (1 + null_values.size))


def _holm_adjusted_pvalues(raw_p_values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(raw_p_values, key=raw_p_values.__getitem__)
    adjusted: dict[str, float] = {}
    running = 0.0
    family_count = len(ordered)
    for rank, family_id in enumerate(ordered):
        running = max(running, (family_count - rank) * raw_p_values[family_id])
        adjusted[family_id] = min(1.0, float(running))
    return adjusted


def _balanced_label_permutation_p_values(
    source_statistics: Sequence[Mapping[str, np.ndarray]],
    *,
    observed_h1: float,
    observed_h2: float,
    observed_h5: float,
    inference: Mapping[str, Any],
) -> dict[str, float]:
    draws = int(inference["family_tests"]["H1"]["draws"])
    rng = np.random.Generator(
        np.random.PCG64(int(inference["family_tests"]["H1"]["seed"]))
    )
    selected = rng.integers(
        0, len(_BALANCED_MASKS), size=(draws, len(source_statistics))
    )
    null_h1 = np.zeros(draws, dtype=float)
    null_h2 = np.zeros(draws, dtype=float)
    null_h5 = np.zeros(draws, dtype=float)
    for source_index, statistics in enumerate(source_statistics):
        selected_indices = selected[:, source_index]
        null_h1 += statistics["delta_s"][selected_indices]
        null_h2 += statistics["delta_auc"][selected_indices]
        null_h5 += statistics["h5"][selected_indices]
    divisor = float(len(source_statistics))
    return {
        "H1": _monte_carlo_p_value(observed_h1, null_h1 / divisor, lower_tail=True),
        "H2": _monte_carlo_p_value(observed_h2, null_h2 / divisor, lower_tail=True),
        "H5": _monte_carlo_p_value(observed_h5, null_h5 / divisor, lower_tail=False),
    }


def _h3_observed(
    records: Sequence[Mapping[str, Any]],
) -> tuple[
    float | None,
    dict[str, float | None],
    list[str],
    np.ndarray | None,
    np.ndarray | None,
    list[list[int]],
]:
    cell_positions: dict[tuple[str, str], list[int]] = {}
    for position, record in enumerate(records):
        cell_positions.setdefault(
            (str(record["collection_key"]), str(record["condition"])), []
        ).append(position)
    x_residual = np.empty(len(records), dtype=float)
    no_variation: list[str] = []
    ordered_cells: list[list[int]] = []
    for (source_id, condition), positions in sorted(cell_positions.items()):
        x = np.asarray(
            [records[position]["whisperx_segment_count"] for position in positions],
            dtype=float,
        )
        if len(set(x.tolist())) < 2:
            no_variation.append(f"{source_id}/{condition}")
        x_ranked = _midranks(x)
        x_residual[positions] = x_ranked - float(x_ranked.mean())
        ordered_cells.append(positions)
    if any(record["delta_pairwise_concordance"] is None for record in records):
        return (
            None,
            {},
            no_variation + ["degenerate_pairwise_concordance"],
            None,
            None,
            ordered_cells,
        )
    y_residual = np.empty(len(records), dtype=float)
    for positions in ordered_cells:
        y = np.asarray(
            [records[position]["delta_pairwise_concordance"] for position in positions],
            dtype=float,
        )
        y_ranked = _midranks(y)
        y_residual[positions] = y_ranked - float(y_ranked.mean())
    if no_variation:
        return None, {}, no_variation, None, None, ordered_cells
    source_correlations: dict[str, float | None] = {}
    for source_id in sorted({str(record["collection_key"]) for record in records}):
        positions = [
            position
            for position, record in enumerate(records)
            if record["collection_key"] == source_id
        ]
        source_correlations[source_id] = _pearson(
            x_residual[positions], y_residual[positions]
        )
    return (
        _pearson(x_residual, y_residual),
        source_correlations,
        [],
        x_residual,
        y_residual,
        ordered_cells,
    )


def _h3_permutation_p_value(
    *,
    observed: float,
    x_residual: np.ndarray,
    y_residual: np.ndarray,
    cells: Sequence[Sequence[int]],
    inference: Mapping[str, Any],
) -> float:
    draws = int(inference["family_tests"]["H3"]["draws"])
    rng = np.random.Generator(
        np.random.PCG64(int(inference["family_tests"]["H3"]["seed"]))
    )
    numerator = np.zeros(draws, dtype=float)
    x_squared_norm = 0.0
    for positions in cells:
        positions_array = np.asarray(positions, dtype=int)
        local_x = x_residual[positions_array]
        local_y = y_residual[positions_array]
        permutation_indices = rng.integers(0, len(_SIX_PERMUTATIONS), size=draws)
        numerator += local_x[_SIX_PERMUTATIONS[permutation_indices]] @ local_y
        x_squared_norm += float(np.dot(local_x, local_x))
    denominator = float(np.sqrt(x_squared_norm * np.dot(y_residual, y_residual)))
    if denominator <= 0.0 or not np.isfinite(denominator):
        raise FrozenHypothesisEvaluationError("H3 residual variance is non-positive")
    return _monte_carlo_p_value(observed, numerator / denominator, lower_tail=True)


def _family_result(
    *,
    estimable: bool,
    directional_support: bool,
    stability_support: bool,
    compute_inference: bool,
    raw_p_value: float | None,
    holm_adjusted_p_value: float | None,
    inference_kind: str,
    **fields: Any,
) -> dict[str, Any]:
    if not estimable:
        status = "not_estimable"
        inference_status = "not_run_not_estimable"
    elif not compute_inference:
        status = "not_supported"
        inference_status = "not_run_design_fixture"
    else:
        status = (
            "supported"
            if directional_support
            and stability_support
            and holm_adjusted_p_value is not None
            and holm_adjusted_p_value <= INFERENCE_ALPHA
            else "not_supported"
        )
        inference_status = "frozen_permutation_complete"
    return {
        "status": status,
        "inference_status": inference_status,
        "inference_kind": inference_kind,
        "directional_support": directional_support,
        "stability_support": stability_support,
        "raw_permutation_p_value": raw_p_value,
        "holm_adjusted_p_value": holm_adjusted_p_value,
        **fields,
    }


def _evaluate_frozen_hypothesis_families(
    *,
    reference_matrices: Mapping[str, Any],
    evaluation_matrices: Mapping[str, Any],
    item_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    inference: Mapping[str, Any],
    execution_kind: str,
    compute_inference: bool,
    feasibility_binding: SourceFeasibilityBindingV2 | None,
    reference_binding: FrozenReferenceBindingV2 | None,
) -> dict[str, Any]:
    if not isinstance(compute_inference, bool):
        raise FrozenHypothesisEvaluationError("compute_inference must be a boolean")
    reference_rows = _rows(item_rows.get("reference"), label="reference")
    evaluation_rows = _rows(item_rows.get("evaluation"), label="evaluation")
    validated_inference = validate_inference_config(
        inference, execution_kind=execution_kind
    )
    validated_binding = (
        _validate_inference_binding(
            feasibility_binding=feasibility_binding,
            reference_binding=reference_binding,
            reference_rows=reference_rows,
            evaluation_rows=evaluation_rows,
        )
        if compute_inference and execution_kind != "synthetic_fixture"
        else None
    )
    if not isinstance(reference_matrices, Mapping) or not isinstance(
        evaluation_matrices, Mapping
    ):
        raise FrozenHypothesisEvaluationError("feature matrices must be mappings")
    if set(reference_matrices) != set(LOCKED_LAYERS) or set(evaluation_matrices) != set(
        LOCKED_LAYERS
    ):
        raise FrozenHypothesisEvaluationError(
            "reference and evaluation matrices must contain exactly the six locked layers"
        )
    reference: dict[str, np.ndarray] = {}
    evaluation: dict[str, np.ndarray] = {}
    reference_dimensions = (
        dict(validated_binding.frozen_reference.feature_dimensions)
        if validated_binding is not None
        else dict.fromkeys(LOCKED_LAYERS, FEATURE_DIMENSION)
    )
    for layer_id in LOCKED_LAYERS:
        ref = _require_matrix(
            reference_matrices[layer_id],
            label=f"reference_matrices[{layer_id}]",
            expected_rows=len(reference_rows),
            expected_dimension=reference_dimensions.get(layer_id),
        )
        reference[layer_id] = ref
        evaluation[layer_id] = _require_matrix(
            evaluation_matrices[layer_id],
            label=f"evaluation_matrices[{layer_id}]",
            expected_rows=len(evaluation_rows),
            expected_dimension=ref.shape[1],
        )
    geometry = _reference_geometry(reference, reference_rows)

    row_keys: set[str] = set()
    cell_indices: dict[tuple[str, str], list[int]] = {}
    source_ids: set[str] = set()
    for index, row in enumerate(evaluation_rows):
        row_key = _row_string(row, "row_key", label=f"evaluation[{index}]")
        if row_key in row_keys:
            raise FrozenHypothesisEvaluationError("evaluation rows repeat row_key")
        row_keys.add(row_key)
        source_id = _row_string(row, "collection_key", label=f"evaluation[{index}]")
        condition = _row_string(row, "condition", label=f"evaluation[{index}]")
        if condition not in CONDITIONS:
            raise FrozenHypothesisEvaluationError(
                "evaluation rows must have speech or tools conditions"
            )
        segment_count = row.get("whisperx_segment_count")
        if (
            isinstance(segment_count, bool)
            or not isinstance(segment_count, int)
            or segment_count < 0
        ):
            raise FrozenHypothesisEvaluationError(
                "evaluation whisperx_segment_count must be a non-negative integer"
            )
        source_ids.add(source_id)
        cell_indices.setdefault((source_id, condition), []).append(index)
    expected_cells = {
        (source_id, condition) for source_id in source_ids for condition in CONDITIONS
    }
    if (
        len(source_ids) != SOURCE_COLLECTION_COUNT
        or len(evaluation_rows)
        != SOURCE_COLLECTION_COUNT * len(CONDITIONS) * ITEMS_PER_CONDITION_COLLECTION
        or set(cell_indices) != expected_cells
        or any(
            len(indices) != ITEMS_PER_CONDITION_COLLECTION
            for indices in cell_indices.values()
        )
    ):
        raise FrozenHypothesisEvaluationError(
            "evaluation rows must be exactly four collections with six rows per condition"
        )

    source_results: list[dict[str, Any]] = []
    source_permutation_statistics: list[dict[str, np.ndarray]] = []
    per_item_concordance: list[dict[str, Any]] = []
    for source_id in sorted(source_ids):
        speech_indices = cell_indices[(source_id, "speech")]
        tool_indices = cell_indices[(source_id, "tools")]
        source_results.append(
            _observed_source_result(
                source_id=source_id,
                speech_indices=speech_indices,
                tool_indices=tool_indices,
                evaluation=evaluation,
                geometry=geometry,
            )
        )
        source_permutation_statistics.append(
            _balanced_source_statistics(
                source_indices=list(speech_indices) + list(tool_indices),
                evaluation=evaluation,
                geometry=geometry,
            )
        )
        for condition, indices in (("speech", speech_indices), ("tools", tool_indices)):
            for item_index in indices:
                early = _item_family_concordance(
                    evaluation,
                    item_index=item_index,
                    cell_indices=indices,
                    layer_ids=EARLY_LAYERS,
                )
                late = _item_family_concordance(
                    evaluation,
                    item_index=item_index,
                    cell_indices=indices,
                    layer_ids=LATE_LAYERS,
                )
                per_item_concordance.append(
                    {
                        "row_key": evaluation_rows[item_index]["row_key"],
                        "collection_key": source_id,
                        "condition": condition,
                        "whisperx_segment_count": evaluation_rows[item_index][
                            "whisperx_segment_count"
                        ],
                        "early_pairwise_concordance": early,
                        "late_pairwise_concordance": late,
                        "delta_pairwise_concordance": None
                        if early is None or late is None
                        else float(late - early),
                    }
                )

    aggregate_delta_s = float(np.mean([record["delta_s"] for record in source_results]))
    h1_joint_source_ids = [
        record["collection_key"]
        for record in source_results
        if record["delta_s"] < 0.0
        and record["families"]["early"]["C"] > 0.0
        and record["families"]["late"]["C"] > 0.0
        and record["families"]["early"]["frozen_reference_auc"] > 0.5
    ]
    aggregate_delta_auc = float(
        np.mean([record["delta_auc"] for record in source_results])
    )
    h2_joint_source_ids = [
        record["collection_key"]
        for record in source_results
        if record["families"]["early"]["frozen_reference_auc"] > 0.5
        and record["delta_auc"] < 0.0
    ]
    aggregate_h5 = float(
        np.mean(
            [
                record["leave_self_out_residual_difference_in_differences"]
                for record in source_results
            ]
        )
    )
    h5_positive_source_ids = [
        record["collection_key"]
        for record in source_results
        if record["leave_self_out_residual_difference_in_differences"] > 0.0
    ]
    h3_rho, h3_by_source, h3_not_estimable_reasons, h3_x, h3_y, h3_cells = _h3_observed(
        per_item_concordance
    )
    h3_negative_source_ids = [
        source_id
        for source_id, value in h3_by_source.items()
        if value is not None and value < 0.0
    ]

    raw_p_values: dict[str, float] = {}
    if compute_inference:
        raw_p_values.update(
            _balanced_label_permutation_p_values(
                source_permutation_statistics,
                observed_h1=aggregate_delta_s,
                observed_h2=aggregate_delta_auc,
                observed_h5=aggregate_h5,
                inference=validated_inference,
            )
        )
        if h3_rho is not None and h3_x is not None and h3_y is not None:
            raw_p_values["H3"] = _h3_permutation_p_value(
                observed=h3_rho,
                x_residual=h3_x,
                y_residual=h3_y,
                cells=h3_cells,
                inference=validated_inference,
            )
        else:
            raw_p_values["H3"] = 1.0
    holm = (
        _holm_adjusted_pvalues(raw_p_values)
        if len(raw_p_values) == len(FROZEN_HYPOTHESIS_FAMILIES)
        else {}
    )
    h1 = _family_result(
        estimable=True,
        directional_support=aggregate_delta_s < 0.0,
        stability_support=len(h1_joint_source_ids) >= 3,
        compute_inference=compute_inference,
        raw_p_value=raw_p_values.get("H1"),
        holm_adjusted_p_value=holm.get("H1"),
        inference_kind="balanced_label_permutation",
        aggregate_delta_s=aggregate_delta_s,
        joint_source_keys=h1_joint_source_ids,
        joint_source_count=len(h1_joint_source_ids),
        criteria={
            "aggregate_delta_s_negative": aggregate_delta_s < 0.0,
            "same_source_joint_gate_at_least_three_of_four": len(h1_joint_source_ids)
            >= 3,
        },
    )
    h2 = _family_result(
        estimable=True,
        directional_support=aggregate_delta_auc < 0.0,
        stability_support=len(h2_joint_source_ids) >= 3,
        compute_inference=compute_inference,
        raw_p_value=raw_p_values.get("H2"),
        holm_adjusted_p_value=holm.get("H2"),
        inference_kind="balanced_label_permutation",
        aggregate_delta_auc=aggregate_delta_auc,
        joint_source_keys=h2_joint_source_ids,
        joint_source_count=len(h2_joint_source_ids),
        criteria={
            "aggregate_delta_auc_negative": aggregate_delta_auc < 0.0,
            "same_source_early_auc_positive_and_delta_auc_negative_at_least_three_of_four": len(
                h2_joint_source_ids
            )
            >= 3,
        },
    )
    h3_estimable = h3_rho is not None and not h3_not_estimable_reasons
    h3 = _family_result(
        estimable=h3_estimable,
        directional_support=h3_rho is not None and h3_rho < 0.0,
        stability_support=len(h3_negative_source_ids) >= 3,
        compute_inference=compute_inference,
        raw_p_value=raw_p_values.get("H3"),
        holm_adjusted_p_value=holm.get("H3"),
        inference_kind="within_source_condition_blocked_permutation",
        correlation=h3_rho,
        source_correlations=h3_by_source,
        negative_source_keys=h3_negative_source_ids,
        not_estimable_reasons=h3_not_estimable_reasons,
        cells_without_asr_variation=[
            value for value in h3_not_estimable_reasons if "/" in value
        ],
        statistic="within_cell_midrank_centered_spearman",
    )
    h5 = _family_result(
        estimable=True,
        directional_support=aggregate_h5 > 0.0,
        stability_support=len(h5_positive_source_ids) >= 3,
        compute_inference=compute_inference,
        raw_p_value=raw_p_values.get("H5"),
        holm_adjusted_p_value=holm.get("H5"),
        inference_kind="balanced_label_permutation",
        aggregate_leave_self_out_residual_difference_in_differences=aggregate_h5,
        positive_source_keys=h5_positive_source_ids,
        positive_source_count=len(h5_positive_source_ids),
    )
    families = {"H1": h1, "H2": h2, "H3": h3, "H5": h5}
    if h1["status"] == "supported":
        outcome = "bounded_support"
    elif any(
        families[family_id]["status"] == "supported" for family_id in ("H2", "H3", "H5")
    ):
        outcome = "primary_inconclusive_with_secondary_support"
    else:
        outcome = "inconclusive_or_conflicting"
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "evaluation_status": "valid",
        "outcome": outcome,
        "episode_outcome_driven_only_by": "H1",
        "secondary_families_cannot_substitute_for_H1": True,
        "inference_unit": (
            "item_label_permutations_conditional_on_fixed_four_source_panel"
        ),
        "source_population_inference": False,
        "three_of_four_source_gate_role": ("stability_only_not_source_level_p_value"),
        "locked_layer_ids": list(LOCKED_LAYERS),
        "reference_shape": {
            "total_rows": REFERENCE_TOTAL_ROWS,
            "speech_rows": REFERENCE_ROWS_PER_TARGET_CONDITION,
            "tools_rows": REFERENCE_ROWS_PER_TARGET_CONDITION,
        },
        "source_results": source_results,
        "per_item_pairwise_concordance": per_item_concordance,
        "hypothesis_families": families,
        "frozen_hypothesis_family_order": list(FROZEN_HYPOTHESIS_FAMILIES),
        "permutation_metadata": validated_inference,
        "feasibility_binding_status": (
            validated_binding.status
            if validated_binding is not None
            else "not_supplied"
        ),
        "authority_granted": False,
        "launch_authorized": False,
        "gpu_authorized": False,
        "tribe_inference_authorized": False,
        "manuscript_update_authorized": False,
        "registration_authorized": False,
        "execution_authorized": False,
        "confirmation_authorized": False,
    }


def evaluate_frozen_hypothesis_families(
    *,
    reference_matrices: Mapping[str, Any],
    evaluation_matrices: Mapping[str, Any],
    item_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    inference: Mapping[str, Any],
    execution_kind: str,
    compute_inference: bool,
    feasibility_binding: SourceFeasibilityBindingV2 | None = None,
    reference_binding: FrozenReferenceBindingV2 | None = None,
) -> dict[str, Any]:
    """Return an exact v2 evaluation from caller-supplied public inputs."""

    if execution_kind not in {"synthetic_fixture", "governed_external_input"}:
        return _invalid_result(
            code="invalid_execution_kind",
            message="execution_kind must be synthetic_fixture or governed_external_input",
        )
    try:
        return _evaluate_frozen_hypothesis_families(
            reference_matrices=reference_matrices,
            evaluation_matrices=evaluation_matrices,
            item_rows=item_rows,
            inference=inference,
            execution_kind=execution_kind,
            compute_inference=compute_inference,
            feasibility_binding=feasibility_binding,
            reference_binding=reference_binding,
        )
    except (
        FrozenHypothesisEvaluationError,
        SourceFeasibilityContractError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _invalid_result(code="frozen_input_invalid", message=str(exc))


__all__ = [
    "EVALUATION_SCHEMA_VERSION",
    "FrozenHypothesisEvaluationError",
    "REFERENCE_ROWS_PER_TARGET_CONDITION",
    "REFERENCE_TOTAL_ROWS",
    "evaluate_frozen_hypothesis_families",
]
