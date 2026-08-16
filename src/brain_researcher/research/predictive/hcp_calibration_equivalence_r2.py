"""Frozen development-only R2 calibration-equivalence procedure for HCP.

This module deliberately never opens the adaptive82 target.  R2 evaluates
seven fixed arms on the existing 244-row / 243-family development partition
under ten predeclared shuffled family GroupKFold repeats.  The Liu benchmark
is re-run from source for every outer fold; historic Liu predictions are not
an input to any score or selection.

``prepare`` materializes only an inactive authorization template, the exact
contract, and all split arrays.  ``launch`` is intentionally separate and
requires a human-supplied authorization bound to that contract.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from sklearn.kernel_ridge import KernelRidge
from sklearn.model_selection import GroupKFold

from brain_researcher.research.predictive import hcp_liu_matched_comparator as liu
from brain_researcher.research.predictive import hcp_nested100_replay as replay

CONTRACT_SCHEMA_VERSION = "br.hcp_calibration_equivalence_r2_contract.v1"
AUTHORIZATION_SCHEMA_VERSION = "br.hcp_calibration_equivalence_r2_authorization.v1"
SPLITS_SCHEMA_VERSION = "br.hcp_calibration_equivalence_r2_splits.v1"
RESULT_SCHEMA_VERSION = "br.hcp_calibration_equivalence_r2_result.v1"
STATE_SCHEMA_VERSION = "br.hcp_calibration_equivalence_r2_state.v1"
TARGET_SNAPSHOT_SCHEMA_VERSION = "br.hcp_calibration_equivalence_r2_target_snapshot.v1"
R2_DESIGN = "calibration_equivalence_v1"
TARGET = "ICA_Cognition"
COVARIATE_POLICY = "precomputed_age_sex_residualized_reconstructed_component_fixed"
TARGET_CONSTRUCTION = (
    "precomputed_age_sex_residualized_rank_IG_component_projection_not_fold_local"
)

DEVELOPMENT_SUBJECT_COUNT = 244
DEVELOPMENT_FAMILY_COUNT = 243
OUTER_FOLDS = 5
INNER_FOLDS = 3
REPEAT_SEEDS = (
    20260810,
    20260811,
    20260812,
    20260813,
    20260814,
    20260815,
    20260816,
    20260817,
    20260818,
    20260819,
)
DEFAULT_REPEAT_WORKERS = 4
TARGET_SNAPSHOT_RELATIVE_PATH = "private/development_target_snapshot.json"

LIU_COMMON_SUPPORT_COUNT = 76
LIU_EFFECTIVE_TERM_COUNT = 74
LIU_MODEL_FAMILY_COUNT = 4
LIU_ALPHA_COUNT = 4
LIU_CANDIDATE_COUNT = 1184


def configure_repeat_runtime(*, seeds: Sequence[int] | None = None, workers: int | None = None) -> None:
    """Override public caller runtime choices while retaining historical defaults."""

    global REPEAT_SEEDS, DEFAULT_REPEAT_WORKERS
    if seeds is not None:
        normalized = tuple(int(value) for value in seeds)
        if not normalized or any(value < 0 for value in normalized):
            raise CalibrationEquivalenceR2Error("repeat seeds must be non-negative")
        REPEAT_SEEDS = normalized
    if workers is not None:
        DEFAULT_REPEAT_WORKERS = _validate_repeat_workers(int(workers))

REPAIR_GATE = {
    "primary_pair": "A3b_cal_minus_A3b_raw",
    "median_delta_r2_at_least": 0.02,
    "positive_delta_r2_repeats_at_least": 8,
    "positive_delta_r2_repeat_denominator": 10,
    "median_delta_mae_at_most": 0.0,
    "median_heldout_calibration_slope_range": [0.8, 1.2],
    "decision_aid_not_acceptance": True,
    "p_values": "not_computed",
}

ARM_SPECS = (
    {
        "arm_id": "A2_raw",
        "family": "A2",
        "term_index": 17,
        "alpha": 0.1,
        "calibration": "raw",
    },
    {
        "arm_id": "A4_raw",
        "family": "A4",
        "term_index": 19,
        "alpha": 0.1,
        "calibration": "raw",
    },
    {
        "arm_id": "A3a_raw",
        "family": "A3a",
        "term_index": 18,
        "alpha": 0.1,
        "calibration": "raw",
    },
    {
        "arm_id": "A3a_cal",
        "family": "A3a",
        "term_index": 18,
        "alpha": 0.1,
        "calibration": "training_only_affine",
        "raw_arm_id": "A3a_raw",
    },
    {
        "arm_id": "A3b_raw",
        "family": "A3b",
        "term_index": 18,
        "alpha": 1.0,
        "calibration": "raw",
    },
    {
        "arm_id": "A3b_cal",
        "family": "A3b",
        "term_index": 18,
        "alpha": 1.0,
        "calibration": "training_only_affine",
        "raw_arm_id": "A3b_raw",
    },
    {
        "arm_id": "C1_raw",
        "family": "C1",
        "term_index": 116,
        "alpha": 1.0,
        "calibration": "raw",
    },
)
ARM_IDS = tuple(str(spec["arm_id"]) for spec in ARM_SPECS)
REQUIRED_EVALUATION_IDS = (*ARM_IDS, "liu_benchmark")


class CalibrationEquivalenceR2Error(ValueError):
    """The R2 contract, authority, or development-only execution is invalid."""


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationEquivalenceR2Error(f"cannot read {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise CalibrationEquivalenceR2Error(f"{label} must be a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CalibrationEquivalenceR2Error(f"{label} must be an object")
    return value


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CalibrationEquivalenceR2Error(f"{label} must be non-empty text")
    return value


def _as_indices(value: object, *, label: str, upper_bound: int) -> np.ndarray:
    if not isinstance(value, list) or not value:
        raise CalibrationEquivalenceR2Error(f"{label} must be a non-empty index list")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise CalibrationEquivalenceR2Error(f"{label} must contain integer indices")
    indices = np.asarray(value, dtype=np.int64)
    if np.any(indices < 0) or np.any(indices >= upper_bound):
        raise CalibrationEquivalenceR2Error(f"{label} has an out-of-range index")
    if len(set(indices.tolist())) != len(indices):
        raise CalibrationEquivalenceR2Error(f"{label} has duplicate indices")
    return indices


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _development_indices(
    *, dataset: replay.HCPDataset, nested100_result: Mapping[str, object]
) -> np.ndarray:
    if nested100_result.get("schema_version") != "br.hcp_nested100_replay.v1":
        raise CalibrationEquivalenceR2Error("unexpected nested100 result schema")
    split = _mapping(nested100_result.get("split"), label="nested100 split")
    development = _as_indices(
        split.get("development_indices"),
        label="nested100 development_indices",
        upper_bound=len(dataset.subject_ids),
    )
    if len(development) != DEVELOPMENT_SUBJECT_COUNT:
        raise CalibrationEquivalenceR2Error("R2 requires exactly 244 development rows")
    families = np.asarray(dataset.family_ids, dtype=str)
    if len(set(families[development])) != DEVELOPMENT_FAMILY_COUNT:
        raise CalibrationEquivalenceR2Error(
            "R2 requires exactly 243 development families"
        )
    canonical = replay.build_split_plan(
        dataset, replay.ReplayConfig()
    ).development_indices
    if development.tolist() != canonical.tolist():
        raise CalibrationEquivalenceR2Error(
            "R2 development rows differ from the canonical nested100 split"
        )
    return development


def _validate_r1_reference(r1_result: Mapping[str, object]) -> dict[str, object]:
    phase = r1_result.get("phase")
    if phase != "AWAITING_R2_AUTHORIZATION":
        raise CalibrationEquivalenceR2Error(
            "R2 requires an R1 result at AWAITING_R2_AUTHORIZATION"
        )
    template_rows = r1_result.get("template_results")
    if not isinstance(template_rows, list):
        raise CalibrationEquivalenceR2Error("R1 result lacks template_results")
    by_template = {
        row.get("template_id"): row
        for row in template_rows
        if isinstance(row, Mapping) and isinstance(row.get("template_id"), str)
    }
    required = (
        ("A2", 17, "A2_c01", 0.1),
        ("A3", 18, "A3_c02", 1.0),
        ("A4", 19, "A4_c01", 0.1),
        ("C1", 116, "C1_c01", 1.0),
    )
    binding: list[dict[str, object]] = []
    for template_id, term_index, candidate_id, alpha in required:
        row = by_template.get(template_id)
        if not isinstance(row, Mapping):
            raise CalibrationEquivalenceR2Error(f"R1 result lacks {template_id}")
        if row.get("model_family") != "kernelridgecosine":
            raise CalibrationEquivalenceR2Error(
                f"R1 {template_id} must use kernelridgecosine"
            )
        if row.get("term_index") != term_index:
            raise CalibrationEquivalenceR2Error(f"R1 {template_id} term drift")
        selection = _mapping(
            row.get("full_development_selection"),
            label=f"R1 {template_id} full development selection",
        )
        params = _mapping(
            selection.get("selected_params"), label=f"R1 {template_id} selected params"
        )
        if (
            selection.get("selected_candidate_id") != candidate_id
            or params.get("alpha") != alpha
        ):
            raise CalibrationEquivalenceR2Error(
                f"R1 {template_id} selected configuration drift"
            )
        binding.append(
            {
                "template_id": template_id,
                "model_family": "kernelridgecosine",
                "term_index": term_index,
                "selected_candidate_id": candidate_id,
                "selected_alpha": alpha,
            }
        )
    a3_selection = _mapping(
        _mapping(by_template["A3"], label="R1 A3").get("full_development_selection"),
        label="R1 A3 full development selection",
    )
    all_a3_configs = a3_selection.get("all_config_rows")
    if not isinstance(all_a3_configs, list) or not any(
        isinstance(row, Mapping)
        and row.get("candidate_id") == "A3_c01"
        and isinstance(row.get("params"), Mapping)
        and row["params"].get("alpha") == 0.1
        for row in all_a3_configs
    ):
        raise CalibrationEquivalenceR2Error(
            "R1 A3 must retain A3_c01 alpha 0.1 for the fixed R2 arm"
        )
    return {
        "schema_version": r1_result.get("schema_version"),
        "phase": phase,
        "fixed_arm_binding": binding,
        "R2_arm_set_historically_R1_adaptive_informed": True,
        "R2_runtime_adaptive82_outcome_access": False,
    }


def _validate_repeat_workers(repeat_workers: int) -> int:
    if isinstance(repeat_workers, bool) or not isinstance(repeat_workers, int):
        raise CalibrationEquivalenceR2Error("repeat_workers must be an integer")
    if repeat_workers < 1 or repeat_workers > len(REPEAT_SEEDS):
        raise CalibrationEquivalenceR2Error("repeat_workers must be between 1 and 10")
    return repeat_workers


def _build_repeat_splits(
    *, development_indices: np.ndarray, family_ids: Sequence[str]
) -> dict[str, object]:
    """Freeze all ten shuffled outer and family-grouped inner split arrays."""

    groups = np.asarray(family_ids, dtype=str)
    repeats: list[dict[str, object]] = []
    for repeat_index, seed in enumerate(REPEAT_SEEDS, start=1):
        outer = GroupKFold(n_splits=OUTER_FOLDS, shuffle=True, random_state=seed)
        outer_rows: list[dict[str, object]] = []
        for fold_index, (train_local, test_local) in enumerate(
            outer.split(development_indices, groups=groups[development_indices]),
            start=1,
        ):
            outer_train = development_indices[np.asarray(train_local, dtype=np.int64)]
            outer_test = development_indices[np.asarray(test_local, dtype=np.int64)]
            inner_seed = seed * 100 + fold_index
            inner = GroupKFold(
                n_splits=INNER_FOLDS, shuffle=True, random_state=inner_seed
            )
            inner_rows: list[dict[str, object]] = []
            for inner_index, (inner_train_local, inner_test_local) in enumerate(
                inner.split(outer_train, groups=groups[outer_train]), start=1
            ):
                inner_rows.append(
                    {
                        "inner_fold": inner_index,
                        "train_indices": outer_train[
                            np.asarray(inner_train_local, dtype=np.int64)
                        ].tolist(),
                        "validation_indices": outer_train[
                            np.asarray(inner_test_local, dtype=np.int64)
                        ].tolist(),
                    }
                )
            outer_rows.append(
                {
                    "outer_fold": fold_index,
                    "train_indices": outer_train.tolist(),
                    "test_indices": outer_test.tolist(),
                    "inner_folds": inner_rows,
                }
            )
        repeats.append(
            {
                "repeat_index": repeat_index,
                "seed": seed,
                "outer_folds": outer_rows,
            }
        )
    splits = {
        "schema_version": SPLITS_SCHEMA_VERSION,
        "development_indices": development_indices.tolist(),
        "repeat_seeds": list(REPEAT_SEEDS),
        "outer_folds": OUTER_FOLDS,
        "inner_folds": INNER_FOLDS,
        "family_grouped": True,
        "repeats": repeats,
    }
    _validate_split_arrays(splits=splits, family_ids=groups)
    return splits


def _validate_split_arrays(
    *, splits: Mapping[str, object], family_ids: np.ndarray
) -> None:
    development = _as_indices(
        splits.get("development_indices"),
        label="persisted development_indices",
        upper_bound=len(family_ids),
    )
    development_set = set(development.tolist())
    raw_repeats = splits.get("repeats")
    if not isinstance(raw_repeats, list) or len(raw_repeats) != len(REPEAT_SEEDS):
        raise CalibrationEquivalenceR2Error("split manifest must have ten repeats")
    for expected_repeat, raw_repeat in enumerate(raw_repeats, start=1):
        repeat = _mapping(raw_repeat, label="repeat split")
        if repeat.get("repeat_index") != expected_repeat:
            raise CalibrationEquivalenceR2Error("repeat split order is invalid")
        if repeat.get("seed") != REPEAT_SEEDS[expected_repeat - 1]:
            raise CalibrationEquivalenceR2Error("repeat split seed is invalid")
        outer_rows = repeat.get("outer_folds")
        if not isinstance(outer_rows, list) or len(outer_rows) != OUTER_FOLDS:
            raise CalibrationEquivalenceR2Error("repeat must have five outer folds")
        observed_outer_test: list[int] = []
        for expected_fold, raw_outer in enumerate(outer_rows, start=1):
            outer = _mapping(raw_outer, label="outer split")
            if outer.get("outer_fold") != expected_fold:
                raise CalibrationEquivalenceR2Error("outer split order is invalid")
            train = _as_indices(
                outer.get("train_indices"),
                label="outer train_indices",
                upper_bound=len(family_ids),
            )
            test = _as_indices(
                outer.get("test_indices"),
                label="outer test_indices",
                upper_bound=len(family_ids),
            )
            if set(train.tolist()) | set(test.tolist()) != development_set:
                raise CalibrationEquivalenceR2Error(
                    "outer fold is not a development partition"
                )
            if set(train.tolist()) & set(test.tolist()):
                raise CalibrationEquivalenceR2Error("outer fold row overlap")
            if set(family_ids[train]) & set(family_ids[test]):
                raise CalibrationEquivalenceR2Error("outer fold family overlap")
            observed_outer_test.extend(test.tolist())
            inner_rows = outer.get("inner_folds")
            if not isinstance(inner_rows, list) or len(inner_rows) != INNER_FOLDS:
                raise CalibrationEquivalenceR2Error(
                    "outer train must have three inner folds"
                )
            observed_inner_validation: list[int] = []
            outer_train_set = set(train.tolist())
            for expected_inner, raw_inner in enumerate(inner_rows, start=1):
                inner = _mapping(raw_inner, label="inner split")
                if inner.get("inner_fold") != expected_inner:
                    raise CalibrationEquivalenceR2Error("inner split order is invalid")
                inner_train = _as_indices(
                    inner.get("train_indices"),
                    label="inner train_indices",
                    upper_bound=len(family_ids),
                )
                validation = _as_indices(
                    inner.get("validation_indices"),
                    label="inner validation_indices",
                    upper_bound=len(family_ids),
                )
                if (
                    set(inner_train.tolist()) | set(validation.tolist())
                    != outer_train_set
                ):
                    raise CalibrationEquivalenceR2Error(
                        "inner fold is not an outer-train partition"
                    )
                if set(inner_train.tolist()) & set(validation.tolist()):
                    raise CalibrationEquivalenceR2Error("inner fold row overlap")
                if set(family_ids[inner_train]) & set(family_ids[validation]):
                    raise CalibrationEquivalenceR2Error("inner fold family overlap")
                observed_inner_validation.extend(validation.tolist())
            if sorted(observed_inner_validation) != sorted(train.tolist()):
                raise CalibrationEquivalenceR2Error(
                    "inner validation union is incomplete"
                )
        if sorted(observed_outer_test) != sorted(development.tolist()):
            raise CalibrationEquivalenceR2Error("outer test union is incomplete")


def _liu_effective_terms(
    *,
    dataset: replay.HCPDataset,
    development_indices: np.ndarray,
    metric_catalog: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Run Liu's target-blind development eligibility screen only."""

    cached_terms = liu._common_support_term_metadata(
        dataset=dataset, metric_catalog=metric_catalog
    )
    placeholder = replay.SplitPlan(
        development_indices=development_indices,
        repartition_indices=np.empty(0, dtype=np.int64),
        outer_splits=(),
        final_inner_splits=(),
    )
    effective_terms, excluded_terms = liu._development_term_eligibility(
        dataset=dataset,
        split_plan=placeholder,
        cached_terms=cached_terms,
    )
    if len(cached_terms) != LIU_COMMON_SUPPORT_COUNT:
        raise CalibrationEquivalenceR2Error("Liu common support must contain 76 terms")
    if len(effective_terms) != LIU_EFFECTIVE_TERM_COUNT:
        raise CalibrationEquivalenceR2Error(
            "Liu development eligibility must retain 74 terms"
        )
    candidates = liu.frozen_liu_candidates(
        tuple(int(row["term_index"]) for row in effective_terms)
    )
    if len(candidates) != LIU_CANDIDATE_COUNT:
        raise CalibrationEquivalenceR2Error("Liu frozen candidate count must be 1184")
    return list(effective_terms), list(excluded_terms)


