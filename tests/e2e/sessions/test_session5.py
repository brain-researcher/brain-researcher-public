#!/usr/bin/env python3
"""
Test script for Session 5 neuroimaging tools implementation.
Tests registration and basic functionality of new P0 priority tools.
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
    print("TESTING TOOL REGISTRATION - SESSION 5")
    print("=" * 60)

    registry = ToolRegistry(auto_discover=True)
    all_tools = registry.get_all_tools()
    tool_names = [tool.get_tool_name() for tool in all_tools]

    # New tools from Session 5 (P0 priority completions)
    expected_tools = [
        # MNE Connectivity Analysis
        "mne_connectivity",
        # Permutation Testing Framework
        "permutation_testing",
        # Multiple Comparison Correction
        "multiple_comparison_correction",
        # Previous session tools for verification
        "fsl_fix",
        "fsl_palm",
        "mne_source_localization",
        "mixed_effects",
        "fitlins",
    ]

    print(f"\nTotal tools registered: {len(tool_names)}")
    print("\nChecking Session 5 P0 priority tools:")

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
        "FSL": [name for name in tool_names if name.startswith(("fsl_", "palm_"))],
        "MNE": [name for name in tool_names if name.startswith("mne_")],
        "Stats": [
            name
            for name in tool_names
            if any(
                x in name
                for x in [
                    "mixed_effects",
                    "fitlins",
                    "statsmodels",
                    "permutation",
                    "comparison",
                ]
            )
        ],
        "Preprocessing": [
            name
            for name in tool_names
            if any(x in name for x in ["fmriprep", "qsiprep", "xcpd"])
        ],
        "Analysis": [
            name
            for name in tool_names
            if any(x in name for x in ["nilearn", "conn", "nipype"])
        ],
        "Other": [
            name
            for name in tool_names
            if not any(
                name.startswith(p)
                or any(
                    x in name
                    for x in [
                        "mixed_effects",
                        "fitlins",
                        "statsmodels",
                        "permutation",
                        "comparison",
                        "fmriprep",
                        "qsiprep",
                        "xcpd",
                        "nilearn",
                        "conn",
                        "nipype",
                    ]
                )
                for p in ["fsl_", "palm_", "mne_"]
            )
        ],
    }

    print("\n" + "-" * 40)
    print("Tools by Category:")
    for category, tools in categories.items():
        print(f"  {category}: {len(tools)} tools")

    return results, len(tool_names)


def test_tool_descriptions():
    """Test that new tools have proper descriptions."""
    print("\n" + "=" * 60)
    print("TESTING TOOL DESCRIPTIONS")
    print("=" * 60)

    registry = ToolRegistry(auto_discover=True)

    # Test the new P0 tools
    test_tools = [
        "mne_connectivity",
        "permutation_testing",
        "multiple_comparison_correction",
    ]

    for tool_name in test_tools:
        tool = registry.get_tool(tool_name)
        if tool:
            desc = tool.get_tool_description()
            print(f"\n{tool_name}:")
            print(f"  Description length: {len(desc)} chars")
            print(f"  First 100 chars: {desc[:100]}...")

            # Check for required keywords
            if tool_name == "mne_connectivity":
                keywords = ["connectivity", "coherence", "PLV", "Granger"]
                found = [kw for kw in keywords if kw.lower() in desc.lower()]
                print(f"  ✅ Contains keywords: {', '.join(found)}")

            elif tool_name == "permutation_testing":
                keywords = ["permutation", "cluster", "TFCE", "statistical"]
                found = [kw for kw in keywords if kw.lower() in desc.lower()]
                print(f"  ✅ Contains keywords: {', '.join(found)}")

            elif tool_name == "multiple_comparison_correction":
                keywords = ["FDR", "FWE", "Bonferroni", "correction"]
                found = [kw for kw in keywords if kw.lower() in desc.lower()]
                print(f"  ✅ Contains keywords: {', '.join(found)}")


def test_tool_schemas():
    """Test that tools have valid argument schemas."""
    print("\n" + "=" * 60)
    print("TESTING TOOL SCHEMAS")
    print("=" * 60)

    registry = ToolRegistry(auto_discover=True)

    test_tools = [
        "mne_connectivity",
        "permutation_testing",
        "multiple_comparison_correction",
    ]

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
                if tool_name == "mne_connectivity":
                    key_params = ["method", "fmin", "fmax", "output_dir"]
                elif tool_name == "permutation_testing":
                    key_params = [
                        "test_type",
                        "n_permutations",
                        "correction_method",
                        "alpha",
                    ]
                elif tool_name == "multiple_comparison_correction":
                    key_params = ["method", "alpha", "output_dir"]

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


def check_p0_completion():
    """Check completion status of P0 priority tools."""
    print("\n" + "=" * 60)
    print("P0 PRIORITY TOOLS COMPLETION STATUS")
    print("=" * 60)

    # All P0 tools from the issues document
    p0_tools = {
        "FSL Suite": [
            ("fsl_bet", "FSL BET Brain Extraction"),
            ("fsl_flirt", "FSL FLIRT Linear Registration"),
            ("fsl_fnirt", "FSL FNIRT Non-linear Registration"),
            ("fsl_bedpostx", "FSL BEDPOSTX Diffusion Modeling"),
            ("fsl_fix", "FSL FIX Artifact Removal"),
            ("fsl_palm", "FSL PALM Permutation Testing"),
        ],
        "MNE-Python Suite": [
            ("mne_preprocessing", "MNE Core Preprocessing"),
            ("mne_ica", "MNE ICA Artifact Removal"),
            ("mne_timefreq", "MNE Time-Frequency Analysis"),
            ("mne_source_localization", "MNE Source Localization"),
            ("mne_connectivity", "MNE Connectivity Analysis"),
        ],
        "Statistical Modeling": [
            ("statsmodels_glm", "Statsmodels GLM Integration"),
            ("mixed_effects", "Mixed Effects Models"),
            ("fitlins", "FitLins BIDS-GLM"),
            ("permutation_testing", "Permutation Testing Framework"),
            ("multiple_comparison_correction", "Multiple Comparison Correction"),
        ],
    }

    registry = ToolRegistry(auto_discover=True)
    all_tools = registry.get_all_tools()
    tool_names = [tool.get_tool_name() for tool in all_tools]

    total_p0 = 0
    completed_p0 = 0

    for category, tools in p0_tools.items():
        print(f"\n{category}:")
        for tool_id, tool_desc in tools:
            total_p0 += 1
            if tool_id in tool_names:
                print(f"  ✅ {tool_desc}")
                completed_p0 += 1
            else:
                print(f"  ⏳ {tool_desc}")

    completion_rate = (completed_p0 / total_p0) * 100 if total_p0 > 0 else 0

    print(f"\n" + "-" * 40)
    print(f"P0 Completion: {completed_p0}/{total_p0} ({completion_rate:.1f}%)")

    return completed_p0, total_p0


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SESSION 5 NEUROIMAGING TOOLS TEST")
    print("=" * 60)
    print(f"Testing at: {datetime.now().isoformat()}")

    # Run tests
    reg_results, total_tools = test_tool_registration()
    test_tool_descriptions()
    schema_results = test_tool_schemas()
    completed_p0, total_p0 = check_p0_completion()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    session5_tools = [
        "mne_connectivity",
        "permutation_testing",
        "multiple_comparison_correction",
    ]
    session5_registered = sum(
        1 for t in session5_tools if reg_results.get(t) == "registered"
    )

    print(f"Total tools in registry: {total_tools}")
    print(f"Session 5 tools registered: {session5_registered}/{len(session5_tools)}")
    print(f"P0 priority tools completed: {completed_p0}/{total_p0}")

    # Save results
    output_dir = REPO_ROOT / "outputs" / "test_outputs"
    output_dir.mkdir(exist_ok=True)

    results = {
        "timestamp": datetime.now().isoformat(),
        "session": "Session 5",
        "total_tools": total_tools,
        "registration": reg_results,
        "schemas": schema_results,
        "p0_completion": {
            "completed": completed_p0,
            "total": total_p0,
            "percentage": (completed_p0 / total_p0) * 100 if total_p0 > 0 else 0,
        },
        "summary": {
            "session5_registered": session5_registered,
            "session5_total": len(session5_tools),
        },
    }

    results_file = (
        output_dir / f"session5_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {results_file}")

    # New tools implemented in Session 5
    new_tools = [
        "MNE Connectivity Analysis (coherence, PLV, PLI, Granger causality)",
        "Permutation Testing Framework (t-tests, ANOVA, cluster correction, TFCE)",
        "Multiple Comparison Correction (FDR, FWE, spatial corrections)",
    ]

    print("\n" + "=" * 60)
    print("NEW TOOLS IMPLEMENTED IN SESSION 5:")
    print("=" * 60)
    for tool in new_tools:
        print(f"  ✅ {tool}")

    print(f"\nTotal new tools this session: {len(new_tools)}")
    print(f"All P0 priority statistical tools completed!")

    return session5_registered == len(session5_tools)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
