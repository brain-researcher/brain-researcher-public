import requests
import json
import pathlib
from time import sleep

BASE = "https://www.cognitiveatlas.org/api/v-alpha"


def fetch_all_tasks():
    resp = requests.get(f"{BASE}/task?format=json")
    resp.raise_for_status()
    return {t["id"]: t for t in resp.json()}


def get_task_concepts(task_id):
    params = {"type": "task", "id": task_id, "format": "json"}
    resp = requests.get(f"{BASE}/search", params=params)
    resp.raise_for_status()
    return resp.json()


def main():
    all_tasks = fetch_all_tasks()
    edges = []
    for i, task_id in enumerate(all_tasks):
        try:
            links = get_task_concepts(task_id)
        except Exception as e:
            print(f"Error fetching concepts for task {task_id}: {e}")
            continue
        for link in links:
            if "concept" in link:
                edges.append(
                    {
                        "task_id": task_id,
                        "task_name": all_tasks[task_id]["name"],
                        "concept_id": link["concept"]["id"],
                        "concept_name": link["concept"]["name"],
                        "relationship": link["relationship"],
                    }
                )
        if (i + 1) % 20 == 0:
            print(f"Processed {i+1}/{len(all_tasks)} tasks...")
            sleep(0.2)  # Be gentle to the API

    out = pathlib.Path("data/graphs/task_concept_edges_v2.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(edges, indent=2))
    print(f"Wrote {len(edges)} edges → {out}")


if __name__ == "__main__":
    main()
