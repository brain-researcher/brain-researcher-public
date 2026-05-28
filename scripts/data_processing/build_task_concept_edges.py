import json
import pathlib
import time

import requests
from cognitiveatlas.api import get_task

from .vocab_loader import id2level0, id2name, task2concept

API = "https://www.cognitiveatlas.org/api/v-alpha/task"


def fetch_full_task(tid):
    url = f"{API}?id={tid}&format=json"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.json()


def extract_concepts(full_task_json):
    # import pdb; pdb.set_trace()
    found = []
    # 1) top-level concepts (rare)
    for c in full_task_json.get("concepts", []):
        found.append(c)
    # 2) concepts attached to contrasts
    for cnt in full_task_json.get("contrasts", []):
        found.extend(cnt.get("concepts", []))
    # 3) concepts in conditions
    for cond in full_task_json.get("conditions", []):
        found.extend(cond.get("concepts", []))
    # 4) concepts in measures (if present)
    for m in full_task_json.get("measures", []):
        found.extend(m.get("concepts", []))
    # deduplicate by concept_id or id
    uniq = {}
    for c in found:
        cid = c.get("concept_id") or c.get("id")
        if cid:
            uniq[cid] = c
    return list(uniq.values())


edges = []
for t in get_task().json:
    tid = t["id"]
    try:
        full = fetch_full_task(tid)
        concept_list = extract_concepts(full)
        if not concept_list:
            continue
        for c in concept_list:
            edges.append(
                {
                    "task_id": tid,
                    "task_name": t["name"],
                    "concept_id": c.get("concept_id") or c.get("id"),
                    "concept_name": c.get("name", ""),
                    "relationship": c.get("relationship", ""),
                }
            )
        time.sleep(0.2)  # be gentle to the API
    except Exception as e:
        print(f"Failed to fetch task {tid}: {e}")

out = pathlib.Path("data/graphs/task_concept_edges.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(edges, indent=2))
print(f"Wrote {len(edges)} edges → {out}")

""" example usage """
# Get the mapping from task_id to concept_ids
task_concept_map = task2concept()

# Example: for a given task_id
task_id = "trm_4fba85a597ca9"
concept_ids = task_concept_map.get(task_id, set())

# Get human-readable names for these concepts
concept_names = [id2name().get(cid, "") for cid in concept_ids]

# Get Level-0 topic/domain for each concept
level0_domains = [id2level0().get(cid, "") for cid in concept_ids]

print(concept_names)
print(level0_domains)
