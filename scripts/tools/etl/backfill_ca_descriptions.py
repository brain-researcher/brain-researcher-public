#!/usr/bin/env python3
"""Populate Task.description/definition from the CA snapshot for richer matching."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import typer
from neo4j import GraphDatabase

app = typer.Typer(help="Backfill Cognitive Atlas task descriptions into Neo4j")


def _load_rows(snapshot: Path) -> List[Dict[str, str]]:
    payload = json.loads(snapshot.read_text())
    rows: List[Dict[str, str]] = []
    for entry in payload:
        task_id = entry.get("id")
        if not task_id:
            continue
        text = (entry.get("definition_text") or "").strip()
        if not text:
            continue
        rows.append({"id": task_id, "description": text, "definition": text})
    return rows


def _chunk(items: List[Dict[str, str]], size: int) -> List[List[Dict[str, str]]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


@app.command()
def apply(  # pylint: disable=too-many-arguments
    snapshot: Path = typer.Argument(..., exists=True, readable=True, help="task_snapshot_full.json"),
    uri: str = typer.Option("bolt://localhost:7687", help="Neo4j URI"),
    user: str = typer.Option("neo4j", help="Neo4j user"),
    password: str = typer.Option("password", help="Neo4j password"),
    database: str = typer.Option("neo4j", help="Neo4j database name"),
    batch_size: int = typer.Option(500, min=1, help="Rows per write batch"),
    loader_version: str = typer.Option("br/kg/ca_description_backfill/0.1"),
    dry_run: bool = typer.Option(False, help="Do not write, just report counts"),
) -> None:
    rows = _load_rows(snapshot)
    typer.echo(f"Loaded {len(rows)} snapshot rows with definition_text")
    if not rows:
        raise typer.Exit(code=0)

    if dry_run:
        typer.echo("Dry-run enabled; skipping Neo4j writes")
        raise typer.Exit(code=0)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    query = """
    UNWIND $rows AS row
    MATCH (t:Task {id: row.id, source:"cognitive_atlas"})
    WITH t, row
    SET t.description = CASE WHEN coalesce(t.description, "") = "" THEN row.description ELSE t.description END,
        t.definition = CASE WHEN coalesce(t.definition, "") = "" THEN row.definition ELSE t.definition END,
        t.updated_at = datetime(),
        t.loader_version = $loader_version
    """

    total = 0
    with driver.session(database=database) as session:
        for chunk in _chunk(rows, batch_size):
            session.run(query, rows=chunk, loader_version=loader_version)
            total += len(chunk)
    driver.close()
    typer.echo(f"Upserted descriptions for {total} tasks")


if __name__ == "__main__":
    app()
