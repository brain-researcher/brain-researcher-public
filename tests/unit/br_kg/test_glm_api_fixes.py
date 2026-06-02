#!/usr/bin/env python3
"""Test the GLM FitLins API fixes directly"""

import os
import sys
from pathlib import Path

# Add paths for proper imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from brain_researcher.services.br_kg.graph.graph_database import BRKGGraphDB

# Test database path - use relative path from project root
DB_PATH = "data/br-kg/db/br_kg_glmfitlins.db"


def test_database_connection():
    """Test basic database connection and initialization"""
    print("Testing database connection...")

    # Check if database file exists
    if not os.path.exists(DB_PATH):
        print(f"❌ Database file not found: {DB_PATH}")
        return False

    try:
        db = BRKGGraphDB(DB_PATH)
        print("✅ Database connected successfully")
        print(f"   - Database path: {DB_PATH}")
        print(f"   - File size: {os.path.getsize(DB_PATH) / 1024 / 1024:.2f} MB")
        db.close()
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


def test_database_content():
    """Test database content and structure"""
    print("\nTesting database content...")

    try:
        db = BRKGGraphDB(DB_PATH)

        # Get all nodes and relationships
        all_nodes = db.find_nodes()
        all_relationships = db.find_relationships()

        print("✅ Database content loaded")
        print(f"   - Total nodes: {len(all_nodes)}")
        print(f"   - Total relationships: {len(all_relationships)}")

        # Test node types
        node_types = {}
        for node_id, node_data in all_nodes:
            labels = node_data.get("labels", [])
            if isinstance(labels, str):
                try:
                    import json

                    labels = json.loads(labels)
                except:
                    labels = [labels]

            for label in labels:
                node_types[label] = node_types.get(label, 0) + 1

        print("   - Node types found:")
        for node_type, count in sorted(node_types.items()):
            print(f"     • {node_type}: {count}")

        # Test relationship types
        rel_types = {}
        for start, end, rel_data in all_relationships:
            rel_type = rel_data.get("type", "UNKNOWN")
            rel_types[rel_type] = rel_types.get(rel_type, 0) + 1

        print("   - Relationship types found:")
        for rel_type, count in sorted(rel_types.items()):
            print(f"     • {rel_type}: {count}")

        db.close()
        return True
    except Exception as e:
        print(f"❌ Database content test failed: {e}")
        return False


def test_specific_queries():
    """Test specific query patterns"""
    print("\nTesting specific queries...")

    try:
        db = BRKGGraphDB(DB_PATH)

        # Test 1: Find datasets
        print("1. Testing dataset queries:")
        datasets = db.find_nodes(labels="Dataset")
        print(f"   ✅ Found {len(datasets)} datasets")

        if datasets:
            node_id, node_data = datasets[0]
            print(f"   - First dataset ID: {node_data.get('dataset_id', 'N/A')}")
            print(f"   - First dataset name: {node_data.get('name', 'N/A')}")

        # Test 2: Find contrasts
        print("\n2. Testing contrast queries:")
        contrasts = db.find_nodes(labels="Contrast")
        print(f"   ✅ Found {len(contrasts)} contrasts")

        if contrasts:
            contrast_id, contrast_data = contrasts[0]
            print(f"   - First contrast ID: {contrast_id}")
            print(f"   - First contrast name: {contrast_data.get('name', 'N/A')}")

        # Test 3: Find constructs
        print("\n3. Testing construct queries:")
        constructs = db.find_nodes(labels="CognitiveConstruct")
        print(f"   ✅ Found {len(constructs)} constructs")

        if constructs:
            construct_id, construct_data = constructs[0]
            print(f"   - First construct ID: {construct_id}")
            print(f"   - First construct name: {construct_data.get('name', 'N/A')}")

        # Test 4: Find relationships
        print("\n4. Testing relationship queries:")
        relationships = db.find_relationships()
        print(f"   ✅ Found {len(relationships)} total relationships")

        if relationships:
            start, end, rel_data = relationships[0]
            print(f"   - First relationship: {start} -> {end}")
            print(f"   - Relationship type: {rel_data.get('type', 'N/A')}")

        # Test 5: Test specific relationship types
        print("\n5. Testing specific relationship types:")
        rel_types_to_test = [
            "HAS_CONTRAST",
            "INVOLVES_CONSTRUCT",
            "HAS_TASK",
            "HAS_CONDITION",
        ]

        for rel_type in rel_types_to_test:
            rels = db.find_relationships(rel_type=rel_type)
            print(f"   - {rel_type}: {len(rels)} relationships")

        db.close()
        return True
    except Exception as e:
        print(f"❌ Specific queries test failed: {e}")
        return False


def test_data_quality():
    """Test data quality and consistency"""
    print("\nTesting data quality...")

    try:
        db = BRKGGraphDB(DB_PATH)

        # Check for orphaned relationships
        all_nodes = set(node_id for node_id, _ in db.find_nodes())
        all_relationships = db.find_relationships()

        orphaned_rels = 0
        for start, end, _ in all_relationships:
            if start not in all_nodes or end not in all_nodes:
                orphaned_rels += 1

        print(f"   - Orphaned relationships: {orphaned_rels}")

        # Check for nodes with properties
        nodes_with_props = 0
        for node_id, node_data in db.find_nodes():
            if node_data.get("properties"):
                nodes_with_props += 1

        print(f"   - Nodes with properties: {nodes_with_props}")

        # Check for relationships with properties
        rels_with_props = 0
        for start, end, rel_data in all_relationships:
            if rel_data.get("properties"):
                rels_with_props += 1

        print(f"   - Relationships with properties: {rels_with_props}")

        db.close()
        return True
    except Exception as e:
        print(f"❌ Data quality test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("🧪 GLM FitLins Database Test Suite")
    print("=" * 50)

    tests = [
        ("Database Connection", test_database_connection),
        ("Database Content", test_database_content),
        ("Specific Queries", test_specific_queries),
        ("Data Quality", test_data_quality),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n📋 Running: {test_name}")
        print("-" * 30)

        if test_func():
            passed += 1
            print(f"✅ {test_name}: PASSED")
        else:
            print(f"❌ {test_name}: FAILED")

    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Database is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the issues above.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
