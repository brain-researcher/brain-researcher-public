"""Score- and identity-bounded two-slot Codex CLI controller contract.

The runner may call this controller only for the frozen two-slot cadence.  It
never receives a within-batch result, a private receipt, an outcome value, or
execution tools.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy

from brain_researcher.research.predictive.foundation_episode.contracts import (
    CANDIDATE_RECEIPT_COUNT,
    CATALOG_SCHEMA,
    CONTROLLER_CALL_BUDGETS,
    CONTROLLER_PRIMARY_BATCH_SLOTS,
    COVERAGE_STRATA,
    DISCOVERY_SCOPE,
    METRIC_CATALOG_SCHEMA,
    RECEIPT_COUNT,
    V1_EXCLUDED_CANDIDATE_PAIRS,
    FoundationEpisodeError,
    canonical_json_bytes,
    controller_cadence_batches,
)

CONTROLLER_MODEL = "gpt-5.6-sol"
CONTROLLER_SCHEMA_NAME = "foundation_mve100_controller_batch_decisions_v2"
REPAIR_VALIDATION_ERROR_CODES = frozenset(
    {
        "invalid_json",
        "response_schema_mismatch",
        "response_batch_length_mismatch",
        "decision_contract_violation",
        "duplicate_candidate",
        "proposal_after_stop",
    }
)
REPAIR_INSTRUCTION = (
    "The prior response failed only structural validation. Return one complete "
    "replacement for the same frozen slots and same ledger. Do not request new "
    "evidence, alter the protocol, or refer to the prior response text."
)


def _controller_cadence_text() -> str:
    """Render the controller-visible cadence from the shared contract constants."""

    cadence = controller_cadence_batches()
    if not cadence or any(row["decision_count"] != 2 for row in cadence):
        raise AssertionError("the controller cadence must be fixed two-slot batches")
    batches = "; ".join(
        f"{row['batch']} slots {row['slots'][0]}-{row['slots'][-1]} "
        f"through ledger cutoff {row['ledger_cutoff_slot']}"
        for row in cadence
    )
    return (
        f"There are exactly {len(cadence)} controller calls, each returning exactly "
        "two frozen decisions before either slot is evaluated. Frozen batches are: "
        f"{batches}. There is no within-batch score peeking."
    )


CONTROLLER_SYSTEM_PROMPT = f"""You are the discovery-only scientific controller for the frozen MVE-100 v2 episode.

The sole outcome target is ICA_Cognition. Signed Pearson r is the primary
outcome statistic, but you never see participant-level values, heldout data,
paths, subject IDs, family IDs, or historical results. You receive only the
sanitized conceptual and classifier catalogs, a validated metric catalog, the
current frozen proposal batch, and an aggregate in-episode ledger.

{_controller_cadence_text()}
Coverage slots must use the required runnable classifier stratum. Adaptive
proposals must stay within the frozen catalog and budget. The budget exposes
the prior v1 candidate-pair exclusions but never v1 outcomes. Slots 97-98 are
host-fixed repartition/split-robustness checks on the same discovery subjects,
not independent or fresh-subject replications. Slots 99-100 are host-fixed
falsifier and synthetic positive-control operations, not controller actions.

