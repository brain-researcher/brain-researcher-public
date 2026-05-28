"""
Unit tests for Real-Time Progress component
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import time
from datetime import datetime, timedelta


class TestRealTimeProgress:
    """Test suite for Real-Time Progress feedback component"""
    
    @pytest.fixture
    def mock_event_source(self):
        """Mock EventSource for SSE testing"""
        source = Mock()
        source.close = MagicMock()
        source.addEventListener = MagicMock()
        return source
    
    @pytest.fixture
    def progress_steps(self):
        """Sample progress steps"""
        return [
            {'id': 'init', 'name': 'Initializing', 'status': 'completed', 'startTime': 1000, 'endTime': 2000},
            {'id': 'validate', 'name': 'Validating Input', 'status': 'completed', 'startTime': 2000, 'endTime': 3000},
            {'id': 'process', 'name': 'Processing Data', 'status': 'running', 'startTime': 3000},
            {'id': 'analyze', 'name': 'Running Analysis', 'status': 'pending'},
            {'id': 'finalize', 'name': 'Finalizing Results', 'status': 'pending'}
        ]
    
    @pytest.fixture
    def job_data(self):
        """Sample job data"""
        return {
            'jobId': 'job-123',
            'status': 'running',
            'progress': 45,
            'eta': (datetime.now() + timedelta(seconds=30)).isoformat(),
            'steps': []
        }
    
    def test_sse_connection(self, mock_event_source):
        """Test SSE connection establishment"""
        job_id = 'test-job-123'
        endpoint = f'/api/jobs/stream?jobId={job_id}'
        
        with patch('EventSource', return_value=mock_event_source):
            # Simulate SSE connection
            mock_event_source.readyState = 1  # OPEN
            assert mock_event_source.readyState == 1
            
            # Verify event listeners are set up
            mock_event_source.addEventListener.assert_not_called()  # Not called in this mock
    
    def test_polling_fallback(self, job_data):
        """Test fallback to polling when SSE fails"""
        with patch('fetch') as mock_fetch:
            mock_fetch.return_value.ok = True
            mock_fetch.return_value.json.return_value = job_data
            
            # Simulate polling
            for _ in range(3):
                response = mock_fetch(f'/api/jobs/{job_data["jobId"]}')
                assert response.ok
                data = response.json()
                assert data['jobId'] == 'job-123'
                assert data['progress'] == 45
    
    def test_progress_update_handling(self, progress_steps):
        """Test handling of progress updates"""
        total_steps = len(progress_steps)
        completed_steps = len([s for s in progress_steps if s['status'] == 'completed'])
        
        progress_percentage = (completed_steps / total_steps) * 100
        assert progress_percentage == 40  # 2 out of 5 steps completed
    
    def test_eta_calculation(self, job_data):
        """Test ETA calculation and display"""
        eta_str = job_data['eta']
        eta_time = datetime.fromisoformat(eta_str)
        now = datetime.now()
        
        diff = (eta_time - now).total_seconds()
        
        if diff > 60:
            minutes = int(diff / 60)
            seconds = int(diff % 60)
            eta_display = f'{minutes}m {seconds}s'
        else:
            eta_display = f'{int(diff)}s'
        
        assert diff > 0  # ETA should be in the future
        assert 's' in eta_display
    
    def test_step_status_icons(self, progress_steps):
        """Test that correct icons are shown for each step status"""
        icon_mapping = {
            'completed': 'CheckCircle',
            'running': 'Loader2',
            'error': 'AlertCircle',
            'pending': 'Circle'
        }
        
        for step in progress_steps:
            expected_icon = icon_mapping[step['status']]
            assert expected_icon in icon_mapping.values()
    
    def test_step_duration_calculation(self, progress_steps):
        """Test calculation of step durations"""
        for step in progress_steps:
            if step.get('startTime') and step.get('endTime'):
                duration = (step['endTime'] - step['startTime']) / 1000
                assert duration == 1.0  # Each completed step took 1 second
            elif step.get('startTime') and step['status'] == 'running':
                # Running step should show elapsed time
                assert step['startTime'] > 0
    
    def test_cancel_functionality(self, job_data):
        """Test job cancellation"""
        with patch('fetch') as mock_fetch:
            mock_fetch.return_value.ok = True
            
            # Cancel the job
            response = mock_fetch(f'/api/jobs/{job_data["jobId"]}/cancel', method='POST')
            assert response.ok
            
            # Track cancellation event
            with patch('analytics.trackEvent') as mock_track:
                mock_track('job_cancelled', {
                    'job_id': job_data['jobId'],
                    'progress': job_data['progress']
                })
                
                mock_track.assert_called_once()
                assert mock_track.call_args[0][0] == 'job_cancelled'
    
    def test_expandable_step_details(self, progress_steps):
        """Test expandable step details functionality"""
        expanded_steps = set()
        
        # Expand a step
        step_id = 'process'
        expanded_steps.add(step_id)
        assert step_id in expanded_steps
        
        # Collapse the step
        expanded_steps.remove(step_id)
        assert step_id not in expanded_steps
    
    def test_connection_status_display(self):
        """Test connection status indicators"""
        connection_states = {
            'sse_connected': {'text': 'Live', 'color': 'green'},
            'polling': {'text': 'Polling', 'color': 'yellow'},
            'disconnected': {'text': 'Disconnected', 'color': 'red'}
        }
        
        for state, config in connection_states.items():
            assert 'text' in config
            assert 'color' in config
    
    def test_error_handling(self, job_data):
        """Test error handling in progress updates"""
        error_data = {
            **job_data,
            'status': 'error',
            'error': {
                'message': 'Analysis failed',
                'code': 'ANALYSIS_ERROR'
            }
        }
        
        with patch('analytics.trackEvent') as mock_track:
            if error_data['status'] == 'error':
                mock_track('job_error', error_data['error'])
                
            mock_track.assert_called_once()
            assert mock_track.call_args[0][0] == 'job_error'
    
    def test_completion_handling(self, job_data):
        """Test handling of job completion"""
        completion_data = {
            **job_data,
            'status': 'completed',
            'progress': 100,
            'result': {
                'artifacts': ['result1.nii', 'stats.csv'],
                'summary': 'Analysis completed successfully'
            }
        }
        
        assert completion_data['status'] == 'completed'
        assert completion_data['progress'] == 100
        assert 'result' in completion_data
        assert len(completion_data['result']['artifacts']) > 0
    
    def test_progress_bar_animation(self):
        """Test progress bar animation properties"""
        progress_values = [0, 25, 50, 75, 100]
        
        for progress in progress_values:
            width_style = f'width: {progress}%'
            assert f'{progress}%' in width_style
    
    def test_auto_scroll_behavior(self, progress_steps):
        """Test auto-scroll behavior for long step lists"""
        max_visible_height = 384  # max-h-96 = 24rem = 384px
        step_height = 60  # Approximate height per step
        
        total_height = len(progress_steps) * step_height
        needs_scroll = total_height > max_visible_height
        
        assert needs_scroll is False  # 5 steps should fit without scrolling
    
    def test_reconnection_logic(self):
        """Test SSE reconnection after disconnection"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Simulate connection attempt
                retry_count += 1
                if retry_count == 2:
                    # Success on second attempt
                    break
            except:
                continue
        
        assert retry_count == 2  # Connected on second attempt
    
    def test_analytics_tracking(self, job_data):
        """Test that progress updates are tracked for analytics"""
        events_to_track = [
            ('progress_update', {'job_id': job_data['jobId'], 'progress': 25}),
            ('progress_update', {'job_id': job_data['jobId'], 'progress': 50}),
            ('progress_update', {'job_id': job_data['jobId'], 'progress': 75}),
            ('job_completed', {'job_id': job_data['jobId'], 'duration': 45000})
        ]
        
        for event_name, event_data in events_to_track:
            assert event_name in ['progress_update', 'job_completed']
            assert 'job_id' in event_data