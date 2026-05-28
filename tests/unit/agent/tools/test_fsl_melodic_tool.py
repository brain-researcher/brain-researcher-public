"""
Tests for FSL MELODIC ICA tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.tools.fsl_melodic_tool import (
    ApproachType,
    DualRegressionArgs,
    DualRegressionTool,
    FSLMELODICTool,
    FSLMELODICNiWrapTool,
    FSLMELODICTools,
    ICADimensionality,
    MELODICArgs,
    MELODICConfig,
    NoiseClassification,
)


class TestMELODICConfig(unittest.TestCase):
    """Test MELODIC configuration generation."""
    
    def setUp(self):
        """Set up test configuration."""
        self.config = MELODICConfig(
            approach=ApproachType.CONCAT,
            n_components=20,
            dimensionality=ICADimensionality.MANUAL,
            tr=2.0,
            output_dir="/tmp/melodic_output",
            mask="/tmp/mask.nii.gz",
            bg_threshold=10.0,
            var_norm=True,
            output_all=True,
            report=True
        )
    
    def test_config_creation(self):
        """Test configuration is created correctly."""
        assert self.config.approach == ApproachType.CONCAT
        assert self.config.n_components == 20
        assert self.config.dimensionality == ICADimensionality.MANUAL
        assert self.config.tr == 2.0
        assert self.config.output_dir == "/tmp/melodic_output"
    
    def test_command_args_generation(self):
        """Test command argument generation."""
        args = self.config.to_command_args()
        
        # Check key arguments are present
        assert "-a" in args
        assert "concat" in args
        assert "-d" in args
        assert "20" in args
        assert "--tr" in args
        assert "2.0" in args
        assert "-o" in args
        assert "/tmp/melodic_output" in args
        assert "-m" in args
        assert "/tmp/mask.nii.gz" in args
        assert "--vn" in args
        assert "--Oall" in args
        assert "--report" in args
    
    def test_automatic_dimensionality(self):
        """Test automatic dimensionality estimation."""
        config = MELODICConfig(
            approach=ApproachType.CONCAT,
            n_components=None,
            dimensionality=ICADimensionality.AUTOMATIC,
            tr=2.0,
            output_dir="/tmp/output"
        )
        args = config.to_command_args()
        
        assert "-d" in args
        assert "0" in args  # 0 means automatic
    
    def test_different_approaches(self):
        """Test different ICA approaches."""
        # Test MIGP approach
        config = MELODICConfig(
            approach=ApproachType.MIGP,
            n_components=None,
            dimensionality=ICADimensionality.AUTOMATIC,
            tr=2.0,
            output_dir="/tmp/output"
        )
        args = config.to_command_args()
        assert "-a" in args
        assert "migp" in args
        
        # Test TENSOR approach
        config.approach = ApproachType.TENSOR
        args = config.to_command_args()
        assert "-a" in args
        assert "tensor" in args


class TestFSLMELODICTool(unittest.TestCase):
    """Test FSL MELODIC ICA tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FSLMELODICTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "fsl_melodic_ica"
        assert "MELODIC" in self.tool.get_tool_description()
        assert "ICA" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == MELODICArgs
    
    def test_prepare_input_list_single_file(self):
        """Test input preparation for single file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = "/tmp/func.nii.gz"
            result = self.tool._prepare_input_list(input_file, temp_dir)
            assert result == input_file
    
    def test_prepare_input_list_multiple_files(self):
        """Test input preparation for multiple files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_files = [
                "/tmp/sub01_func.nii.gz",
                "/tmp/sub02_func.nii.gz",
                "/tmp/sub03_func.nii.gz"
            ]
            result = self.tool._prepare_input_list(input_files, temp_dir)
            
            # Check that a list file was created
            assert os.path.exists(result)
            assert result.endswith("input_files.txt")
            
            # Check file contents
            with open(result, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 3
                for i, line in enumerate(lines):
                    assert input_files[i] in line
    
    def test_run_melodic_basic(self):
        """Test basic MELODIC execution."""
        config = MELODICConfig(
            approach=ApproachType.CONCAT,
            n_components=20,
            dimensionality=ICADimensionality.MANUAL,
            tr=2.0,
            output_dir="/tmp/melodic_output"
        )
        
        result = self.tool._run_melodic(config, "/tmp/func.nii.gz")
        
        assert "command" in result
        assert "melodic" in result["command"]
        assert "-i /tmp/func.nii.gz" in result["command"]
        assert "-o /tmp/melodic_output" in result["command"]
        assert "-d 20" in result["command"]
        assert result["approach"] == "concat"
        assert result["n_components"] == 20
    
    def test_apply_denoising(self):
        """Test denoising application."""
        melodic_dir = "/tmp/melodic_output"
        input_file = "/tmp/func.nii.gz"
        noise_components = [1, 3, 5, 7]
        
        result = self.tool._apply_denoising(
            melodic_dir,
            input_file,
            noise_components
        )
        
        assert "command" in result
        assert "fsl_regfilt" in result["command"]
        assert "-f 1,3,5,7" in result["command"]
        assert result["denoised_file"] == "/tmp/func_denoised.nii.gz"
        assert result["noise_components"] == noise_components
    
    def test_apply_denoising_no_components(self):
        """Test denoising without specified components."""
        result = self.tool._apply_denoising(
            "/tmp/melodic_output",
            "/tmp/func.nii.gz",
            None
        )
        
        assert result["status"] == "skipped"
        assert "No noise components" in result["reason"]
    
    def test_extract_results(self):
        """Test results extraction from MELODIC directory."""
        with tempfile.TemporaryDirectory() as melodic_dir:
            # Create mock MELODIC output structure
            Path(os.path.join(melodic_dir, "melodic_IC.nii.gz")).touch()
            Path(os.path.join(melodic_dir, "melodic_mix")).touch()
            Path(os.path.join(melodic_dir, "melodic_Tmodes")).touch()
            Path(os.path.join(melodic_dir, "melodic_FTmix")).touch()
            Path(os.path.join(melodic_dir, "report.html")).touch()
            Path(os.path.join(melodic_dir, "log.txt")).touch()
            
            # Create stats directory with threshold maps
            stats_dir = os.path.join(melodic_dir, "stats")
            os.makedirs(stats_dir)
            Path(os.path.join(stats_dir, "thresh_zstat1.nii.gz")).touch()
            Path(os.path.join(stats_dir, "thresh_zstat2.nii.gz")).touch()
            
            results = self.tool._extract_results(melodic_dir)
            
            assert results["melodic_dir"] == melodic_dir
            assert "spatial_maps" in results["components"]
            assert "mixing_matrix" in results["components"]
            assert "time_series" in results["components"]
            assert "power_spectra" in results["components"]
            assert "component_1" in results["stats"]
            assert "component_2" in results["stats"]
            assert results["report"] is not None
            assert results["log"] is not None
    
    def test_run_success(self):
        """Test successful MELODIC execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            output_dir = os.path.join(temp_dir, "melodic_output")
            
            result = self.tool._run(
                input_files=input_file,
                output_dir=output_dir,
                tr=2.0,
                approach=ApproachType.CONCAT,
                n_components=20,
                dimensionality=ICADimensionality.MANUAL
            )
            
            assert result.status == "success"
            assert "melodic" in result.data
            assert "command" in result.data["melodic"]
            assert result.data["melodic"]["output_dir"] == output_dir
    
    def test_run_missing_input(self):
        """Test error handling for missing input file."""
        result = self.tool._run(
            input_files="/nonexistent/file.nii.gz",
            output_dir="/tmp/output",
            tr=2.0
        )
        
        assert result.status == "error"
        assert "not found" in result.error
    
    def test_run_with_denoising(self):
        """Test MELODIC with denoising enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            output_dir = os.path.join(temp_dir, "melodic_output")
            
            result = self.tool._run(
                input_files=input_file,
                output_dir=output_dir,
                tr=2.0,
                denoise=True,
                noise_components=[1, 2, 3]
            )
            
            assert result.status == "success"
            assert "denoising" in result.data
            assert result.data["denoising"] is not None
    
    def test_run_group_ica(self):
        """Test group ICA with multiple inputs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_files = [
                os.path.join(temp_dir, "sub01_func.nii.gz"),
                os.path.join(temp_dir, "sub02_func.nii.gz"),
                os.path.join(temp_dir, "sub03_func.nii.gz")
            ]
            for f in input_files:
                Path(f).touch()
            
            output_dir = os.path.join(temp_dir, "group_melodic")
            
            result = self.tool._run(
                input_files=input_files,
                output_dir=output_dir,
                tr=2.0,
                approach=ApproachType.MIGP
            )
            
            assert result.status == "success"
            assert result.data["melodic"]["approach"] == "migp"


class TestDualRegressionTool(unittest.TestCase):
    """Test Dual Regression tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = DualRegressionTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "fsl_dual_regression"
        assert "dual regression" in self.tool.get_tool_description()
        assert "group ICA" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == DualRegressionArgs
    
    def test_run_success(self):
        """Test successful dual regression setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock group ICA directory
            group_ica_dir = os.path.join(temp_dir, "group.ica")
            os.makedirs(group_ica_dir)
            Path(os.path.join(group_ica_dir, "melodic_IC.nii.gz")).touch()
            
            # Create mock subject files
            subject_files = [
                os.path.join(temp_dir, "sub01_func.nii.gz"),
                os.path.join(temp_dir, "sub02_func.nii.gz"),
                os.path.join(temp_dir, "sub03_func.nii.gz")
            ]
            for f in subject_files:
                Path(f).touch()
            
            output_dir = os.path.join(temp_dir, "dual_regression")
            
            result = self.tool._run(
                group_ica_dir=group_ica_dir,
                subject_files=subject_files,
                output_dir=output_dir,
                n_permutations=5000,
                var_norm=True
            )
            
            assert result.status == "success"
            assert "dual_regression" in result.data
            assert result.data["dual_regression"]["n_subjects"] == 3
            assert result.data["dual_regression"]["n_permutations"] == 5000
    
    def test_run_with_design_matrix(self):
        """Test dual regression with design matrix."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Setup files
            group_ica_dir = os.path.join(temp_dir, "group.ica")
            os.makedirs(group_ica_dir)
            Path(os.path.join(group_ica_dir, "melodic_IC.nii.gz")).touch()
            
            subject_files = [os.path.join(temp_dir, f"sub{i:02d}.nii.gz") for i in range(1, 4)]
            for f in subject_files:
                Path(f).touch()
            
            design_matrix = os.path.join(temp_dir, "design.mat")
            Path(design_matrix).touch()
            
            contrast_file = os.path.join(temp_dir, "design.con")
            Path(contrast_file).touch()
            
            output_dir = os.path.join(temp_dir, "dual_regression")
            
            result = self.tool._run(
                group_ica_dir=group_ica_dir,
                subject_files=subject_files,
                output_dir=output_dir,
                design_matrix=design_matrix,
                contrast_file=contrast_file
            )
            
            assert result.status == "success"
            assert result.data["dual_regression"]["design_matrix"] == design_matrix
            assert result.data["dual_regression"]["contrast_file"] == contrast_file
    
    def test_run_missing_group_ica(self):
        """Test error handling for missing group ICA directory."""
        result = self.tool._run(
            group_ica_dir="/nonexistent/group.ica",
            subject_files=["/tmp/sub01.nii.gz"],
            output_dir="/tmp/output"
        )
        
        assert result.status == "error"
        assert "not found" in result.error
    
    def test_run_missing_ic_file(self):
        """Test error handling for missing IC file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create group ICA dir without IC file
            group_ica_dir = os.path.join(temp_dir, "group.ica")
            os.makedirs(group_ica_dir)
            
            subject_file = os.path.join(temp_dir, "sub01.nii.gz")
            Path(subject_file).touch()
            
            result = self.tool._run(
                group_ica_dir=group_ica_dir,
                subject_files=[subject_file],
                output_dir="/tmp/output"
            )
            
            assert result.status == "error"
            assert "IC file not found" in result.error


class TestIntegration(unittest.TestCase):
    """Integration tests for FSL MELODIC tools."""
    
    def test_tools_collection(self):
        """Test getting all FSL MELODIC tools."""
        tools = FSLMELODICTools.get_all_tools()
        assert len(tools) == 3
        assert any(isinstance(t, FSLMELODICTool) for t in tools)
        assert any(isinstance(t, DualRegressionTool) for t in tools)
        assert any(isinstance(t, FSLMELODICNiWrapTool) for t in tools)
    
    def test_melodic_tool_with_all_options(self):
        """Test MELODIC tool with all options enabled."""
        tool = FSLMELODICTool()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            
            mask_file = os.path.join(temp_dir, "mask.nii.gz")
            Path(mask_file).touch()
            
            result = tool._run(
                input_files=input_file,
                output_dir=temp_dir,
                tr=2.0,
                approach=ApproachType.CONCAT,
                n_components=30,
                dimensionality=ICADimensionality.MANUAL,
                mask=mask_file,
                bg_threshold=15.0,
                var_norm=True,
                output_all=True,
                generate_report=True,
                denoise=True,
                noise_components=[1, 2, 3, 4, 5]
            )
            
            assert result.status == "success"
            assert "melodic" in result.data
            assert result.data["melodic"]["n_components"] == 30
            assert "denoising" in result.data
    
    def test_pipeline_melodic_to_dual_regression(self):
        """Test pipeline from MELODIC to dual regression."""
        melodic_tool = FSLMELODICTool()
        dr_tool = DualRegressionTool()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Step 1: Run group MELODIC
            input_files = [
                os.path.join(temp_dir, f"sub{i:02d}_func.nii.gz")
                for i in range(1, 4)
            ]
            for f in input_files:
                Path(f).touch()
            
            melodic_output = os.path.join(temp_dir, "group.ica")
            
            melodic_result = melodic_tool._run(
                input_files=input_files,
                output_dir=melodic_output,
                tr=2.0,
                approach=ApproachType.MIGP
            )
            
            assert melodic_result.status == "success"
            
            # Step 2: Create required files for dual regression
            os.makedirs(melodic_output, exist_ok=True)
            Path(os.path.join(melodic_output, "melodic_IC.nii.gz")).touch()
            
            # Step 3: Run dual regression
            dr_output = os.path.join(temp_dir, "dual_regression")
            
            dr_result = dr_tool._run(
                group_ica_dir=melodic_output,
                subject_files=input_files,
                output_dir=dr_output,
                n_permutations=1000
            )
            
            assert dr_result.status == "success"
            assert dr_result.data["dual_regression"]["group_ica_dir"] == melodic_output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
