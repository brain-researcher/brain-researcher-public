"""Frozen development-only cross-component transfer for HCP ICA outcomes.

Five configurations selected on the Cognition development surface are refit,
without endpoint-specific tuning, on four additional reconstructed ICA
components.  Every transferred configuration is compared with a target-specific
fully nested Liu-style common-support procedure on the exact R2 subjects and
splits.

``prepare`` is outcome-blind: it freezes source identities, split arrays, and an
inactive authorization template, but does not parse any of the four outcome
columns.  ``launch`` is separate and requires an exact human authorization.
"""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from brain_researcher.research.predictive import hcp_calibration_equivalence_r2 as r2
from brain_researcher.research.predictive import hcp_liu_matched_comparator as liu
from brain_researcher.research.predictive import hcp_nested100_replay as replay

CONTRACT_SCHEMA_VERSION = "br.hcp_cross_component_transfer_r3_contract.v1"
AUTHORIZATION_SCHEMA_VERSION = "br.hcp_cross_component_transfer_r3_authorization.v1"
STATE_SCHEMA_VERSION = "br.hcp_cross_component_transfer_r3_state.v1"
TARGET_SNAPSHOT_SCHEMA_VERSION = "br.hcp_cross_component_transfer_r3_targets.v1"
CHECKPOINT_SCHEMA_VERSION = "br.hcp_cross_component_transfer_r3_checkpoint.v1"
RESULT_SCHEMA_VERSION = "br.hcp_cross_component_transfer_r3_result.v1"
DESIGN = "five_fixed_configs_x_four_components_v1"

TARGETS = (
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_IllicitDrugUse",
    "ICA_MentalHealth",
)
FIXED_ARMS = (
    {
        "arm_id": "A2_raw",
        "family": "A2",
        "model_family": "kernelridgecosine",
        "kernel": "cosine",
        "term_index": 17,
        "alpha": 0.1,
        "calibration": False,
    },
    {
        "arm_id": "A3a_raw",
        "family": "A3a",
        "model_family": "kernelridgecosine",
        "kernel": "cosine",
        "term_index": 18,
        "alpha": 0.1,
        "calibration": False,
    },
    {
        "arm_id": "A3b_raw",
        "family": "A3b",
        "model_family": "kernelridgecosine",
        "kernel": "cosine",
        "term_index": 18,
        "alpha": 1.0,
        "calibration": False,
    },
    {
        "arm_id": "A4_raw",
        "family": "A4",
        "model_family": "kernelridgecosine",
        "kernel": "cosine",
        "term_index": 19,
        "alpha": 0.1,
        "calibration": False,
    },
    {
        "arm_id": "C1_raw",
        "family": "C1",
        "model_family": "kernelridgecosine",
        "kernel": "cosine",
        "term_index": 116,
        "alpha": 1.0,
        "calibration": False,
    },
)
ARM_IDS = tuple(str(row["arm_id"]) for row in FIXED_ARMS)
DEVELOPMENT_SUBJECT_COUNT = 244
DEVELOPMENT_FAMILY_COUNT = 243
REPEAT_COUNT = 10
OUTER_FOLDS = 5
INNER_FOLDS = 3
LIU_TERM_COUNT = 74
LIU_CANDIDATE_COUNT = 1184
DEFAULT_WORKERS = 4
MAX_WORKERS = 8
IDENTITY_RELATIVE_PATH = "private/development_identity.json"
TARGET_SNAPSHOT_RELATIVE_PATH = "private/development_target_snapshots.json"


