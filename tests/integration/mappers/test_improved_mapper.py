#!/usr/bin/env python3
"""
Test the improved NiCLIP spatial mapper.
"""

import json
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from brain_researcher.services.neurokg.etl.mappers.niclip_spatial_mapper_improved import (
    get_improved_mapper
)


def test_improved_mapper():
    """Test the improved spatial mapper."""
    print("🧪 Testing Improved NiCLIP Spatial Mapper")
    print("=" * 70)
    
    # Initialize mapper
    print("\n📚 Loading improved mapper...")
    mapper = get_improved_mapper()
    
    if not mapper or not mapper._loaded:
        print("❌ Failed to load improved mapper")
        return
        
    print("✅ Improved mapper loaded successfully")
    print(f"   Loaded {len(mapper.task_priors)} task priors")
    print(f"   Loaded {len(mapper.concept_priors)} concept priors")
    
    # Show percentile thresholds
    print(f"\n📊 Prior percentiles:")
    for p, value in mapper.prior_percentiles.items():
        print(f"   {p}: {value:.4f}")
    
    # Test different brain regions
    test_cases = [
        {
            "name": "Primary Motor Cortex",
            "coord": (-42, -22, 54),
            "expected": ["motor", "movement", "action"]
        },
        {
            "name": "Primary Visual Cortex", 
            "coord": (0, -90, 0),
            "expected": ["visual", "vision", "perception"]
        },
        {
            "name": "Broca's Area",
            "coord": (-50, 20, 0),
            "expected": ["language", "speech", "verbal"]
        },
        {
            "name": "Hippocampus",
            "coord": (-30, -18, -18),
            "expected": ["memory", "learning", "recall"]
        },
        {
            "name": "Dorsolateral PFC",
            "coord": (-44, 36, 20),
            "expected": ["executive", "attention", "control"]
        }
    ]
    
    print(f"\n🧠 Testing coordinate mappings:")
    print("-" * 70)
    
    for test in test_cases:
        print(f"\n📍 {test['name']}: {test['coord']}")
        print(f"   Expected concepts: {', '.join(test['expected'])}")
        
        # Map coordinate
        results = mapper.coordinate_to_concepts([test['coord']], radius=10.0, top_k=5)
        
        if results:
            result = results[0]
            concepts = result.get('concepts', [])
            
            if concepts:
                print(f"\n   Top concepts:")
                for i, concept in enumerate(concepts):
                    # Check if matches expected
                    matches = any(exp in concept['concept'].lower() for exp in test['expected'])
                    match_indicator = "✅" if matches else "  "
                    
                    print(f"   {match_indicator} {i+1}. {concept['concept']}")
                    print(f"         Score: {concept['score']:.3f}")
                    print(f"         Process: {concept['process']}")
            else:
                print(f"   ❌ No concepts found")
                
    # Test region proximity
    print(f"\n\n🎯 Testing region proximity effects:")
    print("-" * 70)
    
    # Test points at different distances from motor cortex
    motor_center = (-42, -22, 54)
    test_distances = [0, 5, 10, 15, 20]
    
    print(f"\nMotor cortex center: {motor_center}")
    print(f"Testing 'motor control' concept at different distances:")
    
    for dist in test_distances:
        # Create test point at distance
        test_coord = (motor_center[0] + dist, motor_center[1], motor_center[2])
        results = mapper.coordinate_to_concepts([test_coord], radius=15.0, top_k=10)
        
        if results and results[0]['concepts']:
            # Find motor control score
            motor_score = 0.0
            for concept in results[0]['concepts']:
                if 'motor' in concept['concept'].lower():
                    motor_score = max(motor_score, concept['score'])
                    
            print(f"   Distance {dist}mm: score = {motor_score:.3f}")
        else:
            print(f"   Distance {dist}mm: no concepts found")


if __name__ == "__main__":
    test_improved_mapper()
    print("\n\n✅ Improved mapper test complete!")