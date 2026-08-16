"""Public, score-blind contract for the new-source TRIBE v2 evaluator.

The original counts, acoustic summaries, selection objective, locked layers,
permutation seeds, default draw count, and Holm family ordering are retained.
Historical identities, source locations, model assets, and reference-row
identities are supplied by the caller's manifest rather than embedded here.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from brain_researcher.research.discovery.programs.tribe_speech_tools_acoustic_matched_validation_v1.evaluator import (
    EARLY_LAYERS,
    FEATURE_DIMENSION,
    LATE_LAYERS,
    LOCKED_LAYERS,
)

PROGRAM_ID = "tribe_speech_tools_new_source_asr_covariate_validation_v2"
PROGRAM_VERSION = "v1"
FROZEN_CONTRACT_SCHEMA_VERSION = "br.tribe_speech_tools_public.new_source_contract.v2"
SOURCE_FEASIBILITY_PACKET_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.source_feasibility.v2"
)
CANDIDATE_POOL_INTAKE_SCHEMA_VERSION = (
    "br.tribe_speech_tools_public.candidate_pool_intake.v2"
)

CONDITIONS = ("speech", "tools")
SOURCE_COLLECTION_COUNT = 4
ITEMS_PER_CONDITION_COLLECTION = 6
SELECTED_ITEM_COUNT = (
    SOURCE_COLLECTION_COUNT * len(CONDITIONS) * ITEMS_PER_CONDITION_COLLECTION
)
MIN_POOL_ITEMS_PER_CONDITION_COLLECTION = 12
MIN_CANDIDATE_POOL_ITEMS = (
    SOURCE_COLLECTION_COUNT * len(CONDITIONS) * MIN_POOL_ITEMS_PER_CONDITION_COLLECTION
)
MAX_ACOUSTIC_BALANCE_DIFFERENCE = 0.5
ACOUSTIC_FEATURES = (
    "log_duration",
    "rms",
    "zero_crossing_rate",
    "spectral_centroid",
    "spectral_bandwidth",
    "spectral_rolloff_85",
    "spectral_flatness",
)
SELECTION_METHOD_ID = "score_blind_minimax_acoustic_balance_v1"
FROZEN_HYPOTHESIS_FAMILIES = ("H1", "H2", "H3", "H5")
INFERENCE_ALPHA = 0.025

FROZEN_PERMUTATION_METADATA: dict[str, Any] = {
    "family_tests": {
        "H1": {
            "permutation": "balanced_label",
            "draws": 99999,
            "rng_bit_generator": "PCG64",
            "seed": 20260811,
        },
        "H2": {
            "permutation": "balanced_label",
            "draws": 99999,
            "rng_bit_generator": "PCG64",
            "seed": 20260811,
        },
        "H3": {
            "permutation": "within_source_condition_blocked",
            "draws": 99999,
            "rng_bit_generator": "PCG64",
            "seed": 20260812,
        },
        "H5": {
            "permutation": "balanced_label",
            "draws": 99999,
            "rng_bit_generator": "PCG64",
            "seed": 20260811,
        },
    },
    "multiplicity": {
        "method": "Holm",
        "families": ["H1", "H2", "H3", "H5"],
        "alpha": 0.025,
    },
}


class SourceFeasibilityContractError(ValueError):
    """A caller-supplied v2 public contract cannot support the frozen design."""


@dataclass(frozen=True, slots=True)
class ReferenceRowBindingV2:
    row_key: str
    condition: str


@dataclass(frozen=True, slots=True)
class FrozenReferenceBindingV2:
    reference_label: str
    item_rows: tuple[ReferenceRowBindingV2, ...]
    locked_layer_ids: tuple[str, ...]
    feature_dimensions: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CandidatePoolItemBindingV2:
    candidate_key: str
    source_token: str
    decoded_pcm_identity: str
    parent_key: str
    collection_key: str
    condition: str
    whisperx_segment_count: int
    acoustic_features: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class CandidatePoolIntakeBindingV2:
    schema_version: str
    program_id: str
    status: str
    source_collection_keys: tuple[str, ...]
    candidate_pool_count: int
    candidate_counts_by_collection_condition: tuple[tuple[str, str, int], ...]
    candidates: tuple[CandidatePoolItemBindingV2, ...]


@dataclass(frozen=True, slots=True)
class EvaluationItemRowBindingV2:
    row_key: str
    collection_key: str
    condition: str
    whisperx_segment_count: int


@dataclass(frozen=True, slots=True)
class AcousticBalanceBindingV2:
    scope: str
    feature: str
    standardized_mean_difference: float


_VALIDATED_BINDING_MARKER = object()
_OPAQUE_ROW_KEY = re.compile(r"^row-[0-9]{4}$")
_OPAQUE_COLLECTION_KEY = re.compile(r"^collection-[0-9]{2}$")


@dataclass(frozen=True, slots=True)
class SourceFeasibilityBindingV2:
    schema_version: str
    program_id: str
    status: str
    intake: CandidatePoolIntakeBindingV2
    frozen_reference: FrozenReferenceBindingV2
    selection_method_id: str
    evaluation_item_rows: tuple[EvaluationItemRowBindingV2, ...]
    acoustic_balance: tuple[AcousticBalanceBindingV2, ...]
    max_acoustic_balance_difference: float
    authority_granted: bool
    launch_authorized: bool
    gpu_authorized: bool
    tribe_inference_authorized: bool
    manuscript_update_authorized: bool
    execution_authorized: bool
    confirmation_authorized: bool
    registration_authorized: bool
    _validator_marker: object = field(repr=False, compare=False)


def is_validator_issued_binding(value: object) -> bool:
    return (
        isinstance(value, SourceFeasibilityBindingV2)
        and value._validator_marker is _VALIDATED_BINDING_MARKER
        and value.schema_version == SOURCE_FEASIBILITY_PACKET_SCHEMA_VERSION
        and value.program_id == PROGRAM_ID
        and value.status == "selected_panel_feasibility_bound"
        and value.authority_granted is False
        and value.launch_authorized is False
        and value.gpu_authorized is False
        and value.tribe_inference_authorized is False
        and value.manuscript_update_authorized is False
        and value.execution_authorized is False
        and value.confirmation_authorized is False
        and value.registration_authorized is False
    )


def rekey_validator_issued_binding(
    binding: SourceFeasibilityBindingV2,
    *,
    reference_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
) -> SourceFeasibilityBindingV2:
    """Replace protected row and collection keys after exact private validation.

    This changes labels only.  It retains condition, segment count, selected
    panel membership, acoustic balance, frozen layers, and every authorization
    flag from the validator-issued binding.  The caller-supplied replacement
    keys must be deterministic opaque values, so evaluator artifacts cannot
    re-emit source-packet identifiers.
    """

    if not is_validator_issued_binding(binding):
        raise SourceFeasibilityContractError(
            "only a validator-issued binding may be rekeyed"
        )
    if len(reference_rows) != len(binding.frozen_reference.item_rows):
        raise SourceFeasibilityContractError(
            "opaque reference rows do not match the frozen reference length"
        )
    parsed_reference: list[ReferenceRowBindingV2] = []
    for index, (raw, original) in enumerate(
        zip(reference_rows, binding.frozen_reference.item_rows, strict=True)
    ):
        row = _object(raw, label=f"reference_rows[{index}]")
        row_key = _text(row.get("row_key"), label=f"reference_rows[{index}].row_key")
        if _OPAQUE_ROW_KEY.fullmatch(row_key) is None:
            raise SourceFeasibilityContractError(
                "controlled reference row keys must be opaque row-#### values"
            )
        if row.get("condition") != original.condition:
            raise SourceFeasibilityContractError(
                "controlled reference conditions must equal the validated binding"
            )
        parsed_reference.append(
            ReferenceRowBindingV2(row_key=row_key, condition=original.condition)
        )
    if len({row.row_key for row in parsed_reference}) != len(parsed_reference):
        raise SourceFeasibilityContractError("controlled reference rows repeat an opaque key")
    if len(evaluation_rows) != len(binding.evaluation_item_rows):
        raise SourceFeasibilityContractError(
            "opaque evaluation rows do not match the selected-panel length"
        )
    collection_map: dict[str, str] = {}
    reverse_collection_map: dict[str, str] = {}
    parsed_evaluation: list[EvaluationItemRowBindingV2] = []
    for index, (raw, original) in enumerate(
        zip(evaluation_rows, binding.evaluation_item_rows, strict=True)
    ):
        row = _object(raw, label=f"evaluation_rows[{index}]")
        row_key = _text(row.get("row_key"), label=f"evaluation_rows[{index}].row_key")
        expected_row_key = f"row-{index:04d}"
        if row_key != expected_row_key or _OPAQUE_ROW_KEY.fullmatch(row_key) is None:
            raise SourceFeasibilityContractError(
                "controlled evaluation row keys must be ordered opaque row-#### values"
            )
        collection_key = _text(
            row.get("collection_key"),
            label=f"evaluation_rows[{index}].collection_key",
        )
        if _OPAQUE_COLLECTION_KEY.fullmatch(collection_key) is None:
            raise SourceFeasibilityContractError(
                "controlled collection keys must be opaque collection-## values"
            )
        if row.get("condition") != original.condition:
            raise SourceFeasibilityContractError(
                "controlled evaluation conditions must equal the validated binding"
            )
        if row.get("whisperx_segment_count") != original.whisperx_segment_count:
            raise SourceFeasibilityContractError(
                "controlled segment counts must equal the validated binding"
            )
        prior = collection_map.setdefault(original.collection_key, collection_key)
        if prior != collection_key:
            raise SourceFeasibilityContractError(
                "one validated collection cannot map to multiple opaque collections"
            )
        reverse = reverse_collection_map.setdefault(collection_key, original.collection_key)
        if reverse != original.collection_key:
            raise SourceFeasibilityContractError(
                "opaque collections must preserve the four validated groups"
            )
        parsed_evaluation.append(
            EvaluationItemRowBindingV2(
                row_key=row_key,
                collection_key=collection_key,
                condition=original.condition,
                whisperx_segment_count=original.whisperx_segment_count,
            )
        )
    if len(collection_map) != SOURCE_COLLECTION_COUNT:
        raise SourceFeasibilityContractError(
            "controlled evaluation rows must retain exactly four collections"
        )
    remapped_candidates = tuple(
        CandidatePoolItemBindingV2(
            candidate_key=candidate.candidate_key,
            source_token=candidate.source_token,
            decoded_pcm_identity=candidate.decoded_pcm_identity,
            parent_key=candidate.parent_key,
            collection_key=collection_map[candidate.collection_key],
            condition=candidate.condition,
            whisperx_segment_count=candidate.whisperx_segment_count,
            acoustic_features=candidate.acoustic_features,
        )
        for candidate in binding.intake.candidates
    )
    remapped_intake = CandidatePoolIntakeBindingV2(
        schema_version=binding.intake.schema_version,
        program_id=binding.intake.program_id,
        status=binding.intake.status,
        source_collection_keys=tuple(sorted(collection_map.values())),
        candidate_pool_count=binding.intake.candidate_pool_count,
        candidate_counts_by_collection_condition=tuple(
            (collection_map[collection_key], condition, count)
            for collection_key, condition, count in binding.intake.candidate_counts_by_collection_condition
        ),
        candidates=remapped_candidates,
    )
    remapped_balance = tuple(
        AcousticBalanceBindingV2(
            scope=(
                balance.scope
                if balance.scope == "pooled"
                else collection_map[balance.scope]
            ),
            feature=balance.feature,
            standardized_mean_difference=balance.standardized_mean_difference,
        )
        for balance in binding.acoustic_balance
    )
    remapped_reference = FrozenReferenceBindingV2(
        reference_label="opaque_controlled_reference",
        item_rows=tuple(parsed_reference),
        locked_layer_ids=binding.frozen_reference.locked_layer_ids,
        feature_dimensions=binding.frozen_reference.feature_dimensions,
    )
    return SourceFeasibilityBindingV2(
        schema_version=binding.schema_version,
        program_id=binding.program_id,
        status=binding.status,
        intake=remapped_intake,
        frozen_reference=remapped_reference,
        selection_method_id=binding.selection_method_id,
        evaluation_item_rows=tuple(parsed_evaluation),
        acoustic_balance=remapped_balance,
        max_acoustic_balance_difference=binding.max_acoustic_balance_difference,
        authority_granted=binding.authority_granted,
        launch_authorized=binding.launch_authorized,
        gpu_authorized=binding.gpu_authorized,
        tribe_inference_authorized=binding.tribe_inference_authorized,
        manuscript_update_authorized=binding.manuscript_update_authorized,
        execution_authorized=binding.execution_authorized,
        confirmation_authorized=binding.confirmation_authorized,
        registration_authorized=binding.registration_authorized,
        _validator_marker=_VALIDATED_BINDING_MARKER,
    )


def default_inference_config() -> dict[str, Any]:
    return {
        "family_tests": {
            family: dict(spec)
            for family, spec in FROZEN_PERMUTATION_METADATA["family_tests"].items()
        },
        "multiplicity": dict(FROZEN_PERMUTATION_METADATA["multiplicity"]),
    }


def validate_inference_config(
    value: Any, *, execution_kind: str
) -> dict[str, Any]:
    """Require explicit PCG64/seeds and frozen 99,999 draws outside fixtures."""

    payload = _object(value, label="inference")
    if set(payload) != {"family_tests", "multiplicity"}:
        raise SourceFeasibilityContractError(
            "inference must contain family_tests and multiplicity"
        )
    families = _object(payload["family_tests"], label="inference.family_tests")
    if tuple(families) != FROZEN_HYPOTHESIS_FAMILIES:
        raise SourceFeasibilityContractError(
            "inference family order must be H1, H2, H3, H5"
        )
    parsed_families: dict[str, dict[str, Any]] = {}
    for family in FROZEN_HYPOTHESIS_FAMILIES:
        supplied = _object(families[family], label=f"inference.family_tests.{family}")
        expected = FROZEN_PERMUTATION_METADATA["family_tests"][family]
        if set(supplied) != set(expected):
            raise SourceFeasibilityContractError(
                f"inference.family_tests.{family} has unexpected fields"
            )
        if supplied.get("permutation") != expected["permutation"]:
            raise SourceFeasibilityContractError(
                f"inference.family_tests.{family} changes the frozen permutation"
            )
        if supplied.get("rng_bit_generator") != "PCG64":
            raise SourceFeasibilityContractError(
                f"inference.family_tests.{family} must use PCG64"
            )
        if supplied.get("seed") != expected["seed"]:
            raise SourceFeasibilityContractError(
                f"inference.family_tests.{family} changes the frozen seed"
            )
        draws = supplied.get("draws")
        if isinstance(draws, bool) or not isinstance(draws, int) or draws <= 0:
            raise SourceFeasibilityContractError(
                f"inference.family_tests.{family}.draws must be positive"
            )
        if execution_kind != "synthetic_fixture" and draws != expected["draws"]:
            raise SourceFeasibilityContractError(
                "non-fixture evaluation must use the frozen 99,999 draws"
            )
        parsed_families[family] = {
            "permutation": expected["permutation"],
            "draws": draws,
            "rng_bit_generator": "PCG64",
            "seed": expected["seed"],
        }
    multiplicity = _object(payload["multiplicity"], label="inference.multiplicity")
    if dict(multiplicity) != FROZEN_PERMUTATION_METADATA["multiplicity"]:
        raise SourceFeasibilityContractError(
            "inference multiplicity must equal the frozen Holm specification"
        )
    return {
        "family_tests": parsed_families,
        "multiplicity": dict(FROZEN_PERMUTATION_METADATA["multiplicity"]),
    }


def _object(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceFeasibilityContractError(f"{label} must be an object")
    return value


def _list(value: Any, *, label: str) -> Sequence[Any]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise SourceFeasibilityContractError(f"{label} must be a list")
    return value


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceFeasibilityContractError(f"{label} must be non-empty text")
    return value.strip()


def _nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceFeasibilityContractError(f"{label} must be a non-negative integer")
    return value


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SourceFeasibilityContractError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise SourceFeasibilityContractError(f"{label} must be finite")
    return number


def validate_frozen_reference_contract(value: Any) -> FrozenReferenceBindingV2:
    """Validate a caller-injected reference binding without embedding its rows."""

    payload = _object(value, label="frozen_reference")
    required = {"reference_label", "item_rows", "locked_layer_ids", "feature_dimensions"}
    if set(payload) != required:
        raise SourceFeasibilityContractError(
            "frozen_reference has an unsupported field set"
        )
    if tuple(payload["locked_layer_ids"]) != LOCKED_LAYERS:
        raise SourceFeasibilityContractError(
            "frozen_reference.locked_layer_ids must equal the six locked layers"
        )
    dimensions = _object(
        payload["feature_dimensions"], label="frozen_reference.feature_dimensions"
    )
    expected_dimensions = dict.fromkeys(LOCKED_LAYERS, FEATURE_DIMENSION)
    if dict(dimensions) != expected_dimensions:
        raise SourceFeasibilityContractError(
            "frozen_reference.feature_dimensions must bind all six frozen layers"
        )
    raw_rows = _list(payload["item_rows"], label="frozen_reference.item_rows")
    if len(raw_rows) != 48:
        raise SourceFeasibilityContractError(
            "frozen_reference.item_rows must contain exactly 48 rows"
        )
    seen_keys: set[str] = set()
    parsed_rows: list[ReferenceRowBindingV2] = []
    for index, raw_row in enumerate(raw_rows):
        row = _object(raw_row, label=f"frozen_reference.item_rows[{index}]")
        if set(row) != {"row_key", "condition"}:
            raise SourceFeasibilityContractError(
                "frozen_reference rows must contain row_key and condition"
            )
        row_key = _text(row["row_key"], label=f"frozen_reference.item_rows[{index}]")
        if row_key in seen_keys:
            raise SourceFeasibilityContractError("frozen_reference rows repeat row_key")
        seen_keys.add(row_key)
        parsed_rows.append(
            ReferenceRowBindingV2(
                row_key=row_key,
                condition=_text(
                    row["condition"],
                    label=f"frozen_reference.item_rows[{index}].condition",
                ),
            )
        )
    if sum(row.condition == "speech" for row in parsed_rows) != 8 or sum(
        row.condition == "tools" for row in parsed_rows
    ) != 8:
        raise SourceFeasibilityContractError(
            "frozen reference must contain exactly eight speech and eight tools rows"
        )
    return FrozenReferenceBindingV2(
        reference_label=_text(payload["reference_label"], label="reference_label"),
        item_rows=tuple(parsed_rows),
        locked_layer_ids=LOCKED_LAYERS,
        feature_dimensions=tuple(expected_dimensions.items()),
    )


def _historical_exposure_sets(
    historical_exposures: Sequence[Mapping[str, Any]],
) -> tuple[set[str], set[str], set[str], set[str]]:
    if not historical_exposures:
        raise SourceFeasibilityContractError(
            "historical exposure sidecars must be explicitly supplied"
        )
    candidate_keys: set[str] = set()
    source_tokens: set[str] = set()
    pcm_tokens: set[str] = set()
    collection_keys: set[str] = set()
    for index, raw_sidecar in enumerate(historical_exposures):
        sidecar = _object(raw_sidecar, label=f"historical_exposures[{index}]")
        for field_name, target in (
            ("candidate_keys", candidate_keys),
            ("source_tokens", source_tokens),
            ("pcm_tokens", pcm_tokens),
            ("collection_keys", collection_keys),
        ):
            for token_index, token in enumerate(
                _list(
                    sidecar.get(field_name),
                    label=f"historical_exposures[{index}].{field_name}",
                )
            ):
                target.add(
                    _text(
                        token,
                        label=f"historical_exposures[{index}].{field_name}[{token_index}]",
                    )
                )
    return candidate_keys, source_tokens, pcm_tokens, collection_keys


def _validate_auditory_qc(value: Any, *, label: str, condition: str) -> None:
    reviews = _list(value, label=label)
    if len(reviews) != 2:
        raise SourceFeasibilityContractError(f"{label} must contain two reviews")
    reviewer_keys: set[str] = set()
    for index, raw_review in enumerate(reviews):
        review = _object(raw_review, label=f"{label}[{index}]")
        reviewer_keys.add(
            _text(review.get("reviewer_key"), label=f"{label}[{index}].reviewer_key")
        )
        if review.get("target_present") is not True:
            raise SourceFeasibilityContractError(f"{label}[{index}].target_present must be true")
        if review.get("opposite_condition_absent") is not True:
            raise SourceFeasibilityContractError(
                f"{label}[{index}].opposite_condition_absent must be true"
            )
        if review.get("dominant_condition") != condition:
            raise SourceFeasibilityContractError(
                f"{label}[{index}].dominant_condition must match candidate condition"
            )
        for field_name in (
            "blinded_to_proposed_condition",
            "blinded_to_source",
            "blinded_to_acoustic",
            "blinded_to_asr",
            "blinded_to_tribe",
        ):
            if review.get(field_name) is not True:
                raise SourceFeasibilityContractError(f"{label}[{index}].{field_name} must be true")
    if len(reviewer_keys) != 2:
        raise SourceFeasibilityContractError(f"{label} requires two distinct reviewers")


def _validate_candidate_pool(
    payload: Mapping[str, Any],
    historical_exposures: Sequence[Mapping[str, Any]],
) -> tuple[CandidatePoolIntakeBindingV2, FrozenReferenceBindingV2]:
    if payload.get("schema_version") != FROZEN_CONTRACT_SCHEMA_VERSION:
        raise SourceFeasibilityContractError("contract schema_version is invalid")
    if payload.get("program_id") != PROGRAM_ID:
        raise SourceFeasibilityContractError("contract program_id is invalid")
    if payload.get("scope") != "prospective_discovery_validation":
        raise SourceFeasibilityContractError("contract scope is invalid")
    for field_name in (
        "score_blind",
        "authority_granted",
        "launch_authorized",
        "gpu_authorized",
        "tribe_inference_authorized",
        "manuscript_update_authorized",
        "execution_authorized",
        "confirmation_authorized",
        "registration_authorized",
    ):
        expected = True if field_name == "score_blind" else False
        if payload.get(field_name) is not expected:
            raise SourceFeasibilityContractError(
                f"contract.{field_name} must be {expected!r}"
            )
    reference = validate_frozen_reference_contract(payload.get("frozen_reference"))
    collection_values = _list(payload.get("source_collections"), label="source_collections")
    collection_keys = tuple(
        _text(value, label="source_collections[]") for value in collection_values
    )
    if len(collection_keys) != SOURCE_COLLECTION_COUNT or len(set(collection_keys)) != len(
        collection_keys
    ):
        raise SourceFeasibilityContractError("source_collections must contain four unique keys")
    historical_candidates, historical_sources, historical_pcm, historical_collections = (
        _historical_exposure_sets(historical_exposures)
    )
    if set(collection_keys).intersection(historical_collections):
        raise SourceFeasibilityContractError(
            "source_collections overlap caller-supplied historical exposure keys"
        )
    raw_candidates = _list(payload.get("candidate_pool"), label="candidate_pool")
    if len(raw_candidates) < MIN_CANDIDATE_POOL_ITEMS:
        raise SourceFeasibilityContractError(
            "candidate_pool must contain at least 96 rows"
        )
    candidate_keys: set[str] = set()
    source_tokens: set[str] = set()
    pcm_tokens: set[str] = set()
    counts: Counter[tuple[str, str]] = Counter()
    parsed: list[CandidatePoolItemBindingV2] = []
    for index, raw_candidate in enumerate(raw_candidates):
        candidate = _object(raw_candidate, label=f"candidate_pool[{index}]")
        required = {
            "candidate_key",
            "source_token",
            "decoded_pcm_identity",
            "parent_key",
            "collection_key",
            "condition",
            "whisperx_segment_count",
            "acoustic_features",
            "score_blind",
            "tribe_inference_run",
            "auditory_qc",
        }
        if set(candidate) != required:
            raise SourceFeasibilityContractError(
                f"candidate_pool[{index}] has an unsupported field set"
            )
        collection_key = _text(
            candidate["collection_key"], label=f"candidate_pool[{index}].collection_key"
        )
        if collection_key not in collection_keys:
            raise SourceFeasibilityContractError(
                f"candidate_pool[{index}] has an undeclared collection key"
            )
        condition = candidate["condition"]
        if condition not in CONDITIONS:
            raise SourceFeasibilityContractError(
                f"candidate_pool[{index}].condition must be speech or tools"
            )
        if candidate["score_blind"] is not True or candidate["tribe_inference_run"] is not False:
            raise SourceFeasibilityContractError(
                "candidate pool must be score-blind and pre-TRIBE"
            )
        candidate_key = _text(
            candidate["candidate_key"], label=f"candidate_pool[{index}].candidate_key"
        )
        source_token = _text(
            candidate["source_token"], label=f"candidate_pool[{index}].source_token"
        )
        pcm_token = _text(
            candidate["decoded_pcm_identity"],
            label=f"candidate_pool[{index}].decoded_pcm_identity",
        )
        for token, observed, historical, field_name in (
            (candidate_key, candidate_keys, historical_candidates, "candidate_key"),
            (source_token, source_tokens, historical_sources, "source_token"),
            (pcm_token, pcm_tokens, historical_pcm, "decoded_pcm_identity"),
        ):
            if token in observed:
                raise SourceFeasibilityContractError(
                    f"candidate_pool repeats {field_name}"
                )
            if token in historical:
                raise SourceFeasibilityContractError(
                    f"candidate_pool overlaps historical {field_name}"
                )
            observed.add(token)
        _validate_auditory_qc(
            candidate["auditory_qc"],
            label=f"candidate_pool[{index}].auditory_qc",
            condition=condition,
        )
        feature_values = _object(
            candidate["acoustic_features"],
            label=f"candidate_pool[{index}].acoustic_features",
        )
        if set(feature_values) != set(ACOUSTIC_FEATURES):
            raise SourceFeasibilityContractError(
                "candidate acoustic_features must contain exactly the seven frozen summaries"
            )
        parsed_features = tuple(
            (feature, _finite(feature_values[feature], label=feature))
            for feature in ACOUSTIC_FEATURES
        )
        counts[(collection_key, condition)] += 1
        parsed.append(
            CandidatePoolItemBindingV2(
                candidate_key=candidate_key,
                source_token=source_token,
                decoded_pcm_identity=pcm_token,
                parent_key=_text(
                    candidate["parent_key"], label=f"candidate_pool[{index}].parent_key"
                ),
                collection_key=collection_key,
                condition=condition,
                whisperx_segment_count=_nonnegative_int(
                    candidate["whisperx_segment_count"],
                    label=f"candidate_pool[{index}].whisperx_segment_count",
                ),
                acoustic_features=parsed_features,
            )
        )
    for collection_key in sorted(collection_keys):
        for condition in CONDITIONS:
            if counts[(collection_key, condition)] < MIN_POOL_ITEMS_PER_CONDITION_COLLECTION:
                raise SourceFeasibilityContractError(
                    "candidate_pool has fewer than 12 rows in a frozen collection/condition cell"
                )
    return (
        CandidatePoolIntakeBindingV2(
            schema_version=CANDIDATE_POOL_INTAKE_SCHEMA_VERSION,
            program_id=PROGRAM_ID,
            status="candidate_pool_intake_validated",
            source_collection_keys=tuple(sorted(collection_keys)),
            candidate_pool_count=len(parsed),
            candidate_counts_by_collection_condition=tuple(
                (collection_key, condition, counts[(collection_key, condition)])
                for collection_key in sorted(collection_keys)
                for condition in CONDITIONS
            ),
            candidates=tuple(parsed),
        ),
        reference,
    )


def validate_source_candidate_pool_intake(
    contract: Mapping[str, Any],
    historical_exposures: Sequence[Mapping[str, Any]],
) -> CandidatePoolIntakeBindingV2:
    return _validate_candidate_pool(
        _object(contract, label="contract"), historical_exposures
    )[0]


def _pool_standard_deviation(
    candidates: Sequence[CandidatePoolItemBindingV2], feature: str
) -> float:
    values = [dict(candidate.acoustic_features)[feature] for candidate in candidates]
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    scale = math.sqrt(variance)
    return 1.0 if scale == 0.0 else scale


def _selected_acoustic_balance(
    *,
    intake: CandidatePoolIntakeBindingV2,
    selected: Sequence[CandidatePoolItemBindingV2],
) -> tuple[AcousticBalanceBindingV2, ...]:
    """Exact private full-pool-standardized SMD computation."""

    results: list[AcousticBalanceBindingV2] = []
    for scope in (*intake.source_collection_keys, "pooled"):
        pool = [
            candidate
            for candidate in intake.candidates
            if scope == "pooled" or candidate.collection_key == scope
        ]
        selected_scope = [
            candidate
            for candidate in selected
            if scope == "pooled" or candidate.collection_key == scope
        ]
        for feature in ACOUSTIC_FEATURES:
            scale = _pool_standard_deviation(pool, feature)
            speech_values = [
                dict(candidate.acoustic_features)[feature]
                for candidate in selected_scope
                if candidate.condition == "speech"
            ]
            tools_values = [
                dict(candidate.acoustic_features)[feature]
                for candidate in selected_scope
                if candidate.condition == "tools"
            ]
            difference = (
                sum(speech_values) / len(speech_values)
                - sum(tools_values) / len(tools_values)
            ) / scale
            result = AcousticBalanceBindingV2(
                scope=scope,
                feature=feature,
                standardized_mean_difference=float(difference),
            )
            if abs(result.standardized_mean_difference) > MAX_ACOUSTIC_BALANCE_DIFFERENCE:
                raise SourceFeasibilityContractError(
                    "selected panel exceeds the frozen acoustic balance threshold"
                )
            results.append(result)
    return tuple(results)


def validate_source_feasibility_contract(
    contract: Mapping[str, Any],
    historical_exposures: Sequence[Mapping[str, Any]],
) -> SourceFeasibilityBindingV2:
    payload = _object(contract, label="contract")
    intake, reference = _validate_candidate_pool(payload, historical_exposures)
    selection = _object(payload.get("selection"), label="selection")
    expected_selection_fields = {
        "method_id",
        "score_blind",
        "uses_tribe_features",
        "uses_frozen_axis_geometry",
        "uses_hypothesis_outcomes",
        "max_absolute_standardized_mean_difference",
        "selected_candidate_keys",
    }
    if set(selection) != expected_selection_fields:
        raise SourceFeasibilityContractError("selection has an unsupported field set")
    expected_values = {
        "method_id": SELECTION_METHOD_ID,
        "score_blind": True,
        "uses_tribe_features": False,
        "uses_frozen_axis_geometry": False,
        "uses_hypothesis_outcomes": False,
        "max_absolute_standardized_mean_difference": MAX_ACOUSTIC_BALANCE_DIFFERENCE,
    }
    for field_name, expected in expected_values.items():
        if selection.get(field_name) != expected:
            raise SourceFeasibilityContractError(
                f"selection.{field_name} changes the frozen selection contract"
            )
    selected_keys = tuple(
        _text(value, label="selection.selected_candidate_keys[]")
        for value in _list(
            selection["selected_candidate_keys"], label="selection.selected_candidate_keys"
        )
    )
    if len(selected_keys) != SELECTED_ITEM_COUNT or len(set(selected_keys)) != len(
        selected_keys
    ):
        raise SourceFeasibilityContractError(
            "selection must contain 48 unique candidate keys"
        )
    by_key = {candidate.candidate_key: candidate for candidate in intake.candidates}
    if set(selected_keys).difference(by_key):
        raise SourceFeasibilityContractError(
            "selection names a candidate outside the validated pool"
        )
    selected = tuple(by_key[key] for key in selected_keys)
    selected_counts = Counter(
        (candidate.collection_key, candidate.condition) for candidate in selected
    )
    expected_counts = Counter(
        {
            (collection_key, condition): ITEMS_PER_CONDITION_COLLECTION
            for collection_key in intake.source_collection_keys
            for condition in CONDITIONS
        }
    )
    if selected_counts != expected_counts:
        raise SourceFeasibilityContractError(
            "selection must have six speech and six tools rows per collection"
        )
    parent_keys = [candidate.parent_key for candidate in selected]
    if len(set(parent_keys)) != len(parent_keys):
        raise SourceFeasibilityContractError(
            "selection must use at most one candidate per parent key"
        )
    for collection_key in intake.source_collection_keys:
        for condition in CONDITIONS:
            values = {
                candidate.whisperx_segment_count
                for candidate in selected
                if candidate.collection_key == collection_key
                and candidate.condition == condition
            }
            if len(values) < 2:
                raise SourceFeasibilityContractError(
                    "pre-TRIBE WhisperX segment count lacks within-cell variation"
                )
    from .score_blind_selector import select_score_blind_panel

    deterministic = select_score_blind_panel(intake)
    if selected_keys != deterministic.selected_candidate_keys:
        raise SourceFeasibilityContractError(
            "selection must equal the deterministic frozen score-blind panel"
        )
    acoustic_balance = _selected_acoustic_balance(intake=intake, selected=selected)
    return SourceFeasibilityBindingV2(
        schema_version=SOURCE_FEASIBILITY_PACKET_SCHEMA_VERSION,
        program_id=PROGRAM_ID,
        status="selected_panel_feasibility_bound",
        intake=intake,
        frozen_reference=reference,
        selection_method_id=SELECTION_METHOD_ID,
        evaluation_item_rows=tuple(
            EvaluationItemRowBindingV2(
                row_key=candidate.candidate_key,
                collection_key=candidate.collection_key,
                condition=candidate.condition,
                whisperx_segment_count=candidate.whisperx_segment_count,
            )
            for candidate in selected
        ),
        acoustic_balance=acoustic_balance,
        max_acoustic_balance_difference=MAX_ACOUSTIC_BALANCE_DIFFERENCE,
        authority_granted=False,
        launch_authorized=False,
        gpu_authorized=False,
        tribe_inference_authorized=False,
        manuscript_update_authorized=False,
        execution_authorized=False,
        confirmation_authorized=False,
        registration_authorized=False,
        _validator_marker=_VALIDATED_BINDING_MARKER,
    )


__all__ = [
    "ACOUSTIC_FEATURES",
    "AcousticBalanceBindingV2",
    "CANDIDATE_POOL_INTAKE_SCHEMA_VERSION",
    "CandidatePoolIntakeBindingV2",
    "CandidatePoolItemBindingV2",
    "CONDITIONS",
    "EARLY_LAYERS",
    "FEATURE_DIMENSION",
    "FROZEN_HYPOTHESIS_FAMILIES",
    "FROZEN_PERMUTATION_METADATA",
    "FrozenReferenceBindingV2",
    "INFERENCE_ALPHA",
    "ITEMS_PER_CONDITION_COLLECTION",
    "LATE_LAYERS",
    "LOCKED_LAYERS",
    "MAX_ACOUSTIC_BALANCE_DIFFERENCE",
    "MIN_CANDIDATE_POOL_ITEMS",
    "MIN_POOL_ITEMS_PER_CONDITION_COLLECTION",
    "PROGRAM_ID",
    "SELECTED_ITEM_COUNT",
    "SELECTION_METHOD_ID",
    "SOURCE_COLLECTION_COUNT",
    "SOURCE_FEASIBILITY_PACKET_SCHEMA_VERSION",
    "SourceFeasibilityBindingV2",
    "SourceFeasibilityContractError",
    "default_inference_config",
    "is_validator_issued_binding",
    "rekey_validator_issued_binding",
    "validate_frozen_reference_contract",
    "validate_inference_config",
    "validate_source_candidate_pool_intake",
    "validate_source_feasibility_contract",
]
