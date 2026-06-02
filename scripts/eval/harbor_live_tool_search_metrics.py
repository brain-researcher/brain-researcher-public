#!/usr/bin/env python3
"""Compute live Harbor retrieval metrics against an MCP HTTP endpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "mcp"))

from call_http_tool import (  # type: ignore[import-not-found]
    DEFAULT_TIMEOUT_S,
    HttpMCPClient,
    default_mcp_url,
    resolve_mcp_token,
)
from scripts.eval.harbor_tool_search_metrics import (  # type: ignore[import-not-found]
    DEFAULT_BENCH_CSV,
    DEFAULT_HARBOR_JSON,
    _gold_tools_for_task,
    _hit,
    _task_id,
    _task_query,
)


def _tool_search_names(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return [str(item.get("name") or "") for item in (payload.get("tools") or [])]


def _structured_search_names(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    names: list[str] = []
    recommendation = data.get("recommendation")
    if isinstance(recommendation, dict):
        tool_id = str(recommendation.get("tool_id") or "").strip()
        if tool_id:
            names.append(tool_id)

    for candidate in data.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        tool_id = str(candidate.get("tool_id") or "").strip()
        if tool_id and tool_id not in names:
            names.append(tool_id)
    return names


def _call_live_search(
    client: HttpMCPClient,
    *,
    query: str,
    tool_name: str,
    limit: int,
    exposed_only: bool,
    first_call: bool,
) -> tuple[list[str], dict[str, Any] | None]:
    if tool_name == "tool_search":
        arguments = {
            "query": query,
            "limit": limit,
            "exposed_only": exposed_only,
            "include_workflows": True,
            "include_total": True,
        }
    elif tool_name == "tool_search_structured":
        arguments = {
            "query": query,
            "exposed_only": exposed_only,
            "default_only": True,
            "k_candidates": max(limit, 50),
        }
    else:
        raise ValueError(f"Unsupported tool_name: {tool_name}")

    response = client.call_tool(
        tool_name,
        arguments,
        prime=first_call,
        initialize=first_call,
    )
    payload = response.get("payload")
    if tool_name == "tool_search":
        return _tool_search_names(payload), payload if isinstance(payload, dict) else None
    return _structured_search_names(payload), payload if isinstance(payload, dict) else None


def _load_benchmark_rows(path: Path) -> dict[str, dict[str, str]]:
    import csv

    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            task_id = str(row.get("task_id") or "").strip()
            if task_id:
                rows[task_id] = row
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-json", type=Path, default=DEFAULT_HARBOR_JSON)
    parser.add_argument("--benchmark-csv", type=Path, default=DEFAULT_BENCH_CSV)
    parser.add_argument(
        "--query-source",
        choices=("title", "instruction", "both"),
        default="instruction",
    )
    parser.add_argument(
        "--tool-name",
        choices=("tool_search", "tool_search_structured"),
        default="tool_search",
    )
    parser.add_argument("--url", default=default_mcp_url())
    parser.add_argument("--token", default=None)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--exposed-only",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--task-id",
        dest="task_ids",
        action="append",
        default=[],
        help="Optional Harbor task IDs to restrict evaluation to.",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    harbor = json.loads(args.harbor_json.read_text(encoding="utf-8"))
    tasks = harbor.get("tasks") or []
    wanted = set(args.task_ids or [])
    if wanted:
        tasks = [task for task in tasks if _task_id(task) in wanted]

    bench_by_id = _load_benchmark_rows(args.benchmark_csv)
    client = HttpMCPClient(
        url=args.url,
        token=resolve_mcp_token(args.token),
        timeout_s=float(args.timeout_s),
        client_name="harbor_live_tool_search_metrics",
        client_version="0.1.0",
    )

    results: list[dict[str, Any]] = []
    first_call = True
    for task in tasks:
        task_id = _task_id(task)
        benchmark_row = bench_by_id.get(task_id)
        gold = _gold_tools_for_task(task, benchmark_row)
        covered = benchmark_row is not None and bool(gold)
        query = _task_query(task, args.query_source)
        names, payload = _call_live_search(
            client,
            query=query,
            tool_name=args.tool_name,
            limit=max(1, args.limit),
            exposed_only=bool(args.exposed_only),
            first_call=first_call,
        )
        first_call = False
        results.append(
            {
                "task_id": task_id,
                "title": task.get("title"),
                "category": task.get("category"),
                "query": query,
                "covered": covered,
                "gold_tools": gold,
                "top": names,
                "top1_hit": _hit(names, gold, 1) if covered else False,
                "top3_hit": _hit(names, gold, 3) if covered else False,
                "payload_summary": {
                    "count": len(names),
                    "has_payload": isinstance(payload, dict),
                },
            }
        )

    covered = [row for row in results if row["covered"]]
    top1_hits = sum(1 for row in covered if row["top1_hit"])
    top3_hits = sum(1 for row in covered if row["top3_hit"])
    payload = {
        "url": args.url,
        "tool_name": args.tool_name,
        "query_source": args.query_source,
        "limit": max(1, args.limit),
        "exposed_only": bool(args.exposed_only),
        "task_count": len(results),
        "covered_task_count": len(covered),
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top1_rate": (top1_hits / len(covered)) if covered else 0.0,
        "top3_rate": (top3_hits / len(covered)) if covered else 0.0,
        "results": results,
    }
    text = json.dumps(payload, indent=2)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
