#!/usr/bin/env python3
"""Cognitive Atlas ingest utility.

Loads Tasks, Concepts, Processes, and light relationships into Neo4j using the
NiCLIP-cleaned drop as the primary source with raw Cognitive Atlas dumps as
fallback. Nodes/edges are merged idempotently and stamped with provenance so
the ONVOC mapper can snap tasks to the ontology immediately after ingestion.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import typer
from neo4j import Driver, GraphDatabase


app = typer.Typer(help="Ingest Cognitive Atlas tasks/concepts/processes into Neo4j")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def discover_file(directory: Path, prefix: str) -> Path:
    matches = sorted(directory.glob(f"{prefix}*.json"))
    if not matches:
        raise FileNotFoundError(f"No files matching {prefix}*.json in {directory}")
    return matches[-1]


def slugify(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-") or None


def split_aliases(raw_value: Optional[str]) -> List[str]:
    if not raw_value:
        return []
    tokens = re.split(r"[,;/]\s*", raw_value)
    cleaned = []
    for token in tokens:
        token = token.strip()
        if token:
            cleaned.append(token)
    return cleaned


def chunked(rows: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for idx in range(0, len(rows), size):
        yield rows[idx : idx + size]


def normalize_id(value: str) -> str:
    return value.lower()


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------


def serialize_metadata(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def build_task_record(row: Dict[str, Any], ingest_variant: str) -> Dict[str, Any]:
    tid = normalize_id(row["id"])
    name = row.get("name") or row.get("alias") or tid
    if not name:
        raise ValueError(f"Task {tid} missing name and alias")
    slug = slugify(row.get("bids_task") or name)
    if slug:
        if slug.endswith("-task"):
            slug = slug[:-5] or slug
        elif slug.endswith("-test"):
            slug = slug[:-5] or slug
    aliases = split_aliases(row.get("alias"))
    record = {
        "id": tid,
        "name": name,
        "slug": slug,
        "description": row.get("definition_text"),
        "aliases": aliases,
        "ingest_variant": ingest_variant,
        "metadata_json": serialize_metadata(row),
    }
    return record


def build_concept_record(row: Dict[str, Any], ingest_variant: str) -> Dict[str, Any]:
    cid = normalize_id(row["id"])
    name = row.get("name") or row.get("alias") or cid
    if not name:
        raise ValueError(f"Concept {cid} missing name and alias")
    aliases = split_aliases(row.get("alias"))
    record = {
        "id": cid,
        "name": name,
        "definition": row.get("definition_text"),
        "aliases": aliases,
        "category": row.get("id_concept_class"),
        "ingest_variant": ingest_variant,
        "metadata_json": serialize_metadata(row),
        "metadata_full_json": None,
    }
    return record


def enrich_from_full(
    concepts: Dict[str, Dict[str, Any]],
    concepts_full_dir: Path,
) -> List[Dict[str, str]]:
    relationships: List[Dict[str, str]] = []
    for path in concepts_full_dir.glob("*.json"):
        data = load_json(path)
        cid = normalize_id(data["id"])
        record = concepts.setdefault(
            cid,
            build_concept_record(data, ingest_variant="raw"),
        )
        if data.get("definition_text"):
            record["definition"] = data["definition_text"]
        record["metadata_full_json"] = serialize_metadata(data)
        for rel in data.get("relationships", []) or []:
            if rel.get("relationship") != "KINDOF":
                continue
            other_id = normalize_id(rel["id"])
            direction = rel.get("direction")
            if direction == "parent":
                relationships.append({"child_id": cid, "parent_id": other_id})
            elif direction == "child":
                relationships.append({"child_id": other_id, "parent_id": cid})
    return relationships


def prepare_tasks(niclip_rows: List[Dict[str, Any]], raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    for row in niclip_rows:
        records[normalize_id(row["id"])] = build_task_record(row, "niclip")
    for row in raw_rows:
        tid = normalize_id(row["id"])
        if tid not in records:
            records[tid] = build_task_record(row, "raw")
    return list(records.values())


def prepare_concepts(
    niclip_rows: List[Dict[str, Any]],
    raw_rows: List[Dict[str, Any]],
    concepts_full_dir: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    concepts: Dict[str, Dict[str, Any]] = {}
    for row in niclip_rows:
        concepts[normalize_id(row["id"])] = build_concept_record(row, "niclip")
    for row in raw_rows:
        cid = normalize_id(row["id"])
        if cid not in concepts:
            concepts[cid] = build_concept_record(row, "raw")
    relationships = enrich_from_full(concepts, concepts_full_dir)
    return list(concepts.values()), relationships


def prepare_processes(cao_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processes: List[Dict[str, Any]] = []
    for row in cao_rows:
        pid = row["id"]
        name = row.get("label")
        if not name:
            raise ValueError(f"Process {pid} missing label")
        processes.append(
            {
                "id": pid,
                "name": name,
                "description": row.get("definition"),
                "synonyms": row.get("synonyms") or [],
                "ingest_variant": "cao",
                "metadata_json": serialize_metadata(row),
            }
        )
    return processes


def prepare_concept_process_edges(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    edges: List[Dict[str, str]] = []
    for row in rows:
        concept_id = normalize_id(row["concept_id"])
        process_id = row["process_id"]
        edges.append({"concept_id": concept_id, "process_id": process_id})
    return edges


# ---------------------------------------------------------------------------
# Neo4j writes
# ---------------------------------------------------------------------------


def build_driver(uri: str, user: str, password: str) -> Driver:
    return GraphDatabase.driver(uri, auth=(user, password))


def ensure_constraints(driver: Driver, database: Optional[str]) -> None:
    statements = [
        """CREATE CONSTRAINT process_id IF NOT EXISTS FOR (p:Process) REQUIRE p.id IS UNIQUE""",
        """CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE""",
        """CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE""",
    ]
    with driver.session(database=database) as session:
        for stmt in statements:
            session.run(stmt)


def upsert_tasks(
    driver: Driver,
    rows: List[Dict[str, Any]],
    loader_version: str,
    batch_size: int,
    database: Optional[str],
) -> int:
    if not rows:
        return 0
    query = """
    UNWIND $rows AS row
    MERGE (t:Task {id: row.id})
    SET t.name = row.name,
        t.slug = row.slug,
        t.description = row.description,
        t.aliases = row.aliases,
        t.source = "cognitive_atlas",
        t.ingest_variant = row.ingest_variant,
        t.metadata_json = row.metadata_json,
        t.loader_version = $loader_version,
        t.updated_at = datetime()
    SET t.created_at = coalesce(t.created_at, datetime())
    """
    with driver.session(database=database) as session:
        for chunk in chunked(rows, batch_size):
            session.run(query, rows=chunk, loader_version=loader_version)
    return len(rows)


def upsert_concepts(
    driver: Driver,
    rows: List[Dict[str, Any]],
    loader_version: str,
    batch_size: int,
    database: Optional[str],
) -> int:
    if not rows:
        return 0
    query = """
    UNWIND $rows AS row
    MERGE (c:Concept {id: row.id})
    SET c.name = row.name,
        c.definition = row.definition,
        c.aliases = row.aliases,
        c.category = row.category,
        c.source = "cognitive_atlas",
        c.ingest_variant = row.ingest_variant,
        c.metadata_json = row.metadata_json,
        c.metadata_full_json = coalesce(row.metadata_full_json, c.metadata_full_json),
        c.loader_version = $loader_version,
        c.updated_at = datetime()
    SET c.created_at = coalesce(c.created_at, datetime())
    """
    with driver.session(database=database) as session:
        for chunk in chunked(rows, batch_size):
            session.run(query, rows=chunk, loader_version=loader_version)
    return len(rows)


def upsert_processes(
    driver: Driver,
    rows: List[Dict[str, Any]],
    loader_version: str,
    batch_size: int,
    database: Optional[str],
) -> int:
    if not rows:
        return 0
    query = """
    UNWIND $rows AS row
    MERGE (p:Process {id: row.id})
    SET p.name = row.name,
        p.description = row.description,
        p.synonyms = row.synonyms,
        p.source = "cognitive_atlas",
        p.ingest_variant = row.ingest_variant,
        p.metadata_json = row.metadata_json,
        p.loader_version = $loader_version,
        p.updated_at = datetime()
    SET p.created_at = coalesce(p.created_at, datetime())
    """
    with driver.session(database=database) as session:
        for chunk in chunked(rows, batch_size):
            session.run(query, rows=chunk, loader_version=loader_version)
    return len(rows)


def merge_concept_relationships(
    driver: Driver,
    rows: List[Dict[str, str]],
    loader_version: str,
    batch_size: int,
    database: Optional[str],
) -> int:
    if not rows:
        return 0
    query = """
    UNWIND $rows AS row
    MATCH (child:Concept {id: row.child_id})
    MATCH (parent:Concept {id: row.parent_id})
    MERGE (child)-[r:KINDOF]->(parent)
    SET r.source = "cognitive_atlas",
        r.loader_version = $loader_version,
        r.updated_at = datetime()
    """
    with driver.session(database=database) as session:
        for chunk in chunked(rows, batch_size):
            session.run(query, rows=chunk, loader_version=loader_version)
    return len(rows)


def merge_concept_process_edges(
    driver: Driver,
    rows: List[Dict[str, str]],
    loader_version: str,
    batch_size: int,
    database: Optional[str],
) -> int:
    if not rows:
        return 0
    query = """
    UNWIND $rows AS row
    MATCH (c:Concept {id: row.concept_id})
    MATCH (p:Process {id: row.process_id})
    MERGE (c)-[r:ALIGNS_WITH]->(p)
    SET r.source = "cognitive_atlas",
        r.loader_version = $loader_version,
        r.updated_at = datetime()
    """
    with driver.session(database=database) as session:
        for chunk in chunked(rows, batch_size):
            session.run(query, rows=chunk, loader_version=loader_version)
    return len(rows)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@app.command()
def ingest(
    niclip_dir: Path = typer.Option(
        Path("data/niclip/data/cognitive_atlas"),
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Directory with NiCLIP cognitive atlas exports",
    ),
    raw_dir: Path = typer.Option(
        Path("data/cognitive_atlas"),
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Directory with raw Cognitive Atlas dumps",
    ),
    neo4j_uri: str = typer.Option("bolt://localhost:7687", help="Neo4j bolt URI"),
    neo4j_user: str = typer.Option("neo4j", help="Neo4j user"),
    neo4j_password: str = typer.Option("password", help="Neo4j password"),
    database: Optional[str] = typer.Option(None, help="Neo4j database name"),
    loader_version: str = typer.Option("br/kg/cogatlas/0.1", help="Loader version tag"),
    batch_size: int = typer.Option(1000, help="UNWIND batch size"),
) -> None:
    """Ingest Cognitive Atlas data into Neo4j."""

    niclip_task_file = discover_file(niclip_dir, "task_snapshot")
    niclip_concept_file = discover_file(niclip_dir, "concept_snapshot")
    raw_task_file = raw_dir / "tasks_raw.json"
    raw_concept_file = raw_dir / "concepts_raw.json"
    concepts_full_dir = raw_dir / "concepts_full"
    cao_constructs_file = raw_dir / "cao_constructs.json"
    cao_concept_process_file = raw_dir / "cao_concept_to_process.json"

    typer.echo(f"Loading tasks from {niclip_task_file}")
    niclip_tasks = load_json(niclip_task_file)
    raw_tasks = load_json(raw_task_file)

    typer.echo(f"Loading concepts from {niclip_concept_file}")
    niclip_concepts = load_json(niclip_concept_file)
    raw_concepts = load_json(raw_concept_file)

    typer.echo(f"Loading processes from {cao_constructs_file}")
    processes_raw = load_json(cao_constructs_file)
    concept_process_links = load_json(cao_concept_process_file)

    typer.echo("Preparing task records")
    tasks = prepare_tasks(niclip_tasks, raw_tasks)

    typer.echo("Preparing concept records and relationships")
    concepts, concept_relationships = prepare_concepts(
        niclip_concepts,
        raw_concepts,
        concepts_full_dir,
    )

    typer.echo("Preparing process records")
    processes = prepare_processes(processes_raw)
    concept_process_edges = prepare_concept_process_edges(concept_process_links)

    driver = build_driver(neo4j_uri, neo4j_user, neo4j_password)
    try:
        ensure_constraints(driver, database)
        tasks_written = upsert_tasks(driver, tasks, loader_version, batch_size, database)
        concepts_written = upsert_concepts(driver, concepts, loader_version, batch_size, database)
        processes_written = upsert_processes(driver, processes, loader_version, batch_size, database)
        rel_written = merge_concept_relationships(
            driver,
            concept_relationships,
            loader_version,
            batch_size,
            database,
        )
        concept_process_written = merge_concept_process_edges(
            driver,
            concept_process_edges,
            loader_version,
            batch_size,
            database,
        )
    finally:
        driver.close()

    typer.echo(
        "Ingest complete: "
        f"tasks={tasks_written}, concepts={concepts_written}, "
        f"processes={processes_written}, concept_kindof={rel_written}, "
        f"concept_process={concept_process_written}"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
