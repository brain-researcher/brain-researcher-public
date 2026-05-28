#!/usr/bin/env python3
"""
Test the enhanced NiCLIP spatial mapper with Gaussian weighting and percentile normalization.
"""

import json
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from brain_researcher.services.neurokg.etl.mappers.niclip_spatial_mapper_enhanced import (
    get_enhanced_mapper
)


def test_enhanced_mapper():
    """Test the enhanced spatial mapper functionality."""
    print("🧪 Testing Enhanced NiCLIP Spatial Mapper")
    print("=" * 70)
    
    # Initialize mapper
    print("\n📚 Loading enhanced mapper...")
    mapper = get_enhanced_mapper(atlas="difumo512")
    
    if not mapper or not mapper._loaded:
        print("❌ Failed to load enhanced mapper")
        return
        
    print("✅ Enhanced mapper loaded successfully")
    
    # Test coordinates from different brain regions
    test_cases = [
        {
            "name": "Primary Motor Cortex (M1)",
            "coordinates": [(-42, -22, 54)],
            "expected_concepts": ["motor", "movement", "action"]
        },
        {
            "name": "Primary Visual Cortex (V1)",
            "coordinates": [(0, -90, 0)],
            "expected_concepts": ["visual", "vision", "perception"]
        },
        {
            "name": "Broca's Area (Language)",
            "coordinates": [(-50, 20, 0)],
            "expected_concepts": ["language", "speech", "verbal"]
        },
        {
            "name": "Hippocampus (Memory)",
            "coordinates": [(-30, -18, -18)],
            "expected_concepts": ["memory", "learning", "recall"]
        },
        {
            "name": "Prefrontal Cortex (Executive)",
            "coordinates": [(-44, 36, 20)],
            "expected_concepts": ["executive", "control", "attention"]
        }
    ]
    
    for test in test_cases:
        print(f"\n\n🧠 Testing: {test['name']}")
        print(f"   Coordinates: {test['coordinates'][0]}")
        print(f"   Expected concepts: {', '.join(test['expected_concepts'])}")
        
        # Map coordinates to concepts
        results = mapper.coordinate_to_concepts(
            test['coordinates'],
            radius=10.0,
            top_k=5,
            min_percentile=50.0
        )
        
        if results:
            result = results[0]
            
            if result.get('error'):
                print(f"   ❌ Error: {result['error']}")
                continue
                
            if result.get('warning'):
                print(f"   ⚠️  Warning: {result['warning']}")
                
            print(f"\n   📊 Results:")
            print(f"      Method: {result.get('method', 'unknown')}")
            print(f"      Parcels used: {result.get('n_parcels', 0)}")
            
            concepts = result.get('concepts', [])
            if concepts:
                print(f"\n   🎯 Top Concepts:")
                for i, concept in enumerate(concepts):
                    print(f"      {i+1}. {concept['concept']}")
                    print(f"         Score: {concept['score']:.3f}")
                    print(f"         Percentile: {concept['percentile']:.1f}%")
                    print(f"         Process: {concept['process']}")
                    
                    # Check if expected concepts found
                    concept_lower = concept['concept'].lower()
                    matches_expected = any(
                        exp in concept_lower 
                        for exp in test['expected_concepts']
                    )
                    if matches_expected:
                        print(f"         ✅ Matches expected domain!")
                        
                    # Show contributing parcels
                    if concept.get('contributing_parcels'):
                        print(f"         Contributing parcels:")
                        for parcel in concept['contributing_parcels'][:2]:
                            print(f"            - {parcel['parcel']} (weight: {parcel['weight']:.3f})")
            else:
                print(f"   ❌ No concepts found")
                
    # Test percentile normalization
    print("\n\n📊 Testing Percentile Normalization")
    print("=" * 70)
    
    if hasattr(mapper, 'percentiles'):
        print(f"\nPercentile thresholds:")
        for p, value in mapper.percentiles.items():
            print(f"   {p}: {value:.4f}")
            
    # Test multi-dimensional embeddings
    print("\n\n🔢 Testing Multi-dimensional Embeddings")
    print("=" * 70)
    
    test_concepts = ["memory", "attention", "motor control", "language"]
    embeddings = mapper.get_concept_embeddings(test_concepts)
    
    print(f"\nGenerated embeddings for {len(test_concepts)} concepts:")
    for concept, embedding in embeddings.items():
        print(f"   {concept}: {embedding.shape} dimensional vector")
        print(f"      L2 norm: {np.linalg.norm(embedding):.3f}")
        print(f"      Non-zero elements: {np.count_nonzero(embedding)}")
        
    # Calculate pairwise similarities
    print(f"\n📐 Pairwise concept similarities:")
    from scipy.spatial.distance import cosine
    
    for i, concept1 in enumerate(test_concepts):
        for j, concept2 in enumerate(test_concepts[i+1:], i+1):
            similarity = 1 - cosine(embeddings[concept1], embeddings[concept2])
            print(f"   {concept1} <-> {concept2}: {similarity:.3f}")


if __name__ == "__main__":
    import numpy as np  # Import here to avoid issues if test fails early
    test_enhanced_mapper()
    print("\n\n✅ Enhanced mapper test complete!")