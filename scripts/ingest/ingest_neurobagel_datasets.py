import os
import requests
from collections import defaultdict
from neo4j import GraphDatabase

API_URL = os.environ.get("NEUROBAGEL_API", "https://api.neurobagel.org/query")

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None

if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("Missing NEO4J env vars")


def fetch_neurobagel(api_url: str = API_URL):
    resp = requests.get(api_url)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", [])


def normalize_dataset_id(name: str) -> str:
    # Neurobagel uses OpenNeuro accessions like ds000001
    slug = name.strip()
    if not slug.startswith("ds"):
        return slug
    return f"ds:openneuro:{slug.lower()}"


def aggregate(rows):
    agg = {}
    for r in rows:
        ds = r.get("DatasetName") or r.get("dataset")
        if not ds:
            continue
        key = normalize_dataset_id(ds)
        entry = agg.setdefault(key, {
            "name": ds,
            "portal": r.get("PortalURI"),
            "modalities": set(),
            "pipelines": set(),
            "subjects": 0,
        })
        if r.get("DatasetImagingModalities"):
            entry["modalities"].update(r["DatasetImagingModalities"])
        if r.get("DatasetPipelines"):
            entry["pipelines"].update(r["DatasetPipelines"])
        try:
            entry["subjects"] += int(r.get("NumMatchingSubjects") or 0)
        except ValueError:
            pass
    return agg


def upsert_to_neo4j(agg):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database=NEO4J_DB) as session:
        for dsid, info in agg.items():
            modalities = sorted(info["modalities"])
            pipelines = sorted(info["pipelines"])
            session.run(
                """
                MERGE (d:Dataset {dataset_id:$dsid})
                ON CREATE SET d.name = coalesce(d.name, $name), d.source_repo='OpenNeuro'
                SET d.portal_uri=$portal,
                    d.nb_modalities=$modalities,
                    d.nb_pipelines=$pipelines,
                    d.nb_subjects=$subjects
                """,
                {
                    "dsid": dsid,
                    "name": info["name"],
                    "portal": info["portal"],
                    "modalities": modalities,
                    "pipelines": pipelines,
                    "subjects": info["subjects"],
                },
            )
            for m in modalities:
                session.run(
                    """
                    MERGE (mo:Modality {name:$m})
                    WITH mo
                    MATCH (d:Dataset {dataset_id:$dsid})
                    MERGE (d)-[:HAS_MODALITY]->(mo)
                    """,
                    {"m": m, "dsid": dsid},
                )
    driver.close()


def main():
    rows = fetch_neurobagel()
    agg = aggregate(rows)
    upsert_to_neo4j(agg)
    print(f"Updated {len(agg)} datasets from Neurobagel")


if __name__ == "__main__":
    main()
