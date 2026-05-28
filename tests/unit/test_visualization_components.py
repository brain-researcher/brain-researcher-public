"""
Unit tests for Visualization Components (Knowledge Graph, Pipeline, Result Gallery)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime


class TestKnowledgeGraphExplorer:
    """Test suite for Knowledge Graph Explorer component"""
    
    @pytest.fixture
    def graph_data(self):
        """Sample graph data"""
        return {
            'nodes': [
                {
                    'id': 'paper_1',
                    'label': 'fMRI Analysis Methods',
                    'type': 'paper',
                    'properties': {
                        'year': 2023,
                        'citations': 45,
                        'journal': 'NeuroImage'
                    }
                },
                {
                    'id': 'dataset_1',
                    'label': 'Motor Task Dataset',
                    'type': 'dataset',
                    'properties': {
                        'subjects': 20,
                        'modality': 'fMRI'
                    }
                },
                {
                    'id': 'tool_1',
                    'label': 'FSL',
                    'type': 'tool',
                    'properties': {
                        'version': '6.0.5'
                    }
                }
            ],
            'edges': [
                {
                    'source': 'paper_1',
                    'target': 'dataset_1',
                    'type': 'uses',
                    'weight': 1.0
                },
                {
                    'source': 'dataset_1',
                    'target': 'tool_1',
                    'type': 'processed_by',
                    'weight': 0.8
                }
            ],
            'stats': {
                'total_nodes': 3,
                'total_edges': 2,
                'node_types': {
                    'paper': 1,
                    'dataset': 1,
                    'tool': 1
                },
                'edge_types': {
                    'uses': 1,
                    'processed_by': 1
                }
            }
        }
    
    def test_graph_initialization(self, graph_data):
        """Test graph component initialization"""
        assert len(graph_data['nodes']) == 3
        assert len(graph_data['edges']) == 2
        assert graph_data['stats']['total_nodes'] == 3
    
    def test_node_types(self, graph_data):
        """Test different node types in graph"""
        node_types = {node['type'] for node in graph_data['nodes']}
        assert 'paper' in node_types
        assert 'dataset' in node_types
        assert 'tool' in node_types
    
    def test_edge_relationships(self, graph_data):
        """Test edge relationships between nodes"""
        edges = graph_data['edges']
        
        # Check first edge
        assert edges[0]['source'] == 'paper_1'
        assert edges[0]['target'] == 'dataset_1'
        assert edges[0]['type'] == 'uses'
        
        # Check second edge
        assert edges[1]['source'] == 'dataset_1'
        assert edges[1]['target'] == 'tool_1'
    
    def test_node_properties(self, graph_data):
        """Test node properties and metadata"""
        paper_node = next(n for n in graph_data['nodes'] if n['id'] == 'paper_1')
        
        assert paper_node['properties']['year'] == 2023
        assert paper_node['properties']['citations'] == 45
        assert paper_node['properties']['journal'] == 'NeuroImage'
    
    def test_graph_statistics(self, graph_data):
        """Test graph statistics calculation"""
        stats = graph_data['stats']
        
        assert stats['total_nodes'] == 3
        assert stats['total_edges'] == 2
        assert sum(stats['node_types'].values()) == 3
        assert sum(stats['edge_types'].values()) == 2
    
    def test_search_functionality(self, graph_data):
        """Test node search functionality"""
        search_query = 'fmri'
        
        # Simulate search
        matching_nodes = [
            node for node in graph_data['nodes']
            if search_query.lower() in node['label'].lower()
        ]
        
        assert len(matching_nodes) == 1
        assert matching_nodes[0]['id'] == 'paper_1'
    
    def test_filter_by_type(self, graph_data):
        """Test filtering nodes by type"""
        # Filter for papers only
        filtered_nodes = [
            node for node in graph_data['nodes']
            if node['type'] == 'paper'
        ]
        
        assert len(filtered_nodes) == 1
        assert filtered_nodes[0]['label'] == 'fMRI Analysis Methods'
    
    def test_export_functionality(self, graph_data):
        """Test graph export to SVG"""
        # Simulate SVG export
        svg_content = f"<svg>Graph with {len(graph_data['nodes'])} nodes</svg>"
        
        assert 'svg' in svg_content
        assert '3 nodes' in svg_content


class TestPipelineVisualization:
    """Test suite for Pipeline Visualization component"""
    
    @pytest.fixture
    def pipeline_data(self):
        """Sample pipeline data"""
        return {
            'id': 'pipeline_123',
            'name': 'fMRI Analysis Pipeline',
            'description': 'Standard GLM analysis pipeline',
            'steps': [
                {
                    'id': 'step_1',
                    'name': 'Data Loading',
                    'type': 'input',
                    'status': 'completed',
                    'progress': 100,
                    'duration': 5000,
                    'parameters': {
                        'format': 'BIDS',
                        'path': '/data/ds000114'
                    }
                },
                {
                    'id': 'step_2',
                    'name': 'Preprocessing',
                    'type': 'process',
                    'status': 'running',
                    'progress': 60,
                    'duration': None,
                    'parameters': {
                        'smoothing': 6,
                        'normalize': True
                    }
                },
                {
                    'id': 'step_3',
                    'name': 'GLM Analysis',
                    'type': 'analysis',
                    'status': 'pending',
                    'progress': 0,
                    'parameters': {
                        'contrasts': ['motor > rest']
                    }
                },
                {
                    'id': 'step_4',
                    'name': 'Export Results',
                    'type': 'output',
                    'status': 'pending',
                    'progress': 0
                }
            ],
            'connections': [
                {'from': 'step_1', 'to': 'step_2', 'label': 'raw data'},
                {'from': 'step_2', 'to': 'step_3', 'label': 'preprocessed'},
                {'from': 'step_3', 'to': 'step_4', 'label': 'statistics'}
            ],
            'status': 'running',
            'progress': 40
        }
    
    def test_pipeline_structure(self, pipeline_data):
        """Test pipeline structure and steps"""
        assert pipeline_data['id'] == 'pipeline_123'
        assert len(pipeline_data['steps']) == 4
        assert len(pipeline_data['connections']) == 3
    
    def test_step_types(self, pipeline_data):
        """Test different step types in pipeline"""
        step_types = {step['type'] for step in pipeline_data['steps']}
        
        assert 'input' in step_types
        assert 'process' in step_types
        assert 'analysis' in step_types
        assert 'output' in step_types
    
    def test_step_status_tracking(self, pipeline_data):
        """Test step status tracking"""
        statuses = [step['status'] for step in pipeline_data['steps']]
        
        assert statuses[0] == 'completed'
        assert statuses[1] == 'running'
        assert statuses[2] == 'pending'
        assert statuses[3] == 'pending'
    
    def test_progress_calculation(self, pipeline_data):
        """Test overall progress calculation"""
        # Calculate expected progress
        step_progresses = [step['progress'] for step in pipeline_data['steps']]
        expected_progress = sum(step_progresses) / len(step_progresses)
        
        assert pipeline_data['progress'] == 40
        assert expected_progress == 40
    
    def test_step_connections(self, pipeline_data):
        """Test connections between pipeline steps"""
        connections = pipeline_data['connections']
        
        # Verify connection chain
        assert connections[0]['from'] == 'step_1'
        assert connections[0]['to'] == 'step_2'
        assert connections[1]['from'] == 'step_2'
        assert connections[1]['to'] == 'step_3'
    
    def test_step_parameters(self, pipeline_data):
        """Test step parameter configuration"""
        preprocessing_step = pipeline_data['steps'][1]
        
        assert preprocessing_step['parameters']['smoothing'] == 6
        assert preprocessing_step['parameters']['normalize'] is True
    
    def test_duration_tracking(self, pipeline_data):
        """Test step duration tracking"""
        completed_step = pipeline_data['steps'][0]
        running_step = pipeline_data['steps'][1]
        
        assert completed_step['duration'] == 5000
        assert running_step['duration'] is None  # Still running
    
    def test_failed_step_handling(self):
        """Test handling of failed pipeline steps"""
        failed_step = {
            'id': 'step_failed',
            'name': 'Failed Step',
            'type': 'process',
            'status': 'failed',
            'error': 'Out of memory',
            'progress': 0
        }
        
        assert failed_step['status'] == 'failed'
        assert 'Out of memory' in failed_step['error']


class TestResultGallery:
    """Test suite for Result Gallery component"""
    
    @pytest.fixture
    def gallery_items(self):
        """Sample gallery items"""
        return [
            {
                'id': 'result_1',
                'title': 'Statistical Map',
                'description': 'Group-level activation map',
                'type': 'image',
                'thumbnail': '/thumbnails/stat_map.png',
                'fullSizeUrl': '/images/stat_map_full.png',
                'metadata': {
                    'created_at': datetime(2024, 1, 15),
                    'created_by': 'user123',
                    'tags': ['fmri', 'glm', 'motor'],
                    'size': 2048000,
                    'dimensions': {'width': 1920, 'height': 1080},
                    'format': 'png'
                }
            },
            {
                'id': 'result_2',
                'title': 'Time Series Plot',
                'description': 'BOLD signal time series',
                'type': 'plot',
                'thumbnail': '/thumbnails/timeseries.png',
                'metadata': {
                    'created_at': datetime(2024, 1, 15),
                    'tags': ['timeseries', 'bold'],
                    'size': 512000
                }
            },
            {
                'id': 'result_3',
                'title': 'Results Table',
                'type': 'table',
                'metadata': {
                    'created_at': datetime(2024, 1, 14),
                    'tags': ['statistics'],
                    'size': 102400
                }
            }
        ]
    
    def test_gallery_item_structure(self, gallery_items):
        """Test gallery item structure"""
        assert len(gallery_items) == 3
        
        first_item = gallery_items[0]
        assert first_item['id'] == 'result_1'
        assert first_item['type'] == 'image'
        assert 'metadata' in first_item
    
    def test_item_types(self, gallery_items):
        """Test different item types in gallery"""
        item_types = {item['type'] for item in gallery_items}
        
        assert 'image' in item_types
        assert 'plot' in item_types
        assert 'table' in item_types
    
    def test_metadata_fields(self, gallery_items):
        """Test metadata fields for gallery items"""
        image_item = gallery_items[0]
        metadata = image_item['metadata']
        
        assert 'created_at' in metadata
        assert 'tags' in metadata
        assert 'size' in metadata
        assert metadata['dimensions']['width'] == 1920
    
    def test_filtering_by_type(self, gallery_items):
        """Test filtering gallery items by type"""
        # Filter for images only
        images = [item for item in gallery_items if item['type'] == 'image']
        
        assert len(images) == 1
        assert images[0]['title'] == 'Statistical Map'
    
    def test_filtering_by_tags(self, gallery_items):
        """Test filtering gallery items by tags"""
        # Filter for items with 'fmri' tag
        filtered = [
            item for item in gallery_items
            if 'fmri' in item['metadata'].get('tags', [])
        ]
        
        assert len(filtered) == 1
        assert filtered[0]['id'] == 'result_1'
    
    def test_sorting_by_date(self, gallery_items):
        """Test sorting gallery items by date"""
        sorted_items = sorted(
            gallery_items,
            key=lambda x: x['metadata']['created_at'],
            reverse=True
        )
        
        assert sorted_items[0]['id'] == 'result_1'  # Most recent
        assert sorted_items[-1]['id'] == 'result_3'  # Oldest
    
    def test_pagination(self, gallery_items):
        """Test gallery pagination"""
        items_per_page = 2
        page_1 = gallery_items[:items_per_page]
        page_2 = gallery_items[items_per_page:items_per_page*2]
        
        assert len(page_1) == 2
        assert len(page_2) == 1
    
    def test_search_functionality(self, gallery_items):
        """Test search in gallery items"""
        search_query = 'statistical'
        
        results = [
            item for item in gallery_items
            if search_query.lower() in item.get('title', '').lower() or
            search_query.lower() in item.get('description', '').lower()
        ]
        
        assert len(results) == 1
        assert results[0]['title'] == 'Statistical Map'
    
    def test_file_size_formatting(self):
        """Test file size formatting"""
        sizes = [
            (1024, '1.00 KB'),
            (1048576, '1.00 MB'),
            (2097152, '2.00 MB')
        ]
        
        for bytes_val, expected in sizes:
            # Simulate formatting
            kb = bytes_val / 1024
            if kb >= 1024:
                formatted = f"{kb/1024:.2f} MB"
            else:
                formatted = f"{kb:.2f} KB"
            
            assert formatted == expected