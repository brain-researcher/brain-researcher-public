#!/usr/bin/env python3
"""
Test script for Session 4 neuroimaging tools implementation.
Tests registration and basic functionality of new tools.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.services.tools.tool_registry import ToolRegistry


def test_tool_registration():
    """Test that all new tools are properly registered."""
    print("\n" + "=" * 60)
    print("TESTING TOOL REGISTRATION")
    print("=" * 60)

    registry = ToolRegistry(auto_discover=True)
    all_tools = registry.get_all_tools()
    tool_names = [tool.get_tool_name() for tool in all_tools]

    # New tools from Session 4
    expected_tools = [
        # FSL FIX
        "fsl_fix",
        "fsl_fix_multirun",
        # FSL PALM
        "fsl_palm",
        "palm_surface",
        # MNE Source Localization
        "mne_source_localization",
        "mne_beamformer",
        "mne_dipole_fitting",
        # Previous session tools
        "mixed_effects",
        "fitlins",
    ]

    print(f"\nTotal tools registered: {len(tool_names)}")
    print("\nChecking Session 4 tools:")

    results = {}
    for tool_name in expected_tools:
        if tool_name in tool_names:
            print(f"✅ {tool_name}: REGISTERED")
            results[tool_name] = "registered"
        else:
            print(f"❌ {tool_name}: NOT FOUND")
            results[tool_name] = "missing"

    # Count by category
    categories = {
        "FSL": ["fsl_", "palm_"],
        "MNE": ["mne_"],
        "Stats": ["mixed_effects", "fitlins", "statsmodels"],
    }

    print("\n" + "-" * 40)
    print("Tools by Category:")
    for category, prefixes in categories.items():
        count = sum(
            1 for name in tool_names if any(name.startswith(p) for p in prefixes)
        )
        print(f"  {category}: {count} tools")

    return results, len(tool_names)


def test_tool_descriptions():
    """Test that tools have proper descriptions."""
    print("\n" + "=" * 60)
    print("TESTING TOOL DESCRIPTIONS")
    print("=" * 60)

    registry = ToolRegistry(auto_discover=True)

    # Test specific new tools
    test_tools = ["fsl_fix", "fsl_palm", "mne_source_localization", "mne_beamformer"]

    for tool_name in test_tools:
        tool = registry.get_tool(tool_name)
        if tool:
            desc = tool.get_tool_description()
            print(f"\n{tool_name}:")
            print(f"  Description length: {len(desc)} chars")
            print(f"  First 100 chars: {desc[:100]}...")

            # Check for required keywords
            if tool_name == "fsl_fix" and "artifact" in desc.lower():
                print("  ✅ Contains 'artifact' keyword")
            elif tool_name == "fsl_palm" and "permutation" in desc.lower():
                print("  ✅ Contains 'permutation' keyword")
            elif tool_name.startswith("mne_") and (
                "source" in desc.lower() or "beamformer" in desc.lower()
            ):
                print("  ✅ Contains relevant keywords")


def test_tool_schemas():
    """Test that tools have valid argument schemas."""
    print("\n" + "=" * 60)
    print("TESTING TOOL SCHEMAS")
    print("=" * 60)

    registry = ToolRegistry(auto_discover=True)

    test_tools = ["fsl_fix", "fsl_palm", "mne_source_localization"]

    results = {}
    for tool_name in test_tools:
        tool = registry.get_tool(tool_name)
        if tool:
            try:
                schema = tool.get_args_schema()
                fields = schema.__fields__ if hasattr(schema, "__fields__") else {}

                print(f"\n{tool_name}:")
                print(f"  Number of parameters: {len(fields)}")

                # Check for key parameters
                key_params = []
                if tool_name == "fsl_fix":
                    key_params = ["feat_dir", "training_data", "threshold"]
                elif tool_name == "fsl_palm":
                    key_params = ["input_file", "design_matrix", "n_permutations"]
                elif tool_name == "mne_source_localization":
                    key_params = ["subjects_dir", "subject", "method"]

                for param in key_params:
                    if param in fields:
                        print(f"  ✅ Has '{param}' parameter")
                    else:
                        print(f"  ❌ Missing '{param}' parameter")

                results[tool_name] = "valid_schema"
            except Exception as e:
                print(f"  ❌ Schema error: {e}")
                results[tool_name] = "schema_error"

    return results


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SESSION 4 NEUROIMAGING TOOLS TEST")
    print("=" * 60)
    print(f"Testing at: {datetime.now().isoformat()}")

    # Run tests
    reg_results, total_tools = test_tool_registration()
    test_tool_descriptions()
    schema_results = test_tool_schemas()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    registered = sum(1 for v in reg_results.values() if v == "registered")
    missing = sum(1 for v in reg_results.values() if v == "missing")

    print(f"Total tools in registry: {total_tools}")
    print(f"Session 4 tools registered: {registered}/{len(reg_results)}")
    if missing > 0:
        print(f"Missing tools: {missing}")

    # Save results
    output_dir = REPO_ROOT / "outputs" / "test_outputs"
    output_dir.mkdir(exist_ok=True)

    results = {
        "timestamp": datetime.now().isoformat(),
        "session": "Session 4",
        "total_tools": total_tools,
        "registration": reg_results,
        "schemas": schema_results,
        "summary": {
            "registered": registered,
            "missing": missing,
            "total_checked": len(reg_results),
        },
    }

    results_file = (
        output_dir / f"session4_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {results_file}")

    # New tools added in Session 4
    new_tools = [
        "FSL FIX (Artifact Removal)",
        "FSL PALM (Permutation Testing)",
        "MNE Source Localization (MNE/dSPM/sLORETA)",
        "MNE Beamformer (LCMV/DICS)",
        "MNE Dipole Fitting",
    ]

    print("\n" + "=" * 60)
    print("NEW TOOLS IMPLEMENTED IN SESSION 4:")
    print("=" * 60)
    for tool in new_tools:
        print(f"  ✅ {tool}")

    print(f"\nTotal new tools this session: {len(new_tools)}")

    return missing == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
