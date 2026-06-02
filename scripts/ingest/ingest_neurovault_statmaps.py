import json, os, re
from pathlib import Path
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None
if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("Missing NEO4J env vars")

DATA_DIR = Path("data/neurovault/cache")
explicit = os.environ.get("NV_JSON")
if explicit:
    JSON_PATH = Path(explicit)
    if not JSON_PATH.exists():
        raise SystemExit(f"NV_JSON not found: {JSON_PATH}")
else:
    json_files = sorted(DATA_DIR.glob("neurovault_images_*.json"))
    if not json_files:
        raise SystemExit("No neurovault images json found in data/neurovault/cache")
    # pick the smallest file to avoid huge loads
    JSON_PATH = min(json_files, key=lambda p: p.stat().st_size)
print(f"Using {JSON_PATH}")

ds_re = re.compile(r"ds\d{6,}", re.IGNORECASE)


def map_dataset(blob: str):
    for m in ds_re.finditer(blob or ""):
        ds = m.group(0).lower()
        if not ds.startswith("ds"):
            ds = "ds" + ds
        return f"ds:openneuro:{ds}"
    return None


def main():
    obj = json.loads(JSON_PATH.read_text())
    maps = obj.get("statistical_maps") or obj.get("images") or []
    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
        with driver.session(database=NEO4J_DB) as session:
            created = 0
            linked = 0
            for m in maps:
                nv_id = str(m.get("id"))
                if not nv_id:
                    continue
                node_id = f"neurovault:{nv_id}"
                props = {
                    "id": node_id,
                    "neurovault_id": nv_id,
                    "source": "neurovault",
                    "collection_id": m.get("collection_id"),
                    "collection_name": m.get("collection_name"),
                    "name": m.get("name"),
                    "map_type": m.get("map_type"),
                    "analysis_level": m.get("analysis_level"),
                    "modality": m.get("modality"),
                    "contrast_definition": m.get("contrast_definition") or m.get("contrast_name"),
                    "statistic": m.get("statistic"),
                    "url": m.get("url"),
                    "doi": m.get("doi") or m.get("paper_url"),
                }
                session.run("MERGE (m:StatMap {id:$id}) SET m += $props", {"id": node_id, "props": props})
                created += 1

                blob = " ".join([
                    m.get("collection_name") or "",
                    m.get("description") or "",
                    m.get("name") or ""
                ])
                ds_id = map_dataset(blob)
                if ds_id:
                    link = session.run(
                        """
                        MATCH (d:Dataset {id:$ds})
                        MATCH (m:StatMap {id:$mid})
                        MERGE (d)-[:HAS_STATMAP]->(m)
                        RETURN d
                        """,
                        {"ds": ds_id, "mid": node_id}
                    ).single()
                    if link:
                        linked += 1
            print(f"StatMaps created/merged: {created}; linked to datasets: {linked}")

if __name__ == "__main__":
    main()