class CrossComponentTransferError(ValueError):
    """The frozen transfer contract, authority, or result is invalid."""


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrossComponentTransferError(f"cannot read {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise CrossComponentTransferError(f"{label} must be a JSON object")
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
        raise CrossComponentTransferError(f"{label} must be an object")
    return value


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CrossComponentTransferError(f"{label} must be non-empty text")
    return value


def _validate_workers(workers: int) -> int:
    if isinstance(workers, bool) or not isinstance(workers, int):
        raise CrossComponentTransferError("workers must be an integer")
    if workers < 1 or workers > MAX_WORKERS:
        raise CrossComponentTransferError(
            f"workers must be between 1 and {MAX_WORKERS}"
        )
    return workers


def _same_value(left: object, right: object) -> bool:
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
            _same_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_value(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _validate_target_header(dataset: replay.HCPDataset) -> None:
    if dataset.target_path is None:
        raise CrossComponentTransferError("target table path is required")
    try:
        with dataset.target_path.open("r", encoding="utf-8", newline="") as handle:
            fieldnames = csv.DictReader(handle).fieldnames
    except (OSError, csv.Error) as exc:
        raise CrossComponentTransferError("cannot read target table header") from exc
    required = {"Subject", *TARGETS}
    if fieldnames is None or not required.issubset(fieldnames):
        raise CrossComponentTransferError(
            "target table lacks a frozen component column"
        )
    if len(dataset.subject_ids) != 326 or len(set(dataset.subject_ids)) != 326:
        raise CrossComponentTransferError(
            "source dataset must contain 326 unique subjects"
        )


def _expected_r2_arm_rows(r2_contract: Mapping[str, object]) -> list[dict[str, object]]:
    raw_arms = r2_contract.get("arms")
    if not isinstance(raw_arms, list):
        raise CrossComponentTransferError("R2 contract lacks arms")
    by_id = {
        row.get("arm_id"): row
        for row in raw_arms
        if isinstance(row, Mapping) and isinstance(row.get("arm_id"), str)
    }
    r1 = _mapping(
        _mapping(r2_contract.get("source_reference"), label="R2 source reference").get(
            "r1"
        ),
        label="R2 R1 reference",
    )
    bindings = r1.get("fixed_arm_binding")
    if not isinstance(bindings, list):
        raise CrossComponentTransferError("R2 contract lacks fixed-arm provenance")
    binding_by_family = {
        row.get("template_id"): row for row in bindings if isinstance(row, Mapping)
    }
    rows: list[dict[str, object]] = []
    for expected in FIXED_ARMS:
        source = _mapping(by_id.get(expected["arm_id"]), label="R2 fixed raw arm")
        for key in ("family", "term_index", "alpha"):
            if source.get(key) != expected[key]:
                raise CrossComponentTransferError(
                    f"R2 arm {expected['arm_id']} has {key} drift"
                )
        if source.get("calibration") != "raw":
            raise CrossComponentTransferError(
                f"R2 arm {expected['arm_id']} must be raw"
            )
        provenance_family = (
            "A3" if expected["family"] in {"A3a", "A3b"} else expected["family"]
        )
        binding = _mapping(
            binding_by_family.get(provenance_family),
            label=f"R2 {provenance_family} provenance",
        )
        if (
            binding.get("model_family") != "kernelridgecosine"
            or binding.get("term_index") != expected["term_index"]
        ):
            raise CrossComponentTransferError(
                f"R2 arm {expected['arm_id']} model provenance drift"
            )
        rows.append(dict(expected))
    return rows


def _validate_r2_result(
    *, r2_contract: Mapping[str, object], r2_result: Mapping[str, object]
) -> dict[str, object]:
    if r2_result.get("schema_version") != r2.RESULT_SCHEMA_VERSION:
        raise CrossComponentTransferError("unexpected R2 result schema")
    if r2_result.get("phase") != "AWAITING_HUMAN_REVIEW":
        raise CrossComponentTransferError("R2 source is not reviewable")
    if r2_result.get("frozen_contract") != dict(r2_contract):
        raise CrossComponentTransferError("R2 result is not bound to the R2 contract")
    repeats = r2_result.get("repeat_results")
    if not isinstance(repeats, list) or len(repeats) != REPEAT_COUNT:
        raise CrossComponentTransferError("R2 result must contain ten repeats")
    win_rows: list[dict[str, object]] = []
    for arm_id in ARM_IDS:
        deltas: list[float] = []
        for raw_repeat in repeats:
            repeat = _mapping(raw_repeat, label="R2 repeat")
            pooled = _mapping(repeat.get("pooled_metrics"), label="R2 pooled metrics")
            arms = _mapping(pooled.get("arms"), label="R2 pooled arms")
            arm = _mapping(arms.get(arm_id), label=f"R2 pooled {arm_id}")
            benchmark = _mapping(
                pooled.get("liu_benchmark"), label="R2 pooled Liu benchmark"
            )
            arm_r = arm.get("signed_pearson_r")
            liu_r = benchmark.get("signed_pearson_r")
            if not isinstance(arm_r, int | float) or not isinstance(liu_r, int | float):
                raise CrossComponentTransferError("R2 pooled r is missing")
            delta = float(arm_r) - float(liu_r)
            if not math.isfinite(delta) or delta <= 0.0:
                raise CrossComponentTransferError(
                    f"R2 arm {arm_id} did not beat Liu in all repeats"
                )
            deltas.append(delta)
        win_rows.append(
            {
                "arm_id": arm_id,
                "repeat_wins_over_liu": len(deltas),
                "repeat_denominator": REPEAT_COUNT,
                "minimum_delta_r": min(deltas),
            }
        )
    return {
        "schema_version": r2_result.get("schema_version"),
        "phase": r2_result.get("phase"),
        "selection_history": win_rows,
        "selection_history_is_transfer_evidence": False,
    }


def _validate_liu_contract(
    *, r2_contract: Mapping[str, object], liu_frozen_contract: Mapping[str, object]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    r2_liu = _mapping(r2_contract.get("liu_benchmark"), label="R2 Liu benchmark")
    effective = r2_liu.get("effective_terms")
    excluded = r2_liu.get("excluded_terms")
    if not isinstance(effective, list) or len(effective) != LIU_TERM_COUNT:
        raise CrossComponentTransferError("R2 must freeze 74 effective Liu terms")
    if not isinstance(excluded, list):
        raise CrossComponentTransferError("R2 excluded Liu terms are missing")
    primary = _mapping(
        liu_frozen_contract.get("primary_common_support_procedure"),
        label="Liu frozen procedure",
    )
    if (
        primary.get("term_count") != LIU_TERM_COUNT
        or primary.get("candidate_count") != LIU_CANDIDATE_COUNT
        or primary.get("model_families") != list(liu.MODEL_FAMILIES)
        or primary.get("alpha_grid") != list(liu.ALPHA_GRID)
    ):
        raise CrossComponentTransferError("Liu frozen procedure differs from R2")
    frozen_terms = primary.get("terms")
    if not isinstance(frozen_terms, list):
        raise CrossComponentTransferError("Liu frozen terms are missing")
    expected_indices = [
        int(_mapping(row, label="R2 Liu term")["term_index"]) for row in effective
    ]
    frozen_indices = [
        int(_mapping(row, label="frozen Liu term")["term_index"])
        for row in frozen_terms
    ]
    if frozen_indices != expected_indices:
        raise CrossComponentTransferError("Liu effective term order differs from R2")
    return [dict(row) for row in effective], [dict(row) for row in excluded]


def prepare_cross_component_transfer_contract(
    *,
    dataset: replay.HCPDataset,
    r2_contract: Mapping[str, object],
    r2_result: Mapping[str, object],
    liu_frozen_contract: Mapping[str, object],
    source_paths: Mapping[str, str],
    workers: int = DEFAULT_WORKERS,
) -> dict[str, object]:
    """Freeze the transfer design without parsing any transferred outcome."""

    worker_count = _validate_workers(workers)
    _validate_target_header(dataset)
    if r2_contract.get("schema_version") != r2.CONTRACT_SCHEMA_VERSION:
        raise CrossComponentTransferError("unexpected R2 contract schema")
    split = _mapping(r2_contract.get("split"), label="R2 split")
    if (
        split.get("development_subject_count") != DEVELOPMENT_SUBJECT_COUNT
        or split.get("development_family_count") != DEVELOPMENT_FAMILY_COUNT
        or split.get("adaptive82_target_access") != "forbidden"
    ):
        raise CrossComponentTransferError("R2 development boundary differs")
    splits = _mapping(r2_contract.get("splits"), label="R2 split arrays")
    r2._validate_split_arrays(
        splits=splits, family_ids=np.asarray(dataset.family_ids, dtype=str)
    )
    development = np.asarray(split.get("development_indices"), dtype=np.int64)
    if development.shape != (DEVELOPMENT_SUBJECT_COUNT,):
        raise CrossComponentTransferError("R2 development indices differ")
    split_manifest_development = np.asarray(
        splits.get("development_indices"), dtype=np.int64
    )
    if not np.array_equal(development, split_manifest_development):
        raise CrossComponentTransferError(
            "R2 split and split-manifest development indices differ"
        )
    if (
        len(set(np.asarray(dataset.family_ids, dtype=str)[development]))
        != DEVELOPMENT_FAMILY_COUNT
    ):
        raise CrossComponentTransferError("R2 development family count differs")
    arms = _expected_r2_arm_rows(r2_contract)
    r2_reference = _validate_r2_result(r2_contract=r2_contract, r2_result=r2_result)
    effective_terms, excluded_terms = _validate_liu_contract(
        r2_contract=r2_contract, liu_frozen_contract=liu_frozen_contract
    )
    cells = [
        {"target": target, "arm_id": arm["arm_id"]}
        for target in TARGETS
        for arm in arms
    ]
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "analysis_label": "development_only_cross_component_transfer_r3",
        "design": DESIGN,
        "source_paths": dict(source_paths),
        "source_reference": {
            "selected_on_endpoint": "ICA_Cognition",
            "r2": r2_reference,
            "r2_contract_schema_version": r2_contract.get("schema_version"),
            "liu_contract_schema_version": liu_frozen_contract.get("schema_version"),
            "historical_liu_predictions_read": False,
        },
        "targets": [
            {
                "target": target,
                "sign_policy": "frozen_as_stored_no_posthoc_flip",
                "target_construction": r2.TARGET_CONSTRUCTION,
                "covariate_policy": r2.COVARIATE_POLICY,
            }
            for target in TARGETS
        ],
        "split": {
            "development_indices": development.tolist(),
            "development_subject_count": DEVELOPMENT_SUBJECT_COUNT,
            "development_family_count": DEVELOPMENT_FAMILY_COUNT,
            "family_grouped": True,
            "adaptive82_target_access": "forbidden",
            "sealed_holdout_target_access": "forbidden",
        },
        "splits": dict(splits),
        "development_identity": {
            "relative_path": IDENTITY_RELATIVE_PATH,
            "subject_count": DEVELOPMENT_SUBJECT_COUNT,
            "family_count": DEVELOPMENT_FAMILY_COUNT,
        },
        "target_access": {
            "prepare_numeric_target_values_parsed": False,
            "launch_allowed_indices": development.tolist(),
            "launch_allowed_columns": list(TARGETS),
            "private_snapshot_relative_path": TARGET_SNAPSHOT_RELATIVE_PATH,
            "nondevelopment_numeric_target_values_parsed": False,
        },
        "fixed_arms": arms,
        "transfer_cells": cells,
        "target_specific_tuning": False,
        "calibration": False,
        "preprocessing": {
            "scope": "fold_local_outer_train_and_inner_train_only",
            "steps": ["QCoD_10_90", "StandardScaler"],
            "representation_search": False,
            "PCA_search": False,
            "split_search": False,
        },
        "liu_benchmark": {
            "role": "target_specific_full_nested_matched_common_support",
            "effective_term_count": LIU_TERM_COUNT,
            "model_families": list(liu.MODEL_FAMILIES),
            "alpha_grid": list(liu.ALPHA_GRID),
            "candidate_count_per_outer_fold": LIU_CANDIDATE_COUNT,
            "inner_selection": "3fold_mean_default_R2_then_candidate_id",
            "effective_terms": effective_terms,
            "excluded_terms": excluded_terms,
            "historic_predictions_or_winner_reuse": "forbidden",
        },
        "execution": {
            "workers": worker_count,
            "target_repeat_tasks": len(TARGETS) * REPEAT_COUNT,
            "required_outer_evaluations": len(TARGETS)
            * REPEAT_COUNT
            * OUTER_FOLDS
            * (len(ARM_IDS) + 1),
            "checkpointing": "one_atomic_target_repeat_checkpoint",
            "successful_checkpoint_resume_validation": (
                "full_frozen_target_repeat_recomputation_before_reuse"
            ),
            "failure_policy": "record_without_replacement_and_continue_fixed_work",
        },
        "authority": {
            "authorization_required_before_target_snapshot_or_launch": True,
            "confirmation_authorization": "NOT_GRANTED",
            "scientific_acceptance_authorization": "NOT_GRANTED",
        },
        "claim_boundary": {
            "same_cohort_development_only": True,
            "retrospective": True,
            "cognition_selected_configurations": True,
            "repeat_partitions_are_independent_replications": False,
            "external_validation": False,
            "confirmed_superiority": False,
            "automatic_champion_selection": False,
            "p_values": "not_computed",
            "scientific_acceptance": False,
        },
    }


def build_authorization_template(
    *, contract: Mapping[str, object]
) -> dict[str, object]:
    return {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorization_id": "hcp_cross_component_transfer_r3_20260810_01",
        "authorized": False,
        "authorized_by": None,
        "design": DESIGN,
        "target_columns": list(TARGETS),
        "include_liu_benchmark": True,
        "target_specific_tuning": False,
        "reuse_adaptive82": False,
        "sealed_holdout_target_access": False,
        "same_cohort_retrospective_acknowledged": False,
        "repeated_splits_not_independent_acknowledged": False,
        "launch_after_contract_validation": True,
        "confirmation_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
        "contract_binding": dict(contract),
    }


def verify_authorization(
    *, contract: Mapping[str, object], authorization: Mapping[str, object]
) -> None:
    required = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorized": True,
        "design": DESIGN,
        "target_columns": list(TARGETS),
        "include_liu_benchmark": True,
        "target_specific_tuning": False,
        "reuse_adaptive82": False,
        "sealed_holdout_target_access": False,
        "same_cohort_retrospective_acknowledged": True,
        "repeated_splits_not_independent_acknowledged": True,
        "launch_after_contract_validation": True,
        "confirmation_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
    }
    for key, expected in required.items():
        if authorization.get(key) != expected:
            raise CrossComponentTransferError(f"authorization field {key} is invalid")
    _required_text(authorization.get("authorization_id"), label="authorization_id")
    _required_text(authorization.get("authorized_by"), label="authorized_by")
    if authorization.get("contract_binding") != dict(contract):
        raise CrossComponentTransferError("authorization is not bound to the contract")


def _development_identity(
    *, dataset: replay.HCPDataset, contract: Mapping[str, object]
) -> dict[str, object]:
    development = np.asarray(
        _mapping(contract.get("split"), label="contract split")["development_indices"],
        dtype=np.int64,
    )
    return {
        "subject_indices": development.tolist(),
        "subject_ids": [dataset.subject_ids[index] for index in development],
        "family_ids": [dataset.family_ids[index] for index in development],
    }


def write_prelaunch_artifacts(
    *, output_dir: Path, dataset: replay.HCPDataset, contract: Mapping[str, object]
) -> dict[str, Path]:
    """Materialize an outcome-blind bundle and stop at authorization."""

    destination = Path(output_dir)
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CrossComponentTransferError(
            "prepare requires a new output directory"
        ) from exc
    identity = _development_identity(dataset=dataset, contract=contract)
    paths = {
        "contract": _write_json(
            destination / "cross_component_contract.json", contract
        ),
        "splits": _write_json(
            destination / "cross_component_splits.json",
            _mapping(contract.get("splits"), label="contract splits"),
        ),
        "authorization_template": _write_json(
            destination / "authorization.template.json",
            build_authorization_template(contract=contract),
        ),
        "identity": _write_json(destination / IDENTITY_RELATIVE_PATH, identity),
        "state": _write_json(
            destination / "state.json",
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "phase": "AWAITING_CROSS_COMPONENT_AUTHORIZATION",
                "target_snapshot_written": False,
                "numeric_target_values_parsed": False,
                "adaptive82_target_accessed": False,
                "sealed_holdout_target_accessed": False,
                "confirmation_started": False,
                "scientific_acceptance": False,
            },
        ),
    }
    os.chmod(paths["authorization_template"], 0o600)
    os.chmod(paths["identity"], 0o600)
    return paths


