"""Exact public evaluator for the recurring TRIBE speech-tools v1 estimand.

The D/S/C/G and frozen-reference AUC calculations are mechanically retained
from the private evaluator.  This public module accepts only caller-supplied
row manifests and already-produced feature matrices.  It neither loads TRIBE
nor supplies a data location, model asset, checkpoint, external command, or
execution identity.
"""

from __future__ import annotations

import io
import json
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PROGRAM_ID = "tribe_speech_tools_acoustic_matched_validation_v1"
EPISODE_ID = PROGRAM_ID
ANALYSIS_CONTRACT_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.recurring_analysis_contract.v1"
)
FEATURE_MANIFEST_SCHEMA_VERSION = "br.tribe_speech_tools_public.layer_features.v1"
INPUT_MANIFEST_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.recurring_input_manifest.v1"
)
EVALUATION_SCHEMA_VERSION = "br.tribe_speech_tools_public.recurring_evaluation.v1"
RUNTIME_FIX_ID = "neuralset.find_enclosed.one_ulp_outward_inclusive.v1"

CONDITIONS = ("speech", "tools")
EARLY_LAYERS = (
    "encoder.layers.0.1",
    "encoder.layers.2.1",
    "encoder.layers.4.1",
)
LATE_LAYERS = (
    "encoder.layers.10.1",
    "encoder.layers.12.1",
    "encoder.layers.14.1",
)
LOCKED_LAYERS = EARLY_LAYERS + LATE_LAYERS
REFERENCE_SUCCESS_ROWS = 48
EVALUATION_SUCCESS_ROWS = 48
REFERENCE_ROWS_PER_CONDITION = 8
ITEMS_PER_CONDITION_COLLECTION = 6
SOURCE_COLLECTION_COUNT = 4
FEATURE_DIMENSION = 1152


@dataclass(frozen=True, slots=True)
class InputRow:
    """One caller-provided logical evaluation row, without source locations."""

    row_key: str
    condition: str
    collection_key: str


@dataclass(frozen=True, slots=True)
class FrozenBundle:
    """A locally supplied public bundle whose storage root is explicit."""

    bundle_dir: Path
    analysis_contract_path: Path
    input_manifest_path: Path
    materialization_report_path: Path
    state_path: Path
    reference_feature_manifest_path: Path
    analysis_contract: Mapping[str, Any]
    input_rows: Mapping[str, InputRow]
    collection_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeatureManifest:
    """Validated caller-supplied layer matrices and their logical row order."""

    path: Path
    payload: Mapping[str, Any]
    rows_by_index: Mapping[int, Mapping[str, Any]]
    matrices: Mapping[str, np.ndarray]
    matrix_paths: Mapping[str, Path]


