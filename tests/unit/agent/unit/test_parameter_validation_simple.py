"""
Simple unit tests for parameter validation system.
Tests core functionality without complex mocking.
"""

import json
import pytest
from pathlib import Path
from brain_researcher.services.agent.parameter_validation import (
    ParameterValidator,
    ParameterDatabase,
    ParameterType,
    ParameterSchema,
)


class TestParameterValidator:
    """Test the main ParameterValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create a validator instance."""
        return ParameterValidator()
    
    def test_validate_integer_type(self, validator):
        """Test integer parameter validation."""
        # Valid integer
        result = validator.validate_parameter(
            "iterations", 
            100,
            {"type": "integer", "range": [1, 1000]}
        )
        assert result["is_valid"] == True
        assert result["value"] == 100
        
        # Out of range
        result = validator.validate_parameter(
            "iterations",
            -5,
            {"type": "integer", "range": [1, 1000]}
        )
        assert result["is_valid"] == False
        assert "out of range" in result["message"].lower()
    
    def test_validate_float_type(self, validator):
        """Test float parameter validation."""
        # Valid float
        result = validator.validate_parameter(
            "threshold",
            3.1,
            {"type": "float", "range": [0, 10]}
        )
        assert result["is_valid"] == True
        assert result["value"] == 3.1
        
        # Invalid type
        result = validator.validate_parameter(
            "threshold",
            "not_a_float",
            {"type": "float", "range": [0, 10]}
        )
        assert result["is_valid"] == False
    
    def test_validate_string_with_options(self, validator):
        """Test string parameter with allowed options."""
        # Valid option
        result = validator.validate_parameter(
            "cost",
            "corratio",
            {"type": "string", "options": ["corratio", "normmi", "leastsq"]}
        )
        assert result["is_valid"] == True
        assert result["value"] == "corratio"
        
        # Invalid option
        result = validator.validate_parameter(
            "cost",
            "invalid",
            {"type": "string", "options": ["corratio", "normmi"]}
        )
        assert result["is_valid"] == False
        assert "not in allowed options" in result["message"].lower()
    
    def test_validate_boolean_type(self, validator):
        """Test boolean parameter validation."""
        result = validator.validate_parameter(
            "parallel",
            True,
            {"type": "boolean"}
        )
        assert result["is_valid"] == True
        assert result["value"] is True
        
        # Convert string to boolean
        result = validator.validate_parameter(
            "parallel",
            "true",
            {"type": "boolean"}
        )
        assert result["is_valid"] == True
        assert result["value"] is True
    
    def test_validate_array_type(self, validator):
        """Test array parameter validation."""
        # Valid array
        result = validator.validate_parameter(
            "fwhm",
            [8, 8, 8],
            {"type": "array", "element_type": "float", "length": 3}
        )
        assert result["is_valid"] == True
        assert result["value"] == [8, 8, 8]
        
        # Wrong length
        result = validator.validate_parameter(
            "fwhm",
            [8, 8],
            {"type": "array", "element_type": "float", "length": 3}
        )
        assert result["is_valid"] == False
    
    def test_validate_tool_parameters(self, validator):
        """Test validation of multiple tool parameters."""
        params = {
            "smooth": 6.0,
            "thresh": 3.1
        }
        
        results = validator.validate_tool_parameters("fsl.feat", params)
        
        # Should return a dictionary of results
        assert isinstance(results, dict)
        assert len(results) > 0
    
    def test_neuroimaging_specific_validation(self, validator):
        """Test neuroimaging-specific validations."""
        # Smoothing FWHM should be positive
        result = validator.validate_parameter(
            "smoothing_fwhm",
            -5,
            {"type": "float", "range": [0, 20]}
        )
        assert result["is_valid"] == False
        
        # TR should be positive
        result = validator.validate_parameter(
            "tr",
            2.0,
            {"type": "float", "range": [0.5, 10]}
        )
        assert result["is_valid"] == True
        assert result["value"] == 2.0
    
    def test_validation_with_context(self, validator):
        """Test context-aware validation."""
        context = {"task": "group_analysis"}
        
        result = validator.validate_parameter(
            "smoothing_fwhm",
            4.0,
            {"type": "float", "range": [0, 20]},
            context=context
        )
        
        assert result["is_valid"] == True
        # Group analysis might suggest larger smoothing
        if "suggested_value" in result:
            assert result["suggested_value"] >= 4.0


