"""Lens Blueprint routes for the BR-KG API.

Carved out of ``br_kg/app.py``: the ``/lens/...`` route handlers (entities /
summary / entity-summary / entity-evidence / entity-evidence-paths / task-tree).
These are thin-ish handlers that delegate to the lens implementation layer
(``lens_endpoints_impl``) and to the concept routes (``kg_list_concepts`` /
``kg_concept_summary`` / ``kg_concept_evidence``), all re-exported from ``app``.

Registration uses an explicit ``register(bp)`` function (called by ``app.py`` on
every import, before ``register_blueprint``) rather than module-level
``@bp.route`` decorators, so the test suite's per-test app reimport (fresh
``kg_bp``) re-wires correctly. This module imports nothing from ``app`` at module
load → cycle-free. All app.py config / helpers / live globals (incl. the
test-patched ``neo4j_db`` / ``performance_monitor`` / ``build_task_family_tree`` /
``_kg_lens_generic_*`` / ``kg_list_concepts`` / ``kg_concept_summary``) are imported
back LAZILY inside each handler so patches are honoured at call time.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from flask import jsonify, request


def kg_lens_entities(lens: str):
    """List seed entities for a lens."""
    from brain_researcher.services.br_kg.app import (
        BR_KG_LENSES_V1,
        LENS_REGISTRY,
        _disease_entity_cache_get,
        _disease_entity_cache_key,
        _disease_entity_cache_set,
        _disease_entity_query_mode,
        _kg_lens_generic_entities,
        _lens_disabled_response,
        _lens_not_found_response,
        _lens_scheme_filter,
        _neo4j_required,
        _normalize_lens,
        kg_list_concepts,
        logger,
        monotonic,
    )

    if not BR_KG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    if lens == "onvoc":
        return kg_list_concepts()

    try:
        _neo4j_required()
        started_at = monotonic()
        q = request.args.get("q", "").strip().lower()
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 2000))
        if lens == "disease":
            scheme_filter = _lens_scheme_filter(lens)
            path_mode = _disease_entity_query_mode(q)
            cache_key = _disease_entity_cache_key(
                lens=lens,
                query=q,
                limit=limit,
                scheme_filter=scheme_filter,
                path_mode=path_mode,
            )
            cached_rows = _disease_entity_cache_get(cache_key)
            if cached_rows is not None:
                elapsed_ms = max((monotonic() - started_at) * 1000.0, 0.0)
                logger.info(
                    "kg_lens_entities lens=%s path_mode=%s cache=%s q=%r limit=%s scheme=%s elapsed_ms=%.2f count=%s",
                    lens,
                    path_mode,
                    "HIT",
                    q,
                    limit,
                    scheme_filter,
                    elapsed_ms,
                    len(cached_rows),
                )
                return jsonify(cached_rows)

            rows = _kg_lens_generic_entities(lens, q, limit)
            _disease_entity_cache_set(cache_key, rows)
            elapsed_ms = max((monotonic() - started_at) * 1000.0, 0.0)
            logger.info(
                "kg_lens_entities lens=%s path_mode=%s cache=%s q=%r limit=%s scheme=%s elapsed_ms=%.2f count=%s",
                lens,
                path_mode,
                "MISS",
                q,
                limit,
                scheme_filter,
                elapsed_ms,
                len(rows),
            )
            return jsonify(rows)

        rows = _kg_lens_generic_entities(lens, q, limit)
        return jsonify(rows)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_lens_entities failed (%s): %s", lens, exc)
        return jsonify({"error": str(exc)}), 500


def kg_task_family_tree():
    """Task-family hierarchy for task lens explorer."""
    from brain_researcher.services.br_kg.app import (
        BR_KG_LENSES_V1,
        _kg_lens_generic_entities,
        _lens_disabled_response,
        _neo4j_required,
        _parse_bool_query_param,
        _task_tree_cache_get,
        _task_tree_cache_set,
        build_task_family_tree,
        logger,
    )

    if not BR_KG_LENSES_V1:
        return _lens_disabled_response()
    try:
        _neo4j_required()
        q = request.args.get("q", "").strip().lower()
        limit = int(request.args.get("limit", 2000))
        limit = max(1, min(limit, 2000))
        include_unmapped = _parse_bool_query_param(
            request.args.get("include_unmapped"),
            default=True,
        )
        cache_key = (q, limit, include_unmapped)
        cached_payload = _task_tree_cache_get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload)

        entities = _kg_lens_generic_entities("task", q, limit)
        families = build_task_family_tree(
            entities,
            query=q,
            include_unmapped=include_unmapped,
        )
        mapped_tasks = sum(
            1
            for entity in entities
            if entity.get("family_id") and entity.get("subfamily_id")
        )
        total_tasks = len(entities)
        unmapped_tasks = max(0, total_tasks - mapped_tasks)
        mapping_ratio = (mapped_tasks / total_tasks) if total_tasks else 0.0
        method_counter = Counter(
            str(entity.get("match_method") or "unmapped") for entity in entities
        )
        method_counts = dict(method_counter)
        logger.info(
            "Task family mapping stats: total=%s mapped=%s unmapped=%s ratio=%.3f methods=%s",
            total_tasks,
            mapped_tasks,
            unmapped_tasks,
            mapping_ratio,
            method_counts,
        )
        if total_tasks > 0 and mapping_ratio < 0.2:
            logger.warning(
                "Task family mapping ratio low: ratio=%.3f (mapped=%s/%s)",
                mapping_ratio,
                mapped_tasks,
                total_tasks,
            )
        payload = {
            "lens": "task",
            "families": families,
            "counts": {
                "families": len(families),
                "tasks": len(entities),
            },
            "mapping_stats": {
                "mapped": mapped_tasks,
                "unmapped": unmapped_tasks,
                "ratio": round(mapping_ratio, 4),
                "methods": method_counts,
            },
        }
        _task_tree_cache_set(cache_key, payload)
        return jsonify(payload)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_task_family_tree failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


def kg_lens_summary(lens: str):
    """Backward-compatible lens summary endpoint.

    Supports:
    - /api/kg/lens/<lens>/summary?entity_id=<id> (delegates to entity summary)
    - /api/kg/lens/<lens>/summary (returns lens-level entity count)
    """
    from brain_researcher.services.br_kg.app import (
        BR_KG_LENSES_V1,
        LENS_REGISTRY,
        ONVOC_CONCEPT_LABELS,
        _lens_disabled_response,
        _lens_not_found_response,
        _lens_scheme_filter,
        _lens_seed_labels,
        _neo4j_required,
        _normalize_lens,
        logger,
        neo4j_db,
    )

    if not BR_KG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    entity_id = (
        request.args.get("entity_id")
        or request.args.get("id")
        or request.args.get("concept_id")
    )
    if entity_id:
        return kg_lens_entity_summary(lens, entity_id)

    try:
        _neo4j_required()
        seed_labels = (
            list(ONVOC_CONCEPT_LABELS) if lens == "onvoc" else _lens_seed_labels(lens)
        )
        scheme_filter = "ONVOC" if lens == "onvoc" else _lens_scheme_filter(lens)
        rows = neo4j_db.execute_query(
            """
            MATCH (n)
            WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            RETURN count(DISTINCT n) AS entities
            """,
            {
                "seed_labels": seed_labels,
                "scheme_filter": scheme_filter,
            },
        )
        total = int((rows[0] if rows else {}).get("entities") or 0)
        return jsonify(
            {"lens": lens, "counts": {"entities": total}, "next_cursor": None}
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_lens_summary failed (%s): %s", lens, exc)
        return jsonify({"error": str(exc)}), 500


def kg_lens_entity_summary(lens: str, entity_id: str):
    """Lightweight entity summary for a lens."""
    from brain_researcher.services.br_kg.app import (
        BR_KG_LENSES_V1,
        LENS_REGISTRY,
        _cache_header_response,
        _kg_lens_generic_summary,
        _lens_disabled_response,
        _lens_not_found_response,
        _neo4j_required,
        _normalize_lens,
        _task_entity_cache_get_with_source,
        _task_entity_cache_key,
        _task_entity_cache_set,
        _task_entity_singleflight_lock,
        kg_concept_summary,
        logger,
        monotonic,
    )

    if not BR_KG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    if lens == "onvoc":
        return kg_concept_summary(entity_id)

    try:
        started_at = monotonic()
        cache_key: tuple[Any, ...] | None = None
        if lens == "task":
            cache_key = _task_entity_cache_key("summary", lens, entity_id)
            cached_hit = _task_entity_cache_get_with_source(cache_key)
            if cached_hit is not None:
                cache_status, cached_summary = cached_hit
                return _cache_header_response(
                    cached_summary,
                    cache_status=cache_status,
                    started_at=started_at,
                )

        if cache_key is not None:
            with _task_entity_singleflight_lock(cache_key):
                cached_hit = _task_entity_cache_get_with_source(cache_key)
                if cached_hit is not None:
                    cache_status, cached_summary = cached_hit
                    return _cache_header_response(
                        cached_summary,
                        cache_status=cache_status,
                        started_at=started_at,
                    )

                _neo4j_required()
                summary = _kg_lens_generic_summary(lens, entity_id)
                if summary is None:
                    return _cache_header_response(
                        {"error": "not found"},
                        cache_status="MISS",
                        started_at=started_at,
                        status=404,
                    )
                _task_entity_cache_set(cache_key, summary)
                return _cache_header_response(
                    summary,
                    cache_status="MISS",
                    started_at=started_at,
                )

        _neo4j_required()
        summary = _kg_lens_generic_summary(lens, entity_id)
        if summary is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(summary)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_lens_entity_summary failed (%s, %s): %s", lens, entity_id, exc)
        return jsonify({"error": str(exc)}), 500


def kg_lens_entity_evidence(lens: str, entity_id: str):
    """Grouped evidence for a lens entity."""
    from brain_researcher.services.br_kg.app import (
        BR_KG_LENSES_V1,
        LENS_EVIDENCE_KEYS,
        LENS_REGISTRY,
        _cache_header_response,
        _kg_lens_generic_evidence,
        _lens_disabled_response,
        _lens_not_found_response,
        _neo4j_required,
        _normalize_lens,
        _parse_bool_query_param,
        _parse_source_mode_query_param,
        _parse_task_scope_query_param,
        _task_entity_cache_get_with_source,
        _task_entity_cache_key,
        _task_entity_cache_set,
        _task_entity_singleflight_lock,
        kg_concept_evidence,
        logger,
        monotonic,
    )

    if not BR_KG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    if lens == "onvoc":
        return kg_concept_evidence(entity_id)

    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 200))
        confidence_min_raw = request.args.get("confidence_min", "0")
        try:
            confidence_min = float(confidence_min_raw)
        except (TypeError, ValueError):
            return (
                jsonify({"error": "confidence_min must be a float between 0 and 1"}),
                400,
            )
        if confidence_min < 0 or confidence_min > 1:
            return jsonify({"error": "confidence_min must be between 0 and 1"}), 400
        try:
            verified_only = _parse_bool_query_param(
                request.args.get("verified_only"),
                default=False,
            )
        except ValueError:
            return jsonify({"error": "verified_only must be a boolean"}), 400
        try:
            include_mediated = _parse_bool_query_param(
                request.args.get("include_mediated"),
                default=True,
            )
        except ValueError:
            return jsonify({"error": "include_mediated must be a boolean"}), 400
        task_scope = "aliases"
        include_task_neighbors = False
        source_mode = "graph_only"
        include_paths = False
        if lens == "task":
            try:
                task_scope = _parse_task_scope_query_param(
                    request.args.get("task_scope"),
                    default="aliases",
                )
            except ValueError:
                return (
                    jsonify(
                        {
                            "error": (
                                "task_scope must be one of: aliases, neighbors, all"
                            )
                        }
                    ),
                    400,
                )
            try:
                include_task_neighbors = _parse_bool_query_param(
                    request.args.get("include_task_neighbors"),
                    default=False,
                )
            except ValueError:
                return (
                    jsonify({"error": "include_task_neighbors must be a boolean"}),
                    400,
                )
            try:
                source_mode = _parse_source_mode_query_param(
                    request.args.get("source_mode"),
                    default="graph_only",
                )
            except ValueError:
                return (
                    jsonify(
                        {
                            "error": "source_mode must be one of: graph_only, graph_plus_live"
                        }
                    ),
                    400,
                )
            try:
                include_paths = _parse_bool_query_param(
                    request.args.get("include_paths"),
                    default=True,
                )
            except ValueError:
                return (
                    jsonify({"error": "include_paths must be a boolean"}),
                    400,
                )
        types = request.args.get(
            "types",
            ",".join(LENS_EVIDENCE_KEYS),
        )
        types_set = {
            t.strip() for t in types.split(",") if t.strip() in LENS_EVIDENCE_KEYS
        }
        if not types_set:
            types_set = set(LENS_EVIDENCE_KEYS)
        space = request.args.get("space")
        atlas = request.args.get("atlas")

        def _compute_payload() -> Any | None:
            _neo4j_required()
            return _kg_lens_generic_evidence(
                lens=lens,
                entity_id=entity_id,
                limit=limit,
                types_set=types_set,
                space=space,
                atlas=atlas,
                confidence_min=confidence_min,
                verified_only=verified_only,
                include_mediated=include_mediated,
                task_scope=task_scope,
                include_task_neighbors=include_task_neighbors,
                source_mode=source_mode,
                include_paths=include_paths,
            )

        started_at = monotonic()
        cache_key: tuple[Any, ...] | None = None
        if lens == "task":
            cache_key = _task_entity_cache_key("evidence", lens, entity_id)
            cached_hit = _task_entity_cache_get_with_source(cache_key)
            if cached_hit is not None:
                cache_status, cached_payload = cached_hit
                return _cache_header_response(
                    cached_payload,
                    cache_status=cache_status,
                    started_at=started_at,
                )

            with _task_entity_singleflight_lock(cache_key):
                cached_hit = _task_entity_cache_get_with_source(cache_key)
                if cached_hit is not None:
                    cache_status, cached_payload = cached_hit
                    return _cache_header_response(
                        cached_payload,
                        cache_status=cache_status,
                        started_at=started_at,
                    )

                payload = _compute_payload()
                if payload is None:
                    return _cache_header_response(
                        {"error": "not found"},
                        cache_status="MISS",
                        started_at=started_at,
                        status=404,
                    )
                _task_entity_cache_set(cache_key, payload)
                return _cache_header_response(
                    payload,
                    cache_status="MISS",
                    started_at=started_at,
                )

        payload = _compute_payload()
        if payload is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(payload)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "kg_lens_entity_evidence failed (%s, %s): %s", lens, entity_id, exc
        )
        return jsonify({"error": str(exc)}), 500


def kg_lens_entity_evidence_paths(lens: str, entity_id: str):
    """Evidence paths for a lens entity."""
    from brain_researcher.services.br_kg.app import (
        BR_KG_LENSES_V1,
        LENS_REGISTRY,
        ONVOC_CONCEPT_LABELS,
        _cache_header_response,
        _collect_evidence_paths,
        _empty_paths_payload,
        _lens_disabled_response,
        _lens_not_found_response,
        _lens_scheme_filter,
        _lens_seed_labels,
        _neo4j_required,
        _normalize_lens,
        _parse_evidence_paths_query_params,
        _task_entity_cache_get_with_source,
        _task_entity_cache_key,
        _task_entity_cache_set,
        _task_entity_singleflight_lock,
        logger,
        monotonic,
    )

    if not BR_KG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    try:
        try:
            limit, confidence_min, verified_only, include_mediated = (
                _parse_evidence_paths_query_params()
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        started_at = monotonic()
        cache_key: tuple[Any, ...] | None = None
        if lens == "task":
            cache_key = _task_entity_cache_key("evidence_paths", lens, entity_id)
            cached_hit = _task_entity_cache_get_with_source(cache_key)
            if cached_hit is not None:
                cache_status, cached_payload = cached_hit
                return _cache_header_response(
                    cached_payload,
                    cache_status=cache_status,
                    started_at=started_at,
                )

        seed_labels = (
            list(ONVOC_CONCEPT_LABELS) if lens == "onvoc" else _lens_seed_labels(lens)
        )
        scheme_filter = "ONVOC" if lens == "onvoc" else _lens_scheme_filter(lens)

        def _compute_paths_payload() -> tuple[dict[str, Any], bool]:
            _neo4j_required()
            result = _collect_evidence_paths(
                entity_id=entity_id,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
                limit=limit,
                confidence_min=confidence_min,
                verified_only=verified_only,
                include_mediated=include_mediated,
            )
            if result is None:
                return (
                    _empty_paths_payload(
                        entity_id=entity_id,
                        lens=lens,
                        warning="entity not found",
                    ),
                    False,
                )
            paths, total = result
            return (
                {
                    "entity": {"id": entity_id, "lens": lens},
                    "counts": {"paths": total},
                    "paths": paths,
                    "next_cursor": None,
                },
                True,
            )

        if cache_key is not None:
            with _task_entity_singleflight_lock(cache_key):
                cached_hit = _task_entity_cache_get_with_source(cache_key)
                if cached_hit is not None:
                    cache_status, cached_payload = cached_hit
                    return _cache_header_response(
                        cached_payload,
                        cache_status=cache_status,
                        started_at=started_at,
                    )

                payload, cacheable = _compute_paths_payload()
                if cacheable:
                    _task_entity_cache_set(cache_key, payload)
                return _cache_header_response(
                    payload,
                    cache_status="MISS",
                    started_at=started_at,
                )

        payload, _ = _compute_paths_payload()
        return jsonify(payload)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "kg_lens_entity_evidence_paths failed (%s, %s): %s",
            lens,
            entity_id,
            exc,
        )
        return jsonify({"error": str(exc)}), 500


def register(bp):
    """Register the lens routes on kg_bp (called by app.py each import)."""
    bp.add_url_rule(
        "/lens/<lens>/entities", methods=["GET"], view_func=kg_lens_entities
    )
    bp.add_url_rule("/lens/task/tree", methods=["GET"], view_func=kg_task_family_tree)
    bp.add_url_rule("/lens/<lens>/summary", methods=["GET"], view_func=kg_lens_summary)
    bp.add_url_rule(
        "/lens/<lens>/entity/<entity_id>/summary",
        methods=["GET"],
        view_func=kg_lens_entity_summary,
    )
    bp.add_url_rule(
        "/lens/<lens>/entity/<entity_id>/evidence",
        methods=["GET"],
        view_func=kg_lens_entity_evidence,
    )
    bp.add_url_rule(
        "/lens/<lens>/entity/<entity_id>/evidence/paths",
        methods=["GET"],
        view_func=kg_lens_entity_evidence_paths,
    )
