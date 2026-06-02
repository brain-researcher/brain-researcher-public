#!/usr/bin/env python
"""
Demo script to test the complete Finder API flow.
Run this to verify the Finder system is working end-to-end.
"""

import json
import sys
from typing import Any, Dict

import requests

BASE_URL = "http://localhost:5000"


def test_natural_language_parsing():
    """Test natural language to filter conversion."""
    print("\n=== Testing Natural Language Parsing ===")

    queries = [
        "fMRI motor task",
        "structural MRI studies",
        "working memory fMRI after 2020",
        "resting state healthy controls",
    ]

    for query in queries:
        response = requests.post(f"{BASE_URL}/kg/suggestFilters", json={"text": query})

        if response.status_code == 200:
            filters = response.json()["filters"]
            print(f"\nQuery: '{query}'")
            print(f"Filters: {json.dumps(filters, indent=2)}")
        else:
            print(f"Error for query '{query}': {response.status_code}")
            return False

    return True


def test_facet_counting():
    """Test dynamic facet counting."""
    print("\n=== Testing Facet Counting ===")

    # Test without filters
    response = requests.post(f"{BASE_URL}/kg/facets", json={"filters": []})

    if response.status_code == 200:
        facets = response.json()["facets"]
        print("\nAvailable facets:")
        for facet, values in facets.items():
            print(f"\n{facet}:")
            for value, count in list(values.items())[:5]:  # Show first 5
                print(f"  - {value}: {count}")
    else:
        print(f"Error getting facets: {response.status_code}")
        return False

    # Test with filter
    filters = [{"facet": "modality", "op": "=", "value": "fmri"}]
    response = requests.post(f"{BASE_URL}/kg/facets", json={"filters": filters})

    if response.status_code == 200:
        print("\nFacets filtered by modality=fmri:")
        facets = response.json()["facets"]
        if "task" in facets:
            print("Tasks available for fMRI datasets:")
            for task, count in list(facets["task"].items())[:5]:
                print(f"  - {task}: {count}")

    return True


def test_dataset_search():
    """Test dataset search functionality."""
    print("\n=== Testing Dataset Search ===")

    # Search without filters
    response = requests.post(
        f"{BASE_URL}/kg/searchDatasets",
        json={"filters": [], "sort": "readiness", "limit": 5, "offset": 0},
    )

    if response.status_code == 200:
        datasets = response.json()["datasets"]
        print(f"\nFound {len(datasets)} datasets (showing first 5)")

        for ds in datasets:
            readiness = ds["readiness"]
            print(f"\n- {ds['name']} (ID: {ds['id']})")
            print(
                f"  Readiness: {readiness['color']} (score: {readiness['score']:.2f})"
            )
            print(f"  Reason: {readiness['reason']}")
    else:
        print(f"Error searching datasets: {response.status_code}")
        return False

    # Search with filters
    filters = [
        {"facet": "modality", "op": "=", "value": "fmri"},
        {"facet": "task", "op": "=", "value": "motor"},
    ]

    response = requests.post(
        f"{BASE_URL}/kg/searchDatasets",
        json={"filters": filters, "sort": "relevance", "limit": 3, "offset": 0},
    )

    if response.status_code == 200:
        datasets = response.json()["datasets"]
        print(f"\n\nFiltered search (fMRI + motor): Found {len(datasets)} datasets")

        for ds in datasets:
            print(f"\n- {ds['name']}")
            if ds.get("why_matched"):
                print(f"  Matched on: {', '.join(ds['why_matched'].keys())}")

    return True


