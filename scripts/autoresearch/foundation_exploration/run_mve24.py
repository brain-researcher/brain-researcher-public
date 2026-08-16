#!/usr/bin/env python3
"""Prepare or supervise the human-gated foundation MVE-100 v2 episode.

``preflight`` is score-blind and stops before authorization.  ``launch`` needs
an existing human authorization and starts a worker beneath a 12-hour external
TERM/KILL supervisor.  Confirmation remains unavailable here.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import IO

from brain_researcher.research.predictive.foundation_episode.contracts import (
    EPISODE_ID,
    PARTITION_SEED,
    FoundationEpisodeError,
    write_canonical_json,
)
from brain_researcher.research.predictive.foundation_episode.preflight import (
    FoundationPreflightRequest,
    run_preflight,
)
from brain_researcher.research.predictive.foundation_episode.codex_cli import (
    configure_codex_runtime,
)
from brain_researcher.research.predictive.foundation_episode.runner import (
    MAX_WALLTIME_SECONDS,
    DiscoveryAuthorization,
    DiscoveryRunResult,
    finalize_terminal_discovery,
    run_discovery,
    verify_discovery_authorization,
    verify_terminal_discovery_authorization,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--term-cache-dir", type=Path, required=True)
    preflight.add_argument("--subject-ids", type=Path, required=True)
    preflight.add_argument("--target-table", type=Path, required=True)
    preflight.add_argument("--target-manifest", type=Path, required=True)
    preflight.add_argument("--subject-intersection", type=Path, required=True)
    preflight.add_argument("--exchangeability-manifest", type=Path, required=True)
    preflight.add_argument("--catalog", type=Path, required=True)
    preflight.add_argument("--output-dir", type=Path, required=True)
    preflight.add_argument("--term-names-file", type=Path, required=True)
    preflight.add_argument("--term-prefixes-file", type=Path, required=True)
    preflight.add_argument("--kernel-source", type=Path, required=True)
    preflight.add_argument("--kernel-symbol", action="append", default=[])
    preflight.add_argument(
        "--seed", type=int, choices=(PARTITION_SEED,), default=PARTITION_SEED
    )
    launch = commands.add_parser("launch")
    launch.add_argument("--bundle-dir", type=Path, required=True)
    launch.add_argument("--authorization-path", type=Path, required=True)
    worker = commands.add_parser("discover", help=argparse.SUPPRESS)
    worker.add_argument("--bundle-dir", type=Path, required=True)
    worker.add_argument("--authorization-path", type=Path, required=True)
    worker.add_argument(
        "--supervised-worker", action="store_true", help=argparse.SUPPRESS
    )
    for command in (preflight, launch, worker):
        command.add_argument("--codex-binary")
        command.add_argument("--codex-version")
        command.add_argument("--codex-model")
        command.add_argument("--codex-reasoning-effort")
    return parser.parse_args(argv)


def _print_result(
    *, phase: str, receipt_count: int, protocol_complete: bool, episode_valid: bool
) -> None:
    print(f"MVE-100-D phase: {phase}")
    print(f"receipt count: {receipt_count}")
    print(f"protocol complete: {protocol_complete}")
    print(f"episode valid: {episode_valid}")
    print("confirmation started: false")
    print("sealed holdout target selected: false")
    print("sealed holdout target converted: false")
    print("sealed holdout target used: false")


def _result_exit_code(result: DiscoveryRunResult) -> int:
    return 0 if result.episode_valid else (4 if result.protocol_complete else 3)


def _run_worker(args: argparse.Namespace) -> int:
    try:
        result = run_discovery(args.bundle_dir, args.authorization_path)
    except FoundationEpisodeError as exc:
        print(f"MVE-100-D discovery refused: {exc}", file=sys.stderr)
        return 2
    _print_result(
        phase=result.phase,
        receipt_count=result.receipt_count,
        protocol_complete=result.protocol_complete,
        episode_valid=result.episode_valid,
    )
    return _result_exit_code(result)


def _acquire_lock(bundle_dir: Path) -> IO[str]:
    path = bundle_dir / "private" / "discovery.launch.lock"
    if path.is_symlink():
        raise FoundationEpisodeError("launch lock must not be a symlink")
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise FoundationEpisodeError(
            "another launch already holds the bundle lock"
        ) from exc
    return handle


def _release_lock(handle: IO[str]) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _worker_parent_death_signal() -> None:
    if ctypes.CDLL(None).prctl(1, signal.SIGKILL) != 0 or os.getppid() == 1:
        raise OSError("cannot establish supervised worker lifetime")


def _worker_child_setup(previous_signal_mask: set[signal.Signals]) -> None:
    """Restore the parent's pre-launch mask before installing child supervision."""

    signal.pthread_sigmask(signal.SIG_SETMASK, previous_signal_mask)
    _worker_parent_death_signal()


