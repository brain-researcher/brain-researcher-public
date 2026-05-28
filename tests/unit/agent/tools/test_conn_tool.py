"""
Tests for CONN functional connectivity tool implementation.
"""

import os
import tempfile
import unittest
from pathlib import Path

import pytest

from brain_researcher.services.tools.conn_tool import (
    AtlasType,
    CONNConfig,
    CONNConnectivityArgs,
    CONNConnectivityTool,
    ConnectivityMeasure,
    CONNGraphTheoryArgs,
    CONNGraphTheoryTool,
    CONNGroupAnalysisArgs,
    CONNGroupAnalysisTool,
    CONNPreprocessingArgs,
    CONNPreprocessingTool,
    CONNTools,
    DenoisingStrategy,
    GraphMetric,
)


class TestCONNConfig(unittest.TestCase):
    """Test CONN configuration."""

    def test_config_creation(self):
        """Test configuration is created correctly."""
        config = CONNConfig(
            project_dir="/data/conn_project",
            matlab_path="/usr/local/MATLAB/R2023b/bin/matlab",
            n_parallel=4,
            memory_gb=16,
        )

        assert config.project_dir == "/data/conn_project"
        assert config.matlab_path == "/usr/local/MATLAB/R2023b/bin/matlab"
        assert config.n_parallel == 4
        assert config.memory_gb == 16

    def test_matlab_command(self):
        """Test MATLAB command generation."""
        config = CONNConfig(project_dir="/data/conn")
        cmd = config.get_matlab_command()

        assert cmd[0] == "/usr/local/MATLAB/R2023b/bin/matlab"
        assert "-nodisplay" in cmd
        assert "-nosplash" in cmd
        assert "-nodesktop" in cmd
        assert "-r" in cmd

    def test_setup_script(self):
        """Test MATLAB setup script generation."""
        config = CONNConfig(
            project_dir="/data/conn", conn_path="/opt/conn", spm_path="/opt/spm12"
        )

        setup = config.get_setup_script()
        assert "addpath('/opt/conn')" in setup
        assert "addpath('/opt/spm12')" in setup
        assert "conn_module('load')" in setup


