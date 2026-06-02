#!/usr/bin/env python
"""
Compare planning traces for baseline vs BR-KG retrieval/action spaces.

Inputs:
  --catalog data/br-kg_exports/2C_planning_catalog.json
  --baseline traces_baseline.jsonl
  --br_kg traces_br_kg.jsonl

Each traces file: JSONL; one object per query: {"query_id": str, "steps": [{"tool_id":..., "dataset_id":..., "consumes": [...], "produces": [...]}], "initial_resources": [...]}.

Metrics (per split):
  - invalid_rate = invalid_steps / total_steps
  - success_at_budget = queries with >=1 valid step / total queries
  - median_iterations_to_first_valid
  - invalid_reason_counts

Writes a JSON summary to stdout and a sidecar per-run JSON under data/br-kg_exports.
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
            produces = set(step.get("produces") or step.get("produced") or tools.get(step.get("tool_id"), {}).get("produces") if isinstance(step, dict) else [])
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


def main():
    ap = argparse.ArgumentParser(description="Compare baseline vs BR-KG planning traces")
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True, help="Baseline traces JSONL")
    ap.add_argument("--br_kg", type=Path, required=True, help="BR-KG traces JSONL")
    ap.add_argument("--out", type=Path, default=Path("data/br-kg_exports/planning_compare.json"))
    args = ap.parse_args()

    tools, datasets = load_catalog(args.catalog)
    base_traces = load_traces(args.baseline)
    kg_traces = load_traces(args.br_kg)

    base_metrics = evaluate(base_traces, tools, datasets)
    kg_metrics = evaluate(kg_traces, tools, datasets)

    summary = {
        "baseline": base_metrics,
        "br_kg": kg_metrics,
        "delta": {
            "invalid_rate": kg_metrics["invalid_rate"] - base_metrics["invalid_rate"],
            "success_at_budget": kg_metrics["success_at_budget"] - base_metrics["success_at_budget"],
            "median_iterations_to_first_valid": (kg_metrics["median_iterations_to_first_valid"] or 0) - (base_metrics["median_iterations_to_first_valid"] or 0),
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
