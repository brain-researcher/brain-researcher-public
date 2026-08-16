"""Conditional paired inference for persisted Cognition R2 OOF predictions.

The analysis compares the previously selected C1/term-116 arm with the matched
Liu procedure.  It is retrospective and conditional on persisted fits and the
reused Cognition cohort; it is not search-adjusted or confirmatory inference.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

import numpy as np

CONTRACT_SCHEMA_VERSION = "br.hcp_cognition_r2_paired_inference_contract.v1"
AUTHORIZATION_SCHEMA_VERSION = (
    "br.hcp_cognition_r2_paired_inference_authorization.v1"
)
PROJECTION_SCHEMA_VERSION = "br.hcp_cognition_family_cluster_projection.v1"
RESULT_SCHEMA_VERSION = "br.hcp_cognition_r2_paired_inference_result.v1"
DESIGN = "cognition_r2_c1_vs_matched_liu_conditional_paired_sensitivity_v1"
TARGET = "ICA_Cognition"
ARM_ID = "C1_raw"
REPEATS = 10
SUBJECTS = 244
FAMILIES = 243
OUTER_FOLDS = 5
INNER_FOLDS = 3
DEFAULT_DRAWS = 9_999
DEFAULT_PERMUTATION_SEED = 20260811
DEFAULT_BOOTSTRAP_SEED = 20260812


def configure_inference_runtime(*, permutation_seed: int | None = None, bootstrap_seed: int | None = None) -> None:
    """Set explicit public inference seeds for this process."""

    global DEFAULT_PERMUTATION_SEED, DEFAULT_BOOTSTRAP_SEED
    if permutation_seed is not None:
        DEFAULT_PERMUTATION_SEED = int(permutation_seed)
    if bootstrap_seed is not None:
        DEFAULT_BOOTSTRAP_SEED = int(bootstrap_seed)


class CognitionPairedInferenceError(RuntimeError):
    """Raised when the frozen Cognition paired-inference contract is invalid."""


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CognitionPairedInferenceError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise CognitionPairedInferenceError(f"{label} must be a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CognitionPairedInferenceError(f"{label} must be an object")
    return value


def _required_list(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CognitionPairedInferenceError(f"{label} must be a list")
    return value


def _corr(y: np.ndarray, prediction: np.ndarray) -> float:
    y_centered = y - np.mean(y)
    p_centered = prediction - np.mean(prediction)
    denominator = float(np.sqrt(np.sum(y_centered**2) * np.sum(p_centered**2)))
    return float(np.sum(y_centered * p_centered) / denominator) if denominator else 0.0


def _metrics(y: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    denominator = float(np.sum((y - np.mean(y)) ** 2))
    residual = float(np.sum((y - prediction) ** 2))
    return {
        "signed_pearson_r": _corr(y, prediction),
        "r2": float(1.0 - residual / denominator) if denominator else 0.0,
        "mae": float(np.mean(np.abs(y - prediction))),
    }


def _family_projection(
    *, r2_contract: Mapping[str, object], snapshot: Mapping[str, object]
) -> dict[str, object]:
    source_paths = _mapping(r2_contract.get("source_paths"), label="source paths")
    source_bundle = Path(str(source_paths.get("source_bundle")))
    runtime_inputs = _read_json(
        source_bundle / "private" / "runtime_inputs.json", label="runtime inputs"
    )
    manifest_path = Path(str(runtime_inputs.get("exchangeability_manifest_path")))
    manifest = _read_json(manifest_path, label="exchangeability manifest")
    rows = _required_list(manifest.get("subjects"), label="exchangeability subjects")
    by_index: dict[int, Mapping[str, object]] = {}
    for raw_row in rows:
        row = _mapping(raw_row, label="exchangeability subject")
        index = int(row.get("index"))
        if index in by_index:
            raise CognitionPairedInferenceError("duplicate exchangeability row index")
        by_index[index] = row
    subject_indices = [int(value) for value in snapshot.get("subject_indices", [])]
    subject_ids = [str(value) for value in snapshot.get("subject_ids", [])]
    if len(subject_indices) != SUBJECTS or len(set(subject_indices)) != SUBJECTS:
        raise CognitionPairedInferenceError("R2 snapshot subject indices changed")
    if len(subject_ids) != SUBJECTS or len(set(subject_ids)) != SUBJECTS:
        raise CognitionPairedInferenceError("R2 snapshot subject IDs changed")
    family_ids: list[str] = []
    for index, subject_id in zip(subject_indices, subject_ids, strict=True):
        row = by_index.get(index)
        if row is None or str(row.get("subject_id")) != subject_id:
            raise CognitionPairedInferenceError(
                "R2 snapshot rows do not match exchangeability manifest"
            )
        family_id = str(row.get("family_id", "")).strip()
        if not family_id:
            raise CognitionPairedInferenceError("exchangeability family ID is empty")
        family_ids.append(family_id)
    if len(set(family_ids)) != FAMILIES:
        raise CognitionPairedInferenceError("R2 development family count changed")
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "source_bundle": str(source_bundle.resolve()),
        "exchangeability_manifest_path": str(manifest_path.resolve()),
        "subject_indices": subject_indices,
        "subject_ids": subject_ids,
        "family_ids": family_ids,
        "subject_count": SUBJECTS,
        "family_count": FAMILIES,
    }


def _source_binding(source_dir: Path) -> tuple[dict[str, object], dict[str, object]]:
    source = Path(source_dir)
    result = _read_json(source / "r2_result.json", label="R2 result")
    r2_contract = _read_json(source / "r2_contract.json", label="R2 contract")
    splits = _read_json(source / "r2_splits.json", label="R2 splits")
    snapshot = _read_json(
        source / "private" / "development_target_snapshot.json",
        label="R2 target snapshot",
    )
    required_result = {
        "schema_version": "br.hcp_calibration_equivalence_r2_result.v1",
        "analysis_label": "development_only_R2_calibration_equivalence_v1",
        "phase": "AWAITING_HUMAN_REVIEW",
        "p_values": "not_computed",
        "automatic_champion_selected": False,
        "confirmation_started": False,
        "final_development_selection": "NOT_PERFORMED",
        "scientific_acceptance": False,
    }
    for key, expected in required_result.items():
        if result.get(key) != expected:
            raise CognitionPairedInferenceError(f"R2 result field {key} changed")
    execution = _mapping(result.get("execution"), label="R2 execution")
    if (
        execution.get("adaptive82_target_accessed") is not False
        or execution.get("all_fixed_repeats_terminal") is not True
        or execution.get("required_evaluation_expected_count") != 400
        or execution.get("required_evaluation_success_count") != 400
        or execution.get("required_evaluations_succeeded") is not True
        or result.get("required_failure_rows") != []
        or result.get("repeat_failures") != []
    ):
        raise CognitionPairedInferenceError("R2 execution is not complete and valid")
    if (
        r2_contract.get("schema_version")
        != "br.hcp_calibration_equivalence_r2_contract.v1"
        or r2_contract.get("R2_design") != "calibration_equivalence_v1"
    ):
        raise CognitionPairedInferenceError("R2 contract identity changed")
    endpoint = _mapping(r2_contract.get("endpoint"), label="R2 endpoint")
    if (
        endpoint.get("target") != TARGET
        or endpoint.get("fold_local_covariate_sensitivity") is not False
    ):
        raise CognitionPairedInferenceError("R2 Cognition endpoint changed")
    arms = _required_list(r2_contract.get("arms"), label="R2 arms")
    fixed = [
        _mapping(arm, label="R2 arm")
        for arm in arms
        if isinstance(arm, Mapping) and arm.get("arm_id") == ARM_ID
    ]
    expected_arm = {
        "alpha": 1.0,
        "arm_id": ARM_ID,
        "calibration": "raw",
        "family": "C1",
        "term_index": 116,
    }
    if len(fixed) != 1 or dict(fixed[0]) != expected_arm:
        raise CognitionPairedInferenceError("R2 C1/term-116 arm changed")
    split = _mapping(r2_contract.get("split"), label="R2 split")
    development_indices = [int(value) for value in split.get("development_indices", [])]
    if (
        split.get("development_subject_count") != SUBJECTS
        or split.get("development_family_count") != FAMILIES
        or development_indices != snapshot.get("subject_indices")
    ):
        raise CognitionPairedInferenceError("R2 development split changed")
    if (
        splits.get("schema_version")
        != "br.hcp_calibration_equivalence_r2_splits.v1"
        or splits.get("family_grouped") is not True
        or splits.get("outer_folds") != OUTER_FOLDS
        or splits.get("inner_folds") != INNER_FOLDS
        or len(splits.get("repeats", [])) != REPEATS
        or splits.get("development_indices") != development_indices
    ):
        raise CognitionPairedInferenceError("R2 repeated split plan changed")
    if r2_contract.get("splits") != splits:
        raise CognitionPairedInferenceError(
            "R2 contract does not bind the persisted repeated split plan"
        )
    if (
        snapshot.get("schema_version")
        != "br.hcp_calibration_equivalence_r2_target_snapshot.v1"
        or len(snapshot.get("y_values", [])) != SUBJECTS
        or not np.all(np.isfinite(np.asarray(snapshot.get("y_values"), dtype=float)))
    ):
        raise CognitionPairedInferenceError("R2 frozen target snapshot changed")
    projection = _family_projection(r2_contract=r2_contract, snapshot=snapshot)
    liu = _mapping(r2_contract.get("liu_benchmark"), label="R2 Liu benchmark")
    source_binding = {
        "source_dir": str(source.resolve()),
        "source_schema_version": result["schema_version"],
        "source_analysis_label": result["analysis_label"],
        "source_phase": result["phase"],
        "source_p_values": result["p_values"],
        "target": TARGET,
        "fixed_arm": expected_arm,
        "matched_liu_procedure": {
            "candidate_count": liu.get("candidate_count"),
            "model_family_count": liu.get("model_family_count"),
            "alpha_count": liu.get("alpha_count"),
            "outer_fold_inner_selection": True,
        },
        "subject_count": SUBJECTS,
        "family_count": FAMILIES,
        "repeat_count": REPEATS,
        "outer_folds": OUTER_FOLDS,
        "inner_folds": INNER_FOLDS,
        "family_cluster_projection": projection,
    }
    return source_binding, projection


def prepare_contract(
    *,
    source_dir: Path,
    draws: int = DEFAULT_DRAWS,
    permutation_seed: int | None = None,
    bootstrap_seed: int | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    if draws < 99:
        raise CognitionPairedInferenceError("draws must be at least 99")
    if permutation_seed is None:
        permutation_seed = DEFAULT_PERMUTATION_SEED
    if bootstrap_seed is None:
        bootstrap_seed = DEFAULT_BOOTSTRAP_SEED
    source, projection = _source_binding(source_dir)
    contract = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "design": DESIGN,
        "source": source,
        "estimand": {
            "primary_statistic": (
                "median_across_10_repeats_of_pooled_oof_delta_signed_pearson_r_"
                "C1_raw_minus_matched_liu"
            ),
            "direction": "one_sided_C1_raw_greater_than_matched_liu",
            "cell_count": 1,
            "repeats_are_independent_samples": False,
            "companion_direction_gate": {
                "median_delta_r2_C1_raw_minus_liu": "greater_than_zero",
                "median_delta_mae_C1_raw_minus_liu": "less_than_zero",
                "inferential_p_values": False,
            },
        },
        "permutation_sensitivity": {
            "draws": draws,
            "seed": permutation_seed,
            "unit": "family_cluster",
            "action": "swap_C1_raw_and_liu_prediction_labels",
            "shared_swap_vector": "all_10_repeats",
            "raw_p": "one_sided_plus_one_monte_carlo",
            "multiplicity": "single_frozen_post_selection_cell_no_internal_adjustment",
            "interpretation": "conditional_algorithm_label_permutation_sensitivity",
        },
        "bootstrap_uncertainty": {
            "draws": draws,
            "seed": bootstrap_seed,
            "unit": "family_cluster",
            "shared_resample": "both_procedures_all_10_repeats",
            "interval": "pointwise_percentile_95_percent",
        },
        "execution": {
            "reads_persisted_oof_predictions_only": True,
            "full_refit": False,
            "raw_target_table_access": False,
            "adaptive82_target_access": False,
            "sealed_holdout_target_access": False,
            "automatic_champion_selection": False,
        },
        "claim_boundary": {
            "retrospective": True,
            "same_cohort": True,
            "post_selection_conditional_on_cognition_search": True,
            "conditional_on_persisted_fits_and_repeated_splits": True,
            "single_cell_nominal_p_is_sensitivity_only": True,
            "search_adjusted": False,
            "whole_procedure_leakage_free": False,
            "design_based_exact_randomization": False,
            "general_liu_procedure_superiority": False,
            "independent_replication": False,
            "external_validation": False,
            "confirmation": False,
            "scientific_acceptance": False,
        },
        "authority": {
            "authorization_required_before_launch": True,
            "confirmation_authorization": "NOT_GRANTED",
            "scientific_acceptance_authorization": "NOT_GRANTED",
        },
    }
    return contract, projection


def authorization_template(contract: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "design": contract.get("design"),
        "source_binding": contract.get("source"),
        "inference_binding": {
            "estimand": contract.get("estimand"),
            "permutation_sensitivity": contract.get("permutation_sensitivity"),
            "bootstrap_uncertainty": contract.get("bootstrap_uncertainty"),
        },
        "authorization_id": "",
        "authorized": False,
        "authorized_by": "",
        "conditional_sensitivity_acknowledged": False,
        "joint_exchangeability_assumption_acknowledged": False,
        "not_search_adjusted_acknowledged": False,
        "same_cohort_retrospective_acknowledged": False,
        "repeats_not_independent_acknowledged": False,
        "full_refit": False,
        "sealed_holdout_target_access": False,
        "confirmation_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
    }


def verify_authorization(
    *, contract: Mapping[str, object], authorization: Mapping[str, object]
) -> None:
    required = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "design": contract.get("design"),
        "authorized": True,
        "conditional_sensitivity_acknowledged": True,
        "joint_exchangeability_assumption_acknowledged": True,
        "not_search_adjusted_acknowledged": True,
        "same_cohort_retrospective_acknowledged": True,
        "repeats_not_independent_acknowledged": True,
        "full_refit": False,
        "sealed_holdout_target_access": False,
        "confirmation_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
    }
    for key, expected in required.items():
        if authorization.get(key) != expected:
            raise CognitionPairedInferenceError(
                f"authorization field {key} is not exact"
            )
    if authorization.get("source_binding") != contract.get("source"):
        raise CognitionPairedInferenceError("authorization source_binding is not exact")
    expected_inference = {
        "estimand": contract.get("estimand"),
        "permutation_sensitivity": contract.get("permutation_sensitivity"),
        "bootstrap_uncertainty": contract.get("bootstrap_uncertainty"),
    }
    if authorization.get("inference_binding") != expected_inference:
        raise CognitionPairedInferenceError("authorization inference_binding is not exact")
    for field in ("authorization_id", "authorized_by"):
        if not isinstance(authorization.get(field), str) or not str(
            authorization.get(field)
        ).strip():
            raise CognitionPairedInferenceError(f"{field} is required")


def write_prelaunch(
    *, output_dir: Path, source_dir: Path, draws: int = DEFAULT_DRAWS
) -> dict[str, Path]:
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise CognitionPairedInferenceError("output directory is not empty")
    contract, projection = prepare_contract(source_dir=source_dir, draws=draws)
    contract_path = destination / "cognition_paired_inference_contract.json"
    template_path = destination / "authorization.template.json"
    projection_path = destination / "private" / "family_cluster_projection.json"
    state_path = destination / "state.json"
    _write_json(contract_path, contract)
    _write_json(template_path, authorization_template(contract))
    os.chmod(template_path, 0o600)
    _write_json(projection_path, projection)
    os.chmod(projection_path, 0o600)
    _write_json(
        state_path,
        {
            "phase": "AWAITING_COGNITION_PAIRED_INFERENCE_AUTHORIZATION",
            "source_predictions_read": False,
            "inference_started": False,
            "scientific_acceptance": False,
        },
    )
    return {
        "contract": contract_path,
        "authorization_template": template_path,
        "family_cluster_projection": projection_path,
        "state": state_path,
    }


def _load_arrays(
    *, source_dir: Path, projection: Mapping[str, object]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    source = Path(source_dir)
    r2_contract = _read_json(source / "r2_contract.json", label="R2 contract")
    r2_splits = _read_json(source / "r2_splits.json", label="R2 splits")
    snapshot = _read_json(
        source / "private" / "development_target_snapshot.json",
        label="R2 target snapshot",
    )
    subject_indices = [int(value) for value in snapshot.get("subject_indices", [])]
    subject_ids = [str(value) for value in snapshot.get("subject_ids", [])]
    if (
        projection.get("subject_indices") != subject_indices
        or projection.get("subject_ids") != subject_ids
    ):
        raise CognitionPairedInferenceError(
            "family projection rows do not match R2 target snapshot"
        )
    family_ids = [str(value) for value in projection.get("family_ids", [])]
    if len(family_ids) != SUBJECTS or len(set(family_ids)) != FAMILIES:
        raise CognitionPairedInferenceError("family projection is invalid")
    unique_families = list(dict.fromkeys(family_ids))
    family_lookup = {family: index for index, family in enumerate(unique_families)}
    subject_family = np.asarray(
        [family_lookup[family] for family in family_ids], dtype=int
    )
    y = np.asarray(snapshot.get("y_values"), dtype=float)
    c1 = np.full((REPEATS, SUBJECTS), np.nan)
    liu = np.full((REPEATS, SUBJECTS), np.nan)
    position = {value: index for index, value in enumerate(subject_indices)}
    planned_repeats = _required_list(
        r2_splits.get("repeats"), label="R2 planned repeats"
    )
    if len(planned_repeats) != REPEATS:
        raise CognitionPairedInferenceError("R2 planned repeat count changed")
    for repeat_index in range(REPEATS):
        repeat = _read_json(
            source / "repeat_results" / f"repeat_{repeat_index + 1:02d}.json",
            label=f"R2 repeat {repeat_index + 1}",
        )
        planned_repeat = _mapping(
            planned_repeats[repeat_index], label="R2 planned repeat"
        )
        if (
            repeat.get("status") != "completed"
            or repeat.get("repeat_index") != repeat_index + 1
            or repeat.get("repeat_index") != planned_repeat.get("repeat_index")
            or repeat.get("seed") != planned_repeat.get("seed")
            or repeat.get("contract_binding") != r2_contract
            or repeat.get("required_failure_rows") != []
        ):
            raise CognitionPairedInferenceError("R2 repeat binding or status changed")
        folds = _required_list(repeat.get("outer_folds"), label="R2 outer folds")
        planned_folds = _required_list(
            planned_repeat.get("outer_folds"), label="R2 planned outer folds"
        )
        if len(folds) != OUTER_FOLDS or len(planned_folds) != OUTER_FOLDS:
            raise CognitionPairedInferenceError("R2 outer-fold count changed")
        seen: set[int] = set()
        for raw_fold, raw_planned_fold in zip(folds, planned_folds, strict=True):
            fold = _mapping(raw_fold, label="R2 outer fold")
            planned_fold = _mapping(raw_planned_fold, label="R2 planned outer fold")
            raw_indices = [int(value) for value in fold.get("outer_test_indices", [])]
            if (
                fold.get("outer_fold") != planned_fold.get("outer_fold")
                or raw_indices != planned_fold.get("test_indices")
            ):
                raise CognitionPairedInferenceError(
                    "R2 repeat outer test rows differ from frozen split plan"
                )
            try:
                indices = [position[value] for value in raw_indices]
            except KeyError as exc:
                raise CognitionPairedInferenceError(
                    "R2 outer test row is outside development snapshot"
                ) from exc
            if seen.intersection(indices):
                raise CognitionPairedInferenceError("R2 outer test rows overlap")
            seen.update(indices)
            arms = _mapping(fold.get("arms"), label="R2 arms")
            c1_record = _mapping(arms.get(ARM_ID), label="R2 C1 record")
            liu_record = _mapping(fold.get("liu_benchmark"), label="R2 Liu record")
            if (
                c1_record.get("status") != "succeeded"
                or liu_record.get("status") != "succeeded"
            ):
                raise CognitionPairedInferenceError("R2 C1 or Liu fold failed")
            c1_prediction = np.asarray(c1_record.get("y_pred"), dtype=float)
            liu_prediction = np.asarray(liu_record.get("y_pred"), dtype=float)
            if (
                c1_prediction.shape != (len(indices),)
                or liu_prediction.shape != (len(indices),)
                or not np.all(np.isfinite(c1_prediction))
                or not np.all(np.isfinite(liu_prediction))
            ):
                raise CognitionPairedInferenceError("R2 prediction rows are invalid")
            c1[repeat_index, indices] = c1_prediction
            liu[repeat_index, indices] = liu_prediction
        if len(seen) != SUBJECTS:
            raise CognitionPairedInferenceError(
                "R2 repeat does not cover every development subject exactly once"
            )
        pooled = _mapping(repeat.get("pooled_metrics"), label="R2 pooled metrics")
        pooled_arms = _mapping(pooled.get("arms"), label="R2 pooled arms")
        stored_c1 = _mapping(pooled_arms.get(ARM_ID), label="R2 pooled C1")
        stored_liu = _mapping(pooled.get("liu_benchmark"), label="R2 pooled Liu")
        for stored, computed in (
            (stored_c1, _metrics(y, c1[repeat_index])),
            (stored_liu, _metrics(y, liu[repeat_index])),
        ):
            for metric, value in computed.items():
                if not np.isclose(float(stored.get(metric)), value, atol=1e-10):
                    raise CognitionPairedInferenceError(
                        f"R2 persisted {metric} does not match predictions"
                    )
    if not all(np.all(np.isfinite(value)) for value in (y, c1, liu)):
        raise CognitionPairedInferenceError("R2 arrays contain non-finite values")
    return y, c1, liu, subject_family, unique_families


def _repeat_metrics(
    y: np.ndarray, c1: np.ndarray, liu: np.ndarray
) -> tuple[list[dict[str, float | int]], float]:
    rows: list[dict[str, float | int]] = []
    for repeat in range(REPEATS):
        c1_metrics = _metrics(y, c1[repeat])
        liu_metrics = _metrics(y, liu[repeat])
        rows.append(
            {
                "repeat_index": repeat + 1,
                "c1_r": c1_metrics["signed_pearson_r"],
                "liu_r": liu_metrics["signed_pearson_r"],
                "delta_r": c1_metrics["signed_pearson_r"]
                - liu_metrics["signed_pearson_r"],
                "c1_r2": c1_metrics["r2"],
                "liu_r2": liu_metrics["r2"],
                "delta_r2": c1_metrics["r2"] - liu_metrics["r2"],
                "c1_mae": c1_metrics["mae"],
                "liu_mae": liu_metrics["mae"],
                "delta_mae": c1_metrics["mae"] - liu_metrics["mae"],
            }
        )
    return rows, float(np.median([float(row["delta_r"]) for row in rows]))


def _permutation_statistics(
    *,
    y: np.ndarray,
    c1: np.ndarray,
    liu: np.ndarray,
    subject_family: np.ndarray,
    family_count: int,
    draws: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    output = np.empty(draws, dtype=float)
    for draw in range(draws):
        swap = rng.integers(0, 2, size=family_count, dtype=np.int8)[
            subject_family
        ].astype(bool)
        deltas = []
        for repeat in range(REPEATS):
            permuted_c1 = np.where(swap, liu[repeat], c1[repeat])
            permuted_liu = np.where(swap, c1[repeat], liu[repeat])
            deltas.append(_corr(y, permuted_c1) - _corr(y, permuted_liu))
        output[draw] = float(np.median(deltas))
    return output


def _bootstrap_statistics(
    *,
    y: np.ndarray,
    c1: np.ndarray,
    liu: np.ndarray,
    subject_family: np.ndarray,
    family_count: int,
    draws: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    members = [np.flatnonzero(subject_family == index) for index in range(family_count)]
    output = np.empty(draws, dtype=float)
    for draw in range(draws):
        sampled = rng.integers(0, family_count, size=family_count)
        indices = np.concatenate([members[index] for index in sampled])
        _, output[draw] = _repeat_metrics(
            y[indices], c1[:, indices], liu[:, indices]
        )
    return output


def run_inference(*, output_dir: Path) -> dict[str, object]:
    destination = Path(output_dir)
    result_path = destination / "cognition_paired_inference_result.json"
    if result_path.exists():
        raise CognitionPairedInferenceError("inference result already exists")
    contract = _read_json(
        destination / "cognition_paired_inference_contract.json",
        label="Cognition inference contract",
    )
    source = _mapping(contract.get("source"), label="source")
    permutation = _mapping(
        contract.get("permutation_sensitivity"), label="permutation"
    )
    bootstrap = _mapping(contract.get("bootstrap_uncertainty"), label="bootstrap")
    expected, _ = prepare_contract(
        source_dir=Path(str(source.get("source_dir"))),
        draws=int(permutation.get("draws")),
        permutation_seed=int(permutation.get("seed")),
        bootstrap_seed=int(bootstrap.get("seed")),
    )
    if contract != expected:
        raise CognitionPairedInferenceError(
            "inference contract differs from current R2 source"
        )
    projection = _read_json(
        destination / "private" / "family_cluster_projection.json",
        label="family projection",
    )
    if projection != source.get("family_cluster_projection"):
        raise CognitionPairedInferenceError("family projection binding changed")
    authorization = _read_json(
        destination / "authorization.json", label="inference authorization"
    )
    verify_authorization(contract=contract, authorization=authorization)
    _write_json(
        destination / "state.json",
        {
            "phase": "RUNNING_COGNITION_PAIRED_SENSITIVITY",
            "source_predictions_read": True,
            "inference_started": True,
            "scientific_acceptance": False,
        },
    )
    y, c1, liu, subject_family, families = _load_arrays(
        source_dir=Path(str(source.get("source_dir"))), projection=projection
    )
    repeat_rows, observed = _repeat_metrics(y, c1, liu)
    draws = int(permutation.get("draws"))
    permuted = _permutation_statistics(
        y=y,
        c1=c1,
        liu=liu,
        subject_family=subject_family,
        family_count=len(families),
        draws=draws,
        seed=int(permutation.get("seed")),
    )
    extreme_draws = int(np.sum(permuted >= observed))
    p_value = float((1 + extreme_draws) / (draws + 1))
    bootstrapped = _bootstrap_statistics(
        y=y,
        c1=c1,
        liu=liu,
        subject_family=subject_family,
        family_count=len(families),
        draws=int(bootstrap.get("draws")),
        seed=int(bootstrap.get("seed")),
    )
    interval = np.quantile(bootstrapped, [0.025, 0.975])
    deltas_r2 = [float(row["delta_r2"]) for row in repeat_rows]
    deltas_mae = [float(row["delta_mae"]) for row in repeat_rows]
    companion = {
        "median_delta_r2": float(np.median(deltas_r2)),
        "positive_delta_r2_repeat_count": int(np.sum(np.asarray(deltas_r2) > 0)),
        "median_delta_mae": float(np.median(deltas_mae)),
        "lower_mae_repeat_count": int(np.sum(np.asarray(deltas_mae) < 0)),
        "direction_gate_passed": bool(
            np.median(deltas_r2) > 0 and np.median(deltas_mae) < 0
        ),
        "p_values_computed": False,
    }
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "phase": "AWAITING_HUMAN_SCIENTIFIC_REVIEW",
        "frozen_contract": contract,
        "target": TARGET,
        "fixed_arm": ARM_ID,
        "comparator": "matched_nested_liu_procedure",
        "observed_median_repeat_delta_r": observed,
        "conditional_one_sided_plus_one_p": p_value,
        "extreme_draws": extreme_draws,
        "draws": draws,
        "family_cluster_bootstrap_pointwise_95_ci": [
            float(interval[0]),
            float(interval[1]),
        ],
        "repeat_metrics": repeat_rows,
        "companion_direction_gate": companion,
        "automatic_champion_selected": False,
        "confirmation_started": False,
        "sealed_holdout_target_access": False,
        "external_validation": False,
        "scientific_acceptance": False,
    }
    _write_json(result_path, result)
    _write_json(
        destination / "state.json",
        {
            "phase": result["phase"],
            "source_predictions_read": True,
            "inference_started": True,
            "result_written": True,
            "scientific_acceptance": False,
        },
    )
    return result


__all__ = [
    "AUTHORIZATION_SCHEMA_VERSION",
    "CONTRACT_SCHEMA_VERSION",
    "CognitionPairedInferenceError",
    "DEFAULT_DRAWS",
    "DESIGN",
    "RESULT_SCHEMA_VERSION",
    "authorization_template",
    "configure_inference_runtime",
    "prepare_contract",
    "run_inference",
    "verify_authorization",
    "write_prelaunch",
]