class FrozenEvaluationInvalid(ValueError):
    """A supplied public input cannot support the frozen v1 estimand."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid(code: str, message: str) -> None:
    raise FrozenEvaluationInvalid(code, message)


def _rows(value: Any, *, label: str) -> list[Mapping[str, Any]]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        _invalid("invalid_rows", f"{label} must be a list of row objects")
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            _invalid("invalid_rows", f"{label}[{index}] must be an object")
        rows.append(row)
    return rows


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid("invalid_string", f"{label} must be non-empty text")
    return value.strip()


def _matrix(
    value: Any, *, label: str, expected_rows: int, expected_columns: int | None
) -> np.ndarray:
    matrix = np.asarray(value, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != expected_rows:
        _invalid(
            "invalid_matrix_shape",
            f"{label} must have {expected_rows} rows",
        )
    if expected_columns is not None and matrix.shape[1] != expected_columns:
        _invalid(
            "invalid_matrix_dimension",
            f"{label} must have {expected_columns} columns",
        )
    if matrix.shape[1] == 0 or not np.all(np.isfinite(matrix)):
        _invalid("invalid_matrix", f"{label} must be finite and non-empty")
    return matrix


def _roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """The private evaluator's tie-aware rank AUC implementation."""

    labels = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    if labels.ndim != 1 or scores.ndim != 1 or labels.shape != scores.shape:
        _invalid(
            "invalid_auc_inputs", "ROC AUC requires same-length label and score vectors"
        )
    n_positive = int(labels.sum())
    n_negative = int(labels.shape[0] - n_positive)
    if n_positive == 0 or n_negative == 0:
        _invalid("invalid_auc_inputs", "ROC AUC requires both conditions")
    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(scores.shape[0], dtype=float)
    start = 0
    while start < scores.shape[0]:
        end = start + 1
        while end < scores.shape[0] and sorted_scores[end] == sorted_scores[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    positive_rank_sum = float(ranks[labels].sum())
    return float(
        (positive_rank_sum - n_positive * (n_positive + 1) / 2.0)
        / (n_positive * n_negative)
    )


def _reference_speech_tools_indices(
    reference_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[int]]:
    indices = {condition: [] for condition in CONDITIONS}
    for index, row in enumerate(reference_rows):
        condition = row.get("condition")
        if condition in indices:
            indices[condition].append(index)
    for condition in CONDITIONS:
        if len(indices[condition]) != REFERENCE_ROWS_PER_CONDITION:
            _invalid(
                "invalid_reference_condition_count",
                "reference must contain exactly eight speech and eight tools rows",
            )
    return indices


def _reference_geometry(
    reference_matrices: Mapping[str, np.ndarray],
    *,
    speech_indices: Sequence[int],
    tools_indices: Sequence[int],
) -> dict[str, dict[str, Any]]:
    """Mechanically retained D/reference-axis construction."""

    geometry: dict[str, dict[str, Any]] = {}
    for layer_id in LOCKED_LAYERS:
        matrix = reference_matrices[layer_id]
        speech = matrix[list(speech_indices)]
        tools = matrix[list(tools_indices)]
        speech_centroid = speech.mean(axis=0)
        tools_centroid = tools.mean(axis=0)
        delta_ref = speech_centroid - tools_centroid
        residuals = np.concatenate(
            (speech - speech_centroid, tools - tools_centroid), axis=0
        )
        dispersion_d = float(np.sqrt(np.mean(np.sum(residuals**2, axis=1))))
        delta_ref_norm = float(np.linalg.norm(delta_ref))
        if not np.isfinite(dispersion_d) or dispersion_d <= 0.0:
            _invalid(
                "nonpositive_reference_dispersion",
                f"reference D is non-positive for {layer_id}",
            )
        if not np.isfinite(delta_ref_norm) or delta_ref_norm <= 0.0:
            _invalid(
                "zero_reference_axis",
                f"reference delta_ref has zero norm for {layer_id}",
            )
        geometry[layer_id] = {
            "delta_ref": delta_ref,
            "dispersion_d": dispersion_d,
            "delta_ref_norm": delta_ref_norm,
            "n_reference_speech": int(speech.shape[0]),
            "n_reference_tools": int(tools.shape[0]),
        }
    return geometry


def _family_mean(values: Sequence[float | None]) -> float | None:
    if any(value is None for value in values):
        return None
    return float(np.mean(np.asarray(values, dtype=float)))


def _evaluate_collection(
    *,
    collection_key: str,
    indices: Sequence[int],
    evaluation_rows: Sequence[Mapping[str, Any]],
    evaluation_matrices: Mapping[str, np.ndarray],
    reference_geometry: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Mechanically retained per-cell D/S/C/G/AUC evaluation."""

    speech_indices = [
        index
        for index in indices
        if evaluation_rows[index].get("condition") == "speech"
    ]
    tools_indices = [
        index
        for index in indices
        if evaluation_rows[index].get("condition") == "tools"
    ]
    layer_records: list[dict[str, Any]] = []
    for layer_id in LOCKED_LAYERS:
        matrix = evaluation_matrices[layer_id]
        speech = matrix[speech_indices]
        tools = matrix[tools_indices]
        delta_eval = speech.mean(axis=0) - tools.mean(axis=0)
        delta_eval_norm = float(np.linalg.norm(delta_eval))
        ref = reference_geometry[layer_id]
        dispersion_d = float(ref["dispersion_d"])
        delta_ref = np.asarray(ref["delta_ref"], dtype=float)
        delta_ref_norm = float(ref["delta_ref_norm"])
        dot_product = float(np.dot(delta_ref, delta_eval))
        separation_s = float(delta_eval_norm / dispersion_d)
        axis_cosine_c = (
            float(dot_product / (delta_ref_norm * delta_eval_norm))
            if delta_eval_norm > 0.0
            else None
        )
        signed_projection_g = float(dot_product / (delta_ref_norm * dispersion_d))
        stacked = np.concatenate((speech, tools), axis=0)
        labels = np.asarray([True] * len(speech) + [False] * len(tools))
        auc = _roc_auc(labels, stacked @ delta_ref)
        layer_records.append(
            {
                "layer_id": layer_id,
                "family": "early" if layer_id in EARLY_LAYERS else "late",
                "n_speech": int(speech.shape[0]),
                "n_tools": int(tools.shape[0]),
                "D": dispersion_d,
                "S": separation_s,
                "C": axis_cosine_c,
                "G": signed_projection_g,
                "frozen_reference_auc": auc,
            }
        )
    by_layer = {record["layer_id"]: record for record in layer_records}
    families: dict[str, dict[str, float | None]] = {}
    for family, layer_ids in (("early", EARLY_LAYERS), ("late", LATE_LAYERS)):
        family_records = [by_layer[layer_id] for layer_id in layer_ids]
        families[family] = {
            "S": _family_mean([record["S"] for record in family_records]),
            "C": _family_mean([record["C"] for record in family_records]),
            "G": _family_mean([record["G"] for record in family_records]),
            "frozen_reference_auc": _family_mean(
                [record["frozen_reference_auc"] for record in family_records]
            ),
        }
    early_s = families["early"]["S"]
    late_s = families["late"]["S"]
    assert early_s is not None and late_s is not None
    return {
        "collection_key": collection_key,
        "layers": layer_records,
        "families": families,
        "delta_s": float(late_s - early_s),
    }


def _validate_evaluation_rows(
    evaluation_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, list[int]]]:
    if len(evaluation_rows) != EVALUATION_SUCCESS_ROWS:
        _invalid("evaluation_row_count", "evaluation must contain exactly 48 rows")
    seen_keys: set[str] = set()
    indices_by_collection: dict[str, list[int]] = {}
    for index, row in enumerate(evaluation_rows):
        row_key = _text(row.get("row_key"), label=f"evaluation[{index}].row_key")
        if row_key in seen_keys:
            _invalid("duplicate_row_key", "evaluation rows repeat row_key")
        seen_keys.add(row_key)
        condition = row.get("condition")
        if condition not in CONDITIONS:
            _invalid("invalid_condition", "evaluation rows must be speech or tools")
        collection_key = _text(
            row.get("collection_key"), label=f"evaluation[{index}].collection_key"
        )
        indices_by_collection.setdefault(collection_key, []).append(index)
    collection_keys = sorted(indices_by_collection)
    if len(collection_keys) != SOURCE_COLLECTION_COUNT:
        _invalid("collection_count", "evaluation must contain exactly four collections")
    for collection_key, indices in indices_by_collection.items():
        if len(indices) != 2 * ITEMS_PER_CONDITION_COLLECTION:
            _invalid(
                "collection_row_count",
                "each collection must contain six speech and six tools rows",
            )
        counts = {
            condition: sum(
                evaluation_rows[index].get("condition") == condition
                for index in indices
            )
            for condition in CONDITIONS
        }
        if counts != dict.fromkeys(CONDITIONS, ITEMS_PER_CONDITION_COLLECTION):
            _invalid(
                "collection_condition_count",
                "each collection must contain six speech and six tools rows",
            )
    return collection_keys, indices_by_collection


def _invalid_result(error: FrozenEvaluationInvalid) -> dict[str, Any]:
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "evaluation_status": "invalid",
        "outcome": "invalid",
        "execution_authorized": False,
        "confirmation_authorized": False,
        "runtime_fix_id": RUNTIME_FIX_ID,
        "invalid_reason": {"code": error.code, "message": str(error)},
        "decision": {
            "bounded_support": False,
            "rule": "not evaluated because the frozen structural/reference contract is invalid",
        },
    }


def evaluate_recurring_v1(
    *,
    reference_matrices: Mapping[str, Any],
    evaluation_matrices: Mapping[str, Any],
    reference_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate the frozen recurring-v1 estimand from explicit public inputs."""

    try:
        parsed_reference_rows = _rows(reference_rows, label="reference_rows")
        parsed_evaluation_rows = _rows(evaluation_rows, label="evaluation_rows")
        if len(parsed_reference_rows) != REFERENCE_SUCCESS_ROWS:
            _invalid("reference_row_count", "reference must contain exactly 48 rows")
        if not isinstance(reference_matrices, Mapping) or not isinstance(
            evaluation_matrices, Mapping
        ):
            _invalid("invalid_matrix_mapping", "feature matrices must be mappings")
        if set(reference_matrices) != set(LOCKED_LAYERS) or set(
            evaluation_matrices
        ) != set(LOCKED_LAYERS):
            _invalid(
                "locked_layers_mismatch",
                "reference and evaluation must contain exactly the six locked layers",
            )
        reference = {
            layer_id: _matrix(
                reference_matrices[layer_id],
                label=f"reference_matrices[{layer_id}]",
                expected_rows=REFERENCE_SUCCESS_ROWS,
                expected_columns=FEATURE_DIMENSION,
            )
            for layer_id in LOCKED_LAYERS
        }
        evaluation = {
            layer_id: _matrix(
                evaluation_matrices[layer_id],
                label=f"evaluation_matrices[{layer_id}]",
                expected_rows=EVALUATION_SUCCESS_ROWS,
                expected_columns=FEATURE_DIMENSION,
            )
            for layer_id in LOCKED_LAYERS
        }
        reference_indices = _reference_speech_tools_indices(parsed_reference_rows)
        collection_keys, indices_by_collection = _validate_evaluation_rows(
            parsed_evaluation_rows
        )
        reference_geometry = _reference_geometry(
            reference,
            speech_indices=reference_indices["speech"],
            tools_indices=reference_indices["tools"],
        )
        collection_results = [
            _evaluate_collection(
                collection_key=collection_key,
                indices=indices_by_collection[collection_key],
                evaluation_rows=parsed_evaluation_rows,
                evaluation_matrices=evaluation,
                reference_geometry=reference_geometry,
            )
            for collection_key in collection_keys
        ]
        aggregate_delta_s = float(
            np.mean(
                np.asarray(
                    [result["delta_s"] for result in collection_results], dtype=float
                )
            )
        )
        negative_delta_s = [
            result["collection_key"]
            for result in collection_results
            if result["delta_s"] < 0.0
        ]
        paired_positive_c = [
            result["collection_key"]
            for result in collection_results
            if result["families"]["early"]["C"] is not None
            and result["families"]["late"]["C"] is not None
            and result["families"]["early"]["C"] > 0.0
            and result["families"]["late"]["C"] > 0.0
        ]
        early_auc_gt_half = [
            result["collection_key"]
            for result in collection_results
            if result["families"]["early"]["frozen_reference_auc"] is not None
            and result["families"]["early"]["frozen_reference_auc"] > 0.5
        ]
        criteria = {
            "aggregate_delta_s_negative": aggregate_delta_s < 0.0,
            "negative_delta_s_at_least_three_of_four": len(negative_delta_s) >= 3,
            "paired_early_late_positive_c_at_least_three_of_four": len(
                paired_positive_c
            )
            >= 3,
            "early_frozen_reference_auc_gt_half_at_least_three_of_four": len(
                early_auc_gt_half
            )
            >= 3,
        }
        bounded_support = all(criteria.values())
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
            "scope": "prospective_discovery_validation",
            "evaluation_status": "valid",
            "outcome": "bounded_support"
            if bounded_support
            else "inconclusive_or_conflicting",
            "execution_authorized": False,
            "confirmation_authorized": False,
            "runtime_fix_id": RUNTIME_FIX_ID,
            "layers": {"early": list(EARLY_LAYERS), "late": list(LATE_LAYERS)},
            "reference": {
                "successful_rows": REFERENCE_SUCCESS_ROWS,
                "speech_rows_used": REFERENCE_ROWS_PER_CONDITION,
                "tools_rows_used": REFERENCE_ROWS_PER_CONDITION,
                "per_layer": {
                    layer_id: {
                        "D": float(reference_geometry[layer_id]["dispersion_d"]),
                        "delta_ref_norm": float(
                            reference_geometry[layer_id]["delta_ref_norm"]
                        ),
                    }
                    for layer_id in LOCKED_LAYERS
                },
            },
            "source_sets": collection_results,
            "aggregate_delta_s": aggregate_delta_s,
            "decision": {
                "bounded_support": bounded_support,
                "criteria": criteria,
                "negative_delta_s_source_sets": negative_delta_s,
                "paired_positive_c_source_sets": paired_positive_c,
                "early_auc_gt_half_source_sets": early_auc_gt_half,
                "rule": "all four frozen conjuncts are required; no metric substitution",
            },
            "interpretation_boundary": [
                "This is prospective discovery validation, not confirmation.",
                "A bounded_support outcome supports only a bounded new-stimulus geometry pattern.",
                "Collection counts are stability units, not conventional significance evidence.",
            ],
        }
    except FrozenEvaluationInvalid as error:
        return _invalid_result(error)
    except (TypeError, ValueError) as error:
        return _invalid_result(
            FrozenEvaluationInvalid("frozen_input_invalid", str(error))
        )


def _read_stable_bytes(path: Path, *, label: str) -> bytes:
    """Read one literal public input while rejecting a replacement in progress."""

    try:
        before = path.stat()
    except FileNotFoundError:
        _invalid("missing_file", f"{label} does not exist")
    except OSError as exc:
        _invalid("unreadable_file", f"cannot stat {label}: {exc}")
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        _invalid("unsafe_file", f"{label} must be a regular non-symlink file")
    try:
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        _invalid("unreadable_file", f"cannot read {label}: {exc}")
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        _invalid("unstable_file", f"{label} changed while it was being read")
    return raw


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(_read_stable_bytes(path, label=label).decode("utf-8"))
    except FrozenEvaluationInvalid:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _invalid("invalid_json", f"{label} must contain a JSON object: {exc}")
    if not isinstance(payload, dict):
        _invalid("invalid_json_shape", f"{label} must contain a JSON object")
    return payload


def _resolve_path(
    value: Any,
    *,
    base_dir: Path,
    label: str,
    require_within_base_dir: bool = False,
) -> Path:
    if not isinstance(value, str) or not value.strip():
        _invalid("missing_path", f"{label} must be a non-empty path string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    if path.is_symlink():
        _invalid("unsafe_file", f"{label} must not be a symlink")
    resolved = path.resolve(strict=False)
    if require_within_base_dir:
        try:
            resolved.relative_to(base_dir.resolve())
        except ValueError:
            _invalid("matrix_path_outside_manifest", f"{label} leaves its manifest root")
    return resolved


def _require_equal(value: Any, expected: Any, *, label: str) -> None:
    if value != expected:
        _invalid("frozen_contract_mismatch", f"{label} must equal the frozen value")


def _as_exact_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        _invalid("invalid_integer", f"{label} must be an integer")
    return int(value)


def _finite_at_most(value: Any, *, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | np.number):
        _invalid("invalid_number", f"{label} must be finite")
    numeric = float(value)
    if not np.isfinite(numeric) or numeric > maximum:
        _invalid("frozen_materialization_mismatch", f"{label} exceeds its limit")
    return numeric


def _validate_public_runtime(value: Any) -> dict[str, Any]:
    """Keep paths and command configuration explicit without executing either."""

    if not isinstance(value, Mapping):
        _invalid("missing_runtime", "analysis contract must contain a runtime object")
    expected = {"mode", "data_root", "model_root", "checkpoint", "command", "seed"}
    if set(value) != expected:
        _invalid("runtime_fields", "runtime must explicitly name all runtime inputs")
    mode = value.get("mode")
    if mode not in {"precomputed_feature_matrices", "injected_adapter"}:
        _invalid("runtime_mode", "runtime.mode is unsupported")
    parsed: dict[str, Any] = {"mode": mode}
    for field in ("data_root", "model_root", "checkpoint", "command"):
        raw = value.get(field)
        if raw is not None and (not isinstance(raw, str) or not raw.strip()):
            _invalid("runtime_value", f"runtime.{field} must be text or null")
        parsed[field] = raw.strip() if isinstance(raw, str) else None
    seed = value.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        _invalid("runtime_seed", "runtime.seed must be an integer or null")
    parsed["seed"] = seed
    if mode == "precomputed_feature_matrices":
        if any(parsed[field] is not None for field in parsed if field != "mode"):
            _invalid(
                "runtime_precomputed_values",
                "precomputed feature matrices require explicit null runtime values",
            )
    else:
        if any(parsed[field] is None for field in ("data_root", "model_root", "checkpoint", "command", "seed")):
            _invalid(
                "runtime_adapter_values",
                "injected_adapter requires explicit roots, checkpoint, command, and seed",
            )
    return parsed


def _validate_analysis_contract(payload: Mapping[str, Any], *, bundle_dir: Path) -> Path:
    _require_equal(
        payload.get("schema_version"),
        ANALYSIS_CONTRACT_SCHEMA_VERSION,
        label="analysis_contract.schema_version",
    )
    _require_equal(payload.get("program_id"), PROGRAM_ID, label="analysis_contract.program_id")
    _require_equal(
        payload.get("scope"),
        "prospective_discovery_validation",
        label="analysis_contract.scope",
    )
    _require_equal(
        payload.get("execution_authorized"),
        False,
        label="analysis_contract.execution_authorized",
    )
    _require_equal(
        payload.get("confirmation_authorized"),
        False,
        label="analysis_contract.confirmation_authorized",
    )
    _require_equal(
        payload.get("input_manifest_bound"),
        True,
        label="analysis_contract.input_manifest_bound",
    )
    _validate_public_runtime(payload.get("runtime"))
    layers = payload.get("layers")
    if not isinstance(layers, Mapping):
        _invalid("missing_layers", "analysis contract is missing layers")
    _require_equal(layers.get("early"), list(EARLY_LAYERS), label="analysis_contract.layers.early")
    _require_equal(layers.get("late"), list(LATE_LAYERS), label="analysis_contract.layers.late")
    reference = payload.get("reference")
    if not isinstance(reference, Mapping):
        _invalid("missing_reference", "analysis contract is missing reference")
    _require_equal(
        reference.get("required_schema_version"),
        FEATURE_MANIFEST_SCHEMA_VERSION,
        label="analysis_contract.reference.required_schema_version",
    )
    _require_equal(
        reference.get("required_success_rows"),
        REFERENCE_SUCCESS_ROWS,
        label="analysis_contract.reference.required_success_rows",
    )
    _require_equal(
        reference.get("required_feature_dimension"),
        FEATURE_DIMENSION,
        label="analysis_contract.reference.required_feature_dimension",
    )
    _require_equal(
        reference.get("required_layer_ids"),
        list(LOCKED_LAYERS),
        label="analysis_contract.reference.required_layer_ids",
    )
    _require_equal(
        reference.get("positive_condition"),
        "speech",
        label="analysis_contract.reference.positive_condition",
    )
    _require_equal(
        reference.get("negative_condition"),
        "tools",
        label="analysis_contract.reference.negative_condition",
    )
    reference_path = _resolve_path(
        reference.get("feature_manifest_path"),
        base_dir=bundle_dir,
        label="analysis_contract.reference.feature_manifest_path",
    )
    primary_estimand = payload.get("primary_estimand")
    if not isinstance(primary_estimand, Mapping):
        _invalid("missing_primary_estimand", "analysis contract is missing primary estimand")
    _require_equal(
        primary_estimand.get("aggregate"),
        "unweighted mean delta_s across four caller-supplied collections",
        label="analysis_contract.primary_estimand.aggregate",
    )
    _require_equal(
        primary_estimand.get("per_collection"),
        "delta_s = mean_late(S) - mean_early(S)",
        label="analysis_contract.primary_estimand.per_collection",
    )
    _require_equal(
        primary_estimand.get("predicted_direction"),
        "negative",
        label="analysis_contract.primary_estimand.predicted_direction",
    )
    decision = payload.get("decision_rule")
    if not isinstance(decision, Mapping):
        _invalid("missing_decision_rule", "analysis contract is missing decision rule")
    _require_equal(
        decision.get("bounded_support"),
        [
            "aggregate delta_s is negative",
            "delta_s is negative in at least three of four collections",
            "early and late family C are both positive in at least three of four paired collections",
            "early frozen-reference AUC is greater than 0.5 in at least three of four collections",
        ],
        label="analysis_contract.decision_rule.bounded_support",
    )
    _require_equal(
        decision.get("no_metric_substitution"),
        True,
        label="analysis_contract.decision_rule.no_metric_substitution",
    )
    _require_equal(
        decision.get("otherwise"),
        "stop as inconclusive or conflicting",
        label="analysis_contract.decision_rule.otherwise",
    )
    return reference_path


def _validate_input_manifest(
    payload: Mapping[str, Any],
) -> tuple[dict[str, InputRow], tuple[str, ...]]:
    _require_equal(
        payload.get("schema_version"),
        INPUT_MANIFEST_SCHEMA_VERSION,
        label="input_manifest.schema_version",
    )
    _require_equal(payload.get("program_id"), PROGRAM_ID, label="input_manifest.program_id")
    _require_equal(payload.get("conditions"), list(CONDITIONS), label="input_manifest.conditions")
    collection_values = payload.get("collection_keys")
    if not isinstance(collection_values, list) or len(collection_values) != SOURCE_COLLECTION_COUNT:
        _invalid("invalid_collections", "input manifest must contain four collection keys")
    collection_keys = tuple(_text(value, label="input_manifest.collection_key") for value in collection_values)
    if len(set(collection_keys)) != SOURCE_COLLECTION_COUNT:
        _invalid("duplicate_collection_key", "input manifest repeats collection keys")
    _require_equal(
        payload.get("items_per_condition_collection"),
        ITEMS_PER_CONDITION_COLLECTION,
        label="input_manifest.items_per_condition_collection",
    )
    values = payload.get("rows")
    if not isinstance(values, list) or len(values) != EVALUATION_SUCCESS_ROWS:
        _invalid("invalid_input_rows", "input manifest must contain exactly 48 rows")
    parsed: dict[str, InputRow] = {}
    counts = {
        (collection_key, condition): 0
        for collection_key in collection_keys
        for condition in CONDITIONS
    }
    for position, raw in enumerate(values):
        if not isinstance(raw, Mapping):
            _invalid("invalid_input_row", f"input_manifest.rows[{position}] must be an object")
        row_key = _text(raw.get("row_key"), label=f"input_manifest.rows[{position}].row_key")
        condition = raw.get("condition")
        if condition not in CONDITIONS:
            _invalid("invalid_condition", "input manifest condition is invalid")
        collection_key = _text(
            raw.get("collection_key"),
            label=f"input_manifest.rows[{position}].collection_key",
        )
        if collection_key not in collection_keys:
            _invalid("invalid_collection_key", "input manifest row has an unknown collection")
        if row_key in parsed:
            _invalid("duplicate_row_key", "input manifest repeats row_key")
        parsed[row_key] = InputRow(
            row_key=row_key,
            condition=condition,
            collection_key=collection_key,
        )
        counts[(collection_key, condition)] += 1
    if any(count != ITEMS_PER_CONDITION_COLLECTION for count in counts.values()):
        _invalid("invalid_input_balance", "input manifest does not retain six rows per cell")
    return parsed, collection_keys


def _validate_bundle_state(
    state: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    collection_keys: Sequence[str],
) -> None:
    for field, expected in {
        "program_id": PROGRAM_ID,
        "status": "READY_AWAITING_SEPARATE_AUTHORIZATION",
        "input_manifest_bound": True,
        "execution_authorized": False,
        "confirmation_authorized": False,
        "feature_extraction_completed": False,
    }.items():
        _require_equal(state.get(field), expected, label=f"state.{field}")
    _require_equal(
        report.get("schema_version"),
        "br.tribe_speech_tools_public.recurring_materialization.v1",
        label="materialization_report.schema_version",
    )
    for field, expected in {
        "program_id": PROGRAM_ID,
        "status": "READY_AWAITING_SEPARATE_AUTHORIZATION",
        "input_manifest_written": True,
        "score_blind": True,
        "feature_extraction_completed": False,
    }.items():
        _require_equal(report.get(field), expected, label=f"materialization_report.{field}")
    _require_equal(
        report.get("collection_keys"),
        list(collection_keys),
        label="materialization_report.collection_keys",
    )
    required = report.get("required")
    if not isinstance(required, Mapping):
        _invalid("missing_materialization_requirements", "materialization report is missing required")
    _require_equal(
        required.get("collection_count"),
        SOURCE_COLLECTION_COUNT,
        label="materialization_report.required.collection_count",
    )
    _require_equal(
        required.get("items_per_condition_collection"),
        ITEMS_PER_CONDITION_COLLECTION,
        label="materialization_report.required.items_per_condition_collection",
    )
    _require_equal(
        required.get("total_rows"),
        EVALUATION_SUCCESS_ROWS,
        label="materialization_report.required.total_rows",
    )
    _require_equal(
        required.get("maximum_abs_pool_standardized_mean_difference"),
        0.5,
        label="materialization_report.required.maximum_abs_pool_standardized_mean_difference",
    )
    selection = report.get("selection")
    if not isinstance(selection, Mapping):
        _invalid("missing_materialization_selection", "materialization report is missing selection")
    _require_equal(
        selection.get("solver_status"),
        "optimal",
        label="materialization_report.selection.solver_status",
    )
    balance = selection.get("balance")
    if not isinstance(balance, Mapping):
        _invalid("missing_materialization_balance", "materialization selection is missing balance")
    _finite_at_most(
        balance.get("observed_max_abs_pool_standardized_mean_difference"),
        maximum=0.5,
        label="materialization_report.selection.balance.observed_max_abs_pool_standardized_mean_difference",
    )


def load_frozen_bundle(bundle_dir: str | Path) -> FrozenBundle:
    """Load the full public v1 bundle from an explicit caller-selected root."""

    raw_bundle_dir = Path(bundle_dir).expanduser()
    if raw_bundle_dir.is_symlink():
        _invalid("unsafe_bundle", "frozen bundle directory must not be a symlink")
    resolved_bundle_dir = raw_bundle_dir.resolve()
    if not resolved_bundle_dir.is_dir():
        _invalid("missing_bundle", "frozen bundle directory does not exist")
    analysis_contract_path = resolved_bundle_dir / "analysis_contract.json"
    input_manifest_path = resolved_bundle_dir / "input_manifest.json"
    materialization_report_path = resolved_bundle_dir / "materialization_report.json"
    state_path = resolved_bundle_dir / "state.json"
    analysis_contract = _read_object(analysis_contract_path, label="analysis contract")
    reference_feature_manifest_path = _validate_analysis_contract(
        analysis_contract,
        bundle_dir=resolved_bundle_dir,
    )
    input_rows, collection_keys = _validate_input_manifest(
        _read_object(input_manifest_path, label="input manifest")
    )
    _validate_bundle_state(
        _read_object(state_path, label="bundle state"),
        _read_object(materialization_report_path, label="materialization report"),
        collection_keys=collection_keys,
    )
    if not reference_feature_manifest_path.is_file():
        _invalid("missing_reference_feature_manifest", "reference feature manifest does not exist")
    return FrozenBundle(
        bundle_dir=resolved_bundle_dir,
        analysis_contract_path=analysis_contract_path,
        input_manifest_path=input_manifest_path,
        materialization_report_path=materialization_report_path,
        state_path=state_path,
        reference_feature_manifest_path=reference_feature_manifest_path,
        analysis_contract=analysis_contract,
        input_rows=input_rows,
        collection_keys=collection_keys,
    )


def _load_matrix(path: Path, *, label: str) -> np.ndarray:
    if path.suffix != ".npy":
        _invalid("invalid_matrix_path", f"{label} must be a NumPy matrix")
    try:
        matrix = np.load(io.BytesIO(_read_stable_bytes(path, label=label)), allow_pickle=False)
    except FrozenEvaluationInvalid:
        raise
    except (OSError, ValueError) as exc:
        _invalid("unreadable_matrix", f"cannot load {label}: {exc}")
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2:
        _invalid("invalid_matrix_shape", f"{label} must be two-dimensional")
    if not np.all(np.isfinite(matrix)):
        _invalid("nonfinite_matrix", f"{label} contains non-finite values")
    return matrix


def _load_feature_manifest(
    path: Path,
    *,
    role: str,
    expected_runtime: Mapping[str, Any],
) -> FeatureManifest:
    payload = _read_object(path, label=f"{role} feature manifest")
    _require_equal(
        payload.get("schema_version"),
        FEATURE_MANIFEST_SCHEMA_VERSION,
        label=f"{role}.schema_version",
    )
    _require_equal(payload.get("program_id"), PROGRAM_ID, label=f"{role}.program_id")
    _require_equal(payload.get("runtime_fix_id"), RUNTIME_FIX_ID, label=f"{role}.runtime_fix_id")
    if _validate_public_runtime(payload.get("runtime")) != dict(expected_runtime):
        _invalid("runtime_mismatch", f"{role}.runtime does not match analysis contract")
    _require_equal(
        payload.get("feature_ids_requested"),
        list(LOCKED_LAYERS),
        label=f"{role}.feature_ids_requested",
    )
    for field, expected in {
        "n_manifest_rows": REFERENCE_SUCCESS_ROWS,
        "n_selected_rows": REFERENCE_SUCCESS_ROWS,
        "n_success_rows": REFERENCE_SUCCESS_ROWS,
        "n_failed_rows": 0,
    }.items():
        _require_equal(payload.get(field), expected, label=f"{role}.{field}")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != REFERENCE_SUCCESS_ROWS:
        _invalid("invalid_feature_rows", f"{role}.rows must contain exactly 48 rows")
    rows_by_index: dict[int, Mapping[str, Any]] = {}
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _invalid("invalid_feature_row", f"{role}.rows[{position}] must be an object")
        _require_equal(row.get("status"), "success", label=f"{role}.rows[{position}].status")
        row_index = _as_exact_int(row.get("row_index"), label=f"{role}.rows[{position}].row_index")
        if row_index in rows_by_index:
            _invalid("duplicate_row_index", f"{role} repeats row_index")
        rows_by_index[row_index] = row
    expected_indices = set(range(REFERENCE_SUCCESS_ROWS))
    if set(rows_by_index) != expected_indices:
        _invalid("invalid_row_indices", f"{role} row_index values must cover 0 through 47")
    layers = payload.get("layers")
    if not isinstance(layers, list):
        _invalid("missing_feature_layers", f"{role}.layers must be a list")
    specifications: dict[str, Mapping[str, Any]] = {}
    for position, layer in enumerate(layers):
        if not isinstance(layer, Mapping):
            _invalid("invalid_feature_layer", f"{role}.layers[{position}] must be an object")
        layer_id = layer.get("layer_id")
        if not isinstance(layer_id, str) or not layer_id:
            _invalid("missing_layer_id", f"{role}.layers[{position}] lacks layer_id")
        if layer_id in specifications:
            _invalid("duplicate_layer_id", f"{role} repeats layer_id")
        specifications[layer_id] = layer
    if set(specifications) != set(LOCKED_LAYERS):
        _invalid("invalid_layer_set", f"{role}.layers must equal the six locked layers")
    matrices: dict[str, np.ndarray] = {}
    matrix_paths: dict[str, Path] = {}
    for layer_id in LOCKED_LAYERS:
        spec = specifications[layer_id]
        matrix_path = _resolve_path(
            spec.get("matrix_path"),
            base_dir=path.parent,
            label=f"{role}.{layer_id}.matrix_path",
            require_within_base_dir=True,
        )
        matrix = _load_matrix(matrix_path, label=f"{role}.{layer_id}")
        if matrix.shape != (REFERENCE_SUCCESS_ROWS, FEATURE_DIMENSION):
            _invalid("invalid_matrix_shape", f"{role}.{layer_id} has wrong shape")
        _require_equal(
            spec.get("shape"),
            [REFERENCE_SUCCESS_ROWS, FEATURE_DIMENSION],
            label=f"{role}.{layer_id}.shape",
        )
        row_indices = spec.get("row_indices")
        if not isinstance(row_indices, list):
            _invalid("missing_layer_row_indices", f"{role}.{layer_id} lacks row_indices")
        parsed_indices = [
            _as_exact_int(value, label=f"{role}.{layer_id}.row_indices[{position}]")
            for position, value in enumerate(row_indices)
        ]
        if len(parsed_indices) != REFERENCE_SUCCESS_ROWS or set(parsed_indices) != expected_indices:
            _invalid("invalid_layer_row_indices", f"{role}.{layer_id} row indices are invalid")
        position_for_index = {
            row_index: matrix_position
            for matrix_position, row_index in enumerate(parsed_indices)
        }
        matrices[layer_id] = matrix[
            [position_for_index[row_index] for row_index in range(REFERENCE_SUCCESS_ROWS)]
        ]
        matrix_paths[layer_id] = matrix_path
    return FeatureManifest(
        path=path,
        payload=payload,
        rows_by_index=rows_by_index,
        matrices=matrices,
        matrix_paths=matrix_paths,
    )


def _reference_manifest_speech_tools_indices(
    reference: FeatureManifest,
) -> dict[str, list[int]]:
    indices = {condition: [] for condition in CONDITIONS}
    for index, row in reference.rows_by_index.items():
        condition = row.get("condition")
        if condition in indices:
            indices[condition].append(index)
    for condition in CONDITIONS:
        indices[condition].sort()
        if len(indices[condition]) != REFERENCE_ROWS_PER_CONDITION:
            _invalid(
                "invalid_reference_condition_count",
                f"reference must contain exactly eight {condition} rows",
            )
    return indices


def _validate_evaluation_feature_rows(
    evaluation: FeatureManifest,
    *,
    frozen_bundle: FrozenBundle,
) -> dict[str, list[int]]:
    observed: dict[str, InputRow] = {}
    indices_by_collection = {
        collection_key: [] for collection_key in frozen_bundle.collection_keys
    }
    for row_index, row in evaluation.rows_by_index.items():
        label = f"evaluation.rows[{row_index}]"
        row_key = _text(row.get("row_key"), label=f"{label}.row_key")
        if row_key in observed:
            _invalid("duplicate_evaluation_row_key", "evaluation repeats row_key")
        expected = frozen_bundle.input_rows.get(row_key)
        if expected is None:
            _invalid("unfrozen_evaluation_row", "evaluation row is not in the frozen input")
        if row.get("condition") != expected.condition:
            _invalid("evaluation_condition_mismatch", "evaluation condition does not match frozen input")
        if row.get("collection_key") != expected.collection_key:
            _invalid("evaluation_collection_mismatch", "evaluation collection does not match frozen input")
        observed[row_key] = expected
        indices_by_collection[expected.collection_key].append(row_index)
    if set(observed) != set(frozen_bundle.input_rows):
        _invalid("evaluation_row_set_mismatch", "evaluation rows do not equal frozen input rows")
    for collection_key in frozen_bundle.collection_keys:
        indices = indices_by_collection[collection_key]
        if len(indices) != 2 * ITEMS_PER_CONDITION_COLLECTION:
            _invalid("evaluation_collection_count_mismatch", "evaluation collection has wrong row count")
        counts = {
            condition: sum(
                evaluation.rows_by_index[index].get("condition") == condition
                for index in indices
            )
            for condition in CONDITIONS
        }
        if counts != dict.fromkeys(CONDITIONS, ITEMS_PER_CONDITION_COLLECTION):
            _invalid("evaluation_condition_count_mismatch", "evaluation collection is unbalanced")
        indices.sort()
    return indices_by_collection


def _public_valid_result(
    *,
    frozen_bundle: FrozenBundle,
    evaluation_features_path: Path,
) -> dict[str, Any]:
    expected_runtime = _validate_public_runtime(frozen_bundle.analysis_contract["runtime"])
    reference = _load_feature_manifest(
        frozen_bundle.reference_feature_manifest_path,
        role="reference",
        expected_runtime=expected_runtime,
    )
    evaluation = _load_feature_manifest(
        evaluation_features_path,
        role="evaluation",
        expected_runtime=expected_runtime,
    )
    reference_indices = _reference_manifest_speech_tools_indices(reference)
    collection_indices = _validate_evaluation_feature_rows(
        evaluation,
        frozen_bundle=frozen_bundle,
    )
    reference_geometry = _reference_geometry(
        reference.matrices,
        speech_indices=reference_indices["speech"],
        tools_indices=reference_indices["tools"],
    )
    evaluation_rows = [evaluation.rows_by_index[index] for index in range(EVALUATION_SUCCESS_ROWS)]
    results = [
        _evaluate_collection(
            collection_key=collection_key,
            indices=collection_indices[collection_key],
            evaluation_rows=evaluation_rows,
            evaluation_matrices=evaluation.matrices,
            reference_geometry=reference_geometry,
        )
        for collection_key in frozen_bundle.collection_keys
    ]
    aggregate_delta_s = float(np.mean(np.asarray([row["delta_s"] for row in results], dtype=float)))
    negative_delta_s = [row["collection_key"] for row in results if row["delta_s"] < 0.0]
    paired_positive_c = [
        row["collection_key"]
        for row in results
        if row["families"]["early"]["C"] is not None
        and row["families"]["late"]["C"] is not None
        and row["families"]["early"]["C"] > 0.0
        and row["families"]["late"]["C"] > 0.0
    ]
    early_auc_gt_half = [
        row["collection_key"]
        for row in results
        if row["families"]["early"]["frozen_reference_auc"] is not None
        and row["families"]["early"]["frozen_reference_auc"] > 0.5
    ]
    criteria = {
        "aggregate_delta_s_negative": aggregate_delta_s < 0.0,
        "negative_delta_s_at_least_three_of_four": len(negative_delta_s) >= 3,
        "paired_early_late_positive_c_at_least_three_of_four": len(paired_positive_c) >= 3,
        "early_frozen_reference_auc_gt_half_at_least_three_of_four": len(early_auc_gt_half) >= 3,
    }
    bounded_support = all(criteria.values())
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "evaluation_status": "valid",
        "outcome": "bounded_support" if bounded_support else "inconclusive_or_conflicting",
        "execution_authorized": False,
        "confirmation_authorized": False,
        "runtime_fix_id": RUNTIME_FIX_ID,
        "input_artifacts": {
            "analysis_contract": frozen_bundle.analysis_contract_path.name,
            "input_manifest": frozen_bundle.input_manifest_path.name,
            "reference_feature_manifest": frozen_bundle.reference_feature_manifest_path.name,
            "evaluation_feature_manifest": evaluation.path.name,
        },
        "layers": {"early": list(EARLY_LAYERS), "late": list(LATE_LAYERS)},
        "reference": {
            "successful_rows": REFERENCE_SUCCESS_ROWS,
            "speech_rows_used": REFERENCE_ROWS_PER_CONDITION,
            "tools_rows_used": REFERENCE_ROWS_PER_CONDITION,
            "per_layer": {
                layer_id: {
                    "D": float(reference_geometry[layer_id]["dispersion_d"]),
                    "delta_ref_norm": float(reference_geometry[layer_id]["delta_ref_norm"]),
                }
                for layer_id in LOCKED_LAYERS
            },
        },
        "source_sets": results,
        "aggregate_delta_s": aggregate_delta_s,
        "decision": {
            "bounded_support": bounded_support,
            "criteria": criteria,
            "negative_delta_s_source_sets": negative_delta_s,
            "paired_positive_c_source_sets": paired_positive_c,
            "early_auc_gt_half_source_sets": early_auc_gt_half,
            "rule": "all four frozen conjuncts are required; no metric substitution",
        },
        "interpretation_boundary": [
            "This is prospective discovery validation, not confirmation.",
            "A bounded_support outcome supports only a bounded new-stimulus geometry pattern.",
            "Collection counts are stability units, not conventional significance evidence.",
        ],
    }


def invalid_evaluation_result(
    *,
    bundle_dir: str | Path,
    evaluation_features_path: str | Path,
    error: FrozenEvaluationInvalid,
) -> dict[str, Any]:
    """Render an invalid public result without carrying caller filesystem paths."""

    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "evaluation_status": "invalid",
        "outcome": "invalid",
        "execution_authorized": False,
        "confirmation_authorized": False,
        "runtime_fix_id": RUNTIME_FIX_ID,
        "input_artifacts": {
            "bundle": Path(bundle_dir).expanduser().name,
            "evaluation_feature_manifest": Path(evaluation_features_path).expanduser().name,
        },
        "invalid_reason": {"code": error.code, "message": str(error)},
        "decision": {
            "bounded_support": False,
            "rule": "not evaluated because the frozen structural/reference contract is invalid",
        },
    }