class TestCONNPreprocessingTool(unittest.TestCase):
    """Test CONN preprocessing tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = CONNPreprocessingTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "conn_preprocessing"
        assert "preprocessing pipeline" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == CONNPreprocessingArgs

    def test_run_basic_preprocessing(self):
        """Test basic preprocessing execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock functional and structural files
            func_file = os.path.join(temp_dir, "func.nii.gz")
            struct_file = os.path.join(temp_dir, "struct.nii.gz")
            Path(func_file).touch()
            Path(struct_file).touch()

            output_dir = os.path.join(temp_dir, "output")

            result = self.tool._run(
                func_files=[func_file],
                structural_file=struct_file,
                output_dir=output_dir,
                tr=2.0,
            )

            assert result.status == "success"
            assert result.data["n_subjects"] == 1
            assert result.data["n_sessions"] == 1
            assert result.data["preprocessing_steps"]["smoothing"] == "6.0mm"

            # Check script file was created
            script_file = Path(result.data["script_file"])
            assert script_file.exists()
            script_content = script_file.read_text()
            assert "CONN Preprocessing Script" in script_content
            assert "CONN_x.Setup.RT = 2.0" in script_content

    def test_run_with_slice_timing(self):
        """Test preprocessing with slice timing correction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            func_file = os.path.join(temp_dir, "func.nii.gz")
            struct_file = os.path.join(temp_dir, "struct.nii.gz")
            Path(func_file).touch()
            Path(struct_file).touch()

            result = self.tool._run(
                func_files=[func_file],
                structural_file=struct_file,
                output_dir=temp_dir,
                tr=2.0,
                slice_order=[1, 3, 5, 2, 4, 6],
            )

            assert result.status == "success"
            script_file = Path(result.data["script_file"])
            script_content = script_file.read_text()
            assert "functional_slicetime" in script_content
            assert "sliceorder = [1, 3, 5, 2, 4, 6]" in script_content

    def test_run_with_denoising_options(self):
        """Test preprocessing with various denoising strategies."""
        with tempfile.TemporaryDirectory() as temp_dir:
            func_file = os.path.join(temp_dir, "func.nii.gz")
            struct_file = os.path.join(temp_dir, "struct.nii.gz")
            Path(func_file).touch()
            Path(struct_file).touch()

            result = self.tool._run(
                func_files=[func_file],
                structural_file=struct_file,
                output_dir=temp_dir,
                tr=2.0,
                denoising=["CompCor", "motion", "scrubbing", "gsr"],
                bandpass=[0.01, 0.1],
                fd_threshold=0.3,
            )

            assert result.status == "success"
            assert result.data["preprocessing_steps"]["denoising"] == [
                "CompCor",
                "motion",
                "scrubbing",
                "gsr",
            ]
            assert result.data["preprocessing_steps"]["bandpass"] == [0.01, 0.1]
            assert result.data["preprocessing_steps"]["fd_threshold"] == 0.3

            script_file = Path(result.data["script_file"])
            script_content = script_file.read_text()
            assert "White Matter" in script_content
            assert "Motion" in script_content
            assert "scrubbing" in script_content
            assert "Global Signal" in script_content
            assert "0.01 0.1" in script_content

    def test_run_multiple_sessions(self):
        """Test preprocessing with multiple functional runs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create multiple functional files
            func_files = []
            for i in range(3):
                func_file = os.path.join(temp_dir, f"func_{i}.nii.gz")
                Path(func_file).touch()
                func_files.append(func_file)

            struct_file = os.path.join(temp_dir, "struct.nii.gz")
            Path(struct_file).touch()

            result = self.tool._run(
                func_files=func_files,
                structural_file=struct_file,
                output_dir=temp_dir,
                tr=2.0,
            )

            assert result.status == "success"
            assert result.data["n_sessions"] == 3

    def test_run_missing_files(self):
        """Test error handling for missing files."""
        result = self.tool._run(
            func_files=["/nonexistent/func.nii.gz"],
            structural_file="/nonexistent/struct.nii.gz",
            output_dir="/tmp",
            tr=2.0,
        )

        assert result.status == "error"
        assert "not found" in result.error


