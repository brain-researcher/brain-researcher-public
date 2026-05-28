"""
GLM FitLins API endpoints for BR-KG

This module provides API endpoints specifically for GLM FitLins data,
including contrasts, cognitive constructs, and their relationships.
"""

import logging
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from brain_researcher.services.neurokg.db.schema import (
    setup_schema as setup_neo4j_schema,
)
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

# Configure logging
logger = logging.getLogger(__name__)

# Create Blueprint
glmfitlins_bp = Blueprint("glmfitlins", __name__, url_prefix="/api/glmfitlins")

# Database configuration - Neo4j only
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE")
# Mirror the service default: avoid preloading the full legacy graph cache on
# request-time DB initialization unless explicitly enabled.
NEO4J_PRELOAD_CACHE = os.environ.get("NEO4J_PRELOAD_CACHE", "false").lower() not in {
    "0",
    "false",
    "no",
}

# Global database connection
_db = None

_DEFAULT_GLM_PRIORS = {
    "hrf_basis": {"canonical": 0.7, "derivs": 0.3},
    "confounds": {"6mot": 0.6, "24mot": 0.4},
    "high_pass": {"128": 1.0},
    "confounds_motion_6": {"present": 1.0, "absent": 0.0},
    "confounds_motion_24": {"present": 0.4, "absent": 0.6},
    "confounds_global_signal": {"present": 0.0, "absent": 1.0},
    "confounds_csf": {"present": 0.0, "absent": 1.0},
    "confounds_white_matter": {"present": 0.0, "absent": 1.0},
    "confounds_csf_wm": {"present": 0.0, "absent": 1.0},
    "confounds_framewise_displacement": {"present": 0.0, "absent": 1.0},
    "confounds_dvars": {"present": 0.0, "absent": 1.0},
    "confounds_cosine_dct": {"present": 1.0, "absent": 0.0},
    "confounds_acompcor": {"present": 0.0, "absent": 1.0},
    "confounds_tcompcor": {"present": 0.0, "absent": 1.0},
    "confounds_ccompcor": {"present": 0.0, "absent": 1.0},
    "confounds_wcompcor": {"present": 0.0, "absent": 1.0},
    "confounds_non_steady_state": {"present": 0.0, "absent": 1.0},
    "confounds_scrub_motion_outliers": {"present": 0.0, "absent": 1.0},
    "confounds_aroma": {"present": 0.0, "absent": 1.0},
}


class GLMFitlinsAPI:
    """Legacy shim for tests expecting a GLMFitlinsAPI class."""

    def __init__(self, *args, **kwargs) -> None:
        pass


def _parse_int_param(
    name: str,
    value: str | None,
    *,
    default: int | None = None,
    minimum: int | None = None,
) -> int | None:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed




def _generate_spec_family(
    priors: dict[str, dict[str, float]],
    *,
    k: int,
    seed: int | None,
    support: dict[str, Any] | None = None,
    literature_support: dict[str, Any] | None = None,
):
    from brain_researcher.core.multiverse.spec_family import generate_spec_family

    default_axes = set((support or {}).get("default_axes") or [])
    lit_axes = set((literature_support or {}).keys())
    axis_sources = {}
    for axis in (priors or {}).keys():
        if axis in lit_axes:
            axis_sources[axis] = "literature"
        elif axis in default_axes:
            axis_sources[axis] = "default"
        else:
            axis_sources[axis] = "neurokg"

    return generate_spec_family(priors or {}, k=k, seed=seed, axis_sources=axis_sources)


def get_db():
    """Get or create database connection"""
    global _db
    if _db is None:
        try:
            _db = require_neo4j_db(
                database=NEO4J_DATABASE,
                preload_cache=NEO4J_PRELOAD_CACHE,
            )
            _ = _db.get_stats()
            try:
                setup_neo4j_schema(_db)
            except Exception as exc:  # pragma: no cover
                logger.warning("Neo4j schema setup skipped for GLM FitLins API: %s", exc)
            logger.info("Connected to Neo4j backend for GLM FitLins API")
        except Exception as exc:
            raise RuntimeError(
                "Neo4j connection failed. Ensure NEO4J_URI/NEO4J_PASSWORD are set."
            ) from exc
    return _db


