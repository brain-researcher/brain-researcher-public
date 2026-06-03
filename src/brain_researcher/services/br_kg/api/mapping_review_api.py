#!/usr/bin/env python3
"""
Mapping Review API for BR-KG

Provides endpoints for reviewing and managing MAPS_TO relationships
created by the NodeLabelLinker and CrossSourceLinker.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request

# Create Blueprint
mapping_review_bp = Blueprint(
    "mapping_review", __name__, url_prefix="/api/mapping-review"
)

logger = logging.getLogger(__name__)

# This will be set by the main app
get_db_func = None


def init_mapping_review_api(get_db: Callable):
    """Initialize the mapping review API with database getter function."""
    global get_db_func
    get_db_func = get_db


def _parse_mapping_id(mapping_id: str) -> tuple[str, str]:
    if "->" not in mapping_id:
        raise ValueError("Invalid mapping ID format")
    return mapping_id.split("->", 1)


def _coerce_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value: {value}") from exc


def _collect_mapping_ids_from_filters(db: Any, filters: dict[str, Any]) -> list[str]:
    source_label = filters.get("source_label")
    target_label = filters.get("target_label")
    confidence_min = _coerce_float(filters.get("confidence_min"), default=0)
    confidence_max = _coerce_float(filters.get("confidence_max"), default=1)
    method = filters.get("method")
    created_by = filters.get("created_by")

    mapping_ids: list[str] = []
    for start_id, end_id, rel_data in db.find_relationships(rel_type="MAPS_TO"):
        start_node = db.get_node(start_id)
        end_node = db.get_node(end_id)
        if not start_node or not end_node:
            continue

        start_labels = start_node.get("labels", [])
        end_labels = end_node.get("labels", [])
        if source_label and source_label not in start_labels:
            continue
        if target_label and target_label not in end_labels:
            continue

        confidence_raw = rel_data.get("confidence", 0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < confidence_min or confidence > confidence_max:
            continue
        if method and rel_data.get("method") != method:
            continue
        if created_by and rel_data.get("created_by") != created_by:
            continue

        mapping_ids.append(f"{start_id}->{end_id}")

    return mapping_ids


def _approve_mapping_internal(
    db: Any, source_id: str, target_id: str, *, reviewer: str
) -> bool:
    relationships = db.find_relationships(
        start_node=source_id, end_node=target_id, rel_type="MAPS_TO"
    )
    if not relationships:
        return False

    patch = {
        "reviewed": True,
        "reviewed_at": datetime.utcnow().isoformat(),
        "reviewed_by": reviewer,
        "review_status": "approved",
    }

    update_relationship = getattr(db, "update_relationship", None)
    if callable(update_relationship):
        return bool(
            update_relationship(
                start_node=source_id,
                end_node=target_id,
                rel_type="MAPS_TO",
                properties=patch,
            )
        )

    updated = False
    rel_store = getattr(db, "_relationships", None)
    if isinstance(rel_store, list):
        for rel in rel_store:
            if (
                rel.get("start") == source_id
                and rel.get("end") == target_id
                and rel.get("data", {}).get("type") == "MAPS_TO"
            ):
                rel.setdefault("data", {}).update(patch)
                updated = True
    return updated


def _purge_cached_maps_to(db: Any, source_id: str, target_id: str) -> None:
    graph = getattr(db, "graph", None)
    if graph is None or not hasattr(graph, "has_edge"):
        return
    if not graph.has_edge(source_id, target_id):
        return

    if getattr(graph, "is_multigraph", lambda: False)():
        edges = list(graph.edges(keys=True, data=True))
        for u, v, key, data in edges:
            if (
                u == source_id
                and v == target_id
                and isinstance(data, dict)
                and data.get("type") == "MAPS_TO"
            ):
                graph.remove_edge(u, v, key=key)
        return

    edge_data = graph.get_edge_data(source_id, target_id) or {}
    if isinstance(edge_data, dict) and edge_data.get("type") == "MAPS_TO":
        graph.remove_edge(source_id, target_id)


def _delete_mapping_internal(db: Any, source_id: str, target_id: str) -> bool:
    relationships = db.find_relationships(
        start_node=source_id, end_node=target_id, rel_type="MAPS_TO"
    )
    if not relationships:
        return False

    execute_query = getattr(db, "execute_query", None)
    if callable(execute_query):
        rows = execute_query(
            (
                "MATCH (a {id:$source_id})-[r:MAPS_TO]->(b {id:$target_id}) "
                "WITH collect(r) AS rels "
                "WITH rels, size(rels) AS deleted_count "
                "FOREACH (rel IN rels | DELETE rel) "
                "RETURN deleted_count"
            ),
            {"source_id": source_id, "target_id": target_id},
        )
        if rows:
            deleted_count = int(rows[0].get("deleted_count") or 0)
            if deleted_count > 0:
                _purge_cached_maps_to(db, source_id, target_id)
            return deleted_count > 0

    rel_store = getattr(db, "_relationships", None)
    if isinstance(rel_store, list):
        before = len(rel_store)
        rel_store[:] = [
            rel
            for rel in rel_store
            if not (
                rel.get("start") == source_id
                and rel.get("end") == target_id
                and rel.get("data", {}).get("type") == "MAPS_TO"
            )
        ]
        deleted = len(rel_store) < before
        if deleted:
            _purge_cached_maps_to(db, source_id, target_id)
        return deleted

    return False


@mapping_review_bp.route("/mappings", methods=["GET"])
def get_mappings():
    """
    Get MAPS_TO relationships for review.

    Query parameters:
    - source_label: Filter by source node label
    - target_label: Filter by target node label
    - confidence_min: Minimum confidence score (0-1)
    - confidence_max: Maximum confidence score (0-1)
    - method: Filter by matching method (embedding, fuzzy, exact)
    - created_by: Filter by creator (e.g., cross_source_linker, scheduled_linker)
    - limit: Maximum number of results (default: 100)
    - offset: Pagination offset (default: 0)
    - sort_by: Sort field (confidence, created_at)
    - sort_order: asc or desc (default: desc)
    """
    try:
        db = get_db_func()

        # Get query parameters
        source_label = request.args.get("source_label")
        target_label = request.args.get("target_label")
        confidence_min = float(request.args.get("confidence_min", 0))
        confidence_max = float(request.args.get("confidence_max", 1))
        method = request.args.get("method")
        created_by = request.args.get("created_by")
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        sort_by = request.args.get("sort_by", "confidence")
        sort_order = request.args.get("sort_order", "desc")

        # Get all MAPS_TO relationships
        all_mappings = db.find_relationships(rel_type="MAPS_TO")

        # Process and filter mappings
        processed_mappings = []

        for start_id, end_id, rel_data in all_mappings:
            # Get node details
            start_node = db.get_node(start_id)
            end_node = db.get_node(end_id)

            if not start_node or not end_node:
                continue

            # Extract labels
            start_labels = start_node.get("labels", [])
            end_labels = end_node.get("labels", [])

            # Apply label filters
            if source_label and source_label not in start_labels:
                continue
            if target_label and target_label not in end_labels:
                continue

            # Apply confidence filter
            confidence = rel_data.get("confidence", 0)
            if confidence < confidence_min or confidence > confidence_max:
                continue

            # Apply method filter
            if method and rel_data.get("method") != method:
                continue

            # Apply created_by filter
            if created_by and rel_data.get("created_by") != created_by:
                continue

            # Create mapping object
            mapping = {
                "id": f"{start_id}->{end_id}",
                "source": {
                    "id": start_id,
                    "name": start_node.get("name", ""),
                    "labels": start_labels,
                    "source": start_node.get("source", ""),
                },
                "target": {
                    "id": end_id,
                    "name": end_node.get("name", ""),
                    "labels": end_labels,
                    "source": end_node.get("source", ""),
                },
                "confidence": confidence,
                "method": rel_data.get("method", "unknown"),
                "created_by": rel_data.get("created_by", "unknown"),
                "created_at": rel_data.get("created_at")
                or rel_data.get("timestamp", ""),
                "properties": rel_data,
            }

            processed_mappings.append(mapping)

        # Sort mappings
        if sort_by == "confidence":
            processed_mappings.sort(
                key=lambda x: x["confidence"], reverse=(sort_order == "desc")
            )
        elif sort_by == "created_at":
            processed_mappings.sort(
                key=lambda x: x["created_at"], reverse=(sort_order == "desc")
            )

        # Apply pagination
        total = len(processed_mappings)
        processed_mappings = processed_mappings[offset : offset + limit]

        return jsonify(
            {
                "mappings": processed_mappings,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    except Exception as e:
        logger.error(f"Error getting mappings: {e}")
        return jsonify({"error": str(e)}), 500


@mapping_review_bp.route("/mappings/<mapping_id>", methods=["DELETE"])
def delete_mapping(mapping_id):
    """
    Delete a MAPS_TO relationship.

    Path parameters:
    - mapping_id: ID in format "source_id->target_id"
    """
    try:
        db = get_db_func()

        # Parse mapping ID
        try:
            source_id, target_id = _parse_mapping_id(mapping_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        # Find and delete the relationship
        relationships = db.find_relationships(
            start_node=source_id, end_node=target_id, rel_type="MAPS_TO"
        )
        if not relationships:
            return jsonify({"error": "Mapping not found"}), 404

        if _delete_mapping_internal(db, source_id, target_id):
            return jsonify({"message": "Mapping deleted successfully"})
        return jsonify({"error": "Failed to delete mapping"}), 500

    except Exception as e:
        logger.error(f"Error deleting mapping: {e}")
        return jsonify({"error": str(e)}), 500


@mapping_review_bp.route("/mappings/<mapping_id>/approve", methods=["POST"])
def approve_mapping(mapping_id):
    """
    Approve a MAPS_TO relationship by updating its properties.

    Path parameters:
    - mapping_id: ID in format "source_id->target_id"
    """
    try:
        db = get_db_func()

        # Parse mapping ID
        try:
            source_id, target_id = _parse_mapping_id(mapping_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        # Find the relationship
        relationships = db.find_relationships(
            start_node=source_id, end_node=target_id, rel_type="MAPS_TO"
        )

        if not relationships:
            return jsonify({"error": "Mapping not found"}), 404

        payload = request.get_json(silent=True) or {}
        reviewer = str(payload.get("reviewer") or "user")
        if _approve_mapping_internal(db, source_id, target_id, reviewer=reviewer):
            return jsonify({"message": "Mapping approved successfully"})
        return jsonify({"error": "Failed to approve mapping"}), 500

    except Exception as e:
        logger.error(f"Error approving mapping: {e}")
        return jsonify({"error": str(e)}), 500


@mapping_review_bp.route("/mappings/stats", methods=["GET"])
def get_mapping_stats():
    """
    Get statistics about MAPS_TO relationships.
    """
    try:
        db = get_db_func()

        # Get all MAPS_TO relationships
        all_mappings = db.find_relationships(rel_type="MAPS_TO")

        # Calculate statistics
        stats = {
            "total_mappings": len(all_mappings),
            "by_method": {},
            "by_source": {},
            "by_confidence": {
                "high": 0,  # >= 0.9
                "medium": 0,  # 0.7 - 0.9
                "low": 0,  # < 0.7
            },
            "by_label_pair": {},
            "reviewed": 0,
            "unreviewed": 0,
        }

        for start_id, end_id, rel_data in all_mappings:
            # Get node details
            start_node = db.get_node(start_id)
            end_node = db.get_node(end_id)

            if not start_node or not end_node:
                continue

            # Count by method
            method = rel_data.get("method", "unknown")
            stats["by_method"][method] = stats["by_method"].get(method, 0) + 1

            # Count by source
            created_by = rel_data.get("created_by", "unknown")
            stats["by_source"][created_by] = stats["by_source"].get(created_by, 0) + 1

            # Count by confidence
            confidence = rel_data.get("confidence", 0)
            if confidence >= 0.9:
                stats["by_confidence"]["high"] += 1
            elif confidence >= 0.7:
                stats["by_confidence"]["medium"] += 1
            else:
                stats["by_confidence"]["low"] += 1

            # Count by label pair
            start_labels = start_node.get("labels", [])
            end_labels = end_node.get("labels", [])

            for s_label in start_labels:
                for e_label in end_labels:
                    pair = f"{s_label}→{e_label}"
                    stats["by_label_pair"][pair] = (
                        stats["by_label_pair"].get(pair, 0) + 1
                    )

            # Count reviewed status
            if rel_data.get("reviewed"):
                stats["reviewed"] += 1
            else:
                stats["unreviewed"] += 1

        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting mapping stats: {e}")
        return jsonify({"error": str(e)}), 500


@mapping_review_bp.route("/mappings/bulk-action", methods=["POST"])
def bulk_action():
    """
    Perform bulk actions on multiple mappings.

    Request body:
    {
        "action": "approve" | "delete",
        "mapping_ids": ["source1->target1", "source2->target2", ...],
        "filters": {
            "confidence_min": 0.9,
            "method": "exact",
            ...
        }
    }
    """
    try:
        db = get_db_func()

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400

        action = data.get("action")
        mapping_ids = data.get("mapping_ids", [])
        filters = data.get("filters", {})
        reviewer = str(data.get("reviewer") or "user")

        if action not in ["approve", "delete"]:
            return jsonify({"error": "Invalid action"}), 400
        if not isinstance(mapping_ids, list):
            return jsonify({"error": "mapping_ids must be a list"}), 400
        if not isinstance(filters, dict):
            return jsonify({"error": "filters must be an object"}), 400

        # If no specific IDs provided, use filters to find mappings
        if not mapping_ids and filters:
            try:
                mapping_ids = _collect_mapping_ids_from_filters(db, filters)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        elif not mapping_ids:
            return jsonify({"error": "Provide mapping_ids or filters"}), 400

        mapping_ids = list(dict.fromkeys(str(mapping_id) for mapping_id in mapping_ids))

        # Process each mapping
        succeeded = 0
        errors = []

        for mapping_id in mapping_ids:
            try:
                source_id, target_id = _parse_mapping_id(mapping_id)

                if action == "approve":
                    ok = _approve_mapping_internal(
                        db, source_id, target_id, reviewer=reviewer
                    )
                elif action == "delete":
                    ok = _delete_mapping_internal(db, source_id, target_id)
                else:  # pragma: no cover - already validated above
                    ok = False

                if ok:
                    succeeded += 1
                else:
                    errors.append(
                        {"mapping_id": mapping_id, "error": "Mapping not found"}
                    )
            except Exception as e:
                errors.append({"mapping_id": mapping_id, "error": str(e)})

        processed = len(mapping_ids)
        failed = processed - succeeded
        return jsonify(
            {
                "processed": processed,
                "succeeded": succeeded,
                "failed": failed,
                "errors": errors,
            }
        )

    except Exception as e:
        logger.error(f"Error in bulk action: {e}")
        return jsonify({"error": str(e)}), 500
