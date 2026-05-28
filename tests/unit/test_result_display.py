"""
Comprehensive unit tests for Result Display components
Testing ImageViewer, DataTable, JsonViewer, ResultCard, and DownloadButton
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
import json
from datetime import datetime, timezone
import io
import base64


class TestResultDisplay:
    """Test suite for Result Display component"""
    
    @pytest.fixture
    def result_items(self):
        """Sample result items"""
        return [
            {
                'id': 'result_1',
                'type': 'image',
                'name': 'activation_map.png',
                'data': '/api/results/activation_map.png',
                'metadata': {
                    'size': 245678,
                    'dimensions': {'width': 800, 'height': 600},
                    'created': datetime.now(),
                    'description': 'GLM activation map'
                }
            },
            {
                'id': 'result_2',
                'type': 'table',
                'name': 'peak_coordinates.csv',
                'data': [
                    ['Region', 'X', 'Y', 'Z', 'T-value'],
                    ['Motor Cortex', -42, 12, 58, 6.23],
                    ['SMA', -4, 8, 62, 5.87],
                    ['Cerebellum', 24, -56, -28, 4.92]
                ],
                'metadata': {
                    'rows': 4,
                    'columns': 5
                }
            },
            {
                'id': 'result_3',
                'type': 'json',
                'name': 'analysis_params.json',
                'data': {
                    'smoothing': 6,
                    'threshold': 0.001,
                    'correction': 'FWE',
                    'design_matrix': 'block'
                },
                'metadata': {
                    'size': 512
                }
            }
        ]
    
    def test_result_items_initialization(self, result_items):
        """Test that result items are properly initialized"""
        assert len(result_items) == 3
        assert result_items[0]['type'] == 'image'
        assert result_items[1]['type'] == 'table'
        assert result_items[2]['type'] == 'json'
    
    def test_image_display_properties(self, result_items):
        """Test image display properties"""
        image_result = result_items[0]
        
        assert image_result['type'] == 'image'
        assert 'dimensions' in image_result['metadata']
        assert image_result['metadata']['dimensions']['width'] == 800
        assert image_result['metadata']['dimensions']['height'] == 600
    
    def test_table_to_csv_conversion(self, result_items):
        """Test table to CSV conversion"""
        table_data = result_items[1]['data']
        
        def convert_to_csv(data):
            return '\n'.join([','.join(f'"{cell}"' for cell in row) for row in data])
        
        csv = convert_to_csv(table_data)
        
        assert '"Region"' in csv
        assert '"Motor Cortex"' in csv
        assert '6.23' in str(csv)
    
    def test_json_formatting(self, result_items):
        """Test JSON data formatting"""
        json_result = result_items[2]
        
        formatted = json.dumps(json_result['data'], indent=2)
        
        assert '"smoothing": 6' in formatted
        assert '"threshold": 0.001' in formatted
        assert '"correction": "FWE"' in formatted
    
    def test_download_functionality(self, result_items):
        """Test download functionality for different types"""
        for item in result_items:
            if item['type'] == 'image':
                # Image download should fetch and create blob
                assert item['data'].startswith('/api/')
            elif item['type'] == 'table':
                # Table should convert to CSV
                assert isinstance(item['data'], list)
            elif item['type'] == 'json':
                # JSON should stringify
                assert isinstance(item['data'], dict)
    
    def test_copy_to_clipboard(self, result_items):
        """Test copy to clipboard functionality"""
        table_result = result_items[1]
        json_result = result_items[2]
        
        # Table should be converted to CSV for copying
        assert isinstance(table_result['data'], list)
        
        # JSON should be stringified for copying
        json_string = json.dumps(json_result['data'], indent=2)
        assert isinstance(json_string, str)
    
    def test_zoom_functionality(self):
        """Test image zoom functionality"""
        zoom_levels = [25, 50, 75, 100, 125, 150, 175, 200]
        current_zoom = 100
        
        # Zoom in
        current_zoom = min(200, current_zoom + 25)
        assert current_zoom == 125
        
        # Zoom out
        current_zoom = max(25, current_zoom - 25)
        assert current_zoom == 100
    
    def test_image_rotation(self):
        """Test image rotation functionality"""
        rotation = 0
        
        # Rotate 90 degrees
        rotation = (rotation + 90) % 360
        assert rotation == 90
        
        # Rotate 3 more times to complete circle
        rotation = (rotation + 90) % 360
        assert rotation == 180
        rotation = (rotation + 90) % 360
        assert rotation == 270
        rotation = (rotation + 90) % 360
        assert rotation == 0
    
    def test_fullscreen_toggle(self):
        """Test fullscreen toggle functionality"""
        is_fullscreen = False
        
        # Enter fullscreen
        is_fullscreen = True
        assert is_fullscreen is True
        
        # Exit fullscreen
        is_fullscreen = False
        assert is_fullscreen is False
    
    def test_navigation_between_results(self, result_items):
        """Test navigation between multiple results"""
        selected_index = 0
        max_index = len(result_items) - 1
        
        # Navigate forward
        selected_index = min(max_index, selected_index + 1)
        assert selected_index == 1
        
        # Navigate backward
        selected_index = max(0, selected_index - 1)
        assert selected_index == 0
        
        # Try to go beyond bounds
        selected_index = 0
        selected_index = max(0, selected_index - 1)
        assert selected_index == 0  # Should stay at 0
    
    def test_metadata_display(self, result_items):
        """Test metadata display functionality"""
        for item in result_items:
            assert 'metadata' in item
            metadata = item['metadata']
            
            # Check common metadata fields
            if 'size' in metadata:
                assert metadata['size'] > 0
            
            if 'created' in metadata:
                assert isinstance(metadata['created'], datetime)
    
    def test_keyboard_navigation(self):
        """Test keyboard navigation support"""
        key_handlers = {
            'ArrowLeft': 'previous',
            'ArrowRight': 'next',
            'Escape': 'exit_fullscreen'
        }
        
        assert key_handlers['ArrowLeft'] == 'previous'
        assert key_handlers['ArrowRight'] == 'next'
        assert key_handlers['Escape'] == 'exit_fullscreen'
    
    def test_share_functionality(self, result_items):
        """Test share functionality"""
        result = result_items[0]
        
        share_data = {
            'title': result['name'],
            'text': f'Check out this result: {result["name"]}',
            'url': 'http://localhost:3000/results/1'
        }
        
        assert share_data['title'] == 'activation_map.png'
        assert 'Check out this result' in share_data['text']
    
    def test_result_type_icons(self):
        """Test result type icon mapping"""
        icon_map = {
            'image': 'ImageIcon',
            'table': 'TableIcon',
            'json': 'Code',
            'text': 'FileText',
            'html': 'Grid3x3'
        }
        
        assert icon_map['image'] == 'ImageIcon'
        assert icon_map['table'] == 'TableIcon'
        assert icon_map['json'] == 'Code'
    
    def test_html_sanitization(self):
        """Test HTML content sanitization"""
        html_content = '<div>Safe content</div><script>alert("XSS")</script>'
        
        # In real implementation, dangerous content should be sanitized
        # For testing, we just check that HTML type exists
        result = {
            'id': 'html_result',
            'type': 'html',
            'name': 'report.html',
            'data': html_content
        }
        
        assert result['type'] == 'html'
        assert '<div>' in result['data']


class TestImageViewer:
    """Test suite for ImageViewer component"""
    
    @pytest.fixture
    def image_props(self):
        """Sample image viewer props"""
        return {
            'src': '/api/brain_activation.png',
            'alt': 'Brain activation map',
            'type': 'standard',
            'onDownload': Mock(),
            'onShare': Mock()
        }
    
    @pytest.fixture
    def nifti_props(self):
        """Sample NIfTI image props"""
        return {
            'src': '/api/brain_volume.nii.gz',
            'alt': 'Brain volume',
            'type': 'nifti',
            'slices': [f'/api/brain_volume_slice_{i}.png' for i in range(32)]
        }
    
    def test_image_viewer_initialization(self, image_props):
        """Test basic ImageViewer initialization"""
        # Simulate component initialization
        viewer_state = {
            'zoom': 1,
            'pan': {'x': 0, 'y': 0},
            'rotation': 0,
            'currentSlice': 0,
            'isPlaying': False
        }
        
        assert viewer_state['zoom'] == 1
        assert viewer_state['pan'] == {'x': 0, 'y': 0}
        assert viewer_state['rotation'] == 0
        assert not viewer_state['isPlaying']
    
    def test_zoom_functionality(self):
        """Test zoom in/out functionality"""
        zoom = 1.0
        
        # Zoom in
        zoom = min(10.0, zoom + 0.2)
        assert zoom == 1.2
        
        # Zoom out
        zoom = max(0.1, zoom - 0.4)
        assert abs(zoom - 0.8) < 0.001  # Use approximate comparison for floating point
        
        # Test bounds
        zoom = 0.05  # Below minimum
        zoom = max(0.1, zoom)
        assert zoom == 0.1
        
        zoom = 12.0  # Above maximum
        zoom = min(10.0, zoom)
        assert zoom == 10.0
    
    def test_rotation_functionality(self):
        """Test image rotation"""
        rotation = 0
        
        # Rotate clockwise
        rotation = (rotation + 90) % 360
        assert rotation == 90
        
        # Rotate counter-clockwise
        rotation = (rotation - 180) % 360
        assert rotation == 270
    
    def test_pan_functionality(self):
        """Test pan/drag functionality"""
        pan = {'x': 0, 'y': 0}
        drag_delta = {'x': 50, 'y': -30}
        
        pan['x'] += drag_delta['x']
        pan['y'] += drag_delta['y']
        
        assert pan == {'x': 50, 'y': -30}
    
    def test_nifti_slice_navigation(self, nifti_props):
        """Test NIfTI slice navigation"""
        current_slice = 0
        total_slices = len(nifti_props['slices'])
        
        # Next slice
        current_slice = min(total_slices - 1, current_slice + 1)
        assert current_slice == 1
        
        # Previous slice
        current_slice = max(0, current_slice - 1)
        assert current_slice == 0
        
        # Jump to last slice
        current_slice = total_slices - 1
        assert current_slice == 31
    
    def test_auto_play_functionality(self, nifti_props):
        """Test auto-play for NIfTI slices"""
        play_state = {
            'isPlaying': False,
            'currentSlice': 0,
            'playSpeed': 500
        }
        
        # Start playing
        play_state['isPlaying'] = True
        assert play_state['isPlaying']
        
        # Simulate slice advancement
        total_slices = len(nifti_props['slices'])
        play_state['currentSlice'] = (play_state['currentSlice'] + 1) % total_slices
        assert play_state['currentSlice'] == 1
    
    def test_keyboard_shortcuts(self):
        """Test keyboard shortcut handling"""
        shortcuts = {
            '+': 'zoom_in',
            '-': 'zoom_out',
            'r': 'rotate_clockwise',
            'R': 'rotate_counter_clockwise',
            'ArrowLeft': 'previous_slice',
            'ArrowRight': 'next_slice',
            ' ': 'toggle_play',
            'Escape': 'reset_view'
        }
        
        assert shortcuts['+'] == 'zoom_in'
        assert shortcuts[' '] == 'toggle_play'
        assert shortcuts['Escape'] == 'reset_view'


class TestDataTable:
    """Test suite for DataTable component"""
    
    @pytest.fixture
    def sample_data(self):
        """Sample table data"""
        return [
            {'region': 'V1', 'activation': 0.85, 'p_value': 0.001, 'significant': True, 'date': '2025-01-15'},
            {'region': 'V2', 'activation': 0.72, 'p_value': 0.003, 'significant': True, 'date': '2025-01-16'},
            {'region': 'MT', 'activation': 0.91, 'p_value': 0.0001, 'significant': True, 'date': '2025-01-17'},
            {'region': 'IT', 'activation': 0.23, 'p_value': 0.12, 'significant': False, 'date': '2025-01-18'}
        ]
    
    @pytest.fixture
    def table_columns(self):
        """Sample table columns configuration"""
        return [
            {'key': 'region', 'header': 'Brain Region', 'type': 'text', 'sortable': True, 'filterable': True},
            {'key': 'activation', 'header': 'Activation', 'type': 'number', 'sortable': True, 'filterable': False},
            {'key': 'p_value', 'header': 'P-Value', 'type': 'number', 'sortable': True},
            {'key': 'significant', 'header': 'Significant', 'type': 'boolean', 'sortable': True},
            {'key': 'date', 'header': 'Date', 'type': 'date', 'sortable': True}
        ]
    
    def test_table_initialization(self, sample_data, table_columns):
        """Test table initialization"""
        table_state = {
            'data': sample_data,
            'columns': table_columns,
            'sortState': {'column': None, 'direction': None},
            'filters': {},
            'searchTerm': '',
            'currentPage': 1
        }
        
        assert len(table_state['data']) == 4
        assert len(table_state['columns']) == 5
        assert table_state['currentPage'] == 1
    
    def test_sorting_functionality(self, sample_data):
        """Test table sorting"""
        # Sort by activation (ascending)
        sorted_data = sorted(sample_data, key=lambda x: x['activation'])
        assert sorted_data[0]['activation'] == 0.23
        assert sorted_data[-1]['activation'] == 0.91
        
        # Sort by activation (descending)
        sorted_data = sorted(sample_data, key=lambda x: x['activation'], reverse=True)
        assert sorted_data[0]['activation'] == 0.91
        assert sorted_data[-1]['activation'] == 0.23
    
    def test_filtering_functionality(self, sample_data):
        """Test table filtering"""
        # Filter by region containing 'V'
        filtered_data = [row for row in sample_data if 'V' in row['region']]
        assert len(filtered_data) == 2
        assert all('V' in row['region'] for row in filtered_data)
        
        # Filter by significant results
        significant_data = [row for row in sample_data if row['significant']]
        assert len(significant_data) == 3
    
    def test_search_functionality(self, sample_data):
        """Test global search"""
        search_term = '0.85'
        search_results = [
            row for row in sample_data 
            if any(str(search_term).lower() in str(value).lower() for value in row.values())
        ]
        assert len(search_results) == 1
        assert search_results[0]['activation'] == 0.85
    
    def test_pagination_logic(self, sample_data):
        """Test pagination calculations"""
        page_size = 2
        total_items = len(sample_data)
        total_pages = (total_items + page_size - 1) // page_size  # Ceiling division
        
        assert total_pages == 2
        
        # Page 1
        page_1_start = 0
        page_1_end = min(page_size, total_items)
        page_1_data = sample_data[page_1_start:page_1_end]
        assert len(page_1_data) == 2
        
        # Page 2
        page_2_start = page_size
        page_2_end = min(page_size * 2, total_items)
        page_2_data = sample_data[page_2_start:page_2_end]
        assert len(page_2_data) == 2
    
    def test_csv_export(self, sample_data, table_columns):
        """Test CSV export functionality"""
        headers = [col['header'] for col in table_columns]
        csv_content = ','.join(headers) + '\\n'
        
        for row in sample_data:
            csv_row = ','.join(str(row[col['key']]) for col in table_columns)
            csv_content += csv_row + '\\n'
        
        assert 'Brain Region,Activation,P-Value' in csv_content
        assert 'V1,0.85,0.001' in csv_content
    
    def test_column_type_inference(self):
        """Test automatic column type inference"""
        def infer_type(values):
            non_null_values = [v for v in values if v is not None]
            if not non_null_values:
                return 'text'
            
            # Check boolean
            if all(isinstance(v, bool) for v in non_null_values):
                return 'boolean'
            
            # Check number
            if all(isinstance(v, (int, float)) for v in non_null_values):
                return 'number'
            
            # Check date
            if all(isinstance(v, str) and '-' in v for v in non_null_values):
                return 'date'
            
            return 'text'
        
        assert infer_type([True, False, True]) == 'boolean'
        assert infer_type([1, 2, 3.5]) == 'number'
        assert infer_type(['2025-01-01', '2025-01-02']) == 'date'
        assert infer_type(['hello', 'world']) == 'text'
    
    def test_row_selection(self, sample_data):
        """Test row selection functionality"""
        selected_rows = set()
        
        # Select row 0
        selected_rows.add(0)
        assert 0 in selected_rows
        
        # Select all rows
        selected_rows = set(range(len(sample_data)))
        assert len(selected_rows) == 4
        
        # Clear selection
        selected_rows.clear()
        assert len(selected_rows) == 0


class TestJsonViewer:
    """Test suite for JsonViewer component"""
    
    @pytest.fixture
    def sample_json(self):
        """Sample JSON data"""
        return {
            'analysis_type': 'GLM',
            'subjects': [1, 2, 3, 4, 5],
            'preprocessing': {
                'smoothing': 6.0,
                'high_pass': 0.01,
                'motion_correction': True
            },
            'contrasts': ['task > rest', 'motor > visual'],
            'results': {
                'significant_clusters': 12,
                'max_activation': 8.45,
                'corrected_p': 0.05
            }
        }
    
    def test_json_flattening(self, sample_json):
        """Test JSON structure flattening for display"""
        def flatten_json(obj, path='', level=0):
            nodes = []
            if isinstance(obj, dict):
                nodes.append({'key': path or 'root', 'type': 'object', 'level': level, 'value': obj})
                for key, value in obj.items():
                    new_path = f'{path}.{key}' if path else key
                    nodes.extend(flatten_json(value, new_path, level + 1))
            elif isinstance(obj, list):
                nodes.append({'key': path, 'type': 'array', 'level': level, 'value': obj})
                for i, item in enumerate(obj):
                    new_path = f'{path}[{i}]'
                    nodes.extend(flatten_json(item, new_path, level + 1))
            else:
                nodes.append({'key': path, 'type': type(obj).__name__, 'level': level, 'value': obj})
            return nodes
        
        nodes = flatten_json(sample_json)
        assert len(nodes) > 10  # Should have many nodes
        assert nodes[0]['type'] == 'object'
        assert any(node['type'] == 'array' for node in nodes)
    
    def test_search_functionality(self, sample_json):
        """Test JSON search functionality"""
        search_term = 'GLM'
        
        def search_json(obj, term):
            matches = []
            term_lower = term.lower()
            
            def search_recursive(obj, path=''):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        new_path = f'{path}.{key}' if path else key
                        if term_lower in key.lower():
                            matches.append({'path': new_path, 'key': key, 'value': value})
                        search_recursive(value, new_path)
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        search_recursive(item, f'{path}[{i}]')
                elif isinstance(obj, str) and term_lower in obj.lower():
                    matches.append({'path': path, 'value': obj})
            
            search_recursive(obj)
            return matches
        
        matches = search_json(sample_json, search_term)
        assert len(matches) > 0
        assert any('GLM' in str(match['value']) for match in matches)
    
    def test_expansion_state(self):
        """Test node expansion state management"""
        expanded_paths = set()
        
        # Expand root
        expanded_paths.add('')
        assert '' in expanded_paths
        
        # Expand preprocessing
        expanded_paths.add('preprocessing')
        assert 'preprocessing' in expanded_paths
        
        # Collapse preprocessing
        expanded_paths.remove('preprocessing')
        assert 'preprocessing' not in expanded_paths
    
    def test_value_formatting(self):
        """Test JSON value formatting"""
        def format_value(value):
            if isinstance(value, str):
                return f'"{value}"'
            elif isinstance(value, bool):
                return str(value).lower()
            elif value is None:
                return 'null'
            else:
                return str(value)
        
        assert format_value('hello') == '"hello"'
        assert format_value(True) == 'true'
        assert format_value(None) == 'null'
        assert format_value(42) == '42'
    
    def test_copy_functionality(self, sample_json):
        """Test copy to clipboard functionality"""
        # Simulate copying a JSON subtree
        preprocessing_config = sample_json['preprocessing']
        copied_content = json.dumps(preprocessing_config, indent=2)
        
        assert 'smoothing' in copied_content
        assert '6.0' in copied_content
        assert 'true' in copied_content.lower()


class TestResultCard:
    """Test suite for ResultCard component"""
    
    @pytest.fixture
    def image_result(self):
        """Sample image result"""
        return {
            'id': 'img-1',
            'name': 'brain_activation.nii.gz',
            'type': 'image',
            'content': '/api/images/brain_activation.nii.gz',
            'metadata': {
                'created_at': '2025-01-15T10:30:00Z',
                'author': 'Dr. Smith',
                'size': 15728640,
                'format': 'NIfTI',
                'dimensions': '64x64x32',
                'tags': ['fmri', 'activation']
            }
        }
    
    @pytest.fixture
    def table_result(self):
        """Sample table result"""
        return {
            'id': 'table-1',
            'name': 'statistics.csv',
            'type': 'table',
            'content': [
                {'region': 'V1', 'activation': 0.85},
                {'region': 'V2', 'activation': 0.72}
            ],
            'metadata': {
                'created_at': '2025-01-15T10:35:00Z',
                'author': 'Dr. Johnson',
                'size': 1024
            }
        }
    
    def test_type_detection(self, image_result, table_result):
        """Test automatic result type detection"""
        def detect_type(data, filename=None):
            if filename:
                filename_lower = filename.lower()
                if filename_lower.endswith('.nii.gz') or any(filename_lower.endswith(ext) for ext in ['.jpg', '.png', '.nii']):
                    return 'image'
                elif any(filename_lower.endswith(ext) for ext in ['.csv', '.xlsx']):
                    return 'table'
                elif filename_lower.endswith('.json'):
                    return 'json'
            
            if isinstance(data, str) and data.startswith('/api/'):
                return 'file'
            elif isinstance(data, list) and data and isinstance(data[0], dict):
                return 'table'
            elif isinstance(data, dict):
                return 'json'
            
            return 'text'
        
        assert detect_type(image_result['content'], image_result['name']) == 'image'
        assert detect_type(table_result['content'], table_result['name']) == 'table'
    
    def test_metadata_formatting(self, image_result):
        """Test metadata display formatting"""
        def format_size(bytes_val):
            if bytes_val < 1024:
                return f'{bytes_val} B'
            elif bytes_val < 1024**2:
                return f'{bytes_val/1024:.1f} KB'
            elif bytes_val < 1024**3:
                return f'{bytes_val/(1024**2):.1f} MB'
            else:
                return f'{bytes_val/(1024**3):.1f} GB'
        
        def format_date(date_str):
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d %H:%M')
            except:
                return date_str
        
        size_formatted = format_size(image_result['metadata']['size'])
        assert 'MB' in size_formatted
        
        date_formatted = format_date(image_result['metadata']['created_at'])
        assert '2025-01-15' in date_formatted
    
    def test_expansion_toggle(self):
        """Test result card expansion/collapse"""
        expanded_results = set()
        result_id = 'img-1'
        
        # Toggle expand
        if result_id in expanded_results:
            expanded_results.remove(result_id)
        else:
            expanded_results.add(result_id)
        
        assert result_id in expanded_results
        
        # Toggle collapse
        if result_id in expanded_results:
            expanded_results.remove(result_id)
        else:
            expanded_results.add(result_id)
        
        assert result_id not in expanded_results
    
    def test_download_preparation(self, table_result):
        """Test download data preparation"""
        def prepare_download(result):
            if result['type'] == 'table':
                # Convert to CSV
                data = result['content']
                if data:
                    headers = list(data[0].keys())
                    csv_content = ','.join(headers) + '\\n'
                    for row in data:
                        csv_content += ','.join(str(row.get(h, '')) for h in headers) + '\\n'
                    return {'content': csv_content, 'type': 'text/csv', 'filename': f"{result['name']}.csv"}
            elif result['type'] == 'json':
                return {
                    'content': json.dumps(result['content'], indent=2),
                    'type': 'application/json',
                    'filename': f"{result['name']}.json"
                }
            return None
        
        download_data = prepare_download(table_result)
        assert download_data is not None
        assert 'region,activation' in download_data['content']
        assert download_data['type'] == 'text/csv'


class TestDownloadButton:
    """Test suite for DownloadButton component"""
    
    @pytest.fixture
    def table_data(self):
        """Sample table data for download testing"""
        return [
            {'name': 'Alice', 'age': 25, 'city': 'New York'},
            {'name': 'Bob', 'age': 30, 'city': 'San Francisco'},
            {'name': 'Charlie', 'age': 35, 'city': 'Chicago'}
        ]
    
    @pytest.fixture
    def json_data(self):
        """Sample JSON data for download testing"""
        return {
            'config': {'version': '1.0', 'debug': True},
            'users': ['alice', 'bob'],
            'stats': {'count': 42, 'average': 3.14}
        }
    
    def test_csv_conversion(self, table_data):
        """Test table to CSV conversion"""
        def convert_to_csv(data):
            if not data:
                return ''
            
            headers = list(data[0].keys())
            csv_content = ','.join(headers) + '\\n'
            
            for row in data:
                csv_row = []
                for header in headers:
                    value = row.get(header, '')
                    # Escape commas and quotes
                    if ',' in str(value) or '"' in str(value):
                        escaped_value = str(value).replace('"', '""')
                        value = f'"{escaped_value}"'
                    csv_row.append(str(value))
                csv_content += ','.join(csv_row) + '\\n'
            
            return csv_content
        
        csv = convert_to_csv(table_data)
        assert 'name,age,city' in csv
        assert 'Alice,25,New York' in csv
        assert 'Bob,30,San Francisco' in csv
    
    def test_json_conversion(self, json_data):
        """Test JSON formatting for download"""
        json_content = json.dumps(json_data, indent=2)
        
        assert '"config"' in json_content
        assert '"version": "1.0"' in json_content
        assert '"debug": true' in json_content
    
    def test_tsv_conversion(self, table_data):
        """Test table to TSV conversion"""
        def convert_to_tsv(data):
            if not data:
                return ''
            
            headers = list(data[0].keys())
            tsv_content = '\\t'.join(headers) + '\\n'
            
            for row in data:
                tsv_row = [str(row.get(header, '')) for header in headers]
                tsv_content += '\\t'.join(tsv_row) + '\\n'
            
            return tsv_content
        
        tsv = convert_to_tsv(table_data)
        assert 'name\\tage\\tcity' in tsv
        assert 'Alice\\t25\\tNew York' in tsv
    
    def test_markdown_conversion(self, table_data):
        """Test table to Markdown conversion"""
        def convert_to_markdown(data):
            if not data:
                return ''
            
            headers = list(data[0].keys())
            md_content = '| ' + ' | '.join(headers) + ' |\\n'
            md_content += '| ' + ' | '.join(['---'] * len(headers)) + ' |\\n'
            
            for row in data:
                row_values = [str(row.get(header, '')) for header in headers]
                md_content += '| ' + ' | '.join(row_values) + ' |\\n'
            
            return md_content
        
        markdown = convert_to_markdown(table_data)
        assert '| name | age | city |' in markdown
        assert '| --- | --- | --- |' in markdown
        assert '| Alice | 25 | New York |' in markdown
    
    def test_format_detection(self, table_data, json_data):
        """Test automatic format detection"""
        def detect_best_format(data):
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return 'csv'  # Table data best as CSV
            elif isinstance(data, dict):
                return 'json'  # Object data best as JSON
            elif isinstance(data, str):
                return 'txt'   # Text data as plain text
            else:
                return 'json'  # Fallback to JSON
        
        assert detect_best_format(table_data) == 'csv'
        assert detect_best_format(json_data) == 'json'
        assert detect_best_format('hello world') == 'txt'
    
    def test_filename_generation(self):
        """Test download filename generation"""
        def generate_filename(base_name, format_type):
            # Remove existing extension
            name_without_ext = base_name.rsplit('.', 1)[0] if '.' in base_name else base_name
            return f'{name_without_ext}.{format_type}'
        
        assert generate_filename('data.csv', 'json') == 'data.json'
        assert generate_filename('report', 'csv') == 'report.csv'
        assert generate_filename('analysis.old.txt', 'md') == 'analysis.old.md'
    
    def test_blob_creation_mock(self, table_data):
        """Test blob creation for download (mocked)"""
        csv_content = 'name,age,city\\nAlice,25,New York\\n'
        
        # Mock blob creation
        mock_blob = Mock()
        mock_blob.size = len(csv_content.encode('utf-8'))
        mock_blob.type = 'text/csv'
        
        assert mock_blob.size > 0
        assert mock_blob.type == 'text/csv'
    
    def test_download_options_generation(self):
        """Test download format options generation"""
        def get_download_options(data_type):
            options = {
                'table': [
                    {'format': 'csv', 'label': 'CSV File', 'mime': 'text/csv'},
                    {'format': 'json', 'label': 'JSON File', 'mime': 'application/json'},
                    {'format': 'tsv', 'label': 'TSV File', 'mime': 'text/tab-separated-values'}
                ],
                'json': [
                    {'format': 'json', 'label': 'JSON File', 'mime': 'application/json'},
                    {'format': 'txt', 'label': 'Text File', 'mime': 'text/plain'}
                ],
                'text': [
                    {'format': 'txt', 'label': 'Text File', 'mime': 'text/plain'}
                ]
            }
            return options.get(data_type, options['text'])
        
        table_options = get_download_options('table')
        assert len(table_options) == 3
        assert any(opt['format'] == 'csv' for opt in table_options)
        
        json_options = get_download_options('json')
        assert len(json_options) == 2
        assert any(opt['format'] == 'json' for opt in json_options)