class TestCONNConnectivityTool(unittest.TestCase):
    """Test CONN connectivity analysis tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = CONNConnectivityTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "conn_connectivity"
        assert "connectivity analysis" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == CONNConnectivityArgs

    def test_run_roi_to_roi_analysis(self):
        """Test ROI-to-ROI connectivity analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock project file
            project_file = os.path.join(temp_dir, "conn_project.mat")
            Path(project_file).touch()

            output_dir = os.path.join(temp_dir, "output")

            result = self.tool._run(
                project_file=project_file,
                output_dir=output_dir,
                analysis_type="roi_to_roi",
                atlas="aal",
                measure="correlation",
            )

            assert result.status == "success"
            assert result.data["analysis_type"] == "roi_to_roi"
            assert result.data["atlas"] == "aal"
            assert result.data["measure"] == "correlation"

            # Check script file
            script_file = Path(result.data["script_file"])
            assert script_file.exists()
            script_content = script_file.read_text()
            assert "CONN Connectivity Analysis Script" in script_content
            assert "conn_dir('rois/aal.nii')" in script_content
            assert "Analysis.type = 'roi_to_roi'" in script_content
            assert "feature_contract.json" in script_content
            assert "feature_contract" in result.data["output_files"]

    def test_run_seed_to_voxel_analysis(self):
        """Test seed-to-voxel connectivity analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = os.path.join(temp_dir, "conn_project.mat")
            Path(project_file).touch()

            # Create mock seed files
            seed_files = []
            for i in range(2):
                seed_file = os.path.join(temp_dir, f"seed_{i}.nii")
                Path(seed_file).touch()
                seed_files.append(seed_file)

            result = self.tool._run(
                project_file=project_file,
                output_dir=temp_dir,
                analysis_type="seed_to_voxel",
                seeds=seed_files,
                measure="partial_correlation",
            )

            assert result.status == "success"
            assert result.data["analysis_type"] == "seed_to_voxel"

            script_file = Path(result.data["script_file"])
            script_content = script_file.read_text()
            assert "seed_to_voxel" in script_content
            assert "Export seed maps" in script_content

    def test_run_with_task_conditions(self):
        """Test connectivity with task modulation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = os.path.join(temp_dir, "conn_project.mat")
            Path(project_file).touch()

            result = self.tool._run(
                project_file=project_file,
                output_dir=temp_dir,
                task_conditions=["rest", "task1", "task2"],
            )

            assert result.status == "success"
            script_file = Path(result.data["script_file"])
            script_content = script_file.read_text()
            assert "Task conditions" in script_content
            assert "'rest'" in script_content
            assert "'task1'" in script_content

    def test_run_dynamic_connectivity(self):
        """Test dynamic connectivity analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = os.path.join(temp_dir, "conn_project.mat")
            Path(project_file).touch()

            result = self.tool._run(
                project_file=project_file, output_dir=temp_dir, dynamic_window=30
            )

            assert result.status == "success"
            assert result.data["dynamic"] is True

            script_file = Path(result.data["script_file"])
            script_content = script_file.read_text()
            assert "Dynamic connectivity" in script_content
            assert "Analysis.window = 30" in script_content

    def test_different_atlases(self):
        """Test different atlas options."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = os.path.join(temp_dir, "conn_project.mat")
            Path(project_file).touch()

            # Test Harvard-Oxford atlas
            result = self.tool._run(
                project_file=project_file, output_dir=temp_dir, atlas="harvard_oxford"
            )

            assert result.status == "success"
            script_content = Path(result.data["script_file"]).read_text()
            assert "harvard-oxford.nii" in script_content

            # Test Schaefer atlas
            result = self.tool._run(
                project_file=project_file, output_dir=temp_dir, atlas="schaefer"
            )

            assert result.status == "success"
            script_content = Path(result.data["script_file"]).read_text()
            assert "schaefer_400.nii" in script_content

    def test_connectivity_measures(self):
        """Test different connectivity measures."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = os.path.join(temp_dir, "conn_project.mat")
            Path(project_file).touch()

            measures = [
                "correlation",
                "partial_correlation",
                "regression",
                "ppi",
                "granger",
            ]

            for measure in measures:
                result = self.tool._run(
                    project_file=project_file, output_dir=temp_dir, measure=measure
                )

                assert result.status == "success"
                assert result.data["measure"] == measure

    def test_run_missing_project(self):
        """Test error handling for missing project file."""
        result = self.tool._run(
            project_file="/nonexistent/project.mat", output_dir="/tmp"
        )

        assert result.status == "error"
        assert "Project file not found" in result.error


class TestCONNGraphTheoryTool(unittest.TestCase):
    """Test CONN graph theory analysis tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = CONNGraphTheoryTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "conn_graph_theory"
        assert "graph theory metrics" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == CONNGraphTheoryArgs

    def test_run_basic_graph_analysis(self):
        """Test basic graph theory analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock connectivity matrix file
            matrix_file = os.path.join(temp_dir, "connectivity.mat")
            Path(matrix_file).touch()

            output_dir = os.path.join(temp_dir, "output")

            result = self.tool._run(
                connectivity_matrix=matrix_file,
                output_dir=output_dir,
                metrics=["degree", "clustering", "efficiency"],
            )

            assert result.status == "success"
            assert result.data["metrics"] == ["degree", "clustering", "efficiency"]
            assert result.data["weighted"] is True

            # Check script file
            script_file = Path(result.data["script_file"])
            assert script_file.exists()
            script_content = script_file.read_text()
            assert "CONN Graph Theory Analysis Script" in script_content
            assert "Brain Connectivity Toolbox" in script_content
            assert "Degree" in script_content
            assert "Clustering coefficient" in script_content
            assert "efficiency" in script_content

    def test_run_with_threshold(self):
        """Test graph analysis with threshold."""
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix_file = os.path.join(temp_dir, "connectivity.mat")
            Path(matrix_file).touch()

            result = self.tool._run(
                connectivity_matrix=matrix_file, output_dir=temp_dir, threshold=0.3
            )

            assert result.status == "success"
            assert result.data["threshold"] == 0.3

            script_content = Path(result.data["script_file"]).read_text()
            assert "threshold = 0.3" in script_content
            assert "W(abs(W) < threshold) = 0" in script_content

    def test_run_with_density(self):
        """Test graph analysis with density threshold."""
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix_file = os.path.join(temp_dir, "connectivity.mat")
            Path(matrix_file).touch()

            result = self.tool._run(
                connectivity_matrix=matrix_file, output_dir=temp_dir, density=0.1
            )

            assert result.status == "success"
            assert result.data["density"] == 0.1

            script_content = Path(result.data["script_file"]).read_text()
            assert "density = 0.1" in script_content
            assert "threshold_proportional" in script_content

    def test_run_binary_graph(self):
        """Test binary graph analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix_file = os.path.join(temp_dir, "connectivity.mat")
            Path(matrix_file).touch()

            result = self.tool._run(
                connectivity_matrix=matrix_file,
                output_dir=temp_dir,
                weighted=False,
                metrics=["degree", "clustering"],
            )

            assert result.status == "success"
            assert result.data["weighted"] is False

            script_content = Path(result.data["script_file"]).read_text()
            assert "weight_conversion(W, 'binarize')" in script_content
            assert "degrees_und" in script_content
            assert "clustering_coef_bu" in script_content

    def test_all_metrics(self):
        """Test all available graph metrics."""
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix_file = os.path.join(temp_dir, "connectivity.mat")
            Path(matrix_file).touch()

            all_metrics = [
                "degree",
                "betweenness",
                "clustering",
                "path_length",
                "efficiency",
                "modularity",
                "centrality",
            ]

            result = self.tool._run(
                connectivity_matrix=matrix_file,
                output_dir=temp_dir,
                metrics=all_metrics,
            )

            assert result.status == "success"
            assert result.data["metrics"] == all_metrics

            script_content = Path(result.data["script_file"]).read_text()
            assert "Betweenness centrality" in script_content
            assert "Characteristic path length" in script_content
            assert "Modularity" in script_content
            assert "Eigenvector centrality" in script_content

    def test_run_missing_matrix(self):
        """Test error handling for missing connectivity matrix."""
        result = self.tool._run(
            connectivity_matrix="/nonexistent/matrix.mat", output_dir="/tmp"
        )

        assert result.status == "error"
        assert "Connectivity matrix not found" in result.error


