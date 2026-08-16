"""Focused public-chain checks using only deterministic synthetic matrices."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from brain_researcher.research.discovery.programs.tribe_speech_tools_acoustic_matched_validation_v1.evaluator import (
    ANALYSIS_CONTRACT_SCHEMA_VERSION,
    FEATURE_MANIFEST_SCHEMA_VERSION,
    INPUT_MANIFEST_SCHEMA_VERSION,
    LEGACY_ANALYSIS_CONTRACT_SCHEMA_VERSION,
    LEGACY_FEATURE_MANIFEST_SCHEMA_VERSION,
    LEGACY_INPUT_MANIFEST_SCHEMA_VERSION,
    PROGRAM_ID as V1_PROGRAM_ID,
    evaluate_recurring_v1,
)
from brain_researcher.research.discovery.programs.tribe_speech_tools_acoustic_matched_validation_v1.execution import (
    execute_frozen_bundle_v1,
    read_frozen_bundle_terminal_execution_evidence,
)
from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.contracts import (
    ACOUSTIC_FEATURES,
    FROZEN_CONTRACT_SCHEMA_VERSION,
    default_inference_config,
    validate_source_candidate_pool_intake,
    validate_source_feasibility_contract,
)
from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.execution_contract import (
    MANIFEST_SCHEMA_VERSION as V2_MANIFEST_SCHEMA_VERSION,
    load_public_v2_execution_contract,
    rebuild_verified_feasibility_binding,
)
from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2 import (
    execution as v2_execution,
)
from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.evaluator import (
    PROGRAM_ID as V2_PROGRAM_ID,
)
from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.score_blind_selector import (
    select_score_blind_panel,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCKED_LAYERS = (
    "encoder.layers.0.1",
    "encoder.layers.2.1",
    "encoder.layers.4.1",
    "encoder.layers.10.1",
    "encoder.layers.12.1",
    "encoder.layers.14.1",
)


def _runtime() -> dict[str, object]:
    return {
        "mode": "precomputed_feature_matrices",
        "data_root": None,
        "model_root": None,
        "checkpoint": None,
        "command": None,
        "seed": None,
    }


def _reference_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(48):
        if index < 8:
            condition = "speech"
        elif index < 16:
            condition = "tools"
        else:
            condition = "other"
        rows.append({"row_key": f"reference-{index}", "condition": condition})
    return rows


def _evaluation_rows(*, include_segment_count: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for collection_index in range(4):
        for condition in ("speech", "tools"):
            for position in range(6):
                row: dict[str, object] = {
                    "row_key": f"candidate-{collection_index}-{condition}-{position}",
                    "collection_key": f"collection-{collection_index}",
                    "condition": condition,
                }
                if include_segment_count:
                    row["whisperx_segment_count"] = position + 1
                rows.append(row)
    return rows


def _matrices() -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    generator = np.random.default_rng(20260816)
    reference: dict[str, np.ndarray] = {}
    evaluation: dict[str, np.ndarray] = {}
    for layer_index, layer_id in enumerate(LOCKED_LAYERS):
        reference_matrix = generator.normal(
            loc=0.0,
            scale=1.0,
            size=(48, 1152),
        )
        reference_matrix[:8, :6] += 0.45
        reference_matrix[8:16, :6] -= 0.45
        evaluation_matrix = generator.normal(
            loc=0.0,
            scale=1.0,
            size=(48, 1152),
        )
        effect = 0.25 if layer_index < 3 else 0.10
        for index, row in enumerate(_evaluation_rows(include_segment_count=False)):
            evaluation_matrix[index, :6] += effect if row["condition"] == "speech" else -effect
        reference[layer_id] = reference_matrix
        evaluation[layer_id] = evaluation_matrix
    return reference, evaluation


def _write_matrix_maps(
    root: Path,
    reference: dict[str, np.ndarray],
    evaluation: dict[str, np.ndarray],
) -> tuple[Path, Path]:
    reference_paths: dict[str, str] = {}
    evaluation_paths: dict[str, str] = {}
    for position, layer_id in enumerate(LOCKED_LAYERS):
        reference_name = f"reference-{position}.npy"
        evaluation_name = f"evaluation-{position}.npy"
        np.save(root / reference_name, reference[layer_id], allow_pickle=False)
        np.save(root / evaluation_name, evaluation[layer_id], allow_pickle=False)
        reference_paths[layer_id] = reference_name
        evaluation_paths[layer_id] = evaluation_name
    reference_map = root / "reference-matrices.json"
    evaluation_map = root / "evaluation-matrices.json"
    reference_map.write_text(json.dumps(reference_paths), encoding="utf-8")
    evaluation_map.write_text(json.dumps(evaluation_paths), encoding="utf-8")
    return reference_map, evaluation_map


def _feature_manifest(
    *,
    program_id: str,
    rows: list[dict[str, object]],
    matrix_prefix: str,
) -> dict[str, object]:
    return {
        "schema_version": FEATURE_MANIFEST_SCHEMA_VERSION,
        "program_id": program_id,
        "runtime_fix_id": "neuralset.find_enclosed.one_ulp_outward_inclusive.v1",
        "runtime": _runtime(),
        "feature_ids_requested": list(LOCKED_LAYERS),
        "n_manifest_rows": 48,
        "n_selected_rows": 48,
        "n_success_rows": 48,
        "n_failed_rows": 0,
        "rows": [
            {"row_index": index, "status": "success", **row}
            for index, row in enumerate(rows)
        ],
        "layers": [
            {
                "layer_id": layer_id,
                "matrix_path": f"{matrix_prefix}-{position}.npy",
                "shape": [48, 1152],
                "row_indices": list(range(48)),
            }
            for position, layer_id in enumerate(LOCKED_LAYERS)
        ],
    }


def _write_v1_controlled_bundle(
    root: Path,
    *,
    reference_rows: list[dict[str, str]],
    evaluation_rows: list[dict[str, object]],
) -> Path:
    bundle = root / "controlled-feature-bundle"
    bundle.mkdir()
    analysis_contract = {
        "schema_version": ANALYSIS_CONTRACT_SCHEMA_VERSION,
        "program_id": V1_PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "execution_authorized": False,
        "confirmation_authorized": False,
        "input_manifest_bound": True,
        "runtime": _runtime(),
        "layers": {
            "early": list(LOCKED_LAYERS[:3]),
            "late": list(LOCKED_LAYERS[3:]),
        },
        "reference": {
            "required_schema_version": FEATURE_MANIFEST_SCHEMA_VERSION,
            "required_success_rows": 48,
            "required_feature_dimension": 1152,
            "required_layer_ids": list(LOCKED_LAYERS),
            "positive_condition": "speech",
            "negative_condition": "tools",
            "feature_manifest_path": "reference-features.json",
        },
        "primary_estimand": {
            "aggregate": "unweighted mean delta_s across four caller-supplied collections",
            "per_collection": "delta_s = mean_late(S) - mean_early(S)",
            "predicted_direction": "negative",
        },
        "decision_rule": {
            "bounded_support": [
                "aggregate delta_s is negative",
                "delta_s is negative in at least three of four collections",
                "early and late family C are both positive in at least three of four paired collections",
                "early frozen-reference AUC is greater than 0.5 in at least three of four collections",
            ],
            "no_metric_substitution": True,
            "otherwise": "stop as inconclusive or conflicting",
        },
    }
    input_manifest = {
        "schema_version": INPUT_MANIFEST_SCHEMA_VERSION,
        "program_id": V1_PROGRAM_ID,
        "conditions": ["speech", "tools"],
        "collection_keys": [f"collection-{index}" for index in range(4)],
        "items_per_condition_collection": 6,
        "rows": evaluation_rows,
    }
    report = {
        "schema_version": "br.tribe_speech_tools_public.recurring_materialization.v1",
        "program_id": V1_PROGRAM_ID,
        "status": "READY_AWAITING_SEPARATE_AUTHORIZATION",
        "input_manifest_written": True,
        "score_blind": True,
        "feature_extraction_completed": False,
        "collection_keys": [f"collection-{index}" for index in range(4)],
        "required": {
            "collection_count": 4,
            "items_per_condition_collection": 6,
            "total_rows": 48,
            "maximum_abs_pool_standardized_mean_difference": 0.5,
        },
        "selection": {
            "solver_status": "optimal",
            "balance": {
                "observed_max_abs_pool_standardized_mean_difference": 0.0,
            },
        },
    }
    state = {
        "program_id": V1_PROGRAM_ID,
        "status": "READY_AWAITING_SEPARATE_AUTHORIZATION",
        "input_manifest_bound": True,
        "execution_authorized": False,
        "confirmation_authorized": False,
        "feature_extraction_completed": False,
    }
    (bundle / "analysis_contract.json").write_text(
        json.dumps(analysis_contract), encoding="utf-8"
    )
    (bundle / "input_manifest.json").write_text(
        json.dumps(input_manifest), encoding="utf-8"
    )
    (bundle / "materialization_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    (bundle / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (bundle / "reference-features.json").write_text(
        json.dumps(
            _feature_manifest(
                program_id=V1_PROGRAM_ID,
                rows=reference_rows,
                matrix_prefix="reference",
            )
        ),
        encoding="utf-8",
    )
    (bundle / "evaluation-features.json").write_text(
        json.dumps(
            _feature_manifest(
                program_id=V1_PROGRAM_ID,
                rows=evaluation_rows,
                matrix_prefix="evaluation",
            )
        ),
        encoding="utf-8",
    )
    return bundle


def _write_v1_legacy_shape_bundle(
    root: Path,
    *,
    reference_rows: list[dict[str, str]],
    evaluation_rows: list[dict[str, object]],
) -> Path:
    """Write a deidentified legacy-format fixture, not a governed replay."""

    bundle = root / "legacy-shape-feature-bundle"
    bundle.mkdir()
    legacy_row_key = "item" + "_id"
    legacy_row_index = "item_row_index"
    legacy_row_indices = "item_row_indices"
    source_sets = [f"legacy-source-{index}" for index in range(4)]
    legacy_evaluation_rows: list[dict[str, object]] = []
    for row_index, row in enumerate(evaluation_rows):
        collection_index = int(str(row["collection_key"]).rsplit("-", 1)[1])
        source_set = source_sets[collection_index]
        relative_media_path = f"fixture-media/{row_index:02d}.wav"
        legacy_evaluation_rows.append(
            {
                legacy_row_key: f"legacy-row-{row_index:02d}",
                legacy_row_index: row_index,
                "condition": row["condition"],
                "status": "success",
                "labels": {"source_set": source_set},
                "source": {"path": relative_media_path},
                "tribe_args": {"audio_path": relative_media_path},
            }
        )
    legacy_reference_rows = [
        {
            legacy_row_key: f"legacy-reference-{row_index:02d}",
            legacy_row_index: row_index,
            "condition": row["condition"],
            "status": "success",
        }
        for row_index, row in enumerate(reference_rows)
    ]
    extraction_contract = {
        "checkpoint_dir": "fixture-model-directory",
        "checkpoint_name": "fixture-model-artifact",
        "text_model_override": "fixture-text-model",
        "audio_model_override": "fixture-audio-model",
        "runtime_fix_id": "neuralset.find_enclosed.one_ulp_outward_inclusive.v1",
        "feature_ids": list(LOCKED_LAYERS),
        "reference_and_evaluation_must_match": True,
        "feature_aggregation": "item-level mean of each captured module tensor, matching v3",
    }
    analysis_contract = {
        "schema_version": LEGACY_ANALYSIS_CONTRACT_SCHEMA_VERSION,
        "episode_id": V1_PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "execution_authorized": False,
        "confirmation_authorized": False,
        "input_manifest_bound": True,
        "frozen_extraction_contract": extraction_contract,
        "layers": {
            "early": list(LOCKED_LAYERS[:3]),
            "late": list(LOCKED_LAYERS[3:]),
        },
        "reference": {
            "required_schema_version": LEGACY_FEATURE_MANIFEST_SCHEMA_VERSION,
            "required_success_rows": 48,
            "required_feature_dimension": 1152,
            "required_layer_ids": list(LOCKED_LAYERS),
            "positive_condition": "speech",
            "negative_condition": "tools",
            "feature_manifest_path": "legacy-reference-features.json",
        },
        "primary_estimand": {
            "aggregate": "unweighted mean delta_s across the four natural source sets",
            "per_source_set": "delta_s = mean_late(S) - mean_early(S)",
            "predicted_direction": "negative",
        },
        "decision_rule": {
            "bounded_support": [
                "aggregate delta_s is negative",
                "delta_s is negative in at least three of four natural source sets",
                "early and late family C are both positive in at least three of four paired source sets",
                "early frozen-reference AUC is greater than 0.5 in at least three of four source sets",
            ],
            "no_metric_substitution": True,
            "otherwise": "stop as inconclusive or conflicting",
        },
    }
    input_manifest = {
        "schema_version": LEGACY_INPUT_MANIFEST_SCHEMA_VERSION,
        "episode_id": V1_PROGRAM_ID,
        "conditions": ["speech", "tools"],
        "source_sets": source_sets,
        "items_per_condition_source_set": 6,
        "items": [
            {
                key: value
                for key, value in row.items()
                if key != legacy_row_index and key != "status"
            }
            for row in legacy_evaluation_rows
        ],
    }
    report = {
        "schema_version": "br.autoresearch.tribe_speech_tools_acoustic_materialization.v1",
        "episode_id": V1_PROGRAM_ID,
        "status": "READY_AWAITING_SEPARATE_AUTHORIZATION",
        "input_manifest_written": True,
        "score_blind": True,
        "cpu_only": True,
        "tribe_inference_run": False,
        "gpu_used": False,
        "blockers": [],
        "natural_source_sets": source_sets,
        "required": {
            "natural_source_set_count": 4,
            "items_per_condition_source_set": 6,
            "total_items": 48,
            "maximum_abs_pool_standardized_mean_difference": 0.5,
        },
        "selection": {
            "solver_status": "optimal",
            "balance": {
                "observed_max_abs_pool_standardized_mean_difference": 0.0,
                "rows": [
                    {
                        "source_set": source_set,
                        "max_abs_pool_standardized_mean_difference": 0.0,
                    }
                    for source_set in [*source_sets, "pooled"]
                ],
            },
        },
    }
    state = {
        "episode_id": V1_PROGRAM_ID,
        "status": "READY_AWAITING_SEPARATE_AUTHORIZATION",
        "input_manifest_bound": True,
        "execution_authorized": False,
        "confirmation_authorized": False,
        "tribe_inference_run": False,
        "gpu_used": False,
        "blockers": [],
    }

    def feature_manifest(
        rows: list[dict[str, object]], matrix_prefix: str
    ) -> dict[str, object]:
        return {
            "schema_version": LEGACY_FEATURE_MANIFEST_SCHEMA_VERSION,
            "runtime_fix_id": "neuralset.find_enclosed.one_ulp_outward_inclusive.v1",
            "checkpoint_dir": "fixture-model-directory",
            "checkpoint_name": "fixture-model-artifact",
            "model_overrides": {
                "data." + "text_feature.model_name": "fixture-text-model",
                "data." + "audio_feature.model_name": "fixture-audio-model",
            },
            "feature_ids_requested": list(LOCKED_LAYERS),
            "n_manifest_items": 48,
            "n_selected_items": 48,
            "n_success_items": 48,
            "n_failed_items": 0,
            "rows": rows,
            "layers": [
                {
                    "layer_id": layer_id,
                    "feature_id": layer_id,
                    "matrix_path": f"{matrix_prefix}-{position}.npy",
                    "path": f"{matrix_prefix}-{position}.npy",
                    "shape": [48, 1152],
                    legacy_row_indices: list(range(48)),
                }
                for position, layer_id in enumerate(LOCKED_LAYERS)
            ],
        }

    for filename, payload in {
        "analysis_contract.json": analysis_contract,
        "input_manifest.json": input_manifest,
        "materialization_report.json": report,
        "state.json": state,
        "legacy-reference-features.json": feature_manifest(
            legacy_reference_rows, "reference"
        ),
        "legacy-evaluation-features.json": feature_manifest(
            legacy_evaluation_rows, "evaluation"
        ),
    }.items():
        (bundle / filename).write_text(json.dumps(payload), encoding="utf-8")
    return bundle


def _controlled_source_contract(reference_rows: list[dict[str, str]]) -> dict[str, object]:
    candidate_pool: list[dict[str, object]] = []
    collection_keys = [f"protected-collection-{index}" for index in range(4)]
    for collection_index, collection_key in enumerate(collection_keys):
        for condition in ("speech", "tools"):
            for position in range(12):
                candidate_pool.append(
                    {
                        "candidate_key": (
                            f"protected-candidate-{collection_index}-{condition}-{position}"
                        ),
                        "source_token": (
                            f"protected-source-{collection_index}-{condition}-{position}"
                        ),
                        "decoded_pcm_identity": (
                            f"protected-pcm-{collection_index}-{condition}-{position}"
                        ),
                        "parent_key": (
                            f"protected-parent-{collection_index}-{condition}-{position}"
                        ),
                        "collection_key": collection_key,
                        "condition": condition,
                        "whisperx_segment_count": position % 2 + 1,
                        "acoustic_features": {
                            feature: float(position) for feature in ACOUSTIC_FEATURES
                        },
                        "score_blind": True,
                        "tribe_inference_run": False,
                        "auditory_qc": [
                            {
                                "reviewer_key": (
                                    f"reviewer-a-{collection_index}-{condition}-{position}"
                                ),
                                "target_present": True,
                                "opposite_condition_absent": True,
                                "dominant_condition": condition,
                                "blinded_to_proposed_condition": True,
                                "blinded_to_source": True,
                                "blinded_to_acoustic": True,
                                "blinded_to_asr": True,
                                "blinded_to_tribe": True,
                            },
                            {
                                "reviewer_key": (
                                    f"reviewer-b-{collection_index}-{condition}-{position}"
                                ),
                                "target_present": True,
                                "opposite_condition_absent": True,
                                "dominant_condition": condition,
                                "blinded_to_proposed_condition": True,
                                "blinded_to_source": True,
                                "blinded_to_acoustic": True,
                                "blinded_to_asr": True,
                                "blinded_to_tribe": True,
                            },
                        ],
                    }
                )
    return {
        "schema_version": FROZEN_CONTRACT_SCHEMA_VERSION,
        "program_id": V2_PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "score_blind": True,
        "authority_granted": False,
        "launch_authorized": False,
        "gpu_authorized": False,
        "tribe_inference_authorized": False,
        "manuscript_update_authorized": False,
        "execution_authorized": False,
        "confirmation_authorized": False,
        "registration_authorized": False,
        "frozen_reference": {
            "reference_label": "protected-reference",
            "item_rows": reference_rows,
            "locked_layer_ids": list(LOCKED_LAYERS),
            "feature_dimensions": {layer: 1152 for layer in LOCKED_LAYERS},
        },
        "source_collections": collection_keys,
        "candidate_pool": candidate_pool,
    }


def _private_shape_v2_controlled_inputs(
    reference_rows: list[dict[str, str]],
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    object,
]:
    """Build deidentified registration-shaped inputs without governed artifacts."""

    public_contract = _controlled_source_contract(reference_rows)
    empty_history = [
        {
            "candidate_keys": [],
            "source_tokens": [],
            "pcm_tokens": [],
            "collection_keys": [],
        }
        for _ in range(8)
    ]
    intake = validate_source_candidate_pool_intake(public_contract, empty_history)
    public_contract["selection"] = select_score_blind_panel(
        intake
    ).to_contract_selection()
    public_binding = validate_source_feasibility_contract(
        public_contract,
        empty_history,
    )

    private_row_field = "item" + "_id"
    private_collection_field = "collection" + "_id"
    private_parent_field = "parent_recording" + "_id"
    private_selected_field = "selected" + "_item" + "_ids"
    checkpoint_directory = "fixture-checkpoint-directory"
    checkpoint_artifact = "fixture-checkpoint-artifact"
    runtime_fix = "neuralset.find_enclosed.one_ulp_outward_inclusive.v1"
    private_candidates: list[dict[str, object]] = []
    for raw_candidate in public_contract["candidate_pool"]:
        candidate = dict(raw_candidate)
        private_candidates.append(
            {
                private_row_field: candidate["candidate_key"],
                private_collection_field: candidate["collection_key"],
                private_parent_field: candidate["parent_key"],
                "condition": candidate["condition"],
                "canonical_source_path": candidate["source_token"],
                "decoded_pcm_identity": candidate["decoded_pcm_identity"],
                "whisperx_segment_count": candidate["whisperx_segment_count"],
                "acoustic_features": {
                    feature: candidate["acoustic_features"][feature]
                    for feature in reversed(ACOUSTIC_FEATURES)
                },
                "score_blind": True,
                "tribe_inference_run": False,
                "gpu_used": False,
                "auditory_qc": [
                    {
                        **{
                            key: value
                            for key, value in dict(review).items()
                            if key != "reviewer_key"
                        },
                        "reviewer_id": dict(review)["reviewer_key"],
                    }
                    for review in candidate["auditory_qc"]
                ],
                "source": {"path": candidate["source_token"]},
                "tribe_args": {"audio_path": candidate["source_token"]},
            }
        )
    selection = dict(public_contract["selection"])
    private_selection = {
        key: value
        for key, value in selection.items()
        if key != "selected_candidate_keys"
    }
    private_selection[private_selected_field] = selection["selected_candidate_keys"]
    packet = {
        "schema_version": (
            "br.autoresearch.tribe_speech_tools_new_source_asr_covariate_"
            "analysis_contract.v2"
        ),
        "program_id": V2_PROGRAM_ID,
        "episode_id": V2_PROGRAM_ID,
        "scope": "prospective_discovery_validation",
        "score_blind": True,
        "authority_granted": False,
        "launch_authorized": False,
        "gpu_authorized": False,
        "tribe_inference_authorized": False,
        "manuscript_update_authorized": False,
        "execution_authorized": False,
        "confirmation_authorized": False,
        "registration_authorized": False,
        "frozen_reference": {
            "program_id": "fixture-reference-program",
            "feature_manifest_identity": "fixture-reference-manifest",
            "feature_manifest_schema_version": LEGACY_FEATURE_MANIFEST_SCHEMA_VERSION,
            "item_rows_identity": "fixture-reference-rows",
            "contract_version": "fixture-reference-contract",
            "runtime_fix_id": runtime_fix,
            "allowed_argv_id": "fixture-launch-contract",
            "checkpoint_dir": checkpoint_directory,
            "checkpoint_name": checkpoint_artifact,
            "locked_layer_ids": list(LOCKED_LAYERS),
            "feature_dimensions": {layer: 1152 for layer in LOCKED_LAYERS},
            "item_rows": [
                {
                    private_row_field: row["row_key"],
                    "condition": row["condition"],
                }
                for row in reference_rows
            ],
        },
        "runtime_closeout_interface": {
            "run_mode": "one_shot",
            "direct_execution_compatible": False,
            "successor_adapter_required": True,
            "execution_authorized": False,
            "confirmation_authorized": False,
        },
        "permutation_metadata": default_inference_config(),
        "hypothesis_families": ["H1", "H2", "H3", "H5"],
        "asr_covariate": {
            "producer": "WhisperX",
            "field": "whisperx_segment_count",
            "cpu_only": True,
            "materialized_before_tribe": True,
        },
        "historical_exposure_role_ids": [
            f"fixture-history-role-{index}" for index in range(8)
        ],
        "source_collections": [
            {
                private_collection_field: collection_key,
                "provenance": {
                    "provider": "fixture-provider",
                    "collection_url": "fixture-collection-location",
                    "release_id": "fixture-release",
                    "license_id": "fixture-license",
                    "license_text": "fixture-license-text",
                    "license_url": "fixture-license-location",
                    "license_status": "verified_for_selected_release",
                },
            }
            for collection_key in public_contract["source_collections"]
        ],
        "candidate_pool": private_candidates,
        "selection": private_selection,
    }

    item_counts = (60, 30, 48, 48, 48, 48, 48, 48)
    sidecars: list[dict[str, object]] = []
    for role_index, item_count in enumerate(item_counts):
        historical_collection = f"fixture-history-collection-{role_index}"
        sidecars.append(
            {
                "schema_version": (
                    "br.autoresearch.tribe_speech_tools_new_source_"
                    "historical_exposure_sidecar.v2"
                ),
                "status": "historical_exposure_pcm_materialized",
                "role_id": f"fixture-history-role-{role_index}",
                "identifier_field": "fixture_identifier",
                "identifier": f"fixture-history-identifier-{role_index}",
                "expected_item_count": item_count,
                "source_manifest_path": f"fixture-source-manifest-{role_index}",
                "collection_identities": [historical_collection],
                "items": [
                    {
                        private_row_field: (
                            f"fixture-history-row-{role_index}-{position:03d}"
                        ),
                        "canonical_source_path": (
                            f"fixture-history-source-{role_index}-{position:03d}"
                        ),
                        "decoded_pcm_identity": (
                            f"fixture-history-pcm-{role_index}-{position:03d}"
                        ),
                        private_collection_field: historical_collection,
                    }
                    for position in range(item_count)
                ],
                "pcm_identity_policy": "fixture opaque sequential grouping",
            }
        )
    return packet, sidecars, public_binding


def _write_private_v2_feature_manifest(
    path: Path,
    *,
    rows: list[dict[str, object]],
    matrix_prefix: str,
) -> None:
    private_row_field = "item" + "_id"
    path.write_text(
        json.dumps(
            {
                "schema_version": LEGACY_FEATURE_MANIFEST_SCHEMA_VERSION,
                "runtime_fix_id": (
                    "neuralset.find_enclosed.one_ulp_outward_inclusive.v1"
                ),
                "checkpoint_dir": "fixture-checkpoint-directory",
                "checkpoint_name": "fixture-checkpoint-artifact",
                "model_overrides": {
                    "data.text_feature.model_name": "fixture-text-model",
                    "data.audio_feature.model_name": "fixture-audio-model",
                },
                "feature_ids_requested": list(LOCKED_LAYERS),
                "n_manifest_items": 48,
                "n_selected_items": 48,
                "n_success_items": 48,
                "n_failed_items": 0,
                "rows": [
                    {
                        "item_row_index": index,
                        private_row_field: row["row_key"],
                        "condition": row["condition"],
                        "status": "success",
                    }
                    for index, row in enumerate(rows)
                ],
                "layers": [
                    {
                        "layer_id": layer_id,
                        "matrix_path": f"{matrix_prefix}-{position}.npy",
                        "shape": [48, 1152],
                        "item_row_indices": list(range(48)),
                    }
                    for position, layer_id in enumerate(LOCKED_LAYERS)
                ],
            }
        ),
        encoding="utf-8",
    )


def test_synthetic_v2_cli_and_v1_controlled_feature_replay(tmp_path: Path) -> None:
    reference, evaluation = _matrices()
    reference_rows = _reference_rows()
    v1_evaluation_rows = _evaluation_rows(include_segment_count=False)
    v2_evaluation_rows = _evaluation_rows(include_segment_count=True)
    reference_map, evaluation_map = _write_matrix_maps(tmp_path, reference, evaluation)

    in_memory = evaluate_recurring_v1(
        reference_matrices=reference,
        evaluation_matrices=evaluation,
        reference_rows=reference_rows,
        evaluation_rows=v1_evaluation_rows,
    )
    assert in_memory["evaluation_status"] == "valid"

    bundle = _write_v1_controlled_bundle(
        tmp_path,
        reference_rows=reference_rows,
        evaluation_rows=v1_evaluation_rows,
    )
    for source in tmp_path.glob("reference-*.npy"):
        (bundle / source.name).write_bytes(source.read_bytes())
    for source in tmp_path.glob("evaluation-*.npy"):
        (bundle / source.name).write_bytes(source.read_bytes())
    v1_artifacts = {
        "evaluation": tmp_path / "controlled-v1-evaluation.json",
        "state": tmp_path / "controlled-v1-state.json",
        "terminal": tmp_path / "controlled-v1-terminal.json",
        "attempt": tmp_path / "controlled-v1-attempt.json",
    }
    controlled_result = execute_frozen_bundle_v1(
        bundle_dir=bundle,
        evaluation_features_path=bundle / "evaluation-features.json",
        evaluation_artifact_path=v1_artifacts["evaluation"],
        state_artifact_path=v1_artifacts["state"],
        terminal_artifact_path=v1_artifacts["terminal"],
        attempt_artifact_path=v1_artifacts["attempt"],
    )
    assert str(bundle) not in json.dumps(controlled_result)
    assert read_frozen_bundle_terminal_execution_evidence(
        bundle_dir=bundle,
        evaluation_features_path=bundle / "evaluation-features.json",
        evaluation_artifact_path=v1_artifacts["evaluation"],
        state_artifact_path=v1_artifacts["state"],
        terminal_artifact_path=v1_artifacts["terminal"],
        attempt_artifact_path=v1_artifacts["attempt"],
    )["status"] == "verified"

    inference = default_inference_config()
    for value in inference["family_tests"].values():
        value["draws"] = 7
    v2_manifest = {
        "schema_version": V2_MANIFEST_SCHEMA_VERSION,
        "program_id": V2_PROGRAM_ID,
        "execution_kind": "synthetic_fixture",
        "runtime": _runtime(),
        "reference_rows": reference_rows,
        "evaluation_rows": v2_evaluation_rows,
        "inference": inference,
        "compute_inference": True,
    }
    manifest_path = tmp_path / "synthetic-v2-manifest.json"
    manifest_path.write_text(json.dumps(v2_manifest), encoding="utf-8")
    artifacts = {
        "evaluation": tmp_path / "synthetic-v2-evaluation.json",
        "state": tmp_path / "synthetic-v2-state.json",
        "terminal": tmp_path / "synthetic-v2-terminal.json",
        "attempt": tmp_path / "synthetic-v2-attempt.json",
    }
    command = [
        sys.executable,
        "-m",
        "brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.execution",
        "evaluate",
        "--manifest",
        str(manifest_path),
        "--reference-matrix-map",
        str(reference_map),
        "--evaluation-matrix-map",
        str(evaluation_map),
        "--evaluation-artifact",
        str(artifacts["evaluation"]),
        "--state-artifact",
        str(artifacts["state"]),
        "--terminal-artifact",
        str(artifacts["terminal"]),
        "--attempt-artifact",
        str(artifacts["attempt"]),
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT / "src")
    subprocess.run(command, check=True, text=True, capture_output=True, env=environment)
    verification = subprocess.run(
        [*command[:3], "verify", *command[4:]],
        check=True,
        text=True,
        capture_output=True,
        env=environment,
    )
    assert '"status": "verified"' in verification.stdout
    artifact = json.loads(artifacts["evaluation"].read_text(encoding="utf-8"))
    assert artifact["scientific_evidence"] == "synthetic_fixture_only"
    assert artifact["evaluation"]["evaluation_status"] == "valid"
    assert str(tmp_path) not in json.dumps(artifact)


def test_v1_legacy_shape_bundle_replays_with_opaque_output(tmp_path: Path) -> None:
    """Legacy contract fields are accepted without exposing fixture identities."""

    reference, evaluation = _matrices()
    reference_rows = _reference_rows()
    evaluation_rows = _evaluation_rows(include_segment_count=False)
    _write_matrix_maps(tmp_path, reference, evaluation)
    bundle = _write_v1_legacy_shape_bundle(
        tmp_path,
        reference_rows=reference_rows,
        evaluation_rows=evaluation_rows,
    )
    for source in tmp_path.glob("reference-*.npy"):
        (bundle / source.name).write_bytes(source.read_bytes())
    for source in tmp_path.glob("evaluation-*.npy"):
        (bundle / source.name).write_bytes(source.read_bytes())
    artifacts = {
        "evaluation": tmp_path / "legacy-v1-evaluation.json",
        "state": tmp_path / "legacy-v1-state.json",
        "terminal": tmp_path / "legacy-v1-terminal.json",
        "attempt": tmp_path / "legacy-v1-attempt.json",
    }
    result = execute_frozen_bundle_v1(
        bundle_dir=bundle,
        evaluation_features_path=bundle / "legacy-evaluation-features.json",
        evaluation_artifact_path=artifacts["evaluation"],
        state_artifact_path=artifacts["state"],
        terminal_artifact_path=artifacts["terminal"],
        attempt_artifact_path=artifacts["attempt"],
    )
    assert result["evaluation_status"] == "valid"
    assert [row["collection_key"] for row in result["source_sets"]] == [
        f"collection-{index:02d}" for index in range(4)
    ]
    rendered = json.dumps(result)
    assert "legacy-row-" not in rendered
    assert "legacy-source-" not in rendered
    assert "fixture-media/" not in rendered
    assert read_frozen_bundle_terminal_execution_evidence(
        bundle_dir=bundle,
        evaluation_features_path=bundle / "legacy-evaluation-features.json",
        evaluation_artifact_path=artifacts["evaluation"],
        state_artifact_path=artifacts["state"],
        terminal_artifact_path=artifacts["terminal"],
        attempt_artifact_path=artifacts["attempt"],
    )["status"] == "verified"


def test_controlled_history_rebuilds_an_opaque_binding(tmp_path: Path) -> None:
    protected_reference_rows = _reference_rows()
    protected_contract = _controlled_source_contract(protected_reference_rows)
    sidecars = [
        {
            "candidate_keys": [],
            "source_tokens": [],
            "pcm_tokens": [],
            "collection_keys": [],
        }
        for _ in range(8)
    ]
    intake = validate_source_candidate_pool_intake(protected_contract, sidecars)
    protected_contract["selection"] = select_score_blind_panel(
        intake
    ).to_contract_selection()
    protected_binding = validate_source_feasibility_contract(
        protected_contract,
        sidecars,
    )
    source_packet = tmp_path / "source-packet.json"
    source_packet.write_text(
        json.dumps({"contract": protected_contract}),
        encoding="utf-8",
    )
    sidecar_paths: list[Path] = []
    for index, sidecar in enumerate(sidecars):
        path = tmp_path / f"history-{index}.json"
        path.write_text(json.dumps(sidecar), encoding="utf-8")
        sidecar_paths.append(path)
    opaque_reference_rows = [
        {"row_key": f"row-{index:04d}", "condition": row["condition"]}
        for index, row in enumerate(protected_reference_rows)
    ]
    opaque_evaluation_rows = [
        {
            "row_key": f"row-{index:04d}",
            "collection_key": f"collection-{index // 12:02d}",
            "condition": row.condition,
            "whisperx_segment_count": row.whisperx_segment_count,
        }
        for index, row in enumerate(protected_binding.evaluation_item_rows)
    ]
    controlled = rebuild_verified_feasibility_binding(
        source_packet_path=source_packet,
        historical_exposure_sidecar_paths=sidecar_paths,
        reference_rows=opaque_reference_rows,
        evaluation_rows=opaque_evaluation_rows,
    )
    assert all(
        row.row_key == f"row-{index:04d}"
        and row.collection_key == f"collection-{index // 12:02d}"
        for index, row in enumerate(controlled.binding.evaluation_item_rows)
    )
    assert "protected-candidate-0-speech-0" in controlled.forbidden_output_tokens


def test_private_shape_v2_controlled_history_binds_rows_and_matrices(
    tmp_path: Path,
) -> None:
    """Registration-shaped inputs are adapted before opaque evaluator replay."""

    reference, evaluation = _matrices()
    reference_map, evaluation_map = _write_matrix_maps(
        tmp_path,
        reference,
        evaluation,
    )
    protected_reference_rows = _reference_rows()
    packet, sidecars, protected_binding = _private_shape_v2_controlled_inputs(
        protected_reference_rows
    )
    source_packet_path = tmp_path / "private-shape-source-packet.json"
    source_packet_path.write_text(json.dumps(packet), encoding="utf-8")
    sidecar_paths: list[Path] = []
    for index, sidecar in enumerate(sidecars):
        sidecar_path = tmp_path / f"private-shape-history-{index}.json"
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
        sidecar_paths.append(sidecar_path)

    protected_evaluation_rows = [
        {
            "row_key": row.row_key,
            "condition": row.condition,
        }
        for row in protected_binding.evaluation_item_rows
    ]
    reference_feature_manifest = tmp_path / "private-reference-features.json"
    evaluation_feature_manifest = tmp_path / "private-evaluation-features.json"
    _write_private_v2_feature_manifest(
        reference_feature_manifest,
        rows=protected_reference_rows,
        matrix_prefix="reference",
    )
    _write_private_v2_feature_manifest(
        evaluation_feature_manifest,
        rows=protected_evaluation_rows,
        matrix_prefix="evaluation",
    )
    opaque_reference_rows = [
        {"row_key": f"row-{index:04d}", "condition": row["condition"]}
        for index, row in enumerate(protected_reference_rows)
    ]
    protected_collections = sorted(
        {row.collection_key for row in protected_binding.evaluation_item_rows}
    )
    collection_map = {
        collection: f"collection-{index:02d}"
        for index, collection in enumerate(protected_collections)
    }
    opaque_evaluation_rows = [
        {
            "row_key": f"row-{index:04d}",
            "collection_key": collection_map[row.collection_key],
            "condition": row.condition,
            "whisperx_segment_count": row.whisperx_segment_count,
        }
        for index, row in enumerate(protected_binding.evaluation_item_rows)
    ]
    with pytest.raises(ValueError, match="legacy controlled history requires"):
        rebuild_verified_feasibility_binding(
            source_packet_path=source_packet_path,
            historical_exposure_sidecar_paths=sidecar_paths,
            reference_rows=opaque_reference_rows,
            evaluation_rows=opaque_evaluation_rows,
        )
    controlled = rebuild_verified_feasibility_binding(
        source_packet_path=source_packet_path,
        historical_exposure_sidecar_paths=sidecar_paths,
        reference_rows=opaque_reference_rows,
        evaluation_rows=opaque_evaluation_rows,
        reference_feature_manifest_path=reference_feature_manifest,
        evaluation_feature_manifest_path=evaluation_feature_manifest,
        reference_matrix_map_path=reference_map,
        evaluation_matrix_map_path=evaluation_map,
    )

    assert [row.row_key for row in controlled.binding.evaluation_item_rows] == [
        f"row-{index:04d}" for index in range(48)
    ]
    assert {
        row.collection_key for row in controlled.binding.evaluation_item_rows
    } == {f"collection-{index:02d}" for index in range(4)}
    assert "protected-candidate-0-speech-0" in controlled.forbidden_output_tokens
    assert "fixture-history-source-0-000" in controlled.forbidden_output_tokens
    assert controlled.canonical_feature_binding_validated is True
    assert controlled.binding.canonical_feature_binding_validated is True

    provider_manifest = tmp_path / "controlled-provider-manifest.json"
    provider_manifest.write_text(
        json.dumps(
            {
                "schema_version": V2_MANIFEST_SCHEMA_VERSION,
                "program_id": V2_PROGRAM_ID,
                "execution_kind": "governed_external_input",
                "runtime": _runtime(),
                "reference_rows": opaque_reference_rows,
                "evaluation_rows": opaque_evaluation_rows,
                "inference": default_inference_config(),
                "compute_inference": True,
            }
        ),
        encoding="utf-8",
    )
    provider_artifacts = {
        "evaluation": tmp_path / "controlled-provider-evaluation.json",
        "state": tmp_path / "controlled-provider-state.json",
        "terminal": tmp_path / "controlled-provider-terminal.json",
        "attempt": tmp_path / "controlled-provider-attempt.json",
    }
    provider_contract = load_public_v2_execution_contract(
        manifest_path=provider_manifest,
        reference_matrix_map_path=reference_map,
        evaluation_matrix_map_path=evaluation_map,
        evaluation_artifact_path=provider_artifacts["evaluation"],
        state_artifact_path=provider_artifacts["state"],
        terminal_artifact_path=provider_artifacts["terminal"],
        attempt_artifact_path=provider_artifacts["attempt"],
    )
    provider_called = False

    def arbitrary_provider(_: object) -> tuple[dict[str, object], dict[str, object]]:
        nonlocal provider_called
        provider_called = True
        return {}, {}

    with pytest.raises(v2_execution.TribeV2ExecutionError, match="canonical matrix"):
        v2_execution.execute_public_v2_evaluation(
            provider_contract,
            feature_map_provider=arbitrary_provider,
            feasibility_binding=controlled.binding,
            reference_binding=controlled.binding.frozen_reference,
            forbidden_output_tokens=controlled.forbidden_output_tokens,
        )
    assert provider_called is False
    assert provider_artifacts["terminal"].exists() is False

    mismatched_map_payload = json.loads(reference_map.read_text(encoding="utf-8"))
    mismatched_map_payload[LOCKED_LAYERS[0]] = "evaluation-0.npy"
    mismatched_map = tmp_path / "mismatched-reference-matrices.json"
    mismatched_map.write_text(json.dumps(mismatched_map_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="matrix map"):
        rebuild_verified_feasibility_binding(
            source_packet_path=source_packet_path,
            historical_exposure_sidecar_paths=sidecar_paths,
            reference_rows=opaque_reference_rows,
            evaluation_rows=opaque_evaluation_rows,
            reference_feature_manifest_path=reference_feature_manifest,
            evaluation_feature_manifest_path=evaluation_feature_manifest,
            reference_matrix_map_path=mismatched_map,
            evaluation_matrix_map_path=evaluation_map,
        )


@pytest.mark.parametrize(
    ("nested_value", "forbidden_tokens"),
    [
        ("prefix-fixture-private-token-suffix", ("fixture-private-token",)),
        (r"Z:\fixture\private-media.wav", ()),
        ("prefix(" + "/" + "data/x)", ()),
        (r"prefix[C:\fixture\private-media.wav]", ()),
        (r"prefix(\\server\share\private-media.wav)", ()),
    ],
)
def test_controlled_history_privacy_rejects_substrings_and_paths(
    nested_value: str,
    forbidden_tokens: tuple[str, ...],
) -> None:
    evaluation = {
        "per_item_pairwise_concordance": [],
        "nested": {"values": [nested_value]},
    }
    with pytest.raises(v2_execution.TribeV2ExecutionError):
        v2_execution._assert_public_evaluation_is_opaque(  # noqa: SLF001
            evaluation,
            forbidden_output_tokens=forbidden_tokens,
        )
