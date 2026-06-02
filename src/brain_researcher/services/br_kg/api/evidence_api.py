"""Evidence retrieval endpoints for BR-KG (Neo4j-backed).

Provides low-latency evidence lookups for:
- Concept/term-centric evidence: publications, tasks, coordinates (peaks)
- Dataset + task context: contrasts attached to a dataset task
- Job peaks: peak coordinates for a result/job_id

Designed for the Next.js UI evidence panels. Uses the active Neo4j backend
via `get_db()` and returns JSON shaped for frontend consumption.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

from flask import Blueprint, jsonify, request

from brain_researcher.services.br_kg.db.bootstrap import get_db
from brain_researcher.services.br_kg.graph.neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)

evidence_bp = Blueprint("evidence", __name__, url_prefix="/api/kg")


def _ensure_neo4j() -> Neo4jGraphDB:
    """Return a Neo4jGraphDB or raise if fallback would be SQLite."""
    db = get_db()
    if not isinstance(db, Neo4jGraphDB):
        raise RuntimeError(
            "Evidence API requires Neo4j backend; SQLite mock not supported."
        )
    return db


def _serialize_node(node: Any) -> Dict[str, Any]:
    """Convert neo4j.Node to plain dict with labels."""
    if node is None:
        return {}
    data = dict(node)
    labels = list(node.labels) if hasattr(node, "labels") else []
    data["labels"] = labels
    data.setdefault(
        "id",
        getattr(node, "id", None) or (node.get("id") if hasattr(node, "get") else None),
    )
    data.setdefault("element_id", getattr(node, "element_id", None))
    return data


def _serialize_relationship(rel: Any) -> Dict[str, Any]:
    """Convert neo4j.Relationship to plain dict with type."""
    if rel is None:
        return {}
    try:
        props = dict(rel.items())
    except Exception:
        props = {}
    props["type"] = getattr(rel, "type", None) or getattr(rel, "rel_type", None)
    props.setdefault("element_id", getattr(rel, "element_id", None))
    return props


def _unique_by_id(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        node_id = item.get("id") or item.get("element_id")
        if node_id in seen:
            continue
        seen.add(node_id)
        out.append(item)
    return out


def _fetch_concept_evidence(
    db: Neo4jGraphDB,
    concept_id: str,
    pub_limit: int,
    coord_limit: int,
    task_limit: int,
) -> Dict[str, Any]:
    cypher = """
    MATCH (t:Term {id:$concept_id})
    OPTIONAL MATCH (t)<-[ht:HAS_TERM]-(p:Publication)
    WITH t, ht, p
    ORDER BY coalesce(p.year, 0) DESC, p.pmid ASC
    LIMIT $pub_limit
    OPTIONAL MATCH (p)-[hc:HAS_COORDINATE]->(c:Coordinate)
    OPTIONAL MATCH (p)-[rt:REPORTS_TASK]->(task:Task)
    RETURN t,
           collect(DISTINCT {pub:p, rel:ht}) AS pubs,
           collect(DISTINCT {coord:c, rel:hc})[0..$coord_limit] AS coords,
           collect(DISTINCT {task:task, rel:rt})[0..$task_limit] AS tasks
    """
    rows = db.execute_query(
        cypher,
        {
            "concept_id": concept_id,
            "pub_limit": pub_limit,
            "coord_limit": coord_limit,
            "task_limit": task_limit,
        },
    )
    if not rows:
        return {"concept_id": concept_id, "found": False}

    row = rows[0]
    term = _serialize_node(row.get("t"))
    publications = [
        {
            "node": _serialize_node(entry.get("pub")),
            "relationship": _serialize_relationship(entry.get("rel")),
        }
        for entry in row.get("pubs", [])
    ]
    coordinates = [
        {
            "node": _serialize_node(entry.get("coord")),
            "relationship": _serialize_relationship(entry.get("rel")),
        }
        for entry in row.get("coords", [])
        if entry.get("coord") is not None
    ]
    tasks = [
        {
            "node": _serialize_node(entry.get("task")),
            "relationship": _serialize_relationship(entry.get("rel")),
        }
        for entry in row.get("tasks", [])
        if entry.get("task") is not None
    ]

    return {
        "concept_id": concept_id,
        "found": True,
        "term": term,
        "counts": {
            "publications": len(publications),
            "coordinates": len(coordinates),
            "tasks": len(tasks),
        },
        "publications": publications,
        "coordinates": coordinates,
        "tasks": tasks,
    }


def _fetch_dataset_task_context(
    db: Neo4jGraphDB, dataset_id: str, task: str, limit: int
) -> Dict[str, Any]:
    cypher = """
    MATCH (d:Dataset {id:$dataset_id})-[:HAS_TASK]->(t:Task {name:$task})
    OPTIONAL MATCH (t)-[:HAS_CONTRAST]->(c:Contrast)
    RETURN d, t, collect(DISTINCT c)[0..$limit] AS contrasts
    """
    rows = db.execute_query(
        cypher,
        {"dataset_id": dataset_id, "task": task, "limit": limit},
    )
    if not rows:
        return {"dataset_id": dataset_id, "task": task, "found": False}

    row = rows[0]
    contrasts = [_serialize_node(c) for c in row.get("contrasts", []) if c]
    return {
        "dataset_id": dataset_id,
        "task": task,
        "found": True,
        "dataset": _serialize_node(row.get("d")),
        "task_node": _serialize_node(row.get("t")),
        "contrasts": contrasts,
        "counts": {"contrasts": len(contrasts)},
    }


def _fetch_job_peaks(db: Neo4jGraphDB, job_id: str, limit: int) -> Dict[str, Any]:
    cypher = """
    MATCH (r:Result {job_id:$job_id})-[:HAS_PEAK]->(p:Peak)
    RETURN r, collect(p)[0..$limit] AS peaks
    """
    rows = db.execute_query(cypher, {"job_id": job_id, "limit": limit})
    if not rows:
        return {"job_id": job_id, "found": False}
    row = rows[0]
    peaks = [_serialize_node(p) for p in row.get("peaks", []) if p]
    return {
        "job_id": job_id,
        "found": True,
        "result": _serialize_node(row.get("r")),
        "peaks": peaks,
        "counts": {"peaks": len(peaks)},
    }


@evidence_bp.route("/evidence", methods=["GET"])
def get_evidence() -> Any:
    """
    Evidence endpoint supporting three modes:
    - concept_id: returns publications, tasks, coordinates linked to a Term
    - dataset_id + task: returns contrasts for a dataset task
    - job_id: returns peaks linked to a Result
    """
    try:
        db = _ensure_neo4j()
        concept_id = request.args.get("concept_id")
        dataset_id = request.args.get("dataset_id")
        task = request.args.get("task")
        job_id = request.args.get("job_id")

        limit = int(request.args.get("limit", 50))
        coord_limit = int(request.args.get("coord_limit", 200))
        task_limit = int(request.args.get("task_limit", 50))

        if concept_id:
            return jsonify(
                _fetch_concept_evidence(
                    db,
                    concept_id=concept_id,
                    pub_limit=limit,
                    coord_limit=coord_limit,
                    task_limit=task_limit,
                )
            )
        if dataset_id and task:
            return jsonify(
                _fetch_dataset_task_context(
                    db,
                    dataset_id=dataset_id,
                    task=task,
                    limit=limit,
                )
            )
        if job_id:
            return jsonify(_fetch_job_peaks(db, job_id=job_id, limit=coord_limit))

        return (
            jsonify(
                {
                    "error": "Provide one of: concept_id; dataset_id+task; job_id.",
                    "example": {
                        "concept_id": "242ffa85576d7602b27fbf5b2869a144",
                        "dataset_id": "ds000001",
                        "task": "Episodic Memory Task",
                        "job_id": "job_123",
                    },
                }
            ),
            400,
        )
    except ValueError as exc:
        return jsonify({"error": f"Invalid parameter: {exc}"}), 400
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unhandled error in evidence endpoint")
        return jsonify({"error": str(exc)}), 500
