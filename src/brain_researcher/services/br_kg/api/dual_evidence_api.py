#!/usr/bin/env python3
"""
Dual Evidence Graph API

Flask API endpoints for querying and managing dual evidence in the
knowledge graph. Provides REST endpoints for:

1. Dual evidence concept queries
2. Evidence conflict management
3. Evidence statistics and analytics
4. Cross-source validation
5. Evidence history and lineage

Key Features:
- Spatial evidence queries
- Conflict detection and resolution
- Evidence provenance tracking
- Multi-source confidence analysis
- Knowledge graph visualization
"""

import json
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Create blueprint
dual_evidence_bp = Blueprint("dual_evidence", __name__, url_prefix="/api/dual-evidence")

# Global integrator instance
_integrator = None


def init_dual_evidence_api(integrator_instance):
    """Initialize the dual evidence API with integrator instance."""
    global _integrator
    _integrator = integrator_instance
    logger.info("Dual Evidence API initialized")


def get_integrator():
    """Get the dual evidence integrator instance."""
    global _integrator
    if _integrator is None:
        from brain_researcher.services.br_kg.etl.mappers.dual_evidence_integrator import (
            DualEvidenceIntegrator,
        )

        _integrator = DualEvidenceIntegrator()
    return _integrator


@dual_evidence_bp.route("/health", methods=["GET"])
def health_check():
    """Health check for dual evidence API."""
    try:
        integrator = get_integrator()
        stats = integrator.graph.get_dual_evidence_stats()
        return jsonify(
            {
                "status": "healthy",
                "database": integrator.db_path,
                "evidence_nodes": stats["dual_evidence"]["evidence_nodes"],
                "fused_concepts": stats["dual_evidence"]["fused_concepts"],
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@dual_evidence_bp.route("/concepts", methods=["GET"])
def query_dual_evidence_concepts():
    """
    Query for concepts with dual evidence.

    Query Parameters:
    - coordinates: JSON array of [x,y,z] coordinates
    - radius: Search radius in mm (default: 10.0)
    - min_confidence: Minimum consensus confidence (default: 0.5)
    - require_multiple_sources: Require multiple evidence sources (default: true)
    """
    try:
        integrator = get_integrator()

        # Parse query parameters
        coordinates_param = request.args.get("coordinates")
        if coordinates_param:
            coordinates = json.loads(coordinates_param)
        else:
            return jsonify({"error": "coordinates parameter required"}), 400

        radius = float(request.args.get("radius", 10.0))
        min_confidence = float(request.args.get("min_confidence", 0.5))
        require_multiple_sources = (
            request.args.get("require_multiple_sources", "true").lower() == "true"
        )

        # Query dual evidence concepts
        concepts = integrator.query_dual_evidence_concepts(
            coordinates=coordinates,
            radius=radius,
            min_consensus_confidence=min_confidence,
            require_multiple_sources=require_multiple_sources,
        )

        return jsonify(
            {
                "query": {
                    "coordinates": coordinates,
                    "radius": radius,
                    "min_confidence": min_confidence,
                    "require_multiple_sources": require_multiple_sources,
                },
                "results": {"count": len(concepts), "concepts": concepts},
            }
        )

    except Exception as e:
        logger.error(f"Error querying dual evidence concepts: {e}")
        return jsonify({"error": str(e)}), 500


@dual_evidence_bp.route("/conflicts", methods=["GET"])
def get_evidence_conflicts():
    """
    Get evidence conflicts, optionally filtered.

    Query Parameters:
    - concept_name: Filter by concept name
    - conflict_type: Filter by conflict type
    - unresolved_only: Only return unresolved conflicts (default: true)
    - coordinates: Optional spatial filter as JSON array
    - radius: Spatial search radius in mm (default: 15.0)
    """
    try:
        integrator = get_integrator()

        # Parse query parameters
        concept_name = request.args.get("concept_name")
        conflict_type = request.args.get("conflict_type")
        unresolved_only = request.args.get("unresolved_only", "true").lower() == "true"
        coordinates_param = request.args.get("coordinates")
        radius = float(request.args.get("radius", 15.0))

        if coordinates_param:
            # Spatial conflict query
            coordinates = json.loads(coordinates_param)
            conflicts = integrator.get_evidence_conflicts_for_region(
                coordinates=coordinates, radius=radius
            )
        else:
            # General conflict query
            conflicts = integrator.graph.get_evidence_conflicts(
                concept_name=concept_name,
                conflict_type=conflict_type,
                unresolved_only=unresolved_only,
            )

        return jsonify(
            {
                "query": {
                    "concept_name": concept_name,
                    "conflict_type": conflict_type,
                    "unresolved_only": unresolved_only,
                    "spatial_filter": coordinates_param is not None,
                },
                "results": {"count": len(conflicts), "conflicts": conflicts},
            }
        )

    except Exception as e:
        logger.error(f"Error getting evidence conflicts: {e}")
        return jsonify({"error": str(e)}), 500


@dual_evidence_bp.route("/conflicts/<conflict_id>/resolve", methods=["POST"])
def resolve_conflict(conflict_id: str):
    """
    Resolve an evidence conflict.

    Request Body:
    - resolution_method: Method used to resolve conflict
    - resolution_data: Data about the resolution
    """
    try:
        integrator = get_integrator()

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        resolution_method = data.get("resolution_method", "manual")
        resolution_data = data.get("resolution_data", {})

        success = integrator.graph.resolve_conflict(
            conflict_id=conflict_id,
            resolution_method=resolution_method,
            resolution_data=resolution_data,
        )

        if success:
            return jsonify(
                {
                    "status": "resolved",
                    "conflict_id": conflict_id,
                    "resolution_method": resolution_method,
                }
            )
        else:
            return jsonify({"error": "Failed to resolve conflict"}), 500

    except Exception as e:
        logger.error(f"Error resolving conflict {conflict_id}: {e}")
        return jsonify({"error": str(e)}), 500


@dual_evidence_bp.route("/enhanced-query", methods=["POST"])
def enhanced_query():
    """
    Enhanced query with evidence history and context.

    Request Body:
    - coordinates: Array of [x,y,z] coordinates
    - radius: Search radius in mm (default: 10.0)
    """
    try:
        integrator = get_integrator()

        data = request.get_json()
        if not data or "coordinates" not in data:
            return jsonify({"error": "coordinates required in request body"}), 400

        coordinates = data["coordinates"]
        radius = data.get("radius", 10.0)

        # Get enhanced query results
        enhanced_results = integrator.enhance_query_with_evidence_history(
            coordinates=coordinates, radius=radius
        )

        return jsonify(enhanced_results)

    except Exception as e:
        logger.error(f"Error performing enhanced query: {e}")
        return jsonify({"error": str(e)}), 500


@dual_evidence_bp.route("/validation/glm", methods=["POST"])
def validate_with_glm():
    """
    Validate evidence using GLM data.

    Request Body:
    - concept_name: Name of concept to validate
    - coordinates: Array of [x,y,z] coordinates
    - contrast_name: Contrast name for GLM lookup
    """
    try:
        integrator = get_integrator()

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        concept_name = data.get("concept_name")
        coordinates = data.get("coordinates")
        contrast_name = data.get("contrast_name")

        if not all([concept_name, coordinates, contrast_name]):
            return (
                jsonify(
                    {"error": "concept_name, coordinates, and contrast_name required"}
                ),
                400,
            )

        # Perform GLM validation
        validation_result = integrator.validate_evidence_with_glm(
            concept_name=concept_name,
            coordinates=coordinates,
            contrast_name=contrast_name,
        )

        return jsonify(validation_result)

    except Exception as e:
        logger.error(f"Error performing GLM validation: {e}")
        return jsonify({"error": str(e)}), 500


@dual_evidence_bp.route("/stats", methods=["GET"])
def get_dual_evidence_stats():
    """Get comprehensive dual evidence statistics."""
    try:
        integrator = get_integrator()
        stats = integrator.graph.get_dual_evidence_stats()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting dual evidence stats: {e}")
        return jsonify({"error": str(e)}), 500


@dual_evidence_bp.route("/export", methods=["GET"])
def export_evidence_summary():
    """
    Export evidence summary.

    Query Parameters:
    - format: Export format (json, csv) - default: json
    - include_conflicts: Include conflict data (default: true)
    - include_concepts: Include concept data (default: true)
    """
    try:
        integrator = get_integrator()

        # Parse query parameters
        export_format = request.args.get("format", "json").lower()
        include_conflicts = (
            request.args.get("include_conflicts", "true").lower() == "true"
        )
        include_concepts = (
            request.args.get("include_concepts", "true").lower() == "true"
        )

        # Get evidence summary
        summary = integrator.export_evidence_summary()

        # Filter based on parameters
        if not include_conflicts:
            summary.pop("evidence_conflicts", None)
        if not include_concepts:
            summary.pop("dual_evidence_concepts", None)

        if export_format == "json":
            return jsonify(summary)
        else:
            return jsonify({"error": f"Unsupported format: {export_format}"}), 400

    except Exception as e:
        logger.error(f"Error exporting evidence summary: {e}")
        return jsonify({"error": str(e)}), 500


@dual_evidence_bp.route("/store-fusion", methods=["POST"])
def store_fusion_result():
    """
    Store a fusion result in the dual evidence graph.

    Request Body:
    - contrast_name: Name of the contrast/query
    - task_name: Name of the task context
    - coordinates: Array of [x,y,z] coordinates
    - fusion_result: Fusion analysis result
    - niclip_data: Optional NiCLIP data
    - llm_data: Optional LLM data
    """
    try:
        integrator = get_integrator()

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        required_fields = ["contrast_name", "task_name", "coordinates", "fusion_result"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Required field missing: {field}"}), 400

        # Store fusion result
        created_nodes = integrator.store_fusion_result(
            contrast_name=data["contrast_name"],
            task_name=data["task_name"],
            coordinates=data["coordinates"],
            fusion_result=data["fusion_result"],
            niclip_data=data.get("niclip_data"),
            llm_data=data.get("llm_data"),
        )

        return jsonify(
            {
                "status": "stored",
                "created_nodes": created_nodes,
                "node_count": len(created_nodes),
            }
        )

    except Exception as e:
        logger.error(f"Error storing fusion result: {e}")
        return jsonify({"error": str(e)}), 500


# Error handlers
@dual_evidence_bp.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@dual_evidence_bp.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


# Blueprint information endpoint
@dual_evidence_bp.route("/", methods=["GET"])
def blueprint_info():
    """Information about the dual evidence API."""
    return jsonify(
        {
            "name": "Dual Evidence Graph API",
            "version": "1.0.0",
            "endpoints": {
                "/health": "API health check",
                "/concepts": "Query dual evidence concepts",
                "/conflicts": "Get evidence conflicts",
                "/conflicts/<id>/resolve": "Resolve a conflict",
                "/enhanced-query": "Enhanced query with history",
                "/validation/glm": "GLM validation",
                "/stats": "Dual evidence statistics",
                "/export": "Export evidence summary",
                "/store-fusion": "Store fusion result",
            },
            "description": "API for querying and managing dual evidence from NiCLIP and LLM sources",
        }
    )


if __name__ == "__main__":
    # Test the API endpoints
    from flask import Flask

    from brain_researcher.services.br_kg.etl.mappers.dual_evidence_integrator import (
        DualEvidenceIntegrator,
    )

    app = Flask(__name__)

    # Initialize with test integrator
    test_integrator = DualEvidenceIntegrator("test_dual_evidence_api.db")
    init_dual_evidence_api(test_integrator)

    # Register blueprint
    app.register_blueprint(dual_evidence_bp)

    print("Dual Evidence API test endpoints:")
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("dual_evidence"):
            print(f"  {rule.methods} {rule.rule}")

    # Test would run server here
    # app.run(debug=True, port=5000)
