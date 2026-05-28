#!/usr/bin/env python3
"""Run targeted non-title regeneration for bounded title-only benchmark rows."""

from __future__ import annotations

import argparse
import json
import logging
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from brain_researcher.services.neurokg.etl import gabriel_generator as gg
from brain_researcher.services.neurokg.etl.loaders.scholarly_metadata_loader import (
    DEFAULT_CACHE_DIR,
    ScholarlyMetadataLoader,
)
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

logger = logging.getLogger(__name__)
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@dataclass
class RegenerationOutcome:
    accepted_records: list[dict[str, Any]]
    zero_records: list[dict[str, Any]]
    title_only_rejected: list[dict[str, Any]]
    target_mismatch: list[dict[str, Any]]
    unresolved_publications: list[dict[str, Any]]
    parse_errors: list[dict[str, Any]]
    raw_payloads: list[dict[str, Any]]


def _failure_payload(
    *,
    generator: gg.GabrielPipelineGenerator,
    paper_id: str,
    row: dict[str, Any],
    exc: Exception,
    raw_path: Path,
    phase: str,
    run_id: str,
) -> dict[str, Any]:
    failure_reason = generator._classify_llm_failure(exc)
    return {
        "paper_id": paper_id,
        "paper_title": str(row.get("paper_title") or "").strip(),
        "target_id": str(row.get("target_id") or "").strip(),
        "target_label": str(row.get("target_label") or "").strip(),
        "claim_id": str(row.get("claim_id") or "").strip(),
        "run_id": str(row.get("run_id") or "").strip(),
        "source_review_bucket": str(
            row.get("regeneration_bucket")
            or row.get("source_review_bucket")
            or ""
        ).strip(),
        "source_bucket_reason": str(
            row.get("bucket_reason") or row.get("source_bucket_reason") or ""
        ).strip(),
        "evidence_section": str(
            row.get("source_evidence_section") or row.get("evidence_section") or ""
        ).strip(),
        "error": str(exc),
        "failure_reason": failure_reason,
        "phase": phase,
        "raw_response_path": str(raw_path),
        "raw_payload": {
            "run_id": run_id,
            "paper_id": paper_id,
            "target_id": str(row.get("target_id") or "").strip(),
            "generated_at": _utc_now_iso(),
            "status": "error",
            "failure_reason": failure_reason,
            "response_text": "",
            "response_meta": {},
            "error": str(exc),
            "raw_response_path": str(raw_path),
        },
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regeneration-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Scholarly metadata cache used to resolve abstract/body text.",
    )
    parser.add_argument(
        "--model",
        default="gemini/gemini-2.5-flash",
        help="LLM model hint for targeted regeneration.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional row limit for debugging (0 = all rows).",
    )
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write(
                "\t".join(
                    str(row.get(column, "")).replace("\t", " ").replace("\n", " ")
                    for column in columns
                )
                + "\n"
            )


def _slugify(value: str) -> str:
    return gg._slugify(value)  # type: ignore[attr-defined]


def _normalize_pmid(value: Any) -> str | None:
    return gg._normalize_pmid(value)  # type: ignore[attr-defined]


def _normalize_doi(value: Any) -> str | None:
    normalized = gg._normalize_doi(value)  # type: ignore[attr-defined]
    if normalized in {"nan", "none", "null"}:
        return None
    return normalized


def _doi_from_paper_id(paper_id: str) -> str | None:
    raw = str(paper_id or "").strip()
    if raw.startswith("doi:"):
        return _normalize_doi(raw.split(":", 1)[1])
    if not raw.startswith("paper:10_"):
        return None
    slug = raw.split(":", 1)[1]
    parts = slug.split("_")
    if len(parts) < 3 or parts[0] != "10":
        return None
    return f"{parts[0]}.{parts[1]}/" + ".".join(parts[2:])


