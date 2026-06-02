import os
from pathlib import Path
import re
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None

VOCAB_PATH = Path("data/neurosynth_nimare/neurosynth_v7/data-neurosynth_version-7_vocab-terms_vocabulary.txt")

slug_re = re.compile(r"[^a-z0-9]+")

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = slug_re.sub("-", text)
    return text.strip("-") or "term"

def main():
    if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
        raise SystemExit("Missing NEO4J env vars")
    if not VOCAB_PATH.exists():
        raise SystemExit(f"Vocab file not found: {VOCAB_PATH}")
    terms = [line.strip() for line in VOCAB_PATH.read_text(encoding='utf-8').splitlines() if line.strip()]
    print(f"Loaded {len(terms)} vocab terms")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    created = 0
    with driver.session(database=NEO4J_DB) as session:
        for term in terms:
            tid = f"neurosynth_term:{slugify(term)}"
            session.run(
                """
                MERGE (t:Term {id:$id})
                SET t.name=$name, t.source='neurosynth'
                """,
                {"id": tid, "name": term},
            )
            created += 1
    print(f"Upserted {created} Term nodes")

if __name__ == "__main__":
    main()
