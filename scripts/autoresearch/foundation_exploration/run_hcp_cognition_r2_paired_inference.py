#!/usr/bin/env python3
"""Prepare, validate, or run Cognition C1-vs-Liu paired inference."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from brain_researcher.research.predictive import (
    hcp_cognition_r2_paired_inference as inference,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source-r2", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--draws", type=int, default=inference.DEFAULT_DRAWS)
    prepare.add_argument("--permutation-seed", type=int, default=inference.DEFAULT_PERMUTATION_SEED)
    prepare.add_argument("--bootstrap-seed", type=int, default=inference.DEFAULT_BOOTSTRAP_SEED)
    validate = commands.add_parser("validate-authorization")
    validate.add_argument("--output-dir", type=Path, required=True)
    launch = commands.add_parser("launch")
    launch.add_argument("--output-dir", type=Path, required=True)
    return parser


def _validate(output_dir: Path) -> None:
    contract = inference._read_json(
        output_dir / "cognition_paired_inference_contract.json", label="contract"
    )
    source = inference._mapping(contract.get("source"), label="source")
    permutation = inference._mapping(
        contract.get("permutation_sensitivity"), label="permutation"
    )
    bootstrap = inference._mapping(
        contract.get("bootstrap_uncertainty"), label="bootstrap"
    )
    expected, _ = inference.prepare_contract(
        source_dir=Path(str(source.get("source_dir"))),
        draws=int(permutation.get("draws")),
        permutation_seed=int(permutation.get("seed")),
        bootstrap_seed=int(bootstrap.get("seed")),
    )
    if contract != expected:
        raise inference.CognitionPairedInferenceError(
            "inference contract differs from current R2 source"
        )
    authorization = inference._read_json(
        output_dir / "authorization.json", label="authorization"
    )
    inference.verify_authorization(
        contract=contract, authorization=authorization
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            inference.configure_inference_runtime(
                permutation_seed=args.permutation_seed,
                bootstrap_seed=args.bootstrap_seed,
            )
        if args.command == "prepare":
            paths = inference.write_prelaunch(
                output_dir=args.output_dir,
                source_dir=args.source_r2,
                draws=args.draws,
            )
            print(f"contract: {paths['contract']}")
            print(f"authorization template: {paths['authorization_template']}")
            print(f"family projection: {paths['family_cluster_projection']}")
            print("phase: AWAITING_COGNITION_PAIRED_INFERENCE_AUTHORIZATION")
            return 0
        if args.command == "validate-authorization":
            _validate(args.output_dir)
            print("authorization: valid")
            return 0
        result = inference.run_inference(output_dir=args.output_dir)
    except inference.CognitionPairedInferenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"phase: {result['phase']}")
    print(
        "conditional one-sided p: "
        f"{result['conditional_one_sided_plus_one_p']:.6f}"
    )
    print(
        "result: "
        f"{args.output_dir / 'cognition_paired_inference_result.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
