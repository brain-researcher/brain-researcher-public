#!/usr/bin/env python3
"""
Analyze Mapping Opportunities in BR-KG

This script analyzes the current database to identify opportunities
for creating MAPS_TO relationships between similar nodes.
"""

import os
import sys
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.neo4j_utils import require_neo4j_db

from brain_researcher.services.br_kg.utils.node_label_linker import NodeLabelLinker


def analyze_concepts(db):
    """Analyze concept nodes for potential mappings."""
    print("\n=== CONCEPT ANALYSIS ===")

    # Get all concept-like nodes
    concept_labels = ["Concept", "CognitiveConstruct"]
    all_concepts = []

    for label in concept_labels:
        nodes = db.find_nodes(labels=label)
        print(f"\n{label}: {len(nodes)} nodes")

        # Sample some nodes
        for node_id, data in nodes[:5]:
            name = data.get("name", data.get("label", "unnamed"))
            source = data.get("source", "unknown")
            print(f"  - {name} (source: {source})")

        if len(nodes) > 5:
            print(f"  ... and {len(nodes) - 5} more")

        all_concepts.extend([(label, node_id, data) for node_id, data in nodes])

    # Check for similar names across different labels
    if len(concept_labels) > 1:
        print("\nPotential cross-label matches:")
        linker = NodeLabelLinker(db)

        # Compare Concept vs CognitiveConstruct
        concepts = [
            (nid, data) for label, nid, data in all_concepts if label == "Concept"
        ]
        constructs = [
            (nid, data)
            for label, nid, data in all_concepts
            if label == "CognitiveConstruct"
        ]

        if concepts and constructs:
            matches = linker.match_nodes(
                concepts[:10], constructs[:10], embed_threshold=0.8, fuzzy_threshold=80
            )

            for n1, n2, score, method in matches[:5]:
                name1 = db.graph.nodes[n1].get("name", n1[:20])
                name2 = db.graph.nodes[n2].get("name", n2[:20])
                print(f"  {name1} ↔ {name2} (score: {score:.3f}, method: {method})")


def analyze_tasks(db):
    """Analyze task nodes for potential mappings."""
    print("\n=== TASK ANALYSIS ===")

    task_labels = ["Task", "TaskDef", "TaskSpec"]
    task_nodes = {}

    for label in task_labels:
        nodes = db.find_nodes(labels=label)
        if nodes:
            task_nodes[label] = nodes
            print(f"\n{label}: {len(nodes)} nodes")

            # Sample some nodes
            for node_id, data in nodes[:3]:
                name = (
                    data.get("name")
                    or data.get("task_name")
                    or data.get("task_label")
                    or "unnamed"
                )
                source = data.get("source", "unknown")
                print(f"  - {name} (source: {source})")


def analyze_datasets(db):
    """Analyze dataset nodes."""
    print("\n=== DATASET ANALYSIS ===")

    dataset_labels = ["Dataset", "OpenNeuro"]

    for label in dataset_labels:
        nodes = db.find_nodes(labels=label)
        if nodes:
            print(f"\n{label}: {len(nodes)} nodes")

            # Check sources
            sources = defaultdict(int)
            for _, data in nodes:
                source = data.get("source", "unknown")
                sources[source] += 1

            for source, count in sources.items():
                print(f"  {source}: {count}")


def analyze_relationships(db):
    """Analyze existing relationships."""
    print("\n=== RELATIONSHIP ANALYSIS ===")

    stats = db.get_stats()

    print("\nExisting relationship types:")
    for rel_type, count in stats["relationship_types"].items():
        print(f"  {rel_type}: {count}")

    # Check for specific relationship patterns
    print("\nRelationship patterns:")

    # Check HAS_CONTRAST
    has_contrast = db.find_relationships(rel_type="HAS_CONTRAST")
    if has_contrast:
        # Get node types involved
        start_types = defaultdict(int)
        end_types = defaultdict(int)

        for start, end, _ in has_contrast[:50]:  # Sample first 50
            start_labels = db.graph.nodes[start].get("labels", [])
            end_labels = db.graph.nodes[end].get("labels", [])

            for label in start_labels:
                start_types[label] += 1
            for label in end_labels:
                end_types[label] += 1

        print("\nHAS_CONTRAST connections:")
        print(f"  From: {dict(start_types)}")
        print(f"  To: {dict(end_types)}")


def suggest_integration_strategy(db):
    """Suggest integration strategy for NodeLabelLinker."""
    print("\n" + "=" * 60)
    print("INTEGRATION STRATEGY")
    print("=" * 60)

    print("\nRecommended MAPS_TO relationships to create:")

    # 1. Concept to CognitiveConstruct
    concepts = db.find_nodes(labels="Concept")
    constructs = db.find_nodes(labels="CognitiveConstruct")

    if concepts and constructs:
        print("\n1. Concept ↔ CognitiveConstruct")
        print(f"   - {len(concepts)} Concepts")
        print(f"   - {len(constructs)} CognitiveConstructs")
        print("   - These likely represent the same entities from different sources")

    # 2. Cross-source concepts
    concept_sources = defaultdict(list)
    for node_id, data in concepts:
        source = data.get("source", "unknown")
        concept_sources[source].append((node_id, data))

    if len(concept_sources) > 1:
        print("\n2. Cross-source Concept linking")
        for source, nodes in concept_sources.items():
            print(f"   - {source}: {len(nodes)} concepts")

    # 3. Dataset variants
    datasets = db.find_nodes(labels="Dataset")
    openneuro = db.find_nodes(labels="OpenNeuro")

    if datasets and openneuro:
        print("\n3. Dataset ↔ OpenNeuro")
        print(f"   - {len(datasets)} Dataset nodes")
        print(f"   - {len(openneuro)} OpenNeuro nodes")
        print("   - May represent the same datasets")

    print("\nSuggested implementation:")
    print("1. Use NodeLabelLinker in data loading scripts")
    print("2. Run periodic batch linking jobs")
    print("3. Add to ETL pipelines for automatic linking")
    print("4. Create admin UI for reviewing/approving mappings")


def main():
    """Main function."""
    print("Analyzing Neo4j backend (NEO4J_* env vars)")
    db = require_neo4j_db(preload_cache=False)

    try:
        analyze_concepts(db)
        analyze_tasks(db)
        analyze_datasets(db)
        analyze_relationships(db)
        suggest_integration_strategy(db)

    finally:
        db.close()


if __name__ == "__main__":
    main()
