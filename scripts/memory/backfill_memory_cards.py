#!/usr/bin/env python3
"""Backfill derived memory cards from persisted MCP runs.

Usage:
  python scripts/memory/backfill_memory_cards.py
  python scripts/memory/backfill_memory_cards.py --run-id br_20260405_123456_abcdef
  python scripts/memory/backfill_memory_cards.py --limit 25

Environment:
  - BR_MCP_RUN_ROOT: optional override for the MCP run root.

Outputs:
  - Writes derived memory records under <RUN_ROOT>/memory/
  - Prints a JSON summary to stdout
"""

from __future__ import annotations

import argparse
import json
import traceback
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import get_mcp_run_root, iter_mcp_run_dirs
from brain_researcher.services.memory import MemoryStore, distill_and_store_run


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Specific run_id to backfill. May be passed multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of runs to process after filtering.",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=None,
        help="Optional explicit MCP run root. Defaults to BR_MCP_RUN_ROOT/get_mcp_run_root().",
    )
    return parser.parse_args(argv)


def _resolve_run_root(run_root: Path | str | None) -> Path:
    if run_root is not None:
        return Path(run_root).expanduser().resolve()
    return Path(get_mcp_run_root()).expanduser().resolve()


def backfill_runs(
    *,
    run_root: Path | str | None = None,
    run_ids: Sequence[str] | None = None,
    limit: int | None = None,
    store: MemoryStore | None = None,
    run_dirs: Iterable[Path] | None = None,
) -> dict[str, Any]:
    resolved_run_root = _resolve_run_root(run_root)
    selected_run_ids = {
        str(item).strip() for item in (run_ids or []) if str(item).strip()
    }
    resolved_store = store or MemoryStore(run_root=resolved_run_root)

    candidate_run_dirs = (
        [Path(path).expanduser().resolve() for path in run_dirs]
        if run_dirs is not None
        else list(iter_mcp_run_dirs(resolved_run_root))
    )
    available_run_ids = {run_dir.name for run_dir in candidate_run_dirs}
    missing_run_ids = sorted(selected_run_ids - available_run_ids)
    if selected_run_ids:
        candidate_run_dirs = [
            run_dir for run_dir in candidate_run_dirs if run_dir.name in selected_run_ids
        ]
    if limit is not None:
        candidate_run_dirs = candidate_run_dirs[: max(0, int(limit))]

    processed: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for run_dir in candidate_run_dirs:
        run_id = run_dir.name
        run_json = run_dir / "run.json"
        if not run_json.exists():
            skipped.append(
                {
                    "run_id": run_id,
                    "reason": "missing run.json",
                    "path": str(run_dir),
                }
            )
            continue
        try:
            result = distill_and_store_run(
                run_id,
                run_dir=run_dir,
                store=resolved_store,
            )
        except Exception as exc:  # pragma: no cover - exercised by real-run eval
            skipped.append(
                {
                    "run_id": run_id,
                    "reason": f"distill failed: {exc.__class__.__name__}: {exc}",
                    "path": str(run_dir),
                    "traceback": traceback.format_exc(limit=3),
                }
            )
            continue
        processed.append(
            {
                "run_id": run_id,
                "episodic_written": bool(result.get("episodic_written")),
                "claim_count": int(result.get("claim_count") or 0),
                "write_count": len(result.get("writes") or []),
            }
        )

    return {
        "ok": True,
        "run_root": str(resolved_run_root),
        "memory_root": str(resolved_store.memory_root),
        "selected_run_ids": sorted(selected_run_ids),
        "missing_run_ids": missing_run_ids,
        "limit": limit,
        "candidate_count": len(candidate_run_dirs),
        "processed_count": len(processed),
        "processed": processed,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = backfill_runs(
        run_root=args.run_root,
        run_ids=args.run_id,
        limit=args.limit,
    )
    print(
        json.dumps(
            summary,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