def _targeted_publication_query(
    *,
    paper_ids: Sequence[str],
    pmids: Sequence[str],
    dois: Sequence[str],
) -> list[dict[str, Any]]:
    query = """
    MATCH (p:Publication)
    WITH p,
         CASE
             WHEN p.doi IS NULL THEN NULL
             WHEN trim(toLower(toString(p.doi))) = 'nan' THEN NULL
             ELSE trim(toLower(toString(p.doi)))
         END AS doi_norm
    WHERE coalesce(toString(p.id), '') IN $paper_ids
       OR coalesce(toString(p.pmid), '') IN $pmids
       OR coalesce(doi_norm, '') IN $dois
    RETURN
        coalesce(toString(p.id), '') AS paper_id,
        coalesce(toString(p.pmid), '') AS pmid,
        doi_norm AS doi,
        coalesce(toString(p.title), toString(p.name), '') AS title,
        coalesce(toString(p.abstract), toString(p.summary), toString(p.description), '') AS abstract,
        coalesce(p.year, p.publication_year) AS year,
        coalesce(toString(p.journal), toString(p.source), '') AS journal
    """
    try:
        db = require_neo4j_db(preload_cache=False)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("Skipping targeted Neo4j publication query: %s", exc)
        return []
    try:
        return db.execute_query(
            query,
            {
                "paper_ids": list(paper_ids),
                "pmids": list(pmids),
                "dois": [str(value).lower() for value in dois],
            },
        )
    finally:
        db.close()


def _seed_from_row_and_db(
    row: dict[str, Any],
    hit: dict[str, Any],
) -> gg.PublicationSeed:
    requested_paper_id = str(row.get("paper_id") or "").strip()
    return gg.PublicationSeed(
        paper_id=requested_paper_id or str(hit.get("paper_id") or "").strip(),
        title=str(hit.get("title") or row.get("paper_title") or requested_paper_id).strip(),
        abstract=str(hit.get("abstract") or "").strip(),
        pmid=_normalize_pmid(hit.get("pmid")),
        doi=_normalize_doi(hit.get("doi")),
        year=gg._coerce_int(hit.get("year")),  # type: ignore[attr-defined]
        journal=gg._clean_text(hit.get("journal")),  # type: ignore[attr-defined]
        source="targeted_neo4j",
    )


def _resolve_publication_seeds(
    rows: Sequence[dict[str, Any]],
    *,
    cache_dir: Path,
) -> tuple[dict[str, gg.PublicationSeed], list[dict[str, Any]]]:
    paper_ids = [str(row.get("paper_id") or "").strip() for row in rows]
    pmid_map = {
        paper_id: _normalize_pmid(paper_id.split(":", 1)[1])
        for paper_id in paper_ids
        if paper_id.startswith("pmid:")
    }
    doi_map = {
        paper_id: (_normalize_doi(paper_id.split(":", 1)[1]) if paper_id.startswith("doi:") else _doi_from_paper_id(paper_id))
        for paper_id in paper_ids
    }

    resolved: dict[str, gg.PublicationSeed] = {}
    unresolved_rows: list[dict[str, Any]] = []

    db_rows = _targeted_publication_query(
        paper_ids=paper_ids,
        pmids=[value for value in pmid_map.values() if value],
        dois=[value for value in doi_map.values() if value],
    )
    by_exact_paper_id = {
        str(item.get("paper_id") or "").strip(): item for item in db_rows if item.get("paper_id")
    }
    by_pmid = {
        _normalize_pmid(item.get("pmid")): item for item in db_rows if _normalize_pmid(item.get("pmid"))
    }
    by_doi = {
        _normalize_doi(item.get("doi")): item for item in db_rows if _normalize_doi(item.get("doi"))
    }

    for row in rows:
        paper_id = str(row.get("paper_id") or "").strip()
        hit = by_exact_paper_id.get(paper_id)
        if hit is None and paper_id in pmid_map:
            hit = by_pmid.get(pmid_map[paper_id])
        if hit is None:
            hit = by_doi.get(doi_map.get(paper_id))
        if hit is not None:
            resolved[paper_id] = _seed_from_row_and_db(row, hit)

    unresolved_candidates = [row for row in rows if str(row.get("paper_id") or "").strip() not in resolved]
    doi_loader = ScholarlyMetadataLoader(cache_dir=str(cache_dir))
    doi_to_row = {
        doi_map[str(row.get("paper_id") or "").strip()]: row
        for row in unresolved_candidates
        if doi_map.get(str(row.get("paper_id") or "").strip())
    }
    generator = gg.GabrielPipelineGenerator(output_root=Path("/tmp"), cache_dir=cache_dir)
    if doi_to_row:
        # Trigger harvest/update of Crossref/OpenAlex cache files first, then read
        # back the raw cache payloads so we retain OpenAlex abstract_inverted_index.
        doi_loader.load_records(dois=list(doi_to_row))
        cache_seed_index = generator._load_cache_seed_index_for_dois(set(doi_to_row))  # type: ignore[attr-defined]
        for doi, row in doi_to_row.items():
            seed = cache_seed_index.get(doi)
            if seed is None:
                continue
            paper_id = str(row.get("paper_id") or "").strip()
            resolved[paper_id] = gg.PublicationSeed(
                paper_id=paper_id,
                title=seed.title or str(row.get("paper_title") or paper_id),
                abstract=seed.abstract,
                pmid=seed.pmid,
                doi=seed.doi,
                year=seed.year,
                journal=seed.journal,
                keywords=seed.keywords,
                body=seed.body,
                source="targeted_cache_or_remote",
            )

    still_unresolved = [row for row in rows if str(row.get("paper_id") or "").strip() not in resolved]
    for row in still_unresolved:
        paper_id = str(row.get("paper_id") or "").strip()
        doi = doi_map.get(paper_id)
        title = str(row.get("paper_title") or "").strip()
        abstract, pmid = _fetch_pubmed_abstract(doi=doi, title=title)
        if not abstract:
            continue
        resolved[paper_id] = gg.PublicationSeed(
            paper_id=paper_id,
            title=title or paper_id,
            abstract=abstract,
            pmid=pmid,
            doi=doi,
            source="targeted_pubmed_fallback",
        )

    for row in rows:
        paper_id = str(row.get("paper_id") or "").strip()
        seed = resolved.get(paper_id)
        if seed is None or not (seed.abstract or seed.body):
            unresolved_rows.append(
                {
                    "paper_id": paper_id,
                    "paper_title": str(row.get("paper_title") or "").strip(),
                    "target_id": str(row.get("target_id") or "").strip(),
                    "target_label": str(row.get("target_label") or "").strip(),
                    "reason": "publication_unresolved_or_no_non_title_text",
                }
            )

    return resolved, unresolved_rows


