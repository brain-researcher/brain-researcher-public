"""Conditional inference for persisted HCP cross-component OOF predictions.

This successor reads a completed R3 transfer bundle without refitting models.  Its
permutation diagnostic is conditional on joint algorithm-label exchangeability;
it is not search-adjusted inference or confirmation.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

import numpy as np

SCHEMA_VERSION = "br.hcp_cross_component_transfer_inference_contract.v1"
AUTHORIZATION_SCHEMA_VERSION = (
    "br.hcp_cross_component_transfer_inference_authorization.v1"
)
RESULT_SCHEMA_VERSION = "br.hcp_cross_component_transfer_inference_result.v1"
DESIGN = "r3_conditional_paired_sensitivity_v1"
TARGETS = (
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_IllicitDrugUse",
    "ICA_MentalHealth",
)
ARMS = ("A2_raw", "A3a_raw", "A3b_raw", "A4_raw", "C1_raw")
REPEATS = 10
SUBJECTS = 244
FAMILIES = 243
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


class TransferInferenceError(RuntimeError):
    """Raised when the frozen inference contract cannot be honored."""


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransferInferenceError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransferInferenceError(f"{label} must be a JSON object")
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
        raise TransferInferenceError(f"{label} must be an object")
    return value


def _source_summary(source_dir: Path) -> dict[str, object]:
    source = Path(source_dir)
    result = _read_json(source / "cross_component_result.json", label="R3 result")
    identity = _read_json(
        source / "private" / "development_identity.json",
        label="R3 development identity",
    )
    targets = _read_json(
        source / "private" / "development_target_snapshots.json",
        label="R3 target snapshot",
    )
    if result.get("phase") != "AWAITING_HUMAN_SCIENTIFIC_REVIEW":
        raise TransferInferenceError("R3 source is not terminal and reviewable")
    if result.get("p_values") != "not_computed":
        raise TransferInferenceError("R3 source p-value boundary changed")
    if result.get("scientific_acceptance") is not False:
        raise TransferInferenceError("R3 source scientific boundary changed")
    if len(identity.get("subject_ids", [])) != SUBJECTS:
        raise TransferInferenceError("R3 source subject count changed")
    family_ids = identity.get("family_ids")
    if not isinstance(family_ids, list) or len(set(family_ids)) != FAMILIES:
        raise TransferInferenceError("R3 source family count changed")
    target_values = targets.get("targets")
    if not isinstance(target_values, Mapping) or set(target_values) != set(TARGETS):
        raise TransferInferenceError("R3 source target set changed")
    return {
        "source_dir": str(source.resolve()),
        "source_phase": result["phase"],
        "source_analysis_label": result.get("analysis_label"),
        "subject_count": SUBJECTS,
        "family_count": FAMILIES,
        "targets": list(TARGETS),
        "arms": list(ARMS),
        "repeat_count": REPEATS,
        "cell_count": len(TARGETS) * len(ARMS),
    }


def prepare_contract(
    *,
    source_dir: Path,
    draws: int = DEFAULT_DRAWS,
    permutation_seed: int | None = None,
    bootstrap_seed: int | None = None,
) -> dict[str, object]:
    if draws < 99:
        raise TransferInferenceError("draws must be at least 99")
    if permutation_seed is None:
        permutation_seed = DEFAULT_PERMUTATION_SEED
    if bootstrap_seed is None:
        bootstrap_seed = DEFAULT_BOOTSTRAP_SEED
    source = _source_summary(source_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "design": DESIGN,
        "source": source,
        "estimand": {
            "primary_statistic": (
                "median_across_10_repeats_of_pooled_oof_delta_signed_pearson_r_"
                "fixed_arm_minus_liu"
            ),
            "cells": "4_targets_x_5_cognition_nominated_fixed_configurations",
            "direction": "one_sided_fixed_arm_greater_than_liu",
            "repeats_are_independent_samples": False,
        },
        "permutation_sensitivity": {
            "draws": draws,
            "seed": permutation_seed,
            "unit": "family_cluster",
            "action": "swap_fixed_arm_and_liu_prediction_labels",
            "shared_swap_vector": "all_targets_arms_repeats",
            "raw_p": "plus_one_monte_carlo",
            "multiplicity": "single_step_max_statistic_over_20_cells",
            "fwer_scope": "weak_fwer_under_complete_joint_exchangeability_null_only",
            "interpretation": "conditional_algorithm_label_permutation_sensitivity",
        },
        "bootstrap_uncertainty": {
            "draws": draws,
            "seed": bootstrap_seed,
            "unit": "family_cluster",
            "shared_resample": "all_targets_arms_repeats_procedures",
            "pointwise_interval": "percentile_95_percent",
            "simultaneous_interval": "max_absolute_studentized_95_percent_20_cells",
        },
        "execution": {
            "full_refit": False,
            "reads_persisted_oof_predictions_only": True,
            "automatic_champion_selection": False,
            "sealed_holdout_target_access": False,
        },
        "claim_boundary": {
            "supplementary_sensitivity_only": True,
            "retrospective": True,
            "same_cohort": True,
            "conditional_on_persisted_fits_splits_and_cognition_nominated_panel": True,
            "design_based_exact_randomization": False,
            "general_equal_performance_null": False,
            "strong_cellwise_fwer": False,
            "full_refit": False,
            "search_adjusted": False,
            "liu_procedure_superiority": False,
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
        "authorized": False,
        "authorized_by": "",
        "conditional_sensitivity_acknowledged": False,
        "joint_exchangeability_assumption_acknowledged": False,
        "weak_fwer_only_acknowledged": False,
        "not_search_adjusted_acknowledged": False,
        "same_cohort_retrospective_acknowledged": False,
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
        "weak_fwer_only_acknowledged": True,
        "not_search_adjusted_acknowledged": True,
        "same_cohort_retrospective_acknowledged": True,
        "full_refit": False,
        "sealed_holdout_target_access": False,
        "confirmation_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
    }
    for key, expected in required.items():
        if authorization.get(key) != expected:
            raise TransferInferenceError(f"authorization field {key} is not exact")
    if authorization.get("source_binding") != contract.get("source"):
        raise TransferInferenceError("authorization source_binding is not exact")
    expected_inference_binding = {
        "estimand": contract.get("estimand"),
        "permutation_sensitivity": contract.get("permutation_sensitivity"),
        "bootstrap_uncertainty": contract.get("bootstrap_uncertainty"),
    }
    if authorization.get("inference_binding") != expected_inference_binding:
        raise TransferInferenceError("authorization inference_binding is not exact")
    if not isinstance(authorization.get("authorized_by"), str) or not str(
        authorization.get("authorized_by")
    ).strip():
        raise TransferInferenceError("authorized_by is required")


def write_prelaunch(
    *, output_dir: Path, source_dir: Path, draws: int = DEFAULT_DRAWS
) -> dict[str, Path]:
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise TransferInferenceError("output directory is not empty")
    contract = prepare_contract(source_dir=source_dir, draws=draws)
    contract_path = destination / "transfer_inference_contract.json"
    template_path = destination / "authorization.template.json"
    state_path = destination / "state.json"
    _write_json(contract_path, contract)
    _write_json(template_path, authorization_template(contract))
    os.chmod(template_path, 0o600)
    _write_json(
        state_path,
        {
            "phase": "AWAITING_TRANSFER_INFERENCE_AUTHORIZATION",
            "source_predictions_read": False,
            "inference_started": False,
            "scientific_acceptance": False,
        },
    )
    return {
        "contract": contract_path,
        "authorization_template": template_path,
        "state": state_path,
    }


def _corr(y: np.ndarray, prediction: np.ndarray) -> float:
    y_centered = y - np.mean(y)
    p_centered = prediction - np.mean(prediction)
    denominator = float(np.sqrt(np.sum(y_centered**2) * np.sum(p_centered**2)))
    return float(np.sum(y_centered * p_centered) / denominator) if denominator else 0.0


def _load_arrays(
    source_dir: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    source = Path(source_dir)
    identity = _read_json(
        source / "private" / "development_identity.json", label="identity"
    )
    snapshot = _read_json(
        source / "private" / "development_target_snapshots.json", label="targets"
    )
    source_indices = [int(value) for value in identity["subject_indices"]]
    identity_subject_ids = [str(value) for value in identity["subject_ids"]]
    snapshot_indices = [int(value) for value in snapshot["subject_indices"]]
    snapshot_subject_ids = [str(value) for value in snapshot["subject_ids"]]
    if (
        len(source_indices) != SUBJECTS
        or len(set(source_indices)) != SUBJECTS
        or len(identity_subject_ids) != SUBJECTS
        or len(set(identity_subject_ids)) != SUBJECTS
        or snapshot_indices != source_indices
        or snapshot_subject_ids != identity_subject_ids
    ):
        raise TransferInferenceError(
            "R3 target snapshot rows do not match development identity"
        )
    position = {value: index for index, value in enumerate(source_indices)}
    family_ids = [str(value) for value in identity["family_ids"]]
    unique_families = list(dict.fromkeys(family_ids))
    family_lookup = {value: index for index, value in enumerate(unique_families)}
    subject_family = np.asarray([family_lookup[value] for value in family_ids], dtype=int)
    target_map = _mapping(snapshot.get("targets"), label="target vectors")
    y = np.asarray([target_map[target] for target in TARGETS], dtype=float)
    ours = np.full((len(TARGETS), len(ARMS), REPEATS, SUBJECTS), np.nan)
    liu = np.full((len(TARGETS), REPEATS, SUBJECTS), np.nan)
    for target_index, target in enumerate(TARGETS):
        for repeat_index in range(REPEATS):
            checkpoint = _read_json(
                source
                / "target_results"
                / target
                / "repeat_results"
                / f"repeat_{repeat_index + 1:02d}.json",
                label=f"{target} repeat {repeat_index + 1}",
            )
            if checkpoint.get("status") != "completed":
                raise TransferInferenceError("R3 checkpoint is not completed")
            folds = checkpoint.get("outer_folds")
            if not isinstance(folds, list) or len(folds) != 5:
                raise TransferInferenceError("R3 outer-fold count changed")
            seen: set[int] = set()
            for raw_fold in folds:
                fold = _mapping(raw_fold, label="outer fold")
                indices = [position[int(value)] for value in fold["outer_test_indices"]]
                if seen.intersection(indices):
                    raise TransferInferenceError("R3 outer test indices overlap")
                seen.update(indices)
                arm_records = _mapping(fold.get("arms"), label="arm records")
                for arm_index, arm in enumerate(ARMS):
                    record = _mapping(arm_records.get(arm), label=arm)
                    ours[target_index, arm_index, repeat_index, indices] = np.asarray(
                        record["y_pred"], dtype=float
                    )
                liu_record = _mapping(fold.get("liu_benchmark"), label="Liu record")
                liu[target_index, repeat_index, indices] = np.asarray(
                    liu_record["y_pred"], dtype=float
                )
            if len(seen) != SUBJECTS:
                raise TransferInferenceError("R3 repeat does not cover development subjects")
    if not all(np.all(np.isfinite(value)) for value in (y, ours, liu)):
        raise TransferInferenceError("R3 arrays contain non-finite values")
    return y, ours, liu, subject_family, unique_families


def _statistic(y: np.ndarray, ours: np.ndarray, liu: np.ndarray) -> np.ndarray:
    output = np.empty((len(TARGETS), len(ARMS)), dtype=float)
    for target_index in range(len(TARGETS)):
        liu_r = np.asarray(
            [_corr(y[target_index], liu[target_index, repeat]) for repeat in range(REPEATS)]
        )
        for arm_index in range(len(ARMS)):
            arm_r = np.asarray(
                [
                    _corr(
                        y[target_index],
                        ours[target_index, arm_index, repeat],
                    )
                    for repeat in range(REPEATS)
                ]
            )
            output[target_index, arm_index] = float(np.median(arm_r - liu_r))
    return output


def _permutation_statistics(
    *,
    y: np.ndarray,
    ours: np.ndarray,
    liu: np.ndarray,
    subject_family: np.ndarray,
    family_count: int,
    draws: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    output = np.empty((draws, len(TARGETS), len(ARMS)), dtype=float)
    for draw in range(draws):
        swap = rng.integers(0, 2, size=family_count, dtype=np.int8)[subject_family].astype(
            bool
        )
        for target_index in range(len(TARGETS)):
            target = y[target_index]
            for arm_index in range(len(ARMS)):
                deltas = []
                for repeat in range(REPEATS):
                    arm_prediction = ours[target_index, arm_index, repeat]
                    liu_prediction = liu[target_index, repeat]
                    permuted_arm = np.where(swap, liu_prediction, arm_prediction)
                    permuted_liu = np.where(swap, arm_prediction, liu_prediction)
                    deltas.append(
                        _corr(target, permuted_arm) - _corr(target, permuted_liu)
                    )
                output[draw, target_index, arm_index] = float(np.median(deltas))
    return output


def _bootstrap_statistics(
    *,
    y: np.ndarray,
    ours: np.ndarray,
    liu: np.ndarray,
    subject_family: np.ndarray,
    family_count: int,
    draws: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    members = [np.flatnonzero(subject_family == index) for index in range(family_count)]
    output = np.empty((draws, len(TARGETS), len(ARMS)), dtype=float)
    for draw in range(draws):
        sampled = rng.integers(0, family_count, size=family_count)
        indices = np.concatenate([members[index] for index in sampled])
        output[draw] = _statistic(y[:, indices], ours[..., indices], liu[..., indices])
    return output


def run_inference(*, output_dir: Path) -> dict[str, object]:
    destination = Path(output_dir)
    result_path = destination / "transfer_inference_result.json"
    if result_path.exists():
        raise TransferInferenceError("inference result already exists")
    contract = _read_json(
        destination / "transfer_inference_contract.json", label="inference contract"
    )
    permutation = _mapping(contract["permutation_sensitivity"], label="permutation")
    bootstrap = _mapping(contract["bootstrap_uncertainty"], label="bootstrap")
    if contract != prepare_contract(
        source_dir=Path(_mapping(contract["source"], label="source")["source_dir"]),
        draws=int(permutation["draws"]),
        permutation_seed=int(permutation["seed"]),
        bootstrap_seed=int(bootstrap["seed"]),
    ):
        raise TransferInferenceError("inference contract differs from current R3 source")
    authorization = _read_json(
        destination / "authorization.json", label="inference authorization"
    )
    verify_authorization(contract=contract, authorization=authorization)
    _write_json(
        destination / "state.json",
        {
            "phase": "RUNNING_CONDITIONAL_TRANSFER_SENSITIVITY",
            "source_predictions_read": True,
            "inference_started": True,
            "scientific_acceptance": False,
        },
    )
    source_dir = Path(_mapping(contract["source"], label="source")["source_dir"])
    y, ours, liu, subject_family, families = _load_arrays(source_dir)
    draws = int(permutation["draws"])
    observed = _statistic(y, ours, liu)
    permuted = _permutation_statistics(
        y=y,
        ours=ours,
        liu=liu,
        subject_family=subject_family,
        family_count=len(families),
        draws=draws,
        seed=int(permutation["seed"]),
    )
    raw_p = (1 + np.sum(permuted >= observed[None, ...], axis=0)) / (draws + 1)
    maximum = np.max(permuted.reshape(draws, -1), axis=1)
    adjusted_p = np.asarray(
        [
            (1 + np.sum(maximum >= value)) / (draws + 1)
            for value in observed.ravel()
        ]
    ).reshape(observed.shape)
    bootstrapped = _bootstrap_statistics(
        y=y,
        ours=ours,
        liu=liu,
        subject_family=subject_family,
        family_count=len(families),
        draws=draws,
        seed=int(bootstrap["seed"]),
    )
    pointwise_low, pointwise_high = np.quantile(bootstrapped, [0.025, 0.975], axis=0)
    standard_error = np.std(bootstrapped, axis=0, ddof=1)
    safe_se = np.where(standard_error > 0, standard_error, 1.0)
    max_abs_t = np.max(
        np.abs((bootstrapped - observed[None, ...]) / safe_se[None, ...]).reshape(
            draws, -1
        ),
        axis=1,
    )
    critical = float(np.quantile(max_abs_t, 0.95))
    simultaneous_low = observed - critical * standard_error
    simultaneous_high = observed + critical * standard_error
    cells = []
    for target_index, target in enumerate(TARGETS):
        for arm_index, arm in enumerate(ARMS):
            cells.append(
                {
                    "target": target,
                    "arm_id": arm,
                    "observed_median_repeat_delta_r": float(
                        observed[target_index, arm_index]
                    ),
                    "conditional_raw_plus_one_p": float(raw_p[target_index, arm_index]),
                    "conditional_weak_fwer_max_stat_p": float(
                        adjusted_p[target_index, arm_index]
                    ),
                    "bootstrap_pointwise_95_ci": [
                        float(pointwise_low[target_index, arm_index]),
                        float(pointwise_high[target_index, arm_index]),
                    ],
                    "bootstrap_simultaneous_95_ci": [
                        float(simultaneous_low[target_index, arm_index]),
                        float(simultaneous_high[target_index, arm_index]),
                    ],
                }
            )
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "phase": "AWAITING_HUMAN_SCIENTIFIC_REVIEW",
        "frozen_contract": contract,
        "cells": cells,
        "draws": draws,
        "automatic_champion_selected": False,
        "confirmation_started": False,
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
            "scientific_acceptance": False,
        },
    )
    return result


__all__ = [
    "ARMS",
    "DESIGN",
    "TARGETS",
    "TransferInferenceError",
    "authorization_template",
    "configure_inference_runtime",
    "prepare_contract",
    "run_inference",
    "verify_authorization",
    "write_prelaunch",
]