def read_prelaunch(
    output_dir: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    destination = Path(output_dir)
    return (
        _read_json(
            destination / "cross_component_contract.json", label="transfer contract"
        ),
        _read_json(
            destination / "cross_component_splits.json", label="transfer splits"
        ),
        _read_json(destination / IDENTITY_RELATIVE_PATH, label="development identity"),
    )


def _targets_for_columns(
    dataset: replay.HCPDataset,
    indices: np.ndarray,
    target_columns: Sequence[str] = TARGETS,
) -> dict[str, np.ndarray]:
    """Parse only authorized columns for the exact authorized subject rows."""

    normalized = np.asarray(indices, dtype=np.int64)
    if normalized.shape != (DEVELOPMENT_SUBJECT_COUNT,):
        raise CrossComponentTransferError("target access must contain exactly 244 rows")
    if len(set(normalized.tolist())) != len(normalized):
        raise CrossComponentTransferError("target access contains duplicate rows")
    if np.any(normalized < 0) or np.any(normalized >= len(dataset.subject_ids)):
        raise CrossComponentTransferError("target access contains an out-of-range row")
    columns = tuple(target_columns)
    if columns != TARGETS:
        raise CrossComponentTransferError(
            "target access columns differ from the contract"
        )
    if dataset.target_path is None:
        raise CrossComponentTransferError("target table path is required")
    wanted = {dataset.subject_ids[int(index)] for index in normalized}
    values: dict[str, dict[str, float]] = {target: {} for target in TARGETS}
    try:
        with dataset.target_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not {"Subject", *TARGETS}.issubset(
                reader.fieldnames
            ):
                raise CrossComponentTransferError(
                    "target table lacks a frozen component column"
                )
            for row in reader:
                subject = row.get("Subject")
                if subject not in wanted:
                    continue
                for target in TARGETS:
                    value = float(row[target])
                    if not math.isfinite(value) or subject in values[target]:
                        raise CrossComponentTransferError(
                            "authorized target values are invalid"
                        )
                    values[target][subject] = value
    except (OSError, csv.Error, ValueError, KeyError) as exc:
        raise CrossComponentTransferError(
            "cannot read authorized development target values"
        ) from exc
    if any(set(values[target]) != wanted for target in TARGETS):
        raise CrossComponentTransferError(
            "target table lacks an authorized development value"
        )
    return {
        target: np.asarray(
            [values[target][dataset.subject_ids[int(index)]] for index in normalized],
            dtype=np.float64,
        )
        for target in TARGETS
    }


def build_target_snapshot(
    *,
    dataset: replay.HCPDataset,
    contract: Mapping[str, object],
    target_accessor: Callable[
        [replay.HCPDataset, np.ndarray, Sequence[str]], Mapping[str, np.ndarray]
    ] = _targets_for_columns,
) -> dict[str, object]:
    development = np.asarray(
        _mapping(contract.get("split"), label="contract split")["development_indices"],
        dtype=np.int64,
    )
    raw_values = target_accessor(dataset, development, TARGETS)
    targets: dict[str, list[float]] = {}
    for target in TARGETS:
        values = np.asarray(raw_values.get(target), dtype=np.float64)
        if values.shape != (DEVELOPMENT_SUBJECT_COUNT,) or not np.all(
            np.isfinite(values)
        ):
            raise CrossComponentTransferError(
                f"authorized snapshot for {target} is invalid"
            )
        targets[target] = values.tolist()
    return {
        "schema_version": TARGET_SNAPSHOT_SCHEMA_VERSION,
        "subject_indices": development.tolist(),
        "subject_ids": [dataset.subject_ids[index] for index in development],
        "target_columns": list(TARGETS),
        "targets": targets,
    }


def _snapshot_target_vectors(
    *,
    dataset: replay.HCPDataset,
    contract: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> dict[str, np.ndarray]:
    if snapshot.get("schema_version") != TARGET_SNAPSHOT_SCHEMA_VERSION:
        raise CrossComponentTransferError("unexpected target snapshot schema")
    development = np.asarray(
        _mapping(contract.get("split"), label="contract split")["development_indices"],
        dtype=np.int64,
    )
    if snapshot.get("subject_indices") != development.tolist():
        raise CrossComponentTransferError("target snapshot indices differ")
    if snapshot.get("subject_ids") != [
        dataset.subject_ids[index] for index in development
    ]:
        raise CrossComponentTransferError("target snapshot subject IDs differ")
    if snapshot.get("target_columns") != list(TARGETS):
        raise CrossComponentTransferError("target snapshot columns differ")
    raw_targets = _mapping(snapshot.get("targets"), label="snapshot targets")
    vectors: dict[str, np.ndarray] = {}
    for target in TARGETS:
        values = np.asarray(raw_targets.get(target), dtype=np.float64)
        if values.shape != (DEVELOPMENT_SUBJECT_COUNT,) or not np.all(
            np.isfinite(values)
        ):
            raise CrossComponentTransferError(f"snapshot {target} values are invalid")
        full = np.full(len(dataset.subject_ids), np.nan, dtype=np.float64)
        full[development] = values
        vectors[target] = full
    return vectors


def _required_record_valid(
    *, record: object, y_true: np.ndarray, liu_record: bool = False
) -> bool:
    if not isinstance(record, Mapping) or record.get("status") != "succeeded":
        return False
    prediction = np.asarray(record.get("y_pred"), dtype=np.float64)
    if prediction.shape != y_true.shape or not np.all(np.isfinite(prediction)):
        return False
    metrics = record.get("metrics")
    if not isinstance(metrics, Mapping) or not _same_value(
        metrics, r2._extended_metrics(y_true, prediction)
    ):
        return False
    if liu_record and record.get("inner_candidate_count") != LIU_CANDIDATE_COUNT:
        return False
    return True


def _pooled_metrics_from_folds(
    *,
    fold_rows: Sequence[Mapping[str, object]],
    y_full: np.ndarray,
    development: np.ndarray,
) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    pooled: dict[str, object] = {"arms": {}}
    predictions: dict[str, np.ndarray] = {}
    for evaluation_id in (*ARM_IDS, "liu_benchmark"):
        combined = np.full(len(y_full), np.nan, dtype=np.float64)
        for fold in fold_rows:
            test = np.asarray(fold["outer_test_indices"], dtype=np.int64)
            record = (
                _mapping(fold.get("liu_benchmark"), label="fold Liu")
                if evaluation_id == "liu_benchmark"
                else _mapping(
                    _mapping(fold.get("arms"), label="fold arms").get(evaluation_id),
                    label=f"fold {evaluation_id}",
                )
            )
            if record.get("status") != "succeeded":
                raise CrossComponentTransferError(
                    f"required evaluation {evaluation_id} failed"
                )
            prediction = np.asarray(record.get("y_pred"), dtype=np.float64)
            if prediction.shape != (len(test),):
                raise CrossComponentTransferError("fold prediction shape differs")
            combined[test] = prediction
        if not np.all(np.isfinite(combined[development])):
            raise CrossComponentTransferError("pooled OOF prediction is incomplete")
        metrics = r2._extended_metrics(y_full[development], combined[development])
        predictions[evaluation_id] = combined
        if evaluation_id == "liu_benchmark":
            pooled["liu_benchmark"] = metrics
        else:
            _mapping(pooled["arms"], label="pooled arms")[evaluation_id] = metrics
    return pooled, predictions


def _finalize_target_repeat(
    *,
    target: str,
    repeat: Mapping[str, object],
    fold_rows: Sequence[Mapping[str, object]],
    y_full: np.ndarray,
    development: np.ndarray,
) -> dict[str, object]:
    pooled, _ = _pooled_metrics_from_folds(
        fold_rows=fold_rows, y_full=y_full, development=development
    )
    benchmark = _mapping(pooled.get("liu_benchmark"), label="pooled Liu")
    pooled_arms = _mapping(pooled.get("arms"), label="pooled arms")
    deltas: dict[str, dict[str, float | None]] = {}
    for arm_id in ARM_IDS:
        arm = _mapping(pooled_arms.get(arm_id), label=f"pooled {arm_id}")
        row: dict[str, float | None] = {}
        for metric in ("signed_pearson_r", "r2", "mae"):
            left = arm.get(metric)
            right = benchmark.get(metric)
            row[f"delta_{metric}"] = (
                float(left) - float(right)
                if isinstance(left, int | float) and isinstance(right, int | float)
                else None
            )
        deltas[arm_id] = row
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "target": target,
        "repeat_index": repeat.get("repeat_index"),
        "seed": repeat.get("seed"),
        "status": "completed",
        "outer_folds": [dict(row) for row in fold_rows],
        "pooled_metrics": pooled,
        "paired_deltas_vs_liu": deltas,
        "required_evaluation_count": OUTER_FOLDS * (len(ARM_IDS) + 1),
        "required_evaluation_success_count": OUTER_FOLDS * (len(ARM_IDS) + 1),
        "error": None,
    }


def _target_repeat_payload(
    *,
    dataset: replay.HCPDataset,
    target: str,
    y_full: np.ndarray,
    repeat: Mapping[str, object],
    effective_term_indices: Sequence[int],
) -> dict[str, object]:
    loader = replay._FeatureLoader(dataset)
    fixed_terms = {int(row["term_index"]) for row in FIXED_ARMS}
    matrices = {
        term: r2._matrix(loader, term)
        for term in sorted(fixed_terms | set(effective_term_indices))
    }
    fold_rows: list[dict[str, object]] = []
    for raw_outer in repeat.get("outer_folds", []):
        outer = _mapping(raw_outer, label="outer fold")
        train = np.asarray(outer["train_indices"], dtype=np.int64)
        test = np.asarray(outer["test_indices"], dtype=np.int64)
        inner = [
            _mapping(row, label="inner fold") for row in outer.get("inner_folds", [])
        ]
        arms: dict[str, dict[str, object]] = {}
        for spec in FIXED_ARMS:
            arms.update(
                r2._run_krr_pair(
                    raw_arm_id=str(spec["arm_id"]),
                    calibrated_arm_id=None,
                    matrix=matrices[int(spec["term_index"])],
                    y_full=y_full,
                    outer_train=train,
                    outer_test=test,
                    inner_folds=inner,
                    alpha=float(spec["alpha"]),
                )
            )
        fold_rows.append(
            {
                "outer_fold": outer.get("outer_fold"),
                "outer_train_indices": train.tolist(),
                "outer_test_indices": test.tolist(),
                "arms": {arm_id: arms[arm_id] for arm_id in ARM_IDS},
                "liu_benchmark": r2._run_liu_outer(
                    matrices=matrices,
                    y_full=y_full,
                    outer_train=train,
                    outer_test=test,
                    inner_folds=inner,
                    effective_term_indices=effective_term_indices,
                ),
            }
        )
    development = np.asarray(
        sorted(
            index
            for raw_outer in repeat.get("outer_folds", [])
            for index in _mapping(raw_outer, label="outer fold")["test_indices"]
        ),
        dtype=np.int64,
    )
    return _finalize_target_repeat(
        target=target,
        repeat=repeat,
        fold_rows=fold_rows,
        y_full=y_full,
        development=development,
    )


def _failure_checkpoint(
    *, target: str, repeat: Mapping[str, object], error: str
) -> dict[str, object]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "target": target,
        "repeat_index": repeat.get("repeat_index"),
        "seed": repeat.get("seed"),
        "status": "failed",
        "outer_folds": [],
        "pooled_metrics": None,
        "paired_deltas_vs_liu": None,
        "required_evaluation_count": OUTER_FOLDS * (len(ARM_IDS) + 1),
        "required_evaluation_success_count": 0,
        "error": error,
    }


