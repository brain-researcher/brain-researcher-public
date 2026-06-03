"""
Tests for runs CLI commands (br runs).

Tests cover:
- br runs ls: List jobs
- br runs inspect: Job details
- br runs plan: Planner trace
- br runs logs: Log streaming
- br runs artifacts: Artifact listing
"""

import pytest
from typer.testing import CliRunner
from unittest.mock import patch, Mock, AsyncMock
from brain_researcher.cli.commands.runs_commands import app, format_timestamp, format_file_size

runner = CliRunner()


# ============================================================================
# Unit Tests for Helpers
# ============================================================================

class TestFormatHelpers:
    """Test formatting helper functions"""

    def test_format_timestamp_valid(self):
        # Unix timestamp for 2024-01-01 00:00:00
        timestamp = 1704067200
        result = format_timestamp(timestamp)
        assert "2024-01-01" in result

    def test_format_timestamp_none(self):
        result = format_timestamp(None)
        assert result == "N/A"

    def test_format_timestamp_zero(self):
        result = format_timestamp(0)
        assert "1970" in result  # Unix epoch

    def test_format_file_size_bytes(self):
        assert format_file_size(512) == "512 B"

    def test_format_file_size_kb(self):
        assert "1.0 KB" in format_file_size(1024)

    def test_format_file_size_mb(self):
        assert "1.0 MB" in format_file_size(1024 * 1024)

    def test_format_file_size_gb(self):
        result = format_file_size(1024 * 1024 * 1024)
        assert "1.00 GB" in result


# ============================================================================
# Integration Tests for Commands
# ============================================================================

class TestRunsList:
    """Test br runs ls command"""

    @patch("brain_researcher.cli.commands.runs_commands.api_post_sync")
    def test_list_basic(self, mock_post):
        mock_post.return_value = {
            "jobs": [
                {
                    "id": "run_abc123",
                    "status": "succeeded",
                    "tool": "fsl_bet",
                    "prompt": "skull strip",
                    "created_at": 1704067200,
                    "plan_summary": {"plan_status": "completed"}
                },
                {
                    "id": "run_xyz789",
                    "status": "running",
                    "tool": "afni.3dSkullStrip",
                    "prompt": "extract brain",
                    "created_at": 1704067100,
                    "plan_summary": {"plan_status": "planned"}
                }
            ],
            "total": 2
        }

        result = runner.invoke(app, ["ls"])

        assert result.exit_code == 0
        assert "run_abc123" in result.stdout
        assert "run_xyz789" in result.stdout
        assert "Plan Status" in result.stdout

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/api/jobs/search"
        payload = call_args[1]["json_data"]
        assert payload["limit"] == 50

    @patch("brain_researcher.cli.commands.runs_commands.api_post_sync")
    def test_list_with_state_filter(self, mock_post):
        mock_post.return_value = {"jobs": [], "total": 0}

        result = runner.invoke(app, ["ls", "--state", "running"])

        assert result.exit_code == 0
        payload = mock_post.call_args[1]["json_data"]
        assert payload["status"] == ["running"]

    @patch("brain_researcher.cli.commands.runs_commands.api_post_sync")
    def test_list_with_limit(self, mock_post):
        mock_post.return_value = {"jobs": [], "total": 0}

        result = runner.invoke(app, ["ls", "--limit", "10"])

        assert result.exit_code == 0
        payload = mock_post.call_args[1]["json_data"]
        assert payload["limit"] == 10

    @patch("brain_researcher.cli.commands.runs_commands.api_post_sync")
    def test_list_empty(self, mock_post):
        mock_post.return_value = {"jobs": [], "total": 0}

        result = runner.invoke(app, ["ls"])

        assert result.exit_code == 0
        assert "No jobs found" in result.stdout


class TestRunsInspect:
    """Test br runs inspect command"""

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_inspect_basic(self, mock_get):
        """Test basic job inspection"""
        def mock_api_get(path, **kwargs):
            if "/plan" in path:
                raise Exception("Plan not available")
            return {
                "job_id": "run_abc123",
                "state": "succeeded",
                "tool": "fsl_bet",
                "prompt": "skull strip",
                "created_at": 1704067200,
                "completed_at": 1704067260,
                "priority": 0
            }

        mock_get.side_effect = mock_api_get

        result = runner.invoke(app, ["inspect", "run_abc123"])

        assert result.exit_code == 0
        assert "run_abc123" in result.stdout
        assert "succeeded" in result.stdout
        assert "fsl_bet" in result.stdout

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_inspect_with_error(self, mock_get):
        """Test inspecting failed job"""
        def mock_api_get(path, **kwargs):
            if "/plan" in path:
                raise Exception("Plan not available")
            return {
                "job_id": "run_failed",
                "state": "failed",
                "error": "Container execution failed",
                "created_at": 1704067200
            }

        mock_get.side_effect = mock_api_get

        result = runner.invoke(app, ["inspect", "run_failed"])

        assert result.exit_code == 0
        assert "failed" in result.stdout
        assert "Container execution failed" in result.stdout

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_inspect_not_found(self, mock_get):
        """Test inspecting non-existent job"""
        import httpx
        mock_get.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=Mock(),
            response=Mock(status_code=404, json=lambda: {"detail": "Job not found"})
        )

        result = runner.invoke(app, ["inspect", "nonexistent"])

        assert result.exit_code == 1


