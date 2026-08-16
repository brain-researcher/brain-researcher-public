#!/usr/bin/env python3
"""Prepare or launch the human-gated, development-only HCP R2 procedure.

``prepare`` persists the complete R2 contract, all ten repeat split arrays,
one private 244-row development-target snapshot, and an inactive authorization
template.  ``launch`` only consumes a manually completed template already in
that output directory and verifies the current 244-row source target against
the snapshot.  Neither command reads adaptive82 target values; the historical
Liu result path is checked for presence but its predictions are never loaded
or reused.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from brain_researcher.research.predictive import hcp_calibration_equivalence_r2 as r2
from brain_researcher.research.predictive import hcp_liu_matched_comparator as liu
from brain_researcher.research.predictive import hcp_nested100_replay as replay


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "launch"):
        command = subparsers.add_parser(name)
        command.add_argument("--source-bundle", type=Path, required=True)
        command.add_argument("--nested100-result", type=Path, required=True)
        command.add_argument("--r1-result", type=Path, required=True)
        command.add_argument("--liu-frozen-contract", type=Path, required=True)
        command.add_argument(
            "--liu-result",
            type=Path,
            required=True,
            help="Historical path retained for provenance only; its content is not read.",
        )
        command.add_argument("--output-dir", type=Path, required=True)
        if name == "prepare":
            command.add_argument(
                "--repeat-workers", type=int, default=r2.DEFAULT_REPEAT_WORKERS
            )
    return parser


def _inputs(
    args: argparse.Namespace,
) -> tuple[
    replay.HCPDataset,
    dict[str, object],
    dict[str, object],
    tuple[dict[str, object], ...],
    dict[str, object],
    dict[str, str],
]:
    if not args.liu_result.is_file():
        raise r2.CalibrationEquivalenceR2Error(
            "Liu result path is missing; its content remains intentionally unread"
        )
    dataset = replay.load_hcp_dataset(args.source_bundle)
    nested100_result = liu.read_nested100_reference(args.nested100_result)
    r1_result = r2._read_json(args.r1_result, label="R1 result")
    metric_catalog = liu.load_common_support_metric_catalog(args.source_bundle)
    liu_frozen_contract = liu.read_frozen_liu_matched_contract(args.liu_frozen_contract)
    source_paths = {
        "source_bundle": str(args.source_bundle),
        "nested100_result": str(args.nested100_result),
        "r1_result": str(args.r1_result),
        "liu_frozen_contract": str(args.liu_frozen_contract),
        "liu_result": str(args.liu_result),
    }
    return (
        dataset,
        nested100_result,
        r1_result,
        metric_catalog,
        liu_frozen_contract,
        source_paths,
    )


def _prepare(args: argparse.Namespace) -> dict[str, Path]:
    (
        dataset,
        nested100_result,
        r1_result,
        metric_catalog,
        liu_frozen_contract,
        source_paths,
    ) = _inputs(args)
    contract = r2.prepare_calibration_equivalence_contract(
        dataset=dataset,
        nested100_result=nested100_result,
        r1_result=r1_result,
        metric_catalog=metric_catalog,
        liu_frozen_contract=liu_frozen_contract,
        source_paths=source_paths,
        repeat_workers=args.repeat_workers,
    )
    development_target_snapshot = r2.build_development_target_snapshot(
        dataset=dataset,
        contract=contract,
    )
    return r2.write_prelaunch_artifacts(
        output_dir=args.output_dir,
        dataset=dataset,
        contract=contract,
        development_target_snapshot=development_target_snapshot,
    )


def _launch(args: argparse.Namespace) -> dict[str, object]:
    (
        dataset,
        nested100_result,
        r1_result,
        metric_catalog,
        liu_frozen_contract,
        source_paths,
    ) = _inputs(args)
    return r2.run_calibration_equivalence(
        output_dir=args.output_dir,
        dataset=dataset,
        nested100_result=nested100_result,
        r1_result=r1_result,
        metric_catalog=metric_catalog,
        liu_frozen_contract=liu_frozen_contract,
        source_paths=source_paths,
        source_bundle_path=args.source_bundle,
        progress=lambda message: print(message, flush=True),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            paths = _prepare(args)
            print(f"R2 contract: {paths['contract']}")
            print(f"R2 splits: {paths['splits']}")
            print(f"R2 authorization: {paths['authorization']}")
            print(
                f"R2 development target snapshot: {paths['development_target_snapshot']}"
            )
            print(
                "R2 authority: awaiting exact externally supplied human authorization"
            )
            print(
                "adaptive82 reuse, confirmation, R3, scientific acceptance: NOT_GRANTED"
            )
            return 0
        result = _launch(args)
    except r2.CalibrationEquivalenceR2Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"R2 phase: {result.get('phase')}")
    print(f"R2 result: {args.output_dir / 'r2_result.json'}")
    return 0 if result.get("phase") == "AWAITING_HUMAN_REVIEW" else 3


if __name__ == "__main__":
    raise SystemExit(main())
