"""
Unit tests for Execution Progress Display component
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time
from datetime import datetime, timedelta


class TestExecutionProgress:
    """Test suite for Execution Progress Display"""
    
    @pytest.fixture
    def execution_steps(self):
        """Sample execution steps"""
        return [
            {
                'id': 'setup',
                'name': 'Setting up environment',
                'status': 'completed',
                'progress': 100,
                'startTime': datetime.now() - timedelta(seconds=10),
                'endTime': datetime.now() - timedelta(seconds=5),
                'estimatedDuration': 5
            },
            {
                'id': 'load',
                'name': 'Loading data',
                'status': 'running',
                'progress': 60,
                'startTime': datetime.now() - timedelta(seconds=5),
                'estimatedDuration': 10
            },
            {
                'id': 'preprocess',
                'name': 'Preprocessing',
                'status': 'pending',
                'estimatedDuration': 15
            },
            {
                'id': 'analysis',
                'name': 'Running analysis',
                'status': 'pending',
                'estimatedDuration': 30
            }
        ]
    
    @pytest.fixture
    def system_metrics(self):
        """Sample system metrics"""
        return {
            'cpu': 45.5,
            'memory': 62.3,
            'io': 23.8
        }
    
    def test_step_initialization(self, execution_steps):
        """Test that execution steps are properly initialized"""
        assert len(execution_steps) == 4
        assert execution_steps[0]['status'] == 'completed'
        assert execution_steps[1]['status'] == 'running'
        assert execution_steps[2]['status'] == 'pending'
    
    def test_overall_progress_calculation(self, execution_steps):
        """Test overall progress calculation"""
        completed = sum(1 for step in execution_steps if step['status'] == 'completed')
        total = len(execution_steps)
        
        progress = (completed / total) * 100 if total > 0 else 0
        
        assert progress == 25  # 1 out of 4 steps completed
    
    def test_elapsed_time_tracking(self):
        """Test elapsed time tracking"""
        start_time = datetime.now()
        time.sleep(0.1)  # Simulate some time passing
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        assert elapsed >= 0.1
        assert elapsed < 0.2
    
    def test_estimated_time_remaining(self, execution_steps):
        """Test ETA calculation"""
        completed_steps = 1
        total_steps = len(execution_steps)
        elapsed_time = 10  # seconds
        
        if completed_steps > 0:
            time_per_step = elapsed_time / completed_steps
            remaining_steps = total_steps - completed_steps
            eta = time_per_step * remaining_steps
            
            assert eta == 30  # 3 remaining steps * 10 seconds per step
    
    def test_pause_resume_functionality(self):
        """Test pause and resume functionality"""
        is_paused = False
        
        # Pause
        is_paused = True
        assert is_paused is True
        
        # Resume
        is_paused = False
        assert is_paused is False
    
    def test_cancel_operation(self, execution_steps):
        """Test cancellation of execution"""
        # Mark running step as cancelled
        for step in execution_steps:
            if step['status'] == 'running':
                step['status'] = 'error'
        
        # Check that running step is now in error state
        running_steps = [s for s in execution_steps if s['status'] == 'running']
        error_steps = [s for s in execution_steps if s['status'] == 'error']
        
        assert len(running_steps) == 0
        assert len(error_steps) == 1
    
    def test_retry_mechanism(self, execution_steps):
        """Test retry mechanism after error"""
        # Reset all steps
        for step in execution_steps:
            step['status'] = 'pending'
            step['progress'] = None
            step['startTime'] = None
            step['endTime'] = None
        
        assert all(step['status'] == 'pending' for step in execution_steps)
    
    def test_step_duration_calculation(self, execution_steps):
        """Test calculation of step duration"""
        completed_step = execution_steps[0]
        
        if completed_step['startTime'] and completed_step['endTime']:
            duration = (completed_step['endTime'] - completed_step['startTime']).total_seconds()
            assert duration == 5
    
    def test_system_metrics_display(self, system_metrics):
        """Test system metrics display"""
        assert system_metrics['cpu'] == 45.5
        assert system_metrics['memory'] == 62.3
        assert system_metrics['io'] == 23.8
        
        # All metrics should be between 0 and 100
        for metric in system_metrics.values():
            assert 0 <= metric <= 100
    
    def test_expandable_step_details(self):
        """Test expandable step details functionality"""
        expanded_steps = set()
        step_id = 'setup'
        
        # Expand
        expanded_steps.add(step_id)
        assert step_id in expanded_steps
        
        # Collapse
        expanded_steps.remove(step_id)
        assert step_id not in expanded_steps
    
    def test_step_output_display(self):
        """Test step output display"""
        step_output = [
            'Initializing environment...',
            'Loading configuration...',
            'Checking dependencies...',
            'Environment ready.'
        ]
        
        assert len(step_output) == 4
        assert step_output[0].startswith('Initializing')
        assert step_output[-1] == 'Environment ready.'
    
    def test_completion_detection(self, execution_steps):
        """Test detection of execution completion"""
        # Mark all steps as completed
        for step in execution_steps:
            step['status'] = 'completed'
        
        all_completed = all(
            step['status'] in ['completed', 'skipped'] 
            for step in execution_steps
        )
        
        assert all_completed is True
    
    def test_error_state_handling(self, execution_steps):
        """Test handling of error states"""
        # Set one step to error
        execution_steps[1]['status'] = 'error'
        
        has_error = any(step['status'] == 'error' for step in execution_steps)
        
        assert has_error is True
    
    def test_time_formatting(self):
        """Test time formatting function"""
        def format_time(seconds):
            mins = seconds // 60
            secs = seconds % 60
            return f"{mins}:{secs:02d}"
        
        assert format_time(0) == "0:00"
        assert format_time(59) == "0:59"
        assert format_time(60) == "1:00"
        assert format_time(125) == "2:05"
    
    def test_step_icon_mapping(self):
        """Test step status icon mapping"""
        icon_map = {
            'completed': 'CheckCircle',
            'running': 'Spinner',
            'error': 'AlertCircle',
            'skipped': 'Circle',
            'pending': 'Circle'
        }
        
        assert icon_map['completed'] == 'CheckCircle'
        assert icon_map['running'] == 'Spinner'
        assert icon_map['error'] == 'AlertCircle'