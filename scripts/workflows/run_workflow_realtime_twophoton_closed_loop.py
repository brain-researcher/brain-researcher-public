#!/usr/bin/env python3
"""Local runner for workflow_realtime_twophoton_closed_loop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.tools.executor import execute_tool


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--params",
        default="params.json",
        help="Path to JSON file containing workflow parameters.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    params_path = Path(args.params).expanduser().resolve()
    params = json.loads(params_path.read_text(encoding="utf-8"))
    result = execute_tool("workflow_realtime_twophoton_closed_loop", params)
    print(json.dumps(result.model_dump(mode="python"), indent=2, default=str))
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
