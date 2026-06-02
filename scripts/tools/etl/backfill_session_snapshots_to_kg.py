#!/usr/bin/env python3
"""Backfill BR research-logging session snapshots into BRKG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from brain_researcher.services.mcp import server as mcp_server

DEFAULT_OUTPUT_JSON = Path("tmp/session_snapshot_kg_backfill/report.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-days", type=int, default=60)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to configured Neo4j instead of returning a dry-run payload.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    return parser.parse_args(argv)


def run_backfill(
    *,
    since_days: int = 60,
    limit: int = 1000,
    apply: bool = False,
) -> dict[str, Any]:
    """Run the MCP-backed session KG backfill surface."""

    return mcp_server.session_backfill_to_kg(
        since_days=since_days,
        limit=limit,
        dry_run=not apply,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_backfill(
        since_days=args.since_days,
        limit=args.limit,
        apply=bool(args.apply),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: result.get(k) for k in ("ok", "dry_run", "node_count", "edge_count", "error")}, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
