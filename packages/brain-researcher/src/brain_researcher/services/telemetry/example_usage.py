"""
Example usage and testing scenarios for TELEMETRY-003 Usage Metrics Tracking System.

This script demonstrates how to use the telemetry system across different services
and provides test scenarios for validation.
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

from .collector import TelemetryCollector
from .aggregator import UsageMetricsAggregator, AggregationWindow, AggregationConfig
from .privacy import PrivacyController
from .integrations import create_agent_telemetry, create_neurokg_telemetry, create_ui_telemetry
from .models import TelemetryConfiguration, EventType, ServiceType, PrivacyLevel


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TelemetryDemo:
    """
    Comprehensive demo of the telemetry system with realistic usage scenarios.
    """
    
    def __init__(self):
        self.config = TelemetryConfiguration(
            collection_enabled=True,
            sampling_rate=1.0,
            batch_size=20,
            flush_interval_seconds=10,
            anonymization_enabled=True,
            gdpr_compliance_mode=True,
            debug_mode=True
        )
        
        # Initialize core components
        self.collector = TelemetryCollector(self.config)
        self.aggregator = UsageMetricsAggregator(AggregationConfig())
        self.privacy_controller = PrivacyController(self.config)
        
        # Connect collector to aggregator
        self.collector.add_processing_handler(self.aggregator.add_events)
        
        # Initialize service integrations
        self.agent_telemetry = create_agent_telemetry(self.config)
        self.neurokg_telemetry = create_neurokg_telemetry(self.config)
        self.ui_telemetry = create_ui_telemetry(self.config)
        
        logger.info("TelemetryDemo initialized")
    
    async def run_comprehensive_demo(self):
        """Run a comprehensive demonstration of all telemetry features."""
        logger.info("Starting comprehensive telemetry demo...")
        
        # Start the collector
        await self.collector.start()
        
        try:
            # Demo scenarios
            await self.demo_basic_event_collection()
            await self.demo_service_integrations()
            await self.demo_user_journeys()
            await self.demo_privacy_features()
            await self.demo_metrics_aggregation()
            await self.demo_real_time_monitoring()
            
            # Generate summary report
            await self.generate_demo_report()
            
        finally:
            # Clean shutdown
            await self.collector.stop()
        
        logger.info("Demo completed successfully!")
    
    async def demo_basic_event_collection(self):
        """Demonstrate basic event collection."""
        logger.info("Demo 1: Basic Event Collection")
        
        # Simulate various event types
        events_to_collect = [
            {
                'event_type': EventType.TOOL_INVOCATION,
                'service': ServiceType.AGENT,
                'feature_name': 'fmri_glm_analysis',
                'action': 'execute',
                'user_id': 'user_001',
                'duration_ms': 15000,
                'success': True
            },
            {
                'event_type': EventType.PAGE_VIEW,
                'service': ServiceType.WEB_UI,
                'feature_name': 'dashboard',
                'action': 'view',
                'user_id': 'user_002',
                'context': {'page_path': '/dashboard/analytics'}
            },
            {
                'event_type': EventType.SEARCH_QUERY,
                'service': ServiceType.NEUROKG,
                'feature_name': 'knowledge_search',
                'action': 'query',
                'user_id': 'user_001',
                'parameters': {'query_type': 'semantic', 'results_limit': 50},
                'duration_ms': 250
            },
            {
                'event_type': EventType.TOOL_ERROR,
                'service': ServiceType.AGENT,
                'feature_name': 'data_preprocessing',
                'action': 'preprocess',
                'user_id': 'user_003',
                'success': False,
                'error_message': 'Invalid BIDS dataset format',
                'privacy_level': PrivacyLevel.INTERNAL_ONLY
            }
        ]
        
        for event_data in events_to_collect:
            event_id = self.collector.collect(**event_data)
            if event_id:
                logger.info(f"Collected event: {event_id}")
        
        # Wait for processing
        await asyncio.sleep(2)
        stats = self.collector.get_stats()
        logger.info(f"Collection stats: {stats}")
    
    async def demo_service_integrations(self):
        """Demonstrate service-specific integrations."""
        logger.info("Demo 2: Service Integrations")
        
        # Agent service integration
        logger.info("Agent Service Integration:")
        self.agent_telemetry.set_user_context('researcher_001', 'session_123')
        
        # Track tool execution
        await self.simulate_agent_workflow()
        
        # BR-KG service integration
        logger.info("BR-KG Service Integration:")
        self.neurokg_telemetry.set_user_context('researcher_001', 'session_123')
        
        # Track graph operations
        await self.simulate_neurokg_operations()
        
        # UI service integration
        logger.info("UI Service Integration:")
        self.ui_telemetry.set_user_context('researcher_001', 'session_123')
        
        # Track UI interactions
        await self.simulate_ui_interactions()
        
        await asyncio.sleep(1)
        logger.info("Service integration demo completed")
    
    async def simulate_agent_workflow(self):
        """Simulate a realistic agent workflow."""
        workflow_steps = [
            ('data_loader', 'load_dataset', {'dataset': 'ds000114', 'subjects': 20}),
            ('preprocessing', 'fmriprep_runner', {'pipeline': 'standard', 'output_space': 'MNI152'}),
            ('quality_check', 'motion_assessment', {'fd_threshold': 0.5}),
            ('analysis', 'first_level_glm', {'model_type': 'canonical_hrf'}),
            ('statistics', 'group_analysis', {'n_subjects': 18, 'contrasts': 3}),
            ('visualization', 'brain_plot', {'map_type': 'statistical', 'threshold': 0.001})
        ]
        
        for i, (category, tool_name, params) in enumerate(workflow_steps):
            # Simulate processing time
            processing_time = random.randint(5000, 30000)
            await asyncio.sleep(0.1)  # Simulate work
            
            # Track tool execution
            success = random.random() > 0.1  # 90% success rate
            error_msg = None if success else f"Processing error in {tool_name}"
            
            self.agent_telemetry.track_tool_execution(
                tool_name=tool_name,
                input_params=params,
                output_artifacts=[f"artifact_{i}.nii.gz", f"log_{i}.txt"] if success else [],
                execution_time_ms=processing_time,
                success=success,
                error_message=error_msg
            )
            
            # Track workflow step
            self.agent_telemetry.track_workflow_step(
                workflow_id="research_workflow_001",
                step_name=tool_name,
                step_index=i,
                success=success
            )
    
    async def simulate_neurokg_operations(self):
        """Simulate BR-KG database operations."""
        operations = [
            ('concept_search', 'complex', 150, 1200),
            ('relationship_query', 'simple', 45, 300),
            ('data_ingestion', 'medium', 1000, 8000),
            ('knowledge_discovery', 'complex', 200, 15000),
            ('graph_traversal', 'medium', 75, 2000)
        ]
        
        for op_type, complexity, result_count, duration in operations:
            await asyncio.sleep(0.05)  # Simulate work
            
            success = random.random() > 0.05  # 95% success rate
            
            if op_type == 'data_ingestion':
                self.neurokg_telemetry.track_data_ingestion(
                    data_source='pubmed_abstracts',
                    record_count=result_count,
                    processing_time_ms=duration,
                    success=success,
                    errors_encountered=0 if success else random.randint(1, 5)
                )
            elif op_type == 'knowledge_discovery':
                self.neurokg_telemetry.track_knowledge_discovery(
                    discovery_type='concept_relationships',
                    entities_analyzed=result_count,
                    relationships_found=result_count // 4,
                    confidence_score=random.uniform(0.6, 0.95)
                )
            else:
                self.neurokg_telemetry.track_graph_query(
                    query_type=op_type,
                    query_complexity=complexity,
                    results_count=result_count,
                    execution_time_ms=duration,
                    success=success
                )
    
    async def simulate_ui_interactions(self):
        """Simulate UI user interactions."""
        interactions = [
            ('navigation_header', 'menu_click', {'menu_item': 'analytics'}),
            ('search_autocomplete', 'search', {'query_length': 15, 'suggestions_shown': 8}),
            ('filter_sidebar', 'filter_apply', {'filters': ['modality:fmri', 'subjects:>10']}),
            ('dataset_card', 'view_details', {'dataset_id': 'ds000114'}),
            ('analysis_form', 'submit', {'analysis_type': 'glm', 'parameters': 12}),
            ('result_display', 'download', {'artifact_type': 'statistical_map'}),
            ('dashboard', 'widget_interact', {'widget_type': 'metrics_overview'})
        ]
        
        for component, action, metadata in interactions:
            await asyncio.sleep(0.02)  # Simulate user thinking time
            
            self.ui_telemetry.track_component_interaction(
                component_name=component,
                interaction_type=action,
                additional_data=metadata
            )
            
            # Simulate page navigation
            if action == 'menu_click':
                self.ui_telemetry.track_page_view(
                    f"/{metadata['menu_item']}",
                    referrer="/dashboard"
                )
    
    async def demo_user_journeys(self):
        """Demonstrate user journey tracking."""
        logger.info("Demo 3: User Journey Tracking")
        
        # Simulate multiple user journeys
        journeys = [
            self.simulate_research_journey,
            self.simulate_exploratory_journey,
            self.simulate_collaboration_journey
        ]
        
        for journey in journeys:
            await journey()
            await asyncio.sleep(0.5)
        
        # Extract and analyze journeys
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        window = AggregationWindow(start_time, end_time, "hour")
        
        journeys = await self.aggregator.extract_user_journeys(window=window)
        logger.info(f"Extracted {len(journeys)} user journeys")
        
        for journey in journeys[:3]:
            logger.info(f"Journey {journey.journey_id}: {journey.total_steps} steps, "
                       f"{journey.completion_rate:.1%} completion rate")
    
    async def simulate_research_journey(self):
        """Simulate a complete research workflow journey."""
        user_id = 'researcher_001'
        session_id = f"research_session_{int(time.time())}"
        
        with self.agent_telemetry.user_context(user_id, session_id):
            # Research workflow steps
            steps = [
                ('session_start', {}),
                ('dataset_search', {'query': 'motor cortex fmri'}),
                ('dataset_selection', {'dataset_id': 'ds000114'}),
                ('analysis_configuration', {'analysis_type': 'glm'}),
                ('analysis_execution', {'duration_ms': 45000}),
                ('results_review', {'artifacts_generated': 5}),
                ('results_export', {'format': 'nifti'}),
                ('session_end', {})
            ]
            
            for step_name, context in steps:
                await asyncio.sleep(0.1)
                
                self.collector.collect(
                    event_type=EventType.FEATURE_ACCESS,
                    service=ServiceType.WEB_UI,
                    feature_name='research_workflow',
                    action=step_name,
                    user_id=user_id,
                    session_id=session_id,
                    context=context,
                    success=True
                )
    
    async def simulate_exploratory_journey(self):
        """Simulate an exploratory data analysis journey."""
        user_id = 'explorer_002'
        session_id = f"explore_session_{int(time.time())}"
        
        with self.ui_telemetry.user_context(user_id, session_id):
            # Exploratory steps
            exploration_actions = [
                'browse_datasets',
                'view_dataset_details',
                'preview_data',
                'compare_datasets',
                'bookmark_interesting',
                'share_findings'
            ]
            
            for action in exploration_actions:
                await asyncio.sleep(0.05)
                
                self.ui_telemetry.track_feature_usage(
                    feature_name='data_explorer',
                    action=action,
                    context={'exploration_type': 'comparative'}
                )
    
    async def simulate_collaboration_journey(self):
        """Simulate a collaboration workflow."""
        user_id = 'collaborator_003'
        session_id = f"collab_session_{int(time.time())}"
        
        collaboration_steps = [
            ('project_access', ServiceType.WEB_UI),
            ('analysis_review', ServiceType.AGENT),
            ('comment_creation', ServiceType.WEB_UI),
            ('result_discussion', ServiceType.WEB_UI),
            ('revision_suggestion', ServiceType.AGENT)
        ]
        
        for step_name, service in collaboration_steps:
            await asyncio.sleep(0.1)
            
            self.collector.collect(
                event_type=EventType.COLLABORATION_ACTION,
                service=service,
                feature_name='collaboration',
                action=step_name,
                user_id=user_id,
                session_id=session_id,
                success=True
            )
    
    async def demo_privacy_features(self):
        """Demonstrate privacy controls and compliance."""
        logger.info("Demo 4: Privacy and Compliance Features")
        
        # Create test events with PII
        test_events = [
            {
                'event_type': EventType.TOOL_INVOCATION,
                'service': ServiceType.AGENT,
                'feature_name': 'data_analysis',
                'user_id': 'john.doe@university.edu',  # PII - email
                'context': {
                    'researcher_name': 'John Doe',  # PII - name
                    'ip_address': '192.168.1.100',  # PII - IP
                    'institution': 'University Research Lab'
                },
                'metadata': {
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',  # PII
                    'session_token': 'abc123def456'
                }
            }
        ]
        
        # Process events through privacy controller
        processed_events = []
        for event_data in test_events:
            # Create event
            event = self.collector._create_event(**event_data)
            
            # Apply privacy controls
            anonymized_event = self.privacy_controller.anonymize_event(event)
            processed_events.append(anonymized_event)
            
            logger.info(f"Original event user_id: {event_data.get('user_id')}")
            logger.info(f"Anonymized user_id: {anonymized_event.user_id}")
        
        # Validate compliance
        for event in processed_events:
            is_compliant, violations = self.privacy_controller.validate_data_compliance(event)
            logger.info(f"Event compliance: {is_compliant}, violations: {violations}")
        
        # Get privacy summary
        privacy_summary = self.privacy_controller.get_privacy_summary(processed_events)
        logger.info(f"Privacy summary: {privacy_summary}")
    
    async def demo_metrics_aggregation(self):
        """Demonstrate metrics aggregation capabilities."""
        logger.info("Demo 5: Metrics Aggregation")
        
        # Wait for events to be processed
        await asyncio.sleep(2)
        
        # Calculate usage metrics
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        window = AggregationWindow(start_time, end_time, "hour")
        
        metrics = await self.aggregator.calculate_usage_metrics(window=window)
        logger.info(f"Generated {len(metrics)} usage metrics")
        
        # Show sample metrics
        for metric in metrics[:5]:
            logger.info(f"Metric: {metric.name} = {metric.value:.2f} {metric.unit}")
        
        # Analyze feature usage
        feature_analysis = await self.aggregator.analyze_feature_usage(window=window)
        logger.info(f"Analyzed {len(feature_analysis)} features")
        
        # Show top features
        for feature in feature_analysis[:3]:
            logger.info(f"Feature: {feature.feature_name}, "
                       f"Usage: {feature.total_uses}, "
                       f"Adoption: {feature.adoption_rate:.1%}")
    
    async def demo_real_time_monitoring(self):
        """Demonstrate real-time monitoring capabilities."""
        logger.info("Demo 6: Real-time Monitoring")
        
        # Get real-time metrics
        real_time_metrics = await self.aggregator.get_real_time_metrics()
        logger.info("Real-time metrics:")
        for key, value in real_time_metrics.items():
            if not isinstance(value, dict):
                logger.info(f"  {key}: {value}")
        
        # Get system health
        collector_stats = self.collector.get_stats()
        aggregator_stats = self.aggregator.get_aggregator_stats()
        
        logger.info(f"Collector stats: {collector_stats}")
        logger.info(f"Aggregator stats: {aggregator_stats}")
    
    async def generate_demo_report(self):
        """Generate a comprehensive demo report."""
        logger.info("Generating Demo Report")
        
        report = {
            'demo_completed_at': datetime.utcnow().isoformat(),
            'collector_stats': self.collector.get_stats(),
            'aggregator_stats': self.aggregator.get_aggregator_stats(),
            'privacy_audit_count': len(self.privacy_controller._audit_logs),
            'configuration': {
                'collection_enabled': self.config.collection_enabled,
                'anonymization_enabled': self.config.anonymization_enabled,
                'gdpr_compliance': self.config.gdpr_compliance_mode,
                'sampling_rate': self.config.sampling_rate
            }
        }
        
        logger.info("=== TELEMETRY DEMO REPORT ===")
        for section, data in report.items():
            logger.info(f"{section.upper()}: {data}")
        
        return report


async def run_telemetry_demo():
    """Main demo runner function."""
    demo = TelemetryDemo()
    await demo.run_comprehensive_demo()


def run_demo():
    """Synchronous wrapper for the demo."""
    asyncio.run(run_telemetry_demo())


if __name__ == "__main__":
    # Run the comprehensive demo
    print("Starting TELEMETRY-003 Usage Metrics System Demo...")
    print("This demo will showcase all telemetry features including:")
    print("- Event collection and processing")
    print("- Service integrations")
    print("- User journey tracking") 
    print("- Privacy controls and compliance")
    print("- Metrics aggregation")
    print("- Real-time monitoring")
    print()
    
    try:
        run_demo()
        print("\n✅ Demo completed successfully!")
        print("Check the logs above for detailed telemetry system demonstration.")
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        raise
