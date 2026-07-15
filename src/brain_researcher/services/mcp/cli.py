"""Lightweight console entrypoint for the Brain Researcher MCP server."""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Callable, Sequence

from brain_researcher import __version__

_SERVER_MODULE = "brain_researcher.services.mcp.server"
_INSTALL_HINT = (
    "Install the MCP runtime from this checkout with "
    "`pip install '.[mcp]'` (or `pip install 'brain_researcher[mcp]'`)."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brain-researcher-mcp",
        description="Run the Brain Researcher MCP server.",
        epilog=(
            "Server transport and network settings are configured with BR_MCP_* "
            "environment variables."
        ),
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _load_server_main() -> Callable[[], None]:
    try:
        module = importlib.import_module(_SERVER_MODULE)
    except ModuleNotFoundError as exc:
        missing = exc.name or "an unknown dependency"
        if missing == "brain_researcher" or missing.startswith("brain_researcher."):
            # An internal package import is a code/package defect, not an optional
            # dependency problem. Preserve the original traceback for debugging.
            raise
        raise RuntimeError(
            f"MCP runtime dependency {missing!r} is not installed. {_INSTALL_HINT}"
        ) from exc
    return module.main


def main(argv: Sequence[str] | None = None) -> None:
    """Parse lightweight flags, then import and run the full server on demand."""

    parser = _parser()
    parser.parse_args(argv)
    try:
        server_main = _load_server_main()
    except RuntimeError as exc:
        parser.exit(status=2, message=f"brain-researcher-mcp: error: {exc}\n")
    server_main()


if __name__ == "__main__":
    main()
