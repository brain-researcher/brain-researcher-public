"""
Tests for Nipype workflow engine tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.tools.nipype_tool import (
    DataGrabberType,
    InterfaceType,
    NipypeBIDSAppArgs,
    NipypeBIDSAppTool,
    NipypeConfig,
    NipypeDistributedArgs,
    NipypeDistributedTool,
    NipypeInterfaceWrapperArgs,
    NipypeInterfaceWrapperTool,
    NipypeTools,
    NipypeWorkflowBuilderArgs,
    NipypeWorkflowBuilderTool,
    WorkflowPlugin,
)


class TestNipypeConfig(unittest.TestCase):
    """Test Nipype configuration."""

    def test_config_creation(self):
        """Test configuration is created correctly."""
        config = NipypeConfig(
            working_dir="/data/nipype",
            crash_dir="/data/nipype/crash",
            plugin="MultiProc",
            plugin_args={"n_procs": 8}
        )

        assert config.working_dir == "/data/nipype"
        assert config.crash_dir == "/data/nipype/crash"
        assert config.plugin == "MultiProc"
        assert config.plugin_args == {"n_procs": 8}

    def test_config_dict(self):
        """Test configuration dictionary generation."""
        config = NipypeConfig(
            working_dir="/data/nipype",
            plugin="SLURM",
            stop_on_first_crash=True
        )

        config_dict = config.get_config_dict()

        assert config_dict["execution"]["plugin"] == "SLURM"
        assert config_dict["execution"]["stop_on_first_crash"] is True
        assert config_dict["logging"]["log_directory"] == "/data/nipype"
        assert "crashdump_dir" not in config_dict["execution"]  # No crash_dir set

    def test_default_values(self):
        """Test default configuration values."""
        config = NipypeConfig(working_dir="/data")

        assert config.plugin == "Linear"
        assert config.hash_method == "timestamp"
        assert config.keep_inputs is True
        assert config.use_relative_paths is True


class TestNipypeWorkflowBuilderTool(unittest.TestCase):
    """Test Nipype workflow builder tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = NipypeWorkflowBuilderTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "nipype_workflow_builder"
        assert "Build and configure Nipype workflows" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == NipypeWorkflowBuilderArgs

    def test_build_simple_workflow(self):
        """Test building a simple workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nodes = [
                {
                    "name": "input_node",
                    "fields": ["in_file", "mask_file"]
                },
                {
                    "name": "smooth_node",
                    "interface": {
                        "type": "fsl",
                        "name": "Smooth",
                        "params": {"fwhm": 6.0}
                    }
                },
                {
                    "name": "output_node",
                    "fields": ["smoothed_file"]
                }
            ]

            connections = [
                ("input_node", "in_file", "smooth_node", "in_file"),
                ("smooth_node", "smoothed_file", "output_node", "smoothed_file")
            ]

            result = self.tool._run(
                name="test_workflow",
                base_dir=temp_dir,
                nodes=nodes,
                connections=connections
            )

            assert result.status == "success"
            assert result.data["workflow_name"] == "test_workflow"
            assert result.data["n_nodes"] == 3
            assert result.data["n_connections"] == 2
            assert result.data["node_names"] == ["input_node", "smooth_node", "output_node"]

            # Check workflow file was created
            workflow_file = Path(result.data["workflow_file"])
            assert workflow_file.exists()
            workflow_content = workflow_file.read_text()
            assert "def create_test_workflow_workflow():" in workflow_content
            assert "pe.Workflow(name=\"test_workflow\")" in workflow_content

    def test_build_with_iterables(self):
        """Test building workflow with iterables."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nodes = [
                {
                    "name": "bet_node",
                    "interface": {
                        "type": "fsl",
                        "name": "BET",
                        "params": {}
                    },
                    "iterables": {
                        "field": "frac",
                        "values": [0.3, 0.4, 0.5, 0.6]
                    }
                }
            ]

            result = self.tool._run(
                name="iterables_workflow",
                base_dir=temp_dir,
                nodes=nodes
            )

            assert result.status == "success"
            workflow_content = Path(result.data["workflow_file"]).read_text()
            assert 'bet_node.iterables = ("frac", [0.3, 0.4, 0.5, 0.6])' in workflow_content

    def test_build_with_plugins(self):
        """Test building workflow with different plugins."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nodes = [{"name": "test_node", "fields": ["field1"]}]

            # Test MultiProc plugin
            result = self.tool._run(
                name="multiproc_wf",
                base_dir=temp_dir,
                nodes=nodes,
                plugin="MultiProc",
                plugin_args={"n_procs": 8, "memory_gb": 16}
            )

            assert result.status == "success"
            assert result.data["plugin"] == "MultiProc"
            workflow_content = Path(result.data["workflow_file"]).read_text()
            assert "plugin_args = {'n_procs': 8, 'memory_gb': 16}" in workflow_content

            # Test SLURM plugin
            result = self.tool._run(
                name="slurm_wf",
                base_dir=temp_dir,
                nodes=nodes,
                plugin="SLURM"
            )

            assert result.status == "success"
            assert result.data["plugin"] == "SLURM"

    def test_multiple_interface_types(self):
        """Test workflow with multiple interface types."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nodes = [
                {
                    "name": "fsl_node",
                    "interface": {"type": "fsl", "name": "BET"}
                },
                {
                    "name": "spm_node",
                    "interface": {"type": "spm", "name": "Smooth"}
                },
                {
                    "name": "fs_node",
                    "interface": {"type": "freesurfer", "name": "ReconAll"}
                }
            ]

            result = self.tool._run(
                name="multi_interface_wf",
                base_dir=temp_dir,
                nodes=nodes
            )

            assert result.status == "success"
            workflow_content = Path(result.data["workflow_file"]).read_text()
            assert "import nipype.interfaces.fsl as fsl" in workflow_content
            assert "import nipype.interfaces.spm as spm" in workflow_content
            assert "import nipype.interfaces.freesurfer as fs" in workflow_content


