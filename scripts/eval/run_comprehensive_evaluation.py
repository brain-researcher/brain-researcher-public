#!/usr/bin/env python3
"""
Run comprehensive evaluation of the NiCLIP-LLM fusion system with detailed analysis.

This script:
1. Tests the fusion system across multiple brain regions and tasks
2. Evaluates performance metrics in detail
3. Identifies specific misalignment patterns
4. Generates actionable recommendations
5. Creates visualization reports
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple
import numpy as np
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from brain_researcher.services.br_kg.etl.evaluation.fusion_evaluator import FusionEvaluator
from brain_researcher.services.br_kg.etl.evaluation.misalignment_fixer import MisalignmentFixer
from brain_researcher.services.tools.br_kg_tools import CoordinateToConceptTool


def run_comprehensive_test_suite() -> Tuple[List[Dict], Dict[str, List]]:
    """Run comprehensive tests across brain regions and cognitive domains."""
    print("🧪 Running Comprehensive Fusion System Evaluation")
    print("=" * 70)

    tool = CoordinateToConceptTool()

    # Comprehensive test suite organized by cognitive domain
    test_suite = {
        "Motor System": [
            {
                "name": "primary_motor_cortex",
                "coordinates": [(-42, -22, 54), (42, -22, 54)],
                "expected": ["motor control", "movement", "motor execution"],
                "description": "M1 - hand area"
            },
            {
                "name": "premotor_cortex",
                "coordinates": [(-24, -4, 64), (24, -4, 64)],
                "expected": ["motor planning", "action preparation", "motor imagery"],
                "description": "Premotor cortex"
            },
            {
                "name": "supplementary_motor_area",
                "coordinates": [(-6, -4, 54), (6, -4, 54)],
                "expected": ["motor control", "movement initiation", "bimanual coordination"],
                "description": "SMA"
            }
        ],
        "Visual System": [
            {
                "name": "primary_visual_cortex",
                "coordinates": [(0, -90, 0), (-10, -95, 0), (10, -95, 0)],
                "expected": ["visual perception", "vision", "visual processing"],
                "description": "V1"
            },
            {
                "name": "fusiform_face_area",
                "coordinates": [(-42, -52, -20), (42, -52, -20)],
                "expected": ["face recognition", "face perception", "visual recognition"],
                "description": "FFA"
            },
            {
                "name": "motion_area_MT",
                "coordinates": [(-44, -76, 4), (44, -76, 4)],
                "expected": ["motion perception", "visual motion", "movement detection"],
                "description": "MT/V5"
            }
        ],
        "Language System": [
            {
                "name": "brocas_area",
                "coordinates": [(-50, 20, 0), (-54, 18, 8)],
                "expected": ["speech production", "language", "verbal fluency"],
                "description": "Broca's area - BA44/45"
            },
            {
                "name": "wernickes_area",
                "coordinates": [(-60, -42, 22), (-64, -38, 20)],
                "expected": ["language comprehension", "speech perception", "semantic processing"],
                "description": "Wernicke's area"
            },
            {
                "name": "angular_gyrus",
                "coordinates": [(-48, -64, 32), (48, -64, 32)],
                "expected": ["reading", "semantic processing", "language"],
                "description": "Angular gyrus"
            }
        ],
        "Memory System": [
            {
                "name": "hippocampus",
                "coordinates": [(-30, -18, -18), (30, -18, -18)],
                "expected": ["memory", "episodic memory", "memory encoding"],
                "description": "Hippocampus"
            },
            {
                "name": "parahippocampal_cortex",
                "coordinates": [(-28, -40, -12), (28, -40, -12)],
                "expected": ["memory", "scene processing", "spatial memory"],
                "description": "Parahippocampal cortex"
            },
            {
                "name": "posterior_parietal",
                "coordinates": [(-30, -60, 40), (30, -60, 40)],
                "expected": ["working memory", "spatial working memory", "attention"],
                "description": "Posterior parietal cortex"
            }
        ],
        "Executive System": [
            {
                "name": "dorsolateral_pfc",
                "coordinates": [(-44, 36, 20), (44, 36, 20)],
                "expected": ["executive control", "working memory", "cognitive control"],
                "description": "DLPFC"
            },
            {
                "name": "anterior_cingulate",
                "coordinates": [(0, 20, 35), (-4, 24, 32), (4, 24, 32)],
                "expected": ["conflict monitoring", "error detection", "attention"],
                "description": "ACC"
            },
            {
                "name": "inferior_frontal_gyrus",
                "coordinates": [(-48, 18, 8), (48, 18, 8)],
                "expected": ["inhibition", "cognitive control", "response inhibition"],
                "description": "IFG"
            }
        ],
        "Emotion System": [
            {
                "name": "amygdala",
                "coordinates": [(-24, -4, -20), (24, -4, -20)],
                "expected": ["emotion", "fear", "emotional processing"],
                "description": "Amygdala"
            },
            {
                "name": "ventromedial_pfc",
                "coordinates": [(0, 48, -12), (-4, 52, -8), (4, 52, -8)],
                "expected": ["emotion regulation", "decision making", "value"],
                "description": "vmPFC"
            },
            {
                "name": "insula",
                "coordinates": [(-36, 16, 4), (36, 16, 4)],
                "expected": ["interoception", "emotion", "pain"],
                "description": "Anterior insula"
            }
        ],
        "Social Cognition": [
            {
                "name": "temporo_parietal_junction",
                "coordinates": [(-50, -60, 32), (50, -60, 32)],
                "expected": ["theory of mind", "mentalizing", "social cognition"],
                "description": "TPJ"
            },
            {
                "name": "medial_pfc",
                "coordinates": [(0, 56, 24), (-4, 60, 20), (4, 60, 20)],
                "expected": ["self-referential", "mentalizing", "social cognition"],
                "description": "mPFC"
            },
            {
                "name": "posterior_sts",
                "coordinates": [(-54, -48, 16), (54, -48, 16)],
                "expected": ["social perception", "biological motion", "face processing"],
                "description": "pSTS"
            }
        ]
    }

    all_results = []
    domain_results = {}

    print(f"\n📊 Testing {sum(len(tests) for tests in test_suite.values())} brain regions across {len(test_suite)} domains\n")

    for domain, tests in test_suite.items():
        print(f"\n🧠 {domain}")
        print("-" * 50)
        domain_results[domain] = []

        for test in tests:
            print(f"  Testing {test['description']}...", end="")

            # Run coordinate to concept mapping
            result = tool._run(
                coordinates=test['coordinates'],
                radius=10.0,
                top_k=10
            )

            if result.status == "success":
                # Extract results
                test_result = {
                    "domain": domain,
                    "region": test['name'],
                    "description": test['description'],
                    "coordinates": test['coordinates'],
                    "expected_concepts": test['expected'],
                    "actual_concepts": [],
                    "fusion_data": result.data.get('fusion', {}),
                    "niclip_enabled": result.metadata.get('niclip_enabled', False),
                    "fusion_enabled": result.metadata.get('fusion_available', False)
                }

                # Extract actual concepts
                if 'coordinate_mappings' in result.data:
                    for mapping in result.data['coordinate_mappings']:
                        for concept in mapping.get('concepts', [])[:5]:
                            test_result['actual_concepts'].append({
                                'name': concept['concept'],
                                'score': concept['score'],
                                'process': concept.get('process', 'unknown')
                            })

                # Calculate match score
                actual_names = [c['name'].lower() for c in test_result['actual_concepts']]
                expected_lower = [e.lower() for e in test['expected']]
                matches = sum(1 for exp in expected_lower if any(exp in act for act in actual_names))
                test_result['match_score'] = matches / len(test['expected']) if test['expected'] else 0

                all_results.append(test_result)
                domain_results[domain].append(test_result)

                # Print result
                if test_result['match_score'] >= 0.5:
                    print(f" ✅ ({test_result['match_score']:.0%} match)")
                else:
                    print(f" ⚠️  ({test_result['match_score']:.0%} match)")
            else:
                print(f" ❌ Error: {result.error}")

    return all_results, domain_results


def analyze_results(all_results: List[Dict], domain_results: Dict[str, List]) -> Dict[str, Any]:
    """Perform detailed analysis of evaluation results."""
    print("\n\n📈 Detailed Analysis")
    print("=" * 70)

    analysis = {
        'overall_metrics': {},
        'domain_metrics': {},
        'concept_analysis': {},
        'fusion_analysis': {},
        'recommendations': []
    }

    # Overall metrics
    total_tests = len(all_results)
    successful_matches = sum(1 for r in all_results if r['match_score'] >= 0.5)

    analysis['overall_metrics'] = {
        'total_regions_tested': total_tests,
        'successful_matches': successful_matches,
        'success_rate': successful_matches / total_tests if total_tests > 0 else 0,
        'niclip_enabled_rate': sum(1 for r in all_results if r['niclip_enabled']) / total_tests,
        'fusion_enabled_rate': sum(1 for r in all_results if r['fusion_enabled']) / total_tests
    }

    print(f"\n🎯 Overall Performance:")
    print(f"   Success rate: {analysis['overall_metrics']['success_rate']:.1%}")
    print(f"   NiCLIP enabled: {analysis['overall_metrics']['niclip_enabled_rate']:.1%}")
    print(f"   Fusion enabled: {analysis['overall_metrics']['fusion_enabled_rate']:.1%}")

    # Domain-specific analysis
    print(f"\n📊 Domain-Specific Performance:")
    for domain, results in domain_results.items():
        domain_success = sum(1 for r in results if r['match_score'] >= 0.5) / len(results) if results else 0
        avg_match = np.mean([r['match_score'] for r in results]) if results else 0

        analysis['domain_metrics'][domain] = {
            'success_rate': domain_success,
            'avg_match_score': avg_match,
            'n_regions': len(results)
        }

        print(f"   {domain}: {domain_success:.1%} success ({avg_match:.1%} avg match)")

    # Concept frequency analysis
    all_concepts = []
    for result in all_results:
        all_concepts.extend([c['name'] for c in result['actual_concepts']])

    concept_counts = pd.Series(all_concepts).value_counts()
    analysis['concept_analysis'] = {
        'total_unique_concepts': len(concept_counts),
        'top_concepts': concept_counts.head(10).to_dict(),
        'concept_diversity': len(concept_counts) / len(all_concepts) if all_concepts else 0
    }

    print(f"\n🏷️  Concept Analysis:")
    print(f"   Unique concepts: {analysis['concept_analysis']['total_unique_concepts']}")
    print(f"   Concept diversity: {analysis['concept_analysis']['concept_diversity']:.1%}")
    print(f"   Top 5 concepts:")
    for concept, count in list(analysis['concept_analysis']['top_concepts'].items())[:5]:
        print(f"      - {concept}: {count} occurrences")

    # Fusion analysis
    fusion_metrics = []
    for result in all_results:
        if result['fusion_data'] and result['fusion_data'].get('fusion_enabled'):
            metrics = result['fusion_data'].get('fusion_metrics', {})
            if metrics:
                fusion_metrics.append(metrics)

    if fusion_metrics:
        analysis['fusion_analysis'] = {
            'avg_confidence': np.mean([m.get('avg_confidence', 0) for m in fusion_metrics]),
            'avg_conflicts': np.mean([m.get('n_conflicts', 0) for m in fusion_metrics]),
            'avg_overlap': np.mean([m.get('overlap_ratio', 0) for m in fusion_metrics])
        }

        print(f"\n🔀 Fusion Analysis:")
        print(f"   Average confidence: {analysis['fusion_analysis']['avg_confidence']:.1%}")
        print(f"   Average conflicts: {analysis['fusion_analysis']['avg_conflicts']:.1f}")
        print(f"   Average overlap: {analysis['fusion_analysis']['avg_overlap']:.1%}")

    # Generate recommendations
    if analysis['overall_metrics']['success_rate'] < 0.7:
        analysis['recommendations'].append("Improve spatial mapping accuracy - success rate below 70%")

    if analysis['concept_analysis']['concept_diversity'] < 0.3:
        analysis['recommendations'].append("Increase concept diversity - too many repeated concepts")

    if analysis['fusion_analysis'] and analysis['fusion_analysis']['avg_overlap'] < 0.5:
        analysis['recommendations'].append("Improve NiCLIP-LLM alignment - low overlap between sources")

    # Find problematic regions
    problematic = [r for r in all_results if r['match_score'] < 0.3]
    if problematic:
        regions = [f"{r['description']} ({r['domain']})" for r in problematic[:3]]
        analysis['recommendations'].append(f"Focus on improving: {', '.join(regions)}")

    print(f"\n💡 Recommendations:")
    for i, rec in enumerate(analysis['recommendations'], 1):
        print(f"   {i}. {rec}")

    return analysis


def create_visualization_report(all_results: List[Dict], domain_results: Dict[str, List], analysis: Dict, output_dir: Path):
    """Create comprehensive visualization report."""
    print("\n\n📊 Creating Visualization Report...")

    # Set up the plot style
    plt.style.use('seaborn-v0_8-darkgrid')
    fig = plt.figure(figsize=(16, 12))

    # 1. Domain performance heatmap
    ax1 = plt.subplot(2, 3, 1)
    domain_scores = {domain: analysis['domain_metrics'][domain]['success_rate']
                     for domain in analysis['domain_metrics']}
    domains = list(domain_scores.keys())
    scores = list(domain_scores.values())

    colors = ['#2ecc71' if s >= 0.7 else '#f39c12' if s >= 0.5 else '#e74c3c' for s in scores]
    bars = ax1.barh(domains, scores, color=colors)
    ax1.set_xlabel('Success Rate')
    ax1.set_title('Performance by Cognitive Domain')
    ax1.set_xlim(0, 1)

    # Add value labels
    for bar, score in zip(bars, scores):
        ax1.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
                f'{score:.0%}', va='center')

    # 2. Concept frequency distribution
    ax2 = plt.subplot(2, 3, 2)
    top_concepts = analysis['concept_analysis']['top_concepts']
    concepts = list(top_concepts.keys())[:10]
    counts = list(top_concepts.values())[:10]

    ax2.bar(range(len(concepts)), counts, color='#3498db')
    ax2.set_xticks(range(len(concepts)))
    ax2.set_xticklabels(concepts, rotation=45, ha='right')
    ax2.set_ylabel('Frequency')
    ax2.set_title('Top 10 Most Frequent Concepts')

    # 3. Match score distribution
    ax3 = plt.subplot(2, 3, 3)
    match_scores = [r['match_score'] for r in all_results]
    ax3.hist(match_scores, bins=20, color='#9b59b6', alpha=0.7, edgecolor='black')
    ax3.axvline(x=0.5, color='red', linestyle='--', label='Success threshold')
    ax3.set_xlabel('Match Score')
    ax3.set_ylabel('Number of Regions')
    ax3.set_title('Distribution of Match Scores')
    ax3.legend()

    # 4. Brain region success map (simplified 2D projection)
    ax4 = plt.subplot(2, 3, 4)
    x_coords = []
    y_coords = []
    colors_map = []

    for result in all_results:
        # Average coordinates for plotting
        avg_coord = np.mean(result['coordinates'], axis=0)
        x_coords.append(avg_coord[0])  # x coordinate
        y_coords.append(avg_coord[2])  # z coordinate (for top view)
        colors_map.append(result['match_score'])

    scatter = ax4.scatter(x_coords, y_coords, c=colors_map, cmap='RdYlGn',
                         s=100, alpha=0.7, edgecolors='black')
    ax4.set_xlabel('X coordinate (mm)')
    ax4.set_ylabel('Z coordinate (mm)')
    ax4.set_title('Brain Region Performance Map (Top View)')
    plt.colorbar(scatter, ax=ax4, label='Match Score')

    # 5. Fusion metrics (if available)
    ax5 = plt.subplot(2, 3, 5)
    if analysis['fusion_analysis']:
        metrics = ['Confidence', 'Overlap', 'Conflicts']
        values = [
            analysis['fusion_analysis']['avg_confidence'],
            analysis['fusion_analysis']['avg_overlap'],
            1 - (analysis['fusion_analysis']['avg_conflicts'] / 5)  # Normalize conflicts
        ]

        ax5.bar(metrics, values, color=['#3498db', '#2ecc71', '#e74c3c'])
        ax5.set_ylim(0, 1)
        ax5.set_ylabel('Score')
        ax5.set_title('Fusion System Metrics')

        # Add value labels
        for i, (metric, value) in enumerate(zip(metrics, values)):
            ax5.text(i, value + 0.02, f'{value:.2f}', ha='center')
    else:
        ax5.text(0.5, 0.5, 'No fusion data available', ha='center', va='center',
                transform=ax5.transAxes, fontsize=12)
        ax5.set_title('Fusion System Metrics')

    # 6. Performance summary text
    ax6 = plt.subplot(2, 3, 6)
    ax6.axis('off')

    summary_text = f"""
