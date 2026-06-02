#!/usr/bin/env python3
"""
Check MAPS_TO Relationships in BR-KG Database

This script checks the current state of MAPS_TO relationships in the database
and demonstrates how to use NodeLabelLinker to create new ones.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.neo4j_utils import require_neo4j_db

from brain_researcher.services.br_kg.utils.node_label_linker import NodeLabelLinker


def check_database_state(db_path):
    """Check the current state of the database."""
    print("Checking Neo4j backend (NEO4J_* env vars)")
    db = require_neo4j_db(db_path, preload_cache=False)

    # Get statistics
    stats = db.get_stats()
    print("\nDatabase Statistics:")
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Total relationships: {stats['total_relationships']}")

    # Show node types
    print("\nNode types:")
    node_labels = stats.get("node_labels", {})
    if isinstance(node_labels, dict):
        for label, count in node_labels.items():
            print(f"  {label}: {count}")
    else:
        for label in node_labels:
            rows = db.execute_query(
                f"MATCH (n:`{label}`) RETURN count(n) AS cnt"
            )
            count = rows[0].get("cnt", 0) if rows else 0
            print(f"  {label}: {count}")

    # Show relationship types
    print("\nRelationship types:")
    rel_types = stats.get("relationship_types", {})
    if isinstance(rel_types, dict):
        for rel_type, count in rel_types.items():
            print(f"  {rel_type}: {count}")
    else:
        for rel_type in rel_types:
            rows = db.execute_query(
                f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
            )
            count = rows[0].get("cnt", 0) if rows else 0
            print(f"  {rel_type}: {count}")

    # Check for MAPS_TO relationships
    if isinstance(rel_types, dict):
        maps_to_count = rel_types.get("MAPS_TO", 0)
    else:
        rows = db.execute_query("MATCH ()-[r:MAPS_TO]->() RETURN count(r) AS cnt")
        maps_to_count = rows[0].get("cnt", 0) if rows else 0
    print(f"\nMAPS_TO relationships: {maps_to_count}")

    if maps_to_count > 0:
        # Show some examples
        maps_to_rels = db.find_relationships(rel_type="MAPS_TO")
        print("\nExample MAPS_TO relationships (first 5):")
        for i, (start, end, props) in enumerate(maps_to_rels[:5]):
            start_data = db.get_node(start) or {}
            end_data = db.get_node(end) or {}

            start_name = (
                start_data.get("name")
                or start_data.get("label")
                or start_data.get("task_name")
                or start[:20]
            )
            end_name = (
                end_data.get("name")
                or end_data.get("label")
                or end_data.get("task_name")
                or end[:20]
            )

            print(f"  {i+1}. {start_name} → {end_name}")
            print(
                f"     Method: {props.get('method', 'unknown')}, "
                f"Confidence: {props.get('confidence', 0):.3f}"
            )

    return db


def suggest_mappings(db):
    """Suggest potential mappings that could be created."""
    print("\n" + "=" * 60)
    print("POTENTIAL MAPPINGS ANALYSIS")
    print("=" * 60)

    # Check for concepts from different sources
    concepts = db.find_nodes(labels="Concept")
    concept_sources = {}
    for node_id, data in concepts:
        source = data.get("source", "unknown")
        if source not in concept_sources:
            concept_sources[source] = 0
        concept_sources[source] += 1

    if len(concept_sources) > 1:
        print("\nConcepts from different sources that could be linked:")
        for source, count in concept_sources.items():
            print(f"  {source}: {count} concepts")

    # Check for tasks
    task_types = ["Task", "TaskDef", "TaskSpec"]
    task_counts = {}
    for task_type in task_types:
        count = db.get_node_count(task_type)
        if count > 0:
            task_counts[task_type] = count

    if len(task_counts) > 1:
        print("\nTask types that could be linked:")
        for task_type, count in task_counts.items():
            print(f"  {task_type}: {count} nodes")

    # Check for brain regions
    regions = db.find_nodes(labels="BrainRegion")
    region_sources = {}
    for node_id, data in regions:
        source = data.get("source", "unknown")
        if source not in region_sources:
            region_sources[source] = 0
        region_sources[source] += 1

    if len(region_sources) > 1:
        print("\nBrain regions from different sources that could be linked:")
        for source, count in region_sources.items():
            print(f"  {source}: {count} regions")


def create_sample_mappings(db):
    """Create sample MAPS_TO relationships if suitable nodes exist."""
    print("\n" + "=" * 60)
    print("CREATING SAMPLE MAPPINGS")
    print("=" * 60)

    linker = NodeLabelLinker(db)

    # Try to link concepts from different sources
    ca_concepts = db.find_nodes(
        labels="Concept", properties={"source": "cognitive_atlas"}
    )
    ns_concepts = db.find_nodes(labels="Concept", properties={"source": "neurosynth"})

    if ca_concepts and ns_concepts:
        print(
            f"\nLinking {len(ca_concepts)} Cognitive Atlas concepts with {len(ns_concepts)} NeuroSynth concepts..."
        )
        created = linker.create_maps_to_edges(
            ca_concepts[:10],  # Limit to first 10 for demo
            ns_concepts[:10],
            embed_threshold=0.8,
            fuzzy_threshold=80,
            additional_props={"demo": True},
        )
        print(f"Created {created} concept mappings")

    # Try to link different task types
    task_specs = db.find_nodes(labels="TaskSpec")
    task_defs = db.find_nodes(labels="TaskDef")

    if task_specs and task_defs:
        print(
            f"\nLinking {len(task_specs)} TaskSpec nodes with {len(task_defs)} TaskDef nodes..."
        )
        created = linker.create_maps_to_edges(
            task_specs[:10],
            task_defs[:10],
            embed_threshold=0.75,
            fuzzy_threshold=75,
            additional_props={"demo": True},
        )
        print(f"Created {created} task mappings")


def main():
    """Main function."""
    import sys

    # Check main database
    db = check_database_state(None)
    if db:
        suggest_mappings(db)

        # Check if --create flag is passed
        create_mappings = "--create" in sys.argv

        if create_mappings:
            print("\nCreating sample mappings...")
            create_sample_mappings(db)

            # Show updated statistics
            stats = db.get_stats()
            maps_to_count = stats["relationship_types"].get("MAPS_TO", 0)
            print(f"\nUpdated MAPS_TO count: {maps_to_count}")
        else:
            print("\nTo create sample MAPS_TO relationships, run with --create flag")

        db.close()

    # Also check for other databases
    print("\n" + "=" * 60)
    print("OTHER DATABASES")
    print("=" * 60)

    other_dbs = [
        "data/br-kg/db/br_kg_integrated.db",
        "data/br-kg/db/br_kg_full.db",
    ]

    for other_db in other_dbs:
        if os.path.exists(other_db):
            print(f"\nFound: {other_db}")
            db = require_neo4j_db(other_db)
            stats = db.get_stats()
            maps_to = stats["relationship_types"].get("MAPS_TO", 0)
            print(
                f"  Total nodes: {stats['total_nodes']}, MAPS_TO relationships: {maps_to}"
            )
            db.close()


if __name__ == "__main__":
    main()