class TestCONNGroupAnalysisTool(unittest.TestCase):
    """Test CONN group-level analysis tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = CONNGroupAnalysisTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "conn_group_analysis"
        assert "group-level connectivity" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == CONNGroupAnalysisArgs

    def test_run_basic_group_analysis(self):
        """Test basic group analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock project files for multiple subjects
            project_files = []
            for i in range(4):
                proj_file = os.path.join(temp_dir, f"subject_{i}.mat")
                Path(proj_file).touch()
                project_files.append(proj_file)

            output_dir = os.path.join(temp_dir, "group_output")

            result = self.tool._run(
                project_files=project_files,
                output_dir=output_dir,
                contrast={"control": 1, "patient": -1},
                correction="fdr",
                threshold=0.05,
            )

            assert result.status == "success"
            assert result.data["n_subjects"] == 4
            assert result.data["contrast"] == {"control": 1, "patient": -1}
            assert result.data["correction"] == "fdr"
            assert result.data["threshold"] == 0.05

            # Check script file
            script_file = Path(result.data["script_file"])
            assert script_file.exists()
            script_content = script_file.read_text()
            assert "CONN Group Analysis Script" in script_content
            assert "n_subjects = 4" in script_content
            assert "'control', 'patient'" in script_content

    def test_run_with_covariates(self):
        """Test group analysis with covariates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_files = []
            for i in range(4):
                proj_file = os.path.join(temp_dir, f"subject_{i}.mat")
                Path(proj_file).touch()
                project_files.append(proj_file)

            result = self.tool._run(
                project_files=project_files,
                output_dir=temp_dir,
                contrast={"group1": 1, "group2": -1},
                covariates={"age": [25, 30, 35, 40], "motion": [0.1, 0.2, 0.15, 0.12]},
            )

            assert result.status == "success"
            script_content = Path(result.data["script_file"]).read_text()
            assert "Add covariates" in script_content
            assert "'age'" in script_content
            assert "'motion'" in script_content
            assert "[25, 30, 35, 40]" in script_content

    def test_different_corrections(self):
        """Test different multiple comparison corrections."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_files = []
            for i in range(2):
                proj_file = os.path.join(temp_dir, f"subject_{i}.mat")
                Path(proj_file).touch()
                project_files.append(proj_file)

            corrections = ["fdr", "bonferroni", "none"]

            for correction in corrections:
                result = self.tool._run(
                    project_files=project_files,
                    output_dir=temp_dir,
                    contrast={"group1": 1, "group2": -1},
                    correction=correction,
                )

                assert result.status == "success"
                assert result.data["correction"] == correction

                script_content = Path(result.data["script_file"]).read_text()
                assert f"Results.correction', '{correction}'" in script_content

    def test_run_missing_projects(self):
        """Test error handling for missing project files."""
        result = self.tool._run(
            project_files=["/nonexistent/proj1.mat", "/nonexistent/proj2.mat"],
            output_dir="/tmp",
            contrast={"group1": 1, "group2": -1},
        )

        assert result.status == "error"
        assert "Project file not found" in result.error


