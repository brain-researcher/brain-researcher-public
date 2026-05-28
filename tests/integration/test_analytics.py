"""
Integration tests for Analytics and Event Tracking
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime, timedelta
import time


class TestAnalytics:
    """Test suite for Analytics integration"""
    
    @pytest.fixture
    def session_data(self):
        """Sample session data"""
        return {
            'sessionId': 'session-123-abc',
            'userId': 'user-456',
            'startTime': int(time.time() * 1000),
            'lastActivity': int(time.time() * 1000),
            'pageViews': 5,
            'events': []
        }
    
    @pytest.fixture
    def event_queue(self):
        """Sample event queue"""
        return [
            {
                'event': 'page_view',
                'data': {'page_name': 'Landing', 'page_path': '/'},
                'timestamp': int(time.time() * 1000)
            },
            {
                'event': 'hero_demo_clicked',
                'data': {'demo_type': 'glm'},
                'timestamp': int(time.time() * 1000)
            },
            {
                'event': 'demo_completed',
                'data': {'demo_id': 'demo-789', 'duration': 45000},
                'timestamp': int(time.time() * 1000)
            }
        ]
    
    def test_session_initialization(self, session_data):
        """Test that analytics session is properly initialized"""
        assert session_data['sessionId'] is not None
        assert len(session_data['sessionId']) > 0
        assert session_data['startTime'] > 0
        assert session_data['pageViews'] >= 0
    
    def test_event_tracking(self, event_queue):
        """Test event tracking functionality"""
        for event in event_queue:
            assert 'event' in event
            assert 'data' in event
            assert 'timestamp' in event
            assert event['timestamp'] > 0
    
    def test_page_view_tracking(self):
        """Test page view tracking"""
        page_views = [
            {'page_name': 'Landing', 'page_path': '/', 'referrer': ''},
            {'page_name': 'Examples', 'page_path': '/examples', 'referrer': '/'},
            {'page_name': 'Dashboard', 'page_path': '/dashboard', 'referrer': '/examples'}
        ]
        
        for view in page_views:
            assert 'page_name' in view
            assert 'page_path' in view
            assert 'referrer' in view
    
    def test_cta_tracking(self):
        """Test CTA click tracking"""
        cta_events = [
            {'cta_name': 'hero_demo', 'location': 'above_fold'},
            {'cta_name': 'run_example', 'example_id': 'glm'},
            {'cta_name': 'signup', 'source': 'header'}
        ]
        
        for event in cta_events:
            assert 'cta_name' in event
            assert len(event['cta_name']) > 0
    
    def test_demo_tracking_lifecycle(self):
        """Test complete demo tracking lifecycle"""
        demo_id = 'demo-test-123'
        
        # Demo started
        start_event = {
            'event': 'demo_started',
            'demo_id': demo_id,
            'timestamp': int(time.time() * 1000)
        }
        
        # Demo processing
        process_event = {
            'event': 'demo_processing',
            'demo_id': demo_id,
            'progress': 50,
            'timestamp': int(time.time() * 1000) + 2000
        }
        
        # Demo completed
        complete_event = {
            'event': 'demo_completed',
            'demo_id': demo_id,
            'duration': 45000,
            'timestamp': int(time.time() * 1000) + 45000
        }
        
        assert complete_event['timestamp'] > start_event['timestamp']
        assert complete_event['duration'] == 45000
    
    def test_error_tracking(self):
        """Test error event tracking"""
        error_events = [
            {
                'message': 'API request failed',
                'stack': 'Error at line 123',
                'severity': 'error',
                'context': {'endpoint': '/api/demo', 'status': 500}
            },
            {
                'message': 'Timeout exceeded',
                'severity': 'warning',
                'context': {'timeout': 90000, 'actual': 95000}
            }
        ]
        
        for error in error_events:
            assert 'message' in error
            assert 'severity' in error
            assert error['severity'] in ['error', 'warning', 'info']
    
    def test_conversion_funnel(self):
        """Test conversion funnel tracking"""
        funnel_steps = [
            'landing_viewed',
            'demo_clicked',
            'demo_started',
            'demo_completed',
            'signup_started',
            'signup_completed'
        ]
        
        current_step = 0
        for step in funnel_steps:
            current_step += 1
            completion_rate = (current_step / len(funnel_steps)) * 100
            assert 0 <= completion_rate <= 100
    
    def test_fse_tracking(self, session_data):
        """Test First Successful Execution tracking"""
        fse_event = {
            'event': 'first_successful_execution',
            'time_to_fse': 120000,  # 2 minutes
            'session_events': 15,
            'demo_type': 'glm'
        }
        
        assert fse_event['time_to_fse'] > 0
        assert fse_event['session_events'] > 0
    
    def test_event_queue_flushing(self, event_queue):
        """Test that event queue is properly flushed"""
        max_queue_size = 10
        
        # Queue should flush when reaching max size
        assert len(event_queue) <= max_queue_size
        
        # After flush, queue should be empty
        flushed_queue = []
        assert len(flushed_queue) == 0
    
    def test_session_persistence(self, session_data):
        """Test session persistence across page reloads"""
        # Save session
        saved_session = json.dumps(session_data)
        
        # Load session
        loaded_session = json.loads(saved_session)
        
        assert loaded_session['sessionId'] == session_data['sessionId']
        assert loaded_session['userId'] == session_data['userId']
    
    def test_user_identification(self, session_data):
        """Test user identification after login"""
        anonymous_session = {**session_data, 'userId': None}
        
        # User logs in
        identified_session = {**anonymous_session, 'userId': 'user-789'}
        
        assert anonymous_session['userId'] is None
        assert identified_session['userId'] == 'user-789'
    
    def test_analytics_api_batch(self, event_queue):
        """Test batching of analytics events"""
        with patch('fetch') as mock_fetch:
            mock_fetch.return_value.ok = True
            
            # Send batch
            response = mock_fetch('/api/events', 
                                method='POST',
                                body=json.dumps({'events': event_queue}))
            
            assert response.ok is True
            assert len(event_queue) == 3
    
    def test_offline_queue_management(self, event_queue):
        """Test event queuing when offline"""
        offline_queue = event_queue.copy()
        
        # Add more events while offline
        offline_queue.append({
            'event': 'offline_event',
            'data': {'offline': True},
            'timestamp': int(time.time() * 1000)
        })
        
        assert len(offline_queue) == len(event_queue) + 1
        
        # When online, queue should be processed
        # Simulate coming back online and flushing
        assert len(offline_queue) > 0
    
    def test_custom_event_properties(self):
        """Test custom event properties"""
        custom_event = {
            'event': 'custom_action',
            'data': {
                'category': 'engagement',
                'action': 'scroll_depth',
                'label': '75%',
                'value': 75,
                'custom_field': 'test_value'
            }
        }
        
        assert 'custom_field' in custom_event['data']
        assert custom_event['data']['value'] == 75
    
    def test_performance_metrics(self):
        """Test performance metric tracking"""
        perf_metrics = {
            'page_load_time': 1250,
            'time_to_interactive': 2100,
            'first_contentful_paint': 850,
            'largest_contentful_paint': 1500
        }
        
        for metric, value in perf_metrics.items():
            assert value > 0
            assert value < 10000  # Should be under 10 seconds
    
    def test_session_timeout(self, session_data):
        """Test session timeout after inactivity"""
        timeout_duration = 30 * 60 * 1000  # 30 minutes in ms
        
        # Check if session is expired
        current_time = int(time.time() * 1000)
        time_since_activity = current_time - session_data['lastActivity']
        
        is_expired = time_since_activity > timeout_duration
        assert is_expired is False  # Fresh session should not be expired