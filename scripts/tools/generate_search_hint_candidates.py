#!/usr/bin/env python3
"""Generate reviewable search-hint candidates for exposed BR tools.

Usage:
  python scripts/tools/generate_search_hint_candidates.py \
    --output artifacts/search_hint_candidates.json

This script does not modify catalog files. It materializes the current inferred
tool metadata so search hints, allowed phases, and approval levels can be
reviewed before any catalog backfill.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.tools.catalog_loader import load_tool_specs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/search_hint_candidates.json"),
        help="Where to write the review artifact JSON.",
    )
    parser.add_argument(
        "--include-workflows",
        action="store_true",
        help="Include declarative workflow ToolSpecs in the exported artifact.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    specs = load_tool_specs(
        exposed_only=True,
        include_workflows=bool(args.include_workflows),
        agent_visible_only=False,
    )
    payload = {
        "count": len(specs),
        "tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "search_hint": spec.search_hint,
                "allowed_phases": list(spec.allowed_phases or []),
                "approval_level": spec.approval_level,
            }
            for spec in specs
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(specs)} tool metadata rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
