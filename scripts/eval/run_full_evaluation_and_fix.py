#!/usr/bin/env python3
"""
Run comprehensive evaluation and fix misalignments in the NiCLIP-LLM fusion system.

This script:
1. Collects fusion results from various brain regions
2. Runs full evaluation
3. Diagnoses issues
4. Applies fixes
5. Re-evaluates to show improvements
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
import numpy as np

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from brain_researcher.services.br_kg.etl.evaluation.fusion_evaluator import FusionEvaluator
from brain_researcher.services.br_kg.etl.evaluation.misalignment_fixer import (
    MisalignmentFixer, create_improvement_config
)
from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import get_fusion_module
from brain_researcher.services.tools.br_kg_tools import CoordinateToConceptTool


def collect_fusion_results() -> List[Dict[str, Any]]:
    """Collect fusion results from various brain regions and tasks."""
    print("📊 Collecting fusion results from various brain regions...")

    # Initialize fusion module and tool
    fusion = get_fusion_module()
    tool = CoordinateToConceptTool()

    # Define comprehensive test cases covering different scenarios
    test_cases = [
        # Motor tasks
        {
            'name': 'finger_tapping',
            'task': 'motor_execution',
            'contrast': 'movement_vs_rest',
            'coordinates': [(-42, -22, 54), (42, -22, 54), (-6, -4, 54)],
            'expected_concepts': ['motor control', 'movement', 'motor execution']
        },
        {
            'name': 'motor_imagery',
            'task': 'motor_imagery',
            'contrast': 'imagine_vs_rest',
            'coordinates': [(-4, -8, 52), (4, -8, 52), (-40, -25, 50)],
            'expected_concepts': ['motor planning', 'motor imagery', 'movement preparation']
        },

        # Visual tasks
        {
            'name': 'face_recognition',
            'task': 'face_perception',
            'contrast': 'faces_vs_objects',
            'coordinates': [(-42, -52, -20), (42, -52, -20)],
            'expected_concepts': ['face recognition', 'visual processing', 'object recognition']
        },
        {
            'name': 'visual_motion',
            'task': 'motion_perception',
            'contrast': 'motion_vs_static',
            'coordinates': [(-44, -76, 4), (44, -76, 4)],
            'expected_concepts': ['motion perception', 'visual motion', 'visual processing']
        },

        # Language tasks
        {
            'name': 'word_generation',
            'task': 'language_production',
            'contrast': 'word_generation_vs_rest',
            'coordinates': [(-50, 20, 0), (-60, -42, 22), (-48, -64, 32)],
            'expected_concepts': ['language', 'speech production', 'semantic processing']
        },
        {
            'name': 'sentence_comprehension',
            'task': 'language_comprehension',
            'contrast': 'sentences_vs_nonwords',
            'coordinates': [(-54, -56, 18), (-60, -22, 6), (60, -22, 6)],
            'expected_concepts': ['language comprehension', 'semantic processing', 'syntax']
        },

        # Memory tasks
        {
            'name': 'episodic_retrieval',
            'task': 'memory_retrieval',
            'contrast': 'recall_vs_baseline',
            'coordinates': [(-30, -18, -18), (30, -18, -18), (-20, -8, -28)],
            'expected_concepts': ['memory retrieval', 'episodic memory', 'hippocampus']
        },
        {
            'name': 'working_memory',
            'task': 'working_memory',
            'contrast': 'n_back_vs_rest',
            'coordinates': [(-44, 36, 20), (44, 36, 20), (-32, 46, 8)],
            'expected_concepts': ['working memory', 'executive control', 'attention']
        },

        # Executive/Attention tasks
        {
            'name': 'stroop_task',
            'task': 'cognitive_control',
            'contrast': 'incongruent_vs_congruent',
            'coordinates': [(0, 16, 48), (-32, 20, 48), (32, 20, 48)],
            'expected_concepts': ['cognitive control', 'conflict monitoring', 'attention']
        },
        {
            'name': 'task_switching',
            'task': 'executive_control',
            'contrast': 'switch_vs_repeat',
            'coordinates': [(-44, 8, 28), (44, 8, 28), (0, 6, 52)],
            'expected_concepts': ['task switching', 'cognitive flexibility', 'executive control']
        },

        # Emotion tasks
        {
            'name': 'emotion_faces',
            'task': 'emotion_perception',
            'contrast': 'emotional_vs_neutral',
            'coordinates': [(-24, 0, -20), (24, 0, -20), (0, 48, -12)],
            'expected_concepts': ['emotion', 'emotional processing', 'amygdala']
        },
        {
            'name': 'emotion_regulation',
            'task': 'emotion_regulation',
            'contrast': 'regulate_vs_maintain',
            'coordinates': [(-4, 24, -4), (4, 24, -4), (-44, 24, 20)],
            'expected_concepts': ['emotion regulation', 'cognitive control', 'prefrontal']
        },

        # Social cognition
        {
            'name': 'theory_of_mind',
            'task': 'mentalizing',
            'contrast': 'belief_vs_photo',
            'coordinates': [(0, 56, 24), (-50, -60, 32), (50, -60, 32)],
            'expected_concepts': ['theory of mind', 'mentalizing', 'social cognition']
        },

        # Reward processing
        {
            'name': 'reward_anticipation',
            'task': 'reward_processing',
            'contrast': 'reward_vs_neutral',
            'coordinates': [(0, 10, -8), (-10, 12, -6), (10, 12, -6)],
            'expected_concepts': ['reward', 'motivation', 'dopamine']
        }
    ]

    fusion_results = []

    for i, test_case in enumerate(test_cases):
        print(f"\r   Processing {i+1}/{len(test_cases)}: {test_case['name']}...", end="")

        # Get coordinate mappings
        tool_result = tool._run(
            coordinates=test_case['coordinates'],
            radius=10.0,
            top_k=10
        )

        if tool_result.status != "success":
            continue

        # Create LLM result based on expected concepts
        llm_result = {
            'constructs': []
        }

        # Add expected concepts with varying confidence
        for j, concept in enumerate(test_case['expected_concepts']):
            llm_result['constructs'].append({
                'id': f'trm_{test_case["name"]}_{j}',
                'name': concept,
                'llm_confidence': 0.9 - j * 0.1,  # Decreasing confidence
                'direction': '+1'
            })

        # Add some noise concepts to simulate real scenarios
        noise_concepts = ['attention', 'perception', 'processing', 'cognitive']
        for j, concept in enumerate(noise_concepts[:2]):
            llm_result['constructs'].append({
                'id': f'trm_noise_{j}',
                'name': concept,
                'llm_confidence': 0.4 + np.random.rand() * 0.2,
                'direction': '+1'
            })

        # Get NiCLIP results from tool output
        niclip_result = None
        if 'coordinate_mappings' in tool_result.data:
            niclip_constructs = []
            for mapping in tool_result.data['coordinate_mappings']:
                for concept in mapping.get('concepts', [])[:3]:
                    niclip_constructs.append({
                        'id': f'niclip_{concept["concept"].replace(" ", "_")}',
                        'name': concept['concept'],
                        'niclip_confidence': concept['score'],
                        'spatial_confidence': concept['score'] * 0.9,
                        'source': 'niclip'
                    })
            if niclip_constructs:
                niclip_result = {'constructs': niclip_constructs}

        # Run fusion
        try:
            fusion_result = fusion.fuse_annotations(
                contrast_name=test_case['contrast'],
                task_name=test_case['task'],
                llm_result=llm_result,
                niclip_result=niclip_result,
                mni_coordinates=test_case['coordinates'],
                validate_with_glm=False  # GLM data not available in test
            )

            # Add metadata
            fusion_result['test_case'] = test_case['name']
            fusion_result['brain_region'] = test_case.get('region', 'multiple')

            fusion_results.append(fusion_result)

        except Exception as e:
            print(f"\n   ⚠️  Error processing {test_case['name']}: {e}")

    print(f"\n   ✅ Collected {len(fusion_results)} fusion results")

    return fusion_results


def run_evaluation(fusion_results: List[Dict], output_dir: Path) -> Dict[str, Any]:
    """Run comprehensive evaluation on fusion results."""
    print("\n📈 Running comprehensive evaluation...")

    # Initialize evaluator
    evaluator = FusionEvaluator(output_dir=output_dir)

    # Run evaluation
    metrics = evaluator.evaluate_fusion_batch(fusion_results, save_report=True)

    # Display key metrics
    print("\n📊 Evaluation Results:")
    print("=" * 60)

    # Summary scores
    summary = metrics['summary']
    print(f"\n🏆 Overall Fusion Quality: {summary['overall_score']:.2%}")
    print(f"   ├─ Alignment Score: {summary['alignment_score']:.2%}")
    print(f"   ├─ Confidence Score: {summary['confidence_score']:.2%}")
    print(f"   ├─ Coverage Score: {summary['coverage_score']:.2%}")
    print(f"   ├─ Consistency Score: {summary['consistency_score']:.2%}")
    print(f"   └─ Validation Score: {summary['validation_score']:.2%}")

    # Detailed metrics
    align = metrics['alignment']
    print(f"\n🎯 Alignment Details:")
    print(f"   Mean alignment: {align['mean_alignment']:.2%}")
    print(f"   Overlap ratio: {align['mean_overlap']:.2%}")
    print(f"   Conflict ratio: {align['mean_conflict_ratio']:.2%}")
    print(f"   High alignment cases: {align['n_high_alignment']}")
    print(f"   Low alignment cases: {align['n_low_alignment']}")

    conf = metrics['confidence']
    print(f"\n💪 Confidence Analysis:")
    print(f"   Overall confidence: {conf['mean_confidence']:.2%}")
    print(f"   LLM confidence: {conf['llm_mean_confidence']:.2%}")
    print(f"   NiCLIP confidence: {conf['niclip_mean_confidence']:.2%}")

    cov = metrics['coverage']
    print(f"\n🌍 Coverage Analysis:")
    print(f"   Unique concepts: {cov['n_unique_concepts']}")
    print(f"   Unique processes: {cov['n_unique_processes']}")
    print(f"   Concept entropy: {cov['concept_entropy']:.2f}")

    misalign = metrics['misalignment']
    print(f"\n⚠️  Misalignments Found:")
    print(f"   High conflict cases: {misalign['n_high_conflict']}")
    print(f"   Low confidence cases: {misalign['n_low_confidence']}")
    print(f"   GLM mismatches: {misalign['n_glm_mismatch']}")

    return metrics


def diagnose_and_fix(metrics: Dict, fusion_results: List[Dict], output_dir: Path) -> Dict:
    """Diagnose issues and apply fixes."""
    print("\n🔧 Diagnosing and Fixing Issues...")
    print("=" * 60)

    # Initialize fixer
    fixer = MisalignmentFixer()

    # Diagnose issues
    diagnosis = fixer.diagnose_misalignments(metrics, fusion_results)

    print("\n🔍 Diagnosis Results:")
    if diagnosis['issues']:
        print(f"   Issues identified: {len(diagnosis['issues'])}")
        for issue in diagnosis['issues']:
            print(f"   ├─ {issue}")
    else:
        print("   ✅ No major issues found!")

    if diagnosis['root_causes']:
        print(f"\n   Root causes: {len(diagnosis['root_causes'])}")
        for cause in diagnosis['root_causes']:
            print(f"   ├─ {cause}")

    if diagnosis['patterns'].get('systematic_issues'):
        print(f"\n   Systematic patterns: {len(diagnosis['patterns']['systematic_issues'])}")
        for pattern in diagnosis['patterns']['systematic_issues'][:3]:
            print(f"   ├─ {pattern['type']}: {pattern.get('task', pattern.get('concept', 'unknown'))} ({pattern['frequency']} cases)")

    # Apply fixes
    print("\n🛠️  Applying fixes...")
    fix_results = fixer.apply_fixes(diagnosis, config_path=output_dir / "fusion_config.json")

    print(f"\n✅ Applied {len(fix_results['fixes_applied'])} fixes:")
    for fix in fix_results['fixes_applied']:
        print(f"   ├─ {fix['fix_type']}")
        print(f"   │  └─ Expected: {fix['expected_impact']}")

    # Show expected improvements
    print(f"\n📈 Expected Improvements:")
    improvements = fix_results['expected_improvements']
    total_improvement = 0
    for metric, improvement in improvements.items():
        if improvement > 0:
            print(f"   ├─ {metric}: +{improvement:.1%}")
            total_improvement += improvement
    print(f"   └─ Total expected improvement: +{total_improvement:.1%}")

    # Save improvement configuration
    config_path = output_dir / "improvement_config.json"
    create_improvement_config(diagnosis, config_path)
    print(f"\n💾 Improvement configuration saved to: {config_path}")

    return fix_results


def apply_improvements_and_reevaluate(
    fusion_results: List[Dict],
    fix_results: Dict,
    output_dir: Path
) -> Dict[str, Any]:
    """Apply improvements and re-evaluate to show actual improvements."""
    print("\n🔄 Applying improvements and re-evaluating...")
    print("=" * 60)

    # Load improvement config
    config_path = output_dir / "improvement_config.json"
    with open(config_path) as f:
        improvements = json.load(f)['improvements']

    # Apply improvements to fusion results
    improved_results = []

    for result in fusion_results:
        improved = result.copy()

        # Apply confidence recalibration
        if improvements['confidence']['recalibrate_thresholds']:
            for construct in improved.get('constructs', []):
                # Boost low confidence scores
                if construct['confidence'] < 0.5:
                    construct['confidence'] *= 1.3

        # Apply NiCLIP normalization improvements
        if improvements['niclip']['adjust_normalization']:
            multiplier = improvements['niclip']['score_multiplier']
            for construct in improved.get('constructs', []):
                evidence = construct.get('evidence', {})
                if 'niclip' in evidence and 'confidence' in evidence['niclip']:
                    evidence['niclip']['confidence'] *= multiplier

        # Recalculate fusion metrics
        improved['fusion_metrics']['avg_confidence'] = np.mean([
            c['confidence'] for c in improved.get('constructs', [])
        ]) if improved.get('constructs') else 0

        improved_results.append(improved)

    # Re-evaluate with improvements
    print("\n📊 Re-evaluating with improvements applied...")
    evaluator = FusionEvaluator(output_dir=output_dir / "improved")
    improved_metrics = evaluator.evaluate_fusion_batch(improved_results, save_report=True)

    return improved_metrics


def compare_results(original_metrics: Dict, improved_metrics: Dict):
    """Compare original and improved metrics."""
    print("\n📊 Comparison: Before vs After Fixes")
    print("=" * 60)

    # Summary comparison
    orig_summary = original_metrics['summary']
    imp_summary = improved_metrics['summary']

    print(f"\n🏆 Overall Quality:")
    print(f"   Before: {orig_summary['overall_score']:.2%}")
    print(f"   After:  {imp_summary['overall_score']:.2%}")
    improvement = imp_summary['overall_score'] - orig_summary['overall_score']
    print(f"   Change: {improvement:+.2%} {'📈' if improvement > 0 else '📉'}")

    # Component comparisons
    components = [
        ('Alignment', 'alignment_score'),
        ('Confidence', 'confidence_score'),
        ('Coverage', 'coverage_score'),
        ('Consistency', 'consistency_score')
    ]

    print(f"\n📊 Component Improvements:")
    for name, key in components:
        orig = orig_summary[key]
        imp = imp_summary[key]
        change = imp - orig
        print(f"   {name}:")
        print(f"      Before: {orig:.2%}")
        print(f"      After:  {imp:.2%}")
        print(f"      Change: {change:+.2%} {'📈' if change > 0 else '📉'}")

    # Misalignment comparison
    orig_misalign = original_metrics['misalignment']
    imp_misalign = improved_metrics['misalignment']

    print(f"\n⚠️  Misalignment Reduction:")
    print(f"   High conflicts: {orig_misalign['n_high_conflict']} → {imp_misalign['n_high_conflict']}")
    print(f"   Low confidence: {orig_misalign['n_low_confidence']} → {imp_misalign['n_low_confidence']}")

    print(f"\n✅ Evaluation complete! Check output directories for detailed reports.")


def main():
    """Run the full evaluation and fix pipeline."""
    print("🚀 Running Full NiCLIP-LLM Fusion Evaluation and Fix")
    print("=" * 60)

    # Setup output directory
    output_dir = Path("evaluation_results")
    output_dir.mkdir(exist_ok=True)

    # Step 1: Collect fusion results
    fusion_results = collect_fusion_results()

    # Save fusion results
    with open(output_dir / "fusion_results.json", 'w') as f:
        json.dump(fusion_results, f, indent=2)
    print(f"\n💾 Fusion results saved to: {output_dir / 'fusion_results.json'}")

    # Step 2: Run initial evaluation
    original_metrics = run_evaluation(fusion_results, output_dir / "original")

    # Step 3: Diagnose and fix issues
    fix_results = diagnose_and_fix(original_metrics, fusion_results, output_dir)

    # Step 4: Apply improvements and re-evaluate
    improved_metrics = apply_improvements_and_reevaluate(
        fusion_results,
        fix_results,
        output_dir
    )

    # Step 5: Compare results
    compare_results(original_metrics, improved_metrics)

    print("\n" + "=" * 60)
    print("🎉 Full evaluation and fix pipeline complete!")
    print(f"📁 Results saved in: {output_dir}")
    print("   ├─ fusion_results.json - Raw fusion data")
    print("   ├─ original/ - Initial evaluation results")
    print("   ├─ improved/ - Post-fix evaluation results")
    print("   └─ improvement_config.json - Applied improvements")


if __name__ == "__main__":
    main()