def validate_frozen_reference(bundle_dir: str | Path) -> dict[str, Any]:
    """Validate an explicit public reference bundle without extracting features."""

    bundle = load_frozen_bundle(bundle_dir)
    runtime = _validate_public_runtime(bundle.analysis_contract["runtime"])
    reference = _load_feature_manifest(
        bundle.reference_feature_manifest_path,
        role="reference",
        expected_runtime=runtime,
    )
    indices = _reference_manifest_speech_tools_indices(reference)
    _reference_geometry(
        reference.matrices,
        speech_indices=indices["speech"],
        tools_indices=indices["tools"],
    )
    return {
        "reference_feature_manifest": reference.path.name,
        "locked_layer_ids": list(LOCKED_LAYERS),
        "successful_rows": REFERENCE_SUCCESS_ROWS,
    }


def evaluate_frozen_validation(
    *,
    bundle_dir: str | Path,
    evaluation_features_path: str | Path,
) -> dict[str, Any]:
    """Evaluate one caller-selected manifest against a caller-selected public bundle."""

    try:
        bundle = load_frozen_bundle(bundle_dir)
        return _public_valid_result(
            frozen_bundle=bundle,
            evaluation_features_path=Path(evaluation_features_path).expanduser().resolve(),
        )
    except FrozenEvaluationInvalid as exc:
        return invalid_evaluation_result(
            bundle_dir=bundle_dir,
            evaluation_features_path=evaluation_features_path,
            error=exc,
        )


