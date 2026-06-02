#!/usr/bin/env python3
"""
Test GLM direction validation in the fusion system.

This script demonstrates how predicted cognitive processes are validated
against actual brain activation patterns (GLM beta values).
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from brain_researcher.services.br_kg.etl.mappers.glm_direction_validator import (
    get_glm_validator,
)
from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import (
    get_fusion_module,
)


def test_glm_validator():
    """Test the GLM validator standalone."""
    print("🧪 Testing GLM Direction Validator")
    print("=" * 70)

    # Initialize validator
    validator = get_glm_validator()

    if not validator:
        print("❌ GLM validator not available")
        return

    print(f"✅ GLM validator loaded")
    print(f"   Available contrasts: {len(validator.get_available_contrasts())}")

    # Show some available contrasts
    contrasts = validator.get_available_contrasts()[:5]
    if contrasts:
        print(f"\n📋 Sample contrasts:")
        for contrast in contrasts:
            print(f"   - {contrast}")

    # Test beta extraction
    if contrasts:
        test_contrast = contrasts[0]
        test_coords = [(-44, 36, 20)]  # DLPFC

        print(f"\n🎯 Testing beta extraction:")
        print(f"   Contrast: {test_contrast}")
        print(f"   Coordinate: {test_coords[0]}")

        beta_results = validator.extract_beta_values(test_contrast, test_coords)

        if beta_results and not beta_results[0].get("error"):
            result = beta_results[0]
            print(f"\n   Beta value: {result['beta_value']:.3f}")
            print(f"   Direction: {result['direction']}")
            print(f"   Local mean: {result['local_mean']:.3f}")
            print(f"   Local std: {result['local_std']:.3f}")
        else:
            print(f"   ❌ Error: {beta_results[0].get('error', 'Unknown')}")


def test_fusion_with_glm():
    """Test the fusion system with GLM validation."""
    print("\n\n🔀 Testing Fusion with GLM Validation")
    print("=" * 70)

    # Initialize fusion module
    fusion = get_fusion_module()

    # Test coordinates and contrast
    test_coords = [
        (-44, 36, 20),  # DLPFC - executive
        (-42, -22, 54),  # Motor cortex
        (-30, -18, -18),  # Hippocampus - memory
    ]

    # Create test LLM result
    llm_result = {
        "constructs": [
            {
                "id": "trm_executive_control",
                "name": "executive control",
                "llm_confidence": 0.85,
                "direction": "+1",
            },
            {
                "id": "trm_working_memory",
                "name": "working memory",
                "llm_confidence": 0.75,
                "direction": "+1",
            },
            {
                "id": "trm_attention",
                "name": "attention",
                "llm_confidence": 0.70,
                "direction": "+1",
            },
        ]
    }

    # Perform fusion with GLM validation
    print(f"\n📍 Testing with coordinates:")
    for coord in test_coords:
        print(f"   {coord}")

    result = fusion.fuse_annotations(
        contrast_name="working_memory_vs_rest",
        task_name="n-back",
        llm_result=llm_result,
        mni_coordinates=test_coords,
        validate_with_glm=True,
    )

    # Display results
    print(f"\n✅ Fusion completed")

    # Show fusion metrics
    metrics = result.get("fusion_metrics", {})
    print(f"\n📊 Fusion Metrics:")
    print(f"   LLM concepts: {metrics.get('n_llm', 0)}")
    print(f"   NiCLIP concepts: {metrics.get('n_niclip', 0)}")
    print(f"   Overlap: {metrics.get('n_overlap', 0)}")

    # Show GLM validation if available
    glm_val = result.get("glm_validation", {})
    if glm_val.get("validation_available"):
        print(f"\n🎯 GLM Validation Results:")
        summary = glm_val.get("summary", {})
        print(f"   Mean alignment: {summary.get('mean_alignment', 0):.2%}")
        print(f"   Aligned predictions: {summary.get('n_aligned', 0)}")
        print(f"   Misaligned predictions: {summary.get('n_misaligned', 0)}")
        print(f"   Neutral predictions: {summary.get('n_neutral', 0)}")

        # Show individual alignments
        print(f"\n   Detailed alignments:")
        for align in glm_val.get("alignments", [])[:3]:
            match_symbol = "✅" if align["direction_match"] else "❌"
            print(f"   {match_symbol} {align['construct']}:")
            print(
                f"      Predicted: {'+' if align['predicted_direction'] > 0 else '-'}"
            )
            print(f"      Actual β: {align['beta_value']:.3f}")
            print(f"      Alignment: {align['alignment_score']:.2%}")
    else:
        print(f"\n⚠️  GLM validation not available")
        if glm_val.get("error"):
            print(f"   Error: {glm_val['error']}")

    # Show top constructs with GLM alignment
    print(f"\n🏆 Top Fused Constructs with GLM Alignment:")
    for i, construct in enumerate(result["constructs"][:3]):
        print(f"\n   {i+1}. {construct['name']}")
        print(f"      Confidence: {construct['confidence']:.2%}")

        if "glm_alignment" in construct:
            glm_align = construct["glm_alignment"]
            match_symbol = "✅" if glm_align["direction_match"] else "❌"
            print(
                f"      GLM: {match_symbol} β={glm_align['beta_value']:.3f}, align={glm_align['score']:.2%}"
            )


def demonstrate_use_cases():
    """Demonstrate practical use cases for GLM validation."""
    print("\n\n💡 Use Cases for GLM Direction Validation")
    print("=" * 70)

    print("\n1️⃣ Quality Control:")
    print("   - Validate that predicted cognitive processes match actual activation")
    print("   - Identify when NiCLIP/LLM predictions conflict with brain data")
    print("   - Flag contrasts where predictions need expert review")

    print("\n2️⃣ Model Improvement:")
    print("   - Use misaligned predictions to improve NiCLIP training")
    print("   - Refine LLM prompts based on GLM feedback")
    print("   - Build dataset of validated brain-cognition mappings")

    print("\n3️⃣ Research Applications:")
    print("   - Ensure cognitive interpretations align with neural evidence")
    print("   - Discover novel brain-cognition relationships")
    print("   - Validate theoretical cognitive models against brain data")

    print("\n4️⃣ Clinical Translation:")
    print("   - Verify that patient brain patterns match expected cognition")
    print("   - Detect atypical brain-cognition relationships")
    print("   - Guide intervention based on validated mappings")


if __name__ == "__main__":
    test_glm_validator()
    test_fusion_with_glm()
    demonstrate_use_cases()

    print("\n\n✅ GLM validation test complete!")
