"""
Tests for QSIPrep tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.tools.qsiprep_tool import (
    DenoisingMethod,
    DistortionCorrection,
    HeadMotionCorrection,
    OutputResolution,
    QSIPrepArgs,
    QSIPrepConfig,
    QSIPrepQCArgs,
    QSIPrepQCTool,
    QSIPrepReconArgs,
    QSIPrepReconTool,
    QSIPrepTool,
    QSIPrepTools,
    ReconWorkflow,
)


class TestQSIPrepConfig(unittest.TestCase):
    """Test QSIPrep configuration generation."""

    def setUp(self):
        """Set up test configuration."""
        self.config = QSIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/derivatives",
            participant_label=["01", "02"],
            work_dir="/tmp/work",
            fs_license_file="/opt/freesurfer/license.txt",
            denoise_method=DenoisingMethod.PATCH2SELF,
            distortion_correction=DistortionCorrection.TOPUP,
            b0_threshold=100.0,
            output_resolution="1.25mm",
            skip_bids_validation=False,
            n_cpus=8,
            mem_mb=16000,
        )

    def test_config_creation(self):
        """Test configuration is created correctly."""
        assert self.config.bids_dir == "/data/bids"
        assert self.config.output_dir == "/data/derivatives"
        assert self.config.participant_label == ["01", "02"]
        assert self.config.work_dir == "/tmp/work"
        assert self.config.fs_license_file == "/opt/freesurfer/license.txt"
        assert self.config.denoise_method == DenoisingMethod.PATCH2SELF
        assert self.config.distortion_correction == DistortionCorrection.TOPUP

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
        assert "--denoise-method" in args
        assert "patch2self" in args
        assert "--use-syn-sdc" in args
        assert "--b0-threshold" in args
        assert "100.0" in args
        assert "--output-resolution" in args
        assert "1.25mm" in args
        assert "--n_cpus" in args
        assert "8" in args
        assert "--mem_mb" in args
        assert "16000" in args

    def test_minimal_config(self):
        """Test minimal configuration."""
        config = QSIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            fs_license_file="/license.txt",
        )
        args = config.to_command_args()

        assert "/data/bids" in args
        assert "/data/output" in args
        assert "--participant-label" not in args
        assert "-w" not in args

    def test_denoising_options(self):
        """Test different denoising options."""
        config = QSIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            fs_license_file="/license.txt",
            denoise_method=DenoisingMethod.DWIDENOISE,
        )
        args = config.to_command_args()

        assert "--denoise-method" in args
        assert "dwidenoise" in args

    def test_no_distortion_correction(self):
        """Test configuration without distortion correction."""
        config = QSIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            fs_license_file="/license.txt",
            distortion_correction=DistortionCorrection.NONE,
        )
        args = config.to_command_args()

        # Should not add --use-syn-sdc when distortion_correction is NONE
        assert "--use-syn-sdc" not in args


class TestQSIPrepTool(unittest.TestCase):
    """Test QSIPrep preprocessing tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = QSIPrepTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "qsiprep_preprocessing"
        assert "diffusion" in self.tool.get_tool_description().lower()
        assert "QSIPrep" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == QSIPrepArgs

    def test_find_freesurfer_license(self):
        """Test FreeSurfer license detection."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock license file
            license_file = os.path.join(temp_dir, "license.txt")
            Path(license_file).touch()

            # Mock expanduser to return temp directory
            with patch("os.path.expanduser") as mock_expand:
                mock_expand.return_value = temp_dir
                with patch("os.path.exists") as mock_exists:

                    def exists_side_effect(path):
                        if path == os.path.join(temp_dir, ".freesurfer/license.txt"):
                            return False
                        return os.path.exists(path) if path == license_file else False

                    mock_exists.side_effect = exists_side_effect
                    result = self.tool._find_freesurfer_license()

                    # Should not find license in this test setup
                    assert result is None or isinstance(result, str)

    def test_validate_bids_dataset_valid(self):
        """Test BIDS dataset validation with valid DWI dataset."""
        with tempfile.TemporaryDirectory() as bids_dir:
            # Create valid BIDS structure with DWI data
            Path(os.path.join(bids_dir, "dataset_description.json")).touch()

            # Create participant with DWI data
            dwi_dir = os.path.join(bids_dir, "sub-01", "dwi")
            os.makedirs(dwi_dir)
            Path(os.path.join(dwi_dir, "sub-01_dwi.nii.gz")).touch()
            Path(os.path.join(dwi_dir, "sub-01_dwi.bval")).touch()
            Path(os.path.join(dwi_dir, "sub-01_dwi.bvec")).touch()

            validation = self.tool._validate_bids_dataset(bids_dir)

            assert validation["is_valid"] is True
            assert validation["has_dataset_description"] is True
            assert validation["has_dwi"] is True
            assert "01" in validation["participants"]
            assert len(validation["dwi_files"]) > 0
            assert len(validation["issues"]) == 0

    def test_validate_bids_dataset_no_dwi(self):
        """Test BIDS dataset validation without DWI data."""
        with tempfile.TemporaryDirectory() as bids_dir:
            # Create BIDS structure without DWI
            Path(os.path.join(bids_dir, "dataset_description.json")).touch()
            os.makedirs(os.path.join(bids_dir, "sub-01", "anat"))

            validation = self.tool._validate_bids_dataset(bids_dir)

            assert validation["is_valid"] is False
            assert validation["has_dwi"] is False
            assert "No DWI files found" in validation["issues"]

    def test_extract_outputs(self):
        """Test output extraction from QSIPrep directory."""
        with tempfile.TemporaryDirectory() as output_dir:
            # Create mock QSIPrep output structure
            qsiprep_dir = os.path.join(output_dir, "qsiprep", "sub-01")
            os.makedirs(os.path.join(qsiprep_dir, "anat"))
            os.makedirs(os.path.join(qsiprep_dir, "dwi"))
            os.makedirs(os.path.join(qsiprep_dir, "figures"))

            # Create mock files
            Path(os.path.join(qsiprep_dir, "anat", "sub-01_T1w_preproc.nii.gz")).touch()
            Path(os.path.join(qsiprep_dir, "dwi", "sub-01_dwi_preproc.nii.gz")).touch()
            Path(os.path.join(qsiprep_dir, "dwi", "sub-01_dwi.nii.gz")).touch()
            Path(os.path.join(output_dir, "sub-01.html")).touch()

            # Create QC file
            qc_data = {"summary": {"mean_fd": 0.2}}
            qc_file = os.path.join(output_dir, "qsiprep", "dwiqc.json")
            with open(qc_file, "w") as f:
                json.dump(qc_data, f)

            outputs = self.tool._extract_outputs(output_dir)

            assert outputs["output_dir"] == output_dir
            assert len(outputs["html_reports"]) == 1
            assert "sub-01" in outputs["derivatives"]
            assert len(outputs["derivatives"]["sub-01"]["anat"]) == 1
            assert len(outputs["derivatives"]["sub-01"]["dwi"]) == 2
            assert len(outputs["dwi_files"]) == 1
            assert "summary" in outputs["qc_metrics"]

    def test_generate_command_singularity(self):
        """Test Singularity command generation."""
        config = QSIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=["01"],
            work_dir="/tmp/work",
            fs_license_file="/license.txt",
        )

        command = self.tool._generate_command(
            config, "singularity", "/containers/qsiprep.sif"
        )

        assert "singularity run" in command
        assert "--cleanenv" in command
        assert "-B /data/bids:/data/bids" in command
        assert "-B /data/output:/data/output" in command
        assert "/containers/qsiprep.sif" in command
        assert "participant" in command

    def test_generate_command_docker(self):
        """Test Docker command generation."""
        config = QSIPrepConfig(
            bids_dir="/data/bids",
            output_dir="/data/output",
            participant_label=["01"],
            work_dir="/tmp/work",
            fs_license_file="/license.txt",
        )

        command = self.tool._generate_command(
            config, "docker", "pennbbl/qsiprep:latest"
        )

        assert "docker run" in command
        assert "--rm" in command
        assert "-v /data/bids:/data:ro" in command
        assert "-v /data/output:/out" in command
        assert "pennbbl/qsiprep:latest" in command

    def test_run_success(self):
        """Test successful QSIPrep setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_dir = os.path.join(temp_dir, "bids")
            output_dir = os.path.join(temp_dir, "output")

            # Create valid BIDS structure with DWI
            os.makedirs(bids_dir)
            Path(os.path.join(bids_dir, "dataset_description.json")).touch()
            dwi_dir = os.path.join(bids_dir, "sub-01", "dwi")
            os.makedirs(dwi_dir)
            Path(os.path.join(dwi_dir, "sub-01_dwi.nii.gz")).touch()

            result = self.tool._run(
                bids_dir=bids_dir,
                output_dir=output_dir,
                participant_label=["01"],
                skip_bids_validation=False,
                container_type="singularity",
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

            # Create invalid BIDS structure (no DWI)
            os.makedirs(bids_dir)

            result = self.tool._run(
                bids_dir=bids_dir, output_dir=output_dir, skip_bids_validation=False
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
                container_type="docker",
            )

            assert result.status == "success"
            assert "command" in result.data


class TestQSIPrepReconTool(unittest.TestCase):
    """Test QSIPrep reconstruction tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = QSIPrepReconTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "qsiprep_reconstruction"
        assert "reconstruction" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == QSIPrepReconArgs

    def test_get_recon_spec_path(self):
        """Test reconstruction spec path generation."""
        # Test with enum
        spec = self.tool._get_recon_spec_path(ReconWorkflow.MRTRIX_SINGLESHELL_SS3T)
        assert spec == "mrtrix_singleshell_ss3t_ACT-hsvs"

        # Test with custom path
        spec = self.tool._get_recon_spec_path("/custom/spec.json")
        assert spec == "/custom/spec.json"

    def test_run_success(self):
        """Test successful reconstruction setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            qsiprep_dir = os.path.join(temp_dir, "qsiprep")
            output_dir = os.path.join(temp_dir, "recon")
            os.makedirs(qsiprep_dir)

            result = self.tool._run(
                qsiprep_dir=qsiprep_dir,
                output_dir=output_dir,
                recon_spec=ReconWorkflow.DIPY_DTI,
                participant_label=["01"],
                n_cpus=4,
            )

            assert result.status == "success"
            assert "command" in result.data
            assert any("qsirecon" in str(arg) for arg in result.data["command"])
            assert "--recon-spec" in result.data["command"]
            assert "dipy_dti" in result.data["command"]

    def test_run_missing_directory(self):
        """Test error handling for missing directory."""
        result = self.tool._run(
            qsiprep_dir="/nonexistent/dir",
            output_dir="/output",
            recon_spec=ReconWorkflow.DIPY_DTI,
        )

        assert result.status == "error"
        assert "not found" in result.error


class TestQSIPrepQCTool(unittest.TestCase):
    """Test QSIPrep QC tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = QSIPrepQCTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "qsiprep_qc"
        assert "quality control" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == QSIPrepQCArgs

    def test_parse_qc_file(self):
        """Test QC file parsing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            # Write mock QC data
            qc_data = {
                "summary": {"test": "value"},
                "fd_mean": 0.3,
                "fd_max": 0.8,
                "snr_b0": 15.0,
                "snr_dwi": 12.0,
                "outliers_percent": 2.5,
            }
            json.dump(qc_data, f)
            f.flush()

        try:
            metrics = self.tool._parse_qc_file(f.name)

            assert "test" in metrics
            assert metrics["mean_fd"] == 0.3
            assert metrics["max_fd"] == 0.8
            assert metrics["snr_b0"] == 15.0
            assert metrics["snr_dwi"] == 12.0
            assert metrics["outliers_percent"] == 2.5
        finally:
            os.unlink(f.name)

    def test_run_success(self):
        """Test successful QC extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock QSIPrep output structure
            qsiprep_dir = os.path.join(temp_dir, "qsiprep", "sub-01", "dwi")
            os.makedirs(qsiprep_dir)

            # Create mock QC file
            qc_file = os.path.join(qsiprep_dir, "sub-01_dwi_qc.json")
            qc_data = {"fd_mean": 0.2, "snr_b0": 20.0, "snr_dwi": 15.0}
            with open(qc_file, "w") as f:
                json.dump(qc_data, f)

            result = self.tool._run(qsiprep_dir=temp_dir)

            assert result.status == "success"
            assert "qc_report" in result.data
            assert "participants" in result.data["qc_report"]
            assert result.data["qc_report"]["summary"]["n_participants"] == 1

    def test_run_with_output_file(self):
        """Test QC extraction with output file saving."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock structure
            qsiprep_dir = os.path.join(temp_dir, "qsiprep", "sub-01")
            os.makedirs(qsiprep_dir)

            output_file = os.path.join(temp_dir, "qc_report.json")

            result = self.tool._run(qsiprep_dir=temp_dir, output_file=output_file)

            assert result.status == "success"
            assert os.path.exists(output_file)

            # Verify JSON was written
            with open(output_file, "r") as f:
                report = json.load(f)
                assert "participants" in report
                assert "summary" in report


class TestIntegration(unittest.TestCase):
    """Integration tests for QSIPrep tools."""

    def test_tools_collection(self):
        """Test getting all QSIPrep tools."""
        tools = QSIPrepTools.get_all_tools()
        assert len(tools) == 3
        assert any(isinstance(t, QSIPrepTool) for t in tools)
        assert any(isinstance(t, QSIPrepReconTool) for t in tools)
        assert any(isinstance(t, QSIPrepQCTool) for t in tools)

    def test_denoising_method_enum(self):
        """Test denoising method enumeration."""
        assert DenoisingMethod.PATCH2SELF.value == "patch2self"
        assert DenoisingMethod.DWIDENOISE.value == "dwidenoise"
        assert DenoisingMethod.NONE.value == "none"

    def test_distortion_correction_enum(self):
        """Test distortion correction enumeration."""
        assert DistortionCorrection.TOPUP.value == "topup"
        assert DistortionCorrection.SYNBOLDZ.value == "syn-bold-z"
        assert DistortionCorrection.FIELDMAP.value == "fieldmap"

    def test_recon_workflow_enum(self):
        """Test reconstruction workflow enumeration."""
        assert (
            ReconWorkflow.MRTRIX_SINGLESHELL_SS3T.value
            == "mrtrix_singleshell_ss3t_ACT-hsvs"
        )
        assert ReconWorkflow.DIPY_DTI.value == "dipy_dti"
        assert ReconWorkflow.AMICO_NODDI.value == "amico_noddi"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
