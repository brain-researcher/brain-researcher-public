#!/usr/bin/env python3
"""Legacy demonstration of working BR-KG Agent tools."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brain_researcher.services.agent.agents.neuro_agent import NeuroAgent
from brain_researcher.services.tools.fmri_tools import (
    BrainSimilarityTool,
    EncodingModelTool,
)
from brain_researcher.services.tools.br_kg_tools import CoordinateToConceptTool


def demo_encoding_model():
    """Demonstrate encoding model tool."""
    print("\n" + "=" * 60)
    print("ENCODING MODEL DEMO")
    print("=" * 60)

    tool = EncodingModelTool()
    print(f"Tool: {tool.get_tool_name()}")
    print(f"Description: {tool.get_tool_description()}")

    # Run encoding model
    result = tool.run(dataset_id="ds000001", parcellation="schaefer_400")

    if result["status"] == "success":
        print("\n✅ Encoding model built successfully!")
        data = result["data"]
        print(f"Mean R² score: {data['r2_scores']['mean']:.3f}")
        print(f"Standard deviation: {data['r2_scores']['std']:.3f}")
        print("\nRegional R² scores:")
        for region, score in data["r2_scores"]["by_region"].items():
            print(f"  - {region}: {score:.3f}")
        print(f"\nModel saved to: {data['model_path']}")
    else:
        print(f"❌ Error: {result['error']}")


def demo_brain_similarity():
    """Demonstrate brain similarity tool."""
    print("\n" + "=" * 60)
    print("BRAIN SIMILARITY DEMO")
    print("=" * 60)

    tool = BrainSimilarityTool()
    print(f"Tool: {tool.get_tool_name()}")
    print(f"Description: {tool.get_tool_description()}")

    # Compare two datasets
    result = tool.run(dataset1="ds000001", dataset2="ds000002", metric="correlation")

    if result["status"] == "success":
        print("\n✅ Similarity computed successfully!")
        data = result["data"]
        print(f"Overall similarity score: {data['similarity_score']:.3f}")
        print(f"Metric used: {data['metric']}")
        print("\nRegional similarities:")
        for region, score in data["regional_similarities"].items():
            print(f"  - {region}: {score:.3f}")
        print(f"\nInterpretation: {data['interpretation']}")
    else:
        print(f"❌ Error: {result['error']}")


def demo_coordinate_to_concept():
    """Demonstrate coordinate to concept mapping."""
    print("\n" + "=" * 60)
    print("COORDINATE TO CONCEPT MAPPING DEMO")
    print("=" * 60)

    tool = CoordinateToConceptTool()
    print(f"Tool: {tool.get_tool_name()}")
    print(f"Description: {tool.get_tool_description()}")

    # Test with multiple coordinates
    test_coordinates = [
        [-42, -22, 54],  # Motor cortex
        [-50, 20, 0],  # Broca's area
        [0, -98, 0],  # Visual cortex
    ]

    result = tool.run(coordinates=test_coordinates, radius=10.0, top_k=3)

    if result["status"] == "success":
        print("\n✅ Coordinate mapping successful!")
        data = result["data"]
        print(f"Note: {data.get('note', '')}")
        print(f"\nMapped {data['n_coordinates']} coordinates:")

        for mapping in data["coordinate_mappings"]:
            coord = mapping["coordinate"]
            print(f"\nCoordinate {coord}:")
            print(f"  Region: {mapping['region']}")
            print("  Concepts:")
            for concept in mapping["concepts"]:
                print(f"    - {concept['concept']} (score: {concept['score']:.2f})")
    else:
        print(f"❌ Error: {result['error']}")


def demo_agent_usage():
    """Demonstrate using the agent with working tools."""
    print("\n" + "=" * 60)
    print("AGENT USAGE DEMO")
    print("=" * 60)

    agent = NeuroAgent()

    # Example queries that will use working tools
    queries = [
        "Build an encoding model for dataset ds000001",
        "Compare brain activation between datasets ds000001 and ds000002",
        "What cognitive concepts are associated with coordinate [-42, -22, 54]?",
    ]

    for query in queries:
        print(f"\nQuery: {query}")
        print("-" * 40)

        try:
            result = agent.run(query)
            print(f"Phase: {result['current_phase']}")
            if result.get("selected_tools"):
                print(f"Tools used: {result['selected_tools']}")
            if result.get("synthesis"):
                print(
                    f"Summary: {result['synthesis'].get('summary', 'No summary available')}"
                )
        except Exception as e:
            print(f"Error: {e}")


def main():
    """Run all demos."""
    print("BR-KG Agent - Working Tools Demonstration")
    print("=" * 80)
    print("\nThis demo shows the tools that are currently working properly.")
    print("These tools can be used even when external services are unavailable.\n")

    # Run individual tool demos
    demo_encoding_model()
    demo_brain_similarity()
    demo_coordinate_to_concept()

    # Run agent demo
    demo_agent_usage()

    import pdb

    pdb.set_trace()
    print("\n" + "=" * 80)
    print("Demo complete!")
    print("\nWorking tools summary:")
    print("✅ encoding_model - Build predictive models of brain activity")
    print("✅ brain_similarity - Compare activation patterns between datasets")
    print("✅ coordinate_to_concept - Map brain coordinates to cognitive concepts")
    print("\nThese tools use mock data when external services are unavailable.")


if __name__ == "__main__":
    main()