def _validate_liu_frozen_contract(
    *,
    liu_frozen_contract: Mapping[str, object],
    effective_terms: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    primary = _mapping(
        liu_frozen_contract.get("primary_common_support_procedure"),
        label="Liu frozen common-support procedure",
    )
    expected = {
        "cached_term_count": LIU_COMMON_SUPPORT_COUNT,
        "term_count": LIU_EFFECTIVE_TERM_COUNT,
        "candidate_count": LIU_CANDIDATE_COUNT,
    }
    for key, value in expected.items():
        if primary.get(key) != value:
            raise CalibrationEquivalenceR2Error(
                f"Liu frozen contract {key} does not match R2"
            )
    if primary.get("model_families") != list(liu.MODEL_FAMILIES):
        raise CalibrationEquivalenceR2Error("Liu frozen contract model families differ")
    if primary.get("alpha_grid") != list(liu.ALPHA_GRID):
        raise CalibrationEquivalenceR2Error("Liu frozen contract alpha grid differs")
    raw_terms = primary.get("terms")
    if not isinstance(raw_terms, list):
        raise CalibrationEquivalenceR2Error("Liu frozen contract terms must be a list")
    current_indices = [int(row["term_index"]) for row in effective_terms]
    frozen_indices = [
        int(_mapping(row, label="Liu frozen term").get("term_index"))
        for row in raw_terms
    ]
    if frozen_indices != current_indices:
        raise CalibrationEquivalenceR2Error(
            "Liu frozen contract effective terms differ from current source"
        )
    return {
        "schema_version": liu_frozen_contract.get("schema_version"),
        "cached_term_count": primary.get("cached_term_count"),
        "term_count": primary.get("term_count"),
        "candidate_count": primary.get("candidate_count"),
        "old_liu_predictions_or_fixed_pipeline": "forbidden",
    }


def prepare_calibration_equivalence_contract(
    *,
    dataset: replay.HCPDataset,
    nested100_result: Mapping[str, object],
    r1_result: Mapping[str, object],
    metric_catalog: Sequence[Mapping[str, object]],
    liu_frozen_contract: Mapping[str, object],
    source_paths: Mapping[str, str],
    repeat_workers: int = DEFAULT_REPEAT_WORKERS,
) -> dict[str, object]:
    """Freeze R2 without reading any adaptive82 target value."""

    workers = _validate_repeat_workers(repeat_workers)
    development = _development_indices(
        dataset=dataset, nested100_result=nested100_result
    )
    splits = _build_repeat_splits(
        development_indices=development, family_ids=dataset.family_ids
    )
    effective_terms, excluded_terms = _liu_effective_terms(
        dataset=dataset,
        development_indices=development,
        metric_catalog=metric_catalog,
    )
    liu_reference = _validate_liu_frozen_contract(
        liu_frozen_contract=liu_frozen_contract, effective_terms=effective_terms
    )
    r1_reference = _validate_r1_reference(r1_result)
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "round": "R2",
        "R2_design": R2_DESIGN,
        "source_paths": dict(source_paths),
        "source_reference": {
            "nested100_schema_version": nested100_result.get("schema_version"),
            "r1": r1_reference,
            "liu": liu_reference,
            "liu_result_content_read": False,
        },
        "endpoint": {
            "target": TARGET,
            "covariate_policy": COVARIATE_POLICY,
            "target_construction": TARGET_CONSTRUCTION,
            "fold_local_covariate_sensitivity": False,
        },
        "split": {
            "development_indices": development.tolist(),
            "development_subject_count": DEVELOPMENT_SUBJECT_COUNT,
            "development_family_count": DEVELOPMENT_FAMILY_COUNT,
            "adaptive82_target_access": "forbidden",
            "adaptive82_prediction": "forbidden",
            "family_grouped": True,
        },
        "development_target_snapshot": {
            "relative_path": TARGET_SNAPSHOT_RELATIVE_PATH,
            "schema_version": TARGET_SNAPSHOT_SCHEMA_VERSION,
            "subject_count": DEVELOPMENT_SUBJECT_COUNT,
            "prepare_source_target_reads": 1,
            "launch_current_source_compare": "exact_development_rows_only",
            "execution_target_dataflow": "frozen_snapshot_only_after_exact_compare",
            "adaptive82_included": False,
        },
        "splits": splits,
        "arms": [dict(spec) for spec in ARM_SPECS],
        "calibration": {
            "method": "unconstrained_OLS_y_equals_a_plus_b_raw_prediction",
            "fit_scope": "outer_train_inner_3fold_OOF_only",
            "base_preprocessing": "fold_local_QCoD_10_90_then_StandardScaler",
            "outer_test_application": "same_outer_train_a_plus_b_times_same_raw_prediction",
            "raw_prediction_sharing": True,
            "primary_pair": "A3b_cal_minus_A3b_raw",
        },
        "repair_gate": dict(REPAIR_GATE),
        "liu_benchmark": {
            "role": "nonselectable_FULL_frozen_matched_common_support",
            "cached_common_support_term_count": LIU_COMMON_SUPPORT_COUNT,
            "development_eligible_term_count": LIU_EFFECTIVE_TERM_COUNT,
            "model_family_count": LIU_MODEL_FAMILY_COUNT,
            "alpha_count": LIU_ALPHA_COUNT,
            "candidate_count": LIU_CANDIDATE_COUNT,
            "selection": "each_outer_train_3fold_mean_inner_default_R2_then_candidate_id",
            "effective_terms": list(effective_terms),
            "excluded_terms": list(excluded_terms),
            "final_development_selection": "forbidden",
            "old_liu_predictions_or_fixed_pipeline": "forbidden",
        },
        "execution": {
            "repeat_workers": workers,
            "repeat_parallelism": "independent_repeat_workers_with_separate_dataset_and_feature_caches",
            "result_order": "repeat_index_ascending",
            "checkpointing": "one_atomic_repeat_result_per_completed_or_failed_repeat",
            "failure_policy": "record_without_replacement_and_continue_all_fixed_work",
            "final_development_selection": "forbidden",
            "adaptive82_prediction": "forbidden",
        },
        "authority": {
            "authorization_required_before_launch": True,
            "confirmation_authorization": "NOT_GRANTED",
            "R3_authorization": "NOT_GRANTED",
            "scientific_acceptance_authorization": "NOT_GRANTED",
        },
        "claim_boundary": {
            "development_only_same_cohort_stability_evaluation": True,
            "R2_arm_set_historically_R1_adaptive_informed": True,
            "R2_runtime_adaptive82_outcome_access": False,
            "only_calibrator_is_training_only": True,
            "whole_R2_procedure_is_wholly_leakage_free": False,
            "holdout_or_confirmation": False,
            "automatic_champion_selection": False,
            "R3_started": False,
            "scientific_acceptance": False,
            "p_values": "not_computed",
        },
    }