def _fetch_pubmed_abstract(*, doi: str | None, title: str) -> tuple[str, str | None]:
    queries: list[str] = []
    if doi:
        queries.append(f"{doi}[AID]")
    if title:
        queries.append(f"\"{title}\"[Title]")

    for query in queries:
        try:
            search_resp = requests.get(
                PUBMED_ESEARCH_URL,
                params={
                    "db": "pubmed",
                    "retmode": "json",
                    "retmax": 1,
                    "term": query,
                },
                timeout=20,
            )
            search_resp.raise_for_status()
            pmids = (
                search_resp.json().get("esearchresult", {}).get("idlist") or []
            )
            if not pmids:
                continue
            pmid = str(pmids[0]).strip()
            fetch_resp = requests.get(
                PUBMED_EFETCH_URL,
                params={
                    "db": "pubmed",
                    "retmode": "xml",
                    "id": pmid,
                },
                timeout=20,
            )
            fetch_resp.raise_for_status()
            root = ET.fromstring(fetch_resp.text)
            abstract_parts = [
                "".join(node.itertext()).strip()
                for node in root.findall(".//Abstract/AbstractText")
                if "".join(node.itertext()).strip()
            ]
            if abstract_parts:
                return " ".join(abstract_parts), pmid
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("PubMed abstract fallback failed for %s: %s", query, exc)
            continue
    return "", None


