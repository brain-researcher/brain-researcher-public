"""
Comprehensive tests for Parameter Inference System (AGENT-005).
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.services.agent.parameter_inference import (
    BIDSEntity,
    BIDSParser,
    ImageMetadata,
    InferredParameters,
    ContextAnalyzer,
    ParameterInferenceEngine,
)
from brain_researcher.services.agent.inference_integration import (
    InferenceAwareValidator,
    SmartParameterHandler,
)


class TestBIDSEntity:
    """Test BIDS entity extraction."""
    
    def test_entity_creation(self):
        """Test creating BIDS entity."""
        entity = BIDSEntity(
            subject="01",
            session="pre",
            task="motor",
            run=1,
            suffix="bold",
        )
        
        assert entity.subject == "01"
        assert entity.session == "pre"
        assert entity.task == "motor"
        assert entity.run == 1
        assert entity.suffix == "bold"
    
    def test_entity_to_dict(self):
        """Test converting entity to dictionary."""
        entity = BIDSEntity(subject="01", task="rest")
        entity_dict = entity.to_dict()
        
        assert entity_dict == {"subject": "01", "task": "rest"}
        assert "session" not in entity_dict  # None values excluded


class TestBIDSParser:
    """Test BIDS file parsing."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.parser = BIDSParser()
    
    def test_parse_functional_filename(self):
        """Test parsing functional MRI filename."""
        filename = "sub-01_ses-pre_task-motor_run-1_bold.nii.gz"
        entity = self.parser.parse_filename(filename)
        
        assert entity.subject == "01"
        assert entity.session == "pre"
        assert entity.task == "motor"
        assert entity.run == 1
        assert entity.suffix == "bold"
        assert entity.extension == ".nii.gz"
    
    def test_parse_anatomical_filename(self):
        """Test parsing anatomical MRI filename."""
        filename = "sub-02_ses-post_T1w.nii.gz"
        entity = self.parser.parse_filename(filename)
        
        assert entity.subject == "02"
        assert entity.session == "post"
        assert entity.suffix == "T1w"
        assert entity.task is None
    
    def test_parse_fieldmap_filename(self):
        """Test parsing fieldmap filename."""
        filename = "sub-03_ses-01_acq-dwi_dir-AP_epi.nii.gz"
        entity = self.parser.parse_filename(filename)
        
        assert entity.subject == "03"
        assert entity.session == "01"
        assert entity.acquisition == "dwi"
        assert entity.suffix == "epi"
    
    def test_read_json_sidecar(self):
        """Test reading JSON sidecar file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json_data = {
                "RepetitionTime": 2.0,
                "EchoTime": 0.03,
                "SliceTiming": [0, 0.5, 1.0, 1.5],
                "PhaseEncodingDirection": "j-",
            }
            json.dump(json_data, f)
            json_path = f.name
        
        try:
            data = self.parser.read_json_sidecar(json_path)
            
            assert data["RepetitionTime"] == 2.0
            assert data["EchoTime"] == 0.03
            assert len(data["SliceTiming"]) == 4
            assert data["PhaseEncodingDirection"] == "j-"
        finally:
            Path(json_path).unlink()
    
    @patch("brain_researcher.services.agent.parameter_inference.nib")
    def test_extract_image_metadata(self, mock_nib):
        """Test extracting metadata from NIfTI file."""
        # Mock nibabel image
        mock_img = MagicMock()
        mock_img.shape = (64, 64, 32, 100)
        mock_img.header.get_zooms.return_value = (3.0, 3.0, 4.0, 2.0)
        mock_img.header.get_xyzt_units.return_value = (None, "sec")
        mock_nib.load.return_value = mock_img
        
        metadata = self.parser.extract_image_metadata("test.nii.gz")
        
        assert metadata.shape == (64, 64, 32, 100)
        assert metadata.voxel_size == (3.0, 3.0, 4.0, 2.0)
        assert metadata.n_volumes == 100
        assert metadata.tr == 2.0


class TestInferredParameters:
    """Test InferredParameters container."""
    
    def test_add_parameter(self):
        """Test adding parameters."""
        inferred = InferredParameters()
        inferred.add_parameter("tr", 2.0, confidence=0.9, source="bids")
        
        assert inferred.parameters["tr"] == 2.0
        assert inferred.confidence["tr"] == 0.9
        assert inferred.sources["tr"] == "bids"
    
    def test_merge_parameters(self):
        """Test merging parameter sets."""
        inferred1 = InferredParameters()
        inferred1.add_parameter("tr", 2.0, confidence=0.9)
        
        inferred2 = InferredParameters()
        inferred2.add_parameter("te", 0.03, confidence=0.8)
        inferred2.add_parameter("tr", 2.5, confidence=0.7)  # Different value
        
        # Merge without override
        inferred1.merge(inferred2, override=False)
        assert inferred1.parameters["tr"] == 2.0  # Original kept
        assert inferred1.parameters["te"] == 0.03  # New added
        
        # Merge with override
        inferred1.merge(inferred2, override=True)
        assert inferred1.parameters["tr"] == 2.5  # Overridden


class TestContextAnalyzer:
    """Test context-based parameter inference."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.analyzer = ContextAnalyzer()
    
    def test_analyze_motor_task_query(self):
        """Test analyzing motor task query."""
        query = "Analyze finger tapping motor task from subject 01"
        inferred = self.analyzer.analyze_query(query)
        
        assert "contrast_type" in inferred.parameters
        assert inferred.parameters["contrast_type"] == "task>rest"
        assert "smoothing_kernel" in inferred.parameters
        assert inferred.parameters["smoothing_kernel"] == 6.0
    
    def test_analyze_resting_state_query(self):
        """Test analyzing resting-state query."""
        query = "Perform connectivity analysis on resting-state fMRI"
        inferred = self.analyzer.analyze_query(query)
        
        assert "analysis_type" in inferred.parameters
        assert inferred.parameters["analysis_type"] == "connectivity"
        assert "bandpass_filter" in inferred.parameters
        assert inferred.parameters["bandpass_filter"] == [0.01, 0.1]
    
    def test_analyze_group_analysis_query(self):
        """Test analyzing group analysis query."""
        query = "Run group-level analysis across all subjects"
        inferred = self.analyzer.analyze_query(query)
        
        assert "analysis_level" in inferred.parameters
        assert inferred.parameters["analysis_level"] == "group"
        assert "normalization_space" in inferred.parameters
        assert inferred.parameters["normalization_space"] == "MNI152"
    
    def test_analyze_previous_results(self):
        """Test inferring from previous results."""
        previous_results = [
            {"parameters": {"tr": 2.0, "smoothing": 6.0}},
            {"parameters": {"tr": 2.0, "smoothing": 8.0}},
            {"parameters": {"tr": 2.0, "smoothing": 6.0}},
        ]
        
        inferred = self.analyzer.analyze_previous_results(previous_results)
        
        assert inferred.parameters["tr"] == 2.0  # Unanimous
        assert inferred.confidence["tr"] >= 0.9
        assert inferred.parameters["smoothing"] == 6.0  # Most common
        assert inferred.confidence["smoothing"] > 0.6