class TestRunsPlan:
    """Test br runs plan command"""

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_plan_view(self, mock_get):
        """Test viewing planner trace"""
        mock_get.return_value = {
            "intent": "skull strip",
            "candidates": [
                {"tool_id": "fsl_bet", "tool_name": "bet", "score": 0.85, "preflight_ok": True, "reason": "OK"},
                {"tool_id": "afni.3dSkullStrip", "tool_name": "3dSkullStrip", "score": 0.79, "preflight_ok": False, "reason": "Image not found"}
            ],
            "chosen": {"tool_id": "fsl_bet", "tool_name": "bet", "score": 0.85},
            "constraints": {"infile": "/data/brain.nii.gz"}
        }

        result = runner.invoke(app, ["plan", "run_abc123"])

        assert result.exit_code == 0
        assert "skull strip" in result.stdout
        assert "fsl_bet" in result.stdout
        assert "0.85" in result.stdout

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_plan_not_found(self, mock_get):
        """Test viewing plan for job without planner"""
        import httpx
        mock_get.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=Mock(),
            response=Mock(status_code=404, json=lambda: {"detail": "Plan not available"})
        )

        result = runner.invoke(app, ["plan", "run_no_plan"])

        assert result.exit_code == 1
        assert "404" in result.stdout or "not have used the planner" in result.stdout


class TestRunsLogs:
    """Test br runs logs command"""

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_logs_static(self, mock_get):
        """Test fetching static logs"""
        mock_get.return_value = {
            "logs": [
                {"timestamp": "2024-01-01 00:00:00", "text": "Starting job"},
                {"timestamp": "2024-01-01 00:00:01", "text": "Processing..."},
                {"timestamp": "2024-01-01 00:00:02", "text": "Complete"}
            ]
        }

        result = runner.invoke(app, ["logs", "run_abc123"])

        assert result.exit_code == 0
        assert "Starting job" in result.stdout
        assert "Complete" in result.stdout

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_logs_empty(self, mock_get):
        """Test fetching logs when none available"""
        mock_get.return_value = {"logs": []}

        result = runner.invoke(app, ["logs", "run_empty"])

        assert result.exit_code == 0
        assert "No logs available" in result.stdout

    # Note: Testing --follow mode would require mocking async streams, which is complex
    # Manual testing is preferred for stream functionality


class TestRunsArtifacts:
    """Test br runs artifacts command"""

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_artifacts_list(self, mock_get):
        """Test listing artifacts"""
        mock_get.return_value = {
            "run_id": "run_abc123",
            "run_dir": "/tmp/runs/run_abc123",
            "file_count": 2,
            "files": [
                {"name": "output.nii.gz", "size": 1048576, "modified": "2024-01-01 00:00:00"},
                {"name": "results.csv", "size": 2048, "modified": "2024-01-01 00:00:01"}
            ]
        }

        result = runner.invoke(app, ["artifacts", "run_abc123"])

        assert result.exit_code == 0
        assert "output.nii.gz" in result.stdout
        assert "results.csv" in result.stdout
        assert "1.0 MB" in result.stdout  # Formatted size

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_artifacts_empty(self, mock_get):
        """Test empty artifacts list"""
        mock_get.return_value = {
            "run_id": "run_empty",
            "run_dir": "/tmp/runs/run_empty",
            "files": []
        }

        result = runner.invoke(app, ["artifacts", "run_empty"])

        assert result.exit_code == 0
        assert "No artifact files found" in result.stdout

    @patch("brain_researcher.cli.commands.runs_commands.api_get_sync")
    def test_artifacts_not_found(self, mock_get):
        """Test artifacts for job without run directory"""
        import httpx
        mock_get.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=Mock(),
            response=Mock(status_code=404, json=lambda: {"detail": "Run directory not found"})
        )

        result = runner.invoke(app, ["artifacts", "run_no_dir"])

        assert result.exit_code == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
