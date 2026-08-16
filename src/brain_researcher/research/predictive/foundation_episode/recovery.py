"""Independent, bounded recovery for six MVE-100 v2 transport failures.

This module intentionally does not resume or mutate the source discovery
episode.  It snapshots the source inputs and historical ledgers into a new
recovery bundle, then executes exactly twelve source-slot-bound receipts.  A
successful recovery is operational evidence only: it cannot change the source
episode's invalid result, authorize confirmation, or make a scientific claim.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from brain_researcher.research.predictive.foundation_episode import codex_cli
from brain_researcher.research.predictive.foundation_episode.codex_cli import (
    CodexCLIError,
    CodexCLIExecutionError,
    CodexCLIValidationError,
    invoke_codex_cli,
    verify_codex_cli_version,
)
from brain_researcher.research.predictive.foundation_episode.contracts import (
    AUTHORIZATION_SCHEMA as SOURCE_AUTHORIZATION_SCHEMA,
)
from brain_researcher.research.predictive.foundation_episode.contracts import (
    DISCOVERY_SCOPE as SOURCE_DISCOVERY_SCOPE,
)
from brain_researcher.research.predictive.foundation_episode.contracts import (
    EPISODE_ID as SOURCE_EPISODE_ID,
)
from brain_researcher.research.predictive.foundation_episode.contracts import (
    PARTITION_SEED,
    V1_EXCLUDED_CANDIDATE_PAIRS,
    FoundationEpisodeError,
)
from brain_researcher.research.predictive.foundation_episode.evaluator import (
    evaluate_fresh_fit,
)
from brain_researcher.research.predictive.foundation_episode.recovery_controller import (
    POST_HOC_PAIR_IDENTITY_VISIBILITY,
    RECOVERY_REPAIR_ERROR_CODES,
    RecoveryControllerError,
    build_recovery_controller_prompt,
    pair_records,
    parse_recovery_batch_decisions,
    recovery_controller_response_schema,
    recovery_validation_error_code,
)
from brain_researcher.research.predictive.foundation_episode.runner import (
    SLOT_RECEIPT_SCHEMA as SOURCE_RECEIPT_SCHEMA,
)
from brain_researcher.research.predictive.foundation_episode.runner import (
    _aggregate_from_result,
    _live_single_gpu,
    _RuntimeData,
)

RECOVERY_EPISODE_ID = "foundation_mve100_ica_cognition_codex_cli_v2_recovery12_v1"
RECOVERY_SCOPE = "transport_recovery12_only"
RECOVERY_AUTHORIZATION_SCHEMA = (
    "predictive.foundation_mve100_recovery12_authorization.v1"
)
RECOVERY_CONTRACT_SCHEMA = "br.foundation_episode.recovery12.contract.v1"
RECOVERY_RECEIPT_SCHEMA = "br.foundation_episode.recovery12.receipt.v1"
RECOVERY_RESULT_SCHEMA = "br.foundation_episode.recovery12.result.v1"
RECOVERY_STATE_SCHEMA = "br.foundation_episode.recovery12.state.v1"
RECOVERY_JOURNAL_SCHEMA = "br.foundation_episode.recovery12.controller_call.v1"
RECOVERY_LEDGER_SCHEMA = "br.foundation_episode.recovery12.source_ledger.v1"
SOURCE_FIELD_SNAPSHOT_SCHEMA = "br.foundation_episode.recovery12.source_fields.v1"
RECOVERY_LOCK_RELATIVE = "private/recovery_launch.lock"
# The historical version default remains, but the public source never assumes
# a workstation-local release label.  A governed caller supplies a compatible
# binary through BR_HCP_CODEX_BINARY.
RECOVERY_PINNED_CODEX_CLI_VERSION = os.environ.get(
    "BR_HCP_CODEX_VERSION", "0.146.1"
)
RECOVERY_PINNED_CODEX_CLI_BINARY = Path(
    os.environ.get("BR_HCP_CODEX_BINARY", codex_cli.CODEX_CLI_BINARY)
)
MAX_WALLTIME_SECONDS = 12 * 60 * 60
CONTROLLER_TIMEOUT_SECONDS = 240.0
RECOVERY_RECEIPT_COUNT = 12


def configure_recovery_runtime(
    *, binary: str | None = None, version: str | None = None
) -> None:
    """Apply an explicit public Codex binary/version to recovery execution."""

    global RECOVERY_PINNED_CODEX_CLI_BINARY, RECOVERY_PINNED_CODEX_CLI_VERSION
    codex_cli.configure_codex_runtime(binary=binary, version=version)
    if binary is not None:
        RECOVERY_PINNED_CODEX_CLI_BINARY = Path(binary)
    if version is not None:
        RECOVERY_PINNED_CODEX_CLI_VERSION = version


@dataclass(frozen=True, slots=True)
class RecoveryBatch:
    """One immutable two-slot retry target from the failed v2 episode."""

    batch: str
    source_slots: tuple[int, int]
    ledger_cutoff: int


RECOVERY_BATCHES = (
    RecoveryBatch("adaptive_batch_6", (19, 20), 18),
    RecoveryBatch("adaptive_batch_13", (33, 34), 32),
    RecoveryBatch("adaptive_batch_14", (35, 36), 34),
    RecoveryBatch("adaptive_batch_17", (41, 42), 40),
    RecoveryBatch("adaptive_batch_19", (45, 46), 44),
    RecoveryBatch("adaptive_batch_44", (95, 96), 94),
)

_SOURCE_SNAPSHOT_ARTIFACTS = (
    "episode_contract.json",
    "input_manifest.json",
    "private/split_plan.private.json",
    "public/split_plan.public.json",
    "private/runtime_inputs.json",
    "public/sanitized_catalog.json",
    "public/metric_catalog.json",
)
_ARTIFACT_ALIASES = {
    "episode_contract.json": "episode_contract",
    "input_manifest.json": "input_manifest",
    "private/split_plan.private.json": "private_split_plan",
    "public/split_plan.public.json": "public_split_plan",
    "private/runtime_inputs.json": "runtime_inputs",
    "public/sanitized_catalog.json": "sanitized_catalog",
    "public/metric_catalog.json": "metric_catalog",
}
_SOURCE_STATE_RELATIVE = "private/discovery_state.json"
_SOURCE_RESULT_RELATIVE = "public/episode_result.json"
_SOURCE_AUTHORIZATION_RELATIVE = "authorization.json"
_SOURCE_RECEIPT_FIELDS = {
    "schema_version",
    "slot",
    "episode_id",
    "authorization_id",
    "slot_contract",
    "status",
    "origin",
    "proposal",
    "evaluation_receipt",
    "controller_aggregate",
    "failure_type",
    "detail",
    "confirmation_started",
    "sealed_holdout_target_selected",
    "sealed_holdout_target_converted",
    "sealed_holdout_target_used",
}
_SOURCE_RECEIPT_BOUNDARY_FIELDS = (
    "confirmation_started",
    "sealed_holdout_target_selected",
    "sealed_holdout_target_converted",
    "sealed_holdout_target_used",
)
_JOURNAL_PURPOSES = frozenset({"primary", "timeout_retry", "schema_repair"})
_TERMINAL_CONTROLLER_FAILURES = frozenset(
    {
        "controller_timeout_exhausted",
        "controller_schema_repair_exhausted",
        "controller_transport_failed",
    }
)
_RECOVERY_RECEIPT_FIELDS = {
    "schema_version",
    "episode_id",
    "authorization_id",
    "source_episode_id",
    "source_authorization_id",
    "recovery_slot",
    "source_slot",
    "source_batch",
    "historical_ledger_cutoff",
    "source_slot_contract",
    "status",
    "origin",
    "proposal",
    "evaluation_receipt",
    "controller_aggregate",
    "failure_type",
    "detail",
    "confirmation_started",
    "sealed_holdout_target_selected",
    "sealed_holdout_target_converted",
    "sealed_holdout_target_used",
    "scientific_acceptance",
}
_RECOVERY_STATE_FIELDS = {
    "schema_version",
    "episode_id",
    "authorization_id",
    "started_at_epoch",
    "deadline_epoch",
    "phase",
    "terminal_recovery_slots",
    "controller_physical_call_count",
    "in_flight",
}
_RECOVERY_JOURNAL_BASE_FIELDS = {
    "schema_version",
    "episode_id",
    "authorization_id",
    "source_episode_id",
    "source_authorization_id",
    "batch",
    "source_slots",
    "ledger_cutoff",
    "attempt_index",
    "purpose",
    "timeout_seconds",
    "status",
}


class RecoveryError(FoundationEpisodeError):
    """The isolated recovery contract or its execution state is invalid."""


class _ControllerTerminalError(RecoveryError):
    """A batch used its allowed physical calls without usable decisions."""

    def __init__(self, failure_type: str, error_type: str) -> None:
        super().__init__(failure_type)
        self.failure_type = failure_type
        self.error_type = error_type


@dataclass(frozen=True, slots=True)
class RecoveryAuthority:
    bundle_dir: Path
    authorization: Mapping[str, object]
    contract: Mapping[str, object]
    artifacts: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class RecoveryRunResult:
    bundle_dir: Path
    receipt_count: int
    recovery_protocol_complete: bool
    recovery_integrity: bool
    source_episode_valid: bool
    scientific_acceptance: bool


def _recovery_schedule() -> list[dict[str, object]]:
    schedule: list[dict[str, object]] = []
    recovery_slot = 1
    for item in RECOVERY_BATCHES:
        for position, source_slot in enumerate(item.source_slots, start=1):
            schedule.append(
                {
                    "recovery_slot": recovery_slot,
                    "source_slot": source_slot,
                    "source_batch": item.batch,
                    "historical_ledger_cutoff": item.ledger_cutoff,
                    "position_in_batch": position,
                }
            )
            recovery_slot += 1
    return schedule


def _resource_tool_gate() -> dict[str, object]:
    return {
        "compute": "local_single_gpu",
        "gpu_count": 1,
        "evaluation_concurrency": 1,
        "candidate_execution_order": "recovery_slot_serial",
        "max_walltime_hours": 12,
        "controller_timeout_seconds": int(CONTROLLER_TIMEOUT_SECONDS),
        "controller_timeout_retries_per_batch": 1,
        "physical_calls_per_batch_hard_max": 2,
        "controller_primary_calls_max": len(RECOVERY_BATCHES),
        "controller_retry_or_repair_calls_max": len(RECOVERY_BATCHES),
        "controller_calls_hard_max": len(RECOVERY_BATCHES) * 2,
        "recovery_receipt_slots": RECOVERY_RECEIPT_COUNT,
        "host_controls": "not_rerun",
        "champion_selection": "not_run",
        "batch_lift": "not_run",
    }


def _recovery_controller_transport() -> dict[str, object]:
    return {
        "schema_version": "br.foundation_episode.recovery12.controller_transport.v1",
        "provider": "codex.cli",
        "pinned_cli_version": RECOVERY_PINNED_CODEX_CLI_VERSION,
        "pinned_cli_binary": str(RECOVERY_PINNED_CODEX_CLI_BINARY),
        "timeout_seconds": int(CONTROLLER_TIMEOUT_SECONDS),
        "primary_timeout_retry": "one_same_prompt_same_historical_ledger",
        "schema_invalid_repair": "one_same_historical_ledger",
        "other_transport_retry": "forbidden",
        "physical_calls_per_batch_hard_max": 2,
    }


def _boundaries() -> dict[str, bool]:
    return {
        "confirmation_started": False,
        "sealed_holdout_target_selected": False,
        "sealed_holdout_target_converted": False,
        "sealed_holdout_target_used": False,
        "scientific_acceptance": False,
    }


def _regular_directory(path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_dir():
        raise RecoveryError(f"{label} must be a regular directory")
    return resolved


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RecoveryError(f"{label} must be a regular JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise RecoveryError(f"{label} must be a JSON object")
    return value


def _under(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RecoveryError("recovery writer escaped its bundle root") from exc
    return candidate


@contextmanager
def _exclusive_recovery_lock(root: Path):
    """Keep one durable non-blocking advisory lock for one recovery bundle."""

    path = _under(root, RECOVERY_LOCK_RELATIVE)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RecoveryError("recovery launch lock must not be a symlink")
    descriptor: int | None = None
    locked = False
    try:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise RecoveryError("recovery bundle already has an active launch") from exc
        except OSError as exc:
            raise RecoveryError("recovery launch lock could not be acquired") from exc
        yield
    finally:
        if descriptor is not None:
            try:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _pinned_recovery_run_command(command: Sequence[str], **kwargs: object) -> object:
    """Replace only the base adapter executable with recovery's configured binary."""

    if (
        isinstance(command, str | bytes | bytearray)
        or not command
        or any(not isinstance(item, str) for item in command)
        or command[0] != codex_cli.CODEX_CLI_BINARY
    ):
        raise RecoveryError("pinned recovery Codex command is invalid")
    return subprocess.run(
        [str(RECOVERY_PINNED_CODEX_CLI_BINARY), *command[1:]], **kwargs
    )


