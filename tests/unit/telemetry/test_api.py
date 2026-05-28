"""
Comprehensive tests for TelemetryAPI - RESTful endpoints for telemetry data access and management.
"""

import pytest
import json
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, List, Any
from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException
import httpx

from brain_researcher.services.telemetry.api import (
    app, TelemetryService, get_telemetry_service,
    EventCollectionRequest, EventCollectionResponse,
    MetricsQueryRequest, MetricsResponse,
    FeatureAnalysisRequest, FeatureAnalysisResponse,
    JourneyAnalysisRequest, JourneyAnalysisResponse,
    RealtimeMetricsResponse, PrivacyComplianceResponse,
    SystemHealthResponse
)
from brain_researcher.services.telemetry.models import (
    TelemetryEvent, UsageMetric, FeatureUsage, UserJourney,
    EventType, ServiceType, PrivacyLevel, MetricType, TelemetryConfiguration
)


class TestRequestResponseModels:
    """Test the API request and response models."""
    
    def test_event_collection_request(self):
        """Test event collection request model."""
        request = EventCollectionRequest(
            event_type=EventType.TOOL_INVOCATION,
            service=ServiceType.AGENT,
            feature_name="test_tool",
            action="execute",
            user_id="user123",
            duration_ms=500,
            success=True,
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )
        
        assert request.event_type == EventType.TOOL_INVOCATION
        assert request.service == ServiceType.AGENT
        assert request.feature_name == "test_tool"
        assert request.duration_ms == 500
        assert request.success is True
        
    def test_event_collection_response(self):
        """Test event collection response model."""
        response = EventCollectionResponse(
            event_id="evt_123",
            collected=True,
            message="Event collected successfully"
        )
        
        assert response.event_id == "evt_123"
        assert response.collected is True
        assert response.message == "Event collected successfully"
        assert isinstance(response.timestamp, datetime)
    
    def test_metrics_query_request_validation(self):
        """Test metrics query request validation."""
        # Valid request
        request = MetricsQueryRequest(
            start_time=datetime(2024, 1, 1, 12, 0, 0),
            end_time=datetime(2024, 1, 1, 18, 0, 0),
            granularity="hour",
            services=[ServiceType.AGENT]
        )
        
        assert request.start_time < request.end_time
        assert request.granularity == "hour"
        
        # Test future time validation
        with pytest.raises(ValueError):
            MetricsQueryRequest(
                start_time=datetime.utcnow() + timedelta(days=1),
                granularity="hour"
            )
    
    def test_feature_analysis_request(self):
        """Test feature analysis request model."""
        request = FeatureAnalysisRequest(
            feature_name="test_feature",
            service=ServiceType.WEB_UI,
            min_usage_count=10
        )
        
        assert request.feature_name == "test_feature"
        assert request.service == ServiceType.WEB_UI
        assert request.min_usage_count == 10
    
    def test_journey_analysis_request_validation(self):
        """Test journey analysis request validation."""
        request = JourneyAnalysisRequest(
            min_steps=5,
            max_journeys=200
        )
        
        assert request.min_steps == 5
        assert request.max_journeys == 200
        
        # Test validation bounds
        with pytest.raises(ValueError):
            JourneyAnalysisRequest(min_steps=1)  # Below minimum
        
        with pytest.raises(ValueError):
            JourneyAnalysisRequest(max_journeys=2000)  # Above maximum


class TestTelemetryService:
    """Test the TelemetryService coordination class."""
    
    @pytest.fixture
    def config(self):
        """Test configuration."""
        return TelemetryConfiguration(
            collection_enabled=True,
            sampling_rate=1.0,
            batch_size=10,
            anonymization_enabled=True
        )
    
    @pytest.fixture
    def telemetry_service(self, config):
        """Create test telemetry service."""
        return TelemetryService(config)
    
    def test_service_initialization(self, config):
        """Test service initialization."""
        service = TelemetryService(config)
        
        assert service.config == config
        assert service.collector is not None
        assert service.aggregator is not None
        assert service.privacy_controller is not None
        assert not service._running
        
        # Check that collector is connected to aggregator
        assert len(service.collector._processing_handlers) > 0
    
    @pytest.mark.asyncio
    async def test_service_lifecycle(self, telemetry_service):
        """Test service start/stop lifecycle."""
        # Initially not running
        assert not telemetry_service._running
        
        # Start service
        await telemetry_service.start()
        assert telemetry_service._running
        
        # Stop service
        await telemetry_service.stop()
        assert not telemetry_service._running
    
    @pytest.mark.asyncio
    async def test_service_idempotent_operations(self, telemetry_service):
        """Test that start/stop operations are idempotent."""
        # Multiple starts should not cause issues
        await telemetry_service.start()
        await telemetry_service.start()  # Second start should be no-op
        assert telemetry_service._running
        
        # Multiple stops should not cause issues
        await telemetry_service.stop()
        await telemetry_service.stop()  # Second stop should be no-op
        assert not telemetry_service._running


