"""Focused public-chain checks using only deterministic synthetic matrices."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from brain_researcher.research.discovery.programs.tribe_speech_tools_acoustic_matched_validation_v1.evaluator import (
    ANALYSIS_CONTRACT_SCHEMA_VERSION,
    FEATURE_MANIFEST_SCHEMA_VERSION,
    INPUT_MANIFEST_SCHEMA_VERSION,
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
    rebuild_verified_feasibility_binding,
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
