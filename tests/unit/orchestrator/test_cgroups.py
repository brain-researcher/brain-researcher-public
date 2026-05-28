"""Unit tests for cgroups enforcement (P3.7)."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_researcher.services.orchestrator.resources.cgroups import (
    apply_cgroups_limits,
    cleanup_cgroups_files,
    write_cgroups_json,
)


class TestWriteCgroupsJson:
    """Test cgroups JSON file generation."""

    def test_write_cgroups_json(self, tmp_path):
        """Test writing a cgroups v2 JSON file."""
        cgroups_dir = str(tmp_path / "cgroups")
        json_path = write_cgroups_json(cgroups_dir, cpu=2, mem_mb=2048, name="test_job")

        # Check file exists
        assert Path(json_path).exists()
        assert json_path == str(tmp_path / "cgroups" / "test_job.json")

        # Check JSON content
        with open(json_path) as f:
            data = json.load(f)

        assert "memory" in data
        assert "cpu" in data
        assert data["memory"]["memory.max"] == str(2048 * 1024 * 1024)
        assert data["cpu"]["cpu.max"] == "200000 100000"

    def test_write_cgroups_json_creates_directory(self, tmp_path):
        """Test that directory is created if it doesn't exist."""
        cgroups_dir = str(tmp_path / "nonexistent" / "cgroups")
        json_path = write_cgroups_json(cgroups_dir, cpu=4, mem_mb=4096, name="test")

        assert Path(json_path).exists()
        assert Path(cgroups_dir).is_dir()

    def test_write_cgroups_json_various_values(self, tmp_path):
        """Test various CPU and memory values."""
        test_cases = [
            (1, 512, "100000 100000", str(512 * 1024 * 1024)),
            (4, 8192, "400000 100000", str(8192 * 1024 * 1024)),
            (16, 65536, "1600000 100000", str(65536 * 1024 * 1024)),
        ]

        for cpu, mem_mb, expected_cpu, expected_mem in test_cases:
            cgroups_dir = str(tmp_path / f"test_{cpu}_{mem_mb}")
            json_path = write_cgroups_json(cgroups_dir, cpu=cpu, mem_mb=mem_mb, name="job")

            with open(json_path) as f:
                data = json.load(f)

            assert data["cpu"]["cpu.max"] == expected_cpu
            assert data["memory"]["memory.max"] == expected_mem


class TestApplyCgroupsLimits:
    """Test applying cgroups limits to commands."""

    def test_apply_cgroups_to_apptainer_exec(self, tmp_path):
        """Test applying cgroups to apptainer exec command."""
        command = ["apptainer", "exec", "container.sif", "bet", "input.nii.gz"]
        run_dir = str(tmp_path)

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="test123",
                run_dir=run_dir,
            )

        # Check that --apply-cgroups was inserted after exec
        assert modified[0] == "apptainer"
        assert modified[1] == "exec"
        assert modified[2] == "--apply-cgroups"
        assert modified[3].endswith("test123.json")
        assert modified[4:] == ["container.sif", "bet", "input.nii.gz"]

        # Check that JSON file was created
        json_path = Path(modified[3])
        assert json_path.exists()

    def test_apply_cgroups_to_apptainer_run(self, tmp_path):
        """Test applying cgroups to apptainer run command."""
        command = ["apptainer", "run", "container.sif"]
        run_dir = str(tmp_path)

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=4,
                mem_mb=4096,
                execution_id="test456",
                run_dir=run_dir,
            )

        assert modified[0] == "apptainer"
        assert modified[1] == "run"
        assert modified[2] == "--apply-cgroups"
        assert modified[3].endswith("test456.json")
        assert modified[4] == "container.sif"

    def test_apply_cgroups_disabled(self, tmp_path):
        """Test that cgroups are not applied when disabled."""
        command = ["apptainer", "exec", "container.sif", "bet"]
        run_dir = str(tmp_path)

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "false"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="test",
                run_dir=run_dir,
            )

        # Command should be unchanged
        assert modified == command

    def test_apply_cgroups_no_env_var(self, tmp_path):
        """Test that cgroups are not applied when env var not set."""
        command = ["apptainer", "exec", "container.sif", "bet"]
        run_dir = str(tmp_path)

        # Ensure env var is not set
        env_backup = os.environ.pop("BR_RESOURCE_CGROUPS_ENABLED", None)
        try:
            modified = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="test",
                run_dir=run_dir,
            )
            assert modified == command
        finally:
            if env_backup is not None:
                os.environ["BR_RESOURCE_CGROUPS_ENABLED"] = env_backup

    def test_apply_cgroups_non_apptainer_command(self, tmp_path):
        """Test that cgroups are not applied to non-apptainer commands."""
        command = ["docker", "run", "image", "command"]
        run_dir = str(tmp_path)

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="test",
                run_dir=run_dir,
            )

        # Command should be unchanged
        assert modified == command

    def test_apply_cgroups_missing_exec_or_run(self, tmp_path):
        """Test handling of apptainer command without exec/run."""
        command = ["apptainer", "inspect", "container.sif"]
        run_dir = str(tmp_path)

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="test",
                run_dir=run_dir,
            )

        # Command should be unchanged (warning logged)
        assert modified == command

    def test_apply_cgroups_empty_command(self, tmp_path):
        """Test handling of empty command."""
        command = []
        run_dir = str(tmp_path)

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="test",
                run_dir=run_dir,
            )

        assert modified == []

    def test_apply_cgroups_with_existing_flags(self, tmp_path):
        """Test applying cgroups to command with existing flags."""
        command = [
            "apptainer",
            "exec",
            "--bind",
            "/data:/data",
            "--no-home",
            "container.sif",
            "bet",
        ]
        run_dir = str(tmp_path)

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="test",
                run_dir=run_dir,
            )

        # --apply-cgroups should be inserted after exec
        assert modified[0] == "apptainer"
        assert modified[1] == "exec"
        assert modified[2] == "--apply-cgroups"
        assert modified[3].endswith(".json")
        # Existing flags should follow
        assert modified[4:] == [
            "--bind",
            "/data:/data",
            "--no-home",
            "container.sif",
            "bet",
        ]


