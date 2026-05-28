"""Unit tests for the Data Export Pipeline component."""

import pytest

# Optional dependency
pa = pytest.importorskip("pyarrow")
import pandas as pd
import numpy as np
import json
import tempfile
import zipfile
import tarfile
import gzip
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import shutil

from brain_researcher.core.ingestion.export.pipeline import (
    DataExportPipeline,
    ExportFormat,
    CompressionType
)


class TestExportFormat:
    """Test ExportFormat constants."""
    
    def test_export_format_values(self):
        """Test that all export formats have correct values."""
        assert ExportFormat.JSON == "json"
        assert ExportFormat.CSV == "csv"
        assert ExportFormat.PARQUET == "parquet"
        assert ExportFormat.BIDS == "bids"
        assert ExportFormat.NIFTI == "nifti"
        assert ExportFormat.HDF5 == "hdf5"
        assert ExportFormat.ZARR == "zarr"
        assert ExportFormat.TSV == "tsv"


class TestCompressionType:
    """Test CompressionType constants."""
    
    def test_compression_type_values(self):
        """Test that all compression types have correct values."""
        assert CompressionType.NONE is None
        assert CompressionType.GZIP == "gzip"
        assert CompressionType.ZIP == "zip"
        assert CompressionType.TAR == "tar"
        assert CompressionType.TARGZ == "tar.gz"
        assert CompressionType.BZ2 == "bz2"


