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

OUTPUT = Path("tmp/cogatlas_onvoc_candidates.csv")
TOP_K = 3
CANDIDATE_THRESHOLD = 70
APPLY_THRESHOLD = int(os.environ.get("APPLY_THRESHOLD", "90"))
SECOND_PASS_THRESHOLD = int(os.environ.get("APPLY_THRESHOLD_FUZZY", "75"))
METHOD = "cogatlas_fuzzy_v1"
VERSION = str(date.today())


def fetch_onvoc(session):
    res = session.run("MATCH (c:OnvocClass) RETURN c.id AS id, c.name AS name, coalesce(c.synonyms,[]) AS syns").data()
    labels = []
    for r in res:
        cid = r["id"]
        for lab in [r["name"], *(r.get("syns") or [])]:
            labels.append((lab, cid))
    return labels


def fetch_cogatlas_concepts(session):
    res = session.run(
        """
        MATCH (c:Concept {source:'cognitive_atlas'})
        RETURN c.id AS id, c.name AS name, coalesce(c.synonyms,[]) AS syns
        """
    ).data()
    out = []
    for r in res:
        name = r.get("name")
        if not name:
            continue
        labels = [name] + list(r.get("syns") or [])
        out.append((r["id"], labels))
    return out


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
        with driver.session(database=NEO4J_DB) as session:
            concepts = fetch_onvoc(session)
            if not concepts:
                raise SystemExit("No ONVOC concepts")
            concept_labels = [c[0] for c in concepts]
            label_to_id = {c[0]: c[1] for c in concepts}

            # Index ONVOC by normalized slug for exact matches
            def slug(text: str) -> str:
                return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")

            slug_to_onvoc = {}
            for lab, cid in concepts:
                if not lab:
                    continue
                slug_to_onvoc.setdefault(slug(lab), cid)

            cog_concepts = fetch_cogatlas_concepts(session)
            rows_out = []
            to_link = []
            for cid, labels in cog_concepts:
                best_exact = None
                # Pass 1: exact/slug match
                for text in labels:
                    if not text:
                        continue
                    s = slug(text)
                    if s in slug_to_onvoc:
                        best_exact = (slug_to_onvoc[s], text)
                        break
                if best_exact:
                    onvoc_id, matched = best_exact
                    rows_out.append([cid, onvoc_id, matched, 100, matched])
                    to_link.append((cid, onvoc_id, 100))
                    continue

                # Pass 2: fuzzy
                for text in labels:
                    if not text:
                        continue
                    matches = process.extract(text, concept_labels, scorer=fuzz.token_set_ratio, limit=TOP_K)
                    for lab, score, _ in matches:
                        if score < CANDIDATE_THRESHOLD:
                            continue
                        onvoc_id = label_to_id[lab]
                        rows_out.append([cid, onvoc_id, lab, score, text])
                        threshold = APPLY_THRESHOLD if APPLY_THRESHOLD else SECOND_PASS_THRESHOLD
                        if score >= threshold:
                            to_link.append((cid, onvoc_id, score))

            with OUTPUT.open('w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["cogatlas_id", "onvoc_id", "onvoc_label", "score", "matched_text"])
                w.writerows(rows_out)
            print(f"Wrote candidates: {len(rows_out)} to {OUTPUT}")

            if APPLY_THRESHOLD:
                created = 0
                for cid, oid, score in to_link:
                    session.run(
                        """
                        MATCH (c:Concept {id:$cid, source:'cognitive_atlas'})
                        MATCH (o:OnvocClass {id:$oid})
                        MERGE (c)-[r:CLASSIFIED_UNDER]->(o)
                        SET r.score=$score, r.method=$method, r.version=$version
                        """,
                        {"cid": cid, "oid": oid, "score": score, "method": METHOD, "version": VERSION},
                    )
                    created += 1
                print(f"Auto-linked cogatlas concepts (score >= {APPLY_THRESHOLD}): {created}")

if __name__ == '__main__':
    main()
