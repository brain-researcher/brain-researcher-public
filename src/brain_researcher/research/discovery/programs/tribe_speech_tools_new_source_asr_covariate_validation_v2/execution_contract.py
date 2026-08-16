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
    ACOUSTIC_FEATURES,
    FEATURE_DIMENSION,
    FROZEN_CONTRACT_SCHEMA_VERSION,
    FROZEN_HYPOTHESIS_FAMILIES,
    LOCKED_LAYERS,
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
    reference_feature_manifest_path: Path | None
    evaluation_feature_manifest_path: Path | None
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
    reference_feature_manifest_path: str | Path | None = None,
    evaluation_feature_manifest_path: str | Path | None = None,
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
        if execution_kind != "synthetic_fixture" and compute_inference is not True:
            raise TribeV2ExecutionContractError(
                "controlled external input must compute the frozen inferential families"
            )
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
            reference_feature_manifest_path=(
                Path(reference_feature_manifest_path).expanduser()
                if reference_feature_manifest_path is not None
                else None
            ),
            evaluation_feature_manifest_path=(
                Path(evaluation_feature_manifest_path).expanduser()
                if evaluation_feature_manifest_path is not None
                else None
            ),
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


_LEGACY_FEATURE_MANIFEST_SCHEMA_VERSION = "br.autoresearch.tribe_layer_features.v1"
_PRIVATE_ITEM_ID_FIELD = "item" + "_id"
_PRIVATE_COLLECTION_ID_FIELD = "collection" + "_id"
_PRIVATE_PARENT_ID_FIELD = "parent_recording" + "_id"
_PRIVATE_SELECTED_IDS_FIELD = "selected" + "_item_ids"
_LEGACY_HISTORICAL_ITEM_COUNTS = (60, 30, 48, 48, 48, 48, 48, 48)


def _text(value: Any, *, label: str) -> str:
    try:
        return require_text(value, label=label)
    except PublicTribeChainError as exc:
        raise TribeV2ExecutionContractError(str(exc)) from exc


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TribeV2ExecutionContractError(f"{label} must be an object")
    return value


