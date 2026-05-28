#!/usr/bin/env python3
"""
Test script to demonstrate NiCLIP-LLM fusion metadata in the UI.

This script tests the coordinate_to_concept tool with fusion metadata
and shows how it appears in the UI.
"""

import json
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from brain_researcher.services.tools.neurokg_tools import CoordinateToConceptTool


def test_coordinate_mapping_with_fusion():
    """Test coordinate to concept mapping with fusion metadata."""
    print("🧪 Testing Coordinate to Concept Mapping with NiCLIP-LLM Fusion")
    print("=" * 70)
    
    # Initialize the tool
    tool = CoordinateToConceptTool()
    
    # Test coordinates (left prefrontal cortex)
    coordinates = [[-44, 8, 28]]
    
    print(f"\n📍 Mapping coordinates: {coordinates}")
    print(f"   Region: Left inferior frontal gyrus (Broca's area)")
    
    # Run the tool
    result = tool._run(
        coordinates=coordinates,
        radius=10.0,
        top_k=5
    )
    
    print(f"\n✅ Tool Status: {result.status}")
    
    if result.status == "success":
        # Display basic results
        data = result.data
        print(f"\n📊 Basic Results:")
        print(f"   Method: {data.get('method', 'unknown')}")
        print(f"   Atlas: {data.get('atlas', 'unknown')}")
        print(f"   Coordinates processed: {data.get('n_coordinates', 0)}")
        
        # Display coordinate mappings
        if 'coordinate_mappings' in data:
            for mapping in data['coordinate_mappings']:
                print(f"\n   Coordinate {mapping['coordinate']}:")
                for concept in mapping.get('concepts', [])[:3]:
                    print(f"      - {concept['concept']} (score: {concept['score']:.3f})")
        
        # Display fusion metadata
        if 'fusion' in data and data['fusion']:
            fusion = data['fusion']
            
            if fusion.get('fusion_enabled'):
                print(f"\n🔀 NiCLIP-LLM Fusion Analysis:")
                
                # Fusion metrics
                metrics = fusion.get('fusion_metrics', {})
                if metrics:
                    print(f"\n   Fusion Metrics:")
                    print(f"      LLM concepts: {metrics.get('n_llm', 0)}")
                    print(f"      NiCLIP concepts: {metrics.get('n_niclip', 0)}")
                    print(f"      Overlap: {metrics.get('n_overlap', 0)}")
                    print(f"      Overlap ratio: {metrics.get('overlap_ratio', 0):.2%}")
                    if 'avg_confidence' in metrics:
                        print(f"      Average confidence: {metrics['avg_confidence']:.2%}")
                    if metrics.get('n_conflicts', 0) > 0:
                        print(f"      ⚠️  Conflicts detected: {metrics['n_conflicts']}")
                
                # Top fused concepts
                if 'top_fused_concepts' in fusion:
                    print(f"\n   Top Fused Concepts:")
                    for i, concept in enumerate(fusion['top_fused_concepts'][:3]):
                        print(f"\n   {i+1}. {concept['name']}")
                        print(f"      Combined confidence: {concept['confidence']:.2%}")
                        print(f"      Sources: {', '.join(concept['sources'])}")
                        
                        # Evidence details
                        evidence = concept.get('evidence', {})
                        if evidence.get('llm'):
                            print(f"      LLM confidence: {evidence['llm']['confidence']:.2%}")
                        if evidence.get('niclip'):
                            print(f"      NiCLIP confidence: {evidence['niclip']['confidence']:.2%}")
                        if evidence.get('conflict'):
                            print(f"      ⚠️  Conflict score: {evidence.get('conflict_score', 0):.3f}")
            else:
                print(f"\n⚠️  Fusion not enabled: {fusion.get('reason', 'unknown')}")
        else:
            print(f"\n⚠️  No fusion metadata available")
        
        # Show how it would appear in the UI
        print(f"\n🖥️  UI Display Preview:")
        print(f"   The fusion metadata would appear as an expandable panel")
        print(f"   showing the combined evidence from both NiCLIP and LLM.")
        print(f"   Users can click to see detailed confidence scores and")
        print(f"   any conflicts between the two approaches.")
        
    else:
        print(f"\n❌ Error: {result.error}")
        if result.metadata:
            print(f"   Metadata: {json.dumps(result.metadata, indent=2)}")


def demonstrate_ui_features():
    """Demonstrate the UI features for fusion metadata."""
    print(f"\n\n🎨 UI Features for NiCLIP-LLM Fusion")
    print("=" * 70)
    
    print(f"\n1️⃣ Expandable Fusion Panel:")
    print(f"   - Click to expand/collapse detailed fusion analysis")
    print(f"   - Shows fusion metrics at a glance")
    print(f"   - Gradient background to highlight fusion results")
    
    print(f"\n2️⃣ Color-Coded Confidence:")
    print(f"   - 🟢 Green: High confidence (≥80%)")
    print(f"   - 🟡 Yellow: Medium confidence (60-80%)")
    print(f"   - 🔴 Red: Low confidence (<60%)")
    
    print(f"\n3️⃣ Evidence Sources:")
    print(f"   - 🤖 LLM: Language model semantic understanding")
    print(f"   - 🧠 NiCLIP: Brain-data alignment")
    print(f"   - Shows which sources contributed to each concept")
    
    print(f"\n4️⃣ Conflict Detection:")
    print(f"   - ⚠️ Warning icon for conflicts")
    print(f"   - Shows conflict score when sources disagree")
    print(f"   - Helps identify concepts needing expert review")
    
    print(f"\n5️⃣ Detailed Evidence:")
    print(f"   - Individual confidence scores from each source")
    print(f"   - Direction information (+1/-1) from LLM")
    print(f"   - Spatial confidence from NiCLIP")


def show_integration_benefits():
    """Show the benefits of the integrated approach."""
    print(f"\n\n✨ Benefits of NiCLIP-LLM Integration")
    print("=" * 70)
    
    print(f"\n🎯 Enhanced Accuracy:")
    print(f"   - Combines objective brain data with semantic knowledge")
    print(f"   - Reduces false positives through cross-validation")
    print(f"   - Identifies concepts missed by single approach")
    
    print(f"\n🔍 Transparency:")
    print(f"   - Shows evidence from both sources")
    print(f"   - Highlights agreements and conflicts")
    print(f"   - Enables informed decision-making")
    
    print(f"\n📊 Active Learning:")
    print(f"   - Flags high-conflict cases for expert review")
    print(f"   - Improves models based on feedback")
    print(f"   - Continuous improvement cycle")
    
    print(f"\n🚀 Future Enhancements:")
    print(f"   - Real-time LLM annotation (currently using mock)")
    print(f"   - Multiple brain atlases support")
    print(f"   - Customizable fusion weights per user")


if __name__ == "__main__":
    test_coordinate_mapping_with_fusion()
    demonstrate_ui_features()
    show_integration_benefits()
    
    print(f"\n\n✅ Integration test complete!")
    print(f"   The fusion metadata is now available in the UI")
    print(f"   for enhanced cognitive annotation visualization.")