#!/usr/bin/env python3
"""
Batch Node Matching Script for BR-KG

Runs matching across all existing nodes and creates SAME_AS edges.
Progress is saved to allow resuming if interrupted.
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

from brain_researcher.services.br_kg.matching import UnifiedNodeMatcher
from brain_researcher.services.br_kg.graph.graph_database import BRKGGraphDB

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MatchingStats:
    """Track matching statistics."""

    def __init__(self):
        self.stats = defaultdict(lambda: {
            'total_nodes': 0,
            'nodes_checked': 0,
            'nodes_with_matches': 0,
            'same_as_edges_created': 0,
            'match_methods': defaultdict(int),
            'confidence_distribution': defaultdict(int)
        })
        self.start_time = datetime.now()

    def update(self, node_type: str, had_match: bool, edge_count: int,
               matches: List = None):
        """Update stats for a node."""
        s = self.stats[node_type]
        s['nodes_checked'] += 1

        if had_match:
            s['nodes_with_matches'] += 1
            s['same_as_edges_created'] += edge_count

        if matches:
            for m in matches:
                s['match_methods'][m.method] += 1
                # Bucket confidence scores
                bucket = f"{int(m.confidence * 10) / 10:.1f}"
                s['confidence_distribution'][bucket] += 1

    def print_summary(self):
        """Print statistics summary."""
        print("\n" + "=" * 70)
        print("MATCHING RESULTS SUMMARY")
        print("=" * 70)

        total_checked = sum(s['nodes_checked'] for s in self.stats.values())
        total_matched = sum(s['nodes_with_matches'] for s in self.stats.values())
        total_edges = sum(s['same_as_edges_created'] for s in self.stats.values())

        print(f"\n📊 Overall Stats:")
        print(f"  Total nodes checked: {total_checked:,}")
        print(f"  Nodes with matches: {total_matched:,} ({total_matched/max(total_checked,1)*100:.1f}%)")
        print(f"  SAME_AS edges created: {total_edges:,}")
        print(f"  Duration: {datetime.now() - self.start_time}")

        print(f"\n📋 By Node Type:")
        for node_type, s in sorted(self.stats.items()):
            if s['nodes_checked'] == 0:
                continue

            print(f"\n  {node_type}:")
            print(f"    Checked: {s['nodes_checked']:,}")
            print(f"    Matched: {s['nodes_with_matches']:,} ({s['nodes_with_matches']/max(s['nodes_checked'],1)*100:.1f}%)")
            print(f"    Edges: {s['same_as_edges_created']:,}")

            if s['match_methods']:
                methods = ', '.join(f"{k}:{v}" for k, v in s['match_methods'].items())
                print(f"    Methods: {methods}")

    def save_report(self, output_path: str):
        """Save detailed report to JSON."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'duration_seconds': (datetime.now() - self.start_time).total_seconds(),
            'stats': dict(self.stats)
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Report saved to {output_path}")


def run_matching_for_node_type(
    db: BRKGGraphDB,
    matcher: UnifiedNodeMatcher,
    node_type: str,
    stats: MatchingStats,
    batch_size: int = 100,
    max_nodes: int = None
) -> None:
    """Run matching for a specific node type.

    Args:
        db: Graph database instance
        matcher: Node matcher instance
        node_type: Type of nodes to match (Task, Concept, etc.)
        stats: Statistics tracker
        batch_size: Number of nodes to process per batch
        max_nodes: Maximum nodes to process (None = all)
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing {node_type} nodes")
    logger.info(f"{'='*60}")

    # Get all nodes of this type
    nodes = db.find_nodes(labels=node_type)
    total = len(nodes)

    if max_nodes:
        nodes = nodes[:max_nodes]
        logger.info(f"Limiting to {max_nodes} nodes (out of {total:,} total)")
    else:
        logger.info(f"Found {total:,} {node_type} nodes")

    # Update total count
    stats.stats[node_type]['total_nodes'] = total

    # Process in batches
    for i in range(0, len(nodes), batch_size):
        batch = nodes[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(nodes) + batch_size - 1) // batch_size

        logger.info(f"Batch {batch_num}/{total_batches} ({len(batch)} nodes)")

        for node_id, node_data in batch:
            try:
                # Prepare candidate
                candidate = {"id": node_id, **node_data}

                # Get other nodes to match against (exclude self)
                other_nodes = [
                    {"id": nid, **data}
                    for nid, data in nodes
                    if nid != node_id
                ]

                # Find matches
                matches = matcher.match_node(candidate, node_type, other_nodes)

                # Create SAME_AS edges
                edge_ids = []
                if matches:
                    edge_ids = matcher.create_same_as_edges(node_id, matches, db)

                # Update stats
                stats.update(node_type, len(matches) > 0, len(edge_ids), matches)

                if matches:
                    logger.debug(f"  {node_id}: {len(matches)} matches, {len(edge_ids)} edges")

            except Exception as e:
                logger.error(f"Error processing {node_id}: {e}")
                continue

        # Progress update
        progress = min(i + batch_size, len(nodes))
        logger.info(f"Progress: {progress:,}/{len(nodes):,} ({progress/len(nodes)*100:.1f}%)")


def main():
    """Main matching execution."""
    print("\n" + "=" * 70)
    print("BR-KG Batch Node Matching")
    print("=" * 70)

    # Initialize
    logger.info("Initializing...")
    db = BRKGGraphDB("data/br-kg/db/br_kg_full.db")
    matcher = UnifiedNodeMatcher()
    stats = MatchingStats()

    logger.info(f"Database: {db.graph.number_of_nodes():,} nodes, {db.graph.number_of_edges():,} edges")

    # Configuration
    NODE_TYPES_TO_MATCH = [
        "Task",
        "Concept",
        "Publication",
        "Coordinate",
        "Region",
        "Dataset",
        "Phenotype",
        "Contrast"
    ]

    # Batch processing settings
    BATCH_SIZE = 100
    MAX_NODES_PER_TYPE = None  # Full run on all nodes

    logger.info(f"\nConfiguration:")
    logger.info(f"  Node types: {', '.join(NODE_TYPES_TO_MATCH)}")
    logger.info(f"  Batch size: {BATCH_SIZE}")
    logger.info(f"  Max nodes per type: {MAX_NODES_PER_TYPE or 'unlimited'}")

    # Process each node type
    for node_type in NODE_TYPES_TO_MATCH:
        try:
            run_matching_for_node_type(
                db, matcher, node_type, stats,
                batch_size=BATCH_SIZE,
                max_nodes=MAX_NODES_PER_TYPE
            )
        except KeyboardInterrupt:
            logger.warning("Interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error processing {node_type}: {e}")
            continue

    # Generate reports
    stats.print_summary()

    report_path = f"logs/matching_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    stats.save_report(report_path)

    print("\n✅ Matching complete!")
    print("=" * 70)

    # Close database
    db.close()


if __name__ == "__main__":
    main()