def build_authorization_template(
    *, contract: Mapping[str, object]
) -> dict[str, object]:
    """Create an inactive, exact-contract-bound human authorization template."""

    return {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorization_id": "hcp_calibration_equivalence_r2_20260810_01",
        "authorized": False,
        "authorized_by": None,
        "R2_design": R2_DESIGN,
        "include_liu_benchmark": True,
        "reuse_adaptive82": False,
        "fold_local_covariate_sensitivity": False,
        "repair_thresholds_acknowledged": False,
        "launch_after_contract_validation": True,
        "confirmation_authorization": "NOT_GRANTED",
        "R3_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
        "contract_binding": dict(contract),
    }


def verify_authorization(
    *, contract: Mapping[str, object], authorization: Mapping[str, object]
) -> None:
    """Require the exact authority literals and the complete frozen contract."""

    if authorization.get("schema_version") != AUTHORIZATION_SCHEMA_VERSION:
        raise CalibrationEquivalenceR2Error("unexpected R2 authorization schema")
    required = {
        "authorized": True,
        "R2_design": R2_DESIGN,
        "include_liu_benchmark": True,
        "reuse_adaptive82": False,
        "fold_local_covariate_sensitivity": False,
        "repair_thresholds_acknowledged": True,
        "launch_after_contract_validation": True,
        "confirmation_authorization": "NOT_GRANTED",
        "R3_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
    }
    for key, expected in required.items():
        if authorization.get(key) != expected:
            raise CalibrationEquivalenceR2Error(
                f"R2 authorization field {key} is invalid"
            )
    _required_text(authorization.get("authorized_by"), label="R2 authorized_by")
    if authorization.get("contract_binding") != dict(contract):
        raise CalibrationEquivalenceR2Error(
            "R2 authorization is not bound to the exact full contract"
        )


def build_development_target_snapshot(
    *,
    dataset: replay.HCPDataset,
    contract: Mapping[str, object],
    target_accessor: Callable[
        [replay.HCPDataset, np.ndarray], np.ndarray
    ] = replay._targets_for_indices,
) -> dict[str, object]:
    """Read exactly the frozen 244-row endpoint once for prepare or launch."""

    split = _mapping(contract.get("split"), label="contract split")
    indices = _as_indices(
        split.get("development_indices"),
        label="contract development_indices",
        upper_bound=len(dataset.subject_ids),
    )
    if len(indices) != DEVELOPMENT_SUBJECT_COUNT:
        raise CalibrationEquivalenceR2Error(
            "target snapshot requires 244 development rows"
        )
    values = np.asarray(target_accessor(dataset, indices), dtype=np.float64)
    if values.shape != (len(indices),) or not np.all(np.isfinite(values)):
        raise CalibrationEquivalenceR2Error(
            "development target snapshot values are invalid"
        )
    return {
        "schema_version": TARGET_SNAPSHOT_SCHEMA_VERSION,
        "subject_indices": indices.tolist(),
        "subject_ids": [dataset.subject_ids[index] for index in indices],
        "y_values": values.tolist(),
    }