class TestNipypeBIDSAppTool(unittest.TestCase):
    """Test Nipype BIDS app tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = NipypeBIDSAppTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "nipype_bids_app"
        assert "BIDS-compatible Nipype pipelines" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == NipypeBIDSAppArgs

    def test_create_preprocessing_app(self):
        """Test creating preprocessing BIDS app."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_dir = os.path.join(temp_dir, "bids")
            output_dir = os.path.join(temp_dir, "output")
            Path(bids_dir).mkdir()

            result = self.tool._run(
                bids_dir=bids_dir,
                output_dir=output_dir,
                pipeline="preprocessing",
                fwhm=8.0,
                tr=2.5
            )

            assert result.status == "success"
            assert result.data["pipeline"] == "preprocessing"
            assert result.data["analysis_level"] == "participant"

            # Check app file
            app_file = Path(result.data["app_file"])
            assert app_file.exists()
            app_content = app_file.read_text()
            assert "def create_bids_preprocessing_workflow" in app_content
            assert "BIDSLayout" in app_content
            assert "fsl.MCFLIRT()" in app_content
            assert "smooth.inputs.fwhm = 8.0" in app_content

            # Check dataset description
            desc_file = Path(result.data["dataset_description"])
            assert desc_file.exists()
            desc_data = json.loads(desc_file.read_text())
            assert desc_data["Name"] == "Nipype BIDS Preprocessing Pipeline"

    def test_create_first_level_app(self):
        """Test creating first-level analysis BIDS app."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_dir = os.path.join(temp_dir, "bids")
            Path(bids_dir).mkdir()

            result = self.tool._run(
                bids_dir=bids_dir,
                output_dir=temp_dir,
                pipeline="first_level",
                task="stroop",
                participant_label=["01", "02"]
            )

            assert result.status == "success"
            assert result.data["pipeline"] == "first_level"
            assert result.data["participants"] == ["01", "02"]

            app_content = Path(result.data["app_file"]).read_text()
            assert "def create_bids_first_level_workflow" in app_content
            assert "fsl.SpecifyModel()" in app_content
            assert "fsl.Level1Design()" in app_content
            assert "fsl.FILMGLS()" in app_content
            assert "task='stroop'" in app_content

    def test_error_missing_bids_dir(self):
        """Test error handling for missing BIDS directory."""
        result = self.tool._run(
            bids_dir="/nonexistent/bids",
            output_dir="/tmp/output"
        )

        assert result.status == "error"
        assert "BIDS directory not found" in result.error


class TestNipypeInterfaceWrapperTool(unittest.TestCase):
    """Test Nipype interface wrapper tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = NipypeInterfaceWrapperTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "nipype_interface_wrapper"
        assert "Wrap and execute individual Nipype interfaces" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == NipypeInterfaceWrapperArgs

    def test_wrap_fsl_interface(self):
        """Test wrapping FSL interface."""
        with tempfile.TemporaryDirectory() as temp_dir:
            inputs = {
                "in_file": "/data/brain.nii.gz",
                "frac": 0.5,
                "robust": True,
                "out_file": "/data/brain_skull.nii.gz"
            }

            result = self.tool._run(
                interface_type="fsl",
                interface_name="BET",
                inputs=inputs,
                output_dir=temp_dir
            )

            assert result.status == "success"
            assert result.data["interface"] == "fsl.BET"

            # Check script file
            script_file = Path(result.data["script_file"])
            assert script_file.exists()
            script_content = script_file.read_text()
            assert "import nipype.interfaces.fsl as fsl" in script_content
            assert "interface = fsl.BET()" in script_content
            assert 'interface.inputs.in_file = "/data/brain.nii.gz"' in script_content
            assert "interface.inputs.frac = 0.5" in script_content
            assert "interface.inputs.robust = True" in script_content

            # Check config file
            config_file = Path(result.data["config_file"])
            assert config_file.exists()
            config_data = json.loads(config_file.read_text())
            assert config_data["interface_type"] == "fsl"
            assert config_data["interface_name"] == "BET"

    def test_wrap_spm_interface(self):
        """Test wrapping SPM interface."""
        with tempfile.TemporaryDirectory() as temp_dir:
            inputs = {
                "in_files": ["/data/func1.nii", "/data/func2.nii"],
                "fwhm": [6, 6, 6]
            }

            result = self.tool._run(
                interface_type="spm",
                interface_name="Smooth",
                inputs=inputs,
                output_dir=temp_dir
            )

            assert result.status == "success"
            assert result.data["interface"] == "spm.Smooth"

            script_content = Path(result.data["script_file"]).read_text()
            assert "import nipype.interfaces.spm as spm" in script_content
            assert "interface = spm.Smooth()" in script_content
            assert "interface.inputs.fwhm = [6, 6, 6]" in script_content

    def test_wrap_with_run_interface(self):
        """Test wrapping with run_interface flag."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.tool._run(
                interface_type="utility",
                interface_name="IdentityInterface",
                inputs={"fields": ["field1", "field2"]},
                output_dir=temp_dir,
                run_interface=True
            )

            assert result.status == "success"
            assert result.data["run_interface"] is True

            script_content = Path(result.data["script_file"]).read_text()
            assert "result = interface.run()" in script_content
            assert "Interface executed successfully!" in script_content

    def test_cmdline_preview(self):
        """Test command line preview for known interfaces."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.tool._run(
                interface_type="fsl",
                interface_name="FLIRT",
                inputs={
                    "in_file": "moving.nii",
                    "reference": "fixed.nii"
                },
                output_dir=temp_dir
            )

            assert result.status == "success"
            assert result.data["cmdline_preview"] == "flirt -in moving.nii -ref fixed.nii -out output"


