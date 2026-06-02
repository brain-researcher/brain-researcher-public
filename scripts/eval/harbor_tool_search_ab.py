#!/usr/bin/env python3
"""Compare MCP tool_search baseline vs family-card routing on Harbor tasks."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility.
    import tomli as tomllib


DEFAULT_HARBOR_ROOT = Path("/app/data/brain_researcher_benchmark/harbor")
DEFAULT_TASK_IDS = [
    "REG-001",
    "PREP-004",
    "OPENNEURO-ML-005",
    "CONN-001",
    "DATA-016",
    "STAT-006",
]


def _load_task_metadata(task_dir: Path) -> dict:
    task_toml = task_dir / "task.toml"
    if not task_toml.exists():
        raise FileNotFoundError(f"Missing task.toml for {task_dir}")
    return tomllib.loads(task_toml.read_text(encoding="utf-8"))


def _load_instruction_query(task_dir: Path) -> str | None:
    instruction = task_dir / "instruction.md"
    if not instruction.exists():
        return None
    for line in instruction.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("Task:"):
            return stripped.removeprefix("Task:").strip()
    return None


def _task_query(task_dir: Path, query_source: str) -> str:
    meta = _load_task_metadata(task_dir)
    title = (
        meta.get("metadata", {}).get("title")
        if isinstance(meta.get("metadata"), dict)
        else None
    )
    title_query = str(title or "").strip()
    instruction_query = _load_instruction_query(task_dir) or title_query

    if query_source == "instruction":
        return instruction_query
    if (
        query_source == "both"
        and instruction_query
        and instruction_query != title_query
    ):
        return f"{title_query}\n{instruction_query}".strip()
    return title_query or instruction_query


@contextmanager
def _tool_search_mode(mode: str) -> Iterator[None]:
    original = {
        "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE": os.environ.get(
            "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"
        ),
        "BR_TOOL_FAMILY_ROUTING_MODE": os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE"),
    }
    try:
        if mode == "cards":
            os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] = "cards"
            os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = "cards"
        else:
            os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] = "legacy"
            os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = "legacy"
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_tool_search(query: str, *, limit: int, exposed_only: bool) -> dict:
    from brain_researcher.services.mcp import server as srv

    return srv.tool_search(
        query=query,
        limit=limit,
        exposed_only=exposed_only,
        include_workflows=True,
        include_total=True,
    )


def _collect_result(
    task_id: str,
    task_dir: Path,
    *,
    query_source: str,
    limit: int,
    exposed_only: bool,
) -> dict:
    meta = _load_task_metadata(task_dir)
    query = _task_query(task_dir, query_source=query_source)

    with _tool_search_mode("legacy"):
        baseline = _run_tool_search(query, limit=limit, exposed_only=exposed_only)
    with _tool_search_mode("cards"):
        cards = _run_tool_search(query, limit=limit, exposed_only=exposed_only)

    def _names(payload: dict) -> list[str]:
        return [str(item.get("name") or "") for item in (payload.get("tools") or [])]

    return {
        "task_id": task_id,
        "title": meta.get("metadata", {}).get("title"),
        "category": meta.get("metadata", {}).get("category"),
        "dataset_id": meta.get("metadata", {}).get("dataset_id"),
        "query": query,
        "baseline_top": _names(baseline),
        "cards_top": _names(cards),
        "baseline_total_matches": baseline.get("total_matches"),
        "cards_total_matches": cards.get("total_matches"),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harbor-root",
        type=Path,
        default=DEFAULT_HARBOR_ROOT,
        help="Path to Harbor benchmark root",
    )
    parser.add_argument(
        "--task-id",
        dest="task_ids",
        action="append",
        default=[],
        help="Task ID to evaluate (can be repeated). Defaults to a small retrieval slice.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="tool_search limit per query",
    )
    parser.add_argument(
        "--query-source",
        choices=("title", "instruction", "both"),
        default="title",
        help="Which task text to use as the retrieval query",
    )
    parser.add_argument(
        "--exposed-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use MCP exposed_only surface",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    harbor_root: Path = args.harbor_root
    task_ids = args.task_ids or list(DEFAULT_TASK_IDS)

    rows: list[dict] = []
    missing: list[str] = []
    for task_id in task_ids:
        task_dir = harbor_root / task_id
        if not task_dir.exists():
            missing.append(task_id)
            continue
        rows.append(
            _collect_result(
                task_id,
                task_dir,
                query_source=args.query_source,
                limit=max(1, int(args.limit)),
                exposed_only=bool(args.exposed_only),
            )
        )

    payload = {
        "harbor_root": str(harbor_root),
        "query_source": args.query_source,
        "limit": max(1, int(args.limit)),
        "exposed_only": bool(args.exposed_only),
        "task_count": len(rows),
        "missing_task_ids": missing,
        "results": rows,
    }

    text = json.dumps(payload, indent=2, sort_keys=False)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
