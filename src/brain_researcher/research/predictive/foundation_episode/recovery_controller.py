"""Strict controller boundary for the fixed MVE-100 v2 transport recovery.

The recovery is deliberately narrower than discovery.  It asks for two
candidate proposals for one already-failed source batch, with a
participant/holdout-blind historical source ledger and pair identities only.
It never exposes recovery outcomes to later controller calls and it never
permits ``stop``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy

from brain_researcher.research.predictive.foundation_episode.contracts import (
    FoundationEpisodeError,
    canonical_json_bytes,
)
from brain_researcher.research.predictive.foundation_episode.controller import (
    _validate_aggregate_ledger,
    _validate_catalog,
    _validate_metric_catalog,
    _validate_slot_contracts,
    controller_response_schema_for_slot_count,
    parse_controller_batch_decisions,
)


class RecoveryControllerError(FoundationEpisodeError):
    """The recovery controller crossed its frozen visible-input boundary."""


POST_HOC_PAIR_IDENTITY_VISIBILITY = {
    "v1_frozen_pairs": "identity_only",
    "source_v2_executed_pairs": "identity_only",
    "earlier_recovery_pairs": "identity_only",
    "current_batch_pair_identities": "not_visible_before_response",
    "future_recovery_pair_identities": "forbidden",
    "future_scores_or_results": "forbidden",
}

RECOVERY_REPAIR_ERROR_CODES = frozenset(
    {
        "invalid_json",
        "response_schema_mismatch",
        "response_batch_length_mismatch",
        "decision_contract_violation",
        "duplicate_candidate",
    }
)
RECOVERY_REPAIR_INSTRUCTION = (
    "The prior response failed only structural validation. Return one complete "
    "replacement for the same frozen source slots, historical ledger, and pair "
    "exclusions. Do not request new evidence, alter the protocol, or refer to "
    "the prior response text."
)

_RECOVERY_BATCH_MAPPING = {
    "adaptive_batch_6": ((19, 20), 18),
    "adaptive_batch_13": ((33, 34), 32),
    "adaptive_batch_14": ((35, 36), 34),
    "adaptive_batch_17": ((41, 42), 40),
    "adaptive_batch_19": ((45, 46), 44),
    "adaptive_batch_44": ((95, 96), 94),
}


def recovery_controller_response_schema() -> dict[str, object]:
    """Return the frozen two-proposal schema with ``stop`` removed."""

    schema = deepcopy(controller_response_schema_for_slot_count(2))
    decisions = schema["properties"]["decisions"]
    assert isinstance(decisions, dict)
    item = decisions["items"]
    assert isinstance(item, dict)
    properties = item["properties"]
    assert isinstance(properties, dict)
    action = properties["action"]
    assert isinstance(action, dict)
    action["enum"] = ["propose_candidate"]
    return schema


def _pair(value: object, *, label: str) -> tuple[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"classifier_key", "term_index"}:
        raise RecoveryControllerError(f"{label} must be an object")
    classifier = value.get("classifier_key")
    term = value.get("term_index")
    if (
        not isinstance(classifier, str)
        or not classifier
        or isinstance(term, bool)
        or not isinstance(term, int)
        or term < 0
    ):
        raise RecoveryControllerError(f"{label} pair identity is invalid")
    return classifier, term


def pair_records(pairs: Sequence[tuple[str, int]]) -> list[dict[str, object]]:
    """Render deterministic public pair identities without any outcomes."""

    return [
        {"classifier_key": classifier, "term_index": term}
        for classifier, term in sorted(set(pairs))
    ]


def _validate_pair_exclusions(
    pair_exclusions: Sequence[object],
) -> set[tuple[str, int]]:
    if (
        isinstance(pair_exclusions, str | bytes | bytearray)
        or not isinstance(pair_exclusions, Sequence)
        or not pair_exclusions
    ):
        raise RecoveryControllerError("pair exclusions must be a sequence")
    pairs = {_pair(value, label="pair exclusion") for value in pair_exclusions}
    if len(pairs) != len(pair_exclusions):
        raise RecoveryControllerError("pair exclusions contain a duplicate identity")
    if list(pair_exclusions) != pair_records(list(pairs)):
        raise RecoveryControllerError(
            "pair exclusions must use canonical identity order"
        )
    return pairs


def _proposal_pair(value: Mapping[str, object]) -> tuple[str, int]:
    """Extract a proposal identity without weakening pair-record strictness."""

    return _pair(
        {
            "classifier_key": value.get("classifier_key"),
            "term_index": value.get("term_index"),
        },
        label="recovery proposal",
    )


def _validate_historical_ledger(
    historical_ledger: Sequence[object], *, cutoff: int
) -> None:
    if isinstance(historical_ledger, str | bytes | bytearray) or not isinstance(
        historical_ledger, Sequence
    ):
        raise RecoveryControllerError("historical ledger must be a sequence")
    if len(historical_ledger) != cutoff:
        raise RecoveryControllerError("historical ledger does not match its cutoff")
    try:
        _validate_aggregate_ledger(historical_ledger, cutoff=cutoff)
    except FoundationEpisodeError as exc:
        raise RecoveryControllerError(
            "historical ledger is not an aggregate-only snapshot"
        ) from exc


def _validate_recovery_batch(
    *, recovery_batch: str, current_slot_contracts: Sequence[object], ledger_cutoff: int
) -> None:
    try:
        contracts, source_batch, source_cutoff = _validate_slot_contracts(
            current_slot_contracts
        )
    except FoundationEpisodeError as exc:
        raise RecoveryControllerError("source slot contracts are invalid") from exc
    expected = _RECOVERY_BATCH_MAPPING.get(recovery_batch)
    if (
        expected is None
        or source_batch != recovery_batch
        or source_cutoff != ledger_cutoff
        or tuple(contract.get("slot") for contract in contracts) != expected[0]
        or ledger_cutoff != expected[1]
    ):
        raise RecoveryControllerError("recovery batch mapping is not frozen")


def recovery_validation_error_code(exc: Exception) -> str:
    """Return the frozen, non-sensitive repair category for a rejected response."""

    message = str(exc).lower()
    if "not json" in message:
        return "invalid_json"
    if "two decisions" in message or "length" in message:
        return "response_batch_length_mismatch"
    if "duplicate" in message or "excluded pair" in message:
        return "duplicate_candidate"
    if "schema" in message or "shape" in message or "response" in message:
        return "response_schema_mismatch"
    return "decision_contract_violation"


def build_recovery_controller_prompt(
    *,
    sanitized_catalog: Mapping[str, object],
    metric_catalog: Mapping[str, object],
    historical_ledger: Sequence[object],
    current_slot_contracts: Sequence[object],
    recovery_batch: str,
    ledger_cutoff: int,
    pair_exclusions: Sequence[object],
    repair_context: Mapping[str, object] | None = None,
) -> str:
    """Build one participant/holdout-blind prompt for an immutable source ledger."""

    if not isinstance(recovery_batch, str) or not recovery_batch:
        raise RecoveryControllerError("recovery batch is invalid")
    if isinstance(ledger_cutoff, bool) or not isinstance(ledger_cutoff, int):
        raise RecoveryControllerError("recovery ledger cutoff is invalid")
    _validate_catalog(sanitized_catalog)
    _validate_metric_catalog(metric_catalog)
    _validate_historical_ledger(historical_ledger, cutoff=ledger_cutoff)
    exclusions = _validate_pair_exclusions(pair_exclusions)
    if (
        isinstance(current_slot_contracts, str | bytes | bytearray)
        or len(current_slot_contracts) != 2
    ):
        raise RecoveryControllerError("recovery controller requires two source slots")
    _validate_recovery_batch(
        recovery_batch=recovery_batch,
        current_slot_contracts=current_slot_contracts,
        ledger_cutoff=ledger_cutoff,
    )
    if repair_context is not None:
        if (
            not isinstance(repair_context, Mapping)
            or set(repair_context) != {"attempt", "validation_error_code"}
            or repair_context.get("attempt") != 1
            or repair_context.get("validation_error_code")
            not in RECOVERY_REPAIR_ERROR_CODES
        ):
            raise RecoveryControllerError("recovery repair context is invalid")

    visible_payload = {
        "sanitized_catalog": sanitized_catalog,
        "metric_catalog": metric_catalog,
        "historical_source_ledger": list(historical_ledger),
        "current_source_slot_contracts": list(current_slot_contracts),
        "recovery_budget": {
            "recovery_batch": recovery_batch,
            "historical_ledger_cutoff": ledger_cutoff,
            "pair_exclusions": pair_records(list(exclusions)),
            "post_hoc_pair_identity_visibility": POST_HOC_PAIR_IDENTITY_VISIBILITY,
            "controller_timeout_seconds": 240,
            "physical_calls_per_batch_hard_max": 2,
        },
    }
    prompt = "\n\n".join(
        [
            "You are the bounded controller for a transport-recovery-only "
            "episode. Return exactly two propose_candidate decisions for the "
            "two supplied source slots. stop is forbidden. Use only the "
            "catalog, historical source ledger, and pair identities supplied. "
            "Do not request hidden data, alter the protocol, or infer future "
            "recovery scores or results.",
            "Return only the JSON object required by the frozen output schema.",
            "Controller-visible JSON follows:\n"
            + canonical_json_bytes(visible_payload).decode("utf-8"),
        ]
    )
    if repair_context is not None:
        prompt += "\n\nStructural repair context follows:\n" + canonical_json_bytes(
            {
                "repair_context": dict(repair_context),
                "instruction": RECOVERY_REPAIR_INSTRUCTION,
            }
        ).decode("utf-8")
    return prompt


def parse_recovery_batch_decisions(
    response_text: str,
    *,
    sanitized_catalog: Mapping[str, object],
    metric_catalog: Mapping[str, object],
    current_slot_contracts: Sequence[object],
    pair_exclusions: Sequence[object],
) -> list[dict[str, object]]:
    """Parse two proposals and reject stop or every already-visible pair."""

    exclusions = _validate_pair_exclusions(pair_exclusions)
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RecoveryControllerError(
            "recovery controller response is not JSON"
        ) from exc
    if not isinstance(payload, Mapping) or set(payload) != {"decisions"}:
        raise RecoveryControllerError("recovery controller response shape is invalid")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != 2:
        raise RecoveryControllerError("recovery controller must return two decisions")
    if any(
        not isinstance(decision, Mapping)
        or decision.get("action") != "propose_candidate"
        for decision in decisions
    ):
        raise RecoveryControllerError("recovery controller stop is forbidden")
    try:
        parsed = parse_controller_batch_decisions(
            response_text,
            sanitized_catalog=sanitized_catalog,
            metric_catalog=metric_catalog,
            current_slot_contracts=current_slot_contracts,
        )
    except FoundationEpisodeError as exc:
        raise RecoveryControllerError(str(exc)) from exc
    proposed = [_proposal_pair(decision) for decision in parsed]
    if len(set(proposed)) != 2:
        raise RecoveryControllerError("recovery batch proposes a duplicate pair")
    if set(proposed) & exclusions:
        raise RecoveryControllerError("recovery proposal repeats an excluded pair")
    return [dict(decision) for decision in parsed]


__all__ = [
    "POST_HOC_PAIR_IDENTITY_VISIBILITY",
    "RECOVERY_REPAIR_ERROR_CODES",
    "RECOVERY_REPAIR_INSTRUCTION",
    "RecoveryControllerError",
    "build_recovery_controller_prompt",
    "pair_records",
    "parse_recovery_batch_decisions",
    "recovery_validation_error_code",
    "recovery_controller_response_schema",
]
