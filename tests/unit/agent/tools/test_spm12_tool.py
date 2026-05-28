"""
Tests for SPM12 tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.tools.spm12_tool import (
    CorrectionType,
    DCMModelType,
    DesignType,
    NormalizationMethod,
    SegmentationMethod,
    SPM12Config,
    SPM12DCMArgs,
    SPM12DCMTool,
    SPM12StatisticalArgs,
    SPM12StatisticalTool,
    SPM12Tools,
    SPM12VBMArgs,
    SPM12VBMTool,
)


class TestSPM12Config(unittest.TestCase):
    """Test SPM12 configuration."""
    
    def setUp(self):
        """Set up test configuration."""
        self.config = SPM12Config(
            matlab_cmd="matlab",
            spm_path="/opt/spm12",
            mcr_path="/opt/mcr",
            use_standalone=False,
            n_threads=4
        )
    
    def test_config_creation(self):
        """Test configuration is created correctly."""
        assert self.config.matlab_cmd == "matlab"
        assert self.config.spm_path == "/opt/spm12"
        assert self.config.mcr_path == "/opt/mcr"
        assert self.config.use_standalone is False
        assert self.config.n_threads == 4
    
    def test_matlab_command_regular(self):
        """Test MATLAB command generation."""
        cmd = self.config.get_matlab_command()
        assert cmd[0] == "matlab"
        assert "-nodisplay" in cmd
        assert "-nosplash" in cmd
        assert "-nodesktop" in cmd
        assert "-r" in cmd
    
    def test_matlab_command_standalone(self):
        """Test standalone SPM command generation."""
        self.config.use_standalone = True
        cmd = self.config.get_matlab_command()
        assert "/opt/spm12/run_spm12.sh" in cmd[0]
        assert "/opt/mcr" in cmd
        assert "batch" in cmd


class TestSPM12StatisticalTool(unittest.TestCase):
    """Test SPM12 statistical analysis tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = SPM12StatisticalTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "spm12_statistical"
        assert "statistical parametric mapping" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == SPM12StatisticalArgs
    
    def test_generate_batch_script_one_sample(self):
        """Test batch script generation for one-sample t-test."""
        with tempfile.TemporaryDirectory() as temp_dir:
            images = [f"/data/sub{i:02d}.nii" for i in range(1, 11)]
            contrasts = {"main_effect": [1]}
            
            script = self.tool._generate_batch_script(
                images=images,
                design_type=DesignType.ONE_SAMPLE_T,
                output_dir=temp_dir,
                covariates=None,
                contrasts=contrasts,
                mask=None,
                correction=CorrectionType.FWE,
                threshold=0.05
            )
            
            assert "factorial_design" in script
            assert "des.t1.scans" in script
            assert all(img in script for img in images)
            assert "spm_jobman('run', matlabbatch)" in script
    
    def test_generate_batch_script_two_sample(self):
        """Test batch script generation for two-sample t-test."""
        with tempfile.TemporaryDirectory() as temp_dir:
            images = [f"/data/sub{i:02d}.nii" for i in range(1, 11)]
            contrasts = {"group_diff": [1, -1]}
            
            script = self.tool._generate_batch_script(
                images=images,
                design_type=DesignType.TWO_SAMPLE_T,
                output_dir=temp_dir,
                covariates=None,
                contrasts=contrasts,
                mask=None,
                correction=CorrectionType.FDR,
                threshold=0.05
            )
            
            assert "des.t2.scans1" in script
            assert "des.t2.scans2" in script
    
    def test_generate_batch_script_with_covariates(self):
        """Test batch script with covariates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            images = [f"/data/sub{i:02d}.nii" for i in range(1, 5)]
            covariates = {"age": [25, 30, 35, 40], "sex": [1, 0, 1, 0]}
            contrasts = {"main": [1]}
            
            script = self.tool._generate_batch_script(
                images=images,
                design_type=DesignType.ONE_SAMPLE_T,
                output_dir=temp_dir,
                covariates=covariates,
                contrasts=contrasts,
                mask=None,
                correction=CorrectionType.NONE,
                threshold=0.001
            )
            
            assert "cov(1).c" in script
            assert "cov(1).cname = 'age'" in script
            assert "cov(2).cname = 'sex'" in script
    
    def test_run_success(self):
        """Test successful statistical analysis setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock images
            images = []
            for i in range(3):
                img_file = os.path.join(temp_dir, f"sub{i:02d}.nii")
                Path(img_file).touch()
                images.append(img_file)
            
            output_dir = os.path.join(temp_dir, "spm_output")
            
            result = self.tool._run(
                images=images,
                design_type=DesignType.ONE_SAMPLE_T,
                output_dir=output_dir,
                contrasts={"main": [1]}
            )
            
            assert result.status == "success"
            assert "command" in result.data
            assert "script_file" in result.data
            assert os.path.exists(result.data["script_file"])
            assert result.data["n_images"] == 3
    
    def test_run_missing_images(self):
        """Test error handling for missing images."""
        result = self.tool._run(
            images=["/nonexistent/img1.nii", "/nonexistent/img2.nii"],
            design_type=DesignType.ONE_SAMPLE_T,
            output_dir="/output",
            contrasts={"main": [1]}
        )
        
        assert result.status == "error"
        assert "not found" in result.error


