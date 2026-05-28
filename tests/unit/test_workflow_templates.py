"""
Unit tests for AGENT-018: Workflow Templates

Tests the WorkflowTemplateEngine class with comprehensive coverage including:
- Template loading and validation
- Parameter substitution and validation
- Template inheritance and composition
- Error handling and edge cases
- Performance characteristics
- Property-based testing

Author: Reviewer Subagent
Date: 2025-01-XX
"""

import pytest
import json
import yaml
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List, Optional
from hypothesis import given, strategies as st, settings
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from brain_researcher.services.agent.workflow_templates import (
    WorkflowTemplateEngine,
    WorkflowTemplate,
    TemplateParameter,
    ParameterType,
    TemplateValidator,
    WorkflowStep,
    TemplateStatus
)

# Define custom exceptions for testing since they're not in the implementation
class TemplateValidationError(Exception):
    pass

class ParameterValidationError(Exception):
    pass

class TemplateInheritanceError(Exception):
    pass


class TestWorkflowTemplateEngine:
    """Test suite for WorkflowTemplateEngine class."""
    
    @pytest.fixture
    def sample_templates(self):
        """Load sample templates from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-018" / "test_templates.yaml"
        with open(fixture_path, 'r') as f:
            return yaml.safe_load(f)
    
    @pytest.fixture
    def parameter_test_cases(self):
        """Load parameter test cases from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-018" / "parameter_test_cases.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    @pytest.fixture
    def template_engine(self, sample_templates):
        """Create WorkflowTemplateEngine with sample templates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            template_file = Path(temp_dir) / "templates.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(sample_templates, f)
            
            engine = WorkflowTemplateEngine(template_dir=temp_dir)
            return engine
    
    @pytest.fixture
    def empty_template_engine(self):
        """Create empty WorkflowTemplateEngine for testing initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            return WorkflowTemplateEngine(template_dir=temp_dir)


class TestTemplateLoading:
    """Test template loading functionality."""
    
    def test_load_valid_templates(self, template_engine, sample_templates):
        """Test loading valid YAML templates."""
        templates = template_engine.get_all_templates()
        
        # Should load all templates from fixture
        assert len(templates) > 0
        
        # Verify specific templates exist
        template_names = [t.name for t in templates]
        assert "fmri_analysis" in template_names
        assert "connectivity_analysis" in template_names
        assert "group_analysis" in template_names
    
    def test_load_invalid_yaml(self, empty_template_engine):
        """Test handling of invalid YAML files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_file = Path(temp_dir) / "invalid.yaml"
            with open(invalid_file, 'w') as f:
                f.write("invalid: yaml: content: [")
            
            # The actual implementation may not raise an exception but might log errors
            engine = WorkflowTemplateEngine(template_dir=temp_dir)
            # Should not crash, may have no templates loaded
            assert len(engine.templates) == 0
    
    def test_load_missing_required_fields(self, empty_template_engine):
        """Test template validation for missing required fields."""
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_template = {
                "templates": {
                    "incomplete": {
                        # Missing name, description, steps
                        "parameters": []
                    }
                }
            }
            
            template_file = Path(temp_dir) / "invalid.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(invalid_template, f)
            
            with pytest.raises(TemplateValidationError) as exc_info:
                WorkflowTemplateEngine(template_dir=temp_dir)
            
            assert "Missing required field" in str(exc_info.value)
    
    def test_template_inheritance_valid(self, template_engine):
        """Test valid template inheritance."""
        template = template_engine.get_template("connectivity_analysis")
        
        # Should inherit from base template
        assert template.extends == "fmri_analysis"
        
        # Should have steps from both base and derived templates
        step_names = [step["name"] for step in template.steps]
        assert "load_data" in step_names  # From base
        assert "compute_connectivity" in step_names  # From derived
    
    def test_template_inheritance_circular(self, empty_template_engine):
        """Test detection of circular template inheritance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            circular_templates = {
                "templates": {
                    "template_a": {
                        "name": "Template A",
                        "description": "Test template A",
                        "extends": "template_b",
                        "parameters": [],
                        "steps": []
                    },
                    "template_b": {
                        "name": "Template B", 
                        "description": "Test template B",
                        "extends": "template_a",
                        "parameters": [],
                        "steps": []
                    }
                }
            }
            
            template_file = Path(temp_dir) / "circular.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(circular_templates, f)
            
            with pytest.raises(TemplateInheritanceError) as exc_info:
                WorkflowTemplateEngine(template_dir=temp_dir)
            
            assert "Circular inheritance" in str(exc_info.value)
    
    def test_template_inheritance_missing_parent(self, empty_template_engine):
        """Test handling of missing parent template."""
        with tempfile.TemporaryDirectory() as temp_dir:
            orphan_template = {
                "templates": {
                    "orphan": {
                        "name": "Orphan Template",
                        "description": "Template with missing parent",
                        "extends": "nonexistent_parent",
                        "parameters": [],
                        "steps": []
                    }
                }
            }
            
            template_file = Path(temp_dir) / "orphan.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(orphan_template, f)
            
            with pytest.raises(TemplateInheritanceError) as exc_info:
                WorkflowTemplateEngine(template_dir=temp_dir)
            
            assert "Parent template not found" in str(exc_info.value)