def _regular_file(path: str | Path, *, label: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise TribeV2ExecutionContractError(f"{label} must be a regular file")
    return candidate.resolve()


def _path_from_mapping(
    value: Any,
    *,
    mapping_path: Path,
    label: str,
) -> Path:
    raw = _text(value, label=label)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = mapping_path.parent / candidate
    return _regular_file(candidate, label=label)


def _public_historical_sidecar_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    fields = {"candidate_keys", "source_tokens", "pcm_tokens", "collection_keys"}
    if set(payload) == fields:
        return dict(payload)
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


def _legacy_historical_sidecars(
    payloads: Sequence[Mapping[str, Any]],
    *,
    expected_role_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if len(payloads) != len(expected_role_ids):
        raise TribeV2ExecutionContractError(
            "controlled history has the wrong number of legacy sidecars"
        )
    by_role: dict[str, Mapping[str, Any]] = {}
    for payload in payloads:
        role_id = _text(payload.get("role_id"), label="historical role")
        if role_id in by_role:
            raise TribeV2ExecutionContractError(
                "legacy historical sidecars repeat a frozen role"
            )
        by_role[role_id] = payload
    if set(by_role) != set(expected_role_ids):
        raise TribeV2ExecutionContractError(
            "legacy historical sidecars do not cover the source packet roles"
        )
    adapted: list[dict[str, Any]] = []
    for index, (expected_role_id, expected_item_count) in enumerate(
        zip(
            expected_role_ids,
            _LEGACY_HISTORICAL_ITEM_COUNTS,
            strict=True,
        )
    ):
        payload = by_role[expected_role_id]
        item_count = payload.get("expected_item_count")
        if item_count != expected_item_count:
            raise TribeV2ExecutionContractError(
                "legacy historical sidecar has the wrong frozen item count"
            )
        for field in ("schema_version", "identifier", "identifier_field", "status"):
            _text(payload.get(field), label="legacy historical sidecar")
        items = _sequence(payload.get("items"), label="legacy historical items")
        if len(items) != item_count:
            raise TribeV2ExecutionContractError(
                "legacy historical sidecar item count does not match its declaration"
            )
        collection_values = _sequence(
            payload.get("collection_identities"),
            label="legacy historical collection identities",
        )
        collection_keys = [
            _text(value, label=f"legacy historical collection[{index}]")
            for value in collection_values
        ]
        if not collection_keys or len(collection_keys) != len(set(collection_keys)):
            raise TribeV2ExecutionContractError(
                "legacy historical collection identities are invalid"
            )
        candidate_keys: list[str] = []
        source_tokens: list[str] = []
        pcm_tokens: list[str] = []
        for item_index, raw_item in enumerate(items):
            item = _mapping(raw_item, label="legacy historical item")
            candidate_keys.append(
                _text(item.get(_PRIVATE_ITEM_ID_FIELD), label="legacy historical item")
            )
            source_tokens.append(
                _text(item.get("canonical_source_path"), label="legacy historical item")
            )
            pcm_tokens.append(
                _text(item.get("decoded_pcm_identity"), label="legacy historical item")
            )
            item_collection = _text(
                item.get(_PRIVATE_COLLECTION_ID_FIELD),
                label="legacy historical item",
            )
            if item_collection not in collection_keys:
                raise TribeV2ExecutionContractError(
                    "legacy historical item is outside its declared collections"
                )
        if (
            len(candidate_keys) != len(set(candidate_keys))
            or len(source_tokens) != len(set(source_tokens))
            or len(pcm_tokens) != len(set(pcm_tokens))
        ):
            raise TribeV2ExecutionContractError(
                "legacy historical sidecar repeats a protected identity"
            )
        adapted.append(
            {
                "candidate_keys": candidate_keys,
                "source_tokens": source_tokens,
                "pcm_tokens": pcm_tokens,
                "collection_keys": collection_keys,
            }
        )
    return adapted


def _legacy_source_packet_contract(
    packet: Mapping[str, Any],
    *,
    raw_sidecars: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], Mapping[str, Any]]:
    """Adapt the registration-shaped packet only after structural validation.

    Protected names remain in this local adapter long enough to verify the
    private selection and historical-exposure constraints.  The evaluator sees
    only the public contract and opaque rows supplied to the execution manifest.
    """

    if _text(packet.get("program_id"), label="source_packet.program_id") != PROGRAM_ID:
        raise TribeV2ExecutionContractError("legacy source packet program is invalid")
    if packet.get("scope") != "prospective_discovery_validation":
        raise TribeV2ExecutionContractError("legacy source packet scope is invalid")
    for field in (
        "authority_granted",
        "launch_authorized",
        "gpu_authorized",
        "tribe_inference_authorized",
        "manuscript_update_authorized",
        "execution_authorized",
        "confirmation_authorized",
        "registration_authorized",
    ):
        if packet.get(field) is not False:
            raise TribeV2ExecutionContractError(
                "legacy source packet changes a frozen authorization boundary"
            )
    if packet.get("score_blind") is not True:
        raise TribeV2ExecutionContractError("legacy source packet must be score-blind")
    if _mapping(packet.get("asr_covariate"), label="asr_covariate") != {
        "producer": "WhisperX",
        "field": "whisperx_segment_count",
        "cpu_only": True,
        "materialized_before_tribe": True,
    }:
        raise TribeV2ExecutionContractError("legacy source packet changes the ASR covariate")
    families = tuple(
        _text(value, label="legacy hypothesis family")
        for value in _sequence(packet.get("hypothesis_families"), label="hypothesis_families")
    )
    if families != FROZEN_HYPOTHESIS_FAMILIES:
        raise TribeV2ExecutionContractError("legacy hypothesis family order is invalid")
    permutation = _mapping(packet.get("permutation_metadata"), label="permutation_metadata")
    try:
        validate_inference_config(
            {
                "family_tests": permutation.get("family_tests"),
                "multiplicity": permutation.get("multiplicity"),
            },
            execution_kind="governed_external_input",
        )
    except ValueError as exc:
        raise TribeV2ExecutionContractError(
            "legacy source packet changes frozen permutation metadata"
        ) from exc
    roles = tuple(
        _text(value, label="historical exposure role")
        for value in _sequence(
            packet.get("historical_exposure_role_ids"),
            label="historical_exposure_role_ids",
        )
    )
    if len(roles) != 8 or len(set(roles)) != 8:
        raise TribeV2ExecutionContractError("legacy source packet must bind eight roles")
    sidecars = _legacy_historical_sidecars(raw_sidecars, expected_role_ids=roles)

    reference = _mapping(packet.get("frozen_reference"), label="frozen_reference")
    reference_rows = _sequence(reference.get("item_rows"), label="frozen_reference.item_rows")
    public_reference_rows = [
        {
            "row_key": _text(
                _mapping(row, label="frozen_reference row").get(_PRIVATE_ITEM_ID_FIELD),
                label="frozen_reference row",
            ),
            "condition": _text(
                _mapping(row, label="frozen_reference row").get("condition"),
                label="frozen_reference row",
            ),
        }
        for row in reference_rows
    ]
    source_collections = _sequence(
        packet.get("source_collections"), label="source_collections"
    )
    public_collections = [
        _text(
            _mapping(row, label="source collection").get(_PRIVATE_COLLECTION_ID_FIELD),
            label="source collection",
        )
        for row in source_collections
    ]
    if len(public_collections) != 4 or len(public_collections) != len(set(public_collections)):
        raise TribeV2ExecutionContractError("legacy source packet has invalid collections")
    raw_candidates = _sequence(packet.get("candidate_pool"), label="candidate_pool")
    public_candidates: list[dict[str, Any]] = []
    for raw_candidate in raw_candidates:
        candidate = _mapping(raw_candidate, label="candidate_pool entry")
        raw_qc = _sequence(candidate.get("auditory_qc"), label="candidate auditory_qc")
        public_qc = []
        for raw_review in raw_qc:
            review = _mapping(raw_review, label="candidate auditory_qc review")
            public_qc.append(
                {
                    "reviewer_key": _text(
                        review.get("reviewer_id"), label="candidate auditory_qc review"
                    ),
                    "target_present": review.get("target_present"),
                    "opposite_condition_absent": review.get("opposite_condition_absent"),
                    "dominant_condition": review.get("dominant_condition"),
                    "blinded_to_proposed_condition": review.get(
                        "blinded_to_proposed_condition"
                    ),
                    "blinded_to_source": review.get("blinded_to_source"),
                    "blinded_to_acoustic": review.get("blinded_to_acoustic"),
                    "blinded_to_asr": review.get("blinded_to_asr"),
                    "blinded_to_tribe": review.get("blinded_to_tribe"),
                }
            )
        acoustic = _mapping(candidate.get("acoustic_features"), label="acoustic_features")
        if set(acoustic) != set(ACOUSTIC_FEATURES):
            raise TribeV2ExecutionContractError(
                "legacy candidate acoustic summaries are incomplete"
            )
        public_candidates.append(
            {
                "candidate_key": _text(
                    candidate.get(_PRIVATE_ITEM_ID_FIELD), label="candidate item"
                ),
                "source_token": _text(
                    candidate.get("canonical_source_path"), label="candidate source"
                ),
                "decoded_pcm_identity": _text(
                    candidate.get("decoded_pcm_identity"), label="candidate PCM"
                ),
                "parent_key": _text(
                    candidate.get(_PRIVATE_PARENT_ID_FIELD), label="candidate parent"
                ),
                "collection_key": _text(
                    candidate.get(_PRIVATE_COLLECTION_ID_FIELD), label="candidate collection"
                ),
                "condition": candidate.get("condition"),
                "whisperx_segment_count": candidate.get("whisperx_segment_count"),
                "acoustic_features": {
                    feature: acoustic[feature] for feature in ACOUSTIC_FEATURES
                },
                "score_blind": candidate.get("score_blind"),
                "tribe_inference_run": candidate.get("tribe_inference_run"),
                "auditory_qc": public_qc,
            }
        )
    selection = _mapping(packet.get("selection"), label="selection")
    public_selection = {
        "method_id": selection.get("method_id"),
        "score_blind": selection.get("score_blind"),
        "uses_tribe_features": selection.get("uses_tribe_features"),
        "uses_frozen_axis_geometry": selection.get("uses_frozen_axis_geometry"),
        "uses_hypothesis_outcomes": selection.get("uses_hypothesis_outcomes"),
        "max_absolute_standardized_mean_difference": selection.get(
            "max_absolute_standardized_mean_difference"
        ),
        "selected_candidate_keys": list(
            _sequence(
                selection.get(_PRIVATE_SELECTED_IDS_FIELD),
                label="selection.selected items",
            )
        ),
    }
    return (
        {
            "schema_version": FROZEN_CONTRACT_SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
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
                "reference_label": "controlled_reference",
                "item_rows": public_reference_rows,
                "locked_layer_ids": reference.get("locked_layer_ids"),
                "feature_dimensions": reference.get("feature_dimensions"),
            },
            "source_collections": public_collections,
            "candidate_pool": public_candidates,
            "selection": public_selection,
        },
        sidecars,
        reference,
    )