def _checkpoint_valid(
    *,
    checkpoint: Mapping[str, object],
    target: str,
    repeat: Mapping[str, object],
    y_full: np.ndarray,
    development: np.ndarray,
) -> bool:
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("target") != target
        or checkpoint.get("repeat_index") != repeat.get("repeat_index")
        or checkpoint.get("seed") != repeat.get("seed")
    ):
        return False
    if checkpoint.get("status") == "failed":
        return (
            isinstance(checkpoint.get("error"), str)
            and checkpoint.get("outer_folds") == []
            and checkpoint.get("required_evaluation_success_count") == 0
        )
    if checkpoint.get("status") != "completed":
        return False
    fold_rows = checkpoint.get("outer_folds")
    source_folds = repeat.get("outer_folds")
    if not isinstance(fold_rows, list) or not isinstance(source_folds, list):
        return False
    if len(fold_rows) != OUTER_FOLDS or len(source_folds) != OUTER_FOLDS:
        return False
    try:
        for raw_observed, raw_expected in zip(fold_rows, source_folds, strict=True):
            observed = _mapping(raw_observed, label="checkpoint fold")
            expected = _mapping(raw_expected, label="source fold")
            if (
                observed.get("outer_fold") != expected.get("outer_fold")
                or observed.get("outer_train_indices") != expected.get("train_indices")
                or observed.get("outer_test_indices") != expected.get("test_indices")
            ):
                return False
            test = np.asarray(expected["test_indices"], dtype=np.int64)
            arms = _mapping(observed.get("arms"), label="checkpoint arms")
            if set(arms) != set(ARM_IDS):
                return False
            if not all(
                _required_record_valid(record=arms[arm_id], y_true=y_full[test])
                for arm_id in ARM_IDS
            ):
                return False
            if not _required_record_valid(
                record=observed.get("liu_benchmark"),
                y_true=y_full[test],
                liu_record=True,
            ):
                return False
        expected_checkpoint = _finalize_target_repeat(
            target=target,
            repeat=repeat,
            fold_rows=[_mapping(row, label="checkpoint fold") for row in fold_rows],
            y_full=y_full,
            development=development,
        )
    except (CrossComponentTransferError, TypeError, ValueError, KeyError):
        return False
    return _same_value(checkpoint, expected_checkpoint)


