"""Legacy demonstration of enhanced agent service features."""

import asyncio
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brain_researcher.services.agent.enhanced_integration import (
    EnhancedAgentOrchestrator, create_enhanced_agent_orchestrator
)
from brain_researcher.services.tools.enhanced_registry import EnhancedToolRegistry
from brain_researcher.services.agent.workflow_composer import WorkflowPattern
from brain_researcher.services.agent.enhanced_evidence import EvidenceType, ConfidenceLevel

logger = logging.getLogger(__name__)


class EnhancedAgentDemo:
    """Demonstration class for enhanced agent features."""

    def __init__(self):
        """Initialize the demonstration system."""
        self.orchestrator = create_enhanced_agent_orchestrator(
            enable_workflow_composition=True,
            enable_advanced_evidence=True,
            enable_error_recovery=True,
            evidence_storage_path=Path("/tmp/demo_evidence")
        )

        logger.info("Enhanced agent demo initialized")

    async def demo_parameter_inference(self) -> Dict[str, Any]:
        """Demonstrate intelligent parameter inference."""
        print("\n=== Parameter Inference Demo ===")

        # Get tool recommendations with parameter inference
        query = "Perform a GLM analysis with conservative statistical thresholds"

        recommendations = self.orchestrator.enhanced_registry.get_intelligent_recommendations(
            query=query,
            context={'data_type': 'fmri', 'analysis_stage': 'statistical'},
            user_preferences={'conservative_analysis': True},
            max_recommendations=3
        )

        print(f"Query: {query}")
        print(f"Found {len(recommendations)} tool recommendations:")

        for i, rec in enumerate(recommendations):
            print(f"\n{i+1}. Tool: {rec.tool.get_tool_name()}")
            print(f"   Confidence: {rec.confidence_score:.3f}")
            print(f"   Estimated time: {rec.estimated_execution_time:.1f}s")
            print(f"   Match reasons: {', '.join(rec.match_reasons)}")
            print(f"   Suggested parameters: {rec.parameter_suggestions}")

        return {
            'query': query,
            'recommendations_count': len(recommendations),
            'top_tool': recommendations[0].tool.get_tool_name() if recommendations else None,
            'top_confidence': recommendations[0].confidence_score if recommendations else 0
        }

    async def demo_workflow_composition(self) -> Dict[str, Any]:
        """Demonstrate automatic workflow composition."""
        print("\n=== Workflow Composition Demo ===")

        query = "I want to preprocess fMRI data and then run a task activation analysis"

        if self.orchestrator.workflow_composer:
            # Compose workflow
            workflow = self.orchestrator.workflow_composer.compose_workflow(
                intent=query,
                context={'data_type': 'fmri'},
                pattern=WorkflowPattern.PREPROCESSING_TO_ANALYSIS
            )

            print(f"Query: {query}")
            print(f"Composed workflow: {workflow.name}")
            print(f"Pattern: {workflow.pattern.value}")
            print(f"Steps: {len(workflow.steps)}")
            print(f"Estimated duration: {workflow.get_total_estimated_duration():.1f}s")

            print("\nWorkflow steps:")
            for i, step in enumerate(workflow.steps):
                print(f"  {i+1}. {step.tool_name}")
                print(f"     Description: {step.tool.get_tool_description()[:100]}...")
                print(f"     Dependencies: {step.dependencies}")
                print(f"     Parameters: {list(step.parameters.keys())}")

            return {
                'workflow_created': True,
                'workflow_id': workflow.pipeline_id,
                'step_count': len(workflow.steps),
                'estimated_duration': workflow.get_total_estimated_duration()
            }
        else:
            print("Workflow composer not available")
            return {'workflow_created': False}

    async def demo_evidence_collection(self) -> Dict[str, Any]:
        """Demonstrate advanced evidence collection and aggregation."""
        print("\n=== Evidence Collection Demo ===")

        # Create evidence collector
        from brain_researcher.services.agent.enhanced_evidence import EnhancedEvidenceCollector

        collector = EnhancedEvidenceCollector(
            storage_path=Path("/tmp/demo_evidence"),
            track_parameters=True,
            track_files=True
        )

        # Collect various types of evidence
        collector.start_chain("Demo analysis workflow")

        # Dataset evidence
        dataset_evidence = collector.collect_dataset(
            dataset_id="ds000114",
            name="Flanker Task Dataset",
            source="OpenNeuro",
            doi="10.18112/openneuro.ds000114.v1.0.1"
        )

        # Tool execution evidence
        tool_evidence = collector.collect_tool_execution(
            tool_name="fmriprep",
            version="23.1.4",
            parameters={'n_cpus': 4, 'mem_gb': 16},
            execution_time=1800.0,
            success=True
        )

        # Analysis results evidence
        result_evidence = collector.collect(
            type=EvidenceType.RESULT,
            source="glm_analysis",
            content={
                'significant_voxels': 1250,
                'peak_t_value': 8.45,
                'peak_coordinates': [-42, -22, 48],
                'corrected_p_value': 0.001
            },
            confidence=ConfidenceLevel.HIGH
        )

        collector.end_chain()

        # Aggregate evidence
        aggregation = collector.aggregate_related_evidence(
            evidence_type=EvidenceType.RESULT,
            method='consensus'
        )

        # Get quality metrics
        quality_score = collector.get_evidence_quality_score()

        # Generate visualizations
        timeline = collector.visualization_api.create_evidence_timeline()
        network = collector.visualization_api.create_evidence_network()

        print(f"Evidence collected:")
        print(f"  - Dataset: {dataset_evidence.evidence_id}")
        print(f"  - Tool execution: {tool_evidence.evidence_id}")
        print(f"  - Analysis result: {result_evidence.evidence_id}")

        if aggregation:
            print(f"  - Aggregation: {aggregation.aggregation_id}")
            print(f"    Confidence: {aggregation.confidence_score:.3f}")
            print(f"    Consensus: {aggregation.consensus_level:.3f}")

        print(f"Evidence quality score: {quality_score['quality_score']:.3f}")
        print(f"Timeline events: {len(timeline['timeline'])}")
        print(f"Network nodes: {len(network['nodes'])}")

        return {
            'evidence_collected': len(collector.evidence),
            'quality_score': quality_score['quality_score'],
            'aggregation_created': aggregation is not None,
            'visualization_data_available': True
        }

    async def demo_error_recovery(self) -> Dict[str, Any]:
        """Demonstrate intelligent error recovery."""
        print("\n=== Error Recovery Demo ===")

        if not self.orchestrator.error_recovery_system:
            print("Error recovery system not available")
            return {'recovery_system_available': False}

        # Simulate an error scenario
        simulated_error = Exception("Out of memory: Cannot allocate 32GB for fMRIPrep processing")

        error_context = {
            'tool_name': 'fmriprep',
            'parameters': {'n_cpus': 8, 'mem_gb': 32},
            'execution_time': 3600,
            'memory_usage': 0.95
        }

        # Analyze the error pattern
        error_analyzer = self.orchestrator.error_recovery_system.error_analyzer
        error_pattern, confidence = error_analyzer.analyze_error(
            str(simulated_error), error_context
        )

        print(f"Simulated error: {simulated_error}")
        print(f"Detected pattern: {error_pattern.value}")
        print(f"Detection confidence: {confidence:.3f}")

        # Get recovery strategies
        strategies = error_analyzer.get_recovery_strategies(error_pattern)
        print(f"Recommended strategies: {[s.value for s in strategies]}")

        # Get parameter adjustments
        adjusted_params = error_analyzer.suggest_parameter_adjustments(
            error_pattern, error_context.get('parameters', {})
        )
        print(f"Suggested parameter adjustments: {adjusted_params}")

        # Find fallback tools
        fallback_selector = self.orchestrator.error_recovery_system.fallback_selector
        fallback_tools = fallback_selector.find_fallback_tools(
            'fmriprep',
            context=error_context
        )

        print(f"Fallback tools: {[(name, f'{score:.3f}') for name, score in fallback_tools[:3]]}")

        return {
            'recovery_system_available': True,
            'error_pattern_detected': error_pattern.value,
            'detection_confidence': confidence,
            'strategies_available': len(strategies),
            'fallback_tools_found': len(fallback_tools),
            'parameter_adjustments': len(adjusted_params)
        }

    async def demo_comprehensive_query_processing(self) -> Dict[str, Any]:
        """Demonstrate comprehensive query processing with all features."""
        print("\n=== Comprehensive Query Processing Demo ===")

        query = "Analyze task-related activation in the flanker task dataset with quality control"

        print(f"Processing query: {query}")
        print("This demonstrates the full enhanced pipeline...")

        # Note: This would normally execute the full pipeline, but for demo
        # we'll simulate the major steps and show what would happen

        result = await self.orchestrator.process_query(
            query=query,
            user_preferences={
                'conservative_analysis': True,
                'quality_control': True
            },
            execution_options={
                'enable_parallel_execution': True,
                'max_recovery_attempts': 3
            }
        )

        print(f"\nQuery processing completed:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Session ID: {result.get('session_id', 'N/A')}")
        print(f"  Execution time: {result.get('execution_time', 0):.2f}s")
        print(f"  Tools executed: {len(result.get('successful_tools', []))}")
        print(f"  Workflow used: {result.get('workflow_used', False)}")
        print(f"  Evidence collected: {result.get('evidence_summary', {}).get('total_evidence', 0)}")
        print(f"  Quality score: {result.get('quality_metrics', {}).get('quality_score', 0):.3f}")

        if result.get('evidence_export_path'):
            print(f"  Evidence report: {result['evidence_export_path']}")

        return result

    def demo_system_status(self) -> Dict[str, Any]:
        """Demonstrate system status and monitoring."""
        print("\n=== System Status Demo ===")

        status = self.orchestrator.get_system_status()

        print("System Status:")
        print(f"  Active sessions: {status.get('active_sessions', 0)}")
        print(f"  Total sessions: {status.get('total_sessions_processed', 0)}")
        print(f"  Success rate: {status.get('performance_metrics', {}).get('success_rate', 0):.3f}")
        print(f"  Average response time: {status.get('performance_metrics', {}).get('average_response_time', 0):.2f}s")

        features = status.get('enhanced_features', {})
        print(f"\nEnhanced Features:")
        print(f"  Workflow composition: {features.get('workflow_composition', False)}")
        print(f"  Error recovery: {features.get('error_recovery', False)}")
        print(f"  Advanced evidence: {features.get('advanced_evidence', False)}")

        tool_stats = status.get('tool_registry_stats', {})
        if 'n_tools' in tool_stats:
            print(f"\nTool Registry:")
            print(f"  Total tools: {tool_stats['n_tools']}")

        return status

    async def run_all_demos(self) -> Dict[str, Any]:
        """Run all demonstration scenarios."""
        print("=== Brain Researcher Enhanced Agent Features Demo ===")

        results = {}

        # Run individual demos
        results['parameter_inference'] = await self.demo_parameter_inference()
        results['workflow_composition'] = await self.demo_workflow_composition()
        results['evidence_collection'] = await self.demo_evidence_collection()
        results['error_recovery'] = await self.demo_error_recovery()
        results['system_status'] = self.demo_system_status()

        # Run comprehensive demo
        try:
            results['comprehensive_processing'] = await self.demo_comprehensive_query_processing()
        except Exception as e:
            print(f"Comprehensive demo error: {e}")
            results['comprehensive_processing'] = {'error': str(e)}

        print("\n=== Demo Summary ===")
        print(f"Parameter inference: {'✓' if results['parameter_inference'].get('recommendations_count', 0) > 0 else '✗'}")
        print(f"Workflow composition: {'✓' if results['workflow_composition'].get('workflow_created', False) else '✗'}")
        print(f"Evidence collection: {'✓' if results['evidence_collection'].get('evidence_collected', 0) > 0 else '✗'}")
        print(f"Error recovery: {'✓' if results['error_recovery'].get('recovery_system_available', False) else '✗'}")
        print(f"Comprehensive processing: {'✓' if results['comprehensive_processing'].get('success', False) else '✗'}")

        return results


async def main():
    """Main demonstration function."""
    demo = EnhancedAgentDemo()
    results = await demo.run_all_demos()

    # Save results to file for inspection
    with open('/tmp/enhanced_agent_demo_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nDemo results saved to: /tmp/enhanced_agent_demo_results.json")
    return results


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)

    # Run the demo
    asyncio.run(main())
