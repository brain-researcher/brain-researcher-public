"""
Lightweight read-only bridge to BR-KG for planner hints.

Uses env:
  NEO4J_URI (default bolt://localhost:7687)
  NEO4J_USER (default neo4j)
  NEO4J_PASSWORD (required)
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from brain_researcher.config.paths import resolve_from_config

_CATALOG_ALIAS_CACHE: Dict[str, str] | None = None


@lru_cache(maxsize=1)
def _get_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD")
    if not pwd:
        return None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        # quick check
        with driver.session() as session:
            session.run("RETURN 1").consume()
        return driver
    except Exception:
        return None


def get_preferred_families_for_pipeline(pipeline_id: str) -> List[str]:
    """Return family IDs preferred for a pipeline template."""
    driver = _get_driver()
    if driver is None:
        return []
    q = """
    MATCH (p:PipelineTemplate {id:$pid})-[:USES_FAMILY]->(f:ToolFamily)
    RETURN f.id AS fid
    """
    try:
        with driver.session() as session:
            res = session.run(q, pid=pipeline_id)
            return [r["fid"] for r in res]
    except Neo4jError:
        return []


def get_family_stats_for_operation(op_id: str) -> List[Tuple[str, int]]:
    """Return (family_id, tool_count) pairs for an operation."""
    driver = _get_driver()
    if driver is None:
        return []
    q = """
    MATCH (f:ToolFamily)-[r:IMPLEMENTS]->(o:Operation {id:$op})
    RETURN f.id AS fid, coalesce(r.tool_count, 0) AS cnt
    """
    try:
        with driver.session() as session:
            res = session.run(q, op=op_id)
            rows = list(res)
        return [(r["fid"], r["cnt"]) for r in rows]
    except Neo4jError:
        return []


def _normalize_values(values: Iterable[str] | None) -> List[str]:
    cleaned: List[str] = []
    for val in values or []:
        if not isinstance(val, str):
            continue
        v = val.strip()
        if v:
            cleaned.append(v)
    return cleaned


def get_tool_ids_for_constraints(
    *,
    modalities: Iterable[str] | None = None,
    consumes: Iterable[str] | None = None,
    produces: Iterable[str] | None = None,
) -> Set[str] | None:
    """Return tool_ids that satisfy the given KG constraints.

    Returns:
        - None if KG is unavailable
        - set of matching tool_ids otherwise (may be empty)
    """
    driver = _get_driver()
    if driver is None:
        return None

    modalities_list = _normalize_values(modalities)
    consumes_list = _normalize_values(consumes)
    produces_list = _normalize_values(produces)

    if not modalities_list and not consumes_list and not produces_list:
        return set()

    query = """
    MATCH (t:Tool)
    WHERE 1 = 1
      AND (size($modalities) = 0 OR EXISTS {
        MATCH (t)-[:SUPPORTS_MODALITY]->(m:Modality)
        WHERE m.name IN $modalities
      })
      AND (size($consumes) = 0 OR EXISTS {
        MATCH (t)-[:HAS_VERSION]->(:ToolVersion)-[:CONSUMES_RESOURCE]->(r:ResourceType)
        WHERE r.name IN $consumes
      })
      AND (size($produces) = 0 OR EXISTS {
        MATCH (t)-[:HAS_VERSION]->(:ToolVersion)-[:PRODUCES_RESOURCE]->(r:ResourceType)
        WHERE r.name IN $produces
      })
    RETURN DISTINCT coalesce(t.tool_id, t.id) AS tool_id
    """

    try:
        with driver.session() as session:
            res = session.run(
                query,
                modalities=modalities_list,
                consumes=consumes_list,
                produces=produces_list,
            )
            return {
                r["tool_id"]
                for r in res
                if r.get("tool_id") and isinstance(r.get("tool_id"), str)
            }
    except Neo4jError:
        return set()


def get_failed_on_stats(
    tool_ids: Iterable[str],
    *,
    dataset_id: str | None = None,
    task_family: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return failure aggregates per tool (fail_count, last_seen, error_categories)."""
    driver = _get_driver()
    if driver is None:
        return {}
    tid_list = _normalize_values(tool_ids)
    if not tid_list:
        return {}
    query = """
    UNWIND $tool_ids AS tid
    OPTIONAL MATCH (t:Tool)
      WHERE t.tool_id = tid OR t.id = tid
    WITH coalesce(t.id, tid) AS tid, t
    OPTIONAL MATCH (t)-[fo:FAILED_ON]->(d:Dataset)
      WHERE ($dataset_id IS NULL OR d.id = $dataset_id OR d.dataset_id = $dataset_id)
        AND ($task_family IS NULL OR fo.task_family = $task_family)
    RETURN tid AS tool_id,
           coalesce(sum(fo.fail_count),0) AS fail_count,
           max(fo.last_seen) AS last_seen,
           collect(DISTINCT fo.error_category) AS error_categories
    """
    try:
        with driver.session() as session:
            res = session.run(
                query,
                tool_ids=tid_list,
                dataset_id=dataset_id,
                task_family=task_family,
            )
            out: dict[str, dict[str, Any]] = {}
            for row in res:
                tid = row.get("tool_id")
                if not tid:
                    continue
                out[str(tid)] = {
                    "fail_count": int(row.get("fail_count") or 0),
                    "last_seen": row.get("last_seen"),
                    "error_categories": [
                        ec
                        for ec in row.get("error_categories") or []
                        if isinstance(ec, str)
                    ],
                }
            return out
    except Neo4jError:
        return {}


