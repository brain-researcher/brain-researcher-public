"""Explicit public execution contract for the recurring TRIBE v1 evaluator.

This is the public counterpart of the private registration-bound contract.  It
keeps the frozen evaluator inputs, while making every location and runtime
setting a caller-provided value.  It does not resolve a dataset, model, or
checkpoint on behalf of the caller.
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

from .evaluator import PROGRAM_ID

MANIFEST_SCHEMA_VERSION = "br.tribe_speech_tools_public.recurring_manifest.v1"
EXECUTION_CONTRACT_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.recurring_execution_contract.v1"
)


class TribeExecutionFrozenContractError(ValueError):
    """A public recurring-v1 manifest fails the frozen execution boundary."""


@dataclass(frozen=True, slots=True)
class RuntimeInputsV1:
    mode: str
    data_root: str | None
    model_root: str | None
    checkpoint: str | None
    command: str | None
    seed: int | None


@dataclass(frozen=True, slots=True)
class PublicRecurringExecutionContract:
    manifest_path: Path
    reference_matrix_map_path: Path
    evaluation_matrix_map_path: Path
    evaluation_artifact_path: Path
    state_artifact_path: Path
    terminal_artifact_path: Path
    attempt_artifact_path: Path
    execution_kind: str
    runtime: RuntimeInputsV1
    reference_rows: tuple[Mapping[str, Any], ...]
    evaluation_rows: tuple[Mapping[str, Any], ...]


def _sequence(value: Any, *, label: str) -> Sequence[Any]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TribeExecutionFrozenContractError(f"{label} must be an array")
    return value


def _path(value: str | Path, *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.parent.is_dir() or candidate.parent.is_symlink():
        raise TribeExecutionFrozenContractError(
            f"{label} parent must be an existing non-symlink directory"
        )
    return candidate


def _runtime(value: Any) -> RuntimeInputsV1:
    try:
        payload = require_mapping(value, label="runtime")
    except PublicTribeChainError as exc:
        raise TribeExecutionFrozenContractError(str(exc)) from exc
    expected = {"mode", "data_root", "model_root", "checkpoint", "command", "seed"}
    if set(payload) != expected:
        raise TribeExecutionFrozenContractError(
            "runtime must explicitly name mode, data_root, model_root, checkpoint, command, and seed"
        )
    mode = payload["mode"]
    if mode not in {"precomputed_feature_matrices", "injected_adapter"}:
        raise TribeExecutionFrozenContractError("runtime.mode is unsupported")
    optional_text: dict[str, str | None] = {}
    for key in ("data_root", "model_root", "checkpoint", "command"):
        raw = payload[key]
        if raw is not None and (not isinstance(raw, str) or not raw.strip()):
            raise TribeExecutionFrozenContractError(f"runtime.{key} must be text or null")
        optional_text[key] = raw.strip() if isinstance(raw, str) else None
    seed = payload["seed"]
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise TribeExecutionFrozenContractError("runtime.seed must be an integer or null")
    if mode == "precomputed_feature_matrices":
        if any(optional_text.values()) or seed is not None:
            raise TribeExecutionFrozenContractError(
                "precomputed_feature_matrices must explicitly set runtime locations and seed to null"
            )
    elif any(optional_text[key] is None for key in optional_text) or seed is None:
        raise TribeExecutionFrozenContractError(
            "injected_adapter requires explicit roots, checkpoint, command, and seed"
        )
    return RuntimeInputsV1(mode=mode, seed=seed, **optional_text)


def load_public_recurring_execution_contract(
    *,
    manifest_path: str | Path,
    reference_matrix_map_path: str | Path,
    evaluation_matrix_map_path: str | Path,
    evaluation_artifact_path: str | Path,
    state_artifact_path: str | Path,
    terminal_artifact_path: str | Path,
    attempt_artifact_path: str | Path,
) -> PublicRecurringExecutionContract:
    """Bind public evaluator inputs without deriving a hidden filesystem root."""

    try:
        manifest = read_json_object(manifest_path, label="manifest")
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise TribeExecutionFrozenContractError("manifest schema_version is invalid")
        if manifest.get("program_id") != PROGRAM_ID:
            raise TribeExecutionFrozenContractError("manifest program_id is invalid")
        execution_kind = require_text(
            manifest.get("execution_kind"), label="manifest.execution_kind"
        )
        if execution_kind not in {"synthetic_fixture", "governed_external_input"}:
            raise TribeExecutionFrozenContractError("manifest execution_kind is invalid")
        reference_rows = tuple(
            require_mapping(row, label="manifest.reference_rows entry")
            for row in _sequence(manifest.get("reference_rows"), label="reference_rows")
        )
        evaluation_rows = tuple(
            require_mapping(row, label="manifest.evaluation_rows entry")
            for row in _sequence(manifest.get("evaluation_rows"), label="evaluation_rows")
        )
        return PublicRecurringExecutionContract(
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
        )
    except (PublicTribeChainError, TypeError) as exc:
        raise TribeExecutionFrozenContractError(str(exc)) from exc


__all__ = [
    "EXECUTION_CONTRACT_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "PublicRecurringExecutionContract",
    "RuntimeInputsV1",
    "TribeExecutionFrozenContractError",
    "load_public_recurring_execution_contract",
]
