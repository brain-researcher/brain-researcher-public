"""Utility for refreshing cognitive concepts from Cognitive Atlas."""

import json
from pathlib import Path

import requests

API_URL = "https://www.cognitiveatlas.org/api/v-alpha/concept"  # public endpoint


def fetch_concepts() -> list[dict]:
    resp = requests.get(API_URL)
    resp.raise_for_status()
    return resp.json().get("data", [])


def update_concepts(target_json: Path) -> None:
    concepts = fetch_concepts()
    out = {
        c["name"].replace(" ", "_").lower(): c.get("definition", "") for c in concepts
    }
    with open(target_json, "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    target = Path("knowledge/constructs.json")
    update_concepts(target)
    print(f"Updated {len(json.load(open(target)))} concepts to {target}")
