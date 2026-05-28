"""Unit tests for Metrics Collector."""

import json
import pytest
import redis
from datetime import datetime, timedelta
from typing import Dict, List
from unittest.mock import Mock, patch, MagicMock
import numpy as np

from brain_researcher.services.feedback.metrics_collector import (
    MetricsCollector,
    MetricsAggregator,
    Event,
    EventType,
    MetricDefinition,
    ExperimentMetrics
)


class TestMetricsAggregator:
    """Test metrics aggregation methods."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.aggregator = MetricsAggregator()
        self.base_time = datetime(2023, 1, 1, 12, 0, 0)
    
    def create_event(self, event_type: EventType, value=None, user_id="user1", session_id="session1", offset_minutes=0):
        """Helper to create test events."""
        return Event(
            user_id=user_id,
            event_type=event_type,
            experiment_id="exp_test",
            variant="control",
            timestamp=self.base_time + timedelta(minutes=offset_minutes),
            metadata={},
            value=value,
            session_id=session_id
        )
    
    def test_calculate_conversion_rate_basic(self):
        """Test basic conversion rate calculation."""
        events = [
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.CONVERSION),
            self.create_event(EventType.CONVERSION)
        ]
        
        rate = self.aggregator.calculate_conversion_rate(events)
        assert rate == 2/3  # 2 conversions, 3 impressions
    
    def test_calculate_conversion_rate_no_impressions(self):
        """Test conversion rate with no impressions."""
        events = [
            self.create_event(EventType.CONVERSION),
            self.create_event(EventType.CLICK)
        ]
        
        rate = self.aggregator.calculate_conversion_rate(events)
        assert rate == 0.0
    
    def test_calculate_conversion_rate_empty(self):
        """Test conversion rate with empty events."""
        rate = self.aggregator.calculate_conversion_rate([])
        assert rate == 0.0
    
    def test_calculate_click_through_rate(self):
        """Test click-through rate calculation."""
        events = [
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.CLICK),
            self.create_event(EventType.CLICK)
        ]
        
        ctr = self.aggregator.calculate_click_through_rate(events)
        assert ctr == 0.5  # 2 clicks, 4 impressions
    
    def test_calculate_average_value(self):
        """Test average value calculation."""
        events = [
            self.create_event(EventType.CONVERSION, value=10.0),
            self.create_event(EventType.CONVERSION, value=20.0),
            self.create_event(EventType.CONVERSION, value=30.0),
            self.create_event(EventType.CONVERSION, value=None)  # Should be ignored
        ]
        
        avg_value = self.aggregator.calculate_average_value(events)
        assert avg_value == 20.0  # (10 + 20 + 30) / 3
    
    def test_calculate_average_value_no_values(self):
        """Test average value with no value data."""
        events = [
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.CLICK)
        ]
        
        avg_value = self.aggregator.calculate_average_value(events)
        assert avg_value == 0.0
    
    def test_calculate_total_value(self):
        """Test total value calculation."""
        events = [
            self.create_event(EventType.CONVERSION, value=10.5),
            self.create_event(EventType.CONVERSION, value=25.0),
            self.create_event(EventType.CONVERSION, value=None)  # Should be ignored
        ]
        
        total_value = self.aggregator.calculate_total_value(events)
        assert total_value == 35.5
    
    def test_calculate_error_rate(self):
        """Test error rate calculation."""
        events = [
            self.create_event(EventType.IMPRESSION),
            self.create_event(EventType.CLICK),
            self.create_event(EventType.ERROR),
            self.create_event(EventType.CONVERSION),
            self.create_event(EventType.ERROR)
        ]
        
        error_rate = self.aggregator.calculate_error_rate(events)
        assert error_rate == 0.4  # 2 errors out of 5 total events
    
    def test_calculate_user_engagement_basic(self):
        """Test user engagement calculation."""
        events = [
            # Session 1: user1, 10 minutes duration, 3 events
            self.create_event(EventType.IMPRESSION, user_id="user1", session_id="session1", offset_minutes=0),
            self.create_event(EventType.CLICK, user_id="user1", session_id="session1", offset_minutes=5),
            self.create_event(EventType.CONVERSION, user_id="user1", session_id="session1", offset_minutes=10),
            
            # Session 2: user2, 20 minutes duration, 2 events
            self.create_event(EventType.IMPRESSION, user_id="user2", session_id="session2", offset_minutes=0),
            self.create_event(EventType.CLICK, user_id="user2", session_id="session2", offset_minutes=20)
        ]
        
        engagement = self.aggregator.calculate_user_engagement(events)
        
        assert engagement["sessions"] == 2
        assert engagement["avg_session_length"] == 15.0  # (10 + 20) / 2 minutes
        assert engagement["events_per_session"] == 2.5  # (3 + 2) / 2
    
    def test_calculate_user_engagement_single_event_sessions(self):
        """Test engagement with single-event sessions (should be ignored)."""
        events = [
            self.create_event(EventType.IMPRESSION, user_id="user1", session_id="session1"),
            self.create_event(EventType.IMPRESSION, user_id="user2", session_id="session2"),
            # Multi-event session
            self.create_event(EventType.IMPRESSION, user_id="user3", session_id="session3", offset_minutes=0),
            self.create_event(EventType.CLICK, user_id="user3", session_id="session3", offset_minutes=10)
        ]
        
        engagement = self.aggregator.calculate_user_engagement(events)
        
        # Only the multi-event session should count
        assert engagement["sessions"] == 3  # Total unique sessions
        assert engagement["avg_session_length"] == 10.0  # Only the valid session
        assert engagement["events_per_session"] == 2.0  # Only the valid session
    
    def test_calculate_user_engagement_empty(self):
        """Test engagement with empty events."""
        engagement = self.aggregator.calculate_user_engagement([])
        
        assert engagement["sessions"] == 0
        assert engagement["avg_session_length"] == 0
        assert engagement["events_per_session"] == 0


class TestEvent:
    """Test Event data class."""
    
    def test_event_creation(self):
        """Test event creation."""
        timestamp = datetime.now()
        event = Event(
            user_id="user123",
            event_type=EventType.CONVERSION,
            experiment_id="exp_test",
            variant="treatment",
            timestamp=timestamp,
            metadata={"source": "web"},
            value=25.99,
            session_id="session456"
        )
        
        assert event.user_id == "user123"
        assert event.event_type == EventType.CONVERSION
        assert event.experiment_id == "exp_test"
        assert event.variant == "treatment"
        assert event.timestamp == timestamp
        assert event.metadata == {"source": "web"}
        assert event.value == 25.99
        assert event.session_id == "session456"


class TestMetricDefinition:
    """Test MetricDefinition data class."""
    
    def test_metric_definition_creation(self):
        """Test metric definition creation."""
        metric_def = MetricDefinition(
            name="custom_conversion",
            description="Custom conversion metric",
            event_types=[EventType.IMPRESSION, EventType.CONVERSION],
            aggregation="conversion_rate",
            conditions={"min_value": 10.0},
            time_window_hours=48
        )
        
        assert metric_def.name == "custom_conversion"
        assert metric_def.description == "Custom conversion metric"
        assert EventType.IMPRESSION in metric_def.event_types
        assert EventType.CONVERSION in metric_def.event_types
        assert metric_def.aggregation == "conversion_rate"
        assert metric_def.conditions == {"min_value": 10.0}
        assert metric_def.time_window_hours == 48


class TestMetricsCollector:
    """Test MetricsCollector class."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.mock_redis = Mock(spec=redis.Redis)
        self.mock_redis.decode_responses = True
        self.collector = MetricsCollector(redis_client=self.mock_redis)
    
    def test_track_event_basic(self):
        """Test basic event tracking."""
        self.collector.track_event(
            user_id="user123",
            event_type="conversion",
            experiment_id="exp_test",
            variant="treatment",
            metadata={"source": "web"},
            value=25.99,
            session_id="session456"
        )
        
        # Verify Redis storage calls
        self.mock_redis.hset.assert_called()
        self.mock_redis.expire.assert_called()
        self.mock_redis.zadd.assert_called()
        self.mock_redis.hincrby.assert_called()
    
    def test_track_event_invalid_type(self):
        """Test tracking event with invalid type."""
        self.collector.track_event(
            user_id="user123",
            event_type="invalid_type",
            experiment_id="exp_test",
            variant="treatment"
        )
        
        # Should still track as CUSTOM event type
        self.mock_redis.hset.assert_called()
    
    def test_track_experiment_event(self):
        """Test experiment-specific event tracking."""
        self.collector.track_experiment_event(
            user_id="user123",
            experiment_id="exp_test",
            variant="treatment",
            event_type="conversion",
            metadata={"campaign": "summer"},
            value=50.0
        )
        
        # Should call both general tracking and experiment counters
        self.mock_redis.hset.assert_called()
        self.mock_redis.hincrby.assert_called()
        self.mock_redis.hincrbyfloat.assert_called()
    
    def test_create_custom_metric_valid(self):
        """Test creating valid custom metric."""
        self.collector.create_custom_metric(
            name="high_value_conversions",
            description="Conversions with value > $50",
            event_types=["conversion"],
            aggregation="count",
            conditions={"min_value": 50.0},
            time_window_hours=24
        )
        
        assert "high_value_conversions" in self.collector.metric_definitions
        
        metric_def = self.collector.metric_definitions["high_value_conversions"]
        assert metric_def.name == "high_value_conversions"
        assert EventType.CONVERSION in metric_def.event_types
        assert metric_def.conditions == {"min_value": 50.0}
        
        # Verify Redis save
        self.mock_redis.hset.assert_called()
    
    def test_create_custom_metric_invalid_event_type(self):
        """Test creating custom metric with invalid event type."""
        with pytest.raises(ValueError, match="Invalid event type"):
            self.collector.create_custom_metric(
                name="invalid_metric",
                description="Invalid metric",
                event_types=["invalid_type"],
                aggregation="count"
            )
    
    def test_create_custom_metric_invalid_aggregation(self):
        """Test creating custom metric with invalid aggregation."""
        with pytest.raises(ValueError, match="Invalid aggregation"):
            self.collector.create_custom_metric(
                name="invalid_metric",
                description="Invalid metric",
                event_types=["impression"],
                aggregation="invalid_agg"
            )
    
    @patch('brain_researcher.services.feedback.metrics_collector.datetime')
    def test_get_real_time_metrics(self, mock_datetime):
        """Test real-time metrics retrieval."""
        current_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.utcnow.return_value = current_time
        
        # Mock experiment variants
        self.collector._get_experiment_variants = Mock(return_value=["control", "treatment"])
        
        # Mock events
        mock_events = [
            Event("user1", EventType.IMPRESSION, "exp_test", "control", current_time, {}, None),
            Event("user1", EventType.CLICK, "exp_test", "control", current_time, {}, None),
            Event("user2", EventType.CONVERSION, "exp_test", "control", current_time, {}, 25.0),
            Event("user3", EventType.ERROR, "exp_test", "control", current_time, {}, None)
        ]
        self.collector._get_events = Mock(return_value=mock_events)
        
        metrics = self.collector.get_real_time_metrics("exp_test", time_window_minutes=60)
        
        assert "control" in metrics
        control_metrics = metrics["control"]
        
        assert control_metrics["impressions"] == 1
        assert control_metrics["clicks"] == 1
        assert control_metrics["conversions"] == 1
        assert control_metrics["errors"] == 1
        assert control_metrics["ctr"] == 1.0  # 1 click / 1 impression
        assert control_metrics["conversion_rate"] == 1.0  # 1 conversion / 1 impression
        assert control_metrics["total_revenue"] == 25.0
    
    def test_get_experiment_metrics(self):
        """Test experiment metrics retrieval."""
        start_time = datetime(2023, 1, 1)
        end_time = datetime(2023, 1, 2)
        
        # Mock variants and metrics calculation
        self.collector._get_experiment_variants = Mock(return_value=["control", "treatment"])
        self.collector._calculate_variant_metrics = Mock(return_value=Mock())
        
        metrics = self.collector.get_experiment_metrics(
            "exp_test",
            start_time=start_time,
            end_time=end_time
        )
        
        assert "control" in metrics
        assert "treatment" in metrics
        
        # Verify calculation was called for each variant
        assert self.collector._calculate_variant_metrics.call_count == 2
    
    def test_get_custom_metric_value_count(self):
        """Test custom metric value calculation - count."""
        # Create custom metric
        self.collector.create_custom_metric(
            name="test_count",
            description="Test count metric",
            event_types=["click"],
            aggregation="count"
        )
        
        # Mock events
        mock_events = [
            Event("user1", EventType.CLICK, "exp_test", "control", datetime.now(), {}, None),
            Event("user2", EventType.CLICK, "exp_test", "control", datetime.now(), {}, None)
        ]
        self.collector._get_events = Mock(return_value=mock_events)
        
        value = self.collector.get_custom_metric_value(
            "test_count",
            "exp_test",
            "control"
        )
        
        assert value == 2.0
    
    def test_get_custom_metric_value_sum(self):
        """Test custom metric value calculation - sum."""
        # Create custom metric
        self.collector.create_custom_metric(
            name="test_revenue",
            description="Test revenue metric",
            event_types=["conversion"],
            aggregation="sum"
        )
        
        # Mock events
        mock_events = [
            Event("user1", EventType.CONVERSION, "exp_test", "control", datetime.now(), {}, 10.0),
            Event("user2", EventType.CONVERSION, "exp_test", "control", datetime.now(), {}, 25.0)
        ]
        self.collector._get_events = Mock(return_value=mock_events)
        
        value = self.collector.get_custom_metric_value(
            "test_revenue",
            "exp_test",
            "control"
        )
        
        assert value == 35.0
    
    def test_get_custom_metric_value_avg(self):
        """Test custom metric value calculation - average."""
        # Create custom metric
        self.collector.create_custom_metric(
            name="test_avg",
            description="Test average metric",
            event_types=["conversion"],
            aggregation="avg"
        )
        
        # Mock events
        mock_events = [
            Event("user1", EventType.CONVERSION, "exp_test", "control", datetime.now(), {}, 10.0),
            Event("user2", EventType.CONVERSION, "exp_test", "control", datetime.now(), {}, 20.0)
        ]
        self.collector._get_events = Mock(return_value=mock_events)
        
        value = self.collector.get_custom_metric_value(
            "test_avg",
            "exp_test",
            "control"
        )
        
        assert value == 15.0
    
    def test_get_custom_metric_undefined(self):
        """Test getting undefined custom metric."""
        with pytest.raises(ValueError, match="Metric undefined_metric not defined"):
            self.collector.get_custom_metric_value(
                "undefined_metric",
                "exp_test",
                "control"
            )
    
    def test_event_matches_conditions_metadata(self):
        """Test event condition matching - metadata."""
        event = Event(
            "user1", EventType.CONVERSION, "exp_test", "control", datetime.now(),
            {"campaign": "summer", "source": "web"}, 25.0
        )
        
        # Matching conditions
        conditions1 = {"metadata": {"campaign": "summer"}}
        assert self.collector._event_matches_conditions(event, conditions1) is True
        
        conditions2 = {"metadata": {"campaign": "summer", "source": "web"}}
        assert self.collector._event_matches_conditions(event, conditions2) is True
        
        # Non-matching conditions
        conditions3 = {"metadata": {"campaign": "winter"}}
        assert self.collector._event_matches_conditions(event, conditions3) is False
        
        conditions4 = {"metadata": {"nonexistent": "value"}}
        assert self.collector._event_matches_conditions(event, conditions4) is False
    
    def test_event_matches_conditions_user_id(self):
        """Test event condition matching - user_id."""
        event = Event(
            "user123", EventType.CONVERSION, "exp_test", "control", datetime.now(),
            {}, 25.0
        )
        
        # Matching condition
        conditions1 = {"user_id": "user123"}
        assert self.collector._event_matches_conditions(event, conditions1) is True
        
        # Non-matching condition
        conditions2 = {"user_id": "user456"}
        assert self.collector._event_matches_conditions(event, conditions2) is False
    
    def test_event_matches_conditions_min_value(self):
        """Test event condition matching - min_value."""
        event = Event(
            "user1", EventType.CONVERSION, "exp_test", "control", datetime.now(),
            {}, 25.0
        )
        
        # Matching condition
        conditions1 = {"min_value": 20.0}
        assert self.collector._event_matches_conditions(event, conditions1) is True
        
        # Non-matching condition
        conditions2 = {"min_value": 30.0}
        assert self.collector._event_matches_conditions(event, conditions2) is False
        
        # No value event
        event_no_value = Event(
            "user1", EventType.CLICK, "exp_test", "control", datetime.now(),
            {}, None
        )
        conditions3 = {"min_value": 10.0}
        assert self.collector._event_matches_conditions(event_no_value, conditions3) is False
    
    def test_get_metrics_dashboard_data(self):
        """Test dashboard data aggregation."""
        # Mock current time
        with patch('brain_researcher.services.feedback.metrics_collector.datetime') as mock_datetime:
            current_time = datetime(2023, 1, 8, 12, 0, 0)  # Week 2 of January
            mock_datetime.utcnow.return_value = current_time
            
            # Mock variants and real-time metrics
            self.collector._get_experiment_variants = Mock(return_value=["control", "treatment"])
            self.collector.get_real_time_metrics = Mock(return_value={"control": {"conversions": 10}})
            
            # Mock daily events
            self.collector._get_events = Mock(return_value=[
                Event("user1", EventType.IMPRESSION, "exp_test", "control", current_time, {}, None),
                Event("user2", EventType.CONVERSION, "exp_test", "control", current_time, {}, 15.0)
            ])
            
            dashboard_data = self.collector.get_metrics_dashboard_data("exp_test")
            
            assert "real_time" in dashboard_data
            assert "daily" in dashboard_data
            assert "last_updated" in dashboard_data
            
            # Should have 7 days of data
            assert len(dashboard_data["daily"]) == 7


