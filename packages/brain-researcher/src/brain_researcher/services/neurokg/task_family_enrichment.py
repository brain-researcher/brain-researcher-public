"""Repair helpers for adding Task -> TaskFamily links onto existing KG tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.services.neurokg.task_family_matcher import TaskFamilyMatcher

_DEFAULT_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[4]
    / "configs"
    / "taxonomy"
    / "exports"
    / "task_families_master.yaml"
)
_DEFAULT_ALIAS_EXTENSIONS_PATH = (
    Path(__file__).resolve().parents[4]
    / "configs"
    / "taxonomy"
    / "exports"
    / "task_family_alias_extensions.yaml"
)
_DEFAULT_ACCEPTED_METHODS = ("exact_alias", "aggressive_fuzzy_guarded")


@dataclass(frozen=True)
class TaskFamilyEnrichmentConfig:
    """Configuration for enriching existing Task nodes with family edges."""

    include_dataset_tasks: bool = True
    include_task_analysis_tasks: bool = True
    only_missing_family: bool = True
    limit: int | None = None
    taxonomy_path: str | None = None
    alias_extensions_path: str | None = None
    accepted_methods: tuple[str, ...] = _DEFAULT_ACCEPTED_METHODS


def enrich_existing_task_family_links(
    db: Any,
    *,
    config: TaskFamilyEnrichmentConfig = TaskFamilyEnrichmentConfig(),
) -> dict[str, Any]:
    """Attach TaskFamily nodes and BELONGS_TO_FAMILY edges to existing Task nodes."""

    matcher = TaskFamilyMatcher(
        taxonomy_path=Path(config.taxonomy_path or _DEFAULT_TAXONOMY_PATH),
        alias_extensions_path=(
            Path(config.alias_extensions_path)
            if config.alias_extensions_path
            else (
                _DEFAULT_ALIAS_EXTENSIONS_PATH
                if _DEFAULT_ALIAS_EXTENSIONS_PATH.exists()
                else None
            )
        ),
        enable_fuzzy=True,
    )
    candidate_tasks = _load_candidate_tasks(db, config=config)

    summary = {
        "candidate_task_count": len(candidate_tasks),
        "matched_task_count": 0,
        "unmatched_task_count": 0,
        "skipped_method_count": 0,
        "family_nodes_touched": 0,
        "task_nodes_updated": 0,
        "family_edges_written": 0,
        "accepted_methods": list(config.accepted_methods),
    }

    family_nodes_touched: set[str] = set()
    for task in candidate_tasks:
        task_id = str(task.get("node_id") or "").strip()
        props = dict(task.get("properties") or {})
        label = _best_task_label(props)
        if not task_id or not label:
            summary["unmatched_task_count"] += 1
            continue

        match_record, match_method, match_score = matcher.match(label)
        if match_record is None:
            summary["unmatched_task_count"] += 1
            continue
        if config.accepted_methods and match_method not in config.accepted_methods:
            summary["skipped_method_count"] += 1
            continue

        family_node_id = match_record.family_id
        family_nodes_touched.add(family_node_id)
        db.create_node(
            "TaskFamily",
            {
                "id": family_node_id,
                "name": match_record.family_label,
                "family_id": match_record.family_id,
                "family_label": match_record.family_label,
                "family_description": match_record.family_description,
                "source": "task_family_enrichment",
            },
            node_id=family_node_id,
        )

        merged_props = dict(props)
        merged_props["family_id"] = match_record.family_id
        merged_props["family_label"] = match_record.family_label
        merged_props["subfamily_id"] = match_record.subfamily_id
        merged_props["subfamily_label"] = match_record.subfamily_label
        merged_props["paradigm_name"] = match_record.paradigm_name
        merged_props["task_family_match_method"] = match_method
        merged_props["task_family_match_score"] = match_score
        merged_props["task_family_match_source"] = "task_family_enrichment"
        db.create_node(task.get("labels") or ["Task"], merged_props, node_id=task_id)

        db.create_relationship(
            task_id,
            family_node_id,
            "BELONGS_TO_FAMILY",
            {
                "source": "task_family_enrichment",
                "match_method": match_method,
                "match_score": match_score,
                "subfamily_id": match_record.subfamily_id,
                "subfamily_label": match_record.subfamily_label,
                "paradigm_name": match_record.paradigm_name,
            },
        )
        summary["matched_task_count"] += 1
        summary["task_nodes_updated"] += 1
        summary["family_edges_written"] += 1

    summary["family_nodes_touched"] = len(family_nodes_touched)
    return summary


def _best_task_label(properties: dict[str, Any]) -> str:
    for key in ("name", "canonical_name", "label", "task_name"):
        value = str(properties.get(key) or "").strip()
        if value:
            return value
    return str(properties.get("id") or "").strip()


def _load_candidate_tasks(
    db: Any,
    *,
    config: TaskFamilyEnrichmentConfig,
) -> list[dict[str, Any]]:
    if callable(getattr(type(db), "_run", None)):
        return _load_candidate_tasks_neo4j(db, config=config)
    return _load_candidate_tasks_generic(db, config=config)


def _load_candidate_tasks_neo4j(
    db: Any,
    *,
    config: TaskFamilyEnrichmentConfig,
) -> list[dict[str, Any]]:
    scope_terms: list[str] = []
    if config.include_dataset_tasks:
        scope_terms.append("EXISTS { MATCH (:Dataset)-[:HAS_TASK|USES_TASK]->(t) }")
    if config.include_task_analysis_tasks:
        scope_terms.append("EXISTS { MATCH (:TaskAnalysis)-[:MAPS_TO]->(t) }")

    where_terms = []
    if scope_terms:
        where_terms.append("(" + " OR ".join(scope_terms) + ")")
    if config.only_missing_family:
        where_terms.append("NOT EXISTS { MATCH (t)-[:BELONGS_TO_FAMILY]->(:TaskFamily) }")

    where_clause = " WHERE " + " AND ".join(where_terms) if where_terms else ""
    limit_clause = f" LIMIT {int(config.limit)}" if config.limit else ""
    query = (
        "MATCH (t:Task)"
        f"{where_clause} "
        "RETURN DISTINCT t.id AS node_id, labels(t) AS labels, properties(t) AS props "
        "ORDER BY node_id"
        f"{limit_clause}"
    )
    rows = db._run(query)  # noqa: SLF001 - deliberate fast path for Neo4j backend
    return [
        {
            "node_id": record["node_id"],
            "labels": list(record["labels"] or []),
            "properties": dict(record["props"] or {}),
        }
        for record in rows
    ]


def _load_candidate_tasks_generic(
    db: Any,
    *,
    config: TaskFamilyEnrichmentConfig,
) -> list[dict[str, Any]]:
    task_nodes = dict(db.find_nodes("Task"))
    candidate_ids: set[str] = set()

    if config.include_dataset_tasks:
        for rel_type in ("HAS_TASK", "USES_TASK"):
            for _, end_node, _ in db.find_relationships(rel_type=rel_type):
                if end_node in task_nodes:
                    candidate_ids.add(end_node)

    if config.include_task_analysis_tasks:
        for _, end_node, _ in db.find_relationships(rel_type="MAPS_TO"):
            if end_node in task_nodes:
                candidate_ids.add(end_node)

    out: list[dict[str, Any]] = []
    for node_id in sorted(candidate_ids):
        if config.only_missing_family and db.find_relationships(
            start_node=node_id,
            rel_type="BELONGS_TO_FAMILY",
        ):
            continue
        out.append(
            {
                "node_id": node_id,
                "labels": task_nodes[node_id].get("labels") or ["Task"],
                "properties": dict(task_nodes[node_id]),
            }
        )
        if config.limit and len(out) >= int(config.limit):
            break
    return out
