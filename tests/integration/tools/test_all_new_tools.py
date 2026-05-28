#!/usr/bin/env python3
"""Test all newly implemented tools."""

import sys
from pathlib import Path
import tempfile
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from brain_researcher.services.tools.genetics_genomics_tools import GeneticsGenomicsTools
from brain_researcher.services.tools.pet_imaging_tools import PETImagingTools
from brain_researcher.services.tools.optical_imaging_tools import OpticalImagingTools
from brain_researcher.services.tools.interactive_visualization_tools import InteractiveVisualizationTools


def test_genetics_tools():
    """Test genetics/genomics tools."""
    print("\n=== Testing Genetics/Genomics Tools ===")
    tools = GeneticsGenomicsTools()
    
    for tool in tools.get_all_tools():
        print(f"Testing {tool.get_tool_name()}...")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = tool._run(output_dir=temp_dir)
            assert result.status == "success", f"{tool.get_tool_name()} failed: {result.error}"
            print(f"  ✓ {tool.get_tool_name()} passed")
    
    print(f"✓ All {len(tools.get_all_tools())} genetics tools passed")
    return len(tools.get_all_tools())


def test_pet_tools():
    """Test PET imaging tools."""
    print("\n=== Testing PET Imaging Tools ===")
    tools = PETImagingTools()
    
    for tool in tools.get_all_tools():
        print(f"Testing {tool.get_tool_name()}...")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = tool._run(output_dir=temp_dir)
            assert result.status == "success", f"{tool.get_tool_name()} failed: {result.error}"
            print(f"  ✓ {tool.get_tool_name()} passed")
    
    print(f"✓ All {len(tools.get_all_tools())} PET tools passed")
    return len(tools.get_all_tools())


def test_optical_tools():
    """Test optical imaging tools."""
    print("\n=== Testing Optical Imaging Tools ===")
    tools = OpticalImagingTools()
    
    for tool in tools.get_all_tools():
        print(f"Testing {tool.get_tool_name()}...")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = tool._run(output_dir=temp_dir)
            assert result.status == "success", f"{tool.get_tool_name()} failed: {result.error}"
            print(f"  ✓ {tool.get_tool_name()} passed")
    
    print(f"✓ All {len(tools.get_all_tools())} optical tools passed")
    return len(tools.get_all_tools())


def test_visualization_tools():
    """Test interactive visualization tools."""
    print("\n=== Testing Interactive Visualization Tools ===")
    tools = InteractiveVisualizationTools()
    
    for tool in tools.get_all_tools():
        print(f"Testing {tool.get_tool_name()}...")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = tool._run(output_dir=temp_dir)
            assert result.status == "success", f"{tool.get_tool_name()} failed: {result.error}"
            print(f"  ✓ {tool.get_tool_name()} passed")
    
    print(f"✓ All {len(tools.get_all_tools())} visualization tools passed")
    return len(tools.get_all_tools())


def main():
    """Run all tests."""
    print("Testing all newly implemented neuroimaging tools...")
    
    total_tools = 0
    
    try:
        # Test each category
        total_tools += test_genetics_tools()
        total_tools += test_pet_tools()
        total_tools += test_optical_tools()
        total_tools += test_visualization_tools()
        
        print("\n" + "="*50)
        print(f"✓ SUCCESS: All {total_tools} new tools tested successfully!")
        print("="*50)
        
        # Print summary
        print("\nSummary of implemented tools:")
        print("- Genetics/Genomics: 8 tools")
        print("- PET Imaging: 6 tools")
        print("- Optical Imaging: 5 tools")
        print("- Interactive Visualization: 5 tools")
        print(f"- Total: {total_tools} tools")
        
        return 0
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())