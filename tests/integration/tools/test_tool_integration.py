#!/usr/bin/env python3
"""
Test the CoordinateToConceptTool with improved mapper.
"""

import json
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from brain_researcher.services.tools.neurokg_tools import CoordinateToConceptTool


def test_tool():
    """Test the tool integration."""
    print("🧪 Testing CoordinateToConceptTool with Improved Mapper")
    print("=" * 70)
    
    # Initialize tool
    tool = CoordinateToConceptTool()
    
    # Test motor cortex
    print("\n📍 Testing Primary Motor Cortex: [-42, -22, 54]")
    
    result = tool._run(
        coordinates=[[-42, -22, 54]],
        radius=10.0,
        top_k=5
    )
    
    print(f"\nStatus: {result.status}")
    
    if result.status == "success":
        data = result.data
        print(f"Method: {data.get('method', 'unknown')}")
        
        mappings = data.get('coordinate_mappings', [])
        if mappings:
            mapping = mappings[0]
            print(f"\nTop concepts:")
            for i, concept in enumerate(mapping.get('concepts', [])[:5]):
                print(f"  {i+1}. {concept['concept']} (score: {concept['score']:.3f})")
                
        # Check fusion
        fusion = data.get('fusion')
        if fusion and fusion.get('fusion_enabled'):
            print(f"\n🔀 Fusion enabled!")
            metrics = fusion.get('fusion_metrics', {})
            print(f"   Overlap: {metrics.get('n_overlap', 0)} concepts")
            print(f"   Conflicts: {metrics.get('n_conflicts', 0)}")
        else:
            print(f"\n⚠️  Fusion not enabled")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    test_tool()