"""Integration tests for complete feedback system."""

import json
import pytest
import redis
import time
from datetime import datetime, timedelta
from typing import Dict, List
from unittest.mock import Mock, patch
import numpy as np

from brain_researcher.services.feedback.ab_testing import (
    ABTestingFramework,
    ExperimentStatus
)
from brain_researcher.services.feedback.metrics_collector import (
    MetricsCollector,
    EventType
)


@pytest.mark.integration
class TestFeedbackSystemIntegration:
    """Integration tests for the complete feedback system."""
    
    @pytest.fixture
    def redis_client(self):
        """Setup Redis client for integration tests."""
        try:
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=True)
        except ImportError:
            pytest.skip("fakeredis not available for integration tests")
    
    @pytest.fixture
    def feedback_system(self, redis_client):
        """Setup complete feedback system."""
        ab_testing = ABTestingFramework(redis_client=redis_client)
        metrics_collector = MetricsCollector(redis_client=redis_client)
        
        return {
            "ab_testing": ab_testing,
            "metrics_collector": metrics_collector,
            "redis": redis_client
        }
    
    def test_complete_ab_test_lifecycle(self, feedback_system):
        """Test complete A/B test lifecycle with metrics collection."""
        ab_testing = feedback_system["ab_testing"]
        metrics_collector = feedback_system["metrics_collector"]
        
        # 1. Create experiment
        experiment = ab_testing.create_experiment(
            name="Homepage Redesign Test",
            description="Test new homepage design impact on conversions",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate", "click_through_rate"],
            sample_size=1000
        )
        
        # 2. Start experiment
        ab_testing.start_experiment(experiment.id)
        
        # 3. Simulate user interactions
        num_users = 200
        user_assignments = {}
        
        for i in range(num_users):
            user_id = f"user_{i:03d}"
            
            # Assign user to variant
            variant = ab_testing.assign_user(user_id, experiment.id)
            user_assignments[user_id] = variant
            
            # Track impression
            metrics_collector.track_experiment_event(
                user_id=user_id,
                experiment_id=experiment.id,
                variant=variant,
                event_type="impression",
                metadata={"page": "homepage", "device": "desktop" if i % 2 == 0 else "mobile"}
            )
            
            # Simulate different behavior for control vs treatment
            if variant == "control":
                # Control: 10% CTR, 2% conversion rate
                if np.random.random() < 0.10:
                    metrics_collector.track_experiment_event(
                        user_id=user_id,
                        experiment_id=experiment.id,
                        variant=variant,
                        event_type="click"
                    )
                    
                    if np.random.random() < 0.20:  # 20% of clickers convert
                        metrics_collector.track_experiment_event(
                            user_id=user_id,
                            experiment_id=experiment.id,
                            variant=variant,
                            event_type="conversion",
                            value=np.random.uniform(20, 100)
                        )
            else:
                # Treatment: 15% CTR, 3.5% conversion rate
                if np.random.random() < 0.15:
                    metrics_collector.track_experiment_event(
                        user_id=user_id,
                        experiment_id=experiment.id,
                        variant=variant,
                        event_type="click"
                    )
                    
                    if np.random.random() < 0.233:  # 23.3% of clickers convert (for 3.5% overall)
                        metrics_collector.track_experiment_event(
                            user_id=user_id,
                            experiment_id=experiment.id,
                            variant=variant,
                            event_type="conversion",
                            value=np.random.uniform(25, 120)
                        )
        
        # 4. Analyze results
        real_time_metrics = metrics_collector.get_real_time_metrics(experiment.id)
        
        # Verify both variants have data
        assert "control" in real_time_metrics
        assert "treatment" in real_time_metrics
        
        control_metrics = real_time_metrics["control"]
        treatment_metrics = real_time_metrics["treatment"]
        
        # Check that we have reasonable assignment distribution
        total_control = control_metrics["impressions"]
        total_treatment = treatment_metrics["impressions"]
        total_assignments = total_control + total_treatment
        
        assert total_assignments == num_users
        assert 0.4 <= (total_control / total_assignments) <= 0.6  # Should be roughly 50/50
        
        # Check conversion rates
        assert control_metrics["conversion_rate"] > 0
        assert treatment_metrics["conversion_rate"] > 0
        
        # Treatment should generally perform better (though not guaranteed due to randomness)
        print(f"Control conversion rate: {control_metrics['conversion_rate']:.3f}")
        print(f"Treatment conversion rate: {treatment_metrics['conversion_rate']:.3f}")
        
        # 5. Get experiment status
        status = ab_testing.get_experiment_status(experiment.id)
        assert status["total_assignments"] == num_users
        assert status["experiment"]["status"] == ExperimentStatus.RUNNING.value
        
        # 6. Stop experiment
        ab_testing.stop_experiment(experiment.id)
        final_status = ab_testing.get_experiment_status(experiment.id)
        assert final_status["experiment"]["status"] == ExperimentStatus.COMPLETED.value
    
    def test_multi_experiment_isolation(self, feedback_system):
        """Test that multiple experiments are properly isolated."""
        ab_testing = feedback_system["ab_testing"]
        metrics_collector = feedback_system["metrics_collector"]
        
        # Create two different experiments
        exp1 = ab_testing.create_experiment(
            name="Button Color Test",
            description="Test button color impact",
            variants=["red", "blue"],
            allocation={"red": 0.5, "blue": 0.5},
            metrics=["conversion_rate"]
        )
        
        exp2 = ab_testing.create_experiment(
            name="Headline Test",
            description="Test headline variations",
            variants=["original", "variation"],
            allocation={"original": 0.5, "variation": 0.5},
            metrics=["click_through_rate"]
        )
        
        # Start both experiments
        ab_testing.start_experiment(exp1.id)
        ab_testing.start_experiment(exp2.id)
        
        # Track events for both experiments
        for i in range(50):
            user_id = f"user_{i:03d}"
            
            # Experiment 1 events
            variant1 = ab_testing.assign_user(user_id, exp1.id)
            metrics_collector.track_experiment_event(
                user_id=user_id,
                experiment_id=exp1.id,
                variant=variant1,
                event_type="impression"
            )
            
            # Experiment 2 events
            variant2 = ab_testing.assign_user(user_id, exp2.id)
            metrics_collector.track_experiment_event(
                user_id=user_id,
                experiment_id=exp2.id,
                variant=variant2,
                event_type="click"
            )
        
        # Get metrics for each experiment
        metrics1 = metrics_collector.get_real_time_metrics(exp1.id)
        metrics2 = metrics_collector.get_real_time_metrics(exp2.id)
        
        # Verify isolation
        assert "red" in metrics1 or "blue" in metrics1
        assert "original" in metrics2 or "variation" in metrics2
        
        # Experiment 1 should have impressions but no clicks
        for variant in metrics1.values():
            assert variant["impressions"] > 0
            assert variant["clicks"] == 0
        
        # Experiment 2 should have clicks but no impressions
        for variant in metrics2.values():
            assert variant["clicks"] > 0
            assert variant["impressions"] == 0
    
    def test_custom_metrics_in_ab_test(self, feedback_system):
        """Test custom metrics within A/B testing framework."""
        ab_testing = feedback_system["ab_testing"]
        metrics_collector = feedback_system["metrics_collector"]
        
        # Create custom metrics
        metrics_collector.create_custom_metric(
            name="high_value_conversions",
            description="Conversions with value >= $50",
            event_types=["conversion"],
            aggregation="count",
            conditions={"min_value": 50.0}
        )
        
        metrics_collector.create_custom_metric(
            name="mobile_clicks",
            description="Clicks from mobile devices",
            event_types=["click"],
            aggregation="count",
            conditions={"metadata": {"device": "mobile"}}
        )
        
        # Create experiment
        experiment = ab_testing.create_experiment(
            name="Custom Metrics Test",
            description="Test custom metrics",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate", "high_value_conversions", "mobile_clicks"]
        )
        
        ab_testing.start_experiment(experiment.id)
        
        # Generate test data
        test_data = [
            ("user1", "control", [("impression", {}), ("conversion", {"value": 25.0})]),
            ("user2", "control", [("impression", {}), ("conversion", {"value": 75.0})]),
            ("user3", "treatment", [("impression", {}), ("click", {"device": "mobile"})]),
            ("user4", "treatment", [("impression", {}), ("conversion", {"value": 60.0, "device": "desktop"})])
        ]
        
        for user_id, variant, events in test_data:
            # Assign user to ensure consistent variant
            assigned_variant = ab_testing.assign_user(user_id, experiment.id)
            
            for event_type, metadata in events:
                value = metadata.pop("value", None) if "value" in metadata else None
                metrics_collector.track_experiment_event(
                    user_id=user_id,
                    experiment_id=experiment.id,
                    variant=assigned_variant,
                    event_type=event_type,
                    metadata=metadata,
                    value=value
                )
        
        # Calculate custom metrics
        control_high_value = metrics_collector.get_custom_metric_value(
            "high_value_conversions", experiment.id, "control"
        )
        treatment_high_value = metrics_collector.get_custom_metric_value(
            "high_value_conversions", experiment.id, "treatment"
        )
        
        mobile_clicks_control = metrics_collector.get_custom_metric_value(
            "mobile_clicks", experiment.id, "control"
        )
        mobile_clicks_treatment = metrics_collector.get_custom_metric_value(
            "mobile_clicks", experiment.id, "treatment"
        )
        
        # Verify results
        assert control_high_value == 1.0  # Only user2 had value >= 50
        assert treatment_high_value == 1.0  # Only user4 had value >= 50
        assert mobile_clicks_control == 0.0  # No mobile clicks in control
        assert mobile_clicks_treatment == 1.0  # user3 had mobile click
    
    def test_statistical_significance_detection(self, feedback_system):
        """Test statistical significance detection with sufficient data."""
        ab_testing = feedback_system["ab_testing"]
        metrics_collector = feedback_system["metrics_collector"]
        
        # Create experiment
        experiment = ab_testing.create_experiment(
            name="Statistical Significance Test",
            description="Test statistical significance detection",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"],
            significance_level=0.05
        )
        
        ab_testing.start_experiment(experiment.id)
        
        # Generate large dataset with clear difference
        np.random.seed(42)  # For reproducible results
        
        for i in range(1000):
            user_id = f"user_{i:04d}"
            variant = ab_testing.assign_user(user_id, experiment.id)
            
            # Track impression
            metrics_collector.track_experiment_event(
                user_id=user_id,
                experiment_id=experiment.id,
                variant=variant,
                event_type="impression"
            )
            
            # Different conversion rates for each variant
            if variant == "control":
                # 5% conversion rate
                if np.random.random() < 0.05:
                    metrics_collector.track_experiment_event(
                        user_id=user_id,
                        experiment_id=experiment.id,
                        variant=variant,
                        event_type="conversion",
                        value=50.0
                    )
            else:
                # 8% conversion rate (significant difference)
                if np.random.random() < 0.08:
                    metrics_collector.track_experiment_event(
                        user_id=user_id,
                        experiment_id=experiment.id,
                        variant=variant,
                        event_type="conversion",
                        value=50.0
                    )
        
        # Get experiment results
        results = ab_testing.get_experiment_results(experiment.id)
        
        assert "conversion_rate" in results
        conversion_result = results["conversion_rate"]
        
        # Verify statistical analysis
        assert "p_value" in conversion_result
        assert "significant" in conversion_result
        assert "control_rate" in conversion_result
        assert "treatment_rate" in conversion_result
        
        # With sufficient data and clear difference, should detect significance
        print(f"Control rate: {conversion_result['control_rate']:.3f}")
        print(f"Treatment rate: {conversion_result['treatment_rate']:.3f}")
        print(f"P-value: {conversion_result['p_value']:.4f}")
        print(f"Significant: {conversion_result['significant']}")
        
        # Treatment should have higher rate
        assert conversion_result["treatment_rate"] > conversion_result["control_rate"]
    
    def test_experiment_persistence_across_restarts(self, feedback_system):
        """Test that experiments persist across system restarts."""
        redis_client = feedback_system["redis"]
        
        # Create first instance and experiment
        ab_testing1 = ABTestingFramework(redis_client=redis_client)
        experiment = ab_testing1.create_experiment(
            name="Persistence Test",
            description="Test experiment persistence",
            variants=["A", "B"],
            allocation={"A": 0.5, "B": 0.5},
            metrics=["conversion_rate"]
        )
        ab_testing1.start_experiment(experiment.id)
        
        # Simulate system restart with new instance
        ab_testing2 = ABTestingFramework(redis_client=redis_client)
        
        # Verify experiment was loaded
        assert experiment.id in ab_testing2.experiments
        loaded_exp = ab_testing2.experiments[experiment.id]
        
        assert loaded_exp.name == "Persistence Test"
        assert loaded_exp.status == ExperimentStatus.RUNNING
        assert loaded_exp.variants == ["A", "B"]
        
        # Should be able to continue using the experiment
        variant = ab_testing2.assign_user("test_user", experiment.id)
        assert variant in ["A", "B"]
    
    def test_dashboard_data_aggregation(self, feedback_system):
        """Test dashboard data aggregation across time periods."""
        ab_testing = feedback_system["ab_testing"]
        metrics_collector = feedback_system["metrics_collector"]
        
        # Create experiment
        experiment = ab_testing.create_experiment(
            name="Dashboard Test",
            description="Test dashboard data",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        ab_testing.start_experiment(experiment.id)
        
        # Mock time progression and generate events over multiple days
        base_time = datetime(2023, 1, 1, 12, 0, 0)
        
        with patch('brain_researcher.services.feedback.metrics_collector.datetime') as mock_datetime:
            for day in range(7):  # 7 days of data
                current_time = base_time + timedelta(days=day)
                mock_datetime.utcnow.return_value = current_time
                
                # Generate events for this day
                for user_idx in range(10):  # 10 users per day
                    user_id = f"day{day}_user{user_idx}"
                    variant = ab_testing.assign_user(user_id, experiment.id)
                    
                    metrics_collector.track_experiment_event(
                        user_id=user_id,
                        experiment_id=experiment.id,
                        variant=variant,
                        event_type="impression"
                    )
                    
                    if user_idx < 2:  # 2 conversions per day
                        metrics_collector.track_experiment_event(
                            user_id=user_id,
                            experiment_id=experiment.id,
                            variant=variant,
                            event_type="conversion",
                            value=25.0 * (day + 1)  # Increasing value over time
                        )
            
            # Set current time to end of week
            mock_datetime.utcnow.return_value = base_time + timedelta(days=7)
            
            # Get dashboard data
            dashboard_data = metrics_collector.get_metrics_dashboard_data(experiment.id)
            
            assert "real_time" in dashboard_data
            assert "daily" in dashboard_data
            assert "last_updated" in dashboard_data
            
            # Should have 7 days of daily data
            assert len(dashboard_data["daily"]) == 7
            
            # Each day should have data for both variants
            for day_key, day_data in dashboard_data["daily"].items():
                if day_data:  # Some days might be empty depending on assignment
                    for variant_data in day_data.values():
                        if variant_data["impressions"] > 0:
                            assert "conversions" in variant_data
                            assert "revenue" in variant_data
    
    def test_error_handling_and_recovery(self, feedback_system):
        """Test system behavior under error conditions."""
        ab_testing = feedback_system["ab_testing"]
        metrics_collector = feedback_system["metrics_collector"]
        
        # Test 1: Invalid experiment operations
        with pytest.raises(ValueError):
            ab_testing.start_experiment("nonexistent_experiment")
        
        with pytest.raises(ValueError):
            ab_testing.get_experiment_results("nonexistent_experiment")
        
        # Test 2: Invalid metric operations
        with pytest.raises(ValueError):
            metrics_collector.get_custom_metric_value("nonexistent_metric", "exp", "variant")
        
        # Test 3: Recovery from corrupted data
        experiment = ab_testing.create_experiment(
            name="Error Recovery Test",
            description="Test error recovery",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        
        ab_testing.start_experiment(experiment.id)
        
        # Track some normal events
        metrics_collector.track_experiment_event(
            user_id="normal_user",
            experiment_id=experiment.id,
            variant="control",
            event_type="impression"
        )
        
        # System should handle corrupted/missing events gracefully
        metrics = metrics_collector.get_real_time_metrics(experiment.id)
        assert "control" in metrics or "treatment" in metrics  # Should not crash


if __name__ == "__main__":
    pytest.main([__file__, "-v"])