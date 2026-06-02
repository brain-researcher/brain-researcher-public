"""External knowledge-base federation routes for the BR-KG API.

Carved out of ``br_kg/app.py``: the ``/api/federation/...`` route handlers that
query Wikidata / DBpedia and merge federated results.

Registration uses an explicit ``register(app)`` function (called by ``app.py`` on
every import) rather than module-level ``@app.route`` decorators, so the test
suite's per-test app reimport re-wires correctly. This module imports nothing
from ``app`` at module load → cycle-free. The connectors / merger / logger stay
in ``app.py`` and are imported back lazily inside each handler (read at call
time, so test patches are honoured).
"""

from __future__ import annotations

from flask import request


def search_wikidata():
    """Search Wikidata for brain-related entities"""
    from brain_researcher.services.br_kg.app import logger, wikidata_connector

    if not wikidata_connector:
        return {"error": "Wikidata connector not available"}, 503

    query = request.args.get("q", "")
    entity_type = request.args.get("type", "brain_regions")
    limit = request.args.get("limit", 50, type=int)

    if not query:
        return {"error": "Query parameter 'q' is required"}, 400

    try:
        if entity_type == "brain_regions":
            results = wikidata_connector.search_brain_regions(query, limit)
        elif entity_type == "conditions":
            results = wikidata_connector.search_neurological_conditions(query, limit)
        elif entity_type == "methods":
            results = wikidata_connector.search_neuroimaging_methods(query, limit)
        elif entity_type == "scientists":
            results = wikidata_connector.search_neuroscientists(query, limit)
        else:
            return {"error": f"Unknown entity type: {entity_type}"}, 400

        return {"results": results, "source": "wikidata", "count": len(results)}, 200
    except Exception as e:
        logger.error("Wikidata search failed: %s", str(e))
        return {"error": "Search failed", "details": str(e)}, 500


def search_dbpedia():
    """Search DBpedia for brain-related entities"""
    from brain_researcher.services.br_kg.app import dbpedia_connector, logger

    if not dbpedia_connector:
        return {"error": "DBpedia connector not available"}, 503

    query = request.args.get("q", "")
    entity_type = request.args.get("type", "anatomy")
    limit = request.args.get("limit", 50, type=int)

    if not query:
        return {"error": "Query parameter 'q' is required"}, 400

    try:
        if entity_type == "anatomy":
            results = dbpedia_connector.search_brain_anatomy(query, limit)
        elif entity_type == "conditions":
            results = dbpedia_connector.search_neurological_conditions(query, limit)
        elif entity_type == "institutions":
            results = dbpedia_connector.search_research_institutions(query, limit=limit)
        elif entity_type == "journals":
            results = dbpedia_connector.search_scientific_journals(query, limit=limit)
        elif entity_type == "scientists":
            results = dbpedia_connector.search_neuroscientists(query, limit)
        else:
            return {"error": f"Unknown entity type: {entity_type}"}, 400

        return {"results": results, "source": "dbpedia", "count": len(results)}, 200
    except Exception as e:
        logger.error("DBpedia search failed: %s", str(e))
        return {"error": "Search failed", "details": str(e)}, 500


def federated_search():
    """Search across multiple external knowledge graphs"""
    from brain_researcher.services.br_kg.app import (
        dbpedia_connector,
        federation_merger,
        logger,
        wikidata_connector,
    )

    if not wikidata_connector or not dbpedia_connector or not federation_merger:
        return {"error": "Federation services not available"}, 503

    query = request.args.get("q", "")
    entity_type = request.args.get("type", "brain_regions")
    limit = request.args.get("limit", 30, type=int)
    merge_strategy = request.args.get("merge", "best_match")

    if not query:
        return {"error": "Query parameter 'q' is required"}, 400

    try:
        results_by_source = {}

        # Search Wikidata
        try:
            if entity_type == "brain_regions":
                wikidata_results = wikidata_connector.search_brain_regions(query, limit)
            elif entity_type == "conditions":
                wikidata_results = wikidata_connector.search_neurological_conditions(
                    query, limit
                )
            else:
                wikidata_results = []
            results_by_source["wikidata"] = wikidata_results
        except Exception as e:
            logger.warning("Wikidata search failed: %s", str(e))
            results_by_source["wikidata"] = []

        # Search DBpedia
        try:
            if entity_type == "brain_regions":
                dbpedia_results = dbpedia_connector.search_brain_anatomy(query, limit)
            elif entity_type == "conditions":
                dbpedia_results = dbpedia_connector.search_neurological_conditions(
                    query, limit
                )
            else:
                dbpedia_results = []
            results_by_source["dbpedia"] = dbpedia_results
        except Exception as e:
            logger.warning("DBpedia search failed: %s", str(e))
            results_by_source["dbpedia"] = []

        # Merge results
        merged_results = federation_merger.merge_results(
            results_by_source, merge_strategy=merge_strategy
        )

        return {
            "results": merged_results[:limit],
            "sources": list(results_by_source.keys()),
            "merge_strategy": merge_strategy,
            "total_before_merge": sum(len(r) for r in results_by_source.values()),
            "total_after_merge": len(merged_results),
        }, 200

    except Exception as e:
        logger.error("Federated search failed: %s", str(e))
        return {"error": "Federated search failed", "details": str(e)}, 500


def register(app):
    """Register the federation routes on the Flask app (called by app.py each import)."""
    app.add_url_rule(
        "/api/federation/wikidata/search", methods=["GET"], view_func=search_wikidata
    )
    app.add_url_rule(
        "/api/federation/dbpedia/search", methods=["GET"], view_func=search_dbpedia
    )
    app.add_url_rule(
        "/api/federation/search", methods=["GET"], view_func=federated_search
    )
