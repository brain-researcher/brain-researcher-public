"""
Comprehensive tests for UsageMetricsAggregator - advanced data aggregation and analysis engine.
"""

import asyncio
import statistics
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from brain_researcher.services.telemetry.aggregator import (
    AggregationConfig,
    AggregationWindow,
    UsageMetricsAggregator,
)
from brain_researcher.services.telemetry.models import (
    EventType,
    FeatureUsage,
    MetricType,
    PrivacyLevel,
    ServiceType,
    TelemetryEvent,
    UsageMetric,
    UserJourney,
)


class TestAggregationWindow:
    """Test the AggregationWindow time window utility."""

    def test_window_initialization(self):
        """Test window initialization and properties."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 18, 0, 0)
        window = AggregationWindow(start, end, "hour")

        assert window.start == start
        assert window.end == end
        assert window.granularity == "hour"
        assert window.duration == timedelta(hours=6)
        assert window.duration_seconds == 6 * 3600

    def test_window_properties(self):
        """Test calculated properties of aggregation window."""
        start = datetime(2024, 1, 1, 0, 0, 0)
        end = datetime(2024, 1, 2, 0, 0, 0)
        window = AggregationWindow(start, end, "day")

        assert window.duration == timedelta(days=1)
        assert window.duration_seconds == 86400


class TestAggregationConfig:
    """Test the AggregationConfig configuration class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AggregationConfig()

        assert config.default_window_hours == 24
        assert config.max_window_days == 90
        assert config.real_time_window_minutes == 15
        assert config.auto_granularity is True
        assert config.min_data_points == 10
        assert config.max_data_points == 1000
        assert config.batch_size == 1000
        assert config.parallel_processing is True
        assert config.cache_results is True
        assert config.cache_ttl_minutes == 30

        # Percentile thresholds should be populated
        assert config.percentile_thresholds == [50.0, 75.0, 90.0, 95.0, 99.0]

    def test_custom_config(self):
        """Test custom configuration values."""
        custom_percentiles = [25.0, 50.0, 75.0, 99.0]
        config = AggregationConfig(
            default_window_hours=48,
            batch_size=500,
            percentile_thresholds=custom_percentiles,
        )

        assert config.default_window_hours == 48
        assert config.batch_size == 500
        assert config.percentile_thresholds == custom_percentiles