def _target_repeat_worker(payload: Mapping[str, object]) -> dict[str, object]:
    source_bundle = Path(
        _required_text(payload.get("source_bundle"), label="worker source bundle")
    )
    dataset = replay.load_hcp_dataset(source_bundle)
    development = np.asarray(payload["development_indices"], dtype=np.int64)
    values = np.asarray(payload["target_values"], dtype=np.float64)
    if values.shape != (DEVELOPMENT_SUBJECT_COUNT,) or not np.all(np.isfinite(values)):
        raise CrossComponentTransferError("worker target values are invalid")
    y_full = np.full(len(dataset.subject_ids), np.nan, dtype=np.float64)
    y_full[development] = values
    return _target_repeat_payload(
        dataset=dataset,
        target=_required_text(payload.get("target"), label="worker target"),
        y_full=y_full,
        repeat=_mapping(payload.get("repeat"), label="worker repeat"),
        effective_term_indices=tuple(
            int(value) for value in payload["effective_term_indices"]
        ),
    )


def _checkpoint_path(output_dir: Path, target: str, repeat_index: int) -> Path:
    return (
        output_dir
        / "target_results"
        / target
        / "repeat_results"
        / f"repeat_{repeat_index:02d}.json"
    )


def _metric_summary(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "median": float(np.median(array)),
        "q25": float(np.quantile(array, 0.25)),
        "q75": float(np.quantile(array, 0.75)),
        "minimum": float(np.min(array)),
        "maximum": float(np.max(array)),
    }