class TestSPM12DCMTool(unittest.TestCase):
    """Test SPM12 DCM tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = SPM12DCMTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "spm12_dcm"
        assert "Dynamic Causal Modeling" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == SPM12DCMArgs
    
    def test_generate_dcm_script(self):
        """Test DCM script generation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            voi_timeseries = {
                "V1": "/data/voi_v1.mat",
                "V2": "/data/voi_v2.mat",
                "V5": "/data/voi_v5.mat"
            }
            a_matrix = [[1, 1, 0], [1, 1, 1], [0, 1, 1]]
            b_matrix = {"attention": [[0, 1, 0], [0, 0, 0], [0, 0, 0]]}
            c_matrix = [[1], [0], [0]]
            
            script = self.tool._generate_dcm_script(
                voi_timeseries=voi_timeseries,
                model_type=DCMModelType.BILINEAR,
                a_matrix=a_matrix,
                b_matrix=b_matrix,
                c_matrix=c_matrix,
                tr=2.0,
                output_dir=temp_dir
            )
            
            assert "DCM Structure Specification" in script
            assert "DCM.n = 3" in script
            assert "DCM.Y.dt = 2.0" in script
            assert "DCM.a =" in script
            assert "DCM.b(:,:,1)" in script
            assert "spm_dcm_estimate(DCM)" in script
            assert "jsonencode(params)" in script
    
    def test_run_success(self):
        """Test successful DCM setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock VOI files
            voi_files = {}
            for region in ["V1", "V2"]:
                voi_file = os.path.join(temp_dir, f"voi_{region}.mat")
                Path(voi_file).touch()
                voi_files[region] = voi_file
            
            output_dir = os.path.join(temp_dir, "dcm_output")
            
            result = self.tool._run(
                voi_timeseries=voi_files,
                model_type=DCMModelType.BILINEAR,
                a_matrix=[[1, 1], [1, 1]],
                tr=2.0,
                output_dir=output_dir
            )
            
            assert result.status == "success"
            assert "command" in result.data
            assert "script_file" in result.data
            assert result.data["n_regions"] == 2
            assert result.data["model_type"] == "bilinear"
    
    def test_run_missing_voi(self):
        """Test error handling for missing VOI files."""
        result = self.tool._run(
            voi_timeseries={"V1": "/nonexistent/voi.mat"},
            model_type=DCMModelType.NONLINEAR,
            a_matrix=[[1]],
            tr=2.0,
            output_dir="/output"
        )
        
        assert result.status == "error"
        assert "VOI file not found" in result.error


class TestSPM12VBMTool(unittest.TestCase):
    """Test SPM12 VBM tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = SPM12VBMTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "spm12_vbm"
        assert "Voxel-Based Morphometry" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == SPM12VBMArgs
    
    def test_generate_vbm_script(self):
        """Test VBM script generation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            structural_images = [f"/data/T1_{i}.nii" for i in range(1, 6)]
            
            script = self.tool._generate_vbm_script(
                structural_images=structural_images,
                output_dir=temp_dir,
                segmentation_method=SegmentationMethod.UNIFIED,
                modulation=True,
                smoothing_fwhm=8.0,
                create_dartel=False
            )
            
            assert "Unified Segmentation" in script
            assert "spatial.preproc" in script
            assert all(img in script for img in structural_images)
            assert "smoothing" in script.lower()
            assert f"fwhm = [8.0 8.0 8.0]" in script
    
    def test_generate_vbm_script_with_dartel(self):
        """Test VBM script with DARTEL."""
        with tempfile.TemporaryDirectory() as temp_dir:
            structural_images = [f"/data/T1_{i}.nii" for i in range(1, 3)]
            
            script = self.tool._generate_vbm_script(
                structural_images=structural_images,
                output_dir=temp_dir,
                segmentation_method=SegmentationMethod.UNIFIED,
                modulation=False,
                smoothing_fwhm=6.0,
                create_dartel=True
            )
            
            assert "DARTEL Template Creation" in script
            assert "tools.dartel.warp" in script
    
    def test_run_success(self):
        """Test successful VBM setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock structural images
            images = []
            for i in range(3):
                img_file = os.path.join(temp_dir, f"T1_{i:02d}.nii")
                Path(img_file).touch()
                images.append(img_file)
            
            output_dir = os.path.join(temp_dir, "vbm_output")
            
            result = self.tool._run(
                structural_images=images,
                output_dir=output_dir,
                segmentation_method=SegmentationMethod.UNIFIED,
                modulation=True,
                smoothing_fwhm=8.0
            )
            
            assert result.status == "success"
            assert "command" in result.data
            assert "script_file" in result.data
            assert result.data["n_subjects"] == 3
            assert result.data["smoothing"] == "8.0mm"
            assert os.path.exists(os.path.join(output_dir, "gray_matter"))
            assert os.path.exists(os.path.join(output_dir, "white_matter"))
    
    def test_run_missing_images(self):
        """Test error handling for missing structural images."""
        result = self.tool._run(
            structural_images=["/nonexistent/T1.nii"],
            output_dir="/output"
        )
        
        assert result.status == "error"
        assert "not found" in result.error