def _targeted_prompt(
    publication: gg.PublicationSeed,
    row: dict[str, Any],
    *,
    title_overlap_guard: bool = False,
) -> str:
    requested_target = {
        "type": str(row.get("target_type") or "").strip(),
        "id": str(row.get("target_id") or "").strip(),
        "label": str(row.get("target_label") or "").strip(),
    }
    prefer_sections = list(row.get("prefer_sections") or ["abstract", "methods", "results", "discussion"])
    schema = gg.PROMPT_TEMPLATE.replace("{max_records}", "1")
    payload = json.dumps(publication.to_prompt_payload(), ensure_ascii=True, indent=2)
    target_payload = json.dumps(requested_target, ensure_ascii=True, indent=2)
    extra_guard = ""
    if title_overlap_guard:
        extra_guard = (
            "9. Your previous answer reused the paper title as evidence. On this retry, "
            "the evidence quote must come from abstract/body text and must not repeat, "
            "contain, or be contained in the paper title after normalization. If you "
            "cannot satisfy that constraint, return {\"records\": []}.\n"
        )

    return (
        "You are regenerating a GABRIEL measurement candidate for exactly one requested target.\n"
        "Return JSON only.\n\n"
        f"{schema}\n\n"
        "Additional regeneration rules:\n"
        "1. Return either zero records or one record.\n"
        f"2. If you return a record, the target must match this requested target exactly:\n{target_payload}\n"
        "3. Use only non-title evidence from abstract, methods, results, discussion, or body text.\n"
        "4. If only the title supports the target or no non-title evidence is available, return {\"records\": []}.\n"
        f"5. Prefer evidence sections in this order: {', '.join(prefer_sections)}.\n"
        "6. Keep mapping.canonical_id equal to the requested target id.\n"
        "7. Do not propose alternative targets.\n"
        "8. The evidence quote must not simply restate the paper title. It must be "
        "a non-title sentence or phrase from abstract/body text.\n"
        f"{extra_guard}\n"
        f"Publication metadata:\n{payload}\n\n"
        "Return strict JSON now. Do not include markdown fences, comments, prose, or trailing commas."
    )


