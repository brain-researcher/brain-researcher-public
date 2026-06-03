#!/usr/bin/env python3
"""
Test suite for RunRecorder minimal logging implementation.

This module tests the new RunRecorder functionality for traceability,
reproducibility, and auditability of agent executions.
"""

import json
import shutil
import tempfile
from pathlib import Path
import pytest

import brain_researcher.services.agent.logging.run_recorder as run_recorder_module
from brain_researcher.config.run_artifacts import get_metadata_root
from brain_researcher.services.agent.logging.run_recorder import (
    RunRecorder,
    get_recorder,
    file_fingerprint,
    redacted_path,
    compute_tool_spec_digest,
    get_package_version,
    get_git_sha,
)
from brain_researcher.services.tools.args_resolver import ArgsResolver


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for test logs."""
    temp_dir = tempfile.mkdtemp(prefix="test_logs_")
    yield temp_dir
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def recorder(temp_log_dir):
    """Create a RunRecorder instance with temporary directory."""
    return RunRecorder(base_path=temp_log_dir)


class TestRunRecorder:
    """Test RunRecorder core functionality."""

    def test_unified_run_id(self, recorder):
        """Test that run_id is consistent across all phases."""
        # Start planning phase
        run_id = recorder.start("planning")
        assert run_id is not None
        assert len(run_id) == 36  # UUID format

        planning_log = recorder.record_planning(
            query="Test query",
            tool_candidates=[{"name": "tool1", "score": 0.8}],
            selected_tool="tool1",
        )

        # Start execution phase with same run_id
        recorder.start("execution", run_id=run_id)
        execution_log = recorder.record_execution(
            query="Test query",
            selected_tool="tool1",
            args_raw={"param": "value"},
            args_resolved={"param": "resolved_value"},
            validation_ok=True,
        )

        # Start review phase with same run_id
        recorder.start("review", run_id=run_id)
        review_log = recorder.record_review(query="Test query", status="PASS")

        # Verify all phases have same run_id
        assert planning_log["run_id"] == run_id
        assert execution_log["run_id"] == run_id
        assert review_log["run_id"] == run_id

    def test_timestamp_structure(self, recorder):
        """Test that all three timestamp types are recorded."""
        recorder.start("planning")
        log = recorder.record_planning(
            query="Test query", tool_candidates=[], selected_tool="test_tool"
        )

        # Check timestamp structure
        assert "timestamps" in log
        timestamps = log["timestamps"]

        # UTC timestamp
        assert "ts_event_utc" in timestamps
        assert timestamps["ts_event_utc"].endswith("Z")

        # Local timestamp with timezone
        assert "ts_event_local" in timestamps
        assert (
            "-" in timestamps["ts_event_local"] or "+" in timestamps["ts_event_local"]
        )

        # Performance timing
        assert "perf" in timestamps
        perf = timestamps["perf"]
        assert "start_ns" in perf
        assert "end_ns" in perf
        assert "duration_ms" in perf
        assert perf["duration_ms"] > 0
        assert perf["end_ns"] > perf["start_ns"]

    def test_schema_version(self, recorder):
        """Test that schema version starts at 0.0."""
        recorder.start("planning")
        log = recorder.record_planning(
            query="Test", tool_candidates=[], selected_tool="test"
        )

        assert log["schema_version"] == "0.0"

    def test_phase_identification(self, recorder):
        """Test that phase is correctly identified."""
        # Planning
        recorder.start("planning")
        planning = recorder.record_planning(
            query="Test", tool_candidates=[], selected_tool="test"
        )
        assert planning["phase"] == "planning"

        # Execution
        recorder.start("execution")
        execution = recorder.record_execution(
            query="Test",
            selected_tool="test",
            args_raw={},
            args_resolved={},
            validation_ok=True,
        )
        assert execution["phase"] == "execution"

        # Review
        recorder.start("review")
        review = recorder.record_review(query="Test", status="PASS")
        assert review["phase"] == "review"


class TestParameterTracing:
    """Test parameter tracing functionality."""

    def test_args_resolution_chain(self, recorder):
        """Test args_raw -> args_resolved -> validation chain."""
        recorder.start("execution")

        args_raw = {"image": "/data/test.nii", "TR": 2.0}
        args_resolved = {"img": "/data/test.nii", "t_r": 2.0, "standardize": True}

        log = recorder.record_execution(
            query="Test query",
            selected_tool="fmri_tool",
            args_raw=args_raw,
            args_resolved=args_resolved,
            validation_ok=True,
            validation_errors=[],
        )

        assert log["args"]["args_raw"] == args_raw
        assert log["args"]["args_resolved"] == args_resolved
        assert log["args"]["validation"]["ok"] is True
        assert log["args"]["validation"]["errors"] == []

    def test_validation_errors(self, recorder):
        """Test recording of validation errors."""
        recorder.start("execution")

        validation_errors = [
            "Missing required parameter: mask",
            "Invalid type for parameter 't_r': expected float",
        ]

        log = recorder.record_execution(
            query="Test query",
            selected_tool="fmri_tool",
            args_raw={"image": "test.nii"},
            args_resolved={"img": "test.nii"},
            validation_ok=False,
            validation_errors=validation_errors,
        )

        assert log["args"]["validation"]["ok"] is False
        assert log["args"]["validation"]["errors"] == validation_errors

    def test_args_resolver_integration(self):
        """Test integration with ArgsResolver."""
        resolver = ArgsResolver()

        # Mock tool spec
        class MockToolSpec:
            name = "test_tool"
            required = ["img"]
            synonyms = {"img": ["image", "input"]}

        params = {"image": "/data/test.nii"}
        result = resolver.resolve_full_pipeline(params, MockToolSpec())

        assert "params" in result
        assert "trace" in result
        assert result["trace"]["args_raw"] == params
        assert "img" in result["params"]  # Synonym resolved
        assert result["trace"]["validation"]["ok"] is True


class TestFileFingerprinting:
    """Test file fingerprinting and privacy features."""

    def test_file_fingerprint(self, tmp_path):
        """Test SHA256 fingerprinting of files."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_content = b"Test content for fingerprinting"
        test_file.write_bytes(test_content)

        fingerprint = file_fingerprint(str(test_file))

        assert "sha256" in fingerprint
        assert "bytes" in fingerprint
        assert "uri" in fingerprint
        assert fingerprint["bytes"] == len(test_content)
        assert fingerprint["uri"].startswith("file://")
        assert len(fingerprint["sha256"]) == 64  # SHA256 hex length

    def test_path_redaction(self):
        """Test privacy-aware path redaction."""
        test_cases = [
            ("/home/username/data/test.nii", "/home/[REDACTED]/data/test.nii"),
            (
                "/Users/john/projects/brain/data.csv",
                "/Users/[REDACTED]/projects/brain/data.csv",
            ),
            (
                "/scratch/temp/analysis/output.npy",
                "/scratch/[REDACTED]/analysis/output.npy",
            ),
            (
                "/mnt/storage/datasets/sub-01/anat.nii",
                "/mnt/[REDACTED]/datasets/sub-01/anat.nii",
            ),
        ]

        for original, expected_pattern in test_cases:
            redacted = redacted_path(original)
            # Check that sensitive parts are redacted
            assert "username" not in redacted
            assert "john" not in redacted

    def test_input_output_fingerprints(self, recorder, tmp_path):
        """Test recording of input/output file fingerprints."""
        # Create test files
        input_file = tmp_path / "input.nii"
        output_file = tmp_path / "output.npy"
        input_file.write_text("input data")
        output_file.write_bytes(b"output data")

        recorder.start("execution")
        log = recorder.record_execution(
            query="Test",
            selected_tool="test_tool",
            args_raw={},
            args_resolved={},
            validation_ok=True,
            input_files=[str(input_file)],
            output_files=[str(output_file)],
        )

        # Check input fingerprints
        assert "input_fingerprints" in log["request"]
        assert len(log["request"]["input_fingerprints"]) == 1
        input_fp = log["request"]["input_fingerprints"][0]
        assert "sha256" in input_fp
        assert "bytes" in input_fp
        assert "path_redacted" in input_fp

        # Check output artifacts
        assert "artifacts" in log["execution"]
        assert len(log["execution"]["artifacts"]) == 1
        output_fp = log["execution"]["artifacts"][0]
        assert "sha256" in output_fp
        assert "bytes" in output_fp
        assert "type" in output_fp


