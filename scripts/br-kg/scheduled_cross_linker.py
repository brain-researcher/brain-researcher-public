#!/usr/bin/env python3
"""
Scheduled Cross-Source Linker

This script is designed to be run periodically (e.g., via cron) to:
1. Find nodes without MAPS_TO relationships
2. Create new cross-source links
3. Generate reports on linking activity

Usage:
    python scripts/br-kg/scheduled_cross_linker.py [--database DB_PATH] [--dry-run] [--report-dir DIR]

Example cron entry (daily at 2 AM):
    0 2 * * * /usr/bin/python3 /path/to/scheduled_cross_linker.py
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.mappers.cross_source_linker import CrossSourceLinker
from graph.neo4j_utils import require_neo4j_db
from graph.neo4j_graph_database import Neo4jGraphDB

from brain_researcher.services.br_kg.utils.node_label_linker import NodeLabelLinker


def setup_logging(log_dir: str = "logs/scheduled"):
    """Setup logging configuration."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    log_file = os.path.join(
        log_dir, f"cross_linker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    return logging.getLogger(__name__)


class ScheduledLinker:
    """Scheduled cross-source linking job."""

    def __init__(self, db_path: str | None, dry_run: bool = False):
        """Initialize the scheduled linker."""
        self.db_path = db_path
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)
        self.stats = {
            "start_time": datetime.utcnow().isoformat(),
            "unmapped_nodes": {},
            "new_links": 0,
            "errors": [],
        }

    def run(self) -> dict:
        """Run the scheduled linking job."""
        self.logger.info("Starting scheduled cross-source linking job")

        if self.dry_run:
            self.logger.info("Running in DRY RUN mode - no changes will be made")

        try:
            # Open database
            db = require_neo4j_db(self.db_path, preload_cache=False)
            self.logger.info("Connected to Neo4j backend for scheduled linking")

            # Get initial stats
            initial_stats = db.get_stats()
            self.logger.info(
                f"Initial MAPS_TO relationships: {initial_stats['relationship_types'].get('MAPS_TO', 0)}"
            )

            # Initialize linker
            linker = CrossSourceLinker(db, auto_link=True, dry_run=self.dry_run)

            # 1. Find unmapped nodes
            self.logger.info("\n=== Finding unmapped nodes ===")
            unmapped_by_label = self._find_all_unmapped_nodes(db, linker)

            # 2. Attempt to link unmapped nodes
            self.logger.info("\n=== Attempting to link unmapped nodes ===")
            total_created = self._link_unmapped_nodes(db, linker, unmapped_by_label)

            # 3. Run standard linking strategies for all sources
            self.logger.info("\n=== Running standard linking strategies ===")
            sources = [
                "cognitive_atlas",
                "neurosynth",
                "openneuro",
                "wikidata",
                "neurovault",
            ]

            for source in sources:
                self.logger.info(f"\nChecking for new links from {source}...")
                links = linker.link_after_source_load(source)
                total_created += links
                self.logger.info(f"Created {links} MAPS_TO relationships for {source}")

            # 4. Look for duplicate patterns
            self.logger.info("\n=== Checking for duplicate patterns ===")
            duplicates_linked = self._link_duplicates(db)
            total_created += duplicates_linked

            # Get final stats
            final_stats = db.get_stats()
            self.stats["new_links"] = total_created
            self.stats["final_maps_to"] = final_stats["relationship_types"].get(
                "MAPS_TO", 0
            )
            self.stats["end_time"] = datetime.utcnow().isoformat()

            # Generate report
            self.logger.info("\n" + "=" * 60)
            self.logger.info("SCHEDULED LINKING JOB COMPLETE")
            self.logger.info(f"Total new MAPS_TO relationships: {total_created}")
            self.logger.info(
                f"Total MAPS_TO relationships in database: {self.stats['final_maps_to']}"
            )

            # Show linking report
            self.logger.info("\n" + linker.get_linking_report())

            db.close()

        except Exception as e:
            self.logger.error(f"Error during scheduled linking: {e}")
            self.stats["errors"].append(str(e))
            raise

        return self.stats

    def _find_all_unmapped_nodes(
        self, db: Neo4jGraphDB, linker: CrossSourceLinker
    ) -> dict[str, list]:
        """Find all nodes without MAPS_TO relationships."""
        unmapped_by_label = {}
        start_all = datetime.utcnow()
        self.logger.info("Scanning for unmapped nodes (start=%s UTC)", start_all.isoformat())

        # Check common node types
        labels_to_check = [
            "Concept",
            "CognitiveConstruct",
            "Task",
            "TaskSpec",
            "TaskDef",
            "BrainRegion",
            "Dataset",
            "OpenNeuro",
            "Contrast",
            "GLMContrast",
            "Collection",
        ]

        for label in labels_to_check:
            label_start = datetime.utcnow()
            self.logger.info("  -> scanning label '%s' (start=%s UTC)", label, label_start.isoformat())
            unmapped = linker.find_unmapped_nodes(label)
            label_end = datetime.utcnow()
            elapsed = (label_end - label_start).total_seconds()
            if unmapped:
                unmapped_by_label[label] = unmapped
                self.logger.info(
                    "    found %d unmapped %s nodes (elapsed %.2fs)",
                    len(unmapped),
                    label,
                    elapsed,
                )
                self.stats["unmapped_nodes"][label] = len(unmapped)
            else:
                self.logger.info("    no unmapped %s nodes (elapsed %.2fs)", label, elapsed)

        total_elapsed = (datetime.utcnow() - start_all).total_seconds()
        self.logger.info("Completed unmapped node scan in %.2fs", total_elapsed)

        return unmapped_by_label

    def _link_unmapped_nodes(
        self,
        db: Neo4jGraphDB,
        linker: CrossSourceLinker,
        unmapped_by_label: dict[str, list],
    ) -> int:
        """Attempt to link unmapped nodes."""
        total_created = 0

        # Define linking attempts for unmapped nodes
        linking_attempts = [
            # Try to link Concepts from different sources
            ("Concept", "Concept", 0.85),
            ("Concept", "CognitiveConstruct", 0.90),
            # Try to link Tasks
            ("Task", "TaskDef", 0.80),
            ("TaskSpec", "TaskDef", 0.80),
            ("TaskSpec", "Task", 0.85),
            # Try to link Brain Regions
            ("BrainRegion", "BrainRegion", 0.75),
            # Try to link Contrasts
            ("Contrast", "GLMContrast", 0.90),
            ("Contrast", "Contrast", 0.85),
            # Try to link Datasets
            ("Dataset", "OpenNeuro", 0.90),
            ("Dataset", "Dataset", 0.85),
        ]

        for source_label, target_label, threshold in linking_attempts:
            if source_label not in unmapped_by_label:
                continue

            self.logger.info(f"\nLinking unmapped {source_label} → {target_label}")

            # Get unmapped source nodes
            source_nodes = unmapped_by_label[source_label]

            # Get all target nodes
            target_nodes = db.find_nodes(labels=target_label)

            if not target_nodes:
                continue

            # Use NodeLabelLinker directly for more control
            label_linker = NodeLabelLinker(db)

            if self.dry_run:
                matches = label_linker.match_nodes(
                    source_nodes,
                    target_nodes,
                    embed_threshold=threshold,
                    fuzzy_threshold=int(threshold * 100),
                )
                self.logger.info(f"[DRY RUN] Would create {len(matches)} links")
                total_created += len(matches)
            else:
                created = label_linker.create_maps_to_edges(
                    source_nodes,
                    target_nodes,
                    embed_threshold=threshold,
                    fuzzy_threshold=int(threshold * 100),
                    additional_props={
                        "created_by": "scheduled_linker",
                        "link_type": "unmapped_recovery",
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
                total_created += created
                self.logger.info(f"Created {created} links")

        return total_created

    def _link_duplicates(self, db: Neo4jGraphDB) -> int:
        """Link known duplicate patterns."""
        if self.dry_run:
            self.logger.info("[DRY RUN] Would check for duplicate patterns")
            return 0

        # Import and run the duplicate linker
        try:
            from scripts.br_kg.link_duplicate_nodes import DuplicateNodeLinker

            dup_linker = DuplicateNodeLinker(db, dry_run=self.dry_run)
            stats = dup_linker.find_and_link_duplicates()

            return stats["total_mappings"]
        except Exception as e:
            self.logger.warning(f"Could not run duplicate linking: {e}")
            return 0

    def save_report(self, report_dir: str):
        """Save job report to file."""
        Path(report_dir).mkdir(parents=True, exist_ok=True)

        report_file = os.path.join(
            report_dir,
            f"linking_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )

        with open(report_file, "w") as f:
            json.dump(self.stats, f, indent=2)

        self.logger.info(f"Report saved to: {report_file}")
        return report_file


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Scheduled cross-source linking job for BR-KG"
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
        "--report-dir",
        default="reports/scheduled_linking",
        help="Directory for saving reports",
    )
    parser.add_argument(
        "--log-dir", default="logs/scheduled", help="Directory for log files"
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.log_dir)

    try:
        # Run scheduled linking
        linker = ScheduledLinker(args.database, dry_run=args.dry_run)
        stats = linker.run()

        # Save report
        if args.report_dir:
            linker.save_report(args.report_dir)

        # Exit with success
        sys.exit(0)

    except Exception as e:
        logger.error(f"Scheduled linking job failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