def _remaining_supervisor_seconds(bundle_dir: Path) -> float:
    state_path = bundle_dir / "private" / "discovery_state.json"
    if not state_path.exists() and not state_path.is_symlink():
        return float(MAX_WALLTIME_SECONDS)
    if state_path.is_symlink() or not state_path.is_file():
        raise FoundationEpisodeError("existing discovery state must be a regular file")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundationEpisodeError(
            "existing discovery state is not readable JSON"
        ) from exc
    deadline = state.get("deadline_epoch") if isinstance(state, dict) else None
    if isinstance(deadline, bool) or not isinstance(deadline, int | float):
        raise FoundationEpisodeError(
            "existing discovery state lacks a numeric deadline"
        )
    return max(0.0, float(deadline) - time.time())


def _write_execution_receipt(
    *,
    bundle_dir: Path,
    authorization_id: str,
    started: float,
    reason: str,
    hard_kill: bool,
    worker_exit_code: int | None,
    supervisor_timeout_seconds: float,
    supervisor_signal: int | None = None,
    worker_process_group_term_forwarded: bool = False,
) -> None:
    payload = {
        "schema_version": "br.foundation_episode.execution_receipt.v2",
        "episode_id": EPISODE_ID,
        "authorization_id": authorization_id,
        "walltime_target_hours": MAX_WALLTIME_SECONDS // 3600,
        "runner_deadline_mode": "between_dispatch_deadline",
        "external_process_timeout_mode": "sigterm_then_hard_kill_after_grace",
        "term_grace_seconds": 5 * 60,
        "external_hard_kill_observed": hard_kill,
        "termination_reason": reason,
        "worker_exit_code": worker_exit_code,
        "supervisor_timeout_seconds": supervisor_timeout_seconds,
        "supervisor_signal": supervisor_signal,
        "worker_process_group_term_forwarded": worker_process_group_term_forwarded,
        "elapsed_seconds": time.monotonic() - started,
    }
    write_canonical_json(
        bundle_dir / "private" / "execution_receipts" / f"launch_{time.time_ns()}.json",
        payload,
    )


def _finalize_expired_terminal(
    authority: DiscoveryAuthorization,
    *,
    started: float,
    timeout_seconds: float,
) -> int:
    try:
        result = finalize_terminal_discovery(authority)
    except FoundationEpisodeError as exc:
        _write_execution_receipt(
            bundle_dir=authority.bundle_dir,
            authorization_id=str(authority.authorization["authorization_id"]),
            started=started,
            reason="runner_deadline_elapsed_before_terminal_receipts_complete",
            hard_kill=False,
            worker_exit_code=None,
            supervisor_timeout_seconds=timeout_seconds,
        )
        print(
            f"MVE-100-D discovery refused: the existing runner deadline has elapsed; {exc}.",
            file=sys.stderr,
        )
        return 124
    _write_execution_receipt(
        bundle_dir=authority.bundle_dir,
        authorization_id=str(authority.authorization["authorization_id"]),
        started=started,
        reason="terminal_only_finalization_after_deadline",
        hard_kill=False,
        worker_exit_code=None,
        supervisor_timeout_seconds=timeout_seconds,
    )
    _print_result(
        phase=result.phase,
        receipt_count=result.receipt_count,
        protocol_complete=result.protocol_complete,
        episode_valid=result.episode_valid,
    )
    return _result_exit_code(result)


def _runtime_child_args(args: argparse.Namespace) -> list[str]:
    """Forward explicit runtime selections across the supervised process boundary."""

    forwarded: list[str] = []
    for flag, attribute in (
        ("--codex-binary", "codex_binary"),
        ("--codex-version", "codex_version"),
        ("--codex-model", "codex_model"),
        ("--codex-reasoning-effort", "codex_reasoning_effort"),
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            forwarded.extend((flag, str(value)))
    return forwarded


def _supervised_worker_command(args: argparse.Namespace) -> list[str]:
    """Build the exact child command, including explicit runtime provenance."""

    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "discover",
        "--bundle-dir",
        str(args.bundle_dir),
        "--authorization-path",
        str(args.authorization_path),
        "--supervised-worker",
        *_runtime_child_args(args),
    ]