Every candidate proposal must state a falsifiable hypothesis and a falsifier.
Coverage slots must propose candidates. Adaptive slots may propose candidates or
stop. Negative, failed, or unavailable results can justify stopping or a bounded
next proposal, never protocol expansion. Do not repeat a completed proposal,
alter gates, invent a classifier or term, reinterpret a prototype as canonical,
or request hidden information. stop means stop discovery without a claim. You
cannot authorize execution, make a claim, select, convert, or use sealed-holdout
target values, or authorize confirmation. Confirmation requires separate human
authorization."""

_FORBIDDEN_KEY_FRAGMENTS = (
    "path",
    "subject",
    "family_id",
    "holdout",
    "histor",
    "current_use",
    "search_priority",
    "notes",
)
_DECISION_REQUIRED = {
    "action",
    "slot",
    "classifier_key",
    "term_index",
    "hypothesis",
    "falsifier",
    "rationale",
}
_SLOT_REQUIRED = {
    "slot",
    "kind",
    "batch",
    "proposal_batch",
    "evidence_release",
    "ledger_cutoff_slot",
    "requires_prior_aggregate",
    "required_stratum",
}
_BUDGET_REQUIRED = {
    "scope",
    "receipt_budget",
    "proposal_batch",
    "batch_slots",
    "executed_receipts",
    "ledger_cutoff_slot",
    "controller_primary_calls_max",
    "controller_schema_repair_calls_max",
    "controller_calls_hard_max",
    "excluded_candidate_pairs",
}
_AGGREGATE_REQUIRED = {
    "schema_version",
    "slot",
    "status",
    "candidate_label",
    "classifier_key",
    "term_index",
    "control_mode",
    "metrics",
    "qc",
    "runtime_sec",
    "failure_type",
}
_AGGREGATE_METRIC_KEYS = {
    "primary_signed_pearson_r",
    "mean_fold_signed_pearson_r",
    "mean_fold_r2",
    "mean_fold_mae",
    "pooled_signed_pearson_r",
}
_AGGREGATE_QC_KEYS = {
    "outer_fold_count",
    "completed_fold_count",
    "failed_fold_count",
    "all_outer_folds_succeeded",
    "primary_metric_available",
}


def _excluded_candidate_pair_records() -> list[dict[str, object]]:
    """Return the score-blind v1 exclusions in their frozen public order."""

    return [
        {"classifier_key": classifier_key, "term_index": term_index}
        for classifier_key, term_index in sorted(V1_EXCLUDED_CANDIDATE_PAIRS)
    ]

_DECISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_DECISION_REQUIRED),
    "properties": {
        "action": {"type": "string", "enum": ["propose_candidate", "stop"]},
        "slot": {"type": "integer", "minimum": 1, "maximum": CANDIDATE_RECEIPT_COUNT},
        "classifier_key": {"type": ["string", "null"], "maxLength": 256},
        "term_index": {"type": ["integer", "null"], "minimum": 0},
        "hypothesis": {"type": ["string", "null"], "maxLength": 600},
        "falsifier": {"type": ["string", "null"], "maxLength": 600},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 600},
    },
}
CONTROLLER_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decisions"],
    "properties": {
        "decisions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": _DECISION_SCHEMA,
        }
    },
}


def _reject_forbidden_keys(value: object, *, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise FoundationEpisodeError(f"{label} contains a non-string key")
            normalized = key.lower()
            if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise FoundationEpisodeError(
                    f"{label} exposes forbidden controller field {key!r}"
                )
            _reject_forbidden_keys(item, label=f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, label=f"{label}[{index}]")


def _validate_catalog(sanitized_catalog: Mapping[str, object]) -> None:
    if sanitized_catalog.get("schema_version") != CATALOG_SCHEMA:
        raise FoundationEpisodeError("controller requires the sanitized catalog schema")
    concepts = sanitized_catalog.get("concepts")
    declared_count = sanitized_catalog.get("concept_count")
    if (
        isinstance(declared_count, bool)
        or not isinstance(declared_count, int)
        or declared_count < 80
        or not isinstance(concepts, list)
        or len(concepts) != declared_count
    ):
        raise FoundationEpisodeError(
            "controller requires the declared 80+ sanitized concepts"
        )
    maturities = {
        "benchmark_native",
        "minimal_viable",
        "prototype",
        "declared",
        "unavailable",
    }
    for index, concept in enumerate(concepts):
        if not isinstance(concept, Mapping) or set(concept) != {
            "concept_id",
            "family",
            "operational_keys",
            "runnable",
            "implementation_maturity",
        }:
            raise FoundationEpisodeError(
                f"sanitized concept {index} has fields outside the public whitelist"
            )
        keys = concept["operational_keys"]
        if not isinstance(keys, list) or any(
            not isinstance(key, str) or not key for key in keys
        ):
            raise FoundationEpisodeError(
                f"sanitized concept {index} operational keys are invalid"
            )
        if (
            concept["runnable"] is not bool(keys)
            or concept["implementation_maturity"] not in maturities
        ):
            raise FoundationEpisodeError(
                f"sanitized concept {index} has inconsistent public state"
            )
    classifier_catalog = sanitized_catalog.get("classifier_catalog")
    if not isinstance(classifier_catalog, list):
        raise FoundationEpisodeError(
            "controller requires a sanitized classifier catalog"
        )
    seen_keys: set[str] = set()
    for entry in classifier_catalog:
        if not isinstance(entry, Mapping) or set(entry) != {
            "classifier_key",
            "runnable",
            "stratum",
            "implementation_maturity",
            "runnable_reason",
        }:
            raise FoundationEpisodeError("classifier catalog entry is invalid")
        key = entry.get("classifier_key")
        if not isinstance(key, str) or not key or key in seen_keys:
            raise FoundationEpisodeError("classifier catalog keys are invalid")
        seen_keys.add(key)
        if entry["stratum"] not in {*COVERAGE_STRATA, "unassigned"}:
            raise FoundationEpisodeError("classifier catalog stratum is invalid")
        if entry["implementation_maturity"] not in maturities:
            raise FoundationEpisodeError("classifier catalog maturity is invalid")
    _reject_forbidden_keys(sanitized_catalog, label="sanitized_catalog")


def _validate_metric_catalog(metric_catalog: Mapping[str, object]) -> None:
    if metric_catalog.get("schema_version") != METRIC_CATALOG_SCHEMA:
        raise FoundationEpisodeError("controller requires the sanitized metric catalog")
    terms = metric_catalog.get("terms")
    if not isinstance(terms, list) or len(terms) != 76:
        raise FoundationEpisodeError("metric catalog must contain exactly 76 terms")
    indices: set[int] = set()
    for term in terms:
        if not isinstance(term, Mapping) or set(term) != {
            "term_index",
            "metric_alias",
            "metric_family",
        }:
            raise FoundationEpisodeError("metric catalog has an invalid term entry")
        index = term.get("term_index")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index in indices
        ):
            raise FoundationEpisodeError("metric catalog term indices are invalid")
        indices.add(index)
        if not isinstance(term.get("metric_alias"), str) or not term["metric_alias"]:
            raise FoundationEpisodeError("metric catalog alias is invalid")
        if not isinstance(term.get("metric_family"), str) or not term["metric_family"]:
            raise FoundationEpisodeError("metric catalog family is invalid")
    _reject_forbidden_keys(metric_catalog, label="metric_catalog")


def _finite_or_null(value: object) -> bool:
    return value is None or (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_aggregate_row(row: object, *, expected_slot: int) -> None:
    if not isinstance(row, Mapping) or set(row) != _AGGREGATE_REQUIRED:
        raise FoundationEpisodeError(
            "aggregate ledger row does not match controller aggregate schema"
        )
    if row.get("schema_version") != "foundation_episode_controller_aggregate_v1":
        raise FoundationEpisodeError("aggregate ledger row schema version is invalid")
    if row.get("slot") != expected_slot:
        raise FoundationEpisodeError(
            "aggregate ledger slots must be continuous from one"
        )
    if row.get("status") not in {"succeeded", "failed", "skipped"}:
        raise FoundationEpisodeError("aggregate ledger terminal status is invalid")
    if (
        not isinstance(row.get("candidate_label"), str)
        or not row["candidate_label"].strip()
    ):
        raise FoundationEpisodeError("aggregate ledger candidate label is invalid")
    if (
        isinstance(row.get("term_index"), bool)
        or not isinstance(row.get("term_index"), int)
        or row["term_index"] < 0
    ):
        raise FoundationEpisodeError("aggregate ledger term index is invalid")
    if not isinstance(row.get("classifier_key"), str) or not row["classifier_key"]:
        raise FoundationEpisodeError("aggregate ledger classifier key is invalid")
    if row.get("control_mode") not in {
        "observed",
        "family_block_shuffle",
        "synthetic_positive_control",
    }:
        raise FoundationEpisodeError("aggregate ledger control mode is invalid")
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != _AGGREGATE_METRIC_KEYS:
        raise FoundationEpisodeError("aggregate ledger metrics are invalid")
    if any(not _finite_or_null(value) for value in metrics.values()):
        raise FoundationEpisodeError("aggregate ledger metrics must be finite or null")
    qc = row.get("qc")
    if not isinstance(qc, Mapping) or set(qc) != _AGGREGATE_QC_KEYS:
        raise FoundationEpisodeError("aggregate ledger QC is invalid")
    if any(
        isinstance(qc[key], bool) or not isinstance(qc[key], int) or qc[key] < 0
        for key in ("outer_fold_count", "completed_fold_count", "failed_fold_count")
    ):
        raise FoundationEpisodeError("aggregate ledger fold counts are invalid")
    if not isinstance(qc["all_outer_folds_succeeded"], bool) or not isinstance(
        qc["primary_metric_available"], bool
    ):
        raise FoundationEpisodeError("aggregate ledger QC flags are invalid")
    if not _finite_or_null(row.get("runtime_sec")):
        raise FoundationEpisodeError("aggregate ledger runtime is invalid")
    if row.get("failure_type") is not None and not isinstance(row["failure_type"], str):
        raise FoundationEpisodeError("aggregate ledger failure type is invalid")


def _validate_aggregate_ledger(
    aggregate_ledger: Sequence[object], *, cutoff: int
) -> None:
    if cutoff == 0:
        if aggregate_ledger:
            raise FoundationEpisodeError(
                "coverage batch must not receive aggregate evidence"
            )
        return
    if len(aggregate_ledger) != cutoff:
        raise FoundationEpisodeError(
            "aggregate ledger row count must equal its frozen cutoff"
        )
    for expected_slot, row in enumerate(aggregate_ledger, start=1):
        _validate_aggregate_row(row, expected_slot=expected_slot)


def _validate_slot_contracts(
    current_slot_contracts: Sequence[object],
) -> tuple[list[Mapping[str, object]], str, int]:
    if isinstance(current_slot_contracts, str | bytes | bytearray) or not isinstance(
        current_slot_contracts, Sequence
    ):
        raise FoundationEpisodeError(
            "controller requires a sequence of current batch slot contracts"
        )
    contracts = list(current_slot_contracts)
    if not contracts or any(not isinstance(item, Mapping) for item in contracts):
        raise FoundationEpisodeError("controller batch slot contracts are invalid")
    first = contracts[0]
    if set(first) != _SLOT_REQUIRED:
        raise FoundationEpisodeError(
            "controller requires the fixed slot contract shape"
        )
    proposal_batch = first["proposal_batch"]
    if (
        not isinstance(proposal_batch, str)
        or proposal_batch not in CONTROLLER_PRIMARY_BATCH_SLOTS
    ):
        raise FoundationEpisodeError(
            "controller may be called only for a frozen proposal batch"
        )
    expected_slots = CONTROLLER_PRIMARY_BATCH_SLOTS[proposal_batch]
    if len(contracts) != len(expected_slots):
        raise FoundationEpisodeError(
            "controller batch size does not match its frozen proposal batch"
        )
    slots: list[int] = []
    cutoff = first["ledger_cutoff_slot"]
    if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff < 0:
        raise FoundationEpisodeError("controller batch ledger cutoff is invalid")
    expected_cutoffs = {
        str(row["batch"]): row["ledger_cutoff_slot"]
        for row in controller_cadence_batches()
    }
    if cutoff != expected_cutoffs.get(proposal_batch):
        raise FoundationEpisodeError("controller batch ledger cutoff is not frozen")
    for contract in contracts:
        if set(contract) != _SLOT_REQUIRED:
            raise FoundationEpisodeError(
                "controller requires the fixed slot contract shape"
            )
        if (
            contract.get("proposal_batch") != proposal_batch
            or contract.get("ledger_cutoff_slot") != cutoff
        ):
            raise FoundationEpisodeError(
                "controller batch contracts disagree on batch evidence"
            )
        slot = contract.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int):
            raise FoundationEpisodeError("controller batch slot is invalid")
        slots.append(slot)
        if slot <= 8 and (
            contract.get("kind") != "coverage_stratum"
            or contract.get("required_stratum") not in COVERAGE_STRATA
            or contract.get("requires_prior_aggregate") is not (cutoff > 0)
        ):
            raise FoundationEpisodeError("coverage slot contract is invalid")
        if slot >= 9 and (
            contract.get("kind") != "adaptive_candidate"
            or contract.get("required_stratum") is not None
            or contract.get("requires_prior_aggregate") is not (cutoff > 0)
        ):
            raise FoundationEpisodeError("adaptive slot contract is invalid")
    if tuple(slots) != expected_slots or not isinstance(cutoff, int) or cutoff < 0:
        raise FoundationEpisodeError(
            "controller batch slots or ledger cutoff are invalid"
        )
    _reject_forbidden_keys(contracts, label="current_slot_contracts")
    return contracts, proposal_batch, cutoff


def validate_controller_visible_inputs(
    *,
    sanitized_catalog: Mapping[str, object],
    metric_catalog: Mapping[str, object],
    aggregate_ledger: Sequence[object],
    current_slot_contracts: Sequence[object],
    budget: Mapping[str, object],
) -> None:
    """Fail closed on controller visibility, batch shape, and evidence cutoff."""

    _validate_catalog(sanitized_catalog)
    _validate_metric_catalog(metric_catalog)
    contracts, proposal_batch, cutoff = _validate_slot_contracts(current_slot_contracts)
    if isinstance(aggregate_ledger, str | bytes | bytearray) or not isinstance(
        aggregate_ledger, Sequence
    ):
        raise FoundationEpisodeError("aggregate_ledger must be a sequence")
    _validate_aggregate_ledger(aggregate_ledger, cutoff=cutoff)
    _reject_forbidden_keys(aggregate_ledger, label="aggregate_ledger")
    if set(budget) != _BUDGET_REQUIRED:
        raise FoundationEpisodeError("controller budget shape is invalid")
    slots = list(CONTROLLER_PRIMARY_BATCH_SLOTS[proposal_batch])
    if (
        budget.get("scope") != DISCOVERY_SCOPE
        or budget.get("receipt_budget") != RECEIPT_COUNT
        or budget.get("proposal_batch") != proposal_batch
        or budget.get("batch_slots") != slots
        or budget.get("executed_receipts") != cutoff
        or budget.get("ledger_cutoff_slot") != cutoff
        or budget.get("controller_primary_calls_max")
        != CONTROLLER_CALL_BUDGETS["controller_primary_calls_max"]
        or budget.get("controller_schema_repair_calls_max")
        != CONTROLLER_CALL_BUDGETS["controller_schema_repair_calls_max"]
        or budget.get("controller_calls_hard_max")
        != CONTROLLER_CALL_BUDGETS["controller_calls_hard_max"]
        or budget.get("excluded_candidate_pairs")
        != _excluded_candidate_pair_records()
    ):
        raise FoundationEpisodeError(
            "controller budget is outside the frozen MVE-100 gate"
        )
    _reject_forbidden_keys(budget, label="budget")


def controller_response_schema_for_slot_count(slot_count: int) -> dict[str, object]:
    if slot_count != 2:
        raise FoundationEpisodeError(
            "controller response schema needs two frozen slots"
        )
    schema = deepcopy(CONTROLLER_RESPONSE_SCHEMA)
    decisions = schema["properties"]["decisions"]
    assert isinstance(decisions, dict)
    decisions["minItems"] = slot_count
    decisions["maxItems"] = slot_count
    return schema


def _validate_repair_context(repair_context: Mapping[str, object] | None) -> None:
    if repair_context is None:
        return
    if set(repair_context) != {"attempt", "validation_error_code"}:
        raise FoundationEpisodeError("controller repair context shape is invalid")
    if repair_context.get("attempt") != 1:
        raise FoundationEpisodeError("controller allows only repair attempt one")
    if repair_context.get("validation_error_code") not in REPAIR_VALIDATION_ERROR_CODES:
        raise FoundationEpisodeError("controller repair error code is not allowlisted")


def build_controller_prompt(
    *,
    sanitized_catalog: Mapping[str, object],
    metric_catalog: Mapping[str, object],
    aggregate_ledger: Sequence[object],
    current_slot_contracts: Sequence[object],
    budget: Mapping[str, object],
    repair_context: Mapping[str, object] | None = None,
) -> str:
    """Build the one stdin prompt for a frozen Codex CLI controller batch.

    Transport configuration and output-schema enforcement belong to
    ``codex_cli.invoke_codex_cli``.  This function deliberately contains only
    controller-visible scientific inputs and never creates an SDK request.
    """

    validate_controller_visible_inputs(
        sanitized_catalog=sanitized_catalog,
        metric_catalog=metric_catalog,
        aggregate_ledger=aggregate_ledger,
        current_slot_contracts=current_slot_contracts,
        budget=budget,
    )
    _validate_repair_context(repair_context)
    visible_payload = {
        "sanitized_catalog": sanitized_catalog,
        "metric_catalog": metric_catalog,
        "aggregate_ledger": list(aggregate_ledger),
        "current_slot_contracts": list(current_slot_contracts),
        "budget": budget,
    }
    input_text = canonical_json_bytes(visible_payload).decode("utf-8")
    # Keep the strict response schema public and frozen independently of the
    # score-blind prompt.  ``invoke_codex_cli`` receives that schema by path.
    controller_response_schema_for_slot_count(len(current_slot_contracts))
    prompt_sections = [
        CONTROLLER_SYSTEM_PROMPT,
        "Return only the JSON object required by the frozen output schema.",
        "Controller-visible JSON follows:\n" + input_text,
    ]
    if repair_context is not None:
        prompt_sections.append(
            "Structural repair context follows:\n"
            + canonical_json_bytes(
                {
                    "repair_context": dict(repair_context),
                    "instruction": REPAIR_INSTRUCTION,
                }
            ).decode("utf-8")
        )
    return "\n\n".join(prompt_sections)


def _parse_controller_decision(
    payload: object,
    *,
    sanitized_catalog: Mapping[str, object],
    metric_catalog: Mapping[str, object],
    current_slot_contract: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _DECISION_REQUIRED:
        raise FoundationEpisodeError("controller decision does not match strict schema")
    if payload["action"] not in {"propose_candidate", "stop"}:
        raise FoundationEpisodeError("controller decision action is invalid")
    slot = payload["slot"]
    if (
        isinstance(slot, bool)
        or not isinstance(slot, int)
        or slot != current_slot_contract.get("slot")
    ):
        raise FoundationEpisodeError(
            "controller decision does not target its frozen slot"
        )
    if not isinstance(payload["rationale"], str) or not payload["rationale"].strip():
        raise FoundationEpisodeError("controller decision rationale is invalid")
    optional_fields = ("classifier_key", "term_index", "hypothesis", "falsifier")
    if slot <= 8 and payload["action"] != "propose_candidate":
        raise FoundationEpisodeError("coverage slots must propose a candidate")
    if payload["action"] == "stop":
        if any(payload[field] is not None for field in optional_fields):
            raise FoundationEpisodeError("stop actions must use null proposal fields")
        return payload
    if any(payload[field] is None for field in optional_fields):
        raise FoundationEpisodeError(
            "candidate proposal must include executable fields"
        )
    classifier_key = payload["classifier_key"]
    term_index = payload["term_index"]
    if not isinstance(classifier_key, str) or not isinstance(term_index, int):
        raise FoundationEpisodeError("candidate proposal classifier fields are invalid")
    if not isinstance(payload["hypothesis"], str) or not payload["hypothesis"].strip():
        raise FoundationEpisodeError("candidate proposal hypothesis is invalid")
    if not isinstance(payload["falsifier"], str) or not payload["falsifier"].strip():
        raise FoundationEpisodeError("candidate proposal falsifier is invalid")
    runnable = {
        str(entry["classifier_key"]): str(entry["stratum"])
        for entry in sanitized_catalog.get("classifier_catalog", [])
        if isinstance(entry, Mapping) and entry.get("runnable") is True
    }
    if classifier_key not in runnable:
        raise FoundationEpisodeError("candidate proposal classifier is not runnable")
    allowed_terms = {
        term.get("term_index")
        for term in metric_catalog.get("terms", [])
        if isinstance(term, Mapping)
    }
    if term_index not in allowed_terms:
        raise FoundationEpisodeError("candidate proposal term is not in metric catalog")
    required_stratum = current_slot_contract.get("required_stratum")
    if required_stratum is not None and runnable[classifier_key] != required_stratum:
        raise FoundationEpisodeError("candidate violates its frozen coverage stratum")
    return payload


def parse_controller_batch_decisions(
    response_text: str,
    *,
    sanitized_catalog: Mapping[str, object],
    metric_catalog: Mapping[str, object],
    current_slot_contracts: Sequence[object],
) -> list[dict[str, object]]:
    """Validate one strict fixed-length controller batch before runner use."""

    contracts, _, _ = _validate_slot_contracts(current_slot_contracts)
    _validate_catalog(sanitized_catalog)
    _validate_metric_catalog(metric_catalog)
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise FoundationEpisodeError("controller response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"decisions"}:
        raise FoundationEpisodeError("controller response does not match batch schema")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != len(contracts):
        raise FoundationEpisodeError(
            "controller response length does not match frozen batch"
        )
    parsed: list[dict[str, object]] = []
    stopped = False
    for decision, contract in zip(decisions, contracts, strict=True):
        parsed_decision = _parse_controller_decision(
            decision,
            sanitized_catalog=sanitized_catalog,
            metric_catalog=metric_catalog,
            current_slot_contract=contract,
        )
        if parsed_decision["action"] == "stop":
            stopped = True
        else:
            if stopped:
                raise FoundationEpisodeError(
                    "adaptive batch cannot propose after a stop decision"
                )
        parsed.append(parsed_decision)
    return parsed


def parse_controller_decision(
    response_text: str,
    *,
    sanitized_catalog: Mapping[str, object],
    metric_catalog: Mapping[str, object],
    current_slot_contract: Mapping[str, object],
) -> dict[str, object]:
    """Compatibility parser for unit-level validation; runners use batch parsing."""

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise FoundationEpisodeError("controller response is not valid JSON") from exc
    _validate_catalog(sanitized_catalog)
    _validate_metric_catalog(metric_catalog)
    return _parse_controller_decision(
        payload,
        sanitized_catalog=sanitized_catalog,
        metric_catalog=metric_catalog,
        current_slot_contract=current_slot_contract,
    )


__all__ = [
    "CONTROLLER_MODEL",
    "CONTROLLER_PRIMARY_BATCH_SLOTS",
    "CONTROLLER_RESPONSE_SCHEMA",
    "CONTROLLER_SCHEMA_NAME",
    "CONTROLLER_SYSTEM_PROMPT",
    "REPAIR_INSTRUCTION",
    "REPAIR_VALIDATION_ERROR_CODES",
    "build_controller_prompt",
    "controller_response_schema_for_slot_count",
    "parse_controller_batch_decisions",
    "parse_controller_decision",
    "validate_controller_visible_inputs",
]
