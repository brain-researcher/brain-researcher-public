"""Public explicit contract for the TRIBE v2 scientific evaluator.

The private module binds a protected materialization and a launch context.
This public counterpart retains the selected-panel, reference, inference, and
feature-matrix boundaries while receiving storage roots, model assets,
commands, seeds, and output locations from caller configuration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_public import (
    PublicTribeChainError,
    read_json_object,
    require_mapping,
    require_text,
)

from .contracts import (
    PROGRAM_ID,
    SourceFeasibilityBindingV2,
    rekey_validator_issued_binding,
    validate_inference_config,
    validate_source_feasibility_contract,
)

MANIFEST_SCHEMA_VERSION = "br.tribe_speech_tools_public.new_source_manifest.v2"
EXECUTION_CONTRACT_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.new_source_execution_contract.v2"
)


class TribeV2ExecutionContractError(ValueError):
    """A public v2 contract fails the frozen evaluator boundary."""


@dataclass(frozen=True, slots=True)
class RuntimeInputsV2:
    mode: str
    data_root: str | None
    model_root: str | None
    checkpoint: str | None
    command: str | None
    seed: int | None


@dataclass(frozen=True, slots=True)
class PublicV2ExecutionContract:
    manifest_path: Path
    reference_matrix_map_path: Path
    evaluation_matrix_map_path: Path
    evaluation_artifact_path: Path
    state_artifact_path: Path
    terminal_artifact_path: Path
    attempt_artifact_path: Path
    execution_kind: str
    runtime: RuntimeInputsV2
    reference_rows: tuple[Mapping[str, Any], ...]
    evaluation_rows: tuple[Mapping[str, Any], ...]
    inference: Mapping[str, Any]
    compute_inference: bool


@dataclass(frozen=True, slots=True)
class ControlledHistoryBindingV2:
    """An in-memory validated binding plus tokens forbidden in public output."""

    binding: SourceFeasibilityBindingV2
    forbidden_output_tokens: tuple[str, ...]


def _sequence(value: Any, *, label: str) -> Sequence[Any]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TribeV2ExecutionContractError(f"{label} must be an array")
    return value


def _path(value: str | Path, *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.parent.is_dir() or candidate.parent.is_symlink():
        raise TribeV2ExecutionContractError(
            f"{label} parent must be an existing non-symlink directory"
        )
    return candidate


def _runtime(value: Any) -> RuntimeInputsV2:
    try:
        payload = require_mapping(value, label="runtime")
    except PublicTribeChainError as exc:
        raise TribeV2ExecutionContractError(str(exc)) from exc
    expected = {"mode", "data_root", "model_root", "checkpoint", "command", "seed"}
    if set(payload) != expected:
        raise TribeV2ExecutionContractError(
            "runtime must explicitly name mode, data_root, model_root, checkpoint, command, and seed"
        )
    mode = payload["mode"]
    if mode not in {"precomputed_feature_matrices", "injected_adapter"}:
        raise TribeV2ExecutionContractError("runtime.mode is unsupported")
    parsed: dict[str, str | int | None] = {"mode": mode}
    for key in ("data_root", "model_root", "checkpoint", "command"):
        raw = payload[key]
        if raw is not None and (not isinstance(raw, str) or not raw.strip()):
            raise TribeV2ExecutionContractError(f"runtime.{key} must be text or null")
        parsed[key] = raw.strip() if isinstance(raw, str) else None
    seed = payload["seed"]
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise TribeV2ExecutionContractError("runtime.seed must be an integer or null")
    parsed["seed"] = seed
    if mode == "precomputed_feature_matrices":
        if any(parsed[key] is not None for key in parsed if key != "mode"):
            raise TribeV2ExecutionContractError(
                "precomputed_feature_matrices requires explicit null runtime values"
            )
    elif any(parsed[key] is None for key in ("data_root", "model_root", "checkpoint", "command", "seed")):
        raise TribeV2ExecutionContractError(
            "injected_adapter requires explicit roots, checkpoint, command, and seed"
        )
    return RuntimeInputsV2(
        mode=str(parsed["mode"]),
        data_root=parsed["data_root"] if isinstance(parsed["data_root"], str) else None,
        model_root=parsed["model_root"] if isinstance(parsed["model_root"], str) else None,
        checkpoint=parsed["checkpoint"] if isinstance(parsed["checkpoint"], str) else None,
        command=parsed["command"] if isinstance(parsed["command"], str) else None,
        seed=parsed["seed"] if isinstance(parsed["seed"], int) else None,
    )


def load_public_v2_execution_contract(
    *,
    manifest_path: str | Path,
    reference_matrix_map_path: str | Path,
    evaluation_matrix_map_path: str | Path,
    evaluation_artifact_path: str | Path,
    state_artifact_path: str | Path,
    terminal_artifact_path: str | Path,
    attempt_artifact_path: str | Path,
) -> PublicV2ExecutionContract:
    """Load only explicit public input configuration; no roots are inferred."""

    try:
        manifest = read_json_object(manifest_path, label="manifest")
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise TribeV2ExecutionContractError("manifest schema_version is invalid")
        if manifest.get("program_id") != PROGRAM_ID:
            raise TribeV2ExecutionContractError("manifest program_id is invalid")
        execution_kind = require_text(
            manifest.get("execution_kind"), label="manifest.execution_kind"
        )
        if execution_kind not in {"synthetic_fixture", "governed_external_input"}:
            raise TribeV2ExecutionContractError("manifest execution_kind is invalid")
        compute_inference = manifest.get("compute_inference")
        if not isinstance(compute_inference, bool):
            raise TribeV2ExecutionContractError("manifest.compute_inference must be boolean")
        reference_rows = tuple(
            require_mapping(row, label="manifest.reference_rows entry")
            for row in _sequence(manifest.get("reference_rows"), label="reference_rows")
        )
        evaluation_rows = tuple(
            require_mapping(row, label="manifest.evaluation_rows entry")
            for row in _sequence(manifest.get("evaluation_rows"), label="evaluation_rows")
        )
        inference = validate_inference_config(
            manifest.get("inference"), execution_kind=execution_kind
        )
        return PublicV2ExecutionContract(
            manifest_path=Path(manifest_path).expanduser(),
            reference_matrix_map_path=Path(reference_matrix_map_path).expanduser(),
            evaluation_matrix_map_path=Path(evaluation_matrix_map_path).expanduser(),
            evaluation_artifact_path=_path(
                evaluation_artifact_path, label="evaluation_artifact"
            ),
            state_artifact_path=_path(state_artifact_path, label="state_artifact"),
            terminal_artifact_path=_path(
                terminal_artifact_path, label="terminal_artifact"
            ),
            attempt_artifact_path=_path(attempt_artifact_path, label="attempt_artifact"),
            execution_kind=execution_kind,
            runtime=_runtime(manifest.get("runtime")),
            reference_rows=reference_rows,
            evaluation_rows=evaluation_rows,
            inference=inference,
            compute_inference=compute_inference,
        )
    except (PublicTribeChainError, TypeError, ValueError) as exc:
        if isinstance(exc, TribeV2ExecutionContractError):
            raise
        raise TribeV2ExecutionContractError(str(exc)) from exc


def _historical_sidecar_payload(path: str | Path) -> dict[str, Any]:
    payload = read_json_object(path, label="historical_exposure_sidecar")
    fields = {"candidate_keys", "source_tokens", "pcm_tokens", "collection_keys"}
    if set(payload) == fields:
        return payload
    sidecars = payload.get("sidecars")
    if (
        isinstance(sidecars, list)
        and len(sidecars) == 1
        and isinstance(sidecars[0], Mapping)
        and set(sidecars[0]) == fields
    ):
        return dict(sidecars[0])
    raise TribeV2ExecutionContractError(
        "historical exposure sidecar must provide the four frozen token sets"
    )


def rebuild_verified_feasibility_binding(
    *,
    source_packet_path: str | Path,
    historical_exposure_sidecar_paths: Sequence[str | Path],
    reference_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
) -> ControlledHistoryBindingV2:
    """Rebuild the validator-issued v2 binding from explicit controlled history.

    The private implementation reads registration-controlled artifacts.  Public
    callers instead inject one source packet and exactly eight sidecars.  The
    returned binding stays in memory, so output artifacts contain no paths or
    row identities beyond the evaluator's caller-selected logical keys.
    """

    if len(historical_exposure_sidecar_paths) != 8:
        raise TribeV2ExecutionContractError(
            "controlled history requires exactly eight historical exposure sidecars"
        )
    packet = read_json_object(source_packet_path, label="source_packet")
    contract = packet.get("contract") if isinstance(packet.get("contract"), Mapping) else packet
    if not isinstance(contract, Mapping):
        raise TribeV2ExecutionContractError("source packet must contain a contract object")
    sidecars = [
        _historical_sidecar_payload(path)
        for path in historical_exposure_sidecar_paths
    ]
    try:
        original = validate_source_feasibility_contract(contract, sidecars)
    except ValueError as exc:
        raise TribeV2ExecutionContractError(
            f"controlled history does not rebuild a valid feasibility binding: {exc}"
        ) from exc
    opaque_binding = rekey_validator_issued_binding(
        original,
        reference_rows=reference_rows,
        evaluation_rows=evaluation_rows,
    )
    tokens: set[str] = set()
    for row in original.frozen_reference.item_rows:
        tokens.add(row.row_key)
    for row in original.evaluation_item_rows:
        tokens.add(row.row_key)
        tokens.add(row.collection_key)
    for candidate in original.intake.candidates:
        tokens.update(
            {
                candidate.candidate_key,
                candidate.source_token,
                candidate.decoded_pcm_identity,
                candidate.parent_key,
                candidate.collection_key,
            }
        )
    for sidecar in sidecars:
        for values in sidecar.values():
            tokens.update(str(value) for value in values)
    return ControlledHistoryBindingV2(
        binding=opaque_binding,
        forbidden_output_tokens=tuple(sorted(token for token in tokens if token)),
    )


__all__ = [
    "EXECUTION_CONTRACT_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "ControlledHistoryBindingV2",
    "PublicV2ExecutionContract",
    "RuntimeInputsV2",
    "TribeV2ExecutionContractError",
    "load_public_v2_execution_contract",
    "rebuild_verified_feasibility_binding",
]
