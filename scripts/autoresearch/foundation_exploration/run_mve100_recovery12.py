#!/usr/bin/env python3
"""Prepare or foreground-launch the bounded MVE-100 v2 recovery episode.

``preflight`` creates a new recovery bundle from a read-only source bundle.
``launch`` executes that separate recovery bundle in the foreground.  The
recovery state machine, rather than this wrapper, checks its 12-hour deadline
before each dispatch.  Neither command resumes or rewrites the source v2
episode.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from brain_researcher.research.predictive.foundation_episode.contracts import (
    FoundationEpisodeError,
)
from brain_researcher.research.predictive.foundation_episode.recovery import (
    RECOVERY_EPISODE_ID,
    prepare_recovery_bundle,
    run_recovery,
    configure_recovery_runtime,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the two deliberately narrow recovery operations."""

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--source-bundle", type=Path, required=True)
    preflight.add_argument("--output-dir", type=Path, required=True)
    preflight.add_argument("--codex-binary")
    preflight.add_argument("--codex-version")

    launch = commands.add_parser("launch")
    launch.add_argument("--bundle-dir", type=Path, required=True)
    launch.add_argument("--authorization-path", type=Path, required=True)
    launch.add_argument("--codex-binary")
    launch.add_argument("--codex-version")

    return parser.parse_args(argv)


def _print_status(
    *, phase: str, receipt_count: int, protocol_complete: bool, integrity: bool
) -> None:
    """Print the operational result without implying a repaired source episode."""

    print(f"MVE-100 recovery12 episode: {RECOVERY_EPISODE_ID}")
    print(f"phase: {phase}")
    print(f"receipt_count: {receipt_count}")
    print(f"protocol_complete: {str(protocol_complete).lower()}")
    print(f"integrity: {str(integrity).lower()}")
    print("source_v2_remains_invalid: true")
    print("source_v2_episode_valid: false")
    print("confirmation_started: false")
    print("scientific_acceptance: false")


def _preflight(args: argparse.Namespace) -> int:
    bundle = prepare_recovery_bundle(
        source_bundle=args.source_bundle,
        output_bundle=args.output_dir,
    )
    print(f"MVE-100 recovery12 preflight bundle: {bundle}")
    _print_status(
        phase="AWAITING_RECOVERY_AUTHORIZATION",
        receipt_count=0,
        protocol_complete=False,
        integrity=False,
    )
    return 0


def _launch(args: argparse.Namespace) -> int:
    result = run_recovery(args.bundle_dir, args.authorization_path)
    phase = (
        "COMPLETED" if result.recovery_integrity else "COMPLETED_WITH_PROTOCOL_FAILURE"
    )
    _print_status(
        phase=phase,
        receipt_count=result.receipt_count,
        protocol_complete=result.recovery_protocol_complete,
        integrity=result.recovery_integrity,
    )
    if result.recovery_integrity:
        return 0
    return 4 if result.recovery_protocol_complete else 3


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_recovery_runtime(
        binary=getattr(args, "codex_binary", None),
        version=getattr(args, "codex_version", None),
    )
    try:
        return _preflight(args) if args.command == "preflight" else _launch(args)
    except FoundationEpisodeError as exc:
        print(f"MVE-100 recovery12 refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
