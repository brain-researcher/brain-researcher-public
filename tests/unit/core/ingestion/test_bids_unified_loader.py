"""Unit tests for BIDS Unified Loader."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from brain_researcher.core.ingestion.loaders.bids_unified import BIDSUnifiedLoader
from brain_researcher.core.ingestion.validation.bids_validator import BIDSValidationResult


class TestBIDSUnifiedLoader:
    """Test BIDSUnifiedLoader class."""
    
    def test_init(self):
        """Test loader initialization."""
        loader = BIDSUnifiedLoader(
            db_path="/test/db.db",
            strict_validation=False,
            cache_results=True
        )
        
        assert loader.db_path == "/test/db.db"
        assert loader.strict_validation is False
        assert loader.cache_results is True
        assert loader.validator is not None
        assert loader._cache == {}
        assert loader.stats["datasets_processed"] == 0
    
    @patch.object(BIDSUnifiedLoader, '_store_result')
    def test_load_dataset_success(self, mock_store, tmp_path):
        """Test successful dataset loading."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        loader = BIDSUnifiedLoader()
        
        # Mock validator result
        with patch.object(loader.validator, 'validate_dataset') as mock_validate:
            mock_result = BIDSValidationResult()
            mock_result.is_valid = True
            mock_result.errors = []
            mock_result.warnings = []
            mock_result.metadata = {
                "dataset_description": {
                    "Name": "Test Dataset",
                    "BIDSVersion": "1.6.0"
                },
                "participants": {"count": 10},
                "tasks": ["rest"],
                "modalities": ["anat", "func"]
            }
            mock_result.quality_metrics = {"overall_quality_score": 85.0}
            mock_validate.return_value = mock_result
            
            result = loader.load_dataset(str(dataset_path))
            
            assert result["is_valid"] is True
            assert result["dataset_name"] == "Test Dataset"
            assert result["bids_version"] == "1.6.0"
            assert result["n_participants"] == 10
            assert result["tasks"] == ["rest"]
            assert result["modalities"] == ["anat", "func"]
            assert result["summary"]["quality_score"] == 85.0
    
    def test_load_dataset_with_cache(self, tmp_path):
        """Test dataset loading with caching."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        (dataset_path / "dataset_description.json").write_text('{}')
        
        loader = BIDSUnifiedLoader(cache_results=True)
        
        # Mock validator
        mock_result = BIDSValidationResult()
        mock_result.is_valid = True
        
        with patch.object(loader.validator, 'validate_dataset', return_value=mock_result) as mock_validate:
            # First load
            result1 = loader.load_dataset(str(dataset_path))
            assert mock_validate.call_count == 1
            
            # Second load should use cache
            result2 = loader.load_dataset(str(dataset_path))
            assert mock_validate.call_count == 1  # No additional call
            
            # Results should be the same
            assert result1["is_valid"] == result2["is_valid"]
    
    def test_load_batch(self, tmp_path):
        """Test batch loading of multiple datasets."""
        # Create test datasets
        dataset1 = tmp_path / "dataset1"
        dataset2 = tmp_path / "dataset2"
        dataset1.mkdir()
        dataset2.mkdir()
        
        loader = BIDSUnifiedLoader()
        
        with patch.object(loader, 'load_dataset') as mock_load:
            mock_load.side_effect = [
                {"is_valid": True, "dataset_name": "Dataset 1"},
                {"is_valid": False, "dataset_name": "Dataset 2"}
            ]
            
            results = loader.load_batch([str(dataset1), str(dataset2)])
            
            assert len(results) == 2
            assert results[str(dataset1)]["is_valid"] is True
            assert results[str(dataset2)]["is_valid"] is False
    
    def test_load_batch_with_error(self, tmp_path):
        """Test batch loading with error handling."""
        dataset1 = tmp_path / "dataset1"
        dataset2 = tmp_path / "nonexistent"
        dataset1.mkdir()
        
        loader = BIDSUnifiedLoader()
        
        with patch.object(loader, 'load_dataset') as mock_load:
            mock_load.side_effect = [
                {"is_valid": True},
                Exception("Dataset not found")
            ]
            
            results = loader.load_batch([str(dataset1), str(dataset2)])
            
            assert len(results) == 2
            assert results[str(dataset1)]["is_valid"] is True
            assert "error" in results[str(dataset2)]
            assert results[str(dataset2)]["is_valid"] is False
    
    def test_validate_only(self):
        """Test validation without metadata extraction."""
        loader = BIDSUnifiedLoader()
        
        with patch('brain_researcher.core.ingestion.validation.bids_validator.BIDSValidator') as MockValidator:
            mock_validator = MockValidator.return_value
            mock_result = BIDSValidationResult()
            mock_validator.validate_dataset.return_value = mock_result
            
            result = loader.validate_only("/test/dataset")
            
            MockValidator.assert_called_once_with(
                strict=loader.strict_validation,
                extract_metadata=False
            )
            mock_validator.validate_dataset.assert_called_once_with("/test/dataset")
    
    def test_get_dataset_info(self, tmp_path):
        """Test dataset info extraction."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        # Create dataset_description.json
        desc_file = dataset_path / "dataset_description.json"
        desc_content = {
            "Name": "Test Dataset",
            "BIDSVersion": "1.6.0"
        }
        desc_file.write_text(json.dumps(desc_content))
        
        # Create subject directories
        (dataset_path / "sub-01" / "anat").mkdir(parents=True)
        (dataset_path / "sub-01" / "func").mkdir(parents=True)
        (dataset_path / "sub-02" / "anat").mkdir(parents=True)
        
        # Create task file
        task_file = dataset_path / "sub-01" / "func" / "sub-01_task-rest_bold.json"
        task_file.write_text('{}')
        
        loader = BIDSUnifiedLoader()
        info = loader.get_dataset_info(str(dataset_path))
        
        assert info["description"]["Name"] == "Test Dataset"
        assert info["n_subjects"] == 2
        assert "rest" in info["tasks"]
        assert set(info["modalities"]) == {"anat", "func"}
    
    def test_check_incremental_changes_no_previous(self, tmp_path):
        """Test incremental change detection with no previous result."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        # Create some files
        (dataset_path / "file1.txt").write_text("content1")
        (dataset_path / "file2.txt").write_text("content2")
        
        loader = BIDSUnifiedLoader()
        changes = loader.check_incremental_changes(str(dataset_path))
        
        assert changes["has_changes"] is True
        assert len(changes["new_files"]) == 2
        assert len(changes["modified_files"]) == 0
        assert len(changes["deleted_files"]) == 0
    
    def test_check_incremental_changes_with_previous(self, tmp_path):
        """Test incremental change detection with previous result."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        # Create files
        file1 = dataset_path / "file1.txt"
        file1.write_text("content1")
        
        # Create mock previous result
        previous_result = BIDSValidationResult()
        previous_result.file_list = {
            "file1.txt": file1.stat().st_mtime - 100,  # Old timestamp
            "file2.txt": 123456789  # Deleted file
        }
        
        loader = BIDSUnifiedLoader()
        changes = loader.check_incremental_changes(str(dataset_path), previous_result)
        
        assert changes["has_changes"] is True
        assert len(changes["new_files"]) == 0
        assert len(changes["modified_files"]) == 1  # file1.txt modified
        assert len(changes["deleted_files"]) == 1  # file2.txt deleted
    
    def test_format_result(self):
        """Test result formatting."""
        validation_result = BIDSValidationResult()
        validation_result.is_valid = True
        validation_result.errors = []
        validation_result.warnings = [{"code": "WARNING"}]
        validation_result.metadata = {
            "dataset_description": {
                "Name": "Test Dataset",
                "BIDSVersion": "1.6.0"
            },
            "participants": {"count": 5},
            "tasks": ["task1", "task2"],
            "modalities": ["anat"]
        }
        validation_result.quality_metrics = {"overall_quality_score": 90.0}
        
        loader = BIDSUnifiedLoader()
        result = loader._format_result(validation_result, "/test/dataset")
        
        assert result["dataset_path"] == "/test/dataset"
        assert result["is_valid"] is True
        assert result["dataset_name"] == "Test Dataset"
        assert result["bids_version"] == "1.6.0"
        assert result["n_participants"] == 5
        assert result["tasks"] == ["task1", "task2"]
        assert result["modalities"] == ["anat"]
        assert result["summary"]["status"] == "valid"
        assert result["summary"]["n_errors"] == 0
        assert result["summary"]["n_warnings"] == 1
        assert result["summary"]["quality_score"] == 90.0
    
    def test_get_cache_key(self, tmp_path):
        """Test cache key generation."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        # Create key files
        (dataset_path / "dataset_description.json").write_text('{}')
        (dataset_path / "participants.tsv").write_text('')
        
        loader = BIDSUnifiedLoader()
        key1 = loader._get_cache_key(dataset_path)
        key2 = loader._get_cache_key(dataset_path)
        
        # Same dataset should generate same key
        assert key1 == key2
        assert len(key1) == 32  # MD5 hash length
    
    def test_update_stats(self):
        """Test statistics updating."""
        loader = BIDSUnifiedLoader()
        
        result1 = BIDSValidationResult()
        result1.is_valid = True
        result1.errors = []
        result1.warnings = [{"code": "W1"}]
        
        result2 = BIDSValidationResult()
        result2.is_valid = False
        result2.errors = [{"code": "E1"}, {"code": "E2"}]
        result2.warnings = []
        
        loader._update_stats(result1)
        loader._update_stats(result2)
        
        assert loader.stats["datasets_processed"] == 2
        assert loader.stats["valid_datasets"] == 1
        assert loader.stats["invalid_datasets"] == 1
        assert loader.stats["total_errors"] == 2
        assert loader.stats["total_warnings"] == 1
    
    def test_get_statistics(self):
        """Test statistics retrieval."""
        loader = BIDSUnifiedLoader()
        loader.stats = {
            "datasets_processed": 10,
            "valid_datasets": 7,
            "invalid_datasets": 3,
            "total_errors": 5,
            "total_warnings": 15
        }
        
        stats = loader.get_statistics()
        
        assert stats["datasets_processed"] == 10
        assert stats["valid_rate"] == 0.7
        assert stats["invalid_rate"] == 0.3
        assert stats["avg_errors_per_dataset"] == 0.5
        assert stats["avg_warnings_per_dataset"] == 1.5
    
    def test_clear_cache(self):
        """Test cache clearing."""
        loader = BIDSUnifiedLoader(cache_results=True)
        loader._cache = {"key1": "value1", "key2": "value2"}
        
        loader.clear_cache()
        
        assert len(loader._cache) == 0
    
    @patch('brain_researcher.core.ingestion.loaders.bids_unified.store_validation_result')
    def test_store_result(self, mock_store_func):
        """Test storing validation result in database."""
        loader = BIDSUnifiedLoader(db_path="/test/db.db")
        
        result = BIDSValidationResult()
        result.is_valid = True
        result.timestamp = "2025-08-21T10:00:00"
        result.errors = []
        result.warnings = []
        result.metadata = {"test": "data"}
        result.quality_metrics = {"score": 85.0}
        
        loader._store_result(result, "/test/dataset")
        
        mock_store_func.assert_called_once()
        call_args = mock_store_func.call_args[0]
        assert call_args[0] == "/test/db.db"
        assert call_args[1]["dataset_path"] == "/test/dataset"
        assert call_args[1]["is_valid"] is True
    
    def test_generate_report(self):
        """Test report generation through loader."""
        loader = BIDSUnifiedLoader()
        
        validation_result = BIDSValidationResult()
        validation_result.is_valid = True
        
        with patch.object(loader.validator, 'generate_report', return_value="Test Report") as mock_generate:
            report = loader.generate_report(validation_result, format="markdown")
            
            mock_generate.assert_called_once_with(validation_result, "markdown")
            assert report == "Test Report"