def _legacy_feature_manifest_paths(
    path: str | Path,
    *,
    expected_rows: Sequence[tuple[str, str]],
    expected_reference: Mapping[str, Any],
    label: str,
) -> tuple[dict[str, Path], Mapping[str, Any]]:
    manifest_path = _regular_file(path, label=label)
    payload = read_json_object(manifest_path, label=label)
    if payload.get("schema_version") != _LEGACY_FEATURE_MANIFEST_SCHEMA_VERSION:
        raise TribeV2ExecutionContractError("controlled feature manifest schema is invalid")
    for field in ("runtime_fix_id", "checkpoint_dir", "checkpoint_name"):
        if payload.get(field) != expected_reference.get(field):
            raise TribeV2ExecutionContractError(
                "controlled feature manifest does not match frozen reference metadata"
            )
    if payload.get("feature_ids_requested") != list(LOCKED_LAYERS):
        raise TribeV2ExecutionContractError("controlled feature manifest changes locked layers")
    for field, expected in {
        "n_manifest_items": len(expected_rows),
        "n_selected_items": len(expected_rows),
        "n_success_items": len(expected_rows),
        "n_failed_items": 0,
    }.items():
        if payload.get(field) != expected:
            raise TribeV2ExecutionContractError("controlled feature manifest row count is invalid")
    raw_rows = _sequence(payload.get("rows"), label="controlled feature rows")
    rows_by_index: dict[int, tuple[str, str]] = {}
    for raw_row in raw_rows:
        row = _mapping(raw_row, label="controlled feature row")
        row_index = row.get("item_row_index")
        if isinstance(row_index, bool) or not isinstance(row_index, int):
            raise TribeV2ExecutionContractError("controlled feature row index is invalid")
        if row_index in rows_by_index or row.get("status") != "success":
            raise TribeV2ExecutionContractError("controlled feature rows are invalid")
        rows_by_index[row_index] = (
            _text(row.get(_PRIVATE_ITEM_ID_FIELD), label="controlled feature row"),
            _text(row.get("condition"), label="controlled feature row"),
        )
    if tuple(rows_by_index.get(index) for index in range(len(expected_rows))) != tuple(
        expected_rows
    ):
        raise TribeV2ExecutionContractError(
            "controlled feature manifest rows do not match the validator binding"
        )
    layers: dict[str, Mapping[str, Any]] = {}
    for raw_layer in _sequence(payload.get("layers"), label="controlled feature layers"):
        layer = _mapping(raw_layer, label="controlled feature layer")
        layer_id = layer.get("layer_id") or layer.get("feature_id")
        if not isinstance(layer_id, str) or layer_id in layers:
            raise TribeV2ExecutionContractError("controlled feature layers are invalid")
        layers[layer_id] = layer
    if set(layers) != set(LOCKED_LAYERS):
        raise TribeV2ExecutionContractError("controlled feature layers do not match lock")
    paths: dict[str, Path] = {}
    for layer_id in LOCKED_LAYERS:
        layer = layers[layer_id]
        if layer.get("shape") != [len(expected_rows), FEATURE_DIMENSION] or layer.get(
            "item_row_indices"
        ) != list(range(len(expected_rows))):
            raise TribeV2ExecutionContractError(
                "controlled feature layer does not retain canonical row order"
            )
        paths[layer_id] = _path_from_mapping(
            layer.get("matrix_path") or layer.get("path"),
            mapping_path=manifest_path,
            label="controlled feature matrix",
        )
    overrides = _mapping(payload.get("model_overrides"), label="model_overrides")
    return paths, overrides