class TestNipypeDistributedTool(unittest.TestCase):
    """Test Nipype distributed execution tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = NipypeDistributedTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "nipype_distributed"
        assert "distributed computing" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == NipypeDistributedArgs

    def test_multiproc_execution(self):
        """Test MultiProc plugin configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock workflow file
            workflow_file = os.path.join(temp_dir, "workflow.py")
            Path(workflow_file).write_text("def create_workflow(): pass")

            result = self.tool._run(
                workflow_file=workflow_file,
                plugin="MultiProc",
                n_procs=8,
                memory_gb=16,
                working_dir=temp_dir
            )

            assert result.status == "success"
            assert result.data["plugin"] == "MultiProc"
            assert result.data["plugin_args"]["n_procs"] == 8
            assert result.data["plugin_args"]["memory_gb"] == 16

            # Check execution script
            exec_file = Path(result.data["execution_script"])
            assert exec_file.exists()
            exec_content = exec_file.read_text()
            assert "plugin_args = {'n_procs': 8, 'memory_gb': 16" in exec_content
            assert 'workflow.run(plugin="MultiProc"' in exec_content

    def test_slurm_execution(self):
        """Test SLURM plugin configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_file = os.path.join(temp_dir, "workflow.py")
            Path(workflow_file).write_text("def create_workflow(): pass")

            result = self.tool._run(
                workflow_file=workflow_file,
                plugin="SLURM",
                n_procs=16,
                memory_gb=32,
                queue="gpu",
                walltime="24:00:00",
                working_dir=temp_dir
            )

            assert result.status == "success"
            assert result.data["plugin"] == "SLURM"
            assert result.data["submit_script"] is not None

            # Check submission script
            submit_file = Path(result.data["submit_script"])
            assert submit_file.exists()
            submit_content = submit_file.read_text()
            assert "#SBATCH --mem=32G" in submit_content
            assert "#SBATCH --cpus-per-task=16" in submit_content
            assert "#SBATCH --partition=gpu" in submit_content
            assert "#SBATCH --time=24:00:00" in submit_content

    def test_sge_execution(self):
        """Test SGE plugin configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_file = os.path.join(temp_dir, "workflow.py")
            Path(workflow_file).write_text("def create_workflow(): pass")

            result = self.tool._run(
                workflow_file=workflow_file,
                plugin="SGE",
                n_procs=4,
                memory_gb=8,
                queue="all.q",
                working_dir=temp_dir
            )

            assert result.status == "success"
            assert result.data["plugin"] == "SGE"

            submit_content = Path(result.data["submit_script"]).read_text()
            assert "#$ -l h_vmem=8G" in submit_content
            assert "#$ -pe smp 4" in submit_content
            assert "#$ -q all.q" in submit_content

    def test_pbs_execution(self):
        """Test PBS plugin configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_file = os.path.join(temp_dir, "workflow.py")
            Path(workflow_file).write_text("def create_workflow(): pass")

            result = self.tool._run(
                workflow_file=workflow_file,
                plugin="PBS",
                n_procs=12,
                memory_gb=24,
                walltime="12:00:00",
                working_dir=temp_dir
            )

            assert result.status == "success"
            assert result.data["plugin"] == "PBS"

            submit_content = Path(result.data["submit_script"]).read_text()
            assert "#PBS -l mem=24gb" in submit_content
            assert "#PBS -l ncpus=12" in submit_content
            assert "#PBS -l walltime=12:00:00" in submit_content

    def test_error_missing_workflow(self):
        """Test error handling for missing workflow file."""
        result = self.tool._run(
            workflow_file="/nonexistent/workflow.py",
            working_dir="/tmp"
        )

        assert result.status == "error"
        assert "Workflow file not found" in result.error


class TestEnumValues(unittest.TestCase):
    """Test enum value definitions."""

    def test_workflow_plugin_enum(self):
        """Test WorkflowPlugin enum values."""
        assert WorkflowPlugin.LINEAR == "Linear"
        assert WorkflowPlugin.MULTIPROC == "MultiProc"
        assert WorkflowPlugin.SLURM == "SLURM"
        assert WorkflowPlugin.SGE == "SGE"
        assert WorkflowPlugin.PBS == "PBS"
        assert WorkflowPlugin.CONDOR == "HTCondor"
        assert WorkflowPlugin.LSF == "LSF"

    def test_data_grabber_enum(self):
        """Test DataGrabberType enum values."""
        assert DataGrabberType.BIDS == "bids"
        assert DataGrabberType.FREESURFER == "freesurfer"
        assert DataGrabberType.CUSTOM == "custom"
        assert DataGrabberType.XNAT == "xnat"
        assert DataGrabberType.FLYWHEEL == "flywheel"

    def test_interface_type_enum(self):
        """Test InterfaceType enum values."""
        assert InterfaceType.FSL == "fsl"
        assert InterfaceType.SPM == "spm"
        assert InterfaceType.FREESURFER == "freesurfer"
        assert InterfaceType.ANTS == "ants"
        assert InterfaceType.AFNI == "afni"
        assert InterfaceType.MRTRIX == "mrtrix"
        assert InterfaceType.DIPY == "dipy"
        assert InterfaceType.NILEARN == "nilearn"


class TestIntegration(unittest.TestCase):
    """Integration tests for Nipype tools."""

    def test_tools_collection(self):
        """Test getting all Nipype tools."""
        tools = NipypeTools.get_all_tools()

        assert len(tools) == 4
        assert any(isinstance(t, NipypeWorkflowBuilderTool) for t in tools)
        assert any(isinstance(t, NipypeBIDSAppTool) for t in tools)
        assert any(isinstance(t, NipypeInterfaceWrapperTool) for t in tools)
        assert any(isinstance(t, NipypeDistributedTool) for t in tools)

    def test_tool_names_unique(self):
        """Test that all tool names are unique."""
        tools = NipypeTools.get_all_tools()
        names = [t.get_tool_name() for t in tools]

        assert len(names) == len(set(names))

    def test_all_tools_inherit_base(self):
        """Test all tools inherit from BRKGToolWrapper."""
        from brain_researcher.services.tools.tool_base import BRKGToolWrapper

        tools = NipypeTools.get_all_tools()
        for tool in tools:
            assert isinstance(tool, BRKGToolWrapper)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])