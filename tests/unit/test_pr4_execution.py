"""Unit tests for PR-4 execution and step tracking.

Tests the new execution, retry, and step tracking functionality.
"""
import pytest
from unittest.mock import Mock, patch
from brain_researcher.services.orchestrator.jobs_steps_api import (
    StepSummary,
    _build_step_summary,
)
from brain_researcher.services.agent.web_service import (
    _is_retryable_error,
    _format_sse,
)


class TestStepSummaryModel:
    """Test the extended StepSummary model from PR-4."""

    def test_step_summary_with_new_fields(self):
        """Test StepSummary instantiation with all PR-4 fields."""
        step = StepSummary(
            step_id="test_001",
            name="Test Step",
            state="succeeded",
            created_at=1234567890,
            started_at=1234567891,
            finished_at=1234567895,
            attempt=2,
            max_attempts=3,
            retry_reason="Timeout on first attempt",
            cache_marker="miss",
            cache_key="abc123",
            execution_time_ms=4000,
            run_dir="/tmp/test",
            provenance_path="/tmp/test/provenance.json",
        )

        assert step.step_id == "test_001"
        assert step.attempt == 2
        assert step.max_attempts == 3
        assert step.retry_reason == "Timeout on first attempt"
        assert step.cache_marker == "miss"
        assert step.cache_key == "abc123"
        assert step.created_at == 1234567890
        assert step.started_at == 1234567891
        assert step.finished_at == 1234567895
        assert step.provenance_path == "/tmp/test/provenance.json"

    def test_step_summary_defaults(self):
        """Test StepSummary with default values."""
        step = StepSummary(step_id="test", state="pending")

        assert step.attempt == 1  # Default
        assert step.max_attempts == 3  # Default
        assert step.cache_marker is None
        assert step.created_at is None


class TestStepParser:
    """Test _build_step_summary parser with PR-4 fields."""

    def test_parse_full_step(self):
        """Test parsing step with all new fields."""
        raw = {
            "step_id": "step_001",
            "state": "succeeded",
            "timestamps": {"created": 100, "started": 101, "finished": 105},
            "attempt": 2,
            "max_attempts": 3,
            "retry_reason": "First attempt failed",
            "cache": {"cache_key": "abc", "cache_hit": False},
            "execution_time_ms": 4000,
            "provenance_path": "/test/provenance.json",
        }

        step = _build_step_summary(raw, 0)

        assert step.created_at == 100
        assert step.started_at == 101
        assert step.finished_at == 105
        assert step.attempt == 2
        assert step.max_attempts == 3
        assert step.retry_reason == "First attempt failed"
        assert step.cache_marker == "miss"
        assert step.cache_key == "abc"
        assert step.provenance_path == "/test/provenance.json"

    def test_parse_cache_hit(self):
        """Test cache hit detection."""
        raw = {"step_id": "test", "state": "ok", "cache": {"cache_hit": True}}
        step = _build_step_summary(raw, 0)
        assert step.cache_marker == "hit"

    def test_parse_cache_from_cache_flag(self):
        """Test cache hit from from_cache flag."""
        raw = {"step_id": "test", "state": "ok", "from_cache": True}
        step = _build_step_summary(raw, 0)
        assert step.cache_marker == "hit"

    def test_parse_cache_disabled(self):
        """Test cache disabled marker."""
        raw = {"step_id": "test", "state": "ok", "cache": {"disabled": True}}
        step = _build_step_summary(raw, 0)
        assert step.cache_marker == "disabled"

    def test_parse_legacy_fields(self):
        """Test backward compatibility with legacy field names."""
        raw = {
            "id": "step_003",  # Legacy
            "state": "failed",
            "start_time": 100,  # Legacy
            "end_time": 105,  # Legacy
            "duration_ms": 5000,  # Legacy
            "error_message": "Tool crashed",  # Legacy
            "run_dir_path": "/runs/step_003",  # Legacy
        }

        step = _build_step_summary(raw, 2)

        assert step.step_id == "step_003"
        assert step.started_at == 100
        assert step.finished_at == 105
        assert step.execution_time_ms == 5000
        assert step.error == "Tool crashed"
        assert step.run_dir == "/runs/step_003"

    def test_parse_invalid_input(self):
        """Test graceful handling of invalid input."""
        step = _build_step_summary("not a dict", 4)

        assert step.step_id == "step-4"
        assert step.state == "unknown"


class TestRetryLogic:
    """Test retry decision logic from PR-4."""

    def test_retryable_timeout_error(self):
        """TimeoutError should be retryable."""
        assert _is_retryable_error(TimeoutError("Request timed out"))

    def test_retryable_connection_error(self):
        """ConnectionError should be retryable."""
        assert _is_retryable_error(ConnectionError("Connection refused"))

    def test_retryable_os_error(self):
        """OSError should be retryable."""
        assert _is_retryable_error(OSError("Resource temporarily unavailable"))

    def test_non_retryable_value_error(self):
        """ValueError should not be retryable."""
        assert not _is_retryable_error(ValueError("Invalid parameter"))

    def test_non_retryable_runtime_error(self):
        """RuntimeError should not be retryable by default."""
        assert not _is_retryable_error(RuntimeError("Tool execution failed"))

    def test_retryable_by_message_pattern(self):
        """Errors with retryable message patterns should be retryable."""
        assert _is_retryable_error(RuntimeError("temporary failure, try again"))
        assert _is_retryable_error(RuntimeError("connection timeout"))
        assert _is_retryable_error(Exception("Resource unavailable"))


class TestSSEFormatting:
    """Test SSE event formatting."""

    def test_format_step_executing(self):
        """Test step_executing event format."""
        event = _format_sse("step_executing", {"step_id": "001", "tool": "test.tool"})

        assert "event: step_executing" in event
        assert '"step_id": "001"' in event
        assert '"tool": "test.tool"' in event
        assert event.endswith("\n\n")

    def test_format_step_retry_started(self):
        """Test step_retry_started event format."""
        event = _format_sse(
            "step_retry_started",
            {"step_id": "001", "attempt": 2, "max_attempts": 3, "reason": "Timeout"},
        )

        assert "event: step_retry_started" in event
        assert '"attempt": 2' in event
        assert '"max_attempts": 3' in event
        assert '"reason": "Timeout"' in event

    def test_format_step_failed(self):
        """Test step_failed event format."""
        event = _format_sse(
            "step_failed",
            {"step_id": "001", "error": "Tool not found", "retryable": False},
        )

        assert "event: step_failed" in event
        assert '"error": "Tool not found"' in event
        assert '"retryable": false' in event
