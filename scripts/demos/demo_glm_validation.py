#!/usr/bin/env python3
"""
Demonstration of GLM validation with mock data.

Shows how the system validates cognitive predictions against
actual brain activation patterns.
"""

import numpy as np
from typing import Dict, List, Any


def demo_glm_validation():
    """Demonstrate GLM validation with realistic scenarios."""
    print("🧠 GLM Direction Validation Demonstration")
    print("=" * 70)
    print("\nThis demo shows how cognitive predictions are validated against")
    print("actual fMRI activation patterns (GLM beta values).\n")

    # Scenario 1: High alignment - Working memory task
    print("📍 Scenario 1: Working Memory Task (n-back)")
    print("-" * 50)

    predictions = [
        {"name": "working memory", "predicted_direction": "+", "confidence": 0.85},
        {"name": "executive control", "predicted_direction": "+", "confidence": 0.80},
        {"name": "attention", "predicted_direction": "+", "confidence": 0.75}
    ]

    glm_results = [
        {"coordinate": "(-44, 36, 20) DLPFC", "beta": 2.34, "actual_direction": "+"},
        {"coordinate": "(-32, 46, 8) ACC", "beta": 1.89, "actual_direction": "+"},
        {"coordinate": "(44, 36, 20) R-DLPFC", "beta": 2.01, "actual_direction": "+"}
    ]

    print("\n🔮 Predictions:")
    for pred in predictions:
        print(f"   • {pred['name']}: {pred['predicted_direction']} (conf: {pred['confidence']:.0%})")

    print("\n📊 Actual GLM Beta Values:")
    for glm in glm_results:
        print(f"   • {glm['coordinate']}: β = {glm['beta']:.2f} ({glm['actual_direction']})")

    print("\n✅ Validation Result: HIGH ALIGNMENT (92%)")
    print("   All predictions match actual brain activation patterns!")

    # Scenario 2: Conflict - Visual task misclassified
    print("\n\n📍 Scenario 2: Visual Recognition Task (misclassified)")
    print("-" * 50)

    predictions = [
        {"name": "executive control", "predicted_direction": "+", "confidence": 0.70},
        {"name": "decision making", "predicted_direction": "+", "confidence": 0.65},
        {"name": "attention", "predicted_direction": "+", "confidence": 0.60}
    ]

    glm_results = [
        {"coordinate": "(0, -90, 0) V1", "beta": 3.45, "actual_direction": "+"},
        {"coordinate": "(-30, -80, 10) V2", "beta": 2.89, "actual_direction": "+"},
        {"coordinate": "(30, -65, -10) V4", "beta": 2.12, "actual_direction": "+"}
    ]

    print("\n🔮 Predictions:")
    for pred in predictions:
        print(f"   • {pred['name']}: {pred['predicted_direction']} (conf: {pred['confidence']:.0%})")

    print("\n📊 Actual GLM Beta Values:")
    for glm in glm_results:
        print(f"   • {glm['coordinate']}: β = {glm['beta']:.2f} ({glm['actual_direction']})")

    print("\n❌ Validation Result: CONFLICT DETECTED (35% alignment)")
    print("   Predictions suggest executive processing, but activation is in visual cortex!")
    print("   → Recommendation: Review task classification and retrain models")

    # Scenario 3: Direction mismatch
    print("\n\n📍 Scenario 3: Inhibition Task (direction mismatch)")
    print("-" * 50)

    predictions = [
        {"name": "motor control", "predicted_direction": "+", "confidence": 0.80},
        {"name": "response inhibition", "predicted_direction": "+", "confidence": 0.75},
        {"name": "cognitive control", "predicted_direction": "+", "confidence": 0.70}
    ]

    glm_results = [
        {"coordinate": "(-42, -22, 54) M1", "beta": -1.67, "actual_direction": "-"},
        {"coordinate": "(6, 16, 48) pre-SMA", "beta": 2.34, "actual_direction": "+"},
        {"coordinate": "(44, 12, 24) rIFG", "beta": 1.89, "actual_direction": "+"}
    ]

    print("\n🔮 Predictions:")
    for pred in predictions:
        print(f"   • {pred['name']}: {pred['predicted_direction']} (conf: {pred['confidence']:.0%})")

    print("\n📊 Actual GLM Beta Values:")
    for glm in glm_results:
        print(f"   • {glm['coordinate']}: β = {glm['beta']:.2f} ({glm['actual_direction']})")

    print("\n⚠️  Validation Result: PARTIAL ALIGNMENT (67%)")
    print("   Motor cortex shows deactivation (inhibition), but predicted activation!")
    print("   → This correctly identifies response inhibition pattern")

    # Summary
    print("\n\n📋 GLM Validation Benefits:")
    print("=" * 70)

    benefits = [
        "1. Ensures cognitive interpretations match neural evidence",
        "2. Detects when models misclassify task types",
        "3. Identifies direction mismatches (activation vs deactivation)",
        "4. Provides confidence scores for clinical/research use",
        "5. Enables continuous model improvement through feedback"
    ]

    for benefit in benefits:
        print(f"   {benefit}")

    print("\n🔄 Integration with NiCLIP-LLM Fusion:")
    print("   • GLM validation adds a third source of evidence")
    print("   • Helps resolve conflicts between NiCLIP and LLM")
    print("   • Provides ground truth from actual brain data")
    print("   • Enables data-driven model refinement")


def show_mathematical_framework():
    """Show the mathematical framework for alignment scoring."""
    print("\n\n📐 Mathematical Framework for GLM Alignment")
    print("=" * 70)

    print("\nAlignment Score Calculation:")
    print("-" * 30)

    print("\n1. Direction Matching:")
    print("   If predicted_direction == actual_direction:")
    print("      base_score = 0.7 + 0.3 * min(|β|/3, 1)")
    print("   Else:")
    print("      base_score = 0.3 - 0.3 * min(|β|/3, 1)")

    print("\n2. Magnitude Weighting:")
    print("   • Stronger activations (|β| > 2) increase confidence")
    print("   • Weak activations (|β| < 0.5) treated as neutral")
    print("   • Deactivations (β < -1) important for inhibition")

    print("\n3. Spatial Consistency:")
    print("   • Check neighboring voxels for consistent patterns")
    print("   • Higher consistency → higher confidence")
    print("   • Isolated activations → lower confidence")

    print("\n4. Final Score:")
    print("   alignment = weighted_avg(direction_match, magnitude, consistency)")
    print("   Range: [0, 1] where >0.8 is high alignment")


if __name__ == "__main__":
    demo_glm_validation()
    show_mathematical_framework()

    print("\n\n✅ GLM Validation Demo Complete!")