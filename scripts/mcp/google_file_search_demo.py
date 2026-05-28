"""Minimal MCP demo for Google File Search via the local MCP server."""

from __future__ import annotations

import argparse
import json
import os
import sys

from brain_researcher.services.mcp import server as mcp_server


def _env_true(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP Google File Search demo")
    parser.add_argument(
        "--operation",
        default="list_stores",
        help="Operation: list_stores, list_files, query",
    )
    parser.add_argument("--store", default=os.getenv("BR_GOOGLE_FILE_SEARCH_STORE"))
    parser.add_argument("--query", default=os.getenv("BR_GOOGLE_FILE_SEARCH_QUERY"))
    parser.add_argument("--page-size", type=int, default=10)
    args = parser.parse_args()

    if not _env_true("BR_MCP_ALLOW_NETWORK"):
        print("Set BR_MCP_ALLOW_NETWORK=1 to enable Google APIs.")
        return 1

    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        print("Set GOOGLE_API_KEY or GEMINI_API_KEY to call Google File Search.")
        return 1

    params = {
        "operation": args.operation,
        "store_name": args.store,
        "query": args.query,
        "page_size": args.page_size,
    }
    response = mcp_server.google_file_search(**params)
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
