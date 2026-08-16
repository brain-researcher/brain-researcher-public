"""Authorized, resumable MVE-100 v2 discovery execution.

The runner consumes only the ordinary preflight records and a separately edited
authorization file.  It is intentionally a small sequential state machine:
one GPU, one evaluation at a time, 100 terminal receipts, and no confirmation.
"""

from __future__ import annotations

import csv
import json
import math
import os
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from brain_researcher.research.predictive.foundation_episode import codex_cli
from brain_researcher.research.predictive.foundation_episode.codex_cli import (
    CodexCLIError,
    CodexCLIResult,
    CodexCLIValidationError,
    build_codex_cli_argv,
    invoke_codex_cli,
    verify_codex_cli_version,
)
from brain_researcher.research.predictive.foundation_episode.contracts import (
    AUTHORIZATION_SCHEMA,
    CANDIDATE_RECEIPT_COUNT,
    CONTROLLER_BATCH_ORDER,
    CONTROLLER_CALL_BUDGETS,
    CONTROLLER_PRIMARY_BATCH_SLOTS,
    DISCOVERY_SCOPE,
    EPISODE_ID,
    HOST_SLOT_CHAMPION_REPARTITION,
    HOST_SLOT_FALSIFIER,
    HOST_SLOT_POSITIVE_CONTROL,
    HOST_SLOT_RUNNER_UP_REPARTITION,
    ICA_TARGET_COLUMNS,
    PARTITION_SEED,
    PHASE_AWAITING_DISCOVERY_AUTHORIZATION,
    PUBLIC_CLAIM_BOUNDARY_FIELDS,
    RECEIPT_COUNT,
    SEARCH_ALPHA_STAGES,
    TARGET_NAME,
    V1_EPISODE_ID,
    V1_EXCLUDED_CANDIDATE_PAIRS,
    FoundationEpisodeError,
    controller_cadence_batches,
)
from brain_researcher.research.predictive.foundation_episode.controller import (
    build_controller_prompt,
    controller_response_schema_for_slot_count,
    parse_controller_batch_decisions,
)
from brain_researcher.research.predictive.foundation_episode.evaluator import (
    EvaluationReceipt,
    controller_aggregate,
    evaluate_fresh_fit,
)

