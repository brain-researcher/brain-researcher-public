"""Integration tests for ToolExecutor run recording.

Tests provenance tracking for command generation and direct execution modes.
"""

import json
from pathlib import Path
import pytest

from brain_researcher.services.agent.tool_executor import (
    ToolExecutor,
    ToolExecutionRequest,
    ExecutionMode,
    ToolCategory,
)
from brain_researcher.services.tools.executors import create_recorder_factory
from brain_researcher.config.run_artifacts import get_recorder_config, reset_recorder_config


@pytest.fixture
def enable_run_recording(tmp_path, monkeypatch):
    """Enable run recording with temporary directory."""
    reset_recorder_config()
    monkeypatch.setenv("BR_RUN_STORE_ENABLED", "true")
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("BR_OUTPUT_COPY_ENABLED", "false")

    config = get_recorder_config()
    assert config.enabled is True
    return config


@pytest.fixture
def tool_executor(enable_run_recording):
    """Create ToolExecutor with recording enabled."""
    factory = create_recorder_factory()
    return ToolExecutor(
        safe_mode=True,
        recorder_factory=factory,
    )


class TestToolExecutorRecordingDirectExecution:
    """Tests for direct execution mode recording."""

    def test_direct_execution_creates_run_dir(self, tool_executor, enable_run_recording):
        """Test that direct execution creates run_dir."""
        request = ToolExecutionRequest(
            tool_name="echo_test",
            parameters={"command": "echo 'Hello World'"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        assert "run_dir" in result.metadata
        run_dir = Path(result.metadata["run_dir"])
        assert run_dir.exists()

    def test_direct_execution_captures_stdout_stderr(self, tool_executor, enable_run_recording):
        """Test that stdout/stderr are captured in provenance."""
        request = ToolExecutionRequest(
            tool_name="test_output",
            parameters={"command": "echo 'stdout message' && echo 'stderr message' >&2"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        run_dir = Path(result.metadata["run_dir"])

        # Check stdout.txt
        stdout_file = run_dir / "stdout.txt"
        assert stdout_file.exists()
        stdout_content = stdout_file.read_text()
        assert "stdout message" in stdout_content

        # Check stderr.txt
        stderr_file = run_dir / "stderr.txt"
        assert stderr_file.exists()
        stderr_content = stderr_file.read_text()
        assert "stderr message" in stderr_content

    def test_direct_execution_provenance_metadata(self, tool_executor, enable_run_recording):
        """Test that provenance includes execution metadata."""
        request = ToolExecutionRequest(
            tool_name="metadata_test",
            parameters={"command": "echo 'test'"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        run_dir = Path(result.metadata["run_dir"])

        # Check provenance.json
        provenance_file = run_dir / "provenance.json"
        assert provenance_file.exists()

        provenance = json.loads(provenance_file.read_text())
        assert provenance["schema_version"] == "1.1.0"  # Updated schema version for pipeline support
        assert provenance["execution_mode"] == "direct_execution"
        assert provenance["tool_category"] == "data_processing"
        assert provenance["tool_name"] == "metadata_test"
        assert "command" in provenance
        assert "timestamps" in provenance

    def test_direct_execution_status_transitions(self, tool_executor, enable_run_recording):
        """Test that status.json records state transitions."""
        request = ToolExecutionRequest(
            tool_name="status_test",
            parameters={"command": "echo 'status test'"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        run_dir = Path(result.metadata["run_dir"])

        # Check status.json
        status_file = run_dir / "status.json"
        assert status_file.exists()

        status = json.loads(status_file.read_text())
        assert status["state"] == "succeeded"
        assert "started_at" in status
        assert "transitions" in status
        assert len(status["transitions"]) >= 1

    def test_direct_execution_failed_command(self, tool_executor, enable_run_recording):
        """Test recording of failed command execution."""
        request = ToolExecutionRequest(
            tool_name="fail_test",
            parameters={"command": "exit 1"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
        )

        result = tool_executor.execute(request)

        assert result.status == "error"
        assert "run_dir" in result.metadata
        run_dir = Path(result.metadata["run_dir"])
        assert run_dir.exists()

        # Check provenance - non-zero exit code doesn't throw exception,
        # so recorder marks it as "succeeded" (command executed without crash)
        # The failure is tracked in the result status, not recorder state
        provenance_file = run_dir / "provenance.json"
        provenance = json.loads(provenance_file.read_text())
        # Recorder succeeded (no exception), even though exit code was 1
        assert provenance["state"] == "succeeded"
        # The exit code failure is in the parameters/result
        assert result.result["returncode"] == 1


class TestToolExecutorRecordingCommandGeneration:
    """Tests for command generation mode recording."""

    def test_command_generation_creates_run_dir(self, tool_executor, enable_run_recording):
        """Test that command generation creates run_dir."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={
                "tool_name": "fsl",
                "command": "bet",
                "input_files": ["/data/sub-001/anat.nii.gz"],
                "output_path": "/data/sub-001/brain.nii.gz",
                "parameters": {"frac": 0.5, "test_id": "run_dir"},
                "use_module": True,
            },
            mode=ExecutionMode.COMMAND_GENERATION,
            category=ToolCategory.NEUROIMAGING,
            execution_id="cg_run_dir",
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        assert "run_dir" in result.metadata
        run_dir = Path(result.metadata["run_dir"])
        assert run_dir.exists()

    def test_command_generation_records_command(self, tool_executor, enable_run_recording):
        """Test that generated command is recorded."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={
                "tool_name": "fsl",
                "command": "bet",
                "input_files": ["/data/sub-002/anat.nii.gz"],
                "output_path": "/data/sub-002/brain.nii.gz",
                "parameters": {"frac": 0.3, "test_id": "record_command"},
                "use_module": True,
            },
            mode=ExecutionMode.COMMAND_GENERATION,
            category=ToolCategory.NEUROIMAGING,
            execution_id="cg_record_command",
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        run_dir = Path(result.metadata["run_dir"])
        assert run_dir.exists()

        command_file = run_dir / "command.txt"
        assert command_file.exists()
        command_text = command_file.read_text().strip()
        assert "module load fsl/6.0.7.16" in command_text
        assert "bet" in command_text
        assert "/data/sub-002/anat.nii.gz" in command_text

        provenance = json.loads((run_dir / "provenance.json").read_text())
        assert provenance["execution_mode"] == "command_generation"
        assert provenance["tool_category"] == "neuroimaging"
        command_tokens = provenance["command"]
        assert command_tokens[:3] == ["module", "load", "fsl/6.0.7.16"]
        assert "bet" in command_tokens

    def test_command_generation_no_stdout_stderr(self, tool_executor, enable_run_recording):
        """Test that command generation has empty stdout/stderr."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={
                "tool_name": "fsl",
                "command": "bet",
                "input_files": ["/data/sub-003/anat.nii.gz"],
                "output_path": "/data/sub-003/brain.nii.gz",
                "parameters": {"frac": 0.4, "test_id": "no_stdout"},
                "use_module": True,
            },
            mode=ExecutionMode.COMMAND_GENERATION,
            category=ToolCategory.NEUROIMAGING,
            execution_id="cg_no_stdout",
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        run_dir = Path(result.metadata["run_dir"])
        assert run_dir.exists()

        stdout_file = run_dir / "stdout.txt"
        stderr_file = run_dir / "stderr.txt"
        assert stdout_file.exists()
        assert stderr_file.exists()
        assert stdout_file.read_text().strip() == ""
        assert stderr_file.read_text().strip() == ""


class TestToolExecutorRecordingMetadata:
    """Tests for execution metadata and provenance."""

    def test_execution_id_matches_run_id(self, tool_executor, enable_run_recording):
        """Test that execution_id is used as run_id."""
        custom_exec_id = "custom_exec_12345"
        request = ToolExecutionRequest(
            tool_name="id_test",
            parameters={"command": "echo 'id test'"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
            execution_id=custom_exec_id,
        )

        result = tool_executor.execute(request)

        assert result.execution_id == custom_exec_id
        run_dir = Path(result.metadata["run_dir"])
        assert custom_exec_id in str(run_dir)

        # Check provenance has correct run_id
        provenance_file = run_dir / "provenance.json"
        provenance = json.loads(provenance_file.read_text())
        assert provenance["run_id"] == custom_exec_id

    def test_parameters_recorded_in_provenance(self, tool_executor, enable_run_recording):
        """Test that execution parameters are recorded."""
        test_params = {"command": "echo 'param test'", "extra_param": "value123"}
        request = ToolExecutionRequest(
            tool_name="param_test",
            parameters=test_params,
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
        )

        result = tool_executor.execute(request)

        assert result.status == "success"
        run_dir = Path(result.metadata["run_dir"])

        provenance_file = run_dir / "provenance.json"
        provenance = json.loads(provenance_file.read_text())
        assert "parameters" in provenance
        assert provenance["parameters"]["command"] == test_params["command"]


class TestToolExecutorRecordingDisabled:
    """Tests for when recording is disabled."""

    def test_execution_without_recording(self, tmp_path, monkeypatch):
        """Test that execution works when recording is disabled."""
        reset_recorder_config()
        monkeypatch.setenv("BR_RUN_STORE_ENABLED", "false")

        config = get_recorder_config()
        assert config.enabled is False

        factory = create_recorder_factory()
        executor = ToolExecutor(recorder_factory=factory)

        request = ToolExecutionRequest(
            tool_name="no_record_test",
            parameters={"command": "echo 'no recording'"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            category=ToolCategory.DATA_PROCESSING,
        )

        result = executor.execute(request)

        # Execution should still work
        assert result.status == "success"
        # run_dir may be in metadata but files won't be created
        if "run_dir" in result.metadata:
            run_dir = Path(result.metadata["run_dir"])
            # Files should not exist when recording is disabled
            assert not (run_dir / "provenance.json").exists() or not run_dir.exists()
