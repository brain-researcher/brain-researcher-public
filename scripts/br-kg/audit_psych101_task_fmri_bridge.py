#!/usr/bin/env python3
"""Audit Psych-101 to task-fMRI bridge coverage in the live KG."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from brain_researcher.services.br_kg.analytics.psych101_task_fmri_bridge_audit import (
    Psych101TaskFmriBridgeAuditConfig,
    run_psych101_task_fmri_bridge_audit,
    write_psych101_task_fmri_bridge_audit_artifacts,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db


def _default_output_dir() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"data/br-kg/analysis/psych101_task_fmri_bridge/{stamp}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=_default_output_dir(),
        help="Directory to write the summary and per-experiment audit table.",
    )
    parser.add_argument(
        "--experiment-limit",
        type=int,
        default=250,
        help="Maximum number of Psych-101 experiments to inspect in detail.",
    )
    parser.add_argument(
        "--neo4j-database",
        help="Optional Neo4j database override.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db = require_neo4j_db(database=args.neo4j_database)
    result = run_psych101_task_fmri_bridge_audit(
        db,
        config=Psych101TaskFmriBridgeAuditConfig(
            experiment_limit=int(args.experiment_limit)
        ),
    )
    artifact_paths = write_psych101_task_fmri_bridge_audit_artifacts(
        result,
        output_dir=Path(args.output_dir).expanduser().resolve(),
    )
    summary = result.get("summary") or {}
    overlap = summary.get("overlap") or {}
    print(f"Wrote artifacts to {Path(args.output_dir).expanduser().resolve()}")
    print(
        "Psych-101 experiments: "
        f"{summary.get('psych101_experiment_count', 0)}"
    )
    print(
        "Canonical task-analysis overlap: "
        f"{overlap.get('canonical_task_analysis_count', 0)}"
    )
    print(
        "Family task-analysis overlap: "
        f"{overlap.get('family_task_analysis_count', 0)}"
    )
    print(f"Artifacts: {artifact_paths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
