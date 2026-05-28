"""
Tests for fMRIPrep tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.tools.fmriprep_tool import (
    CiftiOutput,
    ErrorMode,
    FMRIPrepArgs,
    FMRIPrepConfig,
    FMRIPrepQCArgs,
    FMRIPrepQCTool,
    FMRIPrepTool,
    FMRIPrepTools,
    MemoryProfile,
    OutputSpace,
)


class TestFMRIPrepConfig(unittest.TestCase):
    """Test fMRIPrep configuration generation."""
    
    def setUp(self):
        """Set up test configuration."""
        self.config = FMRIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/derivatives",
            participant_label=["01", "02"],
            work_dir="/tmp/work",
            fs_license_file="/opt/freesurfer/license.txt",
            output_spaces=["MNI152NLin2009cAsym", "T1w", "fsaverage"],
            skip_bids_validation=False,
            use_aroma=True,
            cifti_output="91k",
            n_cpus=8,
            mem_mb=16000,
            low_mem=False
        )
    
    def test_config_creation(self):
        """Test configuration is created correctly."""
        assert self.config.bids_dir == "/data/bids"
        assert self.config.output_dir == "/data/derivatives"
        assert self.config.participant_label == ["01", "02"]
        assert self.config.work_dir == "/tmp/work"
        assert self.config.fs_license_file == "/opt/freesurfer/license.txt"
        assert len(self.config.output_spaces) == 3
        assert self.config.use_aroma is True
        assert self.config.cifti_output == "91k"
    
    def test_command_args_generation(self):
        """Test command argument generation."""
        args = self.config.to_command_args()
        
        # Check key arguments
        assert "/data/bids" in args
        assert "/data/derivatives" in args
        assert "participant" in args
        assert "--participant-label" in args
        assert "01" in args
        assert "02" in args
        assert "-w" in args
        assert "/tmp/work" in args
        assert "--fs-license-file" in args
        assert "--output-spaces" in args
        assert "--use-aroma" in args
        assert "--cifti-output" in args
        assert "91k" in args
        assert "--n-cpus" in args
        assert "8" in args
        assert "--mem-mb" in args
        assert "16000" in args
    
    def test_minimal_config(self):
        """Test minimal configuration."""
        config = FMRIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            fs_license_file="/license.txt",
            output_spaces=["MNI152NLin2009cAsym"]
        )
        args = config.to_command_args()
        
        assert "/data/bids" in args
        assert "/data/output" in args
        assert "--participant-label" not in args
        assert "-w" not in args
    
    def test_longitudinal_config(self):
        """Test longitudinal processing configuration."""
        config = FMRIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=["01"],
            work_dir=None,
            fs_license_file="/license.txt",
            output_spaces=["T1w"],
            longitudinal=True
        )
        args = config.to_command_args()
        
        assert "--longitudinal" in args
    
    def test_fieldmap_less_config(self):
        """Test fieldmap-less correction configuration."""
        config = FMRIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            fs_license_file="/license.txt",
            output_spaces=["MNI152NLin2009cAsym"],
            use_syn_sdc="warn",
            force_syn=True
        )
        args = config.to_command_args()
        
        assert "--use-syn-sdc" in args
        assert "warn" in args
        assert "--force-syn" in args


class TestFMRIPrepTool(unittest.TestCase):
    """Test fMRIPrep tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FMRIPrepTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "fmriprep_preprocessing"
        assert "fMRIPrep" in self.tool.get_tool_description()
        assert "preprocessing" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FMRIPrepArgs
    
    def test_find_freesurfer_license(self):
        """Test FreeSurfer license detection."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock license file
            license_file = os.path.join(temp_dir, "license.txt")
            Path(license_file).touch()
            
            # Mock expanduser to return temp directory
            with patch('os.path.expanduser') as mock_expand:
                mock_expand.return_value = temp_dir
                with patch('os.path.exists') as mock_exists:
                    def exists_side_effect(path):
                        if path == os.path.join(temp_dir, ".freesurfer/license.txt"):
                            return False
                        return os.path.exists(path) if path == license_file else False
                    
                    mock_exists.side_effect = exists_side_effect
                    result = self.tool._find_freesurfer_license()
                    
                    # Should not find license in this test setup
                    assert result is None or isinstance(result, str)
    
    def test_validate_bids_dataset_valid(self):
        """Test BIDS dataset validation with valid dataset."""
        with tempfile.TemporaryDirectory() as bids_dir:
            # Create valid BIDS structure
            Path(os.path.join(bids_dir, "dataset_description.json")).touch()
            Path(os.path.join(bids_dir, "participants.tsv")).touch()
            os.makedirs(os.path.join(bids_dir, "sub-01"))
            os.makedirs(os.path.join(bids_dir, "sub-02"))
            
            validation = self.tool._validate_bids_dataset(bids_dir)
            
            assert validation["is_valid"] is True
            assert validation["has_dataset_description"] is True
            assert validation["has_participants"] is True
            assert "01" in validation["participants"]
            assert "02" in validation["participants"]
            assert len(validation["issues"]) == 0
    
    def test_validate_bids_dataset_invalid(self):
        """Test BIDS dataset validation with invalid dataset."""
        with tempfile.TemporaryDirectory() as bids_dir:
            # Missing required files
            validation = self.tool._validate_bids_dataset(bids_dir)
            
            assert validation["is_valid"] is False
            assert validation["has_dataset_description"] is False
            assert validation["has_participants"] is False
            assert len(validation["participants"]) == 0
            assert len(validation["issues"]) > 0
    
    def test_validate_bids_dataset_nonexistent(self):
        """Test BIDS dataset validation with nonexistent directory."""
        validation = self.tool._validate_bids_dataset("/nonexistent/path")
        
        assert validation["is_valid"] is False
        assert "not found" in validation["issues"][0]
    
    def test_extract_outputs(self):
        """Test output extraction from fMRIPrep directory."""
        with tempfile.TemporaryDirectory() as output_dir:
            # Create mock fMRIPrep output structure
            fmriprep_dir = os.path.join(output_dir, "fmriprep", "sub-01")
            os.makedirs(os.path.join(fmriprep_dir, "anat"))
            os.makedirs(os.path.join(fmriprep_dir, "func"))
            os.makedirs(os.path.join(fmriprep_dir, "figures"))
            
            # Create mock files
            Path(os.path.join(fmriprep_dir, "anat", "sub-01_T1w_preproc.nii.gz")).touch()
            Path(os.path.join(fmriprep_dir, "func", "sub-01_task-rest_bold_preproc.nii.gz")).touch()
            Path(os.path.join(fmriprep_dir, "func", "sub-01_task-rest_desc-confounds_timeseries.tsv")).touch()
            Path(os.path.join(output_dir, "sub-01.html")).touch()
            
            outputs = self.tool._extract_outputs(output_dir)
            
            assert outputs["output_dir"] == output_dir
            assert len(outputs["html_reports"]) == 1
            assert "sub-01" in outputs["derivatives"]
            assert len(outputs["derivatives"]["sub-01"]["anat"]) == 1
            assert len(outputs["derivatives"]["sub-01"]["func"]) == 1
            assert len(outputs["confounds"]) == 1
    
    def test_generate_command_singularity(self):
        """Test Singularity command generation."""
        config = FMRIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=["01"],
            work_dir="/tmp/work",
            fs_license_file="/license.txt",
            output_spaces=["MNI152NLin2009cAsym"]
        )
        
        command = self.tool._generate_command(
            config,
            "singularity",
            "/containers/fmriprep.sif"
        )
        
        assert "singularity run" in command
        assert "--cleanenv" in command
        assert "-B /data/bids:/data/bids" in command
        assert "-B /data/output:/data/output" in command
        assert "/containers/fmriprep.sif" in command
    
    def test_generate_command_docker(self):
        """Test Docker command generation."""
        config = FMRIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=["01"],
            work_dir="/tmp/work",
            fs_license_file="/license.txt",
            output_spaces=["MNI152NLin2009cAsym"]
        )
        
        command = self.tool._generate_command(
            config,
            "docker",
            "nipreps/fmriprep:latest"
        )
        
        assert "docker run" in command
        assert "--rm" in command
        assert "-v /data/bids:/data:ro" in command
        assert "-v /data/output:/out" in command
        assert "nipreps/fmriprep:latest" in command
    
    def test_run_success(self):
        """Test successful fMRIPrep setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_dir = os.path.join(temp_dir, "bids")
            output_dir = os.path.join(temp_dir, "output")
            
            # Create valid BIDS structure
            os.makedirs(bids_dir)
            Path(os.path.join(bids_dir, "dataset_description.json")).touch()
            os.makedirs(os.path.join(bids_dir, "sub-01"))
            
            result = self.tool._run(
                bids_dir=bids_dir,
                output_dir=output_dir,
                participant_label=["01"],
                skip_bids_validation=False,
                container_type="singularity"
            )
            
            assert result.status == "success"
            assert "command" in result.data
            assert "config" in result.data
            assert result.data["config"]["bids_dir"] == bids_dir
            assert result.data["config"]["output_dir"] == output_dir
    
    def test_run_invalid_bids(self):
        """Test error handling for invalid BIDS dataset."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_dir = os.path.join(temp_dir, "bids")
            output_dir = os.path.join(temp_dir, "output")
            
            # Create invalid BIDS structure (missing required files)
            os.makedirs(bids_dir)
            
            result = self.tool._run(
                bids_dir=bids_dir,
                output_dir=output_dir,
                skip_bids_validation=False
            )
            
            assert result.status == "error"
            assert "Invalid BIDS dataset" in result.error
    
    def test_run_skip_validation(self):
        """Test skipping BIDS validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_dir = os.path.join(temp_dir, "bids")
            output_dir = os.path.join(temp_dir, "output")
            
            # Create directory without BIDS structure
            os.makedirs(bids_dir)
            
            result = self.tool._run(
                bids_dir=bids_dir,
                output_dir=output_dir,
                skip_bids_validation=True,
                container_type="docker"
            )
            
            assert result.status == "success"
            assert "command" in result.data
    
    def test_run_with_all_options(self):
        """Test with all options enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_dir = os.path.join(temp_dir, "bids")
            output_dir = os.path.join(temp_dir, "output")
            
            os.makedirs(bids_dir)
            
            result = self.tool._run(
                bids_dir=bids_dir,
                output_dir=output_dir,
                participant_label=["01", "02"],
                output_spaces=["MNI152NLin2009cAsym", "T1w", "fsaverage"],
                skip_bids_validation=True,
                use_aroma=True,
                cifti_output="91k",
                n_cpus=8,
                mem_mb=16000,
                low_mem=False,
                longitudinal=True,
                use_syn_sdc="warn",
                force_syn=True
            )
            
            assert result.status == "success"
            command = result.data["command"]
            assert "--use-aroma" in command
            assert "--cifti-output" in command
            assert "--longitudinal" in command
            assert "--use-syn-sdc" in command


class TestFMRIPrepQCTool(unittest.TestCase):
    """Test fMRIPrep QC tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FMRIPrepQCTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "fmriprep_qc"
        assert "quality control" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FMRIPrepQCArgs
    
    def test_parse_confounds(self):
        """Test confounds file parsing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False) as f:
            # Write mock confounds data
            f.write("framewise_displacement\tstd_dvars\tglobal_signal\tcsf\twhite_matter\tmotion_outlier00\n")
            f.write("0.0\t1.0\t100.0\t50.0\t80.0\t0\n")
            f.write("0.3\t1.1\t101.0\t51.0\t81.0\t0\n")
            f.write("0.8\t1.5\t102.0\t52.0\t82.0\t1\n")
            f.write("0.2\t0.9\t99.0\t49.0\t79.0\t0\n")
            f.name
            
        try:
            metrics = self.tool._parse_confounds(f.name)
            
            assert "mean_fd" in metrics
            assert "max_fd" in metrics
            assert metrics["max_fd"] == 0.8
            assert "percent_fd_above_0.5" in metrics
            assert "mean_dvars" in metrics
            assert "mean_global_signal" in metrics
            assert "n_motion_outliers" in metrics
        finally:
            os.unlink(f.name)
    
    def test_run_success(self):
        """Test successful QC extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock fMRIPrep output structure
            fmriprep_dir = os.path.join(temp_dir, "fmriprep", "sub-01", "func")
            os.makedirs(fmriprep_dir)
            
            # Create mock confounds file
            confounds_file = os.path.join(
                fmriprep_dir,
                "sub-01_task-rest_desc-confounds_timeseries.tsv"
            )
            with open(confounds_file, 'w') as f:
                f.write("framewise_displacement\tstd_dvars\n")
                f.write("0.1\t1.0\n")
                f.write("0.2\t1.1\n")
            
            result = self.tool._run(
                fmriprep_dir=temp_dir
            )
            
            assert result.status == "success"
            assert "qc_report" in result.data
            assert "participants" in result.data["qc_report"]
            assert result.data["qc_report"]["summary"]["n_participants"] == 1
    
    def test_run_missing_directory(self):
        """Test error handling for missing directory."""
        result = self.tool._run(
            fmriprep_dir="/nonexistent/directory"
        )
        
        assert result.status == "error"
        assert "not found" in result.error
    
    def test_run_with_output_file(self):
        """Test QC extraction with output file saving."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock structure
            fmriprep_dir = os.path.join(temp_dir, "fmriprep", "sub-01")
            os.makedirs(fmriprep_dir)
            
            output_file = os.path.join(temp_dir, "qc_report.json")
            
            result = self.tool._run(
                fmriprep_dir=temp_dir,
                output_file=output_file
            )
            
            assert result.status == "success"
            assert os.path.exists(output_file)
            
            # Verify JSON was written
            with open(output_file, 'r') as f:
                report = json.load(f)
                assert "participants" in report
                assert "summary" in report


class TestIntegration(unittest.TestCase):
    """Integration tests for fMRIPrep tools."""
    
    def test_tools_collection(self):
        """Test getting all fMRIPrep tools."""
        tools = FMRIPrepTools.get_all_tools()
        assert len(tools) == 2
        assert any(isinstance(t, FMRIPrepTool) for t in tools)
        assert any(isinstance(t, FMRIPrepQCTool) for t in tools)
    
    def test_output_space_enum(self):
        """Test output space enumeration."""
        assert OutputSpace.MNI152NLin2009cAsym.value == "MNI152NLin2009cAsym"
        assert OutputSpace.FSAVERAGE.value == "fsaverage"
        assert OutputSpace.T1W.value == "T1w"
    
    def test_cifti_output_enum(self):
        """Test CIFTI output enumeration."""
        assert CiftiOutput.RES_91K.value == "91k"
        assert CiftiOutput.RES_170K.value == "170k"
        assert CiftiOutput.NONE.value == ""
    
    def test_memory_profile_enum(self):
        """Test memory profile enumeration."""
        assert MemoryProfile.LOW.value == "low"
        assert MemoryProfile.HIGH.value == "high"
        assert MemoryProfile.RESAMPLING.value == "resampling"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])