def write_evaluation_result(path: str | Path, result: Mapping[str, Any]) -> Path:
    """Write one immutable public evaluator artifact at an explicit output path."""

    from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
        write_json_new,
    )

    return write_json_new(path, result, label="evaluation_result")


def _require_replayed_evaluation_result(
    payload: Mapping[str, Any],
    *,
    bundle_dir: str | Path,
    evaluation_features_path: str | Path,
) -> None:
    expected = evaluate_frozen_validation(
        bundle_dir=bundle_dir,
        evaluation_features_path=evaluation_features_path,
    )
    if dict(payload) != expected:
        _invalid(
            "evaluation_result_replay_mismatch",
            "persisted evaluation result does not equal the deterministic replay",
        )


def read_evaluation_result(
    path: str | Path,
    *,
    bundle_dir: str | Path,
    evaluation_features_path: str | Path,
) -> dict[str, Any]:
    """Read and mechanically replay a public v1 evaluator result.

    Replay locations are explicit caller inputs.  They are intentionally not
    stored in the scientific artifact.
    """

    payload = _read_object(Path(path).expanduser(), label="evaluation result")
    for field, expected in {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "execution_authorized": False,
        "confirmation_authorized": False,
        "runtime_fix_id": RUNTIME_FIX_ID,
    }.items():
        _require_equal(payload.get(field), expected, label=f"evaluation_result.{field}")
    status = payload.get("evaluation_status")
    outcome = payload.get("outcome")
    if status == "invalid":
        _require_equal(outcome, "invalid", label="evaluation_result.outcome")
        reason = payload.get("invalid_reason")
        if not isinstance(reason, Mapping):
            _invalid("invalid_evaluation_result", "invalid result lacks invalid_reason")
        _text(reason.get("code"), label="evaluation_result.invalid_reason.code")
        _text(reason.get("message"), label="evaluation_result.invalid_reason.message")
    elif status == "valid" and outcome in {"bounded_support", "inconclusive_or_conflicting"}:
        decision = payload.get("decision")
        if not isinstance(decision, Mapping) or not isinstance(decision.get("bounded_support"), bool):
            _invalid("invalid_evaluation_result", "valid result lacks a typed decision")
        if bool(decision["bounded_support"]) != (outcome == "bounded_support"):
            _invalid("invalid_evaluation_result", "decision and outcome do not agree")
        source_sets = payload.get("source_sets")
        if not isinstance(source_sets, list) or len(source_sets) != SOURCE_COLLECTION_COUNT:
            _invalid("invalid_evaluation_result", "valid result must contain four collection results")
    else:
        _invalid("invalid_evaluation_result", "evaluation status or outcome is unsupported")
    _require_replayed_evaluation_result(
        payload,
        bundle_dir=bundle_dir,
        evaluation_features_path=evaluation_features_path,
    )
    return dict(payload)


__all__ = [
    "ANALYSIS_CONTRACT_SCHEMA_VERSION",
    "CONDITIONS",
    "EARLY_LAYERS",
    "EVALUATION_SCHEMA_VERSION",
    "FEATURE_MANIFEST_SCHEMA_VERSION",
    "FEATURE_DIMENSION",
    "FeatureManifest",
    "FrozenBundle",
    "FrozenEvaluationInvalid",
    "INPUT_MANIFEST_SCHEMA_VERSION",
    "InputRow",
    "LATE_LAYERS",
    "LOCKED_LAYERS",
    "PROGRAM_ID",
    "RUNTIME_FIX_ID",
    "evaluate_frozen_validation",
    "evaluate_recurring_v1",
    "invalid_evaluation_result",
    "load_frozen_bundle",
    "read_evaluation_result",
    "validate_frozen_reference",
    "write_evaluation_result",
]
