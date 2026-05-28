"""
Tests for XCP-D tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import pytest

from brain_researcher.services.tools.xcpd_tool import (
    DenoisingStrategy,
    OutputType,
    Parcellation,
    SmoothingKernel,
    XCPDArgs,
    XCPDConfig,
    XCPDConnectivityArgs,
    XCPDConnectivityTool,
    XCPDQCArgs,
    XCPDQCTool,
    XCPDTool,
    XCPDTools,
)


class TestXCPDConfig(unittest.TestCase):
    """Test XCP-D configuration generation."""

    def setUp(self):
        """Set up test configuration."""
        self.config = XCPDConfig(
            fmriprep_dir="/data/fmriprep",
            output_dir="/data/xcpd",
            participant_label=["01", "02"],
            work_dir="/tmp/work",
            denoising_strategy=DenoisingStrategy.MODERATE,
            parcellation=Parcellation.SCHAEFER_200,
            smoothing=SmoothingKernel.MEDIUM,
            fd_threshold=0.5,
            despike=True,
            bandpass_filter=(0.01, 0.1),
            cifti=False,
            n_cpus=8,
            mem_gb=16,
        )

    def test_config_creation(self):
        """Test configuration is created correctly."""
        assert self.config.fmriprep_dir == "/data/fmriprep"
        assert self.config.output_dir == "/data/xcpd"
        assert self.config.participant_label == ["01", "02"]
        assert self.config.work_dir == "/tmp/work"
        assert self.config.denoising_strategy == DenoisingStrategy.MODERATE
        assert self.config.parcellation == Parcellation.SCHAEFER_200
        assert self.config.smoothing == SmoothingKernel.MEDIUM
        assert self.config.fd_threshold == 0.5

    def test_command_args_generation(self):
        """Test command argument generation."""
        args = self.config.to_command_args()

        # Check key arguments
        assert "/data/fmriprep" in args
        assert "/data/xcpd" in args
        assert "participant" in args
        assert "--participant-label" in args
        assert "01" in args
        assert "02" in args
        assert "-w" in args
        assert "/tmp/work" in args
        assert "--nuisance-regressors" in args
        assert "36P" in args
        assert "--atlases" in args
        assert "Schaefer2018_200Parcels_7Networks" in args
        assert "--smoothing" in args
        assert "6" in args
        assert "--fd-thresh" in args
        assert "0.5" in args
        assert "--despike" in args
        assert "--lower-bpf" in args
        assert "0.01" in args
        assert "--upper-bpf" in args
        assert "0.1" in args
        assert "--nprocs" in args
        assert "8" in args
        assert "--mem-gb" in args
        assert "16" in args
        assert "--notrack" in args

    def test_minimal_config(self):
        """Test minimal configuration."""
        config = XCPDConfig(
            fmriprep_dir="/data/fmriprep",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
        )
        args = config.to_command_args()

        assert "/data/fmriprep" in args
        assert "/data/output" in args
        assert "--participant-label" not in args
        assert "-w" not in args

    def test_no_bandpass_filter(self):
        """Test configuration without bandpass filter."""
        config = XCPDConfig(
            fmriprep_dir="/data/fmriprep",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            bandpass_filter=None,
        )
        args = config.to_command_args()

        assert "--disable-bandpass-filter" in args
        assert "--lower-bpf" not in args
        assert "--upper-bpf" not in args

    def test_minimal_denoising(self):
        """Test minimal denoising strategy."""
        config = XCPDConfig(
            fmriprep_dir="/data/fmriprep",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            denoising_strategy=DenoisingStrategy.MINIMAL,
        )
        args = config.to_command_args()

        assert "--nuisance-regressors" in args
        assert "24P" in args

    def test_cifti_processing(self):
        """Test CIFTI processing configuration."""
        config = XCPDConfig(
            fmriprep_dir="/data/fmriprep",
            output_dir="/data/output",
            participant_label=None,
            work_dir=None,
            cifti=True,
        )
        args = config.to_command_args()

        assert "--cifti" in args


class TestXCPDTool(unittest.TestCase):
    """Test XCP-D post-processing tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = XCPDTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "xcpd_postprocessing"
        assert "post-process" in self.tool.get_tool_description().lower()
        assert "connectivity" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == XCPDArgs

    def test_validate_fmriprep_outputs_valid(self):
        """Test fMRIPrep output validation with valid data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create valid fMRIPrep structure
            Path(os.path.join(temp_dir, "dataset_description.json")).touch()

            # Create participant with functional data
            func_dir = os.path.join(temp_dir, "sub-01", "func")
            os.makedirs(func_dir)
            Path(
                os.path.join(func_dir, "sub-01_task-rest_desc-preproc_bold.nii.gz")
            ).touch()
            Path(
                os.path.join(func_dir, "sub-01_task-rest_desc-confounds_timeseries.tsv")
            ).touch()

            # Create anatomical data
            anat_dir = os.path.join(temp_dir, "sub-01", "anat")
            os.makedirs(anat_dir)
            Path(os.path.join(anat_dir, "sub-01_desc-preproc_T1w.nii.gz")).touch()

            validation = self.tool._validate_fmriprep_outputs(temp_dir)

            assert validation["is_valid"] is True
            assert validation["has_func"] is True
            assert validation["has_anat"] is True
            assert "01" in validation["participants"]
            assert len(validation["func_files"]) > 0
            assert len(validation["issues"]) == 0

    def test_validate_fmriprep_outputs_no_func(self):
        """Test fMRIPrep validation without functional data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create structure without functional data
            Path(os.path.join(temp_dir, "dataset_description.json")).touch()
            os.makedirs(os.path.join(temp_dir, "sub-01", "anat"))

            validation = self.tool._validate_fmriprep_outputs(temp_dir)

            assert validation["is_valid"] is False
            assert validation["has_func"] is False
            assert "No preprocessed functional files found" in validation["issues"]

    def test_extract_outputs(self):
        """Test output extraction from XCP-D directory."""
        with tempfile.TemporaryDirectory() as output_dir:
            # Create mock XCP-D output structure
            xcp_dir = os.path.join(output_dir, "xcp_d", "sub-01", "func")
            os.makedirs(xcp_dir)

            # Create mock files
            Path(
                os.path.join(xcp_dir, "sub-01_task-rest_desc-denoised_bold.nii.gz")
            ).touch()
            Path(
                os.path.join(
                    xcp_dir, "sub-01_task-rest_atlas-Schaefer200_connectivity.tsv"
                )
            ).touch()
            Path(
                os.path.join(
                    xcp_dir, "sub-01_task-rest_atlas-Schaefer200_timeseries.tsv"
                )
            ).touch()
            Path(os.path.join(output_dir, "sub-01_qc.json")).touch()
            Path(os.path.join(output_dir, "sub-01.html")).touch()

            outputs = self.tool._extract_outputs(output_dir)

            assert outputs["output_dir"] == output_dir
            assert "sub-01" in outputs["connectivity"]
            assert len(outputs["connectivity"]["sub-01"]["matrices"]) == 1
            assert len(outputs["connectivity"]["sub-01"]["timeseries"]) == 1
            assert len(outputs["denoised"]["sub-01"]) == 1
            assert len(outputs["qc_files"]) == 1
            assert len(outputs["reports"]) == 1

    def test_generate_command_singularity(self):
        """Test Singularity command generation."""
        config = XCPDConfig(
            fmriprep_dir="/data/fmriprep",
            output_dir="/data/output",
            participant_label=["01"],
            work_dir="/tmp/work",
            denoising_strategy=DenoisingStrategy.MODERATE,
        )

        command = self.tool._generate_command(
            config, "singularity", "/containers/xcp_d.sif"
        )

        assert "singularity run" in command
        assert "--cleanenv" in command
        assert "-B /data/fmriprep:/data/fmriprep" in command
        assert "-B /data/output:/data/output" in command
        assert "/containers/xcp_d.sif" in command
        assert "participant" in command

    def test_generate_command_docker(self):
        """Test Docker command generation."""
        config = XCPDConfig(
            fmriprep_dir="/data/fmriprep",
            output_dir="/data/output",
            participant_label=["01"],
            work_dir="/tmp/work",
        )

        command = self.tool._generate_command(config, "docker", "pennlinc/xcp_d:latest")

        assert "docker run" in command
        assert "--rm" in command
        assert "-v /data/fmriprep:/data:ro" in command
        assert "-v /data/output:/out" in command
        assert "pennlinc/xcp_d:latest" in command

    def test_run_success(self):
        """Test successful XCP-D setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fmriprep_dir = os.path.join(temp_dir, "fmriprep")
            output_dir = os.path.join(temp_dir, "output")

            # Create valid fMRIPrep structure
            os.makedirs(fmriprep_dir)
            Path(os.path.join(fmriprep_dir, "dataset_description.json")).touch()
            func_dir = os.path.join(fmriprep_dir, "sub-01", "func")
            os.makedirs(func_dir)
            Path(
                os.path.join(func_dir, "sub-01_task-rest_desc-preproc_bold.nii.gz")
            ).touch()

            result = self.tool._run(
                fmriprep_dir=fmriprep_dir,
                output_dir=output_dir,
                participant_label=["01"],
                denoising_strategy=DenoisingStrategy.MODERATE,
                parcellation=Parcellation.SCHAEFER_200,
                container_type="singularity",
            )

            assert result.status == "success"
            assert "command" in result.data
            assert "config" in result.data
            assert result.data["config"]["fmriprep_dir"] == fmriprep_dir
            assert result.data["config"]["output_dir"] == output_dir
            assert result.data["config"]["denoising_strategy"] == "36P"

    def test_run_invalid_fmriprep(self):
        """Test error handling for invalid fMRIPrep directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fmriprep_dir = os.path.join(temp_dir, "fmriprep")
            output_dir = os.path.join(temp_dir, "output")

            # Create invalid structure (no functional data)
            os.makedirs(fmriprep_dir)

            result = self.tool._run(fmriprep_dir=fmriprep_dir, output_dir=output_dir)

            assert result.status == "error"
            assert "Invalid fMRIPrep directory" in result.error

    def test_run_with_custom_parameters(self):
        """Test XCP-D with custom parameters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fmriprep_dir = os.path.join(temp_dir, "fmriprep")
            output_dir = os.path.join(temp_dir, "output")

            # Create valid structure
            os.makedirs(fmriprep_dir)
            Path(os.path.join(fmriprep_dir, "dataset_description.json")).touch()
            func_dir = os.path.join(fmriprep_dir, "sub-01", "func")
            os.makedirs(func_dir)
            Path(
                os.path.join(func_dir, "sub-01_task-rest_desc-preproc_bold.nii.gz")
            ).touch()

            result = self.tool._run(
                fmriprep_dir=fmriprep_dir,
                output_dir=output_dir,
                denoising_strategy=DenoisingStrategy.MINIMAL,
                smoothing=SmoothingKernel.LARGE,
                fd_threshold=0.3,
                despike=False,
                bandpass_filter=None,
                cifti=True,
            )

            assert result.status == "success"
            assert "--nuisance-regressors 24P" in result.data["command"]
            assert "--smoothing 8" in result.data["command"]
            assert "--fd-thresh 0.3" in result.data["command"]
            assert "--despike" not in result.data["command"]
            assert "--disable-bandpass-filter" in result.data["command"]
            assert "--cifti" in result.data["command"]


class TestXCPDConnectivityTool(unittest.TestCase):
    """Test XCP-D connectivity analysis tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = XCPDConnectivityTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "xcpd_connectivity_analysis"
        assert "connectivity" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == XCPDConnectivityArgs

    def test_load_connectivity_matrix(self):
        """Test connectivity matrix loading and analysis."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            # Write mock connectivity matrix
            f.write("ROI\tROI1\tROI2\tROI3\n")
            f.write("ROI1\t1.0\t0.5\t0.3\n")
            f.write("ROI2\t0.5\t1.0\t0.7\n")
            f.write("ROI3\t0.3\t0.7\t1.0\n")
            f.flush()

        try:
            matrix_data = self.tool._load_connectivity_matrix(f.name)

            assert "matrix" in matrix_data
            assert "labels" in matrix_data
            assert "metrics" in matrix_data
            assert matrix_data["metrics"]["n_nodes"] == 3
            assert "mean_connectivity" in matrix_data["metrics"]
            assert "hubs" in matrix_data["metrics"]
        finally:
            os.unlink(f.name)

    def test_run_success(self):
        """Test successful connectivity analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock XCP-D structure with connectivity matrices
            func_dir = os.path.join(temp_dir, "xcp_d", "sub-01", "func")
            os.makedirs(func_dir)

            # Create mock connectivity file
            conn_file = os.path.join(
                func_dir,
                "sub-01_atlas-Schaefer2018_200Parcels_7Networks_connectivity.tsv",
            )
            with open(conn_file, "w") as f:
                f.write("ROI\tROI1\tROI2\n")
                f.write("ROI1\t1.0\t0.5\n")
                f.write("ROI2\t0.5\t1.0\n")

            result = self.tool._run(
                xcpd_dir=temp_dir,
                parcellation=Parcellation.SCHAEFER_200,
                output_file=os.path.join(temp_dir, "connectivity_report.json"),
            )

            assert result.status == "success"
            assert "connectivity_report" in result.data
            assert result.data["connectivity_report"]["summary"]["n_participants"] == 1
            assert "sub-01" in result.data["connectivity_report"]["participants"]
            participant = result.data["connectivity_report"]["participants"]["sub-01"]
            assert os.path.exists(participant["feature_contract"])

    def test_run_missing_directory(self):
        """Test error handling for missing directory."""
        result = self.tool._run(
            xcpd_dir="/nonexistent/dir", parcellation=Parcellation.SCHAEFER_200
        )

        assert result.status == "error"
        assert "not found" in result.error