class TestUsageMetricsAggregator:
    """Test the main UsageMetricsAggregator class."""

    @pytest.fixture
    def config(self):
        """Test configuration."""
        return AggregationConfig(
            default_window_hours=24,
            batch_size=100,
            cache_results=False,  # Disable caching for tests
            min_feature_uses=3,
        )

    @pytest.fixture
    def aggregator(self, config):
        """Create test aggregator."""
        return UsageMetricsAggregator(config)

    @pytest.fixture
    def sample_events(self):
        """Generate sample telemetry events for testing."""
        events = []
        base_time = datetime(2024, 1, 1, 12, 0, 0)

        # Generate diverse events
        for i in range(50):
            timestamp = base_time + timedelta(minutes=i * 5)

            # Mix of event types and services
            event_type = [
                EventType.TOOL_INVOCATION,
                EventType.FEATURE_ACCESS,
                EventType.PAGE_VIEW,
            ][i % 3]
            service = [ServiceType.AGENT, ServiceType.WEB_UI, ServiceType.BR_KG][i % 3]

            events.append(
                TelemetryEvent(
                    id=f"evt_{i:03d}",
                    event_type=event_type,
                    service=service,
                    timestamp=timestamp,
                    user_id=f"user_{i % 10}",  # 10 unique users
                    session_id=f"session_{i % 5}",  # 5 sessions
                    feature_name=f"feature_{i % 8}",  # 8 different features
                    action=["view", "click", "execute", "submit"][i % 4],
                    duration_ms=100 + (i * 50) % 1000,  # Varying durations
                    success=i % 20 != 19,  # 5% error rate
                    privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                )
            )

        return events

    def test_aggregator_initialization(self, config):
        """Test aggregator initialization."""
        aggregator = UsageMetricsAggregator(config)

        assert aggregator.config == config
        assert len(aggregator._events) == 0
        assert len(aggregator._event_index) == 0
        assert len(aggregator._metric_cache) == 0
        assert len(aggregator._real_time_counters) == 0
        assert len(aggregator._active_journeys) == 0
        assert len(aggregator._completed_journeys) == 0

    @pytest.mark.asyncio
    async def test_add_events(self, aggregator, sample_events):
        """Test adding events to the aggregator."""
        await aggregator.add_events(sample_events)

        assert len(aggregator._events) == len(sample_events)
        assert len(aggregator._event_index) == len(sample_events)

        # Check event indexing
        for i, event in enumerate(sample_events):
            assert aggregator._event_index[event.id] == i

    @pytest.mark.asyncio
    async def test_calculate_usage_metrics_basic(self, aggregator, sample_events):
        """Test basic usage metrics calculation."""
        await aggregator.add_events(sample_events)

        # Define window
        window = AggregationWindow(
            start=datetime(2024, 1, 1, 11, 0, 0),
            end=datetime(2024, 1, 1, 17, 0, 0),
            granularity="hour",
        )

        metrics = await aggregator.calculate_usage_metrics(window=window)

        assert len(metrics) > 0
        assert all(isinstance(m, UsageMetric) for m in metrics)

        # Should have total event count metric
        total_metrics = [m for m in metrics if m.name == "Total Events"]
        assert len(total_metrics) == 1
        assert total_metrics[0].value == len(sample_events)

    @pytest.mark.asyncio
    async def test_calculate_usage_counts(self, aggregator, sample_events):
        """Test usage count metrics calculation."""
        await aggregator.add_events(sample_events)

        window = AggregationWindow(
            start=sample_events[0].timestamp - timedelta(hours=1),
            end=sample_events[-1].timestamp + timedelta(hours=1),
            granularity="hour",
        )

        metrics = await aggregator._calculate_usage_counts(sample_events, window)

        # Should have total events metric
        total_metric = next(m for m in metrics if m.name == "Total Events")
        assert total_metric.value == len(sample_events)
        assert total_metric.metric_type == MetricType.USAGE_COUNT
        assert total_metric.unit == "events"

        # Should have service-specific metrics
        service_metrics = [
            m for m in metrics if "Usage" in m.name and m.name != "Total Events"
        ]
        assert len(service_metrics) == 3  # One for each service type

        # Should have unique users metric
        unique_user_metrics = [m for m in metrics if m.name == "Unique Users"]
        assert len(unique_user_metrics) == 1
        assert unique_user_metrics[0].value == 10  # 10 unique users in sample data

    @pytest.mark.asyncio
    async def test_calculate_adoption_metrics(self, aggregator, sample_events):
        """Test feature adoption metrics calculation."""
        await aggregator.add_events(sample_events)

        window = AggregationWindow(
            start=sample_events[0].timestamp - timedelta(hours=1),
            end=sample_events[-1].timestamp + timedelta(hours=1),
            granularity="day",
        )

        metrics = await aggregator._calculate_adoption_metrics(sample_events, window)

        assert len(metrics) > 0

        # All metrics should be adoption rate type
        assert all(m.metric_type == MetricType.ADOPTION_RATE for m in metrics)
        assert all(m.unit == "percentage" for m in metrics)
        assert all(0 <= m.value <= 1 for m in metrics)

        # Should have metrics for each feature
        feature_names = {e.feature_name for e in sample_events if e.feature_name}
        metric_features = {
            m.dimensions.get("feature") for m in metrics if m.dimensions.get("feature")
        }
        assert metric_features == feature_names

    @pytest.mark.asyncio
    async def test_calculate_performance_metrics(self, aggregator, sample_events):
        """Test performance metrics calculation."""
        # Filter events with duration data
        duration_events = [e for e in sample_events if e.duration_ms is not None]

        window = AggregationWindow(
            start=sample_events[0].timestamp - timedelta(hours=1),
            end=sample_events[-1].timestamp + timedelta(hours=1),
            granularity="hour",
        )

        metrics = await aggregator._calculate_performance_metrics(
            duration_events, window
        )

        # Should have average and median response time
        avg_metrics = [m for m in metrics if m.name == "Average Response Time"]
        median_metrics = [m for m in metrics if m.name == "Median Response Time"]

        assert len(avg_metrics) == 1
        assert len(median_metrics) == 1
        assert avg_metrics[0].metric_type == MetricType.PERFORMANCE_METRICS
        assert avg_metrics[0].unit == "milliseconds"

        # Should have percentile metrics
        percentile_metrics = [
            m for m in metrics if "Response Time" in m.name and "P" in m.name
        ]
        assert len(percentile_metrics) > 0

        # Verify percentile calculations
        durations = [e.duration_ms for e in duration_events]
        expected_median = statistics.median(durations)
        assert abs(median_metrics[0].value - expected_median) < 0.01

    @pytest.mark.asyncio
    async def test_calculate_error_metrics(self, aggregator, sample_events):
        """Test error rate metrics calculation."""
        window = AggregationWindow(
            start=sample_events[0].timestamp - timedelta(hours=1),
            end=sample_events[-1].timestamp + timedelta(hours=1),
            granularity="hour",
        )

        metrics = await aggregator._calculate_error_metrics(sample_events, window)

        # Should have overall error rate
        overall_metrics = [m for m in metrics if m.name == "Overall Error Rate"]
        assert len(overall_metrics) == 1

        overall_metric = overall_metrics[0]
        assert overall_metric.metric_type == MetricType.ERROR_RATE
        assert overall_metric.unit == "percentage"

        # Calculate expected error rate (5% in sample data)
        error_events = [e for e in sample_events if not e.success]
        expected_error_rate = len(error_events) / len(sample_events)
        assert abs(overall_metric.value - expected_error_rate) < 0.01

        # Should have service-specific error rates
        service_metrics = [m for m in metrics if m.name != "Overall Error Rate"]
        assert len(service_metrics) > 0

    @pytest.mark.asyncio
    async def test_calculate_temporal_metrics(self, aggregator, sample_events):
        """Test temporal pattern metrics calculation."""
        window = AggregationWindow(
            start=sample_events[0].timestamp - timedelta(hours=1),
            end=sample_events[-1].timestamp + timedelta(hours=1),
            granularity="hour",
        )

        metrics = await aggregator._calculate_temporal_metrics(sample_events, window)

        # Should have peak usage hour metrics
        peak_hour_metrics = [m for m in metrics if m.name == "Peak Usage Hour"]
        peak_count_metrics = [m for m in metrics if m.name == "Peak Hour Event Count"]

        assert len(peak_hour_metrics) == 1
        assert len(peak_count_metrics) == 1

        peak_hour_metric = peak_hour_metrics[0]
        assert peak_hour_metric.metric_type == MetricType.TEMPORAL_PATTERNS
        assert peak_hour_metric.unit == "hour"
        assert 0 <= peak_hour_metric.value <= 23
        assert peak_hour_metric.breakdown is not None

    @pytest.mark.asyncio
    async def test_analyze_feature_usage(self, aggregator, sample_events):
        """Test detailed feature usage analysis."""
        await aggregator.add_events(sample_events)

        feature_analyses = await aggregator.analyze_feature_usage()

        assert len(feature_analyses) > 0
        assert all(isinstance(fa, FeatureUsage) for fa in feature_analyses)

        # Should be sorted by usage count
        usage_counts = [fa.total_uses for fa in feature_analyses]
        assert usage_counts == sorted(usage_counts, reverse=True)

        # Check feature analysis details
        for feature_analysis in feature_analyses:
            assert feature_analysis.total_uses > 0
            assert feature_analysis.unique_users > 0
            assert 0 <= feature_analysis.success_rate <= 1
            assert feature_analysis.trend in ["increasing", "decreasing", "stable"]
            assert 0 <= feature_analysis.error_rate <= 1

    @pytest.mark.asyncio
    async def test_analyze_specific_feature(self, aggregator, sample_events):
        """Test analysis of a specific feature."""
        await aggregator.add_events(sample_events)

        # Analyze specific feature
        feature_name = "feature_1"
        service = ServiceType.AGENT

        feature_analyses = await aggregator.analyze_feature_usage(
            feature_name=feature_name, service=service
        )

        # Should only contain analyses for the specified feature and service
        assert all(fa.feature_name == feature_name for fa in feature_analyses)
        assert all(fa.service == service for fa in feature_analyses)

    @pytest.mark.asyncio
    async def test_extract_user_journeys(self, aggregator, sample_events):
        """Test user journey extraction and analysis."""
        await aggregator.add_events(sample_events)

        journeys = await aggregator.extract_user_journeys()

        assert len(journeys) > 0
        assert all(isinstance(j, UserJourney) for j in journeys)

        # Check journey properties
        for journey in journeys:
            assert journey.journey_id is not None
            assert journey.user_hash is not None
            assert journey.start_time is not None
            assert len(journey.steps) >= 2  # min_steps default is 2
            assert journey.total_steps == len(journey.steps)
            assert journey.completed_steps <= journey.total_steps
            assert 0 <= journey.completion_rate <= 1
            assert journey.total_duration_minutes is not None

    @pytest.mark.asyncio
    async def test_extract_user_journeys_filtered(self, aggregator, sample_events):
        """Test user journey extraction with user filtering."""
        await aggregator.add_events(sample_events)

        # Extract journeys for specific user
        user_hash = "user_5"
        journeys = await aggregator.extract_user_journeys(user_hash=user_hash)

        # Should only contain journeys for the specified user
        for journey in journeys:
            assert journey.user_hash == user_hash or journey.user_hash.startswith(
                "session_"
            )

    @pytest.mark.asyncio
    async def test_get_real_time_metrics(self, aggregator, sample_events):
        """Test real-time metrics calculation."""
        await aggregator.add_events(sample_events)

        real_time_metrics = await aggregator.get_real_time_metrics()

        assert isinstance(real_time_metrics, dict)
        assert "timestamp" in real_time_metrics
        assert "window_minutes" in real_time_metrics
        assert "total_events" in real_time_metrics
        assert "events_per_minute" in real_time_metrics
        assert "services" in real_time_metrics
        assert "features" in real_time_metrics
        assert "errors" in real_time_metrics

        # Check service breakdown
        assert isinstance(real_time_metrics["services"], dict)
        for service_data in real_time_metrics["services"].values():
            assert "event_count" in service_data
            assert "events_per_minute" in service_data

    def test_filter_events(self, aggregator, sample_events):
        """Test event filtering functionality."""
        aggregator._events = sample_events

        # Filter by time window
        start_time = sample_events[10].timestamp
        end_time = sample_events[20].timestamp
        window = AggregationWindow(start_time, end_time, "hour")

        filtered = aggregator._filter_events(window=window)

        for event in filtered:
            assert start_time <= event.timestamp <= end_time

        # Filter by service
        filtered_by_service = aggregator._filter_events(services=[ServiceType.AGENT])
        assert all(e.service == ServiceType.AGENT for e in filtered_by_service)

        # Filter by features
        feature_list = ["feature_1", "feature_2"]
        filtered_by_features = aggregator._filter_events(features=feature_list)
        assert all(
            e.feature_name in feature_list
            for e in filtered_by_features
            if e.feature_name
        )

        # Filter by event types
        event_types = [EventType.TOOL_INVOCATION, EventType.PAGE_VIEW]
        filtered_by_types = aggregator._filter_events(event_types=event_types)
        assert all(e.event_type in event_types for e in filtered_by_types)

    def test_group_events_by_session(self, aggregator, sample_events):
        """Test grouping events by session."""
        aggregator._events = sample_events

        session_groups = aggregator._group_events_by_session(sample_events)

        assert isinstance(session_groups, dict)

        # All events should be in a session group
        total_grouped_events = sum(len(events) for events in session_groups.values())
        events_with_session = sum(1 for e in sample_events if e.session_id)
        assert total_grouped_events == events_with_session

        # Events in same group should have same session ID
        for session_id, events in session_groups.items():
            assert all(e.session_id == session_id for e in events)

    def test_build_user_journey(self, aggregator, sample_events):
        """Test building individual user journey."""
        # Get events for a specific session
        session_events = [e for e in sample_events if e.session_id == "session_0"]
        assert len(session_events) >= 2

        journey = aggregator._build_user_journey("session_0", session_events)

        assert journey is not None
        assert journey.journey_id.startswith("journey_session_0_")
        assert journey.user_hash is not None
        assert len(journey.steps) == len(session_events)
        assert journey.total_steps == len(session_events)

        # Steps should be ordered by timestamp
        step_timestamps = [step["timestamp"] for step in journey.steps]
        assert step_timestamps == sorted(step_timestamps)

    def test_analyze_journey_patterns(self, aggregator):
        """Test journey pattern analysis."""
        # Create sample journeys with some patterns
        journeys = []

        # Common pattern: feature_1 -> feature_2 -> feature_3
        common_steps = [
            {"step_number": 1, "feature_name": "feature_1", "action": "view"},
            {"step_number": 2, "feature_name": "feature_2", "action": "click"},
            {"step_number": 3, "feature_name": "feature_3", "action": "execute"},
        ]

        # Create multiple journeys with this pattern
        for i in range(15):  # Above common_path_threshold
            journey = UserJourney(
                journey_id=f"common_journey_{i}",
                user_hash=f"user_{i}",
                start_time=datetime.utcnow(),
                steps=common_steps.copy(),
                completed_steps=3,
                total_steps=3,
                completion_rate=1.0,
                successful=True,
                common_path=False,
            )
            journeys.append(journey)

        # Add some unique journeys
        for i in range(5):
            unique_steps = [
                {"step_number": 1, "feature_name": f"unique_{i}", "action": "view"}
            ]
            journey = UserJourney(
                journey_id=f"unique_journey_{i}",
                user_hash=f"unique_user_{i}",
                start_time=datetime.utcnow(),
                steps=unique_steps,
                completed_steps=1,
                total_steps=1,
                completion_rate=1.0,
                successful=True,
                common_path=False,
            )
            journeys.append(journey)

        analyzed_journeys = aggregator._analyze_journey_patterns(journeys)

        # Common pattern journeys should be marked as common_path
        common_journeys = [j for j in analyzed_journeys if j.common_path]
        assert len(common_journeys) == 15  # All journeys with the common pattern

        # Unique journeys should not be marked as common
        unique_journeys = [j for j in analyzed_journeys if not j.common_path]
        assert len(unique_journeys) == 5

    def test_percentile_calculation(self, aggregator):
        """Test percentile calculation utility."""
        values = list(range(1, 101))  # 1 to 100

        # Test various percentiles
        assert aggregator._calculate_percentile(values, 50.0) == 50.5
        assert aggregator._calculate_percentile(values, 25.0) == 25.25
        assert aggregator._calculate_percentile(values, 75.0) == 75.75
        assert aggregator._calculate_percentile(values, 90.0) == 90.1

        # Edge cases
        assert aggregator._calculate_percentile([], 50.0) == 0.0
        assert aggregator._calculate_percentile([42], 50.0) == 42

    def test_caching_functionality(self):
        """Test result caching system."""
        config = AggregationConfig(cache_results=True, cache_ttl_minutes=1)
        aggregator = UsageMetricsAggregator(config)

        # Test cache key generation
        window = AggregationWindow(
            start=datetime(2024, 1, 1, 12, 0, 0),
            end=datetime(2024, 1, 1, 18, 0, 0),
            granularity="hour",
        )

        cache_key = aggregator._get_cache_key("test_operation", window, ["service1"])
        assert isinstance(cache_key, str)
        assert len(cache_key) > 0

        # Test caching and retrieval
        test_result = {"test": "data"}
        aggregator._cache_result(cache_key, test_result)

        cached_result = aggregator._get_cached_result(cache_key)
        assert cached_result == test_result

        # Test cache expiration (mock time)
        with patch(
            "brain_researcher.services.telemetry.aggregator.datetime"
        ) as mock_datetime:
            future_time = datetime.utcnow() + timedelta(minutes=5)
            mock_datetime.utcnow.return_value = future_time

            expired_result = aggregator._get_cached_result(cache_key)
            assert expired_result is None

    def test_get_aggregator_stats(self, aggregator, sample_events):
        """Test aggregator statistics reporting."""
        # Add some events
        asyncio.run(aggregator.add_events(sample_events))

        stats = aggregator.get_aggregator_stats()

        assert isinstance(stats, dict)
        assert stats["total_events"] == len(sample_events)
        assert "active_journeys" in stats
        assert "completed_journeys" in stats
        assert "cache_size" in stats
        assert "real_time_counters" in stats
        assert "config" in stats

        # Config should contain key settings
        config_stats = stats["config"]
        assert "default_window_hours" in config_stats
        assert "batch_size" in config_stats
        assert "cache_ttl_minutes" in config_stats
        assert "parallel_processing" in config_stats

    @pytest.mark.asyncio
    async def test_real_time_updates(self, aggregator, sample_events):
        """Test real-time metric updates as events are added."""
        # Add events in batches and check real-time updates
        batch_size = 10

        for i in range(0, len(sample_events), batch_size):
            batch = sample_events[i : i + batch_size]
            await aggregator.add_events(batch)

            # Check that real-time counters are updated
            assert len(aggregator._real_time_counters) > 0

            # Check service counters
            services = aggregator._real_time_counters.get("services", {})
            assert len(services) > 0

            # Check feature counters
            features = aggregator._real_time_counters.get("features", {})
            assert len(features) > 0

    def test_journey_tracking_timeout(self, aggregator):
        """Test journey timeout functionality."""
        # Create events with large time gaps
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        old_event = TelemetryEvent(
            id="old_event",
            event_type=EventType.SESSION_START,
            service=ServiceType.WEB_UI,
            timestamp=base_time,
            session_id="timeout_session",
        )

        # Event that should trigger timeout (3+ hours later)
        timeout_event = TelemetryEvent(
            id="timeout_event",
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.WEB_UI,
            timestamp=base_time + timedelta(hours=4),
            session_id="timeout_session",
        )

        # Add events and trigger journey completion
        aggregator._update_journey_tracking(old_event)
        assert "timeout_session" in aggregator._active_journeys

        aggregator._update_journey_tracking(timeout_event)

        # Journey should be completed due to timeout
        assert len(aggregator._completed_journeys) > 0
        assert "timeout_session" not in aggregator._active_journeys


