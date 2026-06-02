#!/usr/bin/env python3
"""Score the separate Liu-style ICA-component FC line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.research.predictive.component_benchmark import (
    compute_component_line_score,
    load_component_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--phase", default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = load_component_manifest(args.manifest.expanduser().resolve())
    payload = compute_component_line_score(
        args.ledger.expanduser().resolve(),
        manifest,
        phase_name=args.phase,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output_path = args.output.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
