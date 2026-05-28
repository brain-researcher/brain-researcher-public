"""Smoke tests for services.tools imports.

These tests verify that the unified tool system imports correctly
without circular dependencies and that the migration from neurocore
is working as expected.
"""

import pytest
import warnings


class TestPipelineImports:
    """Test pipeline parameter imports from services.tools.pipelines."""

    def test_pipelines_params_import(self):
        """Test that pipeline params import without circular dependency."""
        from brain_researcher.services.tools.pipelines import (
            FMRIPrepParameters,
            QSIPrepParameters,
            FitLinsParameters,
            MRIQCParameters,
            build_fmriprep_command,
            build_qsiprep_command,
            build_fitlins_command,
            build_mriqc_command,
        )
        assert FMRIPrepParameters is not None
        assert QSIPrepParameters is not None
        assert FitLinsParameters is not None
        assert MRIQCParameters is not None

    def test_pipelines_helpers_import(self):
        """Test that pipeline helpers import correctly."""
        from brain_researcher.services.tools.pipelines import (
            run_fmriprep,
            run_qsiprep,
            run_fitlins,
            run_mriqc,
            FMRIPREP_IMAGE,
            QSIPREP_IMAGE,
            FITLINS_IMAGE,
            MRIQC_IMAGE,
        )
        assert run_fmriprep is not None
        assert run_qsiprep is not None
        assert run_fitlins is not None
        assert run_mriqc is not None
        # Verify env override pattern works
        assert FMRIPREP_IMAGE.endswith(".sif") or "fmriprep" in FMRIPREP_IMAGE.lower()
        assert MRIQC_IMAGE.endswith(".sif") or "mriqc" in MRIQC_IMAGE.lower()

    def test_params_facade_import(self):
        """Non-pipeline params import from services.tools.params."""
        from brain_researcher.services.tools.params import FSLBETParameters

        params = FSLBETParameters(input_file="/tmp/in.nii.gz", output_file="/tmp/out.nii.gz")
        assert params.input_file.endswith("in.nii.gz")


class TestUnifiedRegistry:
    """Test UnifiedToolRegistry imports and functionality."""

    def test_unified_registry_import(self):
        """Test UnifiedToolRegistry imports correctly."""
        from brain_researcher.services.tools import UnifiedToolRegistry
        assert UnifiedToolRegistry is not None

    def test_unified_registry_has_tools(self):
        """Test UnifiedToolRegistry provides tools."""
        from brain_researcher.services.tools import UnifiedToolRegistry
        registry = UnifiedToolRegistry()
        tools = registry.get_all_tools()
        # Should have at least some tools (threshold low for minimal installs)
        assert len(tools) > 0, "UnifiedToolRegistry should provide at least one tool"
        # Verify we can access tool names without error
        tool_names = [getattr(t, "name", None) for t in tools]
        assert any(name is not None for name in tool_names), "Tools should have names"


class TestNeurocoreRemoval:
    """Ensure legacy neurocore package is no longer importable."""

    def test_neurocore_import_raises(self):
        with pytest.raises(ImportError):
            __import__("brain_researcher.neurocore")


class TestContainerCommand:
    """Test container command building with path remapping."""

    def test_fmriprep_container_cmd_paths(self):
        """Test that fMRIPrep container command has remapped paths."""
        from brain_researcher.services.tools.pipelines import FMRIPrepParameters
        from brain_researcher.services.tools.pipelines.helpers import (
            _build_fmriprep_container_cmd,
        )

        params = FMRIPrepParameters(bids_dir="/host/data", output_dir="/host/out")
        cmd = _build_fmriprep_container_cmd(params)
        # Container cmd should have remapped paths
        assert "/data" in cmd
        assert "/out" in cmd
        # Host paths should NOT appear in container cmd
        assert "/host/data" not in cmd
        assert "/host/out" not in cmd

    def test_mriqc_container_cmd_paths(self):
        """Test that MRIQC container command has remapped paths."""
        from brain_researcher.services.tools.pipelines import MRIQCParameters
        from brain_researcher.services.tools.pipelines.helpers import (
            _build_mriqc_container_cmd,
        )

        params = MRIQCParameters(bids_dir="/host/data", output_dir="/host/out")
        cmd = _build_mriqc_container_cmd(params)
        # Container cmd should have remapped paths
        assert "/data" in cmd
        assert "/out" in cmd
        # Host paths should NOT appear in container cmd
        assert "/host/data" not in cmd
        assert "/host/out" not in cmd