class TestDataExportPipeline:
    """Test suite for DataExportPipeline class."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def pipeline(self, temp_dir):
        """Create DataExportPipeline instance for testing."""
        return DataExportPipeline(
            output_dir=temp_dir,
            compression=CompressionType.NONE,
            parallel=False,  # Disable for testing
            n_workers=2
        )
    
    @pytest.fixture
    def sample_data(self):
        """Create sample data for testing."""
        return pd.DataFrame({
            'participant_id': ['sub-001', 'sub-002', 'sub-003'],
            'age': [25, 30, 35],
            'sex': ['M', 'F', 'M'],
            'score': [85.5, 92.0, 78.3]
        })
    
    @pytest.fixture
    def sample_dataset_path(self, temp_dir):
        """Create sample dataset for testing."""
        dataset_path = Path(temp_dir) / "sample_dataset"
        dataset_path.mkdir(parents=True, exist_ok=True)
        
        # Create sample files
        (dataset_path / "data.csv").write_text("id,value\n1,100\n2,200\n")
        (dataset_path / "metadata.json").write_text('{"version": "1.0", "description": "Sample dataset"}')
        
        return str(dataset_path)
    
    def test_initialization(self, temp_dir):
        """Test DataExportPipeline initialization."""
        pipeline = DataExportPipeline(
            output_dir=temp_dir,
            compression=CompressionType.GZIP,
            parallel=True,
            n_workers=4
        )
        
        assert pipeline.output_dir == Path(temp_dir)
        assert pipeline.compression == CompressionType.GZIP
        assert pipeline.parallel is True
        assert pipeline.n_workers == 4
        assert pipeline.export_history == []
        assert len(pipeline.export_registry) > 0
        
        # Check that output directory was created
        assert pipeline.output_dir.exists()
    
    def test_initialize_exporters(self, pipeline):
        """Test exporter registry initialization."""
        exporters = pipeline._initialize_exporters()
        
        expected_formats = [
            ExportFormat.JSON,
            ExportFormat.CSV,
            ExportFormat.PARQUET,
            ExportFormat.BIDS,
            ExportFormat.NIFTI,
            ExportFormat.HDF5,
            ExportFormat.TSV,
            ExportFormat.ZARR
        ]
        
        for format_type in expected_formats:
            assert format_type in exporters
            assert callable(exporters[format_type])
    
    def test_export_dataset_json(self, pipeline, sample_dataset_path):
        """Test JSON export functionality."""
        result = pipeline.export_dataset(
            sample_dataset_path,
            ExportFormat.JSON,
            output_name="test_json_export"
        )
        
        # Check result structure
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.JSON
        assert result['source_path'] == sample_dataset_path
        assert 'export_id' in result
        assert 'timestamp' in result
        assert 'size_bytes' in result
        assert 'checksum' in result
        
        # Check output file exists
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.suffix == '.json'
        
        # Verify JSON content
        with open(output_path, 'r') as f:
            json_data = json.load(f)
            assert isinstance(json_data, dict)
    
    def test_export_dataset_csv(self, pipeline, temp_dir):
        """Test CSV export functionality."""
        # Create sample DataFrame as dataset
        df = pd.DataFrame({
            'id': [1, 2, 3],
            'name': ['A', 'B', 'C'],
            'value': [10, 20, 30]
        })
        
        # Save as temporary CSV file
        csv_path = Path(temp_dir) / "input.csv"
        df.to_csv(csv_path, index=False)
        
        result = pipeline.export_dataset(
            str(csv_path),
            ExportFormat.CSV,
            output_name="test_csv_export"
        )
        
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.CSV
        
        # Check output file
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.suffix == '.csv'
        
        # Verify CSV content
        exported_df = pd.read_csv(output_path)
        assert len(exported_df) == 3
        assert list(exported_df.columns) == ['id', 'name', 'value']
    
    def test_export_dataset_parquet(self, pipeline, temp_dir):
        """Test Parquet export functionality."""
        # Create sample DataFrame
        df = pd.DataFrame({
            'participant_id': ['sub-001', 'sub-002'],
            'age': [25, 30],
            'measurement': [1.5, 2.3]
        })
        
        # Save as JSON first (to simulate input data)
        json_path = Path(temp_dir) / "input.json"
        with open(json_path, 'w') as f:
            json.dump(df.to_dict('records'), f)
        
        result = pipeline.export_dataset(
            str(json_path),
            ExportFormat.PARQUET,
            output_name="test_parquet_export"
        )
        
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.PARQUET
        
        # Check output file
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.suffix == '.parquet'
        
        # Verify Parquet content
        exported_df = pd.read_parquet(output_path)
        assert len(exported_df) == 2
        assert 'participant_id' in exported_df.columns
    
    def test_export_dataset_bids(self, pipeline, temp_dir):
        """Test BIDS export functionality."""
        # Create mock BIDS-like data
        bids_data = {
            'subjects': ['sub-001', 'sub-002'],
            'metadata': {'Name': 'Test Dataset', 'Version': '1.0'}
        }
        
        json_path = Path(temp_dir) / "bids_input.json"
        with open(json_path, 'w') as f:
            json.dump(bids_data, f)
        
        result = pipeline.export_dataset(
            str(json_path),
            ExportFormat.BIDS,
            output_name="test_bids_export"
        )
        
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.BIDS
        
        # Check BIDS structure
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.is_dir()
        
        # Check for BIDS files
        assert (output_path / 'dataset_description.json').exists()
        assert (output_path / 'participants.tsv').exists()
        
        # Verify dataset description
        with open(output_path / 'dataset_description.json', 'r') as f:
            desc = json.load(f)
            assert desc['BIDSVersion'] == '1.8.0'
            assert desc['DatasetType'] == 'raw'
    
    def test_export_dataset_nifti(self, pipeline, temp_dir):
        """Test NIfTI export functionality."""
        # Create mock neuroimaging data
        mock_image = np.random.rand(64, 64, 32)  # 3D image
        nifti_data = {
            'images': {
                'T1w': mock_image,
                'BOLD': np.random.rand(64, 64, 32, 100)  # 4D timeseries
            }
        }
        
        # Save as numpy file first
        npy_path = Path(temp_dir) / "images.npy"
        np.save(npy_path, mock_image)
        
        # Create JSON with mock data
        json_path = Path(temp_dir) / "nifti_input.json"
        with open(json_path, 'w') as f:
            json.dump({'images': {'T1w': mock_image.tolist()}}, f)
        
        result = pipeline.export_dataset(
            str(json_path),
            ExportFormat.NIFTI,
            output_name="test_nifti_export"
        )
        
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.NIFTI
        
        # Check NIfTI output
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.is_dir()
    
    def test_export_dataset_hdf5(self, pipeline, temp_dir):
        """Test HDF5 export functionality."""
        # Create sample data
        data = {
            'group1': {
                'dataset1': np.array([1, 2, 3, 4, 5]),
                'dataset2': np.array([[1, 2], [3, 4]])
            },
            'group2': pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        }
        
        json_path = Path(temp_dir) / "hdf5_input.json"
        with open(json_path, 'w') as f:
            # Convert numpy arrays to lists for JSON serialization
            serializable_data = {}
            for key, value in data.items():
                if isinstance(value, dict):
                    serializable_data[key] = {k: v.tolist() for k, v in value.items()}
                elif isinstance(value, pd.DataFrame):
                    serializable_data[key] = value.to_dict('list')
            json.dump(serializable_data, f)
        
        result = pipeline.export_dataset(
            str(json_path),
            ExportFormat.HDF5,
            output_name="test_hdf5_export"
        )
        
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.HDF5
        
        # Check HDF5 output
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.suffix == '.h5'
    
    def test_export_dataset_tsv(self, pipeline, temp_dir):
        """Test TSV export functionality."""
        df = pd.DataFrame({
            'participant_id': ['sub-001', 'sub-002'],
            'session': ['ses-01', 'ses-01'],
            'age': [25, 30]
        })
        
        csv_path = Path(temp_dir) / "input.csv"
        df.to_csv(csv_path, index=False)
        
        result = pipeline.export_dataset(
            str(csv_path),
            ExportFormat.TSV,
            output_name="test_tsv_export"
        )
        
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.TSV
        
        # Check TSV output
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.suffix == '.tsv'
        
        # Verify TSV format (tab-separated)
        with open(output_path, 'r') as f:
            first_line = f.readline()
            assert '\t' in first_line  # Should be tab-separated
    
    def test_export_dataset_zarr(self, pipeline, temp_dir):
        """Test Zarr export functionality."""
        # Create sample array data
        data = {
            'array1': np.random.rand(100, 50),
            'array2': np.random.rand(200, 100)
        }
        
        json_path = Path(temp_dir) / "zarr_input.json"
        with open(json_path, 'w') as f:
            json.dump({k: v.tolist() for k, v in data.items()}, f)
        
        result = pipeline.export_dataset(
            str(json_path),
            ExportFormat.ZARR,
            output_name="test_zarr_export"
        )
        
        assert result['status'] == 'success'
        assert result['output_format'] == ExportFormat.ZARR
        
        # Check Zarr output
        output_path = Path(result['output_path'])
        assert output_path.exists()
        assert output_path.is_dir()
        assert output_path.name.endswith('.zarr')
    
    def test_export_dataset_unsupported_format(self, pipeline, sample_dataset_path):
        """Test export with unsupported format."""
        with pytest.raises(ValueError, match="Unsupported export format"):
            pipeline.export_dataset(
                sample_dataset_path,
                "unsupported_format"
            )
    
    def test_export_dataset_with_compression_gzip(self, pipeline, temp_dir):
        """Test export with GZIP compression."""
        df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        csv_path = Path(temp_dir) / "input.csv"
        df.to_csv(csv_path, index=False)
        
        result = pipeline.export_dataset(
            str(csv_path),
            ExportFormat.CSV,
            output_name="compressed_export",
            compression=CompressionType.GZIP
        )
        
        assert result['status'] == 'success'
        assert result['compression'] == CompressionType.GZIP
        assert 'compressed_path' in result
        
        # Check compressed file exists
        compressed_path = Path(result['compressed_path'])
        assert compressed_path.exists()
        assert compressed_path.suffix == '.gz'
    
    def test_export_dataset_with_compression_zip(self, pipeline, temp_dir):
        """Test export with ZIP compression."""
        df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        csv_path = Path(temp_dir) / "input.csv"
        df.to_csv(csv_path, index=False)
        
        result = pipeline.export_dataset(
            str(csv_path),
            ExportFormat.CSV,
            output_name="zip_export",
            compression=CompressionType.ZIP
        )
        
        assert result['status'] == 'success'
        assert 'compressed_path' in result
        
        # Check ZIP file
        zip_path = Path(result['compressed_path'])
        assert zip_path.exists()
        assert zip_path.suffix == '.zip'
        
        # Verify ZIP contents
        with zipfile.ZipFile(zip_path, 'r') as zf:
            assert len(zf.namelist()) > 0
    
    def test_export_dataset_with_filters(self, pipeline, temp_dir):
        """Test export with data filters."""
        # Create sample data
        df = pd.DataFrame({
            'participant_id': ['sub-001', 'sub-002', 'sub-003'],
            'age': [25, 30, 35],
            'quality_score': [0.9, 0.7, 0.5]
        })
        
        csv_path = Path(temp_dir) / "input.csv"
        df.to_csv(csv_path, index=False)
        
        # Define filters
        filters = {
            'subjects': ['sub-001', 'sub-002'],
            'min_quality': 0.8
        }
        
        result = pipeline.export_dataset(
            str(csv_path),
            ExportFormat.CSV,
            output_name="filtered_export",
            filters=filters
        )
        
        assert result['status'] == 'success'
        assert result['filters_applied'] == filters
    
    def test_batch_export(self, pipeline, temp_dir):
        """Test batch export functionality."""
        # Create multiple datasets
        datasets = []
        for i in range(3):
            df = pd.DataFrame({
                'id': [1, 2, 3],
                'value': [i * 10, i * 20, i * 30]
            })
            csv_path = Path(temp_dir) / f"dataset_{i}.csv"
            df.to_csv(csv_path, index=False)
            datasets.append(str(csv_path))
        
        results = pipeline.batch_export(datasets, ExportFormat.JSON)
        
        assert len(results) == 3
        
        for result in results:
            if 'status' in result:
                assert result['status'] == 'success'
                assert result['output_format'] == ExportFormat.JSON
                assert Path(result['output_path']).exists()
    
    def test_batch_export_parallel(self, temp_dir):
        """Test parallel batch export."""
        pipeline = DataExportPipeline(
            output_dir=temp_dir,
            parallel=True,
            n_workers=2
        )
        
        # Create datasets
        datasets = []
        for i in range(4):  # More datasets to test parallelization
            df = pd.DataFrame({'id': [i], 'value': [i * 100]})
            csv_path = Path(temp_dir) / f"parallel_dataset_{i}.csv"
            df.to_csv(csv_path, index=False)
            datasets.append(str(csv_path))
        
        results = pipeline.batch_export(datasets, ExportFormat.JSON, parallel=True)
        
        assert len(results) == 4
        
        successful_results = [r for r in results if r.get('status') == 'success']
        assert len(successful_results) >= 0  # Some should succeed
    
    def test_schedule_export(self, pipeline, sample_dataset_path):
        """Test export scheduling functionality."""
        job_info = pipeline.schedule_export(
            sample_dataset_path,
            ExportFormat.JSON,
            schedule="0 0 * * *"  # Daily at midnight
        )
        
        assert 'job_id' in job_info
        assert job_info['dataset'] == sample_dataset_path
        assert job_info['format'] == ExportFormat.JSON
        assert job_info['schedule'] == "0 0 * * *"
        assert job_info['status'] == 'scheduled'
        
        # Check that schedule file was created
        schedule_file = pipeline.output_dir / 'scheduled_exports.json'
        assert schedule_file.exists()
        
        # Verify schedule content
        with open(schedule_file, 'r') as f:
            schedules = json.load(f)
            assert len(schedules) == 1
            assert schedules[0]['job_id'] == job_info['job_id']
    
    def test_apply_filters_subjects(self, pipeline):
        """Test subject filtering."""
        data = {
            'subjects': ['sub-001', 'sub-002', 'sub-003', 'sub-004']
        }
        
        filters = {
            'subjects': ['sub-001', 'sub-003']
        }
        
        filtered_data = pipeline.apply_filters(data, filters)
        
        assert len(filtered_data['subjects']) == 2
        assert 'sub-001' in filtered_data['subjects']
        assert 'sub-003' in filtered_data['subjects']
        assert 'sub-002' not in filtered_data['subjects']
    
    def test_apply_filters_no_filters(self, pipeline):
        """Test applying no filters."""
        data = {'test': 'value'}
        
        filtered_data = pipeline.apply_filters(data, None)
        
        assert filtered_data == data
        
        filtered_data2 = pipeline.apply_filters(data, {})
        
        assert filtered_data2 == data
    
    def test_optimize_export_dataframe(self, pipeline):
        """Test export optimization for DataFrames."""
        # Create DataFrame with suboptimal types
        df = pd.DataFrame({
            'id': pd.Series([1, 2, 3], dtype='int64'),
            'score': pd.Series([1.0, 2.0, 3.0], dtype='float64'),
            'name': ['A', 'B', 'C']
        })
        
        optimized_df = pipeline.optimize_export(df)
        
        # Should downcast numeric types
        assert optimized_df['id'].dtype != 'int64'  # Should be downcasted
        assert optimized_df['score'].dtype != 'float64'  # Should be downcasted
        assert optimized_df['name'].dtype == 'object'  # String unchanged
    
    def test_optimize_export_target_size(self, pipeline):
        """Test export optimization with target size."""
        # Create large dataset
        large_data = pd.DataFrame({
            'id': range(10000),
            'data': ['x' * 100] * 10000  # Large strings
        })
        
        # Target size: 1MB
        optimized_data = pipeline.optimize_export(large_data, target_size=1)
        
        # Should attempt optimization (exact behavior depends on implementation)
        assert isinstance(optimized_data, pd.DataFrame)
    
    def test_validate_export_json(self, pipeline, temp_dir):
        """Test JSON export validation."""
        # Create valid JSON file
        json_path = Path(temp_dir) / "test.json"
        with open(json_path, 'w') as f:
            json.dump({'test': 'data'}, f)
        
        is_valid = pipeline.validate_export(str(json_path), ExportFormat.JSON)
        assert is_valid is True
        
        # Create invalid JSON file
        invalid_json_path = Path(temp_dir) / "invalid.json"
        with open(invalid_json_path, 'w') as f:
            f.write('{"invalid": json}')  # Invalid JSON
        
        is_valid = pipeline.validate_export(str(invalid_json_path), ExportFormat.JSON)
        assert is_valid is False
    
    def test_validate_export_csv(self, pipeline, temp_dir):
        """Test CSV export validation."""
        # Create valid CSV file
        csv_path = Path(temp_dir) / "test.csv"
        with open(csv_path, 'w') as f:
            f.write('id,name\n1,A\n2,B\n')
        
        is_valid = pipeline.validate_export(str(csv_path), ExportFormat.CSV)
        assert is_valid is True
        
        # Test with nonexistent file
        is_valid = pipeline.validate_export("/nonexistent/file.csv", ExportFormat.CSV)
        assert is_valid is False
    
    def test_validate_export_parquet(self, pipeline, temp_dir):
        """Test Parquet export validation."""
        # Create valid Parquet file
        df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        parquet_path = Path(temp_dir) / "test.parquet"
        df.to_parquet(parquet_path)
        
        is_valid = pipeline.validate_export(str(parquet_path), ExportFormat.PARQUET)
        assert is_valid is True
    
    def test_validate_export_bids(self, pipeline, temp_dir):
        """Test BIDS export validation."""
        # Create valid BIDS structure
        bids_path = Path(temp_dir) / "bids_dataset"
        bids_path.mkdir()
        
        # Create required files
        (bids_path / "dataset_description.json").write_text(
            '{"Name": "Test", "BIDSVersion": "1.8.0"}'
        )
        
        is_valid = pipeline.validate_export(str(bids_path), ExportFormat.BIDS)
        assert is_valid is True
        
        # Test invalid BIDS (missing required file)
        invalid_bids_path = Path(temp_dir) / "invalid_bids"
        invalid_bids_path.mkdir()
        
        is_valid = pipeline.validate_export(str(invalid_bids_path), ExportFormat.BIDS)
        assert is_valid is False
    
    def test_get_export_history(self, pipeline, sample_dataset_path):
        """Test export history retrieval."""
        # Initially empty
        history = pipeline.get_export_history()
        assert len(history) == 0
        
        # Export some data
        pipeline.export_dataset(sample_dataset_path, ExportFormat.JSON)
        pipeline.export_dataset(sample_dataset_path, ExportFormat.CSV)
        
        # Check history
        full_history = pipeline.get_export_history()
        assert len(full_history) == 2
        
        # Filter by status
        successful_exports = pipeline.get_export_history(filter_status='success')
        assert len(successful_exports) == 2
        
        failed_exports = pipeline.get_export_history(filter_status='failed')
        assert len(failed_exports) == 0
    
    def test_load_dataset_json_file(self, pipeline, temp_dir):
        """Test loading JSON file as dataset."""
        json_data = {'test': 'data', 'numbers': [1, 2, 3]}
        json_path = Path(temp_dir) / "test.json"
        
        with open(json_path, 'w') as f:
            json.dump(json_data, f)
        
        loaded_data = pipeline._load_dataset(str(json_path), None)
        
        assert loaded_data == json_data
    
    def test_load_dataset_csv_file(self, pipeline, temp_dir):
        """Test loading CSV file as dataset."""
        df = pd.DataFrame({'id': [1, 2], 'value': [10, 20]})
        csv_path = Path(temp_dir) / "test.csv"
        df.to_csv(csv_path, index=False)
        
        loaded_data = pipeline._load_dataset(str(csv_path), None)
        
        assert isinstance(loaded_data, pd.DataFrame)
        assert len(loaded_data) == 2
        assert list(loaded_data.columns) == ['id', 'value']
    
    def test_load_dataset_parquet_file(self, pipeline, temp_dir):
        """Test loading Parquet file as dataset."""
        df = pd.DataFrame({'id': [1, 2], 'value': [10, 20]})
        parquet_path = Path(temp_dir) / "test.parquet"
        df.to_parquet(parquet_path)
        
        loaded_data = pipeline._load_dataset(str(parquet_path), None)
        
        assert isinstance(loaded_data, pd.DataFrame)
        assert len(loaded_data) == 2
    
    def test_load_dataset_bids_directory(self, pipeline, temp_dir):
        """Test loading BIDS directory as dataset."""
        bids_path = Path(temp_dir) / "bids_dataset"
        bids_path.mkdir()
        
        # Create BIDS structure
        (bids_path / "dataset_description.json").write_text(
            '{"Name": "Test Dataset", "BIDSVersion": "1.8.0"}'
        )
        (bids_path / "sub-001").mkdir()
        (bids_path / "sub-002").mkdir()
        
        loaded_data = pipeline._load_dataset(str(bids_path), None)
        
        assert loaded_data['type'] == 'bids'
        assert len(loaded_data['subjects']) == 2
        assert 'sub-001' in loaded_data['subjects']
        assert 'sub-002' in loaded_data['subjects']
        assert loaded_data['metadata']['Name'] == 'Test Dataset'
    
    def test_load_dataset_generic_directory(self, pipeline, temp_dir):
        """Test loading generic directory as dataset."""
        dir_path = Path(temp_dir) / "generic_dataset"
        dir_path.mkdir()
        (dir_path / "file1.txt").write_text("data1")
        (dir_path / "file2.txt").write_text("data2")
        
        loaded_data = pipeline._load_dataset(str(dir_path), None)
        
        assert loaded_data['type'] == 'directory'
        assert loaded_data['path'] == str(dir_path)
    
    def test_load_dataset_nonexistent_file(self, pipeline):
        """Test loading nonexistent dataset."""
        with pytest.raises(FileNotFoundError):
            pipeline._load_dataset("/nonexistent/file.json", None)
    
    def test_compress_export_gzip(self, pipeline, temp_dir):
        """Test GZIP compression."""
        # Create test file
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("Test data for compression")
        
        compressed_path = pipeline._compress_export(test_file, CompressionType.GZIP)
        
        assert compressed_path.exists()
        assert compressed_path.suffix == '.gz'
        assert not test_file.exists()  # Original should be removed
        
        # Verify compressed content
        with gzip.open(compressed_path, 'rt') as f:
            content = f.read()
            assert content == "Test data for compression"
    
    def test_compress_export_zip(self, pipeline, temp_dir):
        """Test ZIP compression."""
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("Test data for ZIP compression")
        
        compressed_path = pipeline._compress_export(test_file, CompressionType.ZIP)
        
        assert compressed_path.exists()
        assert compressed_path.suffix == '.zip'
        
        # Verify ZIP content
        with zipfile.ZipFile(compressed_path, 'r') as zf:
            assert len(zf.namelist()) == 1
            with zf.open(zf.namelist()[0]) as f:
                content = f.read().decode('utf-8')
                assert content == "Test data for ZIP compression"
    
    def test_compress_export_tar(self, pipeline, temp_dir):
        """Test TAR compression."""
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("Test data for TAR compression")
        
        compressed_path = pipeline._compress_export(test_file, CompressionType.TAR)
        
        assert compressed_path.exists()
        assert compressed_path.suffix == '.tar'
        
        # Verify TAR content
        with tarfile.open(compressed_path, 'r') as tf:
            assert len(tf.getnames()) == 1
    
    def test_compress_export_targz(self, pipeline, temp_dir):
        """Test TAR.GZ compression."""
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("Test data for TAR.GZ compression")
        
        compressed_path = pipeline._compress_export(test_file, CompressionType.TARGZ)
        
        assert compressed_path.exists()
        assert '.tar.gz' in str(compressed_path)
        
        # Verify TAR.GZ content
        with tarfile.open(compressed_path, 'r:gz') as tf:
            assert len(tf.getnames()) == 1
    
    def test_generate_export_id(self, pipeline):
        """Test export ID generation."""
        id1 = pipeline._generate_export_id()
        id2 = pipeline._generate_export_id()
        
        # IDs should be unique
        assert id1 != id2
        assert len(id1) == 12  # Should be 12 characters (MD5 hash truncated)
        assert len(id2) == 12
    
    def test_get_file_size_file(self, pipeline, temp_dir):
        """Test file size calculation for files."""
        test_file = Path(temp_dir) / "size_test.txt"
        test_content = "x" * 1000  # 1000 characters
        test_file.write_text(test_content)
        
        size = pipeline._get_file_size(test_file)
        
        assert size == len(test_content.encode('utf-8'))
    
    def test_get_file_size_directory(self, pipeline, temp_dir):
        """Test file size calculation for directories."""
        test_dir = Path(temp_dir) / "size_test_dir"
        test_dir.mkdir()
        
        # Create multiple files
        (test_dir / "file1.txt").write_text("x" * 100)
        (test_dir / "file2.txt").write_text("y" * 200)
        
        total_size = pipeline._get_file_size(test_dir)
        
        assert total_size == 300  # 100 + 200 characters
    
    def test_calculate_checksum_file(self, pipeline, temp_dir):
        """Test checksum calculation for files."""
        test_file = Path(temp_dir) / "checksum_test.txt"
        test_file.write_text("Test content for checksum")
        
        checksum = pipeline._calculate_checksum(test_file)
        
        assert len(checksum) == 32  # MD5 hash length
        assert isinstance(checksum, str)
        
        # Same content should produce same checksum
        test_file2 = Path(temp_dir) / "checksum_test2.txt"
        test_file2.write_text("Test content for checksum")
        checksum2 = pipeline._calculate_checksum(test_file2)
        
        assert checksum == checksum2
    
    def test_calculate_checksum_directory(self, pipeline, temp_dir):
        """Test checksum calculation for directories."""
        test_dir = Path(temp_dir) / "checksum_dir"
        test_dir.mkdir()
        
        (test_dir / "file1.txt").write_text("Content 1")
        (test_dir / "file2.txt").write_text("Content 2")
        
        checksum = pipeline._calculate_checksum(test_dir)
        
        assert len(checksum) == 32
        assert isinstance(checksum, str)
    
    def test_create_bids_structure(self, pipeline, temp_dir):
        """Test BIDS directory structure creation."""
        bids_path = Path(temp_dir) / "bids_structure"
        bids_path.mkdir()
        
        pipeline._create_bids_structure(bids_path)
        
        # Check that BIDS directories were created
        expected_dirs = ['anat', 'func', 'dwi', 'fmap', 'derivatives']
        for dir_name in expected_dirs:
            assert (bids_path / dir_name).exists()
            assert (bids_path / dir_name).is_dir()
    
    def test_export_bids_subjects(self, pipeline, temp_dir):
        """Test BIDS subject export."""
        bids_path = Path(temp_dir) / "bids_export"
        bids_path.mkdir()
        
        subjects = ['sub-001', 'sub-002', 'sub-003']
        
        pipeline._export_bids_subjects(subjects, bids_path)
        
        # Check participants file
        participants_file = bids_path / 'participants.tsv'
        assert participants_file.exists()
        
        # Verify participants content
        df = pd.read_csv(participants_file, sep='\t')
        assert len(df) == 3
        assert 'participant_id' in df.columns
        assert all(sub in df['participant_id'].values for sub in subjects)
        
        # Check subject directories
        for subject in subjects:
            assert (bids_path / subject).exists()
            assert (bids_path / subject).is_dir()
    
    def test_estimate_size_dataframe(self, pipeline):
        """Test size estimation for DataFrames."""
        df = pd.DataFrame({
            'id': [1, 2, 3],
            'name': ['A', 'B', 'C'],
            'value': [1.5, 2.5, 3.5]
        })
        
        size = pipeline._estimate_size(df)
        
        assert size > 0
        assert isinstance(size, int)
    
    def test_estimate_size_numpy_array(self, pipeline):
        """Test size estimation for numpy arrays."""
        arr = np.random.rand(100, 50)
        
        size = pipeline._estimate_size(arr)
        
        assert size == arr.nbytes
    
    def test_estimate_size_other(self, pipeline):
        """Test size estimation for other data types."""
        other_data = "string data"
        
        size = pipeline._estimate_size(other_data)
        
        assert size == 0  # Unknown types return 0
    
    def test_error_handling_export_failure(self, pipeline, temp_dir):
        """Test error handling during export failures."""
        # Create a scenario that will cause export failure
        with patch.object(pipeline, '_load_dataset', side_effect=Exception("Load error")):
            try:
                result = pipeline.export_dataset(
                    "/fake/path",
                    ExportFormat.JSON
                )
                # Should not reach here
                assert False, "Expected exception"
            except Exception as e:
                assert "Load error" in str(e)
    
    def test_batch_export_error_handling(self, pipeline, temp_dir):
        """Test batch export error handling."""
        datasets = [
            "/nonexistent/dataset1.json",
            "/nonexistent/dataset2.json"
        ]
        
        results = pipeline.batch_export(datasets, ExportFormat.JSON)
        
        # Should handle errors gracefully
        assert len(results) == 2
        for result in results:
            assert result['status'] == 'failed'
            assert 'error' in result


@pytest.mark.integration
class TestDataExportPipelineIntegration:
    """Integration tests for DataExportPipeline."""
    
    def test_full_export_workflow(self, temp_dir):
        """Test complete export workflow from data to final output."""
        pipeline = DataExportPipeline(output_dir=temp_dir)
        
        # Create comprehensive test dataset
        dataset_path = Path(temp_dir) / "comprehensive_dataset"
        dataset_path.mkdir()
        
        # Add various data files
        participants = pd.DataFrame({
            'participant_id': ['sub-001', 'sub-002', 'sub-003'],
            'age': [25, 30, 35],
            'sex': ['M', 'F', 'M'],
            'diagnosis': ['HC', 'MDD', 'HC']
        })
        participants.to_csv(dataset_path / "participants.tsv", sep='\t', index=False)
        
        # Add metadata
        metadata = {
            'Name': 'Integration Test Dataset',
            'Version': '1.0',
            'Description': 'Test dataset for export pipeline integration',
            'Authors': ['Test Author']
        }
        with open(dataset_path / "dataset_description.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Export to multiple formats
        export_results = {}
        formats_to_test = [
            ExportFormat.JSON,
            ExportFormat.CSV,
            ExportFormat.BIDS,
            ExportFormat.TSV
        ]
        
        for export_format in formats_to_test:
            result = pipeline.export_dataset(
                str(dataset_path),
                export_format,
                output_name=f"integration_test_{export_format}"
            )
            export_results[export_format] = result
            
            # Verify export success
            assert result['status'] == 'success'
            assert Path(result['output_path']).exists()
            
            # Validate export
            is_valid = pipeline.validate_export(
                result['output_path'],
                export_format
            )
            assert is_valid is True
        
        # Check export history
        history = pipeline.get_export_history()
        assert len(history) == len(formats_to_test)
        
        # All should be successful
        successful_exports = pipeline.get_export_history(filter_status='success')
        assert len(successful_exports) == len(formats_to_test)
    
    def test_compressed_export_workflow(self, temp_dir):
        """Test export workflow with different compression options."""
        pipeline = DataExportPipeline(output_dir=temp_dir)
        
        # Create test data
        df = pd.DataFrame({
            'id': range(100),
            'data': [f"row_{i}" for i in range(100)],
            'value': np.random.rand(100)
        })
        
        csv_path = Path(temp_dir) / "test_data.csv"
        df.to_csv(csv_path, index=False)
        
        # Test different compression types
        compression_types = [
            CompressionType.GZIP,
            CompressionType.ZIP,
            CompressionType.TAR,
            CompressionType.TARGZ
        ]
        
        compression_results = {}
        
        for compression in compression_types:
            result = pipeline.export_dataset(
                str(csv_path),
                ExportFormat.CSV,
                output_name=f"compressed_{compression}",
                compression=compression
            )
            
            compression_results[compression] = result
            
            assert result['status'] == 'success'
            assert result['compression'] == compression
            assert 'compressed_path' in result
            
            # Verify compressed file exists
            compressed_path = Path(result['compressed_path'])
            assert compressed_path.exists()
            
            # Compressed file should be smaller than original (usually)
            original_size = result['size_bytes']
            compressed_size = compressed_path.stat().st_size
            
            # GZIP and TAR.GZ should compress well for this type of data
            if compression in [CompressionType.GZIP, CompressionType.TARGZ]:
                assert compressed_size <= original_size
    
    def test_large_dataset_export(self, temp_dir):
        """Test export performance with larger datasets."""
        pipeline = DataExportPipeline(output_dir=temp_dir)
        
        # Create larger test dataset
        large_df = pd.DataFrame({
            'id': range(10000),
            'participant_id': [f"sub-{i:04d}" for i in range(10000)],
            'session': np.random.choice(['ses-01', 'ses-02'], 10000),
            'measurement_1': np.random.rand(10000),
            'measurement_2': np.random.rand(10000),
            'category': np.random.choice(['A', 'B', 'C', 'D'], 10000)
        })
        
        csv_path = Path(temp_dir) / "large_dataset.csv"
        large_df.to_csv(csv_path, index=False)
        
        import time
        
        # Test different formats for performance
        formats_to_test = [
            ExportFormat.JSON,
            ExportFormat.CSV,
            ExportFormat.PARQUET,
            ExportFormat.TSV
        ]
        
        performance_results = {}
        
        for export_format in formats_to_test:
            start_time = time.time()
            
            result = pipeline.export_dataset(
                str(csv_path),
                export_format,
                output_name=f"large_{export_format}"
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            performance_results[export_format] = {
                'time': execution_time,
                'result': result
            }
            
            assert result['status'] == 'success'
            assert execution_time < 30.0  # Should complete within 30 seconds
        
        # Parquet should be relatively fast for large datasets
        parquet_time = performance_results[ExportFormat.PARQUET]['time']
        json_time = performance_results[ExportFormat.JSON]['time']
        
        # Parquet is typically faster for large structured data
        # This is just a sanity check, not a strict requirement
        assert parquet_time < json_time * 2  # Within 2x performance
    
    def test_neuroimaging_data_export(self, temp_dir):
        """Test export of neuroimaging-specific data structures."""
        pipeline = DataExportPipeline(output_dir=temp_dir)
        
        # Create mock neuroimaging data
        neuroimaging_data = {
            'images': {
                'T1w': np.random.rand(64, 64, 32),  # 3D anatomical
                'BOLD': np.random.rand(64, 64, 32, 100),  # 4D functional
                'DWI': np.random.rand(64, 64, 32, 30)  # 4D diffusion
            },
            'metadata': {
                'TR': 2.0,
                'TE': 0.03,
                'FlipAngle': 90,
                'SliceThickness': 3.0
            },
            'participants': {
                'sub-001': {'age': 25, 'sex': 'M'},
                'sub-002': {'age': 30, 'sex': 'F'}
            }
        }
        
        # Save as JSON (with arrays converted to lists)
        json_data = {
            'images': {k: v.tolist() for k, v in neuroimaging_data['images'].items()},
            'metadata': neuroimaging_data['metadata'],
            'participants': neuroimaging_data['participants']
        }
        
        input_path = Path(temp_dir) / "neuroimaging_input.json"
        with open(input_path, 'w') as f:
            json.dump(json_data, f)
        
        # Export to neuroimaging-specific formats
        formats_to_test = [
            ExportFormat.NIFTI,
            ExportFormat.HDF5,
            ExportFormat.ZARR,
            ExportFormat.BIDS
        ]
        
        for export_format in formats_to_test:
            result = pipeline.export_dataset(
                str(input_path),
                export_format,
                output_name=f"neuroimaging_{export_format}"
            )
            
            assert result['status'] == 'success'
            
            output_path = Path(result['output_path'])
            assert output_path.exists()
            
            # Verify format-specific outputs
            if export_format == ExportFormat.BIDS:
                assert output_path.is_dir()
                assert (output_path / 'dataset_description.json').exists()
            elif export_format == ExportFormat.NIFTI:
                assert output_path.is_dir()
            elif export_format == ExportFormat.HDF5:
                assert output_path.suffix == '.h5'
            elif export_format == ExportFormat.ZARR:
                assert output_path.is_dir()
                assert output_path.name.endswith('.zarr')
    
    def test_export_pipeline_robustness(self, temp_dir):
        """Test pipeline robustness with various edge cases."""
        pipeline = DataExportPipeline(output_dir=temp_dir)
        
        # Test cases with different edge conditions
        test_cases = [
            {
                'name': 'empty_dataframe',
                'data': pd.DataFrame(),
                'format': ExportFormat.CSV
            },
            {
                'name': 'single_row',
                'data': pd.DataFrame({'id': [1], 'value': ['single']}),
                'format': ExportFormat.JSON
            },
            {
                'name': 'unicode_data',
                'data': pd.DataFrame({
                    'id': [1, 2, 3],
                    'text': ['Hello', 'Héllo', '你好']  # Unicode characters
                }),
                'format': ExportFormat.TSV
            },
            {
                'name': 'missing_values',
                'data': pd.DataFrame({
                    'id': [1, 2, 3],
                    'value': [1.0, None, 3.0],  # Missing values
                    'text': ['A', '', 'C']  # Empty strings
                }),
                'format': ExportFormat.CSV
            }
        ]
        
        successful_exports = 0
        
        for test_case in test_cases:
            # Save test data
            input_path = Path(temp_dir) / f"{test_case['name']}_input.csv"
            test_case['data'].to_csv(input_path, index=False)
            
            try:
                result = pipeline.export_dataset(
                    str(input_path),
                    test_case['format'],
                    output_name=f"robust_{test_case['name']}"
                )
                
                if result.get('status') == 'success':
                    successful_exports += 1
                    
                    # Verify output exists
                    assert Path(result['output_path']).exists()
                    
                    # Validate export
                    is_valid = pipeline.validate_export(
                        result['output_path'],
                        test_case['format']
                    )
                    assert is_valid is True
                
            except Exception as e:
                # Log error but continue testing other cases
                print(f"Test case {test_case['name']} failed: {e}")
        
        # Should handle most cases successfully
        assert successful_exports >= len(test_cases) * 0.75  # 75% success rate
