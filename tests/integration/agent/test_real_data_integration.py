#!/usr/bin/env python3
"""
Test real data integration for Brain Researcher tools.
"""

import json
import os
import sys

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)

from brain_researcher.services.tools.br_kg_tools import (
    CoordinateToConceptTool,
    GraphQueryTool,
    TaskMappingTool,
)
from brain_researcher.services.tools.fmri_tools import ContrastAnalysisTool


def test_task_mapping_with_real_data():
    """Test task mapping with real vocabulary data."""
    print("\n=== Testing Task Mapping with Real Data ===")
    tool = TaskMappingTool()

    # Test with a known task
    result = tool._run(task_name="n-back")
    print(f"Task: n-back")
    print(f"Status: {result.status}")
    if result.status == "success":
        print(f"Concepts: {result.data.get('concepts', [])[:5]}")  # First 5 concepts
        print(f"Source: {result.data.get('source', 'unknown')}")
        print(f"Metadata: {result.metadata}")
    else:
        print(f"Error: {result.error}")

    return result.status == "success"


def test_contrast_analysis_with_real_glm():
    """Test contrast analysis with real GLM data."""
    print("\n=== Testing Contrast Analysis with Real GLM Data ===")
    tool = ContrastAnalysisTool()

    # Test with balloon task data
    result = tool._run(
        z_map_path="/data/glm/ds000001/pumps_zmap.nii.gz", contrast_name="pumps"
    )

    print(f"Contrast: pumps")
    print(f"Status: {result.status}")
    if result.status == "success":
        print(f"Real data used: {not result.metadata.get('mock_mode', True)}")
        print(f"Z-map used: {result.data.get('z_map_used', 'None')}")
        print(f"Number of clusters: {result.data.get('n_clusters', 0)}")
    else:
        print(f"Error: {result.error}")

    return result.status == "success" and not result.metadata.get("mock_mode", True)


def test_graph_query_neighbors():
    """Test graph query neighbors with fixed parsing."""
    print("\n=== Testing Graph Query Neighbors ===")
    tool = GraphQueryTool()

    # Test neighbors query
    result = tool._run(query_type="neighbors", start_node="working memory")

    print(f"Node: working memory")
    print(f"Status: {result.status}")
    if result.status == "success":
        print(f"Number of neighbors: {result.data.get('n_neighbors', 0)}")
        if result.data.get("neighbors"):
            print(f"First neighbor: {result.data['neighbors'][0]}")
    else:
        print(f"Error: {result.error}")

    return result.status == "success"


def test_coordinate_to_concept_niclip():
    """Test coordinate to concept with NiCLIP if available."""
    print("\n=== Testing Coordinate to Concept ===")
    tool = CoordinateToConceptTool()

    # Test with motor cortex coordinate
    result = tool._run(coordinates=[[-42, -22, 54]], radius=10.0, top_k=5)

    print(f"Coordinate: [-42, -22, 54]")
    print(f"Status: {result.status}")
    if result.status == "success":
        print(f"Method: {result.data.get('method', 'unknown')}")
        print(f"NiCLIP enabled: {result.metadata.get('niclip_enabled', False)}")
        if result.data.get("coordinate_mappings"):
            mapping = result.data["coordinate_mappings"][0]
            print(
                f"Top concept: {mapping['concepts'][0]['concept'] if mapping.get('concepts') else 'None'}"
            )
    else:
        print(f"Error: {result.error}")

    return result.status == "success"


def main():
    """Run all tests and report results."""
    print("Testing Real Data Integration for Brain Researcher Tools")
    print("=" * 60)

    results = {
        "task_mapping": test_task_mapping_with_real_data(),
        "contrast_analysis": test_contrast_analysis_with_real_glm(),
        "graph_query": test_graph_query_neighbors(),
        "coordinate_to_concept": test_coordinate_to_concept_niclip(),
    }

    print("\n=== Summary ===")
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")

    # Check if real data was actually used
    print("\n=== Real Data Usage ===")
    print("- Vocabulary file (ca_topics_level0_v2.json): Check task_mapping source")
    print("- GLM data files: Check contrast_analysis real_data_used flag")
    print("- NiCLIP spatial mapper: Check coordinate_to_concept niclip_enabled flag")

    total_passed = sum(results.values())
    print(f"\nTotal: {total_passed}/{len(results)} tests passed")

    return total_passed == len(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
