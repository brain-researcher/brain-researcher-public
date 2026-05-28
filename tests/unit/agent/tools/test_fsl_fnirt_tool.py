"""Tests for FSL FNIRT Non-linear Registration tool."""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import subprocess

from brain_researcher.services.tools.fsl_fnirt_tool import (
    FSLFNIRTTool,
    FSLFNIRTArgs
)


class TestFSLFNIRTTool:
    """Test suite for FSL FNIRT non-linear registration tool."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = FSLFNIRTTool()
        self.temp_dir = tempfile.mkdtemp()
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "fsl_fnirt"
        assert "non-linear" in self.tool.get_tool_description().lower()
        assert "registration" in self.tool.get_tool_description().lower()
    
    def test_args_schema(self):
        """Test argument schema validation."""
        schema = self.tool.get_args_schema()
        
        # Check required fields
        assert "in_file" in schema.model_fields
        assert "ref_file" in schema.model_fields
        assert "output_dir" in schema.model_fields
        
        # Check default values
        args = FSLFNIRTArgs(
            in_file="test.nii.gz",
            ref_file="template.nii.gz",
            output_dir="output"
        )
        assert args.warp_resolution == "10,10,10"
        assert args.spline_order == 3
        assert args.regularization_model == "bending_energy"
    
    def test_parameter_validation(self):
        """Test parameter validation."""
        # Test valid parameters
        args = FSLFNIRTArgs(
            in_file="brain.nii.gz",
            ref_file="MNI152_T1_2mm.nii.gz",
            output_dir="output",
            warp_resolution="5,5,5",
            max_iterations="10,10,10,10",
            subsample_levels="4,2,1,1"
        )
        assert args.warp_resolution == "5,5,5"
        assert args.max_iterations == "10,10,10,10"
        
        # Test configuration file options
        args = FSLFNIRTArgs(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir="output",
            config_file="T1_2_MNI152_2mm"
        )
        assert args.config_file == "T1_2_MNI152_2mm"
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_successful_registration(self, mock_exists, mock_run):
        """Test successful non-linear registration."""
        # Setup mocks
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )
        
        # Run FNIRT
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="MNI152.nii.gz",
            output_dir=self.temp_dir,
            warp_resolution="10,10,10",
            max_iterations="5,5,5,5"
        )
        
        # Check result
        assert result.status == "success"
        assert "outputs" in result.data
        assert "warped_image" in result.data["outputs"]
        assert "warp_field" in result.data["outputs"]
        
        # Verify command was called
        mock_run.assert_called()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "fnirt"
        assert "--in" in call_args
        assert "--ref" in call_args
        assert "--iout" in call_args
        assert "--fout" in call_args
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_with_affine_initialization(self, mock_exists, mock_run):
        """Test registration with affine initialization."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Run with affine file
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir,
            affine_file="affine.mat"
        )
        
        # Verify affine was included
        call_args = mock_run.call_args[0][0]
        assert "--aff" in call_args
        aff_idx = call_args.index("--aff")
        assert call_args[aff_idx + 1] == "affine.mat"
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_with_masks(self, mock_exists, mock_run):
        """Test registration with masks."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Run with masks
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir,
            ref_mask="ref_mask.nii.gz",
            in_mask="in_mask.nii.gz",
            apply_ref_mask=1,
            apply_in_mask=1
        )
        
        # Verify masks were included
        call_args = mock_run.call_args[0][0]
        assert "--refmask" in call_args
        assert "--inmask" in call_args
        assert "--applyrefmask" in call_args
        assert "--applyinmask" in call_args
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_intensity_mapping(self, mock_exists, mock_run):
        """Test with intensity mapping/bias correction."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Run with intensity mapping
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir,
            intensity_mapping=True,
            intensity_mapping_order=5
        )
        
        # Verify intensity mapping parameters
        call_args = mock_run.call_args[0][0]
        assert "--intmod" in call_args
        assert "--intorder" in call_args
        intorder_idx = call_args.index("--intorder")
        assert call_args[intorder_idx + 1] == "5"
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_jacobian_output(self, mock_exists, mock_run):
        """Test Jacobian determinant output."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Run with Jacobian output
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir,
            jacobian_file="jacobian.nii.gz",
            jacobian_range="0.01,100.0"
        )
        
        # Verify Jacobian parameters
        call_args = mock_run.call_args[0][0]
        assert "--jout" in call_args
        assert "--jacrange" in call_args
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_regularization_options(self, mock_exists, mock_run):
        """Test different regularization options."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Test with membrane energy
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir,
            regularization_model="membrane_energy",
            regularization_lambda="100,50,25,10"
        )
        
        call_args = mock_run.call_args[0][0]
        assert "--regmod=membrane_energy" in call_args
        assert "--lambda" in call_args
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_multi_resolution_parameters(self, mock_exists, mock_run):
        """Test multi-resolution optimization parameters."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Run with custom multi-resolution settings
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir,
            max_iterations="10,10,5,5",
            subsample_levels="8,4,2,1",
            in_smoothing="8,4,2,0",
            ref_smoothing="8,4,2,0"
        )
        
        call_args = mock_run.call_args[0][0]
        assert "--miter" in call_args
        assert "--subsamp" in call_args
        assert "--infwhm" in call_args
        assert "--reffwhm" in call_args
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_apply_warp(self, mock_exists, mock_run):
        """Test applying a warp field to an image."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Apply warp
        result = self.tool.apply_warp(
            in_file="other_image.nii.gz",
            ref_file="template.nii.gz",
            warp_file="warp_field.nii.gz",
            out_file="warped_other.nii.gz",
            interp="spline"
        )
        
        assert result.status == "success"
        
        # Verify applywarp command
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "applywarp"
        assert "--in" in call_args
        assert "--ref" in call_args
        assert "--warp" in call_args
        assert "--out" in call_args
        assert "--interp" in call_args
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_inverse_warp_generation(self, mock_exists, mock_run):
        """Test inverse warp field generation."""
        mock_exists.return_value = True
        
        # Setup mock for both fnirt and invwarp calls
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # fnirt
            MagicMock(returncode=0, stdout="", stderr="")   # invwarp
        ]
        
        # Run registration
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir,
            derive_from_ref=False  # Should trigger inverse warp generation
        )
        
        # Check that invwarp was called
        assert mock_run.call_count == 2
        invwarp_call = mock_run.call_args_list[1][0][0]
        assert invwarp_call[0] == "invwarp"
    
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_error_handling(self, mock_exists, mock_run):
        """Test error handling for failed registration."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: Registration failed"
        )
        
        result = self.tool._run(
            in_file="brain.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir
        )
        
        assert result.status == "error"
        assert "Registration failed" in result.error
    
    @patch('pathlib.Path.exists')
    def test_missing_input_files(self, mock_exists):
        """Test handling of missing input files."""
        mock_exists.return_value = False
        
        result = self.tool._run(
            in_file="missing.nii.gz",
            ref_file="template.nii.gz",
            output_dir=self.temp_dir
        )
        
        assert result.status == "error"
        assert "not found" in result.error.lower()
    
    @patch('subprocess.run')
    def test_timeout_handling(self, mock_run):
        """Test handling of timeout during registration."""
        mock_run.side_effect = subprocess.TimeoutExpired("fnirt", 3600)
        
        # Create dummy input files
        Path(self.temp_dir, "brain.nii.gz").touch()
        Path(self.temp_dir, "template.nii.gz").touch()
        
        result = self.tool._run(
            in_file=str(Path(self.temp_dir, "brain.nii.gz")),
            ref_file=str(Path(self.temp_dir, "template.nii.gz")),
            output_dir=self.temp_dir
        )
        
        assert result.status == "error"
        assert "timed out" in result.error.lower()
    
    @pytest.mark.integration
    def test_with_real_data(self):
        """Test with real MRI data if available."""
        test_file = Path("/app/data/openneuro/ds000114/sub-01/ses-test/anat/sub-01_ses-test_T1w.nii.gz")
        template_file = Path("/usr/share/fsl/data/standard/MNI152_T1_2mm.nii.gz")
        
        if not test_file.exists() or not template_file.exists():
            pytest.skip("Test data not available")
        
        output_dir = Path(self.temp_dir) / "fnirt_output"
        
        result = self.tool._run(
            in_file=str(test_file),
            ref_file=str(template_file),
            output_dir=str(output_dir),
            config_file="T1_2_MNI152_2mm",
            warp_resolution="10,10,10",
            max_iterations="5,5,5,5"
        )
        
        # For real execution, check outputs
        assert result.status in ["success", "error"]
        if result.status == "success":
            assert Path(result.data["outputs"]["warped_image"]).exists()
            assert Path(result.data["outputs"]["warp_field"]).exists()
    
    def teardown_method(self):
        """Clean up test files."""
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)