#!/usr/bin/env python3
"""Command line interface for OpenNeuro loaders."""

import argparse
import logging
import os
import sys

# Ensure project root is on path
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Try different import approaches for script vs module execution
try:
    from brain_researcher.services.br_kg.etl.loaders.openneuro_loader.metadata_loader import (
        OpenNeuroMetadataLoader,
    )
    from brain_researcher.services.br_kg.graph.graph_database import BRKGGraphDB
except ImportError:
    # When running as a script from brain_researcher.services.br_kg directory
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from brain_researcher.services.br_kg.etl.loaders.openneuro_loader.metadata_loader import OpenNeuroMetadataLoader
    from graph.graph_database import BRKGGraphDB

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="OpenNeuro loader")
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum datasets to fetch"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Skip writes to database"
    )
    parser.add_argument(
        "--mode", choices=["metadata", "fitlins", "all"], default="metadata"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    db_path = ":memory:" if args.dry_run else "data/br-kg/db/br_kg_openneuro.db"
    db = BRKGGraphDB(db_path)

    if args.mode in ("metadata", "all"):
        loader = OpenNeuroMetadataLoader(db, dry_run=args.dry_run)
        loader.load_datasets(limit=args.limit)
        if not args.dry_run:
            loader.save_unmatched()
    # FitLins loader integration could be added here in future

    db.close()


if __name__ == "__main__":
    main()
