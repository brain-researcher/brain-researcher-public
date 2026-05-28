"""Reusable FAILED_ON backfill helpers.

Usage:
  NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \
  python scripts/neurokg/backfill_failed_on.py \
    --mode replace --window-days 90

Flags:
  --mode replace      : fail_count set to aggregated count (default)
  --mode accumulate   : fail_count += aggregated count (use cautiously)
  --window-days N    : only consider failures created within the last N days
  --dry-run          : compute stats without mutating KG (safe preview)

The script is idempotent when run in `replace` mode and can be rerun safely.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from typing import Any, Literal

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


def get_driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD")
    if not pwd:
        raise RuntimeError("NEO4J_PASSWORD not set")
    return GraphDatabase.driver(uri, auth=(user, pwd))


__all_modes__ = {"replace", "accumulate"}


def backfill(
    mode: Literal["replace", "accumulate"] = "replace",
    window_days: int | None = None,
    dry_run: bool = False,
) -> dict:
    mode = mode if mode in __all_modes__ else "replace"
    where_clause = ""
    params: dict[str, Any] = {
        "mode": mode,
    }
    if window_days and window_days > 0:
        min_ts = int((time.time() - window_days * 86400) * 1000)
        where_clause = "WHERE f.created_at >= $min_ts"
        params["min_ts"] = min_ts

    if dry_run:
        query = f"""
        MATCH (f:ExecutionFailure)-[:FOR_TOOL]->(t:Tool)
        OPTIONAL MATCH (f)-[:FOR_DATASET]->(d:Dataset)
        {where_clause}
        RETURN count(*) AS failures, count(DISTINCT t) AS tools
        """
    else:
        query = f"""
        MATCH (f:ExecutionFailure)-[:FOR_TOOL]->(t:Tool)
        OPTIONAL MATCH (f)-[:FOR_DATASET]->(d:Dataset)
        {where_clause}
        WITH t, d, coalesce(f.task_family, 'unknown') AS tf, coalesce(f.error_category, 'unknown') AS ec,
             count(*) AS cnt, max(f.run_id) AS last_run_id, max(f.created_at) AS last_seen
        MERGE (t)-[fo:FAILED_ON {{task_family: tf, error_category: ec}}]->(d)
        SET fo.fail_count = {"coalesce(fo.fail_count,0)+cnt" if mode == 'accumulate' else "cnt"},
            fo.last_seen = coalesce(last_seen, timestamp()),
            fo.last_run_id = last_run_id
        RETURN count(*) AS rels, sum(cnt) AS failures
        """
    drv = get_driver()
    with drv.session() as sess:
        res = sess.run(query, **params).single()
        return {
            "relationships_updated": res.get("rels", 0),
            "failures_counted": res.get("failures", 0),
            "mode": mode,
            "window_days": window_days,
            "dry_run": dry_run,
        }


def main():
    parser = argparse.ArgumentParser(description="Backfill FAILED_ON aggregates from ExecutionFailure")
    parser.add_argument("--mode", choices=sorted(__all_modes__), default="replace")
    args = parser.parse_args()

    summary = backfill(mode=args.mode)
    print(summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
