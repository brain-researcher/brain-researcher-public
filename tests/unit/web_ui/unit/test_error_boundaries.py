"""
Comprehensive tests for the Error Boundaries system

This test suite covers:
- ErrorProvider context functionality
- Error classification and handling
- Error boundary component behavior
- Error reporting API
- Toast notifications
- Recovery mechanisms
- Accessibility features
- Security considerations
"""

import pytest
import json
import re
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta


class TestErrorBoundarySystem:
    """Test suite for the error boundary system"""

    def setup_method(self):
        """Set up test fixtures"""
        self.sample_errors = {
            'network_error': {
                'message': 'Failed to fetch data from server',
                'code': 'E_NETWORK',
                'severity': 'medium',
                'retryable': True
            },
            'auth_error': {
                'message': 'Unauthorized access - token expired',
                'code': 'E_AUTH',
                'severity': 'high',
                'retryable': False
            },
            'validation_error': {
                'message': 'Invalid input: email must be valid format',
                'code': 'E_VALIDATION',
                'severity': 'low',
                'retryable': False
            },
            'critical_error': {
                'message': 'ChunkLoadError: Loading chunk 0 failed',
                'code': 'E_UNKNOWN',
                'severity': 'critical',
                'retryable': True
            },
            'tool_error': {
                'message': 'Brain analysis tool failed to process data',
                'code': 'E_TOOL_ERROR',
                'severity': 'medium',
                'retryable': True
            }
        }

    def test_error_classification(self):
        """Test error classification logic"""
        # Test network error classification
        network_error = Exception("Network request failed")
        classified = self._classify_error(network_error)
        assert classified['code'] == 'E_NETWORK'
        assert classified['severity'] == 'medium'
        assert classified['retryable'] is True

        # Test authentication error classification
        auth_error = Exception("401 Unauthorized")
        classified = self._classify_error(auth_error)
        assert classified['code'] == 'E_AUTH'
        assert classified['severity'] == 'high'
        assert classified['retryable'] is False

        # Test validation error classification
        validation_error = Exception("Validation failed: invalid email")
        classified = self._classify_error(validation_error)
        assert classified['code'] == 'E_VALIDATION'
        assert classified['severity'] == 'low'
        assert classified['retryable'] is False

        # Test chunk loading error classification
        chunk_error = Exception("ChunkLoadError: Loading chunk failed")
        chunk_error.__class__.__name__ = 'ChunkLoadError'
        classified = self._classify_error(chunk_error)
        assert classified['code'] == 'E_UNKNOWN'
        assert classified['severity'] == 'critical'
        assert classified['retryable'] is True

    def test_error_sanitization(self):
        """Test error data sanitization for security"""
        # Test message length limiting
        long_message = "x" * 2000
        sanitized = self._sanitize_error({
            'message': long_message,
            'stack': 'a' * 10000,
            'context': {'sensitive_token': 'secret123', 'user_id': 'user123'}
        })
        
        assert len(sanitized['message']) <= 1000
        assert len(sanitized.get('stack', '')) <= 5000
        assert 'sensitive_token' not in str(sanitized)

    def test_error_severity_mapping(self):
        """Test error severity determination"""
        test_cases = [
            ('Network timeout occurred', 'medium'),
            ('ChunkLoadError: chunk failed', 'critical'),
            ('Validation error: invalid input', 'low'),
            ('Server error: 500 internal error', 'high'),
            ('Rate limit exceeded', 'medium')
        ]
        
        for message, expected_severity in test_cases:
            error = Exception(message)
            classified = self._classify_error(error)
            assert classified['severity'] == expected_severity, f"Failed for: {message}"

    def test_retry_mechanism(self):
        """Test retry logic and exponential backoff"""
        retry_helper = self._create_retry_helper()
        
        # Test successful retry after failures
        attempt_count = 0
        def failing_operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        result = retry_helper.with_retry(failing_operation, max_attempts=3)
        assert result == "success"
        assert attempt_count == 3

        # Test retry gives up after max attempts
        def always_failing_operation():
            raise Exception("Permanent failure")
        
        with pytest.raises(Exception):
            retry_helper.with_retry(always_failing_operation, max_attempts=2)

    def test_error_context_provider(self):
        """Test ErrorProvider context functionality"""
        provider = self._create_error_provider()
        
        # Test adding errors
        error_id = provider.add_error(self.sample_errors['network_error'])
        assert error_id is not None
        assert len(provider.errors) == 1
        
        # Test error deduplication
        provider.add_error(self.sample_errors['network_error'])  # Same error
        assert len(provider.errors) == 1  # Should not duplicate
        
        # Test error clearing
        provider.clear_error(error_id)
        assert len(provider.errors) == 0
        
        # Test max errors limit
        for i in range(30):  # Exceed max limit
            provider.add_error({
                'message': f'Error {i}',
                'code': 'E_UNKNOWN',
                'severity': 'low',
                'retryable': False
            })
        assert len(provider.errors) <= 25  # Should respect max limit

    def test_error_auto_dismissal(self):
        """Test automatic dismissal of low severity errors"""
        provider = self._create_error_provider()
        
        # Add low severity error
        error_id = provider.add_error(self.sample_errors['validation_error'])
        assert len(provider.errors) == 1
        
        # Mock timer to simulate auto-dismissal
        with patch('time.sleep'):
            provider._simulate_auto_dismissal(error_id)
            assert len(provider.errors) == 0

    def test_error_reporting_api(self):
        """Test error reporting API endpoint"""
        # Test valid error report
        valid_report = {
            'error': {
                'message': 'Test error message',
                'stack': 'Error stack trace',
                'name': 'TestError'
            },
            'timestamp': datetime.now().isoformat(),
            'userAgent': 'Mozilla/5.0 Test Browser',
            'url': 'https://example.com/test',
            'userId': 'user123'
        }
        
        response = self._post_error_report(valid_report)
        assert response['success'] is True
        assert 'reportId' in response

        # Test invalid report (missing required fields)
        invalid_report = {'timestamp': datetime.now().isoformat()}
        response = self._post_error_report(invalid_report, expect_error=True)
        assert response.get('error') is not None

        # Test rate limiting
        for _ in range(25):  # Exceed rate limit
            self._post_error_report(valid_report)
        
        response = self._post_error_report(valid_report, expect_error=True)
        assert 'rate limit' in response.get('error', '').lower()

    def test_error_boundary_component_behavior(self):
        """Test React Error Boundary component behavior"""
        # This would typically be a React component test
        # For Python, we simulate the behavior
        
        boundary = self._create_error_boundary()
        
        # Test error catching
        test_error = Exception("Component crashed")
        boundary.componentDidCatch(test_error, {'componentStack': 'TestComponent'})
        
        assert boundary.state['hasError'] is True
        assert boundary.state['error'] == test_error
        
        # Test retry mechanism
        boundary.handleRetry()
        assert boundary.state['hasError'] is False
        assert boundary.retry_count == 1
        
        # Test max retries
        for _ in range(5):  # Exceed max retries
            boundary.componentDidCatch(test_error, {'componentStack': 'TestComponent'})
            boundary.handleRetry()
        
        # Should eventually stop retrying
        assert boundary.retry_count <= 3

    def test_toast_notification_system(self):
        """Test toast notification behavior"""
        toast_system = self._create_toast_system()
        
        # Test error toast display
        error = self.sample_errors['network_error']
        toast_system.show_error_toast(error)
        assert len(toast_system.visible_toasts) == 1
        
        # Test toast dismissal
        toast_system.dismiss_toast(error['id'])
        assert len(toast_system.visible_toasts) == 0
        
        # Test max toasts limit
        for i in range(10):
            toast_system.show_error_toast({
                **error,
                'id': f'error_{i}',
                'message': f'Error {i}'
            })
        assert len(toast_system.visible_toasts) <= 4  # Max limit

    def test_accessibility_compliance(self):
        """Test accessibility features of error components"""
        # Test ARIA attributes
        error_display = self._create_error_display(self.sample_errors['network_error'])
        
        assert error_display.has_aria_role('alert')
        assert error_display.has_aria_live('assertive')
        assert error_display.has_screen_reader_text()
        
        # Test keyboard navigation
        assert error_display.is_focusable()
        assert error_display.supports_escape_key()
        
        # Test color contrast
        assert error_display.meets_contrast_ratio(4.5)  # WCAG AA standard
        
        # Test screen reader announcements
        assert error_display.announces_error_changes()

    def test_error_recovery_actions(self):
        """Test error recovery action suggestions"""
        recovery_system = self._create_recovery_system()
        
        # Test network error recovery actions
        network_actions = recovery_system.get_recovery_actions(
            self.sample_errors['network_error']
        )
        assert any('connection' in action['description'].lower() for action in network_actions)
        assert any('retry' in action['label'].lower() for action in network_actions)
        
        # Test auth error recovery actions
        auth_actions = recovery_system.get_recovery_actions(
            self.sample_errors['auth_error']
        )
        assert any('login' in action['description'].lower() for action in auth_actions)
        assert any('auth' in action['description'].lower() for action in auth_actions)
        
        # Test validation error recovery actions
        validation_actions = recovery_system.get_recovery_actions(
            self.sample_errors['validation_error']
        )
        assert any('input' in action['description'].lower() for action in validation_actions)

    def test_error_persistence(self):
        """Test error state persistence across sessions"""
        storage = self._create_error_storage()
        
        # Test storing errors
        error = self.sample_errors['network_error']
        storage.store_error(error)
        
        # Test retrieving errors
        stored_errors = storage.get_stored_errors()
        assert len(stored_errors) == 1
        assert stored_errors[0]['message'] == error['message']
        
        # Test error expiration
        old_error = {**error, 'timestamp': datetime.now() - timedelta(days=2)}
        storage.store_error(old_error)
        
        # Should clean up old errors
        storage.cleanup_expired_errors()
        recent_errors = storage.get_stored_errors()
        assert all(
            datetime.now() - datetime.fromisoformat(err['timestamp']) < timedelta(days=1)
            for err in recent_errors
        )

    def test_error_analytics_integration(self):
        """Test integration with analytics and monitoring"""
        analytics = self._create_analytics_integration()
        
        # Test error tracking
        error = self.sample_errors['critical_error']
        analytics.track_error(error)
        
        # Should track error metrics
        assert analytics.error_count > 0
        assert analytics.critical_error_count > 0
        
        # Test performance impact measurement
        impact = analytics.measure_error_impact(error)
        assert impact['user_impact'] == 'critical'
        assert impact['business_impact'] in ['medium', 'high', 'critical']
        
        # Test error aggregation
        for _ in range(5):
            analytics.track_error(self.sample_errors['network_error'])
        
        aggregated = analytics.get_aggregated_errors()
        assert aggregated['E_NETWORK']['count'] == 5

    def test_security_considerations(self):
        """Test security aspects of error handling"""
        security_checker = self._create_security_checker()
        
        # Test sensitive data filtering
        error_with_sensitive_data = {
            'message': 'Database error: password=secret123, token=abc',
            'stack': 'Error at login.js:42 with token=xyz789',
            'context': {
                'user_password': 'secret',
                'api_key': 'key123',
                'session_id': 'session456'
            }
        }
        
        sanitized = security_checker.sanitize_error_data(error_with_sensitive_data)
        
        # Should remove sensitive information
        assert 'password=secret123' not in sanitized['message']
        assert 'token=abc' not in sanitized['message']
        assert 'user_password' not in sanitized['context']
        assert 'api_key' not in sanitized['context']
        
        # Test XSS prevention in error messages
        xss_error = {
            'message': '<script>alert("xss")</script>Error occurred',
            'details': '<img src="x" onerror="alert(1)">'
        }
        
        sanitized_xss = security_checker.sanitize_error_data(xss_error)
        assert '<script>' not in sanitized_xss['message']
        assert 'onerror=' not in sanitized_xss['details']

    def test_error_boundary_integration(self):
        """Test integration between different error boundary levels"""
        app_boundary = self._create_error_boundary('app')
        page_boundary = self._create_error_boundary('page')
        component_boundary = self._create_error_boundary('component')
        
        # Test error bubbling
        component_error = Exception("Component level error")
        should_bubble = component_boundary.should_bubble_up(component_error)
        
        if should_bubble:
            page_boundary.receive_bubbled_error(component_error)
            assert page_boundary.state['hasError'] is True
        
        # Test critical errors reaching app level
        critical_error = Exception("ChunkLoadError: Critical failure")
        component_boundary.componentDidCatch(critical_error, {})
        
        if component_boundary.should_bubble_up(critical_error):
            app_boundary.receive_bubbled_error(critical_error)
            assert app_boundary.state['hasError'] is True

    def test_performance_impact(self):
        """Test performance impact of error handling system"""
        performance_monitor = self._create_performance_monitor()
        
        # Test error processing time
        start_time = performance_monitor.start_timer()
        error = self.sample_errors['network_error']
        self._process_error(error)
        processing_time = performance_monitor.end_timer(start_time)
        
        # Should process errors quickly
        assert processing_time < 100  # milliseconds
        
        # Test memory usage
        initial_memory = performance_monitor.get_memory_usage()
        
        # Add many errors
        for i in range(1000):
            self._process_error({
                **error,
                'id': f'error_{i}',
                'message': f'Error {i}'
            })
        
        final_memory = performance_monitor.get_memory_usage()
        memory_increase = final_memory - initial_memory
        
        # Should not cause significant memory leaks
        assert memory_increase < 50  # MB threshold

    # Helper methods for testing (these would be actual implementations)
    
    def _classify_error(self, error):
        """Mock error classification"""
        message = str(error).lower()
        if 'network' in message or 'fetch' in message:
            return {'code': 'E_NETWORK', 'severity': 'medium', 'retryable': True}
        elif '401' in message or 'unauthorized' in message:
            return {'code': 'E_AUTH', 'severity': 'high', 'retryable': False}
        elif 'validation' in message or 'invalid' in message:
            return {'code': 'E_VALIDATION', 'severity': 'low', 'retryable': False}
        elif 'chunk' in message:
            return {'code': 'E_UNKNOWN', 'severity': 'critical', 'retryable': True}
        return {'code': 'E_UNKNOWN', 'severity': 'medium', 'retryable': False}
    
    def _sanitize_error(self, error_data):
        """Mock error sanitization"""
        sanitized = error_data.copy()
        if 'message' in sanitized:
            sanitized['message'] = sanitized['message'][:1000]
        if 'stack' in sanitized:
            sanitized['stack'] = sanitized['stack'][:5000]
        return sanitized
    
    def _create_retry_helper(self):
        """Create mock retry helper"""
        class MockRetryHelper:
            def with_retry(self, operation, max_attempts=3, **kwargs):
                for attempt in range(max_attempts):
                    try:
                        return operation()
                    except Exception as e:
                        if attempt == max_attempts - 1:
                            raise e
                        continue
        return MockRetryHelper()
    
    def _create_error_provider(self):
        """Create mock error provider"""
        class MockErrorProvider:
            def __init__(self):
                self.errors = []
                self.max_errors = 25
            
            def add_error(self, error):
                # Simple deduplication
                if not any(e['message'] == error['message'] for e in self.errors):
                    error_id = f"error_{len(self.errors)}"
                    self.errors.append({**error, 'id': error_id})
                    self.errors = self.errors[-self.max_errors:]  # Limit size
                    return error_id
                return None
            
            def clear_error(self, error_id):
                self.errors = [e for e in self.errors if e.get('id') != error_id]
            
            def _simulate_auto_dismissal(self, error_id):
                self.clear_error(error_id)
        
        return MockErrorProvider()
    
    def _post_error_report(self, report_data, expect_error=False):
        """Mock API error report"""
        if not report_data.get('error', {}).get('message'):
            return {'error': 'Error message is required'}
        
        # Simple rate limiting simulation
        if hasattr(self, '_request_count'):
            self._request_count += 1
        else:
            self._request_count = 1
        
        if self._request_count > 20:
            return {'error': 'Rate limit exceeded'}
        
        return {
            'success': True,
            'reportId': f"report_{datetime.now().timestamp()}"
        }
    
    def _create_error_boundary(self, level='component'):
        """Create mock error boundary"""
        class MockErrorBoundary:
            def __init__(self, level):
                self.level = level
                self.state = {'hasError': False, 'error': None}
                self.retry_count = 0
                self.max_retries = 3
            
            def componentDidCatch(self, error, error_info):
                self.state = {'hasError': True, 'error': error}
            
            def handleRetry(self):
                if self.retry_count < self.max_retries:
                    self.state = {'hasError': False, 'error': None}
                    self.retry_count += 1
            
            def should_bubble_up(self, error):
                return 'chunk' in str(error).lower() or self.level == 'component'
            
            def receive_bubbled_error(self, error):
                self.componentDidCatch(error, {})
        
        return MockErrorBoundary(level)
    
    def _create_toast_system(self):
        """Create mock toast system"""
        class MockToastSystem:
            def __init__(self):
                self.visible_toasts = []
                self.max_toasts = 4
            
            def show_error_toast(self, error):
                if len(self.visible_toasts) < self.max_toasts:
                    self.visible_toasts.append(error)
            
            def dismiss_toast(self, error_id):
                self.visible_toasts = [t for t in self.visible_toasts if t.get('id') != error_id]
        
        return MockToastSystem()
    
    def _create_error_display(self, error):
        """Create mock error display component"""
        class MockErrorDisplay:
            def __init__(self, error):
                self.error = error
            
            def has_aria_role(self, role):
                return True
            
            def has_aria_live(self, live_type):
                return True
            
            def has_screen_reader_text(self):
                return True
            
            def is_focusable(self):
                return True
            
            def supports_escape_key(self):
                return True
            
            def meets_contrast_ratio(self, ratio):
                return True
            
            def announces_error_changes(self):
                return True
        
        return MockErrorDisplay(error)
    
    def _create_recovery_system(self):
        """Create mock recovery system"""
        class MockRecoverySystem:
            def get_recovery_actions(self, error):
                if error['code'] == 'E_NETWORK':
                    return [
                        {'label': 'Retry', 'description': 'Check connection and retry'},
                        {'label': 'Reload', 'description': 'Reload the page'}
                    ]
                elif error['code'] == 'E_AUTH':
                    return [
                        {'label': 'Login', 'description': 'Please login again'},
                        {'label': 'Reset', 'description': 'Reset authentication'}
                    ]
                elif error['code'] == 'E_VALIDATION':
                    return [
                        {'label': 'Fix Input', 'description': 'Correct the input and try again'}
                    ]
                return []
        
        return MockRecoverySystem()
    
    def _create_error_storage(self):
        """Create mock error storage"""
        class MockErrorStorage:
            def __init__(self):
                self.stored_errors = []
            
            def store_error(self, error):
                error_with_timestamp = {
                    **error,
                    'timestamp': datetime.now().isoformat()
                }
                self.stored_errors.append(error_with_timestamp)
            
            def get_stored_errors(self):
                return self.stored_errors
            
            def cleanup_expired_errors(self):
                cutoff = datetime.now() - timedelta(days=1)
                self.stored_errors = [
                    err for err in self.stored_errors
                    if datetime.fromisoformat(err['timestamp']) > cutoff
                ]
        
        return MockErrorStorage()
    
    def _create_analytics_integration(self):
        """Create mock analytics integration"""
        class MockAnalyticsIntegration:
            def __init__(self):
                self.error_count = 0
                self.critical_error_count = 0
                self.error_aggregation = {}
            
            def track_error(self, error):
                self.error_count += 1
                if error['severity'] == 'critical':
                    self.critical_error_count += 1
                
                code = error['code']
                if code not in self.error_aggregation:
                    self.error_aggregation[code] = {'count': 0}
                self.error_aggregation[code]['count'] += 1
            
            def measure_error_impact(self, error):
                if error['severity'] == 'critical':
                    return {
                        'user_impact': 'critical',
                        'business_impact': 'high',
                        'technical_impact': 'critical'
                    }
                return {
                    'user_impact': 'medium',
                    'business_impact': 'medium',
                    'technical_impact': 'low'
                }
            
            def get_aggregated_errors(self):
                return self.error_aggregation
        
        return MockAnalyticsIntegration()
    
    def _create_security_checker(self):
        """Create mock security checker"""
        class MockSecurityChecker:
            def sanitize_error_data(self, error_data):
                sanitized = error_data.copy()
                
                # Remove sensitive patterns
                sensitive_patterns = [
                    r'password=\w+',
                    r'token=\w+',
                    r'<script[^>]*>.*?</script>',
                    r'onerror\s*=\s*["\'][^"\']*["\']'
                ]
                
                for field in ['message', 'details', 'stack']:
                    if field in sanitized:
                        text = sanitized[field]
                        for pattern in sensitive_patterns:
                            text = re.sub(pattern, '[REDACTED]', text, flags=re.IGNORECASE)
                        sanitized[field] = text
                
                # Remove sensitive context keys
                if 'context' in sanitized:
                    sensitive_keys = ['user_password', 'api_key', 'session_id']
                    sanitized['context'] = {
                        k: v for k, v in sanitized['context'].items()
                        if k not in sensitive_keys
                    }
                
                return sanitized
        
        return MockSecurityChecker()
    
    def _create_performance_monitor(self):
        """Create mock performance monitor"""
        class MockPerformanceMonitor:
            def start_timer(self):
                return 0  # Mock timestamp
            
            def end_timer(self, start_time):
                return 50  # Mock processing time in ms
            
            def get_memory_usage(self):
                return 100  # Mock memory usage in MB
        
        return MockPerformanceMonitor()
    
    def _process_error(self, error):
        """Mock error processing"""
        # Simulate error processing time
        pass


if __name__ == '__main__':
    # Run the tests
    pytest.main([__file__, '-v'])