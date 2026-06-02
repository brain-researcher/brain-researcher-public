import os
import csv
from pathlib import Path
from typing import Dict, List, Tuple
import yaml
from neo4j import GraphDatabase
from rapidfuzz import process, fuzz

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None
if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("Missing NEO4J env vars")

FAMILIES_DIR = Path("configs/taxonomy/families")
OUTPUT = Path("tmp/task_family_candidates.csv")
CANDIDATE_THRESHOLD = 70
APPLY_THRESHOLD = int(os.environ.get("APPLY_FAMILY_THRESHOLD", "85"))  # auto-link if >= this
TOP_K = 3
METHOD = "family_yaml_fuzzy_v1"


def load_families() -> Tuple[Dict[str, dict], List[Tuple[str, str]]]:
    families = {}
    patterns = []  # (pattern_str, family_id)
    for path in FAMILIES_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text()) or {}
        fid = data.get("id") or path.stem
        label = data.get("label") or fid
        desc = data.get("description") or ""
        families[fid] = {"id": fid, "label": label, "description": desc}
        # level: family label
        patterns.append((label, fid))
        # subfamilies and paradigms
        for sub in data.get("subfamilies", []) or []:
            s_label = sub.get("label") or sub.get("id", "")
            if s_label:
                patterns.append((s_label, fid))
            for parad in sub.get("paradigms", []) or []:
                p_name = parad.get("name")
                if p_name:
                    patterns.append((p_name, fid))
                for al in parad.get("aliases", []) or []:
                    patterns.append((al, fid))
    return families, patterns


def fetch_tasks(session) -> List[str]:
    rows = session.run("MATCH (t:Task) RETURN DISTINCT t.name AS name").data()
    return [r["name"] for r in rows if r.get("name")]


def main():
    families, patterns = load_families()
    if not patterns:
        raise SystemExit("No family patterns loaded")
    pattern_labels = [p[0] for p in patterns]
    pattern_to_fid = {p[0]: p[1] for p in patterns}

    OUTPUT.parent.mkdir(exist_ok=True)

    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
        with driver.session(database=NEO4J_DB) as session:
            tasks = fetch_tasks(session)
            rows_out = []
            to_link = []
            for tname in tasks:
                matches = process.extract(tname, pattern_labels, scorer=fuzz.token_set_ratio, limit=TOP_K)
                for pat, score, _ in matches:
                    if score < CANDIDATE_THRESHOLD:
                        continue
                    fid = pattern_to_fid[pat]
                    rows_out.append([tname, fid, pat, score])
                    if score >= APPLY_THRESHOLD:
                        to_link.append((tname, fid, score))

            # write candidates
            with OUTPUT.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["task_name", "family_id", "matched_pattern", "score"])
                w.writerows(rows_out)
            print(f"Wrote candidates: {len(rows_out)} to {OUTPUT}")

            # upsert family nodes
            for fid, meta in families.items():
                session.run(
                    "MERGE (f:TaskFamily {id:$id}) SET f.label=$label, f.description=$desc",
                    {"id": fid, "label": meta["label"], "desc": meta["description"]},
                )

            # apply links
            created = 0
            for tname, fid, score in to_link:
                session.run(
                    """
                    MATCH (t:Task {name:$tname})
                    MATCH (f:TaskFamily {id:$fid})
                    MERGE (t)-[r:BELONGS_TO_FAMILY]->(f)
                    SET r.score=$score, r.method=$method
                    """,
                    {"tname": tname, "fid": fid, "score": score, "method": METHOD},
                )
                created += 1
            print(f"Auto-linked tasks to families (score >= {APPLY_THRESHOLD}): {created}")

if __name__ == "__main__":
    main()
