#!/usr/bin/env python
"""
Generate BR-KG-aware planning traces from queries_basic.yaml.

For each query:
  - pick the first dataset that satisfies its predicates (via NeoKG catalog snapshot)
  - pick a tool that supports at least one modality of that dataset (fallback random)
  - emit a single-step trace with consumes/produces from the tool spec

This is a lightweight, deterministic stand-in for running the full planner so we can
measure invalid tool selection vs. a naive baseline.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List

import yaml


def load_catalog(path: Path):
    data = json.loads(path.read_text())
    tools = data["tools"]
    datasets = data["datasets"]
    return tools, datasets


def load_queries(path: Path) -> List[Dict[str, Any]]:
    return yaml.safe_load(path.read_text()) or []


def eval_predicate(value, op: str, target) -> bool:
    if op == "eq":
        return value == target
    if op == "contains":
        if isinstance(value, list):
            return target in value
        if isinstance(value, str):
            return target.lower() in value.lower()
        return False
    if op == "gte":
        return value is not None and target is not None and value >= target
    if op == "lte":
        return value is not None and target is not None and value <= target
    return False


def match_dataset(ds: Dict[str, Any], predicates: List[Dict[str, Any]]) -> bool:
    for p in predicates:
        field = p["field"]
        op = p["op"]
        target = p.get("value")
        # nested field like age_range.min
        parts = field.split(".")
        cur = ds
        for part in parts:
            cur = cur.get(part) if isinstance(cur, dict) else None
        if not eval_predicate(cur, op, target):
            return False
    return True


def pick_dataset(datasets: List[Dict[str, Any]], query: Dict[str, Any]):
    preds = query.get("where") or []
    for ds in datasets:
        if match_dataset(ds, preds):
            return ds
    return random.choice(datasets)


def pick_tool(tools: List[Dict[str, Any]], ds: Dict[str, Any]):
    ds_mods = set(ds.get("modalities") or [])
    candidates = [t for t in tools if ds_mods and ds_mods.intersection(set(t.get("modalities") or []))]
    if not candidates:
        return random.choice(tools)
    return random.choice(candidates)


def main():
    ap = argparse.ArgumentParser(description="Generate BR-KG-aware traces")
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--queries", type=Path, default=Path("benchmarks/br-kg/queries_basic.yaml"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    tools, datasets = load_catalog(args.catalog)
    queries = load_queries(args.queries)

    traces = []
    for q in queries:
        ds = pick_dataset(datasets, q)
        tool = pick_tool(tools, ds)
        step = {
            "tool_id": tool["tool_id"],
            "dataset_id": ds["dataset_id"],
            "consumes": tool.get("consumes") or [],
            "produces": tool.get("produces") or [],
        }
        traces.append(
            {
                "query_id": q.get("name") or q.get("template") or f"q{len(traces):04d}",
                "initial_resources": [],
                "steps": [step],
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
    print(f"Wrote {len(traces)} br_kg traces to {args.out}")


if __name__ == "__main__":
    main()