class TestXCPDQCTool(unittest.TestCase):
    """Test XCP-D QC tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = XCPDQCTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "xcpd_qc"
        assert "quality control" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == XCPDQCArgs

    def test_parse_qc_file_json(self):
        """Test QC file parsing for JSON format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            # Write mock QC data
            qc_data = {
                "mean_fd": 0.2,
                "n_censored": 10,
                "mean_dvars": 1.2,
                "tsnr": 45.0,
            }
            json.dump(qc_data, f)
            f.flush()

        try:
            metrics = self.tool._parse_qc_file(f.name)

            assert metrics["mean_fd"] == 0.2
            assert metrics["n_censored"] == 10
            assert metrics["mean_dvars"] == 1.2
            assert metrics["tsnr"] == 45.0
        finally:
            os.unlink(f.name)

    def test_parse_qc_file_tsv(self):
        """Test QC file parsing for TSV format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            # Write mock QC data
            f.write("mean_fd\tn_censored\tmean_dvars\n")
            f.write("0.3\t15\t1.5\n")
            f.flush()

        try:
            metrics = self.tool._parse_qc_file(f.name)

            assert metrics["mean_fd"] == 0.3
            assert metrics["n_censored"] == 15
            assert metrics["mean_dvars"] == 1.5
        finally:
            os.unlink(f.name)

    def test_run_success(self):
        """Test successful QC extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock XCP-D structure
            part_dir = os.path.join(temp_dir, "xcp_d", "sub-01", "func")
            os.makedirs(part_dir)

            # Create mock QC file
            qc_file = os.path.join(part_dir, "sub-01_task-rest_qc.json")
            qc_data = {"mean_fd": 0.25, "n_censored": 5, "mean_dvars": 1.1}
            with open(qc_file, "w") as f:
                json.dump(qc_data, f)

            result = self.tool._run(xcpd_dir=temp_dir)

            assert result.status == "success"
            assert "qc_report" in result.data
            assert result.data["qc_report"]["summary"]["n_participants"] == 1
            assert "sub-01" in result.data["qc_report"]["participants"]

    def test_run_with_output_file(self):
        """Test QC extraction with output file saving."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock structure
            part_dir = os.path.join(temp_dir, "xcp_d", "sub-01")
            os.makedirs(part_dir)

            output_file = os.path.join(temp_dir, "qc_report.json")

            result = self.tool._run(xcpd_dir=temp_dir, output_file=output_file)

            assert result.status == "success"
            assert os.path.exists(output_file)

            # Verify JSON was written
            with open(output_file) as f:
                report = json.load(f)
                assert "participants" in report
                assert "summary" in report


class TestIntegration(unittest.TestCase):
    """Integration tests for XCP-D tools."""

    def test_tools_collection(self):
        """Test getting all XCP-D tools."""
        tools = XCPDTools.get_all_tools()
        assert len(tools) == 3
        assert any(isinstance(t, XCPDTool) for t in tools)
        assert any(isinstance(t, XCPDConnectivityTool) for t in tools)
        assert any(isinstance(t, XCPDQCTool) for t in tools)

    def test_denoising_strategy_enum(self):
        """Test denoising strategy enumeration."""
        assert DenoisingStrategy.MINIMAL.value == "24P"
        assert DenoisingStrategy.MODERATE.value == "36P"
        assert DenoisingStrategy.AGGRESSIVE.value == "acompcor"
        assert DenoisingStrategy.AROMA.value == "aroma"

    def test_parcellation_enum(self):
        """Test parcellation enumeration."""
        assert Parcellation.SCHAEFER_100.value == "Schaefer2018_100Parcels_7Networks"
        assert Parcellation.SCHAEFER_200.value == "Schaefer2018_200Parcels_7Networks"
        assert Parcellation.SCHAEFER_400.value == "Schaefer2018_400Parcels_7Networks"
        assert Parcellation.GLASSER.value == "Glasser360"

    def test_smoothing_kernel_enum(self):
        """Test smoothing kernel enumeration."""
        assert SmoothingKernel.NONE.value == "0"
        assert SmoothingKernel.SMALL.value == "4"
        assert SmoothingKernel.MEDIUM.value == "6"
        assert SmoothingKernel.LARGE.value == "8"

    def test_output_type_enum(self):
        """Test output type enumeration."""
        assert OutputType.MINIMAL.value == "minimal"
        assert OutputType.FULL.value == "full"
        assert OutputType.DEBUG.value == "debug"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