class TestParameterDatabase:
    """Test parameter database functionality."""
    
    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary database."""
        db_file = tmp_path / "test_db.json"
        return ParameterDatabase(str(db_file))
    
    def test_add_and_get_parameter(self, db):
        """Test adding and retrieving parameters."""
        db.add_parameter("test_tool", "param1", {
            "type": "float",
            "range": [0, 10],
            "default": 5.0
        })
        
        param = db.get_parameter("test_tool", "param1")
        assert param is not None
        assert param["type"] == "float"
        assert param["range"] == [0, 10]
        assert param["default"] == 5.0
    
    def test_get_tool_parameters(self, db):
        """Test getting all parameters for a tool."""
        db.add_parameter("fsl", "smooth", {"type": "float"})
        db.add_parameter("fsl", "thresh", {"type": "float"})
        db.add_parameter("spm", "fwhm", {"type": "array"})
        
        fsl_params = db.get_tool_parameters("fsl")
        assert len(fsl_params) == 2
        assert "smooth" in fsl_params
        assert "thresh" in fsl_params
        assert "fwhm" not in fsl_params
    
    def test_update_parameter(self, db):
        """Test updating existing parameters."""
        # Add initial
        db.add_parameter("tool", "param", {
            "type": "float",
            "range": [0, 10]
        })
        
        # Update
        db.update_parameter("tool", "param", {
            "range": [0, 20],
            "default": 5.0
        })
        
        param = db.get_parameter("tool", "param")
        assert param["type"] == "float"  # Original preserved
        assert param["range"] == [0, 20]  # Updated
        assert param["default"] == 5.0  # New field
    
    def test_search_parameters(self, db):
        """Test searching parameters."""
        db.add_parameter("fsl", "smoothing_fwhm", {
            "type": "float",
            "description": "Spatial smoothing kernel"
        })
        db.add_parameter("spm", "smooth", {
            "type": "array",
            "description": "Gaussian smoothing"
        })
        
        results = db.search_parameters("smooth")
        assert len(results) >= 2


class TestIntegration:
    """Integration tests."""
    
    @pytest.fixture
    def validator(self):
        """Create validator."""
        return ParameterValidator()
    
    def test_fsl_bet_parameters(self, validator):
        """Test FSL BET tool parameters."""
        params = {
            "f": 0.5,  # Fractional intensity threshold
            "g": 0,    # Vertical gradient
        }
        
        results = validator.validate_tool_parameters("fsl.bet", params)
        
        # Check that we get results
        assert isinstance(results, dict)
        
        # If schema found, should validate correctly
        if "f" in results:
            assert results["f"]["is_valid"] == True
            assert results["f"]["value"] == 0.5
    
    def test_nilearn_parameters(self, validator):
        """Test nilearn parameters."""
        params = {
            "smoothing_fwhm": 6.0,
            "standardize": True,
            "detrend": True
        }
        
        results = validator.validate_tool_parameters("nilearn", params)
        
        assert isinstance(results, dict)
        
        # Check smoothing validation
        if "smoothing_fwhm" in results:
            assert results["smoothing_fwhm"]["is_valid"] == True
    
    def test_cross_tool_smoothing(self, validator):
        """Test smoothing parameter across different tools."""
        # FSL uses 'smooth'
        fsl_result = validator.validate_parameter(
            "smooth", 6.0,
            {"type": "float", "range": [0, 20]},
            tool="fsl"
        )
        
        # SPM uses 'fwhm' as array
        spm_result = validator.validate_parameter(
            "fwhm", [6, 6, 6],
            {"type": "array", "element_type": "float", "length": 3},
            tool="spm"
        )
        
        # Nilearn uses 'smoothing_fwhm'
        nilearn_result = validator.validate_parameter(
            "smoothing_fwhm", 6.0,
            {"type": "float", "range": [0, 20]},
            tool="nilearn"
        )
        
        assert fsl_result["is_valid"] == True
        assert spm_result["is_valid"] == True
        assert nilearn_result["is_valid"] == True
    
    @pytest.mark.parametrize("param,value,schema,expected", [
        ("iterations", 100, {"type": "integer", "range": [1, 1000]}, True),
        ("iterations", -5, {"type": "integer", "range": [1, 1000]}, False),
        ("threshold", 3.1, {"type": "float", "range": [0, 10]}, True),
        ("threshold", 15, {"type": "float", "range": [0, 10]}, False),
        ("cost", "corratio", {"type": "string", "options": ["corratio", "normmi"]}, True),
        ("cost", "invalid", {"type": "string", "options": ["corratio", "normmi"]}, False),
        ("parallel", True, {"type": "boolean"}, True),
        ("fwhm", [8, 8, 8], {"type": "array", "element_type": "float", "length": 3}, True),
        ("fwhm", [8, 8], {"type": "array", "element_type": "float", "length": 3}, False),
    ])
    def test_parametric_validation(self, validator, param, value, schema, expected):
        """Parametric tests for various parameter types."""
        result = validator.validate_parameter(param, value, schema)
        assert result["is_valid"] == expected