@pytest.mark.performance
class TestAggregatorPerformance:
    """Performance tests for UsageMetricsAggregator."""

    def test_large_dataset_processing(self):
        """Test processing large numbers of events."""
        config = AggregationConfig(batch_size=1000, parallel_processing=True)
        aggregator = UsageMetricsAggregator(config)

        # Generate large dataset
        events = []
        base_time = datetime(2024, 1, 1, 0, 0, 0)

        for i in range(5000):
            events.append(
                TelemetryEvent(
                    id=f"perf_evt_{i}",
                    event_type=EventType.TOOL_INVOCATION,
                    service=ServiceType.AGENT,
                    timestamp=base_time + timedelta(seconds=i),
                    user_id=f"user_{i % 100}",
                    feature_name=f"tool_{i % 50}",
                    duration_ms=(i * 13) % 2000,
                    success=i % 10 != 0,
                )
            )

        # Test processing time
        import time

        start_time = time.time()

        asyncio.run(aggregator.add_events(events))

        end_time = time.time()
        processing_time = end_time - start_time

        # Should process 5000 events reasonably quickly
        assert (
            processing_time < 2.0
        ), f"Too slow: {processing_time:.2f}s for 5000 events"
        assert len(aggregator._events) == 5000

    @pytest.mark.asyncio
    async def test_metrics_calculation_performance(self):
        """Test performance of metrics calculation."""
        config = AggregationConfig()
        aggregator = UsageMetricsAggregator(config)

        # Generate events
        events = []
        base_time = datetime(2024, 1, 1, 0, 0, 0)

        for i in range(2000):
            events.append(
                TelemetryEvent(
                    id=f"calc_evt_{i}",
                    event_type=EventType.FEATURE_ACCESS,
                    service=ServiceType.WEB_UI,
                    timestamp=base_time + timedelta(minutes=i),
                    user_id=f"user_{i % 50}",
                    feature_name=f"feature_{i % 20}",
                    duration_ms=(i * 7) % 1500,
                    success=i % 15 != 0,
                )
            )

        await aggregator.add_events(events)

        # Test metrics calculation time
        import time

        start_time = time.time()

        window = AggregationWindow(
            start=base_time - timedelta(hours=1),
            end=base_time + timedelta(days=2),
            granularity="hour",
        )

        metrics = await aggregator.calculate_usage_metrics(window=window)

        end_time = time.time()
        calculation_time = end_time - start_time

        # Should calculate comprehensive metrics reasonably quickly
        assert (
            calculation_time < 3.0
        ), f"Metrics calculation too slow: {calculation_time:.2f}s"
        assert len(metrics) > 0

    def test_memory_usage_efficiency(self):
        """Test memory usage remains efficient with large datasets."""
        config = AggregationConfig(cache_results=False)  # Disable caching
        aggregator = UsageMetricsAggregator(config)

        # Process events in batches to test memory efficiency
        base_time = datetime(2024, 1, 1, 0, 0, 0)

        for batch_num in range(10):
            batch_events = []
            for i in range(500):
                event_id = batch_num * 500 + i
                batch_events.append(
                    TelemetryEvent(
                        id=f"mem_evt_{event_id}",
                        event_type=EventType.PAGE_VIEW,
                        service=ServiceType.WEB_UI,
                        timestamp=base_time + timedelta(seconds=event_id),
                        user_id=f"user_{event_id % 100}",
                    )
                )

            asyncio.run(aggregator.add_events(batch_events))

        # Memory usage should be proportional to event count
        assert len(aggregator._events) == 5000

        # Real-time counters should be manageable size
        total_counter_entries = sum(
            len(counter_dict)
            for counter_dict in aggregator._real_time_counters.values()
        )
        assert total_counter_entries < 1000  # Should not grow unboundedly