class TestParameterInferenceEngine:
    """Test main inference engine."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.engine = ParameterInferenceEngine()
    
    @patch("brain_researcher.services.agent.parameter_inference.Path")
    def test_infer_from_bids_with_sidecar(self, mock_path_class):
        """Test inferring from BIDS file with JSON sidecar."""
        # Mock file existence
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.suffix = ".gz"
        mock_path.with_suffix.return_value = mock_path
        mock_path_class.return_value = mock_path
        
        # Mock sidecar reading
        with patch.object(self.engine.bids_parser, "read_json_sidecar") as mock_read:
            mock_read.return_value = {
                "RepetitionTime": 2.0,
                "EchoTime": 0.03,
                "SliceTiming": [0, 0.5, 1.0],
            }
            
            # Mock image metadata extraction
            with patch.object(self.engine.bids_parser, "extract_image_metadata") as mock_extract:
                mock_metadata = ImageMetadata(
                    shape=(64, 64, 32, 100),
                    voxel_size=(3.0, 3.0, 4.0),
                    n_volumes=100,
                )
                mock_extract.return_value = mock_metadata
                
                inferred = self.engine.infer_from_bids(
                    "sub-01_task-motor_bold.nii.gz",
                    tool_name="fsl",
                )
        
        # Check that we have some parameters inferred
        assert len(inferred.parameters) > 0
        
        # Check sidecar parameters
        assert inferred.parameters["repetition_time"] == 2.0
        assert inferred.parameters["echo_time"] == 0.03
        
        # Check FSL-mapped parameters
        assert inferred.parameters["tr"] == 2.0  # Mapped from repetition_time
        assert inferred.parameters["te"] == 0.03  # Mapped from echo_time
    
    def test_infer_from_context_with_query(self):
        """Test inferring from context and query."""
        query = "Run GLM analysis on motor task with smoothing"
        
        inferred = self.engine.infer_from_context(
            query=query,
            tool_name="glm_analysis",
        )
        
        # From query context
        assert "contrast_type" in inferred.parameters
        assert "smoothing_kernel" in inferred.parameters
        
        # From intelligent defaults
        assert "high_pass_filter" in inferred.parameters
        assert inferred.parameters["high_pass_filter"] == 128
    
    def test_caching(self):
        """Test parameter inference caching."""
        query = "Test query for caching"
        
        # First call
        inferred1 = self.engine.infer_from_context(query=query)
        
        # Modify cache to test it's being used
        cache_key = f"{query}:None:None"
        self.engine.cache[cache_key].parameters["cached"] = True
        
        # Second call should use cache
        inferred2 = self.engine.infer_from_context(query=query)
        
        assert "cached" in inferred2.parameters
        assert inferred2.parameters["cached"] is True
    
    def test_validate_and_complete(self):
        """Test parameter validation and completion."""
        parameters = {
            "repetition_time": 2.0,
            "dimensions": (64, 64, 32, 100),
        }
        required = ["tr", "n_timepoints", "smoothing"]
        
        completed, missing = self.engine.validate_and_complete(
            parameters, required, tool_name="fsl"
        )
        
        # Should map repetition_time to tr
        assert "tr" in completed
        assert completed["tr"] == 2.0
        
        # Should infer n_timepoints from dimensions
        assert "n_timepoints" in completed
        assert completed["n_timepoints"] == 100
        
        # Should identify smoothing as missing
        assert "smoothing" in missing


class TestInferenceIntegration:
    """Test integration with parameter validation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.validator = InferenceAwareValidator(enable_inference=True)
    
    @patch("brain_researcher.services.agent.inference_integration.ParameterValidator")
    def test_validate_with_inference(self, mock_validator_class):
        """Test validation with automatic inference."""
        # Mock validator
        mock_validator = Mock()
        mock_result = Mock()
        mock_result.is_valid = True
        mock_result.errors = {}
        mock_result.suggestions = {"smoothing": 6.0}
        mock_validator.validate_parameters.return_value = mock_result
        mock_validator.get_tool_schema.return_value = {
            "required": ["tr", "smoothing"],
        }
        mock_validator_class.return_value = mock_validator
        
        # Create validator with mocked dependency
        validator = InferenceAwareValidator(enable_inference=True)
        validator.validator = mock_validator
        
        # Test validation with inference
        params, errors, warnings = validator.validate_with_inference(
            tool_name="glm_analysis",
            parameters={"tr": 2.0},
            query="Run GLM on motor task",
            auto_complete=True,
        )
        
        # Should have original parameter
        assert params["tr"] == 2.0
        
        # Should have suggested parameter
        assert params["smoothing"] == 6.0
        
        # Should have warnings about inference
        assert any("smoothing" in w for w in warnings)
    
    def test_suggest_parameters(self):
        """Test parameter suggestions."""
        suggestions = self.validator.suggest_parameters(
            tool_name="glm_analysis",
            query="Analyze visual task with faces",
        )
        
        # Should suggest visual task parameters
        assert any(
            "contrast_type" in s or "smoothing_kernel" in s
            for s in suggestions
        )
    
    def test_explain_inference(self):
        """Test inference explanation."""
        explanation = self.validator.explain_inference(
            tool_name="glm_analysis",
            parameters={"tr": 2.0},
            query="Run group analysis on motor task",
        )
        
        assert "Parameter Inference for glm_analysis" in explanation
        assert "Query: Run group analysis" in explanation
        assert "Inferred Parameters:" in explanation or "No parameters" in explanation


