#!/usr/bin/env python3
"""Run the frozen HCP 100-template selection-aware internal replay.

This script creates a new output directory. It never modifies the historical
v1/v2/recovery episodes. Its 25 percent partition is a retrospective reused-
HCP repartition, not an unseen holdout or a Liu comparison.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from brain_researcher.research.predictive.hcp_nested100_replay import (
    Nested100ReplayError,
    ReplayConfig,
    frozen_exact100_templates,
    load_hcp_dataset,
    run_frozen_nested100_replay,
    write_replay_result,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--recovery-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260809)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        dataset = load_hcp_dataset(args.source_bundle)
        templates = frozen_exact100_templates(
            v2_bundle=args.source_bundle,
            recovery_bundle=args.recovery_bundle,
        )
        result = run_frozen_nested100_replay(
            dataset=dataset,
            templates=templates,
            config=ReplayConfig(seed=args.seed),
        )
        result_path = write_replay_result(args.output_dir, result)
    except Nested100ReplayError as exc:
        print(f"HCP nested-100 replay refused: {exc}", file=sys.stderr)
        return 2
    print(f"result: {result_path}")
    print("analysis: selection-aware retrospective reused-HCP repartition")
    print("scientific_acceptance: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
