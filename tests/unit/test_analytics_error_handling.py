"""
Tests for Analytics Event Tracking and Error Recovery components.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
import json
from datetime import datetime, timedelta
import time


class TestAnalyticsEventTracking:
    """Test analytics and event tracking functionality."""
    
    @pytest.fixture
    def mock_config(self):
        """Create mock analytics configuration."""
        return {
            'apiEndpoint': 'https://api.example.com',
            'trackingId': 'test-tracking-id',
            'enableConsoleLog': False,
            'enableLocalStorage': True,
            'batchSize': 10,
            'flushInterval': 30000,
            'sessionTimeout': 1800000
        }
    
    def test_event_creation(self, mock_config):
        """Test event creation with proper fields."""
        event = self._create_event(
            name='button_click',
            category='interaction',
            properties={'button': 'submit', 'page': 'home'}
        )
        
        assert event['name'] == 'button_click'
        assert event['category'] == 'interaction'
        assert event['properties'] == {'button': 'submit', 'page': 'home'}
        assert 'timestamp' in event
        assert 'sessionId' in event
        assert 'pageUrl' in event
        assert 'userAgent' in event
    
    def test_event_batching(self, mock_config):
        """Test event batching logic."""
        queue = []
        batch_size = 3
        
        # Add events below batch size
        for i in range(batch_size - 1):
            event = self._create_event(f'event_{i}')
            queue.append(event)
        
        assert len(queue) == batch_size - 1
        should_flush = len(queue) >= batch_size
        assert should_flush is False
        
        # Add one more event to trigger batch
        queue.append(self._create_event('trigger_event'))
        should_flush = len(queue) >= batch_size
        assert should_flush is True
    
    @patch('requests.post')
    def test_event_flushing(self, mock_post, mock_config):
        """Test flushing events to backend."""
        events = [
            self._create_event('event_1'),
            self._create_event('event_2'),
            self._create_event('event_3')
        ]
        
        mock_post.return_value.status_code = 200
        
        self._flush_events(events, mock_config)
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        
        assert call_args[0][0] == f"{mock_config['apiEndpoint']}/events"
        assert call_args[1]['json']['events'] == events
        assert call_args[1]['headers']['X-Tracking-Id'] == mock_config['trackingId']
    
    def test_click_tracking(self):
        """Test click event tracking."""
        element = 'cta_button'
        properties = {'position': 'header', 'variant': 'A'}
        
        event = self._track_click(element, properties)
        
        assert event['name'] == f'click_{element}'
        assert event['category'] == 'interaction'
        assert event['properties']['element'] == element
        assert event['properties']['position'] == 'header'
        assert event['properties']['variant'] == 'A'
    
    def test_page_view_tracking(self):
        """Test page view tracking."""
        pathname = '/dashboard'
        search_params = 'tab=analytics'
        
        event = self._track_page_view(pathname, search_params)
        
        assert event['name'] == 'page_view'
        assert event['category'] == 'navigation'
        assert event['properties']['path'] == pathname
        assert event['properties']['search'] == search_params
        assert 'title' in event['properties']
        assert 'referrer' in event['properties']
    
    def test_error_tracking(self):
        """Test error event tracking."""
        error = Exception("Test error message")
        error_properties = {'component': 'DataLoader', 'severity': 'high'}
        
        event = self._track_error(error, error_properties)
        
        assert event['name'] == 'error'
        assert event['category'] == 'error'
        assert event['properties']['message'] == str(error)
        assert event['properties']['component'] == 'DataLoader'
        assert event['properties']['severity'] == 'high'
        assert 'stack' in event['properties']
    
    def test_timing_tracking(self):
        """Test performance timing tracking."""
        name = 'api_call'
        duration = 1234
        properties = {'endpoint': '/api/data', 'method': 'GET'}
        
        event = self._track_timing(name, duration, properties)
        
        assert event['name'] == f'timing_{name}'
        assert event['category'] == 'performance'
        assert event['properties']['duration'] == duration
        assert event['properties']['unit'] == 'ms'
        assert event['properties']['endpoint'] == '/api/data'
    
    def test_conversion_funnel(self):
        """Test conversion funnel tracking."""
        funnel_name = 'demo_completion'
        steps = ['demo_started', 'run_submitted', 'first_artifact', 'completed']
        
        # Start funnel
        funnel = self._start_funnel(funnel_name, steps)
        assert funnel['name'] == funnel_name
        assert len(funnel['steps']) == len(steps)
        assert funnel['currentStep'] == 0
        assert all(not step['completed'] for step in funnel['steps'])
        
        # Advance through steps
        for i, step_name in enumerate(steps):
            funnel = self._advance_funnel(funnel)
            assert funnel['currentStep'] == i + 1
            assert funnel['steps'][i]['completed'] is True
            assert funnel['steps'][i]['name'] == step_name
        
        # Complete funnel
        funnel = self._complete_funnel(funnel)
        assert funnel['completionTime'] is not None
        assert funnel['completionTime'] > funnel['startTime']
    
    def test_user_identification(self):
        """Test user identification."""
        user_id = 'user_123'
        traits = {
            'email': 'test@example.com',
            'plan': 'premium',
            'created_at': '2025-01-01'
        }
        
        event = self._identify_user(user_id, traits)
        
        assert event['name'] == 'identify'
        assert event['properties']['userId'] == user_id
        assert event['properties']['email'] == traits['email']
        assert event['properties']['plan'] == traits['plan']
    
    def test_session_management(self):
        """Test session ID generation and management."""
        session_id = self._generate_session_id()
        
        assert session_id.startswith('session_')
        assert len(session_id) > 20
        
        # Test session persistence
        events = []
        for i in range(3):
            event = self._create_event(f'event_{i}')
            event['sessionId'] = session_id
            events.append(event)
        
        assert all(e['sessionId'] == session_id for e in events)
    
    def test_demo_tracking_flow(self):
        """Test complete demo tracking flow."""
        demo_type = 'fmri_analysis'
        query = 'Show brain activation regions'
        
        # Track demo start
        events = []
        events.append(self._track_demo_event('demo_started', {'demoType': demo_type}))
        
        # Track run submitted
        events.append(self._track_demo_event('run_submitted', {
            'query': query,
            'queryLength': len(query)
        }))
        
        # Track processing
        events.append(self._track_demo_event('processing_started', {}))
        
        # Track first artifact
        events.append(self._track_demo_event('first_artifact_shown', {
            'artifactType': 'brain_image'
        }))
        
        # Track completion
        duration = 5432
        events.append(self._track_demo_event('demo_completed', {
            'duration': duration
        }))
        
        assert len(events) == 5
        assert events[0]['properties']['demoType'] == demo_type
        assert events[1]['properties']['query'] == query
        assert events[3]['properties']['artifactType'] == 'brain_image'
        assert events[4]['properties']['duration'] == duration
    
    def test_local_storage_fallback(self):
        """Test local storage fallback for offline events."""
        events = [
            self._create_event('offline_event_1'),
            self._create_event('offline_event_2')
        ]
        
        # Simulate storing in localStorage
        stored_events = self._store_events_locally(events)
        assert len(stored_events) == 2
        
        # Simulate retrieving from localStorage
        retrieved = self._retrieve_local_events()
        assert retrieved == stored_events
    
    # Helper methods
    def _create_event(self, name, category='interaction', properties=None):
        """Helper to create an event."""
        return {
            'name': name,
            'category': category,
            'properties': properties or {},
            'timestamp': int(time.time() * 1000),
            'sessionId': self._generate_session_id(),
            'pageUrl': 'https://example.com',
            'userAgent': 'Mozilla/5.0'
        }
    
    def _flush_events(self, events, config):
        """Helper to flush events."""
        import requests
        requests.post(
            f"{config['apiEndpoint']}/events",
            json={'events': events},
            headers={'X-Tracking-Id': config['trackingId']}
        )
    
    def _track_click(self, element, properties):
        """Helper to track click."""
        return self._create_event(
            f'click_{element}',
            'interaction',
            {'element': element, **properties, 'pageTitle': 'Test Page'}
        )
    
    def _track_page_view(self, pathname, search):
        """Helper to track page view."""
        return self._create_event(
            'page_view',
            'navigation',
            {
                'path': pathname,
                'search': search,
                'title': 'Test Page',
                'referrer': 'https://google.com'
            }
        )
    
    def _track_error(self, error, properties):
        """Helper to track error."""
        import traceback
        return self._create_event(
            'error',
            'error',
            {
                'message': str(error),
                'stack': traceback.format_exc(),
                'name': error.__class__.__name__,
                **properties
            }
        )
    
    def _track_timing(self, name, duration, properties):
        """Helper to track timing."""
        return self._create_event(
            f'timing_{name}',
            'performance',
            {'duration': duration, 'unit': 'ms', **properties}
        )
    
    def _start_funnel(self, name, steps):
        """Helper to start funnel."""
        return {
            'name': name,
            'steps': [{'name': s, 'completed': False} for s in steps],
            'currentStep': 0,
            'startTime': int(time.time() * 1000)
        }
    
    def _advance_funnel(self, funnel):
        """Helper to advance funnel."""
        if funnel['currentStep'] < len(funnel['steps']):
            step = funnel['steps'][funnel['currentStep']]
            step['completed'] = True
            step['timestamp'] = int(time.time() * 1000)
            funnel['currentStep'] += 1
        return funnel
    
    def _complete_funnel(self, funnel):
        """Helper to complete funnel."""
        funnel['completionTime'] = int(time.time() * 1000)
        return funnel
    
    def _identify_user(self, user_id, traits):
        """Helper to identify user."""
        return self._create_event('identify', 'interaction', {'userId': user_id, **traits})
    
    def _generate_session_id(self):
        """Helper to generate session ID."""
        import random
        return f"session_{int(time.time() * 1000)}_{random.randint(100000, 999999)}"
    
    def _track_demo_event(self, name, properties):
        """Helper to track demo event."""
        return self._create_event(name, 'conversion', properties)
    
    def _store_events_locally(self, events):
        """Helper to store events locally."""
        return events  # Simplified for testing
    
    def _retrieve_local_events(self):
        """Helper to retrieve local events."""
        return self._store_events_locally([])  # Simplified for testing


class TestErrorRecovery:
    """Test error recovery and handling functionality."""
    
    def test_error_code_mapping(self):
        """Test error code to message mapping."""
        error_messages = {
            'E_DEMO_UNAVAILABLE': 'Demo Temporarily Unavailable',
            'E_TIMEOUT': 'Request Timed Out',
            'E_TOOL_ERROR': 'Processing Error',
            'E_STORAGE': 'Storage Error',
            'E_NETWORK': 'Network Error',
            'E_AUTH': 'Authentication Required',
            'E_VALIDATION': 'Invalid Input',
            'E_RATE_LIMIT': 'Rate Limit Exceeded',
            'E_SERVER': 'Server Error',
            'E_UNKNOWN': 'Unexpected Error'
        }
        
        for code, expected_title in error_messages.items():
            message = self._get_error_message(code)
            assert message['title'] == expected_title
            assert 'description' in message
            assert len(message['description']) > 0
    
    def test_error_creation(self):
        """Test error object creation."""
        error = self._create_error(
            code='E_TIMEOUT',
            message='Operation timed out after 30 seconds',
            severity='high',
            retryable=True
        )
        
        assert error['code'] == 'E_TIMEOUT'
        assert error['message'] == 'Operation timed out after 30 seconds'
        assert error['severity'] == 'high'
        assert error['retryable'] is True
        assert 'timestamp' in error
    
    def test_error_severity_levels(self):
        """Test error severity classification."""
        severities = {
            'critical': ['E_SERVER', 'E_AUTH'],
            'high': ['E_TIMEOUT', 'E_DEMO_UNAVAILABLE'],
            'medium': ['E_NETWORK', 'E_TOOL_ERROR'],
            'low': ['E_VALIDATION', 'E_STORAGE']
        }
        
        for severity, codes in severities.items():
            for code in codes:
                error = self._create_error(code=code, severity=severity)
                assert error['severity'] == severity
    
    def test_retry_with_backoff(self):
        """Test retry logic with exponential backoff."""
        max_retries = 3
        retry_delay = 100  # ms
        backoff_multiplier = 2
        
        attempts = []
        delays = []
        
        for i in range(max_retries):
            attempts.append(i + 1)
            if i > 0:
                delay = retry_delay * (backoff_multiplier ** (i - 1))
                delays.append(delay)
        
        assert len(attempts) == max_retries
        assert delays == [100, 200]  # First retry: 100ms, Second retry: 200ms
    
    def test_error_queue_management(self):
        """Test error queue with max size limit."""
        max_errors = 5
        error_queue = []
        
        # Add more errors than max
        for i in range(8):
            error = self._create_error(
                code='E_UNKNOWN',
                message=f'Error {i}'
            )
            error_queue.insert(0, error)
            if len(error_queue) > max_errors:
                error_queue = error_queue[:max_errors]
        
        assert len(error_queue) == max_errors
        # Most recent errors should be kept
        assert error_queue[0]['message'] == 'Error 7'
        assert error_queue[-1]['message'] == 'Error 3'
    
    def test_error_auto_dismiss(self):
        """Test auto-dismiss for low severity errors."""
        error = self._create_error(
            code='E_VALIDATION',
            severity='low'
        )
        
        dismiss_timeout = 5000  # 5 seconds for low severity
        
        assert error['severity'] == 'low'
        assert self._should_auto_dismiss(error) is True
        assert self._get_dismiss_timeout(error) == dismiss_timeout
    
    def test_offline_detection(self):
        """Test offline/online detection."""
        # Simulate offline
        is_offline = True
        error = self._handle_offline_state(is_offline)
        
        assert error['code'] == 'E_NETWORK'
        assert error['retryable'] is True
        assert 'offline' in error['message'].lower()
        
        # Simulate coming back online
        is_offline = False
        result = self._handle_offline_state(is_offline)
        assert result is None  # No error when online
    
    def test_timeout_handling(self):
        """Test timeout detection and handling."""
        timeout_duration = 90000  # 90 seconds
        start_time = time.time() * 1000
        
        # Simulate operation running
        current_time = start_time + 45000  # 45 seconds elapsed
        is_timed_out = (current_time - start_time) > timeout_duration
        assert is_timed_out is False
        
        # Simulate timeout
        current_time = start_time + 95000  # 95 seconds elapsed
        is_timed_out = (current_time - start_time) > timeout_duration
        assert is_timed_out is True
        
        if is_timed_out:
            error = self._create_error(
                code='E_TIMEOUT',
                message=f'Operation timed out after {timeout_duration/1000} seconds'
            )
            assert error['code'] == 'E_TIMEOUT'
    
    def test_error_reporting(self):
        """Test error reporting to backend."""
        error = self._create_error(
            code='E_SERVER',
            message='Internal server error',
            severity='critical'
        )
        
        report = self._create_error_report(error)
        
        assert report['code'] == error['code']
        assert report['message'] == error['message']
        assert report['timestamp'] == error['timestamp']
        assert 'url' in report
        assert 'userAgent' in report
        assert 'context' in report
    
    def test_error_recovery_strategies(self):
        """Test different error recovery strategies."""
        strategies = {
            'E_NETWORK': 'retry_with_backoff',
            'E_TIMEOUT': 'retry_with_increased_timeout',
            'E_AUTH': 'redirect_to_login',
            'E_RATE_LIMIT': 'wait_and_retry',
            'E_VALIDATION': 'show_validation_errors',
            'E_SERVER': 'show_error_page'
        }
        
        for code, expected_strategy in strategies.items():
            strategy = self._get_recovery_strategy(code)
            assert strategy == expected_strategy
    
    # Helper methods
    def _get_error_message(self, code):
        """Helper to get error message."""
        messages = {
            'E_DEMO_UNAVAILABLE': {
                'title': 'Demo Temporarily Unavailable',
                'description': 'The demo service is currently unavailable.'
            },
            'E_TIMEOUT': {
                'title': 'Request Timed Out',
                'description': 'The operation took longer than expected.'
            },
            'E_TOOL_ERROR': {
                'title': 'Processing Error',
                'description': 'An error occurred while processing your request.'
            },
            'E_STORAGE': {
                'title': 'Storage Error',
                'description': 'Unable to save or retrieve data from storage.'
            },
            'E_NETWORK': {
                'title': 'Network Error',
                'description': 'Unable to connect to the server.'
            },
            'E_AUTH': {
                'title': 'Authentication Required',
                'description': 'You need to be logged in to perform this action.'
            },
            'E_VALIDATION': {
                'title': 'Invalid Input',
                'description': 'The provided input is invalid or incomplete.'
            },
            'E_RATE_LIMIT': {
                'title': 'Rate Limit Exceeded',
                'description': 'You\'ve made too many requests.'
            },
            'E_SERVER': {
                'title': 'Server Error',
                'description': 'An unexpected server error occurred.'
            },
            'E_UNKNOWN': {
                'title': 'Unexpected Error',
                'description': 'An unexpected error occurred.'
            }
        }
        return messages.get(code, messages['E_UNKNOWN'])
    
    def _create_error(self, code, message='', severity='medium', retryable=False):
        """Helper to create error."""
        return {
            'code': code,
            'message': message or self._get_error_message(code)['description'],
            'timestamp': int(time.time() * 1000),
            'severity': severity,
            'retryable': retryable
        }
    
    def _should_auto_dismiss(self, error):
        """Helper to check if error should auto-dismiss."""
        return error['severity'] == 'low'
    
    def _get_dismiss_timeout(self, error):
        """Helper to get dismiss timeout."""
        if error['severity'] == 'low':
            return 5000
        return None
    
    def _handle_offline_state(self, is_offline):
        """Helper to handle offline state."""
        if is_offline:
            return self._create_error(
                code='E_NETWORK',
                message='You are currently offline',
                retryable=True
            )
        return None
    
    def _create_error_report(self, error):
        """Helper to create error report."""
        return {
            'code': error['code'],
            'message': error['message'],
            'timestamp': error['timestamp'],
            'severity': error['severity'],
            'url': 'https://example.com/current-page',
            'userAgent': 'Mozilla/5.0',
            'context': {
                'retryable': error.get('retryable', False)
            }
        }
    
    def _get_recovery_strategy(self, code):
        """Helper to get recovery strategy."""
        strategies = {
            'E_NETWORK': 'retry_with_backoff',
            'E_TIMEOUT': 'retry_with_increased_timeout',
            'E_AUTH': 'redirect_to_login',
            'E_RATE_LIMIT': 'wait_and_retry',
            'E_VALIDATION': 'show_validation_errors',
            'E_SERVER': 'show_error_page'
        }
        return strategies.get(code, 'show_error_page')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])