class TestEnvironmentCapture:
    """Test environment and version capture."""

    def test_environment_fields(self, recorder):
        """Test that environment information is captured."""
        env = recorder.get_environment()

        # Required fields
        assert "python" in env
        assert "git_sha" in env  # May be None if not in git

        # Package versions
        assert "nilearn" in env
        assert "numpy" in env
        assert "nibabel" in env
        assert "langchain" in env

    def test_python_version_format(self, recorder):
        """Test Python version format."""
        env = recorder.get_environment()
        python_version = env["python"]

        # Should be in format X.Y.Z
        parts = python_version.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)

    def test_container_image_from_env(self, recorder, monkeypatch):
        """Test container image detection from environment."""
        # Set environment variable
        monkeypatch.setenv("BR_IMAGE", "brain_researcher:v1.2.3")

        # Clear cache to force re-read
        recorder._env_cache = None
        env = recorder.get_environment()

        assert "container_image" in env
        assert env["container_image"] == "brain_researcher:v1.2.3"


class TestToolSelection:
    """Test tool selection and decision recording."""

    def test_tool_candidates_recording(self, recorder):
        """Test recording of tool candidates with scores."""
        recorder.start("planning")

        candidates = [
            {"name": "connectivity_matrix", "score": 0.85},
            {"name": "correlation_analysis", "score": 0.72},
            {"name": "seed_based_fc", "score": 0.45},
        ]

        log = recorder.record_planning(
            query="Calculate connectivity",
            tool_candidates=candidates,
            selected_tool="connectivity_matrix",
            candidate_count=3,
            candidate_source_counts={"catalog": 2, "br_kg": 1},
            selected_tool_rank=1,
            selected_tool_in_top_k={"top_5": True, "top_10": True},
            family_selected=False,
            family_expand_success=None,
            routing_latency_ms=42.5,
            surface="chat",
        )

        assert log["request"]["tool_candidates"] == candidates
        assert log["request"]["selected_tool"] == "connectivity_matrix"
        assert log["request"]["candidate_count"] == 3
        assert log["request"]["candidate_source_counts"] == {"catalog": 2, "br_kg": 1}
        assert log["request"]["selected_tool_rank"] == 1
        assert log["request"]["selected_tool_in_top_k"] == {
            "top_5": True,
            "top_10": True,
        }
        assert log["request"]["routing_latency_ms"] == 42.5
        assert log["request"]["surface"] == "chat"

    def test_tool_spec_digest(self, recorder):
        """Test tool specification fingerprinting."""
        recorder.start("planning")

        # Mock tool spec
        tool_spec = {
            "name": "test_tool",
            "parameters": {
                "img": {"type": "string", "required": True},
                "t_r": {"type": "float", "default": 2.0},
            },
        }

        log = recorder.record_planning(
            query="Test",
            tool_candidates=[],
            selected_tool="test_tool",
            tool_spec=tool_spec,
        )

        assert "tool_spec_digest" in log["request"]
        digest = log["request"]["tool_spec_digest"]
        assert digest.startswith("sha256:")
        assert len(digest) > 10

    def test_llm_metadata(self, recorder):
        """Test recording of LLM call metadata."""
        recorder.start("planning")

        log = recorder.record_planning(
            query="Test",
            tool_candidates=[],
            selected_tool="test",
            llm_provider="google",
            llm_model="gemini-2.0-flash",
            llm_params={"temperature": 0.2, "max_tokens": 1024, "top_p": 0.9},
        )

        assert "llm_call" in log
        llm = log["llm_call"]
        assert llm["provider"] == "google"
        assert llm["model"] == "gemini-2.0-flash"
        assert llm["params"]["temperature"] == 0.2
        assert llm["params"]["max_tokens"] == 1024


