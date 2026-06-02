#!/usr/bin/env python
"""
Build evaluation artifacts for BR-KG snapshot:
- 2A curator audit sample (CSV)
- 2B retrieval benchmark dataset (JSONL)
- 2C planning catalog (JSON)

Uses the live Neo4j DB pointed to by NEO4J_* env vars. Assumes snapshot already frozen.
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIR = ROOT / "data" / "br_kg_exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Helpers ----

def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def connect_driver():
    uri = get_env("NEO4J_URI")
    user = get_env("NEO4J_USER")
    pwd = get_env("NEO4J_PASSWORD")
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    return driver, db


def bucketize(freqs: Dict[str, int]) -> Dict[str, str]:
    """Assign head/mid/tail buckets by rank: top 10% head, next 40% mid, rest tail."""
    items = sorted(freqs.items(), key=lambda kv: (-kv[1], kv[0]))
    n = len(items)
    head_cut = max(1, math.ceil(n * 0.10))
    mid_cut = max(head_cut + 1, math.ceil(n * 0.50))
    buckets = {}
    for idx, (key, _) in enumerate(items):
        if idx < head_cut:
            buckets[key] = "head"
        elif idx < mid_cut:
            buckets[key] = "mid"
        else:
            buckets[key] = "tail"
    return buckets


# ---- 2A: curator audit sample ----

def fetch_dataset_concept_edges(session) -> List[dict]:
    cypher = """
    MATCH (d:Dataset)-[r:IN_ONVOC]->(c:Concept)
    RETURN d.id AS dataset_id,
           d.name AS dataset_name,
           c.id AS concept_id,
           coalesce(c.label, c.name) AS concept_label,
           r.confidence AS confidence,
           r.method AS method,
           r.evidence_json AS evidence_json
    """
    result = session.run(cypher)
    return [dict(record) for record in result]


def build_2a_sample(edges: List[dict], out_csv: Path, sample_per_bucket: int = 40) -> None:
    # frequency per concept
    concept_freq = Counter(e["concept_id"] for e in edges)
    buckets = bucketize(concept_freq)

    # group edges by bucket
    edges_by_bucket: Dict[str, List[dict]] = defaultdict(list)
    for e in edges:
        b = buckets[e["concept_id"]]
        e_copy = {**e, "bucket": b, "freq": concept_freq[e["concept_id"]]}
        edges_by_bucket[b].append(e_copy)

    random.seed(42)
    sampled: List[dict] = []
    for bucket, items in edges_by_bucket.items():
        k = min(sample_per_bucket, len(items))
        sampled.extend(random.sample(items, k))

    # write CSV
    fieldnames = [
        "edge_type",
        "bucket",
        "dataset_id",
        "dataset_name",
        "concept_id",
        "concept_label",
        "freq",
        "confidence",
        "method",
        "evidence_json",
    ]
    for row in sampled:
        row["edge_type"] = "dataset->concept (IN_ONVOC)"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sampled)

    meta = {
        "total_edges": len(edges),
        "concepts": len(concept_freq),
        "bucket_counts": {b: len(v) for b, v in edges_by_bucket.items()},
        "sample_per_bucket": sample_per_bucket,
    }
    (out_csv.parent / "2A_curator_audit_meta.json").write_text(json.dumps(meta, indent=2))


# ---- 2B: retrieval benchmark ----

def fetch_dataset_labels(session) -> List[dict]:
    cypher = """
    MATCH (d:Dataset)-[:IN_ONVOC]->(c:Concept)
    WITH d, collect(DISTINCT c.id) AS concepts
    RETURN d.id AS dataset_id,
           d.name AS name,
           d.description AS description,
           d.search_blob AS search_blob,
           d.modalities AS modalities,
           d.source_repo AS source_repo,
           d.source_repo_id AS source_repo_id,
           concepts AS concept_ids
    """
    return [dict(r) for r in session.run(cypher)]


def build_2b_benchmark(records: List[dict], concept_buckets: Dict[str, str], out_jsonl: Path) -> None:
    random.seed(42)
    total = 0
    groups: Counter[str] = Counter()
    with out_jsonl.open("w", encoding="utf-8") as f:
        for rec in records:
            concepts = rec.get("concept_ids") or []
            if not concepts:
                continue
            buckets = [concept_buckets.get(c, "tail") for c in concepts]
            text = rec.get("description") or rec.get("search_blob") or rec.get("name")
            group_val = rec.get("source_repo") or rec.get("source_repo_id") or rec["dataset_id"]
            obj = {
                "dataset_id": rec["dataset_id"],
                "name": rec.get("name"),
                "text": text,
                "modalities": rec.get("modalities") or [],
                "concept_ids": concepts,
                "concept_buckets": buckets,
                "source_repo": rec.get("source_repo"),
                "source_repo_id": rec.get("source_repo_id"),
                "group": group_val,
            }
            groups[group_val] += 1
            total += 1
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    top_groups = groups.most_common(10)
    meta = {
        "total_examples": total,
        "unique_groups": len(groups),
        "top_groups": top_groups,
        "group_field": "group",
        "note": "Use this as sparse-label benchmark; downsample tail labels externally. Grouped splits can use `group` (source_repo fallback to dataset_id).",
    }
    (out_jsonl.parent / "2B_retrieval_meta.json").write_text(json.dumps(meta, indent=2))


# ---- 2C: planning catalog ----

def fetch_planning_catalog(session) -> Tuple[List[dict], List[dict], List[dict], List[dict]]:
    tool_cypher = """
    MATCH (t:Tool)-[:HAS_VERSION]->(v:ToolVersion)
    OPTIONAL MATCH (t)-[:IMPLEMENTS_FAMILY]->(tf:TaskFamily)
    OPTIONAL MATCH (t)-[:SUPPORTS_MODALITY]->(m:Modality)
    OPTIONAL MATCH (v)-[:CONSUMES_RESOURCE]->(rin:ResourceType)
    OPTIONAL MATCH (v)-[:PRODUCES_RESOURCE]->(rout:ResourceType)
    RETURN t.id AS tool_id,
           t.name AS tool_name,
           t.description AS description,
           t.runtime_kind AS runtime_kind,
           v.id AS version_id,
           v.version_id AS version,
           collect(DISTINCT tf.name) AS task_families,
           collect(DISTINCT m.name) AS modalities,
           collect(DISTINCT rin.id) AS consumes,
           collect(DISTINCT rout.id) AS produces
    """
    tools = [dict(r) for r in session.run(tool_cypher)]

    dataset_mod_cypher = """
    MATCH (d:Dataset)
    OPTIONAL MATCH (d)-[:HAS_MODALITY]->(m:Modality)
    WITH d, collect(DISTINCT m.name) AS mods
    RETURN d.id AS dataset_id, d.name AS name, mods AS modalities
    """
    datasets = [dict(r) for r in session.run(dataset_mod_cypher)]

    res_types = [dict(r) for r in session.run("MATCH (r:ResourceType) RETURN r.id AS id, r.name AS name")]
    modalities = [dict(r) for r in session.run("MATCH (m:Modality) RETURN m.id AS id, m.name AS name")]
    return tools, datasets, res_types, modalities


def build_2c_catalog(tools, datasets, res_types, modalities, out_json: Path) -> None:
    catalog = {
        "tools": tools,
        "datasets": datasets,
        "resource_types": res_types,
        "modalities": modalities,
        "note": "Use CONSUMES/PRODUCES as preconditions/postconditions; HAS_MODALITY as dataset state",
    }
    out_json.write_text(json.dumps(catalog, indent=2))


# ---- main ----

def main():
    driver, db = connect_driver()
    with driver.session(database=db) as session:
        # 2A
        edges = fetch_dataset_concept_edges(session)
        concept_freq = Counter(e["concept_id"] for e in edges)
        concept_buckets = bucketize(concept_freq)
        build_2a_sample(edges, EXPORT_DIR / "2A_curator_audit_sample.csv")

        # 2B
        records = fetch_dataset_labels(session)
        build_2b_benchmark(records, concept_buckets, EXPORT_DIR / "2B_retrieval_benchmark.jsonl")

        # 2C
        tools, datasets, res_types, modalities = fetch_planning_catalog(session)
        build_2c_catalog(tools, datasets, res_types, modalities, EXPORT_DIR / "2C_planning_catalog.json")

    driver.close()
    print("Done. Outputs in", EXPORT_DIR)


if __name__ == "__main__":
    main()
