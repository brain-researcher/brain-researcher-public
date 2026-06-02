#!/usr/bin/env python3
"""
Examples demonstrating NiCLIP-LLM fusion in various scenarios.

This script shows how the fusion system handles different types of
brain regions and cognitive tasks, highlighting agreements, conflicts,
and edge cases.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from brain_researcher.services.tools.br_kg_tools import CoordinateToConceptTool
from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import get_fusion_module


def print_fusion_results(title: str, result: Dict[str, Any]):
    """Pretty print fusion results."""
    print(f"\n{'='*80}")
    print(f"📍 {title}")
    print(f"{'='*80}")

    if result.get('status') != 'success':
        print(f"❌ Error: {result.get('error', 'Unknown error')}")
        return

    data = result.get('data', {})

    # Basic info
    print(f"\n🧠 Brain Region Analysis:")
    mappings = data.get('coordinate_mappings', [])
    if mappings:
        mapping = mappings[0]
        print(f"   Coordinates: {mapping['coordinate']}")
        print(f"   Top concepts from NiCLIP:")
        for concept in mapping.get('concepts', [])[:3]:
            print(f"      - {concept['concept']} (score: {concept['score']:.3f})")

    # Fusion analysis
    fusion = data.get('fusion', {})
    if fusion and fusion.get('fusion_enabled'):
        print(f"\n🔀 NiCLIP-LLM Fusion Analysis:")

        # Metrics
        metrics = fusion.get('fusion_metrics', {})
        print(f"\n   📊 Fusion Metrics:")
        print(f"      Sources combined: LLM ({metrics.get('n_llm', 0)}) + NiCLIP ({metrics.get('n_niclip', 0)})")
        print(f"      Concept overlap: {metrics.get('n_overlap', 0)} ({metrics.get('overlap_ratio', 0):.1%})")

        if metrics.get('avg_confidence'):
            conf = metrics['avg_confidence']
            color = "🟢" if conf >= 0.8 else "🟡" if conf >= 0.6 else "🔴"
            print(f"      Average confidence: {color} {conf:.1%}")

        if metrics.get('n_conflicts', 0) > 0:
            print(f"      ⚠️  Conflicts detected: {metrics['n_conflicts']}")

        # Top concepts
        top_concepts = fusion.get('top_fused_concepts', [])
        if top_concepts:
            print(f"\n   🎯 Top Fused Concepts:")
            for i, concept in enumerate(top_concepts[:3]):
                print(f"\n   {i+1}. {concept['name']}")

                # Confidence with color
                conf = concept['confidence']
                color = "🟢" if conf >= 0.8 else "🟡" if conf >= 0.6 else "🔴"
                print(f"      Combined confidence: {color} {conf:.1%}")

                # Sources
                print(f"      Evidence sources: {' + '.join(concept['sources'])}")

                # Detailed evidence
                evidence = concept.get('evidence', {})
                if evidence.get('llm'):
                    llm_conf = evidence['llm']['confidence']
                    print(f"      └─ LLM: {llm_conf:.1%}", end="")
                    if evidence['llm'].get('direction'):
                        print(f" (direction: {evidence['llm']['direction']})")
                    else:
                        print()

                if evidence.get('niclip'):
                    niclip_conf = evidence['niclip']['confidence']
                    print(f"      └─ NiCLIP: {niclip_conf:.1%}", end="")
                    if evidence['niclip'].get('spatial_confidence'):
                        print(f" (spatial: {evidence['niclip']['spatial_confidence']:.1%})")
                    else:
                        print()

                # Conflict warning
                if evidence.get('conflict'):
                    print(f"      ⚠️  CONFLICT: Score = {evidence.get('conflict_score', 0):.3f}")
                    print(f"         (Large disagreement between sources)")


def example_1_motor_cortex():
    """Example 1: Primary Motor Cortex - High Agreement Expected"""
    tool = CoordinateToConceptTool()

    # Primary motor cortex coordinates
    result = tool._run(
        coordinates=[[-42, -22, 54]],  # Left M1
        radius=10.0,
        top_k=5
    )

    print_fusion_results(
        "Example 1: Primary Motor Cortex (Expected: High Agreement)",
        result.model_dump()
    )

    print(f"\n💡 Interpretation:")
    print(f"   Motor cortex is well-characterized in both brain imaging and")
    print(f"   cognitive literature, so we expect good agreement between NiCLIP")
    print(f"   and LLM sources.")


def example_2_prefrontal_complex():
    """Example 2: Prefrontal Cortex - Mixed Agreement Expected"""
    tool = CoordinateToConceptTool()

    # Dorsolateral prefrontal cortex
    result = tool._run(
        coordinates=[[-44, 36, 20]],  # Left DLPFC
        radius=10.0,
        top_k=5
    )

    print_fusion_results(
        "Example 2: Dorsolateral Prefrontal Cortex (Expected: Mixed Agreement)",
        result.model_dump()
    )

    print(f"\n💡 Interpretation:")
    print(f"   DLPFC is involved in many cognitive functions (working memory,")
    print(f"   executive control, attention). This complexity may lead to some")
    print(f"   disagreement between brain-based and literature-based evidence.")


def example_3_visual_cortex():
    """Example 3: Visual Cortex - Domain-Specific Region"""
    tool = CoordinateToConceptTool()

    # Primary visual cortex
    result = tool._run(
        coordinates=[[0, -90, 0]],  # V1
        radius=10.0,
        top_k=5
    )

    print_fusion_results(
        "Example 3: Primary Visual Cortex (Expected: Perceptual Focus)",
        result.model_dump()
    )

    print(f"\n💡 Interpretation:")
    print(f"   Visual cortex should show strong evidence for perceptual")
    print(f"   processes. NiCLIP should have high confidence here due to")
    print(f"   clear brain-function mapping.")


def example_4_multiple_coordinates():
    """Example 4: Multiple Coordinates - Network Analysis"""
    tool = CoordinateToConceptTool()

    # Language network coordinates
    result = tool._run(
        coordinates=[
            [-50, 20, 0],    # Broca's area
            [-60, -42, 22],  # Wernicke's area
            [-48, -64, 32]   # Angular gyrus
        ],
        radius=10.0,
        top_k=5
    )

    print_fusion_results(
        "Example 4: Language Network (Multiple Coordinates)",
        result.model_dump()
    )

    print(f"\n💡 Interpretation:")
    print(f"   Multiple coordinates from the language network should converge")
    print(f"   on language-related concepts. This tests the system's ability")
    print(f"   to handle network-level analysis.")


def example_5_edge_case():
    """Example 5: Edge Case - Subcortical Structure"""
    tool = CoordinateToConceptTool()

    # Hippocampus coordinates
    result = tool._run(
        coordinates=[[-30, -18, -18]],  # Left hippocampus
        radius=8.0,  # Smaller radius for subcortical
        top_k=5
    )

    print_fusion_results(
        "Example 5: Hippocampus (Edge Case: Subcortical)",
        result.model_dump()
    )

    print(f"\n💡 Interpretation:")
    print(f"   Subcortical structures may have different coverage in NiCLIP")
    print(f"   vs literature. This tests the system's handling of regions")
    print(f"   that might be underrepresented in one source.")


def demonstrate_ui_scenarios():
    """Show how different scenarios appear in the UI."""
    print(f"\n\n{'='*80}")
    print(f"🖥️  UI Display Scenarios")
    print(f"{'='*80}")

    print(f"\n1️⃣ High Agreement Scenario (Motor Cortex):")
    print(f"   ┌─────────────────────────────────────────┐")
    print(f"   │ 🔀 Fusion Analysis (3 overlapping)     │")
    print(f"   │ ─────────────────────────────────────── │")
    print(f"   │ motor control              🟢 85.2%     │")
    print(f"   │ Sources: 🤖 LLM + 🧠 NiCLIP           │")
    print(f"   │ ✓ Strong agreement between sources      │")
    print(f"   └─────────────────────────────────────────┘")

    print(f"\n2️⃣ Conflict Scenario (Complex Region):")
    print(f"   ┌─────────────────────────────────────────┐")
    print(f"   │ 🔀 Fusion Analysis ⚠️ (2 conflicts)     │")
    print(f"   │ ─────────────────────────────────────── │")
    print(f"   │ working memory             🟡 65.5%     │")
    print(f"   │ LLM: 90% | NiCLIP: 41%                 │")
    print(f"   │ ⚠️ Conflict score: 0.49                 │")
    print(f"   └─────────────────────────────────────────┘")

    print(f"\n3️⃣ Low Confidence Scenario:")
    print(f"   ┌─────────────────────────────────────────┐")
    print(f"   │ 🔀 Fusion Analysis                      │")
    print(f"   │ ─────────────────────────────────────── │")
    print(f"   │ abstract reasoning         🔴 35.2%     │")
    print(f"   │ ℹ️ Low confidence - interpret with care │")
    print(f"   └─────────────────────────────────────────┘")

    print(f"\n4️⃣ Network Analysis (Multiple Regions):")
    print(f"   ┌─────────────────────────────────────────┐")
    print(f"   │ 🔀 Network Fusion (3 coordinates)       │")
    print(f"   │ ─────────────────────────────────────── │")
    print(f"   │ Converging concepts:                    │")
    print(f"   │ • language processing     🟢 88.5%      │")
    print(f"   │ • speech production       🟢 82.3%      │")
    print(f"   │ • semantic processing     🟡 71.0%      │")
    print(f"   └─────────────────────────────────────────┘")


def show_clinical_example():
    """Show a clinical research example."""
    print(f"\n\n{'='*80}")
    print(f"🏥 Clinical Research Example")
    print(f"{'='*80}")

    print(f"\n📋 Scenario: Analyzing fMRI activation from a memory task")
    print(f"\n🔬 Research Question: What cognitive processes are engaged at [-36, -52, -20]?")

    tool = CoordinateToConceptTool()
    result = tool._run(
        coordinates=[[-36, -52, -20]],  # Fusiform area
        radius=10.0,
        top_k=5
    )

    data = result.model_dump().get('data', {})
    fusion = data.get('fusion', {})

    if fusion.get('fusion_enabled'):
        print(f"\n📊 Analysis Results:")
        print(f"   Region identified: Fusiform area")
        print(f"   Primary function: Face and object recognition")

        print(f"\n🔀 Evidence Integration:")
        top_concepts = fusion.get('top_fused_concepts', [])
        for concept in top_concepts[:2]:
            print(f"\n   • {concept['name']}:")
            evidence = concept.get('evidence', {})
            if evidence.get('llm'):
                print(f"     Literature evidence: {evidence['llm']['confidence']:.1%}")
            if evidence.get('niclip'):
                print(f"     Brain alignment: {evidence['niclip']['confidence']:.1%}")
            print(f"     Combined confidence: {concept['confidence']:.1%}")

        print(f"\n✅ Clinical Interpretation:")
        print(f"   The fusion analysis provides multiple lines of evidence")
        print(f"   for each cognitive process, increasing confidence in")
        print(f"   the functional interpretation of the activation.")


def main():
    """Run all examples."""
    print(f"🚀 NiCLIP-LLM Fusion Examples")
    print(f"{'='*80}")
    print(f"\nThese examples demonstrate how the fusion system handles")
    print(f"different brain regions and scenarios.\n")

    # Run examples
    example_1_motor_cortex()
    example_2_prefrontal_complex()
    example_3_visual_cortex()
    example_4_multiple_coordinates()
    example_5_edge_case()

    # Show UI scenarios
    demonstrate_ui_scenarios()

    # Clinical example
    show_clinical_example()

    print(f"\n\n✅ Examples Complete!")
    print(f"{'='*80}")
    print(f"\n💡 Key Takeaways:")
    print(f"   1. Well-characterized regions show high agreement")
    print(f"   2. Complex regions may show conflicts (useful for research)")
    print(f"   3. The system handles multiple coordinates for network analysis")
    print(f"   4. Transparency helps researchers interpret results")
    print(f"   5. Conflicts highlight areas needing further investigation")


if __name__ == "__main__":
    main()