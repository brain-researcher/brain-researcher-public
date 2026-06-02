import os
import csv
from pathlib import Path
from typing import List, Tuple
from datetime import date

from neo4j import GraphDatabase
from rapidfuzz import process, fuzz

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None
if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("Missing NEO4J env vars")

OUTPUT = Path("tmp/task_onvoc_candidates.csv")
TOP_K = 3
CANDIDATE_THRESHOLD = 70  # keep candidates if score >= 70
APPLY_THRESHOLD = int(os.environ.get("APPLY_THRESHOLD", "0"))  # auto-link if score >= this (0 means no auto-link)
METHOD = "fuzzy_token_set_v1"
VERSION = str(date.today())


def fetch_onvoc(session) -> List[Tuple[str, str]]:
    rows = session.run(
        """
        MATCH (c:OnvocClass)
        RETURN c.id AS id, c.name AS name, coalesce(c.synonyms, []) AS syns, coalesce(c.definition,'') AS defn
        """
    ).data()
    concepts = []  # (label_for_match, onvoc_id)
    for r in rows:
        cid = r["id"]
        labels = [r["name"]] + list(r.get("syns") or [])
        for lab in labels:
            concepts.append((lab, cid))
    return concepts


def fetch_tasks(session) -> List[str]:
    rows = session.run(
        """
        MATCH (t:Task)
        RETURN DISTINCT t.name AS name
        """
    ).data()
    return [r["name"] for r in rows if r.get("name")]


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
        with driver.session(database=NEO4J_DB) as session:
            concepts = fetch_onvoc(session)
            if not concepts:
                raise SystemExit("No ONVOC concepts found")
            concept_labels = [c[0] for c in concepts]
            label_to_id = {c[0]: c[1] for c in concepts}

            tasks = fetch_tasks(session)
            rows_out = []
            to_link = []
            for tname in tasks:
                matches = process.extract(
                    tname,
                    concept_labels,
                    scorer=fuzz.token_set_ratio,
                    limit=TOP_K,
                )
                for lab, score, _ in matches:
                    if score < CANDIDATE_THRESHOLD:
                        continue
                    cid = label_to_id[lab]
                    rows_out.append([tname, cid, lab, score])
                    if APPLY_THRESHOLD and score >= APPLY_THRESHOLD:
                        to_link.append((tname, cid, score))

            with OUTPUT.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["task_name", "onvoc_id", "onvoc_label", "score"])
                w.writerows(rows_out)
            print(f"Wrote candidates: {len(rows_out)} to {OUTPUT}")

            if APPLY_THRESHOLD:
                created = 0
                for tname, cid, score in to_link:
                    session.run(
                        """
                        MATCH (t:Task {name:$tname})
                        MATCH (o:OnvocClass {id:$cid})
                        MERGE (t)-[r:CLASSIFIED_UNDER]->(o)
                        SET r.score = $score, r.method = $method, r.version = $version
                        """,
                        {"tname": tname, "cid": cid, "score": score, "method": METHOD, "version": VERSION},
                    )
                    created += 1
                print(f"Auto-linked high-confidence tasks (score >= {APPLY_THRESHOLD}): {created}")

if __name__ == "__main__":
    main()