class TestReviewPhase:
    """Test review phase logging."""

    def test_review_status(self, recorder):
        """Test review status recording."""
        recorder.start("review")

        log = recorder.record_review(
            query="Test",
            status="PASS",
            checks=[
                {"item": "output_validation", "result": "OK", "note": "Shape correct"},
                {"item": "value_range", "result": "OK", "note": "Values in [-1, 1]"},
            ],
            notes="All checks passed",
        )

        assert log["review"]["status"] == "PASS"
        assert len(log["review"]["checks"]) == 2
        assert log["review"]["notes"] == "All checks passed"

    def test_review_checks_structure(self, recorder):
        """Test structure of review checks."""
        recorder.start("review")

        checks = [
            {"item": "shape", "result": "OK", "note": "48x48"},
            {"item": "nan_check", "result": "FAILED", "note": "Found 3 NaN values"},
        ]

        log = recorder.record_review(
            query="Test", status="CHANGES_REQUESTED", checks=checks
        )

        for i, check in enumerate(log["review"]["checks"]):
            assert "item" in check
            assert "result" in check
            assert "note" in check
            assert check == checks[i]


class TestLogPersistence:
    """Test log file writing and persistence."""

    def test_jsonl_file_creation(self, recorder, temp_log_dir):
        """Test that JSONL files are created correctly."""
        recorder.start("planning")
        log = recorder.record_planning(
            query="Test", tool_candidates=[], selected_tool="test"
        )

        # Check session file exists
        session_dir = Path(temp_log_dir) / "sessions"
        assert session_dir.exists()

        jsonl_files = list(session_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1

        # Read and verify content
        with open(jsonl_files[0], "r") as f:
            line = f.readline()
            loaded = json.loads(line)
            assert loaded["run_id"] == log["run_id"]
            assert loaded["phase"] == "planning"

    def test_category_buckets(self, recorder, temp_log_dir):
        """Test that logs are written to category buckets."""
        recorder.start("execution")
        recorder.record_execution(
            query="Test",
            selected_tool="test",
            args_raw={},
            args_resolved={},
            validation_ok=True,
        )

        # Check category directories
        agent_dir = Path(temp_log_dir) / "agent" / "executions.jsonl"
        execution_dir = Path(temp_log_dir) / "execution" / "executions.jsonl"

        assert agent_dir.exists()
        assert execution_dir.exists()

    def test_daily_bucketing(self, recorder, temp_log_dir):
        """Test that logs are bucketed by date."""
        from datetime import datetime

        recorder.start("planning")
        recorder.record_planning(query="Test", tool_candidates=[], selected_tool="test")

        # Check filename format
        today = datetime.now().strftime("%Y-%m-%d")
        expected_file = Path(temp_log_dir) / "sessions" / f"{today}.jsonl"
        assert expected_file.exists()


class TestUtilityFunctions:
    """Test standalone utility functions."""

    def test_get_package_version(self):
        """Test package version retrieval."""
        # Test with a package that should exist
        import sys

        python_version = get_package_version("sys")  # sys doesn't have version

        # Test with numpy (should be installed)
        numpy_version = get_package_version("numpy")
        if numpy_version:
            assert "." in numpy_version  # Should have version format

    def test_compute_tool_spec_digest(self):
        """Test tool spec digest computation."""
        spec1 = {"name": "tool1", "params": {"a": 1, "b": 2}}
        spec2 = {"name": "tool1", "params": {"b": 2, "a": 1}}  # Same but reordered
        spec3 = {"name": "tool2", "params": {"a": 1, "b": 2}}  # Different

        digest1 = compute_tool_spec_digest(spec1)
        digest2 = compute_tool_spec_digest(spec2)
        digest3 = compute_tool_spec_digest(spec3)

        # Same content should give same digest
        assert digest1 == digest2
        # Different content should give different digest
        assert digest1 != digest3

        # Format check
        assert digest1.startswith("sha256:")

    def test_singleton_recorder(self, temp_log_dir):
        """Test singleton recorder instance."""
        recorder1 = get_recorder(temp_log_dir)
        recorder2 = get_recorder(temp_log_dir)

        # Should return same instance
        assert recorder1 is recorder2

    def test_default_base_path_uses_shared_metadata_root(self, monkeypatch, tmp_path):
        """Default recorder root should come from the shared metadata resolver."""
        metadata_root = tmp_path / "artifacts" / "metadata"
        monkeypatch.setenv("BR_METADATA_DIR", str(metadata_root))

        recorder = RunRecorder()

        assert recorder.base == get_metadata_root()
        assert recorder.base == metadata_root.resolve()

    def test_singleton_default_uses_shared_metadata_root(self, monkeypatch, tmp_path):
        """Singleton helper should honor the shared metadata root when unspecified."""
        metadata_root = tmp_path / "artifacts" / "metadata"
        monkeypatch.setenv("BR_METADATA_DIR", str(metadata_root))
        monkeypatch.setattr(run_recorder_module, "_default_recorder", None)

        recorder = get_recorder()

        assert recorder.base == metadata_root.resolve()


# Integration test
def test_full_pipeline_integration(recorder):
    """Test a complete planning->execution->review pipeline."""
    query = "Calculate connectivity matrix for sub-06_bold.nii.gz"

    # Planning phase
    run_id = recorder.start("planning")
    planning_log = recorder.record_planning(
        query=query,
        tool_candidates=[
            {"name": "connectivity_matrix", "score": 0.9},
            {"name": "correlation_matrix", "score": 0.6},
        ],
        selected_tool="connectivity_matrix",
        llm_provider="google",
        llm_model="gemini-2.0-flash",
    )

    # Execution phase
    recorder.start("execution", run_id=run_id)
    execution_log = recorder.record_execution(
        query=query,
        selected_tool="connectivity_matrix",
        args_raw={"img": "sub-06_bold.nii.gz", "atlas": "AAL"},
        args_resolved={
            "img": "/data/sub-06_bold.nii.gz",
            "labels_img": "/atlas/AAL.nii",
        },
        validation_ok=True,
        exit_code=0,
    )

    # Review phase
    recorder.start("review", run_id=run_id)
    review_log = recorder.record_review(
        query=query,
        status="PASS",
        checks=[{"item": "shape", "result": "OK", "note": "116x116"}],
    )

    # Verify consistency
    assert planning_log["run_id"] == execution_log["run_id"] == review_log["run_id"]
    assert planning_log["schema_version"] == "0.0"
    assert execution_log["schema_version"] == "0.0"
    assert review_log["schema_version"] == "0.0"

    # Verify phases
    assert planning_log["phase"] == "planning"
    assert execution_log["phase"] == "execution"
    assert review_log["phase"] == "review"

    # Verify all have timestamps
    for log in [planning_log, execution_log, review_log]:
        assert "timestamps" in log
        assert "ts_event_utc" in log["timestamps"]
        assert "perf" in log["timestamps"]
        assert log["timestamps"]["perf"]["duration_ms"] > 0
