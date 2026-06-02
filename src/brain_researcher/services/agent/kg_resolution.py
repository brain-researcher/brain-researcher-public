"""Lightweight KG-aware resolution helpers (Track B glue).

This module wires together three things the orchestrator needs before planning:

- Query understanding entities -> KG node IDs
- Dataset references -> canonical IDs + local mount paths + KG nodes
- Derivative discovery -> quick reuse hints for pipelines

It is intentionally dependency-light and safe to import from agents, planner, or
other service code. Dataset resource discovery lives in services/shared so lower
layers such as BR-KG can use it without importing the agent layer.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from brain_researcher.services.agent.query_understanding import EntityType, ParsedQuery
from brain_researcher.services.shared.dataset_resource_resolution import (
    DEFAULT_MANUAL_CATALOG,
    _path_from_mounts,
    collect_dataset_resources,
    find_existing_derivatives,
    resolve_dataset_reference,
)
from brain_researcher.services.shared.r2brkg_query_understanding_types import (
    DatasetResolution,
    DatasetResources,
    DerivativeHit,
    KGNodeRef,
    QueryUnderstandingResult,
)

logger = logging.getLogger(__name__)

# Defaults for KG-assisted candidate discovery
DEFAULT_KG_DATASET_LIMIT = 5

# ----------------------------
# KG linking
# ----------------------------


def _default_kg_linker(text: str, entity_type: EntityType) -> KGNodeRef | None:
    """Very lightweight linker when no KG client is provided.

    It generates deterministic IDs so downstream components can still reason
    about nodes even without a live BR-KG backend.
    """

    slug = re.sub(r"\s+", "_", text.strip().lower())
    if not slug:
        return None
    return KGNodeRef(
        id=f"nkglite:{entity_type.value}:{slug}",
        label=text,
        type=entity_type.value,
        score=0.5,
    )


def _service_kg_linker(text: str, entity_type: EntityType) -> KGNodeRef | None:
    """Link entities via the BR-KG query service (preferred).

    Falls back to the deterministic stub if BR-KG is unreachable.
    """

    try:
        from brain_researcher.services.br_kg import query_service

        type_map = {
            EntityType.BRAIN_REGION: ["BrainRegion", "Region", "Parcel"],
            EntityType.DATASET: ["Dataset"],
            EntityType.TASK: ["Task", "Concept", "CognitiveConcept"],
            EntityType.CONTRAST: ["Concept", "CognitiveConcept", "Term"],
            EntityType.STATISTICAL_METHOD: ["Concept", "CognitiveConcept", "Term"],
            EntityType.PREPROCESSING_STEP: ["Concept", "CognitiveConcept", "Term"],
            EntityType.MODALITY: ["Concept", "CognitiveConcept", "Term"],
            EntityType.SUBJECT_GROUP: ["Concept", "CognitiveConcept", "Term"],
            EntityType.METRIC: ["Concept", "CognitiveConcept", "Term"],
        }
        node_types = type_map.get(entity_type)
        matches = query_service.search_nodes(text, node_types=node_types, limit=1)
        if matches:
            m = matches[0]
            return KGNodeRef(id=m.kg_id, label=m.label, type=m.node_type, score=m.score)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("BR-KG service linker failed, falling back to stub: %s", exc)
    return _default_kg_linker(text, entity_type)


def link_entities_to_kg(
    parsed_query: ParsedQuery,
    kg_linker: Callable[[str, EntityType], KGNodeRef | None] | None = None,
) -> list[KGNodeRef]:
    """Map extracted entities to KG nodes.

    Args:
        parsed_query: ParsedQuery produced by the agent parser.
        kg_linker: Optional callable hitting BR-KG; falls back to stub above.

    Returns:
        List of KGNodeRef objects (duplicates removed by id).
    """

    linker = kg_linker or _service_kg_linker
    nodes: dict[str, KGNodeRef] = {}

    for ent in parsed_query.entities:
        if ent.entity_type == EntityType.COORDINATE:
            continue
        node = linker(ent.normalized_form or ent.text, ent.entity_type)
        if node:
            nodes.setdefault(node.id, node)

    return list(nodes.values())


# ----------------------------
# Convenience: bundle everything
# ----------------------------


def build_query_understanding_result(
    parsed_query: ParsedQuery,
    kg_linker: Callable[[str, EntityType], KGNodeRef | None] | None = None,
) -> QueryUnderstandingResult:
    """Construct a standardized QueryUnderstandingResult with KG + datasets."""

    kg_nodes = link_entities_to_kg(parsed_query, kg_linker)
    candidate_datasets = _collect_candidate_datasets(parsed_query, kg_nodes)

    # resolve any dataset-like entities
    resolved: list[DatasetResolution] = []
    for ent in parsed_query.entities:
        if ent.entity_type != EntityType.DATASET:
            continue
        ds = resolve_dataset_reference(ent.text)
        if ds:
            resolved.append(ds)

    # Pull derivative hits for convenience
    derivative_hits: list[DerivativeHit] = []
    for ds in resolved:
        derivative_hits.extend(
            find_existing_derivatives(
                ds.dataset_id,
                manual_catalog=DEFAULT_MANUAL_CATALOG,
            )
        )

    return QueryUnderstandingResult(
        original_query=parsed_query.original_query,
        entities=[ent.__dict__ for ent in parsed_query.entities],
        resolved_datasets=resolved,
        candidate_datasets=candidate_datasets,
        kg_nodes=kg_nodes,
        ambiguities=[],
        existing_derivatives=derivative_hits,
    )


def _collect_candidate_datasets(
    parsed_query: ParsedQuery,
    kg_nodes: list[KGNodeRef],
    *,
    limit: int = DEFAULT_KG_DATASET_LIMIT,
) -> list[DatasetResolution]:
    """Collect KG-derived dataset candidates for query understanding.

    Strategy:
      1) For each KG node, fetch related datasets.
      2) If none found, try text search using the original query.
      3) Map to DatasetResolution via catalog when possible; else use fallback.
    """

    candidates: list[DatasetResolution] = []
    seen_ids: set[str] = set()

    try:
        from brain_researcher.services.br_kg import query_service
    except Exception as exc:  # pragma: no cover - KG optional
        logger.debug("BR-KG query service unavailable: %s", exc)
        return candidates

    # 1) KG-related datasets for matched nodes
    for node in kg_nodes:
        if not node or not node.id:
            continue
        try:
            related = query_service.related_datasets(node.id, limit=limit)
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("related_datasets failed for %s: %s", node.id, exc)
            continue
        for ds in related:
            ds_id = getattr(ds, "dataset_id", None)
            if not ds_id or ds_id in seen_ids:
                continue
            seen_ids.add(ds_id)
            resolved = resolve_dataset_reference(str(ds_id))
            if resolved is None:
                resolved = _fallback_dataset_resolution_from_kg(ds)
            if resolved:
                candidates.append(resolved)

    # 2) Text search fallback if no candidates
    if not candidates and parsed_query.original_query:
        try:
            hits = query_service.search_datasets(
                text=parsed_query.original_query, limit=limit
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug(
                "search_datasets failed for query '%s': %s",
                parsed_query.original_query,
                exc,
            )
            hits = []
        for ds in hits:
            ds_id = getattr(ds, "dataset_id", None)
            if not ds_id or ds_id in seen_ids:
                continue
            seen_ids.add(ds_id)
            resolved = resolve_dataset_reference(str(ds_id))
            if resolved is None:
                resolved = _fallback_dataset_resolution_from_kg(ds)
            if resolved:
                candidates.append(resolved)

    return candidates


def _fallback_dataset_resolution_from_kg(ds: Any) -> DatasetResolution | None:
    """Build a minimal DatasetResolution from a KG dataset record."""
    ds_id = getattr(ds, "dataset_id", None)
    if not ds_id:
        return None

    title = getattr(ds, "title", None) or str(ds_id)
    tasks = getattr(ds, "tasks", None) or []
    modalities = getattr(ds, "modalities", None) or []
    n_subjects = getattr(ds, "n_subjects", None)
    species = getattr(ds, "species", None)
    kg_id = getattr(ds, "kg_id", None)

    remote_url = None
    simple_id = str(ds_id).split(":")[-1]
    if simple_id.startswith("ds"):
        remote_url = f"https://openneuro.org/datasets/{simple_id}"

    return DatasetResolution(
        dataset_id=str(ds_id),
        name=title,
        display_name=title,
        source_repo="br_kg",
        primary_url=remote_url,
        local_path=None,
        kg_node_id=kg_id,
        bids_path=None,
        remote_url=remote_url,
        aliases=[],
        resources=None,
        metadata={
            "tasks": tasks,
            "modalities": modalities,
            "n_subjects": n_subjects,
            "species": species,
            "kg_id": kg_id,
        },
    )


__all__ = [
    "DatasetResolution",
    "DatasetResources",
    "DerivativeHit",
    "KGNodeRef",
    "QueryUnderstandingResult",
    "_path_from_mounts",
    "link_entities_to_kg",
    "resolve_dataset_reference",
    "find_existing_derivatives",
    "collect_dataset_resources",
    "build_query_understanding_result",
]
