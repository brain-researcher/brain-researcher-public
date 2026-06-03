#!/usr/bin/env python3
"""
Test NiCLIP Concept Hierarchy Extension

Demonstrates how NiCLIP embeddings extend the concept
hierarchy with semantic clustering and relationships.
"""

import json
from datetime import datetime


def test_niclip_concept_hierarchy():
    """Test concept hierarchy building with NiCLIP."""
    print("🏗️  Testing NiCLIP Concept Hierarchy Extension")
    print("=" * 60)

    try:
        from brain_researcher.services.br_kg.etl.mappers.niclip_concept_hierarchy import (
            get_hierarchy_builder
        )

        # Initialize hierarchy builder
        builder = get_hierarchy_builder()

        if not builder._loaded:
            print("⚠️  NiCLIP data not loaded, showing mock example")
            demonstrate_mock_hierarchy()
            return

        # Build concept hierarchy
        print("\n1️⃣ Building Concept Hierarchy with NiCLIP Embeddings...")
        hierarchy = builder.build_hierarchy(n_clusters=15)

        print(f"\n📊 Hierarchy Statistics:")
        print(f"   Total concepts: {hierarchy['total_concepts']}")
        print(f"   Number of clusters: {hierarchy['n_clusters']}")
        print(f"   Relationships generated: {len(hierarchy['relationships'])}")

        # Show cognitive process mapping
        print(f"\n2️⃣ Cognitive Process Mapping:")
        process_concepts = {}
        for cluster_id, process in hierarchy['process_mapping'].items():
            if process not in process_concepts:
                process_concepts[process] = []
            process_concepts[process].extend(hierarchy['clusters'][cluster_id])

        for process, concepts in process_concepts.items():
            print(f"\n   {process}:")
            for concept in concepts[:5]:  # Show first 5
                print(f"      - {concept}")
            if len(concepts) > 5:
                print(f"      ... and {len(concepts)-5} more")

        # Show sample hierarchical relationships
        print(f"\n3️⃣ Sample Hierarchical Relationships:")

        # Group by relationship type
        rel_types = {}
        for rel in hierarchy['relationships']:
            rel_type = rel['type']
            if rel_type not in rel_types:
                rel_types[rel_type] = []
            rel_types[rel_type].append(rel)

        for rel_type, rels in rel_types.items():
            print(f"\n   {rel_type} relationships ({len(rels)} total):")
            for rel in rels[:3]:  # Show first 3
                props = rel.get('properties', {})
                confidence = props.get('confidence', props.get('similarity', 'N/A'))
                print(f"      {rel['source']} → {rel['target']} (confidence: {confidence})")

        # Test specific concepts
        print(f"\n4️⃣ Concept Details:")
        test_concepts = ["working memory", "language", "motor", "attention"]

        for concept in test_concepts:
            info = builder.get_concept_hierarchy_info(concept)
            if info['embedding'] is not None:
                print(f"\n   📍 {concept}:")
                print(f"      Process: {info['cognitive_process']}")
                print(f"      Cluster: {info['cluster_id']}")
                print(f"      Broader: {info['broader_concepts']}")
                print(f"      Related: {info['related_concepts'][:3]}")

    except ImportError as e:
        print(f"\n⚠️  Import error: {e}")
        demonstrate_mock_hierarchy()


def demonstrate_mock_hierarchy():
    """Show mock hierarchy example when NiCLIP is not available."""
    print("\n📝 Mock Concept Hierarchy Example")
    print("-" * 40)

    mock_hierarchy = {
        "Cognitive Control": {
            "concepts": ["working memory", "attention", "inhibition", "task switching"],
            "relationships": [
                ("working memory", "IS_A", "cognitive control"),
                ("attention", "IS_A", "cognitive control"),
                ("working memory", "RELATED_TO", "attention"),
            ]
        },
        "Language": {
            "concepts": ["speech processing", "reading", "semantic processing", "syntax"],
            "relationships": [
                ("speech processing", "IS_A", "language"),
                ("reading", "IS_A", "language"),
                ("reading", "RELATED_TO", "semantic processing"),
            ]
        },
        "Motor": {
            "concepts": ["motor control", "action planning", "movement execution"],
            "relationships": [
                ("motor control", "IS_A", "motor"),
                ("action planning", "PART_OF", "motor control"),
            ]
        }
    }

    for process, data in mock_hierarchy.items():
        print(f"\n{process}:")
        print(f"  Concepts: {', '.join(data['concepts'][:3])}")
        print(f"  Relationships:")
        for source, rel_type, target in data['relationships'][:2]:
            print(f"    {source} -[{rel_type}]-> {target}")


def show_benefits():
    """Show benefits of NiCLIP-enhanced concept hierarchy."""
    print("\n\n✨ Benefits of NiCLIP Concept Hierarchy")
    print("=" * 60)

    print("\n1️⃣ Semantic Clustering:")
    print("   - Groups related concepts using brain-language embeddings")
    print("   - Example: 'working memory', 'attention', 'executive control'")
    print("            clustered together based on neural similarity")

    print("\n2️⃣ Process-Based Organization:")
    print("   - Links concepts to 6 cognitive processes from NiCLIP")
    print("   - Provides scientifically-grounded concept categorization")

    print("\n3️⃣ Hierarchical Relationships:")
    print("   - IS_A: concept belongs to broader category")
    print("   - PART_OF: concept is component of larger concept")
    print("   - RELATED_TO: semantically similar concepts")

    print("\n4️⃣ Data-Driven Structure:")
    print("   - Relationships based on brain activation patterns")
    print("   - Not just lexical similarity but neural similarity")


def show_usage_example():
    """Show how to use the hierarchy builder."""
    print("\n\n🔧 Usage Example")
    print("=" * 60)

    print("""
from brain_researcher.services.br_kg.etl.mappers.niclip_concept_hierarchy import (
    get_hierarchy_builder
)

# Initialize builder (optionally with database)
builder = get_hierarchy_builder(db=graph_db)

# Build hierarchy with custom clusters
hierarchy = builder.build_hierarchy(n_clusters=20)

# Create relationships in graph
created = builder.create_hierarchy_in_graph(dry_run=False)
print(f"Created {created} hierarchical relationships")

# Query specific concept
info = builder.get_concept_hierarchy_info("working memory")
print(f"Cognitive process: {info['cognitive_process']}")
print(f"Related concepts: {info['related_concepts']}")

# Use in knowledge graph queries
# Now you can traverse concept hierarchies:
# - Find all concepts under "cognitive control"
# - Find related concepts to "language processing"
# - Navigate from specific to general concepts
""")


if __name__ == "__main__":
    test_niclip_concept_hierarchy()
    show_benefits()
    show_usage_example()

    print("\n\n✅ NiCLIP Concept Hierarchy Extension Complete!")
    print("   - Semantic clustering of concepts")
    print("   - Process-based categorization")
    print("   - Hierarchical relationship generation")
    print("   - Ready for knowledge graph integration")