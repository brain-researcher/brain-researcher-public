"""Runtime helpers for creating ACTIVATES edges from coordinate evidence.

CLI wrappers should import this module instead of depending on the legacy
script namespace.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from typing import Any, Iterable, Sequence

from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_ACTIVATION_LABELS: tuple[str, ...] = ("Task", "Concept")
STAT_KEYS: tuple[str, ...] = (
    "edges_created",
    "edges_skipped_threshold",
    "edges_skipped_exists",
    "errors",
)
PUBLICATION_NODE_LABELS: tuple[str, ...] = ("Study", "Publication")
REQUIRED_NODE_LABELS: tuple[str, ...] = (
    "Task",
    "Concept",
    "Coordinate",
    "BrainRegion",
)
REQUIRED_RELATIONSHIP_TYPES: tuple[str, ...] = (
    "STUDIES",
    "MENTIONS_CONCEPT",
    "HAS_COORDINATE",
    "LOCATED_IN",
)


def _empty_stats() -> dict[str, int]:
    return {key: 0 for key in STAT_KEYS}


def _normalize_counts(raw: Any) -> dict[str, int]:
    if isinstance(raw, list):
        return {str(item): 1 for item in raw}
    if isinstance(raw, dict):
        return {str(key): int(value) for key, value in raw.items()}
    return {}


def collect_coordinate_evidence(db: Any, label: str) -> dict[str, dict[str, set[str]]]:
    """Collect Task/Concept -> BrainRegion coordinate evidence."""
    if db.__class__.__name__ == "Neo4jGraphDB":
        cypher = f"""
        MATCH (n:{label})
        MATCH (n)<-[:STUDIES|MENTIONS_CONCEPT]-(p)
        WHERE p:Study OR p:Publication
        MATCH (p)-[:HAS_COORDINATE]->(c:Coordinate)
        MATCH (c)-[:LOCATED_IN]->(r:BrainRegion)
        RETURN n.id AS nid, r.name AS region, collect(distinct c.id) AS coords
        """
        rows = db.execute_query(cypher)
        evidence: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for row in rows:
            nid = row.get("nid")
            region = row.get("region")
            coords = row.get("coords") or []
            if nid and region:
                evidence[nid][region].update(coords)
        logger.info(
            "Evidence collection (Neo4j batch) complete: %s %s nodes",
            len(evidence),
            label,
        )
        return evidence

    evidence: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    nodes = db.find_nodes(labels=label)
    logger.info("Found %s %s nodes to process", len(nodes), label)

    nodes_processed = 0
    coords_found = 0

    for node_id, _node_data in nodes:
        publication_rels = db.find_relationships(end_node=node_id)
        publications = {
            start
            for start, _end, rel_data in publication_rels
            if rel_data.get("type") in {"STUDIES", "MENTIONS_CONCEPT"}
        }
        if not publications:
            continue

        for pub_id in publications:
            coord_rels = db.find_relationships(
                start_node=pub_id, rel_type="HAS_COORDINATE"
            )
            for _start, coord_id, _rel_data in coord_rels:
                region_rels = db.find_relationships(
                    start_node=coord_id, rel_type="LOCATED_IN"
                )
                for _coord, region_id, _region_rel in region_rels:
                    if region_id in db.graph.nodes:
                        region_data = db.graph.nodes[region_id]
                        region_name = region_data.get("name", region_id)
                        evidence[node_id][region_name].add(coord_id)
                        coords_found += 1

        nodes_processed += 1
        if nodes_processed % 100 == 0:
            logger.info(
                "Processed %s/%s %s nodes, found %s coordinate associations",
                nodes_processed,
                len(nodes),
                label,
                coords_found,
            )

    total_associations = sum(len(regions) for regions in evidence.values())
    logger.info(
        "Evidence collection complete: %s %s nodes have coordinate evidence",
        len(evidence),
        label,
    )
    logger.info("Total region associations: %s", total_associations)
    return evidence


def create_activation_edges(
    db: Any,
    evidence: dict[str, dict[str, set[str]]],
    label: str,
    threshold: int = 5,
    dry_run: bool = False,
) -> dict[str, int]:
    """Create ACTIVATES edges based on an evidence threshold."""
    stats = _empty_stats()
    logger.info("Creating ACTIVATES edges with threshold=%s", threshold)

    for node_id, regions in evidence.items():
        for region_name, coord_ids in regions.items():
            coord_count = len(coord_ids)
            if coord_count < threshold:
                stats["edges_skipped_threshold"] += 1
                continue

            region_nodes = db.find_nodes(
                labels="BrainRegion", properties={"name": region_name}
            )
            if not region_nodes:
                logger.warning("Brain region not found: %s", region_name)
                stats["errors"] += 1
                continue

            region_id = region_nodes[0][0]
            existing = db.find_relationships(
                start_node=node_id,
                end_node=region_id,
                rel_type="ACTIVATES",
            )
            if existing:
                stats["edges_skipped_exists"] += 1
                continue

            properties = {
                "evidence_count": coord_count,
                "coordinate_ids": list(coord_ids)[:10],
                "confidence": min(coord_count / 10.0, 1.0),
                "method": "coordinate_aggregation",
                "threshold": threshold,
            }

            if dry_run:
                stats["edges_created"] += 1
                logger.info(
                    "[DRY RUN] Would create: %s -[ACTIVATES]-> %s (evidence: %s)",
                    node_id,
                    region_name,
                    coord_count,
                )
                continue

            success = db.create_relationship(
                node_id, region_id, "ACTIVATES", properties
            )
            if success:
                stats["edges_created"] += 1
                logger.debug(
                    "Created edge: %s -[ACTIVATES]-> %s (evidence: %s)",
                    node_id,
                    region_name,
                    coord_count,
                )
            else:
                stats["errors"] += 1
                logger.error("Failed to create edge: %s -> %s", node_id, region_id)

    return stats


def validate_database_structure(db: Any) -> bool:
    """Return True when the graph has the minimum labels needed for edge creation."""
    logger.info("Validating database structure...")
    stats = db.get_stats()
    node_labels = _normalize_counts(stats.get("node_labels", {}))
    relationship_types = _normalize_counts(stats.get("relationship_types", {}))

    missing_labels = [
        label for label in REQUIRED_NODE_LABELS if node_labels.get(label, 0) == 0
    ]
    if not any(node_labels.get(label, 0) > 0 for label in PUBLICATION_NODE_LABELS):
        missing_labels.append("Study|Publication")

    if missing_labels:
        logger.error("Missing required node types: %s", missing_labels)
        return False

    missing_relationships = [
        rel
        for rel in REQUIRED_RELATIONSHIP_TYPES
        if relationship_types.get(rel, 0) == 0
    ]
    if missing_relationships:
        logger.warning("Missing expected relationship types: %s", missing_relationships)
        logger.warning("This may be normal if the database is partially loaded")

    logger.info("Database structure validation passed")
    return True


def run_activation_edge_creation(
    db: Any,
    *,
    labels: Iterable[str] = DEFAULT_ACTIVATION_LABELS,
    threshold: int = 5,
    dry_run: bool = False,
    validate: bool = True,
) -> dict[str, int]:
    """Collect evidence and create ACTIVATES edges for the requested labels."""
    if validate and not validate_database_structure(db):
        raise ValueError("Database validation failed")

    total_stats = _empty_stats()
    for label in labels:
        logger.info("\n%s", "=" * 60)
        logger.info("Processing %s nodes...", label)
        logger.info("%s", "=" * 60)

        evidence = collect_coordinate_evidence(db, label)
        if not evidence:
            logger.warning("No coordinate evidence found for %s nodes", label)
            continue

        stats = create_activation_edges(
            db,
            evidence,
            label,
            threshold=threshold,
            dry_run=dry_run,
        )
        for key, value in stats.items():
            total_stats[key] += value

        logger.info("\n%s processing complete:", label)
        logger.info("  - Edges created: %s", stats["edges_created"])
        logger.info(
            "  - Skipped (below threshold): %s",
            stats["edges_skipped_threshold"],
        )
        logger.info(
            "  - Skipped (already exists): %s",
            stats["edges_skipped_exists"],
        )
        logger.info("  - Errors: %s", stats["errors"])

    return total_stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create ACTIVATES edges from coordinate evidence"
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=5,
        help="Minimum coordinate evidence required (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview edges without creating them",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Connecting to Neo4j backend for ACTIVATES edge creation")
    db = require_neo4j_db(args.db_path, preload_cache=False)

    try:
        initial_stats = db.get_stats()
        logger.info(
            "Initial database state: %s nodes, %s relationships",
            initial_stats["total_nodes"],
            initial_stats["total_relationships"],
        )
        total_stats = run_activation_edge_creation(
            db,
            threshold=args.threshold,
            dry_run=args.dry_run,
        )
        final_stats = db.get_stats()
        logger.info("\n%s", "=" * 60)
        logger.info("SUMMARY")
        logger.info("%s", "=" * 60)
        logger.info("Total edges created: %s", total_stats["edges_created"])
        logger.info(
            "Total skipped (threshold): %s",
            total_stats["edges_skipped_threshold"],
        )
        logger.info(
            "Total skipped (exists): %s",
            total_stats["edges_skipped_exists"],
        )
        logger.info("Total errors: %s", total_stats["errors"])
        logger.info(
            "\nDatabase growth: %s -> %s relationships",
            initial_stats["total_relationships"],
            final_stats["total_relationships"],
        )
        if args.dry_run:
            logger.info("\n[DRY RUN] No changes were made to the database")
        return 0
    except Exception as exc:
        logger.error("Error processing database: %s", exc)
        raise
    finally:
        db.close()


__all__ = [
    "DEFAULT_ACTIVATION_LABELS",
    "PUBLICATION_NODE_LABELS",
    "build_parser",
    "collect_coordinate_evidence",
    "create_activation_edges",
    "main",
    "run_activation_edge_creation",
    "validate_database_structure",
]