def _matrix_map_paths(path: str | Path, *, label: str) -> dict[str, Path]:
    mapping_path = _regular_file(path, label=label)
    payload = read_json_object(mapping_path, label=label)
    if set(payload) != set(LOCKED_LAYERS):
        raise TribeV2ExecutionContractError(
            "controlled matrix map must bind exactly the six locked layers"
        )
    return {
        layer_id: _path_from_mapping(
            payload[layer_id], mapping_path=mapping_path, label="controlled matrix map"
        )
        for layer_id in LOCKED_LAYERS
    }


def _bind_controlled_feature_manifests(
    *,
    original: SourceFeasibilityBindingV2,
    expected_reference: Mapping[str, Any],
    reference_feature_manifest_path: str | Path,
    evaluation_feature_manifest_path: str | Path,
    reference_matrix_map_path: str | Path,
    evaluation_matrix_map_path: str | Path,
) -> None:
    reference_paths, reference_overrides = _legacy_feature_manifest_paths(
        reference_feature_manifest_path,
        expected_rows=tuple(
            (row.row_key, row.condition) for row in original.frozen_reference.item_rows
        ),
        expected_reference=expected_reference,
        label="reference_feature_manifest",
    )
    evaluation_paths, evaluation_overrides = _legacy_feature_manifest_paths(
        evaluation_feature_manifest_path,
        expected_rows=tuple(
            (row.row_key, row.condition) for row in original.evaluation_item_rows
        ),
        expected_reference=expected_reference,
        label="evaluation_feature_manifest",
    )
    if reference_overrides != evaluation_overrides:
        raise TribeV2ExecutionContractError(
            "controlled reference and evaluation feature manifests use different models"
        )
    if _matrix_map_paths(reference_matrix_map_path, label="reference_matrix_map") != reference_paths:
        raise TribeV2ExecutionContractError(
            "reference matrix map does not bind the canonical feature manifest"
        )
    if _matrix_map_paths(evaluation_matrix_map_path, label="evaluation_matrix_map") != evaluation_paths:
        raise TribeV2ExecutionContractError(
            "evaluation matrix map does not bind the canonical feature manifest"
        )