def _target_summary(
    *, target: str, checkpoints: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for arm_id in ARM_IDS:
        arm_metrics: dict[str, list[float]] = {
            "signed_pearson_r": [],
            "r2": [],
            "mae": [],
            "calibration_slope": [],
            "prediction_sd_ratio": [],
        }
        liu_metrics: dict[str, list[float]] = {key: [] for key in arm_metrics}
        deltas: dict[str, list[float]] = {
            "delta_signed_pearson_r": [],
            "delta_r2": [],
            "delta_mae": [],
        }
        for checkpoint in checkpoints:
            pooled = _mapping(checkpoint.get("pooled_metrics"), label="pooled metrics")
            arm = _mapping(
                _mapping(pooled.get("arms"), label="pooled arms").get(arm_id),
                label=f"pooled {arm_id}",
            )
            benchmark = _mapping(
                pooled.get("liu_benchmark"), label="pooled Liu benchmark"
            )
            for metric in arm_metrics:
                if isinstance(arm.get(metric), int | float):
                    arm_metrics[metric].append(float(arm[metric]))
                if isinstance(benchmark.get(metric), int | float):
                    liu_metrics[metric].append(float(benchmark[metric]))
            delta_row = _mapping(
                _mapping(
                    checkpoint.get("paired_deltas_vs_liu"), label="paired deltas"
                ).get(arm_id),
                label=f"paired {arm_id}",
            )
            for metric in deltas:
                if isinstance(delta_row.get(metric), int | float):
                    deltas[metric].append(float(delta_row[metric]))
        delta_r = deltas["delta_signed_pearson_r"]
        rows.append(
            {
                "target": target,
                "arm_id": arm_id,
                "repeat_count": len(checkpoints),
                "arm_metrics": {
                    key: _metric_summary(values)
                    for key, values in arm_metrics.items()
                    if values
                },
                "liu_metrics": {
                    key: _metric_summary(values)
                    for key, values in liu_metrics.items()
                    if values
                },
                "paired_deltas": {
                    key: _metric_summary(values)
                    for key, values in deltas.items()
                    if values
                },
                "directional_repeat_wins_by_r": sum(value > 0.0 for value in delta_r),
                "directional_repeat_denominator": len(delta_r),
                "repeats_are_independent_replications": False,
            }
        )
    return {"target": target, "transfer_rows": rows}


def run_cross_component_transfer(
    *,
    output_dir: Path,
    dataset: replay.HCPDataset,
    r2_contract: Mapping[str, object],
    r2_result: Mapping[str, object],
    liu_frozen_contract: Mapping[str, object],
    source_paths: Mapping[str, str],
    source_bundle_path: Path | None = None,
    target_accessor: Callable[
        [replay.HCPDataset, np.ndarray, Sequence[str]], Mapping[str, np.ndarray]
    ] = _targets_for_columns,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Execute the exactly authorized development-only transfer matrix."""

    destination = Path(output_dir)
    result_path = destination / "cross_component_result.json"
    if result_path.exists():
        raise CrossComponentTransferError("transfer result already exists")
    contract, persisted_splits, persisted_identity = read_prelaunch(destination)
    authorization = _read_json(
        destination / "authorization.json", label="transfer authorization"
    )
    workers = _validate_workers(
        int(_mapping(contract.get("execution"), label="execution")["workers"])
    )
    expected_contract = prepare_cross_component_transfer_contract(
        dataset=dataset,
        r2_contract=r2_contract,
        r2_result=r2_result,
        liu_frozen_contract=liu_frozen_contract,
        source_paths=source_paths,
        workers=workers,
    )
    if contract != expected_contract:
        raise CrossComponentTransferError(
            "prepared contract differs from current sources"
        )
    if persisted_splits != contract.get("splits"):
        raise CrossComponentTransferError("persisted split arrays differ from contract")
    if persisted_identity != _development_identity(dataset=dataset, contract=contract):
        raise CrossComponentTransferError("development identity differs from source")
    verify_authorization(contract=contract, authorization=authorization)
    current_snapshot = build_target_snapshot(
        dataset=dataset, contract=contract, target_accessor=target_accessor
    )
    snapshot_path = destination / TARGET_SNAPSHOT_RELATIVE_PATH
    if snapshot_path.exists():
        snapshot = _read_json(snapshot_path, label="target snapshot")
        if snapshot != current_snapshot:
            raise CrossComponentTransferError(
                "current targets differ from frozen snapshot"
            )
    else:
        snapshot = current_snapshot
        _write_json(snapshot_path, snapshot)
        os.chmod(snapshot_path, 0o600)
    target_vectors = _snapshot_target_vectors(
        dataset=dataset, contract=contract, snapshot=snapshot
    )
    development = np.asarray(
        _mapping(contract.get("split"), label="contract split")["development_indices"],
        dtype=np.int64,
    )
    repeats = _mapping(contract.get("splits"), label="contract splits").get("repeats")
    if not isinstance(repeats, list) or len(repeats) != REPEAT_COUNT:
        raise CrossComponentTransferError("contract repeat arrays differ")
    effective_terms = tuple(
        int(_mapping(row, label="effective Liu term")["term_index"])
        for row in _mapping(
            contract.get("liu_benchmark"), label="contract Liu benchmark"
        )["effective_terms"]
    )
    report = progress or (lambda _message: None)
    _write_json(
        destination / "state.json",
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "phase": "CROSS_COMPONENT_RUNNING_DEVELOPMENT_ONLY",
            "target_snapshot_written": True,
            "numeric_target_values_parsed": True,
            "adaptive82_target_accessed": False,
            "sealed_holdout_target_accessed": False,
            "confirmation_started": False,
            "scientific_acceptance": False,
        },
    )
    report("cross-component development-only execution started")
    completed: dict[tuple[str, int], dict[str, object]] = {}
    prior_successful_checkpoints: dict[tuple[str, int], dict[str, object]] = {}
    outstanding: list[tuple[str, Mapping[str, object]]] = []
    for target in TARGETS:
        for raw_repeat in repeats:
            repeat = _mapping(raw_repeat, label="contract repeat")
            index = int(repeat["repeat_index"])
            checkpoint_path = _checkpoint_path(destination, target, index)
            if checkpoint_path.exists():
                checkpoint = _read_json(
                    checkpoint_path, label=f"{target} repeat {index}"
                )
                if not _checkpoint_valid(
                    checkpoint=checkpoint,
                    target=target,
                    repeat=repeat,
                    y_full=target_vectors[target],
                    development=development,
                ):
                    raise CrossComponentTransferError(
                        f"checkpoint {target} repeat {index} is invalid"
                    )
                if checkpoint.get("status") == "completed":
                    prior_successful_checkpoints[(target, index)] = checkpoint
                    outstanding.append((target, repeat))
                else:
                    completed[(target, index)] = checkpoint
            else:
                outstanding.append((target, repeat))

    def persist(
        target: str, repeat: Mapping[str, object], payload: Mapping[str, object]
    ) -> None:
        index = int(repeat["repeat_index"])
        key = (target, index)
        prior = prior_successful_checkpoints.get(key)
        if prior is not None:
            if not _same_value(prior, payload):
                raise CrossComponentTransferError(
                    f"checkpoint {target} repeat {index} differs from full recomputation"
                )
            completed[key] = prior
            report(
                f"{target} repeat {index}/{REPEAT_COUNT} "
                "status=revalidated_by_full_recomputation"
            )
            return
        _write_json(_checkpoint_path(destination, target, index), payload)
        completed[key] = dict(payload)
        report(f"{target} repeat {index}/{REPEAT_COUNT} status={payload.get('status')}")

    if workers > 1 and outstanding:
        if source_bundle_path is None:
            raise CrossComponentTransferError(
                "parallel launch requires source_bundle_path"
            )
        payloads = {
            (target, int(repeat["repeat_index"])): {
                "source_bundle": str(source_bundle_path),
                "development_indices": development.tolist(),
                "target": target,
                "target_values": target_vectors[target][development].tolist(),
                "repeat": dict(repeat),
                "effective_term_indices": list(effective_terms),
            }
            for target, repeat in outstanding
        }
        lookup = {
            (target, int(repeat["repeat_index"])): (target, repeat)
            for target, repeat in outstanding
        }
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_target_repeat_worker, payload): key
                for key, payload in payloads.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                target, repeat = lookup[key]
                try:
                    payload = future.result()
                except Exception as exc:
                    payload = _failure_checkpoint(
                        target=target,
                        repeat=repeat,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                persist(target, repeat, payload)
    else:
        for target, repeat in outstanding:
            try:
                payload = _target_repeat_payload(
                    dataset=dataset,
                    target=target,
                    y_full=target_vectors[target],
                    repeat=repeat,
                    effective_term_indices=effective_terms,
                )
            except Exception as exc:
                payload = _failure_checkpoint(
                    target=target,
                    repeat=repeat,
                    error=f"{type(exc).__name__}: {exc}",
                )
            persist(target, repeat, payload)

    ordered = {
        target: [completed[(target, index)] for index in range(1, REPEAT_COUNT + 1)]
        for target in TARGETS
    }
    all_succeeded = all(
        row.get("status") == "completed" for rows in ordered.values() for row in rows
    )
    summaries = {
        target: _target_summary(target=target, checkpoints=rows)
        for target, rows in ordered.items()
        if all(row.get("status") == "completed" for row in rows)
    }
    for target, rows in ordered.items():
        _write_json(
            destination / "target_results" / target / "result.json",
            {
                "target": target,
                "repeat_results": rows,
                "summary": summaries.get(target),
            },
        )
    phase = (
        "AWAITING_HUMAN_SCIENTIFIC_REVIEW"
        if all_succeeded
        else "CROSS_COMPONENT_FAILED_DEVELOPMENT_ONLY"
    )
    success_count = sum(
        int(row.get("required_evaluation_success_count", 0))
        for rows in ordered.values()
        for row in rows
    )
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "analysis_label": "development_only_cross_component_transfer_r3",
        "phase": phase,
        "frozen_contract": contract,
        "target_summaries": summaries,
        "transfer_matrix": [
            row for summary in summaries.values() for row in summary["transfer_rows"]
        ],
        "execution": {
            "target_repeat_count": len(TARGETS) * REPEAT_COUNT,
            "all_target_repeats_terminal": len(completed)
            == len(TARGETS) * REPEAT_COUNT,
            "required_evaluation_expected_count": len(TARGETS)
            * REPEAT_COUNT
            * OUTER_FOLDS
            * (len(ARM_IDS) + 1),
            "required_evaluation_success_count": success_count,
            "adaptive82_target_accessed": False,
            "sealed_holdout_target_accessed": False,
        },
        "automatic_champion_selected": False,
        "confirmation_started": False,
        "external_validation": False,
        "p_values": "not_computed",
        "scientific_acceptance": False,
    }
    _write_json(result_path, result)
    _write_json(
        destination / "state.json",
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "phase": phase,
            "target_snapshot_written": True,
            "numeric_target_values_parsed": True,
            "adaptive82_target_accessed": False,
            "sealed_holdout_target_accessed": False,
            "confirmation_started": False,
            "scientific_acceptance": False,
        },
    )
    report(f"cross-component phase: {phase}")
    return result


__all__ = [
    "ARM_IDS",
    "AUTHORIZATION_SCHEMA_VERSION",
    "CONTRACT_SCHEMA_VERSION",
    "CrossComponentTransferError",
    "DEFAULT_WORKERS",
    "DESIGN",
    "FIXED_ARMS",
    "TARGETS",
    "build_authorization_template",
    "prepare_cross_component_transfer_contract",
    "run_cross_component_transfer",
    "verify_authorization",
    "write_prelaunch_artifacts",
]
