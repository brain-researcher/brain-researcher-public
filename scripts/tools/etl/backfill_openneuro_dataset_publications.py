#!/usr/bin/env python3
"""Backfill OpenNeuro Dataset->Publication anchors from a reviewed candidate pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

DEFAULT_METHOD_TAG = "openneuro_dataset_publication_backfill_v1"
DEFAULT_RELATIONSHIP_SOURCE = "openneuro_publication_backfill"
DEFAULT_OUTPUT_JSON = Path(
    "tmp/openneuro_publication_backfill/openneuro_dataset_publication_backfill_report.json"
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


def _normalize_dataset_key(value: str) -> str:
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


def _dataset_match_terms(report: dict[str, Any]) -> list[str]:
    dataset_kg_id = _clean_text(report.get("dataset_kg_id"))
    dataset_id = _clean_text(report.get("dataset_id"))
    source_repo_id = _clean_text(report.get("source_repo_id"))
    openneuro_dois = list(report.get("openneuro_dois") or [])
    return _coalesce_unique(
        [
            dataset_kg_id,
            dataset_id,
            source_repo_id,
            *openneuro_dois,
        ]
    )


def _publication_id_for_candidate(candidate: dict[str, Any]) -> str:
    doi = _normalize_optional_doi(candidate.get("doi"))
    if doi:
        return doi
    pmid = _clean_text(candidate.get("pmid"))
    if pmid:
        return f"pmid:{pmid}"
    pmcid = _clean_text(candidate.get("pmcid"))
    if pmcid:
        return f"pmcid:{pmcid.lower()}"
    fingerprint = "|".join(
        [
            _clean_text(candidate.get("title")).lower(),
            _clean_text(candidate.get("url")).lower(),
        ]
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"openneuro_pub:{digest}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-pack", type=Path, required=True)
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument(
        "--dataset-id",
        action="append",
        dest="dataset_ids",
        default=None,
        help="Restrict apply to specific OpenNeuro dataset ids or KG ids.",
    )
    parser.add_argument("--min-score", type=float, default=0.75)
    parser.add_argument("--max-candidates-per-dataset", type=int, default=1)
    parser.add_argument(
        "--allow-title-only",
        action="store_true",
        help="Allow title/url hash identifiers when DOI/PMID/PMCID are missing.",
    )
    parser.add_argument("--method-tag", default=DEFAULT_METHOD_TAG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--prune-method-tag-first",
        action="store_true",
        help="Delete existing CITED_BY edges with the same method_tag before apply.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    return parser.parse_args(argv)


def _load_candidate_reports(path: Path) -> list[dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Candidate pack not found: {resolved}")
    text = resolved.read_text(encoding="utf-8")
    if resolved.suffix.lower() == ".jsonl":
        reports: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                reports.append(payload)
        return reports

    payload = json.loads(text)
    if isinstance(payload, dict) and isinstance(payload.get("dataset_reports"), list):
        return [item for item in payload["dataset_reports"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError(f"Unsupported candidate pack format: {resolved}")


def _dataset_report_keys(report: dict[str, Any]) -> set[str]:
    keys = {
        _normalize_dataset_key(report.get("dataset_kg_id") or ""),
        _normalize_dataset_key(report.get("dataset_id") or ""),
        _normalize_dataset_key(report.get("source_repo_id") or ""),
    }
    return {key for key in keys if key}


def _select_candidate_rows(
    reports: list[dict[str, Any]],
    *,
    dataset_filters: set[str],
    min_score: float,
    max_candidates_per_dataset: int,
    allow_title_only: bool,
    candidate_pack_path: Path,
    method_tag: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected_rows: list[dict[str, Any]] = []
    stats = {
        "dataset_reports_scanned": len(reports),
        "dataset_reports_selected": 0,
        "candidates_considered": 0,
        "candidates_selected": 0,
        "skipped_dataset_filter": 0,
        "skipped_low_score": 0,
        "skipped_missing_identifier": 0,
    }

    for report in reports:
        report_keys = _dataset_report_keys(report)
        if dataset_filters and not (report_keys & dataset_filters):
            stats["skipped_dataset_filter"] += 1
            continue
        stats["dataset_reports_selected"] += 1

        dataset_id = _clean_text(report.get("dataset_id"))
        dataset_kg_id = _clean_text(report.get("dataset_kg_id")) or dataset_id
        source_repo_id = _clean_text(report.get("source_repo_id"))
        dataset_match_terms = _dataset_match_terms(report)
        candidates = list(report.get("candidates") or [])
        keep_count = 0
        for rank, candidate in enumerate(candidates, start=1):
            if keep_count >= max(1, int(max_candidates_per_dataset)):
                break
            if not isinstance(candidate, dict):
                continue
            stats["candidates_considered"] += 1
            score = float(candidate.get("score") or 0.0)
            if score < float(min_score):
                stats["skipped_low_score"] += 1
                continue

            has_stable_identifier = any(
                _clean_text(candidate.get(key)) for key in ("doi", "pmid", "pmcid")
            )
            if not allow_title_only and not has_stable_identifier:
                stats["skipped_missing_identifier"] += 1
                continue

            evidence_urls = _coalesce_unique(
                [item.get("url") for item in (candidate.get("evidence") or [])]
            )
            publication_aliases = _coalesce_unique(
                dataset_match_terms
                + [
                    _clean_text(candidate.get("legacy_accession")),
                    _normalize_optional_doi(candidate.get("doi")) or "",
                    f"doi:{_normalize_optional_doi(candidate.get('doi'))}"
                    if _normalize_optional_doi(candidate.get("doi"))
                    else "",
                    _clean_text(candidate.get("pmid")),
                    f"pmid:{_clean_text(candidate.get('pmid'))}"
                    if _clean_text(candidate.get("pmid"))
                    else "",
                    _clean_text(candidate.get("pmcid")),
                    _clean_text(candidate.get("title")),
                ]
            )
            row = {
                "dataset_kg_id": dataset_kg_id,
                "dataset_id": dataset_id or dataset_kg_id,
                "source_repo_id": source_repo_id,
                "dataset_lookup_terms": dataset_match_terms,
                "dataset_ids": _coalesce_unique([dataset_kg_id, dataset_id]),
                "dataset_primary_id": dataset_kg_id or dataset_id,
                "publication_id": _publication_id_for_candidate(candidate),
                "title": _clean_text(candidate.get("title")),
                "doi": _normalize_optional_doi(candidate.get("doi")),
                "pmid": _clean_text(candidate.get("pmid")) or None,
                "pmcid": _clean_text(candidate.get("pmcid")) or None,
                "journal": _clean_text(candidate.get("journal")) or None,
                "year": candidate.get("year"),
                "reference": _clean_text(candidate.get("url")) or None,
                "legacy_accession": _clean_text(candidate.get("legacy_accession"))
                or None,
                "publication_aliases": publication_aliases,
                "publication_source": DEFAULT_RELATIONSHIP_SOURCE,
                "relationship_source": DEFAULT_RELATIONSHIP_SOURCE,
                "method_tag": method_tag,
                "match_score": round(score, 4),
                "match_reasons": list(candidate.get("match_reasons") or []),
                "search_strategies": list(candidate.get("search_strategies") or []),
                "applied_from_pack": str(candidate_pack_path),
                "candidate_rank": int(rank),
                "evidence_urls": evidence_urls,
            }
            selected_rows.append(row)
            keep_count += 1
            stats["candidates_selected"] += 1

    return selected_rows, stats


def _count_existing_target_edges(
    session: Any,
    *,
    method_tag: str,
    dataset_filters: list[str],
) -> int:
    query = """
    MATCH (d:Dataset)-[r:CITED_BY]->(:Publication)
    WHERE r.method_tag = $method_tag
      AND (
        size($dataset_filters) = 0 OR
        any(term IN $dataset_filters WHERE
          toLower(coalesce(d.id, '')) = term OR
          toLower(coalesce(d.dataset_id, '')) = term OR
          toLower(coalesce(d.source_repo_id, '')) = term OR
          any(alias IN coalesce(d.aliases, []) WHERE toLower(alias) = term)
        )
      )
    RETURN count(r) AS total
    """
    row = session.run(
        query,
        {"method_tag": method_tag, "dataset_filters": dataset_filters},
    ).single()
    return int((row or {}).get("total") or 0)


def _prune_existing_target_edges(
    session: Any,
    *,
    method_tag: str,
    dataset_filters: list[str],
) -> int:
    query = """
    MATCH (d:Dataset)-[r:CITED_BY]->(:Publication)
    WHERE r.method_tag = $method_tag
      AND (
        size($dataset_filters) = 0 OR
        any(term IN $dataset_filters WHERE
          toLower(coalesce(d.id, '')) = term OR
          toLower(coalesce(d.dataset_id, '')) = term OR
          toLower(coalesce(d.source_repo_id, '')) = term OR
          any(alias IN coalesce(d.aliases, []) WHERE toLower(alias) = term)
        )
      )
    WITH collect(r) AS rels
    FOREACH (rel IN rels | DELETE rel)
    RETURN size(rels) AS deleted
    """
    row = session.run(
        query,
        {"method_tag": method_tag, "dataset_filters": dataset_filters},
    ).single()
    return int((row or {}).get("deleted") or 0)


def _count_dataset_matches(session: Any, rows: list[dict[str, Any]]) -> dict[str, int]:
    query = """
    UNWIND $rows AS row
    OPTIONAL MATCH (d:Dataset)
    WHERE any(term IN row.dataset_lookup_terms WHERE
      toLower(coalesce(d.id, '')) = toLower(term) OR
      toLower(coalesce(d.dataset_id, '')) = toLower(term) OR
      toLower(coalesce(d.source_repo_id, '')) = toLower(term) OR
      any(alias IN coalesce(d.aliases, []) WHERE toLower(alias) = toLower(term))
    )
    WITH row, head(collect(DISTINCT d)) AS d
    RETURN count(row) AS selected_rows,
           count(CASE WHEN d IS NOT NULL THEN 1 END) AS matched_rows,
           count(DISTINCT d) AS matched_datasets
    """
    row = session.run(query, {"rows": rows}).single()
    return {
        "selected_rows": int((row or {}).get("selected_rows") or 0),
        "matched_rows": int((row or {}).get("matched_rows") or 0),
        "matched_datasets": int((row or {}).get("matched_datasets") or 0),
    }


def _apply_rows(session: Any, rows: list[dict[str, Any]]) -> dict[str, int]:
    query = """
    UNWIND $rows AS row
    OPTIONAL MATCH (d:Dataset)
    WHERE any(term IN row.dataset_lookup_terms WHERE
      toLower(coalesce(d.id, '')) = toLower(term) OR
      toLower(coalesce(d.dataset_id, '')) = toLower(term) OR
      toLower(coalesce(d.source_repo_id, '')) = toLower(term) OR
      any(alias IN coalesce(d.aliases, []) WHERE toLower(alias) = toLower(term))
    )
    WITH row, head(collect(DISTINCT d)) AS d
    WHERE d IS NOT NULL
    MERGE (p:Publication {id: row.publication_id})
    ON CREATE SET
      p.__openneuro_pub_created = true,
      p.created_at = datetime(),
      p.source = row.publication_source,
      p.method_tag = row.method_tag,
      p.applied_from_pack = row.applied_from_pack,
      p.title = row.title,
      p.doi = row.doi,
      p.pmid = row.pmid,
      p.pmcid = row.pmcid,
      p.journal = row.journal,
      p.year = row.year,
      p.reference = row.reference,
      p.dataset_id = row.dataset_primary_id,
      p.legacy_accession = row.legacy_accession
    SET
      p.source = coalesce(p.source, row.publication_source),
      p.method_tag = coalesce(p.method_tag, row.method_tag),
      p.applied_from_pack = coalesce(p.applied_from_pack, row.applied_from_pack),
      p.title = coalesce(p.title, row.title),
      p.doi = coalesce(p.doi, row.doi),
      p.pmid = coalesce(p.pmid, row.pmid),
      p.pmcid = coalesce(p.pmcid, row.pmcid),
      p.journal = coalesce(p.journal, row.journal),
      p.year = coalesce(p.year, row.year),
      p.reference = coalesce(p.reference, row.reference),
      p.dataset_id = coalesce(p.dataset_id, row.dataset_primary_id),
      p.legacy_accession = coalesce(p.legacy_accession, row.legacy_accession),
      p.aliases = coalesce(p.aliases, []) + [
        alias IN row.publication_aliases
        WHERE NOT alias IN coalesce(p.aliases, [])
      ],
      p.dataset_ids = coalesce(p.dataset_ids, []) + [
        item IN row.dataset_ids
        WHERE NOT item IN coalesce(p.dataset_ids, [])
      ]
    MERGE (d)-[r:CITED_BY {method_tag: row.method_tag}]->(p)
    ON CREATE SET
      r.__openneuro_pub_rel_created = true,
      r.created_at = datetime(),
      r.source = row.relationship_source,
      r.match_score = row.match_score,
      r.match_reasons = row.match_reasons,
      r.search_strategies = row.search_strategies,
      r.applied_from_pack = row.applied_from_pack,
      r.candidate_rank = row.candidate_rank,
      r.evidence_urls = row.evidence_urls
    SET
      r.source = coalesce(r.source, row.relationship_source),
      r.match_score = coalesce(r.match_score, row.match_score),
      r.match_reasons = coalesce(r.match_reasons, row.match_reasons),
      r.search_strategies = coalesce(r.search_strategies, row.search_strategies),
      r.applied_from_pack = coalesce(r.applied_from_pack, row.applied_from_pack),
      r.candidate_rank = coalesce(r.candidate_rank, row.candidate_rank),
      r.evidence_urls = coalesce(r.evidence_urls, row.evidence_urls)
    RETURN count(row) AS matched_rows,
           count(DISTINCT d) AS matched_datasets,
           count(DISTINCT CASE WHEN p.__openneuro_pub_created THEN p END) AS created_publications,
           count(DISTINCT CASE WHEN r.__openneuro_pub_rel_created THEN r END) AS created_edges
    """
    row = session.run(query, {"rows": rows}).single()
    return {
        "matched_rows": int((row or {}).get("matched_rows") or 0),
        "matched_datasets": int((row or {}).get("matched_datasets") or 0),
        "created_publications": int((row or {}).get("created_publications") or 0),
        "created_edges": int((row or {}).get("created_edges") or 0),
    }


def _cleanup_temp_flags(session: Any) -> dict[str, int]:
    pub_query = """
    MATCH (p:Publication)
    WHERE p.__openneuro_pub_created = true
    REMOVE p.__openneuro_pub_created
    RETURN count(p) AS cleaned
    """
    rel_query = """
    MATCH ()-[r:CITED_BY]->()
    WHERE r.__openneuro_pub_rel_created = true
    REMOVE r.__openneuro_pub_rel_created
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
    candidate_pack = args.candidate_pack.expanduser().resolve()
    reports = _load_candidate_reports(candidate_pack)
    dataset_filters = {
        key
        for item in (args.dataset_ids or [])
        for key in {_normalize_dataset_key(item), _clean_text(item).lower()}
        if key
    }
    selected_rows, selection_stats = _select_candidate_rows(
        reports,
        dataset_filters=dataset_filters,
        min_score=float(args.min_score),
        max_candidates_per_dataset=int(args.max_candidates_per_dataset),
        allow_title_only=bool(args.allow_title_only),
        candidate_pack_path=candidate_pack,
        method_tag=str(args.method_tag),
    )

    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "candidate_pack": str(candidate_pack),
        "method_tag": str(args.method_tag),
        "min_score": float(args.min_score),
        "max_candidates_per_dataset": int(args.max_candidates_per_dataset),
        "allow_title_only": bool(args.allow_title_only),
        "dataset_filters": sorted(dataset_filters),
        "selection": selection_stats,
        "selected_pairs": [
            {
                "dataset_id": row["dataset_id"],
                "dataset_kg_id": row["dataset_kg_id"],
                "publication_id": row["publication_id"],
                "title": row["title"],
                "doi": row["doi"],
                "pmid": row["pmid"],
                "match_score": row["match_score"],
                "candidate_rank": row["candidate_rank"],
            }
            for row in selected_rows
        ],
        "graph": {
            "targeted_existing_edges": 0,
            "deleted_existing_edges": 0,
            "matched_rows": 0,
            "matched_datasets": 0,
            "missing_dataset_rows": 0,
            "created_publications": 0,
            "created_edges": 0,
            "existing_edges": 0,
            "cleanup": {},
            "stats_skipped": False,
        },
    }

    needs_db = (not args.dry_run) or bool(args.prune_method_tag_first) or bool(
        args.neo4j_password
    )
    if needs_db and not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    if needs_db:
        with GraphDatabase.driver(
            str(args.neo4j_uri),
            auth=(str(args.neo4j_user), str(args.neo4j_password)),
        ) as driver:
            with driver.session(database=args.neo4j_database or None) as session:
                targeted_existing_edges = _count_existing_target_edges(
                    session,
                    method_tag=str(args.method_tag),
                    dataset_filters=sorted(dataset_filters),
                )
                report["graph"]["targeted_existing_edges"] = targeted_existing_edges

                if args.prune_method_tag_first and not args.dry_run:
                    report["graph"]["deleted_existing_edges"] = _prune_existing_target_edges(
                        session,
                        method_tag=str(args.method_tag),
                        dataset_filters=sorted(dataset_filters),
                    )

                match_stats = _count_dataset_matches(session, selected_rows)
                report["graph"]["matched_rows"] = match_stats["matched_rows"]
                report["graph"]["matched_datasets"] = match_stats["matched_datasets"]
                report["graph"]["missing_dataset_rows"] = max(
                    match_stats["selected_rows"] - match_stats["matched_rows"], 0
                )

                if not args.dry_run and selected_rows:
                    apply_stats = _apply_rows(session, selected_rows)
                    report["graph"]["matched_rows"] = apply_stats["matched_rows"]
                    report["graph"]["matched_datasets"] = apply_stats["matched_datasets"]
                    report["graph"]["missing_dataset_rows"] = max(
                        len(selected_rows) - apply_stats["matched_rows"], 0
                    )
                    report["graph"]["created_publications"] = apply_stats[
                        "created_publications"
                    ]
                    report["graph"]["created_edges"] = apply_stats["created_edges"]
                    report["graph"]["existing_edges"] = max(
                        apply_stats["matched_rows"] - apply_stats["created_edges"], 0
                    )
                    report["graph"]["cleanup"] = _cleanup_temp_flags(session)
    else:
        report["graph"]["stats_skipped"] = True

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