RUNNER_SCHEMA = "br.foundation_episode.discovery_runner.v2"
STATE_SCHEMA = "br.foundation_episode.discovery_state.v2"
SLOT_RECEIPT_SCHEMA = "br.foundation_episode.discovery_slot_receipt.v2"
MAX_WALLTIME_SECONDS = 12 * 60 * 60
_PRIVATE_METRIC_KEYS = {
    "primary_signed_pearson_r",
    "mean_fold_signed_pearson_r",
    "mean_fold_r2",
    "mean_fold_mae",
    "pooled_signed_pearson_r",
    "mean_fold_calibration_slope",
    "pooled_oof_calibration_slope",
}
_CONTROLLER_METRIC_KEYS = _PRIVATE_METRIC_KEYS - {
    "mean_fold_calibration_slope",
    "pooled_oof_calibration_slope",
}
_AGGREGATE_KEYS = {
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


class DiscoveryRunnerError(FoundationEpisodeError):
    """A discovery-only execution gate failed."""


class _ControllerTransportError(DiscoveryRunnerError):
    """A controller request did not return a response to validate."""


class _ControllerSchemaError(DiscoveryRunnerError):
    """A controller response remained invalid after its one repair attempt."""


@dataclass(frozen=True, slots=True)
class _RecordedControllerCall:
    """Sanitized durable outcome for one non-retriable CLI invocation."""

    status: str
    final_json: str | None = None
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class _ControllerBatchFailure:
    """The terminal paired-receipt outcome derived from CLI tombstones."""

    failure_type: str
    error_type: str


@dataclass(frozen=True, slots=True)
class DiscoveryAuthorization:
    bundle_dir: Path
    authorization: Mapping[str, object]
    artifacts: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class DiscoveryRunResult:
    bundle_dir: Path
    state_path: Path
    receipt_dir: Path
    receipt_count: int
    phase: str
    protocol_complete: bool
    episode_valid: bool
    confirmation_started: bool
    sealed_holdout_target_used: bool


def _require_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DiscoveryRunnerError(f"{label} must be non-empty stripped text")
    return value


def _regular_file(path: Path, *, label: str) -> Path:
    candidate = Path(path)
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError as exc:
        raise DiscoveryRunnerError(f"{label} is missing") from exc
    if candidate.is_symlink() or not stat.S_ISREG(mode):
        raise DiscoveryRunnerError(f"{label} must be a regular file")
    return candidate


def _regular_directory(path: Path, *, label: str) -> Path:
    candidate = Path(path)
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError as exc:
        raise DiscoveryRunnerError(f"{label} is missing") from exc
    if candidate.is_symlink() or not stat.S_ISDIR(mode):
        raise DiscoveryRunnerError(f"{label} must be a real directory")
    return candidate


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    _regular_file(path, label=label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryRunnerError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise DiscoveryRunnerError(f"{label} must be a JSON object")
    return payload


def _atomic_json(
    path: Path, payload: Mapping[str, object], *, mode: int = 0o600
) -> None:
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_paths() -> dict[str, str]:
    return {
        "episode_contract": "episode_contract.json",
        "input_manifest": "input_manifest.json",
        "private_split_plan": "private/split_plan.private.json",
        "public_split_plan": "public/split_plan.public.json",
        "sanitized_catalog": "public/sanitized_catalog.json",
        "metric_catalog": "public/metric_catalog.json",
        "controller_prompt": "public/controller_prompt.json",
        "controller_output_schema": "public/controller_output_schema.json",
        "controller_transport": "public/controller_transport.json",
        "controller_liveness": "private/controller_liveness.json",
        "timing_probe": "timing_probe.json",
        "environment_manifest": "environment_manifest.json",
        "runtime_inputs": "private/runtime_inputs.json",
        "preflight": "preflight.json",
    }


def _placeholder(value: str) -> bool:
    return value.casefold().replace("-", "_").replace(" ", "_") in {
        "fill_by_human",
        "placeholder",
        "todo",
        "tbd",
        "unknown",
        "not_authorized",
    }


def _excluded_candidate_pair_records() -> list[dict[str, object]]:
    return [
        {"classifier_key": classifier_key, "term_index": term_index}
        for classifier_key, term_index in sorted(V1_EXCLUDED_CANDIDATE_PAIRS)
    ]


def _validate_v2_round_binding(contract: Mapping[str, object]) -> None:
    """Require the score-blind v1 reuse/exclusion boundary for this v2 round."""

    if contract.get("seed") != PARTITION_SEED:
        raise DiscoveryRunnerError("contract does not freeze the v1 partition seed")
    prior = contract.get("prior_round_binding")
    expected_prior = {
        "v1_episode_id": V1_EPISODE_ID,
        "partition_reuse": "required_same_seed_reconstructed_group_partition",
        "partition_seed": PARTITION_SEED,
        "replication_seed": PARTITION_SEED + 1,
        "controller_visibility": "prior_candidate_pairs_only_no_v1_outcomes",
        "v1_artifact_write": "forbidden",
        "sealed_holdout_access": "forbidden",
    }
    if prior != expected_prior:
        raise DiscoveryRunnerError("contract lacks the frozen v1 round binding")
    hypothesis_space = contract.get("hypothesis_space")
    if not isinstance(hypothesis_space, Mapping) or set(hypothesis_space) != {
        "runnable_classifier_count",
        "metric_term_count",
        "candidate_axis",
        "unique_pair_within_round",
        "excluded_v1_candidate_pairs",
        "forbidden_expansions",
    }:
        raise DiscoveryRunnerError("contract lacks the frozen v2 hypothesis space")
    if (
        hypothesis_space.get("runnable_classifier_count") != 21
        or hypothesis_space.get("metric_term_count") != 76
        or hypothesis_space.get("candidate_axis")
        != "one_runnable_classifier_key_x_one_metric_term_index"
        or hypothesis_space.get("unique_pair_within_round") is not True
        or hypothesis_space.get("excluded_v1_candidate_pairs")
        != _excluded_candidate_pair_records()
        or hypothesis_space.get("forbidden_expansions")
        != [
            "new_classifier_axis",
            "new_metric_axis",
            "hyperparameter_search_axis",
            "sealed_holdout_access",
        ]
    ):
        raise DiscoveryRunnerError("contract has an invalid v2 hypothesis space")


def _validate_protocol(
    contract: Mapping[str, object],
) -> tuple[list[dict[str, object]], Mapping[str, object]]:
    schedule = contract.get("receipt_schedule")
    gates = contract.get("selection_and_gates")
    resource = contract.get("resource_tool_gate")
    evaluator = contract.get("evaluator")
    search_alpha = contract.get("search_alpha_allocation")
    if (
        not isinstance(schedule, list)
        or len(schedule) != RECEIPT_COUNT
        or not isinstance(gates, Mapping)
        or not isinstance(resource, Mapping)
        or not isinstance(evaluator, Mapping)
        or not isinstance(search_alpha, Mapping)
    ):
        raise DiscoveryRunnerError("episode contract lacks the MVE-100 protocol")
    slots: list[dict[str, object]] = []
    for expected, raw in enumerate(schedule, start=1):
        if not isinstance(raw, Mapping) or raw.get("slot") != expected:
            raise DiscoveryRunnerError(
                "receipt schedule is not exactly 100 continuous slots"
            )
        slots.append(dict(raw))
    host_slots = slots[CANDIDATE_RECEIPT_COUNT:]
    expected_host_slots = [
        {
            "slot": HOST_SLOT_CHAMPION_REPARTITION,
            "kind": "champion_repartition_split_robustness_check",
            "batch": "repartition_split_robustness",
            "proposal_batch": "repartition_split_robustness_batch",
            "evidence_release": "aggregate_through_slot_96",
            "ledger_cutoff_slot": CANDIDATE_RECEIPT_COUNT,
            "requires_prior_aggregate": True,
            "required_stratum": None,
        },
        {
            "slot": HOST_SLOT_RUNNER_UP_REPARTITION,
            "kind": "different_stratum_runner_up_repartition_split_robustness_check",
            "batch": "repartition_split_robustness",
            "proposal_batch": "repartition_split_robustness_batch",
            "evidence_release": "aggregate_through_slot_96",
            "ledger_cutoff_slot": CANDIDATE_RECEIPT_COUNT,
            "requires_prior_aggregate": True,
            "required_stratum": None,
        },
        {
            "slot": HOST_SLOT_FALSIFIER,
            "kind": "family_block_shuffle",
            "batch": "falsifier",
            "proposal_batch": "falsifier_batch",
            "evidence_release": "aggregate_through_slot_96",
            "ledger_cutoff_slot": CANDIDATE_RECEIPT_COUNT,
            "requires_prior_aggregate": True,
            "required_stratum": None,
        },
        {
            "slot": HOST_SLOT_POSITIVE_CONTROL,
            "kind": "synthetic_positive_control",
            "batch": "positive_control",
            "proposal_batch": "positive_control_batch",
            "evidence_release": "none",
            "ledger_cutoff_slot": 0,
            "requires_prior_aggregate": False,
            "required_stratum": None,
        },
    ]
    if host_slots != expected_host_slots:
        raise DiscoveryRunnerError("receipt schedule lacks the frozen v2 host slots")
    cadence = controller_cadence_batches()
    for expected_batch in cadence:
        batch = expected_batch["batch"]
        expected_slots = expected_batch["slots"]
        expected_cutoff = expected_batch["ledger_cutoff_slot"]
        batch_slots = [
            slot
            for slot in slots[:CANDIDATE_RECEIPT_COUNT]
            if slot.get("proposal_batch") == batch
        ]
        if [slot.get("slot") for slot in batch_slots] != expected_slots:
            raise DiscoveryRunnerError("receipt schedule violates controller cadence")
        for slot in batch_slots:
            number = slot["slot"]
            is_coverage = isinstance(number, int) and number <= 8
            if (
                slot.get("batch") != batch
                or slot.get("ledger_cutoff_slot") != expected_cutoff
                or slot.get("requires_prior_aggregate") is not (expected_cutoff > 0)
                or slot.get("evidence_release")
                != (
                    "none"
                    if expected_cutoff == 0
                    else f"aggregate_through_slot_{expected_cutoff}"
                )
                or slot.get("kind")
                != ("coverage_stratum" if is_coverage else "adaptive_candidate")
            ):
                raise DiscoveryRunnerError(
                    "receipt schedule has invalid batch evidence"
                )
    if contract.get("proposal_batches") != cadence:
        raise DiscoveryRunnerError("proposal batches do not match controller cadence")
    _validate_v2_round_binding(contract)
    evidence_release = contract.get("evidence_release")
    expected_evidence_batches = [
        {
            "batch": row["batch"],
            "ledger_cutoff_slot": row["ledger_cutoff_slot"],
            "score_release_after_slot": row["score_release_after_slot"],
            "no_within_batch_peeking": row["no_within_batch_peeking"],
        }
        for row in cadence
    ]
    if (
        not isinstance(evidence_release, Mapping)
        or set(evidence_release) != {"kind", "batches", "within_batch_score_visibility"}
        or evidence_release.get("kind") != "aggregate_only_frozen_batch_ledger_v1"
        or evidence_release.get("batches") != expected_evidence_batches
        or evidence_release.get("within_batch_score_visibility") != "forbidden"
    ):
        raise DiscoveryRunnerError("evidence release does not match controller cadence")
    if (
        resource.get("max_walltime_hours") != 12
        or resource.get("receipt_slots") != RECEIPT_COUNT
        or resource.get("evaluation_concurrency") != 1
        or resource.get("gpu_count") != 1
        or any(
            resource.get(key) != value for key, value in CONTROLLER_CALL_BUDGETS.items()
        )
    ):
        raise DiscoveryRunnerError(
            "contract does not freeze the single-GPU walltime gate"
        )
    outer = evaluator.get("outer_cv")
    inner = evaluator.get("inner_cv")
    if (
        not isinstance(outer, Mapping)
        or not isinstance(inner, Mapping)
        or outer.get("kind") != "GroupKFold"
        or outer.get("n_splits") != 5
        or inner.get("kind") != "GroupKFold"
        or inner.get("n_splits") != 3
    ):
        raise DiscoveryRunnerError("contract does not freeze 5x3 GroupKFold")
    if [slot.get("required_stratum") for slot in slots[:8]] != [
        "classical",
        "cpm",
        "tree",
        "shallow",
        "cnn",
        "gnn",
        "transformer",
        "structure-aware",
    ]:
        raise DiscoveryRunnerError("coverage slots do not freeze eight strata")
    _validate_search_alpha_allocation(search_alpha)
    claim_boundary = contract.get("claim_boundary")
    public_result = contract.get("public_episode_result")
    if (
        not isinstance(claim_boundary, Mapping)
        or any(
            not isinstance(claim_boundary.get(field), str)
            or not claim_boundary[field].strip()
            for field in PUBLIC_CLAIM_BOUNDARY_FIELDS[:-1]
        )
        or not isinstance(claim_boundary.get("explicit_nonclaims"), list)
        or not claim_boundary["explicit_nonclaims"]
        or any(
            not isinstance(item, str) or not item.strip()
            for item in claim_boundary["explicit_nonclaims"]
        )
        or not isinstance(public_result, Mapping)
        or public_result.get("claim_boundary_source")
        != "episode_contract.claim_boundary"
        or public_result.get("required_claim_boundary_fields")
        != list(PUBLIC_CLAIM_BOUNDARY_FIELDS)
    ):
        raise DiscoveryRunnerError("contract has an invalid public claim boundary")
    champion = gates.get("champion")
    runner_up = gates.get("different_classifier_stratum_runner_up")
    repartition = gates.get("slots_97_98_repartition_split_robustness")
    falsifier = gates.get("slot_99_falsifier")
    if (
        not isinstance(champion, Mapping)
        or champion.get("selection") != "max_mean_signed_r"
        or champion.get("tie_breaker") != "lowest_slot"
    ):
        raise DiscoveryRunnerError("contract has an invalid champion rule")
    if (
        not isinstance(runner_up, Mapping)
        or runner_up.get("selection") != "max_mean_signed_r"
        or runner_up.get("must_differ_from_champion") != "classifier_stratum"
    ):
        raise DiscoveryRunnerError("contract has an invalid runner-up rule")
    if (
        not isinstance(repartition, Mapping)
        or repartition.get("evaluation_population") != "same_discovery_subjects"
        or repartition.get("split_plan") != "prebound_alternative_seeded_groupkfold_5x3"
        or repartition.get("is_independent_replication") is not False
        or repartition.get("is_fresh_subject_replication") is not False
    ):
        raise DiscoveryRunnerError(
            "contract has an invalid same-cohort robustness rule"
        )
    if (
        not isinstance(falsifier, Mapping)
        or falsifier.get("source") != "champion"
        or falsifier.get("control_mode") != "family_block_shuffle"
        or falsifier.get("runs") != 1
    ):
        raise DiscoveryRunnerError("contract has an invalid slot-99 falsifier")
    positive = gates.get("slot_100_positive_control")
    if (
        not isinstance(positive, Mapping)
        or positive.get("classifier_key") != "ridge"
        or positive.get("term_index") != 0
        or positive.get("synthetic_target") != "raw_edge_0"
        or positive.get("required_outer_fold_count") != 5
        or positive.get("all_outer_folds_must_succeed") is not True
        or positive.get("minimum_mean_signed_r") != 0.90
    ):
        raise DiscoveryRunnerError("contract has an invalid positive-control gate")
    stop_rule = gates.get("stop_rule")
    if stop_rule != {
        "coverage_slots_must_propose": list(range(1, 9)),
        "controller_stop_eligible_slots": list(
            range(9, CANDIDATE_RECEIPT_COUNT + 1)
        ),
        "decision_boundary": "frozen_two_slot_batch",
        "same_batch_after_stop": "skipped_by_controller_stop",
        "remaining_candidate_slots": "skipped_by_controller_stop",
        "host_slots_after_stop": "still_required",
        "efficacy_stop": "not_available",
    }:
        raise DiscoveryRunnerError("contract has an invalid v2 discovery stop rule")
    return slots, gates


def _validate_search_alpha_allocation(
    allocation: Mapping[str, object],
) -> list[dict[str, object]]:
    required = {
        "schema_version",
        "semantics",
        "total_alpha",
        "allocation_unit",
        "denominator",
        "score_mean_denominator",
        "failed_or_stopped_slot_policy",
        "reallocation_policy",
        "controller_cadence_independent",
        "compatibility",
        "allocations",
    }
    if (
        set(allocation) != required
        or allocation.get("schema_version")
        != "br.foundation_episode.search_budget_alpha_allocation.v1"
        or allocation.get("semantics")
        != "fraction_of_frozen_candidate_evaluation_budget_not_significance_level"
        or allocation.get("total_alpha") != 1.0
        or allocation.get("allocation_unit") != "research_stage"
        or allocation.get("denominator") != "prospectively_allocated_slots"
        or allocation.get("score_mean_denominator") != "n_scored"
        or allocation.get("failed_or_stopped_slot_policy")
        != "report_missing_never_impute_zero"
        or allocation.get("reallocation_policy")
        != "forbidden_without_versioned_contract"
        or allocation.get("controller_cadence_independent") is not True
        or allocation.get("compatibility") != "forward_only_new_episode_contract"
    ):
        raise DiscoveryRunnerError("search alpha allocation semantics are invalid")
    raw_allocations = allocation.get("allocations")
    if not isinstance(raw_allocations, list) or not raw_allocations:
        raise DiscoveryRunnerError("search alpha allocation windows are invalid")
    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_slots: set[int] = set()
    alpha_sum = 0.0
    for raw in raw_allocations:
        if not isinstance(raw, Mapping) or set(raw) != {
            "window_id",
            "slots",
            "slot_budget",
            "alpha_mass",
        }:
            raise DiscoveryRunnerError("search alpha allocation window is invalid")
        window_id = raw.get("window_id")
        slots = raw.get("slots")
        alpha_mass = raw.get("alpha_mass")
        if (
            not isinstance(window_id, str)
            or not window_id
            or window_id in seen_ids
            or not isinstance(slots, list)
            or not slots
            or any(
                isinstance(slot, bool)
                or not isinstance(slot, int)
                or not 1 <= slot <= CANDIDATE_RECEIPT_COUNT
                or slot in seen_slots
                for slot in slots
            )
            or len(set(slots)) != len(slots)
            or raw.get("slot_budget") != len(slots)
            or isinstance(alpha_mass, bool)
            or not isinstance(alpha_mass, int | float)
            or not math.isfinite(float(alpha_mass))
            or float(alpha_mass) <= 0.0
        ):
            raise DiscoveryRunnerError("search alpha allocation window is invalid")
        seen_ids.add(window_id)
        seen_slots.update(slots)
        alpha_sum += float(alpha_mass)
        normalized.append(dict(raw))
    expected_windows = [
        {
            "window_id": window_id,
            "slots": list(slots),
            "slot_budget": len(slots),
            "alpha_mass": alpha_mass,
        }
        for window_id, slots, alpha_mass in SEARCH_ALPHA_STAGES
    ]
    if (
        normalized != expected_windows
        or seen_slots != set(range(1, CANDIDATE_RECEIPT_COUNT + 1))
        or not math.isclose(alpha_sum, 1.0)
    ):
        raise DiscoveryRunnerError("search alpha allocation does not close its budget")
    return normalized


def _live_single_gpu() -> None:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DiscoveryRunnerError("torch is required to check the live GPU") from exc
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise DiscoveryRunnerError("discovery requires one live CUDA GPU")
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiscoveryRunnerError("cannot verify live GPU occupancy") from exc
    observed = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    external = observed - {str(os.getpid())}
    if completed.returncode != 0 or external:
        raise DiscoveryRunnerError("discovery requires one idle live CUDA GPU")


def _expected_controller_argv_policy() -> tuple[list[str], list[str]]:
    """Return the frozen transport policy without any run-specific paths."""

    argv = build_codex_cli_argv(
        output_schema_path="<FROZEN_OUTPUT_SCHEMA>",
        output_last_message_path="<PRIVATE_FINAL_OUTPUT>",
        scratch_dir="<EMPTY_READ_ONLY_SCRATCH>",
    )
    sanitized = list(argv)
    sanitized[0] = "<CODEX_CLI_BINARY>"
    return argv, sanitized


def _verify_controller_transport(
    artifacts: Mapping[str, Mapping[str, object]], contract: Mapping[str, object]
) -> None:
    """Require the frozen CLI identity and a successful score-blind seam.

    This is an authorization-time transport check only.  It neither supplies a
    scientific prompt nor dispatches a discovery evaluation.
    """

    controller = contract.get("controller")
    schema = artifacts["controller_output_schema"]
    transport = artifacts["controller_transport"]
    liveness = artifacts["controller_liveness"]
    expected_argv, expected_sanitized_argv = _expected_controller_argv_policy()
    required_transport = {
        "schema_version",
        "provider",
        "cli_binary",
        "cli_version",
        "model",
        "reasoning_effort",
        "argv_policy",
        "sanitized_argv_policy",
        "prompt_delivery",
        "output_schema_artifact",
        "output_last_message",
        "working_directory",
        "tool_event_policy",
        "strict_json_schema",
        "event_audit",
    }
    if (
        not isinstance(controller, Mapping)
        or schema != controller_response_schema_for_slot_count(2)
        or set(transport) != required_transport
        or transport.get("schema_version")
        != "br.foundation_episode.controller_transport.v1"
        or transport.get("provider") != "codex.cli"
        or transport.get("cli_binary") != codex_cli.CODEX_CLI_BINARY
        or transport.get("cli_version") != codex_cli.CODEX_CLI_VERSION
        or transport.get("model") != codex_cli.CODEX_CLI_MODEL
        or transport.get("reasoning_effort") != codex_cli.CODEX_CLI_REASONING_EFFORT
        or transport.get("argv_policy") != expected_argv
        or transport.get("sanitized_argv_policy") != expected_sanitized_argv
        or transport.get("prompt_delivery") != "stdin_only"
        or transport.get("output_schema_artifact")
        != "public/controller_output_schema.json"
        or transport.get("output_last_message") != "temporary_private_file"
        or transport.get("working_directory") != "fresh_empty_read_only_scratch"
        or transport.get("tool_event_policy") != "forbidden_fail_closed"
        or transport.get("strict_json_schema") is not True
        or transport.get("event_audit") != {"format": "jsonl", "complete": True}
        or controller.get("provider") != transport["provider"]
        or controller.get("cli_binary") != transport["cli_binary"]
        or controller.get("model") != transport["model"]
        or controller.get("reasoning_effort") != transport["reasoning_effort"]
        or controller.get("skill_search_enabled") is not False
        or controller.get("skills_include_instructions") is not False
        or controller.get("tool_event_policy") != transport["tool_event_policy"]
        or controller.get("strict_json_schema") is not True
        or controller.get("event_audit") != transport["event_audit"]
    ):
        raise DiscoveryRunnerError("frozen Codex CLI controller transport is invalid")
    required_liveness = {
        "schema_version",
        "score_blind",
        "target_values_seen",
        "passed",
        "final_json",
        "sanitized_argv",
        "cli_version",
        "validation_result",
        "tool_event_count",
    }
    if (
        set(liveness) != required_liveness
        or liveness.get("schema_version")
        != "br.foundation_episode.controller_liveness.v1"
        or liveness.get("score_blind") is not True
        or liveness.get("target_values_seen") is not False
        or liveness.get("passed") is not True
        or liveness.get("final_json") != '{"liveness":"SYNTHETIC_OK"}'
        or liveness.get("sanitized_argv") != expected_sanitized_argv
        or liveness.get("cli_version") != codex_cli.CODEX_CLI_VERSION
        or liveness.get("validation_result")
        != {
            "event_stream": "valid",
            "final_json": "valid_json_object",
            "strict_output_schema": True,
        }
        or liveness.get("tool_event_count") != 0
    ):
        raise DiscoveryRunnerError("score-blind Codex CLI liveness evidence is invalid")
    try:
        observed_version = verify_codex_cli_version()
    except CodexCLIError as exc:
        raise DiscoveryRunnerError("Codex CLI launch recheck failed") from exc
    if observed_version != transport["cli_version"]:
        raise DiscoveryRunnerError("Codex CLI version changed after preflight")


def _verify_discovery_authorization(
    bundle_dir: Path | str,
    authorization_path: Path | str,
    *,
    require_live_gpu: bool,
) -> DiscoveryAuthorization:
    """Verify the human authorization and frozen preflight gates."""

    bundle = _regular_directory(Path(bundle_dir), label="bundle directory")
    artifacts = {
        name: _read_json(bundle / relative, label=name)
        for name, relative in _artifact_paths().items()
    }
    contract = artifacts["episode_contract"]
    if contract.get("episode_id") != EPISODE_ID:
        raise DiscoveryRunnerError("episode contract identity is invalid")
    _validate_protocol(contract)
    private_split_plan = artifacts["private_split_plan"]
    if (
        contract.get("seed") != PARTITION_SEED
        or private_split_plan.get("seed") != PARTITION_SEED
        or private_split_plan.get("replication_seed") != PARTITION_SEED + 1
    ):
        raise DiscoveryRunnerError("v2 must reuse the frozen v1 partition seeds")
    preflight = artifacts["preflight"]
    if (
        preflight.get("episode_id") != EPISODE_ID
        or preflight.get("scope") != DISCOVERY_SCOPE
        or preflight.get("phase") != PHASE_AWAITING_DISCOVERY_AUTHORIZATION
        or preflight.get("launch_ready") is not True
        or preflight.get("five_probes_passed") is not True
        or preflight.get("controller_liveness_passed") is not True
        or preflight.get("one_idle_gpu") is not True
    ):
        raise DiscoveryRunnerError("preflight is not launch-ready for discovery")
    _verify_controller_transport(artifacts, contract)
    probes = artifacts["timing_probe"].get("probes")
    if (
        not isinstance(probes, list)
        or len(probes) != 5
        or any(
            not isinstance(row, Mapping) or row.get("passed") is not True
            for row in probes
        )
    ):
        raise DiscoveryRunnerError("five score-blind engine probes did not all pass")
    gpu = artifacts["environment_manifest"].get("gpu")
    if (
        not isinstance(gpu, Mapping)
        or gpu.get("cuda_available") is not True
        or gpu.get("device_count") != 1
    ):
        raise DiscoveryRunnerError("preflight did not record exactly one CUDA GPU")
    if require_live_gpu:
        _live_single_gpu()
    authorization = _read_json(
        Path(authorization_path), label="discovery authorization"
    )
    required = {
        "schema_version",
        "episode_id",
        "scope",
        "authorized",
        "authorization_id",
        "authorized_by",
        "rationale",
        "confirmation_authorization",
    }
    if (
        set(authorization) != required
        or authorization.get("schema_version") != AUTHORIZATION_SCHEMA
        or authorization.get("episode_id") != EPISODE_ID
        or authorization.get("scope") != DISCOVERY_SCOPE
        or authorization.get("authorized") is not True
    ):
        raise DiscoveryRunnerError("authorization is not a discovery-only grant")
    for field in ("authorization_id", "authorized_by"):
        if _placeholder(_require_text(authorization.get(field), label=field)):
            raise DiscoveryRunnerError(f"{field} is still a placeholder")
    rationale = _require_text(authorization.get("rationale"), label="rationale")
    if (
        _placeholder(rationale)
        or authorization.get("confirmation_authorization") != "NOT_GRANTED"
    ):
        raise DiscoveryRunnerError(
            "authorization must explicitly leave confirmation not granted"
        )
    return DiscoveryAuthorization(
        bundle_dir=bundle, authorization=authorization, artifacts=artifacts
    )


def verify_discovery_authorization(
    bundle_dir: Path | str, authorization_path: Path | str
) -> DiscoveryAuthorization:
    """Verify authorization for a path that may dispatch discovery compute."""

    return _verify_discovery_authorization(
        bundle_dir, authorization_path, require_live_gpu=True
    )


def verify_terminal_discovery_authorization(
    bundle_dir: Path | str, authorization_path: Path | str
) -> DiscoveryAuthorization:
    """Verify authorization for exact-100, no-compute terminal finalization."""

    return _verify_discovery_authorization(
        bundle_dir, authorization_path, require_live_gpu=False
    )


def _state_path(bundle_dir: Path) -> Path:
    return bundle_dir / "private" / "discovery_state.json"


def _receipt_dir(bundle_dir: Path) -> Path:
    return bundle_dir / "private" / "discovery_receipts"


def _receipt_path(bundle_dir: Path, slot: int) -> Path:
    return _receipt_dir(bundle_dir) / f"slot_{slot:02d}.json"


def _controller_calls_dir(bundle_dir: Path) -> Path:
    return bundle_dir / "private" / "controller_calls"


def _controller_call_path(bundle_dir: Path, *, batch: str, attempt: int) -> Path:
    if batch not in CONTROLLER_BATCH_ORDER or attempt not in {0, 1}:
        raise DiscoveryRunnerError("controller journal location is invalid")
    return _controller_calls_dir(bundle_dir) / f"{batch}.{attempt}.json"


def _initial_state(authority: DiscoveryAuthorization, now: float) -> dict[str, object]:
    return {
        "schema_version": STATE_SCHEMA,
        "episode_id": EPISODE_ID,
        "authorization_id": authority.authorization["authorization_id"],
        "started_at_epoch": now,
        "deadline_epoch": now + MAX_WALLTIME_SECONDS,
        "phase": "DISCOVERING",
        "terminal_slots": [],
        "pending_batches": {},
        "controller_call_count": 0,
        "in_flight": None,
        "confirmation_started": False,
        "sealed_holdout_target_selected": False,
        "sealed_holdout_target_converted": False,
        "sealed_holdout_target_used": False,
        "evaluation_concurrency": 1,
    }


def _load_state(authority: DiscoveryAuthorization, now: float) -> dict[str, object]:
    path = _state_path(authority.bundle_dir)
    if not path.exists():
        return _initial_state(authority, now)
    state = _read_json(path, label="discovery state")
    if (
        state.get("schema_version") != STATE_SCHEMA
        or state.get("episode_id") != EPISODE_ID
        or state.get("authorization_id")
        != authority.authorization.get("authorization_id")
    ):
        raise DiscoveryRunnerError(
            "existing state belongs to another discovery authorization"
        )
    if (
        state.get("confirmation_started") is not False
        or state.get("sealed_holdout_target_selected") is not False
        or state.get("sealed_holdout_target_converted") is not False
        or state.get("sealed_holdout_target_used") is not False
        or state.get("evaluation_concurrency") != 1
    ):
        raise DiscoveryRunnerError("existing state violates discovery-only bounds")
    started = state.get("started_at_epoch")
    deadline = state.get("deadline_epoch")
    if (
        not isinstance(started, int | float)
        or not isinstance(deadline, int | float)
        or float(deadline) != float(started) + MAX_WALLTIME_SECONDS
    ):
        raise DiscoveryRunnerError("existing state has an invalid deadline")
    if not isinstance(state.get("terminal_slots"), list) or not isinstance(
        state.get("pending_batches"), Mapping
    ):
        raise DiscoveryRunnerError("existing state has invalid resume records")
    return state


def _record_state(
    authority: DiscoveryAuthorization, state: Mapping[str, object]
) -> None:
    _atomic_json(_state_path(authority.bundle_dir), state)


def _read_slot_receipts(
    authority: DiscoveryAuthorization, state: dict[str, object]
) -> dict[int, dict[str, object]]:
    receipts: dict[int, dict[str, object]] = {}
    directory = _receipt_dir(authority.bundle_dir)
    if directory.exists():
        _regular_directory(directory, label="receipt directory")
        for child in directory.iterdir():
            if not child.name.startswith("slot_") or child.suffix != ".json":
                raise DiscoveryRunnerError(
                    "receipt directory contains an unexpected file"
                )
            token = child.stem.removeprefix("slot_")
            if not token.isdigit() or not 1 <= int(token) <= RECEIPT_COUNT:
                raise DiscoveryRunnerError("receipt directory contains an invalid slot")
            slot = int(token)
            receipt = _read_json(child, label=f"slot {slot} receipt")
            if (
                receipt.get("schema_version") != SLOT_RECEIPT_SCHEMA
                or receipt.get("slot") != slot
                or receipt.get("episode_id") != EPISODE_ID
                or receipt.get("authorization_id")
                != authority.authorization.get("authorization_id")
            ):
                raise DiscoveryRunnerError(
                    "slot receipt belongs to another episode or authorization"
                )
            receipts[slot] = receipt
    observed = sorted(receipts)
    if state.get("terminal_slots") != observed:
        state["terminal_slots"] = observed
        _record_state(authority, state)
    return receipts


def _terminal_aggregate(
    *,
    slot: int,
    status: str,
    classifier_key: str = "host_closed",
    term_index: int = 0,
    control_mode: str = "observed",
    failure_type: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "foundation_episode_controller_aggregate_v1",
        "slot": slot,
        "status": status,
        "candidate_label": f"slot-{slot}:{classifier_key}:term-{term_index}",
        "classifier_key": classifier_key,
        "term_index": term_index,
        "control_mode": control_mode,
        "metrics": dict.fromkeys(sorted(_CONTROLLER_METRIC_KEYS)),
        "qc": {
            "outer_fold_count": 0,
            "completed_fold_count": 0,
            "failed_fold_count": 0,
            "all_outer_folds_succeeded": False,
            "primary_metric_available": False,
        },
        "runtime_sec": None,
        "failure_type": failure_type,
    }


def _aggregate_from_result(
    result: object, *, slot: int
) -> tuple[dict[str, object], dict[str, object]]:
    if isinstance(result, EvaluationReceipt):
        return result.to_dict(), controller_aggregate(result, slot=slot)
    if not isinstance(result, Mapping):
        raise DiscoveryRunnerError(
            "evaluator must return an EvaluationReceipt or mapping"
        )
    private = dict(result)
    required = {
        "status",
        "classifier_key",
        "term_index",
        "seed",
        "control_mode",
        "folds",
        "metrics",
        "runtime_sec",
        "error",
    }
    if set(private) != required or private.get("status") not in {"succeeded", "failed"}:
        raise DiscoveryRunnerError("evaluator mapping has an invalid shape")
    classifier = _require_text(
        private.get("classifier_key"), label="evaluator classifier"
    )
    term = private.get("term_index")
    if isinstance(term, bool) or not isinstance(term, int) or term < 0:
        raise DiscoveryRunnerError("evaluator term index is invalid")
    control = _require_text(private.get("control_mode"), label="evaluator control mode")
    folds = private.get("folds")
    metrics = private.get("metrics")
    if (
        not isinstance(folds, list)
        or not isinstance(metrics, Mapping)
        or set(metrics) != _PRIVATE_METRIC_KEYS
    ):
        raise DiscoveryRunnerError("evaluator metrics or folds are invalid")
    normalized: dict[str, float | None] = {}
    for key in sorted(_PRIVATE_METRIC_KEYS):
        value = metrics[key]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
        ):
            raise DiscoveryRunnerError("evaluator metric is non-finite")
        normalized[key] = None if value is None else float(value)
    completed = sum(
        isinstance(fold, Mapping) and fold.get("status") == "succeeded"
        for fold in folds
    )
    failed = sum(
        isinstance(fold, Mapping) and fold.get("status") == "failed" for fold in folds
    )
    aggregate = {
        "schema_version": "foundation_episode_controller_aggregate_v1",
        "slot": slot,
        "status": private["status"],
        "candidate_label": f"slot-{slot}:{classifier}:term-{term}",
        "classifier_key": classifier,
        "term_index": term,
        "control_mode": control,
        "metrics": {key: normalized[key] for key in sorted(_CONTROLLER_METRIC_KEYS)},
        "qc": {
            "outer_fold_count": len(folds),
            "completed_fold_count": completed,
            "failed_fold_count": failed,
            "all_outer_folds_succeeded": private["status"] == "succeeded"
            and failed == 0,
            "primary_metric_available": normalized["primary_signed_pearson_r"]
            is not None,
        },
        "runtime_sec": private["runtime_sec"],
        "failure_type": (
            private["error"].get("type")
            if isinstance(private["error"], Mapping)
            else None
        ),
    }
    return private, aggregate


def _write_slot(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    receipts: dict[
        int,
        dict[str, object],
    ],
    *,
    slot_contract: Mapping[str, object],
    status: str,
    origin: str,
    proposal: Mapping[str, object] | None = None,
    evaluation_receipt: Mapping[str, object] | None = None,
    aggregate: Mapping[str, object] | None = None,
    failure_type: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> None:
    slot = slot_contract.get("slot")
    if (
        isinstance(slot, bool)
        or not isinstance(slot, int)
        or not 1 <= slot <= RECEIPT_COUNT
    ):
        raise DiscoveryRunnerError("invalid slot contract")
    if slot in receipts:
        return
    if status not in {"succeeded", "failed", "stopped", "skipped"}:
        raise DiscoveryRunnerError("invalid terminal slot status")
    aggregate_classifier = "host_closed"
    aggregate_term = 0
    if proposal is not None:
        try:
            aggregate_classifier, aggregate_term = _proposal_pair(proposal)
        except DiscoveryRunnerError:
            pass
    payload = {
        "schema_version": SLOT_RECEIPT_SCHEMA,
        "slot": slot,
        "episode_id": EPISODE_ID,
        "authorization_id": authority.authorization["authorization_id"],
        "slot_contract": dict(slot_contract),
        "status": status,
        "origin": origin,
        "proposal": dict(proposal) if proposal is not None else None,
        "evaluation_receipt": (
            dict(evaluation_receipt) if evaluation_receipt is not None else None
        ),
        "controller_aggregate": (
            dict(aggregate)
            if aggregate is not None
            else _terminal_aggregate(
                slot=slot,
                status="skipped" if status in {"stopped", "skipped"} else "failed",
                classifier_key=aggregate_classifier,
                term_index=aggregate_term,
                failure_type=failure_type,
            )
        ),
        "failure_type": failure_type,
        "detail": dict(detail) if detail is not None else None,
        "confirmation_started": False,
        "sealed_holdout_target_selected": False,
        "sealed_holdout_target_converted": False,
        "sealed_holdout_target_used": False,
    }
    _atomic_json(_receipt_path(authority.bundle_dir, slot), payload)
    receipts[slot] = payload
    state["terminal_slots"] = sorted(receipts)
    _record_state(authority, state)


def _assert_ledger(ledger: Sequence[object], *, cutoff: int) -> list[dict[str, object]]:
    if len(ledger) != cutoff:
        raise DiscoveryRunnerError("controller ledger does not match its frozen cutoff")
    normalized: list[dict[str, object]] = []
    for expected, raw in enumerate(ledger, start=1):
        if (
            not isinstance(raw, Mapping)
            or set(raw) != _AGGREGATE_KEYS
            or raw.get("slot") != expected
        ):
            raise DiscoveryRunnerError(
                "controller ledger has an invalid terminal aggregate"
            )
        normalized.append(dict(raw))
    return normalized


def _rebuild_ledger(
    receipts: Mapping[int, Mapping[str, object]], *, cutoff: int
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for slot in range(1, cutoff + 1):
        receipt = receipts.get(slot)
        if receipt is None:
            break
        aggregate = receipt.get("controller_aggregate")
        if not isinstance(aggregate, Mapping):
            raise DiscoveryRunnerError("candidate receipt has no controller aggregate")
        result.append(dict(aggregate))
    return result


def _controller_stop_slot(
    receipts: Mapping[int, Mapping[str, object]],
) -> int | None:
    slots = sorted(
        slot
        for slot, receipt in receipts.items()
        if receipt.get("failure_type") == "controller_stop"
    )
    if len(slots) > 1:
        raise DiscoveryRunnerError("multiple controller stop receipts are invalid")
    return slots[0] if slots else None


class _RuntimeData:
    def __init__(self, authority: DiscoveryAuthorization) -> None:
        self.private_plan = authority.artifacts["private_split_plan"]
        self.input_manifest = authority.artifacts["input_manifest"]
        runtime = authority.artifacts["runtime_inputs"]
        self.term_cache = _regular_directory(
            Path(
                _require_text(runtime.get("term_cache_dir"), label="runtime term cache")
            ),
            label="runtime term cache",
        )
        self.target_path = _regular_file(
            Path(
                _require_text(
                    runtime.get("target_table_path"), label="runtime target table"
                )
            ),
            label="runtime target table",
        )
        self.engine_path = _regular_file(
            Path(
                _require_text(runtime.get("kernel_source_path"), label="runtime engine")
            ),
            label="runtime engine",
        )
        term_cache = self.input_manifest.get("term_cache")
        if not isinstance(term_cache, Mapping) or not isinstance(
            term_cache.get("terms"), list
        ):
            raise DiscoveryRunnerError("input manifest lacks term records")
        self.terms = {
            row.get("term_index"): row
            for row in term_cache["terms"]
            if isinstance(row, Mapping) and isinstance(row.get("term_index"), int)
        }
        target_header = self.input_manifest.get("target_table_header")
        expected_target_header = ("Subject", *ICA_TARGET_COLUMNS)
        if (
            not isinstance(target_header, list)
            or tuple(target_header) != expected_target_header
            or self.input_manifest.get("target_table_header_verified") is not True
            or self.input_manifest.get("target_subject_sequence_verified") is not True
            or self.input_manifest.get("subject_intersection_sequence_verified")
            is not True
            or self.input_manifest.get("exchangeability_subject_sequence_verified")
            is not True
            or self.input_manifest.get("family_source") != "exchangeability_manifest"
        ):
            raise DiscoveryRunnerError(
                "input manifest lacks the ICA target identity contract"
            )
        self.target_header = expected_target_header
        self._full_subject_sequence = self._all_subject_ids()
        self.discovery_rows = self._discovery_rows()
        self.global_to_local = {
            int(row["row_index"]): position
            for position, row in enumerate(self.discovery_rows)
        }
        self._groups = np.asarray(
            [str(row["family_id"]) for row in self.discovery_rows], dtype=str
        )
        self._targets: np.ndarray | None = None
        self._matrices: dict[int, np.ndarray] = {}

    def _all_subject_ids(self) -> tuple[str, ...]:
        subject_rows = self.private_plan.get("subject_rows")
        if not isinstance(subject_rows, list) or len(subject_rows) != 326:
            raise DiscoveryRunnerError("private split plan lacks all subject rows")
        rows = {
            row.get("row_index"): row
            for row in subject_rows
            if isinstance(row, Mapping) and isinstance(row.get("row_index"), int)
        }
        if set(rows) != set(range(326)):
            raise DiscoveryRunnerError("private split plan subject rows are malformed")
        subjects: list[str] = []
        for index in range(326):
            row = rows[index]
            subjects.append(_require_text(row.get("subject_id"), label="plan subject"))
            _require_text(row.get("family_id"), label="plan family")
        if len(set(subjects)) != 326:
            raise DiscoveryRunnerError("private split plan subject IDs are not unique")
        return tuple(subjects)

    def _discovery_rows(self) -> list[dict[str, object]]:
        subject_rows = self.private_plan.get("subject_rows")
        discovery = self.private_plan.get("discovery_row_indices")
        holdout = self.private_plan.get("sealed_holdout_row_indices")
        if (
            not isinstance(subject_rows, list)
            or not isinstance(discovery, list)
            or not isinstance(holdout, list)
        ):
            raise DiscoveryRunnerError("private split plan is malformed")
        discovery_set = set(discovery)
        if not discovery_set or discovery_set & set(holdout):
            raise DiscoveryRunnerError(
                "private split plan violates the sealed holdout boundary"
            )
        rows = {
            row.get("row_index"): dict(row)
            for row in subject_rows
            if isinstance(row, Mapping) and isinstance(row.get("row_index"), int)
        }
        if set(rows) != discovery_set | set(holdout):
            raise DiscoveryRunnerError(
                "private split plan does not close over its subject rows"
            )
        result = [rows[index] for index in sorted(discovery_set)]
        for row in result:
            _require_text(row.get("subject_id"), label="discovery subject")
            _require_text(row.get("family_id"), label="discovery family")
        return result

    def groups_only(self) -> np.ndarray:
        return self._groups

    def _verify_target_subject_sequence(self) -> None:
        """Verify all target identities before selecting discovery target values."""

        try:
            with self.target_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = tuple(next(reader, ()))
                if header != self.target_header:
                    raise DiscoveryRunnerError("runtime target table header is invalid")
                subject_column = header.index("Subject")
                subjects: list[str] = []
                seen: set[str] = set()
                for row in reader:
                    if len(row) != len(header):
                        raise DiscoveryRunnerError(
                            "runtime target table row is malformed"
                        )
                    subject = row[subject_column].strip()
                    if not subject or subject in seen:
                        raise DiscoveryRunnerError(
                            "runtime target table Subject values are invalid"
                        )
                    seen.add(subject)
                    subjects.append(subject)
        except DiscoveryRunnerError:
            raise
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise DiscoveryRunnerError("cannot read runtime target identities") from exc
        if tuple(subjects) != self._full_subject_sequence:
            raise DiscoveryRunnerError(
                "runtime target Subject order differs from the frozen split plan"
            )

    def targets_and_groups(self) -> tuple[np.ndarray, np.ndarray]:
        if self._targets is not None:
            return self._targets, self._groups
        self._verify_target_subject_sequence()
        wanted = {str(row["subject_id"]): row for row in self.discovery_rows}
        values: dict[str, float] = {}
        try:
            with self.target_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = tuple(next(reader, ()))
                if header != self.target_header:
                    raise DiscoveryRunnerError("runtime target table header is invalid")
                subject_column = header.index("Subject")
                target_column = header.index(TARGET_NAME)
                for row in reader:
                    if len(row) != len(header):
                        raise DiscoveryRunnerError(
                            "runtime target table row is malformed"
                        )
                    subject = row[subject_column].strip()
                    plan_row = wanted.get(subject)
                    if plan_row is None:
                        continue
                    value = float(row[target_column])
                    if not math.isfinite(value) or subject in values:
                        raise DiscoveryRunnerError(
                            "discovery endpoint value is invalid"
                        )
                    values[subject] = value
        except DiscoveryRunnerError:
            raise
        except (OSError, UnicodeDecodeError, csv.Error, ValueError) as exc:
            raise DiscoveryRunnerError("cannot read discovery target values") from exc
        if set(values) != set(wanted):
            raise DiscoveryRunnerError("target table lacks a discovery endpoint")
        self._targets = np.asarray(
            [values[str(row["subject_id"])] for row in self.discovery_rows],
            dtype=np.float64,
        )
        return self._targets, self._groups

    def matrix(self, term_index: int) -> np.ndarray:
        if term_index in self._matrices:
            return self._matrices[term_index]
        record = self.terms.get(term_index)
        if not isinstance(record, Mapping):
            raise DiscoveryRunnerError(
                "proposed term is absent from the 76-term input manifest"
            )
        filename = _require_text(record.get("file"), label="term filename")
        path = _regular_file(self.term_cache / filename, label="term matrix")
        dataset_name = _require_text(record.get("dataset"), label="term dataset")
        try:
            import h5py

            with h5py.File(path, "r") as handle:
                matrix = np.asarray(
                    handle[dataset_name][
                        np.asarray(
                            [int(row["row_index"]) for row in self.discovery_rows],
                            dtype=np.int64,
                        ),
                        :,
                    ],
                    dtype=np.float32,
                )
        except Exception as exc:
            raise DiscoveryRunnerError(
                "cannot read discovery rows from a term matrix"
            ) from exc
        if matrix.shape[0] != len(self.discovery_rows) or not np.all(
            np.isfinite(matrix)
        ):
            raise DiscoveryRunnerError("discovery matrix is invalid")
        matrix.setflags(write=False)
        self._matrices[term_index] = matrix
        return matrix

    def project_plan(
        self, raw_plan: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        plan = self.private_plan if raw_plan is None else raw_plan
        outer = plan.get("outer_folds")
        if not isinstance(outer, list):
            raise DiscoveryRunnerError("split plan has no outer folds")

        def local(indices: object) -> list[int]:
            if not isinstance(indices, list):
                raise DiscoveryRunnerError("split indices are invalid")
            try:
                return [self.global_to_local[int(index)] for index in indices]
            except (KeyError, TypeError, ValueError) as exc:
                raise DiscoveryRunnerError(
                    "split plan references a sealed row"
                ) from exc

        projected: list[dict[str, object]] = []
        for outer_index, outer_fold in enumerate(outer, start=1):
            if not isinstance(outer_fold, Mapping) or not isinstance(
                outer_fold.get("inner_folds"), list
            ):
                raise DiscoveryRunnerError("outer split fold is invalid")
            inner_rows: list[dict[str, object]] = []
            for inner_index, inner_fold in enumerate(
                outer_fold["inner_folds"], start=1
            ):
                if not isinstance(inner_fold, Mapping):
                    raise DiscoveryRunnerError("inner split fold is invalid")
                inner_rows.append(
                    {
                        "fold_id": inner_fold.get("fold_id", f"inner_{inner_index}"),
                        "train_indices": local(
                            inner_fold.get(
                                "train_row_indices", inner_fold.get("train_indices")
                            )
                        ),
                        "test_indices": local(
                            inner_fold.get(
                                "test_row_indices", inner_fold.get("test_indices")
                            )
                        ),
                    }
                )
            projected.append(
                {
                    "fold_id": outer_fold.get("fold_id", f"outer_{outer_index}"),
                    "train_indices": local(
                        outer_fold.get(
                            "train_row_indices", outer_fold.get("train_indices")
                        )
                    ),
                    "test_indices": local(
                        outer_fold.get(
                            "test_row_indices", outer_fold.get("test_indices")
                        )
                    ),
                    "inner_folds": inner_rows,
                }
            )
        result = {
            "schema_version": plan.get(
                "schema_version", "foundation_episode_group_split_plan_v2"
            ),
            "splitter": plan.get("splitter", "GroupKFold"),
            "evaluation_indices": list(range(len(self.discovery_rows))),
            "outer_folds": projected,
        }
        if result["splitter"] == "SeededGroupKFold":
            result["seed"] = plan.get("seed")
            result["assignment_algorithm"] = plan.get("assignment_algorithm")
        return result


def _batch_slots(
    schedule: Sequence[Mapping[str, object]], batch: str
) -> list[dict[str, object]]:
    return [dict(slot) for slot in schedule if slot.get("proposal_batch") == batch]


def _proposal_pair(proposal: Mapping[str, object]) -> tuple[str, int]:
    classifier = _require_text(
        proposal.get("classifier_key"), label="proposal classifier"
    )
    term = proposal.get("term_index")
    if isinstance(term, bool) or not isinstance(term, int) or term < 0:
        raise DiscoveryRunnerError("proposal term is invalid")
    return classifier, term


def _validation_error_code(exc: Exception) -> str:
    message = str(exc).lower()
    if "not valid json" in message:
        return "invalid_json"
    if "length" in message and "batch" in message:
        return "response_batch_length_mismatch"
    if "duplicate" in message:
        return "duplicate_candidate"
    if "after a stop" in message:
        return "proposal_after_stop"
    if "schema" in message or "response" in message or "decision" in message:
        return "response_schema_mismatch"
    return "decision_contract_violation"


def _read_controller_call(
    authority: DiscoveryAuthorization, *, batch: str, attempt: int
) -> _RecordedControllerCall | None:
    path = _controller_call_path(authority.bundle_dir, batch=batch, attempt=attempt)
    if not path.exists() and not path.is_symlink():
        return None
    record = _read_json(path, label="controller response journal")
    base_fields = {
        "schema_version",
        "episode_id",
        "authorization_id",
        "batch",
        "attempt",
        "received_at_epoch",
    }
    invocation = record.get("invocation")
    expected_invocation = {
        "final_json",
        "sanitized_argv",
        "cli_version",
        "validation_result",
        "tool_event_count",
    }
    _argv, expected_sanitized_argv = _expected_controller_argv_policy()
    if (
        not isinstance(record.get("status"), str)
        or record.get("schema_version") != "br.foundation_episode.controller_call.v3"
        or record.get("episode_id") != EPISODE_ID
        or record.get("authorization_id")
        != authority.authorization.get("authorization_id")
        or record.get("batch") != batch
        or record.get("attempt") != attempt
        or isinstance(record.get("received_at_epoch"), bool)
        or not isinstance(record.get("received_at_epoch"), int | float)
    ):
        raise DiscoveryRunnerError("controller call journal is invalid")
    status = record["status"]
    if status == "succeeded":
        if (
            set(record) != base_fields | {"status", "invocation"}
            or not isinstance(invocation, Mapping)
            or set(invocation) != expected_invocation
            or not isinstance(invocation.get("final_json"), str)
            or invocation.get("sanitized_argv") != expected_sanitized_argv
            or invocation.get("cli_version") != codex_cli.CODEX_CLI_VERSION
            or invocation.get("validation_result")
            != {
                "event_stream": "valid",
                "final_json": "valid_json_object",
                "strict_output_schema": True,
            }
            or invocation.get("tool_event_count") != 0
        ):
            raise DiscoveryRunnerError("controller call journal is invalid")
        return _RecordedControllerCall(
            status=status, final_json=str(invocation["final_json"])
        )
    failure = record.get("failure")
    expected_category = "validation" if status == "validation_failed" else "transport"
    if (
        status not in {"validation_failed", "transport_failed"}
        or set(record) != base_fields | {"status", "failure"}
        or not isinstance(failure, Mapping)
        or set(failure) != {"category", "error_type", "tool_event_count"}
        or failure.get("category") != expected_category
        or not isinstance(failure.get("error_type"), str)
        or not failure["error_type"]
        or isinstance(failure.get("tool_event_count"), bool)
        or not isinstance(failure.get("tool_event_count"), int)
        or failure["tool_event_count"] < 0
    ):
        raise DiscoveryRunnerError("controller call journal is invalid")
    return _RecordedControllerCall(status=status, error_type=failure["error_type"])


def _terminal_controller_failure_from_tombstones(
    authority: DiscoveryAuthorization, *, batch: str
) -> _ControllerBatchFailure | None:
    """Recover only a completed batch failure that the call journal proves.

    A first validation failure is not terminal because the frozen one-time repair
    is still allowed.  A transport failure at either attempt, or a validation
    failure on the repair attempt, is terminal and supplies the exact paired
    receipt outcome on resume.
    """

    primary = _read_controller_call(authority, batch=batch, attempt=0)
    repair = _read_controller_call(authority, batch=batch, attempt=1)
    if primary is None:
        if repair is not None:
            raise DiscoveryRunnerError("repair controller tombstone lacks primary call")
        return None
    if primary.status == "transport_failed":
        if repair is not None:
            raise DiscoveryRunnerError(
                "transport controller tombstone has an impossible repair call"
            )
        return _ControllerBatchFailure(
            failure_type="controller_transport_exhausted",
            error_type=_ControllerTransportError.__name__,
        )
    if repair is None:
        return None
    if repair.status == "transport_failed":
        return _ControllerBatchFailure(
            failure_type="controller_transport_exhausted",
            error_type=_ControllerTransportError.__name__,
        )
    if repair.status == "validation_failed":
        return _ControllerBatchFailure(
            failure_type="controller_schema_repair_exhausted",
            error_type=_ControllerSchemaError.__name__,
        )
    return None


def _pending_controller_batch_failure(
    saved: object, *, expected_slots: list[int], cutoff: int
) -> _ControllerBatchFailure | None:
    """Read the state-level terminal marker written before paired receipts."""

    if not isinstance(saved, Mapping) or "terminal_failure" not in saved:
        return None
    marker = saved.get("terminal_failure")
    failure_type = marker.get("failure_type") if isinstance(marker, Mapping) else None
    error_type = marker.get("error_type") if isinstance(marker, Mapping) else None
    if (
        set(saved) != {"slots", "ledger_cutoff_slot", "terminal_failure"}
        or saved.get("slots") != expected_slots
        or saved.get("ledger_cutoff_slot") != cutoff
        or not isinstance(marker, Mapping)
        or set(marker) != {"failure_type", "error_type"}
        or not isinstance(failure_type, str)
        or failure_type
        not in {
            "controller_transport_exhausted",
            "controller_schema_repair_exhausted",
        }
        or not isinstance(error_type, str)
    ):
        raise DiscoveryRunnerError("saved controller failure marker is invalid")
    expected_error_type = (
        _ControllerTransportError.__name__
        if failure_type == "controller_transport_exhausted"
        else _ControllerSchemaError.__name__
    )
    if error_type != expected_error_type:
        raise DiscoveryRunnerError("saved controller failure marker is invalid")
    return _ControllerBatchFailure(
        failure_type=failure_type,
        error_type=expected_error_type,
    )


def _persist_controller_batch_failure(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    *,
    batch: str,
    expected_slots: list[int],
    cutoff: int,
    failure: _ControllerBatchFailure,
) -> None:
    """Durably mark a terminal batch outcome before either slot receipt writes."""

    pending = state.get("pending_batches")
    if not isinstance(pending, Mapping):
        raise DiscoveryRunnerError("controller state lacks pending batch records")
    marker = {
        "slots": expected_slots,
        "ledger_cutoff_slot": cutoff,
        "terminal_failure": {
            "failure_type": failure.failure_type,
            "error_type": failure.error_type,
        },
    }
    previous = pending.get(batch)
    if previous is not None and previous != marker:
        raise DiscoveryRunnerError("controller batch already has a different outcome")
    updated = dict(pending)
    updated[batch] = marker
    state["pending_batches"] = updated
    _record_state(authority, state)


def _is_controller_failure_pair_receipt(
    receipt: Mapping[str, object], *, failure: _ControllerBatchFailure
) -> bool:
    """Distinguish a synthetic paired failure receipt from an evaluated slot."""

    return (
        receipt.get("status") == "failed"
        and receipt.get("origin") == "controller"
        and receipt.get("proposal") is None
        and receipt.get("evaluation_receipt") is None
        and receipt.get("failure_type") == failure.failure_type
        and receipt.get("detail") == {"error_type": failure.error_type}
    )


def _complete_controller_failure_pair(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    receipts: dict[int, dict[str, object]],
    *,
    slots: Sequence[Mapping[str, object]],
    failure: _ControllerBatchFailure,
) -> None:
    """Finish an interrupted two-slot terminal failure without another CLI call."""

    for slot_contract in slots:
        slot = int(slot_contract["slot"])
        receipt = receipts.get(slot)
        if receipt is not None and not _is_controller_failure_pair_receipt(
            receipt, failure=failure
        ):
            raise DiscoveryRunnerError(
                "controller tombstone conflicts with an evaluated batch receipt"
            )
    for slot_contract in slots:
        slot = int(slot_contract["slot"])
        if slot not in receipts:
            _write_slot(
                authority,
                state,
                receipts,
                slot_contract=slot_contract,
                status="failed",
                origin="controller",
                failure_type=failure.failure_type,
                detail={"error_type": failure.error_type},
            )


def _write_controller_call(
    authority: DiscoveryAuthorization,
    *,
    batch: str,
    attempt: int,
    result: CodexCLIResult,
) -> None:
    invocation = result.persistence_record()
    _argv, expected_sanitized_argv = _expected_controller_argv_policy()
    if (
        set(invocation)
        != {
            "final_json",
            "sanitized_argv",
            "cli_version",
            "validation_result",
            "tool_event_count",
        }
        or not isinstance(invocation.get("final_json"), str)
        or invocation.get("sanitized_argv") != expected_sanitized_argv
        or invocation.get("cli_version") != codex_cli.CODEX_CLI_VERSION
        or invocation.get("validation_result")
        != {
            "event_stream": "valid",
            "final_json": "valid_json_object",
            "strict_output_schema": True,
        }
        or invocation.get("tool_event_count") != 0
    ):
        raise DiscoveryRunnerError("Codex CLI persistence record is invalid")
    _atomic_json(
        _controller_call_path(authority.bundle_dir, batch=batch, attempt=attempt),
        {
            "schema_version": "br.foundation_episode.controller_call.v3",
            "episode_id": EPISODE_ID,
            "authorization_id": authority.authorization["authorization_id"],
            "batch": batch,
            "attempt": attempt,
            "received_at_epoch": time.time(),
            "status": "succeeded",
            "invocation": invocation,
        },
    )


def _write_controller_failure(
    authority: DiscoveryAuthorization,
    *,
    batch: str,
    attempt: int,
    category: str,
    error: BaseException,
) -> None:
    if category not in {"validation", "transport"}:
        raise DiscoveryRunnerError("controller failure category is invalid")
    tool_event_count = getattr(error, "tool_event_count", 0)
    if (
        isinstance(tool_event_count, bool)
        or not isinstance(tool_event_count, int)
        or tool_event_count < 0
    ):
        tool_event_count = 0
    _atomic_json(
        _controller_call_path(authority.bundle_dir, batch=batch, attempt=attempt),
        {
            "schema_version": "br.foundation_episode.controller_call.v3",
            "episode_id": EPISODE_ID,
            "authorization_id": authority.authorization["authorization_id"],
            "batch": batch,
            "attempt": attempt,
            "received_at_epoch": time.time(),
            "status": f"{category}_failed",
            "failure": {
                "category": category,
                "error_type": type(error).__name__,
                "tool_event_count": tool_event_count,
            },
        },
    )


def _persist_controller_failure(
    authority: DiscoveryAuthorization,
    *,
    batch: str,
    attempt: int,
    category: str,
    error: BaseException,
) -> None:
    try:
        _write_controller_failure(
            authority,
            batch=batch,
            attempt=attempt,
            category=category,
            error=error,
        )
    except DiscoveryRunnerError as persist_error:
        raise _ControllerTransportError(type(persist_error).__name__) from persist_error


def _controller_response(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    *,
    batch: str,
    attempt: int,
    prompt: str,
) -> str:
    saved = _read_controller_call(authority, batch=batch, attempt=attempt)
    if saved is not None:
        if saved.status == "succeeded":
            assert saved.final_json is not None
            return saved.final_json
        if saved.status == "validation_failed":
            raise CodexCLIValidationError(
                "recorded controller final JSON validation failure"
            )
        raise _ControllerTransportError(
            saved.error_type or "recorded_controller_transport_failure"
        )
    count = state.get("controller_call_count", 0)
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count >= CONTROLLER_CALL_BUDGETS["controller_calls_hard_max"]
    ):
        raise _ControllerTransportError("controller call limit is exhausted")
    state["controller_call_count"] = count + 1
    state["in_flight"] = {"kind": "controller", "batch": batch, "attempt": attempt}
    _record_state(authority, state)
    durable_outcome = False
    try:
        try:
            result = invoke_codex_cli(
                prompt=prompt,
                output_schema_path=authority.bundle_dir
                / "public"
                / "controller_output_schema.json",
            )
        except CodexCLIValidationError as exc:
            # The process completed, but its final JSON was invalid.  The
            # batch owner may issue exactly one schema-repair attempt.
            _persist_controller_failure(
                authority,
                batch=batch,
                attempt=attempt,
                category="validation",
                error=exc,
            )
            durable_outcome = True
            raise
        except CodexCLIError as exc:
            _persist_controller_failure(
                authority,
                batch=batch,
                attempt=attempt,
                category="transport",
                error=exc,
            )
            durable_outcome = True
            raise _ControllerTransportError(type(exc).__name__) from exc
        except Exception as exc:  # pragma: no cover - defensive process boundary
            _persist_controller_failure(
                authority,
                batch=batch,
                attempt=attempt,
                category="transport",
                error=exc,
            )
            durable_outcome = True
            raise _ControllerTransportError(type(exc).__name__) from exc
        try:
            _write_controller_call(
                authority,
                batch=batch,
                attempt=attempt,
                result=result,
            )
        except DiscoveryRunnerError as exc:
            _persist_controller_failure(
                authority,
                batch=batch,
                attempt=attempt,
                category="transport",
                error=exc,
            )
            durable_outcome = True
            raise _ControllerTransportError(type(exc).__name__) from exc
        durable_outcome = True
        return result.final_json
    finally:
        if durable_outcome:
            state["in_flight"] = None
        _record_state(authority, state)


def _validate_candidate_uniqueness(
    decisions: Sequence[Mapping[str, object]], ledger: Sequence[object]
) -> None:
    seen: set[tuple[str, int]] = set(V1_EXCLUDED_CANDIDATE_PAIRS)
    for record in ledger:
        if not isinstance(record, Mapping):
            raise DiscoveryRunnerError("controller ledger candidate is invalid")
        if record.get("classifier_key") == "host_closed":
            continue
        pair = _proposal_pair(record)
        if pair in seen:
            raise DiscoveryRunnerError("duplicate candidate")
        seen.add(pair)
    for decision in decisions:
        if decision.get("action") != "propose_candidate":
            continue
        pair = _proposal_pair(decision)
        if pair in seen:
            raise DiscoveryRunnerError("duplicate candidate")
        seen.add(pair)


def _parse_controller_decisions(
    *,
    text: str,
    authority: DiscoveryAuthorization,
    slots: Sequence[Mapping[str, object]],
    ledger: Sequence[object],
) -> list[dict[str, object]]:
    decisions = parse_controller_batch_decisions(
        text,
        sanitized_catalog=authority.artifacts["sanitized_catalog"],
        metric_catalog=authority.artifacts["metric_catalog"],
        current_slot_contracts=slots,
    )
    _validate_candidate_uniqueness(decisions, ledger)
    return decisions


def _validate_saved_controller_decisions(
    decisions: Sequence[object],
    *,
    authority: DiscoveryAuthorization,
    slots: Sequence[Mapping[str, object]],
    ledger: Sequence[object],
) -> list[dict[str, object]]:
    try:
        text = json.dumps({"decisions": list(decisions)}, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise DiscoveryRunnerError(
            "saved controller decisions are not JSON values"
        ) from exc
    return _parse_controller_decisions(
        text=text,
        authority=authority,
        slots=slots,
        ledger=ledger,
    )


def _call_controller_batch(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    *,
    batch: str,
    slots: Sequence[Mapping[str, object]],
    ledger: Sequence[object],
) -> list[dict[str, object]]:
    expected_slots = CONTROLLER_PRIMARY_BATCH_SLOTS.get(batch)
    if (
        expected_slots is None
        or tuple(slot.get("slot") for slot in slots) != expected_slots
    ):
        raise DiscoveryRunnerError("controller batch does not match frozen cadence")
    cutoff = int(slots[0]["ledger_cutoff_slot"])
    budget = {
        "scope": DISCOVERY_SCOPE,
        "receipt_budget": RECEIPT_COUNT,
        "proposal_batch": batch,
        "batch_slots": [int(slot["slot"]) for slot in slots],
        "executed_receipts": cutoff,
        "ledger_cutoff_slot": cutoff,
        "excluded_candidate_pairs": _excluded_candidate_pair_records(),
        **CONTROLLER_CALL_BUDGETS,
    }
    prompt = build_controller_prompt(
        sanitized_catalog=authority.artifacts["sanitized_catalog"],
        metric_catalog=authority.artifacts["metric_catalog"],
        aggregate_ledger=list(ledger),
        current_slot_contracts=slots,
        budget=budget,
    )
    try:
        return _parse_controller_decisions(
            text=_controller_response(
                authority,
                state,
                batch=batch,
                attempt=0,
                prompt=prompt,
            ),
            authority=authority,
            slots=slots,
            ledger=ledger,
        )
    except _ControllerTransportError:
        raise
    except (CodexCLIValidationError, FoundationEpisodeError) as primary_error:
        repair_prompt = build_controller_prompt(
            sanitized_catalog=authority.artifacts["sanitized_catalog"],
            metric_catalog=authority.artifacts["metric_catalog"],
            aggregate_ledger=list(ledger),
            current_slot_contracts=slots,
            budget=budget,
            repair_context={
                "attempt": 1,
                "validation_error_code": _validation_error_code(primary_error),
            },
        )
        try:
            return _parse_controller_decisions(
                text=_controller_response(
                    authority,
                    state,
                    batch=batch,
                    attempt=1,
                    prompt=repair_prompt,
                ),
                authority=authority,
                slots=slots,
                ledger=ledger,
            )
        except _ControllerTransportError:
            raise
        except (CodexCLIValidationError, FoundationEpisodeError) as repair_error:
            raise _ControllerSchemaError(type(repair_error).__name__) from repair_error


def _close_controller_batch(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    receipts: dict[int, dict[str, object]],
    *,
    schedule: Sequence[Mapping[str, object]],
    batch: str,
) -> None:
    slots = _batch_slots(schedule, batch)
    if not slots:
        return
    expected_slots = list(CONTROLLER_PRIMARY_BATCH_SLOTS.get(batch, ()))
    if [slot.get("slot") for slot in slots] != expected_slots:
        raise DiscoveryRunnerError("controller batch does not match frozen cadence")
    if all(int(slot["slot"]) in receipts for slot in slots):
        return
    pending = state["pending_batches"]
    assert isinstance(pending, Mapping)
    saved = pending.get(batch)
    cutoff = int(slots[0]["ledger_cutoff_slot"])
    marked_failure = _pending_controller_batch_failure(
        saved, expected_slots=expected_slots, cutoff=cutoff
    )
    if marked_failure is not None:
        _complete_controller_failure_pair(
            authority,
            state,
            receipts,
            slots=slots,
            failure=marked_failure,
        )
        return
    if not isinstance(saved, Mapping):
        failure = _terminal_controller_failure_from_tombstones(authority, batch=batch)
        if failure is not None:
            _complete_controller_failure_pair(
                authority,
                state,
                receipts,
                slots=slots,
                failure=failure,
            )
            return
    if any(int(slot["slot"]) in receipts for slot in slots) and not isinstance(
        saved, Mapping
    ):
        raise DiscoveryRunnerError("evaluated batch lacks persisted paired decisions")
    if isinstance(saved, Mapping):
        if (
            set(saved) != {"slots", "ledger_cutoff_slot", "decisions"}
            or saved.get("slots") != expected_slots
            or saved.get("ledger_cutoff_slot") != cutoff
            or not isinstance(saved.get("decisions"), list)
        ):
            raise DiscoveryRunnerError("saved controller decisions are invalid")
        decisions = _validate_saved_controller_decisions(
            saved["decisions"],
            authority=authority,
            slots=slots,
            ledger=_assert_ledger(
                _rebuild_ledger(receipts, cutoff=cutoff), cutoff=cutoff
            ),
        )
    else:
        try:
            decisions = _call_controller_batch(
                authority,
                state,
                batch=batch,
                slots=slots,
                ledger=_assert_ledger(
                    _rebuild_ledger(receipts, cutoff=cutoff), cutoff=cutoff
                ),
            )
        except _ControllerTransportError as exc:
            failure = _ControllerBatchFailure(
                failure_type="controller_transport_exhausted",
                error_type=type(exc).__name__,
            )
            _persist_controller_batch_failure(
                authority,
                state,
                batch=batch,
                expected_slots=expected_slots,
                cutoff=cutoff,
                failure=failure,
            )
            _complete_controller_failure_pair(
                authority, state, receipts, slots=slots, failure=failure
            )
            return
        except _ControllerSchemaError as exc:
            failure = _ControllerBatchFailure(
                failure_type="controller_schema_repair_exhausted",
                error_type=type(exc).__name__,
            )
            _persist_controller_batch_failure(
                authority,
                state,
                batch=batch,
                expected_slots=expected_slots,
                cutoff=cutoff,
                failure=failure,
            )
            _complete_controller_failure_pair(
                authority, state, receipts, slots=slots, failure=failure
            )
            return
        pending = dict(pending)
        pending[batch] = {
            "slots": expected_slots,
            "ledger_cutoff_slot": cutoff,
            "decisions": decisions,
        }
        state["pending_batches"] = pending
        _record_state(authority, state)
    stop_seen = False
    stop_slot: int | None = None
    for slot, decision in zip(slots, decisions, strict=True):
        number = int(slot["slot"])
        if number in receipts:
            if receipts[number].get("failure_type") == "controller_stop":
                stop_seen = True
                stop_slot = number
            continue
        if stop_seen:
            _write_slot(
                authority,
                state,
                receipts,
                slot_contract=slot,
                status="skipped",
                origin="host",
                failure_type="skipped_by_controller_stop",
            )
        elif decision.get("action") == "stop":
            stop_seen = True
            stop_slot = number
            _write_slot(
                authority,
                state,
                receipts,
                slot_contract=slot,
                status="stopped",
                origin="controller",
                proposal=decision,
                failure_type="controller_stop",
            )
        else:
            # Candidate decisions are evaluated by the main loop after this
            # batch is durably recorded.
            continue
    if stop_slot is not None:
        for later in schedule:
            number = int(later["slot"])
            if stop_slot < number <= CANDIDATE_RECEIPT_COUNT and number not in receipts:
                _write_slot(
                    authority,
                    state,
                    receipts,
                    slot_contract=later,
                    status="skipped",
                    origin="host",
                    failure_type="skipped_by_controller_stop",
                )


def _deadline_exhausted(state: Mapping[str, object], now: float) -> bool:
    deadline = state.get("deadline_epoch")
    return isinstance(deadline, int | float) and now >= float(deadline)


def _close_budget(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    receipts: dict[int, dict[str, object]],
    schedule: Sequence[Mapping[str, object]],
) -> None:
    for slot in schedule:
        number = int(slot["slot"])
        if number not in receipts:
            _write_slot(
                authority,
                state,
                receipts,
                slot_contract=slot,
                status="skipped" if number <= CANDIDATE_RECEIPT_COUNT else "failed",
                origin="host",
                failure_type="budget_exhausted",
            )
    state["phase"] = "BUDGET_EXHAUSTED"
    _record_state(authority, state)


def _evaluate_slot(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    receipts: dict[int, dict[str, object]],
    *,
    slot_contract: Mapping[str, object],
    proposal: Mapping[str, object],
    data: _RuntimeData,
    evaluator: Callable[..., object],
    plan: Mapping[str, object],
    seed: int,
    control_mode: str,
    synthetic: bool = False,
) -> None:
    slot = int(slot_contract["slot"])
    if slot in receipts:
        return
    try:
        classifier, term = _proposal_pair(proposal)
    except DiscoveryRunnerError as exc:
        _write_slot(
            authority,
            state,
            receipts,
            slot_contract=slot_contract,
            status="failed",
            origin="host" if slot > CANDIDATE_RECEIPT_COUNT else "controller",
            proposal=proposal,
            failure_type="invalid_proposal",
            detail={"error_type": type(exc).__name__},
        )
        return
    state["in_flight"] = {"kind": "evaluation", "slot": slot}
    _record_state(authority, state)
    try:
        matrix = data.matrix(term)
        targets, groups = (
            (np.asarray(matrix[:, 0], dtype=np.float64), data.groups_only())
            if synthetic
            else data.targets_and_groups()
        )
        result = evaluator(
            matrix,
            targets,
            groups,
            plan,
            classifier,
            seed,
            engine_path=data.engine_path,
            control_mode=control_mode,
            term_index=term,
        )
        private, aggregate = _aggregate_from_result(result, slot=slot)
        status = "succeeded" if private.get("status") == "succeeded" else "failed"
        _write_slot(
            authority,
            state,
            receipts,
            slot_contract=slot_contract,
            status=status,
            origin="host" if slot > CANDIDATE_RECEIPT_COUNT else "controller",
            proposal=proposal,
            evaluation_receipt=private,
            aggregate=aggregate,
            failure_type=None if status == "succeeded" else "model_evaluation_failure",
        )
    except Exception as exc:
        _write_slot(
            authority,
            state,
            receipts,
            slot_contract=slot_contract,
            status="failed",
            origin="host" if slot > CANDIDATE_RECEIPT_COUNT else "controller",
            proposal=proposal,
            failure_type="model_evaluation_failure",
            detail={"error_type": type(exc).__name__},
        )
    finally:
        state["in_flight"] = None
        _record_state(authority, state)


def _eligible_candidates(
    receipts: Mapping[int, Mapping[str, object]], catalog: Mapping[str, object]
) -> list[dict[str, object]]:
    strata = {
        row.get("classifier_key"): row.get("stratum")
        for row in catalog.get("classifier_catalog", [])
        if isinstance(row, Mapping)
    }
    candidates: list[dict[str, object]] = []
    for slot in range(1, CANDIDATE_RECEIPT_COUNT + 1):
        receipt = receipts.get(slot)
        if not isinstance(receipt, Mapping) or receipt.get("status") != "succeeded":
            continue
        private = receipt.get("evaluation_receipt")
        proposal = receipt.get("proposal")
        if (
            not isinstance(private, Mapping)
            or not isinstance(proposal, Mapping)
            or private.get("control_mode") != "observed"
        ):
            continue
        folds = private.get("folds")
        metrics = private.get("metrics")
        score = (
            metrics.get("mean_fold_signed_pearson_r")
            if isinstance(metrics, Mapping)
            else None
        )
        classifier = private.get("classifier_key")
        if (
            not isinstance(folds, list)
            or len(folds) != 5
            or any(
                not isinstance(row, Mapping) or row.get("status") != "succeeded"
                for row in folds
            )
            or isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(float(score))
            or not isinstance(classifier, str)
            or not isinstance(strata.get(classifier), str)
        ):
            continue
        candidates.append(
            {
                "slot": slot,
                "proposal": dict(proposal),
                "score": float(score),
                "stratum": str(strata[classifier]),
            }
        )
    return sorted(candidates, key=lambda row: (-float(row["score"]), int(row["slot"])))


def _host_slots(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    receipts: dict[int, dict[str, object]],
    *,
    schedule: Sequence[Mapping[str, object]],
    gates: Mapping[str, object],
    data: _RuntimeData,
    evaluator: Callable[..., object],
    now: Callable[[], float],
) -> None:
    by_slot = {int(slot["slot"]): slot for slot in schedule}
    candidates = _eligible_candidates(
        receipts, authority.artifacts["sanitized_catalog"]
    )
    champion = candidates[0] if candidates else None
    primary_plan = data.project_plan()
    alternate = data.private_plan.get("replication_split_plan")
    alternate_seed = data.private_plan.get("replication_seed")
    if (
        not isinstance(alternate, Mapping)
        or isinstance(alternate_seed, bool)
        or not isinstance(alternate_seed, int)
    ):
        raise DiscoveryRunnerError(
            "private split plan lacks the alternate grouped partition"
        )
    alternate_plan = data.project_plan(alternate)
    operations: list[
        tuple[
            int, Mapping[str, object] | None, Mapping[str, object], int, str, bool, str
        ]
    ] = []
    if champion is None:
        operations.extend(
            [
                (
                    HOST_SLOT_CHAMPION_REPARTITION,
                    None,
                    alternate_plan,
                    alternate_seed,
                    "observed",
                    False,
                    "no_eligible_champion",
                ),
                (
                    HOST_SLOT_FALSIFIER,
                    None,
                    primary_plan,
                    int(data.private_plan.get("seed")),
                    "family_block_shuffle",
                    False,
                    "no_eligible_champion",
                ),
            ]
        )
    else:
        champion_proposal = dict(champion["proposal"])
        champion_proposal["host_operation"] = "same_cohort_alternative_partition"
        operations.append(
            (
                HOST_SLOT_CHAMPION_REPARTITION,
                champion_proposal,
                alternate_plan,
                alternate_seed,
                "observed",
                False,
                "",
            )
        )
        shuffle = dict(champion["proposal"])
        shuffle["host_operation"] = "family_block_shuffle_diagnostic_not_p_value"
        operations.append(
            (
                HOST_SLOT_FALSIFIER,
                shuffle,
                primary_plan,
                int(data.private_plan.get("seed")),
                "family_block_shuffle",
                False,
                "",
            )
        )
    runner_up = next(
        (
            row
            for row in candidates
            if champion is not None and row["stratum"] != champion["stratum"]
        ),
        None,
    )
    if runner_up is None:
        operations.append(
            (
                HOST_SLOT_RUNNER_UP_REPARTITION,
                None,
                alternate_plan,
                alternate_seed,
                "observed",
                False,
                "no_different_stratum_runner_up",
            )
        )
    else:
        proposal = dict(runner_up["proposal"])
        proposal["host_operation"] = (
            "same_cohort_alternative_partition_different_stratum"
        )
        operations.append(
            (
                HOST_SLOT_RUNNER_UP_REPARTITION,
                proposal,
                alternate_plan,
                alternate_seed,
                "observed",
                False,
                "",
            )
        )
    positive = gates.get("slot_100_positive_control")
    if not isinstance(positive, Mapping):
        raise DiscoveryRunnerError("contract lacks positive control")
    operations.append(
        (
            HOST_SLOT_POSITIVE_CONTROL,
            {
                "classifier_key": positive.get("classifier_key"),
                "term_index": positive.get("term_index"),
                "hypothesis": "synthetic raw edge zero control",
                "falsifier": "all five outer folds must succeed with the frozen threshold",
                "rationale": "host-fixed control",
                "host_operation": "synthetic_positive_control",
            },
            primary_plan,
            int(data.private_plan.get("seed")),
            "synthetic_positive_control",
            True,
            "",
        )
    )
    for slot, proposal, plan, seed, control, synthetic, failure in sorted(
        operations, key=lambda item: item[0]
    ):
        if slot in receipts:
            continue
        if _deadline_exhausted(state, now()):
            _close_budget(authority, state, receipts, schedule)
            return
        if proposal is None:
            _write_slot(
                authority,
                state,
                receipts,
                slot_contract=by_slot[slot],
                status="failed",
                origin="host",
                failure_type=failure,
            )
        else:
            _evaluate_slot(
                authority,
                state,
                receipts,
                slot_contract=by_slot[slot],
                proposal=proposal,
                data=data,
                evaluator=evaluator,
                plan=plan,
                seed=seed,
                control_mode=control,
                synthetic=synthetic,
            )


def _positive_control_passed(
    receipt: Mapping[str, object] | None, gates: Mapping[str, object]
) -> bool:
    positive = gates.get("slot_100_positive_control")
    private = (
        receipt.get("evaluation_receipt") if isinstance(receipt, Mapping) else None
    )
    if (
        not isinstance(positive, Mapping)
        or not isinstance(private, Mapping)
        or receipt.get("status") != "succeeded"
        or private.get("control_mode") != "synthetic_positive_control"
        or private.get("classifier_key") != "ridge"
        or private.get("term_index") != 0
    ):
        return False
    folds = private.get("folds")
    metrics = private.get("metrics")
    score = (
        metrics.get("mean_fold_signed_pearson_r")
        if isinstance(metrics, Mapping)
        else None
    )
    return (
        isinstance(folds, list)
        and len(folds) == 5
        and all(
            isinstance(row, Mapping) and row.get("status") == "succeeded"
            for row in folds
        )
        and isinstance(score, int | float)
        and not isinstance(score, bool)
        and math.isfinite(float(score))
        and float(score) >= float(positive.get("minimum_mean_signed_r"))
    )


def _protocol_integrity(receipts: Mapping[int, Mapping[str, object]]) -> bool:
    if len(receipts) != RECEIPT_COUNT:
        return False
    if any(
        receipt.get("failure_type")
        in {
            "controller_transport_exhausted",
            "controller_schema_repair_exhausted",
            "duplicate_candidate",
            "interrupted_evaluation",
            "budget_exhausted",
        }
        for receipt in receipts.values()
    ):
        return False
    for slot in range(1, 9):
        receipt = receipts.get(slot)
        if (
            not isinstance(receipt, Mapping)
            or not isinstance(receipt.get("proposal"), Mapping)
            or not isinstance(receipt.get("evaluation_receipt"), Mapping)
        ):
            return False
    return True


def _batch_lift_metrics(
    receipts: Mapping[int, Mapping[str, object]],
    search_alpha: Mapping[str, object],
) -> dict[str, object]:
    """Summarize controller trajectory without turning missing slots into zeroes."""

    allocations = _validate_search_alpha_allocation(search_alpha)
    windows: list[dict[str, object]] = []
    coverage_mean: float | None = None
    for allocation in allocations:
        slots = [int(slot) for slot in allocation["slots"]]
        scores: list[float] = []
        scored_slots: list[int] = []
        for slot in slots:
            receipt = receipts.get(slot)
            aggregate = (
                receipt.get("controller_aggregate")
                if isinstance(receipt, Mapping)
                else None
            )
            metrics = (
                aggregate.get("metrics") if isinstance(aggregate, Mapping) else None
            )
            qc = aggregate.get("qc") if isinstance(aggregate, Mapping) else None
            score = (
                metrics.get("primary_signed_pearson_r")
                if isinstance(metrics, Mapping)
                else None
            )
            if (
                isinstance(receipt, Mapping)
                and receipt.get("status") == "succeeded"
                and isinstance(aggregate, Mapping)
                and aggregate.get("status") == "succeeded"
                and aggregate.get("control_mode") == "observed"
                and isinstance(qc, Mapping)
                and qc.get("outer_fold_count") == 5
                and qc.get("all_outer_folds_succeeded") is True
                and isinstance(score, int | float)
                and not isinstance(score, bool)
                and math.isfinite(float(score))
            ):
                scores.append(float(score))
                scored_slots.append(slot)
        mean_score = float(np.mean(scores)) if scores else None
        if allocation["window_id"] == "coverage":
            coverage_mean = mean_score
        windows.append(
            {
                "window_id": allocation["window_id"],
                "slots": slots,
                "alpha_mass": allocation["alpha_mass"],
                "n_allocated": len(slots),
                "n_scored": len(scores),
                "missing_slots": [slot for slot in slots if slot not in scored_slots],
                "complete": len(scores) == len(slots),
                "mean_primary_signed_pearson_r": mean_score,
                "score_mean_denominator": "n_scored",
                "signed_delta_vs_coverage": None,
            }
        )
    for window in windows:
        mean_score = window["mean_primary_signed_pearson_r"]
        if (
            window["window_id"] != "coverage"
            and isinstance(mean_score, float)
            and coverage_mean is not None
        ):
            window["signed_delta_vs_coverage"] = mean_score - coverage_mean
    return {
        "schema_version": "br.foundation_episode.batch_lift.v1",
        "instrument": "primary_signed_pearson_r",
        "interpretation": "descriptive_controller_trajectory_not_model_superiority_or_test",
        "search_budget_denominator": "prospectively_allocated_slots",
        "score_mean_denominator": "n_scored",
        "missingness_policy": "report_missing_never_impute_zero",
        "compatibility": "forward_only_new_episode_contract",
        "coverage_mean_primary_signed_pearson_r": coverage_mean,
        "windows": windows,
    }


def _finalize(
    authority: DiscoveryAuthorization,
    state: dict[str, object],
    receipts: Mapping[int, Mapping[str, object]],
    gates: Mapping[str, object],
) -> tuple[str, bool, bool]:
    integrity = _protocol_integrity(receipts)
    budget_exhausted = any(
        receipt.get("failure_type") == "budget_exhausted"
        for receipt in receipts.values()
    )
    complete = bool(integrity and not budget_exhausted)
    positive = _positive_control_passed(receipts.get(HOST_SLOT_POSITIVE_CONTROL), gates)
    valid = bool(complete and integrity and positive)
    phase = (
        "COMPLETED"
        if complete
        else (
            "BUDGET_EXHAUSTED"
            if budget_exhausted
            else "COMPLETED_WITH_PROTOCOL_FAILURE"
        )
    )
    state.update(
        {
            "phase": phase,
            "protocol_complete": complete,
            "protocol_integrity": integrity,
            "positive_control_passed": positive,
            "episode_valid": valid,
            "confirmation_started": False,
            "sealed_holdout_target_selected": False,
            "sealed_holdout_target_converted": False,
            "sealed_holdout_target_used": False,
        }
    )
    _record_state(authority, state)
    boundary = authority.artifacts["episode_contract"].get("claim_boundary")
    if not isinstance(boundary, Mapping):
        raise DiscoveryRunnerError("episode contract lacks its public claim boundary")
    public = {
        "schema_version": "br.foundation_episode.discovery_result.v2",
        "episode_id": EPISODE_ID,
        "authorization_id": authority.authorization["authorization_id"],
        "phase": phase,
        "receipt_count": len(receipts),
        "protocol_complete": complete,
        "protocol_integrity": integrity,
        "positive_control_passed": positive,
        "episode_valid": valid,
        "confirmation_started": False,
        "sealed_holdout_target_selected": False,
        "sealed_holdout_target_converted": False,
        "sealed_holdout_target_used": False,
        "scientific_acceptance": False,
        "confirmation_authorized": False,
    }
    for key in PUBLIC_CLAIM_BOUNDARY_FIELDS:
        if key not in boundary:
            raise DiscoveryRunnerError("episode contract lacks a required public claim")
        public[key] = boundary[key]
    search_alpha = authority.artifacts["episode_contract"].get(
        "search_alpha_allocation"
    )
    if not isinstance(search_alpha, Mapping):
        raise DiscoveryRunnerError("episode contract lacks search alpha allocation")
    public["engine_metrics"] = {
        "batch_lift": _batch_lift_metrics(receipts, search_alpha)
    }
    _atomic_json(
        authority.bundle_dir / "public" / "episode_result.json", public, mode=0o644
    )
    return phase, complete, valid


def finalize_terminal_discovery(
    authority: DiscoveryAuthorization,
) -> DiscoveryRunResult:
    """Finalize exactly 100 durable receipts without discovery compute."""

    _schedule, gates = _validate_protocol(authority.artifacts["episode_contract"])
    state = _load_state(authority, time.time())
    receipts = _read_slot_receipts(authority, state)
    if len(receipts) != RECEIPT_COUNT:
        raise DiscoveryRunnerError(
            "terminal-only finalization requires exactly 100 terminal receipts"
        )
    if state.get("in_flight") is not None:
        state["in_flight"] = None
        _record_state(authority, state)
    phase, complete, valid = _finalize(authority, state, receipts, gates)
    return DiscoveryRunResult(
        authority.bundle_dir,
        _state_path(authority.bundle_dir),
        _receipt_dir(authority.bundle_dir),
        len(receipts),
        phase,
        complete,
        valid,
        False,
        False,
    )


def run_discovery(
    bundle_dir: Path | str,
    authorization_path: Path | str,
    *,
    evaluator: Callable[..., object] | None = None,
    wall_clock: Callable[[], float] = time.time,
) -> DiscoveryRunResult:
    """Execute or resume the authorized discovery-only episode."""

    authority = verify_discovery_authorization(bundle_dir, authorization_path)
    schedule, gates = _validate_protocol(authority.artifacts["episode_contract"])
    now = float(wall_clock())
    if not math.isfinite(now):
        raise DiscoveryRunnerError("wall clock is invalid")
    state = _load_state(authority, now)
    receipts = _read_slot_receipts(authority, state)
    in_flight = state.get("in_flight")
    if isinstance(in_flight, Mapping) and in_flight.get("kind") == "evaluation":
        slot = in_flight.get("slot")
        by_slot = {int(item["slot"]): item for item in schedule}
        if isinstance(slot, int) and slot in by_slot and slot not in receipts:
            _write_slot(
                authority,
                state,
                receipts,
                slot_contract=by_slot[slot],
                status="failed",
                origin="host",
                failure_type="interrupted_evaluation",
            )
        state["in_flight"] = None
        _record_state(authority, state)
    elif isinstance(in_flight, Mapping) and in_flight.get("kind") == "controller":
        batch = in_flight.get("batch")
        attempt = in_flight.get("attempt")
        if (
            not isinstance(batch, str)
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
        ):
            raise DiscoveryRunnerError("interrupted controller state is invalid")
        journal = _controller_call_path(
            authority.bundle_dir, batch=batch, attempt=attempt
        )
        if journal.is_symlink() or not journal.is_file():
            slots = _batch_slots(schedule, batch)
            if not slots:
                raise DiscoveryRunnerError("interrupted controller batch is invalid")
            for slot_contract in slots:
                slot = int(slot_contract["slot"])
                if slot not in receipts:
                    _write_slot(
                        authority,
                        state,
                        receipts,
                        slot_contract=slot_contract,
                        status="failed",
                        origin="controller",
                        failure_type="controller_transport_exhausted",
                        detail={"error_type": "interrupted_controller_response"},
                    )
        state["in_flight"] = None
        _record_state(authority, state)
    elif in_flight is not None:
        state["in_flight"] = None
        _record_state(authority, state)
    if len(receipts) == RECEIPT_COUNT:
        phase, complete, valid = _finalize(authority, state, receipts, gates)
        return DiscoveryRunResult(
            authority.bundle_dir,
            _state_path(authority.bundle_dir),
            _receipt_dir(authority.bundle_dir),
            len(receipts),
            phase,
            complete,
            valid,
            False,
            False,
        )
    if _deadline_exhausted(state, float(wall_clock())):
        _close_budget(authority, state, receipts, schedule)
        phase, complete, valid = _finalize(authority, state, receipts, gates)
        return DiscoveryRunResult(
            authority.bundle_dir,
            _state_path(authority.bundle_dir),
            _receipt_dir(authority.bundle_dir),
            len(receipts),
            phase,
            complete,
            valid,
            False,
            False,
        )
    data = _RuntimeData(authority)
    evaluator_fn = evaluate_fresh_fit if evaluator is None else evaluator
    stop_slot = _controller_stop_slot(receipts)
    for batch in CONTROLLER_BATCH_ORDER:
        slots = _batch_slots(schedule, batch)
        if _deadline_exhausted(state, float(wall_clock())):
            _close_budget(authority, state, receipts, schedule)
            break
        if stop_slot is not None and all(
            int(slot["slot"]) > stop_slot for slot in slots
        ):
            for slot in slots:
                if int(slot["slot"]) not in receipts:
                    _write_slot(
                        authority,
                        state,
                        receipts,
                        slot_contract=slot,
                        status="skipped",
                        origin="host",
                        failure_type="skipped_by_controller_stop",
                    )
            continue
        _close_controller_batch(
            authority, state, receipts, schedule=schedule, batch=batch
        )
        saved = state["pending_batches"]
        record = saved.get(batch) if isinstance(saved, Mapping) else None
        decisions = record.get("decisions") if isinstance(record, Mapping) else None
        if isinstance(decisions, list):
            for slot, proposal in zip(slots, decisions, strict=True):
                if (
                    int(slot["slot"]) in receipts
                    or proposal.get("action") != "propose_candidate"
                ):
                    continue
                if _deadline_exhausted(state, float(wall_clock())):
                    _close_budget(authority, state, receipts, schedule)
                    break
                _evaluate_slot(
                    authority,
                    state,
                    receipts,
                    slot_contract=slot,
                    proposal=proposal,
                    data=data,
                    evaluator=evaluator_fn,
                    plan=data.project_plan(),
                    seed=int(data.private_plan.get("seed")),
                    control_mode="observed",
                )
        stop_slot = _controller_stop_slot(receipts)
        if state.get("phase") == "BUDGET_EXHAUSTED":
            break
    if state.get("phase") != "BUDGET_EXHAUSTED":
        _host_slots(
            authority,
            state,
            receipts,
            schedule=schedule,
            gates=gates,
            data=data,
            evaluator=evaluator_fn,
            now=lambda: float(wall_clock()),
        )
    if len(receipts) != RECEIPT_COUNT:
        raise DiscoveryRunnerError(
            "state machine did not publish exactly 100 terminal receipts"
        )
    phase, complete, valid = _finalize(authority, state, receipts, gates)
    return DiscoveryRunResult(
        authority.bundle_dir,
        _state_path(authority.bundle_dir),
        _receipt_dir(authority.bundle_dir),
        len(receipts),
        phase,
        complete,
        valid,
        False,
        False,
    )


__all__ = [
    "DiscoveryAuthorization",
    "DiscoveryRunResult",
    "DiscoveryRunnerError",
    "MAX_WALLTIME_SECONDS",
    "finalize_terminal_discovery",
    "run_discovery",
    "verify_discovery_authorization",
    "verify_terminal_discovery_authorization",
]
