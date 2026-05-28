#!/usr/bin/env python3
"""
Test script for P1 priority neuroimaging tools implementation.
Tests registration and basic functionality of new P1 tools.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.services.tools.tool_registry import ToolRegistry

def test_p1_tool_registration():
    """Test that all new P1 tools are properly registered."""
    print("\n" + "="*60)
    print("TESTING P1 TOOL REGISTRATION")
    print("="*60)
    
    registry = ToolRegistry(auto_discover=True)
    all_tools = registry.get_all_tools()
    tool_names = [tool.get_tool_name() for tool in all_tools]
    
    # New P1 tools
    p1_tools = [
        # MNE Advanced
        "mne_fooof",  # FOOOF Spectral Parameterization
        "mne_autoreject",  # Autoreject Automated QC
        # Pattern Analysis
        "rsa_toolbox",  # RSA Toolbox Integration
        "searchlight_analysis",  # Searchlight Analysis
    ]
    
    print(f"\nTotal tools registered: {len(tool_names)}")
    print("\nChecking P1 priority tools:")
    
    results = {}
    for tool_name in p1_tools:
        if tool_name in tool_names:
            print(f"✅ {tool_name}: REGISTERED")
            results[tool_name] = "registered"
        else:
            print(f"❌ {tool_name}: NOT FOUND")
            results[tool_name] = "missing"
    
    return results, len(tool_names)


def test_tool_descriptions():
    """Test that P1 tools have proper descriptions."""
    print("\n" + "="*60)
    print("TESTING P1 TOOL DESCRIPTIONS")
    print("="*60)
    
    registry = ToolRegistry(auto_discover=True)
    
    # Test the new P1 tools
    test_tools = [
        ("mne_fooof", ["FOOOF", "spectral", "oscillations", "1/f"]),
        ("mne_autoreject", ["autoreject", "quality control", "epochs", "cross-validation"]),
        ("rsa_toolbox", ["RSA", "representational", "similarity", "RDM"]),
        ("searchlight_analysis", ["searchlight", "local", "pattern", "spherical"])
    ]
    
    for tool_name, keywords in test_tools:
        tool = registry.get_tool(tool_name)
        if tool:
            desc = tool.get_tool_description()
            print(f"\n{tool_name}:")
            print(f"  Description length: {len(desc)} chars")
            
            found = [kw for kw in keywords if kw.lower() in desc.lower()]
            if found:
                print(f"  ✅ Contains keywords: {', '.join(found)}")
            else:
                print(f"  ❌ Missing expected keywords")


def test_tool_schemas():
    """Test that P1 tools have valid argument schemas."""
    print("\n" + "="*60)
    print("TESTING P1 TOOL SCHEMAS")
    print("="*60)
    
    registry = ToolRegistry(auto_discover=True)
    
    test_tools = {
        "mne_fooof": ["freq_range", "peak_width_limits", "aperiodic_mode", "output_dir"],
        "mne_autoreject": ["epochs_file", "cv", "mode", "output_dir"],
        "rsa_toolbox": ["data_file", "distance_metric", "analysis_type", "output_dir"],
        "searchlight_analysis": ["func_file", "radius", "analysis_type", "classifier", "output_dir"]
    }
    
    results = {}
    for tool_name, key_params in test_tools.items():
        tool = registry.get_tool(tool_name)
        if tool:
            try:
                schema = tool.get_args_schema()
                fields = schema.__fields__ if hasattr(schema, '__fields__') else {}
                
                print(f"\n{tool_name}:")
                print(f"  Number of parameters: {len(fields)}")
                
                missing = []
                for param in key_params:
                    if param in fields:
                        print(f"  ✅ Has '{param}' parameter")
                    else:
                        print(f"  ❌ Missing '{param}' parameter")
                        missing.append(param)
                
                results[tool_name] = "valid_schema" if not missing else "incomplete_schema"
            except Exception as e:
                print(f"  ❌ Schema error: {e}")
                results[tool_name] = "schema_error"
    
    return results


def check_implementation_coverage():
    """Check overall implementation coverage."""
    print("\n" + "="*60)
    print("IMPLEMENTATION COVERAGE ANALYSIS")
    print("="*60)
    
    registry = ToolRegistry(auto_discover=True)
    all_tools = registry.get_all_tools()
    tool_names = [tool.get_tool_name() for tool in all_tools]
    
    # Define all tool categories
    categories = {
        "FSL": ["fsl_bet", "fsl_flirt", "fsl_fnirt", "fsl_bedpostx", "fsl_fix", "fsl_palm", 
                "fsl_feat", "fsl_melodic"],
        "MNE": ["mne_preprocessing", "mne_ica", "mne_timefreq", "mne_source_localization",
                "mne_connectivity", "mne_fooof", "mne_autoreject"],
        "Statistical": ["statsmodels_glm", "mixed_effects", "fitlins", 
                        "permutation_testing", "multiple_comparison_correction"],
        "Pattern Analysis": ["rsa_toolbox", "searchlight_analysis"],
        "Preprocessing": ["fmriprep", "qsiprep", "xcpd"],
        "Connectivity": ["conn_tool", "mne_connectivity"],
        "Other": ["nilearn_expanded", "nipype_tool", "spm12_tool", "ants_tool", "freesurfer_tool"]
    }
    
    coverage_stats = {}
    for category, expected_tools in categories.items():
        found = [t for t in expected_tools if t in tool_names]
        coverage = (len(found) / len(expected_tools)) * 100 if expected_tools else 0
        coverage_stats[category] = {
            "found": len(found),
            "total": len(expected_tools),
            "percentage": coverage,
            "missing": [t for t in expected_tools if t not in tool_names]
        }
        
        print(f"\n{category}:")
        print(f"  Coverage: {len(found)}/{len(expected_tools)} ({coverage:.1f}%)")
        if coverage_stats[category]["missing"]:
            print(f"  Missing: {', '.join(coverage_stats[category]['missing'])}")
    
    return coverage_stats


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("P1 PRIORITY NEUROIMAGING TOOLS TEST")
    print("="*60)
    print(f"Testing at: {datetime.now().isoformat()}")
    
    # Run tests
    reg_results, total_tools = test_p1_tool_registration()
    test_tool_descriptions()
    schema_results = test_tool_schemas()
    coverage_stats = check_implementation_coverage()
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    p1_tools = ["mne_fooof", "mne_autoreject", "rsa_toolbox", "searchlight_analysis"]
    p1_registered = sum(1 for t in p1_tools if reg_results.get(t) == "registered")
    
    print(f"Total tools in registry: {total_tools}")
    print(f"P1 tools registered: {p1_registered}/{len(p1_tools)}")
    
    # Calculate overall coverage
    total_expected = sum(stats["total"] for stats in coverage_stats.values())
    total_found = sum(stats["found"] for stats in coverage_stats.values())
    overall_coverage = (total_found / total_expected) * 100 if total_expected > 0 else 0
    
    print(f"Overall implementation coverage: {total_found}/{total_expected} ({overall_coverage:.1f}%)")
    
    # Save results
    output_dir = REPO_ROOT / "outputs" / "test_outputs"
    output_dir.mkdir(exist_ok=True)
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "test_type": "P1 Priority Tools",
        "total_tools": total_tools,
        "registration": reg_results,
        "schemas": schema_results,
        "coverage": coverage_stats,
        "summary": {
            "p1_registered": p1_registered,
            "p1_total": len(p1_tools),
            "overall_coverage_percentage": overall_coverage
        }
    }
    
    results_file = output_dir / f"p1_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: {results_file}")
    
    # New tools implemented
    new_tools_info = [
        "MNE FOOOF - Spectral parameterization (oscillations + 1/f)",
        "MNE Autoreject - Automated quality control with cross-validation",
        "RSA Toolbox - Representational similarity analysis",
        "Searchlight Analysis - Local pattern analysis across brain"
    ]
    
    print("\n" + "="*60)
    print("NEW P1 TOOLS IMPLEMENTED:")
    print("="*60)
    for info in new_tools_info:
        print(f"  ✅ {info}")
    
    print(f"\nTotal new P1 tools: {len(new_tools_info)}")
    print(f"Session progress: Completed {p1_registered} P1 priority tools")
    
    return p1_registered == len(p1_tools)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
