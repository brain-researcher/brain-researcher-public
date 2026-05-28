"""Integration tests for BIDS validation with real datasets."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import pytest

from brain_researcher.core.ingestion.loaders.bids_unified import BIDSUnifiedLoader
from brain_researcher.core.ingestion.validation.bids_validator import BIDSValidator


# Real dataset paths for testing
DATASET_DS000114 = "/app/data/openneuro/ds000114"
DATASET_DS000117 = "/app/data/openneuro/ds000117"

# Guard heavy real-data tests unless explicitly enabled
if os.environ.get("RUN_REAL_BIDS") != "1":
    pytest.skip(
        "Set RUN_REAL_BIDS=1 to run real BIDS validation tests",
        allow_module_level=True,
    )


@pytest.fixture
def real_datasets():
    """Fixture providing paths to real BIDS datasets."""
    datasets = []
    
    # Only include datasets that actually exist
    if Path(DATASET_DS000114).exists():
        datasets.append(DATASET_DS000114)
    if Path(DATASET_DS000117).exists():
        datasets.append(DATASET_DS000117)
    
    if not datasets:
        pytest.skip("No real BIDS datasets available for testing")
    
    return datasets


class TestBIDSValidatorIntegration:
    """Integration tests for BIDS validator with real datasets."""
    
    def test_validate_real_dataset_ds000114(self):
        """Test validation of real dataset ds000114."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        validator = BIDSValidator(strict=False, extract_metadata=True)
        result = validator.validate_dataset(DATASET_DS000114)
        
        # Check basic validation
        assert result is not None
        assert isinstance(result.is_valid, bool)
        
        # Check metadata extraction
        assert result.metadata is not None
        if "dataset_description" in result.metadata:
            desc = result.metadata["dataset_description"]
            assert "Name" in desc
            assert "test-retest" in desc["Name"].lower()
            assert "BIDSVersion" in desc
        
        # Check participants
        if "participants" in result.metadata:
            assert result.metadata["participants"]["count"] == 10
        
        # Check tasks
        if "tasks" in result.metadata:
            tasks = result.metadata["tasks"]
            assert "covertverbgeneration" in tasks
            assert "fingerfootlips" in tasks
        
        # Check modalities
        if "modalities" in result.metadata:
            modalities = result.metadata["modalities"]
            assert "anat" in modalities
            assert "func" in modalities
        
        # Check quality metrics
        assert result.quality_metrics is not None
        assert "overall_quality_score" in result.quality_metrics
        assert result.quality_metrics["overall_quality_score"] >= 0
        assert result.quality_metrics["overall_quality_score"] <= 100
    
    def test_validate_real_dataset_ds000117(self):
        """Test validation of real dataset ds000117."""
        if not Path(DATASET_DS000117).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000117}")
        
        validator = BIDSValidator(strict=False, extract_metadata=True)
        result = validator.validate_dataset(DATASET_DS000117)
        
        # Check basic validation
        assert result is not None
        assert isinstance(result.is_valid, bool)
        
        # Check metadata
        if "dataset_description" in result.metadata:
            desc = result.metadata["dataset_description"]
            assert "Name" in desc
            assert "face" in desc["Name"].lower()
        
        # Check participants
        if "participants" in result.metadata:
            assert result.metadata["participants"]["count"] == 17
        
        # Check modalities
        if "modalities" in result.metadata:
            modalities = result.metadata["modalities"]
            # ds000117 has MEG data
            assert any(m in modalities for m in ["anat", "func", "meg"])
    
    def test_bids_validator_command_available(self):
        """Test that bids-validator command is available."""
        try:
            result = subprocess.run(
                ["bids-validator", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            assert result.returncode == 0 or "command not found" not in result.stderr
        except FileNotFoundError:
            pytest.skip("bids-validator not installed")
        except subprocess.TimeoutExpired:
            pytest.fail("bids-validator command timed out")
    
    def test_run_bids_validator_directly(self):
        """Test running bids-validator directly on a dataset."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        try:
            result = subprocess.run(
                ["bids-validator", "--json", DATASET_DS000114],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Should get JSON output
            assert result.stdout
            output = json.loads(result.stdout)
            assert "issues" in output or "summary" in output
            
        except FileNotFoundError:
            pytest.skip("bids-validator not installed")
        except subprocess.TimeoutExpired:
            pytest.fail("bids-validator timed out")


class TestBIDSUnifiedLoaderIntegration:
    """Integration tests for BIDS unified loader with real datasets."""
    
    def test_load_single_dataset(self):
        """Test loading a single real dataset."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        loader = BIDSUnifiedLoader(strict_validation=False, cache_results=True)
        result = loader.load_dataset(DATASET_DS000114)
        
        # Check result structure
        assert "is_valid" in result
        assert "dataset_path" in result
        assert "summary" in result
        
        # Check summary
        summary = result["summary"]
        assert "status" in summary
        assert "n_errors" in summary
        assert "n_warnings" in summary
        assert "quality_score" in summary
        
        # Check extracted metadata
        assert "dataset_name" in result
        assert "bids_version" in result
        assert "n_participants" in result
        
        # Verify known properties of ds000114
        assert result["n_participants"] == 10
        if result.get("tasks"):
            assert len(result["tasks"]) == 5  # ds000114 has 5 tasks
    
    def test_load_batch_datasets(self, real_datasets):
        """Test batch loading of multiple real datasets."""
        loader = BIDSUnifiedLoader(strict_validation=False, cache_results=True)
        results = loader.load_batch(real_datasets)
        
        # Check all datasets were processed
        assert len(results) == len(real_datasets)
        
        # Check each result
        for dataset_path in real_datasets:
            assert dataset_path in results
            result = results[dataset_path]
            
            assert "is_valid" in result or "error" in result
            if "error" not in result:
                assert "summary" in result
                assert "dataset_name" in result
    
    def test_caching_functionality(self):
        """Test that caching works correctly."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        loader = BIDSUnifiedLoader(strict_validation=False, cache_results=True)
        
        # First load
        result1 = loader.load_dataset(DATASET_DS000114)
        
        # Second load should use cache
        with patch.object(loader.validator, 'validate_dataset') as mock_validate:
            result2 = loader.load_dataset(DATASET_DS000114)
            # validate_dataset should not be called due to cache
            mock_validate.assert_not_called()
        
        # Results should be identical
        assert result1["is_valid"] == result2["is_valid"]
        assert result1.get("dataset_name") == result2.get("dataset_name")
    
    def test_incremental_changes_detection(self):
        """Test incremental change detection."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        loader = BIDSUnifiedLoader()
        
        # Check changes (first time, all files are new)
        changes = loader.check_incremental_changes(DATASET_DS000114)
        
        assert changes["has_changes"] is True
        assert len(changes["new_files"]) > 0
        assert len(changes["modified_files"]) == 0
        assert len(changes["deleted_files"]) == 0
    
    def test_get_dataset_info(self):
        """Test getting dataset info without full validation."""
        if not Path(DATASET_DS000117).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000117}")
        
        loader = BIDSUnifiedLoader()
        info = loader.get_dataset_info(DATASET_DS000117)
        
        assert "description" in info
        assert "n_subjects" in info
        assert "modalities" in info
        assert "tasks" in info
        
        # Check known properties of ds000117
        assert info["n_subjects"] == 17
        if "description" in info and info["description"]:
            assert "face" in info["description"].get("Name", "").lower()
    
    def test_report_generation_formats(self):
        """Test report generation in different formats."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        validator = BIDSValidator(strict=False, extract_metadata=True)
        loader = BIDSUnifiedLoader()
        
        # Validate dataset
        validation_result = validator.validate_dataset(DATASET_DS000114)
        
        # Generate reports in different formats
        json_report = loader.generate_report(validation_result, format="json")
        md_report = loader.generate_report(validation_result, format="markdown")
        html_report = loader.generate_report(validation_result, format="html")
        
        # Check JSON report
        assert json_report
        parsed = json.loads(json_report)
        assert "is_valid" in parsed
        assert "metadata" in parsed
        assert "quality_metrics" in parsed
        
        # Check Markdown report
        assert md_report
        assert "# BIDS Validation Report" in md_report
        assert "Dataset Metadata" in md_report
        assert "Quality Metrics" in md_report
        
        # Check HTML report
        assert html_report
        assert "<!DOCTYPE html>" in html_report
        assert "<title>BIDS Validation Report</title>" in html_report
    
    def test_statistics_tracking(self, real_datasets):
        """Test that statistics are properly tracked."""
        loader = BIDSUnifiedLoader(strict_validation=False)
        
        # Process datasets
        for dataset_path in real_datasets:
            loader.load_dataset(dataset_path)
        
        # Get statistics
        stats = loader.get_statistics()
        
        assert stats["datasets_processed"] == len(real_datasets)
        assert "valid_datasets" in stats
        assert "invalid_datasets" in stats
        assert stats["valid_datasets"] + stats["invalid_datasets"] == len(real_datasets)
        
        if stats["datasets_processed"] > 0:
            assert "valid_rate" in stats
            assert "invalid_rate" in stats
            assert "avg_errors_per_dataset" in stats
            assert "avg_warnings_per_dataset" in stats
    
    def test_validate_only_mode(self):
        """Test validation without metadata extraction."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        loader = BIDSUnifiedLoader()
        result = loader.validate_only(DATASET_DS000114)
        
        assert result is not None
        assert hasattr(result, 'is_valid')
        assert hasattr(result, 'errors')
        assert hasattr(result, 'warnings')
    
    def test_clear_cache(self):
        """Test cache clearing functionality."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        loader = BIDSUnifiedLoader(cache_results=True)
        
        # Load dataset to populate cache
        loader.load_dataset(DATASET_DS000114)
        assert len(loader._cache) > 0
        
        # Clear cache
        loader.clear_cache()
        assert len(loader._cache) == 0


class TestReportStorage:
    """Test report storage functionality."""
    
    def test_save_reports_to_temp(self):
        """Test saving reports to temporary directory."""
        if not Path(DATASET_DS000114).exists():
            pytest.skip(f"Dataset not found: {DATASET_DS000114}")
        
        validator = BIDSValidator(strict=False, extract_metadata=True)
        result = validator.validate_dataset(DATASET_DS000114)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Save JSON report
            json_report = validator.generate_report(result, format="json")
            json_file = tmppath / "report.json"
            json_file.write_text(json_report)
            assert json_file.exists()
            
            # Verify JSON is valid
            loaded = json.loads(json_file.read_text())
            assert "is_valid" in loaded
            
            # Save Markdown report
            md_report = validator.generate_report(result, format="markdown")
            md_file = tmppath / "report.md"
            md_file.write_text(md_report)
            assert md_file.exists()
            
            # Save HTML report
            html_report = validator.generate_report(result, format="html")
            html_file = tmppath / "report.html"
            html_file.write_text(html_report)
            assert html_file.exists()


# Mark tests that require real datasets
pytestmark = pytest.mark.skipif(
    not (Path(DATASET_DS000114).exists() or Path(DATASET_DS000117).exists()),
    reason="Real BIDS datasets not available"
)
