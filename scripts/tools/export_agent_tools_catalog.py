#!/usr/bin/env python
"""
Export the running agent's tool registry (as seen by /agent/plan) into a simple catalog JSON
so evaluator scripts can recognize tool_ids returned by the planner.

This calls the agent service /tools/list endpoint (must be running), then writes:
  data/neurokg_exports/agent_tools_catalog.json

Fields: tool_id, name, modalities (if provided), consumes, produces.
"""

from __future__ import annotations

import json
import argparse
from pathlib import Path
import requests


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8001", help="Agent base URL")
    ap.add_argument("--out", type=Path, default=Path("data/neurokg_exports/agent_tools_catalog.json"))
    args = ap.parse_args()

    url = f"{args.host}/tools/list"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    tools = []
    for t in data.get("tools", []):
        tools.append(
            {
                "tool_id": t.get("id") or t.get("name"),
                "name": t.get("name"),
                "modalities": t.get("modalities") or t.get("modalities_supported") or [],
                "consumes": t.get("consumes") or [],
                "produces": t.get("produces") or [],
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"tools": tools, "datasets": []}, indent=2))
    print(f"Exported {len(tools)} tools to {args.out}")


if __name__ == "__main__":
    main()
