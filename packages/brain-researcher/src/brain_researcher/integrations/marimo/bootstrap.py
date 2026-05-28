"""CLI helpers for materializing managed marimo runtime configuration."""

from __future__ import annotations

import argparse
import sys

from .config import BrainResearcherMarimoSettings, write_marimo_user_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write managed marimo config for Brain Researcher runtimes.",
    )
    parser.add_argument(
        "--user-home",
        default=None,
        help="Target home directory for user-scoped marimo config.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = BrainResearcherMarimoSettings.from_env()
    print(write_marimo_user_config(settings, user_home=args.user_home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