def _verify_pinned_recovery_cli() -> None:
    if codex_cli.CODEX_CLI_VERSION != RECOVERY_PINNED_CODEX_CLI_VERSION:
        raise RecoveryError("base Codex adapter version no longer matches recovery pin")
    if (
        RECOVERY_PINNED_CODEX_CLI_BINARY.is_symlink()
        or not RECOVERY_PINNED_CODEX_CLI_BINARY.is_file()
        or not os.access(RECOVERY_PINNED_CODEX_CLI_BINARY, os.X_OK)
    ):
        raise RecoveryError("pinned recovery Codex binary is unavailable")
    try:
        observed = verify_codex_cli_version(run_command=_pinned_recovery_run_command)
    except CodexCLIError as exc:
        raise RecoveryError("pinned recovery Codex version precheck failed") from exc
    if observed != RECOVERY_PINNED_CODEX_CLI_VERSION:
        raise RecoveryError("pinned recovery Codex version is invalid")


def invoke_pinned_recovery_codex_cli(
    *, prompt: str, output_schema_path: Path | str, timeout_seconds: float
) -> object:
    """Invoke the base adapter only through the configured recovery binary."""

    return invoke_codex_cli(
        prompt=prompt,
        output_schema_path=output_schema_path,
        timeout_seconds=timeout_seconds,
        run_command=_pinned_recovery_run_command,
    )


