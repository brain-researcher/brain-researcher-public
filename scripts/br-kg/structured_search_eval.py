#!/usr/bin/env python3
"""Evaluate structured tool search output sizes and stability."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from brain_researcher.services.br_kg import query_service

DEFAULT_QUERIES = [
    "glm", "skull strip", "registration", "diffusion", "surface", "qc", "connectivity"
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_queries(
    queries: list[str],
    *,
    runs: int,
    k_methods: int,
    k_softwares: int,
    k_candidates: int,
    force_fallback: bool,
) -> dict[str, Any]:
    per_query: list[dict[str, Any]] = []
    all_methods: list[int] = []
    all_softwares: list[int] = []
    all_candidates: list[int] = []
    stable_count = 0

    for query in queries:
        run_results: list[dict[str, Any]] = []
        rec_ids: list[str | None] = []
        sources: list[str] = []
        for _ in range(max(1, runs)):
            result = query_service.search_tools_structured(
                query=query,
                k_methods=k_methods,
                k_softwares=k_softwares,
                k_candidates=k_candidates,
                force_fallback=force_fallback,
            )
            run_results.append(result)
            rec = (result.get("recommendation") or {}).get("tool_id")
            rec_ids.append(rec)
            sources.append(result.get("source", "unknown"))
            all_methods.append(len(result.get("methods", []) or []))
            all_softwares.append(len(result.get("softwares", []) or []))
            all_candidates.append(len(result.get("candidates", []) or []))

        stable = len({rid for rid in rec_ids if rid}) <= 1 if rec_ids else False
        if stable:
            stable_count += 1

        per_query.append(
            {
                "query": query,
                "runs": len(run_results),
                "recommendations": rec_ids,
                "stable_recommendation": stable,
                "sources": sources,
                "last_result": run_results[-1] if run_results else {},
            }
        )

    summary = {
        "queries": len(queries),
        "runs_per_query": runs,
        "avg_methods": mean(all_methods) if all_methods else 0,
        "avg_softwares": mean(all_softwares) if all_softwares else 0,
        "avg_candidates": mean(all_candidates) if all_candidates else 0,
        "stable_recommendation_rate": (stable_count / len(queries)) if queries else 0,
    }

    return {"summary": summary, "results": per_query}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate structured tool search outputs.")
    parser.add_argument("--query", action="append", dest="queries", default=[])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--k-methods", type=int, default=8)
    parser.add_argument("--k-softwares", type=int, default=5)
    parser.add_argument("--k-candidates", type=int, default=50)
    parser.add_argument("--force-fallback", action="store_true")
    parser.add_argument(
        "--output",
        default="artifacts/tool_diffs/structured_search_eval.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    queries = args.queries or list(DEFAULT_QUERIES)
    payload = {
        "generated_at": _utc_now(),
        "force_fallback": bool(args.force_fallback),
        "limits": {
            "methods": args.k_methods,
            "softwares": args.k_softwares,
            "candidates": args.k_candidates,
        },
    }
    payload.update(
        run_queries(
            queries,
            runs=max(1, args.runs),
            k_methods=args.k_methods,
            k_softwares=args.k_softwares,
            k_candidates=args.k_candidates,
            force_fallback=args.force_fallback,
        )
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    print(str(output_path))


if __name__ == "__main__":
    main()