class TestIntegration(unittest.TestCase):
    """Integration tests for SPM12 tools."""
    
    def test_tools_collection(self):
        """Test getting all SPM12 tools."""
        tools = SPM12Tools.get_all_tools()
        assert len(tools) == 3
        assert any(isinstance(t, SPM12StatisticalTool) for t in tools)
        assert any(isinstance(t, SPM12DCMTool) for t in tools)
        assert any(isinstance(t, SPM12VBMTool) for t in tools)
    
    def test_design_type_enum(self):
        """Test design type enumeration."""
        assert DesignType.ONE_SAMPLE_T.value == "one_sample_t"
        assert DesignType.TWO_SAMPLE_T.value == "two_sample_t"
        assert DesignType.FLEXIBLE_FACTORIAL.value == "flexible_factorial"
    
    def test_correction_type_enum(self):
        """Test correction type enumeration."""
        assert CorrectionType.FWE.value == "FWE"
        assert CorrectionType.FDR.value == "FDR"
        assert CorrectionType.NONE.value == "none"
    
    def test_dcm_model_type_enum(self):
        """Test DCM model type enumeration."""
        assert DCMModelType.BILINEAR.value == "bilinear"
        assert DCMModelType.NONLINEAR.value == "nonlinear"
        assert DCMModelType.TWO_STATE.value == "two_state"
    
    def test_segmentation_method_enum(self):
        """Test segmentation method enumeration."""
        assert SegmentationMethod.STANDARD.value == "standard"
        assert SegmentationMethod.UNIFIED.value == "unified"
        assert SegmentationMethod.NEW_SEGMENT.value == "new_segment"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])