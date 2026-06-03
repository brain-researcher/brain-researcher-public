"""Lens-endpoint implementation layer for the BR-KG API.

Carved out of ``br_kg/app.py``: the (non-route) functions that implement the
generic + disease lens endpoints — assembling entities / summaries / evidence
rows and collecting live task evidence and evidence paths. The thin
``@app.route`` handlers stay in ``app.py`` and call these by name (so test
``monkeypatch.setattr(app, "_kg_lens_generic_*", ...)`` still intercepts via the
re-export, and none of these functions call the patched ones internally).

These functions sit at the top of the helper call-tree, so they depend on a
broad set of app.py config constants, lower-level helpers (some themselves
re-exported from sibling carved modules), and the live ``neo4j_db`` / ``logger``
globals. Those all stay in ``app.py`` and are imported back LAZILY inside each
function (read at call time, so a test that patches ``app.neo4j_db`` is
honoured), keeping the dependency one-way: ``app -> lens_endpoints_impl``.

``app.py`` re-exports every name below so existing ``app.<name>`` references and
route handlers keep resolving.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any


def _collect_live_task_evidence(
    *,
    entity_id: str,
    entity_label: str,
    limit: int,
    types_set: set[str],
) -> tuple[dict[str, list[dict[str, Any]]], list[str], dict[str, Any]]:
    from brain_researcher.services.br_kg.app import (
        _csv_tokens,
        _run_deep_research_sync,
        _run_google_file_search,
        _utc_iso_now,
        logger,
    )
    now_ts = _utc_iso_now()
    groups: dict[str, list[dict[str, Any]]] = {
        "papers": [],
        "studies": [],
        "statmaps": [],
    }
    sources_used: list[str] = []
    diagnostics: dict[str, Any] = {
        "attempted": False,
        "api_key_present": False,
        "file_search_store_configured": False,
        "deep_research_status": "skipped",
        "file_search_status": "skipped",
        "gfs_reason": None,
        "gfs_call_count": 0,
        "gfs_stores_hit": [],
        "gfs_query_used": None,
        "error_codes": [],
        "hit_counts": {
            "papers": 0,
            "studies": 0,
            "statmaps": 0,
        },
    }
    if not ({"papers", "studies", "statmaps"} & types_set):
        return groups, sources_used, diagnostics

    diagnostics["attempted"] = True
    query = f"{entity_label} {entity_id} fMRI task contrast statmap papers"
    diagnostics["gfs_query_used"] = query
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    diagnostics["api_key_present"] = bool(api_key)
    store_names = (
        _csv_tokens(os.environ.get("BR_FILE_SEARCH_STORE_NAMES"))
        or _csv_tokens(os.environ.get("FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("BR_FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("GOOGLE_FILE_SEARCH_STORE"))
    )
    diagnostics["file_search_store_configured"] = bool(store_names)

    if not api_key:
        diagnostics["error_codes"] = _csv_tokens(
            list(diagnostics.get("error_codes") or []) + ["missing_api_key"]
        )
        return groups, sources_used, diagnostics

    diagnostics["deep_research_status"] = "attempted"
    try:
        deep_result = _run_deep_research_sync(
            {
                "query": query,
                "top_k": max(5, min(limit, 20)),
                "idempotency_key": f"live:{entity_id}:{int(datetime.utcnow().timestamp() * 1000)}",
            }
        )
        deep_status = str(deep_result.get("status") or "").strip().lower()
        if deep_status in {"ok", "partial", "cached"}:
            docs = (deep_result.get("result") or {}).get("documents") or []
            for doc in docs[:limit]:
                title = doc.get("title") or "Web-grounded evidence"
                url = doc.get("url")
                if "papers" in types_set:
                    groups["papers"].append(
                        {
                            "id": url or title,
                            "title": title,
                            "url": url,
                            "source_type": "web_grounded",
                            "source_channel": "deep_research_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
                if "studies" in types_set:
                    groups["studies"].append(
                        {
                            "id": url or title,
                            "name": title,
                            "url": url,
                            "source": "deep_research_live",
                            "source_channel": "deep_research_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
            diagnostics["deep_research_status"] = "ok" if docs else "empty"
            if docs:
                sources_used.append("deep_research_live")
        else:
            diagnostics["deep_research_status"] = "error"
            diagnostics["error_codes"] = _csv_tokens(
                list(diagnostics.get("error_codes") or [])
                + [f"deep_research_{deep_status or 'error'}"]
            )
    except Exception as exc:  # pragma: no cover - network/runtime variability
        diagnostics["deep_research_status"] = "error"
        diagnostics["error_codes"] = _csv_tokens(
            list(diagnostics.get("error_codes") or []) + ["deep_research_exception"]
        )
        logger.warning("live deep research fetch failed for %s: %s", entity_id, exc)

    diagnostics["file_search_status"] = "attempted"
    try:
        gfs_result = _run_google_file_search(query, top_k=max(5, min(limit, 20)))
        gfs_status = str(gfs_result.get("status") or "").strip().lower()
        if gfs_status == "ok":
            hits = gfs_result.get("hits") or []
            diagnostics["gfs_reason"] = gfs_result.get("reason")
            diagnostics["gfs_call_count"] = int(gfs_result.get("call_count") or 0)
            diagnostics["gfs_stores_hit"] = list(gfs_result.get("stores_hit") or [])
            diagnostics["gfs_query_used"] = (
                gfs_result.get("query_used") or gfs_result.get("query") or query
            )
            for hit in hits[:limit]:
                title = hit.get("title") or "File-search evidence"
                doc_id = hit.get("doc_id") or hit.get("doi") or hit.get("pmid") or title
                if "papers" in types_set:
                    groups["papers"].append(
                        {
                            "id": doc_id,
                            "pmid": hit.get("pmid"),
                            "doi": hit.get("doi"),
                            "title": title,
                            "description": hit.get("snippet"),
                            "source_type": "file_search",
                            "source_channel": "file_search_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
                if "studies" in types_set:
                    groups["studies"].append(
                        {
                            "id": doc_id,
                            "name": title,
                            "description": hit.get("snippet"),
                            "source": "file_search_live",
                            "source_channel": "file_search_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
                if "statmaps" in types_set:
                    text = f"{title} {hit.get('snippet') or ''}".lower()
                    if "statmap" in text or "z map" in text or "t map" in text:
                        groups["statmaps"].append(
                            {
                                "map_id": str(doc_id),
                                "contrast": title,
                                "source_channel": "file_search_live",
                                "path_type": "web_grounded",
                                "support_count": 1,
                                "freshness_ts": now_ts,
                            }
                        )
            diagnostics["file_search_status"] = "ok" if hits else "empty"
            if hits:
                sources_used.append("file_search_live")
        elif gfs_status in {"empty", "skipped"}:
            diagnostics["file_search_status"] = gfs_status
            diagnostics["gfs_reason"] = gfs_result.get("reason")
            diagnostics["gfs_call_count"] = int(gfs_result.get("call_count") or 0)
            diagnostics["gfs_stores_hit"] = list(gfs_result.get("stores_hit") or [])
            diagnostics["gfs_query_used"] = (
                gfs_result.get("query_used") or gfs_result.get("query") or query
            )
        else:
            diagnostics["file_search_status"] = "error"
            diagnostics["gfs_reason"] = gfs_result.get("reason")
            diagnostics["gfs_call_count"] = int(gfs_result.get("call_count") or 0)
            diagnostics["gfs_stores_hit"] = list(gfs_result.get("stores_hit") or [])
            diagnostics["gfs_query_used"] = (
                gfs_result.get("query_used") or gfs_result.get("query") or query
            )
            error_code = f"file_search_{gfs_status or 'error'}"
            diagnostics["error_codes"] = _csv_tokens(
                list(diagnostics.get("error_codes") or []) + [error_code]
            )
    except Exception as exc:  # pragma: no cover - network/runtime variability
        diagnostics["file_search_status"] = "error"
        diagnostics["error_codes"] = _csv_tokens(
            list(diagnostics.get("error_codes") or []) + ["file_search_exception"]
        )
        logger.warning("live file-search fetch failed for %s: %s", entity_id, exc)

    diagnostics["hit_counts"] = {
        "papers": len(groups.get("papers") or []),
        "studies": len(groups.get("studies") or []),
        "statmaps": len(groups.get("statmaps") or []),
    }
    return groups, sources_used, diagnostics


def _kg_lens_disease_entity_dataset_id_sets(
    *,
    entity_ids: list[str],
    seed_labels: list[str],
    scheme_filter: str | None,
    include_mediated: bool = True,
) -> dict[str, set[str]]:
    from brain_researcher.services.br_kg.app import (
        ONVOC_DATASET_LABELS,
        ONVOC_LINK_REL_TYPES,
        ONVOC_STATMAP_LABELS,
        STATMAP_DATASET_REL_TYPES,
        neo4j_db,
    )
    dedup_entity_ids = list(
        dict.fromkeys(
            str(entity_id).strip() for entity_id in entity_ids if str(entity_id).strip()
        )
    )
    if not dedup_entity_ids:
        return {}

    rows = neo4j_db.execute_query(
        """
        UNWIND $entity_ids AS entity_id
        MATCH (c)
        WHERE coalesce(c.id, elementId(c)) = entity_id
          AND any(lbl IN labels(c) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(c.scheme, '') = $scheme_filter
            OR toString(coalesce(c.id, '')) STARTS WITH 'ONVOC_'
          )
        CALL {
          WITH c
          OPTIONAL MATCH (c)-[:ABOUT]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
          RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS direct_ids
        }
        CALL {
          WITH c
          OPTIONAL MATCH (m)-[link]->(c)
          WHERE type(link) IN $onvoc_link_rel_types
            AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
          OPTIONAL MATCH (m)-[mdr]-(d)
          WHERE type(mdr) IN $statmap_dataset_rel_types
            AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
          WITH d
          WHERE d IS NOT NULL
          RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS mapped_ids
        }
        WITH coalesce(c.id, elementId(c)) AS id,
             direct_ids + CASE
               WHEN $include_mediated THEN mapped_ids
               ELSE []
             END AS dataset_ids
        UNWIND CASE WHEN size(dataset_ids) = 0 THEN [NULL] ELSE dataset_ids END AS dataset_id
        WITH id, collect(DISTINCT dataset_id) AS dedup_dataset_ids
        RETURN id,
               [x IN dedup_dataset_ids WHERE x IS NOT NULL] AS dataset_ids
        """,
        {
            "entity_ids": dedup_entity_ids,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "include_mediated": include_mediated,
            "dataset_labels": ONVOC_DATASET_LABELS,
            "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
            "statmap_labels": ONVOC_STATMAP_LABELS,
            "statmap_dataset_rel_types": STATMAP_DATASET_REL_TYPES,
        },
    )
    dataset_sets: dict[str, set[str]] = {
        entity_id: set() for entity_id in dedup_entity_ids
    }
    for row in rows:
        entity_id = str(row.get("id") or "").strip()
        if not entity_id:
            continue
        raw_ids = row.get("dataset_ids")
        if isinstance(raw_ids, list):
            dataset_sets[entity_id] = {
                str(dataset_id).strip()
                for dataset_id in raw_ids
                if str(dataset_id).strip()
            }
    return dataset_sets


def _kg_lens_generic_entities(lens: str, q: str, limit: int):
    from brain_researcher.services.br_kg.app import (
        BR_KG_DISEASE_CONNECTED_FIRST,
        GENERIC_CONNECTED_LABELS,
        LENS_REGISTRY,
        _collapse_entities_by_label,
        _disease_alias_candidate_ids,
        _disease_entity_matches_query,
        _disease_entity_query_mode,
        _enrich_task_entities,
        _lens_scheme_filter,
        _lens_seed_labels,
        _make_entity_row,
        neo4j_db,
    )
    seed_labels = _lens_seed_labels(lens)
    scheme_filter = _lens_scheme_filter(lens)

    if lens == "disease":
        query_text = str(q or "").strip().lower()
        path_mode = _disease_entity_query_mode(query_text)
        ranked_mode = path_mode == "ranked"
        candidate_limit = min(max(limit * 3, 300), 1200) if ranked_mode else limit
        params = {
            "candidate_limit": candidate_limit,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "disease_root_ids": list(LENS_REGISTRY[lens].get("disease_root_ids", [])),
            "connected_labels": GENERIC_CONNECTED_LABELS,
            "q": query_text,
            "apply_text_filter": ranked_mode,
            "alias_candidate_ids": (
                _disease_alias_candidate_ids(query_text) if ranked_mode else []
            ),
        }
        if ranked_mode and BR_KG_DISEASE_CONNECTED_FIRST:
            rows = neo4j_db.execute_query(
                """
                MATCH (root)
                WHERE root.id IN $disease_root_ids
                  AND any(lbl IN labels(root) WHERE lbl IN $seed_labels)
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(root.scheme, '') = $scheme_filter
                    OR root.id STARTS WITH 'ONVOC_'
                  )
                MATCH (n)-[:CLASSIFIED_UNDER*1..8]->(root)
                WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
                  AND coalesce(n.id, elementId(n)) IS NOT NULL
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(n.scheme, '') = $scheme_filter
                    OR coalesce(n.id, '') STARTS WITH 'ONVOC_'
                  )
                  AND trim(coalesce(n.label, n.name, n.title, '')) <> ''
                  AND (
                    $apply_text_filter = false
                    OR toLower(coalesce(n.label, n.name, n.title, n.id, elementId(n))) CONTAINS $q
                    OR toLower(coalesce(n.id, elementId(n), '')) CONTAINS $q
                    OR coalesce(n.id, elementId(n)) IN $alias_candidate_ids
                  )
                WITH DISTINCT n
                OPTIONAL MATCH (n)-[]-(m)
                WHERE any(lbl IN labels(m) WHERE lbl IN $connected_labels)
                WITH n, count(DISTINCT m) AS connected_score
                RETURN coalesce(n.id, elementId(n)) AS id,
                       coalesce(n.label, n.name, n.title, n.id, elementId(n)) AS label,
                       coalesce(n.category, n.type, head(labels(n))) AS category,
                       connected_score
                ORDER BY connected_score DESC, label
                LIMIT $candidate_limit
                """,
                params,
            )
        else:
            rows = neo4j_db.execute_query(
                """
                MATCH (root)
                WHERE root.id IN $disease_root_ids
                  AND any(lbl IN labels(root) WHERE lbl IN $seed_labels)
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(root.scheme, '') = $scheme_filter
                    OR root.id STARTS WITH 'ONVOC_'
                  )
                MATCH (n)-[:CLASSIFIED_UNDER*1..8]->(root)
                WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
                  AND coalesce(n.id, elementId(n)) IS NOT NULL
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(n.scheme, '') = $scheme_filter
                    OR coalesce(n.id, '') STARTS WITH 'ONVOC_'
                  )
                  AND trim(coalesce(n.label, n.name, n.title, '')) <> ''
                  AND (
                    $apply_text_filter = false
                    OR toLower(coalesce(n.label, n.name, n.title, n.id, elementId(n))) CONTAINS $q
                    OR toLower(coalesce(n.id, elementId(n), '')) CONTAINS $q
                    OR coalesce(n.id, elementId(n)) IN $alias_candidate_ids
                  )
                RETURN DISTINCT coalesce(n.id, elementId(n)) AS id,
                       coalesce(n.label, n.name, n.title, n.id, elementId(n)) AS label,
                       coalesce(n.category, n.type, head(labels(n))) AS category,
                       0 AS connected_score
                ORDER BY label
                LIMIT $candidate_limit
                """,
                params,
            )
        payload: list[dict[str, Any]] = []
        for row in rows:
            entity_id = str(row.get("id") or "")
            label = str(row.get("label") or "")
            if ranked_mode and not _disease_entity_matches_query(
                entity_id, label, query_text
            ):
                continue
            item = _make_entity_row(
                entity_id=entity_id,
                label=label,
                category=row.get("category"),
            )
            item["connected_score"] = int(row.get("connected_score") or 0)
            payload.append(item)
            if len(payload) >= limit:
                break
        if payload and ranked_mode:
            expanded_entity_ids: list[str] = []
            for item in payload:
                raw_ids = item.get("collapsed_ids")
                ids = raw_ids if isinstance(raw_ids, list) else [item.get("id")]
                expanded_entity_ids.extend(
                    str(entity_id) for entity_id in ids if entity_id
                )

            dataset_id_sets = _kg_lens_disease_entity_dataset_id_sets(
                entity_ids=expanded_entity_ids,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
                include_mediated=True,
            )
            for item in payload:
                raw_ids = item.get("collapsed_ids")
                ids = raw_ids if isinstance(raw_ids, list) else [item.get("id")]
                merged_dataset_ids: set[str] = set()
                for entity_id in ids:
                    normalized_id = str(entity_id or "").strip()
                    if not normalized_id:
                        continue
                    merged_dataset_ids.update(dataset_id_sets.get(normalized_id, set()))
                item["counts"]["datasets"] = len(merged_dataset_ids)
        return payload

    candidate_limit = limit
    if lens in {"task", "population"}:
        candidate_limit = min(max(limit * 5, limit), 5000)

    params = {
        "q": q,
        "limit": candidate_limit,
        "seed_labels": seed_labels,
        "scheme_filter": scheme_filter,
        "require_non_empty": lens in {"task", "population"},
    }
    rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND coalesce(n.id, elementId(n)) IS NOT NULL
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
          AND (
            $q = ''
            OR toLower(coalesce(n.label, n.name, n.title, n.id, elementId(n))) CONTAINS $q
            OR toLower(coalesce(n.id, elementId(n), '')) CONTAINS $q
          )
          AND (
            $require_non_empty = false
            OR size(trim(coalesce(n.label, n.name, n.title, ''))) >= 3
          )
        RETURN coalesce(n.id, elementId(n)) AS id,
               coalesce(n.label, n.name, n.title, n.id, elementId(n)) AS label,
               coalesce(n.category, n.type, head(labels(n))) AS category
        ORDER BY label
        LIMIT $limit
        """,
        params,
    )
    if lens in {"task", "population"}:
        collapsed = _collapse_entities_by_label(rows, lens)[:limit]
        if lens == "task":
            return _enrich_task_entities(collapsed)
        return collapsed
    return [
        _make_entity_row(
            entity_id=row.get("id"),
            label=row.get("label"),
            category=row.get("category"),
        )
        for row in rows
    ]


