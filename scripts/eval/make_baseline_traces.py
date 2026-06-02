#!/usr/bin/env python
"""
Generate a naive baseline trace set by randomly pairing tools and datasets
(ignores modality/resource compatibility). This simulates a retrieval-free
planner to provide a baseline for 2C metrics.

Usage:
  python scripts/eval/make_baseline_traces.py \
    --catalog data/br-kg_exports/2C_planning_catalog.json \
    --out data/br-kg_exports/traces_baseline.jsonl \
    --num 100 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def load_catalog(path: Path):
    data = json.loads(path.read_text())
    return data["tools"], data["datasets"]


def main():
    ap = argparse.ArgumentParser(description="Generate naive baseline traces")
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--num", type=int, default=100, help="Number of queries")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    tools, datasets = load_catalog(args.catalog)
    random.seed(args.seed)

    traces = []
    for qi in range(args.num):
        tool = random.choice(tools)
        ds = random.choice(datasets)
        step = {
            "tool_id": tool["tool_id"],
            "dataset_id": ds["dataset_id"],
            "consumes": tool.get("consumes") or [],
            "produces": tool.get("produces") or [],
        }
        traces.append({
            "query_id": f"baseline_q{qi:04d}",
            "initial_resources": [],
            "steps": [step],
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
    print(f"Wrote {len(traces)} baseline traces to {args.out}")


if __name__ == "__main__":
    main()