def rebuild_verified_feasibility_binding(
    *,
    source_packet_path: str | Path,
    historical_exposure_sidecar_paths: Sequence[str | Path],
    reference_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
    reference_feature_manifest_path: str | Path | None = None,
    evaluation_feature_manifest_path: str | Path | None = None,
    reference_matrix_map_path: str | Path | None = None,
    evaluation_matrix_map_path: str | Path | None = None,
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
    raw_sidecars = [
        read_json_object(path, label="historical_exposure_sidecar")
        for path in historical_exposure_sidecar_paths
    ]
    contract = (
        packet.get("contract")
        if isinstance(packet.get("contract"), Mapping)
        else packet
    )
    if not isinstance(contract, Mapping):
        raise TribeV2ExecutionContractError("source packet must contain a contract object")
    legacy_reference: Mapping[str, Any] | None = None
    if contract.get("schema_version") == FROZEN_CONTRACT_SCHEMA_VERSION:
        sidecars = [_public_historical_sidecar_payload(payload) for payload in raw_sidecars]
    else:
        contract, sidecars, legacy_reference = _legacy_source_packet_contract(
            contract,
            raw_sidecars=raw_sidecars,
        )
    try:
        original = validate_source_feasibility_contract(contract, sidecars)
    except ValueError as exc:
        raise TribeV2ExecutionContractError(
            f"controlled history does not rebuild a valid feasibility binding: {exc}"
        ) from exc
    feature_inputs = (
        reference_feature_manifest_path,
        evaluation_feature_manifest_path,
        reference_matrix_map_path,
        evaluation_matrix_map_path,
    )
    if any(path is not None for path in feature_inputs):
        if any(path is None for path in feature_inputs) or legacy_reference is None:
            raise TribeV2ExecutionContractError(
                "controlled feature binding requires both feature manifests and both matrix maps"
            )
        _bind_controlled_feature_manifests(
            original=original,
            expected_reference=legacy_reference,
            reference_feature_manifest_path=reference_feature_manifest_path,
            evaluation_feature_manifest_path=evaluation_feature_manifest_path,
            reference_matrix_map_path=reference_matrix_map_path,
            evaluation_matrix_map_path=evaluation_matrix_map_path,
        )
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
            if isinstance(values, Sequence) and not isinstance(values, str | bytes):
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
