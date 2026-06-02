#!/usr/bin/env python3
"""
Link Duplicate Nodes Script

This script identifies and links duplicate nodes in the BR-KG database
using the NodeLabelLinker. It's designed to clean up existing duplicates
and can be run as a one-time job or periodically.

Usage:
    python scripts/br-kg/link_duplicate_nodes.py [--database DB_PATH] [--dry-run] [--report]
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.core.ingestion.graph_factory import GraphDatabaseProtocol
from graph.neo4j_utils import require_neo4j_db

from brain_researcher.services.br_kg.utils.node_label_linker import NodeLabelLinker


# Configure logging
def setup_logging(log_dir: str = "logs"):
    """Setup logging configuration."""
    Path(log_dir).mkdir(exist_ok=True)

    log_file = os.path.join(
        log_dir, f"link_duplicate_nodes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    return logging.getLogger(__name__)


class DuplicateNodeLinker:
    """Handles linking of duplicate nodes in BR-KG database."""

    # Define linking rules: (source_label, target_label, threshold, description)
    LINKING_RULES = [
        # Exact duplicates with same source
        (
            "Concept",
            "CognitiveConstruct",
            0.95,
            "Duplicate concepts from Cognitive Atlas",
        ),
        ("Dataset", "OpenNeuro", 0.90, "Duplicate dataset entries"),
        ("Contrast", "GLMContrast", 0.90, "Duplicate contrast entries"),
        # Cross-source mappings with lower thresholds
        ("Concept", "Concept", 0.85, "Cross-source concept mapping"),
        ("Task", "TaskDef", 0.80, "Task to TaskDef mapping"),
        ("TaskSpec", "TaskDef", 0.80, "TaskSpec to TaskDef mapping"),
        ("BrainRegion", "BrainRegion", 0.75, "Cross-source brain region mapping"),
    ]

    def __init__(self, db: GraphDatabaseProtocol, dry_run: bool = False):
        """Initialize the duplicate linker."""
        self.db = db
        self.dry_run = dry_run
        self.linker = NodeLabelLinker(db)
        self.logger = logging.getLogger(__name__)
        self.stats = {
            "total_mappings": 0,
            "mappings_by_type": {},
            "errors": 0,
            "skipped": 0,
        }
        self.db_identifier = (
            getattr(db, "db_path", None)
            or os.getenv("NEO4J_URI")
            or type(db).__name__
        )

    def find_and_link_duplicates(self) -> dict:
        """Find and link all duplicate nodes based on predefined rules."""
        self.logger.info("Starting duplicate node linking process...")

        if self.dry_run:
            self.logger.info("DRY RUN MODE - No changes will be made")

        # Process each linking rule
        for source_label, target_label, threshold, description in self.LINKING_RULES:
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Processing: {description}")
            self.logger.info(
                f"Rule: {source_label} → {target_label} (threshold: {threshold})"
            )

            created = self._process_linking_rule(
                source_label, target_label, threshold, description
            )

            # Update statistics
            rule_key = f"{source_label}→{target_label}"
            self.stats["mappings_by_type"][rule_key] = created
            self.stats["total_mappings"] += created

        return self.stats

    def _process_linking_rule(
        self, source_label: str, target_label: str, threshold: float, description: str
    ) -> int:
        """Process a single linking rule."""
        # Handle same-label cross-source linking
        if source_label == target_label:
            return self._link_cross_source_nodes(source_label, threshold, description)
        else:
            return self._link_different_labels(
                source_label, target_label, threshold, description
            )

    def _link_different_labels(
        self, source_label: str, target_label: str, threshold: float, description: str
    ) -> int:
        """Link nodes with different labels."""
        source_nodes = self.db.find_nodes(labels=source_label)
        target_nodes = self.db.find_nodes(labels=target_label)

        if not source_nodes or not target_nodes:
            self.logger.info(
                f"No nodes found: {len(source_nodes)} {source_label}, "
                f"{len(target_nodes)} {target_label}"
            )
            return 0

        self.logger.info(
            f"Found {len(source_nodes)} {source_label} nodes and "
            f"{len(target_nodes)} {target_label} nodes"
        )

        # Find matches
        matches = self.linker.match_nodes(
            source_nodes,
            target_nodes,
            embed_threshold=threshold,
            fuzzy_threshold=int(threshold * 100),
        )

        self.logger.info(f"Found {len(matches)} potential matches")

        if self.dry_run:
            # Just show what would be created
            for n1, n2, score, method in matches[:10]:
                name1 = self._get_node_name(n1)
                name2 = self._get_node_name(n2)
                self.logger.info(
                    f"  Would link: {name1} → {name2} "
                    f"(score: {score:.3f}, method: {method})"
                )
            if len(matches) > 10:
                self.logger.info(f"  ... and {len(matches) - 10} more")
            return len(matches)
        else:
            # Actually create the mappings
            created = 0
            for n1, n2, score, method in matches:
                try:
                    success = self.db.create_relationship(
                        n1,
                        n2,
                        "MAPS_TO",
                        {
                            "confidence": score,
                            "method": method,
                            "rule": description,
                            "created_by": "link_duplicate_nodes",
                            "created_at": datetime.utcnow().isoformat(),
                        },
                    )
                    if success:
                        created += 1
                except Exception as e:
                    self.logger.error(f"Error creating relationship: {e}")
                    self.stats["errors"] += 1

            self.logger.info(f"Created {created} MAPS_TO relationships")
            return created

    def _link_cross_source_nodes(
        self, label: str, threshold: float, description: str
    ) -> int:
        """Link nodes of the same label from different sources."""
        all_nodes = self.db.find_nodes(labels=label)

        if not all_nodes:
            self.logger.info(f"No {label} nodes found")
            return 0

        # Group by source
        nodes_by_source = {}
        for node_id, data in all_nodes:
            source = data.get("source", "unknown")
            if source not in nodes_by_source:
                nodes_by_source[source] = []
            nodes_by_source[source].append((node_id, data))

        if len(nodes_by_source) < 2:
            self.logger.info(f"Only one source found for {label} nodes")
            return 0

        self.logger.info(
            f"Found {label} nodes from sources: {list(nodes_by_source.keys())}"
        )

        total_created = 0

        # Link between each pair of sources
        sources = list(nodes_by_source.keys())
        for i, source_a in enumerate(sources):
            for source_b in sources[i + 1 :]:
                self.logger.info(f"\nLinking {label} nodes: {source_a} ↔ {source_b}")

                created = self._link_different_labels(
                    label, label, threshold, f"{description} ({source_a} ↔ {source_b})"
                )

                # Need to actually call the linker for same-label linking
                if not self.dry_run:
                    nodes_a = nodes_by_source[source_a]
                    nodes_b = nodes_by_source[source_b]

                    created = self.linker.create_maps_to_edges(
                        nodes_a,
                        nodes_b,
                        embed_threshold=threshold,
                        fuzzy_threshold=int(threshold * 100),
                        additional_props={
                            "rule": description,
                            "source_a": source_a,
                            "source_b": source_b,
                            "created_by": "link_duplicate_nodes",
                        },
                    )

                total_created += created

        return total_created

    def _get_node_name(self, node_id: str) -> str:
        """Get a readable name for a node."""
        try:
            matches = self.db.find_nodes(properties={"id": node_id})
        except Exception:
            matches = []

        if matches:
            _, data = matches[0]
            return (
                data.get("name")
                or data.get("label")
                or data.get("task_name")
                or data.get("title")
                or node_id[:30]
            )

        return node_id[:30]

    def generate_report(self) -> str:
        """Generate a detailed report of the linking process."""
        report = []
        report.append("=" * 60)
        report.append("DUPLICATE NODE LINKING REPORT")
        report.append("=" * 60)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Database: {self.db_identifier}")
        report.append(f"Mode: {'DRY RUN' if self.dry_run else 'PRODUCTION'}")
        report.append("")

        # Summary statistics
        report.append("SUMMARY")
        report.append("-" * 30)
        report.append(
            f"Total MAPS_TO relationships created: {self.stats['total_mappings']}"
        )
        report.append(f"Errors encountered: {self.stats['errors']}")
        report.append("")

        # Detailed breakdown
        report.append("BREAKDOWN BY TYPE")
        report.append("-" * 30)
        for rule_key, count in self.stats["mappings_by_type"].items():
            report.append(f"{rule_key}: {count} mappings")

        # Database state
        report.append("")
        report.append("DATABASE STATE")
        report.append("-" * 30)
        db_stats = self.db.get_stats()
        report.append(f"Total nodes: {db_stats['total_nodes']}")
        report.append(f"Total relationships: {db_stats['total_relationships']}")
        report.append(
            f"MAPS_TO relationships: {db_stats['relationship_types'].get('MAPS_TO', 0)}"
        )

        return "\n".join(report)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Link duplicate nodes in BR-KG database"
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without creating relationships",
    )
    parser.add_argument(
        "--report", action="store_true", help="Generate detailed report"
    )
    parser.add_argument(
        "--output", help="Output file for report (default: print to console)"
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging()

    legacy_db_path = args.database
    db = require_neo4j_db(legacy_db_path, preload_cache=False)
    logger.info("Connected to graph backend: %s", type(db).__name__)

    try:
        # Create linker and process duplicates
        linker = DuplicateNodeLinker(db, dry_run=args.dry_run)
        stats = linker.find_and_link_duplicates()

        # Generate report if requested
        if args.report:
            report = linker.generate_report()

            if args.output:
                with open(args.output, "w") as f:
                    f.write(report)
                logger.info(f"Report saved to: {args.output}")
            else:
                print("\n" + report)

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info(
            f"COMPLETED: Created {stats['total_mappings']} MAPS_TO relationships"
        )

    except Exception as e:
        logger.error(f"Error during processing: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