Performance Summary

Overall Success Rate: {analysis['overall_metrics']['success_rate']:.1%}
Regions Tested: {analysis['overall_metrics']['total_regions_tested']}
Successful Matches: {analysis['overall_metrics']['successful_matches']}

Best Performing Domain:
{max(analysis['domain_metrics'].items(), key=lambda x: x[1]['success_rate'])[0]}
({max(d['success_rate'] for d in analysis['domain_metrics'].values()):.1%})

Worst Performing Domain:
{min(analysis['domain_metrics'].items(), key=lambda x: x[1]['success_rate'])[0]}
({min(d['success_rate'] for d in analysis['domain_metrics'].values()):.1%})

Key Recommendations:
"""

    for i, rec in enumerate(analysis['recommendations'][:3], 1):
        summary_text += f"\n{i}. {rec[:40]}..."

    ax6.text(0.1, 0.9, summary_text, transform=ax6.transAxes,
             fontsize=10, verticalalignment='top', fontfamily='monospace')

    plt.suptitle('NiCLIP-LLM Fusion System Evaluation Report', fontsize=16, y=0.98)
    plt.tight_layout()

    # Save the figure
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plot_path = output_dir / f"evaluation_report_{timestamp}.png"
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"   ✅ Visualization saved to: {plot_path}")

    # Also save detailed results as CSV
    results_df = pd.DataFrame(all_results)
    csv_path = output_dir / f"evaluation_results_{timestamp}.csv"
    results_df.to_csv(csv_path, index=False)
    print(f"   ✅ Detailed results saved to: {csv_path}")


def save_evaluation_report(all_results: List[Dict], analysis: Dict, output_dir: Path):
    """Save comprehensive evaluation report as JSON."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        'timestamp': timestamp,
        'summary': {
            'total_regions_tested': len(all_results),
            'overall_success_rate': analysis['overall_metrics']['success_rate'],
            'key_findings': analysis['recommendations']
        },
        'domain_performance': analysis['domain_metrics'],
        'concept_analysis': analysis['concept_analysis'],
        'fusion_analysis': analysis['fusion_analysis'],
        'detailed_results': all_results
    }

    report_path = output_dir / f"evaluation_report_{timestamp}.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"   ✅ Full report saved to: {report_path}")

    return report_path