def test_dataset_explanation():
    """Test dataset explanation endpoint."""
    print("\n=== Testing Dataset Explanation ===")

    # First get a dataset ID
    response = requests.post(
        f"{BASE_URL}/kg/searchDatasets", json={"filters": [], "limit": 1, "offset": 0}
    )

    if response.status_code != 200:
        print("Could not get dataset for explanation test")
        return False

    datasets = response.json()["datasets"]
    if len(datasets) == 0:
        print("No datasets available for explanation test")
        return True  # Not a failure, just no data

    dataset_id = datasets[0]["id"]
    dataset_name = datasets[0]["name"]

    # Get explanation
    response = requests.get(f"{BASE_URL}/kg/explain/{dataset_id}")

    if response.status_code == 200:
        explanation = response.json()

        print(f"\nExplanation for: {dataset_name}")
        print(f"ID: {dataset_id}")

        if "description" in explanation:
            print(f"\nDescription: {explanation['description'][:200]}...")

        evidence = explanation.get("evidence", {})
        print(f"\nEvidence:")
        print(f"  - Papers: {len(evidence.get('papers', []))}")
        print(f"  - Methods: {len(evidence.get('methods', []))}")
        print(f"  - Derivatives: {len(evidence.get('derivatives', []))}")

        graph = explanation.get("graph", {})
        print(f"\nKnowledge Graph:")
        print(f"  - Nodes: {len(graph.get('nodes', []))}")
        print(f"  - Edges: {len(graph.get('edges', []))}")

        # Show node types
        if graph.get("nodes"):
            node_types = {}
            for node in graph["nodes"]:
                node_type = node.get("type", "unknown")
                node_types[node_type] = node_types.get(node_type, 0) + 1

            print(f"\nNode types:")
            for ntype, count in node_types.items():
                print(f"    - {ntype}: {count}")
    elif response.status_code == 404:
        print(f"Dataset {dataset_id} not found")
    else:
        print(f"Error getting explanation: {response.status_code}")
        return False

    return True


def test_complete_workflow():
    """Test the complete Finder workflow."""
    print("\n=== Testing Complete Workflow ===")
    print("Simulating user journey: Query -> Filters -> Search -> Explain")

    # Step 1: User enters natural language query
    user_query = "fMRI motor task studies"
    print(f"\n1. User query: '{user_query}'")

    response = requests.post(f"{BASE_URL}/kg/suggestFilters", json={"text": user_query})

    if response.status_code != 200:
        print("Failed at step 1")
        return False

    filters = response.json()["filters"]
    print(f"   Generated {len(filters)} filters")

    # Step 2: Get facet counts with filters
    print("\n2. Getting facet counts...")
    response = requests.post(f"{BASE_URL}/kg/facets", json={"filters": filters})

    if response.status_code != 200:
        print("Failed at step 2")
        return False

    facets = response.json()["facets"]
    print(f"   Got {len(facets)} facet categories")

    # Step 3: Search datasets
    print("\n3. Searching datasets...")
    response = requests.post(
        f"{BASE_URL}/kg/searchDatasets",
        json={"filters": filters, "sort": "readiness", "limit": 5, "offset": 0},
    )

    if response.status_code != 200:
        print("Failed at step 3")
        return False

    datasets = response.json()["datasets"]
    print(f"   Found {len(datasets)} matching datasets")

    if len(datasets) > 0:
        # Step 4: Get explanation for top result
        top_dataset = datasets[0]
        print(f"\n4. Getting details for top result: {top_dataset['name']}")

        response = requests.get(f"{BASE_URL}/kg/explain/{top_dataset['id']}")

        if response.status_code == 200:
            explanation = response.json()
            print(f"   Successfully retrieved explanation")
            print(f"   Readiness: {explanation['readiness']['color']}")
            print(
                f"   Evidence items: {sum(len(v) for v in explanation['evidence'].values())}"
            )
            print(f"   Graph nodes: {len(explanation['graph']['nodes'])}")
        else:
            print(f"   Failed to get explanation: {response.status_code}")

    print("\n✅ Complete workflow test successful!")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("FINDER API TEST SUITE")
    print("=" * 60)

    # Check if service is running
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code != 200:
            print(f"❌ BR-KG service not healthy at {BASE_URL}")
            print(
                "Please start the service with: python -m brain_researcher.services.br_kg.app"
            )
            return 1
    except requests.ConnectionError:
        print(f"❌ Cannot connect to BR-KG service at {BASE_URL}")
        print(
            "Please start the service with: python -m brain_researcher.services.br_kg.app"
        )
        return 1

    print(f"✅ BR-KG service is running at {BASE_URL}")

    # Run tests
    tests = [
        ("Natural Language Parsing", test_natural_language_parsing),
        ("Facet Counting", test_facet_counting),
        ("Dataset Search", test_dataset_search),
        ("Dataset Explanation", test_dataset_explanation),
        ("Complete Workflow", test_complete_workflow),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"\n❌ Error in {test_name}: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")

    passed = sum(1 for _, s in results if s)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
