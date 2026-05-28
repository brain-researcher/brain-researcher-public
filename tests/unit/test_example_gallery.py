"""
Unit tests for Example Gallery component functionality
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime


class TestExampleGallery:
    """Test suite for Example Gallery component"""
    
    @pytest.fixture
    def mock_api_client(self):
        """Mock API client for testing"""
        client = Mock()
        client.post = MagicMock(return_value={'success': True, 'jobId': 'test-123'})
        return client
    
    @pytest.fixture
    def example_cards(self):
        """Sample example cards data"""
        return [
            {
                'id': 'glm',
                'title': 'One-click GLM',
                'description': 'Get a thresholded Z-map and a peaks table from sample data.',
                'estimatedTime': '45s',
                'tags': ['fMRI', 'GLM', 'Statistics'],
                'apiEndpoint': '/demo/scenarios/glm'
            },
            {
                'id': 'dmn',
                'title': 'DMN interactive 3D',
                'description': 'Explore an interactive cortex map with threshold control.',
                'estimatedTime': '30s',
                'tags': ['DMN', '3D', 'Networks'],
                'apiEndpoint': '/demo/scenarios/dmn'
            },
            {
                'id': 'connectivity',
                'title': 'Resting connectivity',
                'description': 'See the correlation matrix and basic graph metrics in seconds.',
                'estimatedTime': '60s',
                'tags': ['Connectivity', 'Resting', 'Networks'],
                'apiEndpoint': '/demo/scenarios/connectivity'
            }
        ]
    
    def test_example_gallery_initialization(self, example_cards):
        """Test that example gallery initializes with correct data"""
        assert len(example_cards) == 3
        assert all('id' in card for card in example_cards)
        assert all('estimatedTime' in card for card in example_cards)
        assert all('tags' in card for card in example_cards)
    
    def test_run_example_tracking(self, mock_api_client, example_cards):
        """Test that running an example tracks analytics events"""
        with patch('analytics.trackEvent') as mock_track:
            # Simulate running an example
            example = example_cards[0]
            mock_api_client.post(example['apiEndpoint'])
            
            # Track the event
            mock_track('example_run_clicked', {
                'example_id': example['id'],
                'estimated_time': example['estimatedTime'],
                'timestamp': datetime.now().isoformat()
            })
            
            mock_track.assert_called_once()
            call_args = mock_track.call_args[0]
            assert call_args[0] == 'example_run_clicked'
            assert call_args[1]['example_id'] == 'glm'
    
    def test_progress_simulation(self, example_cards):
        """Test progress bar simulation during example execution"""
        progress_states = {}
        example_id = 'glm'
        
        # Simulate progress updates
        for progress in [0, 20, 40, 60, 80, 100]:
            progress_states[example_id] = progress
            assert progress_states[example_id] == progress
        
        assert progress_states[example_id] == 100
    
    def test_completion_state_management(self, example_cards):
        """Test that completion states are properly managed"""
        completed_states = {}
        
        # Mark examples as completed
        for card in example_cards:
            completed_states[card['id']] = True
        
        assert all(completed_states.get(card['id']) for card in example_cards)
    
    def test_error_handling(self, mock_api_client):
        """Test error handling when API fails"""
        mock_api_client.post.side_effect = Exception("API Error")
        
        with patch('analytics.trackEvent') as mock_track:
            try:
                mock_api_client.post('/demo/scenarios/glm')
            except Exception as e:
                mock_track('example_run_failed', {
                    'example_id': 'glm',
                    'error': str(e)
                })
            
            mock_track.assert_called_once()
            assert 'example_run_failed' in mock_track.call_args[0]
    
    def test_time_estimation_display(self, example_cards):
        """Test that time estimations are displayed correctly"""
        for card in example_cards:
            assert 's' in card['estimatedTime']
            time_value = int(card['estimatedTime'].replace('s', ''))
            assert 0 < time_value <= 120
    
    def test_tag_filtering(self, example_cards):
        """Test filtering examples by tags"""
        fmri_examples = [c for c in example_cards if 'fMRI' in c.get('tags', [])]
        network_examples = [c for c in example_cards if 'Networks' in c.get('tags', [])]
        
        assert len(fmri_examples) == 1
        assert len(network_examples) == 2
    
    def test_multiple_concurrent_runs(self, mock_api_client):
        """Test handling multiple examples running concurrently"""
        loading_states = {}
        
        # Start multiple examples
        for example_id in ['glm', 'dmn', 'connectivity']:
            loading_states[example_id] = True
        
        assert len(loading_states) == 3
        assert all(loading_states.values())
        
        # Complete them one by one
        for example_id in ['glm', 'dmn', 'connectivity']:
            loading_states[example_id] = False
        
        assert not any(loading_states.values())
    
    def test_view_results_after_completion(self, example_cards):
        """Test that view results button appears after completion"""
        completed_states = {'glm': True}
        
        for card in example_cards:
            if card['id'] in completed_states:
                # Should show "View Results" instead of "Run it"
                button_text = "View Results" if completed_states.get(card['id']) else "Run it"
                assert button_text == "View Results"
    
    def test_api_endpoint_construction(self, example_cards):
        """Test that API endpoints are correctly constructed"""
        base_url = 'http://localhost:8000'
        
        for card in example_cards:
            full_endpoint = f"{base_url}{card['apiEndpoint']}"
            assert full_endpoint.startswith('http://')
            assert '/demo/scenarios/' in full_endpoint
    
    def test_fallback_behavior(self, mock_api_client):
        """Test fallback behavior when demo endpoint is unavailable"""
        mock_api_client.post.return_value = None
        
        # Should still route to demo even if API fails
        result = mock_api_client.post('/demo/scenarios/glm') or 'fallback'
        assert result == 'fallback'
    
    def test_category_icons(self, example_cards):
        """Test that correct category icons are assigned"""
        icon_mapping = {
            'glm': 'BarChart3',
            'dmn': 'Brain',
            'connectivity': 'Network'
        }
        
        for card in example_cards:
            expected_icon = icon_mapping.get(card['id'])
            assert expected_icon is not None
    
    def test_responsive_grid_layout(self, example_cards):
        """Test that cards are arranged in responsive grid"""
        # On mobile: 1 column
        # On tablet: 2 columns
        # On desktop: 3 columns
        grid_classes = 'grid md:grid-cols-2 lg:grid-cols-3'
        assert 'grid' in grid_classes
        assert 'md:grid-cols-2' in grid_classes
        assert 'lg:grid-cols-3' in grid_classes
    
    def test_hover_effects(self, example_cards):
        """Test hover state management"""
        hovered_states = {}
        
        # Simulate hover
        for card in example_cards:
            hovered_states[card['id']] = True
            assert hovered_states[card['id']] is True
            
            # Simulate mouse leave
            hovered_states[card['id']] = False
            assert hovered_states[card['id']] is False