#!/usr/bin/env python3
"""
Direct test of the reorganized Nilearn tools.
"""

import sys

from brain_researcher.services.tools.tool_registry import ToolRegistry


def test_tools_registration():
    """Test if new Nilearn tools are properly registered."""

    print("=" * 70)
    print("TESTING NILEARN TOOLS REGISTRATION")
    print("=" * 70)

    # Initialize registry
    registry = ToolRegistry()

    # Expected tools from our reorganization
    expected_tools = [
        # From nilearn_glm.py
        "glm_first_level",
        "glm_second_level",
        # From nilearn_connectivity.py
        "connectivity_matrix",
        "seed_based_fc",
        # From nilearn_viz.py
        "viz_stat_maps",
        "surface_projection",
        # From nilearn_preprocessing.py
        "nifti_masker",
        "roi_extraction",
        "clean_confounds",
        # From nilearn_mvpa.py
        "decoding_classifier",
    ]

    print(f"\nTotal tools registered: {len(registry.tools)}")
    print("\nChecking for Nilearn tools:")
    print("-" * 50)

    found_tools = []
    missing_tools = []

    for tool_name in expected_tools:
        if tool_name in registry.tools:
            tool = registry.tools[tool_name]
            print(f"✓ {tool_name:25} - {tool.description[:50]}...")
            found_tools.append(tool_name)

            # Check if tool has proper schema
            if hasattr(tool, "args_model"):
                schema = tool.args_model.schema()
                params = list(schema.get("properties", {}).keys())[:3]
                print(f"  └─ Schema params: {', '.join(params)}...")
        else:
            print(f"✗ {tool_name:25} - NOT FOUND")
            missing_tools.append(tool_name)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Found: {len(found_tools)}/{len(expected_tools)} tools")

    if missing_tools:
        print(f"\nMissing tools: {', '.join(missing_tools)}")
    else:
        print("\n✓ All expected Nilearn tools are registered!")

    # Test one tool execution
    print("\n" + "=" * 70)
    print("TESTING TOOL EXECUTION")
    print("=" * 70)

    if "connectivity_matrix" in registry.tools:
        print("\nTesting connectivity_matrix tool...")
        tool = registry.tools["connectivity_matrix"]

        # Create test data
        import numpy as np

        test_data = np.random.randn(100, 10)  # 100 timepoints, 10 regions
        np.save("/tmp/test_timeseries.npy", test_data)

        try:
            result = tool.invoke(
                timeseries="/tmp/test_timeseries.npy",
                kind="correlation",
                fisher_z=True,
                output_file="/tmp/test_connectivity.npy",
            )

            if result.get("status") == "success":
                print(f"✓ Tool execution successful!")
                print(f"  Shape: {result.get('shape')}")
                print(f"  Kind: {result.get('kind')}")
            else:
                print(f"✗ Tool execution failed: {result}")

        except Exception as e:
            print(f"✗ Error executing tool: {str(e)}")


if __name__ == "__main__":
    test_tools_registration()
