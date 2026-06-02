"""Lightweight pipeline search over Neo4j for planner/routing use.

Returns a minimal structure with id, name, description, and ordered tool_ids.

Heuristics:
- Filters by modalities if provided.
- Scores by simple word overlap between task text and (name + description + tool_ids).
- Limits results (default 3).

Relocated from ``services/agent/pipeline_catalog`` into the shared layer so that
``services/tools`` can depend on it without a tools -> agent back-edge. The
original agent module re-exports these symbols for backward compatibility.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.config.paths import resolve_from_config

logger = logging.getLogger(__name__)


def _resolve_neo4j_connection(
    uri: str | None,
    user: str | None,
    password: str | None,
) -> tuple[str, str, str | None]:
    """Resolve Neo4j connection settings with explicit > env > legacy fallback."""
    env_uri = (os.getenv("NEO4J_URI") or "").strip()
    env_user = (os.getenv("NEO4J_USER") or "").strip() or "neo4j"
    env_password = os.getenv("NEO4J_PASSWORD")

    resolved_uri = (uri or "").strip() or env_uri or "bolt://localhost:7687"
    resolved_user = (user or "").strip() or env_user
    resolved_password = password if password is not None else env_password
    return resolved_uri, resolved_user, resolved_password


def _score(task: str, name: str, description: str, tools: list[str]) -> int:
    """Simple word-overlap score for sorting pipelines."""
    # tools may be a list of tool_ids (str) or dicts with a tool/tool_id field
    tool_tokens: list[str] = []
    for t in tools or []:
        if isinstance(t, str):
            tool_tokens.append(t)
        elif isinstance(t, dict):
            tool_tokens.append(t.get("tool") or t.get("tool_id") or "")
    text = f"{name} {description} {' '.join(tool_tokens)}".lower()
    words = re.findall(r"\w+", task.lower())
    return sum(1 for w in words if w in text)


def search_pipelines(
    task: str,
    modalities: list[str] | None = None,
    limit: int = 3,
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> list[dict[str, Any]]:
    """Search Pipeline nodes and return ordered steps.

    Args:
        task: free-text task description
        modalities: optional modality filter (fmri/smri/dmri)
        limit: max number of pipelines to return
        uri/user/password: optional Neo4j connection override. If omitted,
            values are resolved from NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD, then
            fallback to bolt://localhost:7687 and neo4j.

    Returns: list of {id,name,description,modalities,steps:[tool_ids]}
    """
    resolved_uri, resolved_user, resolved_password = _resolve_neo4j_connection(
        uri=uri,
        user=user,
        password=password,
    )
    driver = GraphDatabase.driver(resolved_uri, auth=(resolved_user, resolved_password))
    cypher = """
    MATCH (p:Pipeline)
    OPTIONAL MATCH (p)-[s:STEP]->(t:Tool)
    WITH p, s, t
    ORDER BY s.order
    WITH p, collect(t.id) AS tool_ids
    RETURN p.id AS id, p.name AS name, p.description AS description,
           coalesce(p.modalities, []) AS modalities, tool_ids
    """

    with driver.session() as session:
        records = session.run(cypher).values()

    # Load local pipeline templates (YAML) so we can enrich results with params
    templates_by_id: dict[str, Any] = {}
    try:
        templates_path = resolve_from_config("catalog", "pipelines.yaml")
        if templates_path.exists():
            import yaml

            with open(templates_path) as f:
                data = yaml.safe_load(f) or {}
            for pipe in data.get("pipelines", []):
                if pipe.get("id"):
                    templates_by_id[pipe["id"]] = pipe
    except Exception as e:  # best-effort enrichment
        logger.warning(f"Failed to load local pipeline templates: {e}")

    results = []
    task_modalities = set(modalities or [])
    for rid, name, desc, mods, tools in records:
        if task_modalities and mods:
            if not task_modalities.intersection(set(mods)):
                continue
        # If we have a local template, prefer its steps (with params)
        if rid in templates_by_id:
            tmpl = templates_by_id[rid]
            steps = tmpl.get("steps", []) or tools or []
            desc = desc or tmpl.get("description")
            mods = mods or tmpl.get("modalities", [])
        else:
            steps = tools or []

        results.append(
            {
                "id": rid,
                "name": name,
                "description": desc,
                "modalities": mods,
                "steps": steps,
            }
        )

    # Score and sort
    results.sort(
        key=lambda r: _score(task, r["name"] or "", r["description"] or "", r["steps"]),
        reverse=True,
    )
    return results[:limit]


def format_pipeline_summary(pipeline: dict[str, Any]) -> str:
    """Human-readable summary for prompts."""
    steps = " -> ".join(pipeline.get("steps", [])) or "(no steps)"
    return f"{pipeline['id']}: {pipeline.get('name','')} | steps: {steps}"


__all__ = ["search_pipelines", "format_pipeline_summary"]
