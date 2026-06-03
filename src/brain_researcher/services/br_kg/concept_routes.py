"""ONVOC concept Blueprint routes for the BR-KG API.

Carved out of ``br_kg/app.py``: the handlers for the ``/concept(s)`` endpoints
(list / get / evidence / evidence-paths / summary / tree / children) plus the
concept-only ``_onvoc_concept_match_clause`` helper.

Registration is done via the explicit ``register(bp)`` function rather than
module-level ``@bp.route`` decorators: ``app.py`` calls ``register(kg_bp)`` on
every (re)import, so a freshly-created ``kg_bp`` is wired up even when this
module is already cached in ``sys.modules`` (the test suite pops + reimports
``app`` per test, creating a new ``kg_bp`` each time). Because this module
imports nothing from ``app`` at module load, the dependency is strictly one-way
and cycle-free.

The handlers sit at the top of the helper call-tree; the app.py config
constants / helpers / live ``neo4j_db`` / ``performance_monitor`` they use stay
in ``app.py`` and are imported back LAZILY inside each handler (read at call
time, so test patches of ``neo4j_db`` / ``performance_monitor`` are honoured, and
the lazy import always resolves the current ``app`` module after a reimport).
``app.py`` re-exports the handler functions so the lens endpoints that delegate
to them and the tests that monkeypatch them keep resolving.
"""

from __future__ import annotations

from flask import jsonify, request


def _onvoc_concept_match_clause(alias: str) -> str:
    return f"""
    any(lbl IN labels({alias}) WHERE lbl IN $concept_labels)
    AND (
      coalesce({alias}.scheme, '') IN $concept_schemes
      OR any(prefix IN $concept_id_prefixes WHERE toUpper(coalesce({alias}.id, '')) STARTS WITH prefix)
    )
    """


