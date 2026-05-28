"""Unit tests for BIDS Dataset Validator."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from brain_researcher.core.ingestion.validation.bids_validator import (
    BIDSValidator,
    BIDSValidationResult,
)


class TestBIDSValidationResult:
    """Test BIDSValidationResult class."""
    
    def test_init(self):
        """Test initialization of validation result."""
        result = BIDSValidationResult()
        
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.metadata == {}
        assert result.quality_metrics == {}
        assert result.files_checked == 0
        assert isinstance(result.timestamp, str)
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = BIDSValidationResult()
        result.is_valid = False
        result.errors = [{"code": "TEST_ERROR", "message": "Test error"}]
        result.warnings = [{"code": "TEST_WARNING", "message": "Test warning"}]
        result.metadata = {"test": "metadata"}
        result.quality_metrics = {"score": 75.0}
        result.files_checked = 100
        
        result_dict = result.to_dict()
        
        assert result_dict["is_valid"] is False
        assert len(result_dict["errors"]) == 1
        assert len(result_dict["warnings"]) == 1
        assert result_dict["metadata"]["test"] == "metadata"
        assert result_dict["quality_metrics"]["score"] == 75.0
        assert result_dict["files_checked"] == 100
        assert "timestamp" in result_dict


class TestBIDSValidator:
    """Test BIDSValidator class."""
    
    def test_init(self):
        """Test validator initialization."""
        validator = BIDSValidator(strict=True, extract_metadata=False)
        
        assert validator.strict is True
        assert validator.extract_metadata is False
        assert validator.report is not None
    
    @patch('subprocess.run')
    def test_run_bids_validator_success(self, mock_run):
        """Test successful bids-validator execution."""
        # Mock successful bids-validator output
        mock_output = {
            "issues": {
                "errors": [],
                "warnings": []
            },
            "summary": {
                "totalFiles": 100,
                "subjects": ["01", "02"],
                "tasks": ["rest", "task"]
            }
        }
        
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps(mock_output),
            stderr=""
        )
        
        validator = BIDSValidator()
        result = validator._run_bids_validator(Path("/test/dataset"))
        
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0
        assert len(result["warnings"]) == 0
    
    @patch('subprocess.run')
    def test_run_bids_validator_with_errors(self, mock_run):
        """Test bids-validator with errors."""
        mock_output = {
            "issues": {
                "errors": [
                    {
                        "key": "JSON_SCHEMA_VALIDATION_ERROR",
                        "reason": "Invalid JSON file",
                        "files": [
                            {
                                "file": {"relativePath": "/dataset_description.json"},
                                "reason": "Schema validation failed"
                            }
                        ]
                    }
                ],
                "warnings": [
                    {
                        "key": "README_FILE_MISSING",
                        "reason": "README file is missing",
                        "files": []
                    }
                ]
            }
        }
        
        mock_run.return_value = Mock(
            returncode=1,
            stdout=json.dumps(mock_output),
            stderr=""
        )
        
        validator = BIDSValidator()
        result = validator._run_bids_validator(Path("/test/dataset"))
        
        assert result["is_valid"] is False
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "JSON_SCHEMA_VALIDATION_ERROR"
        assert len(result["warnings"]) == 1
        assert result["warnings"][0]["code"] == "README_FILE_MISSING"
    
    @patch('subprocess.run')
    def test_run_bids_validator_timeout(self, mock_run):
        """Test bids-validator timeout handling."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("bids-validator", 300)
        
        validator = BIDSValidator()
        result = validator._run_bids_validator(Path("/test/dataset"))
        
        assert result["is_valid"] is False
        assert len(result["errors"]) == 1
        assert "timeout" in result["errors"][0]["message"].lower()
    
    @patch('subprocess.run')
    def test_run_bids_validator_not_found(self, mock_run):
        """Test handling when bids-validator is not installed."""
        mock_run.side_effect = FileNotFoundError("bids-validator not found")
        
        validator = BIDSValidator()
        result = validator._run_bids_validator(Path("/test/dataset"))
        
        assert result["is_valid"] is False
        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]["message"]
    
    def test_extract_metadata(self, tmp_path):
        """Test metadata extraction from BIDS dataset."""
        # Create mock BIDS structure
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        # Create dataset_description.json
        desc_file = dataset_path / "dataset_description.json"
        desc_content = {
            "Name": "Test Dataset",
            "BIDSVersion": "1.6.0",
            "Authors": ["Test Author"]
        }
        desc_file.write_text(json.dumps(desc_content))
        
        # Create participants.tsv
        participants_file = dataset_path / "participants.tsv"
        participants_file.write_text("participant_id\tage\tsex\nsub-01\t25\tM\nsub-02\t30\tF\n")
        
        # Create subject directories
        (dataset_path / "sub-01" / "anat").mkdir(parents=True)
        (dataset_path / "sub-01" / "func").mkdir(parents=True)
        (dataset_path / "sub-02" / "anat").mkdir(parents=True)
        
        # Create task file
        task_file = dataset_path / "sub-01" / "func" / "sub-01_task-rest_bold.json"
        task_file.write_text('{"TaskName": "rest"}')
        
        validator = BIDSValidator()
        metadata = validator._extract_metadata(dataset_path)
        
        assert metadata["dataset_description"]["Name"] == "Test Dataset"
        assert metadata["dataset_description"]["BIDSVersion"] == "1.6.0"
        assert metadata["participants"]["count"] == 2
        assert "age" in metadata["participants"]["columns"]
        assert "rest" in metadata["tasks"]
        assert set(metadata["modalities"]) == {"anat", "func"}
    
    def test_extract_demographics(self):
        """Test demographic extraction from participants dataframe."""
        import pandas as pd
        
        df = pd.DataFrame({
            "participant_id": ["sub-01", "sub-02", "sub-03"],
            "age": [25, 30, 35],
            "sex": ["M", "F", "M"],
            "handedness": ["R", "R", "L"]
        })
        
        validator = BIDSValidator()
        demographics = validator._extract_demographics(df)
        
        assert demographics["age"]["mean"] == 30.0
        assert demographics["age"]["min"] == 25.0
        assert demographics["age"]["max"] == 35.0
        assert demographics["sex"]["M"] == 2
        assert demographics["sex"]["F"] == 1
        assert demographics["handedness"]["R"] == 2
        assert demographics["handedness"]["L"] == 1
    
    def test_calculate_quality_metrics(self, tmp_path):
        """Test quality metrics calculation."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        # Create required files
        (dataset_path / "dataset_description.json").write_text("{}")
        (dataset_path / "participants.tsv").write_text("")
        
        result = BIDSValidationResult()
        result.errors = [{"code": "ERROR1"}, {"code": "ERROR2"}]
        result.warnings = [{"code": "WARNING1"}]
        result.files_checked = 100
        
        validator = BIDSValidator(strict=False)
        metrics = validator._calculate_quality_metrics(dataset_path, result)
        
        assert "completeness_score" in metrics
        assert "required_files_score" in metrics
        assert "overall_quality_score" in metrics
        assert metrics["required_files"]["dataset_description.json"] is True
        assert metrics["required_files"]["README"] is False
        assert metrics["required_files_score"] > 0
    
    def test_generate_report_json(self):
        """Test JSON report generation."""
        result = BIDSValidationResult()
        result.is_valid = True
        result.metadata = {"test": "data"}
        result.quality_metrics = {"score": 85.0}
        
        validator = BIDSValidator()
        report = validator.generate_report(result, format="json")
        
        parsed = json.loads(report)
        assert parsed["is_valid"] is True
        assert parsed["metadata"]["test"] == "data"
        assert parsed["quality_metrics"]["score"] == 85.0
    
    def test_generate_report_markdown(self):
        """Test Markdown report generation."""
        result = BIDSValidationResult()
        result.is_valid = False
        result.errors = [{"code": "ERROR", "message": "Test error"}]
        result.metadata = {
            "dataset_description": {"Name": "Test", "BIDSVersion": "1.6.0"},
            "participants": {"count": 10},
            "tasks": ["rest"],
            "modalities": ["anat", "func"]
        }
        result.quality_metrics = {"overall_quality_score": 75.0}
        
        validator = BIDSValidator()
        report = validator.generate_report(result, format="markdown")
        
        assert "# BIDS Validation Report" in report
        assert "❌ Invalid" in report
        assert "Test" in report
        assert "1.6.0" in report
        assert "75.0" in str(report)
    
    def test_generate_report_html(self):
        """Test HTML report generation."""
        result = BIDSValidationResult()
        result.is_valid = True
        result.quality_metrics = {"overall_quality_score": 90.0}
        
        validator = BIDSValidator()
        report = validator.generate_report(result, format="html")
        
        assert "<!DOCTYPE html>" in report
        assert "<title>BIDS Validation Report</title>" in report
        assert "✅ Valid" in report
        assert "90.0" in str(report)
    
    def test_generate_report_invalid_format(self):
        """Test invalid report format handling."""
        result = BIDSValidationResult()
        validator = BIDSValidator()
        
        with pytest.raises(ValueError, match="Unsupported format"):
            validator.generate_report(result, format="invalid")
    
    @patch.object(BIDSValidator, '_run_bids_validator')
    @patch.object(BIDSValidator, '_extract_metadata')
    @patch.object(BIDSValidator, '_calculate_quality_metrics')
    @patch.object(BIDSValidator, '_count_files')
    def test_validate_dataset(self, mock_count, mock_metrics, mock_metadata, mock_run, tmp_path):
        """Test complete dataset validation."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        mock_run.return_value = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        mock_metadata.return_value = {"test": "metadata"}
        mock_metrics.return_value = {"score": 100.0}
        mock_count.return_value = 50
        
        validator = BIDSValidator()
        result = validator.validate_dataset(str(dataset_path))
        
        assert result.is_valid is True
        assert result.metadata["test"] == "metadata"
        assert result.quality_metrics["score"] == 100.0
        assert result.files_checked == 50
    
    def test_validate_batch(self, tmp_path):
        """Test batch validation of multiple datasets."""
        # Create two test datasets
        dataset1 = tmp_path / "dataset1"
        dataset2 = tmp_path / "dataset2"
        dataset1.mkdir()
        dataset2.mkdir()
        
        # Add minimal required files
        (dataset1 / "dataset_description.json").write_text('{"Name": "Dataset 1", "BIDSVersion": "1.6.0"}')
        (dataset2 / "dataset_description.json").write_text('{"Name": "Dataset 2", "BIDSVersion": "1.6.0"}')
        
        validator = BIDSValidator()
        
        with patch.object(validator, 'validate_dataset') as mock_validate:
            mock_result1 = BIDSValidationResult()
            mock_result1.is_valid = True
            mock_result2 = BIDSValidationResult()
            mock_result2.is_valid = False
            
            mock_validate.side_effect = [mock_result1, mock_result2]
            
            results = validator.validate_batch([str(dataset1), str(dataset2)])
            
            assert len(results) == 2
            assert results[str(dataset1)].is_valid is True
            assert results[str(dataset2)].is_valid is False