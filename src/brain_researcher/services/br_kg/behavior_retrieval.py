"""Behavior → fMRI retrieval helpers for the KG query service.

Carved out of ``br_kg/query_service.py`` (decomposition slice 2). Holds the
behavior-task seed resolution, dedup/ranking, generic-task detection, and the
behavior-retrieval pack/item builders used by
``query_service.behavior_to_fmri_retrieval``.

``query_service`` re-exports these names so existing ``query_service.<name>``
references keep resolving. The generic record/vector helpers (``_as_list`` /
``_coerce_float_vector`` / ``_cosine_similarity``) and ``get_default_db`` stay in
``query_service`` and are imported lazily inside the consumers, avoiding an
import cycle (verified both import orders).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from brain_researcher.services.br_kg.graph.neo4j_graph_database import Neo4jGraphDB

_GENERIC_BEHAVIOR_TASK_LABELS = {
    "choice task",
    "memory task",
}
_GENERIC_BEHAVIOR_TASK_RE = re.compile(r"^exp\d+[a-z]?$")


def _behavior_task_name(task: Mapping[str, Any]) -> str:
    props = dict(task.get("properties") or {})
    return str(
        props.get("name")
        or props.get("canonical_name")
        or props.get("task_paradigm_name")
        or task.get("id")
        or ""
    )


def _normalize_behavior_task_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _is_generic_behavior_task(task: Mapping[str, Any]) -> bool:
    name = _normalize_behavior_task_name(_behavior_task_name(task))
    if not name:
        return False
    if _GENERIC_BEHAVIOR_TASK_RE.fullmatch(name):
        return True
    return name in _GENERIC_BEHAVIOR_TASK_LABELS


def _behavior_seed_task_quality(task: Mapping[str, Any]) -> tuple[int, str]:
    props = dict(task.get("properties") or {})
    score = 0
    if props.get("canonical_task_id"):
        score += 50
    if props.get("ontology_match_method") == "psych101_curated_registry":
        score += 40
    if props.get("subfamily_id"):
        score += 20
    if props.get("family_id"):
        score += 10
    if props.get("canonical_name"):
        score += 5
    if props.get("task_paradigm_name"):
        score += 5
    if _is_generic_behavior_task(task):
        score -= 100
    return score, _normalize_behavior_task_name(_behavior_task_name(task))


def _dedupe_and_rank_behavior_seed_tasks(
    tasks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        candidate = dict(task)
        existing = by_id.get(task_id)
        if existing is None:
            by_id[task_id] = candidate
            continue
        if _behavior_seed_task_quality(candidate) > _behavior_seed_task_quality(
            existing
        ):
            by_id[task_id] = candidate

    ranked = list(by_id.values())
    non_generic = [task for task in ranked if not _is_generic_behavior_task(task)]
    if non_generic:
        ranked = non_generic

    ranked.sort(
        key=lambda task: (
            -_behavior_seed_task_quality(task)[0],
            _behavior_seed_task_quality(task)[1],
            str(task.get("id") or ""),
        )
    )
    return ranked[:4]


def _resolve_seed_tasks_for_behavior(
    seed: Mapping[str, Any],
    *,
    db: Neo4jGraphDB | None = None,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _as_list, get_default_db

    labels = {str(label) for label in (seed.get("labels") or [])}
    if "Task" in labels:
        return [dict(seed)]

    if not {"Psych101Experiment", "Experiment"} & labels:
        return []

    client = db or get_default_db()
    rows = _as_list(
        client.execute_query(
            """
            MATCH (seed {id:$seed_id})-[:USES_TASK]->(t:Task)
            OPTIONAL MATCH (t)-[:BELONGS_TO_FAMILY]->(tf:TaskFamily)
            RETURN {
              id: coalesce(t.id, elementId(t)),
              labels: labels(t),
              properties: t{.*,
                family_id: coalesce(tf.id, t.family_id),
                family_name: coalesce(tf.name, t.family_label)
              }
            } AS task
            ORDER BY coalesce(t.name, t.canonical_name, t.id)
            """,
            {"seed_id": seed.get("id")},
        )
    )
    tasks = [dict(row["task"]) for row in rows if row.get("task")]
    return _dedupe_and_rank_behavior_seed_tasks(tasks)


def _behavior_neighbor_tasks(
    source_task: Mapping[str, Any],
    *,
    max_neighbors: int,
    min_similarity: float,
    db: Neo4jGraphDB | None = None,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _as_list,
        _coerce_float_vector,
        _cosine_similarity,
        get_default_db,
    )

    source_props = dict(source_task.get("properties") or {})
    source_vec = _coerce_float_vector(source_props.get("embedding_centaur_behavior_v1"))
    if not source_vec or max_neighbors <= 0:
        return []

    client = db or get_default_db()
    source_family_id = _normalize_behavior_task_name(source_props.get("family_id"))
    rows = _as_list(
        client.execute_query(
            """
            MATCH (t:Task)
            OPTIONAL MATCH (t)-[:BELONGS_TO_FAMILY]->(tf:TaskFamily)
            WHERE coalesce(t.id, '') <> $task_id
              AND t.embedding_centaur_behavior_v1 IS NOT NULL
              AND coalesce(t.id, '') STARTS WITH 'psych101:task:'
            RETURN {
              id: coalesce(t.id, elementId(t)),
              labels: labels(t),
              properties: t{.*,
                family_id: coalesce(tf.id, t.family_id),
                family_name: coalesce(tf.name, t.family_label)
              }
            } AS task
            """,
            {"task_id": source_task.get("id")},
        )
    )

    neighbors: list[dict[str, Any]] = []
    for row in rows:
        task = row.get("task")
        if not isinstance(task, dict):
            continue
        if _is_generic_behavior_task(task):
            continue
        similarity = _cosine_similarity(
            source_vec,
            _coerce_float_vector(
                (task.get("properties") or {}).get("embedding_centaur_behavior_v1")
            ),
        )
        if similarity is None or similarity < float(min_similarity):
            continue
        task_copy = dict(task)
        task_props = dict(task_copy.get("properties") or {})
        task_props["behavior_similarity"] = round(float(similarity), 6)
        task_props["behavior_family_match"] = bool(
            source_family_id
            and _normalize_behavior_task_name(task_props.get("family_id"))
            == source_family_id
        )
        task_copy["properties"] = task_props
        neighbors.append(task_copy)

    neighbors.sort(
        key=lambda item: (
            bool((item.get("properties") or {}).get("behavior_family_match")),
            float((item.get("properties") or {}).get("behavior_similarity") or 0.0),
        ),
        reverse=True,
    )
    return neighbors[: int(max_neighbors)]


def _classify_behavior_retrieval_method(
    *,
    path_nodes: Sequence[Mapping[str, Any]],
    path_relationships: Sequence[Mapping[str, Any]],
    behavior_similarity: float | None,
) -> str:
    rel_types = {
        str(rel.get("type") or "")
        for rel in path_relationships
        if isinstance(rel, Mapping)
    }
    task_count = sum(
        1
        for node in path_nodes
        if "Task" in {str(label) for label in (node.get("labels") or [])}
    )

    if "BELONGS_TO_FAMILY" in rel_types:
        base = "family_bridge"
    elif task_count >= 2:
        base = "canonical_bridge"
    else:
        base = "direct_task"

    if behavior_similarity is not None:
        return f"behavior_similar_{base}"
    return base


def _build_behavior_retrieval_item(
    *,
    path: Mapping[str, Any],
    node_lookup: Mapping[str, Mapping[str, Any]],
    outgoing_edges: Mapping[str, list[dict[str, Any]]],
    incoming_edges: Mapping[str, list[dict[str, Any]]],
    source_task: Mapping[str, Any],
    behavior_similarity: float | None,
) -> dict[str, Any] | None:
    map_id = path.get("map_id")
    if not isinstance(map_id, str) or not map_id:
        return None

    path_nodes = [
        node for node in (path.get("nodes") or []) if isinstance(node, Mapping)
    ]
    path_relationships = [
        rel for rel in (path.get("relationships") or []) if isinstance(rel, Mapping)
    ]
    method = _classify_behavior_retrieval_method(
        path_nodes=path_nodes,
        path_relationships=path_relationships,
        behavior_similarity=behavior_similarity,
    )

    task_analysis_ids = sorted(
        {
            str(edge.get("end"))
            for edge in outgoing_edges.get(map_id, [])
            if edge.get("type") == "GENERATED_FROM" and edge.get("end")
        }
    )
    contrast_ids = sorted(
        {
            str(edge.get("end"))
            for edge in outgoing_edges.get(map_id, [])
            if edge.get("type") == "DERIVED_FROM" and edge.get("end")
        }
    )
    matched_task_ids = sorted(
        {
            str(edge.get("end"))
            for ta_id in task_analysis_ids
            for edge in outgoing_edges.get(ta_id, [])
            if edge.get("type") == "MAPS_TO" and edge.get("end")
        }
    )
    dataset_ids = sorted(
        {
            str(edge.get("start"))
            for contrast_id in contrast_ids
            for edge in incoming_edges.get(contrast_id, [])
            if edge.get("type") == "HAS_CONTRAST" and edge.get("start")
        }
    )
    brain_regions = []
    for edge in outgoing_edges.get(map_id, []):
        if edge.get("type") != "IN_REGION" or not edge.get("end"):
            continue
        region_id = str(edge["end"])
        region_node = node_lookup.get(region_id) or {}
        region_props = dict(region_node.get("properties") or {})
        brain_regions.append(
            {
                "brain_region_id": region_id,
                "name": region_props.get("name") or region_props.get("label"),
                "weight": edge.get("properties", {}).get("weight"),
            }
        )
    brain_regions.sort(
        key=lambda item: abs(float(item.get("weight") or 0.0)),
        reverse=True,
    )

    matched_task_id = matched_task_ids[0] if matched_task_ids else None
    matched_task_node = node_lookup.get(matched_task_id or "") or {}
    matched_task_props = dict(matched_task_node.get("properties") or {})
    family_id = None
    family_name = None
    if matched_task_id:
        family_edges = [
            edge
            for edge in outgoing_edges.get(matched_task_id, [])
            if edge.get("type") == "BELONGS_TO_FAMILY" and edge.get("end")
        ]
        if family_edges:
            family_id = str(family_edges[0]["end"])
            family_node = node_lookup.get(family_id) or {}
            family_name = (family_node.get("properties") or {}).get("name")
    if not family_id:
        family_id = matched_task_props.get("family_id") or (
            source_task.get("properties") or {}
        ).get("family_id")
        family_name = matched_task_props.get("family_name") or (
            source_task.get("properties") or {}
        ).get("family_name")

    source_family_id = _normalize_behavior_task_name(
        (source_task.get("properties") or {}).get("family_id")
    )
    matched_family_id = _normalize_behavior_task_name(family_id)
    if behavior_similarity is not None and source_family_id and matched_family_id:
        if source_family_id != matched_family_id:
            return None

    base_scores = {
        "direct_task": 1.0,
        "canonical_bridge": 0.94,
        "family_bridge": 0.88,
        "behavior_similar_direct_task": 0.58,
        "behavior_similar_canonical_bridge": 0.48,
        "behavior_similar_family_bridge": 0.4,
    }
    base_score = float(base_scores.get(method, 0.5))
    if behavior_similarity is not None:
        base_score *= max(0.0, min(1.0, float(behavior_similarity)))

    return {
        "item_id": task_analysis_ids[0] if task_analysis_ids else map_id,
        "task_analysis_id": task_analysis_ids[0] if task_analysis_ids else None,
        "matched_task_id": matched_task_id,
        "matched_task_name": matched_task_props.get("name")
        or matched_task_props.get("canonical_name"),
        "family_id": family_id,
        "family_name": family_name,
        "contrast_ids": contrast_ids,
        "dataset_ids": dataset_ids,
        "stats_map_ids": [map_id],
        "brain_regions": brain_regions,
        "retrieval_methods": [method],
        "source_task_ids": [str(source_task.get("id"))],
        "source_task_names": [
            str(
                (source_task.get("properties") or {}).get("name")
                or (source_task.get("properties") or {}).get("canonical_name")
                or source_task.get("id")
            )
        ],
        "behavior_similarity_max": behavior_similarity,
        "score": round(base_score, 6),
    }


def _merge_behavior_retrieval_item(
    existing: dict[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    for key in ("contrast_ids", "dataset_ids", "stats_map_ids", "source_task_ids"):
        existing[key] = sorted(
            {
                str(value)
                for value in (existing.get(key) or [])
                + [str(value) for value in (incoming.get(key) or [])]
                if value
            }
        )

    existing["source_task_names"] = sorted(
        {
            str(value)
            for value in (existing.get("source_task_names") or [])
            + [str(value) for value in (incoming.get("source_task_names") or [])]
            if value
        }
    )
    existing["retrieval_methods"] = sorted(
        {
            str(value)
            for value in (existing.get("retrieval_methods") or [])
            + [str(value) for value in (incoming.get("retrieval_methods") or [])]
            if value
        }
    )
    existing["score"] = max(
        float(existing.get("score") or 0.0),
        float(incoming.get("score") or 0.0),
    )

    incoming_similarity = incoming.get("behavior_similarity_max")
    existing_similarity = existing.get("behavior_similarity_max")
    if incoming_similarity is not None:
        if existing_similarity is None:
            existing["behavior_similarity_max"] = incoming_similarity
        else:
            existing["behavior_similarity_max"] = max(
                float(existing_similarity),
                float(incoming_similarity),
            )

    seen_regions = {
        str(region.get("brain_region_id"))
        for region in existing.get("brain_regions") or []
        if isinstance(region, Mapping)
    }
    for region in incoming.get("brain_regions") or []:
        if not isinstance(region, Mapping):
            continue
        region_id = str(region.get("brain_region_id") or "")
        if not region_id or region_id in seen_regions:
            continue
        seen_regions.add(region_id)
        existing.setdefault("brain_regions", []).append(dict(region))
    existing["brain_regions"] = sorted(
        existing.get("brain_regions") or [],
        key=lambda item: abs(float(item.get("weight") or 0.0)),
        reverse=True,
    )

    for key in (
        "task_analysis_id",
        "matched_task_id",
        "matched_task_name",
        "family_id",
        "family_name",
    ):
        if not existing.get(key) and incoming.get(key):
            existing[key] = incoming.get(key)
    return existing


def _summarize_behavior_pack_into_items(
    pack: Mapping[str, Any],
    *,
    source_task: Mapping[str, Any],
    behavior_similarity: float | None,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import json_safe_value

    graph = pack.get("graph") or {}
    node_lookup: dict[str, dict[str, Any]] = {}
    outgoing_edges: dict[str, list[dict[str, Any]]] = {}
    incoming_edges: dict[str, list[dict[str, Any]]] = {}

    for node in graph.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            node_payload = json_safe_value(dict(node))
            if isinstance(node_payload, dict):
                node_lookup[node_id] = node_payload

    for edge in graph.get("edges") or []:
        if not isinstance(edge, Mapping):
            continue
        start = edge.get("start")
        end = edge.get("end")
        if (
            not isinstance(start, str)
            or not isinstance(end, str)
            or not start
            or not end
        ):
            continue
        edge_copy = {
            "type": edge.get("type"),
            "start": start,
            "end": end,
            "properties": json_safe_value(dict(edge.get("properties") or {})),
        }
        outgoing_edges.setdefault(start, []).append(edge_copy)
        incoming_edges.setdefault(end, []).append(edge_copy)

    items: list[dict[str, Any]] = []
    for path in pack.get("paths") or []:
        if not isinstance(path, Mapping):
            continue
        item = _build_behavior_retrieval_item(
            path=path,
            node_lookup=node_lookup,
            outgoing_edges=outgoing_edges,
            incoming_edges=incoming_edges,
            source_task=source_task,
            behavior_similarity=behavior_similarity,
        )
        if item is not None:
            items.append(item)
    return items