def kg_list_concepts():
    """List ONVOC concepts with optional search and lightweight counts."""
    from brain_researcher.services.br_kg.app import (
        ONVOC_CONCEPT_LABELS,
        ONVOC_ENTITY_REL_TYPES,
        ONVOC_LINK_REL_TYPES,
        ONVOC_PAPER_LABELS,
        ONVOC_STATMAP_LABELS,
        ONVOC_TASK_LABELS,
        _neo4j_required,
        logger,
        neo4j_db,
    )
    try:
        _neo4j_required()
        q = request.args.get("q", "").strip().lower()
        limit = int(request.args.get("limit", 50))
        # Allow larger lists for UI browsing (previously capped at 200)
        limit = max(1, min(limit, 2000))
        category = request.args.get("category")

        cypher = """
        MATCH (c)
        WHERE any(lbl IN labels(c) WHERE lbl IN $concept_labels)
          AND coalesce(c.id, elementId(c)) IS NOT NULL
          AND (coalesce(c.scheme, '') = 'ONVOC' OR coalesce(c.id, '') STARTS WITH 'ONVOC_')
          AND (
            $q = ''
            OR toLower(coalesce(c.label, c.name, c.id, elementId(c))) CONTAINS $q
            OR toLower(coalesce(c.id, elementId(c), '')) CONTAINS $q
          )
          AND ($cat IS NULL OR c.category = $cat)
        CALL {
          WITH c
          OPTIONAL MATCH (m)-[link]->(c)
          WHERE type(link) IN $onvoc_link_rel_types
            AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
          RETURN count(DISTINCT m) AS statmaps
        }
        CALL {
          WITH c
          OPTIONAL MATCH (t)-[rel]-(c)
          WHERE type(rel) IN $onvoc_entity_rel_types
            AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
          RETURN count(DISTINCT t) AS tasks
        }
        CALL {
          WITH c
          OPTIONAL MATCH (p)-[rel]-(c)
          WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
            AND any(lbl IN labels(p) WHERE lbl IN $paper_labels)
          RETURN count(DISTINCT p) AS papers
        }
        RETURN coalesce(c.id, elementId(c)) AS id,
               coalesce(c.label, c.name, c.id, elementId(c)) AS label,
               c.category AS category,
               {
                 statmaps: statmaps,
                 coords: 0,
                 timeseries: 0,
                 datasets: 0,
                 papers: papers,
                 tasks: tasks,
                 contrasts: 0,
                 tools: 0,
                 studies: 0
               } AS counts
        ORDER BY label
        LIMIT $limit
        """
        rows = neo4j_db.execute_query(
            cypher,
            {
                "q": q,
                "limit": limit,
                "cat": category,
                "concept_labels": ONVOC_CONCEPT_LABELS,
                "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                "statmap_labels": ONVOC_STATMAP_LABELS,
                "task_labels": ONVOC_TASK_LABELS,
                "paper_labels": ONVOC_PAPER_LABELS,
            },
        )
        response_format = (request.args.get("format") or "").strip().lower()
        if response_format in {"array", "legacy"}:
            return jsonify(rows)

        return jsonify(
            {
                "items": rows,
                "counts": {"concepts": len(rows)},
                "next_cursor": None,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_list_concepts failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


def kg_get_concept(concept_id: str):
    """Get one ONVOC concept with parents and children."""
    from brain_researcher.services.br_kg.app import (
        ONVOC_CONCEPT_LABELS,
        _neo4j_required,
        logger,
        neo4j_db,
    )
    try:
        _neo4j_required()
        cypher = """
        MATCH (c)
        WHERE c.id = $id
          AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
          AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
        OPTIONAL MATCH (c)-[:CLASSIFIED_UNDER]->(p)
        WHERE any(lbl IN labels(p) WHERE lbl IN $concept_labels)
          AND (coalesce(p.scheme, '') = 'ONVOC' OR p.id STARTS WITH 'ONVOC_')
        OPTIONAL MATCH (c)<-[:CLASSIFIED_UNDER]-(ch)
        WHERE any(lbl IN labels(ch) WHERE lbl IN $concept_labels)
          AND (coalesce(ch.scheme, '') = 'ONVOC' OR ch.id STARTS WITH 'ONVOC_')
        RETURN c.id AS id,
               coalesce(c.label, c.name, c.id) AS label,
               c.definition AS definition,
               c.synonyms AS synonyms,
               [x IN collect(DISTINCT {id:p.id, label:coalesce(p.label, p.name, p.id)}) WHERE x.id IS NOT NULL] AS parents,
               [x IN collect(DISTINCT {id:ch.id, label:coalesce(ch.label, ch.name, ch.id)}) WHERE x.id IS NOT NULL] AS children
        """
        row = neo4j_db.execute_query(
            cypher,
            {"id": concept_id, "concept_labels": ONVOC_CONCEPT_LABELS},
        )
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(row[0])
    except Exception as exc:  # pragma: no cover
        logger.error("kg_get_concept failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


def kg_concept_evidence(concept_id: str):
    """Grouped evidence for one concept with all evidence types."""
    from brain_researcher.services.br_kg.app import (
        BR_KG_VERIFIED_CONFIDENCE_MIN,
        BR_KG_VERIFIED_TIERS,
        DATASET_TASK_REL_TYPES,
        ONVOC_CONCEPT_ID_PREFIXES,
        ONVOC_CONCEPT_LABELS,
        ONVOC_CONCEPT_SCHEMES,
        ONVOC_CONTRAST_LABELS,
        ONVOC_DATASET_LABELS,
        ONVOC_ENTITY_REL_TYPES,
        ONVOC_LINK_REL_TYPES,
        ONVOC_PAPER_LABELS,
        ONVOC_STATMAP_LABELS,
        ONVOC_STUDY_LABELS,
        ONVOC_TASK_LABELS,
        ONVOC_TIMESERIES_LABELS,
        ONVOC_TOOL_LABELS,
        STATMAP_CONTRAST_REL_TYPES,
        STATMAP_DATASET_REL_TYPES,
        STUDY_CONCEPT_REL_TYPES,
        STUDY_TASK_REL_TYPES,
        TOOL_CONCEPT_REL_TYPES,
        TOOL_TASK_REL_TYPES,
        _cypher_paper_aligned_publication_expr,
        _cypher_paper_aligned_study_expr,
        _cypher_paper_candidate_dedupe_key,
        _cypher_paper_source_type_expr,
        _cypher_study_candidate_dedupe_key,
        _merge_group_items,
        _merge_task_paper_items,
        _neo4j_required,
        _parse_bool_query_param,
        logger,
        neo4j_db,
        performance_monitor,
    )
    try:
        _neo4j_required()
        try:
            include_mediated = _parse_bool_query_param(
                request.args.get("include_mediated"),
                default=True,
            )
        except ValueError:
            return jsonify({"error": "include_mediated must be a boolean"}), 400
        # Fast existence check to return 404 instead of empty evidence for typos
        exists = neo4j_db.execute_query(
            """
            MATCH (c)
            WHERE c.id = $id
              AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
              AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
            RETURN c.id AS id
            LIMIT 1
            """,
            {"id": concept_id, "concept_labels": ONVOC_CONCEPT_LABELS},
        )
        if not exists:
            return jsonify({"error": "not found"}), 404
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 200))
        types = request.args.get(
            "types",
            "statmaps,coords,timeseries,datasets,papers,tasks,contrasts,tools,studies",
        )
        types_set = {t.strip() for t in types.split(",") if t.strip()}
        space = request.args.get("space")
        atlas = request.args.get("atlas")
        confidence_min_raw = request.args.get("confidence_min", "0")
        try:
            confidence_min = float(confidence_min_raw)
        except (TypeError, ValueError):
            return jsonify(
                {"error": "confidence_min must be a float between 0 and 1"}
            ), 400
        if confidence_min < 0 or confidence_min > 1:
            return jsonify({"error": "confidence_min must be between 0 and 1"}), 400
        try:
            verified_only = _parse_bool_query_param(
                request.args.get("verified_only"),
                default=False,
            )
        except ValueError:
            return jsonify({"error": "verified_only must be a boolean"}), 400
        verified_tiers = list(BR_KG_VERIFIED_TIERS)
        verified_confidence_min = BR_KG_VERIFIED_CONFIDENCE_MIN
        groups = {
            "statmaps": [],
            "coords": [],
            "timeseries": [],
            "datasets": [],
            "papers": [],
            "tasks": [],
            "contrasts": [],
            "tools": [],
            "studies": [],
        }
        total_counts = {
            "statmaps": 0,
            "coords": 0,
            "timeseries": 0,
            "datasets": 0,
            "papers": 0,
            "tasks": 0,
            "contrasts": 0,
            "tools": 0,
            "studies": 0,
        }

        # Start performance monitoring
        with performance_monitor.profile_query(
            f"evidence_query_concept_{concept_id}",
            query_type="neo4j",
            user_id=request.headers.get("X-User-ID"),
            ip_address=request.remote_addr,
        ) as profile:
            # Statmaps (with filters)
            if "statmaps" in types_set:
                statmaps_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                        AND ($space IS NULL OR m.space = $space)
                        AND ($atlas IS NULL OR m.atlas = $atlas)
                        AND ($confidence_min <= 0 OR coalesce(link.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(link.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(link.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        map_id: coalesce(m.id, m.map_id, m.name),
                        space: m.space,
                        atlas: m.atlas,
                        contrast: m.contrast,
                        url: m.url,
                        confidence: link.confidence,
                        prov_method: link.method,
                        prov_source: coalesce(link.prov_source, link.source),
                        confidence_tier: link.confidence_tier
                      })[0..$limit] AS items,
                             count(m) AS total
                    }
                    RETURN items, total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "space": space,
                        "atlas": atlas,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                        "statmap_labels": ONVOC_STATMAP_LABELS,
                    },
                )
                if statmaps_rows:
                    groups["statmaps"] = statmaps_rows[0].get("items", [])
                    total_counts["statmaps"] = statmaps_rows[0].get("total", 0)

            # Coords (accept either direction to be robust)
            if "coords" in types_set:
                coords_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (c)<-[:EVIDENCE_OF]-(coord:CoordAnchor)
                      RETURN collect({
                        x: coord.x,
                        y: coord.y,
                        z: coord.z,
                        label: coord.label,
                        statistic: coord.statistic
                      })[0..$limit] AS items,
                             count(coord) AS total
                    }
                    RETURN items, total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                    },
                )
                if coords_rows:
                    groups["coords"] = coords_rows[0].get("items", [])
                    total_counts["coords"] = coords_rows[0].get("total", 0)

            # Timeseries
            if "timeseries" in types_set:
                timeseries_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (c)-[:ABOUT]-(ts)
                      WHERE any(lbl IN labels(ts) WHERE lbl IN $timeseries_labels)
                      RETURN collect({
                        id: ts.id,
                        roi: ts.roi,
                        task: ts.task,
                        url: ts.url
                      })[0..$limit] AS items,
                             count(ts) AS total
                    }
                    RETURN items, total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "timeseries_labels": ONVOC_TIMESERIES_LABELS,
                    },
                )
                if timeseries_rows:
                    groups["timeseries"] = timeseries_rows[0].get("items", [])
                    total_counts["timeseries"] = timeseries_rows[0].get("total", 0)

            # Datasets (support either direction to accommodate legacy ingests)
            if "datasets" in types_set:
                datasets_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE """ + _onvoc_concept_match_clause("c") + """
                    CALL {
                      WITH c
                      MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND ($confidence_min <= 0 OR coalesce(dr.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(dr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(dr.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        name: coalesce(d.name, d.label, d.id),
                        id: d.id,
                        description: d.description,
                        url: coalesce(d.url, d.source_url),
                        confidence: dr.confidence,
                        prov_method: dr.method,
                        prov_source: coalesce(dr.prov_source, dr.source),
                        confidence_tier: dr.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      MATCH (m)-[mdr]-(d)
                      WHERE type(mdr) IN $statmap_dataset_rel_types
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(link.confidence, mdr.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(link.confidence, mdr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mdr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        name: coalesce(d.name, d.label, d.id),
                        id: d.id,
                        description: d.description,
                        url: coalesce(d.url, d.source_url),
                        confidence: coalesce(link.confidence, mdr.confidence),
                        prov_method: coalesce(link.method, mdr.method),
                        prov_source: coalesce(
                          link.prov_source,
                          link.source,
                          mdr.prov_source,
                          mdr.source
                        ),
                        confidence_tier: coalesce(link.confidence_tier, mdr.confidence_tier)
                      }) AS mapped_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN mapped_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "concept_schemes": ONVOC_CONCEPT_SCHEMES,
                        "concept_id_prefixes": ONVOC_CONCEPT_ID_PREFIXES,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "statmap_labels": ONVOC_STATMAP_LABELS,
                        "statmap_dataset_rel_types": STATMAP_DATASET_REL_TYPES,
                    },
                )
                if datasets_rows:
                    groups["datasets"] = datasets_rows[0].get("items", [])
                    total_counts["datasets"] = datasets_rows[0].get("total", 0)

            # Papers
            if "papers" in types_set:
                papers_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE """
                    + _onvoc_concept_match_clause("c")
                    + """
                    CALL {
                      WITH c
                      MATCH (c)<-[rel]-(pub)
                      WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
                        AND any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      WITH pub
                      ORDER BY coalesce(pub.year, 0) DESC, pub.pmid
                      RETURN collect({
                        id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                        pmid: pub.pmid,
                        doi: pub.doi,
                        title: pub.title,
                        year: pub.year,
                        authors: pub.authors,
                        source_type: """
                    + _cypher_paper_source_type_expr("pub")
                    + """,
                        aligned_study_id: """
                    + _cypher_paper_aligned_study_expr("pub")
                    + """,
                        aligned_publication_id: """
                    + _cypher_paper_aligned_publication_expr("pub")
                    + """
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      MATCH (d)-[:CITED_BY]->(pub)
                      WHERE any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
                      WITH pub
                      ORDER BY coalesce(pub.year, 0) DESC, pub.pmid
                      RETURN collect({
                        id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                        pmid: pub.pmid,
                        doi: pub.doi,
                        title: pub.title,
                        year: pub.year,
                        authors: pub.authors,
                        source_type: """
                    + _cypher_paper_source_type_expr("pub")
                    + """,
                        aligned_study_id: """
                    + _cypher_paper_aligned_study_expr("pub")
                    + """,
                        aligned_publication_id: """
                    + _cypher_paper_aligned_publication_expr("pub")
                    + """
                      }) AS mediated_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN mediated_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH candidate,
                         """
                    + _cypher_paper_candidate_dedupe_key("candidate")
                    + """ AS paper_key,
                         CASE
                           WHEN coalesce(candidate.source_type, '') = 'publication' THEN 0
                           ELSE 1
                         END AS source_rank
                    ORDER BY source_rank ASC,
                             coalesce(candidate.year, 0) DESC,
                             toLower(coalesce(candidate.title, candidate.id, ''))
                    WITH paper_key, collect(candidate)[0] AS chosen
                    WITH chosen
                    ORDER BY CASE
                               WHEN coalesce(chosen.source_type, '') = 'publication' THEN 0
                               ELSE 1
                             END ASC,
                             coalesce(chosen.year, 0) DESC,
                             toLower(coalesce(chosen.title, chosen.id, ''))
                    WITH collect(chosen) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "concept_schemes": ONVOC_CONCEPT_SCHEMES,
                        "concept_id_prefixes": ONVOC_CONCEPT_ID_PREFIXES,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "paper_labels": ONVOC_PAPER_LABELS,
                    },
                )
                if papers_rows:
                    raw_items = list(papers_rows[0].get("items", []) or [])
                    direct_items = [
                        item
                        for item in raw_items
                        if str(item.get("source_type") or "") == "publication"
                    ]
                    fallback_items = [
                        item
                        for item in raw_items
                        if str(item.get("source_type") or "") != "publication"
                    ]
                    merged_items, _metrics = _merge_task_paper_items(
                        direct_items,
                        fallback_items,
                        limit=limit,
                    )
                    groups["papers"] = merged_items
                    total_counts["papers"] = max(
                        int(papers_rows[0].get("total", 0) or 0),
                        len(merged_items),
                    )

            # Tasks (direct ONVOC links + dataset-mediated links)
            if "tasks" in types_set:
                tasks_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (t)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: t.id,
                        label: coalesce(t.name, t.label, t.id),
                        description: t.description,
                        doi: t.doi,
                        pmid: t.pmid,
                        neurostore_id: t.neurostore_id,
                        source: t.source,
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (d)-[dc]-(c)
                      WHERE type(dc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      MATCH (d)-[dt]-(t)
                      WHERE type(dt) IN $dataset_task_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(dc.confidence, dt.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(dc.confidence, dt.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(dc.confidence_tier, dt.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        id: t.id,
                        label: coalesce(t.name, t.label, t.id),
                        description: t.description,
                        doi: t.doi,
                        pmid: t.pmid,
                        neurostore_id: t.neurostore_id,
                        source: t.source,
                        confidence: coalesce(dc.confidence, dt.confidence),
                        prov_method: coalesce(dt.method, dc.method),
                        prov_source: coalesce(
                          dt.prov_source,
                          dt.source,
                          dc.prov_source,
                          dc.source
                        ),
                        confidence_tier: coalesce(dt.confidence_tier, dc.confidence_tier)
                      }) AS via_dataset_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_dataset_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "task_labels": ONVOC_TASK_LABELS,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "dataset_task_rel_types": DATASET_TASK_REL_TYPES,
                    },
                )
                if tasks_rows:
                    groups["tasks"] = tasks_rows[0].get("items", [])
                    total_counts["tasks"] = tasks_rows[0].get("total", 0)

            # Contrasts (direct ONVOC links + map-mediated links)
            if "contrasts" in types_set:
                contrasts_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (ct)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: ct.id,
                        label: coalesce(ct.name, ct.label, ct.id),
                        source: ct.source,
                        statmap_count: 0,
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      MATCH (ct)-[mr]-(m)
                      WHERE type(mr) IN $contrast_statmap_rel_types
                        AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(link.confidence, mr.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(link.confidence, mr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      WITH ct, count(DISTINCT m) AS statmap_count
                      RETURN collect({
                        id: ct.id,
                        label: coalesce(ct.name, ct.label, ct.id),
                        source: ct.source,
                        statmap_count: statmap_count,
                        confidence: null,
                        prov_method: "map_mediated",
                        prov_source: "onvoc_link_rel_types",
                        confidence_tier: null
                      }) AS via_map_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_map_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "statmap_labels": ONVOC_STATMAP_LABELS,
                        "contrast_labels": ONVOC_CONTRAST_LABELS,
                        "contrast_statmap_rel_types": STATMAP_CONTRAST_REL_TYPES,
                    },
                )
                if contrasts_rows:
                    groups["contrasts"] = contrasts_rows[0].get("items", [])
                    total_counts["contrasts"] = contrasts_rows[0].get("total", 0)

            # Tools (direct concept links + task-mediated links)
            if "tools" in types_set:
                tools_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (tool)-[rel]-(c)
                      WHERE type(rel) IN $tool_concept_rel_types
                        AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: tool.id,
                        name: coalesce(tool.name, tool.label, tool.id),
                        description: tool.description,
                        source: tool.software,
                        url: tool.url,
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      MATCH (tool)-[tr]-(t)
                      WHERE type(tr) IN $tool_task_rel_types
                        AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(tc.confidence, tr.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(tc.confidence, tr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, tr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        id: tool.id,
                        name: coalesce(tool.name, tool.label, tool.id),
                        description: tool.description,
                        source: tool.software,
                        url: tool.url,
                        confidence: coalesce(tc.confidence, tr.confidence),
                        prov_method: coalesce(tr.method, tc.method),
                        prov_source: coalesce(
                          tr.prov_source,
                          tr.source,
                          tc.prov_source,
                          tc.source
                        ),
                        confidence_tier: coalesce(tr.confidence_tier, tc.confidence_tier)
                      }) AS via_task_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_task_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "task_labels": ONVOC_TASK_LABELS,
                        "tool_labels": ONVOC_TOOL_LABELS,
                        "tool_concept_rel_types": TOOL_CONCEPT_REL_TYPES,
                        "tool_task_rel_types": TOOL_TASK_REL_TYPES,
                    },
                )
                if tools_rows:
                    groups["tools"] = tools_rows[0].get("items", [])
                    total_counts["tools"] = tools_rows[0].get("total", 0)

            # Studies (direct concept links + task-mediated links)
            if "studies" in types_set:
                studies_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE """
                    + _onvoc_concept_match_clause("c")
                    + """
                    CALL {
                      WITH c
                      MATCH (s)-[rel]-(c)
                      WHERE type(rel) IN $study_concept_rel_types
                        AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: s.id,
                        name: coalesce(s.title, s.name, s.id),
                        description: coalesce(s.abstract, s.description),
                        source: s.source,
                        url: coalesce(s.url, s.source_url),
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      MATCH (s)-[st]-(t)
                      WHERE type(st) IN $study_task_rel_types
                        AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(tc.confidence, st.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(tc.confidence, st.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, st.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        id: s.id,
                        name: coalesce(s.title, s.name, s.id),
                        description: coalesce(s.abstract, s.description),
                        source: s.source,
                        url: coalesce(s.url, s.source_url),
                        confidence: coalesce(tc.confidence, st.confidence),
                        prov_method: coalesce(st.method, tc.method),
                        prov_source: coalesce(
                          st.prov_source,
                          st.source,
                          tc.prov_source,
                          tc.source
                        ),
                        confidence_tier: coalesce(st.confidence_tier, tc.confidence_tier)
                      }) AS via_task_items
                    }
                    CALL {
                      WITH c
                      MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      MATCH (d)-[:CITED_BY]->(s)
                      WHERE any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(dr.confidence, 0.0) >= $confidence_min
                        )
                      RETURN collect({
                        id: s.id,
                        name: coalesce(s.title, s.name, s.id),
                        description: coalesce(s.abstract, s.description),
                        source: s.source,
                        url: coalesce(s.url, s.source_url),
                        confidence: dr.confidence,
                        prov_method: dr.method,
                        prov_source: coalesce(dr.prov_source, dr.source),
                        confidence_tier: dr.confidence_tier
                      }) AS via_dataset_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_task_items
                         ELSE []
                       END + CASE
                         WHEN $include_mediated THEN via_dataset_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH candidate,
                         """
                    + _cypher_study_candidate_dedupe_key("candidate")
                    + """ AS study_key
                    ORDER BY coalesce(candidate.confidence, 0.0) DESC,
                             toLower(coalesce(candidate.name, candidate.id, candidate.url, ''))
                    WITH study_key, collect(candidate)[0] AS chosen
                    WITH chosen
                    ORDER BY coalesce(chosen.confidence, 0.0) DESC,
                             toLower(coalesce(chosen.name, chosen.id, chosen.url, ''))
                    WITH collect(chosen) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "concept_schemes": ONVOC_CONCEPT_SCHEMES,
                        "concept_id_prefixes": ONVOC_CONCEPT_ID_PREFIXES,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "task_labels": ONVOC_TASK_LABELS,
                        "study_labels": ONVOC_STUDY_LABELS,
                        "study_concept_rel_types": STUDY_CONCEPT_REL_TYPES,
                        "study_task_rel_types": STUDY_TASK_REL_TYPES,
                    },
                )
                if studies_rows:
                    merged_items, merged_total = _merge_group_items(
                        group_name="studies",
                        existing_items=[],
                        incoming_items=list(studies_rows[0].get("items", []) or []),
                        limit=limit,
                    )
                    groups["studies"] = merged_items
                    total_counts["studies"] = max(
                        int(studies_rows[0].get("total", 0) or 0),
                        merged_total,
                    )

            # Record metrics for monitoring
            total_rows = sum(len(g) for g in groups.values())
            profile.rows_returned = total_rows

        # Log query completion
        logger.info(
            "Evidence query completed",
            extra={
                "concept_id": concept_id,
                "types_requested": list(types_set),
                "result_counts": {k: len(v) for k, v in groups.items()},
                "total_counts": total_counts,
                "space_filter": space,
                "atlas_filter": atlas,
                "confidence_min": confidence_min,
                "verified_only": verified_only,
                "include_mediated": include_mediated,
                "verified_confidence_min": verified_confidence_min,
                "limit": limit,
            },
        )

        return jsonify(
            {
                "concept": {"id": concept_id},
                "counts": total_counts,
                "groups": groups,
                "next_cursor": None,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_evidence failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


def kg_concept_evidence_paths(concept_id: str):
    """Evidence paths for one concept."""
    from brain_researcher.services.br_kg.app import (
        ONVOC_CONCEPT_LABELS,
        _collect_evidence_paths,
        _empty_paths_payload,
        _neo4j_required,
        _parse_evidence_paths_query_params,
        logger,
    )
    try:
        _neo4j_required()
        try:
            limit, confidence_min, verified_only, include_mediated = (
                _parse_evidence_paths_query_params()
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        result = _collect_evidence_paths(
            entity_id=concept_id,
            seed_labels=list(ONVOC_CONCEPT_LABELS),
            scheme_filter="ONVOC",
            limit=limit,
            confidence_min=confidence_min,
            verified_only=verified_only,
            include_mediated=include_mediated,
        )
        if result is None:
            return jsonify(
                _empty_paths_payload(
                    entity_id=concept_id,
                    lens="onvoc",
                    warning="entity not found",
                )
            )
        paths, total = result
        return jsonify(
            {
                "entity": {"id": concept_id},
                "counts": {"paths": total},
                "paths": paths,
                "next_cursor": None,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_evidence_paths failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


def kg_concept_summary(concept_id: str):
    """Lightweight summary for catalog header."""
    from brain_researcher.services.br_kg.app import (
        BR_KG_VERIFIED_CONFIDENCE_MIN,
        BR_KG_VERIFIED_TIERS,
        DATASET_TASK_REL_TYPES,
        ONVOC_CONCEPT_LABELS,
        ONVOC_CONTRAST_LABELS,
        ONVOC_DATASET_LABELS,
        ONVOC_ENTITY_REL_TYPES,
        ONVOC_LINK_REL_TYPES,
        ONVOC_PAPER_LABELS,
        ONVOC_STATMAP_LABELS,
        ONVOC_STUDY_LABELS,
        ONVOC_TASK_LABELS,
        ONVOC_TIMESERIES_LABELS,
        ONVOC_TOOL_LABELS,
        STATMAP_CONTRAST_REL_TYPES,
        STATMAP_DATASET_REL_TYPES,
        STUDY_CONCEPT_REL_TYPES,
        STUDY_TASK_REL_TYPES,
        TOOL_CONCEPT_REL_TYPES,
        TOOL_TASK_REL_TYPES,
        _neo4j_required,
        logger,
        neo4j_db,
        performance_monitor,
    )
    try:
        _neo4j_required()

        # Start performance monitoring
        with performance_monitor.profile_query(
            f"summary_query_concept_{concept_id}",
            query_type="neo4j",
            user_id=request.headers.get("X-User-ID"),
            ip_address=request.remote_addr,
        ) as profile:
            cypher = """
            MATCH (c)
            WHERE c.id = $id
              AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
              AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
            CALL {
              WITH c
              OPTIONAL MATCH (m)-[link]->(c)
              WHERE type(link) IN $onvoc_link_rel_types
                AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
              RETURN count(DISTINCT m) AS statmaps,
                     collect(DISTINCT m.space) AS spaces,
                     collect(DISTINCT m.atlas) AS atlases
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)<-[:EVIDENCE_OF]-(p:CoordAnchor)
              RETURN count(DISTINCT p) AS coords
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)-[:ABOUT]-(t)
              WHERE any(lbl IN labels(t) WHERE lbl IN $timeseries_labels)
              RETURN count(DISTINCT t) AS timeseries
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)-[:ABOUT]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              WITH c, collect(DISTINCT d.id) AS direct_ids
              OPTIONAL MATCH (m)-[link]->(c)
              WHERE type(link) IN $onvoc_link_rel_types
                AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
              OPTIONAL MATCH (m)-[mdr]-(d2)
              WHERE type(mdr) IN $statmap_dataset_rel_types
                AND any(lbl IN labels(d2) WHERE lbl IN $dataset_labels)
              WITH direct_ids, collect(DISTINCT d2.id) AS mapped_ids
              WITH direct_ids + mapped_ids AS dataset_ids
              UNWIND (
                CASE
                  WHEN size(dataset_ids) = 0 THEN [NULL]
                  ELSE dataset_ids
                END
              ) AS dataset_id
              WITH collect(DISTINCT dataset_id) AS uniq_dataset_ids
              RETURN size([x IN uniq_dataset_ids WHERE x IS NOT NULL]) AS datasets
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)<-[rel]-(pp)
              WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
                AND any(lbl IN labels(pp) WHERE lbl IN $paper_labels)
              WITH collect(DISTINCT CASE
                WHEN pp IS NULL THEN NULL
                ELSE {
                  id: coalesce(pp.id, pp.pmid, pp.doi, elementId(pp)),
                  pmid: pp.pmid,
                  doi: pp.doi,
                  title: pp.title,
                  aligned_study_id: CASE
                    WHEN any(lbl IN labels(pp) WHERE lbl = 'Study')
                      THEN coalesce(toString(pp.id), elementId(pp))
                    ELSE head([
                      (pp)-[:ALIGNS_WITH]->(aligned_study:Study) |
                      coalesce(toString(aligned_study.id), elementId(aligned_study))
                    ])
                  END,
                  aligned_publication_id: CASE
                    WHEN any(lbl IN labels(pp) WHERE lbl IN ['Publication', 'Paper'])
                      THEN coalesce(
                        toString(pp.id),
                        toString(pp.pmid),
                        toString(pp.doi),
                        elementId(pp)
                      )
                    ELSE head([
                      (aligned_publication)-[:ALIGNS_WITH]->(pp)
                      WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                      coalesce(
                        toString(aligned_publication.id),
                        toString(aligned_publication.pmid),
                        toString(aligned_publication.doi),
                        elementId(aligned_publication)
                      )
                    ])
                  END
                }
              END) AS direct_items
              OPTIONAL MATCH (c)-[dr]-(d)
              WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              OPTIONAL MATCH (d)-[:CITED_BY]->(pub)
              WHERE any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
              WITH [
                x IN direct_items + collect(DISTINCT CASE
                  WHEN pub IS NULL THEN NULL
                  ELSE {
                    id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                    pmid: pub.pmid,
                    doi: pub.doi,
                    title: pub.title,
                    aligned_study_id: CASE
                      WHEN any(lbl IN labels(pub) WHERE lbl = 'Study')
                        THEN coalesce(toString(pub.id), elementId(pub))
                      ELSE head([
                        (pub)-[:ALIGNS_WITH]->(aligned_study:Study) |
                        coalesce(toString(aligned_study.id), elementId(aligned_study))
                      ])
                    END,
                    aligned_publication_id: CASE
                      WHEN any(lbl IN labels(pub) WHERE lbl IN ['Publication', 'Paper'])
                        THEN coalesce(
                          toString(pub.id),
                          toString(pub.pmid),
                          toString(pub.doi),
                          elementId(pub)
                        )
                      ELSE head([
                        (aligned_publication)-[:ALIGNS_WITH]->(pub)
                        WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                        coalesce(
                          toString(aligned_publication.id),
                          toString(aligned_publication.pmid),
                          toString(aligned_publication.doi),
                          elementId(aligned_publication)
                        )
                      ])
                    END
                  }
                END)
                WHERE x IS NOT NULL
              ] AS paper_items
              UNWIND (
                CASE
                  WHEN size(paper_items) = 0 THEN [NULL]
                  ELSE paper_items
                END
              ) AS paper_item
              WITH paper_item
              WHERE paper_item IS NOT NULL
              WITH CASE
                WHEN coalesce(toString(paper_item.aligned_study_id), '') <> ''
                  THEN 'aligned_study:' + toLower(trim(toString(paper_item.aligned_study_id)))
                WHEN coalesce(toString(paper_item.aligned_publication_id), '') <> ''
                  THEN 'aligned_publication:' + toLower(trim(toString(paper_item.aligned_publication_id)))
                WHEN coalesce(toString(paper_item.pmid), '') <> ''
                  THEN 'pmid:' + toLower(trim(toString(paper_item.pmid)))
                WHEN coalesce(toString(paper_item.doi), '') <> ''
                  THEN 'doi:' + toLower(trim(toString(paper_item.doi)))
                WHEN coalesce(toString(paper_item.title), '') <> ''
                  THEN 'title:' + toLower(trim(toString(paper_item.title)))
                ELSE 'id:' + toLower(trim(coalesce(toString(paper_item.id), '')))
              END AS paper_key
              RETURN count(DISTINCT paper_key) AS papers
            }
            CALL {
              WITH c
              OPTIONAL MATCH (t)-[rel]-(c)
              WHERE type(rel) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
              WITH c, collect(DISTINCT t.id) AS direct_task_ids
              OPTIONAL MATCH (d)-[dc]-(c)
              WHERE type(dc) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              OPTIONAL MATCH (d)-[dt]-(t2)
              WHERE type(dt) IN $dataset_task_rel_types
                AND any(lbl IN labels(t2) WHERE lbl IN $task_labels)
              WITH direct_task_ids, collect(DISTINCT t2.id) AS mapped_task_ids
              WITH direct_task_ids + mapped_task_ids AS task_ids
              UNWIND (
                CASE
                  WHEN size(task_ids) = 0 THEN [NULL]
                  ELSE task_ids
                END
              ) AS task_id
              WITH collect(DISTINCT task_id) AS uniq_task_ids
              RETURN size([x IN uniq_task_ids WHERE x IS NOT NULL]) AS tasks
            }
            CALL {
              WITH c
              OPTIONAL MATCH (ct)-[rel]-(c)
              WHERE type(rel) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
              WITH c, collect(DISTINCT ct.id) AS direct_contrast_ids
              OPTIONAL MATCH (m)-[link]->(c)
              WHERE type(link) IN $onvoc_link_rel_types
                AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
              OPTIONAL MATCH (ct2)-[mr]-(m)
              WHERE type(mr) IN $contrast_statmap_rel_types
                AND any(lbl IN labels(ct2) WHERE lbl IN $contrast_labels)
              WITH direct_contrast_ids, collect(DISTINCT ct2.id) AS mapped_contrast_ids
              WITH direct_contrast_ids + mapped_contrast_ids AS contrast_ids
              UNWIND (
                CASE
                  WHEN size(contrast_ids) = 0 THEN [NULL]
                  ELSE contrast_ids
                END
              ) AS contrast_id
              WITH collect(DISTINCT contrast_id) AS uniq_contrast_ids
              RETURN size([x IN uniq_contrast_ids WHERE x IS NOT NULL]) AS contrasts
            }
            CALL {
              WITH c
              OPTIONAL MATCH (tool)-[rel]-(c)
              WHERE type(rel) IN $tool_concept_rel_types
                AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
              WITH c, collect(DISTINCT tool.id) AS direct_tool_ids
              OPTIONAL MATCH (t)-[tc]-(c)
              WHERE type(tc) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
              OPTIONAL MATCH (tool2)-[tr]-(t)
              WHERE type(tr) IN $tool_task_rel_types
                AND any(lbl IN labels(tool2) WHERE lbl IN $tool_labels)
              WITH direct_tool_ids, collect(DISTINCT tool2.id) AS mapped_tool_ids
              WITH direct_tool_ids + mapped_tool_ids AS tool_ids
              UNWIND (
                CASE
                  WHEN size(tool_ids) = 0 THEN [NULL]
                  ELSE tool_ids
                END
              ) AS tool_id
              WITH collect(DISTINCT tool_id) AS uniq_tool_ids
              RETURN size([x IN uniq_tool_ids WHERE x IS NOT NULL]) AS tools
            }
            CALL {
              WITH c
              OPTIONAL MATCH (s)-[rel]-(c)
              WHERE type(rel) IN $study_concept_rel_types
                AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
              WITH c, collect(DISTINCT s.id) AS direct_study_ids
              OPTIONAL MATCH (t)-[tc]-(c)
              WHERE type(tc) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
              OPTIONAL MATCH (s2)-[st]-(t)
              WHERE type(st) IN $study_task_rel_types
                AND any(lbl IN labels(s2) WHERE lbl IN $study_labels)
              WITH c, direct_study_ids, collect(DISTINCT s2.id) AS mapped_study_ids
              OPTIONAL MATCH (c)-[:ABOUT|IN_ONVOC|HAS_ONVOC_ANNOTATION]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              OPTIONAL MATCH (d)-[:CITED_BY]->(s3)
              WHERE any(lbl IN labels(s3) WHERE lbl IN $study_labels)
              WITH direct_study_ids,
                   mapped_study_ids,
                   collect(DISTINCT s3.id) AS dataset_study_ids
              WITH direct_study_ids + mapped_study_ids + dataset_study_ids AS study_ids
              UNWIND (
                CASE
                  WHEN size(study_ids) = 0 THEN [NULL]
                  ELSE study_ids
                END
              ) AS study_id
              WITH collect(DISTINCT study_id) AS uniq_study_ids
              RETURN size([x IN uniq_study_ids WHERE x IS NOT NULL]) AS studies
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)-[:CLASSIFIED_UNDER]->(parent)
              WHERE any(lbl IN labels(parent) WHERE lbl IN $concept_labels)
                AND (
                  coalesce(parent.scheme, '') = 'ONVOC'
                  OR parent.id STARTS WITH 'ONVOC_'
                )
              WITH c, count(DISTINCT parent) AS parent_count
              OPTIONAL MATCH (c)<-[:CLASSIFIED_UNDER]-(child)
              WHERE any(lbl IN labels(child) WHERE lbl IN $concept_labels)
                AND (
                  coalesce(child.scheme, '') = 'ONVOC'
                  OR child.id STARTS WITH 'ONVOC_'
                )
              RETURN parent_count, count(DISTINCT child) AS child_count
            }
            RETURN {
              id: c.id, label: coalesce(c.label, c.name, c.id),
              status: 'online',
              features: {
                statmaps: statmaps,
                coords: coords,
                timeseries: timeseries,
                datasets: datasets,
                papers: papers,
                tasks: tasks,
                contrasts: contrasts,
                tools: tools,
                studies: studies
              },
              ontology: {
                parents: parent_count,
                children: child_count,
                classified_neighbors: parent_count + child_count
              },
              spaces: [x IN spaces WHERE x IS NOT NULL],
              atlases: [x IN atlases WHERE x IS NOT NULL],
              origin: 'neo4j',
              updated_at: coalesce(c.updated_at, timestamp())
            } AS summary
            """
            summary_params = {
                "id": concept_id,
                "concept_labels": ONVOC_CONCEPT_LABELS,
                "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                "statmap_labels": ONVOC_STATMAP_LABELS,
                "timeseries_labels": ONVOC_TIMESERIES_LABELS,
                "dataset_labels": ONVOC_DATASET_LABELS,
                "paper_labels": ONVOC_PAPER_LABELS,
                "task_labels": ONVOC_TASK_LABELS,
                "contrast_labels": ONVOC_CONTRAST_LABELS,
                "tool_labels": ONVOC_TOOL_LABELS,
                "study_labels": ONVOC_STUDY_LABELS,
                "study_concept_rel_types": STUDY_CONCEPT_REL_TYPES,
                "study_task_rel_types": STUDY_TASK_REL_TYPES,
                "tool_concept_rel_types": TOOL_CONCEPT_REL_TYPES,
                "tool_task_rel_types": TOOL_TASK_REL_TYPES,
                "statmap_dataset_rel_types": STATMAP_DATASET_REL_TYPES,
                "dataset_task_rel_types": DATASET_TASK_REL_TYPES,
                "contrast_statmap_rel_types": STATMAP_CONTRAST_REL_TYPES,
            }
            rows = neo4j_db.execute_query(cypher, summary_params)

            if not rows:
                return jsonify({"error": "not found"}), 404

            summary = rows[0]["summary"]
            feature_keys = [
                "statmaps",
                "coords",
                "timeseries",
                "datasets",
                "papers",
                "tasks",
                "contrasts",
                "tools",
                "studies",
            ]
            total_features = {
                key: int((summary.get("features", {}) or {}).get(key) or 0)
                for key in feature_keys
            }
            summary["features"] = total_features

            verified_params = dict(summary_params)
            verified_params.update(
                {
                    "verified_confidence_min": BR_KG_VERIFIED_CONFIDENCE_MIN,
                    "verified_tiers": list(BR_KG_VERIFIED_TIERS),
                }
            )

            def _query_verified_count(count_cypher: str) -> int:
                count_rows = neo4j_db.execute_query(count_cypher, verified_params)
                if not count_rows:
                    return 0
                return int((count_rows[0] or {}).get("count") or 0)

            verified_features = {
                # Coord/time-series evidence currently has no confidence tier metadata.
                "coords": total_features["coords"],
                "timeseries": total_features["timeseries"],
                "statmaps": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    MATCH (m)-[link]->(c)
                    WHERE type(link) IN $onvoc_link_rel_types
                      AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      AND (
                        coalesce(link.confidence, 0.0) >= $verified_confidence_min
                        OR toLower(coalesce(link.confidence_tier, '')) IN $verified_tiers
                      )
                    RETURN count(DISTINCT m) AS count
                    """
                ),
                "datasets": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (c)-[dr:ABOUT]-(d)
                      WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND (
                          coalesce(dr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(dr.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT d.id) AS direct_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      OPTIONAL MATCH (m)-[mdr]-(d2)
                      WHERE type(mdr) IN $statmap_dataset_rel_types
                        AND any(lbl IN labels(d2) WHERE lbl IN $dataset_labels)
                        AND (
                          coalesce(link.confidence, mdr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mdr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT d2.id) AS mapped_ids
                    }
                    WITH direct_ids + mapped_ids AS dataset_ids
                    UNWIND (
                      CASE
                        WHEN size(dataset_ids) = 0 THEN [NULL]
                        ELSE dataset_ids
                      END
                    ) AS dataset_id
                    WITH collect(DISTINCT dataset_id) AS uniq_dataset_ids
                    RETURN size([x IN uniq_dataset_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "papers": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    OPTIONAL MATCH (c)<-[rel]-(pp)
                    WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
                      AND any(lbl IN labels(pp) WHERE lbl IN $paper_labels)
                      AND (
                        coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                        OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                      )
                    WITH collect(DISTINCT CASE
                      WHEN pp IS NULL THEN NULL
                      ELSE {
                        id: coalesce(pp.id, pp.pmid, pp.doi, elementId(pp)),
                        pmid: pp.pmid,
                        doi: pp.doi,
                        title: pp.title,
                        aligned_study_id: CASE
                          WHEN any(lbl IN labels(pp) WHERE lbl = 'Study')
                            THEN coalesce(toString(pp.id), elementId(pp))
                          ELSE head([
                            (pp)-[:ALIGNS_WITH]->(aligned_study:Study) |
                            coalesce(toString(aligned_study.id), elementId(aligned_study))
                          ])
                        END,
                        aligned_publication_id: CASE
                          WHEN any(lbl IN labels(pp) WHERE lbl IN ['Publication', 'Paper'])
                            THEN coalesce(
                              toString(pp.id),
                              toString(pp.pmid),
                              toString(pp.doi),
                              elementId(pp)
                            )
                          ELSE head([
                            (aligned_publication)-[:ALIGNS_WITH]->(pp)
                            WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                            coalesce(
                              toString(aligned_publication.id),
                              toString(aligned_publication.pmid),
                              toString(aligned_publication.doi),
                              elementId(aligned_publication)
                            )
                          ])
                        END
                      }
                    END) AS direct_items
                    OPTIONAL MATCH (c)-[dr]-(d)
                    WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                      AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                    OPTIONAL MATCH (d)-[:CITED_BY]->(pub)
                    WHERE any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
                    WITH [
                      x IN direct_items + collect(DISTINCT CASE
                        WHEN pub IS NULL THEN NULL
                        ELSE {
                          id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                          pmid: pub.pmid,
                          doi: pub.doi,
                          title: pub.title,
                          aligned_study_id: CASE
                            WHEN any(lbl IN labels(pub) WHERE lbl = 'Study')
                              THEN coalesce(toString(pub.id), elementId(pub))
                            ELSE head([
                              (pub)-[:ALIGNS_WITH]->(aligned_study:Study) |
                              coalesce(toString(aligned_study.id), elementId(aligned_study))
                            ])
                          END,
                          aligned_publication_id: CASE
                            WHEN any(lbl IN labels(pub) WHERE lbl IN ['Publication', 'Paper'])
                              THEN coalesce(
                                toString(pub.id),
                                toString(pub.pmid),
                                toString(pub.doi),
                                elementId(pub)
                              )
                            ELSE head([
                              (aligned_publication)-[:ALIGNS_WITH]->(pub)
                              WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                              coalesce(
                                toString(aligned_publication.id),
                                toString(aligned_publication.pmid),
                                toString(aligned_publication.doi),
                                elementId(aligned_publication)
                              )
                            ])
                          END
                        }
                      END)
                      WHERE x IS NOT NULL
                    ] AS paper_items
                    UNWIND (
                      CASE
                        WHEN size(paper_items) = 0 THEN [NULL]
                        ELSE paper_items
                      END
                    ) AS paper_item
                    WITH paper_item
                    WHERE paper_item IS NOT NULL
                    WITH CASE
                      WHEN coalesce(toString(paper_item.aligned_study_id), '') <> ''
                        THEN 'aligned_study:' + toLower(trim(toString(paper_item.aligned_study_id)))
                      WHEN coalesce(toString(paper_item.aligned_publication_id), '') <> ''
                        THEN 'aligned_publication:' + toLower(trim(toString(paper_item.aligned_publication_id)))
                      WHEN coalesce(toString(paper_item.pmid), '') <> ''
                        THEN 'pmid:' + toLower(trim(toString(paper_item.pmid)))
                      WHEN coalesce(toString(paper_item.doi), '') <> ''
                        THEN 'doi:' + toLower(trim(toString(paper_item.doi)))
                      WHEN coalesce(toString(paper_item.title), '') <> ''
                        THEN 'title:' + toLower(trim(toString(paper_item.title)))
                      ELSE 'id:' + toLower(trim(coalesce(toString(paper_item.id), '')))
                    END AS paper_key
                    RETURN count(DISTINCT paper_key) AS count
                    """
                ),
                "tasks": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (t)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT t.id) AS direct_task_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (d)-[dc]-(c)
                      WHERE type(dc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      OPTIONAL MATCH (d)-[dt]-(t2)
                      WHERE type(dt) IN $dataset_task_rel_types
                        AND any(lbl IN labels(t2) WHERE lbl IN $task_labels)
                        AND (
                          coalesce(dc.confidence, dt.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(dc.confidence_tier, dt.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT t2.id) AS mapped_task_ids
                    }
                    WITH direct_task_ids + mapped_task_ids AS task_ids
                    UNWIND (
                      CASE
                        WHEN size(task_ids) = 0 THEN [NULL]
                        ELSE task_ids
                      END
                    ) AS task_id
                    WITH collect(DISTINCT task_id) AS uniq_task_ids
                    RETURN size([x IN uniq_task_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "contrasts": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (ct)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT ct.id) AS direct_contrast_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      OPTIONAL MATCH (ct2)-[mr]-(m)
                      WHERE type(mr) IN $contrast_statmap_rel_types
                        AND any(lbl IN labels(ct2) WHERE lbl IN $contrast_labels)
                        AND (
                          coalesce(link.confidence, mr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT ct2.id) AS mapped_contrast_ids
                    }
                    WITH direct_contrast_ids + mapped_contrast_ids AS contrast_ids
                    UNWIND (
                      CASE
                        WHEN size(contrast_ids) = 0 THEN [NULL]
                        ELSE contrast_ids
                      END
                    ) AS contrast_id
                    WITH collect(DISTINCT contrast_id) AS uniq_contrast_ids
                    RETURN size([x IN uniq_contrast_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "tools": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (tool)-[rel]-(c)
                      WHERE type(rel) IN $tool_concept_rel_types
                        AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT tool.id) AS direct_tool_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      OPTIONAL MATCH (tool2)-[tr]-(t)
                      WHERE type(tr) IN $tool_task_rel_types
                        AND any(lbl IN labels(tool2) WHERE lbl IN $tool_labels)
                        AND (
                          coalesce(tc.confidence, tr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, tr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT tool2.id) AS mapped_tool_ids
                    }
                    WITH direct_tool_ids + mapped_tool_ids AS tool_ids
                    UNWIND (
                      CASE
                        WHEN size(tool_ids) = 0 THEN [NULL]
                        ELSE tool_ids
                      END
                    ) AS tool_id
                    WITH collect(DISTINCT tool_id) AS uniq_tool_ids
                    RETURN size([x IN uniq_tool_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "studies": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (s)-[rel]-(c)
                      WHERE type(rel) IN $study_concept_rel_types
                        AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT s.id) AS direct_study_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      OPTIONAL MATCH (s2)-[st]-(t)
                      WHERE type(st) IN $study_task_rel_types
                        AND any(lbl IN labels(s2) WHERE lbl IN $study_labels)
                        AND (
                          coalesce(tc.confidence, st.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, st.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT s2.id) AS mapped_study_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND (
                          coalesce(dr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(dr.confidence_tier, '')) IN $verified_tiers
                        )
                      OPTIONAL MATCH (d)-[:CITED_BY]->(s3)
                      WHERE any(lbl IN labels(s3) WHERE lbl IN $study_labels)
                      RETURN collect(DISTINCT s3.id) AS dataset_study_ids
                    }
                    WITH direct_study_ids + mapped_study_ids + dataset_study_ids AS study_ids
                    UNWIND (
                      CASE
                        WHEN size(study_ids) = 0 THEN [NULL]
                        ELSE study_ids
                      END
                    ) AS study_id
                    WITH collect(DISTINCT study_id) AS uniq_study_ids
                    RETURN size([x IN uniq_study_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
            }
            summary["features_verified"] = verified_features
            summary["features_unverified"] = {
                key: max(total_features[key] - int(verified_features.get(key, 0)), 0)
                for key in feature_keys
            }
            profile.rows_returned = 1

            # Log query completion
            logger.info(
                "Summary query completed",
                extra={
                    "concept_id": concept_id,
                    "evidence_counts": summary.get("features", {}),
                    "verified_counts": summary.get("features_verified", {}),
                },
            )

        return jsonify(summary)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_summary failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


def kg_concepts_tree():
    """Return ONVOC roots with children up to a bounded depth (default 3)."""
    from brain_researcher.services.br_kg.app import (
        _neo4j_required,
        logger,
        neo4j_db,
    )
    try:
        _neo4j_required()
        max_depth = int(request.args.get("max_depth", 3))
        max_depth = max(1, min(max_depth, 6))
        root_limit = int(request.args.get("limit", 20))
        root_limit = max(1, min(root_limit, 50))
        scheme = request.args.get("scheme", "ONVOC")

        cypher = """
        MATCH (root:Concept {scheme:$scheme})
        WHERE NOT (root)-[:CLASSIFIED_UNDER]->(:Concept {scheme:$scheme})
          AND root.label IS NOT NULL AND root.label <> ''
        WITH root ORDER BY root.label LIMIT $root_limit
        OPTIONAL MATCH path=(root)<-[:CLASSIFIED_UNDER*1..6]-(child:Concept {scheme:$scheme})
        WHERE length(path) <= $max_depth
          AND child.label IS NOT NULL AND child.label <> ''
        WITH root, child, path, length(path) AS depth
        WITH root,
             collect({child_id: child.id, child_label: child.label, depth: depth,
                      parent_id: CASE WHEN depth = 1 THEN root.id ELSE nodes(path)[-2].id END}) AS edges
        RETURN root.id AS root_id, root.label AS root_label, edges
        """
        rows = neo4j_db.execute_query(
            cypher,
            {"scheme": scheme, "max_depth": max_depth, "root_limit": root_limit},
        )

        # Query to check which nodes have children (for lazy loading support)
        has_children_query = """
        MATCH (node:Concept {scheme:$scheme})
        WHERE EXISTS {
            MATCH (child:Concept {scheme:$scheme})-[:CLASSIFIED_UNDER]->(node)
        }
        RETURN node.id AS id
        """
        has_children_rows = neo4j_db.execute_query(
            has_children_query, {"scheme": scheme}
        )
        has_children_set = {row["id"] for row in has_children_rows}

        trees = []
        for row in rows:
            root_id = row["root_id"]
            root_label = row["root_label"]
            root_has_children = root_id in has_children_set
            root_node = {
                "id": root_id,
                "label": root_label,
                "depth": 0,
                "children": [],
                "hasChildren": root_has_children,
            }
            by_id = {root_id: root_node}
            # sort edges by depth to ensure parents created first
            for edge in sorted(row.get("edges", []), key=lambda e: e["depth"]):
                cid = edge["child_id"]
                if cid in by_id:
                    node = by_id[cid]
                else:
                    node_has_children = cid in has_children_set
                    node = {
                        "id": cid,
                        "label": edge["child_label"],
                        "depth": edge["depth"],
                        "children": [],
                        "hasChildren": node_has_children,
                    }
                    by_id[cid] = node
                parent_id = edge.get("parent_id") or root_id
                parent = by_id.get(parent_id)
                if parent is None:
                    parent = root_node
                    by_id[parent_id] = parent
                # attach if not already present
                if node not in parent["children"]:
                    parent["children"].append(node)
            trees.append(root_node)

        return jsonify({"scheme": scheme, "max_depth": max_depth, "roots": trees})
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concepts_tree failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


def kg_concept_children(concept_id):
    """Get direct children of a specific concept for lazy tree loading."""
    from brain_researcher.services.br_kg.app import (
        logger,
        neo4j_db,
        using_neo4j_backend,
    )
    scheme = request.args.get("scheme", "ONVOC")

    if not using_neo4j_backend:
        return jsonify({"error": "Neo4j backend required"}), 503

    try:
        # Query for direct children only
        query = """
        MATCH path=(child:Concept {scheme:$scheme})-[:CLASSIFIED_UNDER]->(parent:Concept {scheme:$scheme, id:$parent_id})
        WHERE child.label IS NOT NULL AND child.label <> ''
        WITH child, path
        // Calculate depth by counting levels from root
        OPTIONAL MATCH rootPath=(child)-[:CLASSIFIED_UNDER*]->(root:Concept {scheme:$scheme})
        WHERE NOT EXISTS { MATCH (root)-[:CLASSIFIED_UNDER]->(:Concept {scheme:$scheme}) }
        WITH child, CASE WHEN rootPath IS NULL THEN 0 ELSE length(rootPath) END AS depth
        // Check for grandchildren
        OPTIONAL MATCH (grandchild:Concept {scheme:$scheme})-[:CLASSIFIED_UNDER]->(child)
        WHERE grandchild.label IS NOT NULL AND grandchild.label <> ''
        WITH child, depth, count(grandchild) > 0 AS has_children
        RETURN child.id AS id,
               child.label AS label,
               depth,
               has_children
        ORDER BY child.label
        """

        results = neo4j_db.execute_query(
            query, {"scheme": scheme, "parent_id": concept_id}
        )

        children = []
        for row in results:
            children.append(
                {
                    "id": row["id"],
                    "label": row["label"] or row["id"],
                    "depth": row.get("depth", 0),
                    "hasChildren": bool(row["has_children"]),
                }
            )

        return jsonify({"children": children})
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_children failed for %s: %s", concept_id, exc)
        return jsonify({"error": str(exc)}), 500


def register(bp):
    """Register the concept routes on the kg_bp Blueprint (idempotent per bp).

    Called by app.py on every (re)import so a freshly-created kg_bp gets the
    routes even when this module is already cached in sys.modules.
    """
    bp.add_url_rule('/concepts', methods=['GET'], view_func=kg_list_concepts)
    bp.add_url_rule('/concept/<concept_id>', methods=['GET'], view_func=kg_get_concept)
    bp.add_url_rule('/concept/<concept_id>/evidence', methods=['GET'], view_func=kg_concept_evidence)
    bp.add_url_rule('/concept/<concept_id>/evidence/paths', methods=['GET'], view_func=kg_concept_evidence_paths)
    bp.add_url_rule('/concept/<concept_id>/summary', methods=['GET'], view_func=kg_concept_summary)
    bp.add_url_rule('/concepts/tree', methods=['GET'], view_func=kg_concepts_tree)
    bp.add_url_rule('/concept/<concept_id>/children', methods=['GET'], view_func=kg_concept_children)
