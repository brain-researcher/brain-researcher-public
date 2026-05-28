#!/usr/bin/env python
"""Render the scientific-review failure-mode registry Markdown."""

from __future__ import annotations

import argparse
from pathlib import Path

from brain_researcher.services.review.failure_mode_registry import (
    DEFAULT_REGISTRY_PATH,
    load_failure_mode_registry,
    render_failure_mode_registry_markdown,
)

DEFAULT_OUTPUT_PATH = Path("docs/review/failure_mode_registry.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the rendered Markdown differs from the output file.",
    )
    args = parser.parse_args()

    registry = load_failure_mode_registry(args.registry)
    rendered = render_failure_mode_registry_markdown(registry)

    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != rendered:
            print(f"{args.output} is stale; rerun {Path(__file__).as_posix()}")
            return 1
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.output} from {args.registry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