class TestEnumValues(unittest.TestCase):
    """Test enum value definitions."""

    def test_connectivity_measure_enum(self):
        """Test ConnectivityMeasure enum values."""
        assert ConnectivityMeasure.CORRELATION == "correlation"
        assert ConnectivityMeasure.PARTIAL_CORRELATION == "partial_correlation"
        assert ConnectivityMeasure.REGRESSION == "regression"
        assert ConnectivityMeasure.PPI == "ppi"
        assert ConnectivityMeasure.GRANGER == "granger"

    def test_graph_metric_enum(self):
        """Test GraphMetric enum values."""
        assert GraphMetric.DEGREE == "degree"
        assert GraphMetric.BETWEENNESS == "betweenness"
        assert GraphMetric.CLUSTERING == "clustering"
        assert GraphMetric.PATH_LENGTH == "path_length"
        assert GraphMetric.EFFICIENCY == "efficiency"
        assert GraphMetric.MODULARITY == "modularity"
        assert GraphMetric.CENTRALITY == "centrality"

    def test_denoising_strategy_enum(self):
        """Test DenoisingStrategy enum values."""
        assert DenoisingStrategy.COMPCOR == "CompCor"
        assert DenoisingStrategy.ACOMPCOR == "aCompCor"
        assert DenoisingStrategy.TCOMPCOR == "tCompCor"
        assert DenoisingStrategy.MOTION == "motion"
        assert DenoisingStrategy.SCRUBBING == "scrubbing"
        assert DenoisingStrategy.GSR == "gsr"

    def test_atlas_type_enum(self):
        """Test AtlasType enum values."""
        assert AtlasType.AAL == "aal"
        assert AtlasType.HARVARD_OXFORD == "harvard_oxford"
        assert AtlasType.SCHAEFER == "schaefer"
        assert AtlasType.GORDON == "gordon"
        assert AtlasType.POWER == "power"
        assert AtlasType.DOSENBACH == "dosenbach"
        assert AtlasType.CUSTOM == "custom"


class TestIntegration(unittest.TestCase):
    """Integration tests for CONN tools."""

    def test_tools_collection(self):
        """Test getting all CONN tools."""
        tools = CONNTools.get_all_tools()

        assert len(tools) == 4
        assert any(isinstance(t, CONNPreprocessingTool) for t in tools)
        assert any(isinstance(t, CONNConnectivityTool) for t in tools)
        assert any(isinstance(t, CONNGraphTheoryTool) for t in tools)
        assert any(isinstance(t, CONNGroupAnalysisTool) for t in tools)

    def test_tool_names_unique(self):
        """Test that all tool names are unique."""
        tools = CONNTools.get_all_tools()
        names = [t.get_tool_name() for t in tools]

        assert len(names) == len(set(names))

    def test_all_tools_inherit_base(self):
        """Test all tools inherit from NeuroKGToolWrapper."""
        from brain_researcher.services.tools.tool_base import NeuroKGToolWrapper

        tools = CONNTools.get_all_tools()
        for tool in tools:
            assert isinstance(tool, NeuroKGToolWrapper)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
