#!/usr/bin/env python3
"""Prepare or launch the human-gated HCP cross-component transfer R3."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from brain_researcher.research.predictive import (
    hcp_cross_component_transfer_r3 as transfer,
)
from brain_researcher.research.predictive import hcp_liu_matched_comparator as liu
from brain_researcher.research.predictive import hcp_nested100_replay as replay


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "validate-authorization", "launch"):
        command = commands.add_parser(name)
        command.add_argument("--source-bundle", type=Path, required=True)
        command.add_argument("--r2-contract", type=Path, required=True)
        command.add_argument("--r2-result", type=Path, required=True)
        command.add_argument("--liu-frozen-contract", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
        if name == "prepare":
            command.add_argument(
                "--workers", type=int, default=transfer.DEFAULT_WORKERS
            )
    return parser


def _inputs(args: argparse.Namespace):
    dataset = replay.load_hcp_dataset(args.source_bundle)
    r2_contract = transfer._read_json(args.r2_contract, label="R2 contract")
    r2_result = transfer._read_json(args.r2_result, label="R2 result")
    liu_contract = liu.read_frozen_liu_matched_contract(args.liu_frozen_contract)
    source_paths = {
        "source_bundle": str(args.source_bundle),
        "r2_contract": str(args.r2_contract),
        "r2_result": str(args.r2_result),
        "liu_frozen_contract": str(args.liu_frozen_contract),
    }
    return dataset, r2_contract, r2_result, liu_contract, source_paths


def _prepare(args: argparse.Namespace) -> dict[str, Path]:
    dataset, r2_contract, r2_result, liu_contract, source_paths = _inputs(args)
    contract = transfer.prepare_cross_component_transfer_contract(
        dataset=dataset,
        r2_contract=r2_contract,
        r2_result=r2_result,
        liu_frozen_contract=liu_contract,
        source_paths=source_paths,
        workers=args.workers,
    )
    return transfer.write_prelaunch_artifacts(
        output_dir=args.output_dir, dataset=dataset, contract=contract
    )


def _validate_authorization(args: argparse.Namespace) -> None:
    dataset, r2_contract, r2_result, liu_contract, source_paths = _inputs(args)
    contract, splits, identity = transfer.read_prelaunch(args.output_dir)
    expected = transfer.prepare_cross_component_transfer_contract(
        dataset=dataset,
        r2_contract=r2_contract,
        r2_result=r2_result,
        liu_frozen_contract=liu_contract,
        source_paths=source_paths,
        workers=int(contract["execution"]["workers"]),
    )
    if contract != expected or splits != contract["splits"]:
        raise transfer.CrossComponentTransferError(
            "prepared bundle differs from current sources"
        )
    if identity != transfer._development_identity(dataset=dataset, contract=contract):
        raise transfer.CrossComponentTransferError("development identity differs")
    authorization = transfer._read_json(
        args.output_dir / "authorization.json", label="authorization"
    )
    transfer.verify_authorization(contract=contract, authorization=authorization)


def _launch(args: argparse.Namespace) -> dict[str, object]:
    dataset, r2_contract, r2_result, liu_contract, source_paths = _inputs(args)
    return transfer.run_cross_component_transfer(
        output_dir=args.output_dir,
        dataset=dataset,
        r2_contract=r2_contract,
        r2_result=r2_result,
        liu_frozen_contract=liu_contract,
        source_paths=source_paths,
        source_bundle_path=args.source_bundle,
        progress=lambda message: print(message, flush=True),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            paths = _prepare(args)
            print(f"cross-component contract: {paths['contract']}")
            print(f"cross-component splits: {paths['splits']}")
            print(
                "cross-component authorization template: "
                f"{paths['authorization_template']}"
            )
            print("phase: AWAITING_CROSS_COMPONENT_AUTHORIZATION")
            print("numeric transferred targets parsed: false")
            return 0
        if args.command == "validate-authorization":
            _validate_authorization(args)
            print("cross-component authorization: valid")
            return 0
        result = _launch(args)
    except transfer.CrossComponentTransferError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"cross-component phase: {result.get('phase')}")
    print(f"result: {args.output_dir / 'cross_component_result.json'}")
    return 0 if result.get("phase") == "AWAITING_HUMAN_SCIENTIFIC_REVIEW" else 3


if __name__ == "__main__":
    raise SystemExit(main())