class TestAPIEndpoints:
    """Test the FastAPI endpoints using TestClient."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_telemetry_service(self):
        """Create mock telemetry service."""
        service = Mock(spec=TelemetryService)
        service.collector = Mock()
        service.aggregator = Mock()
        service.privacy_controller = Mock()
        service._running = True
        return service
    
    def test_collect_event_success(self, client, mock_telemetry_service):
        """Test successful event collection."""
        # Mock collector to return event ID
        mock_telemetry_service.collector.collect.return_value = "evt_123"
        
        # Override dependency
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/events/collect", json={
                "event_type": "tool_invocation",
                "service": "agent",
                "feature_name": "test_tool",
                "action": "execute",
                "success": True
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["event_id"] == "evt_123"
            assert data["collected"] is True
            assert "successfully" in data["message"]
            
            # Verify collector was called
            mock_telemetry_service.collector.collect.assert_called_once()
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()
    
    def test_collect_event_not_collected(self, client, mock_telemetry_service):
        """Test event not collected (sampling/rate limiting)."""
        # Mock collector to return None (not collected)
        mock_telemetry_service.collector.collect.return_value = None
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/events/collect", json={
                "event_type": "page_view",
                "service": "web_ui"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["event_id"] is None
            assert data["collected"] is False
            assert "not collected" in data["message"]
        finally:
            app.dependency_overrides.clear()
    
    def test_collect_event_error(self, client, mock_telemetry_service):
        """Test event collection error handling."""
        # Mock collector to raise exception
        mock_telemetry_service.collector.collect.side_effect = Exception("Collection failed")
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/events/collect", json={
                "event_type": "feature_access",
                "service": "agent"
            })
            
            assert response.status_code == 500
            assert "Failed to collect event" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()
    
    def test_collect_events_batch(self, client, mock_telemetry_service):
        """Test batch event collection."""
        # Mock collector to return different event IDs
        mock_telemetry_service.collector.collect.side_effect = [
            "evt_001", "evt_002", None  # Third event not collected
        ]
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            events = [
                {"event_type": "tool_invocation", "service": "agent"},
                {"event_type": "page_view", "service": "web_ui"},
                {"event_type": "feature_access", "service": "agent"}
            ]
            
            response = client.post("/telemetry/events/batch", json=events)
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_events"] == 3
            assert data["collected_count"] == 2
            assert data["failed_count"] == 0
            assert len(data["event_ids"]) == 2
            assert "evt_001" in data["event_ids"]
            assert "evt_002" in data["event_ids"]
        finally:
            app.dependency_overrides.clear()
    
    def test_collect_events_batch_size_limit(self, client, mock_telemetry_service):
        """Test batch size limit enforcement."""
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            # Create batch larger than limit (100)
            events = [{"event_type": "page_view", "service": "web_ui"} for _ in range(101)]
            
            response = client.post("/telemetry/events/batch", json=events)
            
            assert response.status_code == 400
            assert "exceed 100 events" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()
    
    def test_get_usage_metrics(self, client, mock_telemetry_service):
        """Test usage metrics endpoint."""
        # Create mock metrics
        mock_metrics = [
            UsageMetric(
                id="metric_001",
                metric_type=MetricType.USAGE_COUNT,
                name="Total Events",
                value=100.0,
                unit="events",
                period_start=datetime(2024, 1, 1, 12, 0, 0),
                period_end=datetime(2024, 1, 1, 18, 0, 0),
                granularity="hour",
                sample_size=100,
                privacy_level=PrivacyLevel.AGGREGATE_ONLY
            )
        ]
        
        mock_telemetry_service.aggregator.calculate_usage_metrics = AsyncMock(return_value=mock_metrics)
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/metrics", json={
                "granularity": "hour",
                "services": ["agent"]
            })
            
            assert response.status_code == 200
            data = response.json()
            assert len(data["metrics"]) == 1
            assert data["total_metrics"] == 1
            assert data["metrics"][0]["name"] == "Total Events"
        finally:
            app.dependency_overrides.clear()
    
    def test_analyze_feature_usage(self, client, mock_telemetry_service):
        """Test feature analysis endpoint."""
        # Create mock feature usage
        mock_features = [
            FeatureUsage(
                feature_name="test_feature",
                service=ServiceType.AGENT,
                total_uses=50,
                unique_users=10,
                success_rate=0.95,
                adoption_rate=0.8,
                retention_rate=0.7,
                frequency=5.0,
                trend="increasing",
                period_over_period_change=15.0,
                error_rate=0.05,
                period_start=datetime(2024, 1, 1, 0, 0, 0),
                period_end=datetime(2024, 1, 2, 0, 0, 0)
            )
        ]
        
        mock_telemetry_service.aggregator.analyze_feature_usage = AsyncMock(return_value=mock_features)
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/features/analyze", json={
                "feature_name": "test_feature",
                "service": "agent",
                "min_usage_count": 5
            })
            
            assert response.status_code == 200
            data = response.json()
            assert len(data["features"]) == 1
            assert data["features"][0]["feature_name"] == "test_feature"
            assert data["features"][0]["total_uses"] == 50
        finally:
            app.dependency_overrides.clear()
    
    def test_analyze_user_journeys(self, client, mock_telemetry_service):
        """Test user journey analysis endpoint."""
        # Create mock user journey
        mock_journeys = [
            UserJourney(
                journey_id="journey_001",
                user_hash="user_abc123",
                start_time=datetime(2024, 1, 1, 12, 0, 0),
                end_time=datetime(2024, 1, 1, 12, 30, 0),
                total_duration_minutes=30.0,
                steps=[
                    {"step_number": 1, "feature_name": "login", "action": "view"},
                    {"step_number": 2, "feature_name": "dashboard", "action": "view"},
                    {"step_number": 3, "feature_name": "analysis", "action": "execute"}
                ],
                completed_steps=3,
                total_steps=3,
                completion_rate=1.0,
                successful=True,
                common_path=True
            )
        ]
        
        mock_telemetry_service.aggregator.extract_user_journeys = AsyncMock(return_value=mock_journeys)
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/journeys/analyze", json={
                "min_steps": 2,
                "max_journeys": 100
            })
            
            assert response.status_code == 200
            data = response.json()
            assert len(data["journeys"]) == 1
            assert data["total_journeys"] == 1
            assert data["common_paths"] == 1
            assert data["avg_journey_length"] == 3.0
        finally:
            app.dependency_overrides.clear()
    
    def test_get_realtime_metrics(self, client, mock_telemetry_service):
        """Test real-time metrics endpoint."""
        mock_realtime_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "window_minutes": 15,
            "total_events": 250,
            "events_per_minute": 16.67,
            "services": {
                "agent": {"event_count": 150, "events_per_minute": 10.0},
                "web_ui": {"event_count": 100, "events_per_minute": 6.67}
            },
            "features": {"tool_1": 50, "tool_2": 30},
            "errors": {"total_errors": 5, "error_rate": 0.02}
        }
        
        mock_telemetry_service.aggregator.get_real_time_metrics = AsyncMock(return_value=mock_realtime_data)
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.get("/telemetry/realtime")
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_events"] == 250
            assert data["window_minutes"] == 15
            assert data["health_score"] > 0.0  # Should calculate health score
            assert "services" in data
            assert "features" in data
        finally:
            app.dependency_overrides.clear()
    
    def test_check_privacy_compliance(self, client, mock_telemetry_service):
        """Test privacy compliance check endpoint."""
        # Mock events and privacy checks
        mock_events = [
            TelemetryEvent(
                id="evt_001",
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI,
                anonymized=True,
                privacy_level=PrivacyLevel.AGGREGATE_ONLY
            )
        ]
        
        mock_telemetry_service.aggregator._events = mock_events
        mock_telemetry_service.privacy_controller.validate_data_compliance.return_value = (True, [])
        mock_telemetry_service.privacy_controller.get_privacy_summary.return_value = {
            "total_events": 1,
            "anonymized_events": 1,
            "anonymization_rate": 100.0
        }
        mock_telemetry_service.privacy_controller._audit_logs = []
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.get("/telemetry/privacy/compliance?days=7")
            
            assert response.status_code == 200
            data = response.json()
            assert data["is_compliant"] is True
            assert len(data["violations"]) == 0
            assert "privacy_summary" in data
            assert data["audit_log_entries"] == 0
        finally:
            app.dependency_overrides.clear()
    
    def test_get_privacy_audit_log(self, client, mock_telemetry_service):
        """Test privacy audit log retrieval."""
        mock_audit_logs = [
            {
                "timestamp": datetime.utcnow().isoformat(),
                "event_id": "evt_001",
                "operation": "anonymize_event",
                "pii_detected": ["email"],
                "anonymization_applied": ["user_id_hash", "email_hash"],
                "privacy_level_change": "internal_only -> aggregate_only",
                "compliance_flags": ["gdpr_compliant"]
            }
        ]
        
        mock_telemetry_service.privacy_controller.export_audit_log.return_value = mock_audit_logs
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.get("/telemetry/privacy/audit?days=7")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["event_id"] == "evt_001"
            assert "pii_detected" in data[0]
        finally:
            app.dependency_overrides.clear()
    
    def test_get_system_health(self, client, mock_telemetry_service):
        """Test system health endpoint."""
        mock_collector_stats = {
            "events_collected": 1000,
            "events_processed": 950,
            "processing_errors": 2
        }
        mock_aggregator_stats = {
            "total_events": 950,
            "active_journeys": 5
        }
        
        mock_telemetry_service.collector.get_stats.return_value = mock_collector_stats
        mock_telemetry_service.aggregator.get_aggregator_stats.return_value = mock_aggregator_stats
        mock_telemetry_service.privacy_controller._audit_logs = []
        mock_telemetry_service.privacy_controller._gdpr_enabled = True
        mock_telemetry_service.privacy_controller._retention_policies = {
            PrivacyLevel.PUBLIC: 365
        }
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.get("/telemetry/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "collector_stats" in data
            assert "aggregator_stats" in data
            assert "privacy_stats" in data
            assert data["privacy_stats"]["gdpr_mode"] is True
        finally:
            app.dependency_overrides.clear()
    
    def test_flush_events_admin(self, client, mock_telemetry_service):
        """Test admin flush events endpoint."""
        mock_telemetry_service.collector._flush_events = AsyncMock()
        mock_telemetry_service.collector.get_stats.return_value = {
            "events_processed": 100,
            "buffer_size": 0
        }
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/admin/flush")
            
            assert response.status_code == 200
            data = response.json()
            assert "flushed successfully" in data["message"]
            assert "events_processed" in data
            
            # Verify flush was called
            mock_telemetry_service.collector._flush_events.assert_called_once_with(force=True)
        finally:
            app.dependency_overrides.clear()
    
    def test_purge_expired_data_admin(self, client, mock_telemetry_service):
        """Test admin purge expired data endpoint."""
        mock_events = [
            TelemetryEvent(
                id="evt_001",
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI
            )
        ]
        
        mock_telemetry_service.aggregator._events = mock_events
        mock_telemetry_service.privacy_controller.purge_expired_data.return_value = ([], 1)
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/admin/purge?days=90")
            
            assert response.status_code == 200
            data = response.json()
            assert "Purged" in data["message"]
            assert data["purged_count"] == 1
            assert data["remaining_events"] == 0
        finally:
            app.dependency_overrides.clear()
    
    def test_invalid_request_validation(self, client):
        """Test API validation for invalid requests."""
        # Test invalid event type
        response = client.post("/telemetry/events/collect", json={
            "event_type": "invalid_type",
            "service": "agent"
        })
        assert response.status_code == 422  # Validation error
        
        # Test invalid granularity
        response = client.post("/telemetry/metrics", json={
            "granularity": "invalid_granularity"
        })
        assert response.status_code == 422  # Validation error
        
        # Test invalid min_steps (below minimum)
        response = client.post("/telemetry/journeys/analyze", json={
            "min_steps": 1
        })
        assert response.status_code == 422  # Validation error
    
    def test_error_handling(self, client, mock_telemetry_service):
        """Test general error handling in endpoints."""
        # Mock service to raise exception
        mock_telemetry_service.aggregator.calculate_usage_metrics = AsyncMock(
            side_effect=Exception("Aggregation failed")
        )
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = client.post("/telemetry/metrics", json={
                "granularity": "hour"
            })
            
            assert response.status_code == 500
            assert "Failed to get metrics" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestAsyncAPIEndpoints:
    """Test async functionality of API endpoints."""
    
    @pytest.fixture
    async def async_client(self):
        """Create async test client."""
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            yield client
    
    @pytest.fixture
    def mock_telemetry_service(self):
        """Create mock telemetry service for async tests."""
        service = Mock(spec=TelemetryService)
        service.collector = Mock()
        service.aggregator = Mock()
        service.privacy_controller = Mock()
        service._running = True
        return service
    
    async def test_concurrent_event_collection(self, async_client, mock_telemetry_service):
        """Test concurrent event collection."""
        mock_telemetry_service.collector.collect.return_value = "evt_concurrent"
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            # Create multiple concurrent requests
            tasks = []
            for i in range(10):
                task = async_client.post("/telemetry/events/collect", json={
                    "event_type": "tool_invocation",
                    "service": "agent",
                    "feature_name": f"tool_{i}"
                })
                tasks.append(task)
            
            # Wait for all requests to complete
            responses = await asyncio.gather(*tasks)
            
            # All should succeed
            assert all(r.status_code == 200 for r in responses)
            assert all(r.json()["collected"] for r in responses)
            
            # Verify collector was called for each request
            assert mock_telemetry_service.collector.collect.call_count == 10
        finally:
            app.dependency_overrides.clear()
    
    async def test_async_metrics_calculation(self, async_client, mock_telemetry_service):
        """Test async metrics calculation."""
        # Mock async aggregation
        mock_metrics = [
            UsageMetric(
                id="async_metric",
                metric_type=MetricType.USAGE_COUNT,
                name="Async Test Metric",
                value=42.0,
                unit="events",
                period_start=datetime(2024, 1, 1, 0, 0, 0),
                period_end=datetime(2024, 1, 2, 0, 0, 0),
                granularity="day",
                sample_size=42,
                privacy_level=PrivacyLevel.AGGREGATE_ONLY
            )
        ]
        
        async def slow_calculation(*args, **kwargs):
            await asyncio.sleep(0.1)  # Simulate async work
            return mock_metrics
        
        mock_telemetry_service.aggregator.calculate_usage_metrics = slow_calculation
        
        app.dependency_overrides[get_telemetry_service] = lambda: mock_telemetry_service
        
        try:
            response = await async_client.post("/telemetry/metrics", json={
                "granularity": "day"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert len(data["metrics"]) == 1
            assert data["metrics"][0]["name"] == "Async Test Metric"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.integration
class TestAPIIntegration:
    """Integration tests with real telemetry components."""
    
    @pytest.fixture
    def real_service(self):
        """Create real telemetry service for integration testing."""
        config = TelemetryConfiguration(
            collection_enabled=True,
            sampling_rate=1.0,
            batch_size=5,
            anonymization_enabled=False  # Disable for simpler testing
        )
        return TelemetryService(config)
    
    @pytest.fixture
    def integration_client(self, real_service):
        """Create test client with real service."""
        app.dependency_overrides[get_telemetry_service] = lambda: real_service
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()
    
    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self, integration_client, real_service):
        """Test complete end-to-end workflow."""
        # Start the service
        await real_service.start()
        
        try:
            # 1. Collect some events
            events = [
                {
                    "event_type": "tool_invocation",
                    "service": "agent",
                    "feature_name": "analysis_tool",
                    "action": "execute",
                    "duration_ms": 1000,
                    "success": True
                },
                {
                    "event_type": "page_view",
                    "service": "web_ui",
                    "feature_name": "dashboard",
                    "action": "view"
                },
                {
                    "event_type": "feature_access",
                    "service": "agent",
                    "feature_name": "analysis_tool",
                    "action": "configure",
                    "success": False,
                    "error_message": "Configuration error"
                }
            ]
            
            # Collect events
            for event in events:
                response = integration_client.post("/telemetry/events/collect", json=event)
                assert response.status_code == 200
                assert response.json()["collected"] is True
            
            # Wait for processing
            await asyncio.sleep(0.5)
            
            # Force flush to ensure events are processed
            flush_response = integration_client.post("/telemetry/admin/flush")
            assert flush_response.status_code == 200
            
            # 2. Check system health
            health_response = integration_client.get("/telemetry/health")
            assert health_response.status_code == 200
            health_data = health_response.json()
            assert health_data["status"] in ["healthy", "degraded"]
            assert health_data["collector_stats"]["events_collected"] >= 3
            
            # 3. Get usage metrics
            metrics_response = integration_client.post("/telemetry/metrics", json={
                "granularity": "hour"
            })
            assert metrics_response.status_code == 200
            metrics_data = metrics_response.json()
            assert len(metrics_data["metrics"]) > 0
            
            # 4. Analyze features
            features_response = integration_client.post("/telemetry/features/analyze", json={
                "min_usage_count": 1
            })
            assert features_response.status_code == 200
            features_data = features_response.json()
            # Should have at least one feature (analysis_tool used twice)
            assert features_data["total_features"] >= 1
            
            # 5. Get real-time metrics
            realtime_response = integration_client.get("/telemetry/realtime")
            assert realtime_response.status_code == 200
            realtime_data = realtime_response.json()
            assert realtime_data["total_events"] >= 3
            
            # 6. Check privacy compliance
            compliance_response = integration_client.get("/telemetry/privacy/compliance")
            assert compliance_response.status_code == 200
            compliance_data = compliance_response.json()
            assert isinstance(compliance_data["is_compliant"], bool)
        
        finally:
            # Clean up
            await real_service.stop()
    
    def test_batch_collection_integration(self, integration_client):
        """Test batch event collection with real service."""
        batch_events = [
            {
                "event_type": "tool_invocation",
                "service": "agent",
                "feature_name": f"tool_{i}",
                "duration_ms": i * 100
            }
            for i in range(10)
        ]
        
        response = integration_client.post("/telemetry/events/batch", json=batch_events)
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_events"] == 10
        assert data["collected_count"] >= 8  # Allow for some sampling/rate limiting
        assert len(data["event_ids"]) == data["collected_count"]
    
    def test_error_recovery_integration(self, integration_client):
        """Test error recovery in integration environment."""
        # Send malformed events that might cause processing errors
        problematic_events = [
            {
                "event_type": "tool_invocation",
                "service": "agent",
                "duration_ms": -100,  # Invalid duration
                "context": {"nested": {"deeply": {"nested": "value"}}}
            },
            {
                "event_type": "feature_access",
                "service": "web_ui",
                "metadata": {"huge_field": "x" * 10000}  # Very large field
            }
        ]
        
        # System should handle these gracefully
        for event in problematic_events:
            response = integration_client.post("/telemetry/events/collect", json=event)
            # Should either succeed or fail gracefully (not crash)
            assert response.status_code in [200, 400, 422, 500]
        
        # System should still be healthy after problematic events
        health_response = integration_client.get("/telemetry/health")
        assert health_response.status_code == 200


@pytest.mark.performance
class TestAPIPerformance:
    """Performance tests for the API endpoints."""
    
    def test_high_volume_event_collection(self):
        """Test high volume event collection performance."""
        config = TelemetryConfiguration(
            max_events_per_second=10000,
            queue_max_size=50000
        )
        service = TelemetryService(config)
        
        app.dependency_overrides[get_telemetry_service] = lambda: service
        client = TestClient(app)
        
        try:
            import time
            start_time = time.time()
            
            # Send many events rapidly
            successful_requests = 0
            for i in range(100):
                response = client.post("/telemetry/events/collect", json={
                    "event_type": "tool_invocation",
                    "service": "agent",
                    "feature_name": f"perf_tool_{i % 10}"
                })
                if response.status_code == 200:
                    successful_requests += 1
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Should handle 100 requests reasonably quickly
            assert duration < 5.0, f"Too slow: {duration:.2f}s for 100 requests"
            assert successful_requests >= 80  # Allow for some rate limiting
        finally:
            app.dependency_overrides.clear()
    
    def test_concurrent_api_requests(self):
        """Test concurrent API request handling."""
        service = TelemetryService()
        app.dependency_overrides[get_telemetry_service] = lambda: service
        
        try:
            import threading
            import time
            
            results = []
            errors = []
            
            def make_requests(thread_id: int):
                client = TestClient(app)
                for i in range(10):
                    try:
                        response = client.post("/telemetry/events/collect", json={
                            "event_type": "page_view",
                            "service": "web_ui",
                            "user_id": f"thread_{thread_id}_user_{i}"
                        })
                        results.append(response.status_code)
                    except Exception as e:
                        errors.append(str(e))
            
            # Start multiple threads
            threads = [threading.Thread(target=make_requests, args=(i,)) for i in range(5)]
            
            start_time = time.time()
            for thread in threads:
                thread.start()
            
            for thread in threads:
                thread.join(timeout=10)
            
            end_time = time.time()
            
            # Should complete without major issues
            assert len(errors) == 0, f"Concurrent request errors: {errors}"
            assert (end_time - start_time) < 10.0
            assert len(results) == 50  # 5 threads * 10 requests each
        finally:
            app.dependency_overrides.clear()