class TestSmartParameterHandler:
    """Test high-level parameter handler."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.handler = SmartParameterHandler()
    
    @patch("brain_researcher.services.agent.inference_integration.InferenceAwareValidator")
    def test_process_parameters_success(self, mock_validator_class):
        """Test successful parameter processing."""
        # Mock validator
        mock_validator = Mock()
        mock_validator.validate_with_inference.return_value = (
            {"tr": 2.0, "smoothing": 6.0},  # validated params
            {},  # no errors
            ["Parameter 'smoothing' inferred"],  # warnings
        )
        mock_validator_class.return_value = mock_validator
        
        # Create handler with mocked validator
        handler = SmartParameterHandler()
        handler.validator = mock_validator
        
        # Process parameters
        result = handler.process_parameters(
            tool_name="glm_analysis",
            user_params={"tr": 2.0},
            context={"query": "Run GLM"},
        )
        
        assert result["tr"] == 2.0
        assert result["smoothing"] == 6.0
        
        # Check history
        assert len(handler.history) == 1
        assert handler.history[0]["tool_name"] == "glm_analysis"
    
    @patch("brain_researcher.services.agent.inference_integration.InferenceAwareValidator")
    def test_process_parameters_with_errors(self, mock_validator_class):
        """Test parameter processing with validation errors."""
        # Mock validator with errors
        mock_validator = Mock()
        mock_validator.validate_with_inference.return_value = (
            {"tr": -1.0},  # invalid param
            {"tr": "TR must be positive"},  # error
            [],  # no warnings
        )
        mock_validator_class.return_value = mock_validator
        
        # Create handler with mocked validator
        handler = SmartParameterHandler()
        handler.validator = mock_validator
        
        # Should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            handler.process_parameters(
                tool_name="glm_analysis",
                user_params={"tr": -1.0},
            )
        
        assert "Parameter validation failed" in str(exc_info.value)
        assert "TR must be positive" in str(exc_info.value)
    
    def test_suggest_missing(self):
        """Test suggesting missing parameters."""
        with patch.object(self.handler.validator, "suggest_parameters") as mock_suggest:
            mock_suggest.return_value = {
                "smoothing": {"value": 6.0, "confidence": 0.8},
                "tr": {"value": 2.0, "confidence": 0.9},
            }
            
            suggestions = self.handler.suggest_missing(
                tool_name="glm_analysis",
                current_params={"tr": 2.0},  # Already have TR
                context={"query": "Run GLM"},
            )
            
            # Should only suggest missing parameters
            assert "smoothing" in suggestions
            assert "tr" not in suggestions  # Already provided


class TestEndToEnd:
    """End-to-end integration tests."""
    
    @pytest.mark.skip(reason="Complex integration test with many dependencies")
    def test_full_inference_pipeline(self):
        """Test complete inference pipeline."""
        # This test requires full integration with ParameterValidator
        # which has complex dependencies. Skipping for now.
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])