def _route_generation(
    generator: gg.GabrielPipelineGenerator,
    *,
    publication: gg.PublicationSeed,
    row: dict[str, Any],
    title_overlap_guard: bool = False,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    prompt = _targeted_prompt(
        publication,
        row,
        title_overlap_guard=title_overlap_guard,
    )
    attempt_limit = max(int(generator._llm_retry_limit()), 1)
    last_exc: Exception | None = None

    for attempt in range(1, attempt_limit + 1):
        try:
            result = generator.router.route_chat(
                prompt=prompt,
                model_hint=generator.model_hint,
                strict_json=True,
            )
            response_text = result.text or ""
            response_meta = {
                "provider": result.metadata.provider,
                "model": result.metadata.model,
                "route": result.metadata.route,
                "transport": result.metadata.transport,
                "fallback_reason": result.metadata.fallback_reason,
                "usage": result.metadata.usage or {},
                "prompt_hash": gg._stable_hash(prompt),  # type: ignore[attr-defined]
                "retry_attempt": attempt,
                "title_overlap_guard": bool(title_overlap_guard),
            }
            payload = generator._parse_json_payload(response_text)
            records = generator._extract_records(payload)
            return records, response_text, response_meta
        except Exception as exc:
            last_exc = exc
            failure_reason = generator._classify_llm_failure(exc)
            if attempt >= attempt_limit or not generator._is_retryable_failure(failure_reason):
                raise
            prompt = generator._build_retry_prompt(
                prompt=prompt,
                attempt=attempt,
                failure_reason=failure_reason,
            )

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Generation failed without a retryable exception")


def _target_matches_requested(record: dict[str, Any], row: dict[str, Any]) -> bool:
    target = dict(record.get("target") or {})
    requested_type = str(row.get("target_type") or "").strip().lower()
    requested_id = str(row.get("target_id") or "").strip().lower()
    requested_label = _slugify(str(row.get("target_label") or "").strip())
    candidate_type = str(target.get("type") or "").strip().lower()
    candidate_id = str(target.get("id") or "").strip().lower()
    candidate_label = _slugify(str(target.get("label") or "").strip())
    if candidate_type and candidate_type != requested_type:
        return False
    if requested_type == "concept":
        return bool(requested_id and candidate_id and candidate_id == requested_id)
    if candidate_id:
        return candidate_id == requested_id
    return bool(candidate_label and candidate_label == requested_label)


def _merge_requested_target(record: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    requested_target = {
        "type": str(row.get("target_type") or "").strip(),
        "id": str(row.get("target_id") or "").strip(),
        "label": str(row.get("target_label") or "").strip(),
    }
    requested_mapping = {
        "canonical_id": requested_target["id"],
        "mapping_type": "exact",
        "mapping_confidence": float(
            record.get("mapping", {}).get("mapping_confidence")
            if record.get("mapping", {}).get("mapping_confidence") is not None
            else 1.0
        ),
    }
    merged = dict(record)
    merged["target"] = requested_target
    mapping = dict(record.get("mapping") or {})
    mapping.update(requested_mapping)
    merged["mapping"] = mapping
    return merged


def run_regeneration(
    rows: Sequence[dict[str, Any]],
    *,
    cache_dir: Path,
    output_dir: Path,
    model_hint: str,
) -> RegenerationOutcome:
    generator = gg.GabrielPipelineGenerator(
        output_root=output_dir,
        cache_dir=cache_dir,
        model_hint=model_hint,
        max_records_per_publication=1,
    )
    resolved_publications, unresolved_publications = _resolve_publication_seeds(rows, cache_dir=cache_dir)
    accepted_records: list[dict[str, Any]] = []
    zero_records: list[dict[str, Any]] = []
    title_only_rejected: list[dict[str, Any]] = []
    target_mismatch: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    raw_payloads: list[dict[str, Any]] = []

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for index, row in enumerate(rows, start=1):
        paper_id = str(row.get("paper_id") or "").strip()
        publication = resolved_publications.get(paper_id)
        if publication is None or not (publication.abstract or publication.body):
            continue
        run_id = f"title-regen-{_slugify(paper_id)}-{index:04d}"
        raw_path = raw_dir / f"{run_id}.json"

        try:
            records, response_text, response_meta = _route_generation(
                generator,
                publication=publication,
                row=row,
            )
        except Exception as exc:
            failure = _failure_payload(
                generator=generator,
                paper_id=paper_id,
                row=row,
                exc=exc,
                raw_path=raw_path,
                phase="initial_generation",
                run_id=run_id,
            )
            parse_errors.append({k: v for k, v in failure.items() if k != "raw_payload"})
            raw_payloads.append(dict(failure["raw_payload"]))
            raw_path.write_text(
                json.dumps(raw_payloads[-1], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            continue

        raw_payload = {
            "run_id": run_id,
            "paper_id": paper_id,
            "target_id": str(row.get("target_id") or "").strip(),
            "generated_at": _utc_now_iso(),
            "status": "ok",
            "response_text": response_text,
            "response_meta": response_meta,
            "raw_response_path": str(raw_path),
        }
        raw_payloads.append(raw_payload)
        raw_path.write_text(
            json.dumps(raw_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if not records:
            zero_records.append(
                {
                    "paper_id": paper_id,
                    "paper_title": str(row.get("paper_title") or "").strip(),
                    "target_id": str(row.get("target_id") or "").strip(),
                    "target_label": str(row.get("target_label") or "").strip(),
                    "reason": "no_non_title_record_returned",
                    "raw_response_path": str(raw_path),
                }
            )
            continue

        base_record = records[0]
        if not _target_matches_requested(base_record, row):
            target_mismatch.append(
                {
                    "paper_id": paper_id,
                    "paper_title": str(row.get("paper_title") or "").strip(),
                    "requested_target_id": str(row.get("target_id") or "").strip(),
                    "requested_target_label": str(row.get("target_label") or "").strip(),
                    "returned_target": dict(base_record.get("target") or {}),
                    "raw_response_path": str(raw_path),
                }
            )
            continue

        finalized = generator._finalize_record(
            publication=publication,
            base_record=_merge_requested_target(base_record, row),
            run_id=run_id,
            raw_response_path=str(raw_path),
            prompt_hash=str(response_meta.get("prompt_hash") or ""),
            template_hash=gg._stable_hash(gg.PROMPT_TEMPLATE),  # type: ignore[attr-defined]
            model_name=str(response_meta.get("model") or model_hint),
            timestamp=_utc_now_iso(),
            measurement_index=1,
        )
        finalized["regeneration_source"] = {
            "source_claim_id": str(row.get("claim_id") or "").strip(),
            "source_run_id": str(row.get("run_id") or "").strip(),
            "source_review_bucket": str(
                row.get("regeneration_bucket")
                or row.get("source_review_bucket")
                or "salvage_task_or_region"
            ).strip(),
            "source_bucket_reason": str(
                row.get("bucket_reason") or row.get("source_bucket_reason") or ""
            ).strip(),
            "source_proposed_action": str(row.get("proposed_action") or "").strip(),
            "source_evidence_section": str(
                row.get("source_evidence_section") or row.get("evidence_section") or ""
            ).strip(),
        }
        if finalized.get("signals", {}).get("title_only_evidence"):
            retry_raw_path = raw_dir / f"{run_id}-title_guard.json"
            try:
                retry_records, retry_response_text, retry_response_meta = _route_generation(
                    generator,
                    publication=publication,
                    row=row,
                    title_overlap_guard=True,
                )
            except Exception as exc:
                failure = _failure_payload(
                    generator=generator,
                    paper_id=paper_id,
                    row=row,
                    exc=exc,
                    raw_path=retry_raw_path,
                    phase="title_overlap_retry",
                    run_id=f"{run_id}-title_guard",
                )
                parse_errors.append({k: v for k, v in failure.items() if k != "raw_payload"})
                retry_payload = dict(failure["raw_payload"])
                raw_payloads.append(retry_payload)
                retry_raw_path.write_text(
                    json.dumps(retry_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                continue

            retry_payload = {
                "run_id": f"{run_id}-title_guard",
                "paper_id": paper_id,
                "target_id": str(row.get("target_id") or "").strip(),
                "generated_at": _utc_now_iso(),
                "status": "ok",
                "response_text": retry_response_text,
                "response_meta": retry_response_meta,
                "raw_response_path": str(retry_raw_path),
            }
            raw_payloads.append(retry_payload)
            retry_raw_path.write_text(
                json.dumps(retry_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if not retry_records:
                zero_records.append(
                    {
                        "paper_id": paper_id,
                        "paper_title": str(row.get("paper_title") or "").strip(),
                        "target_id": str(row.get("target_id") or "").strip(),
                        "target_label": str(row.get("target_label") or "").strip(),
                        "reason": "no_non_title_record_after_title_overlap_retry",
                        "raw_response_path": str(retry_raw_path),
                    }
                )
                continue

            retry_base_record = retry_records[0]
            if not _target_matches_requested(retry_base_record, row):
                target_mismatch.append(
                    {
                        "paper_id": paper_id,
                        "paper_title": str(row.get("paper_title") or "").strip(),
                        "requested_target_id": str(row.get("target_id") or "").strip(),
                        "requested_target_label": str(row.get("target_label") or "").strip(),
                        "returned_target": dict(retry_base_record.get("target") or {}),
                        "raw_response_path": str(retry_raw_path),
                    }
                )
                continue

            finalized = generator._finalize_record(
                publication=publication,
                base_record=_merge_requested_target(retry_base_record, row),
                run_id=f"{run_id}-title_guard",
                raw_response_path=str(retry_raw_path),
                prompt_hash=str(retry_response_meta.get("prompt_hash") or ""),
                template_hash=gg._stable_hash(gg.PROMPT_TEMPLATE),  # type: ignore[attr-defined]
                model_name=str(retry_response_meta.get("model") or model_hint),
                timestamp=_utc_now_iso(),
                measurement_index=1,
            )
            finalized["regeneration_source"] = {
                "source_claim_id": str(row.get("claim_id") or "").strip(),
                "source_run_id": str(row.get("run_id") or "").strip(),
                "source_review_bucket": str(
                    row.get("regeneration_bucket")
                    or row.get("source_review_bucket")
                    or "salvage_task_or_region"
                ).strip(),
                "source_bucket_reason": str(
                    row.get("bucket_reason") or row.get("source_bucket_reason") or ""
                ).strip(),
                "source_proposed_action": str(row.get("proposed_action") or "").strip(),
                "source_evidence_section": str(
                    row.get("source_evidence_section") or row.get("evidence_section") or ""
                ).strip(),
            }
            if finalized.get("signals", {}).get("title_only_evidence"):
                title_only_rejected.append(
                    {
                        "paper_id": paper_id,
                        "paper_title": str(row.get("paper_title") or "").strip(),
                        "target_id": str(row.get("target_id") or "").strip(),
                        "target_label": str(row.get("target_label") or "").strip(),
                        "evidence_section": str(finalized.get("evidence", {}).get("section") or "").strip(),
                        "reason": "llm_returned_title_only_after_regeneration",
                        "raw_response_path": str(retry_raw_path),
                    }
                )
                continue
        accepted_records.append(finalized)

    return RegenerationOutcome(
        accepted_records=accepted_records,
        zero_records=zero_records,
        title_only_rejected=title_only_rejected,
        target_mismatch=target_mismatch,
        unresolved_publications=unresolved_publications,
        parse_errors=parse_errors,
        raw_payloads=raw_payloads,
    )


def _write_regeneration_outputs(
    outcome: RegenerationOutcome,
    *,
    regeneration_pack_path: Path,
    output_dir: Path,
    model_hint: str,
) -> dict[str, Any]:
    _write_jsonl(output_dir / "accepted_records.jsonl", outcome.accepted_records)
    _write_jsonl(output_dir / "zero_records.jsonl", outcome.zero_records)
    _write_jsonl(output_dir / "title_only_rejected.jsonl", outcome.title_only_rejected)
    _write_jsonl(output_dir / "target_mismatch.jsonl", outcome.target_mismatch)
    _write_jsonl(output_dir / "unresolved_publications.jsonl", outcome.unresolved_publications)
    _write_jsonl(output_dir / "parse_errors.jsonl", outcome.parse_errors)

    accepted_tsv_rows = [
        {
            "paper_id": str(row.get("paper", {}).get("id") or "").strip(),
            "paper_title": str(row.get("paper", {}).get("title") or "").strip(),
            "target_id": str(row.get("target", {}).get("id") or "").strip(),
            "target_label": str(row.get("target", {}).get("label") or "").strip(),
            "claim_id": str(row.get("claim", {}).get("id") or "").strip(),
            "claim_text": str(row.get("claim", {}).get("text") or "").strip(),
            "evidence_section": str(row.get("evidence", {}).get("section") or "").strip(),
            "evidence_quote": str(row.get("evidence", {}).get("quote") or "").strip(),
        }
        for row in outcome.accepted_records
    ]
    _write_tsv(
        output_dir / "accepted_records.tsv",
        accepted_tsv_rows,
        columns=[
            "paper_id",
            "paper_title",
            "target_id",
            "target_label",
            "claim_id",
            "claim_text",
            "evidence_section",
            "evidence_quote",
        ],
    )

    counts = {
        "accepted_records": len(outcome.accepted_records),
        "zero_records": len(outcome.zero_records),
        "title_only_rejected": len(outcome.title_only_rejected),
        "target_mismatch": len(outcome.target_mismatch),
        "unresolved_publications": len(outcome.unresolved_publications),
        "parse_errors": len(outcome.parse_errors),
        "rows_total": sum(
            [
                len(outcome.accepted_records),
                len(outcome.zero_records),
                len(outcome.title_only_rejected),
                len(outcome.target_mismatch),
                len(outcome.unresolved_publications),
                len(outcome.parse_errors),
            ]
        ),
    }
    summary = {
        "generated_at": _utc_now_iso(),
        "regeneration_pack_path": str(regeneration_pack_path),
        "model_hint": model_hint,
        "counts": counts,
        "artifacts": {
            "accepted_records_jsonl": str(output_dir / "accepted_records.jsonl"),
            "zero_records_jsonl": str(output_dir / "zero_records.jsonl"),
            "title_only_rejected_jsonl": str(output_dir / "title_only_rejected.jsonl"),
            "target_mismatch_jsonl": str(output_dir / "target_mismatch.jsonl"),
            "unresolved_publications_jsonl": str(output_dir / "unresolved_publications.jsonl"),
            "parse_errors_jsonl": str(output_dir / "parse_errors.jsonl"),
            "summary_json": str(output_dir / "regeneration_summary.json"),
        },
    }
    (output_dir / "regeneration_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    regeneration_pack_path = args.regeneration_pack.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = list(_iter_jsonl(regeneration_pack_path))
    if args.limit and int(args.limit) > 0:
        rows = rows[: int(args.limit)]

    outcome = run_regeneration(
        rows,
        cache_dir=args.cache_dir.expanduser().resolve(),
        output_dir=output_dir,
        model_hint=str(args.model or "").strip(),
    )
    summary = _write_regeneration_outputs(
        outcome,
        regeneration_pack_path=regeneration_pack_path,
        output_dir=output_dir,
        model_hint=str(args.model or "").strip(),
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
