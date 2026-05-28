#!/usr/bin/env python3
"""Backfill Publication-[:CITES]->Publication edges from scholarly metadata."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.services.neurokg.etl.loaders.scholarly_metadata_loader import (
    ScholarlyMetadataLoader,
)

DEFAULT_METHOD_TAG = "publication_citation_backfill_v1"
DEFAULT_RELATIONSHIP_SOURCE = "scholarly_metadata_backfill"
DEFAULT_OUTPUT_JSON = Path(
    "tmp/publication_citation_backfill/publication_citation_backfill_report.json"
)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\x00", " ").split()).strip()


def _normalize_dataset_key(value: Any) -> str:
    text = _clean_text(value).lower()
    if not text:
        return ""
    if text.startswith("ds:openneuro:"):
        return text
    if text.startswith("ds") and len(text) >= 8:
        return f"ds:openneuro:{text}"
    return text


def _normalize_optional_doi(value: Any) -> str | None:
    text = _clean_text(value).lower()
    if not text:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.rstrip(").,;") or None


def _coalesce_unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687")
    )
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument(
        "--dataset-id",
        action="append",
        dest="dataset_ids",
        default=None,
        help="Resolve source publication anchors from Dataset-[:CITED_BY]->Publication.",
    )
    parser.add_argument(
        "--doi",
        action="append",
        dest="dois",
        default=None,
        help="Explicit source publication DOI(s) to harvest.",
    )
    parser.add_argument("--method-tag", default=DEFAULT_METHOD_TAG)
    parser.add_argument("--crossref-mailto", default=_env("CROSSREF_MAILTO"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--prune-method-tag-first",
        action="store_true",
        help="Delete existing CITES edges with the same method_tag before apply.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    return parser.parse_args(argv)


def _resolve_dataset_anchor_publications(
    session: Any,
    *,
    dataset_filters: list[str],
) -> list[dict[str, Any]]:
    if not dataset_filters:
        return []
    query = """
    MATCH (d:Dataset)-[:CITED_BY]->(p:Publication)
    WHERE any(term IN $dataset_filters WHERE
      toLower(coalesce(d.id, '')) = term OR
      toLower(coalesce(d.dataset_id, '')) = term OR
      toLower(coalesce(d.source_repo_id, '')) = term OR
      any(alias IN coalesce(d.aliases, []) WHERE toLower(alias) = term)
    )
    RETURN DISTINCT
      coalesce(d.id, d.dataset_id, d.source_repo_id) AS dataset_kg_id,
      coalesce(d.dataset_id, d.id, d.source_repo_id) AS dataset_id,
      coalesce(d.source_repo_id, '') AS source_repo_id,
      coalesce(p.id, p.doi) AS publication_id,
      coalesce(p.doi, p.id) AS doi,
      coalesce(p.title, p.label, p.name, p.id) AS title
    ORDER BY dataset_kg_id, publication_id
    """
    records = list(session.run(query, {"dataset_filters": dataset_filters}))
    out: list[dict[str, Any]] = []
    for record in records:
        doi = _normalize_optional_doi((record or {}).get("doi"))
        publication_id = _clean_text((record or {}).get("publication_id"))
        if not doi and not publication_id:
            continue
        out.append(
            {
                "dataset_kg_id": _clean_text((record or {}).get("dataset_kg_id")),
                "dataset_id": _clean_text((record or {}).get("dataset_id")),
                "source_repo_id": _clean_text((record or {}).get("source_repo_id")),
                "publication_id": publication_id or doi,
                "doi": doi or _normalize_optional_doi(publication_id),
                "title": _clean_text((record or {}).get("title")),
                "source_kind": "dataset_anchor",
            }
        )
    return out


def _resolve_explicit_publications(
    session: Any,
    *,
    doi_filters: list[str],
) -> list[dict[str, Any]]:
    if not doi_filters:
        return []
    query = """
    MATCH (p:Publication)
    WHERE any(term IN $doi_filters WHERE
      toLower(coalesce(p.id, '')) = term OR
      toLower(coalesce(p.doi, '')) = term OR
      any(alias IN coalesce(p.aliases, []) WHERE toLower(alias) = term)
    )
    RETURN DISTINCT
      coalesce(p.id, p.doi) AS publication_id,
      coalesce(p.doi, p.id) AS doi,
      coalesce(p.title, p.label, p.name, p.id) AS title
    ORDER BY publication_id
    """
    records = list(session.run(query, {"doi_filters": doi_filters}))
    out: list[dict[str, Any]] = []
    matched_keys: set[str] = set()
    for record in records:
        doi = _normalize_optional_doi((record or {}).get("doi"))
        publication_id = _clean_text((record or {}).get("publication_id"))
        key = doi or publication_id
        if not key:
            continue
        matched_keys.add(key)
        out.append(
            {
                "dataset_kg_id": "",
                "dataset_id": "",
                "source_repo_id": "",
                "publication_id": publication_id or doi,
                "doi": doi or _normalize_optional_doi(publication_id),
                "title": _clean_text((record or {}).get("title")),
                "source_kind": "explicit_publication",
            }
        )
    for doi in doi_filters:
        if doi in matched_keys:
            continue
        out.append(
            {
                "dataset_kg_id": "",
                "dataset_id": "",
                "source_repo_id": "",
                "publication_id": doi,
                "doi": doi,
                "title": "",
                "source_kind": "explicit_publication",
            }
        )
    return out


def _resolve_source_publications(
    session: Any,
    *,
    dataset_filters: list[str],
    doi_filters: list[str],
) -> list[dict[str, Any]]:
    raw = _resolve_dataset_anchor_publications(
        session,
        dataset_filters=dataset_filters,
    ) + _resolve_explicit_publications(
        session,
        doi_filters=doi_filters,
    )
    merged: dict[str, dict[str, Any]] = {}
    for row in raw:
        key = _normalize_optional_doi(row.get("doi")) or _clean_text(
            row.get("publication_id")
        )
        if not key:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                **row,
                "dataset_ids": _coalesce_unique(
                    [
                        row.get("dataset_kg_id"),
                        row.get("dataset_id"),
                        row.get("source_repo_id"),
                    ]
                ),
            }
            continue
        existing["dataset_ids"] = _coalesce_unique(
            list(existing.get("dataset_ids") or [])
            + [
                row.get("dataset_kg_id"),
                row.get("dataset_id"),
                row.get("source_repo_id"),
            ]
        )
        if not existing.get("title") and row.get("title"):
            existing["title"] = row.get("title")
    return sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("source_kind") or ""),
            str(item.get("publication_id") or ""),
        ),
    )


def _build_source_lookup_terms(source: dict[str, Any]) -> list[str]:
    doi = _normalize_optional_doi(source.get("doi"))
    publication_id = _clean_text(source.get("publication_id"))
    return _coalesce_unique(
        [
            publication_id,
            doi,
            f"doi:{doi}" if doi else "",
        ]
    )


def _build_citation_rows(
    sources: list[dict[str, Any]],
    *,
    loader: ScholarlyMetadataLoader,
    method_tag: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    source_dois = [
        _normalize_optional_doi(source.get("doi"))
        for source in sources
        if _normalize_optional_doi(source.get("doi"))
    ]
    source_dois = [doi for doi in source_dois if doi]
    if not source_dois:
        return [], {
            "source_publications": len(sources),
            "records_harvested": 0,
            "citation_rows": 0,
            "skipped_missing_doi": len(sources),
            "skipped_missing_citation_doi": 0,
            "skipped_self_citation": 0,
        }
    records = loader.load_records(dois=source_dois)
    source_map = {
        (_normalize_optional_doi(source.get("doi")) or ""): source for source in sources
    }
    rows: list[dict[str, Any]] = []
    skipped_missing_citation_doi = 0
    skipped_self_citation = 0
    for record in records:
        source_doi = _normalize_optional_doi(record.get("doi"))
        if not source_doi or source_doi not in source_map:
            continue
        source = source_map[source_doi]
        seen_targets: set[str] = set()
        for cited in record.get("citations") or []:
            target_doi = _normalize_optional_doi(cited)
            if not target_doi:
                skipped_missing_citation_doi += 1
                continue
            if target_doi == source_doi:
                skipped_self_citation += 1
                continue
            if target_doi in seen_targets:
                continue
            seen_targets.add(target_doi)
            rows.append(
                {
                    "source_publication_id": _clean_text(source.get("publication_id"))
                    or source_doi,
                    "source_lookup_terms": _build_source_lookup_terms(source),
                    "source_doi": source_doi,
                    "source_title": _clean_text(source.get("title"))
                    or _clean_text(record.get("title")),
                    "source_dataset_ids": list(source.get("dataset_ids") or []),
                    "target_publication_id": target_doi,
                    "target_doi": target_doi,
                    "relationship_source": DEFAULT_RELATIONSHIP_SOURCE,
                    "publication_source": "scholarly_metadata_stub",
                    "method_tag": method_tag,
                }
            )
    stats = {
        "source_publications": len(sources),
        "records_harvested": len(records),
        "citation_rows": len(rows),
        "skipped_missing_doi": max(len(sources) - len(source_dois), 0),
        "skipped_missing_citation_doi": skipped_missing_citation_doi,
        "skipped_self_citation": skipped_self_citation,
    }
    return rows, stats


def _count_existing_target_edges(
    session: Any,
    *,
    method_tag: str,
    source_publication_ids: list[str],
) -> int:
    query = """
    MATCH (src:Publication)-[r:CITES]->(:Publication)
    WHERE r.method_tag = $method_tag
      AND (
        size($source_publication_ids) = 0 OR
        any(term IN $source_publication_ids WHERE
          toLower(coalesce(toString(src.id), '')) = term OR
          toLower(coalesce(toString(src.doi), '')) = term OR
          any(alias IN coalesce(src.aliases, []) WHERE toLower(coalesce(toString(alias), '')) = term)
        )
      )
    RETURN count(r) AS total
    """
    row = session.run(
        query,
        {
            "method_tag": method_tag,
            "source_publication_ids": source_publication_ids,
        },
    ).single()
    return int((row or {}).get("total") or 0)


def _prune_existing_target_edges(
    session: Any,
    *,
    method_tag: str,
    source_publication_ids: list[str],
) -> int:
    query = """
    MATCH (src:Publication)-[r:CITES]->(:Publication)
    WHERE r.method_tag = $method_tag
      AND (
        size($source_publication_ids) = 0 OR
        any(term IN $source_publication_ids WHERE
          toLower(coalesce(toString(src.id), '')) = term OR
          toLower(coalesce(toString(src.doi), '')) = term OR
          any(alias IN coalesce(src.aliases, []) WHERE toLower(coalesce(toString(alias), '')) = term)
        )
      )
    WITH collect(r) AS rels
    FOREACH (rel IN rels | DELETE rel)
    RETURN size(rels) AS deleted
    """
    row = session.run(
        query,
        {
            "method_tag": method_tag,
            "source_publication_ids": source_publication_ids,
        },
    ).single()
    return int((row or {}).get("deleted") or 0)


def _count_source_matches(session: Any, rows: list[dict[str, Any]]) -> dict[str, int]:
    query = """
    UNWIND $rows AS row
    OPTIONAL MATCH (src:Publication)
    WHERE any(term IN row.source_lookup_terms WHERE
      toLower(coalesce(toString(src.id), '')) = toLower(term) OR
      toLower(coalesce(toString(src.doi), '')) = toLower(term) OR
      any(alias IN coalesce(src.aliases, []) WHERE toLower(coalesce(toString(alias), '')) = toLower(term))
    )
    WITH row, head(collect(DISTINCT src)) AS src
    RETURN count(row) AS selected_rows,
           count(CASE WHEN src IS NOT NULL THEN 1 END) AS matched_rows,
           count(DISTINCT src) AS matched_publications
    """
    row = session.run(query, {"rows": rows}).single()
    return {
        "selected_rows": int((row or {}).get("selected_rows") or 0),
        "matched_rows": int((row or {}).get("matched_rows") or 0),
        "matched_publications": int((row or {}).get("matched_publications") or 0),
    }


def _apply_rows(session: Any, rows: list[dict[str, Any]]) -> dict[str, int]:
    query = """
    UNWIND $rows AS row
    OPTIONAL MATCH (src:Publication)
    WHERE any(term IN row.source_lookup_terms WHERE
      toLower(coalesce(toString(src.id), '')) = toLower(term) OR
      toLower(coalesce(toString(src.doi), '')) = toLower(term) OR
      any(alias IN coalesce(src.aliases, []) WHERE toLower(coalesce(toString(alias), '')) = toLower(term))
    )
    WITH row, head(collect(DISTINCT src)) AS src
    WHERE src IS NOT NULL
    MERGE (dst:Publication {id: row.target_publication_id})
    ON CREATE SET
      dst.__citation_stub_created = true,
      dst.created_at = datetime(),
      dst.source = row.publication_source,
      dst.method_tag = row.method_tag,
      dst.doi = row.target_doi
    SET
      dst.source = coalesce(dst.source, row.publication_source),
      dst.method_tag = coalesce(dst.method_tag, row.method_tag),
      dst.doi = coalesce(dst.doi, row.target_doi)
    MERGE (src)-[r:CITES {method_tag: row.method_tag, target_id: row.target_publication_id}]->(dst)
    ON CREATE SET
      r.__citation_rel_created = true,
      r.created_at = datetime(),
      r.source = row.relationship_source,
      r.source_publication_id = row.source_publication_id,
      r.source_doi = row.source_doi,
      r.source_title = row.source_title,
      r.source_dataset_ids = row.source_dataset_ids
    SET
      r.source = coalesce(r.source, row.relationship_source),
      r.source_publication_id = coalesce(r.source_publication_id, row.source_publication_id),
      r.source_doi = coalesce(r.source_doi, row.source_doi),
      r.source_title = coalesce(r.source_title, row.source_title),
      r.source_dataset_ids = coalesce(r.source_dataset_ids, row.source_dataset_ids)
    RETURN count(row) AS matched_rows,
           count(DISTINCT src) AS matched_publications,
           count(DISTINCT CASE WHEN dst.__citation_stub_created THEN dst END) AS created_publications,
           count(DISTINCT CASE WHEN r.__citation_rel_created THEN r END) AS created_edges
    """
    row = session.run(query, {"rows": rows}).single()
    return {
        "matched_rows": int((row or {}).get("matched_rows") or 0),
        "matched_publications": int((row or {}).get("matched_publications") or 0),
        "created_publications": int((row or {}).get("created_publications") or 0),
        "created_edges": int((row or {}).get("created_edges") or 0),
    }


def _cleanup_temp_flags(session: Any) -> dict[str, int]:
    pub_query = """
    MATCH (p:Publication)
    WHERE p.__citation_stub_created = true
    REMOVE p.__citation_stub_created
    RETURN count(p) AS cleaned
    """
    rel_query = """
    MATCH ()-[r:CITES]->()
    WHERE r.__citation_rel_created = true
    REMOVE r.__citation_rel_created
    RETURN count(r) AS cleaned
    """
    pub_row = session.run(pub_query).single()
    rel_row = session.run(rel_query).single()
    return {
        "cleaned_publication_flags": int((pub_row or {}).get("cleaned") or 0),
        "cleaned_edge_flags": int((rel_row or {}).get("cleaned") or 0),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset_filters = sorted(
        {
            key
            for item in (args.dataset_ids or [])
            for key in {_normalize_dataset_key(item), _clean_text(item).lower()}
            if key
        }
    )
    doi_filters = sorted(
        {doi for item in (args.dois or []) if (doi := _normalize_optional_doi(item))}
    )

    if not dataset_filters and not doi_filters:
        raise SystemExit("Provide at least one --dataset-id or --doi.")

    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    loader = ScholarlyMetadataLoader(crossref_mailto=args.crossref_mailto)

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            sources = _resolve_source_publications(
                session,
                dataset_filters=dataset_filters,
                doi_filters=doi_filters,
            )
            rows, selection_stats = _build_citation_rows(
                sources,
                loader=loader,
                method_tag=str(args.method_tag),
            )
            source_publication_ids = sorted(
                {
                    _clean_text(source.get("publication_id")).lower()
                    or (_normalize_optional_doi(source.get("doi")) or "")
                    for source in sources
                    if _clean_text(source.get("publication_id"))
                    or _normalize_optional_doi(source.get("doi"))
                }
            )

            report: dict[str, Any] = {
                "generated_at": _utc_now_iso(),
                "dry_run": bool(args.dry_run),
                "method_tag": str(args.method_tag),
                "dataset_filters": dataset_filters,
                "doi_filters": doi_filters,
                "resolved_sources": sources,
                "selection": selection_stats,
                "selected_edges": [
                    {
                        "source_publication_id": row["source_publication_id"],
                        "target_publication_id": row["target_publication_id"],
                        "source_dataset_ids": row["source_dataset_ids"],
                    }
                    for row in rows
                ],
                "graph": {
                    "targeted_existing_edges": _count_existing_target_edges(
                        session,
                        method_tag=str(args.method_tag),
                        source_publication_ids=source_publication_ids,
                    ),
                    "deleted_existing_edges": 0,
                    "matched_rows": 0,
                    "matched_publications": 0,
                    "missing_source_rows": 0,
                    "created_publications": 0,
                    "created_edges": 0,
                    "existing_edges": 0,
                    "cleanup": {},
                },
            }

            if args.prune_method_tag_first and not args.dry_run:
                report["graph"]["deleted_existing_edges"] = (
                    _prune_existing_target_edges(
                        session,
                        method_tag=str(args.method_tag),
                        source_publication_ids=source_publication_ids,
                    )
                )

            match_stats = _count_source_matches(session, rows)
            report["graph"]["matched_rows"] = match_stats["matched_rows"]
            report["graph"]["matched_publications"] = match_stats[
                "matched_publications"
            ]
            report["graph"]["missing_source_rows"] = max(
                match_stats["selected_rows"] - match_stats["matched_rows"], 0
            )

            if not args.dry_run and rows:
                apply_stats = _apply_rows(session, rows)
                report["graph"]["matched_rows"] = apply_stats["matched_rows"]
                report["graph"]["matched_publications"] = apply_stats[
                    "matched_publications"
                ]
                report["graph"]["missing_source_rows"] = max(
                    len(rows) - apply_stats["matched_rows"], 0
                )
                report["graph"]["created_publications"] = apply_stats[
                    "created_publications"
                ]
                report["graph"]["created_edges"] = apply_stats["created_edges"]
                report["graph"]["existing_edges"] = max(
                    apply_stats["matched_rows"] - apply_stats["created_edges"], 0
                )
                report["graph"]["cleanup"] = _cleanup_temp_flags(session)

    output_path = args.output_json.expanduser().resolve()
    _write_report(output_path, report)
    print(
        json.dumps(
            {
                "ok": True,
                "output_path": str(output_path),
                "selection": report["selection"],
                "graph": report["graph"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
