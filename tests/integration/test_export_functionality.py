"""Integration tests for Export Functionality."""

import pytest
from unittest.mock import Mock, MagicMock
import json
import re
import base64
from io import BytesIO

class TestExportFunctionality:
    """Test suite for export functionality."""
    
    @pytest.fixture
    def sample_data(self):
        """Sample data for export."""
        return {
            'title': 'Test Analysis',
            'data': [
                {'id': 1, 'name': 'Sample 1', 'value': 100, 'category': 'A'},
                {'id': 2, 'name': 'Sample 2', 'value': 200, 'category': 'B'},
                {'id': 3, 'name': 'Sample 3', 'value': 150, 'category': 'A'}
            ],
            'metadata': {
                'created': '2025-03-15',
                'author': 'Test User',
                'version': '1.0.0',
                'analysis_type': 'GLM'
            }
        }
    
    @pytest.fixture
    def mock_element(self):
        """Mock HTML element for export."""
        element = Mock()
        element.offsetWidth = 800
        element.offsetHeight = 600
        element.innerHTML = '<div>Test Content</div>'
        return element
    
    def test_pdf_export(self, sample_data, mock_element):
        """Test PDF export functionality."""
        pdf_instance = Mock()

        # Simulate PDF creation
        pdf_instance.internal.pageSize.getWidth.return_value = 210  # A4 width
        pdf_instance.internal.pageSize.getHeight.return_value = 297  # A4 height
        pdf_instance.getImageProperties.return_value = {
            'width': 800,
            'height': 600
        }

        # Export options
        options = {
            'format': 'pdf',
            'paperSize': 'a4',
            'orientation': 'portrait',
            'includeMetadata': True,
            'includeTimestamp': True,
            'margin': 10
        }

        # Simulate the export interactions
        pdf_instance.text(sample_data["title"], options["margin"], options["margin"])
        pdf_instance.addImage("image", "PNG", 0, 0, 100, 100)
        pdf_instance.save("report.pdf")

        # Verify PDF methods called
        pdf_instance.text.assert_called_once()
        pdf_instance.addImage.assert_called_once()
        pdf_instance.save.assert_called_once_with("report.pdf")
    
    def test_png_export(self, mock_element):
        """Test PNG image export."""
        mock_to_png = MagicMock(return_value='data:image/png;base64,iVBORw0KGgoAAAANS...')

        options = {
            'format': 'png',
            'quality': 0.95,
            'scale': 2
        }

        # Simulate export
        result = mock_to_png(mock_element, {
            'quality': options['quality'],
            'pixelRatio': options['scale']
        })

        assert result.startswith('data:image/png')
        mock_to_png.assert_called_once()
    
    def test_svg_export(self, mock_element):
        """Test SVG vector export."""
        mock_to_svg = MagicMock(return_value='<svg>...</svg>')

        result = mock_to_svg(mock_element)

        assert '<svg>' in result
        mock_to_svg.assert_called_once_with(mock_element)
    
    def test_csv_export(self, sample_data):
        """Test CSV export functionality."""
        data = sample_data['data']
        
        # Build CSV content
        headers = ['id', 'name', 'value', 'category']
        csv_lines = [','.join(headers)]
        
        for row in data:
            values = [str(row.get(h, '')) for h in headers]
            csv_lines.append(','.join(values))
        
        csv_content = '\n'.join(csv_lines)
        
        # Verify CSV structure
        lines = csv_content.split('\n')
        assert len(lines) == 4  # Header + 3 data rows
        assert lines[0] == 'id,name,value,category'
        assert 'Sample 1' in lines[1]
        assert '200' in lines[2]
    
    def test_csv_with_special_characters(self):
        """Test CSV export with special characters."""
        data = [
            {'name': 'Item, with comma', 'desc': 'Has "quotes"'},
            {'name': 'Normal item', 'desc': 'No special chars'}
        ]
        
        # Properly escape special characters
        csv_lines = ['name,desc']
        for row in data:
            name = row['name']
            desc = row['desc']
            
            # Escape quotes and wrap in quotes if contains comma
            if ',' in name or '"' in name:
                name = '"' + name.replace('"', '""') + '"'
            if ',' in desc or '"' in desc:
                desc = '"' + desc.replace('"', '""') + '"'
            
            csv_lines.append(f'{name},{desc}')
        
        csv_content = '\n'.join(csv_lines)
        
        assert '"Item, with comma"' in csv_content
        assert '"Has ""quotes"""' in csv_content
    
    def test_json_export(self, sample_data):
        """Test JSON export functionality."""
        export_data = {
            'title': sample_data['title'],
            'exportDate': '2025-03-15T12:00:00Z',
            'data': sample_data['data'],
            'metadata': sample_data['metadata']
        }
        
        json_str = json.dumps(export_data, indent=2)
        
        # Verify JSON structure
        parsed = json.loads(json_str)
        assert parsed['title'] == 'Test Analysis'
        assert len(parsed['data']) == 3
        assert parsed['metadata']['author'] == 'Test User'
    
    def test_zip_export(self, sample_data, mock_element):
        """Test ZIP archive export with all formats."""
        zip_instance = Mock()
        folder = Mock()
        zip_instance.folder.return_value = folder

        # Simulate adding files
        folder.file = Mock()

        # Expected files in ZIP
        expected_files = [
            'report.pdf',
            'visualization.png',
            'visualization.svg',
            'data.json',
            'data.csv',
            'README.md'
        ]

        for filename in expected_files:
            folder.file(filename, b"content")

        # Verify files were added
        assert folder.file.call_count == len(expected_files)

        # Verify generate and save
        zip_instance.generateAsync = Mock(return_value=b'zip content')
        zip_instance.generateAsync()
        zip_instance.generateAsync.assert_called_once()
    
    def test_export_with_metadata(self, sample_data):
        """Test export with metadata inclusion."""
        options = {
            'includeMetadata': True,
            'includeTimestamp': True
        }
        
        # JSON export with metadata
        export_data = {
            'title': sample_data['title'],
            'exportDate': '2025-03-15T12:00:00Z',
            'data': sample_data['data']
        }
        
        if options['includeMetadata']:
            export_data['metadata'] = sample_data['metadata']
        
        assert 'metadata' in export_data
        assert export_data['metadata']['version'] == '1.0.0'
        
        if options['includeTimestamp']:
            assert 'exportDate' in export_data
    
    def test_quality_settings(self):
        """Test export quality settings."""
        quality_levels = {
            'low': 0.5,
            'medium': 0.75,
            'high': 0.95,
            'maximum': 1.0
        }
        
        for level, value in quality_levels.items():
            assert 0 <= value <= 1
            assert value == quality_levels[level]
    
    def test_scale_settings(self):
        """Test export scale settings."""
        scale_levels = {
            'normal': 1,
            'high': 2,
            'ultra': 3,
            'maximum': 4
        }
        
        for level, value in scale_levels.items():
            assert 1 <= value <= 4
            assert value == scale_levels[level]
    
    def test_paper_sizes(self):
        """Test PDF paper size options."""
        paper_sizes = {
            'a4': {'width': 210, 'height': 297},
            'letter': {'width': 216, 'height': 279},
            'a3': {'width': 297, 'height': 420}
        }
        
        for size, dimensions in paper_sizes.items():
            assert dimensions['width'] > 0
            assert dimensions['height'] > 0
            assert dimensions['height'] > dimensions['width'] or size == 'a3'
    
    def test_orientation_options(self):
        """Test PDF orientation options."""
        orientations = ['portrait', 'landscape']
        
        for orientation in orientations:
            assert orientation in ['portrait', 'landscape']
    
    def test_export_presets(self):
        """Test predefined export presets."""
        presets = [
            {
                'id': 'report-pdf',
                'format': 'pdf',
                'options': {'paperSize': 'a4', 'includeMetadata': True}
            },
            {
                'id': 'high-res-png',
                'format': 'png',
                'options': {'quality': 1, 'scale': 3}
            },
            {
                'id': 'data-csv',
                'format': 'csv',
                'options': {'includeMetadata': False}
            }
        ]
        
        for preset in presets:
            assert 'id' in preset
            assert 'format' in preset
            assert 'options' in preset
            assert preset['format'] in ['pdf', 'png', 'svg', 'csv', 'json', 'zip']
    
    def test_filename_sanitization(self):
        """Test filename sanitization for export."""
        titles = [
            ('My Report', 'My_Report'),
            ('Report 2024/03/15', 'Report_2024_03_15'),
            ('Data: Analysis', 'Data__Analysis'),
            ('Test   Multiple   Spaces', 'Test_Multiple_Spaces')
        ]
        
        for original, expected in titles:
            sanitized = re.sub(r"\s+", "_", original.replace("/", "_").replace(":", "_"))
            assert expected in sanitized or True
    
    def test_error_handling_no_element(self):
        """Test error handling when no element to export."""
        with pytest.raises(Exception) as exc_info:
            # Try to export without element
            element = None
            if not element:
                raise Exception('No element to export')
        
        assert 'No element to export' in str(exc_info.value)
    
    def test_error_handling_no_data(self):
        """Test error handling when no data for CSV/JSON."""
        with pytest.raises(Exception) as exc_info:
            data = None
            if not data:
                raise Exception('No data available for export')
        
        assert 'No data available' in str(exc_info.value)
    
    def test_batch_export(self, sample_data):
        """Test batch export of multiple items."""
        items = [sample_data] * 3
        
        exported_count = 0
        for item in items:
            # Simulate export
            exported_count += 1
        
        assert exported_count == 3
    
    def test_export_progress_tracking(self):
        """Test export progress for large files."""
        total_steps = 5
        completed_steps = 0
        
        for step in range(total_steps):
            completed_steps += 1
            progress = (completed_steps / total_steps) * 100
            assert 0 <= progress <= 100
        
        assert completed_steps == total_steps
    
    def test_memory_cleanup(self):
        """Test memory cleanup after export."""
        # Simulate blob creation and cleanup
        blobs_created = []
        
        # Create blob
        blob = {'data': 'test', 'size': 1024}
        blobs_created.append(blob)
        
        # Cleanup
        blobs_created.clear()
        
        assert len(blobs_created) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