class TestCleanupCgroupsFiles:
    """Test cgroups file cleanup."""

    def test_cleanup_cgroups_files(self, tmp_path):
        """Test cleaning up cgroups JSON files."""
        # Create some cgroups files
        cgroups_dir = tmp_path / "cgroups"
        cgroups_dir.mkdir()
        (cgroups_dir / "job1.json").write_text("{}")
        (cgroups_dir / "job2.json").write_text("{}")
        (cgroups_dir / "other.txt").write_text("not json")

        cleanup_cgroups_files(str(tmp_path))

        # JSON files should be deleted, but not other files initially
        # Actually, looking at the implementation, it removes all *.json files
        # and then tries to rmdir the directory
        assert not (cgroups_dir / "job1.json").exists()
        assert not (cgroups_dir / "job2.json").exists()

    def test_cleanup_no_cgroups_dir(self, tmp_path):
        """Test cleanup when cgroups directory doesn't exist."""
        # Should not raise an error
        cleanup_cgroups_files(str(tmp_path / "nonexistent"))

    def test_cleanup_empty_cgroups_dir(self, tmp_path):
        """Test cleanup of empty cgroups directory."""
        cgroups_dir = tmp_path / "cgroups"
        cgroups_dir.mkdir()

        cleanup_cgroups_files(str(tmp_path))

        # Directory should be removed
        assert not cgroups_dir.exists()


class TestCgroupsIntegration:
    """Integration tests for cgroups functionality."""

    def test_write_and_apply_workflow(self, tmp_path):
        """Test the complete workflow of writing and applying cgroups."""
        command = ["apptainer", "exec", "container.sif", "fsl", "bet"]
        run_dir = str(tmp_path)
        execution_id = "integration_test"

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            modified = apply_cgroups_limits(
                command=command,
                cpu=4,
                mem_mb=8192,
                execution_id=execution_id,
                run_dir=run_dir,
            )

        # Verify command modification
        assert "--apply-cgroups" in modified

        # Extract cgroups file path
        cgroups_idx = modified.index("--apply-cgroups")
        cgroups_file = modified[cgroups_idx + 1]

        # Verify file exists and has correct content
        assert Path(cgroups_file).exists()
        with open(cgroups_file) as f:
            data = json.load(f)

        assert data["cpu"]["cpu.max"] == "400000 100000"  # 4 cores
        assert data["memory"]["memory.max"] == str(8192 * 1024 * 1024)  # 8 GB

        # Test cleanup
        cleanup_cgroups_files(run_dir)
        assert not Path(cgroups_file).exists()

    def test_multiple_jobs_same_run_dir(self, tmp_path):
        """Test multiple jobs using the same run directory."""
        run_dir = str(tmp_path)
        command = ["apptainer", "exec", "container.sif", "tool"]

        with patch.dict(os.environ, {"BR_RESOURCE_CGROUPS_ENABLED": "true"}):
            # Create cgroups for multiple jobs
            modified1 = apply_cgroups_limits(
                command=command,
                cpu=2,
                mem_mb=2048,
                execution_id="job1",
                run_dir=run_dir,
            )
            modified2 = apply_cgroups_limits(
                command=command,
                cpu=4,
                mem_mb=4096,
                execution_id="job2",
                run_dir=run_dir,
            )

        # Extract file paths
        cgroups_file1 = modified1[modified1.index("--apply-cgroups") + 1]
        cgroups_file2 = modified2[modified2.index("--apply-cgroups") + 1]

        # Both files should exist
        assert Path(cgroups_file1).exists()
        assert Path(cgroups_file2).exists()

        # Files should be different
        assert cgroups_file1 != cgroups_file2

        # Verify different content
        with open(cgroups_file1) as f:
            data1 = json.load(f)
        with open(cgroups_file2) as f:
            data2 = json.load(f)

        assert data1["cpu"]["cpu.max"] == "200000 100000"
        assert data2["cpu"]["cpu.max"] == "400000 100000"
