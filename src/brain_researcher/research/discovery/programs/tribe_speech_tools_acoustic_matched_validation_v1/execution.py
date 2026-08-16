"""Public recurring-v1 evaluator execution and terminal replay evidence.

The private program binds execution to a protected registration.  This module
only evaluates feature matrices supplied by its caller.  It does not launch a
runtime command, discover a model asset, or infer a location for protected
inputs.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    PublicTribeChainError,
    artifact_name,
    load_matrix_map,
    read_json_object,
    replace_json,
    write_json_new,
)

from .evaluator import (
    EVALUATION_SCHEMA_VERSION,
    evaluate_frozen_validation,
    evaluate_recurring_v1,
    read_evaluation_result,
    write_evaluation_result,
)
from .execution_contract import PublicRecurringExecutionContract

EXECUTION_SCHEMA_VERSION = "br.tribe_speech_tools_public.recurring_execution.v1"
TERMINAL_EVIDENCE_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.recurring_terminal_evidence.v1"
)

FeatureMapProviderV1 = Callable[
    [PublicRecurringExecutionContract],
    tuple[Mapping[str, Any], Mapping[str, Any]],
]


class TribeExecutionEvidenceError(ValueError):
    """A public execution artifact cannot establish terminal evaluator evidence."""


def _artifact_names(contract: PublicRecurringExecutionContract) -> dict[str, str]:
    names = {
        "attempt": artifact_name(contract.attempt_artifact_path, label="attempt_artifact"),
        "state": artifact_name(contract.state_artifact_path, label="state_artifact"),
        "evaluation": artifact_name(
            contract.evaluation_artifact_path, label="evaluation_artifact"
        ),
        "terminal": artifact_name(
            contract.terminal_artifact_path, label="terminal_artifact"
        ),
    }
    if len(set(names.values())) != len(names):
        raise TribeExecutionEvidenceError("all output artifact paths must be distinct")
    return names


def _resolve_feature_maps(
    contract: PublicRecurringExecutionContract,
    feature_map_provider: FeatureMapProviderV1 | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if feature_map_provider is not None:
        value = feature_map_provider(contract)
        if not isinstance(value, tuple) or len(value) != 2:
            raise TribeExecutionEvidenceError(
                "feature_map_provider must return reference and evaluation mappings"
            )
        return value
    if contract.runtime.mode != "precomputed_feature_matrices":
        raise TribeExecutionEvidenceError(
            "injected_adapter runtime requires a caller-provided feature_map_provider"
        )
    return (
        load_matrix_map(contract.reference_matrix_map_path, label="reference_matrix_map"),
        load_matrix_map(
            contract.evaluation_matrix_map_path, label="evaluation_matrix_map"
        ),
    )


def execute_recurring_v1(
    contract: PublicRecurringExecutionContract,
    *,
    feature_map_provider: FeatureMapProviderV1 | None = None,
) -> dict[str, Any]:
    """Execute exactly one caller-bounded v1 evaluation and write named artifacts."""

    names = _artifact_names(contract)
    attempt = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "attempt",
        "execution_kind": contract.execution_kind,
        "status": "started",
        "artifacts": names,
    }
    state = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "state",
        "execution_kind": contract.execution_kind,
        "status": "running",
        "artifacts": names,
    }
    write_json_new(contract.attempt_artifact_path, attempt, label="attempt_artifact")
    write_json_new(contract.state_artifact_path, state, label="state_artifact")
    try:
        reference_matrices, evaluation_matrices = _resolve_feature_maps(
            contract, feature_map_provider
        )
        evaluation = evaluate_recurring_v1(
            reference_matrices=reference_matrices,
            evaluation_matrices=evaluation_matrices,
            reference_rows=contract.reference_rows,
            evaluation_rows=contract.evaluation_rows,
        )
        artifact = {
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "artifact_type": "evaluation",
            "execution_kind": contract.execution_kind,
            "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
            "scientific_evidence": (
                "synthetic_fixture_only"
                if contract.execution_kind == "synthetic_fixture"
                else "public_evaluator_result_only"
            ),
            "evaluation": evaluation,
        }
        write_json_new(
            contract.evaluation_artifact_path, artifact, label="evaluation_artifact"
        )
        completed_state = dict(state)
        completed_state["status"] = "completed"
        replace_json(contract.state_artifact_path, completed_state, label="state_artifact")
        terminal = {
            "schema_version": TERMINAL_EVIDENCE_SCHEMA_VERSION,
            "artifact_type": "terminal_evidence",
            "execution_kind": contract.execution_kind,
            "status": "completed",
            "artifacts": names,
            "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
        }
        write_json_new(
            contract.terminal_artifact_path, terminal, label="terminal_artifact"
        )
        return artifact
    except Exception:
        failed_state = dict(state)
        failed_state["status"] = "failed"
        replace_json(contract.state_artifact_path, failed_state, label="state_artifact")
        raise


def read_recurring_terminal_execution_evidence(
    contract: PublicRecurringExecutionContract,
    *,
    feature_map_provider: FeatureMapProviderV1 | None = None,
) -> dict[str, Any]:
    """Recompute the frozen evaluator and validate all public terminal artifacts."""

    names = _artifact_names(contract)
    try:
        attempt = read_json_object(contract.attempt_artifact_path, label="attempt_artifact")
        state = read_json_object(contract.state_artifact_path, label="state_artifact")
        artifact = read_json_object(
            contract.evaluation_artifact_path, label="evaluation_artifact"
        )
        terminal = read_json_object(
            contract.terminal_artifact_path, label="terminal_artifact"
        )
    except PublicTribeChainError as exc:
        raise TribeExecutionEvidenceError(str(exc)) from exc
    expected_attempt = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "attempt",
        "execution_kind": contract.execution_kind,
        "status": "started",
        "artifacts": names,
    }
    expected_state = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "state",
        "execution_kind": contract.execution_kind,
        "status": "completed",
        "artifacts": names,
    }
    expected_terminal = {
        "schema_version": TERMINAL_EVIDENCE_SCHEMA_VERSION,
        "artifact_type": "terminal_evidence",
        "execution_kind": contract.execution_kind,
        "status": "completed",
        "artifacts": names,
        "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
    }
    if attempt != expected_attempt or state != expected_state or terminal != expected_terminal:
        raise TribeExecutionEvidenceError("attempt, state, or terminal evidence differs")
    expected_evaluation = evaluate_recurring_v1(
        reference_matrices=_resolve_feature_maps(contract, feature_map_provider)[0],
        evaluation_matrices=_resolve_feature_maps(contract, feature_map_provider)[1],
        reference_rows=contract.reference_rows,
        evaluation_rows=contract.evaluation_rows,
    )
    expected_artifact = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "evaluation",
        "execution_kind": contract.execution_kind,
        "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
        "scientific_evidence": (
            "synthetic_fixture_only"
            if contract.execution_kind == "synthetic_fixture"
            else "public_evaluator_result_only"
        ),
        "evaluation": expected_evaluation,
    }
    if artifact != expected_artifact:
        raise TribeExecutionEvidenceError(
            "evaluation artifact is not an exact deterministic evaluator replay"
        )
    return {
        "schema_version": TERMINAL_EVIDENCE_SCHEMA_VERSION,
        "status": "verified",
        "execution_kind": contract.execution_kind,
        "evaluation_status": expected_evaluation["evaluation_status"],
        "outcome": expected_evaluation["outcome"],
    }


def execute_frozen_bundle_v1(
    *,
    bundle_dir: str,
    evaluation_features_path: str,
    evaluation_artifact_path: str,
    state_artifact_path: str,
    terminal_artifact_path: str,
    attempt_artifact_path: str,
) -> dict[str, Any]:
    """Execute the complete public v1 bundle-loader path with explicit outputs."""

    names = {
        "attempt": artifact_name(attempt_artifact_path, label="attempt_artifact"),
        "state": artifact_name(state_artifact_path, label="state_artifact"),
        "evaluation": artifact_name(
            evaluation_artifact_path, label="evaluation_artifact"
        ),
        "terminal": artifact_name(terminal_artifact_path, label="terminal_artifact"),
    }
    if len(set(names.values())) != len(names):
        raise TribeExecutionEvidenceError("all output artifact paths must be distinct")
    attempt = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "attempt",
        "execution_kind": "controlled_feature_replay",
        "status": "started",
        "artifacts": names,
    }
    state = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "state",
        "execution_kind": "controlled_feature_replay",
        "status": "running",
        "artifacts": names,
    }
    write_json_new(attempt_artifact_path, attempt, label="attempt_artifact")
    write_json_new(state_artifact_path, state, label="state_artifact")
    try:
        result = evaluate_frozen_validation(
            bundle_dir=bundle_dir,
            evaluation_features_path=evaluation_features_path,
        )
        write_evaluation_result(evaluation_artifact_path, result)
        completed = dict(state)
        completed["status"] = "completed"
        replace_json(state_artifact_path, completed, label="state_artifact")
        terminal = {
            "schema_version": TERMINAL_EVIDENCE_SCHEMA_VERSION,
            "artifact_type": "terminal_evidence",
            "execution_kind": "controlled_feature_replay",
            "status": "completed",
            "artifacts": names,
            "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
        }
        write_json_new(terminal_artifact_path, terminal, label="terminal_artifact")
        return result
    except Exception:
        failed = dict(state)
        failed["status"] = "failed"
        replace_json(state_artifact_path, failed, label="state_artifact")
        raise


def read_frozen_bundle_terminal_execution_evidence(
    *,
    bundle_dir: str,
    evaluation_features_path: str,
    evaluation_artifact_path: str,
    state_artifact_path: str,
    terminal_artifact_path: str,
    attempt_artifact_path: str,
) -> dict[str, Any]:
    """Validate full v1 bundle artifacts and deterministic evaluator replay."""

    names = {
        "attempt": artifact_name(attempt_artifact_path, label="attempt_artifact"),
        "state": artifact_name(state_artifact_path, label="state_artifact"),
        "evaluation": artifact_name(
            evaluation_artifact_path, label="evaluation_artifact"
        ),
        "terminal": artifact_name(terminal_artifact_path, label="terminal_artifact"),
    }
    if len(set(names.values())) != len(names):
        raise TribeExecutionEvidenceError("all output artifact paths must be distinct")
    try:
        attempt = read_json_object(attempt_artifact_path, label="attempt_artifact")
        state = read_json_object(state_artifact_path, label="state_artifact")
        terminal = read_json_object(terminal_artifact_path, label="terminal_artifact")
    except PublicTribeChainError as exc:
        raise TribeExecutionEvidenceError(str(exc)) from exc
    expected_attempt = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "attempt",
        "execution_kind": "controlled_feature_replay",
        "status": "started",
        "artifacts": names,
    }
    expected_state = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "artifact_type": "state",
        "execution_kind": "controlled_feature_replay",
        "status": "completed",
        "artifacts": names,
    }
    expected_terminal = {
        "schema_version": TERMINAL_EVIDENCE_SCHEMA_VERSION,
        "artifact_type": "terminal_evidence",
        "execution_kind": "controlled_feature_replay",
        "status": "completed",
        "artifacts": names,
        "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
    }
    if attempt != expected_attempt or state != expected_state or terminal != expected_terminal:
        raise TribeExecutionEvidenceError("attempt, state, or terminal evidence differs")
    result = read_evaluation_result(
        evaluation_artifact_path,
        bundle_dir=bundle_dir,
        evaluation_features_path=evaluation_features_path,
    )
    return {
        "schema_version": TERMINAL_EVIDENCE_SCHEMA_VERSION,
        "status": "verified",
        "execution_kind": "controlled_feature_replay",
        "evaluation_status": result["evaluation_status"],
        "outcome": result["outcome"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or verify the public TRIBE recurring-v1 evaluator."
    )
    parser.add_argument("action", choices=("evaluate", "verify"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reference-matrix-map", required=True)
    parser.add_argument("--evaluation-matrix-map", required=True)
    parser.add_argument("--evaluation-artifact", required=True)
    parser.add_argument("--state-artifact", required=True)
    parser.add_argument("--terminal-artifact", required=True)
    parser.add_argument("--attempt-artifact", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from .execution_contract import load_public_recurring_execution_contract

    contract = load_public_recurring_execution_contract(
        manifest_path=args.manifest,
        reference_matrix_map_path=args.reference_matrix_map,
        evaluation_matrix_map_path=args.evaluation_matrix_map,
        evaluation_artifact_path=args.evaluation_artifact,
        state_artifact_path=args.state_artifact,
        terminal_artifact_path=args.terminal_artifact,
        attempt_artifact_path=args.attempt_artifact,
    )
    result = (
        execute_recurring_v1(contract)
        if args.action == "evaluate"
        else read_recurring_terminal_execution_evidence(contract)
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "FeatureMapProviderV1",
    "TribeExecutionEvidenceError",
    "execute_frozen_bundle_v1",
    "execute_recurring_v1",
    "read_frozen_bundle_terminal_execution_evidence",
    "read_recurring_terminal_execution_evidence",
]