def _target_snapshot_y_full(
    *,
    dataset: replay.HCPDataset,
    contract: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> np.ndarray:
    declaration = _mapping(
        contract.get("development_target_snapshot"), label="target snapshot declaration"
    )
    if snapshot.get("schema_version") != declaration.get("schema_version"):
        raise CalibrationEquivalenceR2Error(
            "development target snapshot schema differs"
        )
    indices = _as_indices(
        snapshot.get("subject_indices"),
        label="snapshot subject_indices",
        upper_bound=len(dataset.subject_ids),
    )
    expected_indices = _as_indices(
        _mapping(contract.get("split"), label="contract split").get(
            "development_indices"
        ),
        label="contract development_indices",
        upper_bound=len(dataset.subject_ids),
    )
    if indices.tolist() != expected_indices.tolist():
        raise CalibrationEquivalenceR2Error(
            "development target snapshot indices differ from contract"
        )
    raw_subject_ids = snapshot.get("subject_ids")
    if not isinstance(raw_subject_ids, list) or raw_subject_ids != [
        dataset.subject_ids[index] for index in indices
    ]:
        raise CalibrationEquivalenceR2Error(
            "development target snapshot subject IDs differ from source rows"
        )
    values = np.asarray(snapshot.get("y_values"), dtype=np.float64)
    if values.shape != (len(indices),) or not np.all(np.isfinite(values)):
        raise CalibrationEquivalenceR2Error(
            "development target snapshot y values are invalid"
        )
    full = np.full(len(dataset.subject_ids), np.nan, dtype=np.float64)
    full[indices] = values
    return full


def read_development_target_snapshot(output_dir: Path) -> dict[str, object]:
    return _read_json(
        Path(output_dir) / TARGET_SNAPSHOT_RELATIVE_PATH,
        label="development target snapshot",
    )


def write_prelaunch_artifacts(
    *,
    output_dir: Path,
    dataset: replay.HCPDataset,
    contract: Mapping[str, object],
    development_target_snapshot: Mapping[str, object],
) -> dict[str, Path]:
    """Write the contract, all split arrays, and an inactive template once."""

    destination = Path(output_dir)
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CalibrationEquivalenceR2Error(
            "R2 prepare requires a new output directory"
        ) from exc
    _target_snapshot_y_full(
        dataset=dataset,
        contract=contract,
        snapshot=development_target_snapshot,
    )
    authorization = build_authorization_template(contract=contract)
    paths = {
        "contract": _write_json(destination / "r2_contract.json", contract),
        "splits": _write_json(
            destination / "r2_splits.json",
            _mapping(contract.get("splits"), label="contract splits"),
        ),
        "authorization": _write_json(destination / "authorization.json", authorization),
        "development_target_snapshot": _write_json(
            destination / TARGET_SNAPSHOT_RELATIVE_PATH,
            development_target_snapshot,
        ),
        "state": _write_json(
            destination / "state.json",
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "phase": "AWAITING_R2_AUTHORIZATION",
                "development_target_snapshot_written": True,
                "adaptive82_target_accessed": False,
                "R3_authorization": "NOT_GRANTED",
                "confirmation_started": False,
                "scientific_acceptance": False,
            },
        ),
    }
    os.chmod(paths["authorization"], 0o600)
    os.chmod(paths["development_target_snapshot"], 0o600)
    return paths