def _load_catalog_alias_map() -> Dict[str, str]:
    """Load alias -> canonical dataset_id from configs/datasets catalogs (best effort)."""
    alias_map: Dict[str, str] = {}
    try:
        root = resolve_from_config("datasets")
        candidates = [
            root / "catalog.v1.jsonl",
            root / "catalog_manual.jsonl",
            root / "catalog_openneuro.jsonl",
        ]
        for path in candidates:
            if not path.exists():
                continue
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    dataset_id = obj.get("dataset_id") or obj.get("id")
                    if not dataset_id or not isinstance(dataset_id, str):
                        continue
                    aliases = obj.get("alias") or obj.get("aliases") or []
                    if isinstance(aliases, str):
                        aliases = [aliases]
                    for alias in aliases or []:
                        if not isinstance(alias, str):
                            continue
                        a = alias.strip().lower()
                        if a and a not in alias_map:
                            alias_map[a] = dataset_id
                    srepo = obj.get("source_repo_id")
                    if isinstance(srepo, str) and srepo.strip():
                        alias_map.setdefault(srepo.strip().lower(), dataset_id)
        return alias_map
    except Exception:
        return {}


def resolve_dataset_id(key: Optional[str]) -> Optional[str]:
    """
    Resolve a dataset key (id, dataset_id, openneuro_id, alias) to canonical Dataset.id.
    Uses KG first, then falls back to catalog alias map.
    """
    if not key:
        return None
    k = str(key).strip()
    driver = _get_driver()
    if driver is not None:
        query = """
        MATCH (d:Dataset)
        WHERE d.id = $k OR d.dataset_id = $k OR d.openneuro_id = $k OR $k IN coalesce(d.aliases, [])
        RETURN d.id AS id
        LIMIT 1
        """
        try:
            with driver.session() as session:
                row = session.run(query, k=k).single()
                if row:
                    rid = row.get("id")
                    if rid:
                        return str(rid)
        except Neo4jError:
            pass

    global _CATALOG_ALIAS_CACHE
    if _CATALOG_ALIAS_CACHE is None:
        _CATALOG_ALIAS_CACHE = _load_catalog_alias_map()
    if _CATALOG_ALIAS_CACHE:
        canon = _CATALOG_ALIAS_CACHE.get(k.lower())
        if canon:
            return canon
    return None


def _resolve_key_union(
    *,
    key: Optional[str],
    label: str,
    preferred_prop: str,
    fallback_prop: str,
) -> Optional[str]:
    """
    Resolve a key via UNION (preferred then fallback) to avoid OR scans.
    Returns the preferred property when present, otherwise fallback.
    """
    if not key:
        return None
    driver = _get_driver()
    if driver is None:
        return key

    query = f"""
    MATCH (n:{label} {{{preferred_prop}: $k}})
    RETURN coalesce(n.{preferred_prop}, n.{fallback_prop}) AS canon
    UNION
    MATCH (n:{label} {{{fallback_prop}: $k}})
    RETURN coalesce(n.{preferred_prop}, n.{fallback_prop}) AS canon
    LIMIT 1
    """
    try:
        with driver.session() as session:
            row = session.run(query, k=key).single()
            canon = row.get("canon") if row else None
            return canon or key
    except Neo4jError:
        return key
    except Exception:
        return key


def resolve_tool_key(key: Optional[str]) -> Optional[str]:
    """Resolve a tool identifier to canonical tool_id (fallback id)."""
    return _resolve_key_union(
        key=key,
        label="Tool",
        preferred_prop="tool_id",
        fallback_prop="id",
    )


def resolve_version_key(key: Optional[str]) -> Optional[str]:
    """Resolve a ToolVersion identifier to canonical version_id (fallback id)."""
    return _resolve_key_union(
        key=key,
        label="ToolVersion",
        preferred_prop="version_id",
        fallback_prop="id",
    )


__all__ = [
    "KnowledgePlanner",
    "PlanCache",
    "PlannerConfig",
    "get_failed_on_stats",
    "get_family_stats_for_operation",
    "get_preferred_families_for_pipeline",
    "get_tool_ids_for_constraints",
    "resolve_dataset_id",
    "resolve_tool_key",
    "resolve_version_key",
]