def main():
    """Run the comprehensive evaluation."""
    # Setup output directory
    output_dir = Path("comprehensive_evaluation")
    output_dir.mkdir(exist_ok=True)

    print("🚀 Starting Comprehensive NiCLIP-LLM Fusion Evaluation")
    print("=" * 70)
    print(f"Output directory: {output_dir}")

    # Run test suite
    all_results, domain_results = run_comprehensive_test_suite()

    # Analyze results
    analysis = analyze_results(all_results, domain_results)

    # Create visualizations
    create_visualization_report(all_results, domain_results, analysis, output_dir)

    # Save detailed report
    report_path = save_evaluation_report(all_results, analysis, output_dir)

    # Print final summary
    print("\n\n" + "=" * 70)
    print("✅ Comprehensive Evaluation Complete!")
    print("=" * 70)
    print(f"\n📊 Final Results:")
    print(f"   Overall Success Rate: {analysis['overall_metrics']['success_rate']:.1%}")
    print(f"   Regions Tested: {analysis['overall_metrics']['total_regions_tested']}")
    print(f"   Unique Concepts Found: {analysis['concept_analysis']['total_unique_concepts']}")

    print(f"\n📁 Output Files:")
    print(f"   - Visualization: {output_dir}/evaluation_report_*.png")
    print(f"   - Detailed CSV: {output_dir}/evaluation_results_*.csv")
    print(f"   - Full Report: {report_path}")

    print(f"\n🎯 Next Steps:")
    for i, rec in enumerate(analysis['recommendations'], 1):
        print(f"   {i}. {rec}")


if __name__ == "__main__":
    main()