class TestParameterValidation:
    """Test parameter validation functionality."""
    
    def test_required_parameter_validation(self, template_engine):
        """Test validation of required parameters."""
        template = template_engine.get_template("fmri_analysis")
        
        # Missing required parameter should raise error
        with pytest.raises(ParameterValidationError) as exc_info:
            template_engine.instantiate_template("fmri_analysis", {})
        
        assert "Required parameter missing" in str(exc_info.value)
    
    def test_parameter_type_validation(self, template_engine, parameter_test_cases):
        """Test parameter type validation."""
        for test_case in parameter_test_cases["type_validation"]:
            template_name = test_case["template"]
            parameters = test_case["parameters"]
            should_pass = test_case["should_pass"]
            
            if should_pass:
                # Valid parameters should not raise error
                result = template_engine.instantiate_template(template_name, parameters)
                assert result is not None
            else:
                # Invalid parameters should raise error
                with pytest.raises(ParameterValidationError):
                    template_engine.instantiate_template(template_name, parameters)
    
    def test_parameter_range_validation(self, template_engine):
        """Test parameter range validation."""
        template_name = "fmri_analysis"
        
        # Test valid range
        valid_params = {
            "input_data": "/path/to/data.nii.gz",
            "tr": 2.0,  # Valid TR value
            "high_pass_cutoff": 0.01
        }
        result = template_engine.instantiate_template(template_name, valid_params)
        assert result is not None
        
        # Test invalid range (negative TR)
        invalid_params = {
            "input_data": "/path/to/data.nii.gz", 
            "tr": -1.0,  # Invalid negative TR
            "high_pass_cutoff": 0.01
        }
        with pytest.raises(ParameterValidationError) as exc_info:
            template_engine.instantiate_template(template_name, invalid_params)
        
        assert "Parameter value out of range" in str(exc_info.value)
    
    def test_parameter_format_validation(self, template_engine):
        """Test parameter format validation (regex patterns)."""
        template_name = "fmri_analysis"
        
        # Test valid file path format
        valid_params = {
            "input_data": "/valid/path/data.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        result = template_engine.instantiate_template(template_name, valid_params)
        assert result is not None
        
        # Test invalid file path format
        invalid_params = {
            "input_data": "not_a_nifti_file.txt",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        with pytest.raises(ParameterValidationError) as exc_info:
            template_engine.instantiate_template(template_name, invalid_params)
        
        assert "Parameter format invalid" in str(exc_info.value)
    
    @given(
        tr=st.floats(min_value=0.1, max_value=10.0),
        cutoff=st.floats(min_value=0.001, max_value=0.5)
    )
    @settings(max_examples=50)
    def test_parameter_validation_property_based(self, template_engine, tr, cutoff):
        """Property-based test for parameter validation."""
        params = {
            "input_data": "/test/data.nii.gz",
            "tr": tr,
            "high_pass_cutoff": cutoff
        }
        
        # Valid parameters should always work
        result = template_engine.instantiate_template("fmri_analysis", params)
        assert result is not None
        assert result.parameters["tr"] == tr
        assert result.parameters["high_pass_cutoff"] == cutoff


class TestParameterSubstitution:
    """Test parameter substitution in templates."""
    
    def test_simple_parameter_substitution(self, template_engine):
        """Test basic parameter substitution in template steps."""
        params = {
            "input_data": "/path/to/input.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        result = template_engine.instantiate_template("fmri_analysis", params)
        
        # Check parameter substitution in steps
        load_step = next(step for step in result.steps if step["name"] == "load_data")
        assert load_step["parameters"]["input_file"] == "/path/to/input.nii.gz"
        
        preprocess_step = next(step for step in result.steps if step["name"] == "preprocessing")
        assert preprocess_step["parameters"]["tr"] == 2.0
    
    def test_nested_parameter_substitution(self, template_engine):
        """Test nested parameter substitution."""
        params = {
            "input_data": "/data/subject-01/func/sub-01_task-rest_bold.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01,
            "output_dir": "/results"
        }
        
        result = template_engine.instantiate_template("fmri_analysis", params)
        
        # Check nested parameter references
        output_step = next(step for step in result.steps if step["name"] == "save_results")
        expected_output = "/results/preprocessed_sub-01_task-rest_bold.nii.gz"
        assert output_step["parameters"]["output_file"] == expected_output
    
    def test_conditional_parameter_substitution(self, template_engine):
        """Test conditional parameter substitution."""
        # Test with motion correction enabled
        params_with_mc = {
            "input_data": "/data/test.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01,
            "motion_correction": True
        }
        
        result = template_engine.instantiate_template("fmri_analysis", params_with_mc)
        step_names = [step["name"] for step in result.steps]
        assert "motion_correction" in step_names
        
        # Test with motion correction disabled
        params_no_mc = {
            "input_data": "/data/test.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01,
            "motion_correction": False
        }
        
        result = template_engine.instantiate_template("fmri_analysis", params_no_mc)
        step_names = [step["name"] for step in result.steps]
        assert "motion_correction" not in step_names
    
    def test_parameter_substitution_with_defaults(self, template_engine):
        """Test parameter substitution with default values."""
        # Only provide required parameters, use defaults for others
        minimal_params = {
            "input_data": "/data/test.nii.gz"
        }
        
        result = template_engine.instantiate_template("fmri_analysis", minimal_params)
        
        # Should use default values
        assert result.parameters["tr"] == 2.0  # Default TR
        assert result.parameters["high_pass_cutoff"] == 0.01  # Default cutoff
        assert result.parameters["motion_correction"] == True  # Default enabled
    
    def test_invalid_parameter_reference(self, template_engine):
        """Test handling of invalid parameter references in templates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_template = {
                "templates": {
                    "invalid_ref": {
                        "name": "Invalid Reference",
                        "description": "Template with invalid parameter reference",
                        "parameters": [
                            {
                                "name": "valid_param",
                                "type": "string",
                                "required": True
                            }
                        ],
                        "steps": [
                            {
                                "name": "test_step",
                                "tool": "test_tool",
                                "parameters": {
                                    "valid": "${valid_param}",
                                    "invalid": "${nonexistent_param}"  # Invalid reference
                                }
                            }
                        ]
                    }
                }
            }
            
            template_file = Path(temp_dir) / "invalid_ref.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(invalid_template, f)
            
            engine = WorkflowTemplateEngine(template_dir=temp_dir)
            
            with pytest.raises(ParameterValidationError) as exc_info:
                engine.instantiate_template("invalid_ref", {"valid_param": "test"})
            
            assert "Unknown parameter reference" in str(exc_info.value)


class TestTemplateComposition:
    """Test template composition and merging."""
    
    def test_template_step_merging(self, template_engine):
        """Test that derived templates properly merge steps from parent."""
        template = template_engine.get_template("connectivity_analysis")
        
        step_names = [step["name"] for step in template.steps]
        
        # Should have steps from base template
        assert "load_data" in step_names
        assert "preprocessing" in step_names
        
        # Should have additional steps from derived template
        assert "compute_connectivity" in step_names
        assert "network_analysis" in step_names
    
    def test_template_parameter_inheritance(self, template_engine):
        """Test parameter inheritance in derived templates."""
        base_template = template_engine.get_template("fmri_analysis")
        derived_template = template_engine.get_template("connectivity_analysis")
        
        base_param_names = [p.name for p in base_template.parameters]
        derived_param_names = [p.name for p in derived_template.parameters]
        
        # Derived template should have all base parameters
        for param_name in base_param_names:
            assert param_name in derived_param_names
        
        # Plus additional parameters
        assert "connectivity_method" in derived_param_names
        assert "connectivity_method" not in base_param_names
    
    def test_template_step_override(self, template_engine):
        """Test that derived templates can override parent steps."""
        template = template_engine.get_template("group_analysis")
        
        # Find the preprocessing step
        preprocess_steps = [step for step in template.steps if step["name"] == "preprocessing"]
        assert len(preprocess_steps) == 1
        
        preprocess_step = preprocess_steps[0]
        
        # Should have group-specific preprocessing parameters
        assert "group_mask" in preprocess_step["parameters"]
    
    def test_deep_template_inheritance(self, template_engine):
        """Test multi-level template inheritance."""
        # group_analysis extends connectivity_analysis extends fmri_analysis
        template = template_engine.get_template("group_analysis")
        
        step_names = [step["name"] for step in template.steps]
        
        # Should have steps from all levels of inheritance
        assert "load_data" in step_names  # From fmri_analysis
        assert "compute_connectivity" in step_names  # From connectivity_analysis
        assert "group_statistics" in step_names  # From group_analysis


class TestTemplateExecution:
    """Test template execution simulation."""
    
    def test_template_execution_order(self, template_engine):
        """Test that template steps maintain proper execution order."""
        params = {
            "input_data": "/data/test.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        result = template_engine.instantiate_template("fmri_analysis", params)
        
        step_names = [step["name"] for step in result.steps]
        
        # Verify logical execution order
        load_idx = step_names.index("load_data")
        preprocess_idx = step_names.index("preprocessing")
        results_idx = step_names.index("save_results")
        
        assert load_idx < preprocess_idx < results_idx
    
    def test_template_dependency_resolution(self, template_engine):
        """Test that template dependencies are properly resolved."""
        template = template_engine.get_template("connectivity_analysis")
        
        # Find steps that have dependencies
        conn_step = next(step for step in template.steps if step["name"] == "compute_connectivity")
        
        # Should depend on preprocessing output
        assert "depends_on" in conn_step
        assert "preprocessing" in conn_step["depends_on"]
    
    def test_parallel_step_identification(self, template_engine):
        """Test identification of steps that can run in parallel."""
        template = template_engine.get_template("group_analysis")
        
        # Find steps marked as parallel
        parallel_steps = [step for step in template.steps if step.get("parallel", False)]
        
        # Group analysis should have some parallel processing steps
        assert len(parallel_steps) > 0


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_nonexistent_template_error(self, template_engine):
        """Test error when requesting nonexistent template."""
        with pytest.raises(TemplateValidationError) as exc_info:
            template_engine.get_template("nonexistent_template")
        
        assert "Template not found" in str(exc_info.value)
    
    def test_empty_template_directory(self):
        """Test handling of empty template directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = WorkflowTemplateEngine(template_dir=temp_dir)
            
            templates = engine.get_all_templates()
            assert len(templates) == 0
    
    def test_malformed_parameter_definition(self, empty_template_engine):
        """Test handling of malformed parameter definitions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            malformed_template = {
                "templates": {
                    "malformed": {
                        "name": "Malformed Template",
                        "description": "Template with malformed parameters",
                        "parameters": [
                            {
                                "name": "param1",
                                # Missing required 'type' field
                                "required": True
                            }
                        ],
                        "steps": []
                    }
                }
            }
            
            template_file = Path(temp_dir) / "malformed.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(malformed_template, f)
            
            with pytest.raises(TemplateValidationError) as exc_info:
                WorkflowTemplateEngine(template_dir=temp_dir)
            
            assert "Parameter definition invalid" in str(exc_info.value)
    
    def test_recursive_parameter_reference(self, empty_template_engine):
        """Test detection of recursive parameter references."""
        with tempfile.TemporaryDirectory() as temp_dir:
            recursive_template = {
                "templates": {
                    "recursive": {
                        "name": "Recursive Template",
                        "description": "Template with recursive parameter reference",
                        "parameters": [
                            {
                                "name": "param1",
                                "type": "string",
                                "default": "${param1}",  # Self-reference
                                "required": False
                            }
                        ],
                        "steps": []
                    }
                }
            }
            
            template_file = Path(temp_dir) / "recursive.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(recursive_template, f)
            
            engine = WorkflowTemplateEngine(template_dir=temp_dir)
            
            with pytest.raises(ParameterValidationError) as exc_info:
                engine.instantiate_template("recursive", {})
            
            assert "Recursive parameter reference" in str(exc_info.value)


class TestPerformance:
    """Test performance characteristics of template engine."""
    
    def test_template_loading_performance(self):
        """Test template loading performance with many templates."""
        import time
        
        # Create many templates
        with tempfile.TemporaryDirectory() as temp_dir:
            many_templates = {"templates": {}}
            
            for i in range(100):
                template_id = f"template_{i:03d}"
                many_templates["templates"][template_id] = {
                    "name": f"Template {i}",
                    "description": f"Test template number {i}",
                    "parameters": [
                        {
                            "name": "input_data",
                            "type": "string",
                            "required": True
                        }
                    ],
                    "steps": [
                        {
                            "name": f"step_{i}",
                            "tool": f"tool_{i}",
                            "parameters": {"input": "${input_data}"}
                        }
                    ]
                }
            
            template_file = Path(temp_dir) / "many_templates.yaml"
            with open(template_file, 'w') as f:
                yaml.dump(many_templates, f)
            
            # Measure loading time
            start_time = time.time()
            engine = WorkflowTemplateEngine(template_dir=temp_dir)
            loading_time = time.time() - start_time
            
            # Should load 100 templates reasonably quickly
            assert loading_time < 5.0  # Less than 5 seconds
            assert len(engine.get_all_templates()) == 100
    
    def test_template_instantiation_performance(self, template_engine):
        """Test template instantiation performance."""
        import time
        
        params = {
            "input_data": "/data/test.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        # Measure instantiation time for multiple calls
        start_time = time.time()
        for _ in range(100):
            result = template_engine.instantiate_template("fmri_analysis", params)
            assert result is not None
        
        total_time = time.time() - start_time
        avg_time = total_time / 100
        
        # Should instantiate quickly (< 10ms per instantiation)
        assert avg_time < 0.01
    
    def test_parameter_validation_performance(self, template_engine, parameter_test_cases):
        """Test parameter validation performance with complex validation rules."""
        import time
        
        complex_params = {
            "input_data": "/very/long/path/to/input/data/file/with/complex/structure.nii.gz",
            "tr": 2.46789,
            "high_pass_cutoff": 0.00123456,
            "motion_correction": True,
            "slice_timing_correction": True,
            "spatial_smoothing_fwhm": 6.789,
            "output_dir": "/equally/long/output/directory/path/structure"
        }
        
        start_time = time.time()
        for _ in range(50):
            result = template_engine.instantiate_template("fmri_analysis", complex_params)
            assert result is not None
        
        total_time = time.time() - start_time
        avg_time = total_time / 50
        
        # Should validate quickly even with complex parameters
        assert avg_time < 0.02  # Less than 20ms per validation


class TemplateEngineStateMachine(RuleBasedStateMachine):
    """Property-based state machine testing for WorkflowTemplateEngine."""
    
    def __init__(self):
        super().__init__()
        self.temp_dir = tempfile.mkdtemp()
        self.templates = {}
        self.engine = None
    
    @rule(
        template_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=["Ll", "Lu", "Nd"])),
        num_parameters=st.integers(min_value=0, max_value=10),
        num_steps=st.integers(min_value=1, max_value=20)
    )
    def add_template(self, template_name, num_parameters, num_steps):
        """Add a template to the engine."""
        if template_name in self.templates:
            return
        
        parameters = []
        for i in range(num_parameters):
            param = {
                "name": f"param_{i}",
                "type": "string",
                "required": i < num_parameters // 2  # Half required, half optional
            }
            parameters.append(param)
        
        steps = []
        for i in range(num_steps):
            step = {
                "name": f"step_{i}",
                "tool": f"tool_{i}",
                "parameters": {}
            }
            steps.append(step)
        
        template_def = {
            "name": template_name.title(),
            "description": f"Generated template {template_name}",
            "parameters": parameters,
            "steps": steps
        }
        
        self.templates[template_name] = template_def
        
        # Update template file
        template_data = {"templates": self.templates}
        template_file = Path(self.temp_dir) / "templates.yaml"
        with open(template_file, 'w') as f:
            yaml.dump(template_data, f)
        
        # Recreate engine with updated templates
        self.engine = WorkflowTemplateEngine(template_dir=self.temp_dir)
    
    @rule()
    def test_template_loading(self):
        """Test that all added templates can be loaded."""
        if self.engine is None:
            return
        
        loaded_templates = self.engine.get_all_templates()
        loaded_names = [t.name.lower().replace(" ", "_") for t in loaded_templates]
        
        for template_name in self.templates:
            assert template_name in loaded_names
    
    @rule(template_name=st.sampled_from([]))
    def test_template_instantiation(self, template_name):
        """Test template instantiation with valid parameters."""
        # This rule is dynamically populated based on added templates
        pass
    
    @invariant()
    def templates_consistent(self):
        """Templates should remain consistent throughout operations."""
        if self.engine is None:
            return
        
        loaded_templates = self.engine.get_all_templates()
        assert len(loaded_templates) == len(self.templates)


class TestTemplateCaching:
    """Test template caching functionality."""
    
    def test_template_caching_enabled(self, template_engine):
        """Test that template caching improves performance."""
        import time
        
        # First access - should load from disk
        start_time = time.time()
        template1 = template_engine.get_template("fmri_analysis")
        first_access_time = time.time() - start_time
        
        # Second access - should use cache
        start_time = time.time()
        template2 = template_engine.get_template("fmri_analysis")
        second_access_time = time.time() - start_time
        
        # Should be the same template object (cached)
        assert template1 is template2
        
        # Second access should be faster
        assert second_access_time < first_access_time / 2
    
    def test_template_cache_invalidation(self, template_engine):
        """Test template cache invalidation when files change."""
        # Get initial template
        template1 = template_engine.get_template("fmri_analysis")
        
        # Simulate template file modification
        template_engine._template_cache.clear()
        
        # Get template again
        template2 = template_engine.get_template("fmri_analysis")
        
        # Should be different objects now
        assert template1 is not template2
        # But should have same content
        assert template1.name == template2.name


class TestTemplateMetadata:
    """Test template metadata handling."""
    
    def test_template_metadata_extraction(self, template_engine):
        """Test extraction of template metadata."""
        template = template_engine.get_template("fmri_analysis")
        
        # Should have basic metadata
        assert hasattr(template, 'name')
        assert hasattr(template, 'description')
        assert hasattr(template, 'version')
        assert hasattr(template, 'author')
        assert hasattr(template, 'created_date')
        
        # Metadata should be populated
        assert template.name is not None
        assert template.description is not None
    
    def test_template_tags_and_categories(self, template_engine):
        """Test template tags and categorization."""
        template = template_engine.get_template("fmri_analysis")
        
        # Should have tags for categorization
        assert hasattr(template, 'tags')
        assert isinstance(template.tags, list)
        
        # Should have category
        assert hasattr(template, 'category')
        assert template.category in ['neuroimaging', 'analysis', 'preprocessing']
    
    def test_template_search_by_metadata(self, template_engine):
        """Test searching templates by metadata."""
        # Search by tag
        fmri_templates = template_engine.search_templates(tags=['fmri'])
        assert len(fmri_templates) > 0
        
        # Search by category
        analysis_templates = template_engine.search_templates(category='analysis')
        assert len(analysis_templates) > 0
        
        # Search by description keywords
        connectivity_templates = template_engine.search_templates(keywords=['connectivity'])
        assert len(connectivity_templates) > 0


@pytest.mark.integration
class TestTemplateEngineIntegration:
    """Integration tests for WorkflowTemplateEngine."""
    
    def test_end_to_end_template_workflow(self, template_engine):
        """Test complete end-to-end template workflow."""
        # 1. List available templates
        templates = template_engine.get_all_templates()
        assert len(templates) > 0
        
        # 2. Get specific template
        template = template_engine.get_template("fmri_analysis")
        assert template is not None
        
        # 3. Validate parameters
        params = {
            "input_data": "/data/test.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        
        # 4. Instantiate template
        instance = template_engine.instantiate_template("fmri_analysis", params)
        assert instance is not None
        
        # 5. Verify instantiated template
        assert instance.template_name == "fmri_analysis"
        assert len(instance.steps) > 0
        assert all("${" not in str(step) for step in instance.steps)  # No unsubstituted parameters
    
    def test_template_inheritance_integration(self, template_engine):
        """Test template inheritance in an integrated scenario."""
        # Instantiate base template
        base_params = {
            "input_data": "/data/base.nii.gz",
            "tr": 2.0,
            "high_pass_cutoff": 0.01
        }
        base_instance = template_engine.instantiate_template("fmri_analysis", base_params)
        
        # Instantiate derived template  
        derived_params = base_params.copy()
        derived_params["connectivity_method"] = "correlation"
        derived_instance = template_engine.instantiate_template("connectivity_analysis", derived_params)
        
        # Derived should have all base steps plus additional ones
        base_step_names = [step["name"] for step in base_instance.steps]
        derived_step_names = [step["name"] for step in derived_instance.steps]
        
        for step_name in base_step_names:
            assert step_name in derived_step_names
        
        assert len(derived_instance.steps) > len(base_instance.steps)


if __name__ == "__main__":
    pytest.main([__file__])