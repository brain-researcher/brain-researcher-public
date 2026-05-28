"""Tests for FSL BET brain extraction tool."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from brain_researcher.services.tools.fsl_bet_tool import (
    FSLBETTool,
    FSLBETArgs,
    BETSurfaceEstimation
)


class TestFSLBETTool:
    """Test suite for FSL BET brain extraction tool."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = FSLBETTool()
        self.temp_dir = tempfile.mkdtemp()
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "fsl_bet"
        assert "brain extraction" in self.tool.get_tool_description().lower()
        assert "skull stripping" in self.tool.get_tool_description().lower()
    
    def test_args_schema(self):
        """Test argument schema validation."""
        schema = self.tool.get_args_schema()
        
        # Check required fields
        assert "input_file" in schema.model_fields
        assert "output_file" in schema.model_fields
        
        # Check default values
        args = FSLBETArgs(
            input_file="test.nii.gz",
            output_file="output.nii.gz"
        )
        assert args.fractional_intensity == 0.5
        assert args.generate_mask == True
        assert args.generate_skull == False
    
    def test_fractional_intensity_validation(self):
        """Test fractional intensity parameter validation."""
        # Valid range
        args = FSLBETArgs(
            input_file="test.nii.gz",
            output_file="output.nii.gz",
            fractional_intensity=0.3
        )
        assert args.fractional_intensity == 0.3
        
        # Test bounds
        with pytest.raises(ValueError):
            FSLBETArgs(
                input_file="test.nii.gz",
                output_file="output.nii.gz",
                fractional_intensity=1.5  # Out of range
            )
    
    def test_command_construction_basic(self):
        """Test basic command construction."""
        args = FSLBETArgs(
            input_file="input.nii.gz",
            output_file="output.nii.gz",
            fractional_intensity=0.5,
            generate_mask=True
        )
        
        cmd = self.tool._construct_command(args)
        
        # Check basic command structure
        assert cmd[0].endswith("bet")
        assert "input.nii.gz" in cmd
        assert "output.nii.gz" in cmd
        assert "-f" in cmd
        assert "0.5" in cmd
        assert "-m" in cmd  # Mask generation
    
    def test_command_construction_advanced(self):
        """Test advanced command construction with all options."""
        args = FSLBETArgs(
            input_file="input.nii.gz",
            output_file="output.nii.gz",
            fractional_intensity=0.4,
            gradient_threshold=0.1,
            generate_mask=True,
            generate_skull=True,
            generate_surface=True,
            surface_estimation=BETSurfaceEstimation.ROBUST,
            apply_to_4d=True,
            reduce_bias=True,
            robust_center=True,
            center_coordinates=(128, 128, 64),
            radius=75
        )
        
        cmd = self.tool._construct_command(args)
        
        # Check all parameters are included
        assert "-f" in cmd and "0.4" in cmd
        assert "-g" in cmd and "0.1" in cmd
        assert "-m" in cmd  # Mask
        assert "-s" in cmd  # Skull
        assert "-o" in cmd  # Surface
        assert "-R" in cmd  # Robust
        assert "-F" in cmd  # 4D
        assert "-c" in cmd  # Center coordinates
        assert "128" in cmd
        assert "-r" in cmd and "75" in cmd  # Radius
    
    def test_input_validation(self):
        """Test input file validation."""
        # Non-existent file
        valid, error = self.tool._validate_input("nonexistent.nii.gz")
        assert not valid
        assert "not found" in error
        
        # Invalid format
        temp_file = Path(self.temp_dir) / "test.txt"
        temp_file.write_text("test")
        valid, error = self.tool._validate_input(str(temp_file))
        assert not valid
        assert "Invalid file format" in error
        
        # Valid NIfTI file
        nifti_file = Path(self.temp_dir) / "test.nii.gz"
        nifti_file.touch()
        valid, error = self.tool._validate_input(str(nifti_file))
        assert valid
        assert error == ""
    
    @patch('subprocess.run')
    def test_successful_execution(self, mock_run):
        """Test successful BET execution."""
        # Mock successful subprocess run
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="BET completed successfully",
            stderr=""
        )
        
        # Create test input file
        input_file = Path(self.temp_dir) / "input.nii.gz"
        input_file.touch()
        output_file = Path(self.temp_dir) / "output.nii.gz"
        
        # Run BET
        result = self.tool._run(
            input_file=str(input_file),
            output_file=str(output_file),
            fractional_intensity=0.5,
            generate_mask=True
        )
        
        # Check result
        assert result.status == "success"
        assert "command" in result.data
        assert "outputs" in result.data
        assert result.data["outputs"]["brain"] == str(output_file)
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_failed_execution(self, mock_run):
        """Test handling of BET execution failure."""
        # Mock failed subprocess run
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: Invalid input file"
        )
        
        # Create test input file
        input_file = Path(self.temp_dir) / "input.nii.gz"
        input_file.touch()
        output_file = Path(self.temp_dir) / "output.nii.gz"
        
        # Run BET
        result = self.tool._run(
            input_file=str(input_file),
            output_file=str(output_file)
        )
        
        # Check error handling
        assert result.status == "error"
        assert "BET failed" in result.error
        assert "Invalid input file" in result.error
    
    @patch('subprocess.run')
    def test_timeout_handling(self, mock_run):
        """Test handling of execution timeout."""
        import subprocess
        
        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bet", timeout=300)
        
        # Create test input file
        input_file = Path(self.temp_dir) / "input.nii.gz"
        input_file.touch()
        
        # Run BET
        result = self.tool._run(
            input_file=str(input_file),
            output_file="output.nii.gz"
        )
        
        # Check timeout handling
        assert result.status == "error"
        assert "timed out" in result.error.lower()
    
    @patch('subprocess.run')
    def test_output_file_detection(self, mock_run):
        """Test detection of output files."""
        # Mock successful run
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Create test files
        input_file = Path(self.temp_dir) / "input.nii.gz"
        input_file.touch()
        output_file = Path(self.temp_dir) / "output.nii.gz"
        mask_file = Path(self.temp_dir) / "output_mask.nii.gz"
        skull_file = Path(self.temp_dir) / "output_skull.nii.gz"
        
        # Create mock output files
        output_file.touch()
        mask_file.touch()
        skull_file.touch()
        
        # Run BET with all outputs
        result = self.tool._run(
            input_file=str(input_file),
            output_file=str(output_file),
            generate_mask=True,
            generate_skull=True
        )
        
        # Check all outputs are detected
        assert result.status == "success"
        assert "brain" in result.data["outputs"]
        assert "mask" in result.data["outputs"]
        assert "skull" in result.data["outputs"]
    
    @patch('subprocess.run')
    def test_batch_processing(self, mock_run):
        """Test batch processing of multiple files."""
        # Mock successful runs
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Create test input files
        input_files = []
        for i in range(3):
            input_file = Path(self.temp_dir) / f"input_{i}.nii.gz"
            input_file.touch()
            input_files.append(str(input_file))
        
        # Run batch processing
        result = self.tool.extract_brain_batch(
            input_files=input_files,
            output_dir=self.temp_dir,
            fractional_intensity=0.5
        )
        
        # Check batch results
        assert result.status in ["success", "partial"]
        assert "processed" in result.data
        assert "n_processed" in result.data
        assert result.data["n_processed"] == 3
        assert mock_run.call_count == 3
    
    def test_surface_estimation_options(self):
        """Test different surface estimation options."""
        # Test each option
        for option in BETSurfaceEstimation:
            args = FSLBETArgs(
                input_file="input.nii.gz",
                output_file="output.nii.gz",
                surface_estimation=option
            )
            
            cmd = self.tool._construct_command(args)
            
            if option == BETSurfaceEstimation.ROBUST:
                assert "-R" in cmd
            elif option == BETSurfaceEstimation.EYE_CLEANUP:
                assert "-S" in cmd
            elif option == BETSurfaceEstimation.BIAS_FIELD:
                assert "-B" in cmd
    
    @pytest.mark.integration
    def test_with_real_data(self):
        """Test with real neuroimaging data from ds000114."""
        # Path to test dataset
        test_file = "/app/data/openneuro/ds000114/sub-01/ses-test/anat/sub-01_ses-test_T1w.nii.gz"
        
        if not Path(test_file).exists():
            pytest.skip("Test data not available")
        
        # Run BET on real data
        output_file = Path(self.temp_dir) / "brain.nii.gz"
        
        result = self.tool._run(
            input_file=test_file,
            output_file=str(output_file),
            fractional_intensity=0.5,
            generate_mask=True,
            robust_center=True
        )
        
        # For real execution, would check outputs
        # Here we just verify command generation
        assert result.data.get("command") is not None
        assert test_file in result.data["command"]
    
    def teardown_method(self):
        """Clean up test files."""
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)