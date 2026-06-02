#!/usr/bin/env python3
"""Run the claim-first vs mention-fallback bootstrap benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.br_kg.etl.evaluation.claim_first_vs_mention_bootstrap import (
    DEFAULT_CALIBRATION_PATH,
    DEFAULT_CLAIM_DB,
    DEFAULT_CONTROL_DB,
    DEFAULT_HELDOUT_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_QUALITY_PROFILE,
    DEFAULT_REPORT_PATH,
    DEFAULT_SAMPLE_PATH,
    EXPECTED_FOOTPRINT,
    run_bootstrap_benchmark,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the claim-first vs mention-fallback bootstrap benchmark.",
    )
    parser.add_argument(
        "--sample-path",
        default=str(DEFAULT_SAMPLE_PATH),
        help="Path to the bounded GABRIEL sample JSONL.",
    )
    parser.add_argument(
        "--calibration-path",
        default=str(DEFAULT_CALIBRATION_PATH),
        help="Path to the calibration hypotheses manifest.",
    )
    parser.add_argument(
        "--heldout-path",
        default=str(DEFAULT_HELDOUT_PATH),
        help="Path to the held-out hypotheses manifest.",
    )
    parser.add_argument(
        "--claim-db",
        default=DEFAULT_CLAIM_DB,
        help="Neo4j database name for the claim-first condition.",
    )
    parser.add_argument(
        "--claim-uri",
        default=None,
        help="Optional Neo4j Bolt URI for the claim-first condition.",
    )
    parser.add_argument(
        "--claim-user",
        default=None,
        help="Optional Neo4j username for the claim-first condition.",
    )
    parser.add_argument(
        "--claim-password",
        default=None,
        help="Optional Neo4j password for the claim-first condition.",
    )
    parser.add_argument(
        "--control-db",
        default=DEFAULT_CONTROL_DB,
        help="Neo4j database name for the mention fallback control.",
    )
    parser.add_argument(
        "--control-uri",
        default=None,
        help="Optional Neo4j Bolt URI for the control condition.",
    )
    parser.add_argument(
        "--control-user",
        default=None,
        help="Optional Neo4j username for the control condition.",
    )
    parser.add_argument(
        "--control-password",
        default=None,
        help="Optional Neo4j password for the control condition.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for raw benchmark JSON artifacts.",
    )
    parser.add_argument(
        "--report-path",
        default=str(DEFAULT_REPORT_PATH),
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--quality-profile",
        default=DEFAULT_QUALITY_PROFILE,
        help="Gabriel loader quality profile for ingest (for example: high_precision, kg_bootstrap).",
    )
    parser.add_argument(
        "--skip-footprint-validation",
        action="store_true",
        help="Skip fixed node/edge footprint validation for larger bootstrap samples.",
    )
    parser.add_argument(
        "--include-strict-control",
        action="store_true",
        help="Also run the strict no-direct-mentions sensitivity control.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_bootstrap_benchmark(
        sample_path=Path(args.sample_path).expanduser().resolve(),
        calibration_path=Path(args.calibration_path).expanduser().resolve(),
        heldout_path=Path(args.heldout_path).expanduser().resolve(),
        claim_db=args.claim_db,
        control_db=args.control_db,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        report_path=Path(args.report_path).expanduser().resolve(),
        claim_uri=args.claim_uri,
        claim_user=args.claim_user,
        claim_password=args.claim_password,
        control_uri=args.control_uri,
        control_user=args.control_user,
        control_password=args.control_password,
        quality_profile=args.quality_profile,
        expected_footprint=(
            None if args.skip_footprint_validation else EXPECTED_FOOTPRINT
        ),
        include_strict_control=args.include_strict_control,
    )
    print(json.dumps(report["artifacts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
