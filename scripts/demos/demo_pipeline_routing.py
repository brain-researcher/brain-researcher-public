"""Quick probe for pipeline-based planning.

Usage (from repo root):

    source .env  # must contain NEO4J_URI/USER/PASSWORD
    python scripts/demos/demo_pipeline_routing.py

What it does:
  - Runs a small set of canonical queries (T1 preproc, dMRI tractography, ICA+FIX).
  - Calls `search_pipelines` (Neo4j) with simple keyword tasks.
  - Prints which pipeline was hit and the ordered tool IDs.

This is lightweight: it does NOT execute tools or call the LLM; it only inspects
what the pipeline catalog would return for the queries.
"""

from __future__ import annotations

import os
from typing import List, Dict, Any

from dotenv import load_dotenv

from brain_researcher.services.agent.pipeline_catalog import (
    search_pipelines,
    format_pipeline_summary,
)


def run_probe(tasks: List[Dict[str, Any]]) -> None:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    print(f"Neo4j: {uri} as {user}\n")

    for task in tasks:
        q = task["query"]
        modalities = task.get("modalities")
        print(f"=== {task['id']} ===")
        print(f"Query: {q}")
        if modalities:
            print(f"Modalities filter: {modalities}")

        pipelines = search_pipelines(
            task=q,
            modalities=modalities,
            limit=3,
            uri=uri,
            user=user,
            password=password,
        )

        if not pipelines:
            print("No pipeline hit (planner would fall back to LLM).\n")
            continue

        for p in pipelines:
            print("Pipeline:", format_pipeline_summary(p))
            steps = p.get("steps", []) or []
            print("  Steps (order):")
            for idx, tool in enumerate(steps, 1):
                print(f"    {idx}. {tool}")
        print()


if __name__ == "__main__":
    load_dotenv()

    TASKS = [
        {
            "id": "Q1_T1_preproc",
            "query": "t1 preprocessing MNI skull strip brain extraction",
            "modalities": ["smri"],
        },
        {
            "id": "Q3_dMRI_tractography",
            "query": "diffusion tractography bedpostx",
            "modalities": ["dmri"],
        },
        {
            "id": "Q8_ICA_FIX_cluster",
            "query": "ICA FIX denoise cluster correction AFNI",
            "modalities": ["fmri"],
        },
    ]

    run_probe(TASKS)
