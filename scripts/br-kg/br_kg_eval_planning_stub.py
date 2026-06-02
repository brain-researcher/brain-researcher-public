#!/usr/bin/env python
"""
Minimal precondition checker + metrics for 2C planning traces.

Inputs:
  --catalog data/br-kg_exports/2C_planning_catalog.json
  --traces  traces.jsonl  # each line: {"query_id": str, "steps": [{"tool_id":..., "dataset_id":..., "modalities": [...], "produces": [...]}]}

What it checks today (deterministic, no LLM):
  - Tool modality support: tool.supports_modalities must intersect dataset.modalities.
  - Resource preconditions: tool.consumes must be available in running state (initial_resources + produced so far + step overrides).
    * State updates with tool.produces (or step.produces override) when a step is valid.

Metrics:
  - invalid_rate = invalid_steps / total_steps
  - success@budget = queries with zero invalid steps (or with first valid chain) / total queries
  - median_iterations_to_first_valid (ignoring queries with none)

This is intentionally lightweight so you can plug in planner outputs from baseline vs BR-KG.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Dict, List, Set


def load_catalog(path: Path):
    data = json.loads(path.read_text())
    tools = {t["tool_id"]: t for t in data.get("tools", [])}
    datasets = {d["dataset_id"]: d for d in data.get("datasets", [])}
    return tools, datasets


def load_traces(path: Path):
    traces = []
    with path.open() as f:
        for line in f:
            if line.strip():
                traces.append(json.loads(line))
    return traces


def check_step(step, tools, datasets, available_resources: Set[str]) -> Dict[str, str]:
    tool = tools.get(step.get("tool_id"))
    ds = datasets.get(step.get("dataset_id"))
    if not tool:
        return {"ok": False, "reason": "unknown_tool"}
    if not ds:
        return {"ok": False, "reason": "unknown_dataset"}

    tool_mods = set(tool.get("modalities") or [])
    ds_mods = set(ds.get("modalities") or [])
    if tool_mods and ds_mods and tool_mods.isdisjoint(ds_mods):
        return {"ok": False, "reason": "modality_mismatch"}

    consumes = set(step.get("consumes") or tool.get("consumes") or [])
    missing = consumes - available_resources
    if missing:
        return {"ok": False, "reason": "missing_resource", "missing": sorted(missing)}

    return {"ok": True, "reason": ""}


def evaluate(traces, tools, datasets):
    total_steps = 0
    invalid_steps = 0
    iterations_to_first_valid: List[int] = []
    reason_counts: Dict[str, int] = {}

    for trace in traces:
        state_resources: Set[str] = set(trace.get("initial_resources") or [])
        first_valid = None
        for idx, step in enumerate(trace.get("steps", []), start=1):
            total_steps += 1
            res = check_step(step, tools, datasets, state_resources)
            if not res["ok"]:
                invalid_steps += 1
                reason_counts[res.get("reason", "unknown")] = reason_counts.get(res.get("reason", "unknown"), 0) + 1
                continue

            # step is valid; update state with produced resources
            produces = set(step.get("produces") or step.get("produced") or tool_safe(step, tools, "produces"))
            state_resources.update(produces)
            if first_valid is None:
                first_valid = idx
        if first_valid is not None:
            iterations_to_first_valid.append(first_valid)

    invalid_rate = invalid_steps / total_steps if total_steps else 0.0
    success_rate = len(iterations_to_first_valid) / len(traces) if traces else 0.0
    median_iters = statistics.median(iterations_to_first_valid) if iterations_to_first_valid else None

    return {
        "total_queries": len(traces),
        "total_steps": total_steps,
        "invalid_rate": invalid_rate,
        "success_at_budget": success_rate,
        "median_iterations_to_first_valid": median_iters,
        "invalid_reason_counts": reason_counts,
    }


def tool_safe(step, tools, key: str):
    tool = tools.get(step.get("tool_id")) or {}
    return tool.get(key) or []


def main():
    ap = argparse.ArgumentParser(description="Evaluate planning traces with simple precondition checks")
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--traces", type=Path, required=True)
    args = ap.parse_args()

    tools, datasets = load_catalog(args.catalog)
    traces = load_traces(args.traces)
    metrics = evaluate(traces, tools, datasets)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