@glmfitlins_bp.route("/datasets", methods=["GET"])
def get_datasets():
    """Get all datasets with GLM FitLins data"""
    try:
        db = get_db()
        datasets = db.find_nodes(labels="Dataset")

        result = []
        for node_id, node_data in datasets:
            dataset_info = {
                "id": str(node_id),
                "dataset_id": node_data.get("dataset_id"),
                "name": node_data.get("name"),
                "doi": node_data.get("doi", ""),
                "source": node_data.get("source", "openneuro_glmfitlins"),
            }

            # Get contrast count for this dataset
            relationships = db.find_relationships(
                start_node=node_id, rel_type="HAS_CONTRAST"
            )
            dataset_info["contrast_count"] = len(relationships)

            result.append(dataset_info)

        return jsonify({"datasets": result, "total": len(result)})

    except Exception as e:
        logger.error(f"Error getting datasets: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/contrasts", methods=["GET"])
def get_contrasts():
    """
    Get contrasts, optionally filtered by dataset or task

    Query parameters:
    - dataset_id: Filter by dataset ID
    - task: Filter by task label
    - limit: Maximum number of results (default: 100)
    - offset: Pagination offset (default: 0)
    """
    try:
        db = get_db()

        # Get query parameters
        dataset_id = request.args.get("dataset_id")
        task = request.args.get("task")
        try:
            limit = _parse_int_param(
                "limit", request.args.get("limit"), default=100, minimum=0
            )
            offset = _parse_int_param(
                "offset", request.args.get("offset"), default=0, minimum=0
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        # Build properties filter
        properties = {}
        if dataset_id:
            properties["dataset_id"] = dataset_id
        if task:
            properties["task_label"] = task

        # Query contrasts
        contrasts = db.find_nodes(
            labels="Contrast", properties=properties if properties else None
        )

        # Paginate results
        total = len(contrasts)
        contrasts = contrasts[offset : offset + limit]

        result = []
        for node_id, node_data in contrasts:
            contrast_info = {
                "id": str(node_id),
                "name": node_data.get("name"),
                "task_label": node_data.get("task_label"),
                "dataset_id": node_data.get("dataset_id"),
            }

            # Get associated constructs count
            construct_rels = db.find_relationships(
                start_node=node_id, rel_type="INVOLVES_CONSTRUCT"
            )
            contrast_info["construct_count"] = len(construct_rels)

            result.append(contrast_info)

        return jsonify(
            {"contrasts": result, "total": total, "limit": limit, "offset": offset}
        )

    except Exception as e:
        logger.error(f"Error getting contrasts: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/contrasts/<contrast_id>/constructs", methods=["GET"])
def get_contrast_constructs(contrast_id):
    """Get cognitive constructs associated with a contrast"""
    try:
        db = get_db()

        # First, verify the contrast exists
        contrast_nodes = db.find_nodes(properties={"id": contrast_id})
        if not contrast_nodes:
            # Try finding by node ID in the graph
            found_contrast = False
            for node_id, node_data in db.graph.nodes(data=True):
                if node_id == contrast_id:
                    found_contrast = True
                    break

            if not found_contrast:
                return jsonify({"error": f"Contrast {contrast_id} not found"}), 404

        # Get relationships for this contrast
        relationships = db.find_relationships(
            start_node=contrast_id, rel_type="INVOLVES_CONSTRUCT"
        )

        # Even if no relationships, return empty list (not 404)
        if not relationships:
            return jsonify({"contrast_id": contrast_id, "constructs": [], "total": 0})

        result = []
        for start, end, edge_data in relationships:
            # Get construct node
            construct_nodes = db.find_nodes(properties={"id": end})
            if not construct_nodes:
                # Try finding by node ID in the graph
                for node_id, node_data in db.graph.nodes(data=True):
                    if node_id == end:
                        construct_nodes = [(node_id, node_data)]
                        break

            if construct_nodes:
                _, construct_data = construct_nodes[0]
                construct_info = {
                    "id": construct_data.get("construct_id"),
                    "name": construct_data.get("name"),
                    "direction": edge_data.get("direction", "+1"),
                    "llm_confidence": edge_data.get("llm_confidence", 0),
                    "literature_confidence": edge_data.get("literature_confidence", 0),
                    "overall_confidence": edge_data.get("overall_confidence", 0),
                }
                result.append(construct_info)

        # Sort by overall confidence
        result.sort(key=lambda x: x["overall_confidence"], reverse=True)

        return jsonify(
            {"contrast_id": contrast_id, "constructs": result, "total": len(result)}
        )

    except Exception as e:
        logger.error(f"Error getting contrast constructs: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/constructs", methods=["GET"])
def get_constructs():
    """
    Get all cognitive constructs

    Query parameters:
    - name: Filter by construct name (partial match)
    - min_confidence: Minimum overall confidence threshold
    """
    try:
        db = get_db()

        # Get all construct nodes
        constructs = db.find_nodes(labels="CognitiveConstruct")

        # Get query parameters
        name_filter = request.args.get("name", "").lower()
        try:
            min_confidence = float(request.args.get("min_confidence", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "min_confidence must be a number"}), 400
        try:
            limit_val = _parse_int_param(
                "limit", request.args.get("limit"), default=None, minimum=0
            )
            offset_val = _parse_int_param(
                "offset", request.args.get("offset"), default=0, minimum=0
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        result = []
        for node_id, node_data in constructs:
            construct_name = node_data.get("name", "")

            # Apply name filter
            if name_filter and name_filter not in construct_name.lower():
                continue

            construct_info = {
                "id": node_data.get("construct_id"),
                "name": construct_name,
                "node_id": str(node_id),
            }

            # Get usage statistics
            relationships = db.find_relationships(
                end_node=node_id, rel_type="INVOLVES_CONSTRUCT"
            )

            # Calculate average confidence
            if relationships:
                confidences = [
                    edge_data.get("overall_confidence", 0)
                    for _, _, edge_data in relationships
                ]
                avg_confidence = sum(confidences) / len(confidences)

                # Apply confidence filter
                if avg_confidence < min_confidence:
                    continue

                construct_info["usage_count"] = len(relationships)
                construct_info["avg_confidence"] = round(avg_confidence, 3)
            else:
                construct_info["usage_count"] = 0
                construct_info["avg_confidence"] = 0

            result.append(construct_info)

        # Sort by usage count
        result.sort(key=lambda x: x["usage_count"], reverse=True)

        total = len(result)
        if offset_val or limit_val is not None:
            start = max(0, offset_val)
            end = start + limit_val if limit_val is not None else None
            result = result[start:end]

        payload = {"constructs": result, "total": total}
        if limit_val is not None:
            payload["limit"] = limit_val
            payload["offset"] = offset_val
        return jsonify(payload)

    except Exception as e:
        logger.error(f"Error getting constructs: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/search", methods=["GET"])
def search():
    """
    Search across datasets, contrasts, and constructs

    Query parameters:
    - q: Search query
    - type: Filter by type (dataset, contrast, construct)
    """
    try:
        db = get_db()

        query = request.args.get("q", "").lower()
        type_filter = request.args.get("type")

        if not query:
            return jsonify({"error": "Search query required"}), 400

        try:
            limit_val = _parse_int_param(
                "limit", request.args.get("limit"), default=None, minimum=0
            )
            offset_val = _parse_int_param(
                "offset", request.args.get("offset"), default=0, minimum=0
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        results = {"datasets": [], "contrasts": [], "constructs": []}
        rerank_flag = (request.args.get("rerank") or os.environ.get("BR_SEARCH_RERANK", "")).lower()

        # Search datasets
        if not type_filter or type_filter == "dataset":
            datasets = db.find_nodes(labels="Dataset")
            for node_id, node_data in datasets:
                if (
                    query in node_data.get("dataset_id", "").lower()
                    or query in node_data.get("name", "").lower()
                ):
                    results["datasets"].append(
                        {
                            "id": str(node_id),
                            "dataset_id": node_data.get("dataset_id"),
                            "name": node_data.get("name"),
                        }
                    )

        # Search contrasts
        if not type_filter or type_filter == "contrast":
            contrasts = db.find_nodes(labels="Contrast")
            for node_id, node_data in contrasts:
                if (
                    query in node_data.get("name", "").lower()
                    or query in node_data.get("task_label", "").lower()
                ):
                    results["contrasts"].append(
                        {
                            "id": str(node_id),
                            "name": node_data.get("name"),
                            "task_label": node_data.get("task_label"),
                            "dataset_id": node_data.get("dataset_id"),
                        }
                    )

        # Search constructs
        if not type_filter or type_filter == "construct":
            constructs = db.find_nodes(labels="CognitiveConstruct")
            for node_id, node_data in constructs:
                if query in node_data.get("name", "").lower():
                    results["constructs"].append(
                        {
                            "id": node_data.get("construct_id"),
                            "name": node_data.get("name"),
                            "node_id": str(node_id),
                        }
                    )

        # Optional NiCLIP re-rank (constructs only by default)
        if rerank_flag in {"1", "true", "yes", "on", "niclip"} and results["constructs"]:
            try:
                from brain_researcher.services.tools.niclip_tool import rerank_items

                reranked, meta = rerank_items(query, results["constructs"], text_key="name")
                results["constructs"] = reranked
                results["rerank"] = meta
            except Exception as exc:  # pragma: no cover - optional dependency
                results["rerank"] = {"status": "error", "reason": str(exc)}

        # Optional literature (GFS) re-rank
        if rerank_flag in {"gfs", "literature", "gfs_lit", "gfs_all"}:
            try:
                from brain_researcher.core.literature.gfs_store import search_gfs_auto

                gfs_result = search_gfs_auto(
                    query,
                    top_k=5,
                    weak_evidence=True,
                    max_calls=2,
                )
                hits = gfs_result.get("hits") or []
                corpus = " ".join(
                    f"{hit.get('title', '')} {hit.get('text', '')}" for hit in hits
                ).lower()

                def _score_item(item: dict[str, Any], keys: list[str]) -> int:
                    score = 0
                    for key in keys:
                        text = str(item.get(key, "") or "").strip().lower()
                        if not text:
                            continue
                        score += corpus.count(text)
                    return score

                def _rerank(items: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
                    scored = []
                    for item in items:
                        score = _score_item(item, keys)
                        scored.append((score, item))
                    scored.sort(key=lambda pair: pair[0], reverse=True)
                    return [item for _, item in scored]

                target_all = rerank_flag == "gfs_all"
                if (target_all or rerank_flag in {"gfs", "literature", "gfs_lit"}) and results["constructs"]:
                    results["constructs"] = _rerank(results["constructs"], ["name"])
                if target_all and results["datasets"]:
                    results["datasets"] = _rerank(results["datasets"], ["dataset_id", "name"])
                if target_all and results["contrasts"]:
                    results["contrasts"] = _rerank(results["contrasts"], ["name", "task_label", "dataset_id"])

                results["rerank_gfs"] = {
                    "status": gfs_result.get("status"),
                    "store": gfs_result.get("store"),
                    "model": gfs_result.get("model"),
                    "n_docs_hit": len(hits),
                }
            except Exception as exc:  # pragma: no cover - optional dependency
                results["rerank_gfs"] = {"status": "error", "reason": str(exc)}

        # Add totals
        results["total"] = {
            "datasets": len(results["datasets"]),
            "contrasts": len(results["contrasts"]),
            "constructs": len(results["constructs"]),
            "all": sum(len(v) for v in results.values() if isinstance(v, list)),
        }

        if offset_val or limit_val is not None:
            for key in ("datasets", "contrasts", "constructs"):
                items = results[key]
                start = max(0, offset_val)
                end = start + limit_val if limit_val is not None else None
                results[key] = items[start:end]
            if limit_val is not None:
                results["limit"] = limit_val
                results["offset"] = offset_val

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error searching: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/stats", methods=["GET"])
def get_stats():
    """Get statistics about the GLM FitLins data"""
    try:
        db = get_db()
        stats = db.get_stats()

        # Get specific counts
        datasets = db.find_nodes(labels="Dataset")
        contrasts = db.find_nodes(labels="Contrast")
        constructs = db.find_nodes(labels="CognitiveConstruct")
        subject_groups = db.find_nodes(labels="SubjectGroup")
        subjects = db.find_nodes(labels="Subject")
        phenotypes = db.find_nodes(labels="Phenotype")

        # Calculate relationship statistics
        involves_rels = []
        for node_id, _ in contrasts:
            rels = db.find_relationships(
                start_node=node_id, rel_type="INVOLVES_CONSTRUCT"
            )
            involves_rels.extend(rels)

        # Count new relationship types
        includes_rels = db.find_relationships(rel_type="INCLUDES")
        has_subject_rels = db.find_relationships(rel_type="HAS_SUBJECT")
        has_phenotype_rels = db.find_relationships(rel_type="HAS_PHENOTYPE")

        # Calculate confidence statistics
        confidences = {"llm": [], "literature": [], "overall": []}

        for _, _, edge_data in involves_rels:
            confidences["llm"].append(edge_data.get("llm_confidence", 0))
            confidences["literature"].append(edge_data.get("literature_confidence", 0))
            confidences["overall"].append(edge_data.get("overall_confidence", 0))

        def calc_stats(values):
            if not values:
                return {"mean": 0, "min": 0, "max": 0}
            return {
                "mean": round(sum(values) / len(values), 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
            }

        return jsonify(
            {
                "database": {
                    "total_nodes": stats.get("total_nodes", 0),
                    "total_relationships": stats.get("total_relationships", 0),
                },
                "glmfitlins": {
                    "datasets": len(datasets),
                    "contrasts": len(contrasts),
                    "constructs": len(constructs),
                    "annotations": len(involves_rels),
                    "subject_groups": len(subject_groups),
                    "subjects": len(subjects),
                    "phenotypes": len(phenotypes),
                },
                "relationships": {
                    "involves_construct": len(involves_rels),
                    "includes": len(includes_rels),
                    "has_subject": len(has_subject_rels),
                    "has_phenotype": len(has_phenotype_rels),
                },
                "confidence_stats": {
                    "llm": calc_stats(confidences["llm"]),
                    "literature": calc_stats(confidences["literature"]),
                    "overall": calc_stats(confidences["overall"]),
                },
            }
        )

    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/concept-aliases", methods=["GET"])
def get_concept_aliases():
    """
    Get concept aliases mapping

    Returns the mapping of concept name variations to canonical IDs
    """
    try:
        import csv

        aliases_file = Path(__file__).parent.parent.parent / "concept_aliases.tsv"

        if not aliases_file.exists():
            return (
                jsonify(
                    {
                        "error": "Concept aliases file not found. Run generate_concept_aliases.py first."
                    }
                ),
                404,
            )

        aliases = []
        with open(aliases_file) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                aliases.append({"alias": row["alias"], "concept_id": row["concept_id"]})

        # Group by concept_id for easier lookup
        grouped = {}
        for alias in aliases:
            concept_id = alias["concept_id"]
            if concept_id not in grouped:
                grouped[concept_id] = []
            grouped[concept_id].append(alias["alias"])

        return jsonify(
            {
                "aliases": aliases,
                "grouped_by_concept": grouped,
                "total_aliases": len(aliases),
                "total_concepts": len(grouped),
            }
        )

    except Exception as e:
        logger.error(f"Error getting concept aliases: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/priors", methods=["GET"])
def get_glm_priors():
    """Get GLM design priors (dataset/task/global) when available."""
    try:
        from brain_researcher.services.neurokg import query_service

        dataset_id = request.args.get("dataset_id") or request.args.get("study_id")
        task = request.args.get("task")
        mode = (request.args.get("mode") or "distribution").lower()
        if mode not in {"distribution", "family"}:
            return jsonify({"error": "mode must be 'distribution' or 'family'"}), 400

        try:
            seed = _parse_int_param("seed", request.args.get("seed"), default=None)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if mode == "family":
            try:
                k = _parse_int_param(
                    "k", request.args.get("k"), default=24, minimum=1
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        else:
            k = None

        scope_override = "global" if not dataset_id and not task else None
        result = None
        backend_error = None
        try:
            result = query_service.get_glm_priors(
                task=task,
                study_id=dataset_id,
                db=query_service.get_default_db(),
                scope=scope_override,
            )
        except Exception as exc:
            backend_error = exc

        if result is None:
            # Fallback for SQLite/JSON mock databases
            try:
                db = get_db()
                result = _get_glm_priors_from_graph_db(
                    db, task=task, dataset_id=dataset_id, scope=scope_override
                )
            except Exception as exc:
                backend_error = backend_error or exc
                result = None

        if not result:
            if backend_error:
                return jsonify({"error": "GLM priors backend unavailable"}), 503
            if scope_override == "global":
                result = {
                    "priors": _DEFAULT_GLM_PRIORS,
                    "scanned": 0,
                    "source": "default",
                    "scope": "global",
                    "support": {"n_nodes_scanned": 0, "n_datasets": 0, "n_tasks": 0},
                }
            else:
                return jsonify({"error": "GLM priors not found"}), 404

        support = result.get("support") or {}
        support.setdefault("n_nodes_scanned", result.get("scanned", 0))
        if "n_datasets" not in support:
            support["n_datasets"] = 1 if dataset_id else 0
        if "n_tasks" not in support:
            support["n_tasks"] = 1 if task else 0
        coverage = result.get("coverage") or {}

        # Respect priors as-is (no default axis injection unless no priors exist)
        priors = dict(result.get("priors") or {})
        result["priors"] = priors

        sources = dict(result.get("sources") or {})
        if result.get("source") == "neurokg":
            sources.setdefault("neurokg", support)
        if result.get("literature_support"):
            sources.setdefault("literature", result.get("literature_support"))
        if result.get("source") == "default":
            sources.setdefault("default", {"axes": sorted(priors.keys())})
        if sources:
            result["sources"] = sources

        if mode == "family":
            spec_family = _generate_spec_family(
                result.get("priors", {}),
                k=k or 0,
                seed=seed,
                support=result.get("support"),
                literature_support=result.get("literature_support"),
            )
            return jsonify(
                {
                    "scope": result.get("scope", scope_override or "global"),
                    "source": result.get("source", "neurokg"),
                    "support": support,
                    "coverage": coverage,
                    "literature_support": result.get("literature_support"),
                    "sources": result.get("sources"),
                    "spec_family": spec_family,
                }
            )

        payload = dict(result)
        payload["support"] = support
        payload["coverage"] = coverage
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Error getting GLM priors: {str(e)}")
        return jsonify({"error": str(e)}), 500


@glmfitlins_bp.route("/constructs/<construct_id>/contrasts", methods=["GET"])
def get_construct_contrasts(construct_id: str):
    """Get contrasts linked to a cognitive construct."""
    try:
        db = get_db()
        try:
            min_conf = float(request.args.get("min_confidence", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "min_confidence must be a number"}), 400
        dataset_id = request.args.get("dataset_id")
        try:
            limit_val = _parse_int_param(
                "limit", request.args.get("limit"), default=100, minimum=0
            )
            offset_val = _parse_int_param(
                "offset", request.args.get("offset"), default=0, minimum=0
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        # Resolve construct node
        construct_nodes = db.find_nodes(
            labels="CognitiveConstruct", properties={"construct_id": construct_id}
        )
        if not construct_nodes:
            # Fallback: check direct node id
            if construct_id in db.graph.nodes:
                construct_nodes = [(construct_id, db.graph.nodes[construct_id])]
        if not construct_nodes:
            return jsonify({"error": f"Construct {construct_id} not found"}), 404

        construct_node_id = construct_nodes[0][0]
        rels = db.find_relationships(
            end_node=construct_node_id, rel_type="INVOLVES_CONSTRUCT"
        )

        results = []
        for start_node, _, edge_data in rels:
            contrast_nodes = db.find_nodes(properties={"id": start_node})
            if not contrast_nodes:
                if start_node in db.graph.nodes:
                    contrast_nodes = [(start_node, db.graph.nodes[start_node])]
            if not contrast_nodes:
                continue
            _, contrast_data = contrast_nodes[0]
            if dataset_id and contrast_data.get("dataset_id") != dataset_id:
                continue
            overall = edge_data.get("overall_confidence", 0) or 0
            if overall < min_conf:
                continue
            results.append(
                {
                    "id": str(start_node),
                    "name": contrast_data.get("name"),
                    "task_label": contrast_data.get("task_label"),
                    "dataset_id": contrast_data.get("dataset_id"),
                    "direction": edge_data.get("direction", "+1"),
                    "llm_confidence": edge_data.get("llm_confidence", 0),
                    "literature_confidence": edge_data.get("literature_confidence", 0),
                    "overall_confidence": overall,
                }
            )

        results.sort(key=lambda x: x["overall_confidence"], reverse=True)
        total = len(results)
        results = results[offset_val : offset_val + limit_val]
        return jsonify(
            {
                "construct_id": construct_id,
                "contrasts": results,
                "total": total,
                "limit": limit_val,
                "offset": offset_val,
            }
        )
    except Exception as e:
        logger.error(f"Error getting construct contrasts: {str(e)}")
        return jsonify({"error": str(e)}), 500


def _collect_contrast_constructs(db, contrast_id: str):
    """Internal helper: return constructs for a contrast id."""
    relationships = db.find_relationships(
        start_node=contrast_id, rel_type="INVOLVES_CONSTRUCT"
    )
    if not relationships:
        return []

    result = []
    for _, end, edge_data in relationships:
        construct_nodes = db.find_nodes(properties={"id": end})
        if not construct_nodes:
            if end in db.graph.nodes:
                construct_nodes = [(end, db.graph.nodes[end])]
        if construct_nodes:
            _, construct_data = construct_nodes[0]
            construct_info = {
                "id": construct_data.get("construct_id"),
                "name": construct_data.get("name"),
                "direction": edge_data.get("direction", "+1"),
                "llm_confidence": edge_data.get("llm_confidence", 0),
                "literature_confidence": edge_data.get("literature_confidence", 0),
                "overall_confidence": edge_data.get("overall_confidence", 0),
            }
            result.append(construct_info)
    result.sort(key=lambda x: x["overall_confidence"], reverse=True)
    return result


def _get_glm_priors_from_graph_db(
    db, *, task: str | None, dataset_id: str | None, scope: str | None = None
):
    """Fallback GLM priors lookup for SQLite/JSON graph databases."""
    nodes = db.find_nodes(labels="GLMDesignPrior")
    if not nodes:
        return None

    task_value = (task or "").strip()
    scope_value = scope.lower() if scope else None
    if scope_value not in {None, "dataset", "task", "global"}:
        scope_value = None

    def _match_task(node_task: str | None) -> bool:
        if not task_value:
            return True
        if not node_task:
            return False
        return task_value.lower() in str(node_task).lower()

    def _collect(matches):
        priors = {}
        scanned = 0
        datasets = set()
        tasks = set()
        coverage_sums: dict[str, float] = {}
        coverage_weights: dict[str, float] = {}
        total_specs = 0
        for _, node in matches:
            axes = node.get("axes") or {}
            if not isinstance(axes, dict):
                continue
            for axis, vals in axes.items():
                if not isinstance(vals, dict):
                    continue
                priors.setdefault(axis, {})
                for opt, val in vals.items():
                    try:
                        priors[axis][opt] = priors[axis].get(opt, 0.0) + float(val)
                    except Exception:
                        continue
            scanned += 1
            node_support = node.get("support") or {}
            node_n_specs = node_support.get("n_specs") or node.get("n_specs")
            try:
                node_n_specs = int(node_n_specs) if node_n_specs is not None else 0
            except (TypeError, ValueError):
                node_n_specs = 0
            if node_n_specs:
                total_specs += node_n_specs
                node_coverage = node.get("coverage") or {}
                if isinstance(node_coverage, dict):
                    for axis, value in node_coverage.items():
                        try:
                            cov_val = float(value)
                        except (TypeError, ValueError):
                            continue
                        coverage_sums[axis] = coverage_sums.get(axis, 0.0) + (cov_val * node_n_specs)
                        coverage_weights[axis] = coverage_weights.get(axis, 0.0) + node_n_specs
            dataset_val = node.get("dataset_id") or node.get("study_id")
            if dataset_val:
                datasets.add(str(dataset_val))
            task_val = node.get("task") or node.get("task_label") or node.get("task_name")
            if task_val:
                task_str = str(task_val)
                if task_str.lower() not in {"__all__", "all"}:
                    tasks.add(task_str)
        if not priors:
            return None
        for axis, vals in list(priors.items()):
            total = sum(vals.values())
            if total <= 0:
                priors.pop(axis, None)
                continue
            priors[axis] = {k: v / total for k, v in vals.items()}
        coverage = {
            axis: (coverage_sums[axis] / coverage_weights[axis])
            for axis in coverage_sums
            if coverage_weights.get(axis, 0.0) > 0
        }
        support = {
            "n_nodes_scanned": scanned,
            "n_datasets": len(datasets),
            "n_tasks": len(tasks),
        }
        if total_specs:
            support["n_specs"] = total_specs
        payload = {
            "priors": priors,
            "scanned": scanned,
            "source": "neurokg",
            "support": support,
        }
        if coverage:
            payload["coverage"] = coverage
        return payload

    # Dataset scope
    if dataset_id and scope_value in {None, "dataset"}:
        dataset_matches = [
            (nid, n)
            for nid, n in nodes
            if n.get("dataset_id") == dataset_id and _match_task(n.get("task"))
        ]
        if dataset_matches:
            out = _collect(dataset_matches)
            if out:
                out["scope"] = "dataset"
                return out

    # Task scope
    if scope_value in {None, "task"}:
        if scope_value == "task" and not task_value:
            return None
        task_matches = [
            (nid, n)
            for nid, n in nodes
            if not n.get("dataset_id") and _match_task(n.get("task"))
        ]
        if task_matches:
            out = _collect(task_matches)
            if out:
                out["scope"] = "task"
                return out

    # Global scope
    if scope_value in {None, "global"}:
        global_matches = [
            (nid, n)
            for nid, n in nodes
            if str(n.get("task", "")).lower() in {"__all__", "all"} or not n.get("task")
        ]
        if global_matches:
            out = _collect(global_matches)
            if out:
                out["scope"] = "global"
                return out
    return None


@glmfitlins_bp.route("/contrasts/constructs:batch", methods=["POST"])
def get_contrast_constructs_batch():
    """Batch fetch constructs for multiple contrasts."""
    try:
        db = get_db()
        payload = request.get_json(silent=True) or {}
        contrast_ids = payload.get("contrast_ids") or []
        try:
            min_conf = float(payload.get("min_confidence", 0) or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "min_confidence must be a number"}), 400
        if not isinstance(contrast_ids, list) or not contrast_ids:
            return jsonify({"error": "contrast_ids must be a non-empty list"}), 400

        results = []
        for contrast_id in contrast_ids:
            if not isinstance(contrast_id, str):
                continue
            constructs = _collect_contrast_constructs(db, contrast_id)
            if min_conf:
                constructs = [
                    c for c in constructs if c.get("overall_confidence", 0) >= min_conf
                ]
            results.append(
                {
                    "contrast_id": contrast_id,
                    "constructs": constructs,
                    "total": len(constructs),
                }
            )

        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        logger.error(f"Error batch fetching constructs: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Export blueprint
__all__ = ["glmfitlins_bp"]
