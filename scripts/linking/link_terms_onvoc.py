import os, csv
from datetime import date
from pathlib import Path
from neo4j import GraphDatabase
from rapidfuzz import process, fuzz

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None
if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("Missing NEO4J env vars")

OUTPUT = Path("tmp/terms_onvoc_candidates.csv")
TOP_K = 3
CANDIDATE_THRESHOLD = 70
APPLY_THRESHOLD = int(os.environ.get("APPLY_THRESHOLD", "90"))
METHOD = "terms_fuzzy_v1"
VERSION = str(date.today())


def fetch_onvoc(session):
    res = session.run(
        """
        MATCH (c:OnvocClass)
        RETURN c.id AS id, c.name AS name, coalesce(c.synonyms, []) AS syns
        """
    ).data()
    labels = []
    for r in res:
        cid = r["id"]
        for lab in [r["name"], *(r.get("syns") or [])]:
            labels.append((lab, cid))
    return labels


def fetch_terms(session):
    res = session.run("MATCH (t:Term {source:'neurosynth'}) RETURN t.id AS id, coalesce(t.name,'') AS name").data()
    return [(r["id"], r["name"]) for r in res if r.get("name")]


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
        with driver.session(database=NEO4J_DB) as session:
            concepts = fetch_onvoc(session)
            if not concepts:
                raise SystemExit("No ONVOC concepts")
            concept_labels = [c[0] for c in concepts]
            label_to_id = {c[0]: c[1] for c in concepts}

            terms = fetch_terms(session)
            rows_out = []
            to_link = []
            for tid, name in terms:
                matches = process.extract(name, concept_labels, scorer=fuzz.token_set_ratio, limit=TOP_K)
                for lab, score, _ in matches:
                    if score < CANDIDATE_THRESHOLD:
                        continue
                    cid = label_to_id[lab]
                    rows_out.append([tid, cid, lab, score])
                    if APPLY_THRESHOLD and score >= APPLY_THRESHOLD:
                        to_link.append((tid, cid, score))

            with OUTPUT.open('w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["term_id", "onvoc_id", "onvoc_label", "score"])
                w.writerows(rows_out)
            print(f"Wrote candidates: {len(rows_out)} to {OUTPUT}")

            if APPLY_THRESHOLD:
                created = 0
                for tid, cid, score in to_link:
                    session.run(
                        """
                        MATCH (t:Term {id:$tid})
                        MATCH (o:OnvocClass {id:$cid})
                        MERGE (t)-[r:CLASSIFIED_UNDER]->(o)
                        SET r.score=$score, r.method=$method, r.version=$version
                        """,
                        {"tid": tid, "cid": cid, "score": score, "method": METHOD, "version": VERSION},
                    )
                    created += 1
                print(f"Auto-linked terms (score >= {APPLY_THRESHOLD}): {created}")

if __name__ == '__main__':
    main()
