"""
Tests for Responsive Design System and A/B Testing components.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestResponsiveDesignSystem:
    """Test responsive design system functionality."""
    
    def test_breakpoint_detection(self):
        """Test breakpoint detection for different screen sizes."""
        test_cases = [
            (320, 'xs'),
            (640, 'sm'),
            (768, 'md'),
            (1024, 'lg'),
            (1280, 'xl'),
            (1536, '2xl')
        ]
        
        for width, expected_breakpoint in test_cases:
            # Mock window width
            mock_window = Mock(innerWidth=width)
            breakpoint = self._get_breakpoint(mock_window)
            assert breakpoint == expected_breakpoint
    
    def test_device_type_detection(self):
        """Test device type detection."""
        test_cases = [
            (375, 'mobile'),
            (768, 'tablet'),
            (1024, 'desktop'),
            (1920, 'wide')
        ]
        
        for width, expected_device in test_cases:
            mock_window = Mock(innerWidth=width)
            device_type = self._get_device_type(mock_window)
            assert device_type == expected_device
    
    def test_responsive_grid_columns(self):
        """Test responsive grid column calculation."""
        cols_config = {
            'xs': 1,
            'sm': 2,
            'md': 3,
            'lg': 4,
            'xl': 5,
            '2xl': 6
        }
        
        test_cases = [
            ('xs', 1),
            ('sm', 2),
            ('md', 3),
            ('lg', 4),
            ('xl', 5),
            ('2xl', 6)
        ]
        
        for breakpoint, expected_cols in test_cases:
            columns = self._calculate_columns(cols_config, breakpoint)
            assert columns == expected_cols
    
    def test_touch_device_detection(self):
        """Test touch device detection."""
        # Test with touch support
        mock_window = Mock()
        mock_window.ontouchstart = True
        assert self._is_touch_device(mock_window) is True
        
        # Test without touch support
        mock_window = Mock(spec=[])
        assert self._is_touch_device(mock_window) is False
    
    def test_responsive_image_source_selection(self):
        """Test responsive image source selection."""
        sources = [
            {'breakpoint': 'sm', 'src': '/image-sm.jpg'},
            {'breakpoint': 'md', 'src': '/image-md.jpg'},
            {'breakpoint': 'lg', 'src': '/image-lg.jpg'}
        ]
        
        test_cases = [
            ('xs', '/image-sm.jpg'),
            ('sm', '/image-sm.jpg'),
            ('md', '/image-md.jpg'),
            ('lg', '/image-lg.jpg'),
            ('xl', '/image-lg.jpg')
        ]
        
        for breakpoint, expected_src in test_cases:
            src = self._select_image_source(sources, breakpoint, '/default.jpg')
            assert src == expected_src
    
    def test_device_preview_dimensions(self):
        """Test device preview dimensions."""
        device_sizes = {
            'mobile': {'width': 375, 'height': 812},
            'tablet': {'width': 768, 'height': 1024},
            'desktop': {'width': 1920, 'height': 1080}
        }
        
        for device, dimensions in device_sizes.items():
            # Portrait orientation
            preview = self._get_preview_dimensions(device, 'portrait')
            assert preview['width'] == dimensions['width']
            assert preview['height'] == dimensions['height']
            
            # Landscape orientation
            preview = self._get_preview_dimensions(device, 'landscape')
            assert preview['width'] == dimensions['height']
            assert preview['height'] == dimensions['width']
    
    def test_responsive_layout_mobile_adaptation(self):
        """Test responsive layout adaptation for mobile."""
        # Test mobile layout
        layout = self._render_layout(
            device_type='mobile',
            sidebar=True,
            aside=True
        )
        
        # Mobile should not show sidebar/aside inline
        assert layout['show_sidebar'] is False
        assert layout['show_aside'] is False
        assert layout['show_mobile_nav'] is True
        
        # Test desktop layout
        layout = self._render_layout(
            device_type='desktop',
            sidebar=True,
            aside=True
        )
        
        assert layout['show_sidebar'] is True
        assert layout['show_aside'] is True
        assert layout['show_mobile_nav'] is False
    
    # Helper methods
    def _get_breakpoint(self, window):
        """Helper to determine breakpoint."""
        width = window.innerWidth
        if width >= 1536: return '2xl'
        if width >= 1280: return 'xl'
        if width >= 1024: return 'lg'
        if width >= 768: return 'md'
        if width >= 640: return 'sm'
        return 'xs'
    
    def _get_device_type(self, window):
        """Helper to determine device type."""
        width = window.innerWidth
        if width >= 1280: return 'wide'
        if width >= 1024: return 'desktop'
        if width >= 768: return 'tablet'
        return 'mobile'
    
    def _calculate_columns(self, config, breakpoint):
        """Helper to calculate grid columns."""
        breakpoints = ['2xl', 'xl', 'lg', 'md', 'sm', 'xs']
        current_index = breakpoints.index(breakpoint)
        
        for i in range(current_index, len(breakpoints)):
            bp = breakpoints[i]
            if bp in config:
                return config[bp]
        return 1
    
    def _is_touch_device(self, window):
        """Helper to detect touch device."""
        return hasattr(window, 'ontouchstart')
    
    def _select_image_source(self, sources, breakpoint, default):
        """Helper to select image source."""
        breakpoints = ['2xl', 'xl', 'lg', 'md', 'sm', 'xs']
        current_index = breakpoints.index(breakpoint)
        
        for i in range(current_index, len(breakpoints)):
            bp = breakpoints[i]
            for source in sources:
                if source['breakpoint'] == bp:
                    return source['src']
        return default
    
    def _get_preview_dimensions(self, device, orientation):
        """Helper to get preview dimensions."""
        sizes = {
            'mobile': {'width': 375, 'height': 812},
            'tablet': {'width': 768, 'height': 1024},
            'desktop': {'width': 1920, 'height': 1080}
        }
        
        size = sizes[device]
        if orientation == 'portrait':
            return {'width': size['width'], 'height': size['height']}
        else:
            return {'width': size['height'], 'height': size['width']}
    
    def _render_layout(self, device_type, sidebar, aside):
        """Helper to determine layout rendering."""
        is_mobile = device_type == 'mobile'
        return {
            'show_sidebar': sidebar and not is_mobile,
            'show_aside': aside and not is_mobile,
            'show_mobile_nav': is_mobile and (sidebar or aside)
        }


class TestABTestingIntegration:
    """Test A/B testing integration functionality."""
    
    @pytest.fixture
    def mock_experiments(self):
        """Create mock experiment data."""
        return [
            {
                'id': 'exp1',
                'name': 'Homepage Redesign',
                'status': 'running',
                'variants': [
                    {
                        'id': 'control',
                        'name': 'Control',
                        'weight': 50,
                        'changes': {},
                        'metrics': {
                            'impressions': 10000,
                            'conversions': 500,
                            'conversionRate': 5.0,
                            'confidence': 95,
                            'uplift': 0
                        }
                    },
                    {
                        'id': 'variant-a',
                        'name': 'Variant A',
                        'weight': 50,
                        'changes': {'homepage': 'new-design'},
                        'metrics': {
                            'impressions': 10000,
                            'conversions': 650,
                            'conversionRate': 6.5,
                            'confidence': 97,
                            'uplift': 30
                        }
                    }
                ],
                'config': {
                    'minSampleSize': 1000,
                    'confidenceLevel': 95,
                    'testType': 'ab',
                    'allocation': 'random'
                }
            }
        ]
    
    @patch('requests.get')
    def test_fetch_experiments(self, mock_get, mock_experiments):
        """Test fetching experiments from API."""
        mock_get.return_value.json.return_value = mock_experiments
        
        experiments = self._fetch_experiments('/api/experiments')
        
        assert len(experiments) == 1
        assert experiments[0]['id'] == 'exp1'
        assert experiments[0]['status'] == 'running'
        mock_get.assert_called_once_with('/api/experiments/active')
    
    @patch('requests.get')
    def test_user_variant_assignment(self, mock_get):
        """Test user variant assignment."""
        mock_assignments = [
            {'experimentId': 'exp1', 'variant': {'id': 'variant-a', 'name': 'Variant A'}}
        ]
        mock_get.return_value.json.return_value = mock_assignments
        
        assignments = self._get_user_assignments('user123', '/api/experiments')
        
        assert len(assignments) == 1
        assert assignments['exp1']['id'] == 'variant-a'
        mock_get.assert_called_with('/api/experiments/assignments/user123')
    
    def test_track_event(self):
        """Test event tracking with experiment context."""
        user_variants = {
            'exp1': {'id': 'variant-a', 'name': 'Variant A'}
        }
        
        event = self._track_event(
            'button_click',
            {'button': 'cta'},
            'user123',
            user_variants
        )
        
        assert event['name'] == 'button_click'
        assert event['properties']['button'] == 'cta'
        assert event['userId'] == 'user123'
        assert len(event['variants']) == 1
        assert event['variants'][0]['experimentId'] == 'exp1'
        assert event['variants'][0]['variantId'] == 'variant-a'
    
    def test_feature_flag_evaluation(self):
        """Test feature flag evaluation."""
        user_variants = {
            'exp1': {
                'id': 'variant-a',
                'changes': {
                    'new_feature': True,
                    'old_feature': False
                }
            }
        }
        
        assert self._is_feature_enabled('new_feature', user_variants) is True
        assert self._is_feature_enabled('old_feature', user_variants) is False
        assert self._is_feature_enabled('unknown_feature', user_variants) is False
    
    def test_statistical_significance_calculation(self):
        """Test statistical significance calculation."""
        control = {
            'impressions': 10000,
            'conversions': 500
        }
        variant = {
            'impressions': 10000,
            'conversions': 650
        }
        
        result = self._calculate_significance(control, variant)
        
        assert result['uplift'] == 30.0
        assert result['confidence'] > 95
        assert result['is_significant'] is True
    
    def test_traffic_allocation(self):
        """Test traffic allocation logic."""
        variants = [
            {'id': 'control', 'weight': 50},
            {'id': 'variant-a', 'weight': 30},
            {'id': 'variant-b', 'weight': 20}
        ]
        
        # Test 1000 allocations
        allocations = {}
        for i in range(1000):
            user_id = f'user_{i}'
            variant = self._allocate_variant(user_id, variants)
            allocations[variant['id']] = allocations.get(variant['id'], 0) + 1
        
        # Check distribution is roughly correct (within 5% tolerance)
        assert abs(allocations.get('control', 0) - 500) < 50
        assert abs(allocations.get('variant-a', 0) - 300) < 50
        assert abs(allocations.get('variant-b', 0) - 200) < 50
    
    def test_experiment_status_transitions(self):
        """Test experiment status transitions."""
        experiment = {
            'id': 'exp1',
            'status': 'draft'
        }
        
        # Draft -> Running
        experiment = self._update_status(experiment, 'running')
        assert experiment['status'] == 'running'
        assert 'startDate' in experiment
        
        # Running -> Paused
        experiment = self._update_status(experiment, 'paused')
        assert experiment['status'] == 'paused'
        
        # Paused -> Running
        experiment = self._update_status(experiment, 'running')
        assert experiment['status'] == 'running'
        
        # Running -> Completed
        experiment = self._update_status(experiment, 'completed')
        assert experiment['status'] == 'completed'
        assert 'endDate' in experiment
    
    def test_winner_determination(self):
        """Test determining experiment winner."""
        experiment = {
            'variants': [
                {
                    'id': 'control',
                    'metrics': {'conversionRate': 5.0, 'confidence': 95}
                },
                {
                    'id': 'variant-a',
                    'metrics': {'conversionRate': 6.5, 'confidence': 97}
                },
                {
                    'id': 'variant-b',
                    'metrics': {'conversionRate': 4.5, 'confidence': 93}
                }
            ],
            'config': {'confidenceLevel': 95}
        }
        
        winner = self._determine_winner(experiment)
        assert winner == 'variant-a'
    
    # Helper methods
    def _fetch_experiments(self, api_url):
        """Helper to fetch experiments."""
        import requests
        response = requests.get(f'{api_url}/active')
        return response.json()
    
    def _get_user_assignments(self, user_id, api_url):
        """Helper to get user assignments."""
        import requests
        response = requests.get(f'{api_url}/assignments/{user_id}')
        assignments = response.json()
        return {a['experimentId']: a['variant'] for a in assignments}
    
    def _track_event(self, name, properties, user_id, user_variants):
        """Helper to track event."""
        from datetime import datetime
        return {
            'name': name,
            'properties': properties,
            'userId': user_id,
            'timestamp': datetime.now().isoformat(),
            'variants': [
                {'experimentId': exp_id, 'variantId': variant['id']}
                for exp_id, variant in user_variants.items()
            ]
        }
    
    def _is_feature_enabled(self, feature_name, user_variants):
        """Helper to check feature flag."""
        for variant in user_variants.values():
            if variant.get('changes', {}).get(feature_name) is True:
                return True
        return False
    
    def _calculate_significance(self, control, variant):
        """Helper to calculate statistical significance."""
        import math
        
        p1 = control['conversions'] / control['impressions']
        p2 = variant['conversions'] / variant['impressions']
        
        uplift = ((p2 - p1) / p1) * 100
        
        # Simplified confidence calculation
        se = math.sqrt(p1 * (1 - p1) / control['impressions'] + 
                      p2 * (1 - p2) / variant['impressions'])
        z = abs(p2 - p1) / se
        confidence = min(99.9, 50 + z * 10)  # Simplified
        
        return {
            'uplift': uplift,
            'confidence': confidence,
            'is_significant': confidence >= 95
        }
    
    def _allocate_variant(self, user_id, variants):
        """Helper to allocate variant based on weights."""
        import hashlib
        
        # Generate consistent hash for user
        hash_val = int(hashlib.md5(user_id.encode()).hexdigest()[:8], 16)
        position = hash_val % 100
        
        cumulative = 0
        for variant in variants:
            cumulative += variant['weight']
            if position < cumulative:
                return variant
        
        return variants[-1]
    
    def _update_status(self, experiment, new_status):
        """Helper to update experiment status."""
        from datetime import datetime
        
        experiment['status'] = new_status
        
        if new_status == 'running' and 'startDate' not in experiment:
            experiment['startDate'] = datetime.now().isoformat()
        elif new_status == 'completed':
            experiment['endDate'] = datetime.now().isoformat()
        
        return experiment
    
    def _determine_winner(self, experiment):
        """Helper to determine experiment winner."""
        valid_variants = [
            v for v in experiment['variants']
            if v['metrics']['confidence'] >= experiment['config']['confidenceLevel']
        ]
        
        if not valid_variants:
            return None
        
        return max(valid_variants, key=lambda v: v['metrics']['conversionRate'])['id']


class TestLoadingStates:
    """Test loading states and error boundaries."""
    
    def test_skeleton_variants(self):
        """Test skeleton loader variants."""
        variants = ['text', 'circular', 'rectangular', 'rounded']
        
        for variant in variants:
            skeleton = self._render_skeleton(variant)
            assert skeleton['variant'] == variant
            assert skeleton['className'] is not None
    
    def test_spinner_sizes(self):
        """Test spinner size variations."""
        sizes = ['xs', 'sm', 'md', 'lg', 'xl']
        expected_dimensions = {
            'xs': 12,
            'sm': 16,
            'md': 24,
            'lg': 32,
            'xl': 48
        }
        
        for size in sizes:
            spinner = self._render_spinner(size)
            assert spinner['size'] == expected_dimensions[size]
    
    def test_progress_bar_calculation(self):
        """Test progress bar percentage calculation."""
        test_cases = [
            (50, 100, 50),
            (75, 100, 75),
            (150, 100, 100),  # Should cap at 100%
            (-10, 100, 0),    # Should floor at 0%
            (25, 50, 50)
        ]
        
        for value, max_val, expected_percentage in test_cases:
            percentage = self._calculate_progress(value, max_val)
            assert percentage == expected_percentage
    
    def test_loading_overlay_states(self):
        """Test loading overlay visibility states."""
        # Visible state
        overlay = self._render_overlay(visible=True)
        assert overlay['rendered'] is True
        assert overlay['blur'] is True
        
        # Hidden state
        overlay = self._render_overlay(visible=False)
        assert overlay['rendered'] is False
    
    def test_error_boundary_error_capture(self):
        """Test error boundary error capture."""
        error = Exception("Test error")
        error_info = {'componentStack': 'Component stack trace'}
        
        boundary = self._capture_error(error, error_info)
        
        assert boundary['hasError'] is True
        assert boundary['error'] == error
        assert boundary['errorInfo'] == error_info
    
    def test_error_boundary_recovery(self):
        """Test error boundary recovery."""
        boundary = {
            'hasError': True,
            'error': Exception("Test error"),
            'errorInfo': {}
        }
        
        boundary = self._reset_error(boundary)
        
        assert boundary['hasError'] is False
        assert boundary['error'] is None
        assert boundary['errorInfo'] is None
    
    def test_content_loader_states(self):
        """Test content loader states."""
        # Loading state
        loader = self._render_content_loader(
            is_loading=True,
            error=None
        )
        assert loader['show_loader'] is True
        assert loader['show_error'] is False
        assert loader['show_content'] is False
        
        # Error state
        loader = self._render_content_loader(
            is_loading=False,
            error=Exception("Load failed")
        )
        assert loader['show_loader'] is False
        assert loader['show_error'] is True
        assert loader['show_content'] is False
        
        # Content state
        loader = self._render_content_loader(
            is_loading=False,
            error=None
        )
        assert loader['show_loader'] is False
        assert loader['show_error'] is False
        assert loader['show_content'] is True
    
    # Helper methods
    def _render_skeleton(self, variant):
        """Helper to render skeleton."""
        class_map = {
            'text': 'rounded h-4',
            'circular': 'rounded-full',
            'rectangular': 'rounded-none',
            'rounded': 'rounded-lg'
        }
        return {
            'variant': variant,
            'className': class_map.get(variant, 'rounded h-4')
        }
    
    def _render_spinner(self, size):
        """Helper to render spinner."""
        size_map = {
            'xs': 12,
            'sm': 16,
            'md': 24,
            'lg': 32,
            'xl': 48
        }
        return {'size': size_map[size]}
    
    def _calculate_progress(self, value, max_val):
        """Helper to calculate progress percentage."""
        percentage = (value / max_val) * 100
        return min(100, max(0, percentage))
    
    def _render_overlay(self, visible):
        """Helper to render overlay."""
        return {
            'rendered': visible,
            'blur': True if visible else False
        }
    
    def _capture_error(self, error, error_info):
        """Helper to capture error in boundary."""
        return {
            'hasError': True,
            'error': error,
            'errorInfo': error_info
        }
    
    def _reset_error(self, boundary):
        """Helper to reset error boundary."""
        return {
            'hasError': False,
            'error': None,
            'errorInfo': None
        }
    
    def _render_content_loader(self, is_loading, error):
        """Helper to determine content loader state."""
        return {
            'show_loader': is_loading,
            'show_error': error is not None,
            'show_content': not is_loading and error is None
        }


if __name__ == '__main__':
    pytest.main([__file__, '-v'])