class TestRuntimeLiteral:
    """Test Runtime Literal type includes all expected modes."""

    def test_runtime_literal_includes_wrapper(self):
        """Test that Runtime Literal includes 'wrapper' mode."""
        from brain_researcher.services.tools.executors.container import Runtime
        from typing import get_args

        runtime_options = get_args(Runtime)
        assert "docker" in runtime_options
        assert "apptainer" in runtime_options
        assert "wrapper" in runtime_options


class TestAgentToolImports:
    """Test that agent tools import from services.tools correctly."""

    def test_pipeline_tools_import(self):
        """Test pipeline_tools imports work."""
        from brain_researcher.services.tools.pipeline_tools import (
            RunFMRIPrepTool,
        )
        assert RunFMRIPrepTool is not None

    def test_qc_tools_import(self):
        """Test qc_tools imports work."""
        from brain_researcher.services.tools.qc_tools import (
            MRIQCGroupReportTool,
        )
        assert MRIQCGroupReportTool is not None


class TestStructuredToolAdapter:
    """Test StructuredToolAdapter for registry unification."""

    def test_adapter_import(self):
        """Test that adapter imports correctly."""
        from brain_researcher.services.tools.adapter import (
            StructuredToolAdapter,
            wrap_structured_tools,
        )
        assert StructuredToolAdapter is not None
        assert wrap_structured_tools is not None

    def test_adapter_wraps_tool(self):
        """Test that adapter wraps a StructuredTool correctly."""
        from langchain.tools import StructuredTool
        from pydantic import BaseModel
        from brain_researcher.services.tools.adapter import StructuredToolAdapter

        class TestArgs(BaseModel):
            pass

        tool = StructuredTool(
            name="test",
            description="Test tool",
            func=lambda: "ok",
            args_schema=TestArgs,
        )
        adapter = StructuredToolAdapter(tool)
        assert adapter.get_tool_name() == "test"
        assert adapter.get_tool_description() == "Test tool"
        assert adapter.as_langchain_tool() is tool  # No double-wrap


class TestMRIQCParameters:
    """Test MRIQCParameters dataclass functionality."""

    def test_mriqc_params_creation(self):
        """Test creating MRIQCParameters."""
        from brain_researcher.services.tools.pipelines import MRIQCParameters

        params = MRIQCParameters(
            bids_dir="/data",
            output_dir="/out",
            participant_label=["01", "02"],
        )
        assert params.bids_dir == "/data"
        assert params.output_dir == "/out"
        assert params.participant_label == ("01", "02")
        assert params.analysis_level == "participant"

    def test_mriqc_command_generation(self):
        """Test MRIQCParameters generates correct command."""
        from brain_researcher.services.tools.pipelines import (
            MRIQCParameters,
            build_mriqc_command,
        )

        params = MRIQCParameters(
            bids_dir="/data",
            output_dir="/out",
            participant_label=["01"],
            n_procs=4,
        )
        cmd = build_mriqc_command(params)
        assert cmd[0] == "mriqc"
        assert "/data" in cmd
        assert "/out" in cmd
        assert "--participant-label" in cmd
        assert "--n_procs" in cmd
        assert "4" in cmd

    def test_mriqc_from_payload(self):
        """Test creating MRIQCParameters from payload dict."""
        from brain_researcher.services.tools.pipelines import mriqc_from_payload

        payload = {
            "bids_dir": "/data",
            "output_dir": "/out",
            "participant_label": "01",
            "modalities": ["T1w", "bold"],
        }
        params = mriqc_from_payload(payload)
        assert params.bids_dir == "/data"
        assert params.participant_label == ("01",)
        assert params.modalities == ("T1w", "bold")
