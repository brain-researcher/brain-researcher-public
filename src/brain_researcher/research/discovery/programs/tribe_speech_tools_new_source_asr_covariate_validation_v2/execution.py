"""Public v2 evaluator execution and terminal evidence replay.

This module preserves the private terminal decision shape while replacing the
registration and protected storage boundary with caller-supplied contracts and
optional injected feature or feasibility adapters.  The command configured in
a manifest is descriptive only; this public CLI never starts it.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    PublicTribeChainError,
    artifact_name,
    load_matrix_map,
    read_json_object,
    replace_json,
    write_json_new,
)

from .contracts import FrozenReferenceBindingV2, SourceFeasibilityBindingV2
from .evaluator import EVALUATION_SCHEMA_VERSION, evaluate_frozen_hypothesis_families
from .execution_contract import PublicV2ExecutionContract

RUNTIME_STATE_SCHEMA_VERSION = "br.tribe_speech_tools_public.new_source_runtime_state.v2"
ATTEMPT_CONSUMPTION_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.new_source_attempt_consumption.v1"
)
TERMINAL_BUNDLE_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.new_source_terminal_bundle.v2"
)

FeatureMapProviderV2 = Callable[
    [PublicV2ExecutionContract],
    tuple[Mapping[str, Any], Mapping[str, Any]],
]


class TribeV2ExecutionError(RuntimeError):
    """A public v2 execution cannot establish terminal evaluator evidence."""


_OPAQUE_ROW_KEY = re.compile(r"^row-[0-9]{4}$")
_OPAQUE_COLLECTION_KEY = re.compile(r"^collection-[0-9]{2}$")
_ABSOLUTE_PATH_FRAGMENT = re.compile(r"(?:^|[\s:=])(?:/|[A-Za-z]:[\\/]|\\\\)")


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [
            item
            for nested in value.values()
            for item in _string_values(nested)
        ]
    if isinstance(value, list | tuple):
        return [item for nested in value for item in _string_values(nested)]
    return []


def _assert_public_evaluation_is_opaque(
    evaluation: Mapping[str, Any],
    *,
    forbidden_output_tokens: Sequence[str],
) -> None:
    """Reject a controlled-history artifact that re-emits protected input keys."""

    values = _string_values(evaluation)
    if any(_ABSOLUTE_PATH_FRAGMENT.search(value) is not None for value in values):
        raise TribeV2ExecutionError("public evaluation contains an absolute path")
    forbidden = tuple(token for token in forbidden_output_tokens if token)
    if any(token in value for token in forbidden for value in values):
        raise TribeV2ExecutionError(
            "public evaluation re-emits a controlled-history token"
        )
    for record in evaluation.get("per_item_pairwise_concordance", []):
        if not isinstance(record, Mapping):
            raise TribeV2ExecutionError("per-item evaluator output is malformed")
        row_key = record.get("row_key")
        collection_key = record.get("collection_key")
        if (
            not isinstance(row_key, str)
            or _OPAQUE_ROW_KEY.fullmatch(row_key) is None
            or not isinstance(collection_key, str)
            or _OPAQUE_COLLECTION_KEY.fullmatch(collection_key) is None
        ):
            raise TribeV2ExecutionError(
                "controlled-history evaluator output must use opaque row and collection keys"
            )


def _artifact_names(contract: PublicV2ExecutionContract) -> dict[str, str]:
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
        raise TribeV2ExecutionError("all output artifact paths must be distinct")
    return names


def _resolve_feature_maps(
    contract: PublicV2ExecutionContract,
    feature_map_provider: FeatureMapProviderV2 | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if feature_map_provider is not None:
        value = feature_map_provider(contract)
        if not isinstance(value, tuple) or len(value) != 2:
            raise TribeV2ExecutionError(
                "feature_map_provider must return reference and evaluation mappings"
            )
        return value
    if contract.runtime.mode != "precomputed_feature_matrices":
        raise TribeV2ExecutionError(
            "injected_adapter runtime requires a caller-provided feature_map_provider"
        )
    return (
        load_matrix_map(contract.reference_matrix_map_path, label="reference_matrix_map"),
        load_matrix_map(
            contract.evaluation_matrix_map_path, label="evaluation_matrix_map"
        ),
    )


def _evaluate(
    contract: PublicV2ExecutionContract,
    *,
    feature_map_provider: FeatureMapProviderV2 | None,
    feasibility_binding: SourceFeasibilityBindingV2 | None,
    reference_binding: FrozenReferenceBindingV2 | None,
) -> dict[str, Any]:
    reference_matrices, evaluation_matrices = _resolve_feature_maps(
        contract, feature_map_provider
    )
    return evaluate_frozen_hypothesis_families(
        reference_matrices=reference_matrices,
        evaluation_matrices=evaluation_matrices,
        item_rows={
            "reference": contract.reference_rows,
            "evaluation": contract.evaluation_rows,
        },
        inference=contract.inference,
        execution_kind=contract.execution_kind,
        compute_inference=contract.compute_inference,
        feasibility_binding=feasibility_binding,
        reference_binding=reference_binding,
    )


def execute_public_v2_evaluation(
    contract: PublicV2ExecutionContract,
    *,
    feature_map_provider: FeatureMapProviderV2 | None = None,
    feasibility_binding: SourceFeasibilityBindingV2 | None = None,
    reference_binding: FrozenReferenceBindingV2 | None = None,
    forbidden_output_tokens: Sequence[str] = (),
) -> dict[str, Any]:
    """Consume one explicit attempt and persist an exact v2 evaluator artifact."""

    names = _artifact_names(contract)
    attempt = {
        "schema_version": ATTEMPT_CONSUMPTION_SCHEMA_VERSION,
        "artifact_type": "attempt_consumption",
        "execution_kind": contract.execution_kind,
        "attempt_consumed": True,
        "status": "started",
        "artifacts": names,
    }
    state = {
        "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
        "artifact_type": "runtime_state",
        "execution_kind": contract.execution_kind,
        "status": "running",
        "artifacts": names,
    }
    write_json_new(contract.attempt_artifact_path, attempt, label="attempt_artifact")
    write_json_new(contract.state_artifact_path, state, label="state_artifact")
    try:
        evaluation = _evaluate(
            contract,
            feature_map_provider=feature_map_provider,
            feasibility_binding=feasibility_binding,
            reference_binding=reference_binding,
        )
        if feasibility_binding is not None:
            _assert_public_evaluation_is_opaque(
                evaluation,
                forbidden_output_tokens=forbidden_output_tokens,
            )
        artifact = {
            "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
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
            "schema_version": TERMINAL_BUNDLE_SCHEMA_VERSION,
            "artifact_type": "terminal_execution_evidence",
            "execution_kind": contract.execution_kind,
            "status": "completed",
            "artifacts": names,
            "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
            "attempt_consumed": True,
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


def read_tribe_v2_terminal_execution_evidence(
    contract: PublicV2ExecutionContract,
    *,
    feature_map_provider: FeatureMapProviderV2 | None = None,
    feasibility_binding: SourceFeasibilityBindingV2 | None = None,
    reference_binding: FrozenReferenceBindingV2 | None = None,
    forbidden_output_tokens: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate attempt, state, terminal bundle, and a fresh evaluator replay."""

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
        raise TribeV2ExecutionError(str(exc)) from exc
    expected_attempt = {
        "schema_version": ATTEMPT_CONSUMPTION_SCHEMA_VERSION,
        "artifact_type": "attempt_consumption",
        "execution_kind": contract.execution_kind,
        "attempt_consumed": True,
        "status": "started",
        "artifacts": names,
    }
    expected_state = {
        "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
        "artifact_type": "runtime_state",
        "execution_kind": contract.execution_kind,
        "status": "completed",
        "artifacts": names,
    }
    expected_terminal = {
        "schema_version": TERMINAL_BUNDLE_SCHEMA_VERSION,
        "artifact_type": "terminal_execution_evidence",
        "execution_kind": contract.execution_kind,
        "status": "completed",
        "artifacts": names,
        "evaluator_schema_version": EVALUATION_SCHEMA_VERSION,
        "attempt_consumed": True,
    }
    if attempt != expected_attempt or state != expected_state or terminal != expected_terminal:
        raise TribeV2ExecutionError("attempt, state, or terminal evidence differs")
    evaluation = _evaluate(
        contract,
        feature_map_provider=feature_map_provider,
        feasibility_binding=feasibility_binding,
        reference_binding=reference_binding,
    )
    if feasibility_binding is not None:
        _assert_public_evaluation_is_opaque(
            evaluation,
            forbidden_output_tokens=forbidden_output_tokens,
        )
    if evaluation.get("outcome") not in {
        "bounded_support",
        "inconclusive_or_conflicting",
    }:
        raise TribeV2ExecutionError("terminal evaluator outcome is invalid")
    expected_artifact = {
        "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
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
    if artifact != expected_artifact:
        raise TribeV2ExecutionError(
            "evaluation artifact is not an exact deterministic evaluator replay"
        )
    return {
        "schema_version": TERMINAL_BUNDLE_SCHEMA_VERSION,
        "status": "verified",
        "execution_kind": contract.execution_kind,
        "evaluation_status": evaluation["evaluation_status"],
        "outcome": evaluation["outcome"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or verify the public TRIBE v2 evaluator from feature matrices."
    )
    parser.add_argument(
        "action",
        choices=("evaluate", "verify", "verify-controlled-history"),
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reference-matrix-map", required=True)
    parser.add_argument("--evaluation-matrix-map", required=True)
    parser.add_argument("--reference-feature-manifest")
    parser.add_argument("--evaluation-feature-manifest")
    parser.add_argument("--evaluation-artifact", required=True)
    parser.add_argument("--state-artifact", required=True)
    parser.add_argument("--terminal-artifact", required=True)
    parser.add_argument("--attempt-artifact", required=True)
    parser.add_argument("--source-packet")
    parser.add_argument(
        "--historical-exposure-sidecar",
        action="append",
        default=[],
        dest="historical_exposure_sidecars",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from .execution_contract import (
        load_public_v2_execution_contract,
        rebuild_verified_feasibility_binding,
    )

    contract = load_public_v2_execution_contract(
        manifest_path=args.manifest,
        reference_matrix_map_path=args.reference_matrix_map,
        evaluation_matrix_map_path=args.evaluation_matrix_map,
        reference_feature_manifest_path=args.reference_feature_manifest,
        evaluation_feature_manifest_path=args.evaluation_feature_manifest,
        evaluation_artifact_path=args.evaluation_artifact,
        state_artifact_path=args.state_artifact,
        terminal_artifact_path=args.terminal_artifact,
        attempt_artifact_path=args.attempt_artifact,
    )
    if contract.runtime.mode != "precomputed_feature_matrices":
        raise TribeV2ExecutionError(
            "CLI accepts precomputed matrices only; supply an adapter through the library API"
        )
    has_controlled_history = bool(args.source_packet) or bool(
        args.historical_exposure_sidecars
    )
    if has_controlled_history and (
        not args.source_packet or len(args.historical_exposure_sidecars) != 8
    ):
        raise TribeV2ExecutionError(
            "controlled history requires --source-packet and exactly eight historical sidecars"
        )
    if has_controlled_history and (
        not args.reference_feature_manifest or not args.evaluation_feature_manifest
    ):
        raise TribeV2ExecutionError(
            "controlled history requires both canonical feature manifests"
        )
    controlled_history = (
        rebuild_verified_feasibility_binding(
            source_packet_path=args.source_packet,
            historical_exposure_sidecar_paths=args.historical_exposure_sidecars,
            reference_rows=contract.reference_rows,
            evaluation_rows=contract.evaluation_rows,
            reference_feature_manifest_path=contract.reference_feature_manifest_path,
            evaluation_feature_manifest_path=contract.evaluation_feature_manifest_path,
            reference_matrix_map_path=contract.reference_matrix_map_path,
            evaluation_matrix_map_path=contract.evaluation_matrix_map_path,
        )
        if has_controlled_history
        else None
    )
    binding = controlled_history.binding if controlled_history is not None else None
    forbidden_output_tokens = (
        controlled_history.forbidden_output_tokens
        if controlled_history is not None
        else ()
    )
    if contract.execution_kind != "synthetic_fixture" and contract.compute_inference and binding is None:
        raise TribeV2ExecutionError(
            "inferential external input requires a caller-injected feasibility binding"
        )
    if args.action == "verify-controlled-history" and (
        binding is None or not contract.compute_inference
    ):
        raise TribeV2ExecutionError(
            "verify-controlled-history requires controlled history and inferential evaluation"
        )
    result = (
        execute_public_v2_evaluation(
            contract,
            feasibility_binding=binding,
            reference_binding=binding.frozen_reference if binding is not None else None,
            forbidden_output_tokens=forbidden_output_tokens,
        )
        if args.action == "evaluate"
        else read_tribe_v2_terminal_execution_evidence(
            contract,
            feasibility_binding=binding,
            reference_binding=binding.frozen_reference if binding is not None else None,
            forbidden_output_tokens=forbidden_output_tokens,
        )
    )
    if args.action == "verify-controlled-history":
        result["controlled_history_verified"] = True
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "FeatureMapProviderV2",
    "TribeV2ExecutionError",
    "execute_public_v2_evaluation",
    "read_tribe_v2_terminal_execution_evidence",
]
