"""Evidence pack retrieval for BR-KG.

Given a seed entity (Task/Concept/Contrast/ONVOC/Dataset), return:
- provenance-rich paths linking the seed to concrete evidence (StatsMap/Study/etc.)
- a compact subgraph (nodes + edges) suitable for downstream UI/agent use

This is intentionally template-based (not arbitrary Cypher execution) to keep the
API stable and auditable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from brain_researcher.services.br_kg.graph.neo4j_graph_database import Neo4jGraphDB


@dataclass(frozen=True)
class EvidencePackConfig:
    max_maps: int = 20
    max_paths: int = 20
    max_regions_per_map: int = 8
    max_similar_tasks: int = 10


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def resolve_seed(
    db: Neo4jGraphDB,
    *,
    seed_id: str | None = None,
    label: str | None = None,
    name: str | None = None,
) -> dict[str, Any] | None:
    if seed_id:
        rows = db.execute_query(
            """
            MATCH (n {id:$id})
            RETURN {
              id: coalesce(n.id, elementId(n)),
              labels: labels(n),
              properties: n{.*}
            } AS seed
            LIMIT 1
            """,
            {"id": seed_id},
        )
        return rows[0]["seed"] if rows else None

    if label and name:
        allowed_labels = {
            "Concept",
            "Task",
            "Contrast",
            "Dataset",
            "OnvocClass",
            "OntologyConcept",
            "TaskFamily",
            "Study",
            "Publication",
            "StatsMap",
            "BrainRegion",
        }
        if label not in allowed_labels:
            raise ValueError(f"Unsupported label: {label}")

        rows = db.execute_query(
            f"""
            MATCH (n:`{label}`)
            WHERE toLower(coalesce(n.name, n.title, '')) = toLower($name)
            RETURN {{
              id: coalesce(n.id, elementId(n)),
              labels: labels(n),
              properties: n{{.*}}
            }} AS seed
            LIMIT 1
            """,
            {"name": name},
        )
        return rows[0]["seed"] if rows else None

    return None


def _merge_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id:
        return
    existing = nodes.get(node_id)
    if existing is None:
        nodes[node_id] = node
        return

    merged = dict(existing)
    merged_labels = set(existing.get("labels") or []) | set(node.get("labels") or [])
    merged["labels"] = sorted(
        str(label_value) for label_value in merged_labels if label_value
    )
    props = dict(existing.get("properties") or {})
    props.update(dict(node.get("properties") or {}))
    merged["properties"] = props
    nodes[node_id] = merged


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    start = str(edge.get("start") or "")
    end = str(edge.get("end") or "")
    rel_type = str(edge.get("type") or "")
    method = str((edge.get("properties") or {}).get("method") or "")
    return start, end, rel_type, method


def _merge_edge(
    edges: dict[tuple[str, str, str, str], dict[str, Any]], edge: dict[str, Any]
) -> None:
    key = _edge_key(edge)
    if not all(key[:3]):
        return
    edges.setdefault(key, edge)


def _coerce_rel_type(rel: Any) -> str:
    if isinstance(rel, tuple) and len(rel) == 3:
        return str(rel[1] or "")
    return str(getattr(rel, "type", "") or "")


def _coerce_rel_props(rel: Any) -> dict[str, Any]:
    if isinstance(rel, tuple) and len(rel) == 3:
        return {}
    if isinstance(rel, dict):
        return dict(rel)
    try:
        return dict(rel)
    except Exception:
        return {}


def _find_paths_for_seed(
    db: Neo4jGraphDB,
    seed: dict[str, Any],
    cfg: EvidencePackConfig,
) -> list[dict[str, Any]]:
    seed_id = seed["id"]
    labels = set(seed.get("labels") or [])

    # ONVOC / ontology concept seed: maps point to it via IN_ONVOC
    if seed_id.startswith("ONVOC_") or {"OnvocClass", "OntologyConcept"} & labels:
        rows = db.execute_query(
            """
            MATCH (seed {id:$seed_id})
            MATCH p=(m:StatsMap)-[:IN_ONVOC]->(seed)
            RETURN
              m.id AS map_id,
              [n IN nodes(p) |
                {id: coalesce(n.id, elementId(n)), labels: labels(n), properties: n{.*}}
              ] AS nodes,
              [r IN relationships(p) |
                {type: type(r),
                 start: coalesce(startNode(r).id, elementId(startNode(r))),
                 end: coalesce(endNode(r).id, elementId(endNode(r))),
                 properties: r{.*}}
              ] AS relationships
            ORDER BY coalesce(m.primary_onvoc_confidence, 0.0) DESC
            LIMIT $limit
            """,
            {"seed_id": seed_id, "limit": int(cfg.max_paths)},
        )
        return rows

    # Contrast seed: maps derived from it
    if "Contrast" in labels:
        rows = db.execute_query(
            """
            MATCH (seed:Contrast {id:$seed_id})
            MATCH p=(m:StatsMap)-[:DERIVED_FROM]->(seed)
            RETURN
              m.id AS map_id,
              [n IN nodes(p) |
                {id: coalesce(n.id, elementId(n)), labels: labels(n), properties: n{.*}}
              ] AS nodes,
              [r IN relationships(p) |
                {type: type(r),
                 start: coalesce(startNode(r).id, elementId(startNode(r))),
                 end: coalesce(endNode(r).id, elementId(endNode(r))),
                 properties: r{.*}}
              ] AS relationships
            LIMIT $limit
            """,
            {"seed_id": seed_id, "limit": int(cfg.max_paths)},
        )
        return rows

    # Dataset seed: map paths through its contrasts
    if "Dataset" in labels:
        rows = db.execute_query(
            """
            MATCH (seed:Dataset {id:$seed_id})
            MATCH p=(seed)-[:HAS_CONTRAST]->(c:Contrast)<-[:DERIVED_FROM]-(m:StatsMap)
            WHERE coalesce(m.dataset_id, '') = coalesce(seed.dataset_id, '')
            RETURN
              m.id AS map_id,
              [n IN nodes(p) |
                {id: coalesce(n.id, elementId(n)), labels: labels(n), properties: n{.*}}
              ] AS nodes,
              [r IN relationships(p) |
                {type: type(r),
                 start: coalesce(startNode(r).id, elementId(startNode(r))),
                 end: coalesce(endNode(r).id, elementId(endNode(r))),
                 properties: r{.*}}
              ] AS relationships
            LIMIT $limit
            """,
            {"seed_id": seed_id, "limit": int(cfg.max_paths)},
        )
        return rows

    # Task seed: connect via TaskAnalysis -> StatsMap, including family bridges.
    if "Task" in labels:
        rows = db.execute_query(
            """
            MATCH (seed:Task {id:$seed_id})
            CALL {
              WITH seed
              MATCH p=(seed)<-[:MAPS_TO]-(ta:TaskAnalysis)<-[:GENERATED_FROM]-(m:StatsMap)
              RETURN m.id AS map_id, nodes(p) AS _nodes, relationships(p) AS _rels
              UNION
              WITH seed
              MATCH p=(seed)-[:MAPS_TO]-(t:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)<-[:GENERATED_FROM]-(m:StatsMap)
              RETURN m.id AS map_id, nodes(p) AS _nodes, relationships(p) AS _rels
              UNION
              WITH seed
              MATCH p=(seed)-[:BELONGS_TO_FAMILY]->(:TaskFamily)<-[:BELONGS_TO_FAMILY]-(t:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)<-[:GENERATED_FROM]-(m:StatsMap)
              RETURN m.id AS map_id, nodes(p) AS _nodes, relationships(p) AS _rels
              UNION
              WITH seed
              MATCH p=(seed)-[:MAPS_TO]-(nt:Task)-[:BELONGS_TO_FAMILY]->(:TaskFamily)<-[:BELONGS_TO_FAMILY]-(t:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)<-[:GENERATED_FROM]-(m:StatsMap)
              RETURN m.id AS map_id, nodes(p) AS _nodes, relationships(p) AS _rels
            }
            RETURN
              map_id,
              [n IN _nodes |
                {id: coalesce(n.id, elementId(n)), labels: labels(n), properties: n{.*}}
              ] AS nodes,
              [r IN _rels |
                {type: type(r),
                 start: coalesce(startNode(r).id, elementId(startNode(r))),
                 end: coalesce(endNode(r).id, elementId(endNode(r))),
                 properties: r{.*}}
              ] AS relationships
            LIMIT $limit
            """,
            {"seed_id": seed_id, "limit": int(cfg.max_paths)},
        )
        return rows

    # Concept seed: connect to tasks, then to TaskAnalysis->StatsMap
    if "Concept" in labels:
        rows = db.execute_query(
            """
            MATCH (seed:Concept {id:$seed_id})
            CALL {
              WITH seed
              MATCH p=(seed)-[:MEASUREDBY|MEASURED_BY|MEASURES]->(t:Task)
                        -[:MAPS_TO]-(nt:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)<-[:GENERATED_FROM]-(m:StatsMap)
              RETURN m.id AS map_id, nodes(p) AS _nodes, relationships(p) AS _rels
              UNION
              WITH seed
              MATCH p=(seed)-[:MAPS_TO]->(o:OnvocClass)<-[:IN_ONVOC]-(m:StatsMap)
              RETURN m.id AS map_id, nodes(p) AS _nodes, relationships(p) AS _rels
            }
            RETURN
              map_id,
              [n IN _nodes |
                {id: coalesce(n.id, elementId(n)), labels: labels(n), properties: n{.*}}
              ] AS nodes,
              [r IN _rels |
                {type: type(r),
                 start: coalesce(startNode(r).id, elementId(startNode(r))),
                 end: coalesce(endNode(r).id, elementId(endNode(r))),
                 properties: r{.*}}
              ] AS relationships
            LIMIT $limit
            """,
            {"seed_id": seed_id, "limit": int(cfg.max_paths)},
        )
        return rows

    return []


def build_evidence_pack(
    db: Neo4jGraphDB,
    *,
    seed_id: str | None = None,
    label: str | None = None,
    name: str | None = None,
    cfg: EvidencePackConfig = EvidencePackConfig(),
) -> dict[str, Any]:
    seed = resolve_seed(db, seed_id=seed_id, label=label, name=name)
    if seed is None:
        return {"error": "seed_not_found"}

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    _merge_node(nodes, seed)

    paths = _find_paths_for_seed(db, seed, cfg)
    map_ids: list[str] = []
    for row in paths:
        map_id = row.get("map_id")
        if isinstance(map_id, str) and map_id:
            map_ids.append(map_id)
        for n in row.get("nodes") or []:
            _merge_node(nodes, n)
        for e in row.get("relationships") or []:
            _merge_edge(edges, e)

    map_ids = list(dict.fromkeys(map_ids))

    # Expand map evidence: attach contrast/dataset/taskanalysis/task + top Yeo17 regions.
    if map_ids:
        expanded = db.execute_query(
            """
            UNWIND $map_ids AS map_id
            MATCH (m:StatsMap {id: map_id})
            OPTIONAL MATCH (m)-[df:DERIVED_FROM]->(c:Contrast)
            OPTIONAL MATCH (m)-[gf:GENERATED_FROM]->(ta:TaskAnalysis)
            OPTIONAL MATCH (ta)-[mt:MAPS_TO]->(t:Task)
            OPTIONAL MATCH (m)-[io:IN_ONVOC]->(o)
            RETURN map_id AS map_id, m, df, c, gf, ta, mt, t, io, o
            """,
            {"map_ids": map_ids},
        )

        contrast_ids: list[str] = []
        for row in expanded:
            m = row.get("m")
            if m:
                _merge_node(
                    nodes,
                    {"id": m.get("id"), "labels": ["StatsMap"], "properties": dict(m)},
                )

            def _add_rel(rel, start_node, end_node):
                if not rel or not start_node or not end_node:
                    return
                rel_type = _coerce_rel_type(rel)
                if not rel_type:
                    return
                _merge_edge(
                    edges,
                    {
                        "type": rel_type,
                        "start": start_node.get("id"),
                        "end": end_node.get("id"),
                        "properties": _coerce_rel_props(rel),
                    },
                )

            c = row.get("c")
            if c:
                contrast_ids.append(c.get("id"))
                _merge_node(
                    nodes,
                    {"id": c.get("id"), "labels": ["Contrast"], "properties": dict(c)},
                )
                _add_rel(row.get("df"), row.get("m"), c)

            ta = row.get("ta")
            if ta:
                _merge_node(
                    nodes,
                    {
                        "id": ta.get("id"),
                        "labels": ["TaskAnalysis"],
                        "properties": dict(ta),
                    },
                )
                _add_rel(row.get("gf"), row.get("m"), ta)

            t = row.get("t")
            if t:
                _merge_node(
                    nodes,
                    {"id": t.get("id"), "labels": ["Task"], "properties": dict(t)},
                )
                _add_rel(row.get("mt"), ta, t)

            o = row.get("o")
            if o:
                _merge_node(
                    nodes,
                    {
                        "id": o.get("id"),
                        "labels": list(getattr(o, "labels", [])) or ["OnvocClass"],
                        "properties": dict(o),
                    },
                )
                _add_rel(row.get("io"), row.get("m"), o)

        contrast_ids = list(
            dict.fromkeys([c for c in contrast_ids if isinstance(c, str)])
        )
        if contrast_ids:
            ds_rows = db.execute_query(
                """
                UNWIND $contrast_ids AS cid
                MATCH (d:Dataset)-[hc:HAS_CONTRAST]->(c:Contrast {id: cid})
                RETURN d, hc, c
                """,
                {"contrast_ids": contrast_ids},
            )
            for row in ds_rows:
                d = row.get("d")
                c = row.get("c")
                hc = row.get("hc")
                if d:
                    _merge_node(
                        nodes,
                        {
                            "id": d.get("id"),
                            "labels": ["Dataset"],
                            "properties": dict(d),
                        },
                    )
                if c:
                    _merge_node(
                        nodes,
                        {
                            "id": c.get("id"),
                            "labels": ["Contrast"],
                            "properties": dict(c),
                        },
                    )
                if hc and d and c:
                    _merge_edge(
                        edges,
                        {
                            "type": hc.type,
                            "start": d.get("id"),
                            "end": c.get("id"),
                            "properties": dict(hc),
                        },
                    )

        for map_id in map_ids:
            region_rows = db.execute_query(
                """
                MATCH (m:StatsMap {id:$map_id})-[r:IN_REGION]->(br:BrainRegion)
                WHERE br.atlas = 'Yeo17'
                RETURN br, r
                ORDER BY abs(coalesce(r.weight, 0.0)) DESC
                LIMIT $limit
                """,
                {"map_id": map_id, "limit": int(cfg.max_regions_per_map)},
            )
            for row in region_rows:
                br = row.get("br")
                r = row.get("r")
                if br:
                    _merge_node(
                        nodes,
                        {
                            "id": br.get("id"),
                            "labels": ["BrainRegion"],
                            "properties": dict(br),
                        },
                    )
                if r and br:
                    _merge_edge(
                        edges,
                        {
                            "type": r.type,
                            "start": map_id,
                            "end": br.get("id"),
                            "properties": dict(r),
                        },
                    )

    if "Task" in set(seed.get("labels") or []) and int(cfg.max_similar_tasks) > 0:
        sim = db.execute_query(
            """
            MATCH (seed:Task {id:$seed_id})-[r:SIMILAR_TO]->(t:Task)
            RETURN t, r
            ORDER BY coalesce(r.score, r.confidence, 0.0) DESC
            LIMIT $limit
            """,
            {"seed_id": seed["id"], "limit": int(cfg.max_similar_tasks)},
        )
        for row in sim:
            t = row.get("t")
            r = row.get("r")
            if t:
                _merge_node(
                    nodes,
                    {"id": t.get("id"), "labels": ["Task"], "properties": dict(t)},
                )
            if r and t:
                _merge_edge(
                    edges,
                    {
                        "type": r.type,
                        "start": seed["id"],
                        "end": t.get("id"),
                        "properties": dict(r),
                    },
                )

    return {
        "seed": seed,
        "paths": [
            {
                "map_id": row.get("map_id"),
                "nodes": row.get("nodes") or [],
                "relationships": row.get("relationships") or [],
            }
            for row in paths
        ],
        "graph": {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
        },
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "map_count": len(map_ids),
        },
    }
