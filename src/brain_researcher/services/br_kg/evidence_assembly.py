"""Paper / study evidence assembly + dedup helpers for the BR-KG lens API.

Carved out of ``br_kg/app.py``: the pure helpers that build paper-aligned
Cypher expressions, normalise paper titles, and merge / deduplicate the
study + publication evidence rows returned by the lens endpoints. None of
these own module state; they depend on a small set of shared helpers
(``_as_paper_item`` / ``_paper_dedupe_key`` / ``_default_item_id`` /
``_csv_tokens`` / ``_task_neighbor_dedupe_key``) and two label-regex constants
(``_LABEL_SEP_RE`` / ``_LABEL_SPACE_RE``) that stay in ``app.py`` and are
imported back lazily (inside the consuming functions) to keep the dependency
one-way: ``app -> evidence_assembly``.

``app.py`` re-exports every name below so existing ``app.<name>`` references and
route handlers keep resolving.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _normalize_paper_title(title: Any) -> str:
    from brain_researcher.services.br_kg.app import _LABEL_SEP_RE, _LABEL_SPACE_RE

    text = str(title or "").strip().lower()
    if not text:
        return ""
    text = _LABEL_SEP_RE.sub(" ", text)
    return _LABEL_SPACE_RE.sub(" ", text).strip()


def _cypher_paper_aligned_study_expr(node_var: str) -> str:
    return f"""
    CASE
      WHEN any(lbl IN labels({node_var}) WHERE lbl = 'Study')
        THEN coalesce(toString({node_var}.id), elementId({node_var}))
      ELSE head([
        ({node_var})-[:ALIGNS_WITH]->(aligned_study:Study) |
        coalesce(toString(aligned_study.id), elementId(aligned_study))
      ])
    END
    """.strip()


def _cypher_paper_aligned_publication_expr(node_var: str) -> str:
    return f"""
    CASE
      WHEN any(lbl IN labels({node_var}) WHERE lbl IN ['Publication', 'Paper'])
        THEN coalesce(
          toString({node_var}.id),
          toString({node_var}.pmid),
          toString({node_var}.doi),
          elementId({node_var})
        )
      ELSE head([
        (aligned_publication)-[:ALIGNS_WITH]->({node_var})
        WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
        coalesce(
          toString(aligned_publication.id),
          toString(aligned_publication.pmid),
          toString(aligned_publication.doi),
          elementId(aligned_publication)
        )
      ])
    END
    """.strip()


def _cypher_paper_source_type_expr(node_var: str) -> str:
    return f"""
    CASE
      WHEN any(lbl IN labels({node_var}) WHERE lbl IN ['Publication', 'Paper'])
        THEN 'publication'
      ELSE 'study'
    END
    """.strip()


def _cypher_paper_candidate_dedupe_key(item_var: str) -> str:
    return f"""
    CASE
      WHEN coalesce(toString({item_var}.aligned_study_id), '') <> ''
        THEN 'aligned_study:' + toLower(trim(toString({item_var}.aligned_study_id)))
      WHEN coalesce(toString({item_var}.aligned_publication_id), '') <> ''
        THEN 'aligned_publication:' + toLower(trim(toString({item_var}.aligned_publication_id)))
      WHEN coalesce(toString({item_var}.pmid), '') <> ''
        THEN 'pmid:' + toLower(trim(toString({item_var}.pmid)))
      WHEN coalesce(toString({item_var}.doi), '') <> ''
        THEN 'doi:' + toLower(trim(toString({item_var}.doi)))
      WHEN coalesce(toString({item_var}.title), '') <> ''
        THEN 'title:' + toLower(trim(toString({item_var}.title)))
      ELSE 'id:' + toLower(trim(coalesce(toString({item_var}.id), '')))
    END
    """.strip()


def _cypher_study_candidate_dedupe_key(item_var: str) -> str:
    return f"""
    CASE
      WHEN coalesce(toString({item_var}.id), '') <> ''
        THEN 'id:' + toLower(trim(toString({item_var}.id)))
      WHEN coalesce(toString({item_var}.name), '') <> ''
        THEN 'title:' + toLower(trim(toString({item_var}.name)))
      WHEN coalesce(toString({item_var}.title), '') <> ''
        THEN 'title:' + toLower(trim(toString({item_var}.title)))
      WHEN coalesce(toString({item_var}.url), '') <> ''
        THEN 'url:' + toLower(trim(toString({item_var}.url)))
      ELSE 'raw:' + toLower(trim(coalesce(toString({item_var}.description), '')))
    END
    """.strip()


def _merge_task_paper_items(
    direct_items: list[Mapping[str, Any]],
    fallback_items: list[Mapping[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from brain_researcher.services.br_kg.app import _as_paper_item, _paper_dedupe_key

    merged: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    dedup_dropped = 0

    for raw in direct_items:
        item = _as_paper_item(raw, "publication")
        key = _paper_dedupe_key(item)
        if key in seen:
            dedup_dropped += 1
            existing = merged[seen[key]]
            merged_item = dict(existing)
            for field in (
                "id",
                "pmid",
                "doi",
                "title",
                "year",
                "authors",
                "matched_via_rel_type",
                "canonical_edge_type",
                "confidence",
                "confidence_normalized",
                "confidence_tier",
                "normalization_basis",
                "aligned_publication_id",
                "aligned_study_id",
            ):
                if merged_item.get(field) in (None, "", []) and item.get(field) not in (
                    None,
                    "",
                    [],
                ):
                    merged_item[field] = item[field]
            merged_item["approximate_rule_applied"] = bool(
                merged_item.get("approximate_rule_applied")
                or item.get("approximate_rule_applied")
            )
            merged[seen[key]] = merged_item
            continue
        seen[key] = len(merged)
        merged.append(item)

    for raw in fallback_items:
        item = _as_paper_item(raw, "study")
        key = _paper_dedupe_key(item)
        existing_idx = seen.get(key)
        if existing_idx is None:
            seen[key] = len(merged)
            merged.append(item)
            continue

        dedup_dropped += 1
        existing = merged[existing_idx]
        merged_item = dict(existing)
        for field in (
            "id",
            "pmid",
            "doi",
            "title",
            "year",
            "authors",
            "matched_via_rel_type",
            "canonical_edge_type",
            "confidence",
            "confidence_normalized",
            "confidence_tier",
            "normalization_basis",
            "aligned_publication_id",
            "aligned_study_id",
        ):
            if merged_item.get(field) in (None, "", []) and item.get(field) not in (
                None,
                "",
                [],
            ):
                merged_item[field] = item[field]
        merged_item["approximate_rule_applied"] = bool(
            merged_item.get("approximate_rule_applied")
            or item.get("approximate_rule_applied")
        )
        if merged_item.get("source_type") != "publication" and (
            str(existing.get("source_type") or "") == "publication"
            or str(item.get("source_type") or "") == "publication"
        ):
            merged_item["source_type"] = "publication"
        merged[existing_idx] = merged_item

    direct_hits = sum(1 for item in merged if item.get("source_type") == "publication")
    fallback_hits = sum(1 for item in merged if item.get("source_type") == "study")
    metrics = {
        "task_paper_direct_hits": direct_hits,
        "task_paper_fallback_hits": fallback_hits,
        "task_paper_dedup_dropped": dedup_dropped,
        "task_paper_total_unique": len(merged),
    }
    return merged[:limit], metrics


def _merge_source_channels(existing: Any, incoming: Any) -> str:
    from brain_researcher.services.br_kg.app import _csv_tokens

    merged = _csv_tokens(existing) + _csv_tokens(incoming)
    seen: set[str] = set()
    ordered: list[str] = []
    for token in merged:
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ",".join(ordered)


def _merge_evidence_item(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key in {"source_channel", "support_count"}:
            continue
        if merged.get(key) in (None, "", []) and value not in (None, "", []):
            merged[key] = value

    merged["source_channel"] = _merge_source_channels(
        existing.get("source_channel"),
        incoming.get("source_channel"),
    )
    merged["support_count"] = int(existing.get("support_count") or 1) + int(
        incoming.get("support_count") or 1
    )
    return merged


def _evidence_item_id(item: Mapping[str, Any], group_name: str) -> str:
    from brain_researcher.services.br_kg.app import _default_item_id

    if group_name == "statmaps":
        for key in ("map_id", "id", "contrast", "url"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""
    if group_name == "papers":
        for key in ("pmid", "doi", "id", "title", "url"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""
    if group_name == "studies":
        for key in ("id", "name", "title", "url"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""
    return _default_item_id(item)


def _evidence_dedupe_key(item: Mapping[str, Any], group_name: str) -> str:
    from brain_researcher.services.br_kg.app import (
        _default_item_id,
        _paper_dedupe_key,
        _task_neighbor_dedupe_key,
    )

    if group_name == "papers":
        return _paper_dedupe_key(item)
    if group_name == "studies":
        study_id = str(item.get("id") or "").strip().lower()
        if study_id:
            return f"id:{study_id}"
        title = _normalize_paper_title(item.get("name") or item.get("title"))
        if title:
            return f"title:{title}"
        return f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    if group_name in {"tasks", "task_neighbors"}:
        return _task_neighbor_dedupe_key(item)
    if group_name == "statmaps":
        map_id = str(item.get("map_id") or item.get("id") or "").strip().lower()
        if map_id:
            return f"id:{map_id}"
        contrast = _normalize_paper_title(item.get("contrast"))
        if contrast:
            return f"contrast:{contrast}"
        return f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    item_id = _default_item_id(item).strip().lower()
    if item_id:
        return f"id:{item_id}"
    return (
        f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    )


def _merge_group_items(
    *,
    group_name: str,
    existing_items: list[dict[str, Any]],
    incoming_items: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    deduped: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for item in existing_items:
        key = _evidence_dedupe_key(item, group_name)
        seen[key] = len(deduped)
        deduped.append(dict(item))
    for item in incoming_items:
        key = _evidence_dedupe_key(item, group_name)
        idx = seen.get(key)
        if idx is None:
            seen[key] = len(deduped)
            deduped.append(dict(item))
            continue
        deduped[idx] = _merge_evidence_item(deduped[idx], item)
    total = len(deduped)
    return deduped[:limit], total