def read_prelaunch(
    output_dir: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    destination = Path(output_dir)
    return (
        _read_json(destination / "r2_contract.json", label="R2 contract"),
        _read_json(destination / "authorization.json", label="R2 authorization"),
        _read_json(destination / "r2_splits.json", label="R2 split manifest"),
    )


def _matrix(loader: replay._FeatureLoader, term_index: int) -> np.ndarray:
    try:
        matrix = np.asarray(loader.matrix(term_index), dtype=np.float64)
    except Exception as exc:
        raise CalibrationEquivalenceR2Error(
            f"cannot load R2 term {term_index}: {_error_text(exc)}"
        ) from exc
    if matrix.ndim != 2 or matrix.shape[0] != len(loader.dataset.subject_ids):
        raise CalibrationEquivalenceR2Error(f"R2 term {term_index} has invalid shape")
    if not np.all(np.isfinite(matrix)):
        raise CalibrationEquivalenceR2Error(f"R2 term {term_index} is non-finite")
    return matrix


def _fit_krr_predict(
    *,
    matrix: np.ndarray,
    y_full: np.ndarray,
    train_indices: np.ndarray,
    prediction_indices: np.ndarray,
    alpha: float,
) -> tuple[np.ndarray, int]:
    train_x, prediction_x, feature_count = liu._fit_preprocessor(
        matrix[train_indices], matrix[prediction_indices]
    )
    estimator = KernelRidge(alpha=float(alpha), kernel="cosine")
    estimator.fit(train_x, y_full[train_indices])
    prediction = np.asarray(estimator.predict(prediction_x), dtype=np.float64).reshape(
        -1
    )
    if prediction.shape != (len(prediction_indices),) or not np.all(
        np.isfinite(prediction)
    ):
        raise CalibrationEquivalenceR2Error("KRR returned invalid predictions")
    return prediction, feature_count


def _fit_affine_calibration(
    *,
    matrix: np.ndarray,
    y_full: np.ndarray,
    outer_train: np.ndarray,
    inner_folds: Sequence[Mapping[str, object]],
    alpha: float,
) -> tuple[float, float, dict[str, object]]:
    """Fit unconstrained OLS only on raw inner-OOF predictions of outer train."""

    inner_oof = np.full(len(y_full), np.nan, dtype=np.float64)
    feature_counts: list[int] = []
    for raw_inner in inner_folds:
        inner = _mapping(raw_inner, label="persisted inner split")
        train = np.asarray(inner["train_indices"], dtype=np.int64)
        validation = np.asarray(inner["validation_indices"], dtype=np.int64)
        prediction, count = _fit_krr_predict(
            matrix=matrix,
            y_full=y_full,
            train_indices=train,
            prediction_indices=validation,
            alpha=alpha,
        )
        inner_oof[validation] = prediction
        feature_counts.append(count)
    if not np.all(np.isfinite(inner_oof[outer_train])):
        raise CalibrationEquivalenceR2Error(
            "calibration inner OOF predictions are incomplete"
        )
    design = np.column_stack(
        [np.ones(len(outer_train), dtype=np.float64), inner_oof[outer_train]]
    )
    coefficients, _, _, _ = np.linalg.lstsq(design, y_full[outer_train], rcond=None)
    intercept, slope = float(coefficients[0]), float(coefficients[1])
    if not math.isfinite(intercept) or not math.isfinite(slope):
        raise CalibrationEquivalenceR2Error(
            "calibration OLS coefficients are non-finite"
        )
    return (
        intercept,
        slope,
        {
            "subject_indices": outer_train.tolist(),
            "y_true": y_full[outer_train].tolist(),
            "raw_y_pred": inner_oof[outer_train].tolist(),
            "feature_counts": feature_counts,
        },
    )


def _extended_metrics(
    y_true: np.ndarray, y_pred: np.ndarray
) -> dict[str, float | None]:
    metrics = dict(replay._metrics(y_true, y_pred))
    slope = metrics.get("calibration_slope")
    if slope is None:
        intercept: float | None = None
    else:
        intercept_value = float(np.mean(y_true) - float(slope) * np.mean(y_pred))
        intercept = intercept_value if math.isfinite(intercept_value) else None
    y_sd = float(np.std(y_true))
    prediction_ratio = float(np.std(y_pred) / y_sd) if y_sd > 0.0 else float("nan")
    metrics["calibration_intercept"] = intercept
    metrics["prediction_sd_ratio"] = (
        prediction_ratio if math.isfinite(prediction_ratio) else None
    )
    return metrics


def _failed_arm(*, arm_id: str, error: str) -> dict[str, object]:
    return {
        "arm_id": arm_id,
        "status": "failed",
        "metrics": None,
        "y_pred": None,
        "error": error,
    }


def _run_krr_pair(
    *,
    raw_arm_id: str,
    calibrated_arm_id: str | None,
    matrix: np.ndarray,
    y_full: np.ndarray,
    outer_train: np.ndarray,
    outer_test: np.ndarray,
    inner_folds: Sequence[Mapping[str, object]],
    alpha: float,
) -> dict[str, dict[str, object]]:
    """Run one raw KRR base once; calibrated output shares that raw test vector."""

    result: dict[str, dict[str, object]] = {}
    try:
        raw_prediction, feature_count = _fit_krr_predict(
            matrix=matrix,
            y_full=y_full,
            train_indices=outer_train,
            prediction_indices=outer_test,
            alpha=alpha,
        )
    except Exception as exc:
        reason = _error_text(exc)
        result[raw_arm_id] = _failed_arm(arm_id=raw_arm_id, error=reason)
        if calibrated_arm_id is not None:
            result[calibrated_arm_id] = _failed_arm(
                arm_id=calibrated_arm_id, error=f"raw base failed: {reason}"
            )
        return result
    result[raw_arm_id] = {
        "arm_id": raw_arm_id,
        "status": "succeeded",
        "metrics": _extended_metrics(y_full[outer_test], raw_prediction),
        "y_pred": raw_prediction.tolist(),
        "selected_feature_count": feature_count,
        "error": None,
    }
    if calibrated_arm_id is None:
        return result
    try:
        intercept, slope, inner_oof = _fit_affine_calibration(
            matrix=matrix,
            y_full=y_full,
            outer_train=outer_train,
            inner_folds=inner_folds,
            alpha=alpha,
        )
        calibrated_prediction = intercept + slope * raw_prediction
        if not np.all(np.isfinite(calibrated_prediction)):
            raise CalibrationEquivalenceR2Error(
                "calibrated KRR predictions are non-finite"
            )
        result[calibrated_arm_id] = {
            "arm_id": calibrated_arm_id,
            "status": "succeeded",
            "metrics": _extended_metrics(y_full[outer_test], calibrated_prediction),
            "y_pred": calibrated_prediction.tolist(),
            "raw_y_pred": raw_prediction.tolist(),
            "selected_feature_count": feature_count,
            "calibration": {
                "intercept_a": intercept,
                "slope_b": slope,
                "inner_oof_raw_predictions": inner_oof,
                "shared_outer_test_raw_prediction_from": raw_arm_id,
            },
            "error": None,
        }
    except Exception as exc:
        result[calibrated_arm_id] = _failed_arm(
            arm_id=calibrated_arm_id, error=_error_text(exc)
        )
    return result


def _run_liu_outer(
    *,
    matrices: Mapping[int, np.ndarray],
    y_full: np.ndarray,
    outer_train: np.ndarray,
    outer_test: np.ndarray,
    inner_folds: Sequence[Mapping[str, object]],
    effective_term_indices: Sequence[int],
) -> dict[str, object]:
    """Re-execute the full nonselectable Liu grid for one outer fold."""

    candidates = liu.frozen_liu_candidates(tuple(effective_term_indices))
    try:
        inner_splits = tuple(
            (
                np.asarray(
                    _mapping(row, label="inner split")["train_indices"], dtype=np.int64
                ),
                np.asarray(
                    _mapping(row, label="inner split")["validation_indices"],
                    dtype=np.int64,
                ),
            )
            for row in inner_folds
        )
        candidates_by_term = {
            term_index: tuple(
                candidate
                for candidate in candidates
                if candidate["term_index"] == term_index
            )
            for term_index in effective_term_indices
        }
        inner_rows = [
            row
            for term_index in effective_term_indices
            for row in liu._score_term_candidates_on_inner(
                candidates=candidates_by_term[term_index],
                X=matrices[term_index],
                y=y_full,
                inner_splits=inner_splits,
            )
        ]
        winner = liu._select_inner_candidate(
            candidate_rows=inner_rows,
            expected_count=LIU_CANDIDATE_COUNT,
            stage="R2 Liu outer selection",
        )
        term_index = int(winner["term_index"])
        prediction, feature_count = liu._predict_with_candidate(
            candidate=winner,
            X=matrices[term_index],
            y=y_full,
            train_indices=outer_train,
            prediction_indices=outer_test,
        )
        return {
            "status": "succeeded",
            "metrics": _extended_metrics(y_full[outer_test], prediction),
            "y_pred": prediction.tolist(),
            "selected_candidate_id": winner["candidate_id"],
            "selected_term_index": term_index,
            "selected_model_family": winner["model_family"],
            "selected_alpha": winner["alpha"],
            "selected_feature_count": feature_count,
            "inner_candidate_count": len(inner_rows),
            "inner_candidate_success_count": sum(
                1 for row in inner_rows if row.get("status") == "selected"
            ),
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "metrics": None,
            "y_pred": None,
            "inner_candidate_count": LIU_CANDIDATE_COUNT,
            "inner_candidate_success_count": None,
            "error": _error_text(exc),
        }


def _repeat_payload(
    *,
    dataset: replay.HCPDataset,
    y_full: np.ndarray,
    repeat: Mapping[str, object],
    effective_term_indices: Sequence[int],
) -> dict[str, object]:
    loader = replay._FeatureLoader(dataset)
    fixed_terms = {int(spec["term_index"]) for spec in ARM_SPECS}
    required_terms = tuple(sorted(fixed_terms | set(effective_term_indices)))
    matrices = {
        term_index: _matrix(loader, term_index) for term_index in required_terms
    }
    fold_rows: list[dict[str, object]] = []
    for raw_outer in _mapping(repeat, label="repeat").get("outer_folds", []):
        outer = _mapping(raw_outer, label="outer fold")
        outer_train = np.asarray(outer["train_indices"], dtype=np.int64)
        outer_test = np.asarray(outer["test_indices"], dtype=np.int64)
        inner_folds = [
            _mapping(row, label="inner fold") for row in outer.get("inner_folds", [])
        ]
        arm_rows: dict[str, dict[str, object]] = {}
        arm_rows.update(
            _run_krr_pair(
                raw_arm_id="A2_raw",
                calibrated_arm_id=None,
                matrix=matrices[17],
                y_full=y_full,
                outer_train=outer_train,
                outer_test=outer_test,
                inner_folds=inner_folds,
                alpha=0.1,
            )
        )
        arm_rows.update(
            _run_krr_pair(
                raw_arm_id="A4_raw",
                calibrated_arm_id=None,
                matrix=matrices[19],
                y_full=y_full,
                outer_train=outer_train,
                outer_test=outer_test,
                inner_folds=inner_folds,
                alpha=0.1,
            )
        )
        arm_rows.update(
            _run_krr_pair(
                raw_arm_id="A3a_raw",
                calibrated_arm_id="A3a_cal",
                matrix=matrices[18],
                y_full=y_full,
                outer_train=outer_train,
                outer_test=outer_test,
                inner_folds=inner_folds,
                alpha=0.1,
            )
        )
        arm_rows.update(
            _run_krr_pair(
                raw_arm_id="A3b_raw",
                calibrated_arm_id="A3b_cal",
                matrix=matrices[18],
                y_full=y_full,
                outer_train=outer_train,
                outer_test=outer_test,
                inner_folds=inner_folds,
                alpha=1.0,
            )
        )
        arm_rows.update(
            _run_krr_pair(
                raw_arm_id="C1_raw",
                calibrated_arm_id=None,
                matrix=matrices[116],
                y_full=y_full,
                outer_train=outer_train,
                outer_test=outer_test,
                inner_folds=inner_folds,
                alpha=1.0,
            )
        )
        missing = set(ARM_IDS) - set(arm_rows)
        if missing:
            for arm_id in missing:
                arm_rows[arm_id] = _failed_arm(
                    arm_id=arm_id, error="fixed arm was not evaluated"
                )
        fold_rows.append(
            {
                "outer_fold": outer.get("outer_fold"),
                "outer_train_indices": outer_train.tolist(),
                "outer_test_indices": outer_test.tolist(),
                "arms": {arm_id: arm_rows[arm_id] for arm_id in ARM_IDS},
                "liu_benchmark": _run_liu_outer(
                    matrices=matrices,
                    y_full=y_full,
                    outer_train=outer_train,
                    outer_test=outer_test,
                    inner_folds=inner_folds,
                    effective_term_indices=effective_term_indices,
                ),
            }
        )
    result = {
        "repeat_index": repeat.get("repeat_index"),
        "seed": repeat.get("seed"),
        "outer_folds": fold_rows,
    }
    return _finalize_repeat(result=result, y_full=y_full)


def _pooled_from_folds(
    *,
    fold_rows: Sequence[Mapping[str, object]],
    y_full: np.ndarray,
    key: str,
) -> tuple[dict[str, float | None] | None, np.ndarray | None]:
    prediction = np.full(len(y_full), np.nan, dtype=np.float64)
    for fold in fold_rows:
        test = np.asarray(fold["outer_test_indices"], dtype=np.int64)
        record = _mapping(fold.get(key), label=f"{key} fold record")
        if record.get("status") != "succeeded" or record.get("y_pred") is None:
            return None, None
        values = np.asarray(record["y_pred"], dtype=np.float64)
        if values.shape != (len(test),) or not np.all(np.isfinite(values)):
            return None, None
        prediction[test] = values
    observed = np.flatnonzero(np.isfinite(prediction))
    if len(observed) != DEVELOPMENT_SUBJECT_COUNT:
        return None, None
    return _extended_metrics(y_full[observed], prediction[observed]), prediction


def _add_repeat_pooled_metrics(
    *, result: Mapping[str, object], y_full: np.ndarray
) -> dict[str, object]:
    completed = dict(result)
    fold_rows = [
        _mapping(row, label="repeat outer fold")
        for row in result.get("outer_folds", [])
    ]
    pooled_arms: dict[str, dict[str, float | None] | None] = {}
    predictions: dict[str, np.ndarray | None] = {}
    for arm_id in ARM_IDS:
        adjusted_folds = []
        for fold in fold_rows:
            adjusted = dict(fold)
            adjusted[arm_id] = _mapping(
                _mapping(fold.get("arms"), label="fold arms").get(arm_id),
                label=f"{arm_id} fold result",
            )
            adjusted_folds.append(adjusted)
        pooled_arms[arm_id], predictions[arm_id] = _pooled_from_folds(
            fold_rows=adjusted_folds, y_full=y_full, key=arm_id
        )
    liu_folds = []
    for fold in fold_rows:
        adjusted = dict(fold)
        adjusted["liu"] = _mapping(fold.get("liu_benchmark"), label="Liu fold result")
        liu_folds.append(adjusted)
    pooled_liu, liu_prediction = _pooled_from_folds(
        fold_rows=liu_folds, y_full=y_full, key="liu"
    )
    comparisons: dict[str, dict[str, float | None]] = {}
    a2 = predictions["A2_raw"]
    a4 = predictions["A4_raw"]
    c1 = predictions["C1_raw"]
    if a2 is not None and a4 is not None:
        observed = np.isfinite(a2) & np.isfinite(a4)
        comparisons["A2_A4"] = {
            "prediction_correlation": replay._pearson(a2[observed], a4[observed]),
            "prediction_MAD": float(np.mean(np.abs(a2[observed] - a4[observed]))),
        }
    else:
        comparisons["A2_A4"] = {"prediction_correlation": None, "prediction_MAD": None}
    if a2 is not None and c1 is not None:
        observed = np.isfinite(a2) & np.isfinite(c1)
        comparisons["A2_C1"] = {
            "prediction_correlation": replay._pearson(a2[observed], c1[observed])
        }
    else:
        comparisons["A2_C1"] = {"prediction_correlation": None}
    completed["pooled_metrics"] = {"arms": pooled_arms, "liu_benchmark": pooled_liu}
    completed["pooled_prediction_comparisons"] = comparisons
    completed["liu_pooled_prediction_available"] = liu_prediction is not None
    return completed


def _required_failure_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    """List every one of the eight frozen evaluations that did not succeed."""

    failures: list[dict[str, object]] = []
    for raw_fold in result.get("outer_folds", []):
        fold = _mapping(raw_fold, label="repeat outer fold")
        arms = _mapping(fold.get("arms"), label="repeat fold arms")
        for evaluation_id in REQUIRED_EVALUATION_IDS:
            record = (
                fold.get("liu_benchmark")
                if evaluation_id == "liu_benchmark"
                else arms.get(evaluation_id)
            )
            row = (
                record
                if isinstance(record, Mapping)
                else {
                    "status": "missing",
                    "error": "required evaluation record is missing",
                }
            )
            if row.get("status") != "succeeded":
                failures.append(
                    {
                        "repeat_index": result.get("repeat_index"),
                        "seed": result.get("seed"),
                        "outer_fold": fold.get("outer_fold"),
                        "required_evaluation": evaluation_id,
                        "status": row.get("status"),
                        "error": row.get("error"),
                    }
                )
    return failures


def _finalize_repeat(
    *, result: Mapping[str, object], y_full: np.ndarray
) -> dict[str, object]:
    completed = _add_repeat_pooled_metrics(result=result, y_full=y_full)
    failures = _required_failure_rows(completed)
    completed["required_evaluation_count"] = OUTER_FOLDS * len(REQUIRED_EVALUATION_IDS)
    completed["required_failure_rows"] = failures
    completed["status"] = "completed_with_failures" if failures else "completed"
    return completed


def _repeat_worker(payload: Mapping[str, object]) -> dict[str, object]:
    """A process-local source load gives each repeat independent feature caches."""

    source_bundle = Path(
        _required_text(payload.get("source_bundle"), label="source bundle")
    )
    dataset = replay.load_hcp_dataset(source_bundle)
    development = np.asarray(payload["development_indices"], dtype=np.int64)
    values = np.asarray(payload["development_target"], dtype=np.float64)
    if values.shape != (len(development),) or not np.all(np.isfinite(values)):
        raise CalibrationEquivalenceR2Error(
            "worker development target values are invalid"
        )
    target = np.full(len(dataset.subject_ids), np.nan, dtype=np.float64)
    target[development] = values
    return _repeat_payload(
        dataset=dataset,
        y_full=target,
        repeat=_mapping(payload.get("repeat"), label="worker repeat"),
        effective_term_indices=tuple(
            int(value) for value in payload["effective_term_indices"]
        ),
    )


def _checkpoint_path(output_dir: Path, repeat_index: int) -> Path:
    return output_dir / "repeat_results" / f"repeat_{repeat_index:02d}.json"


def _same_checkpoint_value(left: object, right: object) -> bool:
    """Compare JSON checkpoint values while tolerating numeric recomputation noise."""

    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return bool(
            math.isfinite(float(left))
            and math.isfinite(float(right))
            and np.isclose(float(left), float(right), rtol=1e-10, atol=1e-12)
        )
    if left is None or right is None:
        return left is right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _same_checkpoint_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_checkpoint_value(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _valid_required_record(*, record: object, y_true: np.ndarray) -> bool:
    if not isinstance(record, Mapping):
        return False
    status = record.get("status")
    if status == "failed":
        return record.get("metrics") is None and record.get("y_pred") is None
    if status != "succeeded":
        return False
    prediction = np.asarray(record.get("y_pred"), dtype=np.float64)
    if prediction.shape != y_true.shape or not np.all(np.isfinite(prediction)):
        return False
    metrics = record.get("metrics")
    if not isinstance(metrics, Mapping):
        return False
    if not _same_checkpoint_value(metrics, _extended_metrics(y_true, prediction)):
        return False
    raw_prediction = record.get("raw_y_pred")
    if raw_prediction is not None:
        raw_values = np.asarray(raw_prediction, dtype=np.float64)
        if raw_values.shape != y_true.shape or not np.all(np.isfinite(raw_values)):
            return False
    return True


def _successful_required_evaluation_count(result: Mapping[str, object]) -> int:
    folds = result.get("outer_folds")
    if not isinstance(folds, list) or len(folds) != OUTER_FOLDS:
        return 0
    successful = 0
    for raw_fold in folds:
        if not isinstance(raw_fold, Mapping):
            continue
        arms = raw_fold.get("arms")
        if not isinstance(arms, Mapping):
            continue
        for evaluation_id in REQUIRED_EVALUATION_IDS:
            record = (
                raw_fold.get("liu_benchmark")
                if evaluation_id == "liu_benchmark"
                else arms.get(evaluation_id)
            )
            if (
                isinstance(record, Mapping)
                and record.get("status") == "succeeded"
                and isinstance(record.get("metrics"), Mapping)
                and isinstance(record.get("y_pred"), list)
            ):
                successful += 1
    return successful


def _all_required_evaluations_succeeded(
    repeat_results: Sequence[Mapping[str, object]],
) -> bool:
    expected_per_repeat = OUTER_FOLDS * len(REQUIRED_EVALUATION_IDS)
    expected_total = len(REPEAT_SEEDS) * expected_per_repeat
    return bool(
        len(repeat_results) == len(REPEAT_SEEDS)
        and all(
            row.get("status") == "completed"
            and row.get("required_evaluation_count") == expected_per_repeat
            and row.get("required_failure_rows") == []
            and _successful_required_evaluation_count(row) == expected_per_repeat
            for row in repeat_results
        )
        and sum(_successful_required_evaluation_count(row) for row in repeat_results)
        == expected_total
    )


def _checkpoint_valid(
    *,
    result: Mapping[str, object],
    repeat: Mapping[str, object],
    contract: Mapping[str, object],
    frozen_y_full: np.ndarray,
    development_target_binding: Mapping[str, object],
) -> bool:
    """Accept only a checkpoint bound to this exact contract and target snapshot."""

    try:
        if (
            result.get("repeat_index") != repeat.get("repeat_index")
            or result.get("seed") != repeat.get("seed")
            or result.get("status") not in {"completed", "completed_with_failures"}
            or result.get("contract_binding") != dict(contract)
            or result.get("development_target_binding")
            != dict(development_target_binding)
            or not isinstance(result.get("outer_folds"), list)
            or len(result["outer_folds"]) != OUTER_FOLDS
        ):
            return False
        y_full = np.asarray(frozen_y_full, dtype=np.float64)
        if y_full.ndim != 1:
            return False
        expected_folds = repeat.get("outer_folds")
        if not isinstance(expected_folds, list):
            return False
        for stored, expected in zip(result["outer_folds"], expected_folds, strict=True):
            if not isinstance(stored, Mapping) or not isinstance(expected, Mapping):
                return False
            if (
                stored.get("outer_fold") != expected.get("outer_fold")
                or stored.get("outer_train_indices") != expected.get("train_indices")
                or stored.get("outer_test_indices") != expected.get("test_indices")
            ):
                return False
            test = np.asarray(stored["outer_test_indices"], dtype=np.int64)
            if (
                test.ndim != 1
                or len(test) == 0
                or np.any(test < 0)
                or np.any(test >= len(y_full))
                or not np.all(np.isfinite(y_full[test]))
            ):
                return False
            arms = stored.get("arms")
            if not isinstance(arms, Mapping) or set(arms) != set(ARM_IDS):
                return False
            for arm_id in ARM_IDS:
                if not _valid_required_record(
                    record=arms.get(arm_id), y_true=y_full[test]
                ):
                    return False
            if not _valid_required_record(
                record=stored.get("liu_benchmark"), y_true=y_full[test]
            ):
                return False
        expected_failures = _required_failure_rows(result)
        expected_status = (
            "completed_with_failures" if expected_failures else "completed"
        )
        expected_count = OUTER_FOLDS * len(REQUIRED_EVALUATION_IDS)
        if (
            result.get("required_evaluation_count") != expected_count
            or result.get("required_failure_rows") != expected_failures
            or result.get("status") != expected_status
        ):
            return False
        recomputed = _add_repeat_pooled_metrics(result=result, y_full=y_full)
        for key in (
            "pooled_metrics",
            "pooled_prediction_comparisons",
            "liu_pooled_prediction_available",
        ):
            if not _same_checkpoint_value(result.get(key), recomputed.get(key)):
                return False
    except Exception:
        return False
    return True


def _failure_repeat(*, repeat: Mapping[str, object], error: str) -> dict[str, object]:
    outer_rows = _mapping(repeat, label="failed repeat").get("outer_folds")
    if not isinstance(outer_rows, list) or len(outer_rows) != OUTER_FOLDS:
        raise CalibrationEquivalenceR2Error(
            "failed repeat lacks the frozen outer folds"
        )
    failure_folds: list[dict[str, object]] = []
    for raw_outer in outer_rows:
        outer = _mapping(raw_outer, label="failed outer fold")
        failure_folds.append(
            {
                "outer_fold": outer.get("outer_fold"),
                "outer_train_indices": outer.get("train_indices"),
                "outer_test_indices": outer.get("test_indices"),
                "arms": {
                    arm_id: _failed_arm(arm_id=arm_id, error=error)
                    for arm_id in ARM_IDS
                },
                "liu_benchmark": {
                    "status": "failed",
                    "metrics": None,
                    "y_pred": None,
                    "error": error,
                },
            }
        )
    failed = {
        "repeat_index": repeat.get("repeat_index"),
        "seed": repeat.get("seed"),
        "outer_folds": failure_folds,
        "failure": error,
        "pooled_metrics": {
            "arms": dict.fromkeys(ARM_IDS),
            "liu_benchmark": None,
        },
        "pooled_prediction_comparisons": {
            "A2_A4": {"prediction_correlation": None, "prediction_MAD": None},
            "A2_C1": {"prediction_correlation": None},
        },
        "liu_pooled_prediction_available": False,
    }
    failed["required_evaluation_count"] = OUTER_FOLDS * len(REQUIRED_EVALUATION_IDS)
    failed["required_failure_rows"] = _required_failure_rows(failed)
    failed["status"] = "completed_with_failures"
    return failed


def _median_iqr(values: Sequence[object]) -> dict[str, float | int | None]:
    finite = [
        float(value)
        for value in values
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]
    if not finite:
        return {"n": 0, "median": None, "iqr": None}
    q1, median, q3 = np.percentile(np.asarray(finite, dtype=np.float64), [25, 50, 75])
    return {
        "n": len(finite),
        "median": float(median),
        "iqr": float(q3 - q1),
        "q1": float(q1),
        "q3": float(q3),
    }


def _primary_gate(repeat_results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    required_evaluations_succeeded = _all_required_evaluations_succeeded(repeat_results)
    deltas_r2: list[float | None] = []
    deltas_mae: list[float | None] = []
    calibrated_slopes: list[float | None] = []
    rows: list[dict[str, object]] = []
    for repeat in repeat_results:
        pooled = _mapping(repeat.get("pooled_metrics"), label="repeat pooled metrics")
        arms = _mapping(pooled.get("arms"), label="repeat arm metrics")
        raw = arms.get("A3b_raw")
        calibrated = arms.get("A3b_cal")
        raw_metrics = raw if isinstance(raw, Mapping) else {}
        calibrated_metrics = calibrated if isinstance(calibrated, Mapping) else {}
        raw_r2 = raw_metrics.get("r2")
        cal_r2 = calibrated_metrics.get("r2")
        raw_mae = raw_metrics.get("mae")
        cal_mae = calibrated_metrics.get("mae")
        delta_r2 = (
            float(cal_r2) - float(raw_r2)
            if isinstance(cal_r2, int | float) and isinstance(raw_r2, int | float)
            else None
        )
        delta_mae = (
            float(cal_mae) - float(raw_mae)
            if isinstance(cal_mae, int | float) and isinstance(raw_mae, int | float)
            else None
        )
        slope = calibrated_metrics.get("calibration_slope")
        slope_value = float(slope) if isinstance(slope, int | float) else None
        deltas_r2.append(delta_r2)
        deltas_mae.append(delta_mae)
        calibrated_slopes.append(slope_value)
        rows.append(
            {
                "repeat_index": repeat.get("repeat_index"),
                "seed": repeat.get("seed"),
                "delta_r2_A3b_cal_minus_raw": delta_r2,
                "delta_mae_A3b_cal_minus_raw": delta_mae,
                "A3b_calibration_slope": slope_value,
            }
        )
    r2_summary = _median_iqr(deltas_r2)
    mae_summary = _median_iqr(deltas_mae)
    slope_summary = _median_iqr(calibrated_slopes)
    positive_count = sum(value is not None and value > 0.0 for value in deltas_r2)
    passed = bool(
        required_evaluations_succeeded
        and r2_summary.get("n") == len(REPEAT_SEEDS)
        and mae_summary.get("n") == len(REPEAT_SEEDS)
        and slope_summary.get("n") == len(REPEAT_SEEDS)
        and r2_summary.get("median") is not None
        and float(r2_summary["median"])
        >= float(REPAIR_GATE["median_delta_r2_at_least"])
        and positive_count >= int(REPAIR_GATE["positive_delta_r2_repeats_at_least"])
        and mae_summary.get("median") is not None
        and float(mae_summary["median"])
        <= float(REPAIR_GATE["median_delta_mae_at_most"])
        and slope_summary.get("median") is not None
        and float(REPAIR_GATE["median_heldout_calibration_slope_range"][0])
        <= float(slope_summary["median"])
        <= float(REPAIR_GATE["median_heldout_calibration_slope_range"][1])
    )
    return {
        "primary_pair": REPAIR_GATE["primary_pair"],
        "required_evaluations_succeeded": required_evaluations_succeeded,
        "repeat_level_deltas": rows,
        "median_delta_r2": r2_summary,
        "positive_delta_r2_repeat_count": positive_count,
        "median_delta_mae": mae_summary,
        "median_heldout_calibration_slope": slope_summary,
        "thresholds": dict(REPAIR_GATE),
        "passed": passed,
        "p_values": REPAIR_GATE["p_values"],
    }


def _result_summaries(
    repeat_results: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    metric_keys = (
        "signed_pearson_r",
        "r2",
        "mae",
        "calibration_intercept",
        "calibration_slope",
        "prediction_sd_ratio",
    )
    summaries: dict[str, object] = {}
    all_fold_metrics: dict[str, list[dict[str, object]]] = {
        arm_id: [] for arm_id in (*ARM_IDS, "liu_benchmark")
    }
    for arm_id in (*ARM_IDS, "liu_benchmark"):
        pooled_rows: list[Mapping[str, object]] = []
        for repeat in repeat_results:
            pooled = _mapping(
                repeat.get("pooled_metrics"), label="repeat pooled metrics"
            )
            if arm_id == "liu_benchmark":
                candidate = pooled.get("liu_benchmark")
            else:
                candidate = _mapping(pooled.get("arms"), label="pooled arms").get(
                    arm_id
                )
            if isinstance(candidate, Mapping):
                pooled_rows.append(candidate)
            for raw_fold in repeat.get("outer_folds", []):
                fold = _mapping(raw_fold, label="result outer fold")
                record = (
                    fold.get("liu_benchmark")
                    if arm_id == "liu_benchmark"
                    else _mapping(fold.get("arms"), label="fold arms").get(arm_id)
                )
                record_mapping = record if isinstance(record, Mapping) else {}
                all_fold_metrics[arm_id].append(
                    {
                        "repeat_index": repeat.get("repeat_index"),
                        "seed": repeat.get("seed"),
                        "outer_fold": fold.get("outer_fold"),
                        "status": record_mapping.get("status"),
                        "metrics": record_mapping.get("metrics"),
                        "error": record_mapping.get("error"),
                    }
                )
        summaries[arm_id] = {
            "repeat_pooled_median_iqr": {
                metric: _median_iqr([row.get(metric) for row in pooled_rows])
                for metric in metric_keys
            },
            "repeat_pooled_count": len(pooled_rows),
            "fold_metric_count": len(all_fold_metrics[arm_id]),
        }
    return summaries, all_fold_metrics


def run_calibration_equivalence(
    *,
    output_dir: Path,
    dataset: replay.HCPDataset,
    nested100_result: Mapping[str, object],
    r1_result: Mapping[str, object],
    metric_catalog: Sequence[Mapping[str, object]],
    liu_frozen_contract: Mapping[str, object],
    source_paths: Mapping[str, str],
    source_bundle_path: Path | None = None,
    target_accessor: Callable[
        [replay.HCPDataset, np.ndarray], np.ndarray
    ] = replay._targets_for_indices,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Launch a prepared R2 contract, while preserving the target boundary."""

    destination = Path(output_dir)
    result_path = destination / "r2_result.json"
    if result_path.exists():
        raise CalibrationEquivalenceR2Error(
            "R2 result already exists; launch is refused"
        )
    contract, authorization, persisted_splits = read_prelaunch(destination)
    workers = _validate_repeat_workers(
        _mapping(contract.get("execution"), label="contract execution").get(
            "repeat_workers"
        )
    )
    expected = prepare_calibration_equivalence_contract(
        dataset=dataset,
        nested100_result=nested100_result,
        r1_result=r1_result,
        metric_catalog=metric_catalog,
        liu_frozen_contract=liu_frozen_contract,
        source_paths=source_paths,
        repeat_workers=workers,
    )
    if contract != expected:
        raise CalibrationEquivalenceR2Error(
            "prepared R2 contract differs from exact current sources"
        )
    if persisted_splits != contract.get("splits"):
        raise CalibrationEquivalenceR2Error(
            "persisted R2 split arrays differ from contract"
        )
    _validate_split_arrays(
        splits=persisted_splits, family_ids=np.asarray(dataset.family_ids, dtype=str)
    )
    verify_authorization(contract=contract, authorization=authorization)
    development_target_snapshot = read_development_target_snapshot(destination)
    y_full = _target_snapshot_y_full(
        dataset=dataset,
        contract=contract,
        snapshot=development_target_snapshot,
    )
    current_target_snapshot = build_development_target_snapshot(
        dataset=dataset,
        contract=contract,
        target_accessor=target_accessor,
    )
    if current_target_snapshot != development_target_snapshot:
        raise CalibrationEquivalenceR2Error(
            "current development target source differs from the prepared snapshot"
        )
    development_target_binding = {
        "subject_indices": development_target_snapshot["subject_indices"],
        "subject_ids": development_target_snapshot["subject_ids"],
    }
    report = progress or (lambda _message: None)
    _write_json(
        destination / "state.json",
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "phase": "R2_RUNNING_DEVELOPMENT_ONLY",
            "completed_repeat_indices": [],
            "development_target_snapshot_written": True,
            "adaptive82_target_accessed": False,
            "R3_authorization": "NOT_GRANTED",
            "confirmation_started": False,
            "scientific_acceptance": False,
        },
    )
    report("R2 development-only execution started")

    development = np.asarray(
        development_target_snapshot["subject_indices"], dtype=np.int64
    )
    liu_terms = tuple(
        int(row["term_index"])
        for row in _mapping(contract.get("liu_benchmark"), label="Liu benchmark").get(
            "effective_terms", []
        )
    )
    repeat_rows = _mapping(contract.get("splits"), label="contract splits").get(
        "repeats"
    )
    if not isinstance(repeat_rows, list):
        raise CalibrationEquivalenceR2Error("contract repeats must be a list")
    completed: dict[int, dict[str, object]] = {}
    outstanding: list[Mapping[str, object]] = []
    for raw_repeat in repeat_rows:
        repeat = _mapping(raw_repeat, label="contract repeat")
        index = int(repeat["repeat_index"])
        checkpoint = _checkpoint_path(destination, index)
        if checkpoint.is_file():
            prior = _read_json(checkpoint, label=f"R2 repeat checkpoint {index}")
            if not _checkpoint_valid(
                result=prior,
                repeat=repeat,
                contract=contract,
                frozen_y_full=y_full,
                development_target_binding=development_target_binding,
            ):
                raise CalibrationEquivalenceR2Error(
                    f"R2 repeat checkpoint {index} does not match the frozen contract or target"
                )
            completed[index] = prior
        else:
            outstanding.append(repeat)

    def persist(repeat: Mapping[str, object], payload: Mapping[str, object]) -> None:
        index = int(repeat["repeat_index"])
        checkpoint_payload = {
            **payload,
            "contract_binding": dict(contract),
            "development_target_binding": dict(development_target_binding),
        }
        _write_json(_checkpoint_path(destination, index), checkpoint_payload)
        completed[index] = checkpoint_payload
        _write_json(
            destination / "state.json",
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "phase": "R2_RUNNING_DEVELOPMENT_ONLY",
                "completed_repeat_indices": sorted(completed),
                "development_target_snapshot_written": True,
                "adaptive82_target_accessed": False,
                "R3_authorization": "NOT_GRANTED",
                "confirmation_started": False,
                "scientific_acceptance": False,
            },
        )
        report(
            f"R2 repeat {index}/{len(REPEAT_SEEDS)} terminal "
            f"status={checkpoint_payload.get('status')}"
        )

    if workers > 1 and outstanding:
        if source_bundle_path is None:
            raise CalibrationEquivalenceR2Error(
                "parallel R2 launch requires source_bundle_path for isolated workers"
            )
        payloads = {
            int(repeat["repeat_index"]): {
                "source_bundle": str(source_bundle_path),
                "development_indices": development.tolist(),
                "development_target": y_full[development].tolist(),
                "repeat": dict(repeat),
                "effective_term_indices": list(liu_terms),
            }
            for repeat in outstanding
        }
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_repeat_worker, payload): index
                for index, payload in payloads.items()
            }
            repeat_lookup = {int(row["repeat_index"]): row for row in outstanding}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    repeat_result = future.result()
                except Exception as exc:
                    repeat_result = _failure_repeat(
                        repeat=repeat_lookup[index], error=_error_text(exc)
                    )
                persist(repeat_lookup[index], repeat_result)
    else:
        for repeat in outstanding:
            try:
                repeat_result = _repeat_payload(
                    dataset=dataset,
                    y_full=y_full,
                    repeat=repeat,
                    effective_term_indices=liu_terms,
                )
            except Exception as exc:
                repeat_result = _failure_repeat(repeat=repeat, error=_error_text(exc))
            persist(repeat, repeat_result)

    ordered_repeats = [completed[index] for index in range(1, len(REPEAT_SEEDS) + 1)]
    summaries, all_fold_metrics = _result_summaries(ordered_repeats)
    primary_gate = _primary_gate(ordered_repeats)
    required_evaluations_succeeded = _all_required_evaluations_succeeded(
        ordered_repeats
    )
    phase = (
        "AWAITING_HUMAN_REVIEW"
        if required_evaluations_succeeded
        else "R2_FAILED_DEVELOPMENT_ONLY"
    )
    required_failure_rows = [
        failure
        for row in ordered_repeats
        for failure in row.get("required_failure_rows", [])
        if isinstance(failure, Mapping)
    ]
    failures = [
        {
            "repeat_index": row.get("repeat_index"),
            "seed": row.get("seed"),
            "failure": row.get("failure"),
        }
        for row in ordered_repeats
        if row.get("status") != "completed"
    ]
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "analysis_label": "development_only_R2_calibration_equivalence_v1",
        "phase": phase,
        "frozen_contract": contract,
        "repeat_results": ordered_repeats,
        "all_fold_metrics": all_fold_metrics,
        "repeat_pooled_summaries": summaries,
        "primary_gate": primary_gate,
        "repeat_failures": failures,
        "required_failure_rows": required_failure_rows,
        "execution": {
            "all_fixed_repeats_terminal": len(ordered_repeats) == len(REPEAT_SEEDS),
            "failure_policy": "recorded_without_replacement",
            "parallel_result_order": "repeat_index_ascending",
            "required_evaluation_expected_count": len(REPEAT_SEEDS)
            * OUTER_FOLDS
            * len(REQUIRED_EVALUATION_IDS),
            "required_evaluation_success_count": sum(
                _successful_required_evaluation_count(row) for row in ordered_repeats
            ),
            "required_evaluations_succeeded": required_evaluations_succeeded,
            "adaptive82_target_accessed": False,
        },
        "final_development_selection": "NOT_PERFORMED",
        "automatic_champion_selected": False,
        "R3_authorization": "NOT_GRANTED",
        "confirmation_started": False,
        "scientific_acceptance": False,
        "p_values": "not_computed",
    }
    _write_json(result_path, result)
    _write_json(
        destination / "state.json",
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "phase": phase,
            "development_target_snapshot_written": True,
            "adaptive82_target_accessed": False,
            "R3_authorization": "NOT_GRANTED",
            "confirmation_started": False,
            "scientific_acceptance": False,
        },
    )
    report(f"R2 phase: {phase}")
    return result


__all__ = [
    "ARM_IDS",
    "ARM_SPECS",
    "AUTHORIZATION_SCHEMA_VERSION",
    "CONTRACT_SCHEMA_VERSION",
    "CalibrationEquivalenceR2Error",
    "DEFAULT_REPEAT_WORKERS",
    "R2_DESIGN",
    "REPEAT_SEEDS",
    "build_authorization_template",
    "configure_repeat_runtime",
    "prepare_calibration_equivalence_contract",
    "read_prelaunch",
    "run_calibration_equivalence",
    "verify_authorization",
    "write_prelaunch_artifacts",
]