@pytest.mark.integration 
class TestMetricsCollectorIntegration:
    """Integration tests for metrics collector."""
    
    @pytest.fixture
    def redis_client(self):
        """Setup Redis client for integration tests."""
        try:
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=True)
        except ImportError:
            pytest.skip("fakeredis not available for integration tests")
    
    def test_full_metrics_pipeline(self, redis_client):
        """Test complete metrics collection pipeline."""
        collector = MetricsCollector(redis_client=redis_client)
        
        # Track various events
        events = [
            ("user1", "impression", "exp_test", "control", None, None),
            ("user1", "click", "exp_test", "control", None, None),
            ("user1", "conversion", "exp_test", "control", {"campaign": "test"}, 25.0),
            ("user2", "impression", "exp_test", "treatment", None, None),
            ("user2", "conversion", "exp_test", "treatment", {"campaign": "test"}, 35.0),
            ("user3", "impression", "exp_test", "control", None, None),
            ("user3", "error", "exp_test", "control", {"error_code": "404"}, None)
        ]
        
        for user_id, event_type, exp_id, variant, metadata, value in events:
            collector.track_experiment_event(
                user_id=user_id,
                experiment_id=exp_id,
                variant=variant,
                event_type=event_type,
                metadata=metadata,
                value=value
            )
        
        # Get real-time metrics
        rt_metrics = collector.get_real_time_metrics("exp_test")
        
        # Verify metrics
        assert "control" in rt_metrics
        assert "treatment" in rt_metrics
        
        control_metrics = rt_metrics["control"]
        assert control_metrics["impressions"] == 2
        assert control_metrics["clicks"] == 1
        assert control_metrics["conversions"] == 1
        assert control_metrics["errors"] == 1
        assert control_metrics["conversion_rate"] == 0.5  # 1/2 impressions
        assert control_metrics["total_revenue"] == 25.0
        
        treatment_metrics = rt_metrics["treatment"]
        assert treatment_metrics["impressions"] == 1
        assert treatment_metrics["conversions"] == 1
        assert treatment_metrics["conversion_rate"] == 1.0  # 1/1 impression
        assert treatment_metrics["total_revenue"] == 35.0
    
    def test_custom_metrics_pipeline(self, redis_client):
        """Test custom metrics definition and calculation."""
        collector = MetricsCollector(redis_client=redis_client)
        
        # Create custom metric
        collector.create_custom_metric(
            name="high_value_conversions",
            description="Conversions with value >= $30",
            event_types=["conversion"],
            aggregation="count",
            conditions={"min_value": 30.0}
        )
        
        # Track events
        collector.track_experiment_event("user1", "exp_test", "control", "conversion", value=25.0)
        collector.track_experiment_event("user2", "exp_test", "control", "conversion", value=35.0)
        collector.track_experiment_event("user3", "exp_test", "control", "conversion", value=45.0)
        
        # Calculate custom metric
        value = collector.get_custom_metric_value(
            "high_value_conversions",
            "exp_test", 
            "control"
        )
        
        # Should count only conversions with value >= 30
        assert value == 2.0
    
    def test_time_based_metrics(self, redis_client):
        """Test time-based metric calculations."""
        collector = MetricsCollector(redis_client=redis_client)
        
        base_time = datetime(2023, 1, 1, 12, 0, 0)
        
        # Create events at different times
        with patch('brain_researcher.services.feedback.metrics_collector.datetime') as mock_datetime:
            # Track events at different times
            mock_datetime.utcnow.return_value = base_time
            collector.track_experiment_event("user1", "exp_test", "control", "impression")
            
            mock_datetime.utcnow.return_value = base_time + timedelta(minutes=30)
            collector.track_experiment_event("user1", "exp_test", "control", "conversion", value=20.0)
            
            mock_datetime.utcnow.return_value = base_time + timedelta(hours=2)
            collector.track_experiment_event("user2", "exp_test", "control", "impression")
            
            # Get metrics for different time windows
            mock_datetime.utcnow.return_value = base_time + timedelta(hours=3)
            
            # Real-time metrics (last hour) - should only include user2's impression
            rt_metrics = collector.get_real_time_metrics("exp_test", time_window_minutes=60)
            control_rt = rt_metrics["control"]
            assert control_rt["impressions"] == 1
            assert control_rt["conversions"] == 0
            
            # Experiment metrics (full period)
            exp_metrics = collector.get_experiment_metrics(
                "exp_test",
                start_time=base_time,
                end_time=base_time + timedelta(hours=3)
            )
            
            # Should include all events
            assert "control" in exp_metrics


if __name__ == "__main__":
    pytest.main([__file__])