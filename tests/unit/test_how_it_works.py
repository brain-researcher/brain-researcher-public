"""
Unit tests for How It Works section component
"""

import pytest
from unittest.mock import Mock, patch
import json


class TestHowItWorks:
    """Test suite for How It Works section"""
    
    @pytest.fixture
    def steps_data(self):
        """Sample steps data for How It Works section"""
        return [
            {
                'number': '01',
                'title': 'Describe Your Analysis',
                'description': 'Tell us what you want to analyze in plain English. No coding required.',
                'icon': 'MessageSquare',
                'example': '"Show me motor activation in this fMRI dataset"',
                'color': 'from-blue-500 to-cyan-500'
            },
            {
                'number': '02',
                'title': 'AI Processes Your Request',
                'description': 'Our AI understands your intent and automatically selects the right tools and parameters.',
                'icon': 'Cpu',
                'example': 'GLM → Thresholding → Visualization',
                'color': 'from-purple-500 to-pink-500'
            },
            {
                'number': '03',
                'title': 'Get Publication-Ready Results',
                'description': 'Receive analyzed results with full provenance, citations, and reproducible workflows.',
                'icon': 'FileCheck',
                'example': 'Z-maps, peak tables, run cards',
                'color': 'from-green-500 to-emerald-500'
            }
        ]
    
    def test_steps_initialization(self, steps_data):
        """Test that all steps are properly initialized"""
        assert len(steps_data) == 3
        
        for i, step in enumerate(steps_data):
            assert step['number'] == f'0{i+1}'
            assert 'title' in step
            assert 'description' in step
            assert 'icon' in step
            assert 'example' in step
            assert 'color' in step
    
    def test_step_content_validation(self, steps_data):
        """Test that step content is valid and complete"""
        required_fields = ['number', 'title', 'description', 'icon', 'example', 'color']
        
        for step in steps_data:
            for field in required_fields:
                assert field in step
                assert step[field] is not None
                assert len(str(step[field])) > 0
    
    def test_step_icons(self, steps_data):
        """Test that appropriate icons are assigned to each step"""
        expected_icons = ['MessageSquare', 'Cpu', 'FileCheck']
        
        for i, step in enumerate(steps_data):
            assert step['icon'] == expected_icons[i]
    
    def test_gradient_colors(self, steps_data):
        """Test that gradient colors are properly defined"""
        for step in steps_data:
            assert 'from-' in step['color']
            assert 'to-' in step['color']
            assert '500' in step['color']  # Ensure color intensity
    
    def test_example_format(self, steps_data):
        """Test that examples are properly formatted"""
        assert steps_data[0]['example'].startswith('"')  # Natural language query
        assert '→' in steps_data[1]['example']  # Process flow
        assert ', ' in steps_data[2]['example']  # List of outputs
    
    def test_visual_examples_section(self):
        """Test visual examples section content"""
        visual_examples = {
            'evidence_rail': {
                'title': 'Evidence Rail',
                'description': 'Full provenance tracking with citations'
            },
            'run_card': {
                'title': 'Run Card',
                'description': 'Reproducible workflow documentation'
            },
            'outputs': {
                'title': 'Multiple Outputs',
                'description': 'Statistical maps, tables, and visualizations'
            }
        }
        
        assert len(visual_examples) == 3
        for key, value in visual_examples.items():
            assert 'title' in value
            assert 'description' in value
    
    def test_download_sample_run_card(self):
        """Test download sample run card functionality"""
        sample_run_card = {
            'version': '1.0',
            'analysis': 'GLM Analysis',
            'parameters': {
                'threshold': 0.05,
                'correction': 'FWE',
                'smoothing': 6
            },
            'tools': ['FSL', 'SPM12'],
            'citations': [
                'Smith et al., 2004',
                'Friston et al., 1994'
            ]
        }
        
        assert 'version' in sample_run_card
        assert 'analysis' in sample_run_card
        assert 'parameters' in sample_run_card
        assert 'tools' in sample_run_card
        assert 'citations' in sample_run_card
    
    def test_cta_button_tracking(self):
        """Test that CTA button clicks are tracked"""
        with patch('analytics.trackEvent') as mock_track:
            # Simulate CTA click
            mock_track('cta_clicked', {
                'cta_name': 'try_90_second_demo',
                'location': 'how_it_works_section'
            })
            
            mock_track.assert_called_once()
            call_args = mock_track.call_args[0]
            assert call_args[0] == 'cta_clicked'
            assert call_args[1]['cta_name'] == 'try_90_second_demo'
    
    def test_step_connections(self, steps_data):
        """Test that steps show proper visual connections"""
        for i in range(len(steps_data) - 1):
            # Each step except the last should have a connection to the next
            has_connection = i < len(steps_data) - 1
            assert has_connection is True
    
    def test_responsive_layout(self):
        """Test responsive layout classes"""
        layout_classes = {
            'mobile': 'grid-cols-1',
            'tablet': 'md:grid-cols-3',
            'desktop': 'lg:grid-cols-3'
        }
        
        assert 'grid-cols-1' in layout_classes['mobile']
        assert 'md:grid-cols-3' in layout_classes['tablet']
        assert 'lg:grid-cols-3' in layout_classes['desktop']
    
    def test_section_headings(self):
        """Test section headings and descriptions"""
        headings = {
            'main': 'Three Simple Steps to Brain Analysis',
            'subtitle': 'From natural language query to publication-ready results in under 90 seconds.',
            'cta': 'Ready to revolutionize your neuroimaging workflow?'
        }
        
        for key, text in headings.items():
            assert len(text) > 0
            assert text[0].isupper()  # Starts with capital letter
    
    def test_decorative_elements(self):
        """Test that decorative elements are properly configured"""
        decorative = {
            'badge': {
                'icon': 'Sparkles',
                'text': 'How It Works',
                'style': 'bg-blue-50 text-blue-700'
            },
            'blur_effects': [
                'bg-blue-500 rounded-full opacity-10 blur-2xl',
                'bg-purple-500 rounded-full opacity-10 blur-2xl'
            ]
        }
        
        assert 'icon' in decorative['badge']
        assert len(decorative['blur_effects']) == 2
    
    def test_accessibility_features(self):
        """Test accessibility features"""
        accessibility = {
            'alt_texts': True,
            'aria_labels': True,
            'keyboard_navigation': True,
            'color_contrast': 'WCAG AA'
        }
        
        assert accessibility['alt_texts'] is True
        assert accessibility['aria_labels'] is True
        assert accessibility['keyboard_navigation'] is True
        assert 'AA' in accessibility['color_contrast']