def _kg_lens_disease_dataset_evidence(
    *,
    entity_id: str,
    seed_labels: list[str],
    scheme_filter: str | None,
    limit: int,
    space: str | None,
    atlas: str | None,
    confidence_min: float,
    verified_only: bool,
    include_mediated: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    from brain_researcher.services.br_kg.app import (
        BR_KG_VERIFIED_CONFIDENCE_MIN,
        BR_KG_VERIFIED_TIERS,
        GENERIC_EVIDENCE_LABELS,
        _enrich_lens_evidence_items,
        neo4j_db,
    )
    params = {
        "id": entity_id,
        "seed_labels": seed_labels,
        "scheme_filter": scheme_filter,
        "limit": limit,
        "space": space,
        "atlas": atlas,
        "confidence_min": confidence_min,
        "verified_only": verified_only,
        "verified_confidence_min": BR_KG_VERIFIED_CONFIDENCE_MIN,
        "verified_tiers": list(BR_KG_VERIFIED_TIERS),
        "include_mediated": include_mediated,
        "dataset_labels": GENERIC_EVIDENCE_LABELS["datasets"],
        "paper_labels": GENERIC_EVIDENCE_LABELS["papers"],
        "study_labels": GENERIC_EVIDENCE_LABELS["studies"],
        "task_labels": GENERIC_EVIDENCE_LABELS["tasks"],
        "statmap_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
    }
    rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[rel]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
            )
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'direct',
            matched_via_rel_type: type(rel),
            confidence: rel.confidence,
            confidence_tier: rel.confidence_tier,
            prov_source: coalesce(rel.prov_source, rel.source)
          }) AS direct_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[dp]-(p)
          WHERE any(lbl IN labels(p) WHERE lbl IN $paper_labels)
            AND ($confidence_min <= 0 OR coalesce(dp.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(dp.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(dp.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (p)-[pd]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(dp.confidence, pd.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(dp.confidence, pd.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(dp.confidence_tier, pd.confidence_tier, '')) IN $verified_tiers
            )
          WITH p, d, dp, pd
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_paper',
            matched_via_rel_type: coalesce(type(dp), type(pd)),
            confidence: coalesce(dp.confidence, pd.confidence),
            confidence_tier: coalesce(dp.confidence_tier, pd.confidence_tier),
            prov_source: coalesce(dp.prov_source, dp.source, pd.prov_source, pd.source)
          }) AS paper_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[sr]-(s)
          WHERE any(lbl IN labels(s) WHERE lbl IN $study_labels)
            AND ($confidence_min <= 0 OR coalesce(sr.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(sr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(sr.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (s)-[sd]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(sr.confidence, sd.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(sr.confidence, sd.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(sr.confidence_tier, sd.confidence_tier, '')) IN $verified_tiers
            )
          WITH s, d, sr, sd
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_study',
            matched_via_rel_type: coalesce(type(sr), type(sd)),
            confidence: coalesce(sr.confidence, sd.confidence),
            confidence_tier: coalesce(sr.confidence_tier, sd.confidence_tier),
            prov_source: coalesce(sr.prov_source, sr.source, sd.prov_source, sd.source)
          }) AS study_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[tr]-(t)
          WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
            AND ($confidence_min <= 0 OR coalesce(tr.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(tr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(tr.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (d)-[dt]-(t)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(tr.confidence, dt.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(tr.confidence, dt.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(tr.confidence_tier, dt.confidence_tier, '')) IN $verified_tiers
            )
          WITH t, d, tr, dt
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_task',
            matched_via_rel_type: coalesce(type(tr), type(dt)),
            confidence: coalesce(tr.confidence, dt.confidence),
            confidence_tier: coalesce(tr.confidence_tier, dt.confidence_tier),
            prov_source: coalesce(tr.prov_source, tr.source, dt.prov_source, dt.source)
          }) AS task_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[mr]-(m)
          WHERE any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
            AND ($space IS NULL OR m.space = $space)
            AND ($atlas IS NULL OR m.atlas = $atlas)
            AND ($confidence_min <= 0 OR coalesce(mr.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(mr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(mr.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (m)-[mdr]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(mr.confidence, mdr.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(mr.confidence, mdr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(mr.confidence_tier, mdr.confidence_tier, '')) IN $verified_tiers
            )
          WITH m, d, mr, mdr
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_statmap',
            matched_via_rel_type: coalesce(type(mr), type(mdr)),
            confidence: coalesce(mr.confidence, mdr.confidence),
            confidence_tier: coalesce(mr.confidence_tier, mdr.confidence_tier),
            prov_source: coalesce(mr.prov_source, mr.source, mdr.prov_source, mdr.source)
          }) AS map_items
        }
        WITH direct_items + CASE
             WHEN $include_mediated THEN paper_items + study_items + task_items + map_items
             ELSE []
           END AS items
        UNWIND items AS candidate
        WITH candidate
        WHERE candidate.id IS NOT NULL
        WITH candidate.id AS dataset_id, collect(candidate) AS variants
        WITH dataset_id, head(variants) AS sample, size(variants) AS support
        ORDER BY support DESC, coalesce(sample.name, sample.id)
        WITH collect(sample{.*, path_support: support}) AS dedup_items
        RETURN dedup_items[0..$limit] AS items, size(dedup_items) AS total
        """,
        params,
    )
    row = rows[0] if rows else {"items": [], "total": 0}
    items = row.get("items") or []
    if not include_mediated:
        items = [item for item in items if item.get("link_mode") == "direct"]
        total = len(items)
    else:
        total = int(row.get("total") or 0)
    return (
        _enrich_lens_evidence_items(items),
        total,
    )


def _kg_lens_generic_summary(lens: str, entity_id: str):
    from brain_researcher.services.br_kg.app import (
        GENERIC_EVIDENCE_LABELS,
        _count_task_paper_candidates,
        _empty_counts,
        _lens_scheme_filter,
        _lens_seed_labels,
        neo4j_db,
    )
    seed_labels = _lens_seed_labels(lens)
    scheme_filter = _lens_scheme_filter(lens)
    head_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        RETURN coalesce(n.id, elementId(n)) AS id,
               coalesce(n.label, n.name, n.title, n.id) AS label,
               properties(n) AS props,
               labels(n) AS labels
        LIMIT 1
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    if not head_rows:
        return None

    head = head_rows[0]
    props = head.get("props") or {}
    features = _empty_counts()

    stat_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        OPTIONAL MATCH (n)-[]-(m)
        WHERE any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
        WITH [x IN collect(DISTINCT m) WHERE x IS NOT NULL] AS maps
        RETURN size(maps) AS statmaps,
               [x IN maps WHERE x.space IS NOT NULL | x.space] AS spaces,
               [x IN maps WHERE x.atlas IS NOT NULL | x.atlas] AS atlases
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "statmap_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
        },
    )
    stat_row = stat_rows[0] if stat_rows else {}
    features["statmaps"] = int(stat_row.get("statmaps") or 0)
    spaces = list(dict.fromkeys(stat_row.get("spaces") or []))
    atlases = list(dict.fromkeys(stat_row.get("atlases") or []))

    for feature_name in [
        "coords",
        "timeseries",
        "datasets",
        "papers",
        "tasks",
        "contrasts",
        "tools",
        "studies",
    ]:
        if lens == "task" and feature_name == "papers":
            features[feature_name] = _count_task_paper_candidates(
                entity_id=entity_id,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
            )
            continue
        count_rows = neo4j_db.execute_query(
            """
            MATCH (n)
            WHERE coalesce(n.id, elementId(n)) = $id
              AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            OPTIONAL MATCH (n)-[]-(m)
            WHERE any(lbl IN labels(m) WHERE lbl IN $target_labels)
            RETURN count(DISTINCT m) AS count
            """,
            {
                "id": entity_id,
                "seed_labels": seed_labels,
                "scheme_filter": scheme_filter,
                "target_labels": GENERIC_EVIDENCE_LABELS[feature_name],
            },
        )
        features[feature_name] = int(
            (count_rows[0] if count_rows else {}).get("count") or 0
        )

    if lens == "disease":
        # Disease nodes are usually connected to datasets through mediated paths
        # (paper/study/task/statmap), not only direct one-hop links.
        _, mediated_dataset_total = _kg_lens_disease_dataset_evidence(
            entity_id=entity_id,
            seed_labels=seed_labels,
            scheme_filter=scheme_filter,
            limit=1,
            space=None,
            atlas=None,
            confidence_min=0.0,
            verified_only=False,
        )
        features["datasets"] = max(features["datasets"], int(mediated_dataset_total))

    ont_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        OPTIONAL MATCH (n)-[:CLASSIFIED_UNDER]->(p)
        OPTIONAL MATCH (n)<-[:CLASSIFIED_UNDER]-(c)
        RETURN count(DISTINCT p) AS parents,
               count(DISTINCT c) AS children
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    parents = int((ont_rows[0] if ont_rows else {}).get("parents") or 0)
    children = int((ont_rows[0] if ont_rows else {}).get("children") or 0)

    payload: dict[str, Any] = {
        "id": head.get("id"),
        "label": head.get("label"),
        "status": "online",
        "definition": props.get("definition"),
        "features": features,
        "ontology": {
            "parents": parents,
            "children": children,
            "classified_neighbors": parents + children,
        },
        "spaces": spaces,
        "atlases": atlases,
        "origin": f"neo4j:{lens}",
        "updated_at": props.get("updated_at")
        or int(datetime.utcnow().timestamp() * 1000),
    }
    if lens == "population":
        dataset_rows = neo4j_db.execute_query(
            """
            MATCH (n)
            WHERE coalesce(n.id, elementId(n)) = $id
              AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            OPTIONAL MATCH (n)-[]-(d)
            WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            WITH [x IN collect(DISTINCT d) WHERE x IS NOT NULL] AS datasets
            RETURN [x IN datasets[0..10] | {
              id: coalesce(x.id, elementId(x)),
              name: coalesce(x.name, x.label, x.id),
              url: coalesce(x.url, x.source_url)
            }] AS datasets
            """,
            {
                "id": entity_id,
                "seed_labels": seed_labels,
                "scheme_filter": scheme_filter,
                "dataset_labels": GENERIC_EVIDENCE_LABELS["datasets"],
            },
        )
        linked_datasets = (dataset_rows[0] if dataset_rows else {}).get(
            "datasets"
        ) or []
        dataset_id = (
            props.get("dataset_id")
            or props.get("source_dataset")
            or (linked_datasets[0].get("id") if linked_datasets else None)
        )
        payload["cohort_meta"] = {
            "dataset_id": dataset_id,
            "n_subjects": props.get("n_subjects") or props.get("subjects_count"),
            "age_range": props.get("age_range"),
            "sex_distribution": props.get("sex_distribution")
            or props.get("sex_counts"),
            "linked_datasets": linked_datasets,
        }
        payload["dataset_id"] = dataset_id
    return payload


def _kg_lens_generic_evidence(
    lens: str,
    entity_id: str,
    limit: int,
    types_set: set[str],
    space: str | None,
    atlas: str | None,
    confidence_min: float = 0.0,
    verified_only: bool = False,
    include_mediated: bool = True,
    task_scope: str = "aliases",
    include_task_neighbors: bool = False,
    source_mode: str = "graph_only",
    include_paths: bool = False,
):
    from brain_researcher.services.br_kg.app import (
        BR_KG_VERIFIED_CONFIDENCE_MIN,
        BR_KG_VERIFIED_TIERS,
        EVIDENCE_SOURCE_MODES,
        GENERIC_EVIDENCE_LABELS,
        TASK_EVIDENCE_SCOPES,
        _apply_path_support,
        _count_task_paper_candidates,
        _csv_tokens,
        _empty_counts,
        _empty_groups,
        _enrich_lens_evidence_items,
        _lens_scheme_filter,
        _lens_seed_labels,
        _merge_group_items,
        _merge_task_paper_items,
        _split_task_aliases_and_neighbors,
        _task_study_labels,
        _utc_iso_now,
        _with_graph_defaults,
        logger,
        neo4j_db,
    )
    seed_labels = _lens_seed_labels(lens)
    scheme_filter = _lens_scheme_filter(lens)
    exists_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        RETURN coalesce(n.id, elementId(n)) AS id,
               coalesce(n.label, n.name, n.title, n.id) AS label,
               properties(n) AS props
        LIMIT 1
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    if not exists_rows:
        return None
    entity_row = exists_rows[0]
    if task_scope not in TASK_EVIDENCE_SCOPES:
        task_scope = "aliases"
    if source_mode not in EVIDENCE_SOURCE_MODES:
        source_mode = "graph_only"

    groups = _empty_groups()
    total_counts = _empty_counts()
    task_study_labels = _task_study_labels()
    freshness_ts = _utc_iso_now()
    sources_used: list[str] = ["graph_direct"]
    live_diagnostics: dict[str, Any] | None = None
    warnings: list[str] = []

    def _collect_generic_items(
        target_labels: list[str],
        projection: str,
        extra_where: str = "",
        extra_params: Mapping[str, Any] | None = None,
    ):
        params = {
            "id": entity_id,
            "limit": limit,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "target_labels": target_labels,
            "confidence_min": confidence_min,
            "verified_only": verified_only,
            "verified_confidence_min": BR_KG_VERIFIED_CONFIDENCE_MIN,
            "verified_tiers": list(BR_KG_VERIFIED_TIERS),
        }
        if extra_params:
            params.update(dict(extra_params))
        where_extra = f"\n            {extra_where}" if extra_where else ""
        rows = neo4j_db.execute_query(
            f"""
            MATCH (n)
            WHERE coalesce(n.id, elementId(n)) = $id
              AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            CALL {{
              WITH n
              OPTIONAL MATCH (n)-[rel]-(m)
              WHERE any(lbl IN labels(m) WHERE lbl IN $target_labels)
                AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                AND (
                  NOT $verified_only
                  OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                  OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                ){where_extra}
              WITH m,
                   head([rel_type IN collect(type(rel)) WHERE rel_type IS NOT NULL]) AS rel_type,
                   max(coalesce(rel.confidence, -1.0)) AS rel_confidence,
                   head([tier IN collect(rel.confidence_tier) WHERE tier IS NOT NULL]) AS rel_confidence_tier
              WITH [x IN collect({{
                     node: m,
                     rel_type: rel_type,
                     rel_confidence: CASE
                       WHEN rel_confidence < 0 THEN NULL
                       ELSE rel_confidence
                     END,
                     rel_confidence_tier: rel_confidence_tier
                   }}) WHERE x.node IS NOT NULL] AS nodes
              RETURN [x IN nodes[0..$limit] | {projection}] AS items,
                     size(nodes) AS total
            }}
            RETURN items, total
            """,
            params,
        )
        row = rows[0] if rows else {"items": [], "total": 0}
        return _enrich_lens_evidence_items(row.get("items") or []), int(
            row.get("total") or 0
        )

    if "statmaps" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["statmaps"],
            """{
              map_id: coalesce(x.node.id, x.node.map_id, x.node.name, elementId(x.node)),
              space: x.node.space,
              atlas: x.node.atlas,
              contrast: x.node.contrast,
              url: x.node.url,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
            extra_where="AND ($space IS NULL OR m.space = $space) AND ($atlas IS NULL OR m.atlas = $atlas)",
            extra_params={"space": space, "atlas": atlas},
        )
        groups["statmaps"] = items
        total_counts["statmaps"] = total

    if "coords" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["coords"],
            """{
              x: x.node.x,
              y: x.node.y,
              z: x.node.z,
              label: x.node.label,
              statistic: x.node.statistic,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["coords"] = items
        total_counts["coords"] = total

    if "timeseries" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["timeseries"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              roi: x.node.roi,
              task: x.node.task,
              url: x.node.url,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["timeseries"] = items
        total_counts["timeseries"] = total

    if "datasets" in types_set:
        if lens == "disease":
            items, total = _kg_lens_disease_dataset_evidence(
                entity_id=entity_id,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
                limit=limit,
                space=space,
                atlas=atlas,
                confidence_min=confidence_min,
                verified_only=verified_only,
                include_mediated=include_mediated,
            )
        else:
            items, total = _collect_generic_items(
                GENERIC_EVIDENCE_LABELS["datasets"],
                """{
                  name: coalesce(x.node.name, x.node.label, x.node.id),
                  id: coalesce(x.node.id, elementId(x.node)),
                  description: x.node.description,
                  url: coalesce(x.node.url, x.node.source_url),
                  matched_via_rel_type: x.rel_type,
                  confidence: x.rel_confidence,
                  confidence_tier: x.rel_confidence_tier
                }""",
            )
        groups["datasets"] = items
        total_counts["datasets"] = total

    if "papers" in types_set:
        direct_items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["papers"],
            """{
              id: coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node)),
              pmid: x.node.pmid,
              doi: x.node.doi,
              title: x.node.title,
              year: x.node.year,
              authors: x.node.authors,
              aligned_publication_id: coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node)),
              aligned_study_id: head([(x.node)-[:ALIGNS_WITH]->(s:Study) | coalesce(s.id, elementId(s))]),
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier,
              source_type: 'publication'
            }""",
        )
        if lens == "task":
            fallback_items, _ = _collect_generic_items(
                task_study_labels,
                """{
                  id: coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node)),
                  pmid: x.node.pmid,
                  doi: x.node.doi,
                  title: coalesce(x.node.title, x.node.name, x.node.label),
                  year: x.node.year,
                  authors: x.node.authors,
                  aligned_publication_id: head([
                    (p)-[:ALIGNS_WITH]->(x.node)
                    WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                    | coalesce(p.id, p.pmid, p.doi, elementId(p))
                  ]),
                  aligned_study_id: CASE
                    WHEN size([
                      (p)-[:ALIGNS_WITH]->(x.node)
                      WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                      | 1
                    ]) = 0
                    THEN NULL
                    ELSE coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node))
                  END,
                  matched_via_rel_type: x.rel_type,
                  confidence: x.rel_confidence,
                  confidence_tier: x.rel_confidence_tier,
                  source_type: 'study'
                }""",
            )
            merged_items, metrics = _merge_task_paper_items(
                direct_items=direct_items,
                fallback_items=fallback_items,
                limit=limit,
            )
            dedup_total = _count_task_paper_candidates(
                entity_id=entity_id,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
            )
            groups["papers"] = _enrich_lens_evidence_items(merged_items)
            total_counts["papers"] = dedup_total
            logger.info(
                "task_paper_linking entity_id=%s task_paper_direct_hits=%d "
                "task_paper_fallback_hits=%d task_paper_dedup_dropped=%d "
                "task_paper_total_unique=%d",
                entity_id,
                metrics["task_paper_direct_hits"],
                metrics["task_paper_fallback_hits"],
                metrics["task_paper_dedup_dropped"],
                metrics["task_paper_total_unique"],
            )
        else:
            groups["papers"] = _enrich_lens_evidence_items(direct_items)
            total_counts["papers"] = total

    if "tasks" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["tasks"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              label: coalesce(x.node.name, x.node.label, x.node.id),
              description: x.node.description,
              doi: x.node.doi,
              pmid: x.node.pmid,
              neurostore_id: x.node.neurostore_id,
              source: x.node.source,
              family_id: x.node.family_id,
              subfamily_id: x.node.subfamily_id,
              canonical_task_id: x.node.canonical_task_id,
              canonical_task_label: x.node.canonical_task_label,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        if lens == "task":
            alias_items, neighbor_items = _split_task_aliases_and_neighbors(
                entity_id=str(entity_row.get("id") or entity_id),
                entity_label=entity_row.get("label"),
                entity_props=entity_row.get("props") or {},
                candidate_items=items,
            )
            if task_scope == "neighbors":
                visible_aliases: list[dict[str, Any]] = []
            else:
                visible_aliases = alias_items
            groups["tasks"] = _enrich_lens_evidence_items(visible_aliases[:limit])
            total_counts["tasks"] = len(visible_aliases)

            include_neighbors_output = include_task_neighbors or task_scope in {
                "neighbors",
                "all",
            }
            if include_neighbors_output:
                groups["task_neighbors"] = _enrich_lens_evidence_items(
                    neighbor_items[:limit]
                )
                total_counts["task_neighbors"] = len(neighbor_items)
        else:
            groups["tasks"] = items
            total_counts["tasks"] = total

    if "contrasts" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["contrasts"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              label: coalesce(x.node.name, x.node.label, x.node.id),
              source: x.node.source,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["contrasts"] = items
        total_counts["contrasts"] = total

    if "tools" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["tools"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              name: coalesce(x.node.name, x.node.label, x.node.id),
              description: x.node.description,
              source: coalesce(x.node.software, x.node.source),
              url: x.node.url,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["tools"] = items
        total_counts["tools"] = total

    if "studies" in types_set:
        items, total = _collect_generic_items(
            task_study_labels if lens == "task" else GENERIC_EVIDENCE_LABELS["studies"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              name: coalesce(x.node.title, x.node.name, x.node.id),
              description: coalesce(x.node.abstract, x.node.description),
              source: x.node.source,
              url: coalesce(x.node.url, x.node.source_url),
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["studies"] = items
        total_counts["studies"] = total

    # Normalize graph evidence metadata so UI can consistently render source/path badges.
    for group_name, items in list(groups.items()):
        if group_name not in types_set and group_name != "task_neighbors":
            continue
        if not isinstance(items, list):
            continue
        groups[group_name] = _with_graph_defaults(
            _enrich_lens_evidence_items(items),
            freshness_ts=freshness_ts,
        )

    path_count = 0
    if include_paths:
        path_result = _collect_evidence_paths(
            entity_id=entity_id,
            seed_labels=seed_labels,
            scheme_filter=scheme_filter,
            limit=max(50, limit),
            confidence_min=confidence_min,
            verified_only=verified_only,
            include_mediated=include_mediated,
        )
        if path_result is not None:
            paths, path_count = path_result
            _apply_path_support(groups, paths=paths)
            sources_used.append("graph_paths")

    if lens == "task" and source_mode == "graph_plus_live":
        live_groups, live_sources, live_diagnostics = _collect_live_task_evidence(
            entity_id=str(entity_row.get("id") or entity_id),
            entity_label=str(entity_row.get("label") or entity_id),
            limit=limit,
            types_set=types_set,
        )
        for group_name in ("papers", "studies", "statmaps"):
            if group_name not in types_set:
                continue
            incoming = list(live_groups.get(group_name) or [])
            if not incoming:
                continue
            merged_items, merged_total = _merge_group_items(
                group_name=group_name,
                existing_items=list(groups.get(group_name) or []),
                incoming_items=incoming,
                limit=limit,
            )
            groups[group_name] = merged_items
            total_counts[group_name] = max(
                int(total_counts.get(group_name) or 0),
                merged_total,
            )
        if live_sources:
            sources_used.extend(live_sources)
        if live_diagnostics.get("attempted"):
            if not live_diagnostics.get("api_key_present"):
                warnings.append("live_evidence_disabled_missing_api_key")
            if not live_diagnostics.get("file_search_store_configured"):
                warnings.append("live_evidence_no_store_config")
            if (
                live_diagnostics.get("deep_research_status") == "error"
                or live_diagnostics.get("file_search_status") == "error"
            ):
                warnings.append("live_evidence_provider_error")

    sources_used = _csv_tokens(sources_used)
    requested_groups = sorted(types_set)
    covered_groups = sorted(
        [name for name in requested_groups if len(groups.get(name) or []) > 0]
    )
    coverage_ratio = (
        round(len(covered_groups) / len(requested_groups), 4)
        if requested_groups
        else 1.0
    )

    payload = {
        "entity": {"id": entity_id},
        "counts": total_counts,
        "groups": groups,
        "next_cursor": None,
        "diagnostics": {
            "coverage": {
                "requested_groups": requested_groups,
                "covered_groups": covered_groups,
                "ratio": coverage_ratio,
                "paths": path_count if include_paths else 0,
            }
        },
    }
    if lens == "task":
        payload["meta"] = {
            "task_scope": task_scope,
            "include_task_neighbors": bool(include_task_neighbors),
            "source_mode": source_mode,
            "include_paths": bool(include_paths),
            "sources_used": sources_used,
        }
        if source_mode == "graph_plus_live":
            payload["meta"]["live"] = live_diagnostics or {
                "attempted": False,
                "api_key_present": False,
                "file_search_store_configured": False,
                "deep_research_status": "skipped",
                "file_search_status": "skipped",
                "error_codes": [],
                "hit_counts": {"papers": 0, "studies": 0, "statmaps": 0},
            }
    if warnings:
        payload["warnings"] = _csv_tokens(warnings)
    return payload


def _collect_evidence_paths(
    *,
    entity_id: str,
    seed_labels: list[str],
    scheme_filter: str | None,
    limit: int,
    confidence_min: float,
    verified_only: bool,
    include_mediated: bool,
) -> tuple[list[dict[str, Any]], int] | None:
    from brain_researcher.services.br_kg.app import (
        BR_KG_VERIFIED_CONFIDENCE_MIN,
        BR_KG_VERIFIED_TIERS,
        _evidence_path_signature,
        _evidence_path_templates,
        _serialize_evidence_path_record,
        neo4j_db,
    )
    exists_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        RETURN coalesce(n.id, elementId(n)) AS id
        LIMIT 1
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    if not exists_rows:
        return None

    direct_cypher = """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        MATCH p = (n)-[r]-(target)
        WHERE any(lbl IN labels(target) WHERE lbl IN $target_labels)
          AND ($confidence_min <= 0 OR coalesce(r.confidence, 0.0) >= $confidence_min)
          AND (
            NOT $verified_only
            OR coalesce(r.confidence, 0.0) >= $verified_confidence_min
            OR toLower(coalesce(r.confidence_tier, '')) IN $verified_tiers
          )
        WITH DISTINCT p
        RETURN [node IN nodes(p) | {
                 id: coalesce(node.id, elementId(node)),
                 label: coalesce(node.label, node.name, node.title, node.id),
                 labels: labels(node)
               }] AS nodes,
               [rel IN relationships(p) | {
                 type: type(rel),
                 source_id: coalesce(startNode(rel).id, elementId(startNode(rel))),
                 target_id: coalesce(endNode(rel).id, elementId(endNode(rel))),
                 confidence: rel.confidence,
                 confidence_tier: rel.confidence_tier,
                 prov_source: coalesce(rel.prov_source, rel.source)
               }] AS relationships,
               length(p) AS hops
        LIMIT $limit
    """
    mediated_cypher = """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        MATCH p = (n)-[r1]-(mid)-[r2]-(target)
        WHERE any(lbl IN labels(mid) WHERE lbl IN $middle_labels)
          AND any(lbl IN labels(target) WHERE lbl IN $target_labels)
          AND (
            $confidence_min <= 0
            OR coalesce(r1.confidence, r2.confidence, 0.0) >= $confidence_min
          )
          AND (
            NOT $verified_only
            OR coalesce(r1.confidence, r2.confidence, 0.0) >= $verified_confidence_min
            OR toLower(coalesce(r1.confidence_tier, r2.confidence_tier, '')) IN $verified_tiers
          )
        WITH DISTINCT p
        RETURN [node IN nodes(p) | {
                 id: coalesce(node.id, elementId(node)),
                 label: coalesce(node.label, node.name, node.title, node.id),
                 labels: labels(node)
               }] AS nodes,
               [rel IN relationships(p) | {
                 type: type(rel),
                 source_id: coalesce(startNode(rel).id, elementId(startNode(rel))),
                 target_id: coalesce(endNode(rel).id, elementId(endNode(rel))),
                 confidence: rel.confidence,
                 confidence_tier: rel.confidence_tier,
                 prov_source: coalesce(rel.prov_source, rel.source)
               }] AS relationships,
               length(p) AS hops
        LIMIT $limit
    """

    base_params = {
        "id": entity_id,
        "seed_labels": seed_labels,
        "scheme_filter": scheme_filter,
        "limit": limit,
        "confidence_min": confidence_min,
        "verified_only": verified_only,
        "verified_confidence_min": BR_KG_VERIFIED_CONFIDENCE_MIN,
        "verified_tiers": list(BR_KG_VERIFIED_TIERS),
    }

    dedup: dict[str, dict[str, Any]] = {}
    for template in _evidence_path_templates(include_mediated):
        params = dict(base_params)
        params["target_labels"] = template["target_labels"]
        params["path_type"] = template["path_type"]
        params["match_method"] = template["match_method"]
        cypher = direct_cypher
        middle_labels = template.get("middle_labels")
        if middle_labels:
            params["middle_labels"] = middle_labels
            cypher = mediated_cypher
        rows = neo4j_db.execute_query(cypher, params)
        for row in rows:
            record = _serialize_evidence_path_record(
                path_type=str(template["path_type"]),
                match_method=str(template["match_method"]),
                row=row,
            )
            if record is None:
                continue
            dedup[_evidence_path_signature(record)] = record

    records = list(dedup.values())
    records.sort(
        key=lambda item: (
            item.get("confidence") is None,
            -(item.get("confidence") or 0.0),
            item.get("hops", 0),
            str(item.get("path_type") or ""),
        )
    )
    total = len(records)
    return records[:limit], total
