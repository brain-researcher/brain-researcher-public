#!/usr/bin/env python3
"""Prepare or run the frozen common-support Liu-style HCP comparator.

``prepare`` writes a new, exclusive contract directory without reading numeric
target values.  ``run`` consumes that exact contract and writes one result.
Both stages reuse the nested100 244/82 retrospective split; neither stage is
an original-paper reproduction, an external replication, or scientific
acceptance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from brain_researcher.research.predictive.hcp_liu_matched_comparator import (
    LiuMatchedComparatorError,
    load_common_support_metric_catalog,
    prepare_frozen_liu_matched_contract,
    read_frozen_liu_matched_contract,
    read_nested100_reference,
    run_frozen_liu_matched_comparator,
    write_frozen_liu_matched_contract,
    write_liu_matched_comparator_result,
)
from brain_researcher.research.predictive.hcp_nested100_replay import (
    load_hcp_dataset,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        current = subparsers.add_parser(command)
        current.add_argument("--source-bundle", type=Path, required=True)
        current.add_argument("--nested100-result", type=Path, required=True)
        current.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        dataset = load_hcp_dataset(args.source_bundle)
        reference = read_nested100_reference(args.nested100_result)
        metric_catalog = load_common_support_metric_catalog(args.source_bundle)
        if args.command == "prepare":
            contract = prepare_frozen_liu_matched_contract(
                dataset=dataset,
                nested100_reference=reference,
                metric_catalog=metric_catalog,
                nested100_reference_path=args.nested100_result,
            )
            contract_path = write_frozen_liu_matched_contract(args.output_dir, contract)
            print(f"frozen contract: {contract_path}")
            print("execution: not started")
            return 0
        contract_path = args.output_dir / "frozen_contract.json"
        contract = read_frozen_liu_matched_contract(contract_path)
        result = run_frozen_liu_matched_comparator(
            dataset=dataset,
            nested100_reference=reference,
            metric_catalog=metric_catalog,
            frozen_contract=contract,
            nested100_reference_path=args.nested100_result,
        )
        result_path = write_liu_matched_comparator_result(args.output_dir, result)
    except LiuMatchedComparatorError as exc:
        print(f"HCP Liu matched comparator refused: {exc}", file=sys.stderr)
        return 2
    print(f"result: {result_path}")
    print("analysis: retrospective same-cohort matched comparator")
    print("scientific_acceptance: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