def _supervise(args: argparse.Namespace, *, authority: DiscoveryAuthorization) -> int:
    started = time.monotonic()
    timeout_seconds = _remaining_supervisor_seconds(authority.bundle_dir)
    if timeout_seconds <= 0:
        return _finalize_expired_terminal(
            authority,
            started=started,
            timeout_seconds=timeout_seconds,
        )
    command = _supervised_worker_command(args)
    worker: subprocess.Popen[bytes] | None = None
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    previous_signal_mask: set[signal.Signals] | None = None
    signal_mask_blocked = False
    termination_signal: int | None = None

    def _request_supervisor_shutdown(signum: int, _frame: object) -> None:
        nonlocal termination_signal
        if termination_signal is None:
            termination_signal = signum

    signal.signal(signal.SIGTERM, _request_supervisor_shutdown)
    try:
        previous_signal_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM}
        )
        signal_mask_blocked = True
        try:
            worker = subprocess.Popen(
                command,
                start_new_session=True,
                preexec_fn=lambda: _worker_child_setup(previous_signal_mask),
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_signal_mask)
            signal_mask_blocked = False

        deadline = time.monotonic() + timeout_seconds
        code: int | None = None
        timed_out = False
        while termination_signal is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                code = worker.wait(timeout=min(1.0, remaining))
            except subprocess.TimeoutExpired:
                continue
            break

        if termination_signal is not None:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            hard_kill = False
            forwarded = False
            reason = "supervisor_sigterm_worker_already_exited"
            try:
                os.killpg(worker.pid, signal.SIGTERM)
                forwarded = True
                reason = "supervisor_sigterm_forwarded"
            except ProcessLookupError:
                pass
            try:
                code = worker.wait(timeout=5 * 60)
            except subprocess.TimeoutExpired:
                os.killpg(worker.pid, signal.SIGKILL)
                code = worker.wait()
                hard_kill = True
                reason = "supervisor_sigterm_hard_kill"
            _write_execution_receipt(
                bundle_dir=authority.bundle_dir,
                authorization_id=str(authority.authorization["authorization_id"]),
                started=started,
                reason=reason,
                hard_kill=hard_kill,
                worker_exit_code=code,
                supervisor_timeout_seconds=timeout_seconds,
                supervisor_signal=termination_signal,
                worker_process_group_term_forwarded=forwarded,
            )
            print(
                "MVE-100-D discovery stopped: supervisor SIGTERM forwarded to worker "
                "group.",
                file=sys.stderr,
            )
            return 128 + termination_signal

        if timed_out:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.killpg(worker.pid, signal.SIGTERM)
            reason = "external_process_timeout_sigterm"
            try:
                code = worker.wait(timeout=5 * 60)
            except subprocess.TimeoutExpired:
                os.killpg(worker.pid, signal.SIGKILL)
                code = worker.wait()
                reason = "external_process_timeout_hard_kill"
            _write_execution_receipt(
                bundle_dir=authority.bundle_dir,
                authorization_id=str(authority.authorization["authorization_id"]),
                started=started,
                reason=reason,
                hard_kill=reason == "external_process_timeout_hard_kill",
                worker_exit_code=code,
                supervisor_timeout_seconds=timeout_seconds,
                worker_process_group_term_forwarded=True,
            )
            print(
                "MVE-100-D discovery stopped: external runner-deadline process timeout.",
                file=sys.stderr,
            )
            return 124

        assert code is not None
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        _write_execution_receipt(
            bundle_dir=authority.bundle_dir,
            authorization_id=str(authority.authorization["authorization_id"]),
            started=started,
            reason="worker_exit",
            hard_kill=False,
            worker_exit_code=code,
            supervisor_timeout_seconds=timeout_seconds,
        )
        return code
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if signal_mask_blocked and previous_signal_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_signal_mask)
        signal.signal(signal.SIGTERM, previous_sigterm)


def _launch(args: argparse.Namespace) -> int:
    try:
        deadline_elapsed = _remaining_supervisor_seconds(args.bundle_dir) <= 0
        verifier = (
            verify_terminal_discovery_authorization
            if deadline_elapsed
            else verify_discovery_authorization
        )
        authority = verifier(args.bundle_dir, args.authorization_path)
        lock = _acquire_lock(authority.bundle_dir)
    except FoundationEpisodeError as exc:
        print(f"MVE-100-D discovery refused: {exc}", file=sys.stderr)
        return 2
    try:
        if deadline_elapsed:
            return _finalize_expired_terminal(
                authority,
                started=time.monotonic(),
                timeout_seconds=0.0,
            )
        return _supervise(args, authority=authority)
    finally:
        _release_lock(lock)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_codex_runtime(
        binary=getattr(args, "codex_binary", None),
        version=getattr(args, "codex_version", None),
        model=getattr(args, "codex_model", None),
        reasoning_effort=getattr(args, "codex_reasoning_effort", None),
    )
    if args.command == "launch":
        return _launch(args)
    if args.command == "discover":
        if not args.supervised_worker:
            print(
                "MVE-100-D discovery refused: use the launch supervisor.", file=sys.stderr
            )
            return 2
        return _run_worker(args)
    try:
        result = run_preflight(
            FoundationPreflightRequest(
                term_cache_dir=args.term_cache_dir,
                subject_ids_path=args.subject_ids,
                target_table_path=args.target_table,
                target_manifest_path=args.target_manifest,
                subject_intersection_path=args.subject_intersection,
                exchangeability_manifest_path=args.exchangeability_manifest,
                term_names_path=args.term_names_file,
                term_prefixes_path=args.term_prefixes_file,
                catalog_path=args.catalog,
                output_dir=args.output_dir,
                kernel_source_path=args.kernel_source,
                kernel_symbols=tuple(args.kernel_symbol),
                seed=args.seed,
            )
        )
    except FoundationEpisodeError as exc:
        print(f"MVE-100-D preflight refused: {exc}", file=sys.stderr)
        return 2
    print(f"MVE-100-D phase: {result.phase}")
    print(f"launch ready: {result.launch_ready}")
    print("discovery started: false")
    print("confirmation: not granted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
