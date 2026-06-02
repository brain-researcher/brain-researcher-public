"""CLI helpers for materializing Notebook Intelligence runtime files."""

from __future__ import annotations

import argparse
import sys

from .config import (
    BrainResearcherNotebookIntelligenceSettings,
    write_extension_metadata,
    write_user_config,
    write_user_mcp_config,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write managed Notebook Intelligence config for Brain Researcher.",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Target Python environment prefix for extension metadata.",
    )
    parser.add_argument(
        "--user-home",
        default=None,
        help="Target home directory for user-scoped NBI config.",
    )
    parser.add_argument(
        "--write-extension-metadata",
        action="store_true",
        help="Write share/jupyter/nbi_extensions/<name>/extension.json.",
    )
    parser.add_argument(
        "--write-user-config",
        action="store_true",
        help="Write ~/.jupyter/nbi/mcp.json with the managed BR MCP server.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = BrainResearcherNotebookIntelligenceSettings.from_env()
    wrote_anything = False

    if args.write_extension_metadata:
        path = write_extension_metadata(settings, prefix=args.prefix)
        print(path)
        wrote_anything = True

    if args.write_user_config or not wrote_anything:
        print(write_user_config(settings, user_home=args.user_home))
        print(write_user_mcp_config(settings, user_home=args.user_home))
        wrote_anything = True

    return 0 if wrote_anything else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
