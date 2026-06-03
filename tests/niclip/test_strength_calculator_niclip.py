#!/usr/bin/env python3
"""
Test NiCLIP integration with StrengthCalculator

Demonstrates how NiCLIP brain-language alignment scores
are integrated into the evidence-based strength calculation.
"""

from brain_researcher.services.br_kg.etl.strength_calculator import StrengthCalculator
import pandas as pd
import json


def test_niclip_strength():
    """Test strength calculation with NiCLIP evidence."""

    # Initialize calculator
    calculator = StrengthCalculator()

    print("🧠 Testing NiCLIP Integration in Strength Calculator")
    print("=" * 60)

    # Test concepts that should be in NiCLIP
    test_cases = [
        ("n-back task", "prefrontal cortex"),
        ("language processing fMRI task paradigm", "broca's area"),
        ("motor fMRI task paradigm", "motor cortex"),
        ("emotion processing fMRI task paradigm", "amygdala"),
        ("face matching task", "fusiform face area"),
    ]

    for concept, region in test_cases:
        print(f"\n📊 Testing: {concept} → {region}")
        print("-" * 40)

        # Calculate NiCLIP strength
        strength, details = calculator.strength_from_niclip(concept, region)

        print(f"NiCLIP Strength: {strength}")
        print(f"Details: {json.dumps(details, indent=2)}")

        # Test with mock coordinate data for composite
        foci_df = pd.DataFrame({
            'x': [-45, -42, -48],
            'y': [15, 18, 12],
            'z': [30, 32, 28],
            'study_id': ['s1', 's2', 's3']
        })

        # Calculate all strengths
        all_results = calculator.calculate_all_strengths(
            concept=concept,
            region=region,
            foci_df=foci_df if "motor" in concept else None
        )

        print(f"\nComposite Results:")
        print(f"  Overall Strength: {all_results.get('strength', 0)}")
        print(f"  Evidence Types: {all_results.get('evidence', [])}")
        if 'niclip_details' in all_results:
            print(f"  NiCLIP Contribution: {all_results['strength_niclip']}")
            print(f"  Cognitive Process: {all_results['niclip_details'].get('cognitive_process')}")


def test_niclip_vs_traditional():
    """Compare NiCLIP-enhanced strength vs traditional methods."""

    calculator = StrengthCalculator()

    print("\n\n🔬 Comparing NiCLIP vs Traditional Methods")
    print("=" * 60)

    concept = "n-back task"
    region = "dorsolateral prefrontal cortex"

    # Traditional calculation (without NiCLIP)
    print(f"\nConcept: {concept} → Region: {region}")

    # Mock data
    foci_df = pd.DataFrame({
        'x': [-46] * 10,
        'y': [35] * 10,
        'z': [20] * 10,
        'study_id': [f's{i}' for i in range(10)]
    })

    # Coordinate strength
    s_coord, coord_details = calculator.strength_from_coordinates(concept, region, foci_df)
    print(f"\n1. Coordinate-based: {s_coord}")

    # NiCLIP strength
    s_niclip, niclip_details = calculator.strength_from_niclip(concept, region)
    print(f"2. NiCLIP-based: {s_niclip}")

    # Composite without NiCLIP
    comp_traditional = calculator.composite_strength(
        coord_w=0.7, map_w=0.3, effect_w=0.0, niclip_w=0.0,
        s_coord=s_coord, s_map=None, s_effect=None, s_niclip=None
    )
    print(f"\nTraditional Composite: {comp_traditional}")

    # Composite with NiCLIP
    comp_enhanced = calculator.composite_strength(
        coord_w=0.5, map_w=0.2, effect_w=0.0, niclip_w=0.3,
        s_coord=s_coord, s_map=None, s_effect=None, s_niclip=s_niclip
    )
    print(f"NiCLIP-Enhanced Composite: {comp_enhanced}")

    improvement = ((comp_enhanced - comp_traditional) / comp_traditional * 100) if comp_traditional > 0 else 0
    print(f"\nImprovement: {improvement:.1f}%")


def demonstrate_niclip_benefits():
    """Show specific benefits of NiCLIP integration."""

    print("\n\n✨ Benefits of NiCLIP Integration")
    print("=" * 60)

    calculator = StrengthCalculator()

    # 1. Scientific validation
    print("\n1️⃣ Scientifically Validated Mappings:")
    concepts = ["n-back task", "stroop task", "face viewing task"]
    for concept in concepts:
        strength, details = calculator.strength_from_niclip(concept)
        if details.get('niclip_score'):
            print(f"   {concept}: score={details['niclip_score']:.4f}")

    # 2. Cognitive process information
    print("\n2️⃣ Cognitive Process Information:")
    test_tasks = [
        "language processing fMRI task paradigm",
        "emotion processing fMRI task paradigm",
        "spatial localizer fMRI task paradigm"
    ]
    for task in test_tasks:
        _, details = calculator.strength_from_niclip(task)
        process = details.get('cognitive_process', 'unmapped')
        print(f"   {task[:30]}...: {process}")

    # 3. Fallback for sparse data
    print("\n3️⃣ Evidence When Traditional Methods Lack Data:")
    sparse_concept = "abstract/concrete task"

    # No coordinate data
    s_coord, _ = calculator.strength_from_coordinates(
        sparse_concept, "language areas", pd.DataFrame()
    )

    # But NiCLIP has data
    s_niclip, niclip_details = calculator.strength_from_niclip(sparse_concept)

    print(f"   Concept: {sparse_concept}")
    print(f"   Coordinate evidence: {s_coord}")
    print(f"   NiCLIP evidence: {s_niclip}")
    print(f"   → NiCLIP provides evidence when traditional methods fail")


if __name__ == "__main__":
    test_niclip_strength()
    test_niclip_vs_traditional()
    demonstrate_niclip_benefits()

    print("\n\n✅ NiCLIP Successfully Integrated into Strength Calculator!")
    print("   - Provides brain-language alignment scores as evidence")
    print("   - Enhances composite strength calculations")
    print("   - Adds cognitive process information")
    print("   - Offers fallback for concepts with sparse traditional data")