def _write_json(root: Path, relative: str, payload: object) -> Path:
    path = _under(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise RecoveryError("recovery output path must not be a symlink")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(
            payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
    if "private/" in relative or relative == "authorization.template.json":
        path.chmod(0o600)
    return path


def _assert_separate_roots(source_root: Path, recovery_root: Path) -> None:
    if source_root == recovery_root:
        raise RecoveryError("source and recovery roots must differ")
    try:
        recovery_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise RecoveryError("recovery root must not be nested below the source root")
    try:
        source_root.relative_to(recovery_root)
    except ValueError:
        pass
    else:
        raise RecoveryError("source root must not be nested below the recovery root")


def _source_receipt_path(root: Path, slot: int) -> Path:
    return root / "private" / "discovery_receipts" / f"slot_{slot:02d}.json"


def _source_controller_journal_path(root: Path, batch: str, attempt: int) -> Path:
    return root / "private" / "controller_calls" / f"{batch}.{attempt}.json"


def _nonempty_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RecoveryError(f"{label} must be non-empty text")
    return value


def _validate_source_authorization(authorization: Mapping[str, object]) -> str:
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
        or authorization.get("schema_version") != SOURCE_AUTHORIZATION_SCHEMA
        or authorization.get("episode_id") != SOURCE_EPISODE_ID
        or authorization.get("scope") != SOURCE_DISCOVERY_SCOPE
        or authorization.get("authorized") is not True
        or authorization.get("confirmation_authorization") != "NOT_GRANTED"
    ):
        raise RecoveryError("source authorization is not the frozen v2 discovery grant")
    authorization_id = _nonempty_text(
        authorization.get("authorization_id"), label="source authorization_id"
    )
    for key in ("authorized_by", "rationale"):
        if _nonempty_text(authorization.get(key), label=f"source {key}").startswith(
            "FILL_BY_"
        ):
            raise RecoveryError(f"source {key} is a placeholder")
    if authorization_id.startswith("FILL_BY_"):
        raise RecoveryError("source authorization_id is a placeholder")
    return authorization_id


def _validate_source_transport_receipt(
    receipt: Mapping[str, object],
    *,
    source_slot: int,
    source_slot_contract: Mapping[str, object],
    source_authorization_id: str,
) -> None:
    aggregate = receipt.get("controller_aggregate")
    expected_aggregate = {
        "schema_version": "foundation_episode_controller_aggregate_v1",
        "slot": source_slot,
        "status": "failed",
        "candidate_label": f"slot-{source_slot}:host_closed:term-0",
        "classifier_key": "host_closed",
        "term_index": 0,
        "control_mode": "observed",
        "metrics": {
            "primary_signed_pearson_r": None,
            "mean_fold_signed_pearson_r": None,
            "mean_fold_r2": None,
            "mean_fold_mae": None,
            "pooled_signed_pearson_r": None,
        },
        "qc": {
            "outer_fold_count": 0,
            "completed_fold_count": 0,
            "failed_fold_count": 0,
            "all_outer_folds_succeeded": False,
            "primary_metric_available": False,
        },
        "runtime_sec": None,
        "failure_type": "controller_transport_exhausted",
    }
    if (
        set(receipt) != _SOURCE_RECEIPT_FIELDS
        or receipt.get("schema_version") != SOURCE_RECEIPT_SCHEMA
        or receipt.get("slot") != source_slot
        or receipt.get("episode_id") != SOURCE_EPISODE_ID
        or receipt.get("authorization_id") != source_authorization_id
        or receipt.get("slot_contract") != source_slot_contract
        or receipt.get("status") != "failed"
        or receipt.get("origin") != "controller"
        or receipt.get("proposal") is not None
        or receipt.get("evaluation_receipt") is not None
        or aggregate != expected_aggregate
        or receipt.get("failure_type") != "controller_transport_exhausted"
        or receipt.get("detail") != {"error_type": "_ControllerTransportError"}
        or any(receipt.get(key) is not False for key in _SOURCE_RECEIPT_BOUNDARY_FIELDS)
    ):
        raise RecoveryError(
            "source transport receipt is not the frozen terminal record"
        )


def _validate_source_transport_journal(
    journal: Mapping[str, object], *, batch: str, source_authorization_id: str
) -> None:
    required = {
        "schema_version",
        "episode_id",
        "authorization_id",
        "batch",
        "attempt",
        "received_at_epoch",
        "status",
        "failure",
    }
    failure = journal.get("failure")
    if (
        set(journal) != required
        or journal.get("schema_version") != "br.foundation_episode.controller_call.v3"
        or journal.get("episode_id") != SOURCE_EPISODE_ID
        or journal.get("authorization_id") != source_authorization_id
        or journal.get("batch") != batch
        or journal.get("attempt") != 0
        or isinstance(journal.get("received_at_epoch"), bool)
        or not isinstance(journal.get("received_at_epoch"), int | float)
        or not math.isfinite(float(journal["received_at_epoch"]))
        or journal.get("status") != "transport_failed"
        or failure
        != {
            "category": "transport",
            "error_type": "CodexCLIExecutionError",
            "tool_event_count": 0,
        }
    ):
        raise RecoveryError("source transport controller journal is not frozen")


def _read_source_receipts(source_root: Path) -> dict[int, dict[str, object]]:
    receipts: dict[int, dict[str, object]] = {}
    for slot in range(1, 101):
        receipt = _read_json(
            _source_receipt_path(source_root, slot), label=f"source receipt {slot}"
        )
        if receipt.get("slot") != slot:
            raise RecoveryError("source receipt slot identity is invalid")
        receipts[slot] = receipt
    return receipts


def _source_receipt_fields(receipt: Mapping[str, object]) -> dict[str, object]:
    """Snapshot every source field that can affect a recovery decision or claim."""

    return {
        key: receipt.get(key)
        for key in (
            "slot",
            "episode_id",
            "authorization_id",
            "slot_contract",
            "status",
            "origin",
            "proposal",
            "controller_aggregate",
            "failure_type",
            "detail",
            "confirmation_started",
            "sealed_holdout_target_selected",
            "sealed_holdout_target_converted",
            "sealed_holdout_target_used",
        )
    }


def _validate_source(
    source_root: Path,
) -> tuple[
    dict[str, dict[str, object]],
    dict[int, dict[str, object]],
    dict[str, object],
    dict[str, object],
    list[tuple[str, int]],
    dict[str, dict[str, object]],
]:
    artifacts = {
        relative: _read_json(source_root / relative, label=f"source {relative}")
        for relative in _SOURCE_SNAPSHOT_ARTIFACTS
    }
    source_result = _read_json(
        source_root / _SOURCE_RESULT_RELATIVE, label="source result"
    )
    source_state = _read_json(
        source_root / _SOURCE_STATE_RELATIVE, label="source state"
    )
    source_authorization = _read_json(
        source_root / _SOURCE_AUTHORIZATION_RELATIVE, label="source authorization"
    )
    source_authorization_id = _validate_source_authorization(source_authorization)
    contract = artifacts["episode_contract.json"]
    resource = contract.get("resource_tool_gate")
    schedule = contract.get("receipt_schedule")
    if (
        contract.get("episode_id") != SOURCE_EPISODE_ID
        or not isinstance(resource, Mapping)
        or resource.get("receipt_slots") != 100
        or resource.get("controller_transport_retries") != 0
        or not isinstance(schedule, list)
        or len(schedule) != 100
        or source_result.get("episode_valid") is not False
        or source_result.get("protocol_complete") is not False
        or source_result.get("phase") != "COMPLETED_WITH_PROTOCOL_FAILURE"
        or source_result.get("authorization_id") != source_authorization_id
        or source_state.get("episode_id") != SOURCE_EPISODE_ID
        or source_state.get("authorization_id") != source_authorization_id
        or source_state.get("phase") != "COMPLETED_WITH_PROTOCOL_FAILURE"
        or source_state.get("terminal_slots") != list(range(1, 101))
    ):
        raise RecoveryError("source is not the terminal invalid MVE-100 v2 episode")
    by_slot = {row.get("slot"): row for row in schedule if isinstance(row, Mapping)}
    for item in RECOVERY_BATCHES:
        for source_slot in item.source_slots:
            row = by_slot.get(source_slot)
            if (
                not isinstance(row, Mapping)
                or row.get("proposal_batch") != item.batch
                or row.get("ledger_cutoff_slot") != item.ledger_cutoff
            ):
                raise RecoveryError("source recovery batch mapping is not frozen")
    receipts = _read_source_receipts(source_root)
    for slot, receipt in receipts.items():
        schedule_row = by_slot.get(slot)
        if not isinstance(schedule_row, Mapping):
            raise RecoveryError("source receipt schedule is invalid")
        if (
            receipt.get("schema_version") != SOURCE_RECEIPT_SCHEMA
            or receipt.get("episode_id") != SOURCE_EPISODE_ID
            or receipt.get("authorization_id") != source_authorization_id
            or receipt.get("slot_contract") != schedule_row
            or any(
                receipt.get(key) is not False for key in _SOURCE_RECEIPT_BOUNDARY_FIELDS
            )
        ):
            raise RecoveryError(
                "source receipt is not bound to the source authorization"
            )
    source_journals: dict[str, dict[str, object]] = {}
    for item in RECOVERY_BATCHES:
        journal_path = _source_controller_journal_path(source_root, item.batch, 0)
        journal = _read_json(
            journal_path, label=f"source controller journal {item.batch}"
        )
        _validate_source_transport_journal(
            journal, batch=item.batch, source_authorization_id=source_authorization_id
        )
        retry_path = _source_controller_journal_path(source_root, item.batch, 1)
        if retry_path.exists() or retry_path.is_symlink():
            raise RecoveryError("source transport batch must not have a retry journal")
        source_journals[item.batch] = journal
        for slot in item.source_slots:
            row = by_slot[slot]
            assert isinstance(row, Mapping)
            _validate_source_transport_receipt(
                receipts[slot],
                source_slot=slot,
                source_slot_contract=row,
                source_authorization_id=source_authorization_id,
            )
    pairs: list[tuple[str, int]] = []
    for slot in range(1, 97):
        proposal = receipts[slot].get("proposal")
        if proposal is None:
            continue
        if not isinstance(proposal, Mapping):
            raise RecoveryError("source proposal identity is invalid")
        classifier = proposal.get("classifier_key")
        term = proposal.get("term_index")
        if (
            not isinstance(classifier, str)
            or not classifier
            or isinstance(term, bool)
            or not isinstance(term, int)
            or term < 0
        ):
            raise RecoveryError("source proposal pair is invalid")
        pairs.append((classifier, term))
    if len(pairs) != 84 or len(set(pairs)) != 84:
        raise RecoveryError("source must bind exactly 84 executed candidate pairs")
    return (
        artifacts,
        receipts,
        source_result,
        source_state,
        sorted(pairs),
        source_journals,
    )


def _historical_ledger(
    receipts: Mapping[int, Mapping[str, object]], *, cutoff: int
) -> list[dict[str, object]]:
    ledger: list[dict[str, object]] = []
    for slot in range(1, cutoff + 1):
        receipt = receipts.get(slot)
        aggregate = receipt.get("controller_aggregate") if receipt else None
        if not isinstance(aggregate, Mapping) or aggregate.get("slot") != slot:
            raise RecoveryError("source historical ledger is incomplete")
        ledger.append(dict(aggregate))
    return ledger


def _build_contract(
    *,
    source_root: Path,
    source_authorization: Mapping[str, object],
    source_result: Mapping[str, object],
) -> dict[str, object]:
    source_authorization_id = source_authorization.get("authorization_id")
    if not isinstance(source_authorization_id, str) or not source_authorization_id:
        raise RecoveryError("source authorization identity is invalid")
    return {
        "schema_version": RECOVERY_CONTRACT_SCHEMA,
        "episode_id": RECOVERY_EPISODE_ID,
        "scope": RECOVERY_SCOPE,
        "source": {
            "episode_id": SOURCE_EPISODE_ID,
            "bundle_dir": str(source_root),
            "authorization_id": source_authorization_id,
            "result_phase": source_result.get("phase"),
            "protocol_complete": False,
            "episode_valid": False,
            "receipt_count": 100,
            "executed_pair_count": 84,
            "field_snapshot": "private/source_field_snapshot.json",
        },
        "recovery_schedule": _recovery_schedule(),
        "resource_tool_gate": _resource_tool_gate(),
        "post_hoc_pair_identity_visibility": POST_HOC_PAIR_IDENTITY_VISIBILITY,
        "boundaries": _boundaries(),
    }


def recovery_authorization_template(
    contract: Mapping[str, object],
) -> dict[str, object]:
    """Return a new human-filled authorization, never the source v2 grant."""

    source = contract.get("source")
    if not isinstance(source, Mapping):
        raise RecoveryError("recovery contract lacks a source binding")
    return {
        "schema_version": RECOVERY_AUTHORIZATION_SCHEMA,
        "episode_id": RECOVERY_EPISODE_ID,
        "scope": RECOVERY_SCOPE,
        "authorized": False,
        "authorization_id": "FILL_BY_HUMAN",
        "authorized_by": "FILL_BY_HUMAN",
        "rationale": "FILL_BY_HUMAN",
        "source_episode_id": SOURCE_EPISODE_ID,
        "source_authorization_id": source.get("authorization_id"),
        "confirmation_authorization": "NOT_GRANTED",
        "scientific_acceptance_authorization": "NOT_GRANTED",
    }


def prepare_recovery_bundle(
    *, source_bundle: Path | str, output_bundle: Path | str
) -> Path:
    """Create a new recovery bundle by copying only source-visible inputs.

    ``output_bundle`` must be a fresh, separate directory.  This writer never
    opens a source path for writing and all generated paths are rooted below the
    recovery bundle.
    """

    source_root = _regular_directory(Path(source_bundle), label="source bundle")
    output_root = Path(output_bundle).resolve()
    _assert_separate_roots(source_root, output_root)
    if output_root.exists():
        raise RecoveryError("recovery output bundle must not already exist")
    (
        artifacts,
        receipts,
        source_result,
        source_state,
        source_pairs,
        source_journals,
    ) = _validate_source(source_root)
    source_authorization = _read_json(
        source_root / "authorization.json", label="source authorization"
    )
    output_root.mkdir(parents=True, exist_ok=False)
    contract = _build_contract(
        source_root=source_root,
        source_authorization=source_authorization,
        source_result=source_result,
    )
    for relative, payload in artifacts.items():
        _write_json(output_root, f"snapshot/{relative}", payload)
    ledger_files: dict[str, str] = {}
    for item in RECOVERY_BATCHES:
        relative = f"private/historical_ledgers/{item.batch}.json"
        ledger_files[item.batch] = relative
        _write_json(
            output_root,
            relative,
            {
                "schema_version": RECOVERY_LEDGER_SCHEMA,
                "source_episode_id": SOURCE_EPISODE_ID,
                "batch": item.batch,
                "ledger_cutoff": item.ledger_cutoff,
                "source_slots": list(range(1, item.ledger_cutoff + 1)),
                "aggregate_ledger": _historical_ledger(
                    receipts, cutoff=item.ledger_cutoff
                ),
            },
        )
    _write_json(
        output_root,
        "private/pair_exclusions.json",
        {
            "schema_version": "br.foundation_episode.recovery12.pair_exclusions.v1",
            "v1_frozen_pairs": pair_records(list(V1_EXCLUDED_CANDIDATE_PAIRS)),
            "source_v2_executed_pairs": pair_records(source_pairs),
            "post_hoc_pair_identity_visibility": POST_HOC_PAIR_IDENTITY_VISIBILITY,
        },
    )
    _write_json(
        output_root,
        "private/source_field_snapshot.json",
        {
            "schema_version": SOURCE_FIELD_SNAPSHOT_SCHEMA,
            "source_bundle": str(source_root),
            "artifact_fields": artifacts,
            "source_result": source_result,
            "source_state": source_state,
            "source_authorization": source_authorization,
            "source_controller_journals": source_journals,
            "receipt_fields": [
                _source_receipt_fields(receipts[slot]) for slot in range(1, 101)
            ],
        },
    )
    _write_json(output_root, "recovery_contract.json", contract)
    _write_json(
        output_root,
        "preflight.json",
        {
            "schema_version": "br.foundation_episode.recovery12.preflight.v1",
            "episode_id": RECOVERY_EPISODE_ID,
            "scope": RECOVERY_SCOPE,
            "phase": "AWAITING_RECOVERY_AUTHORIZATION",
            "launch_ready": True,
            "source_episode_valid": False,
            "source_mutation_detected": False,
            "historical_ledger_files": ledger_files,
            "recovery_receipt_slots": RECOVERY_RECEIPT_COUNT,
            **_boundaries(),
        },
    )
    _write_json(
        output_root,
        "public/recovery_controller_output_schema.json",
        recovery_controller_response_schema(),
    )
    _write_json(
        output_root,
        "public/recovery_controller_transport.json",
        _recovery_controller_transport(),
    )
    _write_json(
        output_root,
        "authorization.template.json",
        recovery_authorization_template(contract),
    )
    return output_root


def _validate_contract(contract: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "episode_id",
        "scope",
        "source",
        "recovery_schedule",
        "resource_tool_gate",
        "post_hoc_pair_identity_visibility",
        "boundaries",
    }
    if (
        set(contract) != required
        or contract.get("schema_version") != RECOVERY_CONTRACT_SCHEMA
        or contract.get("episode_id") != RECOVERY_EPISODE_ID
        or contract.get("scope") != RECOVERY_SCOPE
        or contract.get("recovery_schedule") != _recovery_schedule()
        or contract.get("resource_tool_gate") != _resource_tool_gate()
        or contract.get("post_hoc_pair_identity_visibility")
        != POST_HOC_PAIR_IDENTITY_VISIBILITY
        or contract.get("boundaries") != _boundaries()
    ):
        raise RecoveryError("recovery contract is not frozen")
    source = contract.get("source")
    if (
        not isinstance(source, Mapping)
        or set(source)
        != {
            "episode_id",
            "bundle_dir",
            "authorization_id",
            "result_phase",
            "protocol_complete",
            "episode_valid",
            "receipt_count",
            "executed_pair_count",
            "field_snapshot",
        }
        or source.get("episode_id") != SOURCE_EPISODE_ID
        or not isinstance(source.get("bundle_dir"), str)
        or not source.get("bundle_dir")
        or not isinstance(source.get("authorization_id"), str)
        or not source.get("authorization_id")
        or source.get("result_phase") != "COMPLETED_WITH_PROTOCOL_FAILURE"
        or source.get("protocol_complete") is not False
        or source.get("episode_valid") is not False
        or source.get("receipt_count") != 100
        or source.get("executed_pair_count") != 84
        or source.get("field_snapshot") != "private/source_field_snapshot.json"
    ):
        raise RecoveryError("recovery source binding is invalid")


def _artifact_snapshots(root: Path) -> dict[str, dict[str, object]]:
    return {
        alias: _read_json(root / "snapshot" / relative, label=f"snapshot {relative}")
        for relative, alias in _ARTIFACT_ALIASES.items()
    }


def _assert_source_unchanged(root: Path, contract: Mapping[str, object]) -> None:
    source = contract.get("source")
    if not isinstance(source, Mapping):
        raise RecoveryError("recovery source binding is invalid")
    source_root = _regular_directory(
        Path(str(source["bundle_dir"])), label="source bundle"
    )
    _assert_separate_roots(source_root, root)
    snapshot = _read_json(
        root / "private" / "source_field_snapshot.json", label="source field snapshot"
    )
    snapshotted_artifacts = _artifact_snapshots(root)
    expected_artifacts = {
        relative: snapshotted_artifacts[alias]
        for relative, alias in _ARTIFACT_ALIASES.items()
    }
    required_snapshot = {
        "schema_version",
        "source_bundle",
        "artifact_fields",
        "source_result",
        "source_state",
        "source_authorization",
        "source_controller_journals",
        "receipt_fields",
    }
    if (
        set(snapshot) != required_snapshot
        or snapshot.get("schema_version") != SOURCE_FIELD_SNAPSHOT_SCHEMA
        or snapshot.get("source_bundle") != str(source_root)
        or snapshot.get("artifact_fields") != expected_artifacts
    ):
        raise RecoveryError("source field snapshot is invalid")
    if not isinstance(
        snapshot.get("source_authorization"), Mapping
    ) or _validate_source_authorization(snapshot["source_authorization"]) != source.get(
        "authorization_id"
    ):
        raise RecoveryError("source authorization snapshot is invalid")
    artifacts = snapshot.get("artifact_fields")
    if not isinstance(artifacts, Mapping):
        raise RecoveryError("source field snapshot artifacts are invalid")
    for relative, expected in artifacts.items():
        if (
            not isinstance(relative, str)
            or _read_json(source_root / relative, label=f"source {relative}")
            != expected
        ):
            raise RecoveryError("source bundle fields changed after recovery preflight")
    if (
        _read_json(source_root / _SOURCE_RESULT_RELATIVE, label="source result")
        != snapshot.get("source_result")
        or _read_json(source_root / _SOURCE_STATE_RELATIVE, label="source state")
        != snapshot.get("source_state")
        or _read_json(
            source_root / _SOURCE_AUTHORIZATION_RELATIVE, label="source authorization"
        )
        != snapshot.get("source_authorization")
    ):
        raise RecoveryError("source terminal fields changed after recovery preflight")
    source_journals = snapshot.get("source_controller_journals")
    if not isinstance(source_journals, Mapping) or set(source_journals) != {
        item.batch for item in RECOVERY_BATCHES
    }:
        raise RecoveryError("source controller journal snapshot is invalid")
    source_authorization_id = str(source["authorization_id"])
    for batch, expected in source_journals.items():
        if not isinstance(batch, str) or not isinstance(expected, Mapping):
            raise RecoveryError("source controller journal snapshot is invalid")
        _validate_source_transport_journal(
            expected, batch=batch, source_authorization_id=source_authorization_id
        )
        if (
            _read_json(
                _source_controller_journal_path(source_root, batch, 0),
                label=f"source controller journal {batch}",
            )
            != expected
        ):
            raise RecoveryError(
                "source controller journal changed after recovery preflight"
            )
        retry_path = _source_controller_journal_path(source_root, batch, 1)
        if retry_path.exists() or retry_path.is_symlink():
            raise RecoveryError("source transport batch gained a retry journal")
    expected_receipts = snapshot.get("receipt_fields")
    if not isinstance(expected_receipts, list) or len(expected_receipts) != 100:
        raise RecoveryError("source receipt field snapshot is invalid")
    observed = [
        _source_receipt_fields(
            _read_json(
                _source_receipt_path(source_root, slot), label=f"source receipt {slot}"
            )
        )
        for slot in range(1, 101)
    ]
    if observed != expected_receipts:
        raise RecoveryError("source receipt fields changed after recovery preflight")


def _assert_historical_ledgers_match_snapshot(authority: RecoveryAuthority) -> None:
    snapshot = _read_json(
        authority.bundle_dir / "private" / "source_field_snapshot.json",
        label="source field snapshot",
    )
    receipt_fields = snapshot.get("receipt_fields")
    if not isinstance(receipt_fields, list) or len(receipt_fields) != 100:
        raise RecoveryError("source receipt field snapshot is invalid")
    by_slot = {
        row.get("slot"): row for row in receipt_fields if isinstance(row, Mapping)
    }
    for batch in RECOVERY_BATCHES:
        expected_ledger: list[dict[str, object]] = []
        for slot in range(1, batch.ledger_cutoff + 1):
            receipt = by_slot.get(slot)
            aggregate = (
                receipt.get("controller_aggregate")
                if isinstance(receipt, Mapping)
                else None
            )
            if not isinstance(aggregate, Mapping):
                raise RecoveryError("source ledger snapshot is incomplete")
            expected_ledger.append(dict(aggregate))
        observed = _read_json(
            authority.bundle_dir
            / "private"
            / "historical_ledgers"
            / f"{batch.batch}.json",
            label=f"historical ledger {batch.batch}",
        )
        expected = {
            "schema_version": RECOVERY_LEDGER_SCHEMA,
            "source_episode_id": SOURCE_EPISODE_ID,
            "batch": batch.batch,
            "ledger_cutoff": batch.ledger_cutoff,
            "source_slots": list(range(1, batch.ledger_cutoff + 1)),
            "aggregate_ledger": expected_ledger,
        }
        if observed != expected:
            raise RecoveryError("historical ledger differs from the source snapshot")


def _verify_authorization(
    root: Path, authorization_path: Path | str, contract: Mapping[str, object]
) -> dict[str, object]:
    authorization = _read_json(Path(authorization_path), label="recovery authorization")
    source = contract["source"]
    assert isinstance(source, Mapping)
    required = {
        "schema_version",
        "episode_id",
        "scope",
        "authorized",
        "authorization_id",
        "authorized_by",
        "rationale",
        "source_episode_id",
        "source_authorization_id",
        "confirmation_authorization",
        "scientific_acceptance_authorization",
    }
    if (
        set(authorization) != required
        or authorization.get("schema_version") != RECOVERY_AUTHORIZATION_SCHEMA
        or authorization.get("episode_id") != RECOVERY_EPISODE_ID
        or authorization.get("scope") != RECOVERY_SCOPE
        or authorization.get("authorized") is not True
        or authorization.get("source_episode_id") != SOURCE_EPISODE_ID
        or authorization.get("source_authorization_id")
        != source.get("authorization_id")
        or authorization.get("confirmation_authorization") != "NOT_GRANTED"
        or authorization.get("scientific_acceptance_authorization") != "NOT_GRANTED"
    ):
        raise RecoveryError("authorization is not a recovery12-only grant")
    for key in ("authorization_id", "authorized_by", "rationale"):
        value = authorization.get(key)
        if (
            not isinstance(value, str)
            or not value.strip()
            or value.startswith("FILL_BY_")
        ):
            raise RecoveryError(f"recovery authorization {key} is a placeholder")
    return authorization


def verify_recovery_authorization(
    bundle_dir: Path | str, authorization_path: Path | str
) -> RecoveryAuthority:
    """Verify a new recovery grant and immutable source snapshots."""

    root = _regular_directory(Path(bundle_dir), label="recovery bundle")
    contract = _read_json(root / "recovery_contract.json", label="recovery contract")
    _validate_contract(contract)
    preflight = _read_json(root / "preflight.json", label="recovery preflight")
    expected_ledger_files = {
        batch.batch: f"private/historical_ledgers/{batch.batch}.json"
        for batch in RECOVERY_BATCHES
    }
    expected_preflight = {
        "schema_version": "br.foundation_episode.recovery12.preflight.v1",
        "episode_id": RECOVERY_EPISODE_ID,
        "scope": RECOVERY_SCOPE,
        "phase": "AWAITING_RECOVERY_AUTHORIZATION",
        "launch_ready": True,
        "source_episode_valid": False,
        "source_mutation_detected": False,
        "historical_ledger_files": expected_ledger_files,
        "recovery_receipt_slots": RECOVERY_RECEIPT_COUNT,
        **_boundaries(),
    }
    if preflight != expected_preflight:
        raise RecoveryError("recovery preflight is not launch-ready")
    authorization = _verify_authorization(root, authorization_path, contract)
    artifacts = _artifact_snapshots(root)
    output_schema = _read_json(
        root / "public" / "recovery_controller_output_schema.json",
        label="recovery output schema",
    )
    if output_schema != recovery_controller_response_schema():
        raise RecoveryError("recovery controller output schema is not frozen")
    transport = _read_json(
        root / "public" / "recovery_controller_transport.json",
        label="recovery controller transport",
    )
    if transport != _recovery_controller_transport():
        raise RecoveryError("recovery controller transport is not the frozen pin")
    _assert_source_unchanged(root, contract)
    authority = RecoveryAuthority(root, authorization, contract, artifacts)
    _assert_historical_ledgers_match_snapshot(authority)
    _base_pair_exclusions(authority)
    return authority


def _state_path(root: Path) -> Path:
    return root / "private" / "recovery_state.json"


def _receipt_path(root: Path, recovery_slot: int) -> Path:
    return (
        root
        / "private"
        / "recovery_receipts"
        / f"recovery_slot_{recovery_slot:02d}.json"
    )


def _batch_by_name(batch: object) -> RecoveryBatch:
    if not isinstance(batch, str):
        raise RecoveryError("recovery batch identity is invalid")
    for item in RECOVERY_BATCHES:
        if item.batch == batch:
            return item
    raise RecoveryError("recovery batch identity is invalid")


def _initial_state(authority: RecoveryAuthority, now: float) -> dict[str, object]:
    return {
        "schema_version": RECOVERY_STATE_SCHEMA,
        "episode_id": RECOVERY_EPISODE_ID,
        "authorization_id": authority.authorization["authorization_id"],
        "started_at_epoch": now,
        "deadline_epoch": now + MAX_WALLTIME_SECONDS,
        "phase": "RECOVERING",
        "terminal_recovery_slots": [],
        "controller_physical_call_count": 0,
        "in_flight": None,
    }


def _record_state(authority: RecoveryAuthority, state: Mapping[str, object]) -> None:
    _write_json(authority.bundle_dir, "private/recovery_state.json", dict(state))


def _load_state(authority: RecoveryAuthority, now: float) -> dict[str, object]:
    path = _state_path(authority.bundle_dir)
    if not path.exists():
        state = _initial_state(authority, now)
        _record_state(authority, state)
        return state
    state = _read_json(path, label="recovery state")
    required = _RECOVERY_STATE_FIELDS
    started = state.get("started_at_epoch")
    deadline = state.get("deadline_epoch")
    in_flight = state.get("in_flight")
    if (
        set(state) != required
        or state.get("schema_version") != RECOVERY_STATE_SCHEMA
        or state.get("episode_id") != RECOVERY_EPISODE_ID
        or state.get("authorization_id")
        != authority.authorization.get("authorization_id")
        or isinstance(started, bool)
        or not isinstance(started, int | float)
        or not math.isfinite(float(started))
        or isinstance(deadline, bool)
        or not isinstance(deadline, int | float)
        or not math.isfinite(float(deadline))
        or float(deadline) != float(started) + MAX_WALLTIME_SECONDS
        or state.get("phase")
        not in {"RECOVERING", "COMPLETED", "COMPLETED_WITH_PROTOCOL_FAILURE"}
        or not isinstance(state.get("terminal_recovery_slots"), list)
        or not all(
            isinstance(slot, int) and 1 <= slot <= RECOVERY_RECEIPT_COUNT
            for slot in state["terminal_recovery_slots"]
        )
        or state["terminal_recovery_slots"]
        != sorted(set(state["terminal_recovery_slots"]))
        or isinstance(state.get("controller_physical_call_count"), bool)
        or not isinstance(state.get("controller_physical_call_count"), int)
        or not 0 <= state["controller_physical_call_count"] <= len(RECOVERY_BATCHES) * 2
    ):
        raise RecoveryError("recovery state is invalid")
    if in_flight is not None:
        if (
            not isinstance(in_flight, Mapping)
            or set(in_flight) != {"kind", "batch", "attempt_index", "purpose"}
            or in_flight.get("kind") != "controller"
        ):
            raise RecoveryError("recovery in-flight state is invalid")
        batch = _batch_by_name(in_flight.get("batch"))
        attempt_index = in_flight.get("attempt_index")
        purpose = in_flight.get("purpose")
        if (
            isinstance(attempt_index, bool)
            or not isinstance(attempt_index, int)
            or purpose not in _JOURNAL_PURPOSES
        ):
            raise RecoveryError("recovery in-flight state is invalid")
        _journal_path(
            authority.bundle_dir,
            batch=batch.batch,
            attempt_index=attempt_index,
            purpose=str(purpose),
        )
    return state


def _read_receipts(authority: RecoveryAuthority) -> dict[int, dict[str, object]]:
    schedule = authority.contract["recovery_schedule"]
    assert isinstance(schedule, list)
    receipt_dir = authority.bundle_dir / "private" / "recovery_receipts"
    expected_names = {
        f"recovery_slot_{int(row['recovery_slot']):02d}.json" for row in schedule
    }
    if receipt_dir.exists():
        _regular_directory(receipt_dir, label="recovery receipt directory")
        for child in receipt_dir.iterdir():
            if (
                child.name not in expected_names
                or child.is_symlink()
                or not child.is_file()
            ):
                raise RecoveryError(
                    "recovery receipt directory contains an unexpected file"
                )
    source = authority.contract["source"]
    assert isinstance(source, Mapping)
    source_authorization_id = source["authorization_id"]
    receipts: dict[int, dict[str, object]] = {}
    for row in schedule:
        assert isinstance(row, Mapping)
        recovery_slot = int(row["recovery_slot"])
        path = _receipt_path(authority.bundle_dir, recovery_slot)
        if not path.exists():
            continue
        receipt = _read_json(path, label=f"recovery receipt {recovery_slot}")
        batch = next(
            item for item in RECOVERY_BATCHES if item.batch == row["source_batch"]
        )
        source_slot_contract = next(
            contract
            for contract in _source_slot_contracts(authority, batch)
            if contract["slot"] == row["source_slot"]
        )
        if (
            set(receipt) != _RECOVERY_RECEIPT_FIELDS
            or receipt.get("schema_version") != RECOVERY_RECEIPT_SCHEMA
            or receipt.get("episode_id") != RECOVERY_EPISODE_ID
            or receipt.get("authorization_id")
            != authority.authorization.get("authorization_id")
            or receipt.get("source_episode_id") != SOURCE_EPISODE_ID
            or receipt.get("source_authorization_id") != source_authorization_id
            or receipt.get("recovery_slot") != recovery_slot
            or receipt.get("source_slot") != row.get("source_slot")
            or receipt.get("source_batch") != row.get("source_batch")
            or receipt.get("historical_ledger_cutoff")
            != row.get("historical_ledger_cutoff")
            or receipt.get("source_slot_contract") != source_slot_contract
            or receipt.get("status") not in {"succeeded", "failed"}
            or receipt.get("origin") != "recovery_controller"
            or any(receipt.get(key) is not False for key in _boundaries())
        ):
            raise RecoveryError("recovery receipt is invalid")
        proposal = receipt.get("proposal")
        evaluation = receipt.get("evaluation_receipt")
        aggregate = receipt.get("controller_aggregate")
        if proposal is not None and not isinstance(proposal, Mapping):
            raise RecoveryError("recovery receipt proposal is invalid")
        if evaluation is not None and not isinstance(evaluation, Mapping):
            raise RecoveryError("recovery receipt evaluation is invalid")
        if aggregate is not None and (
            not isinstance(aggregate, Mapping)
            or aggregate.get("slot") != row["source_slot"]
        ):
            raise RecoveryError("recovery receipt aggregate is invalid")
        if receipt["status"] == "succeeded" and (
            not isinstance(proposal, Mapping)
            or not isinstance(evaluation, Mapping)
            or not isinstance(aggregate, Mapping)
            or receipt.get("failure_type") is not None
            or receipt.get("detail") is not None
        ):
            raise RecoveryError("successful recovery receipt is incomplete")
        receipts[recovery_slot] = receipt
    return receipts


def _write_receipt(
    authority: RecoveryAuthority,
    state: dict[str, object],
    receipts: dict[int, dict[str, object]],
    *,
    schedule_row: Mapping[str, object],
    source_slot_contract: Mapping[str, object],
    status: str,
    proposal: Mapping[str, object] | None = None,
    evaluation_receipt: Mapping[str, object] | None = None,
    aggregate: Mapping[str, object] | None = None,
    failure_type: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> None:
    recovery_slot = int(schedule_row["recovery_slot"])
    if recovery_slot in receipts:
        return
    if status not in {"succeeded", "failed"}:
        raise RecoveryError("recovery receipt status is invalid")
    payload = {
        "schema_version": RECOVERY_RECEIPT_SCHEMA,
        "episode_id": RECOVERY_EPISODE_ID,
        "authorization_id": authority.authorization["authorization_id"],
        "source_episode_id": SOURCE_EPISODE_ID,
        "source_authorization_id": authority.contract["source"]["authorization_id"],
        "recovery_slot": recovery_slot,
        "source_slot": schedule_row["source_slot"],
        "source_batch": schedule_row["source_batch"],
        "historical_ledger_cutoff": schedule_row["historical_ledger_cutoff"],
        "source_slot_contract": dict(source_slot_contract),
        "status": status,
        "origin": "recovery_controller",
        "proposal": dict(proposal) if proposal is not None else None,
        "evaluation_receipt": (
            dict(evaluation_receipt) if evaluation_receipt is not None else None
        ),
        "controller_aggregate": dict(aggregate) if aggregate is not None else None,
        "failure_type": failure_type,
        "detail": dict(detail) if detail is not None else None,
        **_boundaries(),
    }
    _write_json(
        authority.bundle_dir,
        f"private/recovery_receipts/recovery_slot_{recovery_slot:02d}.json",
        payload,
    )
    receipts[recovery_slot] = payload
    state["terminal_recovery_slots"] = sorted(receipts)
    _record_state(authority, state)


def _journal_path(root: Path, *, batch: str, attempt_index: int, purpose: str) -> Path:
    if (
        batch not in {item.batch for item in RECOVERY_BATCHES}
        or attempt_index not in {0, 1}
        or purpose not in _JOURNAL_PURPOSES
        or (attempt_index == 0 and purpose != "primary")
        or (attempt_index == 1 and purpose == "primary")
    ):
        raise RecoveryError("recovery controller journal identity is invalid")
    return (
        root
        / "private"
        / "recovery_controller_calls"
        / f"{batch}.{attempt_index}.{purpose}.json"
    )


def _read_journal(
    authority: RecoveryAuthority,
    *,
    batch: RecoveryBatch,
    attempt_index: int,
    purpose: str,
    slots: Sequence[Mapping[str, object]],
    pair_exclusions: Sequence[object],
) -> dict[str, object] | None:
    path = _journal_path(
        authority.bundle_dir,
        batch=batch.batch,
        attempt_index=attempt_index,
        purpose=purpose,
    )
    if path.is_symlink():
        raise RecoveryError("recovery controller journal must not be a symlink")
    if not path.exists():
        return None
    record = _read_json(path, label="recovery controller journal")
    status = record.get("status")
    source = authority.contract["source"]
    assert isinstance(source, Mapping)
    if (
        not isinstance(status, str)
        or record.get("schema_version") != RECOVERY_JOURNAL_SCHEMA
        or record.get("episode_id") != RECOVERY_EPISODE_ID
        or record.get("authorization_id")
        != authority.authorization.get("authorization_id")
        or record.get("source_episode_id") != SOURCE_EPISODE_ID
        or record.get("source_authorization_id") != source.get("authorization_id")
        or record.get("batch") != batch.batch
        or record.get("source_slots") != list(batch.source_slots)
        or record.get("ledger_cutoff") != batch.ledger_cutoff
        or record.get("attempt_index") != attempt_index
        or record.get("purpose") != purpose
        or record.get("timeout_seconds") != int(CONTROLLER_TIMEOUT_SECONDS)
        or status not in {"succeeded", "timeout", "schema_invalid", "transport_failed"}
    ):
        raise RecoveryError("recovery controller journal is invalid")
    if status == "succeeded":
        if (
            set(record) != _RECOVERY_JOURNAL_BASE_FIELDS | {"decisions"}
            or not isinstance(record.get("decisions"), list)
            or len(record["decisions"]) != 2
        ):
            raise RecoveryError("recovery controller success journal lacks decisions")
        try:
            validated = parse_recovery_batch_decisions(
                json.dumps({"decisions": record["decisions"]}, sort_keys=True),
                sanitized_catalog=authority.artifacts["sanitized_catalog"],
                metric_catalog=authority.artifacts["metric_catalog"],
                current_slot_contracts=slots,
                pair_exclusions=pair_exclusions,
            )
        except RecoveryControllerError as exc:
            raise RecoveryError(
                "recovery controller success journal no longer validates"
            ) from exc
        if validated != record["decisions"]:
            raise RecoveryError(
                "recovery controller journal decisions are not canonical"
            )
    elif (
        not isinstance(record.get("error_type"), str)
        or not record["error_type"]
        or (
            status == "schema_invalid"
            and (
                set(record)
                != _RECOVERY_JOURNAL_BASE_FIELDS
                | {"error_type", "validation_error_code"}
                or record.get("validation_error_code")
                not in RECOVERY_REPAIR_ERROR_CODES
            )
        )
        or (
            status != "schema_invalid"
            and set(record) != _RECOVERY_JOURNAL_BASE_FIELDS | {"error_type"}
        )
    ):
        raise RecoveryError("recovery controller failure journal lacks strict fields")
    return record


def _terminal_failure_from_journals(
    primary: Mapping[str, object] | None,
    retry_or_repair: Mapping[str, object] | None,
) -> _ControllerTerminalError | None:
    if primary is None:
        return None
    primary_status = primary.get("status")
    if primary_status == "transport_failed":
        if retry_or_repair is not None:
            raise RecoveryError("transport-failed primary journal has a second call")
        return _ControllerTerminalError(
            "controller_transport_failed",
            str(primary.get("error_type", "RecoveryError")),
        )
    if primary_status == "timeout" and retry_or_repair is not None:
        if retry_or_repair.get("status") != "succeeded":
            return _ControllerTerminalError(
                "controller_timeout_exhausted",
                str(retry_or_repair.get("error_type", "RecoveryError")),
            )
    if primary_status == "schema_invalid" and retry_or_repair is not None:
        if retry_or_repair.get("status") != "succeeded":
            return _ControllerTerminalError(
                "controller_schema_repair_exhausted",
                str(retry_or_repair.get("error_type", "RecoveryError")),
            )
    return None


def _assert_batch_receipt_journal_binding(
    receipts: Mapping[int, Mapping[str, object]],
    *,
    batch: RecoveryBatch,
    first_recovery_slot: int,
    successful: Mapping[str, object] | None,
    terminal_failure: _ControllerTerminalError | None,
) -> None:
    if successful is not None:
        decisions = _as_decisions(successful)
        for offset, decision in enumerate(decisions):
            receipt = receipts.get(first_recovery_slot + offset)
            if receipt is not None and receipt.get("proposal") != decision:
                raise RecoveryError(
                    "recovery receipt proposal does not bind its controller journal"
                )
        return
    if terminal_failure is not None:
        for recovery_slot in range(first_recovery_slot, first_recovery_slot + 2):
            receipt = receipts.get(recovery_slot)
            if receipt is not None and (
                receipt.get("status") != "failed"
                or receipt.get("proposal") is not None
                or receipt.get("evaluation_receipt") is not None
                or receipt.get("controller_aggregate") is not None
                or receipt.get("failure_type") != terminal_failure.failure_type
                or receipt.get("detail") != {"error_type": terminal_failure.error_type}
            ):
                raise RecoveryError(
                    "terminal recovery failure receipt conflicts with journal"
                )


def _revalidate_resume_journals(
    authority: RecoveryAuthority,
    state: Mapping[str, object],
    receipts: Mapping[int, Mapping[str, object]],
) -> None:
    directory = authority.bundle_dir / "private" / "recovery_controller_calls"
    expected_names = {
        f"{batch.batch}.{attempt_index}.{purpose}.json"
        for batch in RECOVERY_BATCHES
        for attempt_index, purpose in (
            (0, "primary"),
            (1, "timeout_retry"),
            (1, "schema_repair"),
        )
    }
    if directory.exists():
        _regular_directory(directory, label="recovery controller journal directory")
        for child in directory.iterdir():
            if (
                child.name not in expected_names
                or child.is_symlink()
                or not child.is_file()
            ):
                raise RecoveryError("recovery controller journal directory is invalid")
    journal_count = 0
    for batch_index, batch in enumerate(RECOVERY_BATCHES):
        first_recovery_slot = batch_index * 2 + 1
        slots = _source_slot_contracts(authority, batch)
        exclusions = _pair_exclusions_for_batch(
            authority, receipts, first_recovery_slot=first_recovery_slot
        )
        primary = _read_journal(
            authority,
            batch=batch,
            attempt_index=0,
            purpose="primary",
            slots=slots,
            pair_exclusions=exclusions,
        )
        timeout_retry = _read_journal(
            authority,
            batch=batch,
            attempt_index=1,
            purpose="timeout_retry",
            slots=slots,
            pair_exclusions=exclusions,
        )
        schema_repair = _read_journal(
            authority,
            batch=batch,
            attempt_index=1,
            purpose="schema_repair",
            slots=slots,
            pair_exclusions=exclusions,
        )
        journal_count += sum(
            record is not None for record in (primary, timeout_retry, schema_repair)
        )
        if primary is None:
            if timeout_retry is not None or schema_repair is not None:
                raise RecoveryError("recovery second journal lacks a primary call")
            continue
        if timeout_retry is not None and schema_repair is not None:
            raise RecoveryError("recovery batch has more than two physical calls")
        second = timeout_retry or schema_repair
        if primary.get("status") == "succeeded":
            if second is not None:
                raise RecoveryError("successful primary journal has a second call")
            _assert_batch_receipt_journal_binding(
                receipts,
                batch=batch,
                first_recovery_slot=first_recovery_slot,
                successful=primary,
                terminal_failure=None,
            )
            continue
        if primary.get("status") == "timeout":
            if schema_repair is not None:
                raise RecoveryError("timeout primary used the wrong second call")
        elif primary.get("status") == "schema_invalid":
            if timeout_retry is not None:
                raise RecoveryError("schema-invalid primary used the wrong second call")
        elif primary.get("status") == "transport_failed" and second is not None:
            raise RecoveryError("transport-failed primary has a forbidden retry")
        terminal_failure = _terminal_failure_from_journals(primary, second)
        successful = (
            second
            if second is not None and second.get("status") == "succeeded"
            else None
        )
        _assert_batch_receipt_journal_binding(
            receipts,
            batch=batch,
            first_recovery_slot=first_recovery_slot,
            successful=successful,
            terminal_failure=terminal_failure,
        )
    count = state.get("controller_physical_call_count")
    if count != journal_count:
        raise RecoveryError(
            "recovery state controller call count disagrees with journals"
        )


def _recover_interrupted_controller_call(
    authority: RecoveryAuthority,
    state: dict[str, object],
    receipts: Mapping[int, Mapping[str, object]],
) -> None:
    in_flight = state.get("in_flight")
    if in_flight is None:
        return
    assert isinstance(in_flight, Mapping)
    batch = _batch_by_name(in_flight.get("batch"))
    attempt_index = int(in_flight["attempt_index"])
    purpose = str(in_flight["purpose"])
    slots = _source_slot_contracts(authority, batch)
    first_recovery_slot = RECOVERY_BATCHES.index(batch) * 2 + 1
    exclusions = _pair_exclusions_for_batch(
        authority, receipts, first_recovery_slot=first_recovery_slot
    )
    saved = _read_journal(
        authority,
        batch=batch,
        attempt_index=attempt_index,
        purpose=purpose,
        slots=slots,
        pair_exclusions=exclusions,
    )
    if saved is None:
        _record_journal(
            authority,
            batch=batch.batch,
            attempt_index=attempt_index,
            purpose=purpose,
            status="transport_failed",
            ledger_cutoff=batch.ledger_cutoff,
            error_type="interrupted_controller_call",
        )
    state["in_flight"] = None
    _record_state(authority, state)


def _record_journal(
    authority: RecoveryAuthority,
    *,
    batch: str,
    attempt_index: int,
    purpose: str,
    status: str,
    ledger_cutoff: int,
    decisions: Sequence[Mapping[str, object]] | None = None,
    error_type: str | None = None,
    validation_error_code: str | None = None,
) -> dict[str, object]:
    _journal_path(
        authority.bundle_dir,
        batch=batch,
        attempt_index=attempt_index,
        purpose=purpose,
    )
    recovery_batch = next(item for item in RECOVERY_BATCHES if item.batch == batch)
    if (
        status not in {"succeeded", "timeout", "schema_invalid", "transport_failed"}
        or ledger_cutoff != recovery_batch.ledger_cutoff
    ):
        raise RecoveryError("recovery controller journal status is invalid")
    source = authority.contract["source"]
    assert isinstance(source, Mapping)
    record: dict[str, object] = {
        "schema_version": RECOVERY_JOURNAL_SCHEMA,
        "episode_id": RECOVERY_EPISODE_ID,
        "authorization_id": authority.authorization["authorization_id"],
        "source_episode_id": SOURCE_EPISODE_ID,
        "source_authorization_id": source["authorization_id"],
        "batch": batch,
        "source_slots": list(recovery_batch.source_slots),
        "attempt_index": attempt_index,
        "purpose": purpose,
        "ledger_cutoff": ledger_cutoff,
        "timeout_seconds": int(CONTROLLER_TIMEOUT_SECONDS),
        "status": status,
    }
    if status == "succeeded":
        record["decisions"] = [dict(item) for item in decisions or ()]
    else:
        record["error_type"] = error_type or "RecoveryError"
        if status == "schema_invalid":
            if validation_error_code not in RECOVERY_REPAIR_ERROR_CODES:
                raise RecoveryError("recovery validation error code is invalid")
            record["validation_error_code"] = validation_error_code
    _write_json(
        authority.bundle_dir,
        f"private/recovery_controller_calls/{batch}.{attempt_index}.{purpose}.json",
        record,
    )
    return record


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, CodexCLIExecutionError) and "timed out" in str(exc).lower()


def _dispatch_controller(
    authority: RecoveryAuthority,
    state: dict[str, object],
    *,
    batch: RecoveryBatch,
    attempt_index: int,
    purpose: str,
    prompt: str,
    slots: Sequence[Mapping[str, object]],
    ledger: Sequence[object],
    pair_exclusions: Sequence[object],
    invoker: Callable[..., object],
) -> dict[str, object]:
    saved = _read_journal(
        authority,
        batch=batch,
        attempt_index=attempt_index,
        purpose=purpose,
        slots=slots,
        pair_exclusions=pair_exclusions,
    )
    if saved is not None:
        return saved
    count = state.get("controller_physical_call_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count >= _resource_tool_gate()["controller_calls_hard_max"]
    ):
        raise RecoveryError("recovery controller physical-call budget is exhausted")
    state["controller_physical_call_count"] = count + 1
    state["in_flight"] = {
        "kind": "controller",
        "batch": batch.batch,
        "attempt_index": attempt_index,
        "purpose": purpose,
    }
    _record_state(authority, state)
    try:
        try:
            result = invoker(
                prompt=prompt,
                output_schema_path=authority.bundle_dir
                / "public"
                / "recovery_controller_output_schema.json",
                timeout_seconds=CONTROLLER_TIMEOUT_SECONDS,
            )
        except CodexCLIValidationError as exc:
            return _record_journal(
                authority,
                batch=batch.batch,
                attempt_index=attempt_index,
                purpose=purpose,
                status="schema_invalid",
                ledger_cutoff=batch.ledger_cutoff,
                error_type=type(exc).__name__,
                validation_error_code=recovery_validation_error_code(exc),
            )
        except CodexCLIError as exc:
            return _record_journal(
                authority,
                batch=batch.batch,
                attempt_index=attempt_index,
                purpose=purpose,
                status="timeout" if _is_timeout(exc) else "transport_failed",
                ledger_cutoff=batch.ledger_cutoff,
                error_type=type(exc).__name__,
            )
        except Exception as exc:  # pragma: no cover - external process boundary
            return _record_journal(
                authority,
                batch=batch.batch,
                attempt_index=attempt_index,
                purpose=purpose,
                status="transport_failed",
                ledger_cutoff=batch.ledger_cutoff,
                error_type=type(exc).__name__,
            )
        final_json = getattr(result, "final_json", None)
        if not isinstance(final_json, str):
            return _record_journal(
                authority,
                batch=batch.batch,
                attempt_index=attempt_index,
                purpose=purpose,
                status="transport_failed",
                ledger_cutoff=batch.ledger_cutoff,
                error_type="missing_final_json",
            )
        try:
            decisions = parse_recovery_batch_decisions(
                final_json,
                sanitized_catalog=authority.artifacts["sanitized_catalog"],
                metric_catalog=authority.artifacts["metric_catalog"],
                current_slot_contracts=slots,
                pair_exclusions=pair_exclusions,
            )
        except RecoveryControllerError as exc:
            return _record_journal(
                authority,
                batch=batch.batch,
                attempt_index=attempt_index,
                purpose=purpose,
                status="schema_invalid",
                ledger_cutoff=batch.ledger_cutoff,
                error_type=type(exc).__name__,
                validation_error_code=recovery_validation_error_code(exc),
            )
        return _record_journal(
            authority,
            batch=batch.batch,
            attempt_index=attempt_index,
            purpose=purpose,
            status="succeeded",
            ledger_cutoff=batch.ledger_cutoff,
            decisions=decisions,
        )
    finally:
        state["in_flight"] = None
        _record_state(authority, state)


def _as_decisions(record: Mapping[str, object]) -> list[dict[str, object]]:
    decisions = record.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != 2:
        raise RecoveryError("recovery controller decisions are invalid")
    return [dict(item) for item in decisions if isinstance(item, Mapping)]


def _run_controller_batch(
    authority: RecoveryAuthority,
    state: dict[str, object],
    *,
    batch: RecoveryBatch,
    slots: Sequence[Mapping[str, object]],
    ledger: Sequence[object],
    pair_exclusions: Sequence[object],
    invoker: Callable[..., object],
) -> list[dict[str, object]]:
    primary_prompt = build_recovery_controller_prompt(
        sanitized_catalog=authority.artifacts["sanitized_catalog"],
        metric_catalog=authority.artifacts["metric_catalog"],
        historical_ledger=ledger,
        current_slot_contracts=slots,
        recovery_batch=batch.batch,
        ledger_cutoff=batch.ledger_cutoff,
        pair_exclusions=pair_exclusions,
    )
    primary = _dispatch_controller(
        authority,
        state,
        batch=batch,
        attempt_index=0,
        purpose="primary",
        prompt=primary_prompt,
        slots=slots,
        ledger=ledger,
        pair_exclusions=pair_exclusions,
        invoker=invoker,
    )
    if primary["status"] == "succeeded":
        return _as_decisions(primary)
    if primary["status"] == "timeout":
        retry = _dispatch_controller(
            authority,
            state,
            batch=batch,
            attempt_index=1,
            purpose="timeout_retry",
            prompt=primary_prompt,
            slots=slots,
            ledger=ledger,
            pair_exclusions=pair_exclusions,
            invoker=invoker,
        )
        if retry["status"] == "succeeded":
            return _as_decisions(retry)
        raise _ControllerTerminalError(
            "controller_timeout_exhausted",
            str(retry.get("error_type", "RecoveryError")),
        )
    if primary["status"] == "schema_invalid":
        validation_error_code = primary.get("validation_error_code")
        if validation_error_code not in RECOVERY_REPAIR_ERROR_CODES:
            raise RecoveryError("recovery schema-invalid journal lacks an error code")
        repair_prompt = build_recovery_controller_prompt(
            sanitized_catalog=authority.artifacts["sanitized_catalog"],
            metric_catalog=authority.artifacts["metric_catalog"],
            historical_ledger=ledger,
            current_slot_contracts=slots,
            recovery_batch=batch.batch,
            ledger_cutoff=batch.ledger_cutoff,
            pair_exclusions=pair_exclusions,
            repair_context={
                "attempt": 1,
                "validation_error_code": validation_error_code,
            },
        )
        repair = _dispatch_controller(
            authority,
            state,
            batch=batch,
            attempt_index=1,
            purpose="schema_repair",
            prompt=repair_prompt,
            slots=slots,
            ledger=ledger,
            pair_exclusions=pair_exclusions,
            invoker=invoker,
        )
        if repair["status"] == "succeeded":
            return _as_decisions(repair)
        raise _ControllerTerminalError(
            "controller_schema_repair_exhausted",
            str(repair.get("error_type", "RecoveryError")),
        )
    raise _ControllerTerminalError(
        "controller_transport_failed", str(primary.get("error_type", "RecoveryError"))
    )


def _source_slot_contracts(
    authority: RecoveryAuthority, batch: RecoveryBatch
) -> list[dict[str, object]]:
    schedule = authority.artifacts["episode_contract"].get("receipt_schedule")
    if not isinstance(schedule, list):
        raise RecoveryError("source schedule snapshot is invalid")
    by_slot = {row.get("slot"): row for row in schedule if isinstance(row, Mapping)}
    slots: list[dict[str, object]] = []
    for source_slot in batch.source_slots:
        row = by_slot.get(source_slot)
        if (
            not isinstance(row, Mapping)
            or row.get("proposal_batch") != batch.batch
            or row.get("ledger_cutoff_slot") != batch.ledger_cutoff
        ):
            raise RecoveryError("source slot contract snapshot is invalid")
        slots.append(dict(row))
    return slots


def _load_historical_ledger(
    authority: RecoveryAuthority, batch: RecoveryBatch
) -> list[dict[str, object]]:
    ledger = _read_json(
        authority.bundle_dir / "private" / "historical_ledgers" / f"{batch.batch}.json",
        label=f"historical ledger {batch.batch}",
    )
    rows = ledger.get("aggregate_ledger")
    if (
        ledger.get("schema_version") != RECOVERY_LEDGER_SCHEMA
        or ledger.get("source_episode_id") != SOURCE_EPISODE_ID
        or ledger.get("batch") != batch.batch
        or ledger.get("ledger_cutoff") != batch.ledger_cutoff
        or ledger.get("source_slots") != list(range(1, batch.ledger_cutoff + 1))
        or not isinstance(rows, list)
        or len(rows) != batch.ledger_cutoff
    ):
        raise RecoveryError("historical ledger snapshot is invalid")
    if any(not isinstance(row, Mapping) for row in rows):
        raise RecoveryError("historical ledger rows are invalid")
    return [dict(row) for row in rows]


def _base_pair_exclusions(authority: RecoveryAuthority) -> list[tuple[str, int]]:
    payload = _read_json(
        authority.bundle_dir / "private" / "pair_exclusions.json",
        label="pair exclusions",
    )
    if (
        payload.get("schema_version")
        != "br.foundation_episode.recovery12.pair_exclusions.v1"
        or payload.get("post_hoc_pair_identity_visibility")
        != POST_HOC_PAIR_IDENTITY_VISIBILITY
    ):
        raise RecoveryError("pair exclusion snapshot is invalid")
    pairs: list[tuple[str, int]] = []
    expected_v1 = pair_records(list(V1_EXCLUDED_CANDIDATE_PAIRS))
    expected_source_pairs = _source_pair_records_from_snapshot(authority)
    for key, expected_rows in (
        ("v1_frozen_pairs", expected_v1),
        ("source_v2_executed_pairs", expected_source_pairs),
    ):
        rows = payload.get(key)
        if not isinstance(rows, list) or rows != expected_rows:
            raise RecoveryError("pair exclusion snapshot count is invalid")
        for row in rows:
            if not isinstance(row, Mapping):
                raise RecoveryError("pair exclusion snapshot entry is invalid")
            classifier = row.get("classifier_key")
            term = row.get("term_index")
            if not isinstance(classifier, str) or not isinstance(term, int):
                raise RecoveryError("pair exclusion snapshot entry is invalid")
            pairs.append((classifier, term))
    return pairs


def _source_pair_records_from_snapshot(
    authority: RecoveryAuthority,
) -> list[dict[str, object]]:
    snapshot = _read_json(
        authority.bundle_dir / "private" / "source_field_snapshot.json",
        label="source field snapshot",
    )
    receipt_fields = snapshot.get("receipt_fields")
    if not isinstance(receipt_fields, list) or len(receipt_fields) != 100:
        raise RecoveryError("source receipt field snapshot is invalid")
    pairs: list[tuple[str, int]] = []
    for receipt in receipt_fields:
        if not isinstance(receipt, Mapping) or receipt.get("slot") not in range(1, 97):
            continue
        proposal = receipt.get("proposal")
        if proposal is None:
            continue
        if not isinstance(proposal, Mapping):
            raise RecoveryError("source pair snapshot is invalid")
        classifier = proposal.get("classifier_key")
        term = proposal.get("term_index")
        if (
            not isinstance(classifier, str)
            or isinstance(term, bool)
            or not isinstance(term, int)
        ):
            raise RecoveryError("source pair snapshot is invalid")
        pairs.append((classifier, term))
    if len(pairs) != 84 or len(set(pairs)) != 84:
        raise RecoveryError("source pair snapshot is invalid")
    return pair_records(pairs)


def _pair_exclusions_for_batch(
    authority: RecoveryAuthority,
    receipts: Mapping[int, Mapping[str, object]],
    *,
    first_recovery_slot: int,
) -> list[dict[str, object]]:
    pairs = _base_pair_exclusions(authority)
    for recovery_slot in range(1, first_recovery_slot):
        receipt = receipts.get(recovery_slot)
        proposal = receipt.get("proposal") if receipt else None
        if not isinstance(proposal, Mapping):
            continue
        classifier = proposal.get("classifier_key")
        term = proposal.get("term_index")
        if isinstance(classifier, str) and isinstance(term, int):
            pairs.append((classifier, term))
    return pair_records(pairs)


def _runtime_data(authority: RecoveryAuthority) -> _RuntimeData:
    return _RuntimeData(
        SimpleNamespace(
            artifacts={
                "private_split_plan": authority.artifacts["private_split_plan"],
                "input_manifest": authority.artifacts["input_manifest"],
                "runtime_inputs": authority.artifacts["runtime_inputs"],
            }
        )
    )


def _evaluate_candidate(
    data: _RuntimeData,
    proposal: Mapping[str, object],
    *,
    source_slot: int,
    evaluator: Callable[..., object],
) -> tuple[dict[str, object], dict[str, object]]:
    classifier = proposal.get("classifier_key")
    term = proposal.get("term_index")
    if (
        not isinstance(classifier, str)
        or isinstance(term, bool)
        or not isinstance(term, int)
    ):
        raise RecoveryError("recovery proposal is not executable")
    matrix = data.matrix(term)
    targets, groups = data.targets_and_groups()
    result = evaluator(
        matrix,
        targets,
        groups,
        data.project_plan(),
        classifier,
        PARTITION_SEED,
        engine_path=data.engine_path,
        control_mode="observed",
        term_index=term,
    )
    return _aggregate_from_result(result, slot=source_slot)


def _deadline_exhausted(state: Mapping[str, object], now: float) -> bool:
    deadline = state.get("deadline_epoch")
    return not isinstance(deadline, int | float) or now >= float(deadline)


def _write_remaining_deadline_failures(
    authority: RecoveryAuthority,
    state: dict[str, object],
    receipts: dict[int, dict[str, object]],
) -> None:
    for row in authority.contract["recovery_schedule"]:
        assert isinstance(row, Mapping)
        recovery_slot = int(row["recovery_slot"])
        if recovery_slot in receipts:
            continue
        batch = next(
            item for item in RECOVERY_BATCHES if item.batch == row["source_batch"]
        )
        source_contract = next(
            contract
            for contract in _source_slot_contracts(authority, batch)
            if contract["slot"] == row["source_slot"]
        )
        _write_receipt(
            authority,
            state,
            receipts,
            schedule_row=row,
            source_slot_contract=source_contract,
            status="failed",
            failure_type="recovery_walltime_exhausted",
            detail={"error_type": "RecoveryDeadlineExceeded"},
        )


def _finalize(
    authority: RecoveryAuthority,
    state: dict[str, object],
    receipts: Mapping[int, Mapping[str, object]],
) -> RecoveryRunResult:
    complete = len(receipts) == RECOVERY_RECEIPT_COUNT
    status_counts = {
        "succeeded": sum(
            receipt.get("status") == "succeeded" for receipt in receipts.values()
        ),
        "failed": sum(
            receipt.get("status") == "failed" for receipt in receipts.values()
        ),
    }
    integrity = complete and status_counts["failed"] == 0
    state["phase"] = "COMPLETED" if integrity else "COMPLETED_WITH_PROTOCOL_FAILURE"
    state["terminal_recovery_slots"] = sorted(receipts)
    state["in_flight"] = None
    _record_state(authority, state)
    _write_json(
        authority.bundle_dir,
        "public/recovery_result.json",
        {
            "schema_version": RECOVERY_RESULT_SCHEMA,
            "episode_id": RECOVERY_EPISODE_ID,
            "scope": RECOVERY_SCOPE,
            "source_episode_id": SOURCE_EPISODE_ID,
            "source_episode_valid": False,
            "source_mutation_detected": False,
            "recovery_receipt_count": len(receipts),
            "recovery_receipt_slots_expected": RECOVERY_RECEIPT_COUNT,
            "receipt_status_counts": status_counts,
            "recovery_protocol_complete": complete,
            "recovery_integrity": integrity,
            "controller_physical_call_count": state["controller_physical_call_count"],
            "controller_calls_hard_max": _resource_tool_gate()[
                "controller_calls_hard_max"
            ],
            "scientific_acceptance": False,
            "source_result_rewritten": False,
            "host_controls_rerun": False,
            "champion_selected": False,
            "batch_lift_computed": False,
            **_boundaries(),
        },
    )
    return RecoveryRunResult(
        authority.bundle_dir,
        len(receipts),
        complete,
        integrity,
        False,
        False,
    )


def _run_recovery_locked(
    authority: RecoveryAuthority,
    *,
    evaluator: Callable[..., object] | None = None,
    invoker: Callable[..., object],
    wall_clock: Callable[[], float] = time.time,
) -> RecoveryRunResult:
    _live_single_gpu()
    now = float(wall_clock())
    if not math.isfinite(now):
        raise RecoveryError("recovery wall clock is invalid")
    state = _load_state(authority, now)
    receipts = _read_receipts(authority)
    _recover_interrupted_controller_call(authority, state, receipts)
    _revalidate_resume_journals(authority, state, receipts)
    state["terminal_recovery_slots"] = sorted(receipts)
    _record_state(authority, state)
    data: _RuntimeData | None = None
    evaluator_fn = evaluate_fresh_fit if evaluator is None else evaluator
    try:
        for batch_index, batch in enumerate(RECOVERY_BATCHES):
            first_recovery_slot = batch_index * 2 + 1
            schedule_rows = authority.contract["recovery_schedule"][
                first_recovery_slot - 1 : first_recovery_slot + 1
            ]
            assert isinstance(schedule_rows, list)
            if all(int(row["recovery_slot"]) in receipts for row in schedule_rows):
                continue
            slots = _source_slot_contracts(authority, batch)
            if _deadline_exhausted(state, float(wall_clock())):
                _write_remaining_deadline_failures(authority, state, receipts)
                break
            ledger = _load_historical_ledger(authority, batch)
            exclusions = _pair_exclusions_for_batch(
                authority, receipts, first_recovery_slot=first_recovery_slot
            )
            try:
                decisions = _run_controller_batch(
                    authority,
                    state,
                    batch=batch,
                    slots=slots,
                    ledger=ledger,
                    pair_exclusions=exclusions,
                    invoker=invoker,
                )
            except _ControllerTerminalError as exc:
                for row, source_contract in zip(schedule_rows, slots, strict=True):
                    _write_receipt(
                        authority,
                        state,
                        receipts,
                        schedule_row=row,
                        source_slot_contract=source_contract,
                        status="failed",
                        failure_type=exc.failure_type,
                        detail={"error_type": exc.error_type},
                    )
                continue
            for row, source_contract, proposal in zip(
                schedule_rows, slots, decisions, strict=True
            ):
                if int(row["recovery_slot"]) in receipts:
                    continue
                if _deadline_exhausted(state, float(wall_clock())):
                    _write_remaining_deadline_failures(authority, state, receipts)
                    break
                try:
                    if data is None:
                        data = _runtime_data(authority)
                    private, aggregate = _evaluate_candidate(
                        data,
                        proposal,
                        source_slot=int(row["source_slot"]),
                        evaluator=evaluator_fn,
                    )
                    status = (
                        "succeeded"
                        if private.get("status") == "succeeded"
                        else "failed"
                    )
                    _write_receipt(
                        authority,
                        state,
                        receipts,
                        schedule_row=row,
                        source_slot_contract=source_contract,
                        status=status,
                        proposal=proposal,
                        evaluation_receipt=private,
                        aggregate=aggregate,
                        failure_type=(
                            None
                            if status == "succeeded"
                            else "model_evaluation_failure"
                        ),
                    )
                except Exception as exc:
                    _write_receipt(
                        authority,
                        state,
                        receipts,
                        schedule_row=row,
                        source_slot_contract=source_contract,
                        status="failed",
                        proposal=proposal,
                        failure_type="model_evaluation_failure",
                        detail={"error_type": type(exc).__name__},
                    )
            if state.get("phase") == "COMPLETED_WITH_PROTOCOL_FAILURE":
                break
        if len(receipts) != RECOVERY_RECEIPT_COUNT:
            _write_remaining_deadline_failures(authority, state, receipts)
        _revalidate_resume_journals(authority, state, receipts)
        _assert_source_unchanged(authority.bundle_dir, authority.contract)
        return _finalize(authority, state, receipts)
    finally:
        _assert_source_unchanged(authority.bundle_dir, authority.contract)


def run_recovery(
    bundle_dir: Path | str,
    authorization_path: Path | str,
    *,
    evaluator: Callable[..., object] | None = None,
    invoker: Callable[..., object] = invoke_pinned_recovery_codex_cli,
    wall_clock: Callable[[], float] = time.time,
) -> RecoveryRunResult:
    """Run one locked recovery lifecycle, using the pinned CLI by default."""

    preflight_authority = verify_recovery_authorization(bundle_dir, authorization_path)
    with _exclusive_recovery_lock(preflight_authority.bundle_dir):
        authority = verify_recovery_authorization(bundle_dir, authorization_path)
        if invoker is invoke_pinned_recovery_codex_cli:
            _verify_pinned_recovery_cli()
        return _run_recovery_locked(
            authority,
            evaluator=evaluator,
            invoker=invoker,
            wall_clock=wall_clock,
        )


__all__ = [
    "CONTROLLER_TIMEOUT_SECONDS",
    "MAX_WALLTIME_SECONDS",
    "RECOVERY_AUTHORIZATION_SCHEMA",
    "RECOVERY_BATCHES",
    "RECOVERY_EPISODE_ID",
    "RECOVERY_RECEIPT_COUNT",
    "RECOVERY_SCOPE",
    "RecoveryAuthority",
    "RecoveryError",
    "RecoveryRunResult",
    "configure_recovery_runtime",
    "prepare_recovery_bundle",
    "recovery_authorization_template",
    "run_recovery",
    "verify